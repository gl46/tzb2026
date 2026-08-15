"""Carry one physically committed attachment into the next exact-plan query.

The V1 resolver intentionally accepted only an attachment planned inside the
same bound plan.  A model-owned recovery chain, however, executes one skill per
decision: GRASP commits the attachment in one plan and LIFT/MOVE/PLACE consume
it in later plans.  This module bridges that boundary without trusting a model
field or re-labelling a planned attachment as executed.

The bridge requires both the prior plan's complete query-only geometry binding
and a post-helper active-session execution receipt.  For the new plan it reads
the current object and hand poses from the same mutation-counted scene, derives
the current rigid transform, and produces versioned per-phase geometry
evidence.  It remains a gate-only query and performs no scene mutation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from xh_agent.policy.qrm_lite.a3_attached_object_phase_geometry_v1 import (
    A3AttachedObjectPhaseGeometryUnavailable,
    A3PlannedAttachedObjectBindingV1,
    A3QueryOnlyAttachedObjectPhaseGeometryResolverV1,
    _compose,
    _inverse,
)
from xh_agent.policy.qrm_lite.a3_active_session_attachment_evidence_v2 import (
    A3ActiveSessionAttachedObjectBindingV2,
    A3AttachedObjectPhaseGeometryEvidenceAnyV2,
    A3AttachedObjectPhaseGeometryEvidenceV2,
    A3ExecutedAttachmentBindingV2,
)
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3AttachedObjectGeometryV1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3LinkChildTransformSequenceV1,
    A3RigidTransformV1,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3ScenePoseProviderV1,
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
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = (
    "src/xh_agent/policy/qrm_lite/a3_active_session_attached_object_geometry_v2.py"
)


class A3ActiveSessionAttachedObjectPhaseGeometryResolverV2:
    """Resolver supporting both carried and same-plan planned attachments."""

    query_only: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        bound_plan_sha256: str,
        runtime_snapshot_sha256: str,
        runtime_snapshot_checked_at_ns: int,
        current_hand_world_transform: A3RigidTransformV1,
        scene_geometry: A3SceneCollisionGeometryReceiptV1,
        scene_pose_provider: A3ScenePoseProviderV1,
        active_attachment: A3ExecutedAttachmentBindingV2 | None,
    ) -> None:
        root = project_root.resolve()
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(root / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.bound_plan_sha256 = bound_plan_sha256
        self.runtime_snapshot_sha256 = runtime_snapshot_sha256
        self.runtime_snapshot_checked_at_ns = runtime_snapshot_checked_at_ns
        self.scene_geometry = scene_geometry
        self.scene_pose_provider = scene_pose_provider
        self.real_runtime_provider = mode == "REAL_ISAAC"
        self.mocked_provider = mode == "CONTRACT_TEST"
        self._planned = A3QueryOnlyAttachedObjectPhaseGeometryResolverV1(
            project_root=root,
            mode=mode,
            bound_plan_sha256=bound_plan_sha256,
            runtime_snapshot_checked_at_ns=runtime_snapshot_checked_at_ns,
            scene_geometry=scene_geometry,
            scene_pose_provider=scene_pose_provider,
        )
        self._active: A3ActiveSessionAttachedObjectBindingV2 | None = None
        self._phase_evidence: dict[tuple[str, str], A3AttachedObjectPhaseGeometryEvidenceV2] = {}
        if active_attachment is not None:
            if (
                active_attachment.real_isaac != self.real_runtime_provider
                or active_attachment.contract_test_only != self.mocked_provider
            ):
                raise A3AttachedObjectPhaseGeometryUnavailable(
                    "active attachment execution mode differs from resolver"
                )
            scene_state = produce_a3_scene_state_receipt_v1(
                bound_plan_sha256=bound_plan_sha256,
                runtime_snapshot_sha256=runtime_snapshot_sha256,
                geometry=scene_geometry,
                provider=scene_pose_provider,
                after_ns=runtime_snapshot_checked_at_ns,
                require_real_runtime_provider=self.real_runtime_provider,
            )
            states = {item.link_path: item.world_transform for item in scene_state.link_states}
            try:
                object_world = states[active_attachment.external_contact_path]
            except KeyError as exc:
                raise A3AttachedObjectPhaseGeometryUnavailable(
                    "active attachment path is absent from current scene"
                ) from exc
            relative = _compose(_inverse(current_hand_world_transform), object_world)
            payload = {
                "schema_version": "A3ActiveSessionAttachedObjectBindingV2",
                "bound_plan_sha256": bound_plan_sha256,
                "active_attachment_receipt_sha256": active_attachment.receipt_sha256,
                "active_attachment": active_attachment.model_dump(mode="json"),
                "scene_geometry": scene_geometry.model_dump(mode="json"),
                "scene_state": scene_state.model_dump(mode="json"),
                "current_hand_world_transform": current_hand_world_transform.model_dump(
                    mode="json"
                ),
                "current_object_world_transform": object_world.model_dump(mode="json"),
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
                    and active_attachment.planned_attachment_binding.formal_query_evidence_eligible
                ),
                "query_only": True,
                "articulation_target_writes": 0,
                "simulation_steps": 0,
                "scene_mutations": 0,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            self._active = A3ActiveSessionAttachedObjectBindingV2(
                **payload,
                receipt_sha256=canonical_sha256(payload),
            )

    def validate_initial_attachment(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> None:
        if plan.bound_plan_sha256 != self.bound_plan_sha256:
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "active-session resolver crossed bound plan"
            )
        if self._active is None or attachment_sha256 != (
            self._active.active_attachment_receipt_sha256
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "active-session initial attachment receipt is absent"
            )

    def bind_planned_attachment(
        self,
        *,
        attachment: NonActuatingAttachmentTransitionV1,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> None:
        if self._active is not None:
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "cannot plan a second attachment while one is active"
            )
        self._planned.bind_planned_attachment(
            attachment=attachment,
            plan=plan,
            phase=phase,
            path=path,
        )

    def geometry_for_phase(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> A3AttachedObjectGeometryV1:
        active = self._active
        if active is None or attachment_sha256 != active.active_attachment_receipt_sha256:
            return self._planned.geometry_for_phase(
                attachment_sha256=attachment_sha256,
                plan=plan,
                phase=phase,
                path=path,
            )
        if (
            plan.bound_plan_sha256 != self.bound_plan_sha256
            or phase.phase.command not in {"CARTESIAN_POSE", "GRIPPER_POSITION"}
            or phase.phase.phase_index != path.phase_index
            or phase.phase_sha256 != path.phase_sha256
            or len(path.samples) < 2
        ):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "active-session motion phase crossed attachment/plan/path"
            )
        hands = tuple(
            A3RigidTransformV1(
                translation_world_m=sample.end_effector_world_m,
                rotation_world_wxyz=sample.end_effector_world_wxyz,
            )
            for sample in path.samples
        )
        object_path = active.active_attachment.external_contact_path
        children = tuple(
            item for item in active.scene_geometry.children if item.link_path == object_path
        )
        payloads = tuple(
            item for item in active.scene_geometry.shape_payloads if item.link_path == object_path
        )
        if not children or len(children) != len(payloads):
            raise A3AttachedObjectPhaseGeometryUnavailable(
                "active-session attached source geometry is incomplete"
            )
        transforms = tuple(
            A3LinkChildTransformSequenceV1(
                link_path=child.link_path,
                child_index=child.child_index,
                transforms=tuple(
                    _compose(
                        _compose(hand, active.hand_to_object_transform),
                        child.local_transform,
                    )
                    for hand in hands
                ),
            )
            for child in children
        )
        geometry_payload = {
            "schema_version": "A3AttachedObjectGeometryV1",
            "attached_object_path": object_path,
            "attachment_receipt_sha256": active.active_attachment_receipt_sha256,
            "children": [item.model_dump(mode="json") for item in children],
            "shape_payloads": [item.model_dump(mode="json") for item in payloads],
            "transforms": [item.model_dump(mode="json") for item in transforms],
            "allowed_touch_link_pairs": tuple(
                sorted(
                    tuple(sorted((object_path, robot_path)))
                    for robot_path in active.active_attachment.planned_attachment_binding.allowed_robot_touch_paths
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
            "schema_version": "A3AttachedObjectPhaseGeometryEvidenceV2",
            "bound_plan_sha256": self.bound_plan_sha256,
            "phase_index": phase.phase.phase_index,
            "phase_sha256": phase.phase_sha256,
            "path_sha256": path.path_sha256,
            "attachment_binding": active.model_dump(mode="json"),
            "end_effector_world_transforms": [item.model_dump(mode="json") for item in hands],
            "geometry": geometry.model_dump(mode="json"),
            "real_runtime_provider": self.real_runtime_provider,
            "contract_test_only": self.mocked_provider,
            "formal_query_evidence_eligible": active.formal_query_evidence_eligible,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        evidence = A3AttachedObjectPhaseGeometryEvidenceV2(
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
    ) -> A3AttachedObjectPhaseGeometryEvidenceAnyV2:
        try:
            return self._phase_evidence[(attachment_sha256, path_sha256)]
        except KeyError:
            return self._planned.phase_evidence(
                attachment_sha256=attachment_sha256,
                path_sha256=path_sha256,
            )

    def release_planned_attachment(
        self,
        *,
        attachment_sha256: str,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
    ) -> None:
        if self._active is not None and attachment_sha256 == (
            self._active.active_attachment_receipt_sha256
        ):
            if (
                plan.bound_plan_sha256 != self.bound_plan_sha256
                or phase.phase.command != "REMOVE_ATTACHMENT"
                or phase.phase.phase_index != path.phase_index
                or phase.phase_sha256 != path.phase_sha256
            ):
                raise A3AttachedObjectPhaseGeometryUnavailable(
                    "active-session release crossed plan/phase/path"
                )
            self._active = None
            return
        self._planned.release_planned_attachment(
            attachment_sha256=attachment_sha256,
            plan=plan,
            phase=phase,
            path=path,
        )

    def planned_attachment_bindings(self) -> tuple[A3PlannedAttachedObjectBindingV1, ...]:
        return self._planned.planned_attachment_bindings()
