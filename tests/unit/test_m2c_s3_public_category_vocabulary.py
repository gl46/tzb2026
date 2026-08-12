from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_s3_public_category_vocabulary.py"
SPEC = importlib.util.spec_from_file_location("m2c_s3_category_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def _row() -> dict[str, object]:
    tracks = [
        {
            "schema_version": "PublicTrackSnapshotV2",
            "track_id": "track-target",
            "category": "industrial_cylinder",
            "visual_color": "Yellow",
            "confidence": 0.99,
            "position_world_m": [0.1, 0.2, 0.3],
        },
        {
            "schema_version": "PublicTrackSnapshotV2",
            "track_id": "track-other",
            "category": "industrial_cylinder",
            "visual_color": "blue",
            "confidence": 0.8,
            "position_world_m": [0.2, 0.2, 0.3],
        },
    ]
    return {
        "schema_version": "FailureRecoveryEpisodeV2",
        "task_spec": {
            "instruction": "recover the public yellow target",
            "source": "PUBLIC_RGBD_TASK_SPEC",
            "target_selector": "visual_color=yellow,top_z_band=0.02m,world_x=max",
            "simulator_entity_id_used": False,
        },
        "observation_before": {"tracks": tracks},
        "observation_after": {"tracks": copy.deepcopy(tracks)},
        "recovery_observations": [{"tracks": copy.deepcopy(tracks)}],
        "teacher_response": None,
        "teacher_used": False,
        "policy_input_simulator_truth": False,
    }


def _write_fixture(tmp_path: Path, row: dict[str, object]) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / "s3.jsonl"
    evidence.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "M2CS3PublicCategoryVocabularyInputManifestV1",
                "evidence_files": [
                    {
                        "path": str(evidence),
                        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    }
                ],
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        ),
        encoding="utf-8",
    )
    return manifest, evidence


def test_audit_passes_only_when_category_carries_declared_attribute(tmp_path: Path) -> None:
    manifest, _ = _write_fixture(tmp_path, _row())
    report = AUDIT.audit_manifest(ROOT, manifest)
    assert report["status"] == "PASS_CATEGORY_CARRIES_DECLARED_ATTRIBUTE_VOCABULARY"
    assert report["records_audited"] == 1
    assert report["observations_audited"] == 3
    assert report["tracks_audited"] == 6
    assert report["category_attribute_matches"] == 3
    assert report["declared_attributes"] == ["yellow"]
    assert report["task_spec_target_track_id_read"] is False
    assert report["visual_color_promoted_as_standalone_category"] is False
    assert report["raw_category_and_visual_color_remain_distinct"] is True
    assert report["public_adapter_path"] == "scripts/m2b/build_coarse_training_v2.py"
    assert len(report["public_adapter_sha256"]) == 64
    assert report["teacher_used"] is False
    assert report["privileged_truth_policy_input"] is False


@pytest.mark.parametrize("field", ["category", "visual_color", "pose_xyzquat"])
def test_missing_category_or_pose_fails_closed(tmp_path: Path, field: str) -> None:
    row = _row()
    track = row["observation_before"]["tracks"][0]  # type: ignore[index]
    if field == "pose_xyzquat":
        track.pop("position_world_m")
    else:
        track.pop(field)
    manifest, _ = _write_fixture(tmp_path, row)
    with pytest.raises(
        ValueError,
        match="missing category|missing public pose|lacks visual_color",
    ):
        AUDIT.audit_manifest(ROOT, manifest)


def test_projected_category_attribute_mismatch_fails_closed(tmp_path: Path) -> None:
    row = _row()
    for observation in (
        row["observation_before"],
        row["observation_after"],
        row["recovery_observations"][0],  # type: ignore[index]
    ):
        tracks = observation["tracks"]  # type: ignore[index]
        for track in tracks:
            track["category"] = "industrial_cylinder"
            track["visual_color"] = "blue"
    manifest, _ = _write_fixture(tmp_path, row)
    with pytest.raises(ValueError, match="category vocabulary does not carry"):
        AUDIT.audit_manifest(ROOT, manifest)


def test_task_spec_target_track_id_is_ignored_and_cannot_forge_match(tmp_path: Path) -> None:
    first = _row()
    first["task_spec"]["target_track_id"] = "track-target"  # type: ignore[index]
    first_manifest, _ = _write_fixture(tmp_path / "first", first)
    first_report = AUDIT.audit_manifest(ROOT, first_manifest)

    second = copy.deepcopy(first)
    second["task_spec"]["target_track_id"] = "track-other"  # type: ignore[index]
    second_manifest, _ = _write_fixture(tmp_path / "second", second)
    second_report = AUDIT.audit_manifest(ROOT, second_manifest)
    for field in (
        "status",
        "records_audited",
        "observations_audited",
        "tracks_audited",
        "category_attribute_matches",
        "declared_attributes",
    ):
        assert first_report[field] == second_report[field]
    assert first_report["task_spec_target_track_id_read"] is False

    forged = copy.deepcopy(first)
    forged["task_spec"]["target_selector"] = "visual_color=red,world_x=max"  # type: ignore[index]
    forged_manifest, _ = _write_fixture(tmp_path / "forged", forged)
    with pytest.raises(ValueError, match="category vocabulary does not carry"):
        AUDIT.audit_manifest(ROOT, forged_manifest)


def test_projected_perception_track_requires_category_pose_and_attribute(
    tmp_path: Path,
) -> None:
    row = _row()
    for observation in (
        row["observation_before"],
        row["observation_after"],
        row["recovery_observations"][0],  # type: ignore[index]
    ):
        for track in observation["tracks"]:  # type: ignore[index]
            track["schema_version"] = "PerceptionTrackV1"
            track["category"] = f"{track['category']}:{track.pop('visual_color')}"
            track["pose_xyzquat"] = [*track.pop("position_world_m"), 1.0, 0.0, 0.0, 0.0]
    manifest, _ = _write_fixture(tmp_path, row)
    report = AUDIT.audit_manifest(ROOT, manifest)
    assert report["category_attribute_matches"] == 3


def test_teacher_truth_or_identity_track_field_is_rejected(tmp_path: Path) -> None:
    for field, value in (
        ("teacher_output", "label"),
        ("simulator_truth_role", "TARGET"),
        ("prim_path", "/World/object"),
    ):
        row = _row()
        row["observation_before"]["tracks"][0][field] = value  # type: ignore[index]
        manifest, _ = _write_fixture(tmp_path / field, row)
        with pytest.raises(ValueError, match="forbidden Teacher/truth/identity"):
            AUDIT.audit_manifest(ROOT, manifest)


def test_symlink_and_hash_tamper_are_rejected(tmp_path: Path) -> None:
    manifest, evidence = _write_fixture(tmp_path, _row())
    link = tmp_path / "evidence-link.jsonl"
    link.symlink_to(evidence)
    payload = json.loads(manifest.read_text())
    payload["evidence_files"][0]["path"] = str(link)
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="may not be a symlink"):
        AUDIT.audit_manifest(ROOT, manifest)

    manifest, evidence = _write_fixture(tmp_path / "tamper", _row())
    evidence.write_bytes(evidence.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        AUDIT.audit_manifest(ROOT, manifest)

    real_manifest, _ = _write_fixture(tmp_path / "manifest-link", _row())
    manifest_link = tmp_path / "manifest-symlink.json"
    manifest_link.symlink_to(real_manifest)
    with pytest.raises(OSError):
        AUDIT.audit_manifest(ROOT, manifest_link)


def test_report_is_create_only(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    AUDIT.write_report_create_only(output, {"status": "PASS"})
    with pytest.raises(FileExistsError):
        AUDIT.write_report_create_only(output, {"status": "OVERWRITE"})


def test_current_s3_artifact_replays_official_public_projection(tmp_path: Path) -> None:
    evidence = ROOT / "artifacts/m2c/dataset-v3.jsonl"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "M2CS3PublicCategoryVocabularyInputManifestV1",
                "evidence_files": [
                    {
                        "path": str(evidence),
                        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    }
                ],
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        )
    )
    report = AUDIT.audit_manifest(ROOT, manifest)
    assert report["status"] == "PASS_CATEGORY_CARRIES_DECLARED_ATTRIBUTE_VOCABULARY"
    assert report["records_audited"] == 312
    assert report["task_spec_target_track_id_read"] is False
