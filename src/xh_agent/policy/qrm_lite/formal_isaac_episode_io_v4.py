"""Single-use V4 episode lifecycle and public-capture composition.

The formal backend has two intentionally separate interfaces: an episode
lifecycle and a public capture source.  In production both must operate on the
same persistent Isaac scene owner.  This module supplies that shared state
machine while keeping the interfaces separate so their independently frozen
implementation hashes cannot be conflated.

No simulator identity is exposed to the model.  The scene owner may use
simulator paths only inside its safety/evaluation implementation; the capture
surface is the ADR-0024 public RGB-D/proprioception contract.  Construction in
``REAL_ISAAC`` mode requires a reviewed, execution-eligible deployment whose
repository files still match their frozen hashes.  The repository currently
contains no such deployment binding, so the production path remains
fail-closed.
"""

from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationDeploymentBindingV2,
)
from xh_agent.policy.qrm_lite.formal_isaac_backend_v4 import (
    FormalIsaacEpisodeStartReceiptV4,
    FormalIsaacFinalEvaluationReceiptV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    FormalPublicCapturePacketV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacEndpointBindingV4,
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacStartRequestV4,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PublicDeclaredTargetAttributeBindingV4,
)


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_episode_io_v4.py"
PUBLIC_OBSERVATION_PROVIDER_REPO_PATH = (
    "src/xh_agent/policy/qrm_lite/formal_public_observation_provider_v4.py"
)
ACCEPTED_ADR_REPO_PATH = "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _safe_repo_path(project_root: Path, raw_path: str) -> Path:
    pure = PurePosixPath(raw_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError("formal V4 episode I/O source path escapes the repository")
    target = project_root.joinpath(*pure.parts)
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("formal V4 episode I/O source path escapes the repository") from exc
    return resolved


def _require_bound_file(project_root: Path, raw_path: str, expected_sha256: str) -> None:
    target = _safe_repo_path(project_root, raw_path)
    actual = hashlib.sha256(read_regular_file_once(target)).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"formal V4 episode I/O source hash differs: {raw_path}")


def _git_bytes(project_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError("formal V4 episode I/O Git binding cannot be replayed")
    return completed.stdout


def _require_immutable_commit(
    project_root: Path,
    *,
    immutable_commit: str,
    source_paths: tuple[str, ...],
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
            "formal V4 episode I/O immutable commit is not an ancestor of current HEAD"
        ) from exc
    for raw_path in source_paths:
        current = read_regular_file_once(_safe_repo_path(project_root, raw_path))
        committed = _git_bytes(project_root, "show", f"{immutable_commit}:{raw_path}")
        if committed != current:
            raise ValueError("formal V4 episode I/O source differs from immutable commit")
    status = _git_bytes(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *source_paths,
    )
    if status:
        raise ValueError("formal V4 episode I/O source closure is dirty")


class FormalIsaacEpisodeIODeploymentBindingV1(_FrozenModel):
    """Reviewed composition of lifecycle, capture, owner, and endpoint bytes."""

    schema_version: Literal["FormalIsaacEpisodeIODeploymentBindingV1"] = (
        "FormalIsaacEpisodeIODeploymentBindingV1"
    )
    accepted_adr_path: Literal["docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"] = (
        ACCEPTED_ADR_REPO_PATH
    )
    accepted_adr_sha256: str = Field(pattern=SHA256_PATTERN)
    lifecycle_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_isaac_episode_io_v4.py"
    ] = IMPLEMENTATION_REPO_PATH
    lifecycle_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_owner_implementation_path: str = Field(min_length=1)
    scene_owner_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_source_implementation_path: str = Field(min_length=1)
    capture_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    public_observation_provider_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_public_observation_provider_v4.py"
    ] = PUBLIC_OBSERVATION_PROVIDER_REPO_PATH
    public_observation_provider_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    association_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transitive_dependency_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    review_status: Literal[
        "CONTRACT_TEST_ONLY",
        "REVIEWED_BINDING_ADDENDUM",
    ]
    formal_execution_eligible: bool
    real_isaac: bool
    mocked_physics: bool
    simulator_identity_exposed_to_model: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    deployment_binding_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def mode_and_digest_are_exact(self) -> "FormalIsaacEpisodeIODeploymentBindingV1":
        if self.real_isaac == self.mocked_physics:
            raise ValueError("formal V4 episode I/O deployment must be real or mocked")
        production = self.review_status == "REVIEWED_BINDING_ADDENDUM"
        if self.formal_execution_eligible != production or self.real_isaac != production:
            raise ValueError("formal V4 episode I/O review/mode/eligibility differ")
        if self.mocked_physics == production:
            raise ValueError("formal V4 episode I/O mocked flag differs from review mode")
        if self.deployment_binding_sha256 != _model_sha256(
            self,
            "deployment_binding_sha256",
        ):
            raise ValueError("formal V4 episode I/O deployment digest differs")
        return self


class FormalIsaacSceneStartEvidenceV4(_FrozenModel):
    """Owner-produced public failure-boundary evidence before policy capture."""

    schema_version: Literal["FormalIsaacSceneStartEvidenceV4"] = "FormalIsaacSceneStartEvidenceV4"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    start_request_sha256: str = Field(pattern=SHA256_PATTERN)
    endpoint_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_owner_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    failure_observed_at_ns: int = Field(gt=0)
    public_failure_boundary_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    real_isaac: bool
    mocked_physics: bool
    failure_boundary_derived_from_public_observation: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def mode_and_digest_are_exact(self) -> "FormalIsaacSceneStartEvidenceV4":
        if self.real_isaac == self.mocked_physics:
            raise ValueError("formal V4 scene-start evidence must be real or mocked")
        if self.evidence_sha256 != _model_sha256(self, "evidence_sha256"):
            raise ValueError("formal V4 scene-start evidence digest differs")
        return self


class FormalIsaacSceneFinalEvidenceV4(_FrozenModel):
    """Owner-produced public-only final evaluation over the exact history."""

    schema_version: Literal["FormalIsaacSceneFinalEvidenceV4"] = "FormalIsaacSceneFinalEvidenceV4"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    finalize_request_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_owner_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    last_execution_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    last_bundle_execution_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    execution_response_sha256: tuple[str, ...] = Field(min_length=8, max_length=8)
    public_evaluation_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    evaluated_at_ns: int = Field(gt=0)
    final_task_success: bool
    real_isaac: bool
    mocked_physics: bool
    outcome_used_as_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def mode_and_digest_are_exact(self) -> "FormalIsaacSceneFinalEvidenceV4":
        if self.real_isaac == self.mocked_physics:
            raise ValueError("formal V4 scene-final evidence must be real or mocked")
        if self.evidence_sha256 != _model_sha256(self, "evidence_sha256"):
            raise ValueError("formal V4 scene-final evidence digest differs")
        return self


class FormalIsaacPersistentSceneOwnerV4(Protocol):
    """One persistent scene; never a model, planner, or fallback surface."""

    implementation_sha256: str
    capture_source_implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool

    def establish_public_failure_boundary_v4(
        self,
        request: IsaacStartRequestV4,
    ) -> FormalIsaacSceneStartEvidenceV4: ...

    def capture_public_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicCapturePacketV4: ...

    def evaluate_public_outcome_v4(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacSceneFinalEvidenceV4: ...


class _SharedEpisodeIOSessionV4:
    def __init__(
        self,
        *,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        binding: FormalIsaacEpisodeIODeploymentBindingV1,
        endpoint_binding: IsaacEndpointBindingV4,
        association_deployment: PublicAssociationDeploymentBindingV2,
        declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
        owner: FormalIsaacPersistentSceneOwnerV4,
    ) -> None:
        self.mode = mode
        self.binding = binding
        self.endpoint_binding = endpoint_binding
        self.association_deployment = association_deployment
        self.declared_attribute_binding = declared_attribute_binding
        self.owner = owner
        self._lock = threading.Lock()
        self._run_id: str | None = None
        self._session_id: str | None = None
        self._next_capture_index = 0
        self._previous_completed_at_ns = 0
        self._poisoned = False
        self._terminal = False

    @property
    def real_isaac(self) -> bool:
        return self.mode == "REAL_ISAAC"

    @property
    def mocked_physics(self) -> bool:
        return self.mode == "CONTRACT_TEST"

    def _guard(self) -> None:
        if self.real_isaac:
            require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
        if self._poisoned:
            raise RuntimeError("formal V4 episode I/O is poisoned")

    def start_episode(self, request: IsaacStartRequestV4) -> FormalIsaacEpisodeStartReceiptV4:
        with self._lock:
            self._guard()
            if self._run_id is not None or self._terminal:
                raise RuntimeError("formal V4 episode I/O start is single-use")
            if (
                request.endpoint_binding_sha256 != self.binding.endpoint_binding_sha256
                or request.declared_attribute_binding_sha256
                != self.binding.declared_attribute_binding_sha256
            ):
                raise ValueError("formal V4 episode I/O start crosses deployment")
            self._poisoned = True
            raw = self.owner.establish_public_failure_boundary_v4(request)
            evidence = FormalIsaacSceneStartEvidenceV4.model_validate(
                raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
            )
            expected = {
                "run_id": request.run_id,
                "start_request_sha256": canonical_sha256(request),
                "endpoint_binding_sha256": self.binding.endpoint_binding_sha256,
                "scene_owner_implementation_sha256": (
                    self.binding.scene_owner_implementation_sha256
                ),
                "matched_key": request.matched_key,
                "scene_seed": request.scene_seed,
                "failure_seed": request.failure_seed,
                "sdf_sha256": request.sdf_sha256,
                "supervision_sha256": request.supervision_sha256,
                "declared_attribute_binding_sha256": (request.declared_attribute_binding_sha256),
                "real_isaac": self.real_isaac,
                "mocked_physics": self.mocked_physics,
            }
            if any(getattr(evidence, name) != value for name, value in expected.items()):
                raise ValueError("formal V4 scene-start evidence crosses request/deployment")
            payload: dict[str, Any] = {
                "schema_version": "FormalIsaacEpisodeStartReceiptV4",
                "run_id": request.run_id,
                "session_id": evidence.session_id,
                "start_request_sha256": canonical_sha256(request),
                "endpoint_binding_sha256": self.binding.endpoint_binding_sha256,
                "physical_backend_sha256": self.binding.lifecycle_implementation_sha256,
                "challenge_nonce": request.challenge_nonce,
                "challenge_consumption_id": request.challenge_consumption_id,
                "challenge_consumption_receipt_sha256": (
                    request.challenge_consumption_receipt_sha256
                ),
                "matched_key": request.matched_key,
                "scene_seed": request.scene_seed,
                "failure_seed": request.failure_seed,
                "sdf_sha256": request.sdf_sha256,
                "supervision_sha256": request.supervision_sha256,
                "declared_attribute_binding_sha256": (request.declared_attribute_binding_sha256),
                "qwen_bundle_sha256": canonical_sha256(request.bundle),
                "failure_observed_at_ns": evidence.failure_observed_at_ns,
                "public_failure_boundary_evidence_sha256": (
                    evidence.public_failure_boundary_evidence_sha256
                ),
                "failure_boundary_derived_from_public_observation": True,
                "real_isaac": True,
                "mocked_physics": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            # The formal receipt schema intentionally describes only a real
            # endpoint. Contract-mode composition is tested below the formal
            # coordinator and therefore returns owner evidence, not this path.
            if not self.real_isaac:
                raise RuntimeError("contract episode I/O cannot emit a formal real-Isaac start")
            receipt = FormalIsaacEpisodeStartReceiptV4(
                **payload,
                receipt_sha256=canonical_sha256(payload),
            )
            self._run_id = request.run_id
            self._session_id = evidence.session_id
            self._previous_completed_at_ns = evidence.failure_observed_at_ns
            self._poisoned = False
            return receipt

    def capture_public_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicCapturePacketV4:
        with self._lock:
            self._guard()
            if self._terminal or (run_id, session_id) != (self._run_id, self._session_id):
                raise ValueError("formal V4 public capture crosses active episode")
            if (
                decision_index != self._next_capture_index
                or (
                    decision_index == 0
                    and previous_execution_completed_at_ns != self._previous_completed_at_ns
                )
                or (
                    decision_index > 0
                    and previous_execution_completed_at_ns <= self._previous_completed_at_ns
                )
            ):
                raise ValueError("formal V4 public capture order/time differs")
            self._poisoned = True
            raw = self.owner.capture_public_v4(
                run_id=run_id,
                session_id=session_id,
                decision_index=decision_index,
                previous_execution_completed_at_ns=previous_execution_completed_at_ns,
            )
            packet = FormalPublicCapturePacketV4.model_validate(
                raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
            )
            if (
                packet.run_id != run_id
                or packet.session_id != session_id
                or packet.decision_index != decision_index
                or packet.previous_execution_completed_at_ns != previous_execution_completed_at_ns
                or packet.capture_source_implementation_sha256
                != self.binding.capture_source_implementation_sha256
                or packet.capture.protocol != self.association_deployment.protocol
                or packet.real_isaac != self.real_isaac
                or packet.mocked_physics != self.mocked_physics
            ):
                raise ValueError("formal V4 public capture packet crosses deployment")
            self._next_capture_index += 1
            self._previous_completed_at_ns = previous_execution_completed_at_ns
            self._poisoned = False
            return packet

    def finalize_episode(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacFinalEvaluationReceiptV4:
        with self._lock:
            self._guard()
            if (
                self._terminal
                or (request.run_id, request.session_id) != (self._run_id, self._session_id)
                or self._next_capture_index != 8
                or len(execution_responses) != 8
            ):
                raise ValueError("formal V4 final evaluation crosses active episode")
            responses = tuple(
                IsaacExecuteResponseV4.model_validate(item.model_dump(mode="json"))
                for item in execution_responses
            )
            response_hashes = tuple(canonical_sha256(item) for item in responses)
            self._terminal = True
            raw = self.owner.evaluate_public_outcome_v4(
                request,
                execution_responses=responses,
            )
            evidence = FormalIsaacSceneFinalEvidenceV4.model_validate(
                raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
            )
            expected = {
                "run_id": request.run_id,
                "session_id": request.session_id,
                "finalize_request_sha256": canonical_sha256(request),
                "scene_owner_implementation_sha256": (
                    self.binding.scene_owner_implementation_sha256
                ),
                "last_execution_receipt_sha256": (request.last_execution_receipt_sha256),
                "last_bundle_execution_receipt_sha256": (
                    request.last_bundle_execution_receipt_sha256
                ),
                "execution_response_sha256": response_hashes,
                "real_isaac": self.real_isaac,
                "mocked_physics": self.mocked_physics,
            }
            if any(getattr(evidence, name) != value for name, value in expected.items()):
                raise ValueError("formal V4 final evidence crosses execution history")
            if evidence.evaluated_at_ns <= self._previous_completed_at_ns:
                raise ValueError("formal V4 final evaluation predates public capture history")
            payload: dict[str, Any] = {
                "schema_version": "FormalIsaacFinalEvaluationReceiptV4",
                "run_id": request.run_id,
                "session_id": request.session_id,
                "finalize_request_sha256": canonical_sha256(request),
                "last_execution_receipt_sha256": request.last_execution_receipt_sha256,
                "last_bundle_execution_receipt_sha256": (
                    request.last_bundle_execution_receipt_sha256
                ),
                "execution_response_sha256": response_hashes,
                "public_evaluation_evidence_sha256": (evidence.public_evaluation_evidence_sha256),
                "evaluated_at_ns": evidence.evaluated_at_ns,
                "final_task_success": evidence.final_task_success,
                "completed_model_decisions": 8,
                "outcome_used_as_policy_input": False,
                "real_isaac": True,
                "mocked_physics": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            if not self.real_isaac:
                raise RuntimeError("contract episode I/O cannot emit a formal real-Isaac final")
            return FormalIsaacFinalEvaluationReceiptV4(
                **payload,
                receipt_sha256=canonical_sha256(payload),
            )


class FormalIsaacEpisodeLifecycleAdapterV4:
    """Lifecycle facade consumed by ``FormalIsaacBackendCoordinatorV4``."""

    def __init__(self, session: _SharedEpisodeIOSessionV4) -> None:
        self._session = session
        self.implementation_sha256 = session.binding.lifecycle_implementation_sha256
        self.real_isaac = session.real_isaac
        self.mocked_physics = session.mocked_physics

    def start_episode(self, request: IsaacStartRequestV4) -> FormalIsaacEpisodeStartReceiptV4:
        return self._session.start_episode(request)

    def finalize_episode(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacFinalEvaluationReceiptV4:
        return self._session.finalize_episode(
            request,
            execution_responses=execution_responses,
        )


class FormalIsaacPublicCaptureSourceAdapterV4:
    """Capture-source facade consumed by the replayable observation provider."""

    def __init__(self, session: _SharedEpisodeIOSessionV4) -> None:
        self._session = session
        self.implementation_sha256 = session.binding.capture_source_implementation_sha256
        self.real_isaac = session.real_isaac
        self.mocked_physics = session.mocked_physics

    def capture_public_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicCapturePacketV4:
        return self._session.capture_public_v4(
            run_id=run_id,
            session_id=session_id,
            decision_index=decision_index,
            previous_execution_completed_at_ns=previous_execution_completed_at_ns,
        )


class FormalIsaacEpisodeIOV4:
    """Validated pair of lifecycle/capture facades over one persistent owner."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        binding: FormalIsaacEpisodeIODeploymentBindingV1,
        endpoint_binding: IsaacEndpointBindingV4,
        association_deployment: PublicAssociationDeploymentBindingV2,
        declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
        owner: FormalIsaacPersistentSceneOwnerV4,
    ) -> None:
        project_root = project_root.resolve(strict=True)
        binding = FormalIsaacEpisodeIODeploymentBindingV1.model_validate(
            binding.model_dump(mode="json")
        )
        endpoint_binding = IsaacEndpointBindingV4.model_validate(
            endpoint_binding.model_dump(mode="json")
        )
        association_deployment = PublicAssociationDeploymentBindingV2.model_validate(
            association_deployment.model_dump(mode="json")
        )
        declared_attribute_binding = PublicDeclaredTargetAttributeBindingV4.model_validate(
            declared_attribute_binding.model_dump(mode="json")
        )
        if mode != "REAL_ISAAC" or not binding.formal_execution_eligible:
            raise ValueError("formal V4 episode I/O adapter requires a reviewed real deployment")
        for path, digest in (
            (binding.accepted_adr_path, binding.accepted_adr_sha256),
            (binding.lifecycle_implementation_path, binding.lifecycle_implementation_sha256),
            (binding.scene_owner_implementation_path, binding.scene_owner_implementation_sha256),
            (
                binding.capture_source_implementation_path,
                binding.capture_source_implementation_sha256,
            ),
            (binding.public_observation_provider_path, binding.public_observation_provider_sha256),
        ):
            _require_bound_file(project_root, path, digest)
        source_paths = tuple(
            dict.fromkeys(
                (
                    binding.accepted_adr_path,
                    binding.lifecycle_implementation_path,
                    binding.scene_owner_implementation_path,
                    binding.capture_source_implementation_path,
                    binding.public_observation_provider_path,
                )
            )
        )
        _require_immutable_commit(
            project_root,
            immutable_commit=binding.immutable_commit,
            source_paths=source_paths,
        )
        if (
            canonical_sha256(endpoint_binding) != binding.endpoint_binding_sha256
            or endpoint_binding.physical_backend_sha256 != binding.lifecycle_implementation_sha256
            or endpoint_binding.public_observation_provider_sha256
            != binding.public_observation_provider_sha256
            or endpoint_binding.capture_source_implementation_sha256
            != binding.capture_source_implementation_sha256
            or endpoint_binding.association_deployment_sha256
            != binding.association_deployment_sha256
            or endpoint_binding.immutable_commit != binding.immutable_commit
            or endpoint_binding.container_image_digest != binding.container_image_digest
            or endpoint_binding.transitive_dependency_manifest_sha256
            != binding.transitive_dependency_manifest_sha256
            or association_deployment.deployment_binding_sha256
            != binding.association_deployment_sha256
            or declared_attribute_binding.binding_sha256
            != binding.declared_attribute_binding_sha256
            or owner.implementation_sha256 != binding.scene_owner_implementation_sha256
            or owner.capture_source_implementation_sha256
            != binding.capture_source_implementation_sha256
            or owner.real_isaac != binding.real_isaac
            or owner.mocked_physics != binding.mocked_physics
        ):
            raise ValueError("formal V4 episode I/O dependencies cross deployment")
        session = _SharedEpisodeIOSessionV4(
            mode=mode,
            binding=binding,
            endpoint_binding=endpoint_binding,
            association_deployment=association_deployment,
            declared_attribute_binding=declared_attribute_binding,
            owner=owner,
        )
        self.binding = binding
        self.lifecycle = FormalIsaacEpisodeLifecycleAdapterV4(session)
        self.capture_source = FormalIsaacPublicCaptureSourceAdapterV4(session)
