from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import yaml
import pytest

from xh_agent.grasp.contact_gate import (
    ContactGateInput,
    evaluate_contact_gate,
    symmetric_contact_stall_goal_tolerance_m,
)
from xh_agent.grasp.contact_telemetry import ContactEvent, bilateral_contact_window
from xh_agent.grasp.failure_attribution import FailureClass, attribute_failure
from xh_agent.grasp.orientation_families import (
    candidate_is_eligible,
    candidate_pose,
    gripper_frame_corridor,
    quaternion_rotate,
)
from xh_agent.grasp.release_gate import ReleaseEvidence, evaluate_release
from xh_agent.runtime.continuity import JointSample, check_joint_continuity
from xh_agent.runtime.motion_execution import MotionSegmentEvidence, evaluate_motion_segment


PANDA_JOINT_PROTOCOL_V1 = {
    "panda_joint1": (-2.8973, 2.8973, 2.3925, "revolute", "rad"),
    "panda_joint2": (-1.7628, 1.7628, 2.3925, "revolute", "rad"),
    "panda_joint3": (-2.8973, 2.8973, 2.3925, "revolute", "rad"),
    "panda_joint4": (-3.0718, 0.0175, 2.3925, "revolute", "rad"),
    "panda_joint5": (-2.8973, 2.8973, 2.8710, "revolute", "rad"),
    "panda_joint6": (-0.0175, 3.7525, 2.8710, "revolute", "rad"),
    "panda_joint7": (-2.8973, 2.8973, 2.8973, "revolute", "rad"),
    "panda_finger_joint1": (0.0, 0.04, 0.2, "prismatic", "m"),
    "panda_finger_joint2": (0.0, 0.04, 0.2, "prismatic", "m"),
}


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


def test_contact_stall_tolerance_is_bounded_and_requires_valid_finger_positions() -> None:
    # ADR-0016b franka-copy geometry: q=27 mm command, q=31.5 mm cube
    # surface.  The 3 mm measured engine allowance and 1 mm contract admit a
    # physical stall but cannot turn an arbitrary finger position into PASS.
    assert symmetric_contact_stall_goal_tolerance_m(
        command_per_finger_m=0.027, contact_surface_per_finger_m=0.0315,
    ) == pytest.approx(0.0085)
    assert symmetric_contact_stall_goal_tolerance_m(
        command_per_finger_m=0.033, contact_surface_per_finger_m=0.0315,
    ) == pytest.approx(0.0025)
    with pytest.raises(ValueError):
        symmetric_contact_stall_goal_tolerance_m(
            command_per_finger_m=0.027, contact_surface_per_finger_m=0.041,
        )


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
    assert "panda_leftfinger_fixed_joint_lump__collision_collision" in urdf
    assert "panda_rightfinger_fixed_joint_lump__collision_collision" in urdf
    assert "panda_leftfinger_collision" not in urdf
    assert "panda_rightfinger_collision" not in urdf
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


def test_m1a_moveit_configuration_preserves_controlled_joint_names_limits_and_units() -> None:
    root = Path(__file__).parents[2]
    urdf_root = ET.parse(root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").getroot()
    limits = {
        joint.attrib["name"]: joint.find("limit").attrib
        for joint in urdf_root.findall("joint")
        if joint.attrib["name"].startswith("panda_") and joint.find("limit") is not None
    }
    configured = yaml.safe_load((root / "robot_ws/src/xh_sim/config/m1a_joint_limits.yaml").read_text())["joint_limits"]
    expected_names = set(PANDA_JOINT_PROTOCOL_V1)
    assert set(configured) == expected_names == set(limits)
    for name in expected_names:
        lower, upper, velocity, kind, unit = PANDA_JOINT_PROTOCOL_V1[name]
        joint = next(item for item in urdf_root.findall("joint") if item.attrib["name"] == name)
        assert joint.attrib["type"] == kind
        assert unit == ("rad" if kind == "revolute" else "m")
        assert float(limits[name]["lower"]) == lower
        assert float(limits[name]["upper"]) == upper
        assert float(limits[name]["velocity"]) == velocity
        assert configured[name]["max_velocity"] == velocity
        assert configured[name]["has_velocity_limits"] is True
        assert configured[name]["has_acceleration_limits"] is True
        assert configured[name]["max_acceleration"] > 0
        assert "min_position" not in configured[name]
        assert "max_position" not in configured[name]
    follower = urdf_root.find("joint[@name='panda_finger_joint1']")
    assert follower is not None
    mimic = follower.find("mimic")
    assert mimic is not None
    assert mimic.attrib == {"joint": "panda_finger_joint2", "multiplier": "1", "offset": "0"}
    ros2_control = urdf_root.find("ros2_control")
    assert ros2_control is not None
    q1_interfaces = ros2_control.find("joint[@name='panda_finger_joint1']")
    q2_interfaces = ros2_control.find("joint[@name='panda_finger_joint2']")
    assert q1_interfaces is not None and q2_interfaces is not None
    assert q1_interfaces.attrib == {"name": "panda_finger_joint1", "mimic": "false"}
    assert q1_interfaces.find("command_interface[@name='position']") is None
    assert q1_interfaces.find("state_interface[@name='position']") is not None
    assert q1_interfaces.find("param[@name='mimic']") is None
    assert q1_interfaces.find("param[@name='multiplier']") is None
    assert q2_interfaces.find("command_interface[@name='position']") is not None
    hand_controller = yaml.safe_load(
        (root / "robot_ws/src/xh_sim/config/panda_controllers.yaml").read_text()
    )["panda_hand_physical_controller"]["ros__parameters"]
    assert hand_controller["set_last_command_interface_value_as_state_on_activation"] is True
    source_urdf = root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
    launch = (root / "robot_ws/src/xh_sim/launch/moveit_execution.launch.py").read_text()
    assert '.robot_description(file_path="urdf/panda_controlled.urdf")' in launch
    assert source_urdf.exists()
    simulation_launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    calibration_world = (root / "robot_ws/src/xh_sim/worlds/m1a_contact_calibration.sdf").read_text()
    assert "re.sub" not in simulation_launch
    assert "<collision>.*?</collision>" not in simulation_launch
    assert "calibration_mode" in simulation_launch
    assert "gz-sim-detachable-joint-system" in source_urdf.read_text()
    assert "<position_proportional_gain>1.0</position_proportional_gain>" in source_urdf.read_text()
    # The five M1A bridges remain unchanged.  ADR-0013 adds the two private
    # M1B finger streams plus an internally generated set of cylinder-side
    # contact bridges; neither replaces an M1A supervision topic.
    assert simulation_launch.count("ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts") == 8
    assert "/xh/actuation_internal/m1b/panda_leftfinger_contacts" in simulation_launch
    assert "/xh/actuation_internal/m1b/panda_rightfinger_contacts" in simulation_launch
    assert "cylinder_{index:02d}_contacts" in simulation_launch
    assert '"/xh/supervision/panda_leftfinger_contacts"' in simulation_launch
    assert '"/xh/supervision/panda_rightfinger_contacts"' in simulation_launch
    assert "dynamic_pose/info" in simulation_launch
    assert "red_cube_bilateral_contacts" in simulation_launch
    assert "work_table_bilateral_backstop" in calibration_world
    assert 'model name="work_table_bilateral_support"' in calibration_world
    assert '"/xh/supervision/dynamic_pose"' in simulation_launch
    srdf = (root / "robot_ws/src/xh_sim/config/m1a_panda.srdf").read_text()
    assert "panda_link0\" tip_link=\"panda_hand" in srdf
    assert "panda_leftfinger\" link2=\"object_red_cube" not in srdf
    policy = yaml.safe_load((root / "robot_ws/src/xh_sim/config/m1a_collision_policy.yaml").read_text())
    enabled = {tuple(pair) for pair in policy["enabled_robot_world_collision_pairs"]}
    assert ("panda_leftfinger", "object_red_cube") in enabled
    assert ("panda_rightfinger", "object_red_cube") in enabled
    assert ("panda_link1", "work_table") in enabled
    assert policy["allowed_collision_exceptions"] == [["panda_link0", "work_table"]]


def test_m1a_execution_client_uses_moveit_plan_execute_fk_and_no_pose_write() -> None:
    root = Path(__file__).parents[2]
    source = (root / "scripts/m1a_moveit_execution_client.py").read_text()
    assert '"/plan_kinematic_path"' in source
    assert '"/execute_trajectory"' in source
    assert '"/compute_fk"' in source
    assert '"/get_planning_scene"' in source
    assert '"/joint_states"' in source
    assert '"/panda_arm_controller/controller_state"' in source
    assert '"q_des"' in source and '"q_act"' in source
    assert "max_tracking_error <= 0.05" in source
    assert 'b["timestamp_s"] >= a["timestamp_s"]' in source
    assert "joint_state_distinct_timestamp_count" in source
    assert "distinct_sample_timestamps >= 20" in source
    assert "current_acm()" in source
    assert 'set_allowed_pair(matrix, "panda_link0", "work_table", True)' in source
    assert "post_controller_converged" in source
    assert "consecutive_converged >= 5" in source
    assert "planned_by_name" in source
    assert "PLANNED_JOINT_SET_MISMATCH" in source
    assert "set_pose" not in source and "set_joint" not in source
    s1_runner = (root / "scripts/run_moveit_execution_gate.sh").read_text()
    assert "M1A_S1_CONTROLLER_ACTION_READY" in s1_runner
    assert "'/panda_arm_controller/follow_joint_trajectory'" in s1_runner
    assert "M1A_S1_CONTROLLER_ACTION_UNAVAILABLE" in s1_runner


def test_m1a_contact_calibration_uses_oracle_geometry_hand_control_and_per_trial_windows() -> None:
    root = Path(__file__).parents[2]
    runner = (root / "scripts/run_contact_calibration.sh").read_text()
    client = (root / "scripts/m1a_contact_calibration_client.py").read_text()
    assert "timeout 42" not in runner
    assert "PER_TRIAL_FULL_ACTION_WINDOW" in runner
    assert "gz model" in client and "runtime_cube_pose" in client
    assert '"/compute_ik"' in client
    assert '"/panda_hand_controller/follow_joint_trajectory"' in client
    assert "pad_center_world" in client and "minimum_pad_cube_aabb_separation_m" in client
    assert "CALIBRATION_FINGER_TARGET_INSET_M = 0.002" in client
    assert "calibration_finger_target_inset_m" in client
    assert "runtime_bilateral_cube_pose" in client
    assert "FREE_DYNAMIC_SELF_CENTERING" in client
    assert "target_cube_events" in client
    assert "BILATERAL_PRECONTACT_CLEARANCE_M = 0.001" in client
    assert "BILATERAL_PRECONTACT_VERTICAL_STANDOFF_M = 0.050" in client
    assert "TABLE_TOUCH_PRECONTACT_STANDOFF_M = 0.100" in client
    assert "def table_touch_precontact_pose" in client
    assert "TABLE_PRECONTACT_OR_EXCEPTION_UNAVAILABLE" in client
    assert "client.move_hand_cartesian(table_touch_pose" in client
    assert "BILATERAL_PRECONTACT_FINGER_M = 0.040" in client
    assert "BILATERAL_CONTACT_VERTICAL_OFFSET_M = 0.020" in client
    assert "BILATERAL_FINAL_FINGER_INSET_M = 0.0" in client
    assert "BILATERAL_STEADY_WIDTH_RANGE_M = (0.045, 0.070)" in client
    assert "TABLE_TOUCH_HAND_Z_M = 0.550" in client
    assert "pose.orientation.x = 1.0" in client
    assert "table_contact_pad_evidence" in client
    assert "bilateral_steady_gripper_width_m" in client
    assert 'precontact_motion.get("converged") is True' in client
    assert "def calibration_bilateral_branch_seed()" in client
    assert "name=JOINTS + HAND_JOINTS" in client
    assert "gazebo_link_pose_evidence" in client
    assert "runtime_link_pose" in client
    assert 'r"^\\s*- Pose \\[ XYZ' in client
    assert "CALIBRATION_ONLY_INITIALIZATION" in client
    assert "set_pose" not in client
    assert "bilateral_overlap_s" in client and "observed_rate_hz" in client
    assert "set_pose" not in runner
    world = (root / "robot_ws/src/xh_sim/worlds/p0_pick_place.sdf").read_text()
    assert '<pose>0.22 0.12 0.475 0 0 0</pose>' in world
    calibration_world = (
        root / "robot_ws/src/xh_sim/worlds/m1a_contact_calibration.sdf"
    ).read_text()
    assert '<pose>0.17 0.12 0.755 0 0 0</pose>' in calibration_world
    assert 'model name="work_table_calibration_fixture"' in calibration_world
    assert 'model name="object_red_cube_environment"' in calibration_world
    assert 'model name="calibration_camera_fixture"' in calibration_world
    assert 'gz::sim::systems::Sensors' in calibration_world
    assert "<static>true</static>" in calibration_world
    assert "calibration_cube_anchor" not in calibration_world
    assert "cube_pose_after_action" in client
    assert "observed_positions_m" in client and "max_position_error_m" in client
    assert "JointTolerance" in client
    assert "goal_tolerance_m: float = 0.001" in client
    assert "controller_result_succeeded" in client
    assert "HAND_POST_GOAL_OBSERVATION_SLACK_M = 0.0001" in client
    assert '"/panda_hand_physical_controller/controller_state"' in client
    assert "controller_target_reference_seen" in client
    assert "set_target_touch_exception" in client
    assert "target_touch_exception_restored" in client
    assert '"left", 0.0105, [0.040, 0.040]' in client
    assert '"right", -0.0105, [0.040, 0.040]' in client
    assert '"bilateral", 0.0, [0.027, 0.027]' in client
    assert "begin the evidence window only" in client
    assert "POSE_INDUCED_FIXED_SYMMETRIC_APERTURE" in client
    assert "SYMMETRIC_MIMIC_CLOSE" in client
    assert "calibration_retreat_pose" in client
    assert "BILATERAL_IK_SEED" not in client
    assert "pose-induced, fixed-aperture" in client
    assert "M1A_CALIBRATION_SCOPE" in client
    assert "M1A_CALIBRATION_LABEL" in client and "M1A_CALIBRATION_LABEL" in runner
    assert "FINGER_LENGTH_M = 0.1122" in client and "FINGER_ROOT_Z_M = 0.1032" in client
    assert "Runtime-oracle inline-pad contact pose" in client
    assert "pose_vector(target_pose)" in client and "pose_vector(retreat_pose)" in client
    isolated_runner = (root / "scripts/run_isolated_contact_calibration.sh").read_text()
    aggregator = (root / "scripts/aggregate_isolated_contact_calibration.py").read_text()
    assert "FRESH_GAZEBO_MOVEIT_SESSION_PER_CONDITION" in aggregator
    assert "object_environment_2 table_1 table_2" in isolated_runner
    assert "MISSING_ISOLATED_CONDITION_EVIDENCE" in aggregator
    assert "URDF_HASH_MISMATCH_OR_MISSING_REMOTE_HASH" in aggregator
    assert "Motion causes the label" in client
    assert client.count('"plan_attempts": plan_attempts') >= 2
    assert 'trial.get("retreat", {}).get("executed")' in client
    assert 'scope == "one"' in client
    assert "m1a_contact_calibration.sdf" in runner
    assert "calibration_mode:=true" in runner
    assert "M1A_CALIBRATION_SCOPE" in runner
    simulation_launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    moveit_launch = (root / "robot_ws/src/xh_sim/launch/moveit_execution.launch.py").read_text()
    assert 'LaunchConfiguration("world_file")' in simulation_launch
    assert 'LaunchConfiguration("world_file")' in moveit_launch
    assert "red_cube_environment_contacts" in simulation_launch
    assert "move_joint_target" in client and 'TARGETS[0][1]' in client


def test_isolated_s0_aggregator_requires_all_labels_and_matching_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).parents[2]
    spec = importlib.util.spec_from_file_location(
        "s0_aggregator", root / "scripts/aggregate_isolated_contact_calibration.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    urdf = tmp_path / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
    urdf.parent.mkdir(parents=True)
    urdf.write_text("approved-panda-model")
    model_hash = hashlib.sha256(urdf.read_bytes()).hexdigest()
    logs = []
    for label in module.EXPECTED_LABELS:
        log = tmp_path / f"{label}.log"
        payload = {
            "trials": [
                {
                    "label": "idle", "expected": "none", "passed": True,
                    "event_counts": {"cube_environment": len(logs)},
                },
                {"label": label, "expected": module.expected_kind(label), "passed": True},
            ]
        }
        log.write_text(f"REMOTE_GAZEBO_URDF_SHA256:{model_hash}\n{json.dumps(payload)}\n")
        logs.append(str(log))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["aggregate", "s0-all", *logs])
    assert module.main() == 0
    report = json.loads(Path("reports/m1a-contact-calibration.json").read_text())
    assert report["status"] == "CONTACT_TELEMETRY_CALIBRATED"
    assert report["model_match"] is True
    assert report["calibration_trials_completed"] == 13
    assert report["idle_session_count"] == 13
    assert report["idle_sessions_all_passed"] is True

    Path(logs[-1]).write_text("truncated remote log\n")
    monkeypatch.setattr(sys, "argv", ["aggregate", "s0-missing", *logs])
    assert module.main() == 0
    report = json.loads(Path("reports/m1a-contact-calibration.json").read_text())
    assert report["status"] == "CONTACT_TELEMETRY_PARTIAL"
    assert report["model_match"] is False
    assert any(item.startswith("MISSING_STRUCTURED_EVIDENCE:") for item in report["aggregation_anomalies"])


def test_m1a_rgbd_recorder_uses_real_bridged_camera_frames() -> None:
    root = Path(__file__).parents[2]
    recorder = (root / "scripts/record_m1a_rgbd_video.py").read_text()
    assert '"/xh/camera/rgbd/image"' in recorder
    assert "sensor_msgs.msg import Image" in recorder
    assert 'frame_{self.frames:05d}.ppm' in recorder
    assert "ffmpeg" in recorder


def test_m1a_s2_runs_real_unconstrained_trials_with_early_stop() -> None:
    root = Path(__file__).parents[2]
    runner = (root / "scripts/run_friction_grasp_trials.sh").read_text()
    client = (root / "scripts/m1a_friction_trial_client.py").read_text()
    assert "calibration_mode:=true" in runner
    assert "APPROACH_ALIGNMENT_FAILURE" in runner
    assert "m1a_friction_trial_client.py" in runner
    friction_config = (root / "configs/m1a_friction_trials.yaml").read_text()
    assert "max_total_trials: 15" in friction_config and "THREE_APPROACH_ALIGNMENT_FAILURES_IN_ORIENTATION_RECOVERY" in runner
    assert "RUNTIME_EVIDENCE_MISSING" in runner and "FRICTION_TRIALS_BLOCKED_RUNTIME_EVIDENCE" in runner
    assert "orientation_recovery_configuration" in runner and "resume_prior_trial_count" in runner
    assert "M1A_S2_RECONCILE_ONLY" in runner and "noncanonical_preflight_sessions" in runner
    assert "M1A_S2_RUNTIME_BLOCKED_LOGS" in runner
    assert 'world_file:="$configured_world"' in runner
    assert "detachable_joint_used" in client
    assert "candidate_evaluations" in client
    assert "collision_checked_ik_solved" in client
    assert "preferred_candidate_id" in client and "ordered_viable" in client
    assert "PLANNING_SCENE_TABLE_PADDING_OR_GEOMETRY_UNVERIFIED" in client
    assert "gripper_frame_corridor_evidence" in client
    assert "contact_timeline" in client and "closed_gripper_width_m" in client
    assert "set_pose" not in client
    assert "orientation_candidate_summary" in runner


def test_production_table_orientation_family_keeps_tip_clearance_and_height_guard() -> None:
    root = Path(__file__).parents[2]
    protocol = yaml.safe_load((root / "configs/m1a_friction_trials.yaml").read_text())["grasp_orientation_families"]
    cube = [0.22, 0.12, 0.475]
    top_down = protocol["candidates"][0]
    candidate = candidate_pose(
        cube,
        top_down,
        table_top_z_m=protocol["table_top_z_m"],
        fingertip_table_clearance_m=protocol["fingertip_table_clearance_m"],
    )
    # Inline local finger +Z points down, and the physical link's distal endpoint is
    # exactly the configured 10 mm above the table rather than inside it.
    assert quaternion_rotate(candidate.orientation_xyzw, (0.0, 0.0, 1.0)) == pytest.approx((0.0, 0.0, -1.0))
    assert protocol["pregrasp_standoff_m"] == pytest.approx(0.10)
    fingertip = tuple(
        hand + offset
        for hand, offset in zip(
            candidate.position_xyz_m,
            quaternion_rotate(candidate.orientation_xyzw, (0.0, 0.0, 0.1122)),
        )
    )
    assert fingertip[2] == pytest.approx(0.460)
    assert candidate.fingertip_lowest_z_m == pytest.approx(0.460)
    # The 50 mm cube's centre lies in the measured contact plate span
    # (hand-frame +Z 58.4..112.2 mm), not on the old local-X board line.
    assert candidate.target_center_gripper_frame_m == pytest.approx((0.0, 0.0, 0.0972))
    side = protocol["candidates"][-1]
    assert candidate_is_eligible(cube, side, table_top_z_m=0.45) == (
        False,
        "TARGET_CENTER_BELOW_SIDE_GRASP_MINIMUM_HEIGHT",
    )


def test_grasp_corridor_is_in_panda_hand_frame_not_a_world_vertical_heuristic() -> None:
    identity = gripper_frame_corridor(
        [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0853]
    )
    assert identity["coordinate_frame"] == "panda_hand"
    assert identity["target_in_grasp_corridor"] is True
    rotated_quaternion = [0.0, 2**-0.5, 0.0, 2**-0.5]
    rotated_cube = quaternion_rotate(rotated_quaternion, (0.0, 0.0, 0.0853))
    rotated = gripper_frame_corridor([0.0, 0.0, 0.0], rotated_quaternion, rotated_cube)
    assert rotated["target_in_grasp_corridor"] is True
    selected_cross_section = gripper_frame_corridor(
        [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0972],
        finger_center_line_anchor_m=[0.0, 0.0, 0.0972],
    )
    assert selected_cross_section["target_in_grasp_corridor"] is True
    source = (Path(__file__).parents[2] / "scripts/m1a_contact_gated_trial_client.py").read_text()
    assert "gripper_frame_corridor_evidence" in source
    assert 'maximum_transverse_error_m=float(protocol["gripper_frame_corridor_max_transverse_error_m"])' in source


def test_m1a_s3_attach_is_runtime_gated_and_transport_keeps_a_carried_collision_object() -> None:
    root = Path(__file__).parents[2]
    runner = (root / "scripts/run_contact_gated_grasp.sh").read_text()
    remote_runner = (root / "scripts/run_m1a_s3_remote_episode.sh").read_text()
    source = (root / "scripts/m1a_contact_gated_trial_client.py").read_text()
    calibration_client = (root / "scripts/m1a_contact_calibration_client.py").read_text()
    assert "M1A_S3 episode range must be a non-empty subset of 1..10" in runner
    assert "M1A_S3_UNKNOWN_PREFERRED_CANDIDATE" in runner
    assert '"preferred_candidate_id": data["preferred_candidate_id"]' in runner
    assert "M1A_S3_CLOSE_COMMAND_PER_FINGER_M must be within [0.0, 0.04]" in runner
    # ADR-0016b: re-tuned from 0.033 to 0.027 for the franka pad geometry
    # (0.033 left the 6.5 mm-proud pads ~1.5 mm short of the 50 mm cube).
    assert 'CLOSE_COMMAND_PER_FINGER_M="${M1A_S3_CLOSE_COMMAND_PER_FINGER_M:-0.027}"' in runner
    assert "calibration_mode:=false" in remote_runner
    assert "M1A_S3_LAUNCH_URDF_SHA256" in remote_runner
    assert "install/xh_sim/share/xh_sim/urdf/panda_controlled.urdf" in remote_runner
    assert "evaluate_contact_gate" in source
    assert "symmetric_contact_stall_goal_tolerance_m" in source
    assert '"close_controller_target_reference_seen": close.get("controller_target_reference_seen")' in source
    assert 'constraint_command(DETACH_TOPIC, "detached")' in source
    main = source[source.index("def main()") :]
    assert main.index('constraint_command(DETACH_TOPIC, "detached")') < main.index("cube = runtime_cube_pose()")
    assert "if gate_passed:" in source
    assert 'approach.get("executed") and approach.get("converged")' in source
    assert 'client.set_dynamic_target_reference(cube["xyz"])' in source
    assert '"cube_pose_before_close": (' in source
    assert 'constraint_command(ATTACH_TOPIC, "attached")' in source
    assert source.index("if gate_passed:") < source.index('constraint_command(ATTACH_TOPIC, "attached")')
    assert "CONTACT_GATE_REJECTED" in runner
    assert "set_pose" not in source and "set_model" not in source
    assert "HAND_FK_UNAVAILABLE" in source
    assert "Gazebo /clock paired with Pose_V dynamic_pose bridge" in source
    assert 'client.set_dynamic_target_reference(cube["xyz"])' in source
    assert "POST_CLOSE_DYNAMIC_TARGET_POSE_UNAVAILABLE" in source
    assert "after_sim_timestamp_s=close_completed_sim_s" in source
    assert "and bool(speed.get(\"valid\"))" in source
    assert "attach_cube_scene" in calibration_client
    assert "MOVEIT_ATTACHED_COLLISION_OBJECT" in calibration_client
    assert "detach_cube_scene" in calibration_client
    friction_client = (root / "scripts/m1a_friction_trial_client.py").read_text()
    assert "PREGRASP_CONTROLLER_DID_NOT_CONVERGE" in friction_client
    assert "APPROACH_CONTROLLER_DID_NOT_CONVERGE" in friction_client
    assert "pregrasp_standoff_m" in friction_client


def test_m1a_hand_probe_isolated_from_object_contact_and_enforces_mimic_contract() -> None:
    root = Path(__file__).parents[2]
    client = (root / "scripts/m1a_hand_actuation_probe.py").read_text()
    runner = (root / "scripts/run_m1a_hand_actuation_probe.sh").read_text()
    remote_runner = (root / "scripts/run_m1a_hand_actuation_probe_remote.sh").read_text()
    assert '"scope": "HOME_POSE_NO_ARM_MOTION_NO_OBJECT_CONTACT"' in client
    assert "symmetric_q2_master_close" in client and "asymmetric_rejected" in client
    assert "all_channels_reached_command" in client
    assert "physical_command_emitted" in client
    assert "ASYMMETRIC_MIMIC_COMMAND_REJECTED" in client
    assert "before_link_poses_world_xyz_rpy" in client
    assert "contact_observation" in client
    assert "HAND_MIMIC_Q2_MASTER_VERIFIED" in client
    assert "passive_initial_state" in client
    assert "PASSIVE_INITIAL_TOLERANCE_M = 0.001" in client
    assert "calibration_mode:=false" in remote_runner
    assert "M1A_HAND_PROBE_LAUNCH_URDF_SHA256" in remote_runner
    assert "M1A_HAND_PROBE_GENERATED_SDF_MANIFEST" in remote_runner
    assert "XH_SIM_GENERATED_SDF_DIR" in remote_runner
    assert "HAND_ACTUATION_PROBE_BLOCKED" in runner
    assert "M1A_HAND_PROBE_REPORT_STEM" in runner
    assert "M1A_HAND_PROBE_EXPERIMENT_LABEL" in runner
    assert "S3_HAND_ACTUATION_CHANNELS_NOT_VERIFIED" in (
        root / "scripts/run_contact_gated_grasp.sh"
    ).read_text()
    reconciliation = (root / "scripts/reconcile_m1a_hand_actuation_gate.py").read_text()
    assert "CONTACT_TELEMETRY_PARTIAL" in reconciliation
    assert "HAND_ACTUATION_CHANNELS_NOT_VERIFIED" in reconciliation


def test_adr_0008_adapter_is_fail_closed_and_keeps_one_physical_master() -> None:
    root = Path(__file__).parents[2]
    adr = (root / "docs/decisions/ADR-0008-panda-mimic-compatibility-adapter.md").read_text()
    adapter = (root / "robot_ws/src/xh_sim/scripts/panda_hand_mimic_adapter.py").read_text()
    launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    controllers = (root / "robot_ws/src/xh_sim/config/panda_controllers.yaml").read_text()
    cmake = (root / "robot_ws/src/xh_sim/CMakeLists.txt").read_text()
    assert "Status: **ACCEPTED" in adr
    assert "PANDA_MIMIC_Q2_MASTER" in adr
    assert "SDF mimic / interface visibility audit" in adr
    assert "panda_hand_physical_controller" in controllers
    assert controllers.count("panda_finger_joint1") == 0
    assert "panda_finger_joint2" in controllers
    assert "panda_hand_mimic_adapter.py" in cmake and "panda_hand_mimic_adapter.py" in launch
    assert 'PUBLIC_ACTION = "/panda_hand_controller/follow_joint_trajectory"' in adapter
    assert 'PHYSICAL_ACTION = "/panda_hand_physical_controller/follow_joint_trajectory"' in adapter
    assert 'PHYSICAL_JOINT = "panda_finger_joint2"' in adapter
    assert "MAX_ASYMMETRY_M = 0.001" in adapter
    assert "ASYMMETRIC_MIMIC_COMMAND_REJECTED" in adapter
    assert "MALFORMED_PUBLIC_JOINT_ORDER_OR_SET" in adapter
    assert "MULTI_POINT_TRAJECTORY_UNDEFINED" in adapter
    assert "FollowJointTrajectory.Result.INVALID_GOAL" in adapter
    assert "physical_command_emitted" in adapter
    assert "gz model" not in adapter and "set_pose" not in adapter and "set_joint" not in adapter
    physical_audit = (root / "scripts/run_m1a_hand_mimic_physical_audit.sh").read_text()
    bullet_audit = (root / "scripts/run_m1a_bullet_capability_audit.sh").read_text()
    s0_runner = (root / "scripts/run_contact_calibration.sh").read_text()
    assert "M1A_HAND_MIMIC_PHYSICAL_CONSTRAINT_DECLINED" in physical_audit
    assert "HAND_MIMIC_PHYSICAL_CONSTRAINT_VERIFIED" in physical_audit
    assert "GATE1:" in bullet_audit and "GATE2:" in bullet_audit and "GATE3:" in bullet_audit
    assert "GATE4:" in bullet_audit and "GATE5:" in bullet_audit
    assert 'contacts.get("target_cube_events", 0) > 0' in bullet_audit
    assert 'event_counts", {}).get("cube", 0) > 0' not in bullet_audit
    assert 'invoke("/xh/p0/red_cube/detach","detached")' in bullet_audit
    assert "attached_relative_drift_m" in bullet_audit
    assert "detached_relative_change_m" in bullet_audit
    assert '"attached_follow"' in bullet_audit and '"detached_decoupled"' in bullet_audit
    assert "M1A_BULLET_CAPABILITY_VERIFIED" in (root / "scripts/summarize_m1a_bullet_capability_audit.py").read_text()
    assert "NOT_EVALUATED_AFTER_PRECEDING_GATE_FAILURE" in bullet_audit
    assert "< /dev/null" not in bullet_audit
    assert "</dev/null" in bullet_audit
    bullet_summary = (root / "scripts/summarize_m1a_bullet_capability_audit.py").read_text()
    assert "M1A_BULLET_CAPABILITY_BLOCKED" in bullet_summary
    assert 'contacts.get("target_cube_events", 0) > 0' in bullet_summary
    assert "SetMimicConstraintFeature" in bullet_summary
    assert "bullet_plugin_interface_count" in bullet_summary
    assert "CONTACT_TELEMETRY_BLOCKED_BULLET_CAPABILITY_AUDIT" in s0_runner
    assert "local_generator_sha" in s0_runner
    assert 'bullet.get("gates", {}).get("physical_mimic") is True' in s0_runner
    assert "DART-era static log check is historical evidence" in s0_runner
    assert "M1A_S0_TRIAL:" in s0_runner
    assert "fresh_simulation_session" in s0_runner
    calibration_client = (root / "scripts/m1a_contact_calibration_client.py").read_text()
    assert "object_red_cube_bilateral" in calibration_client
    assert '["timeout", "1.5", "gz", "model", "-m", model]' in calibration_client


def test_adr_0009_bullet_spawn_representation_is_gated_before_s0() -> None:
    root = Path(__file__).parents[2]
    adr = (root / "docs/decisions/ADR-0009-physics-engine-for-sdf-mimic.md").read_text()
    world = (root / "robot_ws/src/xh_sim/worlds/p0_pick_place.sdf").read_text()
    calibration_world = (root / "robot_ws/src/xh_sim/worlds/m1a_contact_calibration.sdf").read_text()
    launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    generator = (root / "robot_ws/src/xh_sim/scripts/generate_panda_spawn_sdf.py").read_text()
    assert "Status: **ACCEPTED" in adr
    assert "gz-physics7-bullet-featherstone-plugin" in adr
    assert "SetMimicConstraintFeature" in adr
    assert "gz sdf -p" in adr
    assert "ros_gz_sim create -file" in adr
    assert "not evidence that the constraint works" in adr
    assert "five independent, fail-closed" in adr
    assert "gz-physics-bullet-featherstone-plugin" in world
    assert "gz-physics-bullet-featherstone-plugin" in calibration_world
    assert '"-file", str(generated_sdf)' in launch
    assert '"-topic", "robot_description"' not in launch
    assert "SDF whitelist diff contains a semantic delta beyond the injected mimic" in generator
    assert "verify_zero_transforms" in generator
    assert "verify_collisions" in generator
    assert "verify_sensors" in generator
    assert "BULLET_SDF_MIMIC_MULTIPLIER = 1.0" in generator
    assert "SEMANTIC_MIMIC_MULTIPLIER = 1.0" in generator
    assert "Rejected Bullet compensation probes" in generator
    assert "valid for multiplier-sign inference" in adr
    assert "approved Bullet opposed-axis compensation probe" in adr
    urdf = (root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_text()
    assert '<joint name="panda_finger_joint1"><param name="mimic">' not in urdf
    assert '<joint name="panda_finger_joint1"><param name="multiplier">' not in urdf
    assert "verify_ros2_control_contract" in generator
    assert "q1 ros2_control must remain state-only" in generator
    assert "q1 ros2_control must explicitly opt out" in generator
    bullet_audit = (root / "scripts/run_m1a_bullet_capability_audit.sh").read_text()
    assert 'local payload_file="$gate_tmp/${marker}.json"' in bullet_audit
    assert 'python3 - "$marker" "$payload_file"' in bullet_audit
    assert 'required = ("initial_detach", "attach", "attached_follow", "detach", "detached_decoupled")' in bullet_audit
    assert "must explicitly detach and observe `detached` before it may attach" in urdf


def test_m1a_s4_runs_a_fresh_oracle_batch_instead_of_relabelling_s1() -> None:
    root = Path(__file__).parents[2]
    source = (root / "scripts/run_b1_oracle_gate.sh").read_text()
    assert 'bash scripts/run_contact_gated_grasp.sh' in source
    assert 'M1A_S3_RUN_ID="$RUN_ID"' in source
    assert '"B1_ORACLE_EXECUTION_VERIFIED"' in source
    assert '"B1_GROUND_TRUTH_POSE_BASELINE"' in source
    assert 'trials == 10' in source
    assert 'successes >= 8' in source
    assert 'direct_object_pose_write") is False' in source
    assert "oracle_pose_in_observation" in source


def test_m1a_status_writer_uses_current_stage_counts_and_dirty_diff() -> None:
    root = Path(__file__).parents[2]
    source = (root / "scripts/write_m1a_status.py").read_text()
    assert '"motion_trials": s1["motion_trials"]' in source
    assert '"frictional_trials": s2["frictional_trials"]' in source
    assert '"working_tree_dirty": bool(changed_files)' in source
    assert "current_model_urdf_sha256" in source
    assert "bullet_capability_audit_status" in source
    assert "bullet_capability_audit_generator_match" in source
    assert "bullet_counterfactual_status" in source
    assert "bullet_static_actuation_audit_status" in source
    assert 'bullet_capability.get("gates", {}).get("physical_mimic") is True' in source
    assert "BULLET_CAPABILITY_AUDIT_NOT_VERIFIED" in source
    assert '"READY_FOR_M1B": status == "PASS"' in source
    assert '"episode_ids": b1_episode_ids' in source
    assert '"seeds": b1_seeds' in source
    assert "attached_cube_table_exception" in source


def test_m1a_runtime_acm_preserves_only_documented_exceptions() -> None:
    root = Path(__file__).parents[2]
    srdf_root = ET.parse(root / "robot_ws/src/xh_sim/config/m1a_panda.srdf").getroot()
    srdf_pairs = {
        (item.attrib["link1"], item.attrib["link2"])
        for item in srdf_root.findall("disable_collisions")
    }
    source = (root / "scripts/m1a_moveit_execution_client.py").read_text()
    tree = ast.parse(source)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"ADJACENT_SELF_PAIRS", "REQUIRED_CHECKED_PAIRS"}
    }
    assert set(assignments["ADJACENT_SELF_PAIRS"]) == srdf_pairs
    checked = set(assignments["REQUIRED_CHECKED_PAIRS"])
    assert ("panda_leftfinger", "object_red_cube") in checked
    assert ("panda_rightfinger", "object_red_cube") in checked
    assert ("panda_link1", "work_table") in checked
    assert not checked & srdf_pairs


def test_adr_0006_fk_sampling_keeps_end_effector_and_protocol_invariants() -> None:
    root = Path(__file__).parents[2]
    script_path = root / "scripts/sample_panda_fk_workspace.py"
    specification = importlib.util.spec_from_file_location("sample_panda_fk_workspace", script_path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    model = module.load_model(root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf")
    scale = module.candidate_scale(model, 0.85)
    assert module.ARM_JOINTS == tuple(f"panda_joint{index}" for index in range(1, 8))
    assert 0 < scale < 1
    assert module.serial_translation_m(model) == pytest.approx(1.3192623327153459)
    # ADR-0016 §4 franka-copy fallback: finger roots at the official 0.0584 m
    # and the first collision element is the full-length grasp plate whose
    # centre sits at (0, +/-0.0039, 0.0269), giving 0.0584 + 0.02718 extension.
    assert module.fixed_end_effector_extension_m(model) == pytest.approx(0.08558124353299532)
    report = module.sample_workspace(model, samples=100, seed=7, target_total_reach_m=0.85)
    candidate = report["candidate_definition"]
    assert candidate["scaled_transforms"] == [*module.ARM_JOINTS, "panda_joint8", module.HAND_JOINT]
    assert candidate["unchanged_transforms"] == ["world_to_panda", *module.FINGER_JOINTS, *module.FINGER_LINKS]
    assert report["sampling"]["fingertip_points_per_model"] == 200


def test_adr_0006_approved_model_is_bound_to_fk_evidence_and_home_gate() -> None:
    root = Path(__file__).parents[2]
    adr = (root / "docs/decisions/ADR-0006-panda-link-proportion-unification.md").read_text()
    report = json.loads((root / "reports/m1a-fk-workspace-sampling.json").read_text())
    assert "ACCEPTED" in adr
    assert "100,000" in adr
    assert "CONTACT_TELEMETRY_PARTIAL" in adr
    assert report["status"] == "APPROVED_MODEL_OFFLINE_FK_EVIDENCE_PENDING_HOME_SELF_COLLISION_GATE"
    assert report["sampling"]["arm_joint_samples"] == 100_000
    official = report["candidate_official_panda_origins"]
    assert official["source"]["sha256"] == (
        "c8ee3bad4d89ad9bf4af717037418a3e6b046d47df6375a92a912a901d256a34"
    )
    assert official["metrics"]["position_only_refinement"]["final_target_distance_m"] < 1e-5
    assert report["bin_place_target_evidence"]["current_controlled_urdf"]["position_only_refinement"]["final_target_distance_m"] < 1e-5
    assert report["blocker"] == "HOME_SELF_COLLISION_GATE_REQUIRED_BEFORE_S0"
    assert report["approval_record"]["bin_a_xyz_m"] == pytest.approx([0.217366447885, -0.249990627453, 0.45])
    # ADR-0008 changed the physical hand after this offline ADR-0006 evidence.
    # The historical hash stays bound to that report; a current home/S0/S1
    # rerun is mandatory and must not be silently relabelled as old evidence.
    assert report["urdf_sha256"] == "2f77f5150f4e4a5a098ab59a56f98216622cfdfd54a0c79dedbe44e19352eff1"
    assert report["urdf_sha256"] != hashlib.sha256(
        (root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_bytes()
    ).hexdigest()


def test_approved_model_keeps_actuation_protocol_and_gates_s0_on_home_collision_check() -> None:
    root = Path(__file__).parents[2]
    urdf = (root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_text()
    srdf = (root / "robot_ws/src/xh_sim/config/m1a_panda.srdf").read_text()
    policy = yaml.safe_load((root / "robot_ws/src/xh_sim/config/m1a_collision_policy.yaml").read_text())
    home_client = (root / "scripts/m1a_home_self_collision_client.py").read_text()
    s0_runner = (root / "scripts/run_contact_calibration.sh").read_text()
    assert 'joint name="panda_joint8" type="fixed"' in urdf
    assert '<parent link="panda_link7"/><child link="panda_link8"/>' in urdf
    assert '<parent link="panda_link8"/><child link="panda_hand"/>' in urdf
    assert '<origin xyz="0 0 0.333" rpy="0 0 0"/>' in urdf
    assert '<origin xyz="0 -0.316 0" rpy="1.57079632679 0 0"/>' in urdf
    assert 'origin xyz="0.000087 -0.037090 -0.068515"' in urdf
    assert 'box size="0.110148 0.184565 0.246977"' in urdf
    assert urdf.count("package://moveit_resources_panda_description/meshes/collision/") == 2
    package_xml = (root / "robot_ws/src/xh_sim/package.xml").read_text()
    assert "<exec_depend>moveit_resources_panda_description</exec_depend>" in package_xml
    assert 'origin xyz="-0.041234 0.034430 0.027923"' in urdf
    assert 'box size="0.192746 0.179159 0.166259"' in urdf
    assert '<disable_collisions link1="panda_link7" link2="panda_link8"' in srdf
    assert '<disable_collisions link1="panda_link8" link2="panda_hand"' in srdf
    home = ET.fromstring(srdf).find("group_state[@name='home']")
    assert home is not None
    home_positions = [float(item.attrib["value"]) for item in home.findall("joint")]
    assert home_positions == pytest.approx([0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0])
    assert "HOME_ARM_POSITIONS = [0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0]" in home_client
    for name, value in zip((f"panda_joint{index}" for index in range(1, 8)), home_positions):
        joint = ET.fromstring(urdf).find(f"ros2_control/joint[@name='{name}']")
        assert joint is not None
        initial = joint.find("state_interface[@name='position']/param[@name='initial_value']")
        assert initial is not None and float(initial.text) == pytest.approx(value)
    assert ("panda_link8", "work_table") in {
        tuple(pair) for pair in policy["enabled_robot_world_collision_pairs"]
    }
    assert '"/check_state_validity"' in home_client
    assert "MOVEIT_CHECK_STATE_VALIDITY_NO_MOTION_COMMAND" in home_client
    home_runner = (root / "scripts/run_m1a_home_self_collision_check.sh").read_text()
    assert "HOME_SELF_COLLISION_GATE_NOT_SATISFIED" in home_runner
    assert "run_isolated_contact_calibration.sh" in home_runner
    assert "HOME_SELF_COLLISION_VERIFIED" in s0_runner
    assert "CONTACT_TELEMETRY_BLOCKED_HOME_SELF_COLLISION_GATE" in s0_runner
    assert "M1A_S0_LAUNCH_PGID" in s0_runner
    assert "trap cleanup EXIT HUP INT TERM" in s0_runner
    s1_runner = (root / "scripts/run_moveit_execution_gate.sh").read_text()
    assert '"CONTACT_TELEMETRY_PARTIAL", "CONTACT_TELEMETRY_CALIBRATED"' in s1_runner
    assert "BLOCKED_S0_RUNTIME_EVIDENCE_REQUIRED" in s1_runner
    assert "M1A_S1_LAUNCH_PGID" in s1_runner
    assert "PASS_EXACT_MATCH_TO_ADJACENT_SELF_PAIRS" in s1_runner
    s1_report = json.loads((root / "reports/m1a-motion-execution.json").read_text())
    assert s1_report["adjacent_self_pairs_audit"] == "PASS_EXACT_MATCH_TO_ADJACENT_SELF_PAIRS"
    assert s1_report["srdf_adjacent_self_pairs"] == s1_report["adjacent_self_pairs_expected"]
    assert ["panda_leftfinger", "object_red_cube"] in s1_report["enabled_collision_pairs"]
    controller_config = (root / "robot_ws/src/xh_sim/config/panda_controllers.yaml").read_text()
    moveit_config = (root / "robot_ws/src/xh_sim/config/m1a_moveit_controllers.yaml").read_text()
    world = (root / "robot_ws/src/xh_sim/worlds/p0_pick_place.sdf").read_text()
    execution_client = (root / "scripts/m1a_moveit_execution_client.py").read_text()
    assert "panda_joint8" not in controller_config and "panda_joint8" not in moveit_config
    assert '<pose>0.217366447885 -0.249990627453 0.45 0 0 0</pose>' in world
    assert '<pose>0.40 0.28 0.49 0 0 0</pose>' in world
    assert '<size>0.30 0.30 0.02</size>' in world
    assert '[0.30, 0.30, 0.10], [0.217366447885, -0.249990627453, 0.50]' in execution_client
    assert "gz-physics-bullet-featherstone-plugin" in world
