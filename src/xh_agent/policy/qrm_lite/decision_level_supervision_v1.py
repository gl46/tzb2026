"""ADR-0026 decision-level supervision contracts.

This module adds a versioned eligibility path.  It deliberately does not
weaken the historical episode-atomic V3/V4 builders: a failed episode still
fails those builders, while an independently replayed eight-step chain may
contribute decisions 0--6 under ADR-0026 section 4.  Decision 7 is admitted
only when its physical receipt proves a successful terminal execution.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.contracts import CoarseIntentV2
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    PathBlockedPublicObservationV3,
)


ADR0026_SHA256 = "ba24b65435b19b3a7700bb7caba83a01d98897a8999aee54af5c2370d410c180"
ADR0026_PATH = "docs/decisions/ADR-0026-m2c-terminal-step-diagnosis.md"
EXPECTED_DECISION_INDICES = tuple(range(8))
PREFIX_DECISION_INDICES = tuple(range(7))

EpisodeTerminalOutcomeV1 = Literal[
    "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED",
    "TERMINAL_PREGRASP_IK_GATE_REJECTED",
    "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED",
]
DecisionObservationV1 = Annotated[
    PathBlockedPublicObservationV3 | PathBlockedPublicObservationV4,
    Field(discriminator="schema_version"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class BoundEvidenceFileV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DecisionGateSummaryV1(StrictModel):
    """One replayed decision's complete admission projection."""

    schema_version: Literal["DecisionGateSummaryV1"] = "DecisionGateSummaryV1"
    decision_index: int = Field(ge=0, le=7)
    canonical_decision_index: bool
    public_observation_fresh_and_unique: bool
    public_capture_unique: bool
    public_candidate_replay_passed: bool
    selected_target_encodable_in_k8: bool
    destination_contract_passed: bool
    exactly_one_canonical_physical_receipt: bool
    expected_skill_executed: bool
    physical_timing_passed: bool
    schema_gate_passed: bool
    stale_track_gate_passed: bool
    frame_unit_gate_passed: bool
    ik_gate_passed: bool
    collision_gate_passed: bool
    controller_gate_passed: bool
    safety_gate_passed: bool
    collision_or_safety_violation: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    terminal_execution_status: str | None = None
    terminal_step_physically_succeeded: bool = False
    all_adr0026_admission_gates_passed: bool

    @model_validator(mode="after")
    def projection_is_exact(self) -> "DecisionGateSummaryV1":
        gates = (
            self.canonical_decision_index,
            self.public_observation_fresh_and_unique,
            self.public_capture_unique,
            self.public_candidate_replay_passed,
            self.destination_contract_passed,
            self.exactly_one_canonical_physical_receipt,
            self.expected_skill_executed,
            self.physical_timing_passed,
            self.schema_gate_passed,
            self.stale_track_gate_passed,
            self.frame_unit_gate_passed,
            self.ik_gate_passed,
            self.collision_gate_passed,
            self.controller_gate_passed,
            self.safety_gate_passed,
        )
        if self.all_adr0026_admission_gates_passed != all(gates):
            raise ValueError("decision gate projection is not exact")
        if self.decision_index != 7 and (
            self.terminal_execution_status is not None or self.terminal_step_physically_succeeded
        ):
            raise ValueError("non-terminal decision carries a terminal outcome")
        if self.terminal_step_physically_succeeded and (
            self.decision_index != 7
            or not self.all_adr0026_admission_gates_passed
            or self.terminal_execution_status != "LIFTED"
        ):
            raise ValueError("terminal physical success is not a passing LIFTED receipt")
        return self


class ADR0026EpisodeEligibilityV1(StrictModel):
    schema_version: Literal["ADR0026EpisodeEligibilityV1"] = "ADR0026EpisodeEligibilityV1"
    episode_id: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    evidence_revision: Literal["V3", "V4"]
    episode_terminal_outcome: EpisodeTerminalOutcomeV1
    episode_final_task_success: bool
    decision_gates: list[DecisionGateSummaryV1] = Field(min_length=8, max_length=8)
    prefix_steps_0_through_6_all_gates_passed: bool
    terminal_step_physically_succeeded: bool
    admitted_decision_indices: list[int]
    pointer_head_masked_decision_indices: list[int]
    episode_level_training_eligible: Literal[False]
    decision_level_prefix_training_eligible: bool
    exclusion_reasons: list[str]
    eligibility_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def eligibility_is_exact(self) -> "ADR0026EpisodeEligibilityV1":
        indices = [item.decision_index for item in self.decision_gates]
        if indices != list(EXPECTED_DECISION_INDICES):
            raise ValueError("decision gates are not the exact ordered eight-step chain")
        prefix_passed = all(
            self.decision_gates[index].all_adr0026_admission_gates_passed
            for index in PREFIX_DECISION_INDICES
        )
        terminal_succeeded = self.decision_gates[7].terminal_step_physically_succeeded
        admitted = list(PREFIX_DECISION_INDICES) if prefix_passed else []
        if prefix_passed and terminal_succeeded:
            admitted.append(7)
        pointer_masked = [
            index
            for index in admitted
            if not self.decision_gates[index].selected_target_encodable_in_k8
        ]
        if (
            self.prefix_steps_0_through_6_all_gates_passed != prefix_passed
            or self.terminal_step_physically_succeeded != terminal_succeeded
            or self.admitted_decision_indices != admitted
            or self.pointer_head_masked_decision_indices != pointer_masked
            or self.decision_level_prefix_training_eligible != prefix_passed
        ):
            raise ValueError("ADR-0026 admitted decision projection differs")
        if prefix_passed != (not self.exclusion_reasons):
            raise ValueError("ADR-0026 exclusion reasons differ from prefix eligibility")
        payload = self.model_dump(mode="json", exclude={"eligibility_sha256"})
        if self.eligibility_sha256 != canonical_sha256(payload):
            raise ValueError("ADR-0026 eligibility digest mismatch")
        return self


def decide_adr0026_episode_eligibility(
    *,
    episode_id: str,
    matched_key: str,
    evidence_revision: Literal["V3", "V4"],
    episode_terminal_outcome: EpisodeTerminalOutcomeV1,
    episode_final_task_success: bool,
    decision_gates: list[DecisionGateSummaryV1],
    exclusion_reasons: list[str],
) -> ADR0026EpisodeEligibilityV1:
    prefix_passed = len(decision_gates) == 8 and all(
        decision_gates[index].all_adr0026_admission_gates_passed
        for index in PREFIX_DECISION_INDICES
    )
    terminal_succeeded = (
        len(decision_gates) == 8 and decision_gates[7].terminal_step_physically_succeeded
    )
    admitted = list(PREFIX_DECISION_INDICES) if prefix_passed else []
    if prefix_passed and terminal_succeeded:
        admitted.append(7)
    pointer_masked = [
        index for index in admitted if not decision_gates[index].selected_target_encodable_in_k8
    ]
    payload = {
        "schema_version": "ADR0026EpisodeEligibilityV1",
        "episode_id": episode_id,
        "matched_key": matched_key,
        "evidence_revision": evidence_revision,
        "episode_terminal_outcome": episode_terminal_outcome,
        "episode_final_task_success": episode_final_task_success,
        "decision_gates": [item.model_dump(mode="json") for item in decision_gates],
        "prefix_steps_0_through_6_all_gates_passed": prefix_passed,
        "terminal_step_physically_succeeded": terminal_succeeded,
        "admitted_decision_indices": admitted,
        "pointer_head_masked_decision_indices": pointer_masked,
        "episode_level_training_eligible": False,
        "decision_level_prefix_training_eligible": prefix_passed,
        "exclusion_reasons": exclusion_reasons,
    }
    payload["eligibility_sha256"] = canonical_sha256(payload)
    return ADR0026EpisodeEligibilityV1.model_validate(payload)


class M2CS4DecisionLevelTrainingSampleV1(StrictModel):
    schema_version: Literal["M2CS4DecisionLevelTrainingSampleV1"] = (
        "M2CS4DecisionLevelTrainingSampleV1"
    )
    evidence_revision: Literal["V3", "V4"]
    sample_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    split: Literal["train"]
    split_group: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    observation: DecisionObservationV1
    model_label: CoarseIntentV2
    skill_label_index: int = Field(ge=0)
    pointer_class_index: int | None = Field(default=None, ge=0)
    destination_class_index: int = Field(ge=0)
    source_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_source: Literal["EXECUTED_PUBLIC_PHYSICAL_CHAIN_ADR0026"] = (
        "EXECUTED_PUBLIC_PHYSICAL_CHAIN_ADR0026"
    )
    skill_provenance: Literal["MODEL"] = "MODEL"
    target_provenance: Literal["MODEL", "NONE"]
    destination_provenance: Literal["MODEL", "NONE"]
    skill_head_supervision_eligible: Literal[True]
    pointer_head_supervision_eligible: bool
    destination_head_supervision_eligible: Literal[True]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    decision_level_training_eligible: Literal[True]
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def sample_is_exact(self) -> "M2CS4DecisionLevelTrainingSampleV1":
        observation_revision = (
            "V3" if self.observation.schema_version == "PathBlockedPublicObservationV3" else "V4"
        )
        if self.evidence_revision != observation_revision:
            raise ValueError("decision sample revision differs from observation")
        if self.pointer_head_supervision_eligible != (self.pointer_class_index is not None):
            raise ValueError("pointer label differs from its supervision mask")
        payload = self.model_dump(mode="json", exclude={"sample_sha256"})
        if self.sample_sha256 != canonical_sha256(payload):
            raise ValueError("decision training sample digest mismatch")
        return self


class M2CS4DecisionLevelSupervisionRowV1(StrictModel):
    schema_version: Literal["M2CS4DecisionLevelSupervisionRowV1"] = (
        "M2CS4DecisionLevelSupervisionRowV1"
    )
    row_id: str = Field(min_length=1)
    evidence_revision: Literal["V3", "V4"]
    episode_id: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    episode_terminal_outcome: EpisodeTerminalOutcomeV1
    episode_final_task_success: bool
    terminal_step_physically_succeeded: bool
    terminal_step_row: bool
    source_report: BoundEvidenceFileV1
    source_raw_evidence: BoundEvidenceFileV1
    eligibility_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_sample: M2CS4DecisionLevelTrainingSampleV1
    episode_level_training_eligible: Literal[False]
    decision_level_training_eligible: Literal[True]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def row_is_exact(self) -> "M2CS4DecisionLevelSupervisionRowV1":
        if self.evidence_revision != self.training_sample.evidence_revision:
            raise ValueError("decision row revision differs from its training sample")
        if (
            self.training_sample.episode_id != self.episode_id
            or self.training_sample.matched_key != self.matched_key
            or self.training_sample.decision_index != self.decision_index
            or self.training_sample.source_evidence_sha256 != self.source_raw_evidence.sha256
        ):
            raise ValueError("decision row identity differs from its training sample")
        if self.terminal_step_row != (self.decision_index == 7):
            raise ValueError("terminal row marker differs from decision index")
        if self.terminal_step_row and not self.terminal_step_physically_succeeded:
            raise ValueError("terminal decision row lacks physical terminal success")
        payload = self.model_dump(mode="json", exclude={"row_sha256"})
        if self.row_sha256 != canonical_sha256(payload):
            raise ValueError("decision row digest mismatch")
        return self


class DecisionDatasetShardV1(StrictModel):
    revision: Literal["V3", "V4"]
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    row_count: int = Field(gt=0)


class M2CS4DecisionLevelDatasetManifestV1(StrictModel):
    schema_version: Literal["M2CS4DecisionLevelDatasetManifestV1"] = (
        "M2CS4DecisionLevelDatasetManifestV1"
    )
    status: Literal["PASS_ADR0026_DECISION_LEVEL_DATASET"]
    accepted_adr: BoundEvidenceFileV1
    source_yield_audit: BoundEvidenceFileV1
    shards: list[DecisionDatasetShardV1] = Field(min_length=2, max_length=2)
    replayed_complete_chains: Literal[49]
    qualifying_prefix_episodes: Literal[49]
    excluded_prefix_episodes: Literal[0]
    final_successful_episodes: Literal[0]
    final_failed_episodes: Literal[49]
    terminal_physically_successful_episodes: Literal[1]
    terminal_physically_failed_episodes: Literal[48]
    decision_rows_total: Literal[344]
    decision_rows_v3: Literal[71]
    decision_rows_v4: Literal[273]
    skill_head_supervised_rows: Literal[344]
    pointer_head_supervised_rows: Literal[330]
    pointer_head_masked_rows: Literal[14]
    destination_head_supervised_rows: Literal[344]
    decision_index_counts: dict[str, int]
    terminal_outcome_episode_counts: dict[str, int]
    terminal_outcome_row_counts: dict[str, int]
    pointer_masked_decisions: list[dict[str, object]] = Field(min_length=14, max_length=14)
    training_executed: Literal[False]
    model_rollout_executed: Literal[False]
    formal_q_b_evaluation_executed: Literal[False]
    q_b_success_definition_changed: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    bundle_smoke_checkpoint_asia_shanghai: Literal["2026-08-20"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def dataset_totals_are_exact(self) -> "M2CS4DecisionLevelDatasetManifestV1":
        if {item.revision for item in self.shards} != {"V3", "V4"}:
            raise ValueError("decision dataset must contain separate V3 and V4 shards")
        if sum(item.row_count for item in self.shards) != self.decision_rows_total:
            raise ValueError("decision shard row counts differ from total")
        expected_indices = {str(index): 49 for index in PREFIX_DECISION_INDICES}
        expected_indices["7"] = 1
        if self.decision_index_counts != expected_indices:
            raise ValueError("decision index histogram differs from ADR-0026 projection")
        if (
            self.skill_head_supervised_rows != self.decision_rows_total
            or self.destination_head_supervised_rows != self.decision_rows_total
            or self.pointer_head_supervised_rows + self.pointer_head_masked_rows
            != self.decision_rows_total
            or len(self.pointer_masked_decisions) != self.pointer_head_masked_rows
        ):
            raise ValueError("decision head supervision totals differ")
        if sum(self.terminal_outcome_episode_counts.values()) != 49:
            raise ValueError("terminal outcome episode histogram differs")
        if sum(self.terminal_outcome_row_counts.values()) != self.decision_rows_total:
            raise ValueError("terminal outcome row histogram differs")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != canonical_sha256(payload):
            raise ValueError("decision dataset manifest digest mismatch")
        return self
