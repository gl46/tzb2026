"""Strict journal contract for the bounded M2C PATH_BLOCKED recovery chain.

This module deliberately validates structured evidence rather than calling the
runtime adapter.  RuntimeSkillRegistryV2 and CoarseIntentV2 can therefore be
implemented independently without weakening the pre-registered attribution
predicate.  The journal contains public RGB-D track IDs only; simulator entity
or prim identity has no field in the contract and is rejected as extra input.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EXPECTED_PATH_BLOCKED_CHAIN: tuple[str, ...] = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)
REGISTERED_DESTINATION_CELLS: tuple[str, ...] = tuple(f"BIN_CELL_{index}" for index in range(6))
POINTER_SLOT_COUNT = 8
NONE_POINTER_CLASS = POINTER_SLOT_COUNT
NONE_DESTINATION_CLASS = len(REGISTERED_DESTINATION_CELLS)

ParameterProvenance = Literal[
    "MODEL",
    "NONE",
    "TASK_SPEC_FALLBACK",
    "B0_CONTINUATION",
]
MappingStatus = Literal[
    "VALID",
    "INVALID_POINTER",
    "STALE_TRACK",
    "INVALID_CELL",
    "INVALID",
]
GateStatus = Literal["PASS", "REJECTED", "NOT_RUN"]
ExecutionSource = Literal[
    "MODEL_SELECTED_REGISTERED_SKILL",
    "B0_FALLBACK",
    "B0_CONTINUATION",
    "NO_PHYSICAL_EXECUTION",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PublicObservationReceiptV2(StrictModel):
    """Hash-bound fresh observation built only from the public RGB-D path."""

    schema_version: Literal["PublicObservationReceiptV2"] = "PublicObservationReceiptV2"
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    rgb_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    depth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["PUBLIC_RGBD"] = "PUBLIC_RGBD"
    fresh: bool = True
    perception_track_ids: list[str] = Field(default_factory=list)
    pointer_slots: list[str] = Field(
        default_factory=list,
        max_length=POINTER_SLOT_COUNT,
    )
    blocker_track_id: str | None = None
    task_target_track_id: str | None = None
    privileged_truth_policy_input: bool = False
    teacher_used: bool = False

    @model_validator(mode="after")
    def reject_oracle_track_identifiers(self) -> "PublicObservationReceiptV2":
        track_ids = [
            *self.perception_track_ids,
            *self.pointer_slots,
            *([self.blocker_track_id] if self.blocker_track_id is not None else []),
            *([self.task_target_track_id] if self.task_target_track_id is not None else []),
        ]
        if any(
            not track_id.startswith("track-")
            or "/" in track_id
            or track_id.startswith("gazebo_perfect_")
            for track_id in track_ids
        ):
            raise ValueError("public observation may contain only public track-* identifiers")
        return self


class PhysicalSkillReceiptV2(StrictModel):
    """One physical skill execution and all unchanged pre-execution gates."""

    schema_version: Literal["PhysicalSkillReceiptV2"] = "PhysicalSkillReceiptV2"
    receipt_id: str = Field(min_length=1)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executed_skill: str = Field(min_length=1)
    execution_source: ExecutionSource
    physically_executed: bool
    started_at_ns: int = Field(gt=0)
    completed_at_ns: int = Field(gt=0)
    schema_gate: GateStatus
    stale_track_gate: GateStatus
    frame_unit_gate: GateStatus
    ik_gate: GateStatus
    collision_gate: GateStatus
    controller_gate: GateStatus
    safety_gate: GateStatus
    collision_or_safety_violation: bool = False
    fallback_reason: str | None = None
    privileged_truth_policy_input: bool = False
    teacher_used: bool = False


class ModelOwnedChainDecisionV2(StrictModel):
    """One model proposal, its public input, mapping, and physical receipt."""

    schema_version: Literal["ModelOwnedChainDecisionV2"] = "ModelOwnedChainDecisionV2"
    decision_id: str = Field(min_length=1)
    step_index: int = Field(ge=0)
    observation: PublicObservationReceiptV2
    model_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_skill: str = Field(min_length=1)
    skill_provenance: ParameterProvenance
    target_track_id: str | None = None
    target_pointer_class: int
    target_provenance: ParameterProvenance
    destination_cell: str | None = None
    destination_class: int
    destination_provenance: ParameterProvenance
    mapping_status: MappingStatus
    physical_skill_receipts: list[PhysicalSkillReceiptV2] = Field(default_factory=list)


class ModelOwnedChainEpisodeV2(StrictModel):
    """Bounded Q-B episode journal beginning at the first PATH_BLOCKED failure."""

    schema_version: Literal["ModelOwnedChainEpisodeV2"] = "ModelOwnedChainEpisodeV2"
    episode_id: str = Field(min_length=1)
    failure_type: Literal["PATH_BLOCKED"] = "PATH_BLOCKED"
    failure_observed_at_ns: int = Field(gt=0)
    final_task_success: bool
    decisions: list[ModelOwnedChainDecisionV2]
    privileged_truth_policy_input: bool = False
    teacher_used: bool = False


class FallbackEventV2(StrictModel):
    schema_version: Literal["FallbackEventV2"] = "FallbackEventV2"
    decision_id: str
    step_index: int
    execution_source: Literal["B0_FALLBACK", "B0_CONTINUATION"]
    executed_skill: str
    fallback_reason: str | None = None


class ModelOwnedChainStepValidationV2(StrictModel):
    schema_version: Literal["ModelOwnedChainStepValidationV2"] = "ModelOwnedChainStepValidationV2"
    decision_id: str
    step_index: int
    expected_skill: str | None
    passed: bool
    exclusion_reasons: list[str] = Field(default_factory=list)


class ModelOwnedChainValidationV2(StrictModel):
    schema_version: Literal["ModelOwnedChainValidationV2"] = "ModelOwnedChainValidationV2"
    episode_id: str
    strict_pure_model_success: bool
    expected_chain: list[str]
    decisions_observed: int
    physical_receipts_observed: int
    fallback_events: list[FallbackEventV2] = Field(default_factory=list)
    exclusion_reasons: list[str] = Field(default_factory=list)
    steps: list[ModelOwnedChainStepValidationV2] = Field(default_factory=list)


def _reason(reasons: list[str], value: str) -> None:
    """Append a deterministic reason once while retaining discovery order."""

    if value not in reasons:
        reasons.append(value)


def _expected_target_role(step_index: int) -> Literal["BLOCKER", "TASK_TARGET", "NONE"]:
    if step_index in {0, 1, 2, 3, 4}:
        return "BLOCKER"
    if step_index in {6, 7}:
        return "TASK_TARGET"
    return "NONE"


def _validate_observation(
    decision: ModelOwnedChainDecisionV2,
    *,
    freshness_floor_ns: int,
    seen_observation_ids: set[str],
    reasons: list[str],
) -> None:
    observation = decision.observation
    prefix = f"{decision.decision_id}:"
    if observation.source != "PUBLIC_RGBD":
        _reason(reasons, prefix + "OBSERVATION_NOT_PUBLIC_RGBD")
    if not observation.fresh:
        _reason(reasons, prefix + "OBSERVATION_NOT_MARKED_FRESH")
    if observation.captured_at_ns <= freshness_floor_ns:
        _reason(reasons, prefix + "OBSERVATION_NOT_FRESH_AFTER_PREVIOUS_EVENT")
    if observation.observation_id in seen_observation_ids:
        _reason(reasons, prefix + "OBSERVATION_RECEIPT_REUSED")
    seen_observation_ids.add(observation.observation_id)
    if observation.privileged_truth_policy_input:
        _reason(reasons, prefix + "PRIVILEGED_TRUTH_POLICY_INPUT")
    if observation.teacher_used:
        _reason(reasons, prefix + "TEACHER_USED")
    if len(observation.perception_track_ids) != len(set(observation.perception_track_ids)):
        _reason(reasons, prefix + "DUPLICATE_PUBLIC_TRACK_ID")
    expected_slots = sorted(set(observation.perception_track_ids))[:POINTER_SLOT_COUNT]
    if observation.pointer_slots != expected_slots:
        _reason(reasons, prefix + "NON_CANONICAL_POINTER_SLOTS")


def _validate_parameters(
    decision: ModelOwnedChainDecisionV2,
    *,
    expected_role: Literal["BLOCKER", "TASK_TARGET", "NONE"],
    destination_required: bool,
    reasons: list[str],
) -> bool:
    """Validate model ownership and return whether a fallback is required."""

    prefix = f"{decision.decision_id}:"
    fallback_required = decision.mapping_status != "VALID"
    if decision.skill_provenance != "MODEL":
        if decision.skill_provenance == "TASK_SPEC_FALLBACK":
            _reason(reasons, prefix + "TASK_SPEC_FALLBACK")
        elif decision.skill_provenance == "B0_CONTINUATION":
            _reason(reasons, prefix + "B0_CONTINUATION_PROVENANCE")
        _reason(reasons, prefix + "SKILL_NOT_MODEL_PROVENANCE")
        fallback_required = True

    if expected_role == "NONE":
        if decision.target_track_id is not None:
            _reason(reasons, prefix + "UNEXPECTED_TARGET_TRACK")
            fallback_required = True
        if decision.target_pointer_class != NONE_POINTER_CLASS:
            _reason(reasons, prefix + "INVALID_POINTER")
            fallback_required = True
        if decision.target_provenance != "NONE":
            if decision.target_provenance == "TASK_SPEC_FALLBACK":
                _reason(reasons, prefix + "TASK_SPEC_FALLBACK")
            else:
                _reason(reasons, prefix + "TARGET_PROVENANCE_NOT_NONE")
            fallback_required = True
    else:
        if decision.target_provenance == "TASK_SPEC_FALLBACK":
            _reason(reasons, prefix + "TASK_SPEC_FALLBACK")
            fallback_required = True
        elif decision.target_provenance != "MODEL":
            _reason(reasons, prefix + "TARGET_NOT_MODEL_PROVENANCE")
            fallback_required = True
        role_track = (
            decision.observation.blocker_track_id
            if expected_role == "BLOCKER"
            else decision.observation.task_target_track_id
        )
        if not role_track or decision.target_track_id != role_track:
            _reason(reasons, prefix + f"TARGET_NOT_PUBLIC_{expected_role}")
            fallback_required = True
        pointer = decision.target_pointer_class
        if not 0 <= pointer < POINTER_SLOT_COUNT:
            _reason(reasons, prefix + "INVALID_POINTER")
            fallback_required = True
        elif pointer >= len(decision.observation.pointer_slots):
            _reason(reasons, prefix + "INVALID_POINTER")
            fallback_required = True
        elif decision.observation.pointer_slots[pointer] != decision.target_track_id:
            _reason(reasons, prefix + "INVALID_POINTER")
            fallback_required = True
        if decision.target_track_id not in decision.observation.perception_track_ids:
            _reason(reasons, prefix + "STALE_TRACK")
            fallback_required = True

    if destination_required:
        if decision.destination_provenance != "MODEL":
            if decision.destination_provenance == "TASK_SPEC_FALLBACK":
                _reason(reasons, prefix + "TASK_SPEC_FALLBACK")
            elif decision.destination_provenance == "B0_CONTINUATION":
                _reason(reasons, prefix + "B0_CONTINUATION_PROVENANCE")
            _reason(reasons, prefix + "DESTINATION_NOT_MODEL_PROVENANCE")
            fallback_required = True
        if decision.destination_cell not in REGISTERED_DESTINATION_CELLS:
            _reason(reasons, prefix + "INVALID_CELL")
            fallback_required = True
        else:
            expected_class = REGISTERED_DESTINATION_CELLS.index(decision.destination_cell)
            if decision.destination_class != expected_class:
                _reason(reasons, prefix + "INVALID_CELL")
                fallback_required = True
    else:
        if decision.destination_cell is not None:
            _reason(reasons, prefix + "UNEXPECTED_DESTINATION_CELL")
            fallback_required = True
        if decision.destination_class != NONE_DESTINATION_CLASS:
            _reason(reasons, prefix + "INVALID_CELL")
            fallback_required = True
        if decision.destination_provenance != "NONE":
            _reason(reasons, prefix + "DESTINATION_PROVENANCE_NOT_NONE")
            fallback_required = True

    mapping_reason = {
        "INVALID_POINTER": "INVALID_POINTER",
        "STALE_TRACK": "STALE_TRACK",
        "INVALID_CELL": "INVALID_CELL",
        "INVALID": "MAPPING_NOT_VALID",
    }.get(decision.mapping_status)
    if mapping_reason:
        _reason(reasons, prefix + mapping_reason)
    return fallback_required


def _validate_receipts(
    decision: ModelOwnedChainDecisionV2,
    *,
    fallback_required: bool,
    seen_receipt_ids: set[str],
    seen_receipt_sha256: set[str],
    reasons: list[str],
    fallback_events: list[FallbackEventV2],
) -> int | None:
    prefix = f"{decision.decision_id}:"
    receipts = decision.physical_skill_receipts
    if len(receipts) != 1:
        _reason(reasons, prefix + "PHYSICAL_RECEIPT_COUNT_NOT_ONE")
    fallback_recorded = False
    completed_at_ns: int | None = None
    for receipt in receipts:
        if receipt.receipt_id in seen_receipt_ids:
            _reason(reasons, prefix + "PHYSICAL_RECEIPT_REUSED")
        seen_receipt_ids.add(receipt.receipt_id)
        if receipt.receipt_sha256 in seen_receipt_sha256:
            _reason(reasons, prefix + "PHYSICAL_RECEIPT_REUSED")
        seen_receipt_sha256.add(receipt.receipt_sha256)
        completed_at_ns = max(completed_at_ns or 0, receipt.completed_at_ns)
        if receipt.execution_source in {"B0_FALLBACK", "B0_CONTINUATION"}:
            fallback_recorded = True
            fallback_events.append(
                FallbackEventV2(
                    decision_id=decision.decision_id,
                    step_index=decision.step_index,
                    execution_source=receipt.execution_source,
                    executed_skill=receipt.executed_skill,
                    fallback_reason=receipt.fallback_reason,
                )
            )
            _reason(reasons, prefix + receipt.execution_source)
            if not receipt.fallback_reason:
                _reason(reasons, prefix + "FALLBACK_REASON_MISSING")
        elif receipt.execution_source == "NO_PHYSICAL_EXECUTION":
            _reason(reasons, prefix + "NO_PHYSICAL_EXECUTION")
        elif receipt.fallback_reason is not None:
            _reason(reasons, prefix + "MODEL_RECEIPT_HAS_FALLBACK_REASON")

        if not receipt.physically_executed:
            _reason(reasons, prefix + "SKILL_NOT_PHYSICALLY_EXECUTED")
        if receipt.started_at_ns <= decision.observation.captured_at_ns:
            _reason(reasons, prefix + "EXECUTION_PRECEDES_PUBLIC_OBSERVATION")
        if receipt.completed_at_ns <= receipt.started_at_ns:
            _reason(reasons, prefix + "INVALID_EXECUTION_TIME_ORDER")
        for gate_name in (
            "schema_gate",
            "stale_track_gate",
            "frame_unit_gate",
            "ik_gate",
            "collision_gate",
            "controller_gate",
            "safety_gate",
        ):
            if getattr(receipt, gate_name) != "PASS":
                _reason(reasons, prefix + gate_name.upper() + "_NOT_PASSING")
        if receipt.collision_or_safety_violation:
            _reason(reasons, prefix + "COLLISION_OR_SAFETY_VIOLATION")
        if receipt.privileged_truth_policy_input:
            _reason(reasons, prefix + "PRIVILEGED_TRUTH_POLICY_INPUT")
        if receipt.teacher_used:
            _reason(reasons, prefix + "TEACHER_USED")
        if (
            receipt.execution_source == "MODEL_SELECTED_REGISTERED_SKILL"
            and receipt.executed_skill != decision.selected_skill
        ):
            _reason(reasons, prefix + "EXECUTED_SKILL_DIFFERS_FROM_MODEL_SELECTION")

    if fallback_required and not fallback_recorded:
        _reason(reasons, prefix + "FALLBACK_NOT_RECORDED")
    return completed_at_ns


def validate_model_owned_chain_episode(
    episode: ModelOwnedChainEpisodeV2,
) -> ModelOwnedChainValidationV2:
    """Validate ADR-0020 section 7(3)(4) without executing the policy.

    Expected bad mappings are evidence, not parse failures: they remain in the
    result with their fallback event and all strict-pure exclusion reasons.
    Contract-shape violations still fail Pydantic validation before this call.
    """

    all_reasons: list[str] = []
    fallback_events: list[FallbackEventV2] = []
    step_results: list[ModelOwnedChainStepValidationV2] = []
    if not episode.final_task_success:
        _reason(all_reasons, "FINAL_TASK_NOT_SUCCESSFUL")
    if episode.privileged_truth_policy_input:
        _reason(all_reasons, "PRIVILEGED_TRUTH_POLICY_INPUT")
    if episode.teacher_used:
        _reason(all_reasons, "TEACHER_USED")
    if len(episode.decisions) != len(EXPECTED_PATH_BLOCKED_CHAIN):
        _reason(all_reasons, "RECOVERY_CHAIN_LENGTH_NOT_EIGHT")

    seen_decision_ids: set[str] = set()
    seen_observation_ids: set[str] = set()
    seen_receipt_ids: set[str] = set()
    seen_receipt_sha256: set[str] = set()
    freshness_floor_ns = episode.failure_observed_at_ns
    for position, decision in enumerate(episode.decisions):
        reasons: list[str] = []
        expected_skill = (
            EXPECTED_PATH_BLOCKED_CHAIN[position]
            if position < len(EXPECTED_PATH_BLOCKED_CHAIN)
            else None
        )
        if decision.decision_id in seen_decision_ids:
            _reason(reasons, f"{decision.decision_id}:DECISION_ID_REUSED")
        seen_decision_ids.add(decision.decision_id)
        if decision.step_index != position:
            _reason(reasons, f"{decision.decision_id}:NON_CANONICAL_STEP_INDEX")
        if expected_skill is None:
            _reason(reasons, f"{decision.decision_id}:UNEXPECTED_EXTRA_DECISION")
        elif decision.selected_skill != expected_skill:
            _reason(
                reasons,
                f"{decision.decision_id}:CHAIN_SKILL_MISMATCH:"
                f"EXPECTED_{expected_skill}:ACTUAL_{decision.selected_skill}",
            )

        _validate_observation(
            decision,
            freshness_floor_ns=freshness_floor_ns,
            seen_observation_ids=seen_observation_ids,
            reasons=reasons,
        )
        expected_role = _expected_target_role(position)
        fallback_required = _validate_parameters(
            decision,
            expected_role=expected_role,
            destination_required=position in {2, 3},
            reasons=reasons,
        )
        completed_at_ns = _validate_receipts(
            decision,
            fallback_required=fallback_required,
            seen_receipt_ids=seen_receipt_ids,
            seen_receipt_sha256=seen_receipt_sha256,
            reasons=reasons,
            fallback_events=fallback_events,
        )
        if completed_at_ns is not None:
            freshness_floor_ns = completed_at_ns
        else:
            # Without a physical receipt, a later observation cannot prove it
            # was captured after this decision's execution.
            freshness_floor_ns = max(
                freshness_floor_ns,
                decision.observation.captured_at_ns,
            )
        for reason in reasons:
            _reason(all_reasons, reason)
        step_results.append(
            ModelOwnedChainStepValidationV2(
                decision_id=decision.decision_id,
                step_index=decision.step_index,
                expected_skill=expected_skill,
                passed=not reasons,
                exclusion_reasons=reasons,
            )
        )

    return ModelOwnedChainValidationV2(
        episode_id=episode.episode_id,
        strict_pure_model_success=not all_reasons,
        expected_chain=list(EXPECTED_PATH_BLOCKED_CHAIN),
        decisions_observed=len(episode.decisions),
        physical_receipts_observed=sum(
            len(decision.physical_skill_receipts) for decision in episode.decisions
        ),
        fallback_events=fallback_events,
        exclusion_reasons=all_reasons,
        steps=step_results,
    )
