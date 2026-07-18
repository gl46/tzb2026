from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xh_agent.agent.closed_loop import record_step
from xh_agent.agent.skill_planner import plan
from xh_agent.grasp.m1b_broker import M1BContactBroker, width_window_from_perceived_diameter
from xh_agent.grasp.hand_preflight import M1BHandPreflightV1, evaluate_hand_preflight
from xh_agent.grasp.post_grasp import evaluate_post_grasp_identity, evaluator_supervision_record
from xh_agent.grasp.reset import M1BResetVerificationV1, validate_reset_records
from xh_agent.recovery.manager import recovery_for
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1
from xh_agent.task_compiler.deterministic import DeterministicTaskCompiler


@pytest.mark.parametrize("instruction,selector,destination", [
    ("把最左边的红色零件放进蓝色料箱。", "minimum_world_x_in_camera_calibrated_table_frame", "blue_bin"),
    ("把倒放的圆柱以正常姿态放入第二排第三格。", "orientation_inverted", "blue_bin_row_2_col_3"),
    ("优先把零件最多区域的零件装箱。", "argmax_region_track_count_then_leftmost", "blue_bin"),
])
def test_deterministic_compiler_supports_required_instructions(instruction: str, selector: str, destination: str) -> None:
    task = DeterministicTaskCompiler().compile(instruction)
    assert task.target_selector == selector
    assert task.destination == destination
    assert task.need_clarification is False
    assert "actual_sim_entity_id" not in task.model_dump_json()


def test_unknown_instruction_requests_clarification() -> None:
    task = DeterministicTaskCompiler().compile("随便放一个进去")
    assert task.need_clarification is True
    assert plan(task) == ["Observe", "AskClarification"]


def test_step_requires_a_fresh_observation_and_compares_expected_actual() -> None:
    step = record_step(step_id=1, skill="Approach", before_id="obs-1", before_timestamp_ns=1, after_id="obs-2", after_timestamp_ns=2, actual={"target_visible": True, "collision_free": True}, command_ref="trajectory://approach")
    assert step.comparison == "SUCCESS"
    with pytest.raises(ValidationError):
        step.model_copy(update={"observation_after_id": "obs-1"}).model_validate(step.model_copy(update={"observation_after_id": "obs-1"}).model_dump())


@pytest.mark.parametrize("failure_type", ["EMPTY_GRASP", "WRONG_OBJECT", "UNSTABLE_OR_WRONG_PLACEMENT", "RELEASE_FAILURE"])
def test_recovery_changes_parameters_and_has_bounded_retry(failure_type: str) -> None:
    recovery = recovery_for(failure_type)
    assert recovery.changed_parameters
    assert recovery.retry_budget == 2
    assert "cleanup" not in " ".join(recovery.recovery_subgoals).lower()


def test_m1b_broker_selects_only_same_entity_and_hides_it_from_public_feedback() -> None:
    broker = M1BContactBroker()
    feedback, internal = broker.select(left_entities={"cylinder_02"}, right_entities={"cylinder_02", "cylinder_03"}, bilateral_overlap_s=0.100, consecutive_samples=3)
    assert feedback.grasp_success is True
    assert feedback.reobservation_required is True
    assert not hasattr(feedback, "actual_sim_entity_id")
    assert internal["attach_topic"] == "/xh/m1b/cylinder_02/attach"
    rejected, internal_rejected = broker.select(left_entities={"cylinder_01"}, right_entities={"cylinder_02"}, bilateral_overlap_s=0.100, consecutive_samples=3)
    assert rejected.grasp_success is False
    assert internal_rejected["actual_sim_entity_id"] is None
    early, _ = broker.select(left_entities={"cylinder_02"}, right_entities={"cylinder_02"}, bilateral_overlap_s=0.099, consecutive_samples=3)
    assert early.tactile_state == "bilateral_contact_window_incomplete"
    assert broker.cylinder_entities([("panda_leftfinger::collision", "cylinder_02::link::collision")]) == {"cylinder_02"}


def test_m1b_width_window_is_perception_derived_and_clamped() -> None:
    lower, upper = width_window_from_perceived_diameter(0.05)
    assert 0 <= lower < upper <= 0.08
    with pytest.raises(ValueError):
        width_window_from_perceived_diameter(0.2)


def test_m1b_static_camera_calibration_is_versioned_and_invertible() -> None:
    root = Path(__file__).parents[2]
    calibration = M1BStaticCameraCalibrationV1.from_file(root / "configs/m1b_camera_calibration.json")
    optical = (0.12, -0.08, 1.35)
    world = calibration.optical_to_world(optical)
    assert calibration.world_to_optical(world) == pytest.approx(optical)
    assert calibration.camera_optical_frame == "camera_fixture/camera_rgbd/front_rgbd"
    assert len(calibration.fingerprint) == 64
    tf_args = calibration.static_tf_arguments()
    assert "--frame-id" in tf_args and "world" in tf_args
    assert "--child-frame-id" in tf_args and calibration.camera_optical_frame in tf_args


def test_post_grasp_identity_routes_wrong_object_without_entity_leak() -> None:
    wrong = evaluate_post_grasp_identity(target_track_id="track-11111111", carried_track_id="track-22222222")
    assert wrong.identity_status == "WRONG_OBJECT"
    assert wrong.wrong_object_detected is True
    assert "actual_sim_entity_id" not in wrong.__dict__
    assert recovery_for("WRONG_OBJECT").recovery_subgoals[1] == "SafePlaceNonTarget"
    unobserved = evaluate_post_grasp_identity(target_track_id="track-11111111", carried_track_id=None)
    assert unobserved.reobservation_required is True
    supervision = evaluator_supervision_record(actual_sim_entity_id="cylinder_02", wrong_object=True)
    assert supervision["wrong_object"] is True


def test_m1b_reset_requires_every_generated_detachable_state() -> None:
    good = [
        M1BResetVerificationV1("cylinder_01", "/xh/m1b/cylinder_01/detach", "/xh/m1b/cylinder_01/grasp_state", True, ('data: "detached"',)),
        M1BResetVerificationV1("cylinder_02", "/xh/m1b/cylinder_02/detach", "/xh/m1b/cylinder_02/grasp_state", True, ('data: "detached"',)),
    ]
    assert validate_reset_records(good, ["cylinder_01", "cylinder_02"])[0] == "RESET_VERIFIED"
    missing = [*good[:-1], M1BResetVerificationV1("cylinder_02", "/xh/m1b/cylinder_02/detach", "/xh/m1b/cylinder_02/grasp_state", False, ())]
    status, reasons = validate_reset_records(missing, ["cylinder_01", "cylinder_02"])
    assert status == "INVALID_RESET"
    assert reasons == ("DETACH_STATE_UNOBSERVED:cylinder_02",)


def test_m1b_moveit_server_does_not_start_a_second_simulation() -> None:
    source = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/launch/m1b_moveit_server.launch.py").read_text()
    assert "simulation.launch.py" not in source.replace("``simulation.launch.py``", "")
    assert "moveit_ros_move_group" in source


def test_m1b_launch_has_paused_startup_contract_without_changing_default_m1a_run() -> None:
    source = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    assert 'DeclareLaunchArgument(\n            "start_paused"' in source
    assert "ADR-0014 requires this for M1B detach-first reset" in source
    assert "else '-r -s --headless-rendering '" in source


def test_m1b_hand_preflight_requires_physical_endpoint_feedback() -> None:
    good = M1BHandPreflightV1(True, True, 0.04, 0.04, 0.04)
    assert evaluate_hand_preflight(good)[0] == "HAND_PREFLIGHT_VERIFIED"
    stalled = M1BHandPreflightV1(True, False, 0.0023, -0.0007, 0.04)
    status, reasons = evaluate_hand_preflight(stalled)
    assert status == "HAND_ACTUATION_UNVERIFIED"
    assert {"HAND_CONTROLLER_NOT_SUCCEEDED", "LEFT_FINGER_ENDPOINT_ERROR", "RIGHT_FINGER_ENDPOINT_ERROR"} <= set(reasons)
