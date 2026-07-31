"""Hash-bound prospective Isaac runtime-mapping evidence for M2B."""

from __future__ import annotations

from collections import Counter
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.skill_registry import (
    MappingRejection,
    RuntimeSkillMappingResultV1,
    RuntimeSkillRequestV1,
)


GateStatus = Literal["PASS", "REJECTED", "NOT_APPLICABLE", "NOT_RUN"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class M2BProspectiveRuntimeDecisionV1(StrictModel):
    schema_version: Literal["M2BProspectiveRuntimeDecisionV1"] = (
        "M2BProspectiveRuntimeDecisionV1"
    )
    decision_id: str
    sample_id: str
    failure_type: Literal[
        "EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"
    ]
    request: RuntimeSkillRequestV1
    mapping: RuntimeSkillMappingResultV1
    ik_gate: GateStatus
    collision_gate: GateStatus
    safety_gate: GateStatus
    registry_sha256: str
    model_checkpoint_sha256: str
    model_input_sha256: str
    model_output_sha256: str
    request_sha256: str
    mapping_result_sha256: str
    source_hashes: dict[str, str] = Field(default_factory=dict)
    isolated_preflight_evidence_sha256: str | None = None
    prospective_planning_check: bool
    isolated_from_evaluation_rollout: bool
    evaluation_execution_started: bool
    model_selected: Literal[True] = True
    privileged_truth_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False

    @model_validator(mode="after")
    def evidence_is_prospective_and_hash_bound(
        self,
    ) -> "M2BProspectiveRuntimeDecisionV1":
        provenance = {
            "registry": self.registry_sha256,
            "checkpoint": self.model_checkpoint_sha256,
            "input": self.model_input_sha256,
            "output": self.model_output_sha256,
            "request": self.request_sha256,
            "mapping_result": self.mapping_result_sha256,
        }
        invalid = sorted(
            name
            for name, digest in provenance.items()
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None
        )
        if invalid:
            raise ValueError(
                f"runtime decision lacks hash-bound provenance: {invalid}"
            )
        gates = (self.ik_gate, self.collision_gate, self.safety_gate)
        planning_rejections = {
            MappingRejection.IK_REJECTION,
            MappingRejection.COLLISION_REJECTION,
            MappingRejection.SAFETY_REJECTION,
        }
        planning_ran = self.mapping.status == "VALID" or (
            self.mapping.rejection_reason in planning_rejections
        )
        if planning_ran:
            if (
                not self.prospective_planning_check
                or not self.isolated_from_evaluation_rollout
                or self.evaluation_execution_started
            ):
                raise ValueError(
                    "planning evidence is not prospective to evaluation execution"
                )
            if "NOT_RUN" in gates:
                raise ValueError(
                    "prospective planning evidence has an unrun gate"
                )
            if re.fullmatch(
                r"[0-9a-f]{64}",
                self.isolated_preflight_evidence_sha256 or "",
            ) is None:
                raise ValueError(
                    "prospective planning lacks isolated preflight evidence"
                )
            if not self.source_hashes or any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in self.source_hashes.values()
            ):
                raise ValueError(
                    "prospective planning lacks hash-bound scene sources"
                )
        elif self.prospective_planning_check:
            raise ValueError(
                "structural rejection may not claim a planning preflight"
            )
        if self.mapping.status == "VALID" and "REJECTED" in gates:
            raise ValueError("valid runtime mapping contains a rejected gate")
        if self.mapping.status == "REJECTED" and planning_ran:
            expected_gate = {
                MappingRejection.IK_REJECTION: self.ik_gate,
                MappingRejection.COLLISION_REJECTION: self.collision_gate,
                MappingRejection.SAFETY_REJECTION: self.safety_gate,
            }[self.mapping.rejection_reason]
            if expected_gate != "REJECTED":
                raise ValueError(
                    "planning rejection disagrees with its gate status"
                )
        return self

    @property
    def executable_mapping(self) -> bool:
        return bool(
            self.mapping.status == "VALID"
            and all(
                gate in {"PASS", "NOT_APPLICABLE"}
                for gate in (
                    self.ik_gate,
                    self.collision_gate,
                    self.safety_gate,
                )
            )
        )


def summarize_prospective_runtime_mapping(
    records: list[M2BProspectiveRuntimeDecisionV1],
) -> dict[str, object]:
    executable = [record for record in records if record.executable_mapping]
    planning_complete = all(
        record.prospective_planning_check
        if record.mapping.status == "VALID"
        or record.mapping.rejection_reason
        in {
            MappingRejection.IK_REJECTION,
            MappingRejection.COLLISION_REJECTION,
            MappingRejection.SAFETY_REJECTION,
        }
        else True
        for record in records
    )
    failures = {record.failure_type for record in records}
    decision_ids = {record.decision_id for record in records}
    sample_ids = {record.sample_id for record in records}
    registry_hashes = {record.registry_sha256 for record in records}
    checkpoint_hashes = {
        record.model_checkpoint_sha256 for record in records
    }
    rate = len(executable) / len(records) if records else None
    findings = []
    if len(decision_ids) != len(records):
        findings.append("duplicate decision_id")
    if len(sample_ids) != len(records):
        findings.append("duplicate sample_id")
    if len(registry_hashes) != 1:
        findings.append("mixed runtime registries")
    if len(checkpoint_hashes) != 1:
        findings.append("mixed model checkpoints")
    formal_ready = bool(
        len(records) >= 20
        and failures
        == {"EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"}
        and planning_complete
        and rate is not None
        and rate >= 0.95
        and not findings
    )
    rejection_histogram = Counter(
        record.mapping.rejection_reason.value
        for record in records
        if record.mapping.rejection_reason is not None
    )
    return {
        "schema_version": "M2BProspectiveRuntimeMappingReportV1",
        "status": (
            "PASS_PROSPECTIVE_RUNTIME_MAPPING"
            if formal_ready
            else "IN_PROGRESS_PROSPECTIVE_RUNTIME_MAPPING"
        ),
        "model_outputs": len(records),
        "model_selected_decisions": len(records),
        "unique_decision_ids": len(decision_ids),
        "unique_sample_ids": len(sample_ids),
        "executable_mappings": len(executable),
        "runtime_mapping_rate": rate,
        "minimum_runtime_mapping_rate": 0.95,
        "planning_checks_complete": planning_complete,
        "failure_types": sorted(failures),
        "rejection_reason_histogram": dict(
            sorted(rejection_histogram.items())
        ),
        "findings": findings,
        "formal_mapping_ready": formal_ready,
        "prospective_preflight_only": True,
        "post_execution_receipts_promoted": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
