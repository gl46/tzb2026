"""Replayable ADR-0024 A.3 evidence for one exact-plan motion phase.

The high-level preflight contract historically recorded only one summary row
per executor segment.  ADR-0024 requires stronger evidence: every decoded
controlled-Panda collision child, every non-ACM child pair, every executor
segment, and every rejection-biased dynamic subdivision must be covered by the
pinned float64 Bullet query.  This module is the versioned bridge between those
two layers.

It owns no simulator object and performs no actuation.  Validation rebuilds the
collision world and the complete child-pair request from the embedded immutable
inputs, then replays the native receipt predicate.  Contract fixtures remain
explicitly non-formal; only a real read-only FK provider plus the pinned native
backend can set ``formal_query_evidence_eligible``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3AttachedObjectGeometryV1,
    A3ControlledPandaGeometryReceiptV1,
    A3ReadOnlyFKReceiptV1,
    build_self_collision_world_from_fk_v1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3BulletNumericConfigurationV1,
    A3ChildPairCCDReceiptV1,
    A3ChildPairCCDRequestV1,
    A3SelfCollisionWorldV1,
    build_child_pair_ccd_request_v1,
    verify_child_pair_ccd_receipt_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3PhaseSweptCollisionEvidenceV1(_FrozenModel):
    """Complete pure-data replay inputs and outputs for one motion phase."""

    schema_version: Literal["A3PhaseSweptCollisionEvidenceV1"] = "A3PhaseSweptCollisionEvidenceV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    native_backend_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    executor_joint_names: tuple[str, ...] = Field(min_length=1)
    executor_joint_state_sequence: tuple[tuple[float, ...], ...] = Field(min_length=2)
    geometry: A3ControlledPandaGeometryReceiptV1
    attached_objects: tuple[A3AttachedObjectGeometryV1, ...] = ()
    fk_receipt: A3ReadOnlyFKReceiptV1
    collision_world: A3SelfCollisionWorldV1
    numeric_configuration: A3BulletNumericConfigurationV1
    child_pair_request: A3ChildPairCCDRequestV1
    native_receipt: A3ChildPairCCDReceiptV1
    complete_non_acm_child_pair_product: Literal[True] = True
    all_dynamic_subdivisions_replayed: Literal[True] = True
    formal_query_evidence_eligible: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def replay_complete_child_pair_query(self) -> "A3PhaseSweptCollisionEvidenceV1":
        if any(
            len(state) != len(self.executor_joint_names)
            for state in self.executor_joint_state_sequence
        ):
            raise ValueError("A.3 phase joint-state sequence width differs")
        expected_state_sha256 = canonical_sha256(
            {
                "joint_names": self.executor_joint_names,
                "joint_state_sequence": self.executor_joint_state_sequence,
            }
        )
        if (
            self.fk_receipt.bound_plan_sha256 != self.bound_plan_sha256
            or self.fk_receipt.geometry_receipt_sha256 != self.geometry.receipt_sha256
            or self.fk_receipt.executor_joint_state_sequence_sha256 != expected_state_sha256
            or self.fk_receipt.executor_state_count != len(self.executor_joint_state_sequence)
            or self.native_receipt.backend_implementation_sha256
            != self.native_backend_implementation_sha256
        ):
            raise ValueError("A.3 phase FK evidence crossed plan/geometry/path states")

        try:
            expected_world = build_self_collision_world_from_fk_v1(
                geometry=self.geometry,
                fk_receipt=self.fk_receipt,
                require_real_runtime_provider=self.formal_query_evidence_eligible,
                attached_objects=self.attached_objects,
            )
        except Exception as exc:
            raise ValueError("A.3 phase FK/geometry production binding differs") from exc
        if expected_world != self.collision_world:
            raise ValueError("A.3 phase collision world is not reproducible")
        try:
            expected_request = build_child_pair_ccd_request_v1(
                bound_plan_sha256=self.bound_plan_sha256,
                world=expected_world,
                configuration=self.numeric_configuration,
            )
        except Exception as exc:
            raise ValueError("A.3 phase child-pair request replay failed") from exc
        if expected_request != self.child_pair_request:
            raise ValueError("A.3 phase child-pair request is not reproducible")
        try:
            verify_child_pair_ccd_receipt_v1(
                expected_request,
                self.native_receipt,
                configuration=self.numeric_configuration,
                require_real_native_backend=self.formal_query_evidence_eligible,
            )
        except Exception as exc:
            raise ValueError("A.3 phase native CCD receipt does not prove CLEAR") from exc
        if self.native_receipt.status != "PASS":
            raise ValueError("A.3 phase native CCD aggregate did not pass")

        exact_formal_eligibility = bool(
            not self.geometry.contract_test_only
            and self.fk_receipt.real_runtime_provider
            and not self.fk_receipt.contract_test_only
            and self.native_receipt.real_native_backend
            and not self.native_receipt.contract_test_only
        )
        if self.formal_query_evidence_eligible != exact_formal_eligibility:
            raise ValueError("A.3 phase formal-query eligibility differs from dependencies")
        expected_digest = canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        )
        if self.evidence_sha256 != expected_digest:
            raise ValueError("A.3 phase swept-collision evidence digest differs")
        return self


def build_a3_phase_swept_collision_evidence_v1(
    *,
    bound_plan_sha256: str,
    phase_index: int,
    phase_sha256: str,
    path_sha256: str,
    phase_provider_implementation_sha256: str,
    phase_algorithm_sha256: str,
    native_backend_implementation_sha256: str,
    executor_joint_names: tuple[str, ...],
    executor_joint_state_sequence: tuple[tuple[float, ...], ...],
    geometry: A3ControlledPandaGeometryReceiptV1,
    attached_objects: tuple[A3AttachedObjectGeometryV1, ...],
    fk_receipt: A3ReadOnlyFKReceiptV1,
    collision_world: A3SelfCollisionWorldV1,
    numeric_configuration: A3BulletNumericConfigurationV1,
    child_pair_request: A3ChildPairCCDRequestV1,
    native_receipt: A3ChildPairCCDReceiptV1,
) -> A3PhaseSweptCollisionEvidenceV1:
    """Construct the canonical envelope; the model validator performs replay."""

    formal_eligible = bool(
        not geometry.contract_test_only
        and fk_receipt.real_runtime_provider
        and not fk_receipt.contract_test_only
        and native_receipt.real_native_backend
        and not native_receipt.contract_test_only
    )
    payload = {
        "schema_version": "A3PhaseSweptCollisionEvidenceV1",
        "bound_plan_sha256": bound_plan_sha256,
        "phase_index": phase_index,
        "phase_sha256": phase_sha256,
        "path_sha256": path_sha256,
        "phase_provider_implementation_sha256": phase_provider_implementation_sha256,
        "phase_algorithm_sha256": phase_algorithm_sha256,
        "native_backend_implementation_sha256": native_backend_implementation_sha256,
        "executor_joint_names": executor_joint_names,
        "executor_joint_state_sequence": executor_joint_state_sequence,
        "geometry": geometry.model_dump(mode="json"),
        "attached_objects": [item.model_dump(mode="json") for item in attached_objects],
        "fk_receipt": fk_receipt.model_dump(mode="json"),
        "collision_world": collision_world.model_dump(mode="json"),
        "numeric_configuration": numeric_configuration.model_dump(mode="json"),
        "child_pair_request": child_pair_request.model_dump(mode="json"),
        "native_receipt": native_receipt.model_dump(mode="json"),
        "complete_non_acm_child_pair_product": True,
        "all_dynamic_subdivisions_replayed": True,
        "formal_query_evidence_eligible": formal_eligible,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return A3PhaseSweptCollisionEvidenceV1(
        **payload,
        evidence_sha256=canonical_sha256(payload),
    )
