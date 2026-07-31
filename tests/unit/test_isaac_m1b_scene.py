import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from xh_agent.contracts.models import EpisodeTransitionV0, ObjectTrackV0
from xh_agent.data.isaac_m1b import (
    M1B_SDF_SHA256,
    M1B_URDF_SHA256,
    OFFICIAL_ISAAC_FRANKA_RELATIVE_USD,
    load_m1b_gripper_effort_limit,
    load_m1b_isaac_generated_scene,
    load_m1b_isaac_scene,
    load_robot_base_pose,
    resolve_official_franka_asset,
    scene_collision_primitive_count,
    scene_primitive_count,
    validate_m1b_physics_contract,
    verify_source_hashes,
)
from xh_agent.data.isaac_m1b_episode import (
    PANDA_DOF_NAMES,
    IsaacM1BPolicyCameraFrameV1,
    IsaacM1BRuntimeFrameV1,
    IsaacM1BSupervisionFrameV1,
    build_transition,
    intersect_pixel_ray_with_world_z,
    public_results_to_tracks,
    transform_optical_point,
)
from xh_agent.grasp.free_gap import (
    isaac_top_down_orientation_wxyz,
    rank_clearance_safe_yaw_candidates,
    select_free_gap_yaw_from_xy,
)
from xh_agent.perception.interfaces import BBoxV1, PerceptionResultV1


ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from generate_industrial_scenes import render  # noqa: E402
from evaluate_isaac_m1b_perception_gate import (  # noqa: E402
    _read_transitions,
    _validate_transition_metrics,
    evaluate,
    optimal_public_truth_assignment,
)
from run_isaac_m1b_tolerance_campaign import (  # noqa: E402
    summarize as summarize_isaac_tolerance,
    valid_orientation_gate_evidence,
    worklist as isaac_tolerance_worklist,
)
from run_isaac_m1b_dual_benchmark import (  # noqa: E402
    parse_gpu_indices,
    parse_smi_csv,
    summarize_gpu_samples,
)

SDF = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
URDF = ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"


def test_isaac_m1b_adapter_is_hash_bound_to_accepted_sources() -> None:
    assert verify_source_hashes(SDF, URDF) == {
        "industrial_cylinder_v1.sdf": M1B_SDF_SHA256,
        "panda_controlled.urdf": M1B_URDF_SHA256,
    }


def test_isaac_m1b_adapter_preserves_scene_geometry_and_camera_contract() -> None:
    scene = load_m1b_isaac_scene(SDF)

    assert scene.cylinder_count == 6
    assert len(scene.models) == 10
    assert scene_primitive_count(scene.models) == 13
    assert scene_collision_primitive_count(scene.models) == 8
    assert [camera.name for camera in scene.cameras] == [
        "policy_rgbd",
        "front_rgbd",
        "overhead_rgbd",
        "side_rgbd",
    ]
    assert scene.cameras[0].position == (-0.8, -0.8, 1.4)
    assert "PUBLIC_POLICY_RGBD_INPUT" in scene.cameras[0].provenance
    assert scene.cameras[1].position == (0.8, 0.8, 1.4)
    assert "ROTATED_180_DEG" in scene.cameras[1].provenance
    assert all(camera.resolution == (640, 480) for camera in scene.cameras)
    assert all(camera.horizontal_fov_rad == pytest.approx(1.047) for camera in scene.cameras)
    assert all(camera.clipping_range_m == (0.1, 4.0) for camera in scene.cameras)
    cylinders = [model for model in scene.models if model.semantic_class == "industrial_cylinder"]
    for cylinder in cylinders:
        assert cylinder.static is False
        visual = cylinder.links[0].visuals[0]
        collision = cylinder.links[0].collisions[0]
        assert visual.shape == "cylinder"
        assert visual.radius == pytest.approx(0.015)
        assert visual.length == pytest.approx(0.08)
        assert collision.shape == visual.shape
        assert collision.radius == visual.radius
        assert collision.length == visual.length
        assert cylinder.links[0].mass_kg == pytest.approx(0.045)
        assert cylinder.links[0].linear_velocity_decay is None
        assert cylinder.links[0].angular_velocity_decay is None

    table = next(model for model in scene.models if model.name == "industrial_work_table")
    assert table.static is True
    assert table.links[0].collisions[0].size == (1.5, 1.0, 0.1)

    partition_bin = next(model for model in scene.models if model.name == "blue_partition_bin")
    assert partition_bin.static is True
    assert partition_bin.pose.xyz == (0.2, 0.15, 0.45)
    assert [collision.name for collision in partition_bin.links[0].collisions] == ["floor"]

    physics = validate_m1b_physics_contract(scene)
    assert physics["dynamic_model_count"] == 6
    assert physics["collision_primitive_count"] == 8
    assert physics["static_collision_model_names"] == (
        "industrial_work_table",
        "blue_partition_bin",
    )
    assert set(physics["cylinder_masses_kg"].values()) == {0.045}
    assert {
        tuple(decay.values())
        for decay in physics["cylinder_velocity_decay"].values()
    } == {(None, None)}
    assert physics["sdf_default_surface"] == {
        "static_friction": 1.0,
        "dynamic_friction": 1.0,
        "restitution": 0.0,
    }
    assert physics["source_engine_sleep_threshold"]["value"] == pytest.approx(
        0.05
    )


def test_isaac_m1b_adapter_fails_closed_if_source_changes(tmp_path: Path) -> None:
    changed = tmp_path / "industrial_cylinder_v1.sdf"
    changed.write_text(SDF.read_text().replace("0.015", "0.016", 1))

    with pytest.raises(ValueError, match="hash mismatch"):
        load_m1b_isaac_scene(changed)


def test_official_isaac_franka_asset_is_fixed_and_resolved_from_assets_root() -> None:
    assert (
        OFFICIAL_ISAAC_FRANKA_RELATIVE_USD
        == "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
    )
    assert resolve_official_franka_asset("https://assets.example/Isaac/6.0/") == (
        "https://assets.example/Isaac/6.0/"
        "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
    )
    with pytest.raises(ValueError, match="assets root is empty"):
        resolve_official_franka_asset(" ")


def test_isaac_builder_makes_official_gripper_variant_explicit() -> None:
    source = (SCRIPTS / "isaac_m1b_dataset_benchmark.py").read_text()
    assert 'choices=("AlternateFinger", "Default")' in source
    assert 'default="Default"' in source
    assert '"Gripper": gripper_variant' in source
    assert "ARGS.gripper_variant" in source
    assert '"xhM1BOfficialAssetContract"' in source


def test_official_franka_uses_hash_bound_production_robot_base_pose() -> None:
    pose = load_robot_base_pose(URDF)
    assert pose.xyz == (-0.35, 0.0, 0.45)
    assert pose.rpy == (0.0, 0.0, 0.0)


def test_official_franka_uses_hash_bound_production_gripper_effort() -> None:
    assert load_m1b_gripper_effort_limit(URDF) == pytest.approx(20.0)


def test_generated_scene_loader_binds_canonical_objects_and_supervision(
    tmp_path: Path,
) -> None:
    generated_sdf, supervision = render(SDF.read_text(), 3001)
    sdf_path = tmp_path / "scene-3001.sdf"
    supervision_path = tmp_path / "scene-3001.supervision.json"
    sdf_path.write_text(generated_sdf)
    supervision_path.write_text(json.dumps(supervision))

    scene = load_m1b_isaac_generated_scene(sdf_path, supervision_path)

    assert scene.scene_seed == 3001
    assert scene.source_supervision_sha256 is not None
    assert 6 <= scene.cylinder_count <= 12
    assert [model.name for model in scene.dynamic_models] == [
        f"cylinder_{index:02d}" for index in range(1, scene.cylinder_count + 1)
    ]
    assert {
        (
            model.links[0].linear_velocity_decay,
            model.links[0].angular_velocity_decay,
        )
        for model in scene.dynamic_models
    } == {(0.5, 0.5)}


def test_generated_scene_loader_rejects_sdf_supervision_mismatch(
    tmp_path: Path,
) -> None:
    generated_sdf, supervision = render(SDF.read_text(), 3001)
    supervision["simulator_supervision"]["objects"][0]["actual_sim_entity_id"] = "cylinder_99"
    sdf_path = tmp_path / "scene-3001.sdf"
    supervision_path = tmp_path / "scene-3001.supervision.json"
    sdf_path.write_text(generated_sdf)
    supervision_path.write_text(json.dumps(supervision))

    with pytest.raises(ValueError, match="not canonical"):
        load_m1b_isaac_generated_scene(sdf_path, supervision_path)


def _isaac_runtime_frame(step_id: int) -> IsaacM1BRuntimeFrameV1:
    return IsaacM1BRuntimeFrameV1(
        episode_id="isaac-m1b-worker-0",
        step_id=step_id,
        timestamp_ns=step_id + 1,
        policy_camera=IsaacM1BPolicyCameraFrameV1(
            rgb_uri=f"dataset://policy_rgbd/rgb/{step_id:06d}.png",
            depth_uri=f"dataset://policy_rgbd/depth/{step_id:06d}.npy",
            camera_intrinsics=[
                500.0,
                0.0,
                320.0,
                0.0,
                500.0,
                240.0,
                0.0,
                0.0,
                1.0,
            ],
            camera_to_world_optical=[
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ],
        ),
        joint_names=list(PANDA_DOF_NAMES),
        joint_position=[0.0] * 9,
        joint_velocity=[0.0] * 9,
        end_effector_pose_world_xyzw=[0.0, 0.0, 0.8, 0.0, 0.0, 0.0, 1.0],
        gripper_state="open",
        action_target_joint_position=[0.01 * step_id] * 9,
    )


def _public_result(step_id: int) -> PerceptionResultV1:
    return PerceptionResultV1(
        frame_id="policy_rgbd",
        timestamp_ns=step_id + 1,
        track_id="track-1234abcd",
        category="industrial_cylinder",
        bbox_or_mask=BBoxV1(x=300, y=210, width=20, height=30),
        position_3d=[0.1, 0.2, 0.42],
        orientation_state="normal",
        confidence=0.9,
        covariance_or_quality={
            "component_centroid_u_px": 320.0 + 500.0 * 0.1 / 0.48915,
            "component_centroid_v_px": 240.0 + 500.0 * 0.2 / 0.48915,
            "support_plane_optical_x_m": 0.1,
            "support_plane_optical_y_m": 0.2,
            "support_plane_optical_z_m": 0.45,
        },
        visibility=0.8,
        source_components=["geometric_rgbd_v1"],
    )


def test_isaac_m1b_runtime_and_supervision_are_structurally_separate() -> None:
    runtime = _isaac_runtime_frame(0)
    assert "cylinder_01" not in runtime.model_dump_json()
    leaked = runtime.model_dump()
    leaked["perfect_object_poses_world_xyzw"] = {
        "cylinder_01": [0.0, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0]
    }
    with pytest.raises(ValidationError):
        IsaacM1BRuntimeFrameV1.model_validate(leaked)

    supervision = IsaacM1BSupervisionFrameV1(
        episode_id=runtime.episode_id,
        step_id=runtime.step_id,
        timestamp_ns=runtime.timestamp_ns,
        perfect_object_poses_world_xyzw={
            "cylinder_01": [0.0, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0]
        },
    )
    assert supervision.training_and_evaluation_only is True


def test_isaac_m1b_transition_is_teacher_free_and_public_observation_only() -> None:
    before = _isaac_runtime_frame(0)
    after = _isaac_runtime_frame(1)
    supervision = IsaacM1BSupervisionFrameV1(
        episode_id=after.episode_id,
        step_id=after.step_id,
        timestamp_ns=after.timestamp_ns,
        perfect_object_poses_world_xyzw={
            "cylinder_01": [0.0, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0]
        },
    )
    transition = build_transition(
        before,
        after,
        [_public_result(0)],
        [_public_result(1)],
        supervision,
        table_supported_center_offset_m=0.03915,
        table_support_world_z_bounds_m=(0.43, 0.47),
        selected_public_track_id="track-1234abcd",
    )

    policy_json = json.dumps(
        {
            "before": transition.observation_before.model_dump(),
            "after": transition.observation_after.model_dump(),
        }
    )
    assert "cylinder_01" not in policy_json
    assert transition.observation_before.segmentation_uri is None
    assert transition.teacher_response is None
    assert transition.provenance["mode"] == "SIM_ONLY"
    assert transition.provenance["local_simplified_robot_used"] == "false"
    assert transition.action_trajectory.dimension_names == list(PANDA_DOF_NAMES)
    assert transition.action_trajectory.units == "radian_arm_metre_finger"
    track = transition.observation_before.object_tracks[0]
    assert track.pose[:2] == pytest.approx([0.1, 0.2])
    assert track.pose[2] == pytest.approx(0.48915)
    assert transition.observation_before.relation_graph == [
        {
            "subject": "track-1234abcd",
            "predicate": "public_orientation_state",
            "object": "normal",
        },
        {
            "subject": "track-1234abcd",
            "predicate": "public_center_support_offset",
            "object": "class_half_length",
        },
        {
            "subject": "track-1234abcd",
            "predicate": "public_center_xy_projection",
            "object": (
                "ray_plane_world_x_plus_"
                "visible_surface_radius_world_y"
            ),
        },
    ]


def test_isaac_tilted_track_uses_public_perceived_radius_for_center_z() -> None:
    frame = _isaac_runtime_frame(0)
    tilted = _public_result(0).model_copy(
        update={"orientation_state": "tilted"}
    )

    tracks, relations = public_results_to_tracks(
        [tilted],
        frame.policy_camera,
        table_supported_center_offset_m=0.03915,
        table_support_world_z_bounds_m=(0.43, 0.47),
    )

    perceived_diameter_m = 20 * 0.42 / 500.0
    assert tracks[0].pose[2] == pytest.approx(
        0.45 + perceived_diameter_m / 2.0
    )
    assert relations[-1] == {
        "subject": "track-1234abcd",
        "predicate": "public_center_xy_projection",
        "object": (
            "ray_plane_world_x_plus_"
            "visible_surface_radius_world_y"
        ),
    }
    assert relations[-2] == {
        "subject": "track-1234abcd",
        "predicate": "public_center_support_offset",
        "object": "perceived_radius",
    }


def test_isaac_public_pixel_ray_intersection_uses_explicit_calibration() -> None:
    frame = _isaac_runtime_frame(0)

    assert intersect_pixel_ray_with_world_z(
        frame.policy_camera,
        pixel_u=320.0,
        pixel_v=240.0,
        world_z_m=1.0,
    ) == pytest.approx([0.0, 0.0, 1.0])


def test_optical_transform_uses_explicit_column_vector_convention() -> None:
    transform = [
        1.0,
        0.0,
        0.0,
        0.5,
        0.0,
        0.0,
        -1.0,
        0.4,
        0.0,
        1.0,
        0.0,
        1.2,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    assert transform_optical_point(transform, [0.1, 0.2, 0.3]) == pytest.approx(
        [0.6, 0.1, 1.4]
    )


def test_isaac_capture_writes_policy_and_truth_streams_with_metric_plane_depth() -> None:
    source = (SCRIPTS / "isaac_m1b_dataset_benchmark.py").read_text()
    assert '"distance_to_image_plane"' in source
    assert '"distance_to_camera"' not in source
    assert "_configure_camera_optics(stage, SCENE.cameras)" in source
    assert "camera_spec.horizontal_fov_rad" in source
    assert "camera_spec.clipping_range_m" in source
    assert 'output / "runtime_frames.jsonl"' in source
    assert 'output / "supervision_frames.jsonl"' in source
    assert '"NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"' in source
    assert '"local_simplified_robot_used": False' in source
    assert '"dataset_benchmark_source_sha256": sha256_file(__file__)' in source
    assert '"--static-perception-audit"' in source
    assert "_freeze_cylinders_for_static_perception_audit(stage)" in source
    assert '"CALIBRATION_ONLY_STATIC_PERCEPTION"' in source
    assert '"student_training_eligible": (' in source
    assert "not ARGS.static_perception_audit" in source
    assert "and not ARGS.shadow_rollout" in source
    assert '"training_eligible": (' in source
    assert source.count("and not ARGS.shadow_rollout") >= 2


def test_isaac_tolerance_probe_offsets_only_calibration_target_not_scene_truth() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert '"--calibration-offset-xyz-m"' in source
    assert "CALIBRATION_OFFSET_XYZ_M" in source
    assert "commanded_target_center = target_live_center + calibration_offset" in source
    assert "contact_goal = commanded_target_center + np.asarray(" in source
    assert '"CALIBRATION_ONLY_INITIALIZATION_NOT_POLICY_INPUT"' in source
    assert "target_live_center +=" not in source


def test_isaac_probe_same_process_reset_is_physical_and_fail_closed() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert '"--same-process-reset-gate"' in source
    assert "prim.set_world_poses(" in source
    assert "prim.set_velocities(" in source
    assert "minimum_settling_steps = 120" in source
    assert "jog = _step_pose(robot, jog_goal, steps=120)" in source
    assert "minimum_hand_jog_motion_m = 0.020" in source
    assert "maximum_allowed_object_jog_motion_m = 0.001" in source
    assert "prim.set_enabled_gravities(False)" in source
    assert "prim.set_sleep_thresholds(reset_jog_sleep_threshold)" in source
    assert "prim.get_sleep_thresholds())[0][0]" in source
    assert "prim.set_enabled_gravities(original_gravity_enabled[entity])" in source
    assert "prim.set_sleep_thresholds(original_sleep_thresholds[entity])" in source
    assert "RESET_INFRASTRUCTURE_GRAVITY_ISOLATED_JOG_AFTER_" in source
    assert "and settling_stable" in source
    assert (
        "maximum_object_jog_motion_m <= maximum_allowed_object_jog_motion_m"
        in source
    )
    assert "and same_process_reset_pass" in source
    assert '"RESET_INFRASTRUCTURE_SUPERVISION_NOT_POLICY_INPUT"' in source


def test_isaac_probe_detach_gate_checks_relative_decoupling() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert "attachment_absent_after_detach" in source
    assert "detached_object_motion - detached_hand_motion" in source
    assert "minimum_decoupled_relative_change_m = 0.020" in source
    assert "minimum_detach_jog_m = 0.020" in source
    assert "ADR0013_ACCEPTANCE3_GATE4_RELATIVE_DECOUPLING" in source
    assert "detached_object_motion_m <= 0.01" not in source


def test_isaac_probe_m2b_failures_change_physical_state_before_recovery() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert '"--m2b-inject-empty-grasp"' in source
    assert '"--m2b-inject-release-failure"' in source
    assert '"--m2b-task-target-object"' in source
    assert "empty_feedback, empty_broker = broker_from_window(empty_samples)" in source
    assert "not empty_feedback.grasp_success" in source
    assert "empty_attachment_absent" in source
    assert "np.linalg.norm(empty_object_delta)) <= 0.005" in source
    assert "attachment_remained = stage.GetPrimAtPath(ATTACH_JOINT_PATH).IsValid()" in source
    assert "np.linalg.norm(release_object_delta)) >= 0.01" in source
    assert "release_follow_error_m <= 0.02" in source
    assert 'else "NOT_CAPTURED_BY_ACTUATION_PROBE"' in source
    assert '"training_eligible": bool(' in source
    assert "and m2b_injection_pass" in source
    assert '"broker_attached_actual_contact"' in source
    assert '"reassociate_target_executed": bool(' in source
    assert '"regrasp_target_executed": bool(' in source


def test_isaac_probe_m2b_public_predicates_use_rgbd_not_truth() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert '"--m2b-capture-public-rgbd"' in source
    assert '"--m2b-task-target-public-color"' in source
    assert "GeometricRGBDBaseline(" in source
    assert "select_task_target_track(" in source
    assert "infer_empty_grasp_predicates(" in source
    assert "infer_occlusion_aware_wrong_object_predicates(" in source
    assert "infer_occlusion_aware_release_failure_predicates(" in source
    assert "except ValueError as error:" in source
    assert "PUBLIC_TARGET_TRACK_MISSING" in source
    assert '"public_observation_rejection": empty_public_rejection' in source
    assert '"simulator_truth_policy_input": False' in source


def test_isaac_stage_builder_ports_sdf_velocity_decay_to_physx() -> None:
    source = (SCRIPTS / "isaac_m1b_dataset_benchmark.py").read_text()
    assert "PhysxSchema.PhysxRigidBodyAPI.Apply(link_prim)" in source
    assert "CreateLinearDampingAttr().Set(" in source
    assert "CreateAngularDampingAttr().Set(" in source
    assert "CreateSleepThresholdAttr().Set(" in source
    assert '"rigid_body_damping": rigid_body_damping' in source
    assert "_create_sdf_default_physics_material(stage)" in source
    assert "CreateStaticFrictionAttr().Set(" in source
    assert "CreateDynamicFrictionAttr().Set(" in source
    assert 'UsdShade.Tokens.weakerThanDescendants,\n        "physics",' in source


def test_isaac_probe_reuses_s1_pose_error_gate_before_attach() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert "PRODUCTION_EE_POSITION_ERROR_GATE_M = 0.020" in source
    assert '"S1_VERIFIED_MOVEIT_EXECUTION_EE_POSITION_ERROR_GATE"' in source
    assert "if attempt_feedback.grasp_success and motion_gate[\"passed\"]:" in source
    assert 'evidence["status"] = (' in source
    assert '"POSE_GATE_REJECTED"' in source
    assert "if selected_contact_goal is None:" in source


def test_isaac_probe_ports_adr0016b_two_stage_preclose() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert "M1B_PRECLOSE_PUBLIC_DIAMETER_MARGIN_M = 0.011" in source
    assert "M1B_SOURCE_FALLBACK_FINGER_BOARD_THICKNESS_M = 0.006" in source
    assert "NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M = 0.0" in source
    assert "NVIDIA_DEFAULT_COLLISION_INNER_FACE_BOUND_ABS_MAX_M = 0.000084" in source
    assert "M1B_CLOSE_SQUEEZE_M = 0.002" in source
    assert "calibration_perceived_diameter_m = 2.0 * target_collision.radius" in source
    assert "steps=M1B_PRECLOSE_STEPS" in source
    assert "steps=M1B_PRECLOSE_SETTLE_STEPS" in source
    assert "(close_target_m, M1B_TERMINAL_CLOSE_STEPS)" in source
    assert "(close_target_m, M1B_POST_CLOSE_OBSERVATION_STEPS)" in source
    assert '"ADR0016B_TWO_STAGE_PUBLIC_DIAMETER_PRECLOSE"' in source
    assert '"--preclose-before-contact-descent"' in source
    assert '"PREGRASP_BEFORE_CONTACT_DESCENT"' in source
    assert '"AT_CONTACT_BEFORE_TERMINAL_CLOSE"' in source
    assert (
        '"CALIBRATION_ONLY_SDF_CLASS_GEOMETRY_NOT_POLICY_INPUT"' in source
    )
    assert "load_m1b_gripper_effort_limit(ARGS.urdf)" in source
    assert "ISAACLAB_FRANKA_HAND_STIFFNESS_N_PER_M = 2_000.0" in source
    assert "ISAACLAB_FRANKA_HAND_DAMPING_N_S_PER_M = 100.0" in source
    assert "robot.set_dof_gains(" in source
    assert "robot.set_dof_max_efforts(source_aligned_max_efforts)" in source
    assert (
        '"PINNED_NVIDIA_ISAACLAB_FRANKA_HAND_GAINS_WITH_"\n'
        '                "HASH_LOCKED_PRODUCTION_URDF_EFFORT_CAP"'
    ) in source
    assert "def _json_native_usd_metadata(" in source
    assert "Vt.StringArray" in source
    assert "official_asset_contract = _json_native_usd_metadata(" in source


def test_isaac_probe_uses_adr0016_free_gap_yaw_without_policy_truth() -> None:
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert '"--calibration-free-gap-yaw"' in source
    assert '"--calibration-free-gap-yaw-override-rad"' in source
    assert "select_free_gap_yaw_from_xy(" in source
    assert "CALIBRATION_ONLY_SAFE_GRID_OVERRIDE_NOT_POLICY_INPUT" in source
    assert "SAFE_GRID_FIRST_POSE_FEASIBLE_BY_" in source
    assert "closed_gripper_during_scan" in source
    assert "NOT_EXECUTED_ORIENTATION_FEASIBILITY_GATE_REJECTED" in source
    assert '"CALIBRATION_LIVE_SUPERVISION_FREE_GAP_GEOMETRY"' in source
    assert "def _restore_calibration_scene_after_orientation_scan(" in source
    assert "CALIBRATION_ONLY_ORIENTATION_SCAN_SCENE_RESTORATION_" in source
    assert '"orientation_scan_scene_restoration"' in source
    assert "minimum_settling_steps = 120" in source
    assert "stability_displacement_limit_m = 0.00025" in source
    assert "def _wait_for_natural_scene_stability(" in source
    assert '"--natural-scene-stability-audit"' in source
    assert "SDF_DERIVED_PHYSICS_NATURAL_GRAVITY_SETTLING_" in source
    assert '"gravity_disabled": False' in source
    assert '"velocities_zeroed": False' in source
    assert '"sleep_threshold_modified": False' in source
    assert '"initial_scene_natural_stability"' in source
    assert '"scene-stability-diagnostic.json"' in source
    assert "m1b_diagnostic_contact_sensor" not in source
    assert '"target_object_diagnostic_only"' not in source
    assert '"restore_error_is_acceptance_gate": False' in source
    assert "target_reobserved_after_orientation_scan" in source
    assert "prim.set_world_poses(" in source
    assert "prim.set_velocities(" in source
    assert "isaac_top_down_orientation_wxyz(" in source
    assert isaac_top_down_orientation_wxyz(0.0) == pytest.approx(
        (0.0, 1.0, 0.0, 0.0)
    )
    assert isaac_top_down_orientation_wxyz(np.pi / 2) == pytest.approx(
        (0.0, np.sqrt(0.5), np.sqrt(0.5), 0.0)
    )
    result = select_free_gap_yaw_from_xy(
        [0.0, 0.0],
        [[0.0, -0.07], [0.0, 0.07]],
        source="CALIBRATION_TEST_ONLY",
    )
    assert len(result["candidates"]) == 12
    assert result["selected_yaw_rad"] == pytest.approx(np.pi / 2)
    assert result["clearance_ok"] is True
    assert result["source"] == "CALIBRATION_TEST_ONLY"
    ranked = rank_clearance_safe_yaw_candidates(result)
    assert ranked[0]["yaw_rad"] == pytest.approx(np.pi / 2)
    assert all(candidate["min_clearance_m"] >= 0.005 for candidate in ranked)


def test_public_yaw_ik_scan_never_admits_clearance_rejection() -> None:
    ranked = rank_clearance_safe_yaw_candidates(
        {
            "candidates": [
                {"yaw_rad": 0.0, "min_clearance_m": 0.0049},
                {"yaw_rad": 0.2, "min_clearance_m": 0.02},
                {"yaw_rad": 0.1, "min_clearance_m": 0.02},
            ]
        }
    )
    assert ranked == [
        {"yaw_rad": 0.1, "min_clearance_m": 0.02},
        {"yaw_rad": 0.2, "min_clearance_m": 0.02},
    ]
    source = (SCRIPTS / "isaac_m1b_actuation_probe.py").read_text()
    assert "rank_clearance_safe_yaw_candidates(yaw)" in source
    assert "PREGRASP_IK_GATE_REJECTED" in source
    assert "<= PRODUCTION_EE_POSITION_ERROR_GATE_M" in source
    unconstrained = select_free_gap_yaw_from_xy(
        [0.0, 0.0], [], source="PUBLIC_NO_NEIGHBORS"
    )
    assert len(rank_clearance_safe_yaw_candidates(unconstrained)) == 12


def test_isaac_tolerance_campaign_uses_writable_evidence_mount_and_validates_file() -> None:
    source = (SCRIPTS / "run_isaac_m1b_tolerance_campaign.py").read_text()
    assert "trial_dir.chmod(0o777)" in source
    assert 'f"--calibration-offset-xyz-m={offset}"' in source
    assert '"--calibration-free-gap-yaw"' in source
    assert '"grasp_yaw_contract"' in source
    assert "S1_20mm_PREGRASP_AND_CONTACT_POSE_GATES" in source
    assert "ADR0016B_H120_TWO_STAGE_OFFICIAL_Q20p5_PRECLOSE" in source
    assert "OFFICIAL_Q14_2mm_WINDOW_EDGE_SQUEEZE" in source
    assert "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q" in source
    assert "ADR0016B_REPORTED_CORRIDOR_VALID_SCENE3000_SLOTS_1_2_4" in source
    assert '"--ipc=host"' not in source
    assert '"--network=host"' not in source
    assert "prior_infrastructure_failures" in source
    assert '"prior_infrastructure_failure_count"' in source
    assert "evidence = _valid_trial_evidence(" in source
    assert "completed.returncode == 0" not in source
    assert '"actuation_probe_source_sha256": sha256_file(__file__)' in (
        SCRIPTS / "isaac_m1b_actuation_probe.py"
    ).read_text()
    assert "expected_probe_sha256=probe_sha256" in source
    assert '"campaign_runner_source_sha256": runner_sha256' in source


def test_isaac_tolerance_campaign_accepts_clean_preclose_pose_rejection() -> None:
    selected = {
        "source": (
            "ADR0016_SAFE_FREE_GAP_GRID_PLUS_S1_20MM_"
            "PREGRASP_AND_CONTACT_POSE_GATE"
        ),
        "selected": True,
        "candidates": [
            {
                "passed": True,
                "closed_gripper_during_scan": False,
            }
        ],
    }
    assert valid_orientation_gate_evidence(
        {"status": "PASS"},
        selected,
        {},
    )

    rejected = {
        **selected,
        "selected": False,
        "candidates": [
            {
                "passed": False,
                "closed_gripper_during_scan": False,
            }
        ],
    }
    rejected_payload = {
        "status": "POSE_GATE_REJECTED",
        "contact_feedback": {"grasp_success": False},
        "attached_entity": None,
        "attachment": None,
    }
    rejected_attempt = {
        "preclose": {"executed": False},
        "terminal_close": {"executed": False},
    }
    assert valid_orientation_gate_evidence(
        rejected_payload,
        rejected,
        rejected_attempt,
    )
    assert not valid_orientation_gate_evidence(
        rejected_payload,
        {
            **rejected,
            "candidates": [
                {
                    "passed": False,
                    "closed_gripper_during_scan": True,
                }
            ],
        },
        rejected_attempt,
    )
    assert not valid_orientation_gate_evidence(
        rejected_payload,
        rejected,
        {
            "preclose": {"executed": True},
            "terminal_close": {"executed": False},
        },
    )


def test_isaac_transition_builder_runs_public_rgbd_before_offline_truth_join(
    tmp_path: Path,
) -> None:
    front = tmp_path / "policy_rgbd"
    (front / "rgb").mkdir(parents=True)
    (front / "depth").mkdir()
    depth = np.full((64, 64), 0.45, dtype=np.float32)
    depth[24:34, 28:38] = 0.42
    rgb = np.full((64, 64, 3), 128, dtype=np.uint8)
    rgb[24:34, 28:38] = [220, 25, 25]
    for step in range(2):
        Image.fromarray(rgb).save(front / "rgb" / f"{step:06d}.png")
        np.save(front / "depth" / f"{step:06d}.npy", depth)

    runtime = []
    truth = []
    for step in range(2):
        frame = _isaac_runtime_frame(step)
        # The synthetic fixture is 64x64; only the principal point changes.
        frame.policy_camera.camera_intrinsics = [
            100.0,
            0.0,
            32.0,
            0.0,
            100.0,
            32.0,
            0.0,
            0.0,
            1.0,
        ]
        runtime.append(frame.model_dump_json())
        truth.append(
            IsaacM1BSupervisionFrameV1(
                episode_id=frame.episode_id,
                step_id=frame.step_id,
                timestamp_ns=frame.timestamp_ns,
                perfect_object_poses_world_xyzw={
                    "cylinder_01": [0.0, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0]
                },
            ).model_dump_json()
        )
    (tmp_path / "runtime_frames.jsonl").write_text("\n".join(runtime) + "\n")
    (tmp_path / "supervision_frames.jsonl").write_text("\n".join(truth) + "\n")
    runtime_path = tmp_path / "runtime_frames.jsonl"
    supervision_path = tmp_path / "supervision_frames.jsonl"
    (tmp_path / "metrics.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "capture_mode": "DYNAMIC_STUDENT_DATASET",
                "dataset_benchmark_source_sha256": hashlib.sha256(
                    (SCRIPTS / "isaac_m1b_dataset_benchmark.py").read_bytes()
                ).hexdigest(),
                "robot_asset": {
                    "provenance": (
                        "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"
                    ),
                    "local_simplified_robot_used": False,
                    "variants": {
                        "Gripper": "Default",
                        "Mesh": "Performance",
                    },
                },
                "student_dataset_protocol": {
                    "runtime_frames_sha256": hashlib.sha256(
                        runtime_path.read_bytes()
                    ).hexdigest(),
                    "supervision_frames_sha256": hashlib.sha256(
                        supervision_path.read_bytes()
                    ).hexdigest(),
                    "streams_physically_separate": True,
                    "policy_segmentation_input": False,
                    "teacher_required": False,
                    "training_eligible": True,
                },
            }
        )
        + "\n"
    )
    output = tmp_path / "episode_transitions.jsonl"
    xy_correction = tmp_path / "xy-correction.json"
    xy_correction.write_text(
        json.dumps(
            {
                "schema_version": "M1BPublicGeometryXYCorrectionV1",
                "feature_order": [
                    "bias",
                    "surface_optical_x_m",
                    "surface_optical_y_m",
                    "surface_optical_z_m",
                    "perceived_diameter_m",
                    "public_orientation_is_tilted",
                ],
                "signed_residual_coefficients_world_xy": {
                    "x": [0.0] * 6,
                    "y": [0.0] * 6,
                },
                "training_input_sha256": "a" * 64,
                "truth_boundary": (
                    "simulator supervision is training-only; runtime uses "
                    "public RGB-D geometry and public orientation_state only"
                ),
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_isaac_m1b_transitions.py"),
            "--dataset-root",
            str(tmp_path),
            "--output",
            str(output),
            "--xy-correction",
            str(xy_correction),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    transition = EpisodeTransitionV0.model_validate_json(output.read_text())
    assert transition.teacher_response is None
    assert transition.observation_before.object_tracks
    assert "cylinder_01" not in transition.observation_before.model_dump_json()
    metrics = json.loads((tmp_path / "transition_metrics.json").read_text())
    assert metrics["status"] == "PASS"
    assert len(metrics["transition_builder_source_sha256"]) == 64
    assert metrics["transitions"] == 1
    assert metrics["teacher_response_nonnull"] == 0
    assert metrics["policy_segmentation_uri_nonnull"] == 0
    assert metrics["capture_mode"] == "DYNAMIC_STUDENT_DATASET"
    assert metrics["student_training_eligible"] is True
    assert len(metrics["public_xy_correction_fingerprint"]) == 64
    assert metrics["public_xy_correction_runtime_enabled"] is True
    assert (
        metrics["tilted_center_support_offset"]
        == "PUBLIC_PERCEIVED_RADIUS"
    )
    assert (
        metrics["center_xy_projection"]
        == (
            "PUBLIC_RAY_PLANE_WORLD_X_PLUS_"
            "VISIBLE_SURFACE_RADIUS_WORLD_Y"
        )
    )
    assert metrics["official_robot_variants"] == {
        "Gripper": "Default",
        "Mesh": "Performance",
    }
    assert _validate_transition_metrics(tmp_path, output)["status"] == "PASS"

    teacher_payload = transition.model_dump(mode="json")
    teacher_payload["teacher_response"] = {
        "schema_version": "TeacherResponseV0",
        "status": "MOCK",
    }
    teacher_stream = tmp_path / "teacher_transitions.jsonl"
    teacher_stream.write_text(json.dumps(teacher_payload) + "\n")
    with pytest.raises(ValueError, match="TeacherResponse is forbidden"):
        _read_transitions(teacher_stream)

    segmentation_payload = transition.model_dump(mode="json")
    segmentation_payload["observation_before"]["segmentation_uri"] = (
        "dataset://policy_rgbd/instance/000000.png"
    )
    segmentation_stream = tmp_path / "segmentation_transitions.jsonl"
    segmentation_stream.write_text(json.dumps(segmentation_payload) + "\n")
    with pytest.raises(ValueError, match="policy segmentation is forbidden"):
        _read_transitions(segmentation_stream)

    invalid_transition_metrics = json.loads(
        (tmp_path / "transition_metrics.json").read_text()
    )
    invalid_transition_metrics["official_robot_variants"]["Gripper"] = (
        "AlternateFinger"
    )
    (tmp_path / "transition_metrics.json").write_text(
        json.dumps(invalid_transition_metrics) + "\n"
    )
    with pytest.raises(ValueError, match="Teacher-free official"):
        _validate_transition_metrics(tmp_path, output)


def test_isaac_public_perception_audit_stays_offline_and_requires_isaac_envelope() -> None:
    source = (SCRIPTS / "evaluate_isaac_m1b_perception_gate.py").read_text()
    assert 'action="append"' in source
    assert '"datasets": [' in source
    assert 'payload.get("trial_count_valid") != 81' in source
    assert "TeacherResponse is forbidden" in source
    assert "_validate_transition_metrics(" in source
    assert '"perception_gate_source_sha256"' in source
    assert '"--require-static-perception-audit"' in source
    assert '"CALIBRATION_ONLY_STATIC_PERCEPTION"' in source
    before = _isaac_runtime_frame(0)
    after = _isaac_runtime_frame(1)
    truth_pose = [0.1, 0.2, 0.48915, 0.0, 0.0, 0.0, 1.0]
    supervision = [
        IsaacM1BSupervisionFrameV1(
            episode_id=before.episode_id,
            step_id=before.step_id,
            timestamp_ns=before.timestamp_ns,
            perfect_object_poses_world_xyzw={"cylinder_01": truth_pose},
        ),
        IsaacM1BSupervisionFrameV1(
            episode_id=after.episode_id,
            step_id=after.step_id,
            timestamp_ns=after.timestamp_ns,
            perfect_object_poses_world_xyzw={"cylinder_01": truth_pose},
        ),
    ]
    transition = build_transition(
        before,
        after,
        [_public_result(0)],
        [_public_result(1)],
        supervision[1],
        table_supported_center_offset_m=0.03915,
        table_support_world_z_bounds_m=(0.43, 0.47),
        selected_public_track_id="track-1234abcd",
    )

    audit_only = evaluate(
        [transition],
        supervision,
        max_association_distance_m=0.06,
        tolerance_envelope_m=None,
    )
    assert audit_only["status"] == "ACTUAL_ISAAC_RGBD_AUDIT_COMPLETE_GATE_PENDING"
    assert audit_only["matched_truth_recall"] == 1.0
    assert audit_only["p90_abs_error_world_xyz_m"] == pytest.approx(
        {"x": 0.0, "y": 0.0, "z": 0.0}
    )
    assert audit_only["gate"]["status"] == "AUDIT_ONLY_NO_ISAAC_TOLERANCE_ENVELOPE"

    gated = evaluate(
        [transition],
        supervision,
        max_association_distance_m=0.06,
        tolerance_envelope_m={"x": 0.01, "y": 0.01, "z": 0.01},
    )
    assert gated["status"] == "GO"
    assert gated["gate"]["axis_pass"] == {"x": True, "y": True, "z": True}
    shifted_supervision = [
        frame.model_copy(
            update={
                "perfect_object_poses_world_xyzw": {
                    "cylinder_01": [
                        0.101,
                        *truth_pose[1:],
                    ]
                }
            }
        )
        for frame in supervision
    ]
    zero_envelope = evaluate(
        [transition],
        shifted_supervision,
        max_association_distance_m=0.06,
        tolerance_envelope_m={"x": 0.0, "y": 0.01, "z": 0.01},
    )
    assert zero_envelope["status"] == "NO_GO"
    assert zero_envelope["gate"]["all_envelope_axes_nonzero"] is False
    assert zero_envelope["gate"]["axis_pass"]["x"] is False
    zero_envelope_with_zero_error = evaluate(
        [transition],
        supervision,
        max_association_distance_m=0.06,
        tolerance_envelope_m={"x": 0.0, "y": 0.01, "z": 0.01},
    )
    assert zero_envelope_with_zero_error["gate"]["axis_pass"]["x"] is True
    assert zero_envelope_with_zero_error["status"] == "NO_GO"


def test_isaac_public_truth_assignment_maximizes_cardinality_before_distance() -> None:
    public_tracks = [
        ObjectTrackV0(
            object_id="track-11111111",
            category="industrial_cylinder",
            pose=[0.01, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0],
            confidence=0.9,
        ),
        ObjectTrackV0(
            object_id="track-22222222",
            category="industrial_cylinder",
            pose=[0.04, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0],
            confidence=0.9,
        ),
    ]
    matches = optimal_public_truth_assignment(
        public_tracks,
        {
            "cylinder_01": [0.0, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0],
            "cylinder_02": [0.05, 0.0, 0.49, 0.0, 0.0, 0.0, 1.0],
        },
        max_distance_m=0.03,
    )
    assert [(track.object_id, entity) for track, entity, _ in matches] == [
        ("track-11111111", "cylinder_01"),
        ("track-22222222", "cylinder_02"),
    ]


def test_isaac_tolerance_worklist_is_81_trials_and_crosses_three_objects() -> None:
    trials = isaac_tolerance_worklist()
    assert len(trials) == 81
    assert {trial["axis"] for trial in trials} == {"x", "y", "z"}
    assert {float(trial["offset_m"]) for trial in trials} == {
        0.0,
        -0.005,
        0.005,
        -0.010,
        0.010,
        -0.015,
        0.015,
        -0.020,
        0.020,
    }
    for axis in ("x", "y", "z"):
        for offset_m in {
            0.0,
            -0.005,
            0.005,
            -0.010,
            0.010,
            -0.015,
            0.015,
            -0.020,
            0.020,
        }:
            point = [
                trial
                for trial in trials
                if trial["axis"] == axis and trial["offset_m"] == offset_m
            ]
            assert {trial["target_object"] for trial in point} == {
                "cylinder_01",
                "cylinder_02",
                "cylinder_04",
            }


def test_isaac_tolerance_summary_uses_signed_monotonic_closure(tmp_path: Path) -> None:
    trials = isaac_tolerance_worklist()
    records = [
        {
            **trial,
            "status": "PASS",
            "success": not (
                trial["axis"] == "x" and float(trial["offset_m"]) == 0.020
            ),
        }
        for trial in trials
    ]
    stage = tmp_path / "physics.usdc"
    stage.write_bytes(b"official-isaac-stage")
    summary = summarize_isaac_tolerance(
        trials,
        records,
        stage=stage,
        contact_centerline_m=0.120,
        probe_sha256="probe-sha256",
        runner_sha256="runner-sha256",
    )
    assert summary["status"] == "COMPLETE_CALIBRATION_ONLY"
    assert summary["tolerance_envelope_m"] == {
        "x": 0.015,
        "y": 0.020,
        "z": 0.020,
    }
    assert summary["point_results"]["x:+0.020"]["pass"] is False


def test_isaac_dual_runner_requires_two_distinct_gpus_and_parses_smi() -> None:
    source = (SCRIPTS / "run_isaac_m1b_dual_benchmark.py").read_text()
    assert "_stop_owned_workers(" in source
    assert 'f"{container_prefix}-worker{worker_id}"' in source
    assert "SERIALIZED_KIT_INITIALIZATION_THEN_SHARED_START_BARRIER" in source
    assert "expected_source_sha256=dataset_benchmark_sha256" in source
    assert '{"Gripper": "Default", "Mesh": "Performance"}' in source
    assert '"dual_runner_source_sha256": dual_runner_sha256' in source
    assert '"--ipc=host"' not in source
    assert '"--network=host"' not in source
    assert parse_gpu_indices("0,1") == (0, 1)
    with pytest.raises(Exception, match="two distinct"):
        parse_gpu_indices("0,0")
    samples = parse_smi_csv(
        "0, 2048, 55, 120.5\n"
        "1, 3072, 65, 130.5\n"
        "not,a,valid,row\n"
    )
    assert samples == [
        {
            "gpu_index": 0,
            "memory_used_mib": 2048.0,
            "utilization_gpu_percent": 55.0,
            "power_draw_w": 120.5,
        },
        {
            "gpu_index": 1,
            "memory_used_mib": 3072.0,
            "utilization_gpu_percent": 65.0,
            "power_draw_w": 130.5,
        },
    ]
    summary = summarize_gpu_samples(samples, (0, 1))
    assert summary["0"]["memory_used_mib_peak"] == 2048.0
    assert summary["1"]["utilization_gpu_percent_peak"] == 65.0
