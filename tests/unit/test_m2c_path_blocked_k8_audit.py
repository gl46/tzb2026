"""Public-only regression tests for the offline PATH_BLOCKED K=8 auditor."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_path_blocked_k8_failure.py"
SPEC = importlib.util.spec_from_file_location("m2c_k8_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _public_frame(count: int) -> tuple[np.ndarray, np.ndarray]:
    """Make disconnected public-red components, ordered left to right."""

    rgb = np.full((24, 104, 3), 128, dtype=np.uint8)
    depth = np.ones((24, 104), dtype=np.float32)
    for index in range(count):
        column = 2 + index * 8
        rgb[4:8, column : column + 4] = (230, 100, 100)
        depth[4:8, column : column + 4] = 0.8
    return rgb, depth


def _attempt(tmp_path: Path, *, count: int) -> tuple[Path, Path]:
    captures = tmp_path / "m2b_public_rgbd"
    (captures / "rgb").mkdir(parents=True)
    (captures / "depth").mkdir()
    capture_items: list[dict[str, object]] = []
    for index, label in enumerate(
        ("before_failure_identity_binding", "m2c_step_06_reassociate_target")
    ):
        rgb, depth = _public_frame(count)
        rgb_path = captures / "rgb" / f"{label}.png"
        depth_path = captures / "depth" / f"{label}.npy"
        Image.fromarray(rgb, mode="RGB").save(rgb_path)
        np.save(depth_path, depth)
        capture_items.append(
            {
                "label": label,
                "timestamp_ns": 100 + index,
                "rgb_uri": f"dataset://m2b_public_rgbd/rgb/{label}.png",
                "depth_uri": f"dataset://m2b_public_rgbd/depth/{label}.npy",
                "rgb_sha256": _sha256(rgb_path),
                "depth_sha256": _sha256(depth_path),
                "source": "PUBLIC_RGBD",
            }
        )
    metrics = {
        "m2b_public_rgbd": {
            "schema_version": "M2BPublicRGBDEvidenceV2",
            "camera_frame": "m2b_policy_rgbd_optical",
            "camera_intrinsics": [80.0, 0.0, 52.0, 0.0, 80.0, 12.0, 0.0, 0.0, 1.0],
            "camera_to_world_optical": [
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
            "depth_semantics": "METRIC_DISTANCE_TO_IMAGE_PLANE",
            "task_spec": {
                "target_selector": "visual_color=red,top_z_band=0.02m,world_x=max",
                "source": "PUBLIC_RGBD_TASK_SPEC",
                "simulator_entity_id_used": False,
            },
            "captures": capture_items,
            "simulator_truth_policy_input": False,
        }
    }
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    return metrics_path, captures


def test_audit_reports_public_target_outside_k8_and_binds_assets(tmp_path: Path) -> None:
    metrics, captures = _attempt(tmp_path, count=12)

    report = AUDIT.audit_attempt(metrics, captures)

    initial = report["initial_public_task_selector"]
    step6 = report["step6_public_reassociation"]
    assert initial["target_rank_by_literal_track_id"] > 8
    assert initial["reason"] == "PUBLIC_TARGET_OUTSIDE_CANONICAL_K8"
    assert step6["target_rank_by_literal_track_id"] > 8
    assert step6["public_track_count"] == 12
    assert step6["reason"] == "PUBLIC_TARGET_OUTSIDE_CANONICAL_K8"
    assert len(report["frames"][0]["canonical_k8_slots"]) == 8
    assert report["frozen_baseline"] == {
        "name": "GeometricRGBDBaseline",
        "maximum_association_distance_m": 0.12,
        "confidence_filter_applied": False,
        "canonical_slot_count": 8,
    }
    assert report["teacher_used"] is False
    assert report["privileged_truth_policy_input"] is False
    assert "semantic" not in json.dumps(report).lower()
    assert report["input_file_sha256"]["frames"][0]["rgb_sha256"] == _sha256(
        captures / "rgb" / "before_failure_identity_binding.png"
    )


def test_audit_reports_k8_membership_when_target_rank_is_at_most_eight(
    tmp_path: Path,
) -> None:
    metrics, captures = _attempt(tmp_path, count=8)

    report = AUDIT.audit_attempt(metrics, captures)

    assert report["initial_public_task_selector"]["target_rank_by_literal_track_id"] <= 8
    assert report["initial_public_task_selector"]["reason"] is None
    assert report["step6_public_reassociation"]["reason"] is None


def test_audit_rejects_missing_or_tampered_public_assets(tmp_path: Path) -> None:
    metrics, captures = _attempt(tmp_path, count=8)
    (captures / "depth" / "m2c_step_06_reassociate_target.npy").unlink()
    with pytest.raises(ValueError, match="depth URI must resolve"):
        AUDIT.audit_attempt(metrics, captures)

    metrics, captures = _attempt(tmp_path / "tampered", count=8)
    rgb = captures / "rgb" / "before_failure_identity_binding.png"
    rgb.write_bytes(rgb.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="RGB SHA-256 mismatch"):
        AUDIT.audit_attempt(metrics, captures)


def test_audit_rejects_semantic_instance_or_privileged_input(tmp_path: Path) -> None:
    metrics, captures = _attempt(tmp_path, count=8)
    payload = json.loads(metrics.read_text())
    payload["m2b_public_rgbd"]["semantic_segmentation_uri"] = "dataset://semantic/mask.png"
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="semantic or instance"):
        AUDIT.audit_attempt(metrics, captures)

    metrics, captures = _attempt(tmp_path / "privileged", count=8)
    payload = json.loads(metrics.read_text())
    payload["m2b_public_rgbd"]["privileged_truth_policy_input"] = True
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must be false"):
        AUDIT.audit_attempt(metrics, captures)

    metrics, captures = _attempt(tmp_path / "stage-supervision", count=8)
    payload = json.loads(metrics.read_text())
    payload["output_counts"] = {"semantic": 1, "instance": 1}
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    report = AUDIT.audit_attempt(metrics, captures)
    assert report["privileged_truth_policy_input"] is False


def test_audit_accepts_diagnostic_partial_record_bound_to_stage_calibration(
    tmp_path: Path,
) -> None:
    metrics, captures = _attempt(tmp_path, count=12)
    payload = json.loads(metrics.read_text())
    public = payload.pop("m2b_public_rgbd")
    payload["policy_camera_calibration"] = {
        "camera_intrinsics": public["camera_intrinsics"],
        "camera_to_world_optical": public["camera_to_world_optical"],
        "depth_semantics": public["depth_semantics"],
    }
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    partial = tmp_path / "partial-public-rgbd.json"
    public.update(
        {
            "schema_version": "M2CPartialPublicRGBDAuditInputV1",
            "evidence_use": "DIAGNOSTIC_ONLY_NOT_TRAINING_OR_EVALUATION",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "probe_console_sha256": "a" * 64,
            "collection_job_sha256": "b" * 64,
            "matched_key": "m2c-s4-fixture-key",
            "scene_seed": 12000,
            "failure_seed": 120007,
            "sdf_sha256": "c" * 64,
            "supervision_sha256": "d" * 64,
        }
    )
    partial.write_text(json.dumps(public), encoding="utf-8")

    report = AUDIT.audit_attempt(
        metrics,
        captures,
        partial_public_rgbd_record=partial,
    )

    assert report["step6_public_reassociation"]["reason"] == ("PUBLIC_TARGET_OUTSIDE_CANONICAL_K8")
    assert report["partial_public_rgbd_record_sha256"] == _sha256(partial)


def test_partial_record_must_match_stage_public_calibration(tmp_path: Path) -> None:
    metrics, captures = _attempt(tmp_path, count=8)
    payload = json.loads(metrics.read_text())
    public = payload.pop("m2b_public_rgbd")
    payload["policy_camera_calibration"] = {
        "camera_intrinsics": public["camera_intrinsics"],
        "camera_to_world_optical": public["camera_to_world_optical"],
        "depth_semantics": public["depth_semantics"],
    }
    metrics.write_text(json.dumps(payload), encoding="utf-8")
    public.update(
        {
            "schema_version": "M2CPartialPublicRGBDAuditInputV1",
            "evidence_use": "DIAGNOSTIC_ONLY_NOT_TRAINING_OR_EVALUATION",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "probe_console_sha256": "a" * 64,
            "collection_job_sha256": "b" * 64,
            "matched_key": "m2c-s4-fixture-key",
            "scene_seed": 12000,
            "failure_seed": 120007,
            "sdf_sha256": "c" * 64,
            "supervision_sha256": "d" * 64,
        }
    )
    public["camera_intrinsics"][0] += 1.0
    partial = tmp_path / "partial-public-rgbd.json"
    partial.write_text(json.dumps(public), encoding="utf-8")

    with pytest.raises(ValueError, match="differs from stage calibration"):
        AUDIT.audit_attempt(
            metrics,
            captures,
            partial_public_rgbd_record=partial,
        )


def test_aggregate_manifest_binding_rejects_duplicate_layout_or_identity(
    tmp_path: Path,
) -> None:
    manifest = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    records = []
    for sdf_sha in dict.fromkeys(item["sdf_sha256"] for item in manifest["training_keys"]):
        records.append(
            next(item for item in manifest["training_keys"] if item["sdf_sha256"] == sdf_sha)
        )
    attempts = [
        {
            "attempt_identity": {
                field: record[field]
                for field in (
                    "matched_key",
                    "scene_seed",
                    "failure_seed",
                    "sdf_sha256",
                    "supervision_sha256",
                )
            }
        }
        for record in records
    ]

    binding = AUDIT._validate_aggregate_against_frozen_training_manifest(
        attempts,
        ROOT / "configs/m2c_s4_training_keys.json",
    )
    assert binding["training_keys_total"] == 36
    assert binding["keys_per_sdf_layout"] == [12, 12, 12]
    assert binding["audited_training_keys"] == 3

    duplicated = [attempts[0], attempts[0], attempts[2]]
    with pytest.raises(ValueError, match="duplicated"):
        AUDIT._validate_aggregate_against_frozen_training_manifest(
            duplicated,
            ROOT / "configs/m2c_s4_training_keys.json",
        )

    tampered = json.loads(json.dumps(attempts))
    tampered[0]["attempt_identity"]["failure_seed"] += 1
    with pytest.raises(ValueError, match="failure_seed"):
        AUDIT._validate_aggregate_against_frozen_training_manifest(
            tampered,
            ROOT / "configs/m2c_s4_training_keys.json",
        )

    tampered_manifest = json.loads(json.dumps(manifest))
    tampered_manifest["training_keys"][0]["failure_seed"] += 1
    tampered_path = tmp_path / "tampered-training-keys.json"
    tampered_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="content digest"):
        AUDIT._validate_aggregate_against_frozen_training_manifest(
            attempts,
            tampered_path,
        )
