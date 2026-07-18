from __future__ import annotations

import math
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from xh_agent.agent.closed_loop import record_step
from xh_agent.agent.skill_planner import plan
from xh_agent.grasp.m1b_broker import M1BContactBroker, width_window_from_perceived_diameter
from xh_agent.grasp.hand_preflight import M1BHandPreflightV1, evaluate_hand_preflight
from xh_agent.grasp.m1b_contact_window import M1BContactSampleV1, broker_from_window
from xh_agent.grasp.tolerance_envelope import OffsetTrialV1, perception_axis_audit, reachability_gate, tolerance_envelope
from evaluate_m1b_reachability_gate import actual_perception_errors, measured_tolerance_envelope
from xh_agent.grasp.post_grasp import evaluate_post_grasp_identity, evaluator_supervision_record
from xh_agent.grasp.reset import M1BResetVerificationV1, validate_reset_records
from xh_agent.recovery.manager import recovery_for
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1
from xh_agent.task_compiler.deterministic import DeterministicTaskCompiler

SCRIPTS = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from audit_m1b_center_reachability import percentile90, perceived_diameter_m  # noqa: E402
from generate_industrial_scenes import ROBOT_BASE_KEEP_OUT_RADIUS_M, ROBOT_BASE_XY, render  # noqa: E402
from summarize_m1b_tolerance_campaign import summarize  # noqa: E402
from xh_agent.perception.interfaces import BBoxV1, PerceptionResultV1  # noqa: E402


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


def test_m1b_camera_center_correction_uses_only_perceived_diameter() -> None:
    root = Path(__file__).parents[2]
    calibration = M1BStaticCameraCalibrationV1.from_file(root / "configs/m1b_camera_calibration.json")
    surface = (-0.25, 0.10, 1.30)
    center = calibration.visible_surface_to_center_world(surface, 0.05)
    assert center == pytest.approx(calibration.optical_to_world((-0.25, 0.10, 1.325)))
    with pytest.raises(ValueError):
        calibration.visible_surface_to_center_world(surface, 0.2)


def test_m1b_center_audit_uses_public_bbox_depth_and_nearest_rank_p90() -> None:
    prediction = PerceptionResultV1(
        frame_id="camera", timestamp_ns=1, track_id="track-1234abcd", category="industrial_cylinder",
        bbox_or_mask=BBoxV1(x=10, y=20, width=20, height=30), position_3d=[0.0, 0.0, 1.0],
        orientation_state="normal", confidence=0.9, visibility=0.9, source_components=["test"],
    )
    assert perceived_diameter_m(prediction, [1000.0, 0.0, 0.0, 0.0, 800.0, 0.0, 0.0, 0.0, 1.0]) == pytest.approx(0.025)
    assert percentile90([0.001, 0.002, 0.003, 0.004]) == pytest.approx(0.004)


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


def test_m1b_amendment_reset_gate_is_physical_and_fails_closed_on_missing_pose() -> None:
    source = (Path(__file__).parents[2] / "scripts/verify_m1b_reset_noncoupling.py").read_text()
    assert 'SETTLE_S = 2.0' in source
    assert 'MAX_OBJECT_DISPLACEMENT_M = 0.001' in source
    assert 'MIN_EE_DISPLACEMENT_M = 0.02' in source
    assert 'MAX_HOME_JOINT_ERROR_RAD = 0.10' in source
    assert 'HOME_JOG_JOINT_INDEX = 2' in source
    assert 'HOME_JOG_DELTA_RAD = -0.05' in source
    assert 'client.move_joint_target(jog_target)' in source
    assert 'def move_to_home_neighborhood(client: CalibrationClient, initial: dict[str, object])' in source
    assert 'client.move_joint_target(HOME_ARM_POSITIONS)' in source
    assert '"method": "S1_MOVEIT_PLANNED_EXECUTION"' in source
    assert 'def verify_live_home(client: CalibrationClient) -> dict[str, object]:' in source
    assert 'except subprocess.TimeoutExpired:' in source
    assert 'return None' in source
    assert 'final = {name: supervision_model_position(name) for name in names}' in source
    assert 'POSE_SNAPSHOT_ATTEMPTS = 3' in source
    assert 'POSE_QUERY_TIMEOUT_S = 5' in source
    assert 'if all(sample is not None for sample in final.values()):' in source
    assert 'def set_world_pause(world_name: str, paused: bool)' in source
    assert '"world_pause_controls"' in source
    assert 'parser.add_argument("--scene-supervision", required=True, type=Path)' in source
    assert 'apply_calibration_cylinder_scene(client, labels)' in source
    assert '"planner_cylinder_scene"' in source
    assert '"object_positions_before_m": before' in source
    assert '"object_positions_after_m": after' in source
    assert '"RESET_PHYSICAL_NONCOUPLING_VERIFIED" if passed else "INVALID_RESET"' in source
    assert '"online_truth_access": False' in source


def test_m1b_amendment_detach_does_not_wait_on_auxiliary_one_shot_state() -> None:
    source = (Path(__file__).parents[2] / "scripts/m1b_reset_detach.py").read_text()
    assert "auxiliary_grasp_state_not_waited_per_amendment_1" in source
    assert "the companion physical non-coupling verifier is the sole final reset" in source
    assert "def broadcast_detach_round(object_names: list[str], timeout_s: float)" in source
    assert '"post_resume_detach_round"' in source
    assert '"POST_RESUME_DETACH_PUBLISH_FAILED"' in source
    assert '"stderr": "timeout", "published": False' in source


def test_m1b_tolerance_attach_uses_detachablejoint_empty_payload() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_trial.py").read_text()
    assert '["gz", "topic", "-t", topic, "-m", "gz.msgs.Empty", "-p", ""]' in source
    assert '"-p", "unused: true"' not in source
    assert 'approach_motion_accepted = bool(approach.get("executed") and approach.get("converged"))' in source
    assert '"pregrasp_terminal_convergence_required": True' in source
    assert '"contact_descend_terminal_convergence_required": False' in source
    assert '"contact_descend_contact_authorization": "POST_CLOSE_BILATERAL_SAME_ENTITY_WINDOW"' in source
    assert 'M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M = 0.220' in source
    assert 'M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M = 0.065' in source
    assert 'M1B_NORMAL_SIDE_HAND_X_OFFSET_M = -0.080' in source
    assert 'M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M = 0.001' in source
    assert 'value.position.y = centre_world_m[1] + M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M' in source
    assert 'value.position.x = centre_world_m[0] + M1B_NORMAL_SIDE_HAND_X_OFFSET_M' in source
    assert 'def m1b_close_finger_targets_from_perceived_diameter(' in source
    assert 'width_window_from_perceived_diameter(perceived_diameter_m)' in source
    assert 'M1B_FINGER_BOARD_THICKNESS_M = 0.018' in source
    assert 'per_finger_target_m = (selected_inner_gap_m + M1B_FINGER_BOARD_THICKNESS_M) / 2.0' in source
    assert '"inner_pad_gap_window_m"' in source
    assert 'def public_track_from_evidence(' in source
    assert 'def capture_near_public_observation(' in source
    assert 'def select_near_public_track(' in source
    assert 'M1B_NEAR_REOBSERVATION_MAX_ASSOCIATION_DISTANCE_M = 0.050' in source
    assert 'M1B_NEAR_REOBSERVATION_FRAME_COUNT = 3' in source
    assert '"aggregation": "PER_AXIS_MEDIAN_OF_PUBLIC_RGBD_FRAMES"' in source
    assert '"track_id": str(initial_public_track["track_id"])' in source
    assert '"near_pregrasp_public_reobservation": near_reobservation' in source
    assert '"PUBLIC_NEAR_REOBSERVATION_GATE_REJECTED"' in source
    assert 'aperture_source.add_argument("--calibration-fixture-diameter-m", type=float' in source
    assert 'aperture_source.add_argument("--public-perception-evidence", type=Path' in source
    assert '"--enable-near-pregrasp-reobservation", action="store_true"' in source
    assert '"source": "CALIBRATION_FIXTURE_DECLARED_GEOMETRY"' in source
    assert '"baseline_perception_free": args.calibration_fixture_diameter_m is not None' in source
    assert 'CALIBRATION_SETTLE_S = 2.0' in source
    assert 'def calibration_live_model_center(entity_name: str)' in source
    assert 'time.sleep(CALIBRATION_SETTLE_S)' in source
    assert '"EVALUATOR_ONLY_GAZEBO_MODEL_POSE_AFTER_SETTLE"' in source
    assert 'HAND_FEEDBACK_READY_TIMEOUT_S = 12.0' in source
    assert 'def wait_for_finite_hand_feedback(client: CalibrationClient)' in source
    assert 'hand_feedback_ready = client.wait_calibration_ready() and wait_for_finite_hand_feedback(client)' in source
    assert '"evidence_sha256": hashlib.sha256(raw).hexdigest()' in source
    assert 'close = client.command_hand(close_targets)' in source
    assert '"source": "ACTUAL_PUBLIC_RGBD_GEOMETRIC_OUTPUT"' in source
    assert 'if contact_descend.get("executed"):' in source
    assert 'only the non-contact\n            # approach requires strict terminal convergence' in source
    assert 'contact_start_index = len(raw)' in source


def test_m1b_moveit_execution_waits_for_planned_trajectory() -> None:
    source = (Path(__file__).parents[2] / "scripts/m1a_moveit_execution_client.py").read_text()
    assert 'trajectory_duration_s = final_time.sec + final_time.nanosec * 1e-9' in source
    assert 'result_timeout_s = min(120.0, max(60.0, trajectory_duration_s + 30.0))' in source
    assert 'timeout_sec=result_timeout_s' in source


def test_m1b_generated_cylinders_clear_the_fixed_robot_base() -> None:
    template = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf").read_text()
    _, supervision = render(template, 1017, orientations=("normal",))
    for label in supervision["simulator_supervision"]["objects"]:
        x, y, _ = label["position_3d_world"]
        assert math.dist((x, y), ROBOT_BASE_XY) >= ROBOT_BASE_KEEP_OUT_RADIUS_M


def test_m1b_moveit_server_does_not_start_a_second_simulation() -> None:
    source = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/launch/m1b_moveit_server.launch.py").read_text()
    assert "simulation.launch.py" not in source.replace("``simulation.launch.py``", "")
    assert "moveit_ros_move_group" in source


def test_m1b_launch_has_paused_startup_contract_without_changing_default_m1a_run() -> None:
    source = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    assert 'DeclareLaunchArgument(\n            "start_paused"' in source
    assert "ADR-0014 requires this for M1B detach-first reset" in source
    assert "else '-r -s --headless-rendering '" in source
    reset = (Path(__file__).parents[2] / "scripts/m1b_reset_detach.py").read_text()
    assert "--activate-controllers requires --resume-world" in reset
    assert "CONTROLLER_ACTIVATION_FAILED" in reset
    assert "source /opt/ros/jazzy/setup.bash" in reset
    assert "ros2 control switch_controllers" in reset
    assert "for attempt in range(1, 4)" in reset
    assert "CONTROLLERS_ALREADY_ACTIVE" in reset
    assert "WORLD_CONTROL_TIMEOUT_MS = 10000" in reset


def test_m1b_hand_preflight_requires_physical_endpoint_feedback() -> None:
    good = M1BHandPreflightV1(True, True, 0.04, 0.04, 0.04)
    assert evaluate_hand_preflight(good)[0] == "HAND_PREFLIGHT_VERIFIED"
    stalled = M1BHandPreflightV1(True, False, 0.0023, -0.0007, 0.04)
    status, reasons = evaluate_hand_preflight(stalled)
    assert status == "HAND_ACTUATION_UNVERIFIED"
    assert {"HAND_CONTROLLER_NOT_SUCCEEDED", "LEFT_FINGER_ENDPOINT_ERROR", "RIGHT_FINGER_ENDPOINT_ERROR"} <= set(reasons)


def test_m1b_contact_window_requires_matched_same_entity_samples() -> None:
    samples = [
        M1BContactSampleV1(time, finger, ((f"panda_{finger}finger::collision", "cylinder_02::link::collision"),))
        for time in (1.0, 1.05, 1.10)
        for finger in ("left", "right")
    ]
    feedback, internal = broker_from_window(samples)
    assert feedback.grasp_success is True
    assert internal["attach_topic"] == "/xh/m1b/cylinder_02/attach"
    early, _ = broker_from_window(samples[:-2])
    assert early.grasp_success is False


def test_m1b_contact_window_accepts_bounded_stamp_jitter_but_not_stale_contacts() -> None:
    jittered = [
        M1BContactSampleV1(time, "left", (("panda_leftfinger::collision", "cylinder_02::link::collision"),))
        for time in (1.000, 1.050, 1.100)
    ] + [
        M1BContactSampleV1(time, "right", (("panda_rightfinger::collision", "cylinder_02::link::collision"),))
        for time in (1.015, 1.065, 1.115)
    ]
    assert broker_from_window(jittered)[0].grasp_success is True

    stale = [
        M1BContactSampleV1(time, finger, ((f"panda_{finger}finger::collision", "cylinder_02::link::collision"),))
        for time in (1.0, 1.5, 2.0)
        for finger in ("left", "right")
    ]
    assert broker_from_window(stale)[0].grasp_success is False


def test_m1b_s0_style_tolerance_gate_requires_repeated_trials_and_margin() -> None:
    trials = [
        OffsetTrialV1(axis, offset, success)
        for axis in ("x", "y", "z")
        for offset, success in ((0.0, True), (0.005, True), (0.010, True))
        for _ in range(3)
    ]
    envelope = tolerance_envelope(trials)
    assert envelope == {"x": 0.010, "y": 0.010, "z": 0.010}
    audit = perception_axis_audit([(0.004, -0.003, 0.005)] * 30)
    assert reachability_gate(envelope, audit)[0] == "GO"
    assert reachability_gate(envelope, perception_axis_audit([(0.007, 0.0, 0.0)] * 30))[1] == ("P90_EXCEEDS_60_PERCENT_TOLERANCE:x",)


def test_m1b_reachability_gate_accepts_only_complete_actual_evidence() -> None:
    envelope = measured_tolerance_envelope({
        "schema_version": "M1BToleranceEnvelopeV1",
        "status": "COMPLETE_CALIBRATION_ONLY",
        "trial_count": 81,
        "tolerance_envelope_m": {"x": 0.02, "y": None, "z": 0.01},
    })
    assert envelope == {"x": 0.02, "y": None, "z": 0.01}
    with pytest.raises(ValueError, match="not complete"):
        measured_tolerance_envelope({"schema_version": "M1BToleranceEnvelopeV1", "status": "RUNNING", "trial_count": 81, "tolerance_envelope_m": {"x": 0.02, "y": 0.01, "z": 0.01}})
    errors = actual_perception_errors({"status": "ACTUAL_GAZEBO_RGBD_FRAMES_EVALUATED", "matches": [{"error_world_xyz_m": [0.001, -0.002, 0.003]}]})
    assert errors == [(0.001, -0.002, 0.003)]
    with pytest.raises(ValueError, match="not an actual"):
        actual_perception_errors({"status": "MANIFEST_ONLY_NO_GAZEBO_FRAMES", "matches": []})


def test_m1b_tolerance_worklist_binds_three_distinct_calibration_instances(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    output = tmp_path / "worklist.json"
    subprocess.run([sys.executable, "scripts/plan_m1b_tolerance_calibration.py", "--config", "configs/m1b_normal_tolerance_calibration.json", "--output", str(output)], cwd=root, check=True)
    worklist = json.loads(output.read_text())
    assert worklist["trial_count"] == 81
    first_point = [trial for trial in worklist["trials"] if trial["axis"] == "x" and trial["offset_m"] == 0.0]
    assert len({(trial["scene_seed"], trial["object_slot"]) for trial in first_point}) == 3


def test_m1b_tolerance_summary_requires_all_trials_and_applies_signed_monotonic_closure(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    worklist_path = tmp_path / "worklist.json"
    subprocess.run([sys.executable, "scripts/plan_m1b_tolerance_calibration.py", "--config", "configs/m1b_normal_tolerance_calibration.json", "--output", str(worklist_path)], cwd=root, check=True)
    worklist = json.loads(worklist_path.read_text())
    raw = tmp_path / "raw"; raw.mkdir()
    for index, trial in enumerate(worklist["trials"]):
        success = not (trial["axis"] == "y" and trial["offset_m"] == 0.015)
        record = {"provenance": "CALIBRATION_ONLY_INITIALIZATION", "trial": trial, "baseline_perception_free": True, "bilateral_same_entity_contact": success, "attach": {"state_confirmed": success}}
        (raw / f"trial-{index:03d}.json").write_text(json.dumps(record))
    summary = summarize(worklist, raw)
    assert summary["tolerance_envelope_m"] == {"x": 0.02, "y": 0.01, "z": 0.02}
    (raw / "trial-080.json").unlink()
    with pytest.raises(ValueError, match="missing raw trial evidence"):
        summarize(worklist, raw)


def test_m1b_remote_tolerance_campaign_requires_fresh_partitions_and_full_reset() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_campaign_remote.sh").read_text()
    assert 'for index in $(seq 0 80)' in source
    assert 'partition="m1b_tolerance_campaign_$index"' in source
    assert '--resume-world --activate-controllers' in source
    assert '--calibration-fixture-diameter-m "$fixture_diameter_m"' in source
    assert 'cleanup_partition "$partition"' in source
    assert 'INFRASTRUCTURE_FAILURE:TRIAL:index=$index' in source
    assert 'summarize_m1b_tolerance_campaign.py' in source
