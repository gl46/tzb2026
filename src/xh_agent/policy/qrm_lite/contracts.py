"""QRM-Lite training and observation contracts.

Online policy inputs must never include simulator oracle fields.
SimulatorSupervision is training/eval only and lives on QRMTrainingSampleV1 labels.
"""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FailureType(str, Enum):
    NONE = "NONE"
    EMPTY_GRASP = "EMPTY_GRASP"
    WRONG_OBJECT = "WRONG_OBJECT"
    DROP_OR_SLIP = "DROP_OR_SLIP"
    UNSTABLE_PLACEMENT = "UNSTABLE_PLACEMENT"
    WRONG_CELL = "WRONG_CELL"
    RELEASE_FAILURE = "RELEASE_FAILURE"
    PATH_BLOCKED = "PATH_BLOCKED"
    TRACKING_LOST = "TRACKING_LOST"
    UNKNOWN = "UNKNOWN"


class FailureContextV1(StrictModel):
    schema_version: Literal["FailureContextV1"] = "FailureContextV1"
    last_skill: str | None = None
    expected_predicates: list[str] = Field(default_factory=list)
    observed_predicates: list[str] = Field(default_factory=list)
    predicate_residual: list[str] = Field(default_factory=list)
    failure_type: FailureType = FailureType.NONE
    retry_count: int = Field(default=0, ge=0)
    attempted_recoveries: list[str] = Field(default_factory=list)
    last_action_summary: str | None = None
    last_target_track_id: str | None = None


class HistoryStepV1(StrictModel):
    """Compact observation-state-action summary for in-context adaptation."""

    step_id: int = Field(ge=0)
    rgb_uri: str | None = None
    joint_position: list[float] = Field(default_factory=list)
    end_effector_pose: list[float] = Field(default_factory=list)
    action_summary: list[float] = Field(default_factory=list)
    skill_type: str | None = None


class PerceptionTrackV1(StrictModel):
    track_id: str
    category: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pose_xyzquat: list[float] | None = Field(default=None, min_length=7, max_length=7)
    crop_uri: str | None = None


class QRMObservationV1(StrictModel):
    schema_version: Literal["QRMObservationV1"] = "QRMObservationV1"
    episode_id: str
    step_id: int = Field(ge=0)
    timestamp_ns: int = Field(default=0, ge=0)
    instruction: str
    rgb_uri: str | None = None
    depth_uri: str | None = None
    multi_view_rgb_uris: list[str] = Field(default_factory=list)
    camera_frame: str = "camera_optical"
    camera_intrinsics: list[float] = Field(default_factory=list)  # 3x3 row-major
    camera_extrinsics_base_T_cam: list[float] = Field(default_factory=list)  # 4x4 row-major
    joint_position: list[float] = Field(default_factory=list)
    joint_velocity: list[float] = Field(default_factory=list)
    end_effector_pose_base: list[float] = Field(default_factory=list)  # xyz + quat wxyz
    gripper_state: float = Field(default=0.0, ge=0.0, le=1.0)
    current_skill_stage: str | None = None
    perception_tracks: list[PerceptionTrackV1] = Field(default_factory=list)
    history: list[HistoryStepV1] = Field(default_factory=list)
    failure_context: FailureContextV1 = Field(default_factory=FailureContextV1)

    @model_validator(mode="after")
    def reject_oracle_keys_in_tracks(self) -> "QRMObservationV1":
        # Soft guard: track ids must not look like gazebo entity oracles if flagged.
        for track in self.perception_tracks:
            if track.track_id.startswith("gazebo_perfect_"):
                raise ValueError("online observation may not carry gazebo perfect entity ids")
        return self


class CoarseIntentV1(StrictModel):
    schema_version: Literal["CoarseIntentV1"] = "CoarseIntentV1"
    skill_type: str
    target_track_id: str | None = None
    grasp_family: str = "unknown"
    recovery_mode: str = "none"
    reobserve_flag: bool = False
    orientation_goal: str | None = None
    coarse_translation_bins: list[int] = Field(default_factory=list)
    coarse_rotation_bins: list[int] = Field(default_factory=list)
    failure_type_aux: FailureType | None = None


class CameraFrameActionChunkV1(StrictModel):
    """T x D camera-frame residual/absolute action chunk.

    Default D=10:
      dx, dy, dz (m, camera optical)
      r6d_0..r6d_5 (continuous 6D rotation residual)
      gripper (0 open .. 1 closed)
    Convention:
      - translation is expressed in camera optical frame
      - rotation residual is local EE delta mapped into camera frame (right-multiply on EE)
      - chunk length and fps are explicit fields
    """

    schema_version: Literal["CameraFrameActionChunkV1"] = "CameraFrameActionChunkV1"
    coordinate_frame: Literal["camera_optical"] = "camera_optical"
    representation: Literal["delta_ee_cam_r6d_gripper"] = "delta_ee_cam_r6d_gripper"
    units: str = "m_rad_norm"
    fps: float = Field(default=5.0, gt=0)
    dimension_names: list[str] = Field(
        default_factory=lambda: [
            "dx",
            "dy",
            "dz",
            "r6d_0",
            "r6d_1",
            "r6d_2",
            "r6d_3",
            "r6d_4",
            "r6d_5",
            "gripper",
        ]
    )
    values: list[list[float]] = Field(min_length=1)
    action_mask: list[list[float]] | None = None
    normalization_method: str = "none"
    normalization_revision: str = "qrm-lite-alpha-v1"
    is_residual: bool = True

    @model_validator(mode="after")
    def validate_chunk(self) -> "CameraFrameActionChunkV1":
        width = len(self.dimension_names)
        if width < 1:
            raise ValueError("dimension_names must be non-empty")
        for row in self.values:
            if len(row) != width:
                raise ValueError("action chunk T×D must match dimension_names")
            if not all(isfinite(v) for v in row):
                raise ValueError("action chunk may not contain NaN or Inf")
        if self.action_mask is not None:
            if len(self.action_mask) != len(self.values):
                raise ValueError("action_mask length must match values")
            for mask_row in self.action_mask:
                if len(mask_row) != width:
                    raise ValueError("action_mask width must match dimension_names")
        return self


class QRMTrainingSampleV1(StrictModel):
    schema_version: Literal["QRMTrainingSampleV1"] = "QRMTrainingSampleV1"
    sample_id: str
    episode_id: str
    seed: int = 0
    split: Literal["train", "val", "test", "overfit"] = "train"
    observation: QRMObservationV1
    coarse_intent: CoarseIntentV1
    nominal_action_chunk: CameraFrameActionChunkV1
    residual_action_chunk: CameraFrameActionChunkV1
    target_action_chunk: CameraFrameActionChunkV1
    simulator_supervision: dict[str, Any] | None = None
    provenance: dict[str, str] = Field(default_factory=dict)
    synthetic: bool = False
