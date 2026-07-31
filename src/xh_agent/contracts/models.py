"""Versioned data contracts separating policy observations from simulator truth."""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SkillType(str, Enum):
    OBSERVE = "OBSERVE"
    APPROACH = "APPROACH"
    GRASP = "GRASP"
    LIFT = "LIFT"
    MOVE = "MOVE"
    PLACE = "PLACE"
    RELEASE = "RELEASE"
    BACKOFF = "BACKOFF"
    REGRASP = "REGRASP"
    REOBSERVE = "REOBSERVE"
    SAFE_PLACE_NON_TARGET = "SAFE_PLACE_NON_TARGET"
    REASSOCIATE_TARGET = "REASSOCIATE_TARGET"
    RETRY_RELEASE = "RETRY_RELEASE"
    STOP = "STOP"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"


class TargetConstraintsV0(StrictModel):
    category: str | None = None
    color: str | None = None
    shape: str | None = None


class TaskSpecV0(StrictModel):
    schema_version: Literal["TaskSpecV0"] = "TaskSpecV0"
    task_id: str
    operation: str
    target_object_id: str | None = None
    target_constraints: TargetConstraintsV0 = Field(default_factory=TargetConstraintsV0)
    spatial_selector: str | None = None
    reference_frame: str
    destination: str
    goal_predicates: list[str]
    constraints: list[str] = Field(default_factory=list)
    ambiguity_score: float = Field(ge=0, le=1)
    need_clarification: bool
    source_instruction: str

    @model_validator(mode="after")
    def target_is_referenced_or_constrained(self) -> "TaskSpecV0":
        if self.target_object_id is None and not any(self.target_constraints.model_dump().values()):
            raise ValueError("target must use an existing object ID or explicit resolving constraints")
        return self


class ObjectTrackV0(StrictModel):
    object_id: str
    category: str
    pose: list[float] = Field(min_length=7, max_length=7)
    confidence: float = Field(ge=0, le=1)


class ObservationV0(StrictModel):
    schema_version: Literal["ObservationV0"] = "ObservationV0"
    episode_id: str
    step_id: int = Field(ge=0)
    timestamp_ns: int = Field(ge=0)
    rgb_uri: str
    depth_uri: str | None = None
    segmentation_uri: str | None = None
    camera_intrinsics: list[float] = Field(min_length=9, max_length=9)
    camera_extrinsics: list[float] = Field(min_length=16, max_length=16)
    joint_position: list[float]
    joint_velocity: list[float]
    end_effector_pose: list[float] = Field(min_length=7, max_length=7)
    gripper_state: str
    object_tracks: list[ObjectTrackV0]
    relation_graph: list[dict[str, str]] = Field(default_factory=list)
    current_task_id: str
    current_subgoal: str | None = None
    coordinate_frame: str
    uncertainty: float = Field(ge=0, le=1)


class SimulatorSupervisionV0(StrictModel):
    schema_version: Literal["SimulatorSupervisionV0"] = "SimulatorSupervisionV0"
    training_and_evaluation_only: Literal[True] = True
    perfect_object_poses: dict[str, list[float]]
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    collisions: list[dict[str, Any]] = Field(default_factory=list)
    grasp_states: dict[str, bool] = Field(default_factory=dict)
    slip_events: list[dict[str, Any]] = Field(default_factory=list)
    task_success: bool
    physical_parameters: dict[str, float] = Field(default_factory=dict)
    failure_injection: dict[str, Any] = Field(default_factory=dict)
    simulator: str
    simulator_version: str


class CandidateSkillV0(StrictModel):
    schema_version: Literal["CandidateSkillV0"] = "CandidateSkillV0"
    skill_type: SkillType
    target_object_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    coordinate_frame: str
    preconditions: list[str] = Field(default_factory=list)
    expected_effects: list[str] = Field(default_factory=list)
    generated_by: str
    candidate_id: str


class ActionTrajectoryV0(StrictModel):
    schema_version: Literal["ActionTrajectoryV0"] = "ActionTrajectoryV0"
    embodiment: str
    representation: str
    coordinate_frame: str
    units: str
    fps: float = Field(gt=0)
    values: list[list[float]] = Field(min_length=1)
    dimension_names: list[str] = Field(min_length=1)
    normalization_method: str
    normalization_revision: str
    source_skill: str
    source_policy: str

    @model_validator(mode="after")
    def rectangular_finite_trajectory(self) -> "ActionTrajectoryV0":
        width = len(self.dimension_names)
        if any(len(row) != width for row in self.values):
            raise ValueError("trajectory T×D values must match dimension_names")
        if not all(isfinite(value) for row in self.values for value in row):
            raise ValueError("trajectory may not contain NaN or Inf")
        return self

    def validate_real_teacher_mapping(self) -> None:
        blocked = {"", "UNKNOWN", "UNSPECIFIED", "NONE"}
        if any(value.upper() in blocked for value in (
            self.coordinate_frame, self.units, self.normalization_method, self.normalization_revision
        )):
            raise ValueError("real Teacher request requires known frame, units, and normalization")


class TeacherRequestV0(StrictModel):
    schema_version: Literal["TeacherRequestV0"] = "TeacherRequestV0"
    candidate_model: str
    checkpoint_revision: str
    conditioning_observation: ObservationV0
    action_trajectory: ActionTrajectoryV0
    prompt: str
    seed: int
    generation_parameters: dict[str, Any] = Field(default_factory=dict)
    action_domain: str
    action_mapping_revision: str

    def validate_for_real_teacher(self) -> None:
        self.action_trajectory.validate_real_teacher_mapping()
        if self.action_mapping_revision.upper() in {"", "UNKNOWN", "UNSPECIFIED", "NONE"}:
            raise ValueError("real Teacher request requires a verified action mapping revision")


class TeacherResponseV0(StrictModel):
    schema_version: Literal["TeacherResponseV0"] = "TeacherResponseV0"
    status: Literal["PENDING", "SUCCEEDED", "FAILED", "CANCELLED", "MOCK"]
    output_uris: list[str] = Field(default_factory=list)
    latency_ms: float | None = Field(default=None, ge=0)
    peak_vram_mb: float | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)


class EpisodeTransitionV0(StrictModel):
    schema_version: Literal["EpisodeTransitionV0"] = "EpisodeTransitionV0"
    observation_before: ObservationV0
    task_spec: TaskSpecV0
    candidate_skill: CandidateSkillV0
    action_trajectory: ActionTrajectoryV0
    observation_after: ObservationV0
    simulator_supervision: SimulatorSupervisionV0
    teacher_response: TeacherResponseV0 | None = None
    semantic_labels: dict[str, Any] | None = None
    task_progress: float = Field(ge=0, le=1)
    failure_type: str | None = None
    provenance: dict[str, str]


class BakeoffSampleV0(StrictModel):
    schema_version: Literal["BakeoffSampleV0"] = "BakeoffSampleV0"
    sample_id: str
    initial_rgb_uri: str
    depth_uri: str | None = None
    language_task: str
    action_trajectory_uri: str
    action_mapping_revision: str
    gazebo_future_uri: str
    simulator_hard_label_uri: str
    scene_id: str
    failure_type: str | None = None


CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "task-spec-v0.schema.json": TaskSpecV0,
    "observation-v0.schema.json": ObservationV0,
    "simulator-supervision-v0.schema.json": SimulatorSupervisionV0,
    "candidate-skill-v0.schema.json": CandidateSkillV0,
    "action-trajectory-v0.schema.json": ActionTrajectoryV0,
    "teacher-request-v0.schema.json": TeacherRequestV0,
    "teacher-response-v0.schema.json": TeacherResponseV0,
    "episode-transition-v0.schema.json": EpisodeTransitionV0,
    "bakeoff-sample-v0.schema.json": BakeoffSampleV0,
}
