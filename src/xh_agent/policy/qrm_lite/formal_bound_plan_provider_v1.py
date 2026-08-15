"""Single-use, deployment-bound provider for formal V4 exact plans.

The provider does not invent waypoints.  A separately frozen synthesis backend
must return the complete ADR-0022 A.1--A.4 envelope plus a query-only pre-plan
state receipt.  This module independently replays all dynamic wire bindings,
the state receipt, source/commit/container closure, and the frozen per-skill
phase schema before exposing the plan to ``FormalExactPlanRuntimeV1``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ADR_0022_PATH,
    ADR_0024_PATH,
    ExactPlanSourceBindingV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    validate_bound_exact_plan_inputs_v1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacExecuteRequestV4
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once
from xh_agent.policy.qrm_lite.skill_registry_v2 import RuntimeSkillMappingResultV2


ADR_0022_ADDENDUM_PATH = "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"
S4_UNLOCK_CONFIG_PATH = "configs/m2c_s4_unlock_bindings.json"
_EXPECTED_SKILLS = frozenset(
    {
        "GRASP",
        "LIFT",
        "MOVE",
        "PLACE",
        "RELEASE",
        "REOBSERVE",
        "REASSOCIATE_TARGET",
        "REGRASP",
    }
)
_EXPECTED_SOURCE_ROLES = frozenset(
    {
        "PRIMITIVE_ENTRYPOINT",
        "PREFLIGHT_IMPLEMENTATION",
        "EXECUTOR_IMPLEMENTATION",
        "TRANSITIVE_DEPENDENCY_MANIFEST",
        "ISAAC_RUNTIME",
        "IK_ALGORITHM",
        "JOINT_LIMIT_CONFIGURATION",
        "SWEPT_COLLISION_ALGORITHM",
        "ROBOT_ASSET",
        "CONTROLLER_CONFIGURATION",
        "SAFETY_CONFIGURATION",
        "SCENE_ASSET",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


class FormalPreplanStateReceiptV1(_FrozenModel):
    """Query-only active-session state used by the bound planner."""

    schema_version: Literal["FormalPreplanStateReceiptV1"] = "FormalPreplanStateReceiptV1"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_synthesis_state_sha256: str = Field(pattern=SHA256_PATTERN)
    state_sha256: str = Field(pattern=SHA256_PATTERN)
    state_frame: Literal["world"] = "world"
    state_dimensions: Literal[8] = 8
    state_units: Literal["rad_7_plus_per_finger_m"] = "rad_7_plus_per_finger_m"
    state_timestamp_ns: int = Field(gt=0)
    freshness_limit_ns: int = Field(gt=0)
    query_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    task_spec_fallback_used: Literal[False] = False
    privileged_identity_or_pose_used: Literal[False] = False
    privileged_contact_or_success_truth_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def receipt_is_canonical(self) -> "FormalPreplanStateReceiptV1":
        if self.plan_synthesis_state_sha256 == self.state_sha256:
            raise ValueError("formal synthesis and physical state digests coincide")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal pre-plan state receipt digest differs")
        return self


class BoundExactPlanSynthesisResultV1(_FrozenModel):
    schema_version: Literal["BoundExactPlanSynthesisResultV1"] = "BoundExactPlanSynthesisResultV1"
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_mapping_sha256: str = Field(pattern=SHA256_PATTERN)
    synthesis_backend_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_receipt: FormalPreplanStateReceiptV1
    bound_plan: M2CExactPlanPrimitivePlanV1
    result_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_constructed_before_any_command: Literal[True] = True
    physical_execution_claimed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def result_is_canonical(self) -> "BoundExactPlanSynthesisResultV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("bound exact-plan synthesis result digest differs")
        return self


class FormalExactPlanSynthesisBackendV1(Protocol):
    implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool

    def synthesize_bound_plan(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
        mapping: RuntimeSkillMappingResultV2,
    ) -> BoundExactPlanSynthesisResultV1: ...


class FormalBoundPlanProviderDeploymentV1(_FrozenModel):
    """Reviewed Phase-2 binding consumed before a synthesis callback."""

    schema_version: Literal["FormalBoundPlanProviderDeploymentV1"] = (
        "FormalBoundPlanProviderDeploymentV1"
    )
    adr_0022_sha256: str = Field(pattern=SHA256_PATTERN)
    adr_0024_sha256: str = Field(pattern=SHA256_PATTERN)
    binding_addendum_sha256: str = Field(pattern=SHA256_PATTERN)
    unlock_config_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    synthesis_backend_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    query_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    source_bindings: tuple[ExactPlanSourceBindingV1, ...] = Field(min_length=12)
    phase_schema_by_skill: tuple[tuple[str, str], ...] = Field(min_length=8, max_length=8)
    reviewed_addendum_accepted: Literal[True] = True
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def skill_and_source_sets_are_exact(self) -> "FormalBoundPlanProviderDeploymentV1":
        roles = [item.role for item in self.source_bindings]
        if len(roles) != len(set(roles)) or frozenset(roles) != _EXPECTED_SOURCE_ROLES:
            raise ValueError("bound-plan provider source role set differs")
        skills = [skill for skill, _ in self.phase_schema_by_skill]
        if len(skills) != len(set(skills)) or frozenset(skills) != _EXPECTED_SKILLS:
            raise ValueError("bound-plan provider phase-schema skill set differs")
        return self


class FormalBoundExactPlanProviderV1:
    """Consume one synthesis attempt and expose only a fully replayed plan."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        backend: FormalExactPlanSynthesisBackendV1,
        deployment: FormalBoundPlanProviderDeploymentV1 | None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.mode = mode
        self.backend = backend
        self.deployment = deployment
        self.implementation_sha256 = _file_sha256(Path(__file__))
        self._consumed_request_sha256: set[str] = set()
        if mode == "CONTRACT_TEST":
            if deployment is not None or backend.real_isaac or not backend.mocked_physics:
                raise ExactPlanUnavailable(
                    "contract bound-plan provider received production dependencies"
                )
        else:
            require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
            self._validate_production_deployment()

    @property
    def formal_execution_eligible(self) -> bool:
        return bool(
            self.mode == "REAL_ISAAC"
            and self.deployment is not None
            and self.backend.real_isaac
            and not self.backend.mocked_physics
        )

    def _validate_production_deployment(self) -> None:
        binding = self.deployment
        if (
            binding is None
            or not self.backend.real_isaac
            or self.backend.mocked_physics
            or binding.provider_implementation_sha256 != self.implementation_sha256
            or binding.synthesis_backend_implementation_sha256 != self.backend.implementation_sha256
        ):
            raise ExactPlanUnavailable("REAL_ISAAC bound-plan deployment differs")
        expected_files = {
            ADR_0022_PATH: binding.adr_0022_sha256,
            ADR_0024_PATH: binding.adr_0024_sha256,
            ADR_0022_ADDENDUM_PATH: binding.binding_addendum_sha256,
            S4_UNLOCK_CONFIG_PATH: binding.unlock_config_sha256,
        }
        for relative, expected_sha256 in expected_files.items():
            if _file_sha256(self.project_root / relative) != expected_sha256:
                raise ExactPlanUnavailable(f"bound-plan deployment file differs: {relative}")

    def build_bound_plan(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
        mapping: RuntimeSkillMappingResultV2,
    ) -> M2CExactPlanPrimitivePlanV1:
        if self.mode == "REAL_ISAAC":
            # Re-check immediately before the query-only active-session read;
            # a long-lived process may cross the fixed experiment boundary.
            require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
        request_sha256 = canonical_sha256(request)
        if request_sha256 in self._consumed_request_sha256:
            raise ExactPlanUnavailable("formal bound-plan synthesis request was already consumed")
        # A query can observe active session state.  Consume it before calling
        # the backend so a lost/rejected result cannot be retried or selected.
        self._consumed_request_sha256.add(request_sha256)
        raw_result = self.backend.synthesize_bound_plan(
            request=request,
            observation=observation,
            mapping=mapping,
        )
        result = BoundExactPlanSynthesisResultV1.model_validate(
            raw_result.model_dump(mode="json") if isinstance(raw_result, BaseModel) else raw_result
        )
        state = result.preplan_state_receipt
        plan = result.bound_plan
        mapping_sha256 = validate_bound_exact_plan_inputs_v1(
            request=request,
            observation=observation,
            mapping=mapping,
            plan=plan,
        )
        expected_result = {
            "request_sha256": request_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "runtime_mapping_sha256": mapping_sha256,
            "synthesis_backend_implementation_sha256": self.backend.implementation_sha256,
        }
        if any(getattr(result, name) != value for name, value in expected_result.items()):
            raise ExactPlanUnavailable("bound-plan synthesis result crosses request/runtime")
        expected_state = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "plan_synthesis_state_sha256": plan.inputs.plan_synthesis_state_sha256,
            "state_sha256": plan.inputs.preplan_state_sha256,
            "state_frame": plan.inputs.preplan_state_frame,
            "state_dimensions": plan.inputs.preplan_state_dimensions,
            "state_units": plan.inputs.preplan_state_units,
            "state_timestamp_ns": plan.inputs.preplan_state_timestamp_ns,
            "freshness_limit_ns": plan.inputs.preplan_state_freshness_limit_ns,
        }
        if any(getattr(state, name) != value for name, value in expected_state.items()):
            raise ExactPlanUnavailable("bound plan crosses its query-only pre-plan state")
        if state.state_timestamp_ns <= observation.captured_at_ns:
            raise ExactPlanUnavailable("pre-plan state is not newer than the public capture")
        if plan.inputs.plan_constructed_at_ns < state.state_timestamp_ns:
            raise ExactPlanUnavailable("bound plan predates its query-only state")

        deployment = self.deployment
        if self.mode == "REAL_ISAAC":
            assert deployment is not None
            if (
                state.query_source_implementation_sha256
                != deployment.query_source_implementation_sha256
                or plan.inputs.immutable_commit != deployment.immutable_commit
                or plan.inputs.container_image_digest != deployment.container_image_digest
                or plan.source_bindings != deployment.source_bindings
                or dict(deployment.phase_schema_by_skill).get(
                    plan.exact_execution_plan.canonical_skill
                )
                != plan.phase_schema_sha256
            ):
                raise ExactPlanUnavailable("bound plan differs from reviewed deployment")
        return plan
