from __future__ import annotations

import pytest

from m2b.build_isolated_preflight_manifest import (
    M2BIsolatedPreflightPlanV1,
    manifest_from_payload,
)


def empty_grasp_payload() -> dict:
    return {
        "source_hashes": {
            "scene.sdf": "a" * 64,
            "scene.supervision.json": "b" * 64,
        },
        "m2b_public_rgbd": {
            "simulator_truth_policy_input": False,
            "captures": [{"label": "empty_grasp_reobserve"}],
        },
        "m2b_recovery": {
            "empty_grasp": {"training_eligible": True}
        },
    }


def test_isolated_action_run_becomes_prospective_preflight() -> None:
    plan = M2BIsolatedPreflightPlanV1(
        sample_id="sample-1",
        failure_type="EMPTY_GRASP",
        runtime_action="HOLD_AND_CAPTURE_PUBLIC_RGBD",
        preflight_evidence_path="/evidence/actuation-probe.json",
    )
    manifest = manifest_from_payload(
        plan,
        empty_grasp_payload(),
        evidence_sha256="c" * 64,
    )
    assert manifest.receipt.complete_and_passing is True
    assert manifest.receipt.model_selected is False
    assert manifest.isolated_from_evaluation_rollout is True
    assert manifest.evaluation_execution_started is False
    assert manifest.model_selection_triggered_preflight is True
    assert manifest.teacher_used is False


def test_preflight_rejects_different_runtime_action() -> None:
    plan = M2BIsolatedPreflightPlanV1(
        sample_id="sample-1",
        failure_type="EMPTY_GRASP",
        runtime_action="B0_RELEASE_RETRY",
        preflight_evidence_path="/evidence/actuation-probe.json",
    )
    with pytest.raises(ValueError, match="was not preflighted"):
        manifest_from_payload(
            plan,
            empty_grasp_payload(),
            evidence_sha256="c" * 64,
        )
