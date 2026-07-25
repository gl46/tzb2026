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
from xh_agent.grasp.contact_seek import descending_contact_seek_offsets_m
from xh_agent.grasp.hand_preflight import M1BHandPreflightV1, evaluate_hand_preflight
from xh_agent.grasp.m1b_contact_window import M1BContactSampleV1, broker_from_window
from xh_agent.grasp.tolerance_envelope import OffsetTrialV1, perception_axis_audit, reachability_gate, tolerance_envelope
from evaluate_m1b_reachability_gate import actual_perception_errors, measured_tolerance_envelope
from xh_agent.grasp.post_grasp import evaluate_post_grasp_identity, evaluator_supervision_record
from xh_agent.grasp.reset import M1BResetVerificationV1, validate_reset_records
from xh_agent.recovery.manager import recovery_for
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1
from xh_agent.runtime.m1b_center_correction import M1BPublicGeometryXYCorrectionV1, M1BTableSupportedCylinderCenterV1
from xh_agent.task_compiler.deterministic import DeterministicTaskCompiler

SCRIPTS = Path(__file__).parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from audit_m1b_center_reachability import percentile90, perceived_diameter_m  # noqa: E402
from generate_industrial_scenes import BIN_DROP_TARGET_Z_M, CYLINDER_HALF_LENGTH_M, ROBOT_BASE_KEEP_OUT_RADIUS_M, ROBOT_BASE_XY, SPAWN_CLEARANCE_M, TABLE_TOP_Z, bin_cell_targets, render  # noqa: E402
from summarize_m1b_tolerance_campaign import summarize  # noqa: E402
from m1b_wrong_object_drill import carried_track_from_vacancy, vacated_tracks_from_post_frames  # noqa: E402
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


def test_contact_seek_schedule_is_bounded_and_pose_independent() -> None:
    assert descending_contact_seek_offsets_m(start_m=0.270, minimum_m=0.060, step_m=0.005) == (
        0.270, 0.265, 0.260, 0.255, 0.250, 0.245, 0.240, 0.235,
        0.230, 0.225, 0.220, 0.215, 0.210, 0.205, 0.200, 0.195,
        0.190, 0.185, 0.180, 0.175, 0.170, 0.165, 0.160, 0.155,
        0.150, 0.145, 0.140, 0.135, 0.130, 0.125, 0.120, 0.115,
        0.110, 0.105, 0.100, 0.095, 0.090, 0.085, 0.080, 0.075,
        0.070, 0.065, 0.060,
    )
    with pytest.raises(ValueError):
        descending_contact_seek_offsets_m(start_m=0.05, minimum_m=0.06, step_m=0.005)


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
    evidence = calibration.episode_tf_evidence()
    assert evidence["parent_frame"] == "world"
    assert evidence["camera_optical_frame"] == calibration.camera_optical_frame
    assert evidence["world_to_camera_link_translation_m"] == [-0.8, -0.8, 1.4]
    assert evidence["tf_chain_sha256"] == calibration.fingerprint
    recorder = (root / "scripts/record_m1b_alpha_ros.py").read_text(encoding="utf-8")
    assert '"translation_m"' in recorder
    assert '"rotation_xyzw"' in recorder
    assert '"tf_chain_sha256"' in recorder


def test_m1b_public_geometry_corrections_are_bounded_and_public_only(tmp_path: Path) -> None:
    payload = {
        "schema_version": "M1BPublicGeometryXYCorrectionV1",
        "feature_order": ["bias", "surface_optical_x_m", "surface_optical_y_m", "surface_optical_z_m", "perceived_diameter_m", "public_orientation_is_tilted"],
        "signed_residual_coefficients_world_xy": {"x": [0.001, 0, 0, 0, 0, 0], "y": [-0.002, 0, 0, 0, 0, 0]},
        "training_input_sha256": "a" * 64,
        "truth_boundary": "simulator supervision is training-only; runtime uses public RGB-D geometry and public orientation_state only",
    }
    path = tmp_path / "correction.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    correction = M1BPublicGeometryXYCorrectionV1.from_file(path)
    assert correction.correct_xy((0.1, 0.2, 0.3), surface_optical_m=(0.0, 0.0, 1.0), perceived_diameter_m=0.03, orientation_state="normal") == pytest.approx((0.099, 0.202, 0.3))
    with pytest.raises(ValueError, match="orientation_state"):
        correction.correct_xy((0.1, 0.2, 0.3), surface_optical_m=(0.0, 0.0, 1.0), perceived_diameter_m=0.03, orientation_state="unknown")
    support_path = tmp_path / "support.json"
    support_path.write_text(json.dumps({
        "schema_version": "M1BTableSupportedCylinderCenterV1", "center_offset_above_support_m": 0.03915,
        "support_world_z_bounds_m": [0.43, 0.47],
        "truth_boundary": "runtime support plane comes from public RGB-D; dimensions come from the versioned industrial-cylinder class contract",
    }), encoding="utf-8")
    support = M1BTableSupportedCylinderCenterV1.from_file(support_path)
    assert support.correct_z((0.1, 0.2, 0.3), (0.0, 0.0, 0.45)) == pytest.approx((0.1, 0.2, 0.48915))


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


def test_wrong_object_carried_track_association_fails_closed_when_public_vacancy_is_ambiguous() -> None:
    assert carried_track_from_vacancy(["track-22222222"]) == "track-22222222"
    assert carried_track_from_vacancy([]) is None
    assert carried_track_from_vacancy(["track-22222222", "track-33333333"]) is None
    source = (Path(__file__).parents[2] / "scripts/m1b_wrong_object_drill.py").read_text()
    assert "VACATED_SPAWN_NEAREST_ATTACHED_ENTITY" not in source
    assert "--target-public-track-id" in source
    assert "UNIQUE_VACATED_PUBLIC_TRACK" in source


def test_wrong_object_multiframe_reobservation_retains_one_frame_dropouts() -> None:
    pre = {
        "track-carried": {"centre_world_m": [0.10, 0.10, 0.49]},
        "track-briefly-occluded": {"centre_world_m": [0.20, 0.20, 0.49]},
        "track-stable": {"centre_world_m": [0.30, 0.30, 0.49]},
    }
    post_frames = [
        {"post-stable": {"centre_world_m": [0.301, 0.299, 0.49]}},
        {
            "post-occluded": {"centre_world_m": [0.199, 0.201, 0.49]},
            "post-stable": {"centre_world_m": [0.300, 0.300, 0.49]},
        },
    ]
    assert vacated_tracks_from_post_frames(pre, post_frames) == ["track-carried"]


def test_public_postgrasp_lift_is_public_only_and_retains_physical_attach() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_public_postgrasp_lift.py").read_text()
    assert "--public-perception-evidence" in source
    assert "--public-track-id" in source
    assert "public_collision_id(args.public_track_id)" in source
    assert "apply_public_cylinder_scene(client, tracks)" in source
    assert "client.move_hand_cartesian" in source
    assert "--observation-retreat" in source
    assert "restrict_carrier_table_contact" in source
    assert "client.move_joint_target(HOME_ARM_POSITIONS)" in source
    assert '"online_truth_access": False' in source
    assert '"physical_detach_command_sent": False' in source
    assert "gazebo_pose" not in source
    assert "--supervision" not in source


def test_attached_roundtrip_records_moveit_carrier_preflight_before_transport() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_attached_roundtrip.py").read_text()
    assert 'parser.add_argument(\n        "--public-collision-id", required=True,' in source
    assert 'remove = CollisionObject(id=carrier_collision_id)' in source
    assert 'attached.object.id = carrier_collision_id' in source
    assert 'set_allowed_pair(matrix, carrier_collision_id, link, True)' in source
    assert '"public_carrier_collision_id": args.public_collision_id' in source
    assert '"moveit_carried_object_preflight": moveit_carried_object_preflight' in source
    assert 'preflight["status"] = "FK_OR_CYLINDER_POSE_UNAVAILABLE"' in source
    assert 'preflight["status"] = "WORLD_OBJECT_REMOVE_REJECTED"' in source
    assert '"ATTACHED_OBJECT_REJECTED"' in source
    assert '"APPLIED"' in source


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
    assert "issubset(set(names))" in source
    assert "positions(observed_names)" in source


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
    assert 'def m1b_top_down_contact_seek_descent(' in source
    assert 'def m1b_top_down_contact_descend_with_seek(' in source
    assert '"MEASURED_CONTINUOUS_BASELINE_DESCENT"' in source
    assert 'start_m=M1B_TOP_CONTACT_CENTERLINE_Z_M - M1B_CONTACT_SEEK_STEP_M' in source
    assert '"CONTACT_SEEK_BILATERAL_WINDOW_NOT_OBSERVED"' in source
    assert '"CARTESIAN" in str(contact_descend.get("reason", ""))' in source
    assert '"--enable-contact-seeking-terminal-descent", action="store_true"' in source
    assert 'contact_samples_since_seek_start=lambda: raw[seek_contact_start_index:]' in source
    assert 'contact_descend.get("seek_contact_found")' in source
    assert 'ik_seed=ik_seed' in source
    calibration = (Path(__file__).parents[2] / "scripts/m1a_contact_calibration_client.py").read_text()
    assert 'ik_seed: list[float] | None = None' in calibration
    assert '"caller_previous_cartesian_endpoint"' in calibration
    assert 'M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M = 0.220' in source
    assert 'M1B_NORMAL_CONTACT_HAND_Z_OFFSET_M = 0.065' in source
    assert 'M1B_NORMAL_SIDE_HAND_X_OFFSET_M = -0.080' in source
    # Retired to zero for the ADR-0016b franka-copy hand: the jaw midpoint is
    # hand y=0 by construction and measured constant to 5 um across openings,
    # so the old sideways-pad +1 mm correction was a pure systematic error.
    assert 'M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M = 0.0' in source
    assert 'bias_y = math.cos(yaw_rad) * hand_y_centerline_bias_m' in source
    assert 'value.position.y = centre_world_m[1] + hand_x_offset_m * board_y + bias_y' in source
    assert 'hand_y_centerline_bias_m = M1B_NORMAL_HAND_Y_CENTERLINE_BIAS_M if args.calibration_hand_y_bias_m is None else args.calibration_hand_y_bias_m' in source
    assert 'hand_x_offset_m: float = M1B_NORMAL_SIDE_HAND_X_OFFSET_M' in source
    assert 'value.position.x = centre_world_m[0] + hand_x_offset_m' in source
    assert 'def m1b_close_finger_targets_from_perceived_diameter(' in source
    assert 'width_window_from_perceived_diameter(perceived_diameter_m)' in source
    assert 'M1B_FINGER_BOARD_THICKNESS_M = 0.006' in source
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
    assert '"baseline_perception_free": calibration_mode and not args.enable_near_pregrasp_reobservation' in source
    assert 'CALIBRATION_SETTLE_S = 2.0' in source
    assert 'def calibration_live_model_center(entity_name: str)' in source
    assert 'time.sleep(CALIBRATION_SETTLE_S)' in source
    assert '"EVALUATOR_ONLY_GAZEBO_MODEL_POSE_AFTER_SETTLE"' in source
    assert 'HAND_FEEDBACK_READY_TIMEOUT_S = 12.0' in source
    assert 'def wait_for_finite_hand_feedback(client: CalibrationClient)' in source
    assert 'hand_feedback_ready = client.wait_calibration_ready() and wait_for_finite_hand_feedback(client)' in source
    assert '"evidence_sha256": hashlib.sha256(raw).hexdigest()' in source
    assert 'M1B_NORMAL_CLOSE_DURATION_S = 0.8' in source
    # The final descent is a straight seeded-waypoint cartesian segment and
    # the close is two-stage (pre-close clear of the modelled skin, settle,
    # then window-edge squeeze) — the measured remedy for the OMPL side-bow
    # and the bullet-featherstone per-pair force-response dead band.
    assert 'def move_hand_cartesian(' in (Path(__file__).parents[2] / "scripts/m1a_contact_calibration_client.py").read_text()
    assert 'MoveIt computeCartesianPath straight vertical descent' in source or 'seeded_waypoint' in source or 'SEEDED_PER_WAYPOINT' in (Path(__file__).parents[2] / "scripts/m1a_contact_calibration_client.py").read_text()
    assert 'preclose = client.command_hand(' in source
    assert 'close = client.command_hand(' in source and 'duration_s=1.2' in source
    assert '"hand_close_duration_s": M1B_NORMAL_CLOSE_DURATION_S' in source
    assert '--calibration-hand-y-bias-m' in source
    assert '--calibration-keep-target-collision-through-descend' in source
    assert '--calibration-lateral-insertion' in source
    assert '--calibration-lateral-insertion-hand-z-offset-m' in source
    assert '--calibration-lateral-insert-target-touch-exception' in source
    assert '--calibration-vertical-board-ik-probe' in source
    assert 'requires one explicit lateral insertion height' in source
    assert 'M1B_CALIBRATION_LATERAL_INSERTION_CLEAR_HAND_X_OFFSETS_M = (-0.200, -0.160, -0.140, -0.120)' in source
    assert 'M1B_CALIBRATION_LATERAL_INSERTION_HAND_Z_OFFSETS_M = (0.065, 0.080, 0.095, 0.105)' in source
    assert 'M1B_CALIBRATION_LATERAL_INSERTION_YAWS_RAD = tuple(math.radians(value) for value in range(0, 360, 30))' in source
    assert 'def m1b_calibration_lateral_insertion(' in source
    assert 'for magnitude_m in (abs(value) for value in M1B_CALIBRATION_LATERAL_INSERTION_CLEAR_HAND_X_OFFSETS_M):' in source
    assert '("high_clear", M1B_NORMAL_PRECONTACT_HAND_Z_OFFSET_M, clear_x_offset_m)' in source
    assert '("low_clear", z_offset_m, clear_x_offset_m)' in source
    assert '("lateral_insert", z_offset_m, final_x_offset_m)' in source
    assert '"candidate_attempts": candidate_attempts' in source
    assert '"lateral_target_contact_authorization": lateral_contact_authorization' in source
    assert 'authorize_lateral_target_contact=authorize_lateral_target_contact' in source
    assert 'failed_physical_candidate' in source
    assert 'Do not chain a\n                        # second candidate through that altered state' in source
    assert 'lateral_target_touch_exception_restored = client.set_target_touch_exception(False, target_id=target_entity)' in source
    assert '"calibration_lateral_target_touch_exception_restored": lateral_target_touch_exception_restored' in source
    assert 'def m1b_calibration_vertical_board_ik_probe(' in source
    assert 'def m1b_calibration_scene_labels_at_lift(' in source
    assert 'virtual_labels = m1b_calibration_scene_labels_at_lift(labels, lift_m=lift_m)' in source
    assert 'M1B_CALIBRATION_VERTICAL_BOARD_HAND_X_OFFSETS_M' in source
    assert 'M1B_CALIBRATION_VERTICAL_BOARD_HAND_Z_OFFSETS_M' in source
    assert '"executed_physical_motion": False' in source
    assert '"finger_board_axis_world": [0.0, 0.0, 1.0]' in source
    assert 'solution = client.ik(pose)' in source
    assert '"low_clear_preflight_ik"' in source
    assert '"lateral_insert_preflight_ik"' in source
    assert 'for yaw_rad in M1B_CALIBRATION_LATERAL_INSERTION_YAWS_RAD:' in source
    assert 'value.orientation.x = math.cos(yaw_rad / 2.0)' in source
    assert 'value.orientation.y = math.sin(yaw_rad / 2.0)' in source
    assert '"yaw_candidates_degrees"' in source
    assert '--calibration-lateral-insertion requires --calibration-keep-target-collision-through-descend' in source
    assert '"calibration_lateral_insertion": args.calibration_lateral_insertion' in source
    assert '"calibration_motion_diagnostic": calibration_motion' in source
    assert 'if calibration_motion is not None' in source
    assert '"source": "ACTUAL_PUBLIC_RGBD_GEOMETRIC_OUTPUT"' in source
    assert 'if contact_descend.get("executed"):' in source
    assert 'only the non-contact\n            # approach requires strict terminal convergence' in source
    assert 'contact_start_index = len(raw)' in source
    assert 'def m1b_top_down_precontact(' in source
    assert 'def m1b_top_down_contact_descend(' in source
    assert '"tool_axis_world": [0.0, 0.0, -1.0]' in source
    assert '--public-free-gap-yaw-rad' in source
    assert '"PUBLIC_RGBD_FREE_GAP_GEOMETRY"' in source
    assert 'm1b_top_down_precontact + m1b_top_down_contact_descend' in source


def test_m1b_public_production_grasp_rejects_supervision_inputs() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_trial.py").read_text()
    assert '"public production mode forbids --trial, --supervision, and --object-slot"' in source
    assert '"public production requires --enable-near-pregrasp-reobservation"' in source
    assert 'def public_tracks_from_evidence(' in source
    assert 'def m1b_public_free_gap_yaw(' in source
    assert 'def apply_public_cylinder_scene(' in source
    assert '"PUBLIC_PERCEPTION_PRODUCTION"' in source
    assert '"PUBLIC_RGBD_TRACKS"' in source
    assert 'target_entity = str(target_label["actual_sim_entity_id"])' in source
    # The privileged entity lookup remains exclusively under the calibration
    # branch, while production receives its collision target from a public
    # perception track with a namespace that cannot equal a simulator entity.
    assert 'planning_target_id = public_collision_id(args.public_track_id)' in source
    assert 'return f"m1b_public_{track_id}"' in source


def test_m1b_public_target_selector_is_perception_only() -> None:
    source = (Path(__file__).parents[2] / "scripts/select_m1b_public_grasp_target.py").read_text()
    assert '"provenance": "PUBLIC_PERCEPTION_ONLY"' in source
    assert '"online_truth_access": False' in source
    assert 'M1BPublicGeometryXYCorrectionV1' in source
    assert 'M1BTableSupportedCylinderCenterV1' in source
    assert 'simulator_supervision' not in source
    assert 'INDUSTRIAL_DIAMETER_RANGE_M = (0.020, 0.040)' in source
    runner = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_trial.py").read_text()
    assert 'M1B_PUBLIC_INDUSTRIAL_DIAMETER_RANGE_M = (0.020, 0.040)' in runner
    assert 'selected public track diameter is outside the approved industrial-cylinder class band' in runner


def test_m1b_public_geometry_gate_passes_measured_inputs_by_name() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_adr0016b_public_geometry_gate.sh").read_text()
    assert '--tolerance-trials reports/m1b-adr0016b-tolerance-envelope.json' in source
    assert '--perception-errors "$test_audit"' in source
    assert 'CURRENT_GEOMETRY_SPLIT_INCOMPLETE' in source


def test_m1b_acceptance_utilities_match_current_public_geometry_contract() -> None:
    root = Path(__file__).parents[2]
    roundtrip = (root / "scripts" / "run_m1b_attached_roundtrip.py").read_text(encoding="utf-8")
    wrong_object = (root / "scripts" / "m1b_wrong_object_drill.py").read_text(encoding="utf-8")
    assert "M1B_CYLINDER_LENGTH_M = 0.080" in roundtrip
    assert "M1B_CYLINDER_RADIUS_M = 0.015" in roundtrip
    assert "M1BPublicGeometryXYCorrectionV1" in wrong_object
    assert "M1BTableSupportedCylinderCenterV1" in wrong_object
    assert "UNIQUE_VACATED_PUBLIC_TRACK" in wrong_object


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
        assert label["layout_reachability"]["passed"] is True
    assert len(supervision["layout_reachability"]["bin_cells"]) == 6
    assert all(item["passed"] for item in supervision["layout_reachability"]["bin_cells"])


def test_m1b_adr_0016_corridor_prefilter_rejects_near_base_spawns() -> None:
    from generate_industrial_scenes import MIN_TOP_GRASP_CORRIDOR_RADIUS_M
    template = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf").read_text()
    # The corridor radius sits between the measured infeasible ceiling (0.228 m)
    # and the feasible floor (0.273 m) from the ADR-0016 §3 scan.
    assert 0.228 < MIN_TOP_GRASP_CORRIDOR_RADIUS_M < 0.273
    for seed in (1017, 5017, 1042, 1099, 1200):
        _, supervision = render(template, seed, orientations=("normal",))
        for label in supervision["simulator_supervision"]["objects"]:
            x, y, _ = label["position_3d_world"]
            reach = label["layout_reachability"]
            assert math.dist((x, y), ROBOT_BASE_XY) >= MIN_TOP_GRASP_CORRIDOR_RADIUS_M
            assert reach["top_grasp_corridor_radius_ok"] is True
            assert reach["min_top_grasp_corridor_radius_m"] == MIN_TOP_GRASP_CORRIDOR_RADIUS_M


def test_m1b_calibration_pedestal_is_normal_only_and_lifts_labels() -> None:
    template = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf").read_text()
    scene, supervision = render(template, 1017, orientations=("normal",), pedestal_lift_m=0.04)
    labels = supervision["simulator_supervision"]["objects"]
    assert scene.count('name="cylinder_pedestal_') == len(labels)
    assert supervision["calibration_fixture"] == {
        "kind": "static_narrow_pedestal",
        "pedestal_lift_m": 0.04,
        "calibration_only": True,
    }
    assert all(label["position_3d_world"][2] == pytest.approx(TABLE_TOP_Z + 0.04 + CYLINDER_HALF_LENGTH_M + SPAWN_CLEARANCE_M) for label in labels)
    assert all(label["layout_reachability"]["passed"] is True for label in labels)
    with pytest.raises(ValueError, match="normal cylinders"):
        render(template, 1017, pedestal_lift_m=0.04)


def test_m1b_adr_0014_scene_geometry_and_bin_layout_are_consistent() -> None:
    root = Path(__file__).parents[2]
    template = (root / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf").read_text()
    assert template.count("<radius>0.015</radius>") == 12
    assert template.count("<length>0.08</length>") == 12
    assert template.count("<mass>0.045</mass>") == 6
    assert "<radius>0.025</radius>" not in template
    assert "<length>0.09</length>" not in template
    assert "<mass>0.06</mass>" not in template
    assert "<pose>0.20 0 0.45 0 0 1.57079632679</pose>" in template
    assert len(bin_cell_targets()) == 6
    assert all(target[2] == BIN_DROP_TARGET_Z_M for target in bin_cell_targets())
    assert min(target[1] for target in bin_cell_targets()) == pytest.approx(0.01)


def test_m1b_adr_0016b_franka_fallback_hand_keeps_its_contracts() -> None:
    urdf = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_text()
    # ADR-0016 §4 pre-authorized fallback: the hand geometry is a
    # primitive-approximated copy of the official franka_description meshes,
    # so the inline-topology boxes are intentionally gone.  What must remain
    # unchanged are the ADR-0016 "unchanged contracts": joint names, [0,0.04]
    # limits, the q2-master mimic, both named collision elements, and both
    # finger contact-sensor topics.
    assert '<joint name="panda_finger_joint1" type="prismatic">' in urdf
    assert '<joint name="panda_finger_joint2" type="prismatic">' in urdf
    assert urdf.count('lower="0" upper="0.04"') == 2
    assert '<mimic joint="panda_finger_joint2" multiplier="1" offset="0"/>' in urdf
    assert urdf.count('<origin xyz="0 0 0.0584" rpy="0 0 0"/>') == 2
    # Both contract collision element names are retained on both fingers.
    assert urdf.count('name="collision"') == 2
    assert urdf.count('name="tapered_tip_collision"') == 2
    # The grasp element is a full-length plate (the measured bullet-featherstone
    # dead band rejected the short block), face modelled proud of the y=0 plane.
    assert urdf.count('<box size="0.021 0.0208 0.0538"/>') == 4
    assert '/xh/supervision/panda_leftfinger_contacts' in urdf
    assert '/xh/supervision/panda_rightfinger_contacts' in urdf
    # Both collision elements are bound to the finger contact sensors so the
    # distal grasp plate is observed, not only the recessed proximal body.
    assert urdf.count('panda_leftfinger_fixed_joint_lump__tapered_tip_collision_collision_1') == 1
    assert urdf.count('panda_rightfinger_fixed_joint_lump__tapered_tip_collision_collision_1') == 1


def test_m1b_adr_0016_orientation_scan_requires_kinematics_and_populated_corridor() -> None:
    source = (Path(__file__).parents[2] / "scripts/scan_m1b_orientation_feasibility.py").read_text()
    assert '"empty_scene_kinematic"' in source
    assert '"populated_scene_corridor"' in source
    assert 'client.ik(pose, avoid_collisions=collision_aware' in source
    assert 'client.plan(solution) if collision_aware' in source
    assert 'apply_calibration_cylinder_scene(client, labels)' in source
    assert 'bin_cell_targets()' in source
    assert '"scene_admission": "FAIL_CLOSED"' in source
    assert 'ORIENTATION_FEASIBILITY_VERIFIED' in source


def test_m1b_scene_admission_replaces_prior_seed_collision_objects() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_trial.py").read_text()
    assert 'expected_ids = {f"cylinder_{index:02d}" for index in range(1, 13)}' in source
    assert 'PlanningSceneComponents.WORLD_OBJECT_NAMES' in source
    assert 'for object_id in sorted(existing_ids):' in source
    assert 'item.operation = CollisionObject.REMOVE' in source
    assert 'if existing_ids and not client.apply_scene_diff(removal):' in source


def test_m1b_adr_0016_top_contact_height_includes_tapered_tip_clearance() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_trial.py").read_text()
    # The measured two-sided Z bounds meet at 118 mm, but an 81-trial campaign
    # there scored the official closure worse (Z 5 -> 0 mm) on a noise draw, so
    # production stays at the value the committed acceptance rests on.
    assert 'M1B_TOP_CONTACT_CENTERLINE_Z_M = 0.120' in source
    assert 'tip into the tabletop' in source


def test_m1b_gz_ros2_control_keeps_standard_description_topic_contract() -> None:
    urdf = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf").read_text()
    assert "<robot_param>" not in urdf
    assert "<robot_param_node>" not in urdf


def test_m1b_startup_replays_generated_description_to_controller_manager() -> None:
    root = Path(__file__).parents[2]
    launch = (root / "robot_ws/src/xh_sim/launch/simulation.launch.py").read_text()
    relay = (root / "robot_ws/src/xh_sim/scripts/robot_description_relay.py").read_text()
    cmake = (root / "robot_ws/src/xh_sim/CMakeLists.txt").read_text()
    assert "robot_description_relay.py" in launch
    assert '"urdf_path": str(generated_urdf)' in launch
    assert "TimerAction(period=3.0, actions=[robot_description_relay])" in launch
    assert "DurabilityPolicy.TRANSIENT_LOCAL" in relay
    assert 'create_publisher(String, "/robot_description", qos)' in relay
    assert "robot_description_relay.py" in cmake


def test_m1b_moveit_server_does_not_start_a_second_simulation() -> None:
    source = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/launch/m1b_moveit_server.launch.py").read_text()
    assert "simulation.launch.py" not in source.replace("``simulation.launch.py``", "")
    assert "moveit_ros_move_group" in source
    execution = (Path(__file__).parents[2] / "robot_ws/src/xh_sim/launch/moveit_execution.launch.py").read_text()
    assert 'DeclareLaunchArgument(\n            "world_name"' in execution
    assert '"world_name": world_name' in execution


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


def test_m1b_tolerance_campaign_requires_amendment_1_physical_reset_proof() -> None:
    source = (Path(__file__).parents[2] / "scripts/run_m1b_tolerance_campaign_remote.sh").read_text()
    assert "scripts/verify_m1b_reset_noncoupling.py" in source
    assert '"RESET_PHYSICAL_NONCOUPLING_VERIFIED"' in source
    assert "INVALID_RESET_RETRY:PHYSICAL_NONCOUPLING" in source
    assert "INVALID_RESET_RETRY:POST_VERIFY_RESUME" in source
    assert "--req 'pause: false'" in source
    assert "M1B_TOLERANCE_RESET_MAX_ATTEMPTS" in source
    assert "INVALID_RESET_RETRY:PHYSICAL_NONCOUPLING" in source
    assert "INFRASTRUCTURE_FAILURE:RESET_RETRY_EXHAUSTED" in source
    assert "M1B_TOLERANCE_ALLOW_RESUME" in source
    assert "RESUME_RAW_PREFIX_MISMATCH" in source


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


def test_m1a_hand_post_goal_observation_waits_for_fresh_state_without_relaxing_tolerance() -> None:
    """A stale snapshot must not be reported as a physical hand failure.

    The ADR-0009 bullet audit recorded max_position_error_m 0.00713 m while the
    controller returned SUCCEEDED against its own 1 mm tolerance, mimic tracking
    error was 1.1e-08 m, and the next read of the same joints was 0.039999 m of
    a 0.04 m command.  Two S3 release steps failed identically.  The cause was a
    fixed three-spin post-goal wait, so this pins the replacement as a
    *measurement* fix: the snapshot must post-date the result, while the 1 mm
    action contract and its 0.1 mm sampling slack stay exactly as they were.
    """
    source = (Path(__file__).parents[2] / "scripts/m1a_contact_calibration_client.py").read_text()
    # The contract itself is untouched.
    assert "HAND_POST_GOAL_OBSERVATION_SLACK_M = 0.0001" in source
    assert "max_position_error_m <= goal_tolerance_m + HAND_POST_GOAL_OBSERVATION_SLACK_M" in source
    assert "mimic_tracking_error_m <= goal_tolerance_m + HAND_POST_GOAL_OBSERVATION_SLACK_M" in source
    # The fixed-spin assumption is gone, replaced by counted fresh deliveries.
    assert "for _ in range(3):\n            rclpy.spin_once" not in source
    assert "HAND_POST_GOAL_FRESH_SAMPLES = 3" in source
    assert "HAND_POST_GOAL_SETTLE_TIMEOUT_S = 2.0" in source
    assert "self.hand_state_seq += 1" in source
    assert "self.hand_state_seq - seq_at_result < HAND_POST_GOAL_FRESH_SAMPLES" in source
    # Bounded: a genuinely short hand must still fail rather than spin forever.
    assert "settle_deadline = time.monotonic() + HAND_POST_GOAL_SETTLE_TIMEOUT_S" in source
    assert "while time.monotonic() < settle_deadline:" in source


def test_m1b_descent_step_probe_is_diagnostic_and_cannot_alter_admission() -> None:
    """The step probe answers a question; it must never become a gate.

    Re-walking a failing descent at a finer step is only legitimate as a
    diagnostic.  If it could relax scene admission it would be a gate
    relaxation dressed as a measurement, so this pins that it executes no
    motion, writes its own schema, and leaves the production step constant and
    the joint-jump guard untouched.
    """
    source = (Path(__file__).parents[2] / "scripts/scan_m1b_orientation_feasibility.py").read_text()
    assert "SCAN_MAX_STEP_M = 0.005" in source
    assert "SCAN_MAX_JOINT_STEP_RAD = 0.35" in source
    assert "PROBE_STEP_SIZES_M = (0.005, 0.0025, 0.00125)" in source
    assert "max_step_m: float = SCAN_MAX_STEP_M" in source
    assert "steps = max(2, math.ceil(M1B_TOP_PRECONTACT_STANDOFF_M / max_step_m))" in source
    assert '"schema_version": "M1BDescentStepProbeV1"' in source
    assert '"provenance": "DIAGNOSTIC_ONLY_NO_EXECUTED_MOTION"' in source
    # The probe must not touch the admission verdict or its status strings.
    probe_body = source[source.index("def run_descent_step_probe"):source.index("def main()")]
    assert "ORIENTATION_FEASIBILITY_VERIFIED" not in probe_body
    assert "scene_admission" not in probe_body
    assert "client.execute" not in probe_body and "move_hand_cartesian" not in probe_body
    # A scoped target-touch exception must still be restored.
    assert "set_target_touch_exception(False" in probe_body
    assert "target_touch_exception_restored" in probe_body


def test_m1b_contact_window_records_its_own_span_on_pass_and_on_near_miss() -> None:
    """The broker's numbers must reach the evidence, not be re-derived offline.

    A rejected window used to record nothing but "incomplete", so a 97 ms
    near miss and a finger that never touched the object were
    indistinguishable.  Re-deriving the span from the raw samples invites the
    wrong metric (max(first)..min(last) across fingers overstates the run), so
    the broker states its own measurement on every branch.  These fields are
    diagnostic: the accept/reject decision is unchanged.
    """
    passing = [
        M1BContactSampleV1(time, finger, ((f"panda_{finger}finger::collision", "cylinder_02::link::collision"),))
        for time in (1.0, 1.05, 1.10, 1.15)
        for finger in ("left", "right")
    ]
    feedback, internal = broker_from_window(passing)
    assert feedback.grasp_success is True
    assert internal["bilateral_overlap_s"] == pytest.approx(0.150)
    assert internal["consecutive_samples"] == 4
    assert internal["required_bilateral_overlap_s"] == 0.100
    assert internal["required_consecutive_samples"] == 3
    assert internal["candidate_entities"] == ["cylinder_02"]
    assert internal["left_right_pairing_window_s"] == 0.050
    assert internal["max_consecutive_sample_gap_s"] == 0.060

    # 97 ms of continuous bilateral contact: a genuine grasp that the window
    # end truncated, not an absence of contact.  It must still be rejected.
    near_miss = [
        M1BContactSampleV1(time, finger, ((f"panda_{finger}finger::collision", "cylinder_02::link::collision"),))
        for time in (1.000, 1.050, 1.097)
        for finger in ("left", "right")
    ]
    rejected, near_internal = broker_from_window(near_miss)
    assert rejected.grasp_success is False
    assert rejected.tactile_state == "bilateral_contact_window_incomplete"
    assert near_internal["bilateral_overlap_s"] == 0.0
    assert near_internal["observed_best_bilateral_overlap_s"] == pytest.approx(0.097)
    assert near_internal["observed_best_consecutive_samples"] == 3
    assert near_internal["paired_bilateral_sample_count"] == 3


def test_m1b_contact_window_reports_which_finger_was_missing() -> None:
    single_sided = [
        M1BContactSampleV1(time, "left", (("panda_leftfinger::collision", "cylinder_02::link::collision"),))
        for time in (1.0, 1.05, 1.10)
    ]
    feedback, internal = broker_from_window(single_sided)
    assert feedback.grasp_success is False
    assert internal["per_finger_sample_count"] == {"left": 3, "right": 0}
    assert internal["observed_best_bilateral_overlap_s"] == 0.0
    assert internal["candidate_entities"] == []


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
    assert measured_tolerance_envelope({
        "schema_version": "M1BADR0016ToleranceEnvelopeEvidenceV2",
        "status": "COMPLETE_CALIBRATION_ONLY",
        "trial_count": 81,
        "tolerance_envelope_m": {"x": 0.015, "y": 0.015, "z": 0.005},
    }) == {"x": 0.015, "y": 0.015, "z": 0.005}
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
    assert 'for index in $(seq "$start_index" "$end_index")' in source
    assert 'M1B_TOLERANCE_START_INDEX:-0' in source
    assert 'M1B_TOLERANCE_END_INDEX:-80' in source
    assert 'M1B_TOLERANCE_CALIBRATION_HAND_Y_BIAS_M' in source
    assert 'M1B_TOLERANCE_KEEP_TARGET_COLLISION_THROUGH_DESCEND' in source
    assert 'M1B_TOLERANCE_TOP_CONTACT_HEIGHT_M' in source
    assert '--calibration-top-contact-height-m' in source
    assert 'domain=$((130 + index + reset_attempt))' in source
    assert 'Paused Gazebo cannot be required to have loaded controllers' in source
    assert source.index('scripts/m1b_reset_detach.py') < source.index('scripts/verify_m1b_reset_noncoupling.py')
    assert 'wait_for_m1b_controller_load()' not in source
    assert 'fails closed if that lifecycle does not complete' in source
    assert 'PARTIAL_CAMPAIGN_COMPLETE:$start_index:$end_index' in source
    assert 'partition="m1b_tolerance_campaign_${index}_reset_${reset_attempt}"' in source
    assert 'for reset_attempt in $(seq 1 "$reset_max_attempts")' in source
    assert '--resume-world --activate-controllers' in source
    assert '--calibration-fixture-diameter-m "$fixture_diameter_m"' in source
    assert 'cleanup_partition "$partition"' in source
    assert 'INFRASTRUCTURE_FAILURE:TRIAL:index=$index' in source
    assert 'summarize_m1b_tolerance_campaign.py' in source
