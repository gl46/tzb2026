"""Strict M2B matched closed-loop attribution and metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


GateStatus = Literal["PASS", "REJECTED", "NOT_APPLICABLE", "NOT_RUN"]
Method = Literal[
    "B0",
    "QRM_COARSE_NO_FC",
    "QRM_COARSE_FC",
    "QRM_COARSE_FC_MLP",
]
ExecutionSource = Literal[
    "MODEL_SELECTED_B0_SKILL",
    "B0_FALLBACK",
    "B0_BASELINE",
    "NONE",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class M2BClosedLoopDecisionV1(StrictModel):
    schema_version: Literal["M2BClosedLoopDecisionV1"] = (
        "M2BClosedLoopDecisionV1"
    )
    decision_id: str
    step_id: int = Field(ge=0)
    selected_skill: str
    previous_failed_skill: str | None = None
    model_decision: bool
    mapping_status: Literal["VALID", "REJECTED", "NOT_APPLICABLE"]
    ik_gate: GateStatus
    collision_gate: GateStatus
    safety_gate: GateStatus
    execution_source: ExecutionSource
    executed_skill: str | None = None
    fallback_reason: str | None = None
    outcome: Literal["SUCCESS", "FAILURE", "UNKNOWN"] = "UNKNOWN"
    collision_or_safety_violation: bool = False
    registry_sha256: str | None = None
    model_checkpoint_sha256: str | None = None
    model_input_sha256: str | None = None
    model_output_sha256: str | None = None
    mapping_result_sha256: str | None = None
    gate_evidence_sha256: dict[str, str] = Field(default_factory=dict)
    privileged_truth_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False

    @model_validator(mode="after")
    def attribution_is_consistent(self) -> "M2BClosedLoopDecisionV1":
        gates = (self.ik_gate, self.collision_gate, self.safety_gate)
        if self.model_decision:
            provenance = {
                "registry": self.registry_sha256,
                "checkpoint": self.model_checkpoint_sha256,
                "input": self.model_input_sha256,
                "output": self.model_output_sha256,
                "mapping_result": self.mapping_result_sha256,
            }
            invalid = sorted(
                name
                for name, digest in provenance.items()
                if digest is None
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            )
            if invalid:
                raise ValueError(
                    "model decision lacks hash-bound provenance: "
                    f"{invalid}"
                )
        if self.execution_source == "MODEL_SELECTED_B0_SKILL":
            if not self.model_decision or self.mapping_status != "VALID":
                raise ValueError("model execution requires a valid model mapping")
            if "REJECTED" in gates or "NOT_RUN" in gates:
                raise ValueError("model execution requires completed passing gates")
            if self.executed_skill != self.selected_skill:
                raise ValueError("executed model skill differs from selected skill")
            if self.fallback_reason is not None:
                raise ValueError("model execution may not carry a fallback reason")
            missing_gate_evidence = sorted(
                gate
                for gate in ("ik", "collision", "safety")
                if re.fullmatch(
                    r"[0-9a-f]{64}",
                    self.gate_evidence_sha256.get(gate, ""),
                )
                is None
            )
            if missing_gate_evidence:
                raise ValueError(
                    "model execution lacks gate evidence hashes: "
                    f"{missing_gate_evidence}"
                )
        if self.execution_source == "B0_FALLBACK":
            if not self.model_decision or not self.fallback_reason:
                raise ValueError("B0 fallback requires a model decision and reason")
        if self.execution_source == "B0_BASELINE" and self.model_decision:
            raise ValueError("B0 baseline may not be attributed to a model")
        if self.execution_source == "NONE" and self.executed_skill is not None:
            raise ValueError("non-execution may not name an executed skill")
        if self.collision_or_safety_violation and self.outcome == "SUCCESS":
            raise ValueError("a safety violation may not be a successful decision")
        return self


class M2BClosedLoopEpisodeV1(StrictModel):
    schema_version: Literal["M2BClosedLoopEpisodeV1"] = (
        "M2BClosedLoopEpisodeV1"
    )
    episode_id: str
    matched_key: str
    method: Method
    scene_seed: int
    failure_type: str
    initial_success: bool
    final_success: bool
    recovery_attempted: bool
    recovery_success: bool | None = None
    retries: int = Field(ge=0)
    task_time_s: float = Field(ge=0.0)
    decisions: list[M2BClosedLoopDecisionV1] = Field(min_length=1)
    collision_or_safety_violation: bool = False
    privileged_truth_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False

    @model_validator(mode="after")
    def episode_is_consistent(self) -> "M2BClosedLoopEpisodeV1":
        if self.recovery_success is not None and not self.recovery_attempted:
            raise ValueError("recovery result exists without a recovery attempt")
        if self.collision_or_safety_violation != any(
            decision.collision_or_safety_violation
            for decision in self.decisions
        ):
            raise ValueError("episode safety flag differs from decision evidence")
        if self.method == "B0" and any(
            decision.model_decision for decision in self.decisions
        ):
            raise ValueError("B0 episode contains a model decision")
        if self.method != "B0" and not any(
            decision.model_decision for decision in self.decisions
        ):
            raise ValueError("QRM episode contains no model decision")
        return self


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize_method(
    episodes: list[M2BClosedLoopEpisodeV1],
) -> dict[str, object]:
    decisions = [decision for episode in episodes for decision in episode.decisions]
    model = [decision for decision in decisions if decision.model_decision]
    valid = [decision for decision in model if decision.mapping_status == "VALID"]
    executed = [
        decision
        for decision in model
        if decision.execution_source == "MODEL_SELECTED_B0_SKILL"
    ]
    fallback = [
        decision
        for decision in model
        if decision.execution_source == "B0_FALLBACK"
    ]
    system_success_with_fallback = [
        episode
        for episode in episodes
        if episode.final_success
        and any(
            decision.execution_source == "B0_FALLBACK"
            for decision in episode.decisions
        )
    ]
    system_success_with_non_model_continuation = [
        episode
        for episode in episodes
        if episode.method != "B0"
        and episode.final_success
        and any(
            decision.execution_source == "B0_BASELINE"
            for decision in episode.decisions
        )
    ]
    model_success_episodes = [
        episode
        for episode in episodes
        if episode.final_success
        and any(
            decision.execution_source == "MODEL_SELECTED_B0_SKILL"
            for decision in episode.decisions
        )
        and not any(
            decision.execution_source in {"B0_FALLBACK", "B0_BASELINE"}
            for decision in episode.decisions
        )
    ]
    recovery = [episode for episode in episodes if episode.recovery_attempted]
    recovery_success = [
        episode for episode in recovery if episode.recovery_success is True
    ]
    repeat_eligible = [
        decision
        for decision in model
        if decision.previous_failed_skill is not None
    ]
    repeat = [
        decision
        for decision in repeat_eligible
        if decision.selected_skill == decision.previous_failed_skill
    ]
    safety_rejected = [
        decision for decision in model if decision.safety_gate == "REJECTED"
    ]
    invalid = [
        decision for decision in model if decision.mapping_status == "REJECTED"
    ]
    failure_totals = Counter(episode.failure_type for episode in recovery)
    failure_success = Counter(
        episode.failure_type
        for episode in recovery
        if episode.recovery_success is True
    )
    return {
        "episodes": len(episodes),
        "decisions_total": len(decisions),
        "model_decisions_total": len(model),
        "model_decisions_valid": len(valid),
        "model_decisions_executed": len(executed),
        "model_decisions_fallback": len(fallback),
        "model_execution_coverage": _rate(len(executed), len(model)),
        "invalid_mapping_rate": _rate(len(invalid), len(model)),
        "safety_rejection_rate": _rate(len(safety_rejected), len(model)),
        "b0_fallback_rate": _rate(len(fallback), len(model)),
        "initial_success_rate": _rate(
            sum(episode.initial_success for episode in episodes), len(episodes)
        ),
        "final_task_success_rate": _rate(
            sum(episode.final_success for episode in episodes), len(episodes)
        ),
        "conditional_recovery_success_rate": _rate(
            len(recovery_success), len(recovery)
        ),
        "per_failure_recovery_rate": {
            failure: _rate(failure_success[failure], total)
            for failure, total in sorted(failure_totals.items())
        },
        "same_failed_action_repeat_rate": _rate(
            len(repeat), len(repeat_eligible)
        ),
        "average_retries": (
            sum(episode.retries for episode in episodes) / len(episodes)
            if episodes
            else None
        ),
        "average_task_time_s": (
            sum(episode.task_time_s for episode in episodes) / len(episodes)
            if episodes
            else None
        ),
        "system_success_with_b0_fallback": len(system_success_with_fallback),
        "system_success_with_non_model_continuation": len(
            system_success_with_non_model_continuation
        ),
        "model_success_episodes": len(model_success_episodes),
        "model_executed_successful_decisions": sum(
            decision.outcome == "SUCCESS" for decision in executed
        ),
        "collision_or_safety_violations": sum(
            episode.collision_or_safety_violation for episode in episodes
        ),
        "fallback_reason_histogram": dict(
            sorted(
                Counter(
                    decision.fallback_reason
                    for decision in fallback
                    if decision.fallback_reason is not None
                ).items()
            )
        ),
    }


def summarize_matched(
    episodes: list[M2BClosedLoopEpisodeV1],
    *,
    expected_methods: tuple[Method, ...],
) -> dict[str, object]:
    by_method: dict[str, list[M2BClosedLoopEpisodeV1]] = defaultdict(list)
    by_key: dict[str, list[M2BClosedLoopEpisodeV1]] = defaultdict(list)
    findings: list[str] = []
    mandatory_methods = {
        "B0",
        "QRM_COARSE_NO_FC",
        "QRM_COARSE_FC",
    }
    missing_mandatory = mandatory_methods - set(expected_methods)
    if missing_mandatory:
        findings.append(
            f"mandatory methods absent: {sorted(missing_mandatory)}"
        )
    episode_ids = [episode.episode_id for episode in episodes]
    duplicate_episode_ids = sorted(
        episode_id
        for episode_id in set(episode_ids)
        if episode_ids.count(episode_id) > 1
    )
    if duplicate_episode_ids:
        findings.append(
            f"duplicate episode IDs: {duplicate_episode_ids}"
        )
    decision_ids = [
        decision.decision_id
        for episode in episodes
        for decision in episode.decisions
    ]
    duplicate_decision_ids = sorted(
        decision_id
        for decision_id in set(decision_ids)
        if decision_ids.count(decision_id) > 1
    )
    if duplicate_decision_ids:
        findings.append(
            f"duplicate decision IDs: {duplicate_decision_ids}"
        )
    for episode in episodes:
        by_method[episode.method].append(episode)
        by_key[episode.matched_key].append(episode)
    expected = set(expected_methods)
    for key, group in sorted(by_key.items()):
        methods = [episode.method for episode in group]
        missing = expected - set(methods)
        duplicates = sorted(
            method for method in set(methods) if methods.count(method) > 1
        )
        if missing:
            findings.append(f"{key}: missing methods {sorted(missing)}")
        if duplicates:
            findings.append(f"{key}: duplicate methods {duplicates}")
        seeds = {episode.scene_seed for episode in group}
        failures = {episode.failure_type for episode in group}
        if len(seeds) != 1 or len(failures) != 1:
            findings.append(f"{key}: scene/failure mismatch")
    method_metrics = {
        method: summarize_method(by_method.get(method, []))
        for method in expected_methods
    }
    qrm_executed = sum(
        int(method_metrics[method]["model_decisions_executed"])
        for method in expected_methods
        if method != "B0"
    )
    complete_keys = sum(
        {episode.method for episode in group} == expected
        and len(group) == len(expected)
        for group in by_key.values()
    )
    formal_ready = bool(
        not findings
        and complete_keys >= 10
        and len(episodes) >= 30
        and qrm_executed >= 20
    )
    return {
        "schema_version": "M2BMatchedClosedLoopReportV1",
        "status": (
            "PASS_FORMAL_MATCHED_EVALUATION_COMPLETE"
            if formal_ready
            else "IN_PROGRESS_NOT_FORMAL"
        ),
        "expected_methods": list(expected_methods),
        "episodes": len(episodes),
        "matched_keys": len(by_key),
        "complete_matched_keys": complete_keys,
        "unique_episode_ids": len(set(episode_ids)),
        "unique_decision_ids": len(set(decision_ids)),
        "qrm_model_decisions_executed": qrm_executed,
        "minimum_model_executed_gate": 20,
        "method_metrics": method_metrics,
        "findings": findings,
        "formal_evaluation_ready": formal_ready,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "world_model_replaced": False,
    }
