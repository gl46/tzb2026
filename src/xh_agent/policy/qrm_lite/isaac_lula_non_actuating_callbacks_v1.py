"""Fail-closed production gateway for ADR-0022 A.3 Isaac/Lula queries.

This module deliberately does not import Isaac, open a stage, step physics, or
write controller/attachment state.  It verifies an immutable image/source/
asset closure and then gates a separately reviewed active-session query
backend.  The audited Isaac Sim 6.0.1 image does not currently provide enough
evidence to instantiate the production adapter: Lula IK/FK enters an opaque
native library, its public solver explicitly has no collision avoidance, the
robot collision-detector extension declares no public API, and there is no
reviewed hypothetical-path attachment/contact query.

Contract fixtures may exercise the mutation-counter guard, but cannot create a
production-capable audit receipt and cannot be passed to the formal preflight.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightConfigurationV1,
    NonActuatingAttachmentTransitionV1,
    NonActuatingPhasePathV1,
    NonActuatingSweptCollisionV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


ISAAC_6_0_1_IMAGE_DIGEST = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"

_ISAAC_6_0_1_FILES: tuple[tuple[str, str, str, int], ...] = (
    (
        "LULA_KINEMATICS_PYTHON_WRAPPER",
        "extsDeprecated/isaacsim.robot_motion.motion_generation/isaacsim/robot_motion/"
        "motion_generation/lula/kinematics.py",
        "e5a33c21634f9d9c761aa4fd122f7245c78eab0b4bcc010d63e17668d2ec43c5",
        25397,
    ),
    (
        "LULA_INTERFACE_HELPER",
        "extsDeprecated/isaacsim.robot_motion.motion_generation/isaacsim/robot_motion/"
        "motion_generation/lula/interface_helper.py",
        "d99b4e6136eac8b5ed72b4652a9e302f6650316f5e1da0bf622097557a7d21a2",
        8057,
    ),
    (
        "LULA_PYTHON_EXTENSION",
        "extsDeprecated/isaacsim.robot_motion.lula/pip_prebundle/"
        "lula.cpython-312-x86_64-linux-gnu.so",
        "40f10561eb4ef404ae6b9034c6d692bbfced12cc78ba3e68ea4a88336b26ba11",
        8026832,
    ),
    (
        "LULA_KINEMATICS_LIBRARY",
        "extsDeprecated/isaacsim.robot_motion.lula/pip_prebundle/_lula_libs/liblula_kinematics.so",
        "197c48f8388a33df94c88a4f37fd30715e745ae89e56d30e585b5d7515f3cfa1",
        750568,
    ),
    (
        "LULA_MATH_LIBRARY",
        "extsDeprecated/isaacsim.robot_motion.lula/pip_prebundle/_lula_libs/liblula_math.so",
        "c18c9659f92e1d3b14ce7a27315193bcb17fbee8949978cf73162e1813b71084",
        684184,
    ),
    (
        "LULA_UTIL_LIBRARY",
        "extsDeprecated/isaacsim.robot_motion.lula/pip_prebundle/_lula_libs/liblula_util.so",
        "c7a5244e64fb257d095b10e4b91d6adb645014505bd87bfcb75ee1a407e91ed2",
        340704,
    ),
    (
        "LULA_ROBOT_DESCRIPTOR",
        "extsDeprecated/isaacsim.robot_motion.motion_generation/motion_policy_configs/"
        "franka/rmpflow/robot_descriptor.yaml",
        "e4e1125a73be58093f5b496ceca843abd0a752701ff276e5661b8cb54cdc3355",
        5490,
    ),
    (
        "LULA_ROBOT_DESCRIPTION",
        "extsDeprecated/isaacsim.robot_motion.motion_generation/motion_policy_configs/"
        "franka/lula_franka_gen.urdf",
        "e9024642e7952cbcaec0ae14425bf1cd19d674d3c98eeef3793913f63a8101b6",
        14771,
    ),
    (
        "COLLISION_DETECTOR_PUBLIC_API_DECLARATION",
        "exts/isaacsim.robot_setup.collision_detector/config/python_api.md",
        "21ea5f9f5def5f8f616127ccb5b734b079c6b269a87919baec64da6ca6a2122e",
        80,
    ),
)

_CAPABILITIES = frozenset(
    {
        "IK_FK_PATH_SAMPLING",
        "SWEPT_COLLISION",
        "ATTACHMENT_CONTACT_TRANSITION",
        "ACTIVE_SESSION_RUNTIME_SNAPSHOT",
    }
)
# No human-reviewed source proof exists at this commit.  A manifest-provided
# hash is not self-authenticating: enabling one of these entries requires a
# reviewed source change that pins the accepted proof digest here.
_APPROVED_QUERY_ONLY_PROOFS_V1: dict[str, str | None] = {
    capability: None for capability in _CAPABILITIES
}


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IsaacQueryCapabilityUnavailable(RuntimeError):
    """A missing proof prevents any formal callback result."""


class IsaacQueryMutationDetected(RuntimeError):
    """A nominal query changed an actuation/scene counter."""


def _canonical_model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _read_stable_regular_file(path: Path) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise IsaacQueryCapabilityUnavailable(
                f"closure member is not a single-link regular file: {path}"
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise IsaacQueryCapabilityUnavailable(f"closure member changed while read: {path}")
        return digest.hexdigest(), before.st_size
    finally:
        os.close(descriptor)


class IsaacClosureFileV1(FrozenModel):
    schema_version: Literal["IsaacClosureFileV1"] = "IsaacClosureFileV1"
    role: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def relative_path_is_safe(self) -> "IsaacClosureFileV1":
        path = Path(self.relative_path)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("closure file path escapes the image root")
        return self


class IsaacQueryCapabilityV1(FrozenModel):
    schema_version: Literal["IsaacQueryCapabilityV1"] = "IsaacQueryCapabilityV1"
    capability: Literal[
        "IK_FK_PATH_SAMPLING",
        "SWEPT_COLLISION",
        "ATTACHMENT_CONTACT_TRANSITION",
        "ACTIVE_SESSION_RUNTIME_SNAPSHOT",
    ]
    status: Literal["PROVEN_QUERY_ONLY", "NOT_AVAILABLE"]
    reason: str = Field(min_length=1)
    proof_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def proof_matches_status(self) -> "IsaacQueryCapabilityV1":
        if (self.status == "PROVEN_QUERY_ONLY") != (self.proof_sha256 is not None):
            raise ValueError("capability status/proof differs")
        approved = _APPROVED_QUERY_ONLY_PROOFS_V1[self.capability]
        if self.status == "PROVEN_QUERY_ONLY" and self.proof_sha256 != approved:
            raise ValueError("capability proof is not pinned by the reviewed adapter source")
        return self


class IsaacLulaQueryClosureManifestV1(FrozenModel):
    schema_version: Literal["IsaacLulaQueryClosureManifestV1"] = "IsaacLulaQueryClosureManifestV1"
    scope: Literal["PRODUCTION_ISAAC_6_0_1", "CONTRACT_FIXTURE"]
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    isaac_runtime_version: Literal["6.0.1"] = "6.0.1"
    expected_preflight_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    files: tuple[IsaacClosureFileV1, ...] = Field(min_length=1)
    capabilities: tuple[IsaacQueryCapabilityV1, ...] = Field(min_length=4)
    reviewed_binding_addendum_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    teacher_allowed: Literal[False] = False
    privileged_truth_policy_input_allowed: Literal[False] = False
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "IsaacLulaQueryClosureManifestV1":
        roles = tuple(item.role for item in self.files)
        capabilities = tuple(item.capability for item in self.capabilities)
        if len(roles) != len(set(roles)):
            raise ValueError("closure file roles repeat")
        if len(capabilities) != len(set(capabilities)) or set(capabilities) != _CAPABILITIES:
            raise ValueError("query capability set differs")
        all_proven = all(item.status == "PROVEN_QUERY_ONLY" for item in self.capabilities)
        if self.scope == "CONTRACT_FIXTURE" and all_proven:
            raise ValueError("contract fixture cannot claim a production-complete proof")
        if all_proven != (self.reviewed_binding_addendum_sha256 is not None):
            raise ValueError("complete capability proof/addendum binding differs")
        if self.manifest_sha256 != _canonical_model_sha256(self, "manifest_sha256"):
            raise ValueError("Isaac/Lula query closure manifest digest differs")
        return self


class NonActuatingMutationCountersV1(FrozenModel):
    schema_version: Literal["NonActuatingMutationCountersV1"] = "NonActuatingMutationCountersV1"
    articulation_target_writes: int = Field(ge=0)
    simulation_steps: int = Field(ge=0)
    scene_mutations: int = Field(ge=0)
    attachment_mutations: int = Field(ge=0)
    capture_operations: int = Field(ge=0)


class IsaacLulaQueryClosureAuditReceiptV1(FrozenModel):
    schema_version: Literal["IsaacLulaQueryClosureAuditReceiptV1"] = (
        "IsaacLulaQueryClosureAuditReceiptV1"
    )
    manifest: IsaacLulaQueryClosureManifestV1
    complete_preflight_configuration: ExactPlanPreflightConfigurationV1
    adapter_source_sha256: str = Field(pattern=SHA256_PATTERN)
    verified_file_roles: tuple[str, ...] = Field(min_length=1)
    blockers: tuple[str, ...]
    production_callback_available: Literal[False] = False
    scene_started: Literal[False] = False
    simulation_steps: Literal[0] = 0
    articulation_target_writes: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    attachment_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def crossed_and_canonical(self) -> "IsaacLulaQueryClosureAuditReceiptV1":
        roles = tuple(item.role for item in self.manifest.files)
        if (
            self.manifest.expected_preflight_configuration_sha256
            != self.complete_preflight_configuration.configuration_sha256
            or self.complete_preflight_configuration.callback_implementation_sha256
            != self.adapter_source_sha256
            or self.verified_file_roles != roles
        ):
            raise ValueError("query closure audit receipt crossed manifest/configuration")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("query closure audit receipt digest differs")
        return self


def _manifest_with_digest(**payload: Any) -> IsaacLulaQueryClosureManifestV1:
    return IsaacLulaQueryClosureManifestV1(
        **payload,
        manifest_sha256=canonical_sha256(payload),
    )


def canonical_isaac_6_0_1_blocked_manifest(
    *,
    configuration: ExactPlanPreflightConfigurationV1,
) -> IsaacLulaQueryClosureManifestV1:
    """Return the source-audited current image manifest; it is intentionally blocked."""

    files = tuple(
        IsaacClosureFileV1(role=role, relative_path=path, sha256=digest, size_bytes=size)
        for role, path, digest, size in _ISAAC_6_0_1_FILES
    )
    capabilities = (
        IsaacQueryCapabilityV1(
            capability="IK_FK_PATH_SAMPLING",
            status="NOT_AVAILABLE",
            reason=(
                "Python wrapper calls opaque lula.cpython/liblula_kinematics native code; "
                "no accepted non-actuation proof binds that binary implementation"
            ),
        ),
        IsaacQueryCapabilityV1(
            capability="SWEPT_COLLISION",
            status="NOT_AVAILABLE",
            reason=(
                "LulaKinematicsSolver.supports_collision_avoidance() is False and the "
                "Isaac robot collision-detector extension declares 'No public API'"
            ),
        ),
        IsaacQueryCapabilityV1(
            capability="ATTACHMENT_CONTACT_TRANSITION",
            status="NOT_AVAILABLE",
            reason=(
                "no reviewed API checks hypothetical bilateral contact/attachment transitions "
                "without a physics step or scene mutation"
            ),
        ),
        IsaacQueryCapabilityV1(
            capability="ACTIVE_SESSION_RUNTIME_SNAPSHOT",
            status="NOT_AVAILABLE",
            reason=(
                "no source-frozen active-session snapshot/counter backend is bound to the "
                "persistent formal Isaac process"
            ),
        ),
    )
    payload: dict[str, Any] = {
        "schema_version": "IsaacLulaQueryClosureManifestV1",
        "scope": "PRODUCTION_ISAAC_6_0_1",
        "container_image_digest": ISAAC_6_0_1_IMAGE_DIGEST,
        "isaac_runtime_version": "6.0.1",
        "expected_preflight_configuration_sha256": configuration.configuration_sha256,
        "files": [item.model_dump(mode="json") for item in files],
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        "reviewed_binding_addendum_sha256": None,
        "teacher_allowed": False,
        "privileged_truth_policy_input_allowed": False,
    }
    return _manifest_with_digest(**payload)


def audit_isaac_lula_query_closure_v1(
    *,
    image_root: Path,
    manifest: IsaacLulaQueryClosureManifestV1,
    configuration: ExactPlanPreflightConfigurationV1,
) -> IsaacLulaQueryClosureAuditReceiptV1:
    """Read and bind the closure without importing Isaac or creating a scene."""

    root = image_root.resolve(strict=True)
    if not root.is_dir():
        raise IsaacQueryCapabilityUnavailable("Isaac image root is not a directory")
    adapter_sha256, _ = _read_stable_regular_file(Path(__file__))
    if (
        configuration.configuration_sha256 != manifest.expected_preflight_configuration_sha256
        or configuration.callback_implementation_sha256 != adapter_sha256
    ):
        raise IsaacQueryCapabilityUnavailable(
            "preflight configuration differs from closure/adapter source binding"
        )
    role_to_file = {item.role: item for item in manifest.files}
    robot_description = role_to_file.get("LULA_ROBOT_DESCRIPTION")
    if (
        robot_description is not None
        and configuration.ik.robot_description_sha256 != robot_description.sha256
    ):
        raise IsaacQueryCapabilityUnavailable(
            "IK robot description differs from the bound Lula asset"
        )
    verified: list[str] = []
    for expected in manifest.files:
        candidate = root.joinpath(expected.relative_path)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise IsaacQueryCapabilityUnavailable("closure member escaped image root") from exc
        digest, size = _read_stable_regular_file(candidate)
        if digest != expected.sha256 or size != expected.size_bytes:
            raise IsaacQueryCapabilityUnavailable(
                f"closure member hash/size mismatch for {expected.role}"
            )
        verified.append(expected.role)
    blockers = tuple(
        f"{item.capability}:{item.reason}"
        for item in manifest.capabilities
        if item.status == "NOT_AVAILABLE"
    )
    payload: dict[str, Any] = {
        "schema_version": "IsaacLulaQueryClosureAuditReceiptV1",
        "manifest": manifest.model_dump(mode="json"),
        "complete_preflight_configuration": configuration.model_dump(mode="json"),
        "adapter_source_sha256": adapter_sha256,
        "verified_file_roles": verified,
        "blockers": blockers,
        "production_callback_available": False,
        "scene_started": False,
        "simulation_steps": 0,
        "articulation_target_writes": 0,
        "scene_mutations": 0,
        "attachment_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return IsaacLulaQueryClosureAuditReceiptV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


class BoundIsaacQueryBackendV1(Protocol):
    implementation_sha256: str

    def read_mutation_counters(self) -> NonActuatingMutationCountersV1: ...


T = TypeVar("T")


def run_non_actuating_backend_query_v1(
    backend: BoundIsaacQueryBackendV1,
    query: Callable[[], T],
) -> T:
    """Contract guard only; this function alone is not production attestation."""

    before = backend.read_mutation_counters()
    try:
        result = query()
    except Exception as exc:
        try:
            after = backend.read_mutation_counters()
        except Exception as counter_exc:
            raise IsaacQueryMutationDetected(
                "query failed and post-query mutation counters are unavailable"
            ) from counter_exc
        if after != before:
            raise IsaacQueryMutationDetected("failed query changed mutation counters") from exc
        raise
    try:
        after = backend.read_mutation_counters()
    except Exception as exc:
        raise IsaacQueryMutationDetected("post-query mutation counters are unavailable") from exc
    if after != before:
        raise IsaacQueryMutationDetected("query changed mutation counters")
    return result


class IsaacLulaNonActuatingCallbacksV1:
    """Production preflight callback adapter; unavailable until every proof exists."""

    non_actuating: Literal[True] = True

    def __init__(
        self,
        *,
        audit_receipt: IsaacLulaQueryClosureAuditReceiptV1,
        backend: BoundIsaacQueryBackendV1,
    ) -> None:
        raise IsaacQueryCapabilityUnavailable(
            "Isaac/Lula production query callback is NOT_AVAILABLE at this source commit: "
            + "; ".join(audit_receipt.blockers)
        )
        # Unreachable until reviewed proof hashes are pinned by a later source
        # revision; retained to make the eventual adapter contract explicit.
        self.audit_receipt = audit_receipt
        self.backend = backend
        config = audit_receipt.complete_preflight_configuration
        self.implementation_sha256 = audit_receipt.adapter_source_sha256
        self.ik_algorithm_sha256 = config.ik.algorithm_sha256
        self.swept_collision_algorithm_sha256 = config.swept_collision.algorithm_sha256
        self.attachment_algorithm_sha256 = config.attachment.algorithm_sha256

    def _call(self, name: str, expected_type: type[T], *args: Any, **kwargs: Any) -> T:
        method = getattr(self.backend, name, None)
        if not callable(method):
            raise IsaacQueryCapabilityUnavailable(f"bound query backend lacks {name}")
        result = run_non_actuating_backend_query_v1(
            self.backend,
            lambda: method(*args, **kwargs),
        )
        if not isinstance(result, expected_type):
            raise IsaacQueryCapabilityUnavailable(f"bound query backend returned wrong {name} type")
        return result

    def snapshot_runtime(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> PreflightRuntimeSnapshotV1:
        return self._call("snapshot_runtime", PreflightRuntimeSnapshotV1, plan)

    def solve_phase_path(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        *,
        start_state_sha256: str,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingPhasePathV1:
        return self._call(
            "solve_phase_path",
            NonActuatingPhasePathV1,
            plan,
            phase,
            start_state_sha256=start_state_sha256,
            configuration=configuration,
        )

    def check_swept_collision(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingSweptCollisionV1:
        return self._call(
            "check_swept_collision",
            NonActuatingSweptCollisionV1,
            plan,
            phase,
            path,
            configuration=configuration,
        )

    def check_attachment_transition(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        expected_attachment_present: bool,
        expected_attachment_sha256: str | None,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingAttachmentTransitionV1:
        return self._call(
            "check_attachment_transition",
            NonActuatingAttachmentTransitionV1,
            plan,
            phase,
            path,
            expected_attachment_present=expected_attachment_present,
            expected_attachment_sha256=expected_attachment_sha256,
            configuration=configuration,
        )
