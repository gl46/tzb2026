from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

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
    expected_names = {f"panda_joint{index}" for index in range(1, 8)} | {
        "panda_finger_joint1", "panda_finger_joint2"
    }
    assert set(configured) == expected_names == set(limits)
    for name in expected_names:
        assert configured[name]["max_velocity"] == float(limits[name]["velocity"])
        assert configured[name]["has_velocity_limits"] is True
        assert configured[name]["has_acceleration_limits"] is True
        assert configured[name]["max_acceleration"] > 0
        assert "min_position" not in configured[name]
        assert "max_position" not in configured[name]
    source_urdf = root / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
    launch = (root / "robot_ws/src/xh_sim/launch/moveit_execution.launch.py").read_text()
    assert '.robot_description(file_path="urdf/panda_controlled.urdf")' in launch
    assert source_urdf.exists()
    simulation_launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    assert "re.sub" not in simulation_launch
    assert "<collision>.*?</collision>" not in simulation_launch
    assert "calibration_mode" in simulation_launch
    assert "gz-sim-detachable-joint-system" in simulation_launch
    assert "<position_proportional_gain>1.0</position_proportional_gain>" in source_urdf.read_text()
    # Finger pair, static grasp target and dynamic target-equivalent/table
    # control each have their own explicit Gazebo contact bridge.
    assert simulation_launch.count("ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts") == 4
    assert '"/xh/supervision/panda_leftfinger_contacts"' in simulation_launch
    assert '"/xh/supervision/panda_rightfinger_contacts"' in simulation_launch
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
    assert "current_acm()" in source
    assert 'set_allowed_pair(matrix, "panda_link0", "work_table", True)' in source
    assert "post_controller_converged" in source
    assert "consecutive_converged >= 5" in source
    assert "planned_by_name" in source
    assert "PLANNED_JOINT_SET_MISMATCH" in source
    assert "set_pose" not in source and "set_joint" not in source


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
    assert "set_target_touch_exception" in client
    assert "target_touch_exception_restored" in client
    assert '"left", -0.040, [0.010, 0.04]' in client
    assert '"right", 0.0, [0.04, 0.010]' in client
    assert '"bilateral", -0.030, [0.010, 0.010]' in client
    assert "calibration_retreat_pose" in client
    assert "semantic test is the commanded finger close" in client
    assert client.count('"plan_attempts": plan_attempts') >= 2
    assert 'trial.get("retreat", {}).get("executed")' in client
    assert "m1a_contact_calibration.sdf" in runner
    assert "calibration_mode:=true" in runner
    simulation_launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    moveit_launch = (root / "robot_ws/src/xh_sim/launch/moveit_execution.launch.py").read_text()
    assert 'LaunchConfiguration("world_file")' in simulation_launch
    assert 'LaunchConfiguration("world_file")' in moveit_launch
    assert "red_cube_environment_contacts" in simulation_launch
    assert "move_joint_target" in client and 'TARGETS[0][1]' in client


def test_m1a_rgbd_recorder_uses_real_bridged_camera_frames() -> None:
    root = Path(__file__).parents[2]
    recorder = (root / "scripts/record_m1a_rgbd_video.py").read_text()
    assert '"/xh/camera/rgbd/image"' in recorder
    assert "sensor_msgs.msg import Image" in recorder
    assert 'frame_{self.frames:05d}.ppm' in recorder
    assert "ffmpeg" in recorder


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
