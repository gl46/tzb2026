"""Validated public task contracts.  No simulator identity is representable."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TaskSpecV1(StrictModel):
    schema_version: Literal["TaskSpecV1"] = "TaskSpecV1"
    task_id: str
    raw_instruction: str
    operation: Literal["pick_place", "bin_transport"]
    target_query: str
    target_track_id_optional: str | None = Field(default=None, pattern=r"^track-[0-9a-f]{8}$")
    target_attributes: dict[str, str] = Field(default_factory=dict)
    target_selector: str
    destination: str
    orientation_requirement: str
    priority_rule: str
    subgoals: list[str] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    ambiguity: float = Field(ge=0, le=1)
    need_clarification: bool
    compiler_backend: Literal["deterministic", "qwen_adapter"]
    compiler_evidence: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def require_reason_for_clarification(self) -> "TaskSpecV1":
        if self.need_clarification and self.ambiguity == 0:
            raise ValueError("clarification requires nonzero ambiguity")
        return self


class TaskMemoryV1(StrictModel):
    schema_version: Literal["TaskMemoryV1"] = "TaskMemoryV1"
    task_id: str
    current_subgoal: str | None = None
    completed_subgoals: list[str] = Field(default_factory=list)
    attempt_count: int = Field(default=0, ge=0)
    selected_track: str | None = Field(default=None, pattern=r"^track-[0-9a-f]{8}$")
    expected_predicates: dict[str, bool] = Field(default_factory=dict)
    last_observation_summary: dict[str, object] = Field(default_factory=dict)
    last_failure: str | None = None
    recovery_history: list[str] = Field(default_factory=list)
    step_budget: int = Field(default=24, gt=0)


class ExpectedOutcomeV1(StrictModel):
    schema_version: Literal["ExpectedOutcomeV1"] = "ExpectedOutcomeV1"
    skill_name: str
    predicates: dict[str, bool]
    numeric_tolerances: dict[str, float] = Field(default_factory=dict)


class StepRecordV1(StrictModel):
    schema_version: Literal["StepRecordV1"] = "StepRecordV1"
    step_id: int = Field(ge=0)
    skill_name: str
    observation_before_id: str
    observation_before_timestamp_ns: int = Field(ge=0)
    expected_outcome: ExpectedOutcomeV1
    command_or_trajectory_ref: str
    controller_result: str
    observation_after_id: str
    observation_after_timestamp_ns: int = Field(ge=0)
    actual_predicates: dict[str, bool]
    comparison: Literal["SUCCESS", "UNCERTAIN_REOBSERVE", "FAILURE_RECOVERABLE", "FAILURE_TERMINAL"]
    residual_summary: dict[str, float | bool | str] = Field(default_factory=dict)
    failure_type: str | None = None
    next_decision: str

    @model_validator(mode="after")
    def require_fresh_observation(self) -> "StepRecordV1":
        if self.observation_after_timestamp_ns <= self.observation_before_timestamp_ns:
            raise ValueError("every skill requires a newer observation")
        if self.observation_after_id == self.observation_before_id:
            raise ValueError("every skill requires a distinct observation id")
        return self


class RecoveryPlanV1(StrictModel):
    schema_version: Literal["RecoveryPlanV1"] = "RecoveryPlanV1"
    failure_type: Literal["EMPTY_GRASP", "UNSTABLE_OR_WRONG_PLACEMENT", "RELEASE_FAILURE"]
    evidence: list[str] = Field(min_length=1)
    recovery_subgoals: list[str] = Field(min_length=1)
    retry_budget: int = Field(gt=0)
    changed_parameters: dict[str, float | str | bool] = Field(min_length=1)
    stop_condition: str
