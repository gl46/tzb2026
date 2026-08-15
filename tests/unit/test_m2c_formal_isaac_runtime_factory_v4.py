from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationDeploymentBindingV2,
    PublicAssociationProtocolV2,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPrimitiveDeploymentBindingV1,
    ExactPlanSourceBindingV1,
    M2CExactPlanPrimitiveBundleV1,
)
from xh_agent.policy.qrm_lite.formal_bound_plan_provider_v1 import (
    FormalBoundExactPlanProviderV1,
    FormalBoundPlanProviderDeploymentV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_episode_io_v4 import (
    FormalIsaacEpisodeIODeploymentBindingV1,
    FormalIsaacEpisodeIOV4,
)
from xh_agent.policy.qrm_lite.formal_isaac_runtime_factory_v4 import (
    BOUND_PROVIDER_REPO_PATH,
    EPISODE_IO_REPO_PATH,
    EXACT_RUNTIME_REPO_PATH,
    IMPLEMENTATION_REPO_PATH,
    OBSERVATION_PROVIDER_REPO_PATH,
    PRIMITIVE_BUNDLE_REPO_PATH,
    FormalIsaacV4RuntimeFactoryBindingV1,
    FormalIsaacV4RuntimeFactoryV1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    ReplayableFormalPublicObservationProviderV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacEndpointBindingV4
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PublicDeclaredTargetAttributeBindingV4,
)


ROOT = Path(__file__).parents[2]
ENDPOINT_REPO_PATH = "scripts/m2c/serve_formal_isaac_endpoint_v4.py"
SCENE_OWNER_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_persistent_scene_v4.py"
REGISTRY_REPO_PATH = "configs/qrm_runtime_mapping_v2.yaml"
SOURCE_PATHS = (
    IMPLEMENTATION_REPO_PATH,
    ENDPOINT_REPO_PATH,
    EPISODE_IO_REPO_PATH,
    OBSERVATION_PROVIDER_REPO_PATH,
    EXACT_RUNTIME_REPO_PATH,
    BOUND_PROVIDER_REPO_PATH,
    PRIMITIVE_BUNDLE_REPO_PATH,
    SCENE_OWNER_REPO_PATH,
    REGISTRY_REPO_PATH,
)
SOURCE_ROLES = (
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
)
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


def _git(project: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _project(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    project = tmp_path / "project"
    project.mkdir()
    for relative in SOURCE_PATHS:
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    _git(project, "init", "-q")
    _git(project, "config", "user.name", "M2C Contract")
    _git(project, "config", "user.email", "m2c-contract@example.invalid")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "freeze V4 runtime factory fixture")
    commit = _git(project, "rev-parse", "HEAD")
    hashes = {
        relative: hashlib.sha256((project / relative).read_bytes()).hexdigest()
        for relative in SOURCE_PATHS
    }
    return project, commit, hashes


def _association(source_sha256: str) -> PublicAssociationDeploymentBindingV2:
    transform = [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    protocol = PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=transform,
        calibration_sha256=canonical_sha256(transform),
    )
    payload = {
        "schema_version": "PublicAssociationDeploymentBindingV2",
        "associator_revision": "PublicTrackAssociatorV2",
        "associator_implementation_sha256": "1" * 64,
        "capture_source_implementation_sha256": source_sha256,
        "protocol": protocol.model_dump(mode="json"),
        "protocol_sha256": canonical_sha256(protocol),
        "assignment_objective": (
            "MAXIMUM_CARDINALITY_THEN_MINIMUM_TOTAL_QUANTIZED_COST_THEN_LEXICOGRAPHIC_V2"
        ),
        "association_gate_m": 0.12,
        "ambiguity_margin_m": 0.02,
        "cost_quantum_m": 0.000001,
        "max_consecutive_unmatched_captures": 2,
        "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
        "max_current_detections": 32,
    }
    payload["deployment_binding_sha256"] = canonical_sha256(payload)
    return PublicAssociationDeploymentBindingV2.model_validate(payload)


def _attribute() -> PublicDeclaredTargetAttributeBindingV4:
    payload = {
        "schema_version": "PublicDeclaredTargetAttributeBindingV4",
        "declared_target_attribute": "yellow",
        "public_target_selector": "visual_color=yellow",
        "selector_source_implementation_sha256": "2" * 64,
        "task_spec_public_receipt_sha256": "3" * 64,
    }
    payload["binding_sha256"] = canonical_sha256(payload)
    return PublicDeclaredTargetAttributeBindingV4.model_validate(payload)


def _contracts(
    tmp_path: Path,
) -> tuple[
    Path,
    IsaacEndpointBindingV4,
    FormalIsaacEpisodeIODeploymentBindingV1,
    PublicAssociationDeploymentBindingV2,
    PublicDeclaredTargetAttributeBindingV4,
    FormalBoundPlanProviderDeploymentV1,
    ExactPlanPrimitiveDeploymentBindingV1,
    FormalIsaacV4RuntimeFactoryBindingV1,
]:
    project, commit, hashes = _project(tmp_path)
    association = _association(hashes[SCENE_OWNER_REPO_PATH])
    attribute = _attribute()
    endpoint = IsaacEndpointBindingV4(
        endpoint_base_url="http://127.0.0.1:18765",
        host="labserver",
        implementation_path=ENDPOINT_REPO_PATH,
        implementation_sha256=hashes[ENDPOINT_REPO_PATH],
        physical_backend_path=EPISODE_IO_REPO_PATH,
        physical_backend_sha256=hashes[EPISODE_IO_REPO_PATH],
        public_observation_provider_path=OBSERVATION_PROVIDER_REPO_PATH,
        public_observation_provider_sha256=hashes[OBSERVATION_PROVIDER_REPO_PATH],
        formal_exact_plan_runtime_path=EXACT_RUNTIME_REPO_PATH,
        formal_exact_plan_runtime_sha256=hashes[EXACT_RUNTIME_REPO_PATH],
        bound_plan_provider_path=BOUND_PROVIDER_REPO_PATH,
        bound_plan_provider_sha256=hashes[BOUND_PROVIDER_REPO_PATH],
        primitive_bundle_path=PRIMITIVE_BUNDLE_REPO_PATH,
        primitive_bundle_sha256=hashes[PRIMITIVE_BUNDLE_REPO_PATH],
        a3_deployment_binding_sha256="4" * 64,
        runtime_registry_path=REGISTRY_REPO_PATH,
        runtime_registry_sha256=hashes[REGISTRY_REPO_PATH],
        association_deployment_sha256=association.deployment_binding_sha256,
        capture_source_implementation_sha256=hashes[SCENE_OWNER_REPO_PATH],
        declared_attribute_selector_implementation_sha256=(
            attribute.selector_source_implementation_sha256
        ),
        immutable_commit=commit,
        container_image_digest="sha256:" + "5" * 64,
        transitive_dependency_manifest_sha256="6" * 64,
    )
    episode_payload = {
        "schema_version": "FormalIsaacEpisodeIODeploymentBindingV1",
        "accepted_adr_path": "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md",
        "accepted_adr_sha256": "7" * 64,
        "lifecycle_implementation_path": EPISODE_IO_REPO_PATH,
        "lifecycle_implementation_sha256": hashes[EPISODE_IO_REPO_PATH],
        "scene_owner_implementation_path": SCENE_OWNER_REPO_PATH,
        "scene_owner_implementation_sha256": hashes[SCENE_OWNER_REPO_PATH],
        "capture_source_implementation_path": SCENE_OWNER_REPO_PATH,
        "capture_source_implementation_sha256": hashes[SCENE_OWNER_REPO_PATH],
        "public_observation_provider_path": OBSERVATION_PROVIDER_REPO_PATH,
        "public_observation_provider_sha256": hashes[OBSERVATION_PROVIDER_REPO_PATH],
        "endpoint_binding_sha256": canonical_sha256(endpoint),
        "association_deployment_sha256": association.deployment_binding_sha256,
        "declared_attribute_binding_sha256": attribute.binding_sha256,
        "immutable_commit": commit,
        "container_image_digest": endpoint.container_image_digest,
        "transitive_dependency_manifest_sha256": (endpoint.transitive_dependency_manifest_sha256),
        "review_status": "REVIEWED_BINDING_ADDENDUM",
        "formal_execution_eligible": True,
        "real_isaac": True,
        "mocked_physics": False,
        "simulator_identity_exposed_to_model": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    episode_payload["deployment_binding_sha256"] = canonical_sha256(episode_payload)
    episode = FormalIsaacEpisodeIODeploymentBindingV1.model_validate(episode_payload)
    source_bindings = tuple(
        ExactPlanSourceBindingV1(
            role=role,  # type: ignore[arg-type]
            path=PRIMITIVE_BUNDLE_REPO_PATH,
            sha256=hashes[PRIMITIVE_BUNDLE_REPO_PATH],
        )
        for role in SOURCE_ROLES
    )
    phase_schema = tuple((skill, "8" * 64) for skill in SKILLS)
    provider = FormalBoundPlanProviderDeploymentV1(
        adr_0022_sha256="9" * 64,
        adr_0024_sha256="a" * 64,
        binding_addendum_sha256="b" * 64,
        unlock_config_sha256="c" * 64,
        immutable_commit=commit,
        container_image_digest=endpoint.container_image_digest,
        provider_implementation_sha256=hashes[BOUND_PROVIDER_REPO_PATH],
        synthesis_backend_implementation_sha256="d" * 64,
        query_source_implementation_sha256="e" * 64,
        source_bindings=source_bindings,
        phase_schema_by_skill=phase_schema,
    )
    bundle = ExactPlanPrimitiveDeploymentBindingV1(
        adr_sha256=provider.adr_0022_sha256,
        superseding_adr_sha256=provider.adr_0024_sha256,
        binding_addendum_sha256=provider.binding_addendum_sha256,
        unlock_config_sha256=provider.unlock_config_sha256,
        immutable_commit=commit,
        container_image_digest=endpoint.container_image_digest,
        source_bindings=source_bindings,
        phase_schema_by_skill=phase_schema,
        execution_mode="REAL_ISAAC",
    )
    factory_payload = {
        "schema_version": "FormalIsaacV4RuntimeFactoryBindingV1",
        "factory_implementation_path": IMPLEMENTATION_REPO_PATH,
        "factory_implementation_sha256": hashes[IMPLEMENTATION_REPO_PATH],
        "endpoint_binding_sha256": canonical_sha256(endpoint),
        "episode_io_deployment_binding_sha256": canonical_sha256(episode),
        "bound_plan_provider_deployment_sha256": canonical_sha256(provider),
        "primitive_bundle_deployment_sha256": canonical_sha256(bundle),
        "immutable_commit": commit,
        "container_image_digest": endpoint.container_image_digest,
        "transitive_dependency_manifest_sha256": (endpoint.transitive_dependency_manifest_sha256),
        "review_status": "REVIEWED_BINDING_ADDENDUM",
        "formal_execution_eligible": True,
        "invalid_action_policy": "TERMINAL_NO_PHYSICAL_EXECUTION",
        "b0_runtime_fallback_present": False,
        "real_isaac": True,
        "mocked_physics": False,
        "scripted_decision_source": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    factory_payload["binding_sha256"] = canonical_sha256(factory_payload)
    factory = FormalIsaacV4RuntimeFactoryBindingV1.model_validate(factory_payload)
    return project, endpoint, episode, association, attribute, provider, bundle, factory


class _Lifecycle:
    real_isaac = True
    mocked_physics = False

    def __init__(self, implementation_sha256: str) -> None:
        self.implementation_sha256 = implementation_sha256


class _CaptureSource:
    real_isaac = True
    mocked_physics = False

    def __init__(self, implementation_sha256: str) -> None:
        self.implementation_sha256 = implementation_sha256


def _objects(
    *,
    project: Path,
    endpoint: IsaacEndpointBindingV4,
    episode_binding: FormalIsaacEpisodeIODeploymentBindingV1,
    association: PublicAssociationDeploymentBindingV2,
    attribute: PublicDeclaredTargetAttributeBindingV4,
    provider_deployment: FormalBoundPlanProviderDeploymentV1,
    bundle_deployment: ExactPlanPrimitiveDeploymentBindingV1,
):
    episode_io = object.__new__(FormalIsaacEpisodeIOV4)
    episode_io.binding = episode_binding
    episode_io.lifecycle = _Lifecycle(endpoint.physical_backend_sha256)
    episode_io.capture_source = _CaptureSource(endpoint.capture_source_implementation_sha256)
    observations = object.__new__(ReplayableFormalPublicObservationProviderV4)
    observations.mode = "REAL_ISAAC"
    observations.source = episode_io.capture_source
    observations.deployment = association
    observations.attribute_binding = attribute
    provider = object.__new__(FormalBoundExactPlanProviderV1)
    provider.project_root = project
    provider.mode = "REAL_ISAAC"
    provider.backend = SimpleNamespace(real_isaac=True, mocked_physics=False)
    provider.deployment = provider_deployment
    provider.implementation_sha256 = endpoint.bound_plan_provider_sha256
    bundle = object.__new__(M2CExactPlanPrimitiveBundleV1)
    bundle.project_root = project
    bundle.binding = bundle_deployment
    bundle.preflight_verifier = object()
    bundle.executor = SimpleNamespace(real_isaac=True)
    return episode_io, observations, provider, bundle


def _factory(tmp_path: Path):  # noqa: ANN202
    contracts = _contracts(tmp_path)
    project, endpoint, episode, association, attribute, provider, bundle, factory = contracts
    episode_io, observations, provider_object, bundle_object = _objects(
        project=project,
        endpoint=endpoint,
        episode_binding=episode,
        association=association,
        attribute=attribute,
        provider_deployment=provider,
        bundle_deployment=bundle,
    )
    instance = FormalIsaacV4RuntimeFactoryV1(
        project_root=project,
        binding=factory,
        endpoint_binding=endpoint,
        episode_io=episode_io,
        observation_provider=observations,
        association_deployment=association,
        declared_attribute_binding=attribute,
        bound_plan_provider=provider_object,
        bound_plan_provider_deployment=provider,
        primitive_bundle=bundle_object,
        primitive_bundle_deployment=bundle,
        runtime_registry_sha256=endpoint.runtime_registry_sha256,
    )
    return instance, contracts, (episode_io, observations, provider_object, bundle_object)


def test_factory_composes_one_backend_without_starting_scene(tmp_path: Path) -> None:
    instance, contracts, objects = _factory(tmp_path)
    _, endpoint, episode, association, attribute, provider, bundle, factory = contracts
    episode_io, observations, provider_object, bundle_object = objects
    receipt = instance.assembly.receipt
    assert instance.assembly.backend.lifecycle is episode_io.lifecycle
    assert instance.assembly.backend.observation_provider is observations
    assert instance.assembly.backend.exact_plan_runtime.provider is provider_object
    assert instance.assembly.backend.exact_plan_runtime.bundle is bundle_object
    assert receipt.factory_binding_sha256 == factory.binding_sha256
    assert receipt.endpoint_binding_sha256 == canonical_sha256(endpoint)
    assert receipt.episode_io_deployment_binding_sha256 == canonical_sha256(episode)
    assert receipt.association_deployment_sha256 == association.deployment_binding_sha256
    assert receipt.declared_attribute_binding_sha256 == attribute.binding_sha256
    assert receipt.bound_plan_provider_deployment_sha256 == canonical_sha256(provider)
    assert receipt.primitive_bundle_deployment_sha256 == canonical_sha256(bundle)
    assert receipt.physical_execution_performed is False
    assert receipt.scene_started is False
    assert receipt.model_inference_performed is False


def test_factory_rejects_crossed_capture_source_before_backend(tmp_path: Path) -> None:
    contracts = _contracts(tmp_path)
    project, endpoint, episode, association, attribute, provider, bundle, factory = contracts
    episode_io, observations, provider_object, bundle_object = _objects(
        project=project,
        endpoint=endpoint,
        episode_binding=episode,
        association=association,
        attribute=attribute,
        provider_deployment=provider,
        bundle_deployment=bundle,
    )
    observations.source = _CaptureSource(endpoint.capture_source_implementation_sha256)
    with pytest.raises(ValueError, match="objects cross"):
        FormalIsaacV4RuntimeFactoryV1(
            project_root=project,
            binding=factory,
            endpoint_binding=endpoint,
            episode_io=episode_io,
            observation_provider=observations,
            association_deployment=association,
            declared_attribute_binding=attribute,
            bound_plan_provider=provider_object,
            bound_plan_provider_deployment=provider,
            primitive_bundle=bundle_object,
            primitive_bundle_deployment=bundle,
            runtime_registry_sha256=endpoint.runtime_registry_sha256,
        )


def test_factory_rejects_dirty_runtime_source(tmp_path: Path) -> None:
    contracts = _contracts(tmp_path)
    project, endpoint, episode, association, attribute, provider, bundle, factory = contracts
    episode_io, observations, provider_object, bundle_object = _objects(
        project=project,
        endpoint=endpoint,
        episode_binding=episode,
        association=association,
        attribute=attribute,
        provider_deployment=provider,
        bundle_deployment=bundle,
    )
    (project / REGISTRY_REPO_PATH).write_text("tampered: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source digest differs"):
        FormalIsaacV4RuntimeFactoryV1(
            project_root=project,
            binding=factory,
            endpoint_binding=endpoint,
            episode_io=episode_io,
            observation_provider=observations,
            association_deployment=association,
            declared_attribute_binding=attribute,
            bound_plan_provider=provider_object,
            bound_plan_provider_deployment=provider,
            primitive_bundle=bundle_object,
            primitive_bundle_deployment=bundle,
            runtime_registry_sha256=endpoint.runtime_registry_sha256,
        )


def test_factory_binding_rejects_digest_tamper(tmp_path: Path) -> None:
    *_, factory = _contracts(tmp_path)
    with pytest.raises(ValueError, match="binding digest differs"):
        FormalIsaacV4RuntimeFactoryBindingV1.model_validate(
            {**factory.model_dump(mode="json"), "immutable_commit": "f" * 40}
        )


def test_factory_rejects_untyped_episode_io(tmp_path: Path) -> None:
    project, endpoint, episode, association, attribute, provider, bundle, factory = _contracts(
        tmp_path
    )
    _, observations, provider_object, bundle_object = _objects(
        project=project,
        endpoint=endpoint,
        episode_binding=episode,
        association=association,
        attribute=attribute,
        provider_deployment=provider,
        bundle_deployment=bundle,
    )
    with pytest.raises(TypeError, match="FormalIsaacEpisodeIOV4"):
        FormalIsaacV4RuntimeFactoryV1(
            project_root=project,
            binding=factory,
            endpoint_binding=endpoint,
            episode_io=SimpleNamespace(binding=episode),  # type: ignore[arg-type]
            observation_provider=observations,
            association_deployment=association,
            declared_attribute_binding=attribute,
            bound_plan_provider=provider_object,
            bound_plan_provider_deployment=provider,
            primitive_bundle=bundle_object,
            primitive_bundle_deployment=bundle,
            runtime_registry_sha256=endpoint.runtime_registry_sha256,
        )
