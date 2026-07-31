from __future__ import annotations

import pytest

from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    extract_physical_runtime_gate_receipt,
)


def base_payload() -> dict[str, object]:
    return {
        "m2b_public_rgbd": {
            "simulator_truth_policy_input": False,
            "captures": [{"label": "empty_grasp_reobserve"}],
        },
        "phases": {
            "detach_retreat": {
                "final_error_m": 0.001,
                "collision_gate": {"status": "PASS"},
            }
        },
        "detached_noncoupling": {"passed": True},
        "m2b_recovery": {
            "empty_grasp": {"training_eligible": True},
            "wrong_object": {
                "training_eligible": True,
                "safe_place_non_target_passed": True,
            },
            "release_failure": {
                "training_eligible": True,
                "retry_detach_and_retreat_passed": True,
            },
        },
    }


@pytest.mark.parametrize(
    ("failure", "skill", "action"),
    [
        ("EMPTY_GRASP", "REOBSERVE", "HOLD_AND_CAPTURE_PUBLIC_RGBD"),
        (
            "WRONG_OBJECT",
            "SAFE_PLACE_NON_TARGET",
            "B0_SAFE_PLACE_NON_TARGET",
        ),
        ("RELEASE_FAILURE", "RETRY_RELEASE", "B0_RELEASE_RETRY"),
    ],
)
def test_extracts_passing_post_execution_receipt(
    failure: str,
    skill: str,
    action: str,
) -> None:
    receipt = extract_physical_runtime_gate_receipt(
        base_payload(), failure_type=failure
    )
    assert receipt.recovery_skill == skill
    assert receipt.runtime_action == action
    assert receipt.complete_and_passing is True
    assert receipt.model_selected is False
    assert receipt.prospective_planning_check is False
    assert receipt.teacher_used is False


def test_missing_collision_monitor_stays_not_run() -> None:
    payload = base_payload()
    payload["phases"]["detach_retreat"].pop("collision_gate")  # type: ignore[index, union-attr]
    receipt = extract_physical_runtime_gate_receipt(
        payload, failure_type="RELEASE_FAILURE"
    )
    assert receipt.collision_gate == "NOT_RUN"
    assert receipt.complete_and_passing is False


def test_rejects_missing_public_only_policy_declaration() -> None:
    payload = base_payload()
    payload["m2b_public_rgbd"]["simulator_truth_policy_input"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="public-only"):
        extract_physical_runtime_gate_receipt(
            payload, failure_type="WRONG_OBJECT"
        )
