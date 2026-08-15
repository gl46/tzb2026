"""Per-decision exact-plan bundle factory for one persistent Isaac scene.

The exact-plan preflight callbacks and executor are intentionally single-use.
This factory claims the physical state captured during plan synthesis, creates
one query-only runtime snapshot, asks one byte-bound component source to build
the remaining bundle graph, and then independently checks that every object in
that graph belongs to the same plan, scene, mutation counter, attachment
registry, and deployment.

Component construction is covered by the existing project evidence bar: its
implementation bytes and transitive dependency manifest are frozen by the
Phase-2 binding addendum.  Construction is additionally bracketed by the
active-session mutation counter, so a source cannot silently perform a command
while presenting itself as a non-actuating assembler.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_exact_plan_callbacks_v1 import (
    A3ExactPlanNonActuatingCallbacksV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanA3DeploymentBindingV2,
    ExactPlanPreflightConfigurationV1,
    ExactPlanPreflightV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPrimitiveDeploymentBindingV1,
    M2CExactPlanPrimitiveBundleV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_a3_runtime_snapshot_v1 import (
    IMPLEMENTATION_REPO_PATH as RUNTIME_SNAPSHOT_IMPLEMENTATION_REPO_PATH,
    FormalIsaacA3RuntimeReadinessSourceV1,
    FormalIsaacA3RuntimeSnapshotProviderV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_plan_synthesis_query_v1 import (
    IMPLEMENTATION_REPO_PATH as PLAN_SYNTHESIS_QUERY_IMPLEMENTATION_REPO_PATH,
    FormalIsaacPlanSynthesisStateQueryV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.isaac_active_session_query_v1 import (
    IMPLEMENTATION_REPO_PATH as ACTIVE_SESSION_QUERY_IMPLEMENTATION_REPO_PATH,
    IsaacActiveSessionQueryProviderV1,
)
from xh_agent.policy.qrm_lite.isaac_exact_plan_runtime_v1 import (
    FrozenProbeExactPlanExecutorV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = (
    "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_bundle_factory_v1.py"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacExactPlanBundleFactoryUnavailable(RuntimeError):
    """One fresh bundle cannot be assembled without crossing the scene."""


def _safe_source_path(project_root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise FormalIsaacExactPlanBundleFactoryUnavailable(
            "formal exact-plan component source path escapes the repository"
        )
    cursor = project_root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan component source path contains a symlink"
            )
    try:
        resolved = cursor.resolve(strict=True)
    except OSError as exc:
        raise FormalIsaacExactPlanBundleFactoryUnavailable(
            "formal exact-plan component source is unavailable"
        ) from exc
    if not resolved.is_relative_to(project_root):
        raise FormalIsaacExactPlanBundleFactoryUnavailable(
            "formal exact-plan component source resolves outside the repository"
        )
    return resolved


class FormalIsaacExactPlanBundleFactoryBindingV1(_FrozenModel):
    """Future addendum identity for the concrete per-decision assembler."""

    schema_version: Literal["FormalIsaacExactPlanBundleFactoryBindingV1"] = (
        "FormalIsaacExactPlanBundleFactoryBindingV1"
    )
    factory_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_bundle_factory_v1.py"
    ] = IMPLEMENTATION_REPO_PATH
    factory_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    component_source_implementation_path: str = Field(min_length=1)
    component_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_readiness_source_implementation_path: str = Field(min_length=1)
    runtime_readiness_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_snapshot_provider_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_isaac_a3_runtime_snapshot_v1.py"
    ] = RUNTIME_SNAPSHOT_IMPLEMENTATION_REPO_PATH
    runtime_snapshot_provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_synthesis_query_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_isaac_plan_synthesis_query_v1.py"
    ] = PLAN_SYNTHESIS_QUERY_IMPLEMENTATION_REPO_PATH
    plan_synthesis_query_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    active_session_query_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/isaac_active_session_query_v1.py"
    ] = ACTIVE_SESSION_QUERY_IMPLEMENTATION_REPO_PATH
    active_session_query_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    primitive_bundle_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    a3_deployment_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    complete_preflight_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transitive_dependency_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    same_persistent_scene_required: Literal[True] = True
    one_fresh_bundle_per_decision: Literal[True] = True
    construction_must_be_non_actuating: Literal[True] = True
    formal_execution_eligible: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    binding_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "FormalIsaacExactPlanBundleFactoryBindingV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("formal exact-plan bundle-factory binding digest differs")
        return self


class FormalIsaacExactPlanComponentSourceV1(Protocol):
    """Reviewed non-actuating constructor for the concrete callback graph."""

    implementation_path: str
    implementation_sha256: str
    real_isaac: bool
    mocked_runtime: bool
    formal_execution_eligible: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1
    active_attachment_source: object
    scene_geometry: object
    scene_pose_provider: object

    def build_bundle_components(
        self,
        *,
        plan: M2CExactPlanPrimitivePlanV1,
        active_session_provider: IsaacActiveSessionQueryProviderV1,
        runtime_snapshot_provider: FormalIsaacA3RuntimeSnapshotProviderV1,
        runtime_snapshot: PreflightRuntimeSnapshotV1,
        configuration: ExactPlanPreflightConfigurationV1,
        primitive_binding: ExactPlanPrimitiveDeploymentBindingV1,
        a3_deployment_binding: ExactPlanA3DeploymentBindingV2 | None,
    ) -> M2CExactPlanPrimitiveBundleV1: ...


class FormalIsaacPerDecisionExactPlanBundleFactoryV1:
    """Claim one synthesis state and assemble exactly one checked bundle."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        binding: FormalIsaacExactPlanBundleFactoryBindingV1 | None,
        primitive_binding: ExactPlanPrimitiveDeploymentBindingV1,
        a3_deployment_binding: ExactPlanA3DeploymentBindingV2 | None,
        plan_synthesis_query: FormalIsaacPlanSynthesisStateQueryV1,
        readiness_source: FormalIsaacA3RuntimeReadinessSourceV1,
        component_source: FormalIsaacExactPlanComponentSourceV1,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.mode = mode
        self.binding = binding
        self.primitive_binding = ExactPlanPrimitiveDeploymentBindingV1.model_validate(
            primitive_binding.model_dump(mode="json")
        )
        self.a3_deployment_binding = (
            ExactPlanA3DeploymentBindingV2.model_validate(
                a3_deployment_binding.model_dump(mode="json")
            )
            if a3_deployment_binding is not None
            else None
        )
        self.plan_synthesis_query = plan_synthesis_query
        self.readiness_source = readiness_source
        self.component_source = component_source
        self.configuration = ExactPlanPreflightConfigurationV1.model_validate(
            configuration.model_dump(mode="json")
        )
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(self.project_root / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.runtime_snapshot_provider_implementation_sha256 = hashlib.sha256(
            read_regular_file_once(self.project_root / RUNTIME_SNAPSHOT_IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        self.plan_synthesis_query_implementation_sha256 = hashlib.sha256(
            read_regular_file_once(
                self.project_root / PLAN_SYNTHESIS_QUERY_IMPLEMENTATION_REPO_PATH
            )
        ).hexdigest()
        self.active_session_query_implementation_sha256 = hashlib.sha256(
            read_regular_file_once(
                self.project_root / ACTIVE_SESSION_QUERY_IMPLEMENTATION_REPO_PATH
            )
        ).hexdigest()
        component_path = _safe_source_path(
            self.project_root,
            component_source.implementation_path,
        )
        self.component_source_implementation_sha256 = hashlib.sha256(
            read_regular_file_once(component_path)
        ).hexdigest()
        self._consumed_plan_sha256: set[str] = set()

        counter = plan_synthesis_query.active_session_factory.mutation_counter_source
        active_configuration = getattr(
            plan_synthesis_query.active_session_factory,
            "configuration",
            None,
        )
        if (
            component_source.implementation_sha256 != self.component_source_implementation_sha256
            or plan_synthesis_query.implementation_sha256
            != self.plan_synthesis_query_implementation_sha256
            or active_configuration is None
            or active_configuration.query_adapter_implementation_sha256
            != self.active_session_query_implementation_sha256
            or readiness_source.mutation_counter_source is not counter
            or component_source.mutation_counter_source is not counter
            or component_source.active_attachment_source
            is not readiness_source.active_attachment_source
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan component sources cross persistent scene identity"
            )
        expected_mode = "REAL_ISAAC" if mode == "REAL_ISAAC" else "CONTRACT_TEST"
        if (
            plan_synthesis_query.mode != expected_mode
            or self.primitive_binding.execution_mode != expected_mode
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan factory mode differs from plan/bundle deployment"
            )
        if mode == "REAL_ISAAC":
            self._validate_real_binding()
        elif (
            binding is not None
            or a3_deployment_binding is not None
            or readiness_source.real_isaac
            or not readiness_source.mocked_runtime
            or component_source.real_isaac
            or not component_source.mocked_runtime
            or component_source.formal_execution_eligible
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "contract exact-plan factory received production claims"
            )

    def _validate_real_binding(self) -> None:
        binding = self.binding
        a3_binding = self.a3_deployment_binding
        source = self.component_source
        readiness = self.readiness_source
        if (
            binding is None
            or a3_binding is None
            or not source.real_isaac
            or source.mocked_runtime
            or not source.formal_execution_eligible
            or not readiness.real_isaac
            or readiness.mocked_runtime
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "REAL_ISAAC exact-plan factory lacks reviewed production bindings"
            )
        expected = {
            "factory_implementation_sha256": self.implementation_sha256,
            "component_source_implementation_path": source.implementation_path,
            "component_source_implementation_sha256": (self.component_source_implementation_sha256),
            "runtime_readiness_source_implementation_path": readiness.implementation_path,
            "runtime_readiness_source_implementation_sha256": (readiness.implementation_sha256),
            "runtime_snapshot_provider_implementation_sha256": (
                self.runtime_snapshot_provider_implementation_sha256
            ),
            "plan_synthesis_query_implementation_sha256": (
                self.plan_synthesis_query_implementation_sha256
            ),
            "active_session_query_implementation_sha256": (
                self.active_session_query_implementation_sha256
            ),
            "primitive_bundle_deployment_sha256": canonical_sha256(self.primitive_binding),
            "a3_deployment_binding_sha256": canonical_sha256(a3_binding),
            "complete_preflight_configuration_sha256": (self.configuration.configuration_sha256),
            "immutable_commit": self.primitive_binding.immutable_commit,
            "container_image_digest": self.primitive_binding.container_image_digest,
            "transitive_dependency_manifest_sha256": (
                a3_binding.formal_deployment_closure_binding[2]
            ),
        }
        if (
            any(getattr(binding, name) != value for name, value in expected.items())
            or a3_binding.immutable_commit != self.primitive_binding.immutable_commit
            or a3_binding.container_image_digest != self.primitive_binding.container_image_digest
            or a3_binding.binding_addendum_sha256 != self.primitive_binding.binding_addendum_sha256
            or a3_binding.unlock_config_sha256 != self.primitive_binding.unlock_config_sha256
            or a3_binding.phase_schema_by_skill != self.primitive_binding.phase_schema_by_skill
            or a3_binding.plan_source_bindings_sha256
            != canonical_sha256(self.primitive_binding.source_bindings)
            or a3_binding.complete_preflight_configuration_sha256
            != self.configuration.configuration_sha256
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan factory binding crosses deployment"
            )

    @property
    def formal_execution_eligible(self) -> bool:
        return bool(
            self.mode == "REAL_ISAAC"
            and self.binding is not None
            and self.a3_deployment_binding is not None
            and self.component_source.formal_execution_eligible
        )

    def _validate_bundle_graph(
        self,
        *,
        plan: M2CExactPlanPrimitivePlanV1,
        active_session: IsaacActiveSessionQueryProviderV1,
        snapshot_provider: FormalIsaacA3RuntimeSnapshotProviderV1,
        bundle: M2CExactPlanPrimitiveBundleV1,
    ) -> None:
        preflight = bundle.preflight_verifier
        executor = bundle.executor
        callbacks = getattr(preflight, "callbacks", None)
        phase_path = getattr(callbacks, "phase_path_provider", None)
        collision = getattr(callbacks, "swept_collision_provider", None)
        attachment = getattr(callbacks, "attachment_transition_provider", None)
        resolver = getattr(callbacks, "attached_geometry_resolver", None)
        snapshot = getattr(callbacks, "runtime_snapshot", None)
        scene_state = getattr(collision, "scene_state", None)
        if self.mode == "REAL_ISAAC" and (
            not isinstance(preflight, ExactPlanPreflightV1)
            or not isinstance(callbacks, A3ExactPlanNonActuatingCallbacksV1)
            or not isinstance(executor, FrozenProbeExactPlanExecutorV1)
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "REAL_ISAAC component source returned a non-production graph"
            )
        if (
            bundle.project_root != self.project_root
            or bundle.binding != self.primitive_binding
            or preflight is None
            or executor is None
            or callbacks is None
            or phase_path is None
            or collision is None
            or attachment is None
            or resolver is None
            or snapshot is None
            or scene_state is None
            or getattr(preflight, "configuration", None) != self.configuration
            or getattr(preflight, "project_root", None) != self.project_root
            or getattr(preflight, "deployment_binding", None) != self.a3_deployment_binding
            or snapshot.bound_plan_sha256 != plan.bound_plan_sha256
            or snapshot.preplan_state_sha256 != plan.inputs.preplan_state_sha256
            or getattr(callbacks, "configuration", None) != self.configuration
            or getattr(callbacks, "runtime_snapshot", None) != snapshot
            or getattr(callbacks, "ik_algorithm_sha256", None)
            != self.configuration.ik.algorithm_sha256
            or getattr(callbacks, "swept_collision_algorithm_sha256", None)
            != self.configuration.swept_collision.algorithm_sha256
            or getattr(callbacks, "attachment_algorithm_sha256", None)
            != self.configuration.attachment.algorithm_sha256
            or getattr(callbacks, "implementation_sha256", None)
            != self.configuration.callback_implementation_sha256
            or getattr(callbacks, "mutation_counter_source", None)
            is not active_session.mutation_counter_source
            or getattr(phase_path, "state_source", None) is not active_session
            or getattr(phase_path, "effort_provider", None) is not active_session
            or getattr(getattr(phase_path, "ik_coordinator", None), "counter_source", None)
            is not active_session.mutation_counter_source
            or getattr(attachment, "runtime_snapshot", None) != snapshot
            or getattr(
                attachment,
                "runtime_snapshot_provider_implementation_sha256",
                None,
            )
            != snapshot_provider.implementation_sha256
            or getattr(collision, "scene_geometry", None) != self.component_source.scene_geometry
            or getattr(scene_state, "bound_plan_sha256", None) != plan.bound_plan_sha256
            or getattr(scene_state, "runtime_snapshot_sha256", None) != snapshot.snapshot_sha256
            or getattr(resolver, "bound_plan_sha256", None) != plan.bound_plan_sha256
            or getattr(resolver, "runtime_snapshot_sha256", None) != snapshot.snapshot_sha256
            or getattr(resolver, "scene_geometry", None) != self.component_source.scene_geometry
            or getattr(resolver, "scene_pose_provider", None)
            is not self.component_source.scene_pose_provider
            or getattr(executor, "project_root", None) != self.project_root
            or getattr(executor, "deployment_binding", None) != self.primitive_binding
            or getattr(executor, "mutation_counter_source", None)
            is not active_session.mutation_counter_source
            or getattr(executor, "attachment_state_registry", None)
            is not self.component_source.active_attachment_source
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan component graph crosses plan/scene/deployment"
            )
        if self.mode == "REAL_ISAAC" and (
            not bundle.formal_execution_eligible
            or getattr(callbacks, "formal_query_evidence_eligible", False) is not True
            or getattr(collision, "formal_query_evidence_eligible", False) is not True
            or getattr(resolver, "real_runtime_provider", False) is not True
            or getattr(executor, "real_isaac", False) is not True
        ):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "REAL_ISAAC component graph is not formal-evidence eligible"
            )

    def build_bundle(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> M2CExactPlanPrimitiveBundleV1:
        plan_sha256 = plan.bound_plan_sha256
        if plan_sha256 in self._consumed_plan_sha256:
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan bundle plan was already consumed"
            )
        if self.mode == "REAL_ISAAC" and not self.formal_execution_eligible:
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan bundle factory is not production-bound"
            )
        # Consume before claiming the physical state or calling the component
        # constructor.  Neither a crossed plan nor a constructor failure may
        # be retried with another callback graph.
        self._consumed_plan_sha256.add(plan_sha256)
        counter = self.plan_synthesis_query.active_session_factory.mutation_counter_source
        before = counter.snapshot_mutation_counters()
        active_session = self.plan_synthesis_query.claim_active_session_query_provider(plan)
        if active_session.mutation_counter_source is not counter:
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "claimed active-session state crosses persistent scene counter"
            )
        snapshot_provider = FormalIsaacA3RuntimeSnapshotProviderV1(
            project_root=self.project_root,
            mode=self.mode,
            active_session_provider=active_session,
            readiness_source=self.readiness_source,
            configuration=self.configuration,
        )
        snapshot = snapshot_provider.build_snapshot(plan)
        bundle = self.component_source.build_bundle_components(
            plan=plan,
            active_session_provider=active_session,
            runtime_snapshot_provider=snapshot_provider,
            runtime_snapshot=snapshot,
            configuration=self.configuration,
            primitive_binding=self.primitive_binding,
            a3_deployment_binding=self.a3_deployment_binding,
        )
        if not isinstance(bundle, M2CExactPlanPrimitiveBundleV1):
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "component source returned the wrong primitive bundle type"
            )
        after = counter.snapshot_mutation_counters()
        if before != after:
            raise FormalIsaacExactPlanBundleFactoryUnavailable(
                "formal exact-plan bundle construction mutated the active scene"
            )
        self._validate_bundle_graph(
            plan=plan,
            active_session=active_session,
            snapshot_provider=snapshot_provider,
            bundle=bundle,
        )
        return bundle


def implementation_sha256_v1(project_root: Path) -> str:
    return hashlib.sha256(
        read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
    ).hexdigest()
