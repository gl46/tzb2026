"""Strict evidence contracts for an ADR-approved M2C S5 closed loop.

These models do not authorize a residual architecture.  They only describe
the minimum evidence envelope that a separately accepted human ADR and its
implementation must produce before an S5 result can be summarized.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.closed_loop_metrics import M2BClosedLoopEpisodeV1
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import physical_receipt_sha256
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2


S5Method = Literal["QRM_COARSE_FC", "QRM_COARSE_FC_MLP"]
S5ResidualMode = Literal["ZERO_RESIDUAL", "MLP_RESIDUAL"]
S5_OPTION_A_ADR_MARKER = "M2C-S5-SELECTED-OPTION: A"


def validate_s5_accepted_adr_text(text: str, *, selected_option: str) -> None:
    """Require a human-readable acceptance and an exact machine-readable option."""

    if "Status: Accepted" not in text or "NOT APPROVED" in text:
        raise ValueError("S5 governance does not bind an accepted human ADR")
    expected = {"A": S5_OPTION_A_ADR_MARKER}.get(selected_option)
    if expected is None or expected not in text.splitlines():
        raise ValueError("S5 accepted ADR does not bind the implemented selected option")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BoundFileV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class S5AcceptedGovernanceReceiptV1(StrictModel):
    """A committed, separate human approval; the request document is invalid."""

    schema_version: Literal["M2CS5AcceptedGovernanceReceiptV1"]
    status: Literal["ACCEPTED_HUMAN_ADR"]
    # Only option A has an implemented evidence contract.  A future approval
    # of option B must land its full-dimension contract as a separate formal
    # code change; accepting B under the translation-only schema would be a
    # silent architecture substitution.
    selected_option: Literal["A"]
    adr: BoundFileV1
    approval_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    world_model_mainline_mandatory: Literal[True]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    b0_changed: Literal[False]
    safety_or_execution_gate_changed: Literal[False]


class S5ResidualEpisodeEvidenceV1(StrictModel):
    schema_version: Literal["M2CS5ResidualEpisodeEvidenceV1"]
    episode: M2BClosedLoopEpisodeV1
    physical_execution_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residual_mode: S5ResidualMode
    world_model_mainline_replaced: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def mode_matches_method(self) -> "S5ResidualEpisodeEvidenceV1":
        expected = {
            "QRM_COARSE_FC": "ZERO_RESIDUAL",
            "QRM_COARSE_FC_MLP": "MLP_RESIDUAL",
        }.get(self.episode.method)
        if expected is None or self.residual_mode != expected:
            raise ValueError("S5 residual mode differs from the episode method")
        return self


class S5PhysicalExecutionReceiptV1(StrictModel):
    """One real S5 arm execution bound to its world-model and exact plan."""

    schema_version: Literal["M2CS5PhysicalExecutionReceiptV1"]
    evidence_origin: Literal["FORMAL_ISAAC_S5_RESIDUAL_CLOSED_LOOP"]
    execution_mode: Literal["REAL_PHYSICS_NO_MOCKS"]
    host: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    collected_at_ns: int = Field(gt=0)
    episode_id: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    method: S5Method
    residual_mode: S5ResidualMode
    final_task_success: bool
    qwen_world_model_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residual_checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    nominal_action_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residual_input_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    residual_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residual_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    residual_is_exact_zero: bool
    exact_execution_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executed_exact_execution_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_skill_receipts: list[PhysicalSkillReceiptV2] = Field(min_length=1)
    r6d_residual_exact_zero: bool
    gripper_residual_exact_zero: bool
    real_physics: Literal[True] = True
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    world_model_mainline: Literal[True] = True
    residual_refines_world_model_action: Literal[True] = True
    residual_selects_or_replaces_skill: Literal[False] = False
    b0_fallback_or_continuation_used: Literal[False] = False
    collision_or_safety_violation: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def provenance_and_execution_are_exact(self) -> "S5PhysicalExecutionReceiptV1":
        expected_mode = {
            "QRM_COARSE_FC": "ZERO_RESIDUAL",
            "QRM_COARSE_FC_MLP": "MLP_RESIDUAL",
        }[self.method]
        if self.residual_mode != expected_mode:
            raise ValueError("S5 receipt residual mode differs from its method")
        if self.method == "QRM_COARSE_FC":
            if (
                self.residual_checkpoint_sha256 is not None
                or self.residual_input_sha256 is not None
                or not self.residual_is_exact_zero
            ):
                raise ValueError("zero-residual arm contains active residual provenance")
        elif (
            self.residual_checkpoint_sha256 is None
            or self.residual_input_sha256 is None
            or self.residual_is_exact_zero
        ):
            raise ValueError("MLP-residual arm lacks active residual provenance")
        if self.exact_execution_plan_sha256 != self.executed_exact_execution_plan_sha256:
            raise ValueError("S5 executed plan differs from the preflighted exact plan")
        if not self.r6d_residual_exact_zero or not self.gripper_residual_exact_zero:
            raise ValueError(
                "S5 receipt activates r6d/gripper without an implemented full-dimension contract"
            )
        receipt_ids: set[str] = set()
        receipt_hashes: set[str] = set()
        for receipt in self.physical_skill_receipts:
            if receipt.receipt_sha256 != physical_receipt_sha256(receipt):
                raise ValueError("S5 physical skill receipt hash is not canonical")
            if receipt.receipt_id in receipt_ids or receipt.receipt_sha256 in receipt_hashes:
                raise ValueError("S5 physical skill receipt is reused")
            receipt_ids.add(receipt.receipt_id)
            receipt_hashes.add(receipt.receipt_sha256)
            if (
                not receipt.physically_executed
                or receipt.execution_source != "MODEL_SELECTED_REGISTERED_SKILL"
                or receipt.fallback_reason is not None
                or receipt.collision_or_safety_violation
            ):
                raise ValueError("S5 receipt is not a pure model-owned physical execution")
            for gate in (
                "schema_gate",
                "stale_track_gate",
                "frame_unit_gate",
                "ik_gate",
                "collision_gate",
                "controller_gate",
                "safety_gate",
            ):
                if getattr(receipt, gate) != "PASS":
                    raise ValueError(f"S5 physical receipt has non-passing {gate}")
            if receipt.teacher_used or receipt.privileged_truth_policy_input:
                raise ValueError("S5 physical receipt violates Teacher/truth boundary")
        return self

    def required_raw_digests(self) -> set[str]:
        required = {
            self.qwen_world_model_bundle_sha256,
            self.nominal_action_sha256,
            self.residual_output_sha256,
            self.residual_protocol_sha256,
            self.exact_execution_plan_sha256,
            *(receipt.receipt_sha256 for receipt in self.physical_skill_receipts),
        }
        if self.residual_checkpoint_sha256 is not None:
            required.add(self.residual_checkpoint_sha256)
        if self.residual_input_sha256 is not None:
            required.add(self.residual_input_sha256)
        return required

    def validate_episode_binding(self, row: S5ResidualEpisodeEvidenceV1) -> None:
        episode = row.episode
        if (
            self.run_id != episode.episode_id
            or self.episode_id != episode.episode_id
            or self.matched_key != episode.matched_key
            or self.method != episode.method
            or self.residual_mode != row.residual_mode
            or self.final_task_success != episode.final_success
        ):
            raise ValueError("S5 physical receipt differs from its episode evidence")
