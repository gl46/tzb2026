from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from m2c.build_s4_v4_training_manifest import build_manifest
from m2c.derive_model_owned_chain_probe import derive_probe_bytes_v4
from m2c.package_path_blocked_collection import package_collection
from m2c import run_path_blocked_collection_worker as worker
from m2c.run_path_blocked_collection_worker import parse_args
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2CS4V4TrainingKeyManifestV1,
    host_replay_probe_chain_v4,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_v4_manifest_and_cli_defaults_are_strict() -> None:
    built = build_manifest()
    assert len(built["training_keys"]) == 36
    assert built["accepted_implementation_commit"] == ("abc08e63de85263f781b458ac50b3644f806ec6c")
    assert built["selection_uses_rollout_outcomes"] is False
    identities = {
        (item["scene_seed"], item["failure_seed"], item["matched_key"])
        for item in built["training_keys"]
    }
    assert len(identities) == 36
    args = parse_args(
        [
            "--project-root",
            str(ROOT),
            "--source-root",
            "/tmp/source",
            "--sdf",
            "/tmp/scene.sdf",
            "--supervision",
            "/tmp/scene.json",
            "--urdf",
            "/tmp/robot.urdf",
            "--upstream-v4-probe",
            "/tmp/probe.py",
            "--output-root",
            "/tmp/raw",
            "--packaged-output-root",
            "/tmp/packaged",
            "--role",
            "TRAIN",
            "--matched-key",
            "key",
        ]
    )
    assert args.revision == "V4"
    assert args.training_keys.name == "m2c_s4_v4_training_keys.json"


def test_v4_derived_probe_is_raw_only_and_compiles() -> None:
    derived = derive_probe_bytes_v4(UPSTREAM.read_bytes())
    source = derived.decode()
    compile(source, "derived-v4.py", "exec")
    assert '"m2c_v4_raw_association_captures"' in source
    assert '"schema_version": "M2CPathBlockedRawProbeChainV4"' in source
    assert "build_public_track_candidates_v3" not in source
    assert "M2C_V4_RAW_ASSOCIATION_CAPTURES = []" in source
    assert "bind_consumed_claim_to_raw_session" in source
    assert "authorize_probe_start" not in source
    assert "probe-entry-broker" not in source
    assert "probe-entry-token" not in source


def test_v4_worker_has_no_launcher_or_broker_precondition() -> None:
    source = (ROOT / "scripts/m2c/run_path_blocked_collection_worker.py").read_text()
    v4_gate = source[source.index("def _run_cli_preimport_guard") : source.index("from m2c.")]
    assert 'revision in {"V2", "V4"}' in v4_gate
    run_body = source[source.index("def run(") : source.index("def parse_args(")]
    assert 'if revision == "V3":' in run_body
    assert "v4_auth.issue_probe_start_capability" not in run_body
    assert "v4_auth.start_probe_entry_broker" not in run_body
    assert "v4_auth.consume_probe_launch" not in run_body
    assert "v4_auth.terminalize_probe_launch" not in run_body


def test_v4_output_mount_uses_frozen_image_uid_and_is_resealed(tmp_path: Path) -> None:
    output = tmp_path / "container-output"
    worker._prepare_v4_container_output_directory(
        output,
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    payload = output / "payload.json"
    payload.write_text("{}\n")
    nested = output / "nested"
    nested.mkdir()
    (nested / "receipt.json").write_text("{}\n")

    worker._seal_v4_container_output_directory(output)

    assert stat.S_IMODE(output.stat().st_mode) == 0o500
    assert stat.S_IMODE(nested.stat().st_mode) == 0o500
    assert stat.S_IMODE(payload.stat().st_mode) == 0o400
    assert stat.S_IMODE((nested / "receipt.json").stat().st_mode) == 0o400
    assert worker.V4_ISAAC_RUNTIME_USER == "isaac-sim"
    assert (worker.V4_ISAAC_RUNTIME_UID, worker.V4_ISAAC_RUNTIME_GID) == (1234, 1234)


def test_v4_runtime_user_is_read_from_exact_image(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "isaac-sim\n"

    def run_stub(command: list[str], **_kwargs: object) -> Completed:
        calls.append(command)
        return Completed()

    monkeypatch.setattr(worker.subprocess, "run", run_stub)
    worker._require_v4_image_runtime_user(image_reference="sha256:" + "1" * 64)
    assert calls == [
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Config.User}}",
            "sha256:" + "1" * 64,
        ]
    ]

    Completed.stdout = "root\n"
    with pytest.raises(worker.CollectionAuthorizationError, match="runtime user"):
        worker._require_v4_image_runtime_user(image_reference="sha256:" + "1" * 64)


def test_v4_claim_projection_is_byte_exact_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical-claim.json"
    canonical.write_text('{"schema_version":"test"}\n')
    monkeypatch.setattr(
        v4_auth.M2CS4V4CollectionConsumptionReceiptV1,
        "model_validate_json",
        lambda _raw: object(),
    )
    projection = worker._project_v4_claim_for_container(
        canonical_claim=canonical,
        job_root=tmp_path,
        owner_uid=os.geteuid(),
        owner_gid=os.getegid(),
    )
    assert projection.read_bytes() == canonical.read_bytes()
    assert stat.S_IMODE(projection.stat().st_mode) == 0o400
    assert stat.S_IMODE(projection.parent.stat().st_mode) == 0o500


def test_v4_authorization_surface_ends_at_claim_bound_raw_verification() -> None:
    source = Path(v4_auth.__file__).read_text()
    assert "def verify_claim_bound_raw_session(" in source
    for forbidden in (
        "class M2CS4V4ProbeStartCapabilityV1",
        "class M2CS4V4ProbeLaunchConsumptionReceiptV1",
        "def issue_probe_start_capability(",
        "def consume_probe_launch(",
        "def start_probe_entry_broker(",
        "def terminalize_probe_launch(",
        "def authorize_probe_start(",
        "def verify_packaging_authorization(",
        "import socket",
        "import threading",
        "LAUNCH_CONSUMPTION_DIRECTORY",
        "PROBE_ENTRY_DIRECTORY",
        "CANONICAL_PROBE_ENTRY_BROKER_ROOT",
    ):
        assert forbidden not in source


def test_v4_create_only_claim_rejects_duplicate(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest()
    key = manifest.training_keys[0]
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)

    @dataclass(frozen=True)
    class Prereg:
        batch_id: str
        ledger_namespace: str
        ledger_root: str
        candidate_contract_revision: str
        checkpoint_architecture_revision: str
        container_image: str
        container_image_id: str
        repository_relative_path: str
        prereg_sha256: str
        committed_source_snapshot: v4_auth.CommittedSourceSnapshotV1
        selected_keys: list[v4_auth.SelectedV4TrainKeyV1]

    @dataclass(frozen=True)
    class Resolved:
        prereg: Prereg
        manifest: M2CS4V4TrainingKeyManifestV1
        file_sha256: str
        introduced_commit: str

    selected = v4_auth.SelectedV4TrainKeyV1(
        scene_seed=key.scene_seed,
        failure_seed=key.failure_seed,
        matched_key=key.matched_key,
        sdf_sha256=key.sdf_sha256,
        supervision_sha256=key.supervision_sha256,
    )
    resolved = Resolved(
        prereg=Prereg(
            batch_id="m2c-s4-v4-train-batch-04",
            ledger_namespace="M2C_S4_V4_COLLECTION_BATCH04",
            ledger_root=str(ledger),
            candidate_contract_revision="PublicTrackCandidateV4",
            checkpoint_architecture_revision="M2C_Q012_V4",
            container_image="nvcr.io/nvidia/isaac-sim:6.0.1",
            container_image_id=(
                "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
            ),
            repository_relative_path="docs/decisions/batch04.json",
            prereg_sha256="1" * 64,
            committed_source_snapshot=v4_auth.CommittedSourceSnapshotV1(
                commit="2" * 40,
                tree="3" * 40,
                file_count=1,
                total_bytes=1,
                inventory_sha256="4" * 64,
            ),
            selected_keys=[selected],
        ),
        manifest=manifest,
        file_sha256="5" * 64,
        introduced_commit="6" * 40,
    )
    monkeypatch.setattr(v4_auth, "selected_key_ordinal", lambda *_args, **_kwargs: (0, selected))
    common = {
        "resolved": resolved,
        "matched_key": key.matched_key,
        "now_ns": 1,
        "challenge_nonce": "7" * 64,
        "source_urdf_sha256": "8" * 64,
        "upstream_v4_probe_sha256": (
            "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
        ),
        "derived_probe_sha256": "9" * 64,
        "container_image_id": (
            "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
        ),
    }
    claim = v4_auth.consume_collection_key(**common)  # type: ignore[arg-type]
    assert claim.name == "claim-00000000.json"
    with pytest.raises(v4_auth.CollectionAuthorizationError, match="already consumed"):
        v4_auth.consume_collection_key(**common)  # type: ignore[arg-type]


def test_direct_programmatic_v4_packaging_is_not_authorized() -> None:
    with pytest.raises(ValueError, match="committed preregistration and consumed key claim"):
        package_collection(
            raw_probe_path=Path("missing-raw.json"),
            evidence_root=Path("missing-evidence"),
            output_root=Path("missing-output"),
            role="TRAIN",
            matched_key="unclaimed",
            training_keys_path=Path("missing-training.json"),
            s6_keys_path=Path("missing-s6.json"),
            runtime_registry_path=Path("missing-runtime.json"),
            derived_probe_path=Path("missing-derived.py"),
            upstream_v4_probe_path=Path("missing-upstream.py"),
            revision="V4",
            collection_prereg_path=None,
            collection_claim_path=None,
        )


def _manifest() -> M2CS4V4TrainingKeyManifestV1:
    payload = build_manifest()
    import xh_agent.policy.qrm_lite.path_blocked_collection_v4 as collection

    collection.V4_MANIFEST_CONTENT_SHA256 = str(payload["manifest_sha256"])
    return M2CS4V4TrainingKeyManifestV1.model_validate(payload)


def _raw_bundle() -> tuple[dict[str, object], list[dict[str, object]]]:
    captures: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    previous_timestamp = 0
    for index in range(8):
        timestamp = 100 + index * 100
        samples = [
            {
                "schema_version": "PublicRobotProprioceptionV2",
                "timestamp_ns": timestamp if index == 0 else previous_timestamp,
                "world_frame": "world",
                "end_effector_position_world_m": [0.0, 0.0, 0.8],
                "end_effector_orientation_world_xyzw": [0.0, 0.0, 0.0, 1.0],
                "gripper_width_m": 0.04,
                "gripper_closed": False,
            }
        ]
        if index:
            samples.append(
                {
                    **samples[0],
                    "timestamp_ns": timestamp,
                }
            )
        detections = []
        for offset, color in ((0.0, "red"), (0.3, "yellow")):
            detections.append(
                {
                    "schema_version": "PublicRGBDDetectionV2",
                    "timestamp_ns": timestamp,
                    "frame_id": "m2b_policy_rgbd_optical",
                    "category": "industrial_cylinder",
                    "attributes": {"visual_color": color},
                    "position_3d": [offset, 0.0, 0.5],
                    "confidence": 0.9,
                    "bbox_or_mask": {"x": 1, "y": 2, "width": 3, "height": 4},
                    "visibility": 1.0,
                    "covariance_or_quality": {},
                }
            )
        capture: dict[str, object] = {
            "schema_version": "M2CV4RawPublicAssociationCaptureV1",
            "timestamp_ns": timestamp,
            "camera_frame": "m2b_policy_rgbd_optical",
            "world_frame": "world",
            "position_units": "m",
            "camera_to_world_row_major": [
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ],
            "detections": detections,
            "proprioception_interval": samples,
            "last_physically_executed_public_skill": (
                {
                    "schema_version": "LastPhysicallyExecutedPublicSkillV2",
                    "skill_name": [
                        "GRASP",
                        "LIFT",
                        "MOVE",
                        "PLACE",
                        "RELEASE",
                        "REOBSERVE",
                        "REASSOCIATE_TARGET",
                    ][index - 1],
                    "started_at_ns": previous_timestamp + 1,
                    "completed_at_ns": timestamp - 1,
                }
                if index
                else None
            ),
            "rgb_uri": f"dataset://rgb/{index}.png",
            "depth_uri": f"dataset://depth/{index}.npy",
            "rgb_sha256": f"{index + 1:064x}",
            "depth_sha256": f"{index + 101:064x}",
        }
        captures.append(capture)
        receipt_core = {
            "schema_version": "PathBlockedPhysicalSkillReceiptV2",
            "receipt_id": f"receipt-{index}",
            "receipt_uri": f"dataset://physical/{index}.json",
            "executed_skill": [
                "GRASP",
                "LIFT",
                "MOVE",
                "PLACE",
                "RELEASE",
                "REOBSERVE",
                "REASSOCIATE_TARGET",
                "REGRASP",
            ][index],
            "execution_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
            "physically_executed": True,
            "started_at_ns": timestamp + 1,
            "completed_at_ns": timestamp + 99,
            "schema_gate": "PASS",
            "stale_track_gate": "PASS",
            "frame_unit_gate": "PASS",
            "ik_gate": "PASS",
            "collision_gate": "PASS",
            "controller_gate": "PASS",
            "safety_gate": "PASS",
            "collision_or_safety_violation": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "action_protocol": {
                "schema_version": "PhysicalActionProtocolV2",
                "coordinate_frame": "world",
                "units": "m",
                "dimensions": 3,
                "frequency_hz": 60,
                "normalization": "none",
            },
            "execution_measurements": {"test": True},
        }
        receipt_core["receipt_sha256"] = canonical(receipt_core)
        observation = {
            "schema_version": "PathBlockedRawPublicObservationV4",
            "observation_id": f"observation-{index}",
            "captured_at_ns": timestamp,
            "source": "PUBLIC_RGBD",
            "fresh": True,
            "rgb_uri": capture["rgb_uri"],
            "depth_uri": capture["depth_uri"],
            "rgb_sha256": capture["rgb_sha256"],
            "depth_sha256": capture["depth_sha256"],
            "capture_receipt_sha256": canonical(capture),
            "association_capture_index": index,
            "declared_target_attribute": "yellow",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "task_target_track_id_used_for_candidates": False,
        }
        steps.append(
            {
                "schema_version": "PathBlockedRawPhysicalStepEvidenceV4",
                "decision_index": index,
                "observation": observation,
                "scripted_public_selector_color": (
                    "red" if index <= 4 else "yellow" if index >= 6 else None
                ),
                "destination_cell_label": "BIN_CELL_3" if index in {2, 3} else None,
                "physical_receipts": [receipt_core],
                "label_source": "PUBLIC_RGBD_PHYSICAL_SUPERVISION",
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        )
        previous_timestamp = timestamp
    chain = {
        "schema_version": "M2CPathBlockedRawProbeChainV4",
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "episode_id": "episode",
        "failure_type": "PATH_BLOCKED",
        "scene_seed": 1,
        "failure_seed": 2,
        "split": "train",
        "split_group": "scene-1",
        "matched_key": "key",
        "collection_role": "TRAIN",
        "collection_key": "key-collection",
        "declared_target_attribute": "yellow",
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "collection_authorization_sha256": "a" * 64,
        "sdf_sha256": "b" * 64,
        "supervision_sha256": "c" * 64,
        "failure_observed_at_ns": 1,
        "final_task_success": True,
        "steps": steps,
        "model_rollout": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return chain, captures


def test_v4_host_replay_happy_and_history_tamper() -> None:
    manifest = _manifest()
    key = manifest.training_keys[0]
    chain, captures = _raw_bundle()
    chain.update(
        scene_seed=key.scene_seed,
        failure_seed=key.failure_seed,
        matched_key=key.matched_key,
        collection_key=f"{key.matched_key}-collection",
        sdf_sha256=key.sdf_sha256,
        supervision_sha256=key.supervision_sha256,
    )
    replayed = host_replay_probe_chain_v4(
        chain,
        captures,
        training_key=key,
        training_manifest=manifest,
        capture_source_implementation_sha256="d" * 64,
    )
    assert len(replayed.steps) == 8
    assert [len(item.observation.association_history) for item in replayed.steps] == list(
        range(1, 9)
    )
    assert replayed.steps[0].public_blocker_track_id
    assert replayed.steps[6].public_task_target_track_id

    tampered = copy.deepcopy(captures)
    tampered[3]["camera_to_world_row_major"][3] = 0.01
    with pytest.raises(ValueError, match="capture receipt differs"):
        host_replay_probe_chain_v4(
            chain,
            tampered,
            training_key=key,
            training_manifest=manifest,
            capture_source_implementation_sha256="d" * 64,
        )

    bad_chain = copy.deepcopy(chain)
    bad_chain["steps"][2]["observation"]["association_capture_index"] = 1
    with pytest.raises(ValueError, match="ordered capture history"):
        host_replay_probe_chain_v4(
            bad_chain,
            captures,
            training_key=key,
            training_manifest=manifest,
            capture_source_implementation_sha256="d" * 64,
        )


class _PackagedAuthorization:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {"schema_version": "TestV4PackagedAuthorization"}


def test_v4_packager_happy_path_and_asset_tamper(tmp_path: Path, monkeypatch) -> None:
    manifest = _manifest()
    key = manifest.training_keys[0]
    chain, captures = _raw_bundle()
    chain.update(
        scene_seed=key.scene_seed,
        failure_seed=key.failure_seed,
        matched_key=key.matched_key,
        collection_key=f"{key.matched_key}-collection",
        sdf_sha256=key.sdf_sha256,
        supervision_sha256=key.supervision_sha256,
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "console.log").write_text("test\n")
    for index, capture in enumerate(captures):
        for kind, suffix in (("rgb", ".png"), ("depth", ".npy")):
            path = evidence / kind / f"{index}{suffix}"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(f"{kind}-{index}".encode())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            capture[f"{kind}_sha256"] = digest
            chain["steps"][index]["observation"][f"{kind}_sha256"] = digest
        chain["steps"][index]["observation"]["capture_receipt_sha256"] = canonical(capture)
    derived = tmp_path / "derived.py"
    derived.write_bytes(derive_probe_bytes_v4(UPSTREAM.read_bytes()))
    authorization: dict[str, object] = {}
    chain["collection_authorization_sha256"] = canonical(authorization)
    raw = {
        "status": "PASS",
        "not_policy_rollout": True,
        "actuation_probe_source_sha256": hashlib.sha256(derived.read_bytes()).hexdigest(),
        "m2c_v4_collection_authorization": authorization,
        "m2c_v4_raw_association_captures": captures,
        "m2c_path_blocked_physical_chain": chain,
    }
    raw_path = evidence / "actuation-probe.json"
    raw_path.write_text(json.dumps(raw))
    monkeypatch.setattr(
        "m2c.package_path_blocked_collection.v4_auth.verify_claim_bound_raw_session",
        lambda **_kwargs: (object(), object(), _PackagedAuthorization()),
    )
    common = {
        "raw_probe_path": raw_path,
        "evidence_root": evidence,
        "role": "TRAIN",
        "matched_key": key.matched_key,
        "training_keys_path": ROOT / "configs/m2c_s4_v4_training_keys.json",
        "s6_keys_path": ROOT / "configs/m2c_s6_evaluation_keys.json",
        "runtime_registry_path": ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        "derived_probe_path": derived,
        "upstream_v4_probe_path": UPSTREAM,
        "revision": "V4",
        "collection_prereg_path": tmp_path / "prereg.json",
        "collection_claim_path": tmp_path / "claim.json",
    }
    result = package_collection(output_root=tmp_path / "packaged", **common)
    assert result["status"] == "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    assert result["candidate_contract_revision"] == "PublicTrackCandidateV4"
    assert result["physical_chain_steps"] == 8

    (evidence / "rgb/3.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="asset SHA-256 mismatch"):
        package_collection(output_root=tmp_path / "tampered-output", **common)
