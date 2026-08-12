from __future__ import annotations

import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite.coarse_policy import DEFAULT_SKILLS
from xh_agent.policy.qrm_lite.models_q012 import RECOVERY_SKILLS
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
    M2C_Q012_V2_SKILL_LABELS,
    POINTER_CLASS_LABELS,
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
    ProbePackagingError,
    build_path_blocked_supervised_dataset,
    build_path_blocked_supervised_steps,
    canonical_manifest_sha256,
    package_probe_payload,
    raw_evidence_json_schema,
    supervised_step_json_schema,
    validate_path_blocked_physical_evidence,
)


REGISTRY_SHA = "a" * 64
BLOCKER = "track-public-blocker"
TARGET = "track-public-task-target"
OTHER = "track-public-other"
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


def _collection_key(
    *,
    collection_key: str = "m2c-qb-train-10001-77",
    role: str = "TRAIN",
    matched_key: str = "m2c-qb-train-match-10001-77",
    scene_seed: int = 10001,
    failure_seed: int = 77,
    split: str = "train",
) -> dict[str, object]:
    return {
        "collection_key": collection_key,
        "collection_role": role,
        "matched_key": matched_key,
        "scene_seed": scene_seed,
        "failure_seed": failure_seed,
        "split": split,
        "split_group": f"scene-{scene_seed}",
    }


def _collection_manifest(
    keys: list[dict[str, object]] | None = None,
) -> FrozenPathBlockedCollectionManifestV2:
    return FrozenPathBlockedCollectionManifestV2(
        manifest_key="m2c-qb-collection-manifest-v1",
        runtime_registry_sha256=REGISTRY_SHA,
        skill_labels=list(dict.fromkeys([*DEFAULT_SKILLS, *RECOVERY_SKILLS])),
        pointer_class_labels=[f"SLOT_{index}" for index in range(8)] + ["NONE"],
        destination_class_labels=[f"BIN_CELL_{index}" for index in range(6)] + ["NONE"],
        keys=keys or [_collection_key()],
    )


def _s6_manifest(
    keys: list[dict[str, object]] | None = None,
) -> FrozenS6ExclusionManifestV2:
    return FrozenS6ExclusionManifestV2(
        manifest_key="m2c-s6-frozen-keys-v1",
        keys=keys
        or [
            {
                "matched_key": "m2c-s6-match-20001-88",
                "scene_seed": 20001,
                "failure_seed": 88,
            }
        ],
    )


def _track(track_id: str, color: str) -> dict[str, object]:
    return {
        "track_id": track_id,
        "category": f"industrial_cylinder:{color}",
        "confidence": 0.99,
        "pose_xyzquat": [0.1, 0.2, 0.5, 1.0, 0.0, 0.0, 0.0],
    }


def _evidence(
    *,
    collection: FrozenPathBlockedCollectionManifestV2 | None = None,
    s6: FrozenS6ExclusionManifestV2 | None = None,
    collection_key: dict[str, object] | None = None,
) -> dict[str, object]:
    collection = collection or _collection_manifest()
    s6 = s6 or _s6_manifest()
    key = collection_key or _collection_key()
    steps: list[dict[str, object]] = []
    previous_completed = 100
    tracks = [_track(TARGET, "yellow"), _track(OTHER, "green"), _track(BLOCKER, "red")]
    canonical_slots: list[str | None] = [BLOCKER, OTHER, TARGET, None, None, None, None, None]
    for index, skill in enumerate(CHAIN):
        captured_at = previous_completed + 10
        started_at = captured_at + 10
        completed_at = started_at + 10
        destination = "BIN_CELL_3" if index in {2, 3} else None
        steps.append(
            {
                "decision_index": index,
                "observation": {
                    "observation_id": f"observation-{index}",
                    "captured_at_ns": captured_at,
                    "source": "PUBLIC_RGBD",
                    "fresh": True,
                    "rgb_uri": f"dataset://episode/rgb/{index}.png",
                    "depth_uri": f"dataset://episode/depth/{index}.npy",
                    "rgb_sha256": f"{100 + index:064x}",
                    "depth_sha256": f"{200 + index:064x}",
                    "capture_receipt_sha256": f"{300 + index:064x}",
                    "perception_tracks": tracks,
                    "canonical_slots": canonical_slots,
                },
                "public_blocker_track_id": BLOCKER,
                "public_task_target_track_id": TARGET,
                "destination_cell_label": destination,
                "physical_receipts": [
                    {
                        "receipt_id": f"receipt-{index}",
                        "receipt_uri": f"evidence://episode/receipt/{index}.json",
                        "receipt_sha256": f"{400 + index:064x}",
                        "executed_skill": skill,
                        "physically_executed": True,
                        "started_at_ns": started_at,
                        "completed_at_ns": completed_at,
                        "execution_measurements": {
                            "fixture_physical_success": True,
                            "decision_index": index,
                        },
                        "action_protocol": {
                            "coordinate_frame": (
                                "policy_rgbd_optical" if skill == "REOBSERVE" else "world"
                            ),
                            "units": "none"
                            if skill in {"REOBSERVE", "REASSOCIATE_TARGET"}
                            else "m_rad",
                            "dimensions": 0 if skill in {"REOBSERVE", "REASSOCIATE_TARGET"} else 3,
                            "frequency_hz": 60.0,
                            "normalization": "none",
                        },
                        "schema_gate": "PASS",
                        "stale_track_gate": "PASS",
                        "frame_unit_gate": "PASS",
                        "ik_gate": "PASS",
                        "collision_gate": "PASS",
                        "controller_gate": "PASS",
                        "safety_gate": "PASS",
                    }
                ],
            }
        )
        previous_completed = completed_at
    return {
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "episode_id": f"episode-{key['scene_seed']}-{key['failure_seed']}",
        "scene_seed": key["scene_seed"],
        "failure_seed": key["failure_seed"],
        "split": key["split"],
        "split_group": key["split_group"],
        "matched_key": key["matched_key"],
        "collection_role": key["collection_role"],
        "collection_key": key["collection_key"],
        "collection_manifest_ref": {
            "manifest_key": collection.manifest_key,
            "manifest_sha256": canonical_manifest_sha256(collection),
        },
        "s6_exclusion_manifest_ref": {
            "manifest_key": s6.manifest_key,
            "manifest_sha256": canonical_manifest_sha256(s6),
        },
        "runtime_registry_sha256": REGISTRY_SHA,
        "sdf_sha256": "b" * 64,
        "supervision_sha256": "c" * 64,
        "source_evidence_uri": "evidence://episode/physical-chain.json",
        "source_evidence_sha256": f"{int(key['scene_seed']):064x}",
        "failure_observed_at_ns": 100,
        "final_task_success": True,
        "steps": steps,
    }


def _write_packaging_fixture(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
    dict[str, Path],
]:
    runtime = tmp_path / "qrm_runtime_mapping_v2.yaml"
    runtime.write_text("frozen: runtime\n", encoding="utf-8")
    runtime_sha = __import__("hashlib").sha256(runtime.read_bytes()).hexdigest()
    collection = _collection_manifest()
    collection.runtime_registry_sha256 = runtime_sha
    s6 = _s6_manifest()
    collection_path = tmp_path / "collection.json"
    s6_path = tmp_path / "s6.json"
    collection_path.write_text(collection.model_dump_json(indent=2), encoding="utf-8")
    s6_path.write_text(s6.model_dump_json(indent=2), encoding="utf-8")

    evidence = _evidence(collection=collection, s6=s6)
    for step in evidence["steps"]:  # type: ignore[index]
        observation = step["observation"]
        for kind in ("rgb", "depth"):
            uri = observation[f"{kind}_uri"]
            asset = tmp_path / str(uri).removeprefix("dataset://")
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(f"{kind}-{step['decision_index']}".encode())
            observation[f"{kind}_sha256"] = (
                __import__("hashlib").sha256(asset.read_bytes()).hexdigest()
            )
        capture_core = {
            key: observation[key]
            for key in (
                "observation_id",
                "captured_at_ns",
                "source",
                "rgb_uri",
                "depth_uri",
                "rgb_sha256",
                "depth_sha256",
                "perception_tracks",
                "canonical_slots",
            )
        }
        observation["capture_receipt_sha256"] = (
            __import__("hashlib")
            .sha256(
                json.dumps(
                    capture_core,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            .hexdigest()
        )
        receipt = step["physical_receipts"][0]
        receipt_core = {
            "schema_version": "PathBlockedPhysicalSkillReceiptV2",
            **receipt,
            "execution_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
            "collision_or_safety_violation": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        receipt_core["action_protocol"] = {
            "schema_version": "PhysicalActionProtocolV2",
            **receipt_core["action_protocol"],
        }
        receipt.clear()
        receipt.update(receipt_core)
        receipt["receipt_sha256"] = (
            __import__("hashlib")
            .sha256(
                json.dumps(
                    {key: value for key, value in receipt.items() if key != "receipt_sha256"},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            .hexdigest()
        )

    raw_chain = {
        key: value
        for key, value in evidence.items()
        if key
        not in {
            "collection_manifest_ref",
            "s6_exclusion_manifest_ref",
            "runtime_registry_sha256",
            "source_evidence_uri",
            "source_evidence_sha256",
        }
    }
    raw_chain["schema_version"] = "M2CPathBlockedProbeChainV2"
    payload: dict[str, object] = {"m2c_path_blocked_physical_chain": raw_chain}
    probe_path = tmp_path / "actuation-probe.json"
    probe_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return (
        payload,
        collection,
        s6,
        {
            "runtime": runtime,
            "collection": collection_path,
            "s6": s6_path,
            "probe": probe_path,
        },
    )


def test_contract_label_orders_and_json_schemas_are_explicit() -> None:
    assert M2C_Q012_V2_SKILL_LABELS == tuple(dict.fromkeys([*DEFAULT_SKILLS, *RECOVERY_SKILLS]))
    assert POINTER_CLASS_LABELS == tuple([f"SLOT_{i}" for i in range(8)] + ["NONE"])
    assert DESTINATION_CLASS_LABELS == tuple([f"BIN_CELL_{i}" for i in range(6)] + ["NONE"])
    raw_schema = raw_evidence_json_schema()
    sample_schema = supervised_step_json_schema()
    assert raw_schema["title"] == "M2CPathBlockedPhysicalChainEvidenceV2"
    assert sample_schema["title"] == "M2CPathBlockedSupervisedStepV2"
    assert "entity_id" not in str(raw_schema)
    assert "prim_path" not in str(raw_schema)
    assert "checkpoint_path" not in str(raw_schema)
    assert "model_label" not in str(raw_schema)
    assert "pointer_class_index" not in str(raw_schema)
    assert "destination_class_index" not in str(raw_schema)


def test_host_wrapper_binds_files_and_recomputes_all_probe_hashes(tmp_path: Path) -> None:
    payload, collection, s6, paths = _write_packaging_fixture(tmp_path)

    packaged = package_probe_payload(
        payload,
        probe_evidence_path=paths["probe"],
        evidence_root=tmp_path,
        source_evidence_uri="evidence://isaac/actuation-probe.json",
        collection_manifest=collection,
        collection_manifest_path=paths["collection"],
        s6_manifest=s6,
        s6_manifest_path=paths["s6"],
        runtime_registry_path=paths["runtime"],
        expected_sdf_sha256="b" * 64,
        expected_supervision_sha256="c" * 64,
    )

    assert packaged.collection_manifest_ref.manifest_sha256 == canonical_manifest_sha256(collection)
    assert packaged.s6_exclusion_manifest_ref.manifest_sha256 == canonical_manifest_sha256(s6)
    assert (
        packaged.runtime_registry_sha256
        == __import__("hashlib").sha256(paths["runtime"].read_bytes()).hexdigest()
    )
    assert (
        packaged.source_evidence_sha256
        == __import__("hashlib").sha256(paths["probe"].read_bytes()).hexdigest()
    )
    assert len(packaged.steps) == 8
    assert all(
        "public_blocker_track_id" not in step.observation.model_dump()
        and "public_task_target_track_id" not in step.observation.model_dump()
        for step in packaged.steps
    )


@pytest.mark.parametrize("tamper", ["rgb", "capture", "receipt", "identity"])
def test_host_wrapper_rejects_tampered_probe_bindings(tmp_path: Path, tamper: str) -> None:
    payload, collection, s6, paths = _write_packaging_fixture(tmp_path)
    chain = payload["m2c_path_blocked_physical_chain"]
    if tamper == "rgb":
        rgb = tmp_path / str(chain["steps"][0]["observation"]["rgb_uri"]).removeprefix(  # type: ignore[index]
            "dataset://"
        )
        rgb.write_bytes(b"tampered")
    elif tamper == "capture":
        chain["steps"][0]["observation"]["capture_receipt_sha256"] = "f" * 64  # type: ignore[index]
    elif tamper == "receipt":
        chain["steps"][0]["physical_receipts"][0]["receipt_sha256"] = "f" * 64  # type: ignore[index]
    else:
        chain["scene_seed"] = 999999  # type: ignore[index]
    paths["probe"].write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ProbePackagingError):
        package_probe_payload(
            payload,
            probe_evidence_path=paths["probe"],
            evidence_root=tmp_path,
            source_evidence_uri="evidence://isaac/actuation-probe.json",
            collection_manifest=collection,
            collection_manifest_path=paths["collection"],
            s6_manifest=s6,
            s6_manifest_path=paths["s6"],
            runtime_registry_path=paths["runtime"],
            expected_sdf_sha256="b" * 64,
            expected_supervision_sha256="c" * 64,
        )


def test_host_wrapper_rejects_in_memory_payload_not_read_from_file(tmp_path: Path) -> None:
    payload, collection, s6, paths = _write_packaging_fixture(tmp_path)
    payload["m2c_path_blocked_physical_chain"]["episode_id"] = "changed-after-read"  # type: ignore[index]

    with pytest.raises(ProbePackagingError, match="differs from probe evidence file"):
        package_probe_payload(
            payload,
            probe_evidence_path=paths["probe"],
            evidence_root=tmp_path,
            source_evidence_uri="evidence://isaac/actuation-probe.json",
            collection_manifest=collection,
            collection_manifest_path=paths["collection"],
            s6_manifest=s6,
            s6_manifest_path=paths["s6"],
            runtime_registry_path=paths["runtime"],
            expected_sdf_sha256="b" * 64,
            expected_supervision_sha256="c" * 64,
        )


def test_probe_cannot_self_assert_model_label_or_class_index(tmp_path: Path) -> None:
    payload, collection, s6, paths = _write_packaging_fixture(tmp_path)
    payload["m2c_path_blocked_physical_chain"]["steps"][0]["pointer_class_index"] = 0  # type: ignore[index]
    paths["probe"].write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(ProbePackagingError, match="may not self-assert training labels"):
        package_probe_payload(
            payload,
            probe_evidence_path=paths["probe"],
            evidence_root=tmp_path,
            source_evidence_uri="evidence://isaac/actuation-probe.json",
            collection_manifest=collection,
            collection_manifest_path=paths["collection"],
            s6_manifest=s6,
            s6_manifest_path=paths["s6"],
            runtime_registry_path=paths["runtime"],
            expected_sdf_sha256="b" * 64,
            expected_supervision_sha256="c" * 64,
        )


def test_host_wrapper_checks_frozen_scene_artifact_hashes(tmp_path: Path) -> None:
    payload, collection, s6, paths = _write_packaging_fixture(tmp_path)

    with pytest.raises(ProbePackagingError, match="SDF SHA-256"):
        package_probe_payload(
            payload,
            probe_evidence_path=paths["probe"],
            evidence_root=tmp_path,
            source_evidence_uri="evidence://isaac/actuation-probe.json",
            collection_manifest=collection,
            collection_manifest_path=paths["collection"],
            s6_manifest=s6,
            s6_manifest_path=paths["s6"],
            runtime_registry_path=paths["runtime"],
            expected_sdf_sha256="d" * 64,
            expected_supervision_sha256="c" * 64,
        )


def test_green_train_chain_builds_exactly_eight_supervised_steps() -> None:
    collection = _collection_manifest()
    s6 = _s6_manifest()
    result = build_path_blocked_supervised_steps(
        _evidence(collection=collection, s6=s6),
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.validation.status == "PASS_TRAIN"
    assert result.validation.physical_evidence_valid is True
    assert result.validation.model_training_eligible is True
    assert result.validation.exclusion_reasons == []
    assert len(result.samples) == 8
    assert [sample.model_label.skill_type for sample in result.samples] == list(CHAIN)
    assert [sample.pointer_class_index for sample in result.samples] == [0, 0, 0, 0, 0, 8, 2, 2]
    assert [sample.destination_class_index for sample in result.samples] == [6, 6, 3, 3, 6, 6, 6, 6]
    assert all(sample.model_training_eligible for sample in result.samples)
    assert all(sample.teacher_used is False for sample in result.samples)
    assert all(sample.privileged_truth_policy_input is False for sample in result.samples)
    assert all(sample.physical_receipt_sha256 for sample in result.samples)
    assert "public_blocker_track_id" not in type(result.samples[0].observation).model_fields
    assert all(
        "public_task_target_track_id" not in type(sample.observation).model_fields
        for sample in result.samples
    )


def test_smoke_chain_is_physically_valid_but_never_training_eligible() -> None:
    key = _collection_key(role="SMOKE", split="test")
    collection = _collection_manifest([key])
    s6 = _s6_manifest()
    result = build_path_blocked_supervised_steps(
        _evidence(collection=collection, s6=s6, collection_key=key),
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.validation.status == "PASS_SMOKE"
    assert result.validation.physical_evidence_valid is True
    assert result.validation.model_training_eligible is False
    assert result.validation.exclusion_reasons == ["COLLECTION_ROLE_SMOKE_NOT_TRAINING"]
    assert len(result.samples) == 8
    assert all(not sample.model_training_eligible for sample in result.samples)
    assert all(sample.exclusion_reasons for sample in result.samples)


def test_old_raw_v1_index_cannot_be_promoted_to_training_labels() -> None:
    old_raw = {
        "schema_version": "M2CPathBlockedRawEvidenceV1",
        "scene_seed": 9077,
        "failure_type": "PATH_BLOCKED",
        "evidence_path": "/remote/actuation-probe.json",
        "evidence_sha256": "d" * 64,
        "model_training_eligible": False,
    }
    collection = _collection_manifest()
    s6 = _s6_manifest()

    result = build_path_blocked_supervised_steps(
        old_raw,
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.validation.status == "INVALID_SCHEMA"
    assert result.validation.model_training_eligible is False
    assert result.samples == []
    assert any(
        reason.startswith("RAW_EVIDENCE_SCHEMA_INVALID")
        for reason in result.validation.exclusion_reasons
    )


def test_v4_and_s6_keys_are_strictly_excluded() -> None:
    s6_key = {
        "matched_key": "m2c-s6-match-overlap",
        "scene_seed": 10002,
        "failure_seed": 78,
    }
    s6 = _s6_manifest([s6_key])
    collection_key = _collection_key(
        collection_key="s6-overlap",
        matched_key="m2c-s6-match-overlap",
        scene_seed=10002,
        failure_seed=78,
    )
    collection = _collection_manifest([collection_key])
    s6_result = build_path_blocked_supervised_steps(
        _evidence(collection=collection, s6=s6, collection_key=collection_key),
        collection_manifest=collection,
        s6_manifest=s6,
    )
    assert s6_result.samples == []
    assert "S6_MATCHED_KEY_EXCLUDED" in s6_result.validation.exclusion_reasons
    assert "S6_SCENE_GROUP_EXCLUDED" in s6_result.validation.exclusion_reasons

    v4_key = _collection_key(
        collection_key="v4-overlap",
        matched_key="m2c-qb-train-v4-overlap",
        scene_seed=9077,
        failure_seed=79,
    )
    v4_collection = _collection_manifest([v4_key])
    v4_result = build_path_blocked_supervised_steps(
        _evidence(collection=v4_collection, s6=_s6_manifest(), collection_key=v4_key),
        collection_manifest=v4_collection,
        s6_manifest=_s6_manifest(),
    )
    assert v4_result.samples == []
    assert "V4_QA_SCENE_SEED_EXCLUDED" in v4_result.validation.exclusion_reasons


def test_noncanonical_tracks_missing_freshness_or_receipt_fail_closed() -> None:
    collection = _collection_manifest()
    s6 = _s6_manifest()
    evidence = _evidence(collection=collection, s6=s6)
    step = evidence["steps"][2]  # type: ignore[index]
    step["observation"]["fresh"] = False
    step["observation"]["canonical_slots"] = [TARGET, BLOCKER, OTHER, None, None, None, None, None]
    step["physical_receipts"] = []

    result = build_path_blocked_supervised_steps(
        evidence,
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.samples == []
    reasons = result.validation.exclusion_reasons
    assert "STEP_2:PUBLIC_OBSERVATION_NOT_FRESH" in reasons
    assert "STEP_2:NON_CANONICAL_K8_TRACK_SLOTS" in reasons
    assert "STEP_2:PHYSICAL_RECEIPT_COUNT_NOT_ONE" in reasons


def test_pointer_destination_and_move_place_contract_fail_closed() -> None:
    collection = _collection_manifest()
    s6 = _s6_manifest()
    evidence = _evidence(collection=collection, s6=s6)
    evidence["steps"][0]["public_blocker_track_id"] = "track-not-in-k8"  # type: ignore[index]
    evidence["steps"][2]["destination_cell_label"] = "BIN_CELL_2"  # type: ignore[index]
    evidence["steps"][3]["destination_cell_label"] = "BIN_CELL_4"  # type: ignore[index]

    result = build_path_blocked_supervised_steps(
        evidence,
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.samples == []
    assert "STEP_0:PUBLIC_TARGET_OUTSIDE_CANONICAL_K8" in result.validation.exclusion_reasons
    assert "STEP_3:MOVE_PLACE_DESTINATION_DISAGREE" in result.validation.exclusion_reasons


def test_teacher_or_privileged_input_kills_training() -> None:
    collection = _collection_manifest()
    s6 = _s6_manifest()
    evidence = _evidence(collection=collection, s6=s6)
    evidence["steps"][0]["teacher_used"] = True  # type: ignore[index]
    evidence["steps"][1]["observation"]["privileged_truth_policy_input"] = True  # type: ignore[index]

    result = validate_path_blocked_physical_evidence(
        evidence,
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.status == "INVALID_SCHEMA"
    assert result.exclusion_reasons == [
        "RAW_EVIDENCE_SCHEMA_INVALID:steps.0:value_error",
        "RAW_EVIDENCE_SCHEMA_INVALID:steps.1:value_error",
    ]


@pytest.mark.parametrize(
    "measurements",
    (
        {"target": "/World/M1B/cylinder_01/link"},
        {"target": "cylinder_01"},
        {"entity_name": "red"},
        {"follow_error_m": float("inf")},
        {},
    ),
)
def test_execution_measurements_reject_oracle_identity_and_nonfinite_values(
    measurements: dict[str, object],
) -> None:
    collection = _collection_manifest()
    s6 = _s6_manifest()
    evidence = _evidence(collection=collection, s6=s6)
    evidence["steps"][0]["physical_receipts"][0]["execution_measurements"] = measurements  # type: ignore[index]

    result = validate_path_blocked_physical_evidence(
        evidence,
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.status == "INVALID_SCHEMA"
    assert len(result.exclusion_reasons) == 1
    assert result.exclusion_reasons[0].startswith(
        "RAW_EVIDENCE_SCHEMA_INVALID:steps.0.physical_receipts.0"
    )


def test_manifest_hash_and_frozen_collection_key_are_mandatory() -> None:
    collection = _collection_manifest()
    s6 = _s6_manifest()
    evidence = _evidence(collection=collection, s6=s6)
    evidence["collection_manifest_ref"]["manifest_sha256"] = "f" * 64  # type: ignore[index]
    evidence["collection_key"] = "not-frozen"

    result = build_path_blocked_supervised_steps(
        evidence,
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert result.samples == []
    assert "COLLECTION_MANIFEST_SHA256_MISMATCH" in result.validation.exclusion_reasons
    assert (
        "COLLECTION_KEY_NOT_EXACTLY_ONCE_IN_FROZEN_MANIFEST" in result.validation.exclusion_reasons
    )


def test_batch_dataset_hash_is_deterministic_and_checkpoint_is_absent() -> None:
    first_key = _collection_key()
    second_key = _collection_key(
        collection_key="m2c-qb-train-10003-79",
        matched_key="m2c-qb-train-match-10003-79",
        scene_seed=10003,
        failure_seed=79,
        split="val",
    )
    collection = _collection_manifest([first_key, second_key])
    s6 = _s6_manifest()
    first = _evidence(collection=collection, s6=s6, collection_key=first_key)
    second = _evidence(collection=collection, s6=s6, collection_key=second_key)

    forward = build_path_blocked_supervised_dataset(
        [first, second],
        collection_manifest=collection,
        s6_manifest=s6,
    )
    reverse = build_path_blocked_supervised_dataset(
        [second, first],
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert forward.status == "PASS"
    assert forward.dataset_sha256 == reverse.dataset_sha256
    assert forward.episodes_training_eligible == 2
    assert forward.samples_training_eligible == 16
    assert forward.checkpoint_path is None
    assert forward.checkpoint_sha256 is None


def test_batch_reused_evidence_is_disqualified() -> None:
    first_key = _collection_key()
    second_key = _collection_key(
        collection_key="m2c-qb-train-10003-79",
        matched_key="m2c-qb-train-match-10003-79",
        scene_seed=10003,
        failure_seed=79,
        split="val",
    )
    collection = _collection_manifest([first_key, second_key])
    s6 = _s6_manifest()
    first = _evidence(collection=collection, s6=s6, collection_key=first_key)
    second = _evidence(collection=collection, s6=s6, collection_key=second_key)
    second["source_evidence_sha256"] = first["source_evidence_sha256"]

    dataset = build_path_blocked_supervised_dataset(
        [first, second],
        collection_manifest=collection,
        s6_manifest=s6,
    )

    assert dataset.status == "PARTIAL"
    assert dataset.samples_training_eligible == 0
    assert "SOURCE_EVIDENCE_SHA256_REUSED_ACROSS_EPISODES" in dataset.exclusion_reasons
