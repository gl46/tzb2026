"""Isaac M1B frame contracts and Teacher-independent transition assembly.

The runtime and supervision records are intentionally separate.  Runtime
records contain only policy-visible sensor calibration, robot state, and the
commanded action.  Simulator entity poses enter only the offline supervision
record used to assemble ``EpisodeTransitionV0`` training/evaluation samples.
"""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.contracts.models import (
    ActionTrajectoryV0,
    CandidateSkillV0,
    EpisodeTransitionV0,
    ObjectTrackV0,
    ObservationV0,
    SimulatorSupervisionV0,
    SkillType,
    TargetConstraintsV0,
    TaskSpecV0,
)
from xh_agent.perception.interfaces import PerceptionResultV1
from xh_agent.runtime.m1b_center_correction import (
    M1BPublicGeometryXYCorrectionV1,
)


PANDA_DOF_NAMES = tuple(
    [f"panda_joint{index}" for index in range(1, 8)]
    + ["panda_finger_joint1", "panda_finger_joint2"]
)
PANDA_DOF_UNITS = "radian_arm_metre_finger"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class IsaacM1BPolicyCameraFrameV1(StrictModel):
    schema_version: Literal["IsaacM1BPolicyCameraFrameV1"] = (
        "IsaacM1BPolicyCameraFrameV1"
    )
    name: Literal["policy_rgbd"] = "policy_rgbd"
    rgb_uri: str
    depth_uri: str
    camera_intrinsics: list[float] = Field(min_length=9, max_length=9)
    camera_to_world_optical: list[float] = Field(min_length=16, max_length=16)
    depth_semantics: Literal["METRIC_DISTANCE_TO_IMAGE_PLANE"] = (
        "METRIC_DISTANCE_TO_IMAGE_PLANE"
    )

    @model_validator(mode="after")
    def finite_calibration(self) -> "IsaacM1BPolicyCameraFrameV1":
        values = [*self.camera_intrinsics, *self.camera_to_world_optical]
        if not all(isfinite(value) for value in values):
            raise ValueError("camera calibration may not contain NaN or Inf")
        if self.camera_intrinsics[0] <= 0 or self.camera_intrinsics[4] <= 0:
            raise ValueError("camera focal lengths must be positive")
        return self


class IsaacM1BRuntimeFrameV1(StrictModel):
    """One policy-visible Isaac frame with no simulator object truth."""

    schema_version: Literal["IsaacM1BRuntimeFrameV1"] = "IsaacM1BRuntimeFrameV1"
    episode_id: str
    step_id: int = Field(ge=0)
    timestamp_ns: int = Field(ge=0)
    policy_camera: IsaacM1BPolicyCameraFrameV1
    joint_names: list[str] = Field(min_length=9, max_length=9)
    joint_position: list[float] = Field(min_length=9, max_length=9)
    joint_velocity: list[float] = Field(min_length=9, max_length=9)
    end_effector_pose_world_xyzw: list[float] = Field(min_length=7, max_length=7)
    gripper_state: Literal["open", "closed", "partially_open"]
    action_target_joint_position: list[float] = Field(min_length=9, max_length=9)
    action_frequency_hz: Literal[30.0] = 30.0
    action_normalization: Literal["identity"] = "identity"

    @model_validator(mode="after")
    def explicit_finite_action_protocol(self) -> "IsaacM1BRuntimeFrameV1":
        if tuple(self.joint_names) != PANDA_DOF_NAMES:
            raise ValueError(
                f"joint_names must be the explicit Panda order {PANDA_DOF_NAMES}"
            )
        values = [
            *self.joint_position,
            *self.joint_velocity,
            *self.end_effector_pose_world_xyzw,
            *self.action_target_joint_position,
        ]
        if not all(isfinite(value) for value in values):
            raise ValueError("runtime robot state/action may not contain NaN or Inf")
        return self


class IsaacM1BSupervisionFrameV1(StrictModel):
    """Offline-only simulator truth, stored separately from runtime frames."""

    schema_version: Literal["IsaacM1BSupervisionFrameV1"] = (
        "IsaacM1BSupervisionFrameV1"
    )
    training_and_evaluation_only: Literal[True] = True
    episode_id: str
    step_id: int = Field(ge=0)
    timestamp_ns: int = Field(ge=0)
    perfect_object_poses_world_xyzw: dict[
        str, list[float]
    ]
    contacts: list[dict[str, object]] = Field(default_factory=list)
    collisions: list[dict[str, object]] = Field(default_factory=list)
    grasp_states: dict[str, bool] = Field(default_factory=dict)
    slip_events: list[dict[str, object]] = Field(default_factory=list)
    task_success: bool = False
    physical_parameters: dict[str, float] = Field(default_factory=dict)
    failure_injection: dict[str, object] = Field(default_factory=dict)
    simulator: Literal["Isaac Sim"] = "Isaac Sim"
    simulator_version: Literal["6.0.1"] = "6.0.1"

    @model_validator(mode="after")
    def finite_pose_truth(self) -> "IsaacM1BSupervisionFrameV1":
        for entity, pose in self.perfect_object_poses_world_xyzw.items():
            if len(pose) != 7 or not all(isfinite(value) for value in pose):
                raise ValueError(f"invalid perfect pose for {entity}")
        return self


def transform_optical_point(
    camera_to_world_optical: list[float],
    point_optical_m: list[float] | tuple[float, float, float],
) -> list[float]:
    """Apply a conventional row-major, column-vector 4x4 transform."""

    if len(camera_to_world_optical) != 16 or len(point_optical_m) != 3:
        raise ValueError("expected a 4x4 transform and a three-dimensional point")
    x, y, z = point_optical_m
    matrix = camera_to_world_optical
    output = [
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    ]
    if not all(isfinite(value) for value in output):
        raise ValueError("transformed point is non-finite")
    return output


def intersect_pixel_ray_with_world_z(
    camera: IsaacM1BPolicyCameraFrameV1,
    *,
    pixel_u: float,
    pixel_v: float,
    world_z_m: float,
) -> list[float]:
    """Intersect one public image ray with an observation-derived world-Z plane."""

    values = [pixel_u, pixel_v, world_z_m]
    if not all(isfinite(value) for value in values):
        raise ValueError("pixel-ray intersection inputs must be finite")
    intrinsics = camera.camera_intrinsics
    transform = camera.camera_to_world_optical
    ray_optical = [
        (pixel_u - intrinsics[2]) / intrinsics[0],
        (pixel_v - intrinsics[5]) / intrinsics[4],
        1.0,
    ]
    ray_world = [
        transform[0] * ray_optical[0]
        + transform[1] * ray_optical[1]
        + transform[2],
        transform[4] * ray_optical[0]
        + transform[5] * ray_optical[1]
        + transform[6],
        transform[8] * ray_optical[0]
        + transform[9] * ray_optical[1]
        + transform[10],
    ]
    camera_origin_world = [transform[3], transform[7], transform[11]]
    if abs(ray_world[2]) <= 1e-9:
        raise ValueError("public image ray is parallel to the world-Z plane")
    distance = (world_z_m - camera_origin_world[2]) / ray_world[2]
    if not isfinite(distance) or distance <= 0:
        raise ValueError("public image ray intersects behind the camera")
    return [
        camera_origin_world[0] + distance * ray_world[0],
        camera_origin_world[1] + distance * ray_world[1],
        world_z_m,
    ]


def _perceived_diameter_m(
    result: PerceptionResultV1,
    camera_intrinsics: list[float],
) -> float:
    focal = min(float(camera_intrinsics[0]), float(camera_intrinsics[4]))
    pixel_diameter = min(result.bbox_or_mask.width, result.bbox_or_mask.height)
    depth = float(result.position_3d[2])
    if focal <= 0 or pixel_diameter <= 0 or depth <= 0:
        raise ValueError("invalid public geometry for perceived diameter")
    return pixel_diameter * depth / focal


def public_results_to_tracks(
    results: list[PerceptionResultV1],
    camera: IsaacM1BPolicyCameraFrameV1,
    *,
    table_supported_center_offset_m: float,
    table_support_world_z_bounds_m: tuple[float, float],
    public_xy_correction: M1BPublicGeometryXYCorrectionV1 | None = None,
) -> tuple[list[ObjectTrackV0], list[dict[str, str]]]:
    """Convert public RGB-D results to world-frame tracks without simulator truth.

    The geometric baseline does not estimate a continuous orientation
    quaternion.  The required ObjectTrack quaternion is therefore an explicit
    identity sentinel; the public coarse orientation is retained in the
    relation graph and provenance instead of inventing an unmeasured rotation.
    """

    if not 0 < table_supported_center_offset_m < 0.2:
        raise ValueError("table-supported centre offset is outside the M1B class band")
    lower_support_z, upper_support_z = table_support_world_z_bounds_m
    if not (
        isfinite(lower_support_z)
        and isfinite(upper_support_z)
        and lower_support_z < upper_support_z
    ):
        raise ValueError("table support Z bounds must be finite and ordered")
    tracks: list[ObjectTrackV0] = []
    relations: list[dict[str, str]] = []
    for result in results:
        diameter_m = _perceived_diameter_m(result, camera.camera_intrinsics)
        quality = result.covariance_or_quality
        support_optical = [
            float(quality[f"support_plane_optical_{axis}_m"])
            for axis in ("x", "y", "z")
        ]
        support_world = transform_optical_point(
            camera.camera_to_world_optical,
            support_optical,
        )
        if not lower_support_z <= support_world[2] <= upper_support_z:
            raise ValueError(
                f"public support Z {support_world[2]} is outside the admitted workspace"
            )
        support_offset_m = (
            diameter_m / 2.0
            if result.orientation_state == "tilted"
            else table_supported_center_offset_m
        )
        ray_centre_world = intersect_pixel_ray_with_world_z(
            camera,
            pixel_u=float(quality["component_centroid_u_px"]),
            pixel_v=float(quality["component_centroid_v_px"]),
            world_z_m=support_world[2] + support_offset_m,
        )
        visible_surface_centre_optical = [
            float(value) for value in result.position_3d
        ]
        visible_surface_centre_optical[2] += diameter_m / 2.0
        visible_surface_centre_world = transform_optical_point(
            camera.camera_to_world_optical,
            visible_surface_centre_optical,
        )
        centre_world = [
            ray_centre_world[0],
            visible_surface_centre_world[1],
            ray_centre_world[2],
        ]
        if public_xy_correction is not None:
            centre_world = list(
                public_xy_correction.correct_xy(
                    tuple(centre_world),
                    surface_optical_m=tuple(
                        float(value) for value in result.position_3d
                    ),
                    perceived_diameter_m=diameter_m,
                    orientation_state=result.orientation_state,
                )
            )
        tracks.append(
            ObjectTrackV0(
                object_id=result.track_id,
                category=result.category,
                pose=[*centre_world, 0.0, 0.0, 0.0, 1.0],
                confidence=result.confidence,
            )
        )
        relations.append(
            {
                "subject": result.track_id,
                "predicate": "public_orientation_state",
                "object": result.orientation_state,
            }
        )
        relations.append(
            {
                "subject": result.track_id,
                "predicate": "public_center_support_offset",
                "object": (
                    "perceived_radius"
                    if result.orientation_state == "tilted"
                    else "class_half_length"
                ),
            }
        )
        relations.append(
            {
                "subject": result.track_id,
                "predicate": "public_center_xy_projection",
                "object": (
                    "ray_plane_world_x_plus_"
                    "visible_surface_radius_world_y"
                ),
            }
        )
    return tracks, relations


def observation_from_runtime_frame(
    frame: IsaacM1BRuntimeFrameV1,
    results: list[PerceptionResultV1],
    *,
    table_supported_center_offset_m: float,
    table_support_world_z_bounds_m: tuple[float, float],
    current_task_id: str,
    public_xy_correction: M1BPublicGeometryXYCorrectionV1 | None = None,
) -> ObservationV0:
    tracks, relations = public_results_to_tracks(
        results,
        frame.policy_camera,
        table_supported_center_offset_m=table_supported_center_offset_m,
        table_support_world_z_bounds_m=table_support_world_z_bounds_m,
        public_xy_correction=public_xy_correction,
    )
    mean_confidence = (
        sum(track.confidence for track in tracks) / len(tracks) if tracks else 0.0
    )
    return ObservationV0(
        episode_id=frame.episode_id,
        step_id=frame.step_id,
        timestamp_ns=frame.timestamp_ns,
        rgb_uri=frame.policy_camera.rgb_uri,
        depth_uri=frame.policy_camera.depth_uri,
        # Isaac instance/semantic ground truth is deliberately not policy input.
        segmentation_uri=None,
        camera_intrinsics=frame.policy_camera.camera_intrinsics,
        camera_extrinsics=frame.policy_camera.camera_to_world_optical,
        joint_position=frame.joint_position,
        joint_velocity=frame.joint_velocity,
        end_effector_pose=frame.end_effector_pose_world_xyzw,
        gripper_state=frame.gripper_state,
        object_tracks=tracks,
        relation_graph=relations,
        current_task_id=current_task_id,
        current_subgoal="observe_dynamics",
        coordinate_frame="world",
        uncertainty=1.0 - mean_confidence,
    )


def build_transition(
    before: IsaacM1BRuntimeFrameV1,
    after: IsaacM1BRuntimeFrameV1,
    before_results: list[PerceptionResultV1],
    after_results: list[PerceptionResultV1],
    supervision_after: IsaacM1BSupervisionFrameV1,
    *,
    table_supported_center_offset_m: float,
    table_support_world_z_bounds_m: tuple[float, float],
    selected_public_track_id: str | None,
    public_xy_correction: M1BPublicGeometryXYCorrectionV1 | None = None,
) -> EpisodeTransitionV0:
    """Join one adjacent frame pair at the offline-only truth boundary."""

    if before.episode_id != after.episode_id:
        raise ValueError("runtime frame episode IDs do not match")
    if after.step_id != before.step_id + 1:
        raise ValueError("runtime frames must be adjacent")
    if (
        supervision_after.episode_id != after.episode_id
        or supervision_after.step_id != after.step_id
        or supervision_after.timestamp_ns != after.timestamp_ns
    ):
        raise ValueError("supervision frame does not match the after runtime frame")
    task_id = f"{before.episode_id}-observe-dynamics"
    observation_before = observation_from_runtime_frame(
        before,
        before_results,
        table_supported_center_offset_m=table_supported_center_offset_m,
        table_support_world_z_bounds_m=table_support_world_z_bounds_m,
        current_task_id=task_id,
        public_xy_correction=public_xy_correction,
    )
    observation_after = observation_from_runtime_frame(
        after,
        after_results,
        table_supported_center_offset_m=table_supported_center_offset_m,
        table_support_world_z_bounds_m=table_support_world_z_bounds_m,
        current_task_id=task_id,
        public_xy_correction=public_xy_correction,
    )
    if selected_public_track_id is not None and selected_public_track_id not in {
        track.object_id for track in observation_before.object_tracks
    }:
        raise ValueError("selected target is not present in the public before observation")
    target_constraints = (
        TargetConstraintsV0()
        if selected_public_track_id is not None
        else TargetConstraintsV0(category="industrial_cylinder")
    )
    return EpisodeTransitionV0(
        observation_before=observation_before,
        task_spec=TaskSpecV0(
            task_id=task_id,
            operation="observe_dynamics",
            target_object_id=selected_public_track_id,
            target_constraints=target_constraints,
            spatial_selector="minimum_world_x_from_public_rgbd",
            reference_frame="world",
            destination="same_scene",
            goal_predicates=["public_track_remains_observed"],
            constraints=["simulator truth unavailable to execution policy"],
            ambiguity_score=0.0 if selected_public_track_id is not None else 1.0,
            need_clarification=selected_public_track_id is None,
            source_instruction="Observe the leftmost industrial cylinder while moving.",
        ),
        candidate_skill=CandidateSkillV0(
            skill_type=SkillType.MOVE,
            target_object_id=selected_public_track_id,
            parameters={"dataset_excitation": True},
            coordinate_frame="PANDA_DOF_ORDER_BY_NAME",
            preconditions=["official Franka articulation initialized"],
            expected_effects=["new public RGB-D observation"],
            generated_by="ISAAC_DATASET_EXCITATION_NOT_POLICY",
            candidate_id=f"{before.episode_id}-move-{after.step_id:06d}",
        ),
        action_trajectory=ActionTrajectoryV0(
            embodiment="NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA",
            representation="joint_position_target",
            coordinate_frame="PANDA_DOF_ORDER_BY_NAME",
            units=PANDA_DOF_UNITS,
            fps=after.action_frequency_hz,
            values=[after.action_target_joint_position],
            dimension_names=after.joint_names,
            normalization_method=after.action_normalization,
            normalization_revision="isaac-m1b-joint-identity-v1",
            source_skill="MOVE",
            source_policy="ISAAC_DATASET_EXCITATION_NOT_POLICY",
        ),
        observation_after=observation_after,
        simulator_supervision=SimulatorSupervisionV0(
            perfect_object_poses=supervision_after.perfect_object_poses_world_xyzw,
            contacts=supervision_after.contacts,
            collisions=supervision_after.collisions,
            grasp_states=supervision_after.grasp_states,
            slip_events=supervision_after.slip_events,
            task_success=supervision_after.task_success,
            physical_parameters=supervision_after.physical_parameters,
            failure_injection=supervision_after.failure_injection,
            simulator=supervision_after.simulator,
            simulator_version=supervision_after.simulator_version,
        ),
        teacher_response=None,
        semantic_labels={
            "policy_perception": "geometric_rgbd_v1",
            "continuous_orientation_estimated": False,
            "coarse_orientation_location": "observation.relation_graph",
            "offline_segmentation_available": True,
        },
        task_progress=0.0,
        failure_type=None,
        provenance={
            "mode": "SIM_ONLY",
            "robot_asset": "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD",
            "local_simplified_robot_used": "false",
            "truth_boundary": (
                "runtime frame and RGB-D inference are policy-visible; matched "
                "supervision frame is joined offline and never passed to Student.predict"
            ),
            "teacher": "absent",
            "orientation_encoding": (
                "identity quaternion is an explicit no-continuous-estimate sentinel; "
                "public coarse state is in relation_graph"
            ),
        },
    )
