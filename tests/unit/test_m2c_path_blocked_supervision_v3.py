from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from m2c.derive_model_owned_chain_probe import derive_probe_bytes_v3
from m2c.materialize_s4_s6_scenes import materialize, records_for_v3_train
from m2c.package_path_blocked_collection import package_collection
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    FrozenS6ExclusionManifestV2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    M2CPathBlockedPhysicalChainEvidenceV3,
    M2CS4V3TrainingKeyManifestV1,
    PathBlockedPublicObservationV3,
    V3_MANIFEST_FILE_SHA256,
    build_path_blocked_supervised_dataset_v3,
    canonical_sha256,
    load_v3_training_manifest,
    package_probe_chain_v3,
    recompute_candidate_payload_v3,
    validate_path_blocked_physical_evidence_v3,
)
from xh_agent.policy.qrm_lite.public_tracks_v3 import (
    build_public_track_candidates_v3,
    canonical_candidate_payload_v3,
    canonical_candidate_sha256_v3,
)


ROOT = Path(__file__).parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
V3_MANIFEST = ROOT / "configs/m2c_s4_v3_training_keys.json"
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


def _s6() -> FrozenS6ExclusionManifestV2:
    frozen = json.loads((ROOT / "configs/m2c_s6_evaluation_keys.json").read_text())
    return FrozenS6ExclusionManifestV2(
        manifest_key="M2C_S6_FROZEN_EVALUATION_KEYS",
        keys=[
            {
                "matched_key": item["matched_key"],
                "scene_seed": item["scene_seed"],
                "failure_seed": item["failure_seed"],
            }
            for item in frozen["evaluation_keys"]
        ],
    )


def _tracks() -> list[dict[str, object]]:
    # More than K=8 manipulable others proves semantic role ranking, rather
    # than literal-ID truncation, keeps the declared yellow target.
    return [
        {
            "track_id": "track-target-z",
            "category": "industrial_cylinder:yellow",
            "confidence": 0.51,
            "pose_xyzquat": [0.2, 0.1, 0.5, 1, 0, 0, 0],
        },
        {
            "track_id": "track-blocker",
            "category": "industrial_cylinder:red",
            "confidence": 0.99,
            "pose_xyzquat": [0.1, 0.1, 0.5, 1, 0, 0, 0],
        },
        *[
            {
                "track_id": f"track-other-{index}",
                "category": "industrial_cylinder:green",
                "confidence": 0.98 - index / 100,
                "pose_xyzquat": [0.1, 0.2, 0.5, 1, 0, 0, 0],
            }
            for index in range(9)
        ],
    ]


def _observation(index: int) -> dict[str, object]:
    tracks = _tracks()
    candidates = build_public_track_candidates_v3(tracks, declared_target_attribute="yellow")
    payload = canonical_candidate_payload_v3(candidates)
    return {
        "schema_version": "PathBlockedPublicObservationV3",
        "observation_id": f"observation-v3-{index}",
        "captured_at_ns": 110 + index * 30,
        "source": "PUBLIC_RGBD",
        "fresh": True,
        "rgb_uri": f"dataset://rgb/{index}.png",
        "depth_uri": f"dataset://depth/{index}.npy",
        "rgb_sha256": f"{1000 + index:064x}",
        "depth_sha256": f"{2000 + index:064x}",
        "capture_receipt_sha256": f"{3000 + index:064x}",
        "perception_tracks": tracks,
        "declared_target_attribute": "yellow",
        "candidate_payload": payload,
        "candidate_payload_sha256": canonical_candidate_sha256_v3(candidates),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "task_target_track_id_used_for_candidates": False,
    }


def _physical_evidence() -> tuple[
    M2CPathBlockedPhysicalChainEvidenceV3,
    M2CS4V3TrainingKeyManifestV1,
    FrozenS6ExclusionManifestV2,
]:
    manifest = load_v3_training_manifest(V3_MANIFEST)
    key = manifest.training_keys[0]
    steps = []
    for index, skill in enumerate(CHAIN):
        observation = _observation(index)
        receipt_core = {
            "schema_version": "PathBlockedPhysicalSkillReceiptV2",
            "receipt_id": f"receipt-v3-{index}",
            "receipt_uri": f"dataset://receipts/{index}.json",
            "execution_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
            "executed_skill": skill,
            "physically_executed": True,
            "started_at_ns": 120 + index * 30,
            "completed_at_ns": 130 + index * 30,
            "action_protocol": {
                "schema_version": "PhysicalActionProtocolV2",
                "coordinate_frame": "world",
                "units": "none" if skill in {"REOBSERVE", "REASSOCIATE_TARGET"} else "m_rad",
                "dimensions": 0 if skill in {"REOBSERVE", "REASSOCIATE_TARGET"} else 3,
                "frequency_hz": 60.0,
                "normalization": "none",
            },
            "execution_measurements": {"unit_fixture": True, "decision_index": index},
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
        steps.append(
            {
                "schema_version": "PathBlockedPhysicalStepEvidenceV3",
                "decision_index": index,
                "observation": observation,
                "public_blocker_track_id": "track-blocker" if index <= 4 else None,
                "public_task_target_track_id": "track-target-z" if index >= 6 else None,
                "destination_cell_label": key.destination_cell if index in {2, 3} else None,
                "physical_receipts": [
                    {**receipt_core, "receipt_sha256": canonical_sha256(receipt_core)}
                ],
                "label_source": "PUBLIC_RGBD_PHYSICAL_SUPERVISION",
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        )
    raw = {
        "schema_version": "M2CPathBlockedProbeChainV3",
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "episode_id": "unit-v3-episode",
        "failure_type": "PATH_BLOCKED",
        "scene_seed": key.scene_seed,
        "failure_seed": key.failure_seed,
        "split": "train",
        "split_group": f"scene-{key.scene_seed}",
        "matched_key": key.matched_key,
        "collection_role": "TRAIN",
        "collection_key": f"{key.matched_key}-collection-v3",
        "declared_target_attribute": "yellow",
        "candidate_contract_revision": "PublicTrackCandidateV3",
        "checkpoint_architecture_revision": "M2C_Q012_V3",
        "sdf_sha256": key.sdf_sha256,
        "supervision_sha256": key.supervision_sha256,
        "failure_observed_at_ns": 100,
        "final_task_success": True,
        "steps": steps,
        "model_rollout": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    s6 = _s6()
    evidence = package_probe_chain_v3(
        raw,
        training_manifest=manifest,
        s6_manifest=s6,
        runtime_registry_sha256="d" * 64,
        source_evidence_uri="dataset://actuation-probe.json",
        source_evidence_sha256="e" * 64,
    )
    return evidence, manifest, s6


def test_v3_derive_is_train_only_and_does_not_reinterpret_v2_slots() -> None:
    source = derive_probe_bytes_v3(UPSTREAM.read_bytes()).decode()
    ast.parse(source)
    assert "public_tracks_v2" not in source
    assert "canonical_slots" not in source
    assert "PathBlockedPublicObservationV3" in source
    assert "M2CPathBlockedProbeChainV3" in source
    assert "m2c-declared-target-attribute" in source
    assert 'choices=("TRAIN",)' in source
    assert "task_target_track_id_used_for_candidates" in source


def test_manifest_is_exact_train_only_and_old_v2_manifest_is_rejected() -> None:
    manifest = load_v3_training_manifest(V3_MANIFEST)
    assert hashlib.sha256(V3_MANIFEST.read_bytes()).hexdigest() == V3_MANIFEST_FILE_SHA256
    assert len(manifest.training_keys) == 36
    assert manifest.physical_prerequisite_smoke_keys == []
    assert all(key.role == "TRAIN" and key.split == "train" for key in manifest.training_keys)
    with pytest.raises(ValueError, match="exact frozen TRAIN manifest"):
        load_v3_training_manifest(ROOT / "configs/m2c_s4_training_keys.json")


def test_host_recomputes_slots_and_rejects_forged_candidate_or_target_identity() -> None:
    evidence, manifest, s6 = _physical_evidence()
    assert (
        evidence.steps[0].observation.candidate_payload.candidates[0].track_id == "track-target-z"
    )
    validation = validate_path_blocked_physical_evidence_v3(
        evidence, training_manifest=manifest, s6_manifest=s6
    )
    assert validation.status == "PASS_TRAIN"
    forged = evidence.model_dump(mode="json")
    forged["steps"][0]["observation"]["candidate_payload"]["candidates"].reverse()
    invalid = validate_path_blocked_physical_evidence_v3(
        forged, training_manifest=manifest, s6_manifest=s6
    )
    assert "STEP_0:V3_CANDIDATES_NOT_HOST_RECOMPUTABLE" in invalid.exclusion_reasons
    poisoned = evidence.steps[0].observation.model_dump(mode="json")
    poisoned["perception_tracks"][0]["task_target_track_id"] = "truth-target"
    with pytest.raises(Exception):
        PathBlockedPublicObservationV3.model_validate(poisoned)


def test_v3_dataset_emits_eight_m2c_q012_v3_rows() -> None:
    evidence, manifest, s6 = _physical_evidence()
    dataset = build_path_blocked_supervised_dataset_v3(
        evidence, training_manifest=manifest, s6_manifest=s6
    )
    assert dataset.status == "PASS"
    assert len(dataset.samples) == 8
    assert all(row.checkpoint_architecture_revision == "M2C_Q012_V3" for row in dataset.samples)
    assert dataset.samples[0].pointer_class_index == 1
    assert dataset.samples[6].pointer_class_index == 0
    assert all(
        not row.teacher_used and not row.privileged_truth_policy_input for row in dataset.samples
    )


def test_v3_first_three_source_assets_materialize_create_only(tmp_path: Path) -> None:
    manifest_payload = json.loads(V3_MANIFEST.read_text())
    records = records_for_v3_train(manifest_payload, limit=3)
    receipt = materialize(records, output_root=tmp_path / "v3-first-three")
    assert receipt["status"] == "MATERIALIZED_OFFLINE_NO_ISAAC_EXECUTION"
    assert len(receipt["records"]) == 3
    assert (tmp_path / "v3-first-three" / "panda_controlled.urdf").is_file()
    with pytest.raises(FileExistsError):
        materialize(records, output_root=tmp_path / "v3-first-three")


def test_v3_schema_rejects_smoke_teacher_truth_and_s6_identity() -> None:
    evidence, manifest, s6 = _physical_evidence()
    for field, value in (
        ("collection_role", "SMOKE"),
        ("teacher_used", True),
        ("privileged_truth_policy_input", True),
    ):
        forged = evidence.model_dump(mode="json")
        forged[field] = value
        invalid = validate_path_blocked_physical_evidence_v3(
            forged, training_manifest=manifest, s6_manifest=s6
        )
        assert invalid.status == "INVALID_SCHEMA"
    s6_key = s6.keys[0]
    forged = evidence.model_copy(
        update={"scene_seed": s6_key.scene_seed, "matched_key": s6_key.matched_key}
    )
    invalid = validate_path_blocked_physical_evidence_v3(
        forged, training_manifest=manifest, s6_manifest=s6
    )
    assert "S6_IDENTITY_EXCLUDED" in invalid.exclusion_reasons


def test_v3_packager_rejects_asset_and_capture_hash_tampering() -> None:
    # Focused source audit: the package implementation must verify both asset
    # bytes and the top-level capture core before publishing any bundle.
    source = (ROOT / "scripts/m2c/package_path_blocked_collection.py").read_text()
    assert "V3 {kind} asset SHA-256 mismatch" in source
    assert "V3 capture receipt SHA-256 mismatch" in source
    assert 'dataset.validation if revision == "V3"' in source

    observation = _observation(0)
    parsed = PathBlockedPublicObservationV3.model_validate(observation)
    payload, digest = recompute_candidate_payload_v3(parsed)
    assert payload == observation["candidate_payload"]
    assert digest == observation["candidate_payload_sha256"]
    tampered = copy.deepcopy(observation)
    tampered["rgb_sha256"] = "f" * 64
    # Candidate reconstruction is intentionally independent of asset hashes;
    # the packaging asset/capture checks are the fail-closed layer.
    payload_after, digest_after = recompute_candidate_payload_v3(
        PathBlockedPublicObservationV3.model_validate(tampered)
    )
    assert (payload_after, digest_after) == (payload, digest)


def _write_v3_package_fixture(tmp_path: Path) -> tuple[dict[str, Path], str]:
    evidence, manifest, _s6_manifest = _physical_evidence()
    raw = evidence.model_dump(mode="json")
    for field in (
        "v3_training_manifest_ref",
        "s6_exclusion_manifest_sha256",
        "runtime_registry_sha256",
        "source_evidence_uri",
        "source_evidence_sha256",
    ):
        raw.pop(field)
    raw["schema_version"] = "M2CPathBlockedProbeChainV3"
    raw["collection_authorization_sha256"] = canonical_sha256({})
    evidence_root = tmp_path / "raw"
    evidence_root.mkdir(parents=True)
    captures: list[dict[str, object]] = []
    for step in raw["steps"]:
        observation = step["observation"]
        for kind in ("rgb", "depth"):
            uri = observation[f"{kind}_uri"]
            asset = evidence_root / uri.removeprefix("dataset://")
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(f"v3-{kind}-{step['decision_index']}".encode())
            observation[f"{kind}_sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest()
        capture = {
            "label": f"v3-unit-{step['decision_index']}",
            "timestamp_ns": observation["captured_at_ns"],
            "rgb_uri": observation["rgb_uri"],
            "depth_uri": observation["depth_uri"],
            "rgb_sha256": observation["rgb_sha256"],
            "depth_sha256": observation["depth_sha256"],
            "source": "PUBLIC_RGBD",
        }
        captures.append(capture)
        observation["capture_receipt_sha256"] = canonical_sha256(capture)
    derived = tmp_path / "derived-v3.py"
    derived.write_bytes(derive_probe_bytes_v3(UPSTREAM.read_bytes()))
    payload = {
        "status": "PASS",
        "not_policy_rollout": True,
        "actuation_probe_source_sha256": hashlib.sha256(derived.read_bytes()).hexdigest(),
        # Unit-only downstream validation tests monkeypatch the authorization
        # verifier. This value deliberately cannot represent real evidence.
        "m2c_v3_collection_authorization": {},
        "m2b_public_rgbd": {
            "schema_version": "M2BPublicRGBDEvidenceV2",
            "captures": captures,
            "simulator_truth_policy_input": False,
        },
        "m2c_path_blocked_physical_chain": raw,
    }
    raw["collection_authorization_sha256"] = canonical_sha256(
        payload["m2c_v3_collection_authorization"]
    )
    probe = evidence_root / "actuation-probe.json"
    probe.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (evidence_root / "console.log").write_text("unit-only authorization fixture\n")
    return {
        "evidence": evidence_root,
        "probe": probe,
        "derived": derived,
        "output": tmp_path / "bundles",
    }, manifest.training_keys[0].matched_key


def _package_v3(
    paths: dict[str, Path],
    matched_key: str,
    *,
    contract_authorization_fixture: bool = False,
) -> dict[str, object]:
    return package_collection(
        raw_probe_path=paths["probe"],
        evidence_root=paths["evidence"],
        output_root=paths["output"],
        role="TRAIN",
        matched_key=matched_key,
        training_keys_path=V3_MANIFEST,
        s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
        runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        derived_probe_path=paths["derived"],
        upstream_v4_probe_path=UPSTREAM,
        revision="V3",
        collection_prereg_path=(
            paths["evidence"] / "fixture-prereg.json" if contract_authorization_fixture else None
        ),
        collection_claim_path=(
            paths["evidence"] / "fixture-claim.json" if contract_authorization_fixture else None
        ),
    )


class _UnitPackagedAuthorization:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {
            "schema_version": "UNIT_ONLY_PACKAGED_AUTHORIZATION",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }


def test_v3_legacy_fixture_cannot_be_published_without_new_authorization(tmp_path: Path) -> None:
    paths, matched_key = _write_v3_package_fixture(tmp_path / "happy")
    with pytest.raises(ValueError, match="committed preregistration"):
        _package_v3(paths, matched_key)
    assert not paths["output"].exists()


def test_v3_downstream_asset_and_capture_tamper_checks_remain_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Production still requires a committed preregistration and exact ledger
    # member. This fixture isolates the downstream package validation layer.
    monkeypatch.setattr(
        "m2c.package_path_blocked_collection.verify_packaging_authorization",
        lambda **_kwargs: (None, None, _UnitPackagedAuthorization()),
    )

    paths, matched_key = _write_v3_package_fixture(tmp_path / "happy")
    result = _package_v3(paths, matched_key, contract_authorization_fixture=True)
    assert result["schema_version"] == "M2CPathBlockedCollectionReceiptV3"
    assert result["candidate_contract_revision"] == "PublicTrackCandidateV3"
    assert result["checkpoint_architecture_revision"] == "M2C_Q012_V3"
    assert (paths["output"] / "train" / matched_key / "supervised-steps-v3.json").is_file()

    paths, matched_key = _write_v3_package_fixture(tmp_path / "rgb-tamper")
    rgb = next((paths["evidence"] / "rgb").glob("*.png"))
    rgb.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="V3 RGB asset SHA-256 mismatch"):
        _package_v3(paths, matched_key, contract_authorization_fixture=True)

    paths, matched_key = _write_v3_package_fixture(tmp_path / "capture-tamper")
    payload = json.loads(paths["probe"].read_text())
    payload["m2b_public_rgbd"]["captures"][0]["label"] = "tampered-core"
    paths["probe"].write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="V3 capture receipt SHA-256 mismatch"):
        _package_v3(paths, matched_key, contract_authorization_fixture=True)
