"""Host-local HMAC replay receipts and legacy OpenSSH attestations.

Each host verifies only its own symmetric-key transcript.  The two HMAC keys
are never brought together or serialized.  ADR-0024 withdrew OpenSSH signing
as an S4 entry precondition.  ``HostWireHMACVerificationReceiptV2`` is the
current unsigned, byte-bound receipt; the V1 SSH types remain only so older
evidence can be audited without reinterpreting it.
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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    IsaacCaptureRequestV2,
    IsaacCaptureResponseV2,
    IsaacExecuteRequestV2,
    IsaacExecuteResponseV2,
    IsaacFinalizeRequestV2,
    IsaacFinalizeResponseV2,
    IsaacStartRequestV2,
    IsaacStartResponseV2,
    canonical_json_bytes,
    canonical_sha256,
    verify_inference_request,
    verify_inference_response,
    verify_wire_message,
)


AUTH_NAMESPACE = "m2c-wire-auth-v1@xh-agent"
NODE2_PRINCIPAL = "m2c-node2-qwen-evidence-authority"
LABSERVER_PRINCIPAL = "m2c-labserver-isaac-evidence-authority"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
HostRole = Literal["NODE2_QWEN", "LABSERVER_ISAAC"]
HOST_HMAC_VERIFIER_IMPLEMENTATION_PATH = "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py"
WIRE_CHALLENGE_MANIFEST_PATH = "configs/m2c_s4_wire_challenges.json"
CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT = "/var/lib/xh-agent/m2c-s4-wire-challenge-consumption-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class HostWireAuthenticationCoreV1(StrictModel):
    schema_version: Literal["M2CHostWireAuthenticationCoreV1"] = "M2CHostWireAuthenticationCoreV1"
    host_role: HostRole
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    formal_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    service_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    session_audit_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    envelope_set_sha256: str = Field(pattern=SHA256_PATTERN)
    authenticated_envelope_count: int
    request_envelope_count: int
    response_envelope_count: int
    verifier_implementation_path: str = Field(min_length=1)
    verifier_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    public_trust_root_sha256: str = Field(pattern=SHA256_PATTERN)
    signature_scheme: Literal["OPENSSH_ED25519_SSHSIG"] = "OPENSSH_ED25519_SSHSIG"
    signature_namespace: Literal[AUTH_NAMESPACE] = AUTH_NAMESPACE
    signer_principal: str = Field(min_length=1)
    audit_cleanly_stopped: Literal[True] = True
    all_hmac_valid: Literal[True] = True
    hmac_secret_exported: Literal[False] = False
    hmac_secret_persisted_in_receipt: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def role_has_exact_counts_and_principal(self) -> "HostWireAuthenticationCoreV1":
        expected = {
            "NODE2_QWEN": (16, 8, 8, NODE2_PRINCIPAL, False),
            "LABSERVER_ISAAC": (36, 18, 18, LABSERVER_PRINCIPAL, True),
        }[self.host_role]
        observed = (
            self.authenticated_envelope_count,
            self.request_envelope_count,
            self.response_envelope_count,
            self.signer_principal,
            self.session_audit_sha256 is not None,
        )
        if observed != expected:
            raise ValueError("host authentication role/count/principal contract differs")
        return self


class SignedHostWireAuthenticationReceiptV1(StrictModel):
    schema_version: Literal["M2CSignedHostWireAuthenticationReceiptV1"] = (
        "M2CSignedHostWireAuthenticationReceiptV1"
    )
    core: HostWireAuthenticationCoreV1
    signature_armored: str = Field(
        pattern=r"^-----BEGIN SSH SIGNATURE-----[\s\S]+-----END SSH SIGNATURE-----\n?$"
    )


class HostWireHMACVerificationCoreV2(StrictModel):
    """Public result of one host replaying only its own HMAC transcript."""

    schema_version: Literal["M2CHostWireHMACVerificationCoreV2"] = (
        "M2CHostWireHMACVerificationCoreV2"
    )
    host_role: HostRole
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    formal_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    service_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    session_audit_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    envelope_set_sha256: str = Field(pattern=SHA256_PATTERN)
    authenticated_envelope_count: int
    request_envelope_count: int
    response_envelope_count: int
    verifier_implementation_path: Literal[HOST_HMAC_VERIFIER_IMPLEMENTATION_PATH] = (
        HOST_HMAC_VERIFIER_IMPLEMENTATION_PATH
    )
    verifier_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    audit_cleanly_stopped: Literal[True] = True
    all_hmac_valid: Literal[True] = True
    hmac_secret_exported: Literal[False] = False
    hmac_secret_persisted_in_receipt: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def role_has_exact_counts(self) -> "HostWireHMACVerificationCoreV2":
        expected = {
            "NODE2_QWEN": (16, 8, 8, False),
            "LABSERVER_ISAAC": (36, 18, 18, True),
        }[self.host_role]
        observed = (
            self.authenticated_envelope_count,
            self.request_envelope_count,
            self.response_envelope_count,
            self.session_audit_sha256 is not None,
        )
        if observed != expected:
            raise ValueError("host HMAC receipt role/count/session contract differs")
        return self


class HostWireHMACVerificationReceiptV2(StrictModel):
    schema_version: Literal["M2CHostWireHMACVerificationReceiptV2"] = (
        "M2CHostWireHMACVerificationReceiptV2"
    )
    core: HostWireHMACVerificationCoreV2


class WireChallengeConsumptionReceiptV1(StrictModel):
    """Create-only proof that one preregistered challenge was claimed once."""

    schema_version: Literal["M2CWireChallengeConsumptionReceiptV1"] = (
        "M2CWireChallengeConsumptionReceiptV1"
    )
    status: Literal["CONSUMED_BEFORE_ENDPOINT_CONTACT"] = "CONSUMED_BEFORE_ENDPOINT_CONTACT"
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=SHA256_PATTERN)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    challenge_manifest_path: Literal[WIRE_CHALLENGE_MANIFEST_PATH] = WIRE_CHALLENGE_MANIFEST_PATH
    challenge_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    ledger_root: str = Field(min_length=1)
    consumption_id: str = Field(pattern=SHA256_PATTERN)
    consumed_at_ns: int = Field(gt=0)
    create_only_o_excl: Literal[True] = True
    remains_consumed_after_rejection_or_failure: Literal[True] = True
    endpoint_contact_before_consumption_allowed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def deterministic_consumption_identity(self) -> "WireChallengeConsumptionReceiptV1":
        if Path(self.ledger_root) != Path(CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT):
            raise ValueError("wire challenge consumption ledger root is not canonical")
        expected = wire_challenge_consumption_id(
            challenge_nonce=self.challenge_nonce,
            challenge_manifest_sha256=self.challenge_manifest_sha256,
        )
        if self.consumption_id != expected:
            raise ValueError("wire challenge consumption ID is not canonical")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wire_challenge_consumption_id(
    *,
    challenge_nonce: str,
    challenge_manifest_sha256: str,
) -> str:
    if (
        re.fullmatch(SHA256_PATTERN, challenge_nonce) is None
        or re.fullmatch(SHA256_PATTERN, challenge_manifest_sha256) is None
    ):
        raise ValueError("wire challenge consumption identity contains malformed SHA-256")
    return canonical_sha256(
        {
            "namespace": "m2c-wire-challenge-consumption-v1",
            "challenge_nonce": challenge_nonce,
            "challenge_manifest_sha256": challenge_manifest_sha256,
        }
    )


def wire_challenge_consumption_path(ledger_directory: Path, challenge_nonce: str) -> Path:
    if re.fullmatch(SHA256_PATTERN, challenge_nonce) is None:
        raise ValueError("wire challenge nonce is malformed")
    return ledger_directory / f"consumed-{challenge_nonce}.json"


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise NotADirectoryError(path)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def consume_wire_challenge_create_only(
    *,
    ledger_directory: Path,
    challenge_manifest_path: Path,
    run_id: str,
    challenge_nonce: str,
    matched_key: str,
    scene_seed: int,
    failure_seed: int,
    consumed_at_ns: int,
) -> tuple[Path, WireChallengeConsumptionReceiptV1]:
    """Atomically consume a preregistered challenge before endpoint contact."""

    if ledger_directory.resolve() != Path(CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT).resolve():
        raise ValueError("wire challenge consumption ledger root is not canonical")
    manifest_bytes = read_regular_file_once(challenge_manifest_path)
    manifest_sha256 = sha256_bytes(manifest_bytes)
    manifest = _parse_json_object(manifest_bytes, label="wire challenge manifest")
    if (
        manifest.get("schema_version") != "M2CS4WireChallengeManifestV1"
        or manifest.get("formal_q_b_evaluation_authorized") is not False
        or manifest.get("teacher_used") is not False
        or manifest.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("wire challenge manifest governance differs")
    matches = [
        item
        for item in manifest.get("challenge_records", [])
        if isinstance(item, dict)
        and item.get("run_id") == run_id
        and item.get("challenge_nonce") == challenge_nonce
        and item.get("matched_key") == matched_key
        and item.get("scene_seed") == scene_seed
        and item.get("failure_seed") == failure_seed
    ]
    if len(matches) != 1:
        raise ValueError("wire challenge consumption does not match one preregistration")
    receipt = WireChallengeConsumptionReceiptV1(
        run_id=run_id,
        challenge_nonce=challenge_nonce,
        matched_key=matched_key,
        scene_seed=scene_seed,
        failure_seed=failure_seed,
        challenge_manifest_sha256=manifest_sha256,
        ledger_root=str(ledger_directory.resolve()),
        consumption_id=wire_challenge_consumption_id(
            challenge_nonce=challenge_nonce,
            challenge_manifest_sha256=manifest_sha256,
        ),
        consumed_at_ns=consumed_at_ns,
    )
    payload = canonical_json_bytes(receipt) + b"\n"
    ledger_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_stat = ledger_directory.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(directory_stat.st_mode)
        or ledger_directory.is_symlink()
        or directory_stat.st_uid != os.geteuid()
        or directory_stat.st_mode & 0o077
    ):
        raise PermissionError("wire challenge consumption ledger directory is unsafe")
    path = wire_challenge_consumption_path(ledger_directory, challenge_nonce)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o400)
    try:
        # Persist the exclusive name before writing.  From this point onward
        # every failure leaves a permanent tombstone, so the challenge can
        # never be retried after an ambiguous durability outcome.
        _fsync_directory(ledger_directory)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("wire challenge consumption write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(ledger_directory)
    return path, receipt


def load_consumed_wire_challenge_from_canonical_ledger(
    *,
    ledger_directory: Path,
    challenge_nonce: str,
    run_id: str,
    matched_key: str,
    scene_seed: int,
    failure_seed: int,
) -> tuple[Path, WireChallengeConsumptionReceiptV1, str]:
    """Re-read one immutable canonical ledger receipt before endpoint contact."""

    canonical_root = Path(CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT).resolve()
    if ledger_directory.resolve() != canonical_root:
        raise ValueError("wire challenge consumption ledger root is not canonical")
    path = wire_challenge_consumption_path(ledger_directory, challenge_nonce)
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o277
    ):
        raise PermissionError(
            "wire challenge consumption receipt is not immutable private evidence"
        )
    raw = read_regular_file_once(path)
    receipt = WireChallengeConsumptionReceiptV1.model_validate(
        _parse_json_object(raw, label="wire challenge consumption receipt")
    )
    if raw != canonical_json_bytes(receipt) + b"\n":
        raise ValueError("wire challenge consumption receipt is not canonical JSON")
    expected = (run_id, challenge_nonce, matched_key, scene_seed, failure_seed)
    observed = (
        receipt.run_id,
        receipt.challenge_nonce,
        receipt.matched_key,
        receipt.scene_seed,
        receipt.failure_seed,
    )
    if observed != expected:
        raise ValueError("wire challenge consumption receipt differs from requested run")
    return path, receipt, sha256_bytes(raw)


def read_regular_file_once(path: Path, *, require_private: bool = False) -> bytes:
    """Read one regular file through one non-following descriptor.

    Metadata is checked before and after the read so a path swap or in-place
    rewrite cannot silently change the bytes being authenticated.
    """

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("wire authentication input must be a regular file")
        if require_private:
            if before.st_uid != os.geteuid() or before.st_mode & 0o077:
                raise PermissionError("private signing key must be current-user mode 0600")
            if before.st_nlink != 1:
                raise PermissionError("private signing key must have exactly one hard link")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
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
        data = b"".join(chunks)
        if identity_before != identity_after or len(data) != before.st_size:
            raise ValueError("wire authentication input changed while it was read")
        return data
    finally:
        os.close(descriptor)


def _write_private_file(path: Path, data: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("failed to write private authentication material")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ssh_environment() -> dict[str, str]:
    return {"LANG": "C", "LC_ALL": "C"}


def _validate_allowed_signers_bytes(data: bytes, *, principal: str) -> None:
    escaped = re.escape(principal.encode("ascii"))
    pattern = rb"^" + escaped + rb" ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\x00\r\n]+)?\n?$"
    if re.fullmatch(pattern, data) is None:
        raise ValueError(
            "allowed-signers trust root must contain exactly the fixed principal "
            "and one Ed25519 public key"
        )


def _parse_json_object(data: bytes, *, label: str) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be one JSON object")
    return value


def _read_canonical_audit(data: bytes, *, schema: str, label: str) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise ValueError(f"{label} is not newline-terminated canonical JSONL")
    lines = data.splitlines()
    records = [json.loads(line) for line in lines]
    if not records or any(not isinstance(item, dict) for item in records):
        raise ValueError(f"{label} is empty or non-object")
    first_sequence = records[0].get("sequence")
    if first_sequence != 1 or any(
        item.get("schema_version") != schema
        or item.get("sequence") != first_sequence + index - 1
        or canonical_json_bytes(item) != lines[index - 1]
        for index, item in enumerate(records, start=1)
    ):
        raise ValueError(f"{label} is not canonical contiguous JSONL")
    if any(item.get("event_type") == "WIRE_REQUEST_REJECTED" for item in records):
        raise ValueError(f"{label} contains a rejected request")
    return records


def _wire_events(
    records: list[dict[str, Any]],
    *,
    expected_paths: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    wire_records = [
        item
        for item in records
        if item.get("event_type") in {"WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED"}
    ]
    expected_event_types = [
        expected
        for _ in range(len(wire_records) // 2)
        for expected in ("WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED")
    ]
    observed_event_types = [item.get("event_type") for item in wire_records]
    if len(wire_records) % 2 or observed_event_types != expected_event_types:
        raise ValueError("wire audit is not the exact request/response sequence")
    if len(wire_records) != 2 * len(expected_paths):
        raise ValueError("wire audit path count differs from the expected transaction")
    observed_paths = [item.get("payload", {}).get("path") for item in wire_records]
    expected_wire_paths = [path for path in expected_paths for _ in range(2)]
    if observed_paths != expected_wire_paths:
        raise ValueError("wire audit endpoint path sequence differs")
    ordered = [item.get("payload", {}).get("signed_wire") for item in wire_records]
    if any(not isinstance(item, dict) for item in ordered):
        raise ValueError("wire audit contains a missing/non-object envelope")
    transcript = [
        {
            "event_type": item["event_type"],
            "path": item["payload"]["path"],
            "signed_wire": item["payload"]["signed_wire"],
        }
        for item in wire_records
    ]
    return ordered[0::2], ordered[1::2], transcript


def canonical_envelope_set_sha256(
    records: list[dict[str, Any]],
    *,
    expected_paths: list[str],
) -> str:
    """Return the exact ordered request/response transcript digest."""

    _, _, transcript = _wire_events(records, expected_paths=expected_paths)
    return canonical_sha256(transcript)


def _formal_identity(formal: Mapping[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    if (
        formal.get("schema_version") != "M2CFormalSplitRunnerEvidenceV2"
        or formal.get("status") != "COMPLETE_REAL_PHYSICAL_EPISODE"
        or formal.get("synthetic") is not False
        or formal.get("mocked_physics") is not False
        or formal.get("teacher_used") is not False
        or formal.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("formal evidence is not complete real-physical V2 evidence")
    cycles = formal.get("wire_cycles")
    if not isinstance(cycles, list) or len(cycles) != 8:
        raise ValueError("formal evidence does not contain exactly eight wire cycles")
    run_id = formal.get("run_id")
    challenge = formal.get("challenge_nonce")
    if not isinstance(run_id, str) or not re.fullmatch(SHA256_PATTERN, str(challenge)):
        raise ValueError("formal evidence run/challenge identity is malformed")
    return run_id, str(challenge), cycles


def verify_node2_qwen_transcript(
    formal_bytes: bytes,
    audit_bytes: bytes,
    *,
    secret: bytes,
) -> tuple[str, str, str]:
    formal = _parse_json_object(formal_bytes, label="formal evidence")
    run_id, challenge, cycles = _formal_identity(formal)
    records = _read_canonical_audit(
        audit_bytes,
        schema="FormalQwenAuditEventV2",
        label="Qwen service audit",
    )
    from xh_agent.policy.qrm_lite.formal_split_runner_v2 import FORMAL_INFERENCE_PATH

    requests, responses, ordered = _wire_events(
        records,
        expected_paths=[FORMAL_INFERENCE_PATH] * 8,
    )
    if len(requests) != 8 or len(responses) != 8:
        raise ValueError("Qwen audit does not contain exactly eight request/response pairs")
    expected_requests = [item["inference_request"] for item in cycles]
    expected_responses = [item["inference_response"] for item in cycles]
    if requests != expected_requests or responses != expected_responses:
        raise ValueError("Qwen audit differs from formal evidence")
    for index, (request, response) in enumerate(zip(requests, responses)):
        signed_request = verify_inference_request(request, secret)
        signed_response = verify_inference_response(response, secret)
        if (
            signed_request.payload.run_id != run_id
            or signed_request.payload.challenge_nonce != challenge
            or signed_request.payload.decision_index != index
            or signed_response.payload.run_id != run_id
            or signed_response.payload.decision_index != index
            or signed_response.payload.request_payload_sha256 != signed_request.payload_sha256
        ):
            raise ValueError("Qwen authenticated envelope identity/linkage differs")
    event_types = [item.get("event_type") for item in records]
    expected_event_types = [
        "SERVICE_STARTED",
        *[
            event
            for _ in range(8)
            for event in ("WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED")
        ],
        "SERVICE_COMPLETED",
        "SERVICE_STOPPED",
    ]
    if event_types != expected_event_types:
        raise ValueError("Qwen service audit is not completed and cleanly stopped")
    started = records[0].get("payload", {})
    completed = records[-2].get("payload", {})
    stopped = records[-1].get("payload", {})
    service_id = started.get("service_id")
    if (
        not isinstance(service_id, str)
        or re.fullmatch(r"^[0-9a-f]{32}$", service_id) is None
        or started
        != {
            "service_id": service_id,
            "path": FORMAL_INFERENCE_PATH,
            "expected_decisions": 8,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
    ):
        raise ValueError("Qwen start event identity/provenance differs")
    if completed != {
        "service_id": service_id,
        "run_id": run_id,
        "responses_committed": 8,
        "formal_evidence_complete": True,
    }:
        raise ValueError("Qwen completion event differs from the authenticated run")
    if stopped != {
        "service_id": service_id,
        "run_id": run_id,
        "responses_committed": 8,
        "completed": True,
        "poisoned": False,
        "rejections_recorded": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }:
        raise ValueError("Qwen stop event is not a clean eight-response completion")
    return run_id, challenge, canonical_sha256(ordered)


def verify_labserver_isaac_transcript(
    formal_bytes: bytes,
    service_bytes: bytes,
    session_bytes: bytes,
    *,
    secret: bytes,
) -> tuple[str, str, str]:
    formal = _parse_json_object(formal_bytes, label="formal evidence")
    run_id, challenge, cycles = _formal_identity(formal)
    service = _read_canonical_audit(
        service_bytes, schema="FormalIsaacAuditEventV2", label="Isaac service audit"
    )
    session = _read_canonical_audit(
        session_bytes, schema="FormalIsaacAuditEventV2", label="Isaac session audit"
    )
    service_by_sequence = {item["sequence"]: item for item in service}
    if any(service_by_sequence.get(item["sequence"]) != item for item in session):
        raise ValueError("Isaac session audit is not an exact service subset")
    session_start = next(
        (index for index, item in enumerate(service) if item == session[0]),
        None,
    )
    if session_start is None or service[session_start:] != session:
        raise ValueError("Isaac session audit is not the exact service-audit suffix")
    if session[0].get("event_type") != "SESSION_AUDIT_CREATED":
        raise ValueError("Isaac session audit does not start at session creation")
    from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
        FORMAL_ISAAC_CAPTURE_PATH,
        FORMAL_ISAAC_EXECUTE_PATH,
        FORMAL_ISAAC_FINALIZE_PATH,
        FORMAL_ISAAC_START_PATH,
    )

    expected_paths = [FORMAL_ISAAC_START_PATH]
    for _ in range(8):
        expected_paths.extend((FORMAL_ISAAC_CAPTURE_PATH, FORMAL_ISAAC_EXECUTE_PATH))
    expected_paths.append(FORMAL_ISAAC_FINALIZE_PATH)
    requests, responses, ordered = _wire_events(
        service,
        expected_paths=expected_paths,
    )
    if len(requests) != 18 or len(responses) != 18:
        raise ValueError("Isaac audit does not contain exactly 18 request/response pairs")
    request_specs: list[tuple[str, type[BaseModel]]] = [
        ("ISAAC_START_REQUEST", IsaacStartRequestV2)
    ]
    response_specs: list[tuple[str, type[BaseModel]]] = [
        ("ISAAC_START_RESPONSE", IsaacStartResponseV2)
    ]
    for _ in range(8):
        request_specs.extend(
            [
                ("ISAAC_CAPTURE_REQUEST", IsaacCaptureRequestV2),
                ("ISAAC_EXECUTE_REQUEST", IsaacExecuteRequestV2),
            ]
        )
        response_specs.extend(
            [
                ("ISAAC_CAPTURE_RESPONSE", IsaacCaptureResponseV2),
                ("ISAAC_EXECUTE_RESPONSE", IsaacExecuteResponseV2),
            ]
        )
    request_specs.append(("ISAAC_FINALIZE_REQUEST", IsaacFinalizeRequestV2))
    response_specs.append(("ISAAC_FINALIZE_RESPONSE", IsaacFinalizeResponseV2))
    typed_requests = [
        verify_wire_message(raw, expected_type=name, payload_model=model, secret=secret)[1]
        for raw, (name, model) in zip(requests, request_specs)
    ]
    typed_responses = [
        verify_wire_message(raw, expected_type=name, payload_model=model, secret=secret)[1]
        for raw, (name, model) in zip(responses, response_specs)
    ]
    start = typed_requests[0]
    if start.run_id != run_id or start.challenge_nonce != challenge:
        raise ValueError("Isaac start request differs from formal run/challenge")
    expected_requests = [
        requests[0],
        *[value for item in cycles for value in (item["capture_request"], item["execute_request"])],
        formal["finalize_request"],
    ]
    expected_responses = [
        responses[0],
        *[
            value
            for item in cycles
            for value in (item["capture_response"], item["execute_response"])
        ],
        formal["finalize_response"],
    ]
    if requests != expected_requests or responses != expected_responses:
        raise ValueError("Isaac audit differs from formal evidence")
    if typed_responses[0].model_dump(mode="json") != formal["start_response"]:
        raise ValueError("Isaac signed start response differs from formal evidence")
    if (
        service[0].get("event_type") != "SERVICE_STARTED"
        or service[-1].get("event_type") != "SERVICE_STOPPED"
        or service[-1].get("payload", {}).get("clean_shutdown") is not True
        or sum(item.get("event_type") == "SERVICE_STARTED" for item in service) != 1
        or sum(item.get("event_type") == "SERVICE_STOPPED" for item in service) != 1
    ):
        raise ValueError("Isaac service audit is not cleanly stopped")
    return run_id, challenge, canonical_sha256(ordered)


def _principal(role: HostRole) -> str:
    return NODE2_PRINCIPAL if role == "NODE2_QWEN" else LABSERVER_PRINCIPAL


def sign_core(
    core: HostWireAuthenticationCoreV1,
    *,
    private_key_path: Path,
    ssh_keygen: Path = Path("/usr/bin/ssh-keygen"),
) -> str:
    private_key_bytes = read_regular_file_once(private_key_path, require_private=True)
    with tempfile.TemporaryDirectory(prefix="m2c-wire-auth-sign-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        private_copy = root / "signing_key"
        _write_private_file(private_copy, private_key_bytes)
        public_key = subprocess.run(
            [str(ssh_keygen), "-y", "-f", str(private_copy)],
            capture_output=True,
            check=False,
            timeout=30,
            env=_ssh_environment(),
            close_fds=True,
        )
        if (
            public_key.returncode != 0
            or re.fullmatch(
                rb"ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\x00\r\n]+)?\n?",
                public_key.stdout,
            )
            is None
        ):
            raise ValueError("wire authentication signing key is not OpenSSH Ed25519")
        completed = subprocess.run(
            [
                str(ssh_keygen),
                "-Y",
                "sign",
                "-f",
                str(private_copy),
                "-n",
                AUTH_NAMESPACE,
            ],
            input=canonical_json_bytes(core),
            capture_output=True,
            check=False,
            timeout=30,
            env=_ssh_environment(),
            close_fds=True,
        )
    if completed.returncode != 0:
        raise ValueError("OpenSSH Ed25519 signing failed closed")
    signature = completed.stdout.decode("ascii")
    if "BEGIN SSH SIGNATURE" not in signature:
        raise ValueError("OpenSSH signer did not emit an armored SSHSIG")
    return signature


def verify_receipt_signature(
    receipt: SignedHostWireAuthenticationReceiptV1,
    *,
    allowed_signers_bytes: bytes,
    ssh_keygen: Path = Path("/usr/bin/ssh-keygen"),
) -> None:
    _validate_allowed_signers_bytes(
        allowed_signers_bytes,
        principal=_principal(receipt.core.host_role),
    )
    with tempfile.TemporaryDirectory(prefix="m2c-wire-auth-verify-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        allowed = root / "allowed_signers"
        signature = root / "signature"
        _write_private_file(allowed, allowed_signers_bytes)
        _write_private_file(signature, receipt.signature_armored.encode("ascii"))
        completed = subprocess.run(
            [
                str(ssh_keygen),
                "-Y",
                "verify",
                "-f",
                str(allowed),
                "-I",
                receipt.core.signer_principal,
                "-n",
                AUTH_NAMESPACE,
                "-s",
                str(signature),
            ],
            input=canonical_json_bytes(receipt.core),
            capture_output=True,
            check=False,
            timeout=30,
            env=_ssh_environment(),
            close_fds=True,
        )
    if completed.returncode != 0:
        raise ValueError("OpenSSH Ed25519 wire attestation signature is invalid")


def build_signed_receipt(
    *,
    host_role: HostRole,
    run_id: str,
    challenge_nonce: str,
    formal_evidence_bytes: bytes,
    service_audit_bytes: bytes,
    session_audit_bytes: bytes | None,
    envelope_set_sha256: str,
    verifier_implementation_path: str,
    verifier_implementation_bytes: bytes,
    allowed_signers_bytes: bytes,
    private_key_path: Path,
) -> SignedHostWireAuthenticationReceiptV1:
    core = HostWireAuthenticationCoreV1(
        host_role=host_role,
        run_id=run_id,
        challenge_nonce=challenge_nonce,
        formal_evidence_sha256=sha256_bytes(formal_evidence_bytes),
        service_audit_sha256=sha256_bytes(service_audit_bytes),
        session_audit_sha256=(
            sha256_bytes(session_audit_bytes) if session_audit_bytes is not None else None
        ),
        envelope_set_sha256=envelope_set_sha256,
        authenticated_envelope_count=16 if host_role == "NODE2_QWEN" else 36,
        request_envelope_count=8 if host_role == "NODE2_QWEN" else 18,
        response_envelope_count=8 if host_role == "NODE2_QWEN" else 18,
        verifier_implementation_path=verifier_implementation_path,
        verifier_implementation_sha256=sha256_bytes(verifier_implementation_bytes),
        public_trust_root_sha256=sha256_bytes(allowed_signers_bytes),
        signer_principal=_principal(host_role),
    )
    return SignedHostWireAuthenticationReceiptV1(
        core=core,
        signature_armored=sign_core(core, private_key_path=private_key_path),
    )


def build_hmac_verification_receipt_v2(
    *,
    host_role: HostRole,
    formal_evidence_bytes: bytes,
    service_audit_bytes: bytes,
    session_audit_bytes: bytes | None,
    secret: bytes,
    verifier_implementation_bytes: bytes,
) -> HostWireHMACVerificationReceiptV2:
    """Replay one host transcript and emit an unsigned content receipt.

    The caller supplies exactly one host-local secret.  This function never
    serializes that secret and has no SSH/key-authority input.
    """

    if host_role == "NODE2_QWEN":
        if session_audit_bytes is not None:
            raise ValueError("node2 HMAC verification may not accept a session audit")
        run_id, challenge_nonce, envelope_set_sha256 = verify_node2_qwen_transcript(
            formal_evidence_bytes,
            service_audit_bytes,
            secret=secret,
        )
    else:
        if session_audit_bytes is None:
            raise ValueError("labserver HMAC verification requires the Isaac session audit")
        run_id, challenge_nonce, envelope_set_sha256 = verify_labserver_isaac_transcript(
            formal_evidence_bytes,
            service_audit_bytes,
            session_audit_bytes,
            secret=secret,
        )
    core = HostWireHMACVerificationCoreV2(
        host_role=host_role,
        run_id=run_id,
        challenge_nonce=challenge_nonce,
        formal_evidence_sha256=sha256_bytes(formal_evidence_bytes),
        service_audit_sha256=sha256_bytes(service_audit_bytes),
        session_audit_sha256=(
            sha256_bytes(session_audit_bytes) if session_audit_bytes is not None else None
        ),
        envelope_set_sha256=envelope_set_sha256,
        authenticated_envelope_count=16 if host_role == "NODE2_QWEN" else 36,
        request_envelope_count=8 if host_role == "NODE2_QWEN" else 18,
        response_envelope_count=8 if host_role == "NODE2_QWEN" else 18,
        verifier_implementation_sha256=sha256_bytes(verifier_implementation_bytes),
    )
    return HostWireHMACVerificationReceiptV2(core=core)
