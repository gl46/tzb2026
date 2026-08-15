from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_m2c_formal_exact_plan_synthesis_v1 import (
    _configuration as _synthesis_configuration,
    _request_and_mapping,
)
from test_m2c_formal_isaac_a3_runtime_snapshot_v1 import (
    _Journal,
    _ReadinessSource,
    _preflight_configuration,
)
from test_m2c_formal_isaac_plan_synthesis_query_v1 import _query
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPrimitiveDeploymentBindingV1,
    M2CExactPlanPrimitiveBundleV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanA3DeploymentBindingV2,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_synthesis_v1 import (
    ConfiguredFormalExactPlanSynthesisBackendV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_exact_plan_bundle_factory_v1 import (
    FormalIsaacExactPlanBundleFactoryBindingV1,
    FormalIsaacExactPlanBundleFactoryUnavailable,
    FormalIsaacPerDecisionExactPlanBundleFactoryV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_scene_safety_binding_v1 import (
    FormalIsaacActiveAttachmentRegistryV2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "tests/unit/test_m2c_formal_isaac_exact_plan_bundle_factory_v1.py"
SKILLS = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)


def _plan_and_query(tmp_path: Path):  # type: ignore[no-untyped-def]
    request, mapping = _request_and_mapping("GRASP")
    query, _ = _query()
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_synthesis_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 4,
    )
    result = backend.synthesize_bound_plan(
        request=request,
        observation=request.observation,
        mapping=mapping,
    )
    return result.bound_plan, query


def _primitive_binding(plan) -> ExactPlanPrimitiveDeploymentBindingV1:  # type: ignore[no-untyped-def]
    phase_schemas = tuple(
        (
            skill,
            plan.phase_schema_sha256
            if skill == plan.exact_execution_plan.canonical_skill
            else "f" * 64,
        )
        for skill in SKILLS
    )
    return ExactPlanPrimitiveDeploymentBindingV1(
        adr_sha256=hashlib.sha256(
            (
                ROOT / "docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"
            ).read_bytes()
        ).hexdigest(),
        superseding_adr_sha256=hashlib.sha256(
            (ROOT / "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md").read_bytes()
        ).hexdigest(),
        binding_addendum_sha256="a" * 64,
        unlock_config_sha256="b" * 64,
        immutable_commit=plan.inputs.immutable_commit,
        container_image_digest=plan.inputs.container_image_digest,
        source_bindings=plan.source_bindings,
        phase_schema_by_skill=phase_schemas,
        execution_mode="CONTRACT_TEST",
    )


class _ComponentSource:
    implementation_path = SOURCE_PATH
    real_isaac = False
    mocked_runtime = True
    formal_execution_eligible = False

    def __init__(
        self,
        *,
        counter,
        attachment,
        cross: str | None = None,
        mutate: bool = False,
        wrong_type: bool = False,
    ) -> None:
        self.implementation_sha256 = hashlib.sha256(
            (ROOT / self.implementation_path).read_bytes()
        ).hexdigest()
        self.mutation_counter_source = counter
        self.active_attachment_source = attachment
        self.scene_geometry = SimpleNamespace(receipt_sha256="1" * 64)
        self.scene_pose_provider = object()
        self.cross = cross
        self.mutate = mutate
        self.wrong_type = wrong_type
        self.calls = 0

    def build_bundle_components(
        self,
        *,
        plan,
        active_session_provider,
        runtime_snapshot_provider,
        runtime_snapshot,
        configuration,
        primitive_binding,
        a3_deployment_binding,
    ):
        self.calls += 1
        if self.mutate:
            self.mutation_counter_source.writes += 1
        if self.wrong_type:
            return object()
        phase_path = SimpleNamespace(
            state_source=(object() if self.cross == "active_state" else active_session_provider),
            effort_provider=active_session_provider,
            ik_coordinator=SimpleNamespace(
                counter_source=active_session_provider.mutation_counter_source
            ),
        )
        scene_geometry = object() if self.cross == "scene_geometry" else self.scene_geometry
        scene_state = SimpleNamespace(
            bound_plan_sha256=plan.bound_plan_sha256,
            runtime_snapshot_sha256=runtime_snapshot.snapshot_sha256,
        )
        collision = SimpleNamespace(
            scene_geometry=scene_geometry,
            scene_state=scene_state,
            formal_query_evidence_eligible=False,
        )
        attachment = SimpleNamespace(
            runtime_snapshot=runtime_snapshot,
            runtime_snapshot_provider_implementation_sha256=(
                runtime_snapshot_provider.implementation_sha256
            ),
        )
        resolver = SimpleNamespace(
            bound_plan_sha256=plan.bound_plan_sha256,
            runtime_snapshot_sha256=runtime_snapshot.snapshot_sha256,
            scene_geometry=self.scene_geometry,
            scene_pose_provider=self.scene_pose_provider,
            real_runtime_provider=False,
            mocked_provider=True,
        )
        callbacks = SimpleNamespace(
            configuration=configuration,
            runtime_snapshot=runtime_snapshot,
            mutation_counter_source=active_session_provider.mutation_counter_source,
            phase_path_provider=phase_path,
            swept_collision_provider=collision,
            attachment_transition_provider=attachment,
            attached_geometry_resolver=resolver,
            ik_algorithm_sha256=configuration.ik.algorithm_sha256,
            swept_collision_algorithm_sha256=(configuration.swept_collision.algorithm_sha256),
            attachment_algorithm_sha256=configuration.attachment.algorithm_sha256,
            implementation_sha256=configuration.callback_implementation_sha256,
            formal_query_evidence_eligible=False,
        )
        preflight = SimpleNamespace(
            callbacks=callbacks,
            configuration=configuration,
            project_root=ROOT,
            deployment_binding=a3_deployment_binding,
            implementation_sha256="2" * 64,
        )
        executor = SimpleNamespace(
            project_root=ROOT,
            deployment_binding=primitive_binding,
            mutation_counter_source=active_session_provider.mutation_counter_source,
            attachment_state_registry=(
                object() if self.cross == "attachment_registry" else self.active_attachment_source
            ),
            real_isaac=False,
            implementation_sha256="3" * 64,
        )
        return M2CExactPlanPrimitiveBundleV1(
            project_root=ROOT,
            binding=primitive_binding,
            preflight_verifier=preflight,
            executor=executor,
        )


def _factory(
    tmp_path: Path,
    *,
    cross: str | None = None,
    mutate: bool = False,
    wrong_type: bool = False,
):  # type: ignore[no-untyped-def]
    plan, query = _plan_and_query(tmp_path)
    counter = query.active_session_factory.mutation_counter_source
    attachment = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=_Journal(),
    )
    readiness = _ReadinessSource(counter, attachment)
    active_for_configuration = query.active_session_factory.create_active_session_query_provider()
    configuration = _preflight_configuration(active_for_configuration)
    component = _ComponentSource(
        counter=counter,
        attachment=attachment,
        cross=cross,
        mutate=mutate,
        wrong_type=wrong_type,
    )
    factory = FormalIsaacPerDecisionExactPlanBundleFactoryV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        binding=None,
        primitive_binding=_primitive_binding(plan),
        a3_deployment_binding=None,
        plan_synthesis_query=query,
        readiness_source=readiness,
        component_source=component,
        configuration=configuration,
    )
    return plan, query, component, factory


def test_factory_builds_one_bundle_over_the_claimed_state(tmp_path: Path) -> None:
    plan, _, component, factory = _factory(tmp_path)

    bundle = factory.build_bundle(plan)

    callbacks = bundle.preflight_verifier.callbacks
    assert component.calls == 1
    assert callbacks.runtime_snapshot.bound_plan_sha256 == plan.bound_plan_sha256
    assert callbacks.phase_path_provider.state_source is (
        callbacks.phase_path_provider.effort_provider
    )
    assert callbacks.mutation_counter_source is component.mutation_counter_source
    assert bundle.executor.attachment_state_registry is component.active_attachment_source
    assert factory.formal_execution_eligible is False
    with pytest.raises(FormalIsaacExactPlanBundleFactoryUnavailable, match="already consumed"):
        factory.build_bundle(plan)


@pytest.mark.parametrize(
    "cross",
    ("active_state", "scene_geometry", "attachment_registry"),
)
def test_factory_rejects_crossed_component_graph(
    tmp_path: Path,
    cross: str,
) -> None:
    plan, _, component, factory = _factory(tmp_path, cross=cross)

    with pytest.raises(FormalIsaacExactPlanBundleFactoryUnavailable, match="crosses"):
        factory.build_bundle(plan)
    assert component.calls == 1


def test_factory_rejects_component_construction_mutation(tmp_path: Path) -> None:
    plan, _, _, factory = _factory(tmp_path, mutate=True)

    with pytest.raises(FormalIsaacExactPlanBundleFactoryUnavailable, match="mutated"):
        factory.build_bundle(plan)


def test_factory_rejects_wrong_bundle_type(tmp_path: Path) -> None:
    plan, _, _, factory = _factory(tmp_path, wrong_type=True)

    with pytest.raises(FormalIsaacExactPlanBundleFactoryUnavailable, match="wrong"):
        factory.build_bundle(plan)


def test_factory_constructor_rejects_crossed_component_source_bytes(
    tmp_path: Path,
) -> None:
    plan, query = _plan_and_query(tmp_path)
    counter = query.active_session_factory.mutation_counter_source
    attachment = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=_Journal(),
    )
    readiness = _ReadinessSource(counter, attachment)
    component = _ComponentSource(counter=counter, attachment=attachment)
    component.implementation_sha256 = "f" * 64
    active = query.active_session_factory.create_active_session_query_provider()

    with pytest.raises(FormalIsaacExactPlanBundleFactoryUnavailable, match="cross"):
        FormalIsaacPerDecisionExactPlanBundleFactoryV1(
            project_root=ROOT,
            mode="CONTRACT_TEST",
            binding=None,
            primitive_binding=_primitive_binding(plan),
            a3_deployment_binding=None,
            plan_synthesis_query=query,
            readiness_source=readiness,
            component_source=component,
            configuration=_preflight_configuration(active),
        )


def test_crossed_plan_consumes_query_state_and_cannot_retry(tmp_path: Path) -> None:
    plan, query, _, factory = _factory(tmp_path)
    crossed = plan.model_copy(
        update={"inputs": plan.inputs.model_copy(update={"plan_synthesis_state_sha256": "f" * 64})}
    )

    with pytest.raises(Exception, match="crosses"):
        factory.build_bundle(crossed)
    with pytest.raises(Exception, match="already claimed"):
        query.claim_active_session_query_provider(plan)


def _a3_binding(
    *,
    plan,
    primitive: ExactPlanPrimitiveDeploymentBindingV1,
    configuration,
    transitive_manifest_sha256: str,
) -> ExactPlanA3DeploymentBindingV2:
    payload = {
        "schema_version": "ExactPlanA3DeploymentBindingV2",
        "status": "ACCEPTED_PHASE2_BINDING_ADDENDUM",
        "accepted_adr_sha256": ("62c14028df1ad91e4d3c4282c4775e33149292e9bcf10add2d505be8c7424689"),
        "binding_addendum_sha256": primitive.binding_addendum_sha256,
        "unlock_config_sha256": primitive.unlock_config_sha256,
        "immutable_commit": primitive.immutable_commit,
        "container_image_digest": primitive.container_image_digest,
        "preflight_implementation_path": (
            "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py"
        ),
        "preflight_implementation_sha256": "1" * 64,
        "callback_implementation_path": (
            "src/xh_agent/policy/qrm_lite/a3_exact_plan_callbacks_v1.py"
        ),
        "callback_implementation_sha256": configuration.callback_implementation_sha256,
        "complete_preflight_configuration_sha256": configuration.configuration_sha256,
        "plan_source_bindings_sha256": canonical_sha256(plan.source_bindings),
        "phase_schema_by_skill": primitive.phase_schema_by_skill,
        "session_audit_implementation_sha256": "2" * 64,
        "host_hmac_verifier_sha256": "3" * 64,
        "entry_gate_sha256": "4" * 64,
        "formal_physical_runner_binding": ("scripts/m2c/formal_runner.py", "5" * 64),
        "formal_deployment_closure_binding": (
            primitive.immutable_commit,
            primitive.container_image_digest,
            transitive_manifest_sha256,
        ),
        "frozen_b0_runtime_wrapper_binding": None,
        "offline_wire_authentication_verifier_binding": None,
        "reviewed_addendum_accepted": True,
        "immutable_git_tree_required": True,
        "session_bound_execution_receipt_required": True,
        "host_hmac_post_execution_replay_required": True,
        "trusted_host_signature_required": False,
        "launcher_attestation_required": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    draft = ExactPlanA3DeploymentBindingV2.model_construct(
        **payload,
        binding_sha256="0" * 64,
    )
    normalized = draft.model_dump(mode="json", exclude={"binding_sha256"})
    normalized["binding_sha256"] = canonical_sha256(normalized)
    return ExactPlanA3DeploymentBindingV2.model_validate(normalized)


def test_real_binding_cross_checks_transitive_manifest(tmp_path: Path) -> None:
    plan, query = _plan_and_query(tmp_path)
    primitive = ExactPlanPrimitiveDeploymentBindingV1.model_validate(
        {
            **_primitive_binding(plan).model_dump(mode="json"),
            "execution_mode": "REAL_ISAAC",
        }
    )
    active = query.active_session_factory.create_active_session_query_provider()
    configuration = _preflight_configuration(active)
    manifest_sha256 = "6" * 64
    a3 = _a3_binding(
        plan=plan,
        primitive=primitive,
        configuration=configuration,
        transitive_manifest_sha256=manifest_sha256,
    )
    component = SimpleNamespace(
        implementation_path=SOURCE_PATH,
        real_isaac=True,
        mocked_runtime=False,
        formal_execution_eligible=True,
    )
    readiness = SimpleNamespace(
        implementation_path=SOURCE_PATH,
        implementation_sha256="7" * 64,
        real_isaac=True,
        mocked_runtime=False,
    )
    implementation_sha256 = hashlib.sha256(
        (
            ROOT / "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_bundle_factory_v1.py"
        ).read_bytes()
    ).hexdigest()
    component_sha256 = hashlib.sha256((ROOT / SOURCE_PATH).read_bytes()).hexdigest()
    binding_payload = {
        "schema_version": "FormalIsaacExactPlanBundleFactoryBindingV1",
        "factory_implementation_sha256": implementation_sha256,
        "component_source_implementation_path": SOURCE_PATH,
        "component_source_implementation_sha256": component_sha256,
        "runtime_readiness_source_implementation_path": SOURCE_PATH,
        "runtime_readiness_source_implementation_sha256": readiness.implementation_sha256,
        "primitive_bundle_deployment_sha256": canonical_sha256(primitive),
        "a3_deployment_binding_sha256": canonical_sha256(a3),
        "complete_preflight_configuration_sha256": configuration.configuration_sha256,
        "immutable_commit": primitive.immutable_commit,
        "container_image_digest": primitive.container_image_digest,
        "transitive_dependency_manifest_sha256": manifest_sha256,
        "same_persistent_scene_required": True,
        "one_fresh_bundle_per_decision": True,
        "construction_must_be_non_actuating": True,
        "formal_execution_eligible": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    binding_draft = FormalIsaacExactPlanBundleFactoryBindingV1.model_construct(
        **binding_payload,
        binding_sha256="0" * 64,
    )
    binding_payload = binding_draft.model_dump(
        mode="json",
        exclude={"binding_sha256"},
    )
    binding_payload["binding_sha256"] = canonical_sha256(binding_payload)
    binding = FormalIsaacExactPlanBundleFactoryBindingV1.model_validate(binding_payload)
    factory = object.__new__(FormalIsaacPerDecisionExactPlanBundleFactoryV1)
    factory.binding = binding
    factory.a3_deployment_binding = a3
    factory.component_source = component
    factory.readiness_source = readiness
    factory.implementation_sha256 = implementation_sha256
    factory.component_source_implementation_sha256 = component_sha256
    factory.primitive_binding = primitive
    factory.configuration = configuration

    factory._validate_real_binding()

    crossed_payload = binding.model_dump(mode="json", exclude={"binding_sha256"})
    crossed_payload["transitive_dependency_manifest_sha256"] = "8" * 64
    crossed_payload["binding_sha256"] = canonical_sha256(crossed_payload)
    factory.binding = FormalIsaacExactPlanBundleFactoryBindingV1.model_validate(crossed_payload)
    with pytest.raises(FormalIsaacExactPlanBundleFactoryUnavailable, match="crosses"):
        factory._validate_real_binding()
