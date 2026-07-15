"""Declarative failures, independent of a specific simulator backend."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FailureMode(str, Enum):
    GRASP_POSE_OFFSET = "grasp_pose_offset"
    GRIPPER_WIDTH_MISMATCH = "gripper_width_mismatch"
    LOW_FRICTION_SLIP = "low_friction_slip"
    OBSTACLE_INSERTION = "obstacle_insertion"
    OBJECT_OCCLUSION = "object_occlusion"
    RELEASE_DELAY = "release_delay"
    TARGET_MOVED_DURING_EXECUTION = "target_moved_during_execution"


class FailureInjectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FailureMode
    enabled: bool = False
    seed: int = 0
    magnitude: float = Field(default=0.0, ge=0.0)
    applies_at_step: int = Field(default=0, ge=0)
