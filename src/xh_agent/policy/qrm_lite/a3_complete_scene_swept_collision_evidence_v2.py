"""Replayable complete-scene A.3 evidence for one exact-plan motion phase."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_attached_object_phase_geometry_v1 import (
    A3AttachedObjectPhaseGeometryEvidenceV1,
)
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
    build_child_pair_ccd_request_v1,
    verify_child_pair_ccd_receipt_v1,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_collision_v2 import (
    A3CompleteSceneCollisionWorldV2,
    build_a3_complete_scene_collision_world_v2,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3SceneStateReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3CompleteScenePhaseSweptCollisionEvidenceV2(_FrozenModel):
    schema_version: Literal["A3CompleteScenePhaseSweptCollisionEvidenceV2"] = (
        "A3CompleteScenePhaseSweptCollisionEvidenceV2"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    collision_geometry_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    native_backend_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    executor_joint_names: tuple[str, ...] = Field(min_length=1)
    executor_joint_state_sequence: tuple[tuple[float, ...], ...] = Field(min_length=2)
    robot_geometry: A3ControlledPandaGeometryReceiptV1
    attached_objects: tuple[A3AttachedObjectGeometryV1, ...] = ()
    attached_object_phase_geometry_evidence: tuple[
        A3AttachedObjectPhaseGeometryEvidenceV1, ...
    ] = ()
    fk_receipt: A3ReadOnlyFKReceiptV1
    scene_geometry: A3SceneCollisionGeometryReceiptV1
    scene_state: A3SceneStateReceiptV1
    complete_scene_world: A3CompleteSceneCollisionWorldV2
    numeric_configuration: A3BulletNumericConfigurationV1
    child_pair_request: A3ChildPairCCDRequestV1
    native_receipt: A3ChildPairCCDReceiptV1
    complete_robot_self_child_pair_product: Literal[True] = True
    complete_robot_environment_child_pair_product: Literal[True] = True
    complete_attached_environment_child_pair_product: Literal[True] = True
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
    def replay_complete_scene_query(
        self,
    ) -> "A3CompleteScenePhaseSweptCollisionEvidenceV2":
        if any(
            len(state) != len(self.executor_joint_names)
            for state in self.executor_joint_state_sequence
        ):
            raise ValueError("A.3 complete-scene joint-state sequence width differs")
        expected_states = canonical_sha256(
            {
                "joint_names": self.executor_joint_names,
                "joint_state_sequence": self.executor_joint_state_sequence,
            }
        )
        if (
            self.fk_receipt.bound_plan_sha256 != self.bound_plan_sha256
            or self.fk_receipt.geometry_receipt_sha256 != self.robot_geometry.receipt_sha256
            or self.fk_receipt.executor_joint_state_sequence_sha256 != expected_states
            or self.fk_receipt.executor_state_count != len(self.executor_joint_state_sequence)
            or self.scene_state.bound_plan_sha256 != self.bound_plan_sha256
            or self.native_receipt.backend_implementation_sha256
            != self.native_backend_implementation_sha256
            or tuple(item.geometry for item in self.attached_object_phase_geometry_evidence)
            != self.attached_objects
            or any(
                item.bound_plan_sha256 != self.bound_plan_sha256
                or item.phase_index != self.phase_index
                or item.phase_sha256 != self.phase_sha256
                or item.path_sha256 != self.path_sha256
                for item in self.attached_object_phase_geometry_evidence
            )
        ):
            raise ValueError("A.3 complete-scene evidence crossed plan/path dependencies")
        try:
            base_world = build_self_collision_world_from_fk_v1(
                geometry=self.robot_geometry,
                fk_receipt=self.fk_receipt,
                require_real_runtime_provider=self.formal_query_evidence_eligible,
                attached_objects=self.attached_objects,
            )
            expected_complete = build_a3_complete_scene_collision_world_v2(
                bound_plan_sha256=self.bound_plan_sha256,
                phase_index=self.phase_index,
                phase_sha256=self.phase_sha256,
                path_sha256=self.path_sha256,
                base_world=base_world,
                base_shape_payloads=(
                    *self.robot_geometry.shape_payloads,
                    *(payload for item in self.attached_objects for payload in item.shape_payloads),
                ),
                scene_geometry=self.scene_geometry,
                scene_state=self.scene_state,
                allowed_robot_contact_paths=(self.complete_scene_world.allowed_robot_contact_paths),
                allowed_external_contact_paths=(
                    self.complete_scene_world.allowed_external_contact_paths
                ),
                real_attached_geometry_resolver=(
                    self.complete_scene_world.real_attached_geometry_resolver
                ),
                contract_test_only=self.complete_scene_world.contract_test_only,
            )
        except Exception as exc:
            raise ValueError("A.3 complete-scene world replay failed") from exc
        if expected_complete != self.complete_scene_world:
            raise ValueError("A.3 complete-scene world differs from replay")
        expected_geometry_binding = canonical_sha256(
            {
                "schema_version": "A3CompleteSceneCollisionGeometryBindingV2",
                "robot_geometry_receipt_sha256": self.robot_geometry.receipt_sha256,
                "scene_geometry_receipt_sha256": self.scene_geometry.receipt_sha256,
            }
        )
        if self.collision_geometry_binding_sha256 != expected_geometry_binding:
            raise ValueError("A.3 complete-scene geometry binding differs")
        try:
            expected_request = build_child_pair_ccd_request_v1(
                bound_plan_sha256=self.bound_plan_sha256,
                world=expected_complete.collision_world,
                configuration=self.numeric_configuration,
            )
            verify_child_pair_ccd_receipt_v1(
                expected_request,
                self.native_receipt,
                configuration=self.numeric_configuration,
                require_real_native_backend=self.formal_query_evidence_eligible,
            )
        except Exception as exc:
            raise ValueError("A.3 complete-scene native query did not prove CLEAR") from exc
        if expected_request != self.child_pair_request or self.native_receipt.status != "PASS":
            raise ValueError("A.3 complete-scene request/receipt replay differs")
        expected_formal = bool(
            not self.robot_geometry.contract_test_only
            and self.fk_receipt.real_runtime_provider
            and not self.fk_receipt.contract_test_only
            and self.complete_scene_world.formal_query_evidence_eligible
            and self.native_receipt.real_native_backend
            and not self.native_receipt.contract_test_only
            and all(
                item.formal_query_evidence_eligible
                for item in self.attached_object_phase_geometry_evidence
            )
        )
        if self.formal_query_evidence_eligible != expected_formal:
            raise ValueError("A.3 complete-scene formal eligibility differs")
        if self.evidence_sha256 != canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        ):
            raise ValueError("A.3 complete-scene swept evidence digest differs")
        return self


def build_a3_complete_scene_phase_evidence_v2(
    *,
    bound_plan_sha256: str,
    phase_index: int,
    phase_sha256: str,
    path_sha256: str,
    phase_provider_implementation_sha256: str,
    phase_algorithm_sha256: str,
    collision_geometry_binding_sha256: str,
    native_backend_implementation_sha256: str,
    executor_joint_names: tuple[str, ...],
    executor_joint_state_sequence: tuple[tuple[float, ...], ...],
    robot_geometry: A3ControlledPandaGeometryReceiptV1,
    attached_objects: tuple[A3AttachedObjectGeometryV1, ...],
    attached_object_phase_geometry_evidence: tuple[A3AttachedObjectPhaseGeometryEvidenceV1, ...],
    fk_receipt: A3ReadOnlyFKReceiptV1,
    scene_geometry: A3SceneCollisionGeometryReceiptV1,
    scene_state: A3SceneStateReceiptV1,
    complete_scene_world: A3CompleteSceneCollisionWorldV2,
    numeric_configuration: A3BulletNumericConfigurationV1,
    child_pair_request: A3ChildPairCCDRequestV1,
    native_receipt: A3ChildPairCCDReceiptV1,
) -> A3CompleteScenePhaseSweptCollisionEvidenceV2:
    formal_eligible = bool(
        not robot_geometry.contract_test_only
        and fk_receipt.real_runtime_provider
        and not fk_receipt.contract_test_only
        and complete_scene_world.formal_query_evidence_eligible
        and native_receipt.real_native_backend
        and not native_receipt.contract_test_only
        and all(
            item.formal_query_evidence_eligible for item in attached_object_phase_geometry_evidence
        )
    )
    payload = {
        "schema_version": "A3CompleteScenePhaseSweptCollisionEvidenceV2",
        "bound_plan_sha256": bound_plan_sha256,
        "phase_index": phase_index,
        "phase_sha256": phase_sha256,
        "path_sha256": path_sha256,
        "phase_provider_implementation_sha256": phase_provider_implementation_sha256,
        "phase_algorithm_sha256": phase_algorithm_sha256,
        "collision_geometry_binding_sha256": collision_geometry_binding_sha256,
        "native_backend_implementation_sha256": native_backend_implementation_sha256,
        "executor_joint_names": executor_joint_names,
        "executor_joint_state_sequence": executor_joint_state_sequence,
        "robot_geometry": robot_geometry.model_dump(mode="json"),
        "attached_objects": [item.model_dump(mode="json") for item in attached_objects],
        "attached_object_phase_geometry_evidence": [
            item.model_dump(mode="json") for item in attached_object_phase_geometry_evidence
        ],
        "fk_receipt": fk_receipt.model_dump(mode="json"),
        "scene_geometry": scene_geometry.model_dump(mode="json"),
        "scene_state": scene_state.model_dump(mode="json"),
        "complete_scene_world": complete_scene_world.model_dump(mode="json"),
        "numeric_configuration": numeric_configuration.model_dump(mode="json"),
        "child_pair_request": child_pair_request.model_dump(mode="json"),
        "native_receipt": native_receipt.model_dump(mode="json"),
        "complete_robot_self_child_pair_product": True,
        "complete_robot_environment_child_pair_product": True,
        "complete_attached_environment_child_pair_product": True,
        "all_dynamic_subdivisions_replayed": True,
        "formal_query_evidence_eligible": formal_eligible,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return A3CompleteScenePhaseSweptCollisionEvidenceV2(
        **payload,
        evidence_sha256=canonical_sha256(payload),
    )
