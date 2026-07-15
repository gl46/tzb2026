from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from xh_agent.baselines.b1 import MockPlanningBackend, run_b1
from xh_agent.diagnostics.doctor import remote_doctor
from xh_agent.skills.failure_injection import FailureInjectionConfig, FailureMode
from test_contracts import task


ROOT = Path(__file__).parents[2]


def test_failure_config_covers_all_required_modes() -> None:
    expected = {"grasp_pose_offset", "gripper_width_mismatch", "low_friction_slip", "obstacle_insertion", "object_occlusion", "release_delay", "target_moved_during_execution"}
    assert {mode.value for mode in FailureMode} == expected
    assert FailureInjectionConfig(mode=FailureMode.LOW_FRICTION_SLIP, enabled=True).enabled


def test_p0_scene_contract_has_props_bin_and_rgbd_sensor() -> None:
    world = ROOT / "robot_ws/src/xh_sim/worlds/p0_pick_place.sdf"
    root = ET.parse(world).getroot()
    names = {element.attrib["name"] for element in root.findall(".//model")}
    assert {"work_table", "panda_p0_stub", "object_red_cube", "object_blue_cylinder", "object_green_sphere", "bin_a"} <= names
    bin_model = root.find(".//model[@name='bin_a']")
    assert bin_model is not None and len(bin_model.findall(".//collision")) >= 5
    sensor = root.find(".//sensor[@name='front_rgbd']")
    assert sensor is not None and sensor.attrib["type"] == "rgbd_camera"
    launch_source = (ROOT / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text(encoding="utf-8")
    assert "ros_gz_sim" in launch_source and "IncludeLaunchDescription" in launch_source


def test_controller_backed_panda_contract_has_all_controlled_joints() -> None:
    urdf = ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
    root = ET.parse(urdf).getroot()
    control = root.find("ros2_control")
    assert control is not None
    assert control.findtext("./hardware/plugin") == "gz_ros2_control/GazeboSimSystem"
    controlled = {joint.attrib["name"] for joint in control.findall("joint")}
    assert {f"panda_joint{index}" for index in range(1, 8)} <= controlled
    assert {"panda_finger_joint1", "panda_finger_joint2"} <= controlled
    config = yaml.safe_load((ROOT / "robot_ws/src/xh_sim/config/panda_controllers.yaml").read_text())
    manager = config["controller_manager"]["ros__parameters"]
    assert manager["panda_arm_controller"]["type"] == "joint_trajectory_controller/JointTrajectoryController"
    assert manager["panda_hand_controller"]["type"] == "joint_trajectory_controller/JointTrajectoryController"


def test_constrained_pick_place_runner_labels_its_grasp_mode() -> None:
    runner = (ROOT / "scripts/run_constrained_pick_place.sh").read_text()
    assert "GAZEBO_DETACHABLE_JOINT_CONSTRAINT" in runner
    assert "finger_contact_grasp_verified\": False" in runner
    assert "object_inside_bin_after_settle" in runner


def test_constrained_episode_recorder_preserves_truth_boundary() -> None:
    recorder = (ROOT / "scripts/record_constrained_transfer_episode.py").read_text()
    assert "object_tracks=[]" in recorder
    assert "SimulatorSupervisionV0" in recorder
    assert "GAZEBO_DETACHABLE_JOINT_CONSTRAINT" in recorder


def test_empty_grasp_failure_batch_is_bounded_and_counts_twenty_runs() -> None:
    runner = (ROOT / "scripts/run_empty_grasp_failure_batch.sh").read_text()
    assert "seq 1 20" in runner
    assert "VERIFIED_20_EMPTY_GRASP_FAILURE_TRAJECTORIES" in runner
    assert "gz topic -t /xh/p0/red_cube/attach" not in runner


def test_completion_audit_checks_two_actual_failure_modes() -> None:
    audit = (ROOT / "scripts/audit_m0_completion.py").read_text()
    assert "twenty_actual_failures" in audit
    assert "second_actual_failure" in audit




def test_b1_reports_backend_blocked_instead_of_success() -> None:
    result = run_b1(task(), MockPlanningBackend())
    assert result.status == "BLOCKED"
    assert result.recovery_skill is not None


def test_b1_default_is_a_runnable_deterministic_interface_baseline() -> None:
    result = run_b1(task())
    assert result.status == "READY"
    assert len(result.skills) == 6


def test_remote_not_configured_and_smoke_script_are_safe() -> None:
    assert remote_doctor(None, None)["items"]["ssh"]["status"] == "NOT_APPLICABLE"
    source = (ROOT / "scripts/run_sim_smoke_test.sh").read_text(encoding="utf-8")
    assert "timeout" in source and "trap cleanup" in source and "setsid" in source
    moveit_source = (ROOT / "scripts/run_moveit_planning_smoke.sh").read_text(encoding="utf-8")
    assert "plan_kinematic_path" in moveit_source and "setsid" in moveit_source


def test_download_is_dry_run_and_no_token_output() -> None:
    completed = subprocess.run(["bash", "scripts/download_teacher_candidate.sh", "nvidia/Cosmos3-Nano"], cwd=ROOT,
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert "DRY_RUN" in completed.stdout
    assert "token" not in (completed.stdout + completed.stderr).lower()
