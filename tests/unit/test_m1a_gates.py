from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from xh_agent.grasp.contact_gate import ContactGateInput, evaluate_contact_gate
from xh_agent.grasp.contact_telemetry import ContactEvent, bilateral_contact_window
from xh_agent.grasp.failure_attribution import FailureClass, attribute_failure
from xh_agent.grasp.release_gate import ReleaseEvidence, evaluate_release
from xh_agent.runtime.continuity import JointSample, check_joint_continuity
from xh_agent.runtime.motion_execution import MotionSegmentEvidence, evaluate_motion_segment


def contact_events(*, target: str = "red_cube", duration_s: float = 0.1) -> list[ContactEvent]:
    timestamps = [0.0, duration_s / 2.0, duration_s]
    events: list[ContactEvent] = []
    for timestamp in timestamps:
        events.extend(
            [
                ContactEvent(timestamp, "left", target, ("panda_leftfinger", target)),
                ContactEvent(timestamp, "right", target, ("panda_rightfinger", target)),
            ]
        )
    return events


def samples(*, jump: float = 0.01, count: int = 20) -> list[JointSample]:
    return [
        JointSample(index * 0.01, {"panda_joint1": index * jump})
        for index in range(count)
    ]


def continuity() -> object:
    return check_joint_continuity(
        samples(), velocity_limits_rad_s={"panda_joint1": 2.0}, expected_final_positions={"panda_joint1": 0.19}
    )


def good_gate_input(**updates: object) -> ContactGateInput:
    values: dict[str, object] = {
        "target_id": "red_cube",
        "expected_target_id": "red_cube",
        "bilateral_contact_valid": True,
        "gripper_width_m": 0.05,
        "object_width_estimate_m": 0.05,
        "target_in_grasp_corridor": True,
        "relative_linear_speed_mean_mps": 0.01,
        "relative_linear_speed_peak_mps": 0.02,
        "seconds_since_close_command": 0.1,
        "already_attached": False,
        "prohibited_collision": False,
        "controller_aborted": False,
        "valid_sim_timestamps": True,
    }
    values.update(updates)
    return ContactGateInput(**values)  # type: ignore[arg-type]


def test_bilateral_contact_requires_same_target_three_samples_and_100ms() -> None:
    assert bilateral_contact_window(contact_events(), target_id="red_cube") == (True, (), 0.1, 3)
    assert bilateral_contact_window(contact_events(duration_s=0.099), target_id="red_cube")[0] is False
    assert bilateral_contact_window(contact_events(duration_s=0.099), target_id="red_cube")[1] == ("BILATERAL_OVERLAP_TOO_SHORT",)


def test_single_finger_or_mixed_target_contact_never_forms_bilateral_gate() -> None:
    left_only = [ContactEvent(0.0, "left", "red_cube", ("panda_leftfinger", "red_cube"))]
    assert bilateral_contact_window(left_only, target_id="red_cube")[1] == ("RIGHT_FINGER_TARGET_CONTACT_MISSING",)
    events = contact_events()
    events[1] = ContactEvent(0.0, "right", "blue_cube", ("panda_rightfinger", "blue_cube"))
    events[3] = ContactEvent(0.05, "right", "blue_cube", ("panda_rightfinger", "blue_cube"))
    events[5] = ContactEvent(0.1, "right", "blue_cube", ("panda_rightfinger", "blue_cube"))
    assert bilateral_contact_window(events, target_id="red_cube")[0] is False


def test_contact_timestamp_rewind_fails_closed() -> None:
    events = contact_events()
    events[2] = ContactEvent(-0.01, "left", "red_cube", ("panda_leftfinger", "red_cube"))
    assert bilateral_contact_window(events, target_id="red_cube")[1] == ("CONTACT_TIME_REWIND",)


def test_contact_gate_rejects_each_critical_missing_condition() -> None:
    assert evaluate_contact_gate(good_gate_input())[0] is True
    for update, reason in [
        ({"bilateral_contact_valid": False}, "BILATERAL_CONTACT_INVALID"),
        ({"gripper_width_m": 0.04}, "GRIPPER_WIDTH_OUT_OF_RANGE"),
        ({"relative_linear_speed_mean_mps": 0.021}, "RELATIVE_SPEED_TOO_HIGH"),
        ({"target_in_grasp_corridor": False}, "TARGET_OUTSIDE_GRASP_CORRIDOR"),
        ({"target_id": "blue_cube"}, "TARGET_ID_MISMATCH"),
        ({"seconds_since_close_command": 1.01}, "NO_RECENT_CLOSE_COMMAND"),
        ({"prohibited_collision": True}, "PROHIBITED_COLLISION"),
    ]:
        passed, reasons = evaluate_contact_gate(good_gate_input(**update))
        assert not passed
        assert reason in reasons


def test_continuity_rejects_teleport_short_series_and_nonmonotonic_time() -> None:
    jumped = samples(jump=0.2)
    result = check_joint_continuity(
        jumped, velocity_limits_rad_s={"panda_joint1": 100.0}, expected_final_positions={"panda_joint1": 3.8}
    )
    assert not result.passed
    assert "ADJACENT_JOINT_JUMP" in result.reasons
    too_few = check_joint_continuity(samples(count=2), velocity_limits_rad_s={"panda_joint1": 2.0}, expected_final_positions={"panda_joint1": 0.01})
    assert "INSUFFICIENT_JOINT_STATE_SAMPLES" in too_few.reasons
    rewind = samples()
    rewind[3] = JointSample(0.0, {"panda_joint1": 0.03})
    assert "NON_MONOTONIC_JOINT_STATE_TIME" in check_joint_continuity(
        rewind, velocity_limits_rad_s={"panda_joint1": 2.0}, expected_final_positions={"panda_joint1": 0.19}
    ).reasons


def test_motion_plan_only_and_controller_abort_never_verify_execution() -> None:
    base = dict(
        planned=True,
        action_endpoint="/execute_trajectory",
        action_goal_uuid="goal",
        controller_result="SUCCEEDED",
        duration_s=1.0,
        max_final_joint_error_rad=0.01,
        ee_position_error_m=0.01,
        ee_orientation_error_rad=0.01,
        continuity=continuity(),
        gazebo_set_pose_or_joint_called=False,
        moveit_model_matches_gazebo=True,
        scene_collision_objects=("table", "bin_a"),
    )
    assert evaluate_motion_segment(MotionSegmentEvidence(dispatched=False, **base))[0] == "PLAN_ONLY"
    status, reasons = evaluate_motion_segment(MotionSegmentEvidence(dispatched=True, controller_result="ABORTED", **{key: value for key, value in base.items() if key != "controller_result"}))
    assert status == "PARTIAL_EXECUTION_VERIFIED"
    assert "CONTROLLER_NOT_SUCCEEDED" in reasons


def test_motion_gate_rejects_error_and_direct_pose_write() -> None:
    evidence = MotionSegmentEvidence(
        planned=True,
        dispatched=True,
        action_endpoint="/execute_trajectory",
        action_goal_uuid="goal",
        controller_result="SUCCEEDED",
        duration_s=1.0,
        max_final_joint_error_rad=0.06,
        ee_position_error_m=0.03,
        ee_orientation_error_rad=0.01,
        continuity=continuity(),
        gazebo_set_pose_or_joint_called=True,
        moveit_model_matches_gazebo=True,
        scene_collision_objects=("table", "bin_a"),
    )
    _, reasons = evaluate_motion_segment(evidence)
    assert {"FINAL_JOINT_ERROR_EXCEEDED", "EE_POSITION_ERROR_EXCEEDED", "GAZEBO_DIRECT_POSE_OR_JOINT_WRITE"}.issubset(reasons)


def test_release_requires_task_time_open_detach_and_settle() -> None:
    good = ReleaseEvidence(True, True, 0.07, 0.1, False, True, 1.0, 0.001, False, False)
    assert evaluate_release(good) == (True, ())
    cleanup = ReleaseEvidence(True, True, 0.07, 0.1, False, True, 1.0, 0.001, True, False)
    assert "CLEANUP_DETACH" in evaluate_release(cleanup)[1]
    delayed = ReleaseEvidence(True, True, 0.07, 0.51, False, True, 1.0, 0.001, False, False)
    assert "DETACH_DEADLINE_MISSED" in evaluate_release(delayed)[1]


def test_failure_attribution_is_closed_and_prioritizes_approach() -> None:
    assert attribute_failure(fingertip_to_object_center_m=0.031, bilateral_contact=False, lifted_m=0.0, held_s=0.0, released_explicitly=False, object_stable_in_bin=False) is FailureClass.APPROACH_ALIGNMENT_FAILURE
    assert attribute_failure(fingertip_to_object_center_m=0.01, bilateral_contact=False, lifted_m=0.0, held_s=0.0, released_explicitly=False, object_stable_in_bin=False) is FailureClass.CONTACT_CLOSURE_FAILURE
    assert attribute_failure(fingertip_to_object_center_m=0.01, bilateral_contact=True, lifted_m=0.05, held_s=0.5, released_explicitly=False, object_stable_in_bin=False) is FailureClass.HOLD_TRANSPORT_FAILURE
    assert attribute_failure(fingertip_to_object_center_m=0.01, bilateral_contact=True, lifted_m=0.05, held_s=1.0, released_explicitly=False, object_stable_in_bin=False) is FailureClass.RELEASE_PLACEMENT_FAILURE


def test_m1a_protocol_files_define_fail_closed_sensor_and_execution_gates() -> None:
    root = Path(__file__).parents[2]
    contact = yaml.safe_load((root / "configs/m1a_contact_gate.yaml").read_text())
    execution = yaml.safe_load((root / "configs/m1a_execution_gate.yaml").read_text())
    assert contact["bilateral_contact_overlap_s"] == 0.1
    assert contact["minimum_consecutive_samples"] == 3
    assert execution["max_final_joint_error_rad"] == 0.05
    assert execution["required_motion_trials"] == 10
    urdf = (root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_text()
    assert "left_finger_contact" in urdf and "right_finger_contact" in urdf
    runner = (root / "scripts/run_m1a_validation.sh").read_text()
    assert "run_m1a_m0_smoke.sh" in runner
    assert "run_contact_calibration.sh" in runner and "run_moveit_execution_gate.sh" in runner
    assert "run_friction_grasp_trials.sh" in runner
    assert "set_pose" not in runner and "set_model" not in runner


def test_m1a_manifest_report_hashes_are_verifiable() -> None:
    root = Path(__file__).parents[2]
    manifest = json.loads((root / "data/manifests/m1a-runtime-grasp-v1.json").read_text())
    assert manifest["schema_version"] == "m1a-runtime-grasp-v1"
    for relative_path, expected_hash in manifest["file_hashes"].items():
        actual_hash = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
        assert actual_hash == expected_hash
