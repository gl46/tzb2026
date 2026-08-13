"""Fail-closed ADR-0022 Phase-2 deployment/readiness verifier.

This module is intentionally an evidence consumer, not a deployment tool.  It
can render a binding addendum and a machine-readable binding proposal only
after independently checking host-signed, byte-bound, real-Isaac evidence.
It never edits ``s4_entry_gate.py`` and cannot set an unlock binding.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanBundleExecutionReceiptV1,
    ExactPlanPreflightReceiptV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_json_bytes, canonical_sha256
from xh_agent.policy.qrm_lite.frozen_b0_fallback_wrapper_v1 import (
    FROZEN_B0_MANIFEST_SHA256,
    FROZEN_B0_PROBE_SHA256,
    FrozenB0ActiveSessionBindingV1,
    FrozenB0FallbackReceiptV1,
    FrozenB0FallbackRequestV1,
    FrozenB0FallbackWrapperV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    LABSERVER_PRINCIPAL,
    SignedHostWireAuthenticationReceiptV1,
    canonical_envelope_set_sha256,
    verify_receipt_signature,
)
from xh_agent.policy.qrm_lite.public_tracks_v3 import (
    build_public_track_candidates_v3,
    canonical_candidate_sha256_v3,
)
from xh_agent.policy.qrm_lite.s4_entry_gate import FormalTransitiveImportClosureManifestV1


SCHEMA_VERSION = "M2CADR0022BindingAddendumReadinessV1"
INDEX_SCHEMA = "M2CADR0022Phase2EvidenceIndexV1"
DEPLOYMENT_AUTH_NAMESPACE = "m2c-phase2-deployment-v1@xh-agent"
ADR_PATH = "docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"
BUNDLE_PATH = "src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py"
WRAPPER_PATH = "src/xh_agent/policy/qrm_lite/frozen_b0_fallback_wrapper_v1.py"
ENTRY_GATE_PATH = "src/xh_agent/policy/qrm_lite/s4_entry_gate.py"
OFFLINE_VERIFIER_PATH = "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py"
FORMAL_RUNNER_PATH = "scripts/m2c/run_formal_model_owned_chain.py"
NODE2_TRUST_ROOT_PATH = "configs/m2c_phase2_node2_allowed_signers"
LABSERVER_TRUST_ROOT_PATH = "configs/m2c_phase2_labserver_allowed_signers"
ADDENDUM_PATH = "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"
UNLOCK_CONFIG_PATH = "configs/m2c_s4_unlock_bindings.json"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
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
ARTIFACT_NAMES = frozenset(
    {
        "formal_evidence",
        "qwen_service_audit",
        "isaac_service_audit",
        "isaac_session_audit",
        "node2_wire_auth_receipt",
        "labserver_wire_auth_receipt",
        "transitive_import_manifest",
        "exact_plan_physical_evidence",
        "b0_active_session_evidence",
        "b0_validation_audit",
    }
)


class ReadinessFailure(RuntimeError):
    """A required deployment or provenance fact failed closed."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceFileBindingV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def relative_safe_path(self) -> "EvidenceFileBindingV1":
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("evidence file binding must be a contained relative path")
        return self


class ProjectFileBindingV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def repository_relative_path(self) -> "ProjectFileBindingV1":
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("project binding must be a repository-relative path")
        return self


class ExactPlanSkillPhysicalValidationV1(StrictModel):
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
    decision_index: int = Field(ge=0, le=7)
    plan: M2CExactPlanPrimitivePlanV1
    preflight_receipt: ExactPlanPreflightReceiptV1
    execution_receipt: ExactPlanBundleExecutionReceiptV1
    preflight_audit_record_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_audit_record_sha256: tuple[str, ...] = Field(min_length=1)
    execution_audit_record_sha256: str = Field(pattern=SHA256_PATTERN)


class ExactPlanPhysicalEvidenceV1(StrictModel):
    schema_version: Literal["M2CExactPlanPhysicalEvidenceV1"] = "M2CExactPlanPhysicalEvidenceV1"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    formal_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    isaac_session_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    validations: tuple[ExactPlanSkillPhysicalValidationV1, ...] = Field(min_length=8, max_length=8)
    real_isaac: Literal[True] = True
    formal_evidence: Literal[True] = True
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    contract_test_only: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_skill_order(self) -> "ExactPlanPhysicalEvidenceV1":
        observed = tuple((item.decision_index, item.canonical_skill) for item in self.validations)
        if observed != tuple(enumerate(SKILLS)):
            raise ValueError("physical validation is not the exact eight-skill ordered chain")
        return self


class FrozenB0ActiveSessionPhysicalEvidenceV1(StrictModel):
    schema_version: Literal["M2CFrozenB0ActiveSessionPhysicalEvidenceV1"] = (
        "M2CFrozenB0ActiveSessionPhysicalEvidenceV1"
    )
    request: FrozenB0FallbackRequestV1
    active_session_binding: FrozenB0ActiveSessionBindingV1
    receipt: FrozenB0FallbackReceiptV1
    b0_validation_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    audit_record_sha256: str = Field(pattern=SHA256_PATTERN)
    real_isaac: Literal[True] = True
    unchanged_b0_invoked: Literal[True] = True
    backend_reimplemented_b0: Literal[False] = False
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    contract_test_only: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class Phase2DeploymentAttestationCoreV1(StrictModel):
    schema_version: Literal["M2CPhase2DeploymentAttestationCoreV1"] = (
        "M2CPhase2DeploymentAttestationCoreV1"
    )
    host_role: Literal["LABSERVER_ISAAC"] = "LABSERVER_ISAAC"
    signer_principal: Literal[LABSERVER_PRINCIPAL] = LABSERVER_PRINCIPAL
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_sha256: dict[str, str]
    public_trust_root_sha256: str = Field(pattern=SHA256_PATTERN)
    signature_scheme: Literal["OPENSSH_ED25519_SSHSIG"] = "OPENSSH_ED25519_SSHSIG"
    signature_namespace: Literal[DEPLOYMENT_AUTH_NAMESPACE] = DEPLOYMENT_AUTH_NAMESPACE
    audit_cleanly_stopped: Literal[True] = True
    real_isaac: Literal[True] = True
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_artifact_set(self) -> "Phase2DeploymentAttestationCoreV1":
        if set(self.artifact_sha256) != ARTIFACT_NAMES or any(
            re.fullmatch(SHA256_PATTERN, digest) is None for digest in self.artifact_sha256.values()
        ):
            raise ValueError("deployment attestation artifact set is incomplete or malformed")
        return self


class SignedPhase2DeploymentAttestationV1(StrictModel):
    schema_version: Literal["M2CSignedPhase2DeploymentAttestationV1"] = (
        "M2CSignedPhase2DeploymentAttestationV1"
    )
    core: Phase2DeploymentAttestationCoreV1
    signature_armored: str = Field(
        pattern=r"^-----BEGIN SSH SIGNATURE-----[\s\S]+-----END SSH SIGNATURE-----\n?$"
    )


class Phase2EvidenceIndexV1(StrictModel):
    schema_version: Literal[INDEX_SCHEMA] = INDEX_SCHEMA
    status: Literal["COLLECTED_REAL_PHASE2_EVIDENCE"] = "COLLECTED_REAL_PHASE2_EVIDENCE"
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    formal_runner: ProjectFileBindingV1
    primitive_bundle: ProjectFileBindingV1
    b0_runtime_wrapper: ProjectFileBindingV1
    offline_wire_verifier: ProjectFileBindingV1
    node2_trust_root: ProjectFileBindingV1
    labserver_trust_root: ProjectFileBindingV1
    artifacts: dict[str, EvidenceFileBindingV1]
    deployment_attestation: EvidenceFileBindingV1
    source_bindings_independently_reviewed: Literal[True] = True
    container_digest_observed_on_labserver: Literal[True] = True
    no_binding_applied_by_collector: Literal[True] = True
    training_executed: Literal[False] = False
    q_b_evaluation_executed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_paths_and_artifacts(self) -> "Phase2EvidenceIndexV1":
        expected_paths = {
            self.formal_runner.path: FORMAL_RUNNER_PATH,
            self.primitive_bundle.path: BUNDLE_PATH,
            self.b0_runtime_wrapper.path: WRAPPER_PATH,
            self.offline_wire_verifier.path: OFFLINE_VERIFIER_PATH,
            self.node2_trust_root.path: NODE2_TRUST_ROOT_PATH,
            self.labserver_trust_root.path: LABSERVER_TRUST_ROOT_PATH,
        }
        if any(observed != expected for observed, expected in expected_paths.items()):
            raise ValueError("Phase-2 index uses an unapproved source/trust-root path")
        if set(self.artifacts) != ARTIFACT_NAMES:
            raise ValueError("Phase-2 evidence index artifact set is not exact")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessFailure(f"evidence input is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)

        def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after):
            raise ReadinessFailure(f"evidence input changed during read: {path}")
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


def _resolve_contained(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ReadinessFailure(f"evidence file is absent: {relative}") from error
    if not resolved.is_relative_to(root.resolve()) or path.is_symlink():
        raise ReadinessFailure(f"evidence file escapes its root: {relative}")
    return path


def _read_bound_files(
    root: Path, bindings: Mapping[str, EvidenceFileBindingV1]
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    identities: set[tuple[int, int]] = set()
    for name, binding in bindings.items():
        path = _resolve_contained(root, binding.path)
        metadata = path.stat(follow_symlinks=False)
        identity = (metadata.st_dev, metadata.st_ino)
        if identity in identities:
            raise ReadinessFailure("two evidence roles alias the same file")
        identities.add(identity)
        payload = read_regular_file_once(path)
        if sha256_bytes(payload) != binding.sha256:
            raise ReadinessFailure(f"evidence SHA-256 mismatch: {name}")
        payloads[name] = payload
    return payloads


def _git_file(project: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=project,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise ReadinessFailure(f"immutable commit does not contain required file: {path}")
    return completed.stdout


def _require_ancestor_commit(project: Path, commit: str) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=project,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise ReadinessFailure("immutable implementation commit is not an ancestor of HEAD")


def _verify_project_binding(project: Path, commit: str, binding: ProjectFileBindingV1) -> bytes:
    committed = _git_file(project, commit, binding.path)
    if sha256_bytes(committed) != binding.sha256:
        raise ReadinessFailure(f"committed project binding differs: {binding.path}")
    current = read_regular_file_once(project / binding.path)
    if current != committed:
        raise ReadinessFailure(
            f"worktree project binding differs from immutable commit: {binding.path}"
        )
    return current


def _read_canonical_jsonl(data: bytes, *, schema: str, label: str) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise ReadinessFailure(f"{label} is not newline-terminated")
    lines = data.splitlines()
    try:
        records = [json.loads(line) for line in lines]
    except json.JSONDecodeError as error:
        raise ReadinessFailure(f"{label} is not JSONL") from error
    if not records or any(not isinstance(record, dict) for record in records):
        raise ReadinessFailure(f"{label} is empty or non-object")
    first = records[0].get("sequence")
    if not isinstance(first, int) or any(
        record.get("schema_version") != schema
        or record.get("sequence") != first + index
        or canonical_json_bytes(record) != lines[index]
        for index, record in enumerate(records)
    ):
        raise ReadinessFailure(f"{label} is not canonical contiguous JSONL")
    return records


def _verify_deployment_signature(
    receipt: SignedPhase2DeploymentAttestationV1,
    *,
    allowed_signers_bytes: bytes,
    ssh_keygen: Path = Path("/usr/bin/ssh-keygen"),
) -> None:
    expected = re.escape(LABSERVER_PRINCIPAL.encode("ascii"))
    if (
        re.fullmatch(
            rb"^" + expected + rb" ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\x00\r\n]+)?\n?$",
            allowed_signers_bytes,
        )
        is None
    ):
        raise ReadinessFailure("labserver trust root is not one fixed Ed25519 principal")
    with tempfile.TemporaryDirectory(prefix="m2c-phase2-auth-") as directory:
        root = Path(directory)
        allowed = root / "allowed_signers"
        signature = root / "signature"
        allowed.write_bytes(allowed_signers_bytes)
        signature.write_text(receipt.signature_armored, encoding="ascii")
        completed = subprocess.run(
            [
                str(ssh_keygen),
                "-Y",
                "verify",
                "-f",
                str(allowed),
                "-I",
                LABSERVER_PRINCIPAL,
                "-n",
                DEPLOYMENT_AUTH_NAMESPACE,
                "-s",
                str(signature),
            ],
            input=canonical_json_bytes(receipt.core),
            capture_output=True,
            check=False,
            env={"LANG": "C", "LC_ALL": "C"},
        )
    if completed.returncode:
        raise ReadinessFailure("labserver Phase-2 deployment signature is invalid")


def _verify_audit_startup_and_linkage(
    payloads: Mapping[str, bytes],
    *,
    formal: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    qwen = _read_canonical_jsonl(
        payloads["qwen_service_audit"], schema="FormalQwenAuditEventV2", label="Qwen audit"
    )
    isaac_service = _read_canonical_jsonl(
        payloads["isaac_service_audit"],
        schema="FormalIsaacAuditEventV2",
        label="Isaac service audit",
    )
    isaac_session = _read_canonical_jsonl(
        payloads["isaac_session_audit"],
        schema="FormalIsaacAuditEventV2",
        label="Isaac session audit",
    )
    if (
        qwen[0].get("event_type") != "SERVICE_STARTED"
        or qwen[-1].get("event_type") != "SERVICE_STOPPED"
    ):
        raise ReadinessFailure("Qwen startup/clean-stop lifecycle is incomplete")
    if isaac_service[0].get("event_type") != "SERVICE_STARTED":
        raise ReadinessFailure("Isaac audit lacks the real service startup prefix")
    if isaac_session[0].get("event_type") != "SESSION_AUDIT_CREATED":
        raise ReadinessFailure("Isaac session lacks create-only startup binding")
    service_by_sequence = {record["sequence"]: record for record in isaac_service}
    if any(service_by_sequence.get(record["sequence"]) != record for record in isaac_session):
        raise ReadinessFailure("Isaac session audit is not an exact service-audit subset")
    if (
        formal.get("schema_version") != "M2CFormalSplitRunnerEvidenceV2"
        or formal.get("status") != "COMPLETE_REAL_PHYSICAL_EPISODE"
    ):
        raise ReadinessFailure("formal evidence is not one complete real physical episode")
    cycles = formal.get("wire_cycles")
    if not isinstance(cycles, list) or len(cycles) != 8:
        raise ReadinessFailure("formal evidence does not contain eight wire cycles")
    qwen_requests = [item for item in qwen if item.get("event_type") == "WIRE_REQUEST_RECEIVED"]
    qwen_responses = [item for item in qwen if item.get("event_type") == "WIRE_RESPONSE_COMMITTED"]
    isaac_requests = [
        item for item in isaac_service if item.get("event_type") == "WIRE_REQUEST_RECEIVED"
    ]
    isaac_responses = [
        item for item in isaac_service if item.get("event_type") == "WIRE_RESPONSE_COMMITTED"
    ]
    if (len(qwen_requests), len(qwen_responses), len(isaac_requests), len(isaac_responses)) != (
        8,
        8,
        18,
        18,
    ):
        raise ReadinessFailure(
            "host startup audits lack the exact authenticated transaction counts"
        )
    if any(item.get("event_type") == "WIRE_REQUEST_REJECTED" for item in (*qwen, *isaac_service)):
        raise ReadinessFailure("host startup/transaction audit contains a rejection")
    if isaac_responses[0].get("payload", {}).get("signed_wire", {}).get("payload") != formal.get(
        "start_response"
    ):
        raise ReadinessFailure("Isaac startup response differs from formal evidence")
    if [item.get("payload", {}).get("signed_wire") for item in qwen_requests] != [
        cycle["inference_request"] for cycle in cycles
    ] or [item.get("payload", {}).get("signed_wire") for item in qwen_responses] != [
        cycle["inference_response"] for cycle in cycles
    ]:
        raise ReadinessFailure("Qwen startup audit transaction differs from formal evidence")
    if [item.get("payload", {}).get("signed_wire") for item in isaac_requests[1:]] != [
        *[
            envelope
            for cycle in cycles
            for envelope in (cycle["capture_request"], cycle["execute_request"])
        ],
        formal["finalize_request"],
    ] or [item.get("payload", {}).get("signed_wire") for item in isaac_responses[1:]] != [
        *[
            envelope
            for cycle in cycles
            for envelope in (cycle["capture_response"], cycle["execute_response"])
        ],
        formal["finalize_response"],
    ]:
        raise ReadinessFailure("Isaac startup audit transaction differs from formal evidence")
    return qwen, isaac_service, isaac_session


def _audit_record(records: list[dict[str, Any]], digest: str, event_type: str) -> dict[str, Any]:
    matches = [
        record
        for record in records
        if sha256_bytes(canonical_json_bytes(record)) == digest
        and record.get("event_type") == event_type
    ]
    if len(matches) != 1:
        raise ReadinessFailure(f"signed audit lacks exactly one {event_type} record")
    return matches[0]


def _verify_exact_plan_evidence(
    raw: ExactPlanPhysicalEvidenceV1,
    *,
    index: Phase2EvidenceIndexV1,
    payloads: Mapping[str, bytes],
    session_audit: list[dict[str, Any]],
    closure: FormalTransitiveImportClosureManifestV1,
) -> None:
    if (
        raw.implementation_commit != index.implementation_commit
        or raw.container_image_digest != index.container_image_digest
        or raw.formal_evidence_sha256 != index.artifacts["formal_evidence"].sha256
        or raw.isaac_session_audit_sha256 != index.artifacts["isaac_session_audit"].sha256
    ):
        raise ReadinessFailure("exact-plan evidence differs from deployment/formal identity")
    formal = _json_object(payloads["formal_evidence"], label="formal evidence")
    session_id = formal.get("start_response", {}).get("session_id")
    if (raw.run_id, raw.session_id) != (formal.get("run_id"), session_id):
        raise ReadinessFailure("exact-plan evidence differs from formal run/session")
    for validation in raw.validations:
        plan = validation.plan
        preflight = validation.preflight_receipt
        execution = validation.execution_receipt
        cycle = formal["wire_cycles"][validation.decision_index]
        capture = cycle.get("capture_response", {}).get("payload", {})
        inference = cycle.get("inference_response", {})
        execute_request = cycle.get("execute_request", {}).get("payload", {})
        execute = cycle.get("execute_response", {}).get("payload", {})
        observation = capture.get("observation", {})
        mapping = execute.get("mapping", {})
        source_by_role = {source.role: source.sha256 for source in plan.source_bindings}
        expected_a1 = {
            "observation_id": execute_request.get("observation_id"),
            "capture_receipt_sha256": execute_request.get("capture_receipt_sha256"),
            "rgb_sha256": observation.get("rgb", {}).get("sha256"),
            "depth_sha256": observation.get("depth", {}).get("sha256"),
            "canonical_public_tracks_sha256": canonical_candidate_sha256_v3(
                build_public_track_candidates_v3(
                    observation.get("perception_tracks", []),
                    declared_target_attribute="yellow",
                )
            ),
            "signed_model_inference_response_sha256": canonical_sha256(inference),
            "runtime_mapping_sha256": canonical_sha256(mapping),
            "canonical_skill": mapping.get("canonical_skill"),
            "runtime_action": mapping.get("runtime_action"),
            "target_track_id": mapping.get("target_track_id"),
            "resolved_execution_parameters_sha256": canonical_sha256(
                mapping.get("execution_parameters")
            ),
        }
        if (
            plan.inputs.run_id != raw.run_id
            or plan.inputs.session_id != raw.session_id
            or plan.inputs.decision_index != validation.decision_index
            or plan.inputs.canonical_skill != validation.canonical_skill
            or plan.inputs.immutable_commit != index.implementation_commit
            or plan.inputs.container_image_digest != index.container_image_digest
            or any(getattr(plan.inputs, field) != value for field, value in expected_a1.items())
            or execute.get("exact_execution_plan")
            != plan.exact_execution_plan.model_dump(mode="json")
            or execute.get("exact_execution_plan_sha256") != plan.exact_execution_plan_sha256
            or execute.get("executed_exact_execution_plan_sha256")
            != plan.exact_execution_plan_sha256
        ):
            raise ReadinessFailure("exact-plan A.1 identity differs from physical validation")
        if any(closure.files.get(source.path) != source.sha256 for source in plan.source_bindings):
            raise ReadinessFailure("exact-plan source binding is absent from transitive closure")
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
            raise ReadinessFailure("preflight gate algorithm/config hashes differ from closure")
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
            raise ReadinessFailure("preflight is not the immutable complete plan gate set")
        if (
            execution.bound_plan_sha256 != plan.bound_plan_sha256
            or execution.preflight_receipt_sha256 != preflight.receipt_sha256
            or execution.status != "PASS"
            or not execution.real_isaac
            or not execution.formal_evidence
            or len(execution.phase_receipts) != len(phases)
        ):
            raise ReadinessFailure("bundle execution is not a complete real-Isaac PASS")
        for result, phase in zip(execution.phase_receipts, phases, strict=True):
            if (
                result.bound_plan_sha256 != plan.bound_plan_sha256
                or result.phase_index != phase.phase.phase_index
                or result.phase_sha256 != phase.phase_sha256
                or result.status != "PASS"
                or not result.operation_executed
                or not result.real_isaac
                or result.contract_test_only
            ):
                raise ReadinessFailure("physical phase receipt differs from precomputed plan")
        preflight_record = _audit_record(
            session_audit,
            validation.preflight_audit_record_sha256,
            "ADR0022_EXACT_PLAN_PREFLIGHT_COMMITTED",
        )
        phase_records = [
            _audit_record(
                session_audit,
                digest,
                "ADR0022_EXACT_PLAN_PHASE_RECEIPT_COMMITTED",
            )
            for digest in validation.phase_audit_record_sha256
        ]
        execution_record = _audit_record(
            session_audit,
            validation.execution_audit_record_sha256,
            "ADR0022_EXACT_PLAN_BUNDLE_RECEIPT_COMMITTED",
        )
        if len(phase_records) != len(phases):
            raise ReadinessFailure("signed audit phase-receipt count differs from plan")
        expected = {
            "run_id": raw.run_id,
            "session_id": raw.session_id,
            "decision_index": validation.decision_index,
            "canonical_skill": validation.canonical_skill,
            "bound_plan_sha256": plan.bound_plan_sha256,
        }
        if any(
            preflight_record.get("payload", {}).get(key) != value for key, value in expected.items()
        ):
            raise ReadinessFailure("signed preflight audit identity differs")
        if preflight_record.get("payload", {}).get("receipt_sha256") != preflight.receipt_sha256:
            raise ReadinessFailure("signed preflight audit receipt differs")
        for record, result in zip(phase_records, execution.phase_receipts, strict=True):
            if record.get("payload", {}).get("phase_receipt_sha256") != canonical_sha256(result):
                raise ReadinessFailure("signed physical phase audit receipt differs")
        if execution_record.get("payload", {}).get("execution_receipt_sha256") != canonical_sha256(
            execution
        ):
            raise ReadinessFailure("signed bundle execution audit receipt differs")


def _verify_b0_evidence(
    raw: FrozenB0ActiveSessionPhysicalEvidenceV1,
    *,
    index: Phase2EvidenceIndexV1,
    audit: list[dict[str, Any]],
    closure: FormalTransitiveImportClosureManifestV1,
    manifest_receipt_sha256: str,
    frozen_source_bindings: Mapping[str, str],
) -> None:
    binding = raw.active_session_binding
    receipt = raw.receipt
    if (
        binding.immutable_commit != index.implementation_commit
        or binding.container_image_digest != index.container_image_digest
        or binding.wrapper_entrypoint_path != WRAPPER_PATH
        or binding.wrapper_entrypoint_sha256 != index.b0_runtime_wrapper.sha256
        or closure.files.get(binding.wrapper_entrypoint_path) != binding.wrapper_entrypoint_sha256
        or closure.files.get(binding.active_session_b0_entrypoint_path) != FROZEN_B0_PROBE_SHA256
        or binding.freeze_manifest_sha256 != FROZEN_B0_MANIFEST_SHA256
        or receipt.manifest_receipt_sha256 != manifest_receipt_sha256
        or any(closure.files.get(path) != digest for path, digest in frozen_source_bindings.items())
    ):
        raise ReadinessFailure("active-session B0 binding differs from frozen closure")
    if (
        receipt.request_sha256 != canonical_sha256(raw.request)
        or receipt.invocation_argv_sha256 != binding.exact_argv_sha256
        or receipt.invocation_environment_sha256 != binding.exact_environment_sha256
        or not receipt.physically_executed
        or receipt.execution_source != "B0_FALLBACK"
        or receipt.executed_skill != "B0_FALLBACK"
        or receipt.status not in {"PASS", "FAILED"}
        or not receipt.active_session_compatible
        or receipt.pure_model_success_eligible
    ):
        raise ReadinessFailure("B0 receipt is not a real unchanged active-session invocation")
    record = _audit_record(audit, raw.audit_record_sha256, "ADR0022_FROZEN_B0_FALLBACK_COMMITTED")
    payload = record.get("payload", {})
    if (
        payload.get("run_id") != raw.request.run_id
        or payload.get("session_id") != raw.request.session_id
        or payload.get("decision_index") != raw.request.decision_index
        or payload.get("request_sha256") != canonical_sha256(raw.request)
        or payload.get("receipt_sha256") != receipt.receipt_sha256
        or payload.get("execution_source") != "B0_FALLBACK"
        or payload.get("pure_model_success_eligible") is not False
    ):
        raise ReadinessFailure("signed B0 validation audit differs from physical receipt")


def verify_phase2_evidence(
    project: Path, evidence_index_path: Path
) -> tuple[Phase2EvidenceIndexV1, dict[str, Any]]:
    project = project.resolve()
    index_path = evidence_index_path.resolve()
    index = Phase2EvidenceIndexV1.model_validate(
        _json_object(read_regular_file_once(index_path), label="Phase-2 evidence index")
    )
    _require_ancestor_commit(project, index.implementation_commit)
    evidence_root = index_path.parent
    project_payloads = {
        "formal_runner": _verify_project_binding(
            project, index.implementation_commit, index.formal_runner
        ),
        "primitive_bundle": _verify_project_binding(
            project, index.implementation_commit, index.primitive_bundle
        ),
        "b0_runtime_wrapper": _verify_project_binding(
            project, index.implementation_commit, index.b0_runtime_wrapper
        ),
        "offline_wire_verifier": _verify_project_binding(
            project, index.implementation_commit, index.offline_wire_verifier
        ),
        "node2_trust_root": _verify_project_binding(
            project, index.implementation_commit, index.node2_trust_root
        ),
        "labserver_trust_root": _verify_project_binding(
            project, index.implementation_commit, index.labserver_trust_root
        ),
    }
    payloads = _read_bound_files(
        evidence_root,
        {**index.artifacts, "deployment_attestation": index.deployment_attestation},
    )
    attestation_bytes = payloads.pop("deployment_attestation")
    formal = _json_object(payloads["formal_evidence"], label="formal evidence")
    qwen_audit, isaac_audit, isaac_session = _verify_audit_startup_and_linkage(
        payloads, formal=formal
    )
    closure = FormalTransitiveImportClosureManifestV1.model_validate(
        _json_object(payloads["transitive_import_manifest"], label="transitive closure")
    )
    if (
        closure.implementation_commit != index.implementation_commit
        or closure.container_image_digest != index.container_image_digest
        or any(
            closure.files.get(binding.path) != binding.sha256
            for binding in (
                index.formal_runner,
                index.primitive_bundle,
                index.b0_runtime_wrapper,
                index.offline_wire_verifier,
                index.node2_trust_root,
                index.labserver_trust_root,
            )
        )
    ):
        raise ReadinessFailure("transitive closure lacks the exact runtime/trust sources")
    auth = {
        "NODE2_QWEN": SignedHostWireAuthenticationReceiptV1.model_validate(
            _json_object(payloads["node2_wire_auth_receipt"], label="node2 auth receipt")
        ),
        "LABSERVER_ISAAC": SignedHostWireAuthenticationReceiptV1.model_validate(
            _json_object(payloads["labserver_wire_auth_receipt"], label="labserver auth receipt")
        ),
    }
    for role, receipt in auth.items():
        if receipt.core.host_role != role:
            raise ReadinessFailure("host wire authentication roles are swapped")
        trust = project_payloads[
            "node2_trust_root" if role == "NODE2_QWEN" else "labserver_trust_root"
        ]
        verify_receipt_signature(receipt, allowed_signers_bytes=trust)
        if (
            receipt.core.formal_evidence_sha256 != index.artifacts["formal_evidence"].sha256
            or receipt.core.public_trust_root_sha256 != sha256_bytes(trust)
            or receipt.core.run_id != formal.get("run_id")
            or receipt.core.challenge_nonce != formal.get("challenge_nonce")
            or receipt.core.verifier_implementation_path != index.offline_wire_verifier.path
            or receipt.core.verifier_implementation_sha256 != index.offline_wire_verifier.sha256
        ):
            raise ReadinessFailure("host wire receipt differs from evidence/trust root")
    if (
        auth["NODE2_QWEN"].core.service_audit_sha256 != index.artifacts["qwen_service_audit"].sha256
        or auth["LABSERVER_ISAAC"].core.service_audit_sha256
        != index.artifacts["isaac_service_audit"].sha256
        or auth["LABSERVER_ISAAC"].core.session_audit_sha256
        != index.artifacts["isaac_session_audit"].sha256
    ):
        raise ReadinessFailure("host wire receipts do not bind the audited startup transcripts")
    from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
        FORMAL_INFERENCE_PATH,
        FORMAL_ISAAC_CAPTURE_PATH,
        FORMAL_ISAAC_EXECUTE_PATH,
        FORMAL_ISAAC_FINALIZE_PATH,
        FORMAL_ISAAC_START_PATH,
    )

    isaac_paths = [FORMAL_ISAAC_START_PATH]
    for _ in range(8):
        isaac_paths.extend((FORMAL_ISAAC_CAPTURE_PATH, FORMAL_ISAAC_EXECUTE_PATH))
    isaac_paths.append(FORMAL_ISAAC_FINALIZE_PATH)
    if auth["NODE2_QWEN"].core.envelope_set_sha256 != canonical_envelope_set_sha256(
        qwen_audit, expected_paths=[FORMAL_INFERENCE_PATH] * 8
    ) or auth["LABSERVER_ISAAC"].core.envelope_set_sha256 != canonical_envelope_set_sha256(
        isaac_audit, expected_paths=isaac_paths
    ):
        raise ReadinessFailure("host wire receipt envelope-set digest differs from audit")
    attestation = SignedPhase2DeploymentAttestationV1.model_validate(
        _json_object(attestation_bytes, label="deployment attestation")
    )
    if (
        attestation.core.implementation_commit != index.implementation_commit
        or attestation.core.container_image_digest != index.container_image_digest
        or attestation.core.artifact_sha256
        != {name: binding.sha256 for name, binding in index.artifacts.items()}
        or attestation.core.public_trust_root_sha256 != index.labserver_trust_root.sha256
    ):
        raise ReadinessFailure("deployment attestation differs from the complete evidence index")
    _verify_deployment_signature(
        attestation, allowed_signers_bytes=project_payloads["labserver_trust_root"]
    )
    exact = ExactPlanPhysicalEvidenceV1.model_validate(
        _json_object(payloads["exact_plan_physical_evidence"], label="exact-plan evidence")
    )
    _verify_exact_plan_evidence(
        exact,
        index=index,
        payloads=payloads,
        session_audit=isaac_session,
        closure=closure,
    )
    b0_audit = _read_canonical_jsonl(
        payloads["b0_validation_audit"],
        schema="M2CPhase2B0ValidationAuditEventV1",
        label="B0 validation audit",
    )
    b0 = FrozenB0ActiveSessionPhysicalEvidenceV1.model_validate(
        _json_object(payloads["b0_active_session_evidence"], label="B0 evidence")
    )
    if b0.b0_validation_audit_sha256 != index.artifacts["b0_validation_audit"].sha256:
        raise ReadinessFailure("B0 evidence differs from its signed validation audit")
    b0_manifest = FrozenB0FallbackWrapperV1(project_root=project).verify_frozen_sources()
    _verify_b0_evidence(
        b0,
        index=index,
        audit=b0_audit,
        closure=closure,
        manifest_receipt_sha256=canonical_sha256(b0_manifest),
        frozen_source_bindings={item.path: item.sha256 for item in b0_manifest.source_bindings},
    )
    return index, {
        "implementation_commit": index.implementation_commit,
        "container_image_digest": index.container_image_digest,
        "transitive_import_manifest_sha256": index.artifacts["transitive_import_manifest"].sha256,
        "formal_runner_binding": [index.formal_runner.path, index.formal_runner.sha256],
        "frozen_b0_runtime_wrapper_binding": [
            index.b0_runtime_wrapper.path,
            index.b0_runtime_wrapper.sha256,
        ],
        "offline_wire_authentication_verifier_binding": {
            "NODE2_QWEN": [
                index.offline_wire_verifier.path,
                index.offline_wire_verifier.sha256,
                index.node2_trust_root.path,
                index.node2_trust_root.sha256,
            ],
            "LABSERVER_ISAAC": [
                index.offline_wire_verifier.path,
                index.offline_wire_verifier.sha256,
                index.labserver_trust_root.path,
                index.labserver_trust_root.sha256,
            ],
        },
        "exact_plan_skills_verified": list(SKILLS),
        "active_session_unchanged_b0_verified": True,
        "host_startup_and_wire_authentication_verified": True,
        "deployment_attestation_sha256": index.deployment_attestation.sha256,
    }


def build_readiness_report(
    project: Path, evidence_index_path: Path | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    blockers: list[str] = []
    verified: dict[str, Any] | None = None
    if evidence_index_path is None:
        blockers.extend(
            [
                "PHASE2_EVIDENCE_INDEX_MISSING",
                "REAL_EXACT_PLAN_EIGHT_SKILL_RECEIPTS_MISSING",
                "ACTIVE_SESSION_UNCHANGED_B0_RECEIPT_MISSING",
                "SIGNED_HOST_STARTUP_AND_DEPLOYMENT_ATTESTATION_MISSING",
                "NODE2_LABSERVER_WIRE_TRUST_ROOTS_MISSING",
                "CONTAINER_TRANSITIVE_IMPORT_CLOSURE_MISSING",
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
            "verified": verified,
            "blockers": blockers,
            "required_trust_root_paths": [NODE2_TRUST_ROOT_PATH, LABSERVER_TRUST_ROOT_PATH],
            "required_real_evidence": [
                "eight real-Isaac exact-plan/preflight/phase/bundle receipts in signed audit",
                "real active-session unchanged-B0 invocation receipt in signed audit",
                "node2 and labserver host-local HMAC verification receipts with Ed25519 signatures",
                "strict Qwen/Isaac startup lifecycle and signed START request/response",
                "immutable commit, container digest, complete transitive import and asset closure",
            ],
            "governance": {
                "four_source_bindings_changed": False,
                "training_executed": False,
                "formal_q_b_evaluation_executed": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "contract_or_mock_counted_as_physical_evidence": False,
            },
        },
        verified,
    )


def render_binding_proposal(verified: Mapping[str, Any], *, addendum_sha256: str) -> bytes:
    proposal = {
        "schema_version": "M2CS4UnlockBindingProposalV1",
        "status": "EVIDENCE_VERIFIED_REQUIRES_SEPARATE_REVIEWED_SOURCE_COMMIT",
        "adr_path": ADR_PATH,
        "binding_addendum_path": ADDENDUM_PATH,
        "binding_addendum_sha256": addendum_sha256,
        "FORMAL_PHYSICAL_RUNNER_BINDING": verified["formal_runner_binding"],
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING": [
            verified["implementation_commit"],
            verified["container_image_digest"],
            verified["transitive_import_manifest_sha256"],
        ],
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING": verified["frozen_b0_runtime_wrapper_binding"],
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING": verified[
            "offline_wire_authentication_verifier_binding"
        ],
        "applied_to_source": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return (json.dumps(proposal, indent=2, sort_keys=True) + "\n").encode()


def render_binding_addendum(verified: Mapping[str, Any]) -> bytes:
    skills = ", ".join(f"`{skill}`" for skill in verified["exact_plan_skills_verified"])
    content = f"""# ADR-0022 Phase-2 binding addendum

- Status: **EVIDENCE VERIFIED; SEPARATE REVIEWED SOURCE-BINDING COMMIT REQUIRED**
- Governing ADR: `{ADR_PATH}`
- Immutable implementation commit: `{verified["implementation_commit"]}`
- Container image digest: `{verified["container_image_digest"]}`
- Transitive import manifest SHA-256: `{verified["transitive_import_manifest_sha256"]}`
- Source bindings changed by this addendum generator: **false**
- Teacher used: **false**
- Privileged truth policy input: **false**

The create-only Phase-2 verifier checked the complete byte-bound evidence set,
both host-local wire-authentication signatures, startup lifecycle, immutable
deployment closure, real exact-plan phase receipts, and the active-session
unchanged-B0 wrapper receipt. This document proposes bindings for a separate
reviewed commit; it does not itself unlock S4, training, or Q-B evaluation.

## Exact-plan primitive

Verified real-Isaac skill coverage: {skills}.

Formal runner binding: `{verified["formal_runner_binding"]}`.

## Unchanged B0 wrapper

Active-session unchanged-B0 invocation verified: **true**.
Wrapper binding: `{verified["frozen_b0_runtime_wrapper_binding"]}`.

## Host authentication and startup

Node2 and labserver host-local HMAC receipts, Ed25519 public trust roots,
canonical append-only audits, and the signed Isaac START transaction were
cross-bound to the same formal evidence and deployment attestation.

## Application boundary

`{UNLOCK_CONFIG_PATH}` is a proposal only. Applying any of the four bindings
still requires one separately reviewed source commit referencing ADR-0022 and
this addendum. No generated artifact may be backfilled onto earlier evidence.
"""
    return content.encode()
