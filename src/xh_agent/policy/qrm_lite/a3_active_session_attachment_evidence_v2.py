"""Strict evidence models for carrying an executed attachment across plans."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_attached_object_phase_geometry_v1 import (
    A3AttachedObjectPhaseGeometryEvidenceV1,
    A3PlannedAttachedObjectBindingV1,
    _compose,
    _same_transform,
)
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3AttachedObjectGeometryV1,
    A3FileBindingV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3LinkChildTransformSequenceV1,
    A3RigidTransformV1,
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


def _model_sha256(model: BaseModel, field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={field}))


class A3ExecutedAttachmentBindingV2(_FrozenModel):
    """Post-helper registry receipt cross-bound to its preflight geometry."""

    schema_version: Literal["A3ExecutedAttachmentBindingV2"] = "A3ExecutedAttachmentBindingV2"
    public_track_id: str = Field(pattern=r"^track-[0-9a-f]{8}$")
    external_contact_path: str = Field(pattern=r"^/World/M1B/[^\s]+$")
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    planned_attachment_sha256: str = Field(pattern=SHA256_PATTERN)
    planned_attachment_binding: A3PlannedAttachedObjectBindingV1
    attached_at_ns: int = Field(gt=0)
    helper_returned_before_registry_commit: Literal[True] = True
    real_isaac: bool
    contract_test_only: bool
    formal_execution_evidence_eligible: bool
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "A3ExecutedAttachmentBindingV2":
        planned = self.planned_attachment_binding
        if (
            planned.bound_plan_sha256 != self.bound_plan_sha256
            or planned.attachment_sha256 != self.planned_attachment_sha256
            or planned.external_link_path != self.external_contact_path
            or planned.attachment_transition_evidence.phase_sha256 != self.phase_sha256
            or self.real_isaac == self.contract_test_only
        ):
            raise ValueError("executed attachment crossed its planned A.3 geometry")
        expected_formal = bool(
            self.real_isaac
            and not self.contract_test_only
            and planned.formal_query_evidence_eligible
        )
        if self.formal_execution_evidence_eligible != expected_formal:
            raise ValueError("executed attachment formal eligibility differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("executed attachment binding digest differs")
        return self


class A3ActiveSessionAttachedObjectBindingV2(_FrozenModel):
    """Current-plan geometry root for one previously executed attachment."""

    schema_version: Literal["A3ActiveSessionAttachedObjectBindingV2"] = (
        "A3ActiveSessionAttachedObjectBindingV2"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    active_attachment_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    active_attachment: A3ExecutedAttachmentBindingV2
    scene_geometry: A3SceneCollisionGeometryReceiptV1
    scene_state: A3SceneStateReceiptV1
    current_hand_world_transform: A3RigidTransformV1
    current_object_world_transform: A3RigidTransformV1
    hand_to_object_transform: A3RigidTransformV1
    resolver_implementation: A3FileBindingV1
    real_runtime_provider: bool
    contract_test_only: bool
    formal_query_evidence_eligible: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def replay_current_attachment(self) -> "A3ActiveSessionAttachedObjectBindingV2":
        active = self.active_attachment
        states = {item.link_path: item.world_transform for item in self.scene_state.link_states}
        path = active.external_contact_path
        if (
            self.real_runtime_provider == self.contract_test_only
            or self.active_attachment_receipt_sha256 != active.receipt_sha256
            or self.scene_state.bound_plan_sha256 != self.bound_plan_sha256
            or self.scene_state.geometry_receipt_sha256 != self.scene_geometry.receipt_sha256
            or path not in self.scene_geometry.dynamic_collision_link_paths
            or path not in states
            or states[path] != self.current_object_world_transform
            or active.planned_attachment_binding.scene_geometry.receipt_sha256
            != self.scene_geometry.receipt_sha256
        ):
            raise ValueError("active-session attachment crossed scene/plan/geometry")
        reconstructed = _compose(
            self.current_hand_world_transform,
            self.hand_to_object_transform,
        )
        if not _same_transform(reconstructed, self.current_object_world_transform):
            raise ValueError("active-session hand/object transform is not replayable")
        expected_formal = bool(
            self.real_runtime_provider
            and self.scene_state.real_runtime_provider
            and not self.scene_state.contract_test_only
            and active.formal_execution_evidence_eligible
            and active.planned_attachment_binding.formal_query_evidence_eligible
        )
        if self.formal_query_evidence_eligible != expected_formal:
            raise ValueError("active-session attachment formal eligibility differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("active-session attachment binding digest differs")
        return self


class A3AttachedObjectPhaseGeometryEvidenceV2(_FrozenModel):
    """Per-sample geometry replay rooted in an executed prior attachment."""

    schema_version: Literal["A3AttachedObjectPhaseGeometryEvidenceV2"] = (
        "A3AttachedObjectPhaseGeometryEvidenceV2"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_binding: A3ActiveSessionAttachedObjectBindingV2
    end_effector_world_transforms: tuple[A3RigidTransformV1, ...] = Field(min_length=2)
    geometry: A3AttachedObjectGeometryV1
    real_runtime_provider: bool
    contract_test_only: bool
    formal_query_evidence_eligible: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def replay_phase_geometry(self) -> "A3AttachedObjectPhaseGeometryEvidenceV2":
        binding = self.attachment_binding
        path = binding.active_attachment.external_contact_path
        source_children = tuple(
            item for item in binding.scene_geometry.children if item.link_path == path
        )
        source_payloads = tuple(
            item for item in binding.scene_geometry.shape_payloads if item.link_path == path
        )
        expected_transforms = tuple(
            A3LinkChildTransformSequenceV1(
                link_path=child.link_path,
                child_index=child.child_index,
                transforms=tuple(
                    _compose(
                        _compose(hand, binding.hand_to_object_transform),
                        child.local_transform,
                    )
                    for hand in self.end_effector_world_transforms
                ),
            )
            for child in source_children
        )
        if (
            self.bound_plan_sha256 != binding.bound_plan_sha256
            or self.geometry.attached_object_path != path
            or self.geometry.attachment_receipt_sha256 != binding.active_attachment_receipt_sha256
            or self.geometry.children != source_children
            or self.geometry.shape_payloads != source_payloads
            or self.geometry.transforms != expected_transforms
            or self.geometry.executor_state_count != len(self.end_effector_world_transforms)
            or self.geometry.allowed_touch_link_pairs
            != tuple(
                sorted(
                    tuple(sorted((path, robot_path)))
                    for robot_path in binding.active_attachment.planned_attachment_binding.allowed_robot_touch_paths
                )
            )
            or self.real_runtime_provider != binding.real_runtime_provider
            or self.contract_test_only != binding.contract_test_only
            or self.formal_query_evidence_eligible != binding.formal_query_evidence_eligible
        ):
            raise ValueError("active-session phase geometry is not reproducible")
        if self.evidence_sha256 != _model_sha256(self, "evidence_sha256"):
            raise ValueError("active-session phase geometry evidence digest differs")
        return self


A3AttachedObjectPhaseGeometryEvidenceAnyV2 = (
    A3AttachedObjectPhaseGeometryEvidenceV1 | A3AttachedObjectPhaseGeometryEvidenceV2
)
