"""Replayable query-only geometry for an A.3 planned attached object.

The attachment transition contract identifies one external scene link and two
allowed robot fingers, but it deliberately does not mutate Isaac.  This module
binds that planned attachment to the frozen scene geometry and a getter-only
active-session scene-state receipt.  It then carries the object rigidly with
the end-effector poses already present in each non-actuating phase path.

No TaskSpec identity, simulator entity truth, contact outcome, controller
command, physics step, or scene mutation is accepted as an input.  An existing
attachment is usable only when its complete binding receipt is supplied; an
unknown initial attachment therefore fails closed.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    A3ScenePoseProviderV1,
    A3SceneStateReceiptV1,
    produce_a3_scene_state_receipt_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    NonActuatingAttachmentTransitionV1,
    NonActuatingPhasePathV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_attached_object_phase_geometry_v1.py"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3AttachedObjectPhaseGeometryUnavailable(RuntimeError):
    """The planned payload geometry is absent, crossed, or non-replayable."""


def _model_sha256(model: BaseModel, field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={field}))


def _canonical_quaternion(
    values: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if not all(math.isfinite(value) for value in values):
        raise A3AttachedObjectPhaseGeometryUnavailable(
            "A.3 attached-object quaternion is non-finite"
        )
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0.0:
        raise A3AttachedObjectPhaseGeometryUnavailable(
            "A.3 attached-object quaternion is degenerate"
        )
    normalized = tuple(value / norm for value in values)
    for value in normalized:
        if abs(value) > 1e-15:
            return tuple(-item for item in normalized) if value < 0.0 else normalized
    raise A3AttachedObjectPhaseGeometryUnavailable(
        "A.3 attached-object quaternion has no canonical sign"
    )


def _rotate(
    quaternion: tuple[float, float, float, float],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    w, x, y, z = quaternion
    vx, vy, vz = vector
    return (
        (1 - 2 * (y * y + z * z)) * vx + 2 * (x * y - w * z) * vy + 2 * (x * z + w * y) * vz,
        2 * (x * y + w * z) * vx + (1 - 2 * (x * x + z * z)) * vy + 2 * (y * z - w * x) * vz,
        2 * (x * z - w * y) * vx + 2 * (y * z + w * x) * vy + (1 - 2 * (x * x + y * y)) * vz,
    )


def _compose(
    left: A3RigidTransformV1,
    right: A3RigidTransformV1,
) -> A3RigidTransformV1:
    lw, lx, ly, lz = left.rotation_world_wxyz
    rw, rx, ry, rz = right.rotation_world_wxyz
    rotation = _canonical_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )
    translated = _rotate(left.rotation_world_wxyz, right.translation_world_m)
    return A3RigidTransformV1(
        translation_world_m=tuple(
            origin + offset
            for origin, offset in zip(left.translation_world_m, translated, strict=True)
        ),
        rotation_world_wxyz=rotation,
    )


def _inverse(transform: A3RigidTransformV1) -> A3RigidTransformV1:
    w, x, y, z = transform.rotation_world_wxyz
    rotation = _canonical_quaternion((w, -x, -y, -z))
    translated = _rotate(
        rotation,
        tuple(-value for value in transform.translation_world_m),
    )
    return A3RigidTransformV1(
        translation_world_m=translated,
        rotation_world_wxyz=rotation,
    )


def _same_transform(left: A3RigidTransformV1, right: A3RigidTransformV1) -> bool:
    return all(
        math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9)
        for a, b in zip(
            (*left.translation_world_m, *left.rotation_world_wxyz),
            (*right.translation_world_m, *right.rotation_world_wxyz),
            strict=True,
        )
    )


class A3PlannedAttachedObjectBindingV1(_FrozenModel):
    """The complete immutable object/hand binding created by one ATTACH phase."""

    schema_version: Literal["A3PlannedAttachedObjectBindingV1"] = "A3PlannedAttachedObjectBindingV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_transition: NonActuatingAttachmentTransitionV1
    external_link_path: str = Field(pattern=r"^/World/M1B/[^/]+/[^/]+$")
    allowed_robot_touch_paths: tuple[str, str]
    scene_geometry: A3SceneCollisionGeometryReceiptV1
    scene_state: A3SceneStateReceiptV1
    attach_hand_world_transform: A3RigidTransformV1
    attach_object_world_transform: A3RigidTransformV1
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
    def replay_binding(self) -> "A3PlannedAttachedObjectBindingV1":
        transition = self.attachment_transition
        evidence = transition.a3_attachment_evidence
        pair = transition.bilateral_contact_pairs
        source_links = {item.link_path: item for item in self.scene_geometry.source_links}
        states = {item.link_path: item.world_transform for item in self.scene_state.link_states}
        if (
            self.real_runtime_provider == self.contract_test_only
            or transition.transition != "ATTACH"
            or transition.attachment_sha256_after != self.attachment_sha256
            or transition.bound_plan_sha256 != self.bound_plan_sha256
            or evidence is None
            or len(pair) != 1
            or pair[0].external_path != self.external_link_path
            or tuple(sorted((pair[0].left_robot_path, pair[0].right_robot_path)))
            != self.allowed_robot_touch_paths
            or self.external_link_path not in source_links
            or not source_links[self.external_link_path].dynamic
            or self.external_link_path not in states
            or self.scene_state.bound_plan_sha256 != self.bound_plan_sha256
            or self.scene_state.runtime_snapshot_sha256 != evidence.runtime_snapshot_sha256
            or self.scene_state.geometry_receipt_sha256 != self.scene_geometry.receipt_sha256
            or self.attach_object_world_transform != states[self.external_link_path]
        ):
            raise ValueError("A.3 planned attached-object binding crossed its source evidence")
        expected_object = _compose(self.attach_hand_world_transform, self.hand_to_object_transform)
        if not _same_transform(expected_object, self.attach_object_world_transform):
            raise ValueError("A.3 planned hand/object relative transform differs")
        expected_formal = bool(
            self.real_runtime_provider
            and self.scene_state.real_runtime_provider
            and not self.scene_state.contract_test_only
            and evidence.formal_query_evidence_eligible
        )
        if self.formal_query_evidence_eligible != expected_formal:
            raise ValueError("A.3 planned attached-object formal eligibility differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 planned attached-object binding digest differs")
        return self


class A3AttachedObjectPhaseGeometryEvidenceV1(_FrozenModel):
    """Replayable per-sample attached geometry for one later motion phase."""

    schema_version: Literal["A3AttachedObjectPhaseGeometryEvidenceV1"] = (
        "A3AttachedObjectPhaseGeometryEvidenceV1"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_binding: A3PlannedAttachedObjectBindingV1
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
    def replay_phase_geometry(self) -> "A3AttachedObjectPhaseGeometryEvidenceV1":
        binding = self.attachment_binding
        source_children = tuple(
            item
            for item in binding.scene_geometry.children
            if item.link_path == binding.external_link_path
        )
        source_payloads = tuple(
            item
            for item in binding.scene_geometry.shape_payloads
            if item.link_path == binding.external_link_path
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
            or self.geometry.attached_object_path != binding.external_link_path
            or self.geometry.attachment_receipt_sha256 != binding.attachment_sha256
            or self.geometry.children != source_children
            or self.geometry.shape_payloads != source_payloads
            or self.geometry.transforms != expected_transforms
            or self.geometry.executor_state_count != len(self.end_effector_world_transforms)
            or self.geometry.allowed_touch_link_pairs
            != tuple(
                sorted(
                    tuple(sorted((binding.external_link_path, path)))
                    for path in binding.allowed_robot_touch_paths
                )
            )
            or self.real_runtime_provider != binding.real_runtime_provider
            or self.contract_test_only != binding.contract_test_only
        ):
            raise ValueError("A.3 attached-object phase geometry is not reproducible")
        expected_formal = bool(
            binding.formal_query_evidence_eligible and self.real_runtime_provider
        )
        if self.formal_query_evidence_eligible != expected_formal:
            raise ValueError("A.3 attached-object phase formal eligibility differs")
        if self.evidence_sha256 != _model_sha256(self, "evidence_sha256"):
            raise ValueError("A.3 attached-object phase evidence digest differs")
        return self


class A3QueryOnlyAttachedObjectPhaseGeometryResolverV1:
    """Single-plan resolver implementing the callback geometry protocol."""

    query_only: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        bound_plan_sha256: str,
        runtime_snapshot_checked_at_ns: int,
        scene_geometry: A3SceneCollisionGeometryReceiptV1,
        scene_pose_provider: A3ScenePoseProviderV1,
        initial_bindings: tuple[A3PlannedAttachedObjectBindingV1, ...] = (),
    ) -> None:
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.bound_plan_sha256 = bound_plan_sha256
        self.runtime_snapshot_checked_at_ns = runtime_snapshot_checked_at_ns
        self.scene_geometry = scene_geometry
        self.scene_pose_provider = scene_pose_provider
        self.real_runtime_provider = mode == "REAL_ISAAC"
        self.mocked_provider = mode == "CONTRACT_TEST"
        if (
            self.real_runtime_provider != scene_pose_provider.real_runtime_provider
            or self.mocked_provider != scene_pose_provider.contract_test_only
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 attached-object resolver/provider mode differs"
            )
        self._bindings = {item.attachment_sha256: item for item in initial_bindings}
        self._phase_evidence: dict[tuple[str, str], A3AttachedObjectPhaseGeometryEvidenceV1] = {}
        if len(self._bindings) != len(initial_bindings) or any(
            item.bound_plan_sha256 != bound_plan_sha256
            or item.scene_geometry != scene_geometry
            or item.resolver_implementation.sha256 != self.implementation_sha256
            or item.real_runtime_provider != self.real_runtime_provider
            for item in initial_bindings
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 initial attached-object binding differs"
            )

    def _require_plan(self, plan: M2CExactPlanPrimitivePlanV1) -> None:
        if plan.bound_plan_sha256 != self.bound_plan_sha256:
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 attached-object resolver crossed the bound plan"
            )

    def validate_initial_attachment(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> None:
        self._require_plan(plan)
        if attachment_sha256 not in self._bindings:
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 initial attachment lacks a complete geometry binding"
            )

    def bind_planned_attachment(
        self,
        *,
        attachment: NonActuatingAttachmentTransitionV1,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> None:
        self._require_plan(plan)
        evidence = attachment.a3_attachment_evidence
        if (
            attachment.transition != "ATTACH"
            or attachment.attachment_sha256_after is None
            or evidence is None
            or len(attachment.bilateral_contact_pairs) != 1
            or phase.phase.command != "ATTACH_CONTACT_ENTITY"
            or phase.phase.phase_index != attachment.phase_index
            or phase.phase_sha256 != attachment.phase_sha256
            or path.bound_plan_sha256 != self.bound_plan_sha256
            or path.phase_index != attachment.phase_index
            or path.phase_sha256 != attachment.phase_sha256
            or path.path_sha256 != attachment.path_sha256
            or not path.samples
            or attachment.attachment_sha256_after in self._bindings
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 planned attachment crossed plan/phase/path identity"
            )
        pair = attachment.bilateral_contact_pairs[0]
        scene_state = produce_a3_scene_state_receipt_v1(
            bound_plan_sha256=self.bound_plan_sha256,
            runtime_snapshot_sha256=evidence.runtime_snapshot_sha256,
            geometry=self.scene_geometry,
            provider=self.scene_pose_provider,
            after_ns=self.runtime_snapshot_checked_at_ns,
            require_real_runtime_provider=self.real_runtime_provider,
        )
        state_by_path = {item.link_path: item.world_transform for item in scene_state.link_states}
        if pair.external_path not in state_by_path:
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 planned attached object is absent from scene state"
            )
        terminal = path.samples[-1]
        hand = A3RigidTransformV1(
            translation_world_m=terminal.end_effector_world_m,
            rotation_world_wxyz=terminal.end_effector_world_wxyz,
        )
        object_world = state_by_path[pair.external_path]
        relative = _compose(_inverse(hand), object_world)
        payload = {
            "schema_version": "A3PlannedAttachedObjectBindingV1",
            "bound_plan_sha256": self.bound_plan_sha256,
            "attachment_sha256": attachment.attachment_sha256_after,
            "attachment_transition": attachment.model_dump(mode="json"),
            "external_link_path": pair.external_path,
            "allowed_robot_touch_paths": tuple(
                sorted((pair.left_robot_path, pair.right_robot_path))
            ),
            "scene_geometry": self.scene_geometry.model_dump(mode="json"),
            "scene_state": scene_state.model_dump(mode="json"),
            "attach_hand_world_transform": hand.model_dump(mode="json"),
            "attach_object_world_transform": object_world.model_dump(mode="json"),
            "hand_to_object_transform": relative.model_dump(mode="json"),
            "resolver_implementation": {
                "path": IMPLEMENTATION_REPO_PATH,
                "sha256": self.implementation_sha256,
            },
            "real_runtime_provider": self.real_runtime_provider,
            "contract_test_only": self.mocked_provider,
            "formal_query_evidence_eligible": bool(
                self.real_runtime_provider
                and scene_state.real_runtime_provider
                and evidence.formal_query_evidence_eligible
            ),
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        binding = A3PlannedAttachedObjectBindingV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
        self._bindings[binding.attachment_sha256] = binding

    def geometry_for_phase(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> A3AttachedObjectGeometryV1:
        self._require_plan(plan)
        binding = self._bindings.get(attachment_sha256)
        if (
            binding is None
            or phase.phase.command not in {"CARTESIAN_POSE", "GRIPPER_POSITION"}
            or phase.phase.phase_index != path.phase_index
            or phase.phase_sha256 != path.phase_sha256
            or path.bound_plan_sha256 != self.bound_plan_sha256
            or len(path.samples) < 2
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 attached-object motion phase crossed its binding"
            )
        hands = tuple(
            A3RigidTransformV1(
                translation_world_m=sample.end_effector_world_m,
                rotation_world_wxyz=sample.end_effector_world_wxyz,
            )
            for sample in path.samples
        )
        children = tuple(
            item
            for item in self.scene_geometry.children
            if item.link_path == binding.external_link_path
        )
        payloads = tuple(
            item
            for item in self.scene_geometry.shape_payloads
            if item.link_path == binding.external_link_path
        )
        if not children or len(children) != len(payloads):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 attached-object source geometry is incomplete"
            )
        transforms = tuple(
            A3LinkChildTransformSequenceV1(
                link_path=child.link_path,
                child_index=child.child_index,
                transforms=tuple(
                    _compose(
                        _compose(hand, binding.hand_to_object_transform), child.local_transform
                    )
                    for hand in hands
                ),
            )
            for child in children
        )
        geometry_payload = {
            "schema_version": "A3AttachedObjectGeometryV1",
            "attached_object_path": binding.external_link_path,
            "attachment_receipt_sha256": binding.attachment_sha256,
            "children": [item.model_dump(mode="json") for item in children],
            "shape_payloads": [item.model_dump(mode="json") for item in payloads],
            "transforms": [item.model_dump(mode="json") for item in transforms],
            "allowed_touch_link_pairs": tuple(
                sorted(
                    tuple(sorted((binding.external_link_path, item)))
                    for item in binding.allowed_robot_touch_paths
                )
            ),
            "executor_state_count": len(hands),
            "complete_compound_expansion": True,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
        }
        geometry = A3AttachedObjectGeometryV1(
            **geometry_payload,
            receipt_sha256=canonical_sha256(geometry_payload),
        )
        evidence_payload = {
            "schema_version": "A3AttachedObjectPhaseGeometryEvidenceV1",
            "bound_plan_sha256": self.bound_plan_sha256,
            "phase_index": phase.phase.phase_index,
            "phase_sha256": phase.phase_sha256,
            "path_sha256": path.path_sha256,
            "attachment_binding": binding.model_dump(mode="json"),
            "end_effector_world_transforms": [item.model_dump(mode="json") for item in hands],
            "geometry": geometry.model_dump(mode="json"),
            "real_runtime_provider": self.real_runtime_provider,
            "contract_test_only": self.mocked_provider,
            "formal_query_evidence_eligible": binding.formal_query_evidence_eligible,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        evidence = A3AttachedObjectPhaseGeometryEvidenceV1(
            **evidence_payload,
            evidence_sha256=canonical_sha256(evidence_payload),
        )
        self._phase_evidence[(attachment_sha256, path.path_sha256)] = evidence
        return geometry

    def phase_evidence(
        self,
        *,
        attachment_sha256: str,
        path_sha256: str,
    ) -> A3AttachedObjectPhaseGeometryEvidenceV1:
        try:
            return self._phase_evidence[(attachment_sha256, path_sha256)]
        except KeyError as exc:
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 attached-object phase evidence is unavailable"
            ) from exc

    def release_planned_attachment(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> None:
        self._require_plan(plan)
        if (
            attachment_sha256 not in self._bindings
            or phase.phase.command != "REMOVE_ATTACHMENT"
            or phase.phase.phase_index != path.phase_index
            or phase.phase_sha256 != path.phase_sha256
            or path.bound_plan_sha256 != self.bound_plan_sha256
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "A.3 attached-object release crossed plan/phase/path identity"
            )
        del self._bindings[attachment_sha256]
