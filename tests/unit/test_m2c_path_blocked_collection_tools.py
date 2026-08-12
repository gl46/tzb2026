from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from m2c.package_path_blocked_collection import (
    canonical_sha256,
    package_collection,
    project_frozen_manifests,
)
from m2c.derive_model_owned_chain_probe import derive_probe_bytes
from m2c.run_path_blocked_collection_worker import (
    prepare_job,
    stage_is_valid,
    validate_frozen_scene_semantics,
)


ROOT = Path(__file__).parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
CHAIN = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)


def _write_physical_probe_fixture(
    tmp_path: Path,
    *,
    role: str,
) -> tuple[Path, Path, Path, dict, str]:
    """Write synthetic unit evidence matching the physical probe contract.

    This fixture exercises host validation and packaging only.  Its explicit
    ``unit_fixture`` measurements and local temporary path prevent it from
    being confused with an Isaac integration artifact.
    """

    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    field = "training_keys" if role == "TRAIN" else "physical_prerequisite_smoke_keys"
    record = training[field][0]
    evidence_root = tmp_path / "raw"
    evidence_root.mkdir(parents=True)
    blocker = "track-public-blocker"
    target = "track-public-task-target"
    other = "track-public-other"
    tracks = [
        {
            "track_id": target,
            "category": "industrial_cylinder:yellow",
            "confidence": 0.99,
            "pose_xyzquat": [0.2, 0.1, 0.5, 1.0, 0.0, 0.0, 0.0],
        },
        {
            "track_id": other,
            "category": "industrial_cylinder:green",
            "confidence": 0.98,
            "pose_xyzquat": [0.1, 0.2, 0.5, 1.0, 0.0, 0.0, 0.0],
        },
        {
            "track_id": blocker,
            "category": "industrial_cylinder:red",
            "confidence": 0.97,
            "pose_xyzquat": [0.1, 0.1, 0.5, 1.0, 0.0, 0.0, 0.0],
        },
    ]
    canonical_slots = [blocker, other, target, None, None, None, None, None]
    captures: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []
    previous_completed_at_ns = 100
    for index, skill in enumerate(CHAIN):
        captured_at_ns = previous_completed_at_ns + 10
        started_at_ns = captured_at_ns + 10
        completed_at_ns = started_at_ns + 10
        rgb_uri = f"dataset://m2b_public_rgbd/rgb/step-{index:02d}.png"
        depth_uri = f"dataset://m2b_public_rgbd/depth/step-{index:02d}.npy"
        rgb_path = evidence_root / rgb_uri.removeprefix("dataset://")
        depth_path = evidence_root / depth_uri.removeprefix("dataset://")
        rgb_path.parent.mkdir(parents=True, exist_ok=True)
        depth_path.parent.mkdir(parents=True, exist_ok=True)
        rgb_path.write_bytes(f"unit-rgb-{role}-{index}".encode())
        depth_path.write_bytes(f"unit-depth-{role}-{index}".encode())
        capture = {
            "label": f"m2c-step-{index:02d}-{skill.lower()}",
            "timestamp_ns": captured_at_ns,
            "rgb_uri": rgb_uri,
            "depth_uri": depth_uri,
            "rgb_sha256": hashlib.sha256(rgb_path.read_bytes()).hexdigest(),
            "depth_sha256": hashlib.sha256(depth_path.read_bytes()).hexdigest(),
            "source": "PUBLIC_RGBD",
        }
        captures.append(capture)
        observation = {
            "schema_version": "PathBlockedPublicObservationV2",
            "observation_id": f"{record['matched_key']}-observation-{index}",
            "captured_at_ns": captured_at_ns,
            "source": "PUBLIC_RGBD",
            "fresh": True,
            "rgb_uri": rgb_uri,
            "depth_uri": depth_uri,
            "rgb_sha256": capture["rgb_sha256"],
            "depth_sha256": capture["depth_sha256"],
            "capture_receipt_sha256": canonical_sha256(capture),
            "perception_tracks": tracks,
            "canonical_slots": canonical_slots,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        receipt_core = {
            "schema_version": "PathBlockedPhysicalSkillReceiptV2",
            "receipt_id": f"{record['matched_key']}-receipt-{index}",
            "receipt_uri": (
                f"dataset://m2c_path_blocked/physical/{record['matched_key']}/step-{index:02d}.json"
            ),
            "execution_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
            "executed_skill": skill,
            "physically_executed": True,
            "started_at_ns": started_at_ns,
            "completed_at_ns": completed_at_ns,
            "action_protocol": {
                "schema_version": "PhysicalActionProtocolV2",
                "coordinate_frame": ("policy_rgbd_optical" if skill == "REOBSERVE" else "world"),
                "units": ("none" if skill in {"REOBSERVE", "REASSOCIATE_TARGET"} else "m_rad"),
                "dimensions": 0 if skill in {"REOBSERVE", "REASSOCIATE_TARGET"} else 3,
                "frequency_hz": 60.0,
                "normalization": "none",
            },
            "execution_measurements": {
                "unit_fixture": True,
                "decision_index": index,
                "capture_receipt_sha256": observation["capture_receipt_sha256"],
            },
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
        }
        receipt = {**receipt_core, "receipt_sha256": canonical_sha256(receipt_core)}
        step: dict[str, object] = {
            "schema_version": "PathBlockedPhysicalStepEvidenceV2",
            "decision_index": index,
            "observation": observation,
            "public_blocker_track_id": blocker if index <= 4 else None,
            "public_task_target_track_id": target if index >= 6 else None,
            "destination_cell_label": record["destination_cell"] if index in {2, 3} else None,
            "physical_receipts": [receipt],
            "label_source": "PUBLIC_RGBD_PHYSICAL_SUPERVISION",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        steps.append(step)
        previous_completed_at_ns = completed_at_ns

    derived_probe = tmp_path / "derived-path-blocked-probe.py"
    derived_probe.write_bytes(derive_probe_bytes(UPSTREAM.read_bytes()))
    probe_source_sha256 = hashlib.sha256(derived_probe.read_bytes()).hexdigest()
    payload = {
        "status": "PASS",
        "not_policy_rollout": True,
        "actuation_probe_source_sha256": probe_source_sha256,
        "m2b_public_rgbd": {
            "schema_version": "M2BPublicRGBDEvidenceV2",
            "captures": captures,
            "simulator_truth_policy_input": False,
        },
        "m2c_path_blocked_physical_chain": {
            "schema_version": "M2CPathBlockedProbeChainV2",
            "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
            "episode_id": f"unit-fixture-{record['matched_key']}",
            "failure_type": "PATH_BLOCKED",
            "scene_seed": record["scene_seed"],
            "failure_seed": record["failure_seed"],
            "split": record["split"],
            "split_group": f"scene-{record['scene_seed']}",
            "matched_key": record["matched_key"],
            "collection_role": role,
            "collection_key": f"{record['matched_key']}-collection",
            "sdf_sha256": record["sdf_sha256"],
            "supervision_sha256": record["supervision_sha256"],
            "failure_observed_at_ns": 100,
            "final_task_success": True,
            "steps": steps,
            "model_rollout": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        },
    }
    probe_path = evidence_root / "actuation-probe.json"
    probe_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return evidence_root, probe_path, derived_probe, record, probe_source_sha256


def _source_root(tmp_path: Path, *, role: str = "SMOKE") -> tuple[Path, dict]:
    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    record = training["training_keys" if role == "TRAIN" else "physical_prerequisite_smoke_keys"][0]
    source = tmp_path / "source"
    source.mkdir(parents=True)
    from m2c.s4_scene_family import materialize_scene

    template = (ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf").read_text()
    materialized = materialize_scene(
        template,
        int(record["scene_seed"]),
        tuple(record["anchor_xy_m"]),
    )
    assert materialized is not None
    sdf, supervision, _receipt = materialized
    (source / f"scene-{record['scene_seed']}.sdf").write_bytes(sdf)
    (source / f"scene-{record['scene_seed']}.supervision.json").write_bytes(supervision)
    shutil.copy(
        ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf",
        source / "panda_controlled.urdf",
    )
    return source, record


def _worker_args(tmp_path: Path, *, role: str = "SMOKE") -> argparse.Namespace:
    source, record = _source_root(tmp_path, role=role)
    return argparse.Namespace(
        project_root=ROOT,
        source_root=source,
        sdf=source / f"scene-{record['scene_seed']}.sdf",
        supervision=source / f"scene-{record['scene_seed']}.supervision.json",
        urdf=source / "panda_controlled.urdf",
        upstream_v4_probe=UPSTREAM,
        output_root=tmp_path / "jobs",
        packaged_output_root=tmp_path / "bundles",
        role=role,
        matched_key=record["matched_key"],
        gpu=0,
        image="nvcr.io/nvidia/isaac-sim:6.0.1",
        container_prefix="m2c-test",
        stage_timeout_s=1.0,
        probe_timeout_s=1.0,
        dry_run=True,
        training_keys=ROOT / "configs/m2c_s4_training_keys.json",
        s6_keys=ROOT / "configs/m2c_s6_evaluation_keys.json",
        runtime_registry=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
    )


def test_worker_dry_run_is_exact_single_key_scripted_public_chain(tmp_path: Path) -> None:
    args = _worker_args(tmp_path)
    receipt, stage, probe = prepare_job(args)

    assert receipt["status"] == "DRY_RUN_NOT_EXECUTED"
    assert receipt["decision_source"] == "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    assert receipt["model_owned"] is False
    assert receipt["formal_q_b_evaluation"] is False
    assert receipt["teacher_used"] is False
    assert receipt["privileged_truth_policy_input"] is False
    assert "--m2c-chain-role" in probe
    assert probe[probe.index("--m2c-chain-role") + 1] == "SMOKE"
    assert "--m2c-split" in probe
    assert probe[probe.index("--m2c-split") + 1] == "val"
    assert probe[probe.index("--m2c-matched-key") + 1] == args.matched_key
    assert probe[probe.index("--m2c-decision-source") + 1] == (
        "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    )
    assert "--m2b-capture-public-rgbd" in probe
    assert "--m2c-scripted-safe-place-bin-cell" in probe
    assert "--qrm-checkpoint" not in probe
    assert "--qrm-checkpoint" not in stage
    assert stage[stage.index("--gpus") + 1] == "device=0"
    assert stage[stage.index("--physical-gpu-index") + 1] == "0"
    derived = Path(receipt["derived_probe"])
    assert derived.is_file()
    derived_source = derived.read_text(encoding="utf-8")
    assert 'm2b_wrong_regrasp.get("follow_error_m", float("inf"))' not in derived_source
    assert 'np.isfinite(float(m2b_wrong_regrasp["follow_error_m"]))' in derived_source
    assert "from xh_agent.policy.qrm_lite.m2c_hard_freeze import" in derived_source
    assert "require_pre_freeze(" in derived_source
    assert derived_source.index("require_pre_freeze(") < derived_source.index(
        "from isaacsim import SimulationApp"
    )
    assert hashlib.sha256(derived.read_bytes()).hexdigest() == receipt["derived_probe_sha256"]
    job = json.loads((derived.parent / "collection-job-v2.json").read_text())
    assert job["training_executed"] is False
    assert job["evaluation_executed"] is False

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        prepare_job(args)


def test_worker_maps_selected_host_gpu_to_container_cuda_zero(tmp_path: Path) -> None:
    args = _worker_args(tmp_path)
    args.gpu = 1
    _receipt, stage, probe = prepare_job(args)

    assert stage[stage.index("--gpus") + 1] == "device=1"
    assert probe[probe.index("--gpus") + 1] == "device=1"
    assert stage[stage.index("--physical-gpu-index") + 1] == "0"


def test_worker_rejects_role_key_or_frozen_source_hash_mismatch(tmp_path: Path) -> None:
    args = _worker_args(tmp_path)
    training = json.loads(args.training_keys.read_text())
    args.matched_key = training["training_keys"][0]["matched_key"]
    with pytest.raises(ValueError, match="not exactly once"):
        prepare_job(args)

    args = _worker_args(tmp_path / "tamper")
    args.sdf.write_text(args.sdf.read_text() + "<!-- tampered -->\n")
    with pytest.raises(ValueError, match="SDF SHA-256"):
        prepare_job(args)

    args = _worker_args(tmp_path / "urdf-tamper")
    args.urdf.write_text(args.urdf.read_text() + "<!-- tampered -->\n")
    with pytest.raises(ValueError, match="URDF name or SHA-256"):
        prepare_job(args)


def test_stage_gate_binds_sdf_supervision_urdf_and_clean_stage(tmp_path: Path) -> None:
    source, _record = _source_root(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    clean = stage / "m1b_physics_scene.usdc"
    clean.write_bytes(b"unit clean stage")
    metrics = {
        "status": "PASS",
        "source_hashes": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                next(source.glob("*.sdf")),
                next(source.glob("*.supervision.json")),
                source / "panda_controlled.urdf",
            )
        },
        "clean_physics_stage": {
            "sha256": hashlib.sha256(clean.read_bytes()).hexdigest(),
        },
    }
    (stage / "metrics.json").write_text(json.dumps(metrics))
    sdf = next(source.glob("*.sdf"))
    supervision = next(source.glob("*.supervision.json"))
    urdf = source / "panda_controlled.urdf"

    assert stage_is_valid(stage, sdf=sdf, supervision=supervision, urdf=urdf)
    metrics["source_hashes"][urdf.name] = "0" * 64
    (stage / "metrics.json").write_text(json.dumps(metrics))
    assert not stage_is_valid(stage, sdf=sdf, supervision=supervision, urdf=urdf)


def test_scene_semantics_bind_evaluator_roles_to_frozen_public_selectors(
    tmp_path: Path,
) -> None:
    source, record = _source_root(tmp_path)
    supervision_path = next(source.glob("*.supervision.json"))
    supervision = json.loads(supervision_path.read_text())
    validate_frozen_scene_semantics(supervision, record)

    supervision["m2c_headroom_domain"]["target_entity_evaluator_only"] = "cylinder_01"
    with pytest.raises(ValueError, match="scene roles, public selectors, or destination"):
        validate_frozen_scene_semantics(supervision, record)


def test_projected_manifests_fail_closed_on_embedded_hash_and_s6_overlap(
    tmp_path: Path,
) -> None:
    training = tmp_path / "training.json"
    s6 = tmp_path / "s6.json"
    shutil.copy(ROOT / "configs/m2c_s4_training_keys.json", training)
    shutil.copy(ROOT / "configs/m2c_s6_evaluation_keys.json", s6)
    payload = json.loads(training.read_text())
    payload["teacher_used"] = True
    training.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="embedded manifest_sha256 mismatch"):
        project_frozen_manifests(
            training,
            s6,
            ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        )

    shutil.copy(ROOT / "configs/m2c_s4_training_keys.json", training)
    training_payload = json.loads(training.read_text())
    s6_payload = json.loads(s6.read_text())
    training_payload["training_keys"][0] = dict(s6_payload["evaluation_keys"][0])
    training_payload["training_keys"][0]["role"] = "TRAIN"
    training_payload.pop("manifest_sha256", None)
    training_payload["manifest_sha256"] = canonical_sha256(training_payload)
    training.write_text(json.dumps(training_payload, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ValueError):
        project_frozen_manifests(
            training,
            s6,
            ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        )


def test_packager_never_overwrites_existing_bundle_before_parsing_probe(
    tmp_path: Path,
) -> None:
    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    key = training["physical_prerequisite_smoke_keys"][0]
    output = tmp_path / "bundles"
    destination = output / "smoke" / key["matched_key"]
    destination.mkdir(parents=True)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    raw = raw_root / "actuation-probe.json"
    raw.write_text("{}")
    derived = tmp_path / "derived.py"
    derived.write_text("untrusted but overwrite gate runs first")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        package_collection(
            raw_probe_path=raw,
            evidence_root=raw_root,
            output_root=output,
            role="SMOKE",
            matched_key=key["matched_key"],
            training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
            derived_probe_path=derived,
            upstream_v4_probe_path=UPSTREAM,
        )


@pytest.mark.parametrize(
    ("role", "training_eligible"),
    [("TRAIN", True), ("SMOKE", False)],
)
def test_packager_accepts_exact_eight_step_chain_and_publishes_resolvable_bundle(
    tmp_path: Path,
    role: str,
    training_eligible: bool,
) -> None:
    (
        evidence_root,
        raw_probe,
        derived_probe,
        record,
        probe_source_sha256,
    ) = _write_physical_probe_fixture(tmp_path, role=role)
    output_root = tmp_path / "bundles"

    result = package_collection(
        raw_probe_path=raw_probe,
        evidence_root=evidence_root,
        output_root=output_root,
        role=role,
        matched_key=record["matched_key"],
        training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
        s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
        runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        derived_probe_path=derived_probe,
        upstream_v4_probe_path=UPSTREAM,
    )

    bundle = Path(result["output"])
    receipt = json.loads((bundle / "collection-receipt-v2.json").read_text())
    dataset = json.loads((bundle / "supervised-steps-v2.json").read_text())
    packaged = json.loads((bundle / "packaged-physical-chain-v2.json").read_text())
    assert receipt["status"] == "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    assert receipt["decision_source"] == "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    assert receipt["model_owned"] is False
    assert receipt["model_rollout"] is False
    assert receipt["formal_q_b_evaluation"] is False
    assert receipt["pure_model_success_evidence"] is False
    assert receipt["physical_chain_steps"] == 8
    assert receipt["physical_receipts"] == 8
    assert receipt["fresh_public_rgbd_observations"] == 8
    assert receipt["executing_probe_source_sha256"] == probe_source_sha256
    assert receipt["derived_probe_file_sha256"] == probe_source_sha256
    assert receipt["teacher_used"] is False
    assert receipt["privileged_truth_policy_input"] is False
    assert dataset["episodes_physical_valid"] == 1
    assert dataset["episodes_training_eligible"] == int(training_eligible)
    assert dataset["samples_training_eligible"] == (8 if training_eligible else 0)
    assert len(dataset["samples"]) == 8
    assert [sample["model_label"]["skill_type"] for sample in dataset["samples"]] == list(CHAIN)
    assert all(
        sample["model_training_eligible"] is training_eligible for sample in dataset["samples"]
    )
    assert all(
        sample["teacher_used"] is False and sample["privileged_truth_policy_input"] is False
        for sample in dataset["samples"]
    )
    assert len(packaged["steps"]) == 8
    assert len({step["observation"]["capture_receipt_sha256"] for step in packaged["steps"]}) == 8
    assert len({step["physical_receipts"][0]["receipt_sha256"] for step in packaged["steps"]}) == 8
    for step in packaged["steps"]:
        for uri in (
            step["observation"]["rgb_uri"],
            step["observation"]["depth_uri"],
            step["physical_receipts"][0]["receipt_uri"],
        ):
            assert uri.startswith("dataset://")
            assert (bundle / uri.removeprefix("dataset://")).is_file()
        physical_receipt = step["physical_receipts"][0]
        assert physical_receipt["execution_source"] == ("SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION")
        assert physical_receipt["execution_measurements"]

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        package_collection(
            raw_probe_path=raw_probe,
            evidence_root=evidence_root,
            output_root=output_root,
            role=role,
            matched_key=record["matched_key"],
            training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
            derived_probe_path=derived_probe,
            upstream_v4_probe_path=UPSTREAM,
        )
