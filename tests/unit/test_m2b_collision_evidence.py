from __future__ import annotations

from xh_agent.policy.qrm_lite.collision_evidence import (
    evaluate_robot_collision_events,
)


def event(path0: str, path1: str, *, step: int = 10) -> dict[str, object]:
    return {
        "physics_step": step,
        "event_type": 1,
        "actor0": path0,
        "actor1": path1,
        "collider0": path0,
        "collider1": path1,
        "contact_point_count": 1,
    }


def test_free_motion_rejects_robot_environment_contact() -> None:
    result = evaluate_robot_collision_events(
        [event("/World/Robot/panda_link4/mesh", "/World/M1B/table/link")],
        phase="PUBLIC_REGRASP_PREGRASP",
    )
    assert result["status"] == "REJECTED"
    assert result["unexpected_robot_contact_events"] == 1
    assert result["privileged_truth_policy_input"] is False
    assert result["teacher_used"] is False


def test_phase_local_finger_target_contact_is_allowed() -> None:
    result = evaluate_robot_collision_events(
        [
            event(
                "/World/Robot/panda_leftfinger/collision",
                "/World/M1B/cylinder_07/link/collision",
            )
        ],
        phase="PUBLIC_REGRASP_CONTACT",
        allowed_robot_collider_prefixes=(
            "/World/Robot/panda_leftfinger",
            "/World/Robot/panda_rightfinger",
        ),
        allowed_external_collider_prefixes=("/World/M1B/cylinder_07/link",),
    )
    assert result["status"] == "PASS"
    assert result["allowed_robot_contact_events"] == 1
    assert result["unexpected_robot_contact_events"] == 0


def test_same_external_contact_is_rejected_outside_explicit_phase_allowlist() -> None:
    result = evaluate_robot_collision_events(
        [
            event(
                "/World/Robot/panda_leftfinger/collision",
                "/World/M1B/cylinder_07/link/collision",
            )
        ],
        phase="DETACH_RETREAT",
    )
    assert result["status"] == "REJECTED"


def test_scene_only_contacts_do_not_fail_robot_collision_gate_and_dedupe() -> None:
    scene_event = event(
        "/World/M1B/cylinder_04/link",
        "/World/M1B/table/link",
    )
    result = evaluate_robot_collision_events(
        [scene_event, scene_event],
        phase="HOLD_AND_CAPTURE",
    )
    assert result["status"] == "PASS"
    assert result["events_total"] == 1
    assert result["robot_contact_events"] == 0


def test_robot_self_contact_is_never_allowlisted() -> None:
    result = evaluate_robot_collision_events(
        [
            event(
                "/World/Robot/panda_leftfinger",
                "/World/Robot/panda_rightfinger",
            )
        ],
        phase="PUBLIC_REGRASP_CONTACT",
        allowed_robot_collider_prefixes=("/World/Robot",),
        allowed_external_collider_prefixes=("/World/Robot",),
    )
    assert result["status"] == "REJECTED"
