"""Fail-closed bridge from a remapped V4 decision to the exact-plan bundle.

The bridge is deliberately not wired into the live Isaac backend yet.  It
accepts no waypoint generator and cannot infer action mappings.  A separate
provider must return a complete ADR-0022 A.1--A.4 envelope; this coordinator
recomputes all dynamic public/model/mapping bindings, runs the whole-plan
preflight, and exposes one single-use execution attempt.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    IsaacExecuteRequestV2,
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import RuntimeSkillMappingResultV2


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoundExactPlanProviderV1(Protocol):
    """External provider of one already complete, immutable plan envelope."""

    def build_bound_plan(
        self,
        *,
        request: IsaacExecuteRequestV2,
        observation: FormalPublicObservationV4,
        mapping: RuntimeSkillMappingResultV2,
    ) -> M2CExactPlanPrimitivePlanV1: ...


class ExactPlanBundleRuntimeV1(Protocol):
    def preflight(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> ExactPlanPreflightReceiptV1: ...

    def execute(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        preflight: ExactPlanPreflightReceiptV1,
    ) -> ExactPlanBundleExecutionReceiptV1: ...


class PreparedFormalExactPlanV1(_FrozenModel):
    """Cached all-phase preflight result; still not proof of execution."""

    schema_version: Literal["PreparedFormalExactPlanV1"] = "PreparedFormalExactPlanV1"
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_mapping_sha256: str = Field(pattern=SHA256_PATTERN)
    bound_plan: M2CExactPlanPrimitivePlanV1
    preflight_receipt: ExactPlanPreflightReceiptV1
    prepared_sha256: str = Field(pattern=SHA256_PATTERN)
    all_phases_passed_before_any_command: Literal[True] = True
    physical_execution_claimed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def preparation_is_canonical_and_cross_bound(self) -> "PreparedFormalExactPlanV1":
        if self.preflight_receipt.bound_plan_sha256 != self.bound_plan.bound_plan_sha256:
            raise ValueError("prepared preflight receipt differs from bound plan")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"prepared_sha256"}))
        if self.prepared_sha256 != expected:
            raise ValueError("prepared formal exact-plan digest differs")
        return self


def canonical_runtime_mapping_sha256_v1(mapping: RuntimeSkillMappingResultV2) -> str:
    """Hash the semantic mapping result without the non-semantic gate trace.

    The exact-plan gate appends its own result after this digest is computed;
    excluding ``gate_trace`` avoids a hash cycle while retaining every mapping
    field that determines the action, target, parameters, and attribution.
    """

    return canonical_sha256(mapping.model_dump(mode="json", exclude={"gate_trace"}))


class FormalExactPlanRuntimeV1:
    """One-at-a-time prepare/execute coordinator with no planning fallback."""

    def __init__(
        self,
        *,
        provider: BoundExactPlanProviderV1 | None,
        bundle: ExactPlanBundleRuntimeV1 | None,
    ) -> None:
        self.provider = provider
        self.bundle = bundle
        self._active: PreparedFormalExactPlanV1 | None = None
        self._consumed_plan_sha256: set[str] = set()

    def prepare(
        self,
        *,
        request: IsaacExecuteRequestV2,
        observation: FormalPublicObservationV4,
        mapping: RuntimeSkillMappingResultV2,
    ) -> PreparedFormalExactPlanV1:
        """Validate the complete dynamic envelope and preflight every phase."""

        if self.provider is None or self.bundle is None:
            raise ExactPlanUnavailable("formal bound-plan provider/bundle is absent")
        if self._active is not None:
            raise ExactPlanUnavailable("a prepared exact plan is already active")
        if (
            mapping.status != "VALID"
            or mapping.fallback_required
            or mapping.execution_attribution != "MODEL_SELECTED_REGISTERED_SKILL"
            or mapping.canonical_skill is None
            or mapping.runtime_action is None
        ):
            raise ExactPlanUnavailable("only a VALID model-attributed mapping may be prepared")
        if (
            request.observation_id != observation.observation_id
            or request.capture_receipt_sha256 != observation.capture_receipt_sha256
        ):
            raise ExactPlanUnavailable("execute request differs from the replayed V4 capture")

        plan = self.provider.build_bound_plan(
            request=request,
            observation=observation,
            mapping=mapping,
        )
        if not isinstance(plan, M2CExactPlanPrimitivePlanV1):
            raise ExactPlanUnavailable("bound-plan provider returned the wrong schema")
        mapping_sha256 = canonical_runtime_mapping_sha256_v1(mapping)
        wire = plan.exact_execution_plan
        inputs = plan.inputs
        destination_cell = (
            mapping.destination_resolution.destination_cell
            if mapping.destination_resolution is not None
            else None
        )
        expected_wire: dict[str, Any] = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": request.observation_id,
            "capture_receipt_sha256": request.capture_receipt_sha256,
            "canonical_skill": mapping.canonical_skill,
            "runtime_action": mapping.runtime_action,
            "execution_parameters_sha256": canonical_sha256(mapping.execution_parameters),
            "target_track_id": mapping.target_track_id,
        }
        if any(getattr(wire, name) != value for name, value in expected_wire.items()):
            raise ExactPlanUnavailable("bound exact wire plan differs from request/mapping")
        expected_inputs: dict[str, Any] = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "rgb_sha256": observation.rgb.sha256,
            "depth_sha256": observation.depth.sha256,
            "canonical_public_tracks_sha256": (observation.canonical_public_tracks_sha256),
            "signed_model_inference_response_sha256": request.inference_response_sha256,
            "runtime_mapping_sha256": mapping_sha256,
            "canonical_skill": mapping.canonical_skill,
            "runtime_action": mapping.runtime_action,
            "target_track_id": mapping.target_track_id,
            "destination_cell": destination_cell,
            "resolved_execution_parameters_sha256": canonical_sha256(mapping.execution_parameters),
        }
        if any(getattr(inputs, name) != value for name, value in expected_inputs.items()):
            raise ExactPlanUnavailable("A.1 inputs differ from replayed public/model/mapping data")
        if plan.bound_plan_sha256 in self._consumed_plan_sha256:
            raise ExactPlanUnavailable("bound plan was already consumed")

        preflight = self.bundle.preflight(plan)
        payload = {
            "schema_version": "PreparedFormalExactPlanV1",
            "request_sha256": canonical_sha256(request),
            "formal_observation_sha256": observation.wire_sha256,
            "runtime_mapping_sha256": mapping_sha256,
            "bound_plan": plan,
            "preflight_receipt": preflight,
            "all_phases_passed_before_any_command": True,
            "physical_execution_claimed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        prepared = PreparedFormalExactPlanV1(
            **payload,
            prepared_sha256=canonical_sha256(payload),
        )
        self._active = prepared
        return prepared

    def execute_once(
        self,
        prepared: PreparedFormalExactPlanV1,
    ) -> ExactPlanBundleExecutionReceiptV1:
        """Consume the preparation before calling the possibly physical bundle."""

        active = self._active
        if active is None or active.prepared_sha256 != prepared.prepared_sha256:
            raise ExactPlanUnavailable("prepared exact plan is absent or differs")
        plan_sha256 = active.bound_plan.bound_plan_sha256
        if plan_sha256 in self._consumed_plan_sha256:
            raise ExactPlanUnavailable("prepared exact plan was already consumed")
        if self.bundle is None:
            raise ExactPlanUnavailable("formal exact-plan bundle is absent")

        # Consume before the executor call: an exception after possible
        # actuation must never make the plan retryable.
        self._active = None
        self._consumed_plan_sha256.add(plan_sha256)
        receipt = self.bundle.execute(active.bound_plan, active.preflight_receipt)
        if (
            receipt.bound_plan_sha256 != plan_sha256
            or receipt.preflight_receipt_sha256 != active.preflight_receipt.receipt_sha256
        ):
            raise ExactPlanUnavailable("bundle execution receipt differs from preparation")
        return receipt
