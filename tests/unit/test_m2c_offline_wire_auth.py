from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    AUTH_NAMESPACE,
    CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT,
    HostWireAuthenticationCoreV1,
    HostWireHMACVerificationCoreV2,
    HostWireHMACVerificationReceiptV2,
    SignedHostWireAuthenticationReceiptV1,
    WireChallengeConsumptionReceiptV1,
    _read_canonical_audit,
    _wire_events,
    consume_wire_challenge_create_only,
    sign_core,
    verify_receipt_signature,
    wire_challenge_consumption_id,
)


def _keys(tmp_path: Path, principal: str) -> tuple[Path, bytes]:
    private = tmp_path / "signer"
    completed = subprocess.run(
        ["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    allowed = principal.encode() + b" " + private.with_suffix(".pub").read_bytes()
    return private, allowed


def _core() -> HostWireAuthenticationCoreV1:
    return HostWireAuthenticationCoreV1(
        host_role="NODE2_QWEN",
        run_id="preregistered-run",
        challenge_nonce="1" * 64,
        formal_evidence_sha256="2" * 64,
        service_audit_sha256="3" * 64,
        envelope_set_sha256="4" * 64,
        authenticated_envelope_count=16,
        request_envelope_count=8,
        response_envelope_count=8,
        verifier_implementation_path="src/x.py",
        verifier_implementation_sha256="5" * 64,
        public_trust_root_sha256="6" * 64,
        signer_principal="m2c-node2-qwen-evidence-authority",
    )


def test_openssh_ed25519_signature_binds_every_core_field(tmp_path: Path) -> None:
    core = _core()
    private, allowed = _keys(tmp_path, core.signer_principal)
    receipt = SignedHostWireAuthenticationReceiptV1(
        core=core,
        signature_armored=sign_core(core, private_key_path=private),
    )
    verify_receipt_signature(receipt, allowed_signers_bytes=allowed)

    tampered = receipt.model_copy(
        update={"core": core.model_copy(update={"challenge_nonce": "9" * 64})}
    )
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_receipt_signature(tampered, allowed_signers_bytes=allowed)


def test_wrong_principal_namespace_or_non_ed25519_trust_root_fails(tmp_path: Path) -> None:
    core = _core()
    private, allowed = _keys(tmp_path, core.signer_principal)
    receipt = SignedHostWireAuthenticationReceiptV1(
        core=core,
        signature_armored=sign_core(core, private_key_path=private),
    )
    with pytest.raises(ValueError, match="exactly the fixed principal"):
        verify_receipt_signature(
            receipt,
            allowed_signers_bytes=allowed.replace(core.signer_principal.encode(), b"other"),
        )
    with pytest.raises(ValueError, match="one Ed25519"):
        verify_receipt_signature(
            receipt,
            allowed_signers_bytes=core.signer_principal.encode() + b" ssh-rsa AAAA\n",
        )
    assert AUTH_NAMESPACE == "m2c-wire-auth-v1@xh-agent"


def test_role_schema_rejects_cross_host_counts_or_missing_session() -> None:
    raw = _core().model_dump(mode="json")
    raw["host_role"] = "LABSERVER_ISAAC"
    raw["signer_principal"] = "m2c-labserver-isaac-evidence-authority"
    with pytest.raises(ValidationError, match="role/count/principal"):
        HostWireAuthenticationCoreV1.model_validate(raw)


def test_unsigned_v2_receipt_has_no_ssh_or_trust_fields() -> None:
    core = HostWireHMACVerificationCoreV2(
        host_role="NODE2_QWEN",
        run_id="run",
        challenge_nonce="1" * 64,
        formal_evidence_sha256="2" * 64,
        service_audit_sha256="3" * 64,
        envelope_set_sha256="4" * 64,
        authenticated_envelope_count=16,
        request_envelope_count=8,
        response_envelope_count=8,
        verifier_implementation_sha256="5" * 64,
    )
    raw = HostWireHMACVerificationReceiptV2(core=core).model_dump(mode="json")
    encoded = json.dumps(raw)
    assert "signature" not in encoded
    assert "trust_root" not in encoded
    assert "principal" not in encoded
    with pytest.raises(ValidationError, match="Extra inputs"):
        HostWireHMACVerificationReceiptV2.model_validate({**raw, "signature_armored": "fake"})


def test_challenge_consumption_is_create_only_and_tamper_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "ledger"
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.offline_wire_auth_v1.CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT",
        str(ledger),
    )
    manifest = tmp_path / "manifest.json"
    challenge = "1" * 64
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "M2CS4WireChallengeManifestV1",
                "challenge_records": [
                    {
                        "run_id": "run",
                        "challenge_nonce": challenge,
                        "matched_key": "key",
                        "scene_seed": 1,
                        "failure_seed": 2,
                    }
                ],
                "formal_q_b_evaluation_authorized": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
            sort_keys=True,
        )
    )
    path, receipt = consume_wire_challenge_create_only(
        ledger_directory=ledger,
        challenge_manifest_path=manifest,
        run_id="run",
        challenge_nonce=challenge,
        matched_key="key",
        scene_seed=1,
        failure_seed=2,
        consumed_at_ns=1,
    )
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o400
    assert receipt.consumption_id == wire_challenge_consumption_id(
        challenge_nonce=challenge,
        challenge_manifest_sha256=receipt.challenge_manifest_sha256,
    )
    with pytest.raises(FileExistsError):
        consume_wire_challenge_create_only(
            ledger_directory=ledger,
            challenge_manifest_path=manifest,
            run_id="run",
            challenge_nonce=challenge,
            matched_key="key",
            scene_seed=1,
            failure_seed=2,
            consumed_at_ns=2,
        )
    tampered = receipt.model_dump(mode="json")
    tampered["consumption_id"] = "0" * 64
    with pytest.raises(ValidationError, match="not canonical"):
        WireChallengeConsumptionReceiptV1.model_validate(tampered)
    assert CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT.startswith("/var/lib/")


def test_signer_rejects_symlink_private_key(tmp_path: Path) -> None:
    core = _core()
    private, _ = _keys(tmp_path, core.signer_principal)
    link = tmp_path / "signer-link"
    link.symlink_to(private)
    with pytest.raises(OSError):
        sign_core(core, private_key_path=link)


def test_signer_rejects_rsa_private_key(tmp_path: Path) -> None:
    core = _core()
    private = tmp_path / "rsa-signer"
    completed = subprocess.run(
        ["/usr/bin/ssh-keygen", "-q", "-t", "rsa", "-N", "", "-f", str(private)],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    with pytest.raises(ValueError, match="not OpenSSH Ed25519"):
        sign_core(core, private_key_path=private)


def test_allowed_signers_rejects_extra_lines_even_with_valid_ed25519_key(
    tmp_path: Path,
) -> None:
    core = _core()
    private, allowed = _keys(tmp_path, core.signer_principal)
    receipt = SignedHostWireAuthenticationReceiptV1(
        core=core,
        signature_armored=sign_core(core, private_key_path=private),
    )
    with pytest.raises(ValueError, match="exactly the fixed principal"):
        verify_receipt_signature(
            receipt,
            allowed_signers_bytes=allowed + b"other ssh-ed25519 AAAA\n",
        )


def _audit_bytes(events: list[tuple[str, dict[str, object]]]) -> bytes:
    lines = []
    for sequence, (event_type, payload) in enumerate(events, start=1):
        lines.append(
            json.dumps(
                {
                    "schema_version": "FormalQwenAuditEventV2",
                    "sequence": sequence,
                    "recorded_at_ns": sequence,
                    "event_type": event_type,
                    "payload": payload,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    return b"\n".join(lines) + b"\n"


def test_wire_event_parser_rejects_reordered_pairs_or_wrong_path() -> None:
    envelope = {"payload": {}, "payload_sha256": "1" * 64, "hmac_sha256": "2" * 64}
    reordered = [
        ("WIRE_REQUEST_RECEIVED", {"path": "/formal", "signed_wire": envelope}),
        ("WIRE_REQUEST_RECEIVED", {"path": "/formal", "signed_wire": envelope}),
        ("WIRE_RESPONSE_COMMITTED", {"path": "/formal", "signed_wire": envelope}),
        ("WIRE_RESPONSE_COMMITTED", {"path": "/formal", "signed_wire": envelope}),
    ]
    records = _read_canonical_audit(
        _audit_bytes(reordered),
        schema="FormalQwenAuditEventV2",
        label="fixture audit",
    )
    with pytest.raises(ValueError, match="request/response sequence"):
        _wire_events(records, expected_paths=["/formal", "/formal"])

    paired = [
        ("WIRE_REQUEST_RECEIVED", {"path": "/wrong", "signed_wire": envelope}),
        ("WIRE_RESPONSE_COMMITTED", {"path": "/wrong", "signed_wire": envelope}),
    ]
    records = _read_canonical_audit(
        _audit_bytes(paired),
        schema="FormalQwenAuditEventV2",
        label="fixture audit",
    )
    with pytest.raises(ValueError, match="endpoint path"):
        _wire_events(records, expected_paths=["/formal"])


def test_audit_parser_rejects_nonone_sequence_or_truncated_final_line() -> None:
    valid = _audit_bytes([("SERVICE_STARTED", {})])
    shifted = valid.replace(b'"sequence":1', b'"sequence":9')
    with pytest.raises(ValueError, match="canonical contiguous"):
        _read_canonical_audit(
            shifted,
            schema="FormalQwenAuditEventV2",
            label="fixture audit",
        )
    with pytest.raises(ValueError, match="newline-terminated"):
        _read_canonical_audit(
            valid.rstrip(b"\n"),
            schema="FormalQwenAuditEventV2",
            label="fixture audit",
        )
