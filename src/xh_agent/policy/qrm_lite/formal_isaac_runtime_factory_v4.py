"""Single production assembly boundary for the formal V4 Isaac runtime.

The individual V4 lifecycle, public-observation, exact-plan provider, and
primitive bundle contracts intentionally validate their own deployments.  A
formal endpoint still needs one place that proves those already-constructed
objects belong to the *same* immutable deployment before exposing a backend.

This module performs that composition only.  It does not load Isaac, build a
scene, synthesize a plan, execute a command, or provide an experimental
authorization.  Every source used by the assembled runtime is re-read from a
clean immutable Git commit before the coordinator is returned.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationDeploymentBindingV2,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPrimitiveDeploymentBindingV1,
    M2CExactPlanPrimitiveBundleV1,
)
from xh_agent.policy.qrm_lite.formal_bound_plan_provider_v1 import (
    FormalBoundExactPlanProviderV1,
    FormalBoundPlanProviderDeploymentV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    FormalExactPlanRuntimeV1,
    PerDecisionExactPlanBundleRuntimeV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_backend_v4 import (
    FormalIsaacBackendCoordinatorV4,
)
from xh_agent.policy.qrm_lite.formal_isaac_episode_io_v4 import (
    FormalIsaacEpisodeIODeploymentBindingV1,
    FormalIsaacEpisodeIOV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    ReplayableFormalPublicObservationProviderV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacEndpointBindingV4
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PublicDeclaredTargetAttributeBindingV4,
)


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_runtime_factory_v4.py"
EPISODE_IO_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_episode_io_v4.py"
OBSERVATION_PROVIDER_REPO_PATH = (
    "src/xh_agent/policy/qrm_lite/formal_public_observation_provider_v4.py"
)
EXACT_RUNTIME_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_exact_plan_runtime_v1.py"
BOUND_PROVIDER_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_bound_plan_provider_v1.py"
PRIMITIVE_BUNDLE_REPO_PATH = "src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacV4RuntimeFactoryBindingV1(_FrozenModel):
    """Reviewed identity of one complete formal V4 runtime assembly."""

    schema_version: Literal["FormalIsaacV4RuntimeFactoryBindingV1"] = (
        "FormalIsaacV4RuntimeFactoryBindingV1"
    )
    factory_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_isaac_runtime_factory_v4.py"
    ] = IMPLEMENTATION_REPO_PATH
    factory_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    episode_io_deployment_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    bound_plan_provider_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    primitive_bundle_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transitive_dependency_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    review_status: Literal["REVIEWED_BINDING_ADDENDUM"] = "REVIEWED_BINDING_ADDENDUM"
    formal_execution_eligible: Literal[True] = True
    invalid_action_policy: Literal["TERMINAL_NO_PHYSICAL_EXECUTION"] = (
        "TERMINAL_NO_PHYSICAL_EXECUTION"
    )
    b0_runtime_fallback_present: Literal[False] = False
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    scripted_decision_source: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    binding_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "FormalIsaacV4RuntimeFactoryBindingV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("formal V4 runtime-factory binding digest differs")
        return self


class FormalIsaacV4RuntimeAssemblyReceiptV1(_FrozenModel):
    """Non-executing receipt for one successfully composed runtime."""

    schema_version: Literal["FormalIsaacV4RuntimeAssemblyReceiptV1"] = (
        "FormalIsaacV4RuntimeAssemblyReceiptV1"
    )
    factory_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    episode_io_deployment_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    bound_plan_provider_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    primitive_bundle_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    association_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_registry_sha256: str = Field(pattern=SHA256_PATTERN)
    source_inventory_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_execution_performed: Literal[False] = False
    scene_started: Literal[False] = False
    model_inference_performed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "FormalIsaacV4RuntimeAssemblyReceiptV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal V4 runtime assembly receipt digest differs")
        return self


@dataclass(frozen=True)
class FormalIsaacV4RuntimeAssemblyV1:
    """The backend and its non-executing assembly receipt."""

    backend: FormalIsaacBackendCoordinatorV4
    receipt: FormalIsaacV4RuntimeAssemblyReceiptV1


def _sha256(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def _safe_repo_path(project_root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("formal V4 runtime source path escapes repository")
    cursor = project_root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("formal V4 runtime source path contains a symlink")
    path = cursor.resolve(strict=True)
    if not path.is_relative_to(project_root):
        raise ValueError("formal V4 runtime source resolves outside repository")
    return path


def _git_bytes(project_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    return completed.stdout


def _source_inventory(
    *,
    binding: FormalIsaacV4RuntimeFactoryBindingV1,
    endpoint: IsaacEndpointBindingV4,
    episode_io_binding: FormalIsaacEpisodeIODeploymentBindingV1,
) -> tuple[tuple[str, str], ...]:
    requested = (
        (binding.factory_implementation_path, binding.factory_implementation_sha256),
        (endpoint.implementation_path, endpoint.implementation_sha256),
        (endpoint.physical_backend_path, endpoint.physical_backend_sha256),
        (endpoint.public_observation_provider_path, endpoint.public_observation_provider_sha256),
        (endpoint.formal_exact_plan_runtime_path, endpoint.formal_exact_plan_runtime_sha256),
        (endpoint.bound_plan_provider_path, endpoint.bound_plan_provider_sha256),
        (endpoint.primitive_bundle_path, endpoint.primitive_bundle_sha256),
        (endpoint.runtime_registry_path, endpoint.runtime_registry_sha256),
        (
            episode_io_binding.lifecycle_implementation_path,
            episode_io_binding.lifecycle_implementation_sha256,
        ),
        (
            episode_io_binding.scene_owner_implementation_path,
            episode_io_binding.scene_owner_implementation_sha256,
        ),
        (
            episode_io_binding.capture_source_implementation_path,
            episode_io_binding.capture_source_implementation_sha256,
        ),
    )
    by_path: dict[str, str] = {}
    for path, digest in requested:
        previous = by_path.setdefault(path, digest)
        if previous != digest:
            raise ValueError("formal V4 runtime assigns two digests to one source path")
    return tuple(sorted(by_path.items()))


def _verify_immutable_source_inventory(
    project_root: Path,
    *,
    immutable_commit: str,
    inventory: tuple[tuple[str, str], ...],
) -> None:
    head = _git_bytes(project_root, "rev-parse", "HEAD").decode("ascii").strip()
    try:
        _git_bytes(
            project_root,
            "merge-base",
            "--is-ancestor",
            immutable_commit,
            head,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            "formal V4 runtime factory commit is not an ancestor of current HEAD"
        ) from exc
    for raw_path, expected_sha256 in inventory:
        path = _safe_repo_path(project_root, raw_path)
        current = read_regular_file_once(path)
        if hashlib.sha256(current).hexdigest() != expected_sha256:
            raise ValueError(f"formal V4 runtime source digest differs: {raw_path}")
        committed = _git_bytes(project_root, "show", f"{immutable_commit}:{raw_path}")
        if current != committed:
            raise ValueError(f"formal V4 runtime source differs from commit: {raw_path}")
    status = _git_bytes(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *(path for path, _ in inventory),
    )
    if status:
        raise ValueError("formal V4 runtime source inventory is dirty")


def _validate_contract_graph(
    *,
    binding: FormalIsaacV4RuntimeFactoryBindingV1,
    endpoint: IsaacEndpointBindingV4,
    episode_io_binding: FormalIsaacEpisodeIODeploymentBindingV1,
    association_deployment: PublicAssociationDeploymentBindingV2,
    declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
    provider_deployment: FormalBoundPlanProviderDeploymentV1,
    bundle_deployment: ExactPlanPrimitiveDeploymentBindingV1,
) -> None:
    expected = {
        "endpoint_binding_sha256": canonical_sha256(endpoint),
        "episode_io_deployment_binding_sha256": canonical_sha256(episode_io_binding),
        "bound_plan_provider_deployment_sha256": canonical_sha256(provider_deployment),
        "primitive_bundle_deployment_sha256": canonical_sha256(bundle_deployment),
        "immutable_commit": endpoint.immutable_commit,
        "container_image_digest": endpoint.container_image_digest,
        "transitive_dependency_manifest_sha256": (endpoint.transitive_dependency_manifest_sha256),
    }
    if any(getattr(binding, name) != value for name, value in expected.items()):
        raise ValueError("formal V4 runtime factory binding crosses deployment")
    if (
        endpoint.physical_backend_path != EPISODE_IO_REPO_PATH
        or endpoint.physical_backend_sha256 != episode_io_binding.lifecycle_implementation_sha256
        or episode_io_binding.lifecycle_implementation_path != EPISODE_IO_REPO_PATH
        or endpoint.public_observation_provider_path != OBSERVATION_PROVIDER_REPO_PATH
        or endpoint.formal_exact_plan_runtime_path != EXACT_RUNTIME_REPO_PATH
        or endpoint.bound_plan_provider_path != BOUND_PROVIDER_REPO_PATH
        or endpoint.primitive_bundle_path != PRIMITIVE_BUNDLE_REPO_PATH
    ):
        raise ValueError("formal V4 endpoint runtime source paths differ from V4 contracts")
    if (
        episode_io_binding.endpoint_binding_sha256 != canonical_sha256(endpoint)
        or episode_io_binding.association_deployment_sha256
        != association_deployment.deployment_binding_sha256
        or episode_io_binding.declared_attribute_binding_sha256
        != declared_attribute_binding.binding_sha256
        or episode_io_binding.public_observation_provider_sha256
        != endpoint.public_observation_provider_sha256
        or episode_io_binding.capture_source_implementation_sha256
        != endpoint.capture_source_implementation_sha256
        or episode_io_binding.immutable_commit != endpoint.immutable_commit
        or episode_io_binding.container_image_digest != endpoint.container_image_digest
        or episode_io_binding.transitive_dependency_manifest_sha256
        != endpoint.transitive_dependency_manifest_sha256
    ):
        raise ValueError("formal V4 episode I/O deployment crosses endpoint")
    if (
        association_deployment.capture_source_implementation_sha256
        != endpoint.capture_source_implementation_sha256
        or association_deployment.deployment_binding_sha256
        != endpoint.association_deployment_sha256
        or declared_attribute_binding.selector_source_implementation_sha256
        != endpoint.declared_attribute_selector_implementation_sha256
    ):
        raise ValueError("formal V4 public association deployment crosses endpoint")
    if (
        provider_deployment.provider_implementation_sha256 != endpoint.bound_plan_provider_sha256
        or provider_deployment.immutable_commit != endpoint.immutable_commit
        or provider_deployment.container_image_digest != endpoint.container_image_digest
        or bundle_deployment.immutable_commit != endpoint.immutable_commit
        or bundle_deployment.container_image_digest != endpoint.container_image_digest
        or provider_deployment.source_bindings != bundle_deployment.source_bindings
        or provider_deployment.phase_schema_by_skill != bundle_deployment.phase_schema_by_skill
        or provider_deployment.binding_addendum_sha256 != bundle_deployment.binding_addendum_sha256
        or provider_deployment.unlock_config_sha256 != bundle_deployment.unlock_config_sha256
        or provider_deployment.adr_0022_sha256 != bundle_deployment.adr_sha256
        or provider_deployment.adr_0024_sha256 != bundle_deployment.superseding_adr_sha256
    ):
        raise ValueError("formal V4 plan provider and primitive bundle cross deployment")
    role_hashes = {item.role: item.sha256 for item in bundle_deployment.source_bindings}
    if role_hashes["PRIMITIVE_ENTRYPOINT"] != endpoint.primitive_bundle_sha256:
        raise ValueError("formal V4 primitive entrypoint differs from endpoint binding")


class FormalIsaacV4RuntimeFactoryV1:
    """Compose exactly one reviewed V4 backend without starting its scene."""

    def __init__(
        self,
        *,
        project_root: Path,
        binding: FormalIsaacV4RuntimeFactoryBindingV1,
        endpoint_binding: IsaacEndpointBindingV4,
        episode_io: FormalIsaacEpisodeIOV4,
        observation_provider: ReplayableFormalPublicObservationProviderV4,
        association_deployment: PublicAssociationDeploymentBindingV2,
        declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
        bound_plan_provider: FormalBoundExactPlanProviderV1,
        bound_plan_provider_deployment: FormalBoundPlanProviderDeploymentV1,
        primitive_bundle: M2CExactPlanPrimitiveBundleV1 | PerDecisionExactPlanBundleRuntimeV1,
        primitive_bundle_deployment: ExactPlanPrimitiveDeploymentBindingV1,
        runtime_registry_sha256: str,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        project_root = project_root.resolve(strict=True)
        if not isinstance(episode_io, FormalIsaacEpisodeIOV4):
            raise TypeError("formal V4 runtime factory requires FormalIsaacEpisodeIOV4")
        if not isinstance(
            observation_provider,
            ReplayableFormalPublicObservationProviderV4,
        ):
            raise TypeError("formal V4 runtime factory requires replayable observations")
        if not isinstance(bound_plan_provider, FormalBoundExactPlanProviderV1):
            raise TypeError("formal V4 runtime factory requires the bound plan provider")
        if not isinstance(
            primitive_bundle,
            (M2CExactPlanPrimitiveBundleV1, PerDecisionExactPlanBundleRuntimeV1),
        ):
            raise TypeError("formal V4 runtime factory requires the exact primitive bundle")
        binding = FormalIsaacV4RuntimeFactoryBindingV1.model_validate(
            binding.model_dump(mode="json")
        )
        endpoint_binding = IsaacEndpointBindingV4.model_validate(
            endpoint_binding.model_dump(mode="json")
        )
        episode_io_binding = FormalIsaacEpisodeIODeploymentBindingV1.model_validate(
            episode_io.binding.model_dump(mode="json")
        )
        association_deployment = PublicAssociationDeploymentBindingV2.model_validate(
            association_deployment.model_dump(mode="json")
        )
        declared_attribute_binding = PublicDeclaredTargetAttributeBindingV4.model_validate(
            declared_attribute_binding.model_dump(mode="json")
        )
        provider_deployment = FormalBoundPlanProviderDeploymentV1.model_validate(
            bound_plan_provider_deployment.model_dump(mode="json")
        )
        bundle_deployment = ExactPlanPrimitiveDeploymentBindingV1.model_validate(
            primitive_bundle_deployment.model_dump(mode="json")
        )
        _validate_contract_graph(
            binding=binding,
            endpoint=endpoint_binding,
            episode_io_binding=episode_io_binding,
            association_deployment=association_deployment,
            declared_attribute_binding=declared_attribute_binding,
            provider_deployment=provider_deployment,
            bundle_deployment=bundle_deployment,
        )
        if _sha256(Path(__file__)) != binding.factory_implementation_sha256:
            raise ValueError("loaded formal V4 runtime factory bytes differ from binding")
        inventory = _source_inventory(
            binding=binding,
            endpoint=endpoint_binding,
            episode_io_binding=episode_io_binding,
        )
        _verify_immutable_source_inventory(
            project_root,
            immutable_commit=binding.immutable_commit,
            inventory=inventory,
        )
        if (
            episode_io.binding != episode_io_binding
            or observation_provider.source is not episode_io.capture_source
            or observation_provider.mode != "REAL_ISAAC"
            or observation_provider.deployment != association_deployment
            or observation_provider.attribute_binding != declared_attribute_binding
            or bound_plan_provider.project_root != project_root
            or bound_plan_provider.deployment != provider_deployment
            or not bound_plan_provider.formal_execution_eligible
            or bound_plan_provider.implementation_sha256
            != endpoint_binding.bound_plan_provider_sha256
            or primitive_bundle.project_root != project_root
            or primitive_bundle.binding != bundle_deployment
            or not primitive_bundle.formal_execution_eligible
            or runtime_registry_sha256 != endpoint_binding.runtime_registry_sha256
        ):
            raise ValueError("formal V4 runtime objects cross reviewed deployment")
        exact_runtime = FormalExactPlanRuntimeV1(
            provider=bound_plan_provider,
            bundle=primitive_bundle,
        )
        backend = FormalIsaacBackendCoordinatorV4(
            endpoint_binding=endpoint_binding,
            lifecycle=episode_io.lifecycle,
            observation_provider=observation_provider,
            observation_provider_implementation_sha256=(
                endpoint_binding.public_observation_provider_sha256
            ),
            exact_plan_runtime=exact_runtime,
            exact_plan_runtime_implementation_sha256=(
                endpoint_binding.formal_exact_plan_runtime_sha256
            ),
            runtime_registry_sha256=runtime_registry_sha256,
            now_ns=now_ns,
        )
        receipt_payload: dict[str, Any] = {
            "schema_version": "FormalIsaacV4RuntimeAssemblyReceiptV1",
            "factory_binding_sha256": binding.binding_sha256,
            "endpoint_binding_sha256": canonical_sha256(endpoint_binding),
            "episode_io_deployment_binding_sha256": canonical_sha256(episode_io_binding),
            "bound_plan_provider_deployment_sha256": canonical_sha256(provider_deployment),
            "primitive_bundle_deployment_sha256": canonical_sha256(bundle_deployment),
            "association_deployment_sha256": (association_deployment.deployment_binding_sha256),
            "declared_attribute_binding_sha256": declared_attribute_binding.binding_sha256,
            "runtime_registry_sha256": runtime_registry_sha256,
            "source_inventory_sha256": canonical_sha256(
                [{"path": path, "sha256": digest} for path, digest in inventory]
            ),
            "physical_execution_performed": False,
            "scene_started": False,
            "model_inference_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        self.binding = binding
        self.assembly = FormalIsaacV4RuntimeAssemblyV1(
            backend=backend,
            receipt=FormalIsaacV4RuntimeAssemblyReceiptV1(
                **receipt_payload,
                receipt_sha256=canonical_sha256(receipt_payload),
            ),
        )


def implementation_sha256_v4() -> str:
    """Return the factory byte identity for a future reviewed addendum."""

    return _sha256(Path(__file__))
