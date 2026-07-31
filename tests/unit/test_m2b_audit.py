from __future__ import annotations

import json
from pathlib import Path

from m2b.audit_m2a import (
    entropy,
    failure_context_audit,
    mapping_audit,
    residual_audit,
)


def _episode(
    episode_id: str,
    *,
    failure_type: str,
    skill: str,
    residual: list[float],
    split: str = "train",
) -> dict:
    context = {
        "failure_type": failure_type,
        "last_skill": "OBSERVE",
        "expected_predicates": ["observed"],
        "observed_predicates": [],
        "predicate_residual": ["missing:observed"]
        if failure_type != "NONE"
        else [],
        "retry_count": 0,
        "attempted_recoveries": [],
    }
    return {
        "episode_id": episode_id,
        "scene_seed": int(episode_id.rsplit("-", 1)[-1]),
        "split": split,
        "failure_context": context,
        "nominal_skill": skill,
        "recovery_sequence": [skill] if failure_type != "NONE" else [],
        "nominal_action": {"values": [[0.0] * 10]},
        "residual_action": {
            "dimension_names": [
                "dx",
                "dy",
                "dz",
                "r0",
                "r1",
                "r2",
                "r3",
                "r4",
                "r5",
                "gripper",
            ],
            "values": [residual, residual],
        },
        "result": {},
        "provenance": {
            "residual_label": "truth_minus_public_track",
        },
    }


def test_entropy_distinguishes_constant_and_balanced_values() -> None:
    assert entropy(["a", "a"]) == 0.0
    assert entropy(["a", "b"]) == 1.0


def test_failure_context_audit_reports_missing_mandatory_failures() -> None:
    episodes = [
        _episode(
            "episode-1",
            failure_type="NONE",
            skill="APPROACH",
            residual=[0.0] * 10,
        ),
        _episode(
            "episode-2",
            failure_type="TRACKING_LOST",
            skill="REOBSERVE",
            residual=[0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            split="test",
        ),
    ]
    report = failure_context_audit(episodes)
    assert report["status"] == "LIMITED"
    assert report["mandatory_failure_counts"] == {
        "EMPTY_GRASP": 0,
        "WRONG_OBJECT": 0,
        "RELEASE_FAILURE": 0,
    }
    assert report["scene_split_conflicts"] == 0
    assert report["verdict"] == "INCONCLUSIVE"


def test_residual_audit_detects_unsupported_correction_targets() -> None:
    episode = _episode(
        "episode-1",
        failure_type="NONE",
        skill="APPROACH",
        residual=[0.03, -0.02, 0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )
    report = residual_audit([episode])
    assert report["status"] == "RESIDUAL_TARGET_DEGENERATE"
    assert report["translation_saturation_count"] == 1
    assert report["successful_correction_label_count"] == 0
    assert report["nominal_action_exact_zero_count"] == 1


def test_mapping_audit_separates_integration_absence_from_bad_output() -> None:
    decisions = [
        {
            "coarse_skill": "APPROACH",
            "mapping_validation": "REJECTED_NO_OFFICIAL_EVIDENCE",
            "public_track_count": 4,
            "residual_proposed": True,
            "applies_to_step": 1,
        }
    ]
    source = (
        'False,\n                    "UNVERIFIED_CAMERA_RESIDUAL_TO_JOINT_MAPPING"\n'
        '"REJECTED_NO_OFFICIAL_EVIDENCE"'
    )
    report = mapping_audit(
        decisions,
        metrics_files=1,
        worker_source=source,
    )
    assert report["integration_gate_is_unconditional"] is True
    assert report["model_output_invalid_count_proven"] == 0
    assert report["reason_histogram"]["integration_mapping_absent"] == 1


def test_audit_module_does_not_write_m2a_reports() -> None:
    source = Path(__file__).parents[2] / "scripts" / "m2b" / "audit_m2a.py"
    text = source.read_text()
    assert 'write_report(\n        args.report_dir / "m2a-' not in text
    assert json.loads('{"teacher_used": false}')["teacher_used"] is False

