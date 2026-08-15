"""ADR-0024 Phase-2 readiness verifier for formal V4 evidence.

The historical V1 verifier intentionally retains the superseded SSH and
active-session B0 requirements.  This V2 consumer implements the accepted
ADR-0024 contract instead:

* one create-only wire-challenge consumption receipt;
* a finalized eight-decision formal V4 episode;
* canonical Qwen and Isaac service/session journals;
* two unsigned, host-local HMAC verification receipts;
* one immutable Git/container/transitive-import closure; and
* real-Isaac validation receipts for all eight registered skills.

The module is an evidence consumer only.  It cannot edit the entry gate or
apply a production binding.  Generated files, when evidence is complete, are
create-only proposals for a separate reviewed commit.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3BulletFloat64BuildManifestV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPreflightReceiptV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanA3DeploymentBindingV2,
)
from xh_agent.policy.qrm_lite.formal_split_host_v4 import M2CFormalSplitRunnerEvidenceV4
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_json_bytes,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_ISAAC_EXECUTE_PATH_V4,
    FORMAL_WIRE_PROTOCOL_V4,
    IsaacEndpointBindingV4,
    IsaacExecuteResponseV4,
    IsaacStartRequestV4,
)
from xh_agent.policy.qrm_lite.formal_isaac_episode_io_v4 import (
    FormalIsaacEpisodeIODeploymentBindingV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    WireChallengeConsumptionReceiptV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v4 import (
    HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH,
    HostWireHMACVerificationReceiptV4,
    _event_between,
    _first_wire_time,
    _formal_and_consumption,
    _isaac_paths,
    _parse_audit,
    _wire_events,
)
from xh_agent.policy.qrm_lite.s4_entry_gate import (
    FormalTransitiveImportClosureManifestV1,
)
from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationDeploymentBindingV2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    M2CQ012DeploymentManifestV4,
    PublicDeclaredTargetAttributeBindingV4,
)


SCHEMA_VERSION = "M2CADR0024BindingAddendumReadinessV2"
INDEX_SCHEMA = "M2CADR0024Phase2EvidenceIndexV2"
ADDENDUM_PATH = "docs/decisions/ADR-0024-PHASE2-BINDING-ADDENDUM.md"
UNLOCK_CONFIG_PATH = "configs/m2c_s4_unlock_bindings.json"
ADR_PATH = "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"

FORMAL_RUNNER_PATH = "scripts/m2c/run_formal_model_owned_chain_v4.py"
OFFLINE_VERIFIER_PATH = HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH
ENTRY_GATE_PATH = "src/xh_agent/policy/qrm_lite/s4_entry_gate.py"
ENTRY_V4_SCHEMA_MARKERS = (
    "M2CS4PhysicalIntegrationReceiptV3",
    "M2CFormalSplitRunnerEvidenceV4",
    "HostWireHMACVerificationReceiptV4",
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

REQUIRED_PROJECT_PATHS = frozenset(
    {
        ADR_PATH,
        "scripts/m2c/formal_isaac_v4_backend.py",
        "scripts/m2c/qwen_coarse_v4.py",
        FORMAL_RUNNER_PATH,
        "scripts/m2c/serve_formal_isaac_endpoint_v4.py",
        "scripts/m2c/serve_qwen_coarse_v4.py",
        "scripts/m2c/verify_formal_wire_auth_v4.py",
        "src/xh_agent/perception/public_track_associator_v2.py",
        "src/xh_agent/policy/qrm_lite/a3_bullet_production_adapter_v1.py",
        "src/xh_agent/policy/qrm_lite/a3_bullet_self_ccd_v1.cpp",
        "src/xh_agent/policy/qrm_lite/a3_bullet_self_ccd_v1.py",
        "src/xh_agent/policy/qrm_lite/exact_plan_preflight_v1.py",
        "src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py",
        "src/xh_agent/policy/qrm_lite/formal_bound_plan_provider_v1.py",
        "src/xh_agent/policy/qrm_lite/formal_exact_plan_runtime_v1.py",
        "src/xh_agent/policy/qrm_lite/formal_isaac_backend_v4.py",
        "src/xh_agent/policy/qrm_lite/formal_isaac_endpoint_v4.py",
        "src/xh_agent/policy/qrm_lite/formal_public_observation_provider_v4.py",
        "src/xh_agent/policy/qrm_lite/formal_public_observation_v4.py",
        "src/xh_agent/policy/qrm_lite/formal_split_host_v4.py",
        "src/xh_agent/policy/qrm_lite/formal_split_runner_v4.py",
        "src/xh_agent/policy/qrm_lite/isaac_exact_plan_runtime_v1.py",
        OFFLINE_VERIFIER_PATH,
        "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v4.py",
        "src/xh_agent/policy/qrm_lite/public_tracks_v4.py",
        "src/xh_agent/policy/qrm_lite/phase2_binding_readiness_v2.py",
        ENTRY_GATE_PATH,
    }
)

ARTIFACT_NAMES = frozenset(
    {
        "formal_evidence",
        "challenge_consumption_receipt",
        "qwen_service_audit",
        "isaac_service_audit",
        "isaac_session_audit",
        "node2_hmac_receipt",
        "labserver_hmac_receipt",
        "transitive_import_manifest",
        "deployment_asset_manifest",
        "exact_plan_eight_skill_evidence",
        "exact_plan_eight_skill_audit",
    }
)


class ReadinessFailure(RuntimeError):
    """A required immutable deployment or physical-evidence fact failed."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceFileBindingV2(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def contained_relative_path(self) -> "EvidenceFileBindingV2":
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("evidence binding must be a contained relative path")
        return self


class ProjectFileBindingV2(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def repository_relative_path(self) -> "ProjectFileBindingV2":
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("project binding must be repository-relative")
        return self


DeploymentAssetRoleV3 = Literal[
    "CONTAINER_IMAGE_INSPECT",
    "PYTHON_DEPENDENCY_INVENTORY",
    "QWEN_BUNDLE_MANIFEST",
    "QWEN_HEAD_CHECKPOINT",
    "QWEN_HEAD_DEPLOYMENT",
    "ISAAC_ENDPOINT_BINDING",
    "PUBLIC_ASSOCIATION_DEPLOYMENT_BINDING",
    "DECLARED_ATTRIBUTE_BINDING",
    "FORMAL_EPISODE_IO_DEPLOYMENT_BINDING",
    "EXACT_PLAN_SYNTHESIS_CONFIGURATION",
    "EXACT_PLAN_SYNTHESIS_DEPENDENCY_MANIFEST",
    "EXACT_PLAN_A3_DEPLOYMENT_BINDING",
    "EXACT_PLAN_PRIMITIVE_DEPLOYMENT_BINDING",
    "EXACT_PLAN_EXECUTOR_DEPLOYMENT_BINDING",
    "QUERY_ONLY_FK_DEPLOYMENT_BINDING",
    "CONTROLLED_ROBOT_URDF",
    "CONTROLLED_ROBOT_SRDF",
    "PANDA_LINK2_COLLISION_STL",
    "PANDA_LINK4_COLLISION_STL",
    "A3_NATIVE_BUILD_MANIFEST",
    "A3_NATIVE_SHARED_OBJECT",
    "BULLET_COLLISION_LIBRARY",
    "BULLET_LINEAR_MATH_LIBRARY",
    "SCENE_SDF",
    "SCENE_SUPERVISION",
    "SCENE_USD",
    "CAMERA_CALIBRATION",
    "RUNTIME_SKILL_REGISTRY",
    "FORMAL_CHALLENGE_MANIFEST",
    "QWEN_BUNDLE_FILE",
    "QWEN_ADAPTER_FILE",
    "QWEN_MODEL_CACHE_FILE",
    "ISAAC_DEPENDENCY_FILE",
]

DeploymentAssetTreeRoleV3 = Literal[
    "QWEN_BUNDLE_TREE",
    "QWEN_ADAPTER_TREE",
    "QWEN_MODEL_CACHE_TREE",
    "ISAAC_DEPENDENCY_TREE",
]

DEPLOYMENT_ASSET_SINGLETON_ROLES_V3 = frozenset(
    {
        "CONTAINER_IMAGE_INSPECT",
        "PYTHON_DEPENDENCY_INVENTORY",
        "QWEN_BUNDLE_MANIFEST",
        "QWEN_HEAD_CHECKPOINT",
        "QWEN_HEAD_DEPLOYMENT",
        "ISAAC_ENDPOINT_BINDING",
        "PUBLIC_ASSOCIATION_DEPLOYMENT_BINDING",
        "DECLARED_ATTRIBUTE_BINDING",
        "FORMAL_EPISODE_IO_DEPLOYMENT_BINDING",
        "EXACT_PLAN_SYNTHESIS_CONFIGURATION",
        "EXACT_PLAN_SYNTHESIS_DEPENDENCY_MANIFEST",
        "EXACT_PLAN_A3_DEPLOYMENT_BINDING",
        "EXACT_PLAN_PRIMITIVE_DEPLOYMENT_BINDING",
        "EXACT_PLAN_EXECUTOR_DEPLOYMENT_BINDING",
        "QUERY_ONLY_FK_DEPLOYMENT_BINDING",
        "CONTROLLED_ROBOT_URDF",
        "CONTROLLED_ROBOT_SRDF",
        "PANDA_LINK2_COLLISION_STL",
        "PANDA_LINK4_COLLISION_STL",
        "A3_NATIVE_BUILD_MANIFEST",
        "A3_NATIVE_SHARED_OBJECT",
        "BULLET_COLLISION_LIBRARY",
        "BULLET_LINEAR_MATH_LIBRARY",
        "SCENE_SDF",
        "SCENE_SUPERVISION",
        "SCENE_USD",
        "CAMERA_CALIBRATION",
        "RUNTIME_SKILL_REGISTRY",
        "FORMAL_CHALLENGE_MANIFEST",
    }
)

DEPLOYMENT_ASSET_TREE_CONTENT_ROLE_V3: dict[str, str] = {
    "QWEN_BUNDLE_TREE": "QWEN_BUNDLE_FILE",
    "QWEN_ADAPTER_TREE": "QWEN_ADAPTER_FILE",
    "QWEN_MODEL_CACHE_TREE": "QWEN_MODEL_CACHE_FILE",
    "ISAAC_DEPENDENCY_TREE": "ISAAC_DEPENDENCY_FILE",
}


def deployment_tree_sha256_v3(files: Mapping[str, str]) -> str:
    """Recompute the frozen path+content tree digest used by Qwen V4."""

    digest = hashlib.sha256()
    for path, sha256 in sorted(files.items()):
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("deployment tree inventory path is not relative")
        if re.fullmatch(SHA256_PATTERN, sha256) is None:
            raise ValueError("deployment tree inventory file digest is malformed")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256))
    return digest.hexdigest()


class DeploymentAssetBindingV3(StrictModel):
    deployment_path: str = Field(min_length=1)
    evidence_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    roles: tuple[DeploymentAssetRoleV3, ...] = Field(min_length=1)
    kind: Literal[
        "ROBOT_ASSET",
        "SCENE_ASSET",
        "ISAAC_RUNTIME",
        "NATIVE_RUNTIME",
        "MODEL_ASSET",
        "CONFIGURATION",
    ]

    @model_validator(mode="after")
    def paths_and_roles_are_exact(self) -> "DeploymentAssetBindingV3":
        deployment = PurePosixPath(self.deployment_path)
        if not deployment.is_absolute() or ".." in deployment.parts:
            raise ValueError("deployment asset path must be absolute and normalized")
        path = Path(self.evidence_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("deployment asset evidence path must be contained")
        if tuple(sorted(set(self.roles))) != self.roles:
            raise ValueError("deployment asset roles must be unique canonical order")
        return self


class DeploymentAssetTreeInventoryV3(StrictModel):
    schema_version: Literal["M2CDeploymentAssetTreeInventoryV3"] = (
        "M2CDeploymentAssetTreeInventoryV3"
    )
    tree_role: DeploymentAssetTreeRoleV3
    root_path: str = Field(min_length=1)
    files: dict[str, str] = Field(min_length=1)
    tree_sha256: str = Field(pattern=SHA256_PATTERN)
    complete_recursive_file_inventory: Literal[True] = True

    @model_validator(mode="after")
    def exact_tree(self) -> "DeploymentAssetTreeInventoryV3":
        root = PurePosixPath(self.root_path)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("deployment tree root must be absolute and normalized")
        if self.tree_sha256 != deployment_tree_sha256_v3(self.files):
            raise ValueError("deployment tree inventory digest differs")
        return self


class Phase2ContainerImageInspectV3(StrictModel):
    schema_version: Literal["M2CPhase2ContainerImageInspectV3"] = "M2CPhase2ContainerImageInspectV3"
    image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    repo_digests: tuple[str, ...] = Field(min_length=1)
    inspect_exit_code: Literal[0] = 0
    observed_before_endpoint_start: Literal[True] = True

    @model_validator(mode="after")
    def exact_image_identity(self) -> "Phase2ContainerImageInspectV3":
        if len(self.repo_digests) != len(set(self.repo_digests)) or any(
            "@sha256:" not in item for item in self.repo_digests
        ):
            raise ValueError("container image inspect repo digests differ")
        return self


class Phase2DeploymentAssetManifestV3(StrictModel):
    schema_version: Literal["M2CPhase2DeploymentAssetManifestV3"] = (
        "M2CPhase2DeploymentAssetManifestV3"
    )
    deployment_profile: Literal["M2C_FORMAL_V4_FULL_DEPLOYMENT_V1"] = (
        "M2C_FORMAL_V4_FULL_DEPLOYMENT_V1"
    )
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    bindings: tuple[DeploymentAssetBindingV3, ...] = Field(min_length=1)
    tree_inventories: tuple[DeploymentAssetTreeInventoryV3, ...] = Field(min_length=4)
    complete_runtime_and_asset_closure: Literal[True] = True
    content_addressed_immutable_snapshot: Literal[True] = True
    generated_inside_bound_container: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_profile_and_trees(self) -> "Phase2DeploymentAssetManifestV3":
        deployment_paths = tuple(item.deployment_path for item in self.bindings)
        evidence_paths = tuple(item.evidence_path for item in self.bindings)
        if len(deployment_paths) != len(set(deployment_paths)) or len(evidence_paths) != len(
            set(evidence_paths)
        ):
            raise ValueError("deployment asset manifest paths are duplicated")
        counts = {
            role: sum(role in binding.roles for binding in self.bindings)
            for role in DEPLOYMENT_ASSET_SINGLETON_ROLES_V3
        }
        if any(count != 1 for count in counts.values()):
            raise ValueError("deployment asset manifest lacks the exact singleton role set")
        if any(
            sum(role in DEPLOYMENT_ASSET_SINGLETON_ROLES_V3 for role in binding.roles) > 1
            for binding in self.bindings
        ):
            raise ValueError("one deployment asset cannot satisfy two singleton roles")
        inventories = {item.tree_role: item for item in self.tree_inventories}
        if len(inventories) != len(self.tree_inventories) or set(inventories) != set(
            DEPLOYMENT_ASSET_TREE_CONTENT_ROLE_V3
        ):
            raise ValueError("deployment asset manifest lacks the exact tree role set")
        for tree_role, content_role in DEPLOYMENT_ASSET_TREE_CONTENT_ROLE_V3.items():
            inventory = inventories[tree_role]
            root = PurePosixPath(inventory.root_path)
            actual: dict[str, str] = {}
            for binding in self.bindings:
                if content_role not in binding.roles:
                    continue
                deployment = PurePosixPath(binding.deployment_path)
                try:
                    relative = deployment.relative_to(root)
                except ValueError as error:
                    raise ValueError("deployment tree member escapes its exact root") from error
                relative_path = relative.as_posix()
                if relative_path in {"", "."} or relative_path in actual:
                    raise ValueError("deployment tree member path is duplicated or empty")
                actual[relative_path] = binding.sha256
            if actual != inventory.files:
                raise ValueError("deployment tree inventory differs from its asset bindings")
        return self


def _asset_binding_for_role_v3(
    manifest: Phase2DeploymentAssetManifestV3,
    role: str,
) -> DeploymentAssetBindingV3:
    matches = [binding for binding in manifest.bindings if role in binding.roles]
    if len(matches) != 1:
        raise ReadinessFailure(f"deployment asset role is not singleton: {role}")
    return matches[0]


def _verify_deployment_assets_against_formal_v3(
    *,
    manifest: Phase2DeploymentAssetManifestV3,
    payload_by_role: Mapping[str, bytes],
    formal: M2CFormalSplitRunnerEvidenceV4,
) -> None:
    """Bind the exact deployment snapshot back to the formal V4 episode."""

    bundle = formal.bundle
    singleton_sha = {
        role: _asset_binding_for_role_v3(manifest, role).sha256
        for role in DEPLOYMENT_ASSET_SINGLETON_ROLES_V3
    }
    if (
        singleton_sha["QWEN_BUNDLE_MANIFEST"] != bundle.bundle_manifest_file_sha256
        or singleton_sha["QWEN_HEAD_CHECKPOINT"] != bundle.head_checkpoint_sha256
        or singleton_sha["QWEN_HEAD_DEPLOYMENT"] != bundle.head_deployment_file_sha256
        or singleton_sha["SCENE_SDF"] != formal.sdf_sha256
        or singleton_sha["SCENE_SUPERVISION"] != formal.supervision_sha256
    ):
        raise ReadinessFailure("deployment asset singleton differs from formal V4 evidence")

    inventories = {item.tree_role: item for item in manifest.tree_inventories}
    if (
        inventories["QWEN_BUNDLE_TREE"].tree_sha256 != bundle.bundle_tree_sha256
        or inventories["QWEN_ADAPTER_TREE"].tree_sha256 != bundle.adapter_tree_sha256
        or inventories["QWEN_MODEL_CACHE_TREE"].tree_sha256 != bundle.model_cache_tree_sha256
        or inventories["QWEN_MODEL_CACHE_TREE"].root_path != bundle.model_cache_dir
    ):
        raise ReadinessFailure("Qwen deployment tree differs from formal V4 bundle")

    bundle_manifest_binding = _asset_binding_for_role_v3(
        manifest,
        "QWEN_BUNDLE_MANIFEST",
    )
    bundle_root = PurePosixPath(bundle_manifest_binding.deployment_path).parent
    if (
        inventories["QWEN_BUNDLE_TREE"].root_path != bundle_root.as_posix()
        or inventories["QWEN_ADAPTER_TREE"].root_path != (bundle_root / "adapter").as_posix()
        or PurePosixPath(
            _asset_binding_for_role_v3(manifest, "QWEN_HEAD_CHECKPOINT").deployment_path
        )
        != bundle_root / "qwen_coarse_v4_heads.npz"
        or PurePosixPath(
            _asset_binding_for_role_v3(manifest, "QWEN_HEAD_DEPLOYMENT").deployment_path
        )
        != bundle_root / "qwen_coarse_v4_checkpoint_deployment.json"
    ):
        raise ReadinessFailure("Qwen deployment paths differ from the frozen V4 layout")

    try:
        bundle_manifest = json.loads(payload_by_role["QWEN_BUNDLE_MANIFEST"])
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ReadinessFailure("Qwen bundle manifest deployment asset is invalid JSON") from error
    expected_bundle_fields: dict[str, object] = {
        "schema_version": bundle.bundle_manifest_schema_version,
        "architecture_revision": bundle.architecture_revision,
        "public_track_associator_revision": bundle.public_track_associator_revision,
        "public_track_candidate_revision": bundle.public_track_candidate_revision,
        "model_id": bundle.model_id,
        "model_revision": bundle.model_revision,
        "failure_context": bundle.failure_context,
        "base_model_snapshot_tree_sha256": bundle.model_cache_tree_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "head_deployment_file_sha256": bundle.head_deployment_file_sha256,
        "training_dataset_sha256": bundle.training_dataset_sha256,
        "s6_manifest_file_sha256": bundle.s6_manifest_file_sha256,
        "s6_manifest_sha256": bundle.s6_manifest_sha256,
        "bundle_sha256": bundle.bundle_sha256,
        "training_complete": True,
        "physical_evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    if bundle.training_contract_revision == "ADR0026_DECISION_LEVEL_PREFIX_0_6_V1":
        expected_bundle_fields.update(
            {
                "status": ("TRAINED_QWEN_LORA_M2C_Q012_V4_ADR0026_DECISION_LEVEL"),
                "training_contract_revision": bundle.training_contract_revision,
                "training_dataset_report_file_sha256": (bundle.training_dataset_report_file_sha256),
                "training_dataset_report_sha256": (bundle.training_dataset_report_sha256),
                "training_dataset_manifest_file_sha256": (bundle.training_manifest_file_sha256),
                "training_dataset_manifest_sha256": bundle.training_manifest_sha256,
                "source_training_manifests": [
                    item.model_dump(mode="json") for item in bundle.source_training_manifests
                ],
            }
        )
    else:
        expected_bundle_fields.update(
            {
                "status": "TRAINED_QWEN_LORA_M2C_Q012_V4",
                "training_manifest_file_sha256": bundle.training_manifest_file_sha256,
                "training_manifest_sha256": bundle.training_manifest_sha256,
            }
        )
    if (
        not isinstance(bundle_manifest, dict)
        or any(bundle_manifest.get(key) != value for key, value in expected_bundle_fields.items())
        or canonical_sha256(
            {key: value for key, value in bundle_manifest.items() if key != "bundle_sha256"}
        )
        != bundle.bundle_sha256
    ):
        raise ReadinessFailure("Qwen bundle manifest content differs from formal V4 bundle")

    try:
        head_deployment = M2CQ012DeploymentManifestV4.model_validate_json(
            payload_by_role["QWEN_HEAD_DEPLOYMENT"]
        )
        endpoint = IsaacEndpointBindingV4.model_validate_json(
            payload_by_role["ISAAC_ENDPOINT_BINDING"]
        )
        association = PublicAssociationDeploymentBindingV2.model_validate_json(
            payload_by_role["PUBLIC_ASSOCIATION_DEPLOYMENT_BINDING"]
        )
        attribute = PublicDeclaredTargetAttributeBindingV4.model_validate_json(
            payload_by_role["DECLARED_ATTRIBUTE_BINDING"]
        )
        episode_io = FormalIsaacEpisodeIODeploymentBindingV1.model_validate_json(
            payload_by_role["FORMAL_EPISODE_IO_DEPLOYMENT_BINDING"]
        )
        a3 = ExactPlanA3DeploymentBindingV2.model_validate_json(
            payload_by_role["EXACT_PLAN_A3_DEPLOYMENT_BINDING"]
        )
        native_build = A3BulletFloat64BuildManifestV1.model_validate_json(
            payload_by_role["A3_NATIVE_BUILD_MANIFEST"]
        )
        image_inspect = Phase2ContainerImageInspectV3.model_validate_json(
            payload_by_role["CONTAINER_IMAGE_INSPECT"]
        )
    except (KeyError, ValidationError) as error:
        raise ReadinessFailure("one deployment binding asset has invalid strict schema") from error
    endpoint_sha256 = canonical_sha256(endpoint)
    if (
        endpoint != formal.isaac_endpoint_binding
        or head_deployment.checkpoint_file_sha256 != bundle.head_checkpoint_sha256
        or head_deployment.checkpoint_binding_sha256 != bundle.checkpoint_binding_sha256
        or head_deployment.deployment_manifest_sha256 != bundle.head_deployment_manifest_sha256
        or bundle_manifest.get("head_deployment") != head_deployment.model_dump(mode="json")
        or association.deployment_binding_sha256 != bundle.association_deployment_sha256
        or association.deployment_binding_sha256 != endpoint.association_deployment_sha256
        or attribute.binding_sha256 != formal.declared_attribute_binding_sha256
        or episode_io.review_status != "REVIEWED_BINDING_ADDENDUM"
        or not episode_io.formal_execution_eligible
        or episode_io.immutable_commit != manifest.implementation_commit
        or episode_io.container_image_digest != manifest.container_image_digest
        or episode_io.endpoint_binding_sha256 != endpoint_sha256
        or episode_io.association_deployment_sha256 != association.deployment_binding_sha256
        or episode_io.declared_attribute_binding_sha256 != attribute.binding_sha256
        or a3.immutable_commit != manifest.implementation_commit
        or a3.container_image_digest != manifest.container_image_digest
        or a3.binding_sha256 != endpoint.a3_deployment_binding_sha256
        or image_inspect.image_id != manifest.container_image_digest
        or native_build.native_shared_object.sha256 != singleton_sha["A3_NATIVE_SHARED_OBJECT"]
        or native_build.bullet_collision_library.sha256 != singleton_sha["BULLET_COLLISION_LIBRARY"]
        or native_build.bullet_linear_math_library.sha256
        != singleton_sha["BULLET_LINEAR_MATH_LIBRARY"]
    ):
        raise ReadinessFailure("formal V4 deployment bindings cross one another")


class ExactPlanSkillPhysicalValidationV2(StrictModel):
    validation_index: int = Field(ge=0, le=7)
    canonical_skill: Literal[
        "GRASP",
        "LIFT",
        "MOVE",
        "PLACE",
        "RELEASE",
        "REOBSERVE",
        "REASSOCIATE_TARGET",
        "REGRASP",
    ]
    plan: M2CExactPlanPrimitivePlanV1
    preflight_receipt: ExactPlanPreflightReceiptV1
    execution_receipt: ExactPlanBundleExecutionReceiptV1
    committed_audit_record_sha256: str = Field(pattern=SHA256_PATTERN)


class ExactPlanEightSkillPhysicalEvidenceV2(StrictModel):
    schema_version: Literal["M2CExactPlanEightSkillPhysicalEvidenceV2"] = (
        "M2CExactPlanEightSkillPhysicalEvidenceV2"
    )
    status: Literal["COMPLETE_REAL_ISAAC_EIGHT_SKILL_VALIDATION"] = (
        "COMPLETE_REAL_ISAAC_EIGHT_SKILL_VALIDATION"
    )
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transitive_import_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    validation_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    validations: tuple[ExactPlanSkillPhysicalValidationV2, ...] = Field(
        min_length=8,
        max_length=8,
    )
    real_isaac: Literal[True] = True
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    contract_test_only: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_skill_coverage(self) -> "ExactPlanEightSkillPhysicalEvidenceV2":
        observed = tuple((item.validation_index, item.canonical_skill) for item in self.validations)
        if observed != tuple(enumerate(SKILLS)):
            raise ValueError("eight-skill evidence is not the exact registered skill order")
        return self


class Phase2EvidenceIndexV2(StrictModel):
    schema_version: Literal[INDEX_SCHEMA] = INDEX_SCHEMA
    status: Literal["COLLECTED_REAL_ADR0024_PHASE2_EVIDENCE"] = (
        "COLLECTED_REAL_ADR0024_PHASE2_EVIDENCE"
    )
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    project_bindings: tuple[ProjectFileBindingV2, ...] = Field(min_length=1)
    artifacts: dict[str, EvidenceFileBindingV2]
    source_bindings_independently_reviewed: Literal[True] = True
    container_digest_observed_on_labserver: Literal[True] = True
    no_binding_applied_by_collector: Literal[True] = True
    b0_runtime_wrapper_present: Literal[False] = False
    b0_runtime_fallback_invocation_allowed: Literal[False] = False
    invalid_or_rejected_action_policy: Literal["TERMINAL_NO_PHYSICAL_EXECUTION"] = (
        "TERMINAL_NO_PHYSICAL_EXECUTION"
    )
    training_executed: Literal[False] = False
    q_b_evaluation_executed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_source_and_artifact_sets(self) -> "Phase2EvidenceIndexV2":
        paths = tuple(binding.path for binding in self.project_bindings)
        if len(paths) != len(set(paths)) or frozenset(paths) != REQUIRED_PROJECT_PATHS:
            raise ValueError("Phase-2 V2 project binding set is not exact")
        if set(self.artifacts) != ARTIFACT_NAMES:
            raise ValueError("Phase-2 V2 artifact set is not exact")
        return self


class VerifiedPhase2EvidenceV2(StrictModel):
    schema_version: Literal["M2CVerifiedPhase2EvidenceV2"] = "M2CVerifiedPhase2EvidenceV2"
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transitive_import_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_runner_binding: tuple[str, str]
    formal_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    challenge_consumption_id: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    final_task_success: bool
    strict_pure_model_success: bool
    model_decision_count: Literal[8] = 8
    real_model_operation_count: Literal[8] = 8
    exact_plan_skills_verified: tuple[str, ...]
    host_hmac_roles_verified: tuple[Literal["NODE2_QWEN", "LABSERVER_ISAAC"], ...]
    formal_v4_finalized_eight_decisions: Literal[True] = True
    real_isaac_eight_skill_validation: Literal[True] = True
    b0_runtime_wrapper_binding: None = None
    offline_wire_authentication_verifier_binding: None = None
    binding_application_authorized: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_verified_sets(self) -> "VerifiedPhase2EvidenceV2":
        if self.exact_plan_skills_verified != SKILLS:
            raise ValueError("verified Phase-2 skill set differs")
        if self.host_hmac_roles_verified != ("NODE2_QWEN", "LABSERVER_ISAAC"):
            raise ValueError("verified Phase-2 host role set differs")
        if (
            self.formal_runner_binding[0] != FORMAL_RUNNER_PATH
            or re.fullmatch(
                SHA256_PATTERN,
                self.formal_runner_binding[1],
            )
            is None
        ):
            raise ValueError("verified formal runner binding differs")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessFailure(f"input is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda item: (  # noqa: E731
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise ReadinessFailure(f"input changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessFailure(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise ReadinessFailure(f"{label} is not one JSON object")
    return value


def _git_file(project: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=project,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise ReadinessFailure(f"immutable commit lacks required file: {path}")
    return completed.stdout


def _require_ancestor_commit(project: Path, commit: str) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=project,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise ReadinessFailure("implementation commit is not an ancestor of HEAD")


def _verify_project_file(project: Path, commit: str, path: str, digest: str) -> bytes:
    committed = _git_file(project, commit, path)
    if sha256_bytes(committed) != digest:
        raise ReadinessFailure(f"committed project binding differs: {path}")
    current = read_regular_file_once(project / path)
    if current != committed:
        raise ReadinessFailure(f"worktree project binding differs from commit: {path}")
    return current


def _resolve_contained(root: Path, relative: str) -> Path:
    unresolved = root / relative
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as error:
        raise ReadinessFailure(f"evidence file is absent: {relative}") from error
    if unresolved.is_symlink() or not resolved.is_relative_to(root.resolve()):
        raise ReadinessFailure(f"evidence file escapes its root: {relative}")
    return unresolved


def _read_bound_artifacts(
    root: Path,
    bindings: Mapping[str, EvidenceFileBindingV2],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    identities: set[tuple[int, int]] = set()
    for role, binding in bindings.items():
        path = _resolve_contained(root, binding.path)
        metadata = path.stat(follow_symlinks=False)
        identity = (metadata.st_dev, metadata.st_ino)
        if identity in identities:
            raise ReadinessFailure("two Phase-2 evidence roles alias one inode")
        identities.add(identity)
        payload = read_regular_file_once(path)
        if sha256_bytes(payload) != binding.sha256:
            raise ReadinessFailure(f"Phase-2 evidence SHA-256 differs: {role}")
        payloads[role] = payload
    return payloads


def _read_exact_validation_audit(data: bytes) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise ReadinessFailure("eight-skill audit is not newline-terminated")
    lines = data.splitlines()
    try:
        records = [json.loads(line) for line in lines]
    except json.JSONDecodeError as error:
        raise ReadinessFailure("eight-skill audit is not JSONL") from error
    previous_time = 0
    for index, (record, line) in enumerate(zip(records, lines), start=1):
        recorded_at_ns = record.get("recorded_at_ns") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record)
            != {"schema_version", "sequence", "recorded_at_ns", "event_type", "payload"}
            or record.get("schema_version") != "M2CExactPlanSkillValidationAuditEventV2"
            or record.get("sequence") != index
            or not isinstance(recorded_at_ns, int)
            or recorded_at_ns <= previous_time
            or record.get("event_type") != "EXACT_PLAN_SKILL_VALIDATION_COMMITTED_V2"
            or not isinstance(record.get("payload"), dict)
            or canonical_json_bytes(record) != line
        ):
            raise ReadinessFailure("eight-skill audit is not canonical/contiguous")
        previous_time = recorded_at_ns
    if len(records) != 8:
        raise ReadinessFailure("eight-skill audit does not contain exactly eight commits")
    return records


def _verify_exact_plan_evidence_v2(
    evidence: ExactPlanEightSkillPhysicalEvidenceV2,
    *,
    index: Phase2EvidenceIndexV2,
    available_deployment_bindings: Mapping[str, str],
    transitive_import_manifest_sha256: str,
    audit_bytes: bytes,
    audit_binding_sha256: str,
) -> None:
    if (
        evidence.implementation_commit != index.implementation_commit
        or evidence.container_image_digest != index.container_image_digest
        or evidence.transitive_import_manifest_sha256
        != index.artifacts["transitive_import_manifest"].sha256
        or evidence.validation_audit_sha256 != audit_binding_sha256
    ):
        raise ReadinessFailure("eight-skill evidence differs from immutable deployment")
    records = _read_exact_validation_audit(audit_bytes)
    for validation, record in zip(evidence.validations, records, strict=True):
        plan = validation.plan
        preflight = validation.preflight_receipt
        execution = validation.execution_receipt
        if (
            plan.inputs.run_id != evidence.run_id
            or plan.inputs.session_id != evidence.session_id
            or plan.inputs.decision_index != validation.validation_index
            or plan.inputs.canonical_skill != validation.canonical_skill
            or plan.exact_execution_plan.canonical_skill != validation.canonical_skill
            or plan.inputs.immutable_commit != index.implementation_commit
            or plan.inputs.container_image_digest != index.container_image_digest
        ):
            raise ReadinessFailure("eight-skill plan identity differs")
        source_by_role = {item.role: item.sha256 for item in plan.source_bindings}
        for source in plan.source_bindings:
            if source.role == "TRANSITIVE_DEPENDENCY_MANIFEST":
                matched = source.sha256 == transitive_import_manifest_sha256
            else:
                matched = available_deployment_bindings.get(source.path) == source.sha256
            if not matched:
                raise ReadinessFailure(
                    "eight-skill plan source is absent from import/asset closure"
                )
        required_gate_bindings = {
            "IK_ALGORITHM": "ik_algorithm_sha256",
            "JOINT_LIMIT_CONFIGURATION": "limits_configuration_sha256",
            "SWEPT_COLLISION_ALGORITHM": "swept_collision_algorithm_sha256",
            "CONTROLLER_CONFIGURATION": "controller_configuration_sha256",
            "SAFETY_CONFIGURATION": "safety_configuration_sha256",
        }
        if any(
            any(
                getattr(result, field) != source_by_role[role]
                for role, field in required_gate_bindings.items()
            )
            for result in preflight.phase_results
        ):
            raise ReadinessFailure("eight-skill preflight source bindings differ")
        phases = plan.phases
        if (
            preflight.bound_plan_sha256 != plan.bound_plan_sha256
            or len(preflight.phase_results) != len(phases)
            or tuple(item.phase_index for item in preflight.phase_results)
            != tuple(range(len(phases)))
            or any(
                result.phase_sha256 != phase.phase_sha256
                or result.preplan_state_sha256 != plan.inputs.preplan_state_sha256
                for result, phase in zip(preflight.phase_results, phases, strict=True)
            )
        ):
            raise ReadinessFailure("eight-skill preflight does not cover the immutable plan")
        if (
            execution.bound_plan_sha256 != plan.bound_plan_sha256
            or execution.preflight_receipt_sha256 != preflight.receipt_sha256
            or execution.status != "PASS"
            or not execution.real_isaac
            or not execution.formal_evidence
            or len(execution.phase_receipts) != len(phases)
            or any(
                receipt.bound_plan_sha256 != plan.bound_plan_sha256
                or receipt.phase_index != phase.phase.phase_index
                or receipt.phase_sha256 != phase.phase_sha256
                or receipt.status != "PASS"
                or not receipt.operation_executed
                or not receipt.real_isaac
                or receipt.contract_test_only
                for receipt, phase in zip(execution.phase_receipts, phases, strict=True)
            )
        ):
            raise ReadinessFailure("eight-skill bundle receipt is not a complete real-Isaac PASS")
        expected_payload = {
            "run_id": evidence.run_id,
            "session_id": evidence.session_id,
            "validation_index": validation.validation_index,
            "canonical_skill": validation.canonical_skill,
            "bound_plan_sha256": plan.bound_plan_sha256,
            "preflight_receipt_sha256": preflight.receipt_sha256,
            "execution_receipt_sha256": canonical_sha256(execution),
            "phase_count": len(phases),
            "real_isaac": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        if (
            sha256_bytes(canonical_json_bytes(record)) != validation.committed_audit_record_sha256
            or record["payload"] != expected_payload
        ):
            raise ReadinessFailure("eight-skill audit record differs from physical receipt")


def _verify_qwen_structure(
    formal: M2CFormalSplitRunnerEvidenceV4,
    consumption: WireChallengeConsumptionReceiptV1,
    audit_bytes: bytes,
) -> str:
    records = _parse_audit(
        audit_bytes,
        schema="FormalQwenAuditEventV4",
        label="Phase-2 Qwen service audit",
        require_sequence_one=True,
    )
    if consumption.consumed_at_ns >= _first_wire_time(records):
        raise ReadinessFailure("challenge was not consumed before Qwen contact")
    requests, responses, transcript = _wire_events(
        records,
        expected_paths=[FORMAL_INFERENCE_PATH_V4] * 8,
    )
    if requests != [
        cycle.inference_request.model_dump(mode="json") for cycle in formal.wire_cycles
    ] or responses != [
        cycle.inference_response.model_dump(mode="json") for cycle in formal.wire_cycles
    ]:
        raise ReadinessFailure("Qwen service audit differs from formal V4 evidence")
    expected_types = [
        "SERVICE_STARTED",
        *[
            event
            for _ in range(8)
            for event in ("WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED")
        ],
        "SERVICE_COMPLETED",
        "SERVICE_STOPPED",
    ]
    if [item["event_type"] for item in records] != expected_types:
        raise ReadinessFailure("Qwen service lifecycle is not the exact finalized lifecycle")
    start = records[0]["payload"]
    service_id = start.get("service_id")
    if (
        not isinstance(service_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", service_id) is None
        or start
        != {
            "service_id": service_id,
            "path": FORMAL_INFERENCE_PATH_V4,
            "protocol": FORMAL_WIRE_PROTOCOL_V4,
            "architecture_revision": "M2C_Q012_V4",
            "expected_decisions": 8,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        or records[-2]["payload"]
        != {
            "service_id": service_id,
            "run_id": formal.run_id,
            "protocol": FORMAL_WIRE_PROTOCOL_V4,
            "responses_committed": 8,
            "formal_evidence_complete": True,
        }
        or records[-1]["payload"]
        != {
            "service_id": service_id,
            "run_id": formal.run_id,
            "protocol": FORMAL_WIRE_PROTOCOL_V4,
            "responses_committed": 8,
            "completed": True,
            "poisoned": False,
            "rejections_recorded": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
    ):
        raise ReadinessFailure("Qwen service start/completion/stop payload differs")
    return canonical_sha256(transcript)


def _verify_isaac_structure(
    formal: M2CFormalSplitRunnerEvidenceV4,
    consumption: WireChallengeConsumptionReceiptV1,
    service_bytes: bytes,
    session_bytes: bytes,
) -> str:
    service = _parse_audit(
        service_bytes,
        schema="FormalIsaacAuditEventV2",
        label="Phase-2 Isaac service audit",
        require_sequence_one=True,
    )
    session = _parse_audit(
        session_bytes,
        schema="FormalIsaacAuditEventV2",
        label="Phase-2 Isaac session audit",
        require_sequence_one=False,
    )
    if consumption.consumed_at_ns >= _first_wire_time(service):
        raise ReadinessFailure("challenge was not consumed before Isaac contact")
    offset = next((index for index, item in enumerate(service) if item == session[0]), None)
    if offset is None or service[offset:] != session:
        raise ReadinessFailure("Isaac session audit is not the exact service suffix")
    if session[0]["event_type"] != "SESSION_AUDIT_CREATED":
        raise ReadinessFailure("Isaac session audit does not begin at creation")
    requests, responses, transcript = _wire_events(
        service,
        expected_paths=_isaac_paths(formal),
    )
    expected_requests = [formal.start_request.model_dump(mode="json")]
    expected_responses = [formal.start_response.model_dump(mode="json")]
    for cycle in formal.wire_cycles:
        expected_requests.extend(
            [
                cycle.capture_request.model_dump(mode="json"),
                cycle.execute_request.model_dump(mode="json"),
            ]
        )
        expected_responses.extend(
            [
                cycle.capture_response.model_dump(mode="json"),
                cycle.execute_response.model_dump(mode="json"),
            ]
        )
    assert formal.finalize_request is not None and formal.finalize_response is not None
    expected_requests.append(formal.finalize_request.model_dump(mode="json"))
    expected_responses.append(formal.finalize_response.model_dump(mode="json"))
    if requests != expected_requests or responses != expected_responses:
        raise ReadinessFailure("Isaac service audit differs from formal V4 evidence")
    if (
        service[0]["event_type"] != "SERVICE_STARTED"
        or service[0]["payload"]
        != {
            "service_id": service[0]["payload"].get("service_id"),
            "formal_evidence": False,
            "physical_execution_performed": False,
        }
        or service[-1]["event_type"] != "SERVICE_STOPPED"
        or service[-1]["payload"] != {"clean_shutdown": True}
    ):
        raise ReadinessFailure("Isaac service is not cleanly started/stopped")
    service_id = service[0]["payload"]["service_id"]
    if not isinstance(service_id, str) or re.fullmatch(r"[0-9a-f]{32}", service_id) is None:
        raise ReadinessFailure("Isaac service ID is malformed")
    ready = [item for item in service if item["event_type"] == "HTTP_SERVER_READY_V4"]
    if (
        len(ready) != 1
        or ready[0]["sequence"] >= _first_wire_time_sequence(service)
        or ready[0]["payload"].get("formal_execution_started") is not False
    ):
        raise ReadinessFailure("Isaac HTTP service was not ready before contact")
    allowed = {
        "SERVICE_STARTED",
        "HTTP_SERVER_READY_V4",
        "WIRE_REQUEST_RECEIVED",
        "SESSION_AUDIT_CREATED",
        "ISAAC_V4_START_ACCEPTED_FOR_BACKEND",
        "WIRE_RESPONSE_COMMITTED",
        "EXACT_EXECUTION_PLAN_EXECUTED_V4",
        "ISAAC_V4_TERMINAL_FAILURE_COMMITTED",
        "HTTP_ACCESS",
        "SERVICE_STOPPED",
    }
    if any(item["event_type"] not in allowed for item in service):
        raise ReadinessFailure("Isaac service audit contains an unknown lifecycle event")
    wire = [
        item
        for item in service
        if item["event_type"] in {"WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED"}
    ]
    start_request = IsaacStartRequestV4.model_validate(formal.start_request.payload)
    session_created = _event_between(
        service,
        event_type="SESSION_AUDIT_CREATED",
        after_sequence=wire[0]["sequence"],
        before_sequence=wire[1]["sequence"],
    )
    session_identity = canonical_sha256(
        {
            "request_sha256": canonical_sha256(start_request),
            "run_id": formal.run_id,
            "service_id": service_id,
        }
    )
    session_path = session_created["payload"].get("session_audit_path")
    if (
        session_created["payload"]
        != {
            "request_sha256": canonical_sha256(start_request),
            "run_id": formal.run_id,
            "session_audit_path": session_path,
        }
        or not isinstance(session_path, str)
        or Path(session_path).name != f"session-{session_identity}.jsonl"
    ):
        raise ReadinessFailure("Isaac session creation identity differs")
    accepted = _event_between(
        service,
        event_type="ISAAC_V4_START_ACCEPTED_FOR_BACKEND",
        after_sequence=wire[0]["sequence"],
        before_sequence=wire[1]["sequence"],
    )
    if accepted["payload"] != {"request": start_request.model_dump(mode="json")}:
        raise ReadinessFailure("Isaac backend start acceptance differs")
    execute_responses = [
        IsaacExecuteResponseV4.model_validate(cycle.execute_response.payload)
        for cycle in formal.wire_cycles
    ]
    if any(response.disposition != "CONTINUE" for response in execute_responses):
        raise ReadinessFailure("finalized Phase-2 smoke contains a terminal execute response")
    execute_request_indices = [
        index
        for index, item in enumerate(wire)
        if item["event_type"] == "WIRE_REQUEST_RECEIVED"
        and item["payload"].get("path") == FORMAL_ISAAC_EXECUTE_PATH_V4
    ]
    for response, wire_index in zip(execute_responses, execute_request_indices, strict=True):
        lifecycle = _event_between(
            service,
            event_type="EXACT_EXECUTION_PLAN_EXECUTED_V4",
            after_sequence=wire[wire_index]["sequence"],
            before_sequence=wire[wire_index + 1]["sequence"],
        )
        receipt = response.execution_receipts[0]
        if lifecycle["payload"] != {
            "decision_index": response.decision_index,
            "bound_plan_sha256": response.bound_plan_sha256,
            "preflight_receipt_sha256": response.preflight_receipt_sha256,
            "bundle_execution_receipt_sha256": response.bundle_execution_receipt_sha256,
            "operation_kind": receipt.operation_kind,
        }:
            raise ReadinessFailure("Isaac exact-plan lifecycle payload differs")
    if sum(item["event_type"] == "EXACT_EXECUTION_PLAN_EXECUTED_V4" for item in service) != 8:
        raise ReadinessFailure("Isaac service does not contain eight exact-plan lifecycle events")
    return canonical_sha256(transcript)


def _first_wire_time_sequence(records: list[dict[str, Any]]) -> int:
    return next(
        item["sequence"] for item in records if item["event_type"] == "WIRE_REQUEST_RECEIVED"
    )


def _verify_host_receipts(
    *,
    formal: M2CFormalSplitRunnerEvidenceV4,
    index: Phase2EvidenceIndexV2,
    payloads: Mapping[str, bytes],
    verifier_sha256: str,
    qwen_envelope_sha256: str,
    isaac_envelope_sha256: str,
) -> None:
    receipts = {
        "NODE2_QWEN": HostWireHMACVerificationReceiptV4.model_validate_json(
            payloads["node2_hmac_receipt"]
        ),
        "LABSERVER_ISAAC": HostWireHMACVerificationReceiptV4.model_validate_json(
            payloads["labserver_hmac_receipt"]
        ),
    }
    formal_sha256 = index.artifacts["formal_evidence"].sha256
    for role, receipt in receipts.items():
        core = receipt.core
        expected_service = (
            index.artifacts["qwen_service_audit"].sha256
            if role == "NODE2_QWEN"
            else index.artifacts["isaac_service_audit"].sha256
        )
        expected_session = (
            None if role == "NODE2_QWEN" else index.artifacts["isaac_session_audit"].sha256
        )
        expected_envelopes = qwen_envelope_sha256 if role == "NODE2_QWEN" else isaac_envelope_sha256
        if (
            core.host_role != role
            or core.run_id != formal.run_id
            or core.challenge_nonce != formal.challenge_nonce
            or core.challenge_consumption_id != formal.challenge_consumption_id
            or core.challenge_consumption_receipt_sha256
            != formal.challenge_consumption_receipt_sha256
            or core.formal_evidence_sha256 != formal_sha256
            or core.formal_wire_transcript_sha256 != formal.wire_transcript_sha256
            or core.service_audit_sha256 != expected_service
            or core.session_audit_sha256 != expected_session
            or core.envelope_set_sha256 != expected_envelopes
            or core.completion_kind != "FINALIZED"
            or core.decision_count != 8
            or core.verifier_implementation_path != OFFLINE_VERIFIER_PATH
            or core.verifier_implementation_sha256 != verifier_sha256
        ):
            raise ReadinessFailure(f"{role} host-local HMAC receipt differs")


def verify_phase2_evidence(
    project: Path,
    evidence_index_path: Path,
    *,
    expected_index_sha256: str | None = None,
) -> tuple[Phase2EvidenceIndexV2, VerifiedPhase2EvidenceV2]:
    project = project.resolve()
    if evidence_index_path.is_symlink():
        raise ReadinessFailure("Phase-2 evidence index may not be a symlink")
    index_path = evidence_index_path.resolve(strict=True)
    index_bytes = read_regular_file_once(index_path)
    if expected_index_sha256 is not None and sha256_bytes(index_bytes) != expected_index_sha256:
        raise ReadinessFailure("Phase-2 evidence index SHA-256 differs from its entry receipt")
    index = Phase2EvidenceIndexV2.model_validate(
        _json_object(index_bytes, label="Phase-2 V2 evidence index")
    )
    _require_ancestor_commit(project, index.implementation_commit)
    project_by_path = {binding.path: binding for binding in index.project_bindings}
    project_payloads: dict[str, bytes] = {}
    for binding in index.project_bindings:
        project_payloads[binding.path] = _verify_project_file(
            project,
            index.implementation_commit,
            binding.path,
            binding.sha256,
        )
    entry_source = project_payloads[ENTRY_GATE_PATH].decode("utf-8")
    if any(marker not in entry_source for marker in ENTRY_V4_SCHEMA_MARKERS):
        raise ReadinessFailure("S4 entry gate does not replay the formal V4 evidence schema")
    payloads = _read_bound_artifacts(index_path.parent, index.artifacts)
    closure = FormalTransitiveImportClosureManifestV1.model_validate_json(
        payloads["transitive_import_manifest"]
    )
    if (
        closure.implementation_commit != index.implementation_commit
        or closure.container_image_digest != index.container_image_digest
        or any(
            closure.files.get(path) != binding.sha256 for path, binding in project_by_path.items()
        )
    ):
        raise ReadinessFailure("transitive closure lacks an exact Phase-2 project binding")
    for path, digest in closure.files.items():
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReadinessFailure("transitive closure contains a non-repository path")
        if sha256_bytes(_git_file(project, index.implementation_commit, path)) != digest:
            raise ReadinessFailure(f"transitive closure differs from immutable commit: {path}")
    asset_manifest = Phase2DeploymentAssetManifestV3.model_validate_json(
        payloads["deployment_asset_manifest"]
    )
    if (
        asset_manifest.implementation_commit != index.implementation_commit
        or asset_manifest.container_image_digest != index.container_image_digest
    ):
        raise ReadinessFailure("deployment asset manifest differs from immutable deployment")
    asset_bindings: dict[str, str] = {}
    asset_payload_by_role: dict[str, bytes] = {}
    artifact_identities: set[tuple[int, int]] = set()
    for artifact in index.artifacts.values():
        artifact_path = _resolve_contained(index_path.parent, artifact.path)
        metadata = artifact_path.stat(follow_symlinks=False)
        artifact_identities.add((metadata.st_dev, metadata.st_ino))
    asset_identities: set[tuple[int, int]] = set()
    for binding in asset_manifest.bindings:
        path = _resolve_contained(index_path.parent, binding.evidence_path)
        metadata = path.stat(follow_symlinks=False)
        identity = (metadata.st_dev, metadata.st_ino)
        if identity in asset_identities or identity in artifact_identities:
            raise ReadinessFailure("two evidence roles/deployment assets alias one inode")
        asset_identities.add(identity)
        asset_payload = read_regular_file_once(path)
        if sha256_bytes(asset_payload) != binding.sha256:
            raise ReadinessFailure(f"deployment asset SHA-256 differs: {binding.deployment_path}")
        asset_bindings[binding.deployment_path] = binding.sha256
        for role in binding.roles:
            if role in DEPLOYMENT_ASSET_SINGLETON_ROLES_V3:
                asset_payload_by_role[role] = asset_payload
    overlapping = set(closure.files).intersection(asset_bindings)
    if any(closure.files[path] != asset_bindings[path] for path in overlapping):
        raise ReadinessFailure("import and asset closures disagree on one deployment path")
    available_deployment_bindings = {**closure.files, **asset_bindings}
    formal, consumption = _formal_and_consumption(
        payloads["formal_evidence"],
        payloads["challenge_consumption_receipt"],
    )
    _verify_deployment_assets_against_formal_v3(
        manifest=asset_manifest,
        payload_by_role=asset_payload_by_role,
        formal=formal,
    )
    if (
        formal.completion_kind != "FINALIZED"
        or len(formal.wire_cycles) != 8
        or formal.model_decision_count != 8
        or formal.real_model_operation_count != 8
        or formal.collision_or_safety_violation
        or formal.b0_runtime_fallback_present
        or any(
            IsaacExecuteResponseV4.model_validate(cycle.execute_response.payload).disposition
            != "CONTINUE"
            for cycle in formal.wire_cycles
        )
    ):
        raise ReadinessFailure("formal V4 evidence is not a clean finalized eight-operation run")
    if (
        sha256_bytes(payloads["formal_evidence"]) != index.artifacts["formal_evidence"].sha256
        or sha256_bytes(payloads["challenge_consumption_receipt"])
        != formal.challenge_consumption_receipt_sha256
    ):
        raise ReadinessFailure("formal V4 evidence or consumption file SHA-256 differs")
    qwen_digest = _verify_qwen_structure(
        formal,
        consumption,
        payloads["qwen_service_audit"],
    )
    isaac_digest = _verify_isaac_structure(
        formal,
        consumption,
        payloads["isaac_service_audit"],
        payloads["isaac_session_audit"],
    )
    _verify_host_receipts(
        formal=formal,
        index=index,
        payloads=payloads,
        verifier_sha256=project_by_path[OFFLINE_VERIFIER_PATH].sha256,
        qwen_envelope_sha256=qwen_digest,
        isaac_envelope_sha256=isaac_digest,
    )
    exact = ExactPlanEightSkillPhysicalEvidenceV2.model_validate_json(
        payloads["exact_plan_eight_skill_evidence"]
    )
    _verify_exact_plan_evidence_v2(
        exact,
        index=index,
        available_deployment_bindings=available_deployment_bindings,
        transitive_import_manifest_sha256=index.artifacts["transitive_import_manifest"].sha256,
        audit_bytes=payloads["exact_plan_eight_skill_audit"],
        audit_binding_sha256=index.artifacts["exact_plan_eight_skill_audit"].sha256,
    )
    verified = VerifiedPhase2EvidenceV2(
        implementation_commit=index.implementation_commit,
        container_image_digest=index.container_image_digest,
        transitive_import_manifest_sha256=index.artifacts["transitive_import_manifest"].sha256,
        formal_runner_binding=(
            FORMAL_RUNNER_PATH,
            project_by_path[FORMAL_RUNNER_PATH].sha256,
        ),
        formal_evidence_sha256=index.artifacts["formal_evidence"].sha256,
        challenge_consumption_receipt_sha256=index.artifacts[
            "challenge_consumption_receipt"
        ].sha256,
        run_id=formal.run_id,
        challenge_nonce=formal.challenge_nonce,
        challenge_consumption_id=formal.challenge_consumption_id,
        matched_key=formal.matched_key,
        scene_seed=formal.scene_seed,
        failure_seed=formal.failure_seed,
        sdf_sha256=formal.sdf_sha256,
        supervision_sha256=formal.supervision_sha256,
        final_task_success=formal.final_task_success,
        strict_pure_model_success=formal.strict_pure_model_success,
        exact_plan_skills_verified=SKILLS,
        host_hmac_roles_verified=("NODE2_QWEN", "LABSERVER_ISAAC"),
    )
    return index, verified


def build_readiness_report(
    project: Path,
    evidence_index_path: Path | None,
) -> tuple[dict[str, Any], VerifiedPhase2EvidenceV2 | None]:
    blockers: list[str] = []
    verified: VerifiedPhase2EvidenceV2 | None = None
    if evidence_index_path is None:
        blockers.extend(
            [
                "PHASE2_EVIDENCE_INDEX_MISSING",
                "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
                "REAL_BOUND_PLAN_SYNTHESIS_BACKEND_NOT_BOUND",
                "REAL_ISAAC_EPISODE_LIFECYCLE_AND_CAPTURE_SOURCE_NOT_BOUND",
                "REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND",
                "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
                "REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING",
                "REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING",
                "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
            ]
        )
    else:
        try:
            _, verified = verify_phase2_evidence(project, evidence_index_path)
        except (
            OSError,
            subprocess.SubprocessError,
            ValidationError,
            ValueError,
            ReadinessFailure,
        ) as error:
            blockers.append(f"PHASE2_EVIDENCE_FAILED_CLOSED:{type(error).__name__}:{error}")
    ready = not blockers and verified is not None
    return (
        {
            "schema_version": SCHEMA_VERSION,
            "status": "READY_FOR_BINDING_ADDENDUM_GENERATION" if ready else "BLOCKED",
            "ready": ready,
            "binding_addendum_generation_authorized": ready,
            "source_binding_application_authorized": False,
            "evidence_index_path": str(evidence_index_path) if evidence_index_path else None,
            "verified": verified.model_dump(mode="json") if verified else None,
            "blockers": blockers,
            "required_trust_root_paths": [],
            "required_real_evidence": [
                "eight real-Isaac exact-plan/preflight/phase/bundle skill validations",
                "one finalized eight-decision formal V4 run and create-only challenge receipt",
                "canonical Qwen/Isaac service and exact Isaac session-suffix journals",
                "node2 and labserver host-local HMAC verification receipts",
                "immutable Git commit, image digest, transitive import and asset closure",
            ],
            "governance": {
                "two_active_source_bindings_changed": False,
                "withdrawn_compatibility_bindings_remain_none": True,
                "training_executed": False,
                "formal_q_b_evaluation_executed": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "contract_or_mock_counted_as_physical_evidence": False,
            },
        },
        verified,
    )


def render_binding_proposal(
    verified: VerifiedPhase2EvidenceV2,
    *,
    addendum_sha256: str,
) -> bytes:
    verified = VerifiedPhase2EvidenceV2.model_validate(verified)
    if re.fullmatch(SHA256_PATTERN, addendum_sha256) is None:
        raise ReadinessFailure("binding addendum SHA-256 is malformed")
    proposal = {
        "schema_version": "M2CS4UnlockBindingProposalV2",
        "status": "EVIDENCE_VERIFIED_REQUIRES_SEPARATE_REVIEWED_SOURCE_COMMIT",
        "adr_path": ADR_PATH,
        "binding_addendum_path": ADDENDUM_PATH,
        "binding_addendum_sha256": addendum_sha256,
        "FORMAL_PHYSICAL_RUNNER_BINDING": list(verified.formal_runner_binding),
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING": [
            verified.implementation_commit,
            verified.container_image_digest,
            verified.transitive_import_manifest_sha256,
        ],
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING": None,
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING": None,
        "applied_to_source": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return (json.dumps(proposal, indent=2, sort_keys=True) + "\n").encode()


def render_binding_addendum(verified: VerifiedPhase2EvidenceV2) -> bytes:
    verified = VerifiedPhase2EvidenceV2.model_validate(verified)
    skills = ", ".join(f"`{skill}`" for skill in verified.exact_plan_skills_verified)
    return f"""# ADR-0024 Phase-2 binding addendum

- Status: **EVIDENCE VERIFIED; SEPARATE REVIEWED SOURCE-BINDING COMMIT REQUIRED**
- Governing ADR: `{ADR_PATH}`
- Immutable implementation commit: `{verified.implementation_commit}`
- Container image digest: `{verified.container_image_digest}`
- Transitive import manifest SHA-256: `{verified.transitive_import_manifest_sha256}`
- Formal evidence SHA-256: `{verified.formal_evidence_sha256}`
- Challenge consumption receipt SHA-256: `{verified.challenge_consumption_receipt_sha256}`
- Source bindings changed by this generator: **false**
- Teacher used: **false**
- Privileged truth policy input: **false**

The V2 readiness verifier replayed the finalized formal V4 episode, canonical
Qwen and Isaac journals, the exact Isaac session suffix, both host-local HMAC
receipts, the immutable Git/image/import closure, and real-Isaac validation
for all registered skills: {skills}.

ADR-0024 withdrew the active-session B0 fallback and SSH/trusted-host signing
prerequisites. Invalid mapping or preflight remains terminal
`NO_PHYSICAL_EXECUTION`; it is never relabelled as B0. The independent B0
comparison arm remains byte-frozen and is not a runtime fallback.

`{UNLOCK_CONFIG_PATH}` is a proposal only. It sets only the formal runner and
deployment-closure bindings. Both withdrawn compatibility sentinels remain
`None`, and applying either active binding requires a separate reviewed source
commit. This addendum does not run training or Q-B evaluation.
""".encode()
