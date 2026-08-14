"""Deterministic query-only A.3 attachment transition provider.

The provider selects no simulator entity and performs no contact query.  It
turns the already frozen bilateral-contact allowlists into one planned broker
pair, binds that pair to the preflight runtime snapshot, and carries the
planned attachment state through later phases.  Actual same-entity bilateral
contact remains an execution-time gate in the unchanged physical primitive.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Callable, Literal

from xh_agent.policy.qrm_lite.a3_attachment_transition_evidence_v1 import (
    build_a3_attachment_transition_evidence_v1,
    canonical_planned_attachment_sha256_v1,
    canonical_planned_bilateral_pair_v1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightConfigurationV1,
    NonActuatingAttachmentTransitionV1,
    NonActuatingPhasePathV1,
    PlannedBilateralContactPairV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/a3_attachment_transition_v1.py"


class A3AttachmentTransitionUnavailable(RuntimeError):
    """The frozen phase cannot produce one deterministic planned transition."""


class A3AttachmentTransitionProviderV1:
    non_actuating: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        runtime_snapshot: PreflightRuntimeSnapshotV1,
        runtime_snapshot_provider_implementation_sha256: str,
        real_runtime_snapshot: bool,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if (mode == "REAL_ISAAC") != real_runtime_snapshot:
            raise A3AttachmentTransitionUnavailable(
                "A.3 attachment provider mode differs from runtime snapshot provenance"
            )
        self.mode = mode
        self.runtime_snapshot = runtime_snapshot
        self.runtime_snapshot_provider_implementation_sha256 = (
            runtime_snapshot_provider_implementation_sha256
        )
        self.real_runtime_snapshot = real_runtime_snapshot
        self.monotonic_ns = monotonic_ns
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.algorithm_sha256 = canonical_sha256(
            {
                "schema_version": "A3AttachmentTransitionAlgorithmV1",
                "implementation_sha256": self.implementation_sha256,
                "runtime_snapshot_provider_implementation_sha256": (
                    runtime_snapshot_provider_implementation_sha256
                ),
                "selection": "EXACT_LEFT_RIGHT_EXTERNAL_ALLOWLIST_PRODUCT",
                "physical_contact_claimed": False,
                "runtime_broker_still_required": True,
            }
        )

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    def _validate_configuration(
        self,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> None:
        expected_id = (
            "A3_PLANNED_ATTACHMENT_TRANSITION_V1"
            if self.mode == "REAL_ISAAC"
            else "A3_PLANNED_ATTACHMENT_TRANSITION_CONTRACT_V1"
        )
        attachment = configuration.attachment
        if (
            attachment.algorithm_id != expected_id
            or attachment.algorithm_sha256 != self.algorithm_sha256
            or not attachment.require_unique_bilateral_contact_pair
            or not attachment.require_terminal_bilateral_contact_selector
            or not attachment.query_only_required
        ):
            raise A3AttachmentTransitionUnavailable(
                "A.3 attachment configuration differs from the frozen provider"
            )

    def query_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        expected_attachment_present: bool,
        expected_attachment_sha256: str | None,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingAttachmentTransitionV1:
        self._validate_configuration(configuration)
        wire = phase.phase
        if (
            wire.phase_index >= len(plan.phases)
            or plan.phases[wire.phase_index] != phase
            or path.bound_plan_sha256 != plan.bound_plan_sha256
            or path.phase_index != wire.phase_index
            or path.phase_sha256 != phase.phase_sha256
            or self.runtime_snapshot.bound_plan_sha256 != plan.bound_plan_sha256
            or (
                wire.phase_index == 0
                and (
                    expected_attachment_present != self.runtime_snapshot.active_attachment_present
                    or expected_attachment_sha256 != self.runtime_snapshot.active_attachment_sha256
                )
            )
        ):
            raise A3AttachmentTransitionUnavailable(
                "A.3 attachment query crossed plan/phase/path/runtime state"
            )
        if expected_attachment_present != (expected_attachment_sha256 is not None):
            raise A3AttachmentTransitionUnavailable(
                "A.3 attachment query received an inconsistent before-state"
            )

        started = self.monotonic_ns()
        transition = {
            "ATTACH_CONTACT_ENTITY": "ATTACH",
            "REMOVE_ATTACHMENT": "REMOVE",
        }.get(wire.command, "NONE")
        pair = None
        after_present = expected_attachment_present
        after_sha256 = expected_attachment_sha256
        if transition == "ATTACH":
            if expected_attachment_present:
                raise A3AttachmentTransitionUnavailable(
                    "A.3 attachment query cannot attach an already attached plan"
                )
            try:
                pair = canonical_planned_bilateral_pair_v1(
                    allowed_robot_contact_paths=wire.allowed_robot_contact_paths,
                    allowed_external_contact_paths=wire.allowed_external_contact_paths,
                )
            except ValueError as exc:
                raise A3AttachmentTransitionUnavailable(
                    "A.3 attachment allowlists lack one bilateral broker pair"
                ) from exc
            after_present = True
            after_sha256 = canonical_planned_attachment_sha256_v1(
                bound_plan_sha256=plan.bound_plan_sha256,
                phase_index=wire.phase_index,
                phase_sha256=phase.phase_sha256,
                path_sha256=path.path_sha256,
                runtime_snapshot_sha256=self.runtime_snapshot.snapshot_sha256,
                pair=pair,
                attachment_configuration_sha256=(configuration.attachment.configuration_sha256),
            )
        elif transition == "REMOVE":
            if not expected_attachment_present or expected_attachment_sha256 is None:
                raise A3AttachmentTransitionUnavailable(
                    "A.3 attachment removal lacks a bound attachment identity"
                )
            after_present = False
            after_sha256 = None

        evidence_payload: dict[str, object] = {
            "schema_version": "A3AttachmentTransitionEvidenceV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_index": wire.phase_index,
            "phase_sha256": phase.phase_sha256,
            "path_sha256": path.path_sha256,
            "runtime_snapshot_sha256": self.runtime_snapshot.snapshot_sha256,
            "runtime_snapshot_provider_implementation_sha256": (
                self.runtime_snapshot_provider_implementation_sha256
            ),
            "provider_implementation_sha256": self.implementation_sha256,
            "algorithm_sha256": self.algorithm_sha256,
            "attachment_configuration_sha256": (configuration.attachment.configuration_sha256),
            "command": wire.command,
            "transition": transition,
            "attachment_or_removal_selector": phase.attachment_or_removal_selector,
            "allowed_robot_contact_paths": wire.allowed_robot_contact_paths,
            "allowed_external_contact_paths": wire.allowed_external_contact_paths,
            "planned_bilateral_pair": pair.model_dump(mode="json") if pair else None,
            "attachment_present_before": expected_attachment_present,
            "attachment_sha256_before": expected_attachment_sha256,
            "attachment_present_after": after_present,
            "attachment_sha256_after": after_sha256,
            "real_runtime_snapshot": self.real_runtime_snapshot,
            "formal_query_evidence_eligible": self.formal_query_evidence_eligible,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        evidence = build_a3_attachment_transition_evidence_v1(**evidence_payload)
        duration = self.monotonic_ns() - started
        if duration < 0:
            raise A3AttachmentTransitionUnavailable("A.3 attachment query clock reversed")
        pairs = (
            ()
            if pair is None
            else (
                PlannedBilateralContactPairV1(
                    left_robot_path=pair.left_robot_path,
                    right_robot_path=pair.right_robot_path,
                    external_path=pair.external_path,
                ),
            )
        )
        payload = {
            "schema_version": "NonActuatingAttachmentTransitionV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_index": wire.phase_index,
            "phase_sha256": phase.phase_sha256,
            "path_sha256": path.path_sha256,
            "command": wire.command,
            "transition": transition,
            "attachment_or_removal_selector": phase.attachment_or_removal_selector,
            "allowed_robot_contact_paths": wire.allowed_robot_contact_paths,
            "allowed_external_contact_paths": wire.allowed_external_contact_paths,
            "bilateral_contact_pairs": [item.model_dump(mode="json") for item in pairs],
            "attachment_present_before": expected_attachment_present,
            "attachment_sha256_before": expected_attachment_sha256,
            "attachment_present_after": after_present,
            "attachment_sha256_after": after_sha256,
            "complete": True,
            "algorithm_sha256": self.algorithm_sha256,
            "configuration_sha256": configuration.attachment.configuration_sha256,
            "a3_attachment_evidence": evidence.model_dump(mode="json"),
            "query_duration_ns": duration,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return NonActuatingAttachmentTransitionV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
