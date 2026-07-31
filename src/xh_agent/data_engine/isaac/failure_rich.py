"""Dataset V2 physical failure/recovery gates and residual-pair validation."""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.data_engine.isaac.contract import audit_policy_projection
from xh_agent.policy.qrm_lite.contracts import FailureContextV1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PhysicalFailureType(str, Enum):
    EMPTY_GRASP = "EMPTY_GRASP"
    WRONG_OBJECT = "WRONG_OBJECT"
    RELEASE_FAILURE = "RELEASE_FAILURE"
    UNSTABLE_PLACEMENT = "UNSTABLE_PLACEMENT"


class PhysicalFailureEvidenceV2(StrictModel):
    schema_version: Literal["PhysicalFailureEvidenceV2"] = (
        "PhysicalFailureEvidenceV2"
    )
    failure_type: PhysicalFailureType
    injection_commanded: bool
    close_command_issued: bool = False
    release_command_issued: bool = False
    bilateral_grasp_observed: bool | None = None
    attachment_created: bool | None = None
    attachment_remained_after_release: bool | None = None
    contacted_entity_id: str | None = None
    attached_entity_id: str | None = None
    task_target_entity_id: str | None = None
    task_target_track_id: str | None = None
    carried_public_track_id: str | None = None
    target_lift_delta_m: float | None = None
    carried_follow_delta_m: float | None = None
    public_observed_predicates: list[str] = Field(default_factory=list)
    supervision_only: Literal[True] = True

    @model_validator(mode="after")
    def physical_state_matches_failure(self) -> "PhysicalFailureEvidenceV2":
        if not self.injection_commanded:
            raise ValueError("failure injection was not commanded")
        observed = set(self.public_observed_predicates)
        if self.failure_type == PhysicalFailureType.EMPTY_GRASP:
            if not self.close_command_issued:
                raise ValueError("EMPTY_GRASP requires a close command")
            if self.bilateral_grasp_observed is not False:
                raise ValueError("EMPTY_GRASP requires absent bilateral grasp")
            if self.attachment_created is not False:
                raise ValueError("EMPTY_GRASP must not create an attachment")
            if self.target_lift_delta_m is None or self.target_lift_delta_m > 0.005:
                raise ValueError("EMPTY_GRASP target followed the lift")
            if not {"grasped=false", "lifted=false"}.issubset(observed):
                raise ValueError("EMPTY_GRASP public predicates are incomplete")
        elif self.failure_type == PhysicalFailureType.WRONG_OBJECT:
            if not self.close_command_issued or self.bilateral_grasp_observed is not True:
                raise ValueError("WRONG_OBJECT requires a physical grasp")
            if not self.contacted_entity_id or not self.attached_entity_id:
                raise ValueError("WRONG_OBJECT contact/attach evidence is missing")
            if self.contacted_entity_id != self.attached_entity_id:
                raise ValueError("broker did not attach the contacted entity")
            if self.attached_entity_id == self.task_target_entity_id:
                raise ValueError("WRONG_OBJECT carried the task target")
            if not self.task_target_track_id or not self.carried_public_track_id:
                raise ValueError("WRONG_OBJECT public association is missing")
            if self.task_target_track_id == self.carried_public_track_id:
                raise ValueError("WRONG_OBJECT public tracks do not disagree")
            if "carried_target_match=false" not in observed:
                raise ValueError("WRONG_OBJECT public mismatch was not observed")
        elif self.failure_type == PhysicalFailureType.RELEASE_FAILURE:
            if not self.release_command_issued:
                raise ValueError("RELEASE_FAILURE requires a release command")
            if self.attachment_remained_after_release is not True:
                raise ValueError("RELEASE_FAILURE attachment did not remain")
            if self.carried_follow_delta_m is None or self.carried_follow_delta_m < 0.01:
                raise ValueError("RELEASE_FAILURE lacks physical follow evidence")
            if "released=false" not in observed:
                raise ValueError("RELEASE_FAILURE public predicate is missing")
        elif "stable_placement=false" not in observed:
            raise ValueError("UNSTABLE_PLACEMENT public predicate is missing")
        return self


class RecoveryExecutionV2(StrictModel):
    schema_version: Literal["RecoveryExecutionV2"] = "RecoveryExecutionV2"
    sequence: list[str] = Field(min_length=1)
    steps_executed: list[str] = Field(min_length=1)
    public_final_predicates: list[str]
    successful: bool
    cleanup_only: bool = False
    retry_count: int = Field(ge=1)

    @model_validator(mode="after")
    def planned_steps_were_executed(self) -> "RecoveryExecutionV2":
        if self.steps_executed != self.sequence:
            raise ValueError("recovery sequence was not fully executed in order")
        if self.successful and self.cleanup_only:
            raise ValueError("cleanup may not count as recovery success")
        return self


class ResidualCorrectionPairV2(StrictModel):
    schema_version: Literal["ResidualCorrectionPairV2"] = (
        "ResidualCorrectionPairV2"
    )
    dimension_names: list[str] = Field(min_length=10, max_length=10)
    coordinate_frame: Literal["camera_optical"] = "camera_optical"
    units: Literal["m_rad_norm"] = "m_rad_norm"
    perturbed_nominal: list[float] = Field(min_length=10, max_length=10)
    corrected_action: list[float] = Field(min_length=10, max_length=10)
    residual_target: list[float] = Field(min_length=10, max_length=10)
    perturbation_xyz_m: list[float] = Field(min_length=3, max_length=3)
    correction_physically_successful: bool
    training_only_privileged_label: Literal[True] = True

    @model_validator(mode="after")
    def target_is_reconstructible_and_bounded(self) -> "ResidualCorrectionPairV2":
        values = [
            *self.perturbed_nominal,
            *self.corrected_action,
            *self.residual_target,
            *self.perturbation_xyz_m,
        ]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("residual pair contains NaN/Inf")
        expected = [
            corrected - nominal
            for corrected, nominal in zip(
                self.corrected_action, self.perturbed_nominal
            )
        ]
        if any(
            not math.isclose(actual, target, abs_tol=1e-9)
            for actual, target in zip(expected, self.residual_target)
        ):
            raise ValueError("residual target is not corrected - nominal")
        x, y, z = self.perturbation_xyz_m
        if not (0.002 <= abs(x) <= 0.015):
            raise ValueError("X perturbation is outside the M1B envelope")
        if not (0.002 <= abs(y) <= 0.015):
            raise ValueError("Y perturbation is outside the M1B envelope")
        if not (0.001 <= abs(z) <= 0.005):
            raise ValueError("Z perturbation is outside the M1B envelope")
        if not self.correction_physically_successful:
            raise ValueError("unsuccessful correction may not supervise residual")
        return self


RECOVERY_REQUIREMENTS = {
    PhysicalFailureType.EMPTY_GRASP: (
        "REOBSERVE",
        "REGRASP",
    ),
    PhysicalFailureType.WRONG_OBJECT: (
        "SAFE_PLACE_NON_TARGET",
        "REASSOCIATE_TARGET",
        "REGRASP",
    ),
    PhysicalFailureType.RELEASE_FAILURE: (
        "RETRY_RELEASE",
        "RETREAT",
        "REOBSERVE",
    ),
    PhysicalFailureType.UNSTABLE_PLACEMENT: (
        "REOBSERVE",
        "REGRASP",
        "POSE_CORRECTION",
        "PLACE",
    ),
}


def validate_failure_recovery_episode(episode: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        failure = PhysicalFailureEvidenceV2.model_validate(
            episode["simulator_supervision"]["physical_failure_evidence"]
        )
    except (KeyError, ValueError) as exc:
        return [f"physical failure evidence: {exc}"]
    try:
        recovery = RecoveryExecutionV2.model_validate(
            episode["recovery_execution"]
        )
    except (KeyError, ValueError) as exc:
        return [f"recovery execution: {exc}"]
    expected_prefix = RECOVERY_REQUIREMENTS[failure.failure_type]
    if tuple(recovery.sequence[: len(expected_prefix)]) != expected_prefix:
        errors.append(
            f"{failure.failure_type.value} recovery sequence mismatch"
        )
    context = episode.get("failure_context", {})
    try:
        parsed_context = FailureContextV1.model_validate(context)
    except ValueError as exc:
        errors.append(f"FailureContext invalid: {exc}")
    else:
        if parsed_context.failure_type.value != failure.failure_type.value:
            errors.append("FailureContext failure_type disagrees with physics")
        if not parsed_context.predicate_residual:
            errors.append("FailureContext predicate_residual is empty")
        if not parsed_context.previous_skill and not parsed_context.last_skill:
            errors.append("FailureContext previous skill is empty")
        if parsed_context.retry_count < 1:
            errors.append("FailureContext retry_count must be positive")
        if parsed_context.attempted_recoveries != recovery.steps_executed:
            errors.append("FailureContext recovery history disagrees with execution")
        expected_result = "SUCCESS" if recovery.successful else "FAILED"
        if parsed_context.last_recovery_result != expected_result:
            errors.append("FailureContext last_recovery_result disagrees")
    errors.extend(
        audit_policy_projection(
            {
                "observation_before": episode.get("observation_before", {}),
                "observation_after": episode.get("observation_after", {}),
                "recovery_observations": episode.get("recovery_observations", []),
                "failure_context": context,
                "task_spec": episode.get("task_spec", {}),
            }
        )
    )
    return sorted(set(errors))


def failure_rich_group_key(
    scene_seed: int,
    failure_type: str,
    injection_seed: int,
) -> str:
    return f"scene-{scene_seed}:failure-{failure_type}:injection-{injection_seed}"
