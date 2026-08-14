from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from m2c import verify_formal_wire_auth_v4 as verifier_cli
from test_m2c_formal_isaac_endpoint_v4 import SECRET as ISAAC_SECRET
from test_m2c_formal_isaac_endpoint_v4 import _endpoint
from test_m2c_formal_split_host_v4 import QWEN_SECRET, _InMemoryTransport, _inputs
from xh_agent.policy.qrm_lite.formal_split_host_v4 import (
    FormalV4RunInputs,
    M2CFormalSplitRunnerEvidenceV4,
    run_formal_v4_episode,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_json_bytes
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_WIRE_PROTOCOL_V4,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT,
    WireChallengeConsumptionReceiptV1,
    wire_challenge_consumption_id,
    wire_challenge_consumption_path,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v4 import (
    HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH,
    HostWireHMACVerificationReceiptV4,
    build_hmac_verification_receipt_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SHA256 = "a" * 64


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _consumption_bytes(
    *,
    base_inputs: FormalV4RunInputs,
    consumed_at_ns: int,
) -> tuple[bytes, WireChallengeConsumptionReceiptV1]:
    consumption_id = wire_challenge_consumption_id(
        challenge_nonce=base_inputs.challenge_nonce,
        challenge_manifest_sha256=MANIFEST_SHA256,
    )
    receipt = WireChallengeConsumptionReceiptV1(
        run_id=base_inputs.run_id,
        challenge_nonce=base_inputs.challenge_nonce,
        matched_key=base_inputs.matched_key,
        scene_seed=base_inputs.scene_seed,
        failure_seed=base_inputs.failure_seed,
        challenge_manifest_sha256=MANIFEST_SHA256,
        ledger_root=CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT,
        consumption_id=consumption_id,
        consumed_at_ns=consumed_at_ns,
    )
    return canonical_json_bytes(receipt) + b"\n", receipt


def _qwen_audit(evidence: M2CFormalSplitRunnerEvidenceV4) -> bytes:
    service_id = "1" * 32
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "SERVICE_STARTED",
            {
                "service_id": service_id,
                "path": FORMAL_INFERENCE_PATH_V4,
                "protocol": FORMAL_WIRE_PROTOCOL_V4,
                "architecture_revision": "M2C_Q012_V4",
                "expected_decisions": 8,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
        )
    ]
    for cycle in evidence.wire_cycles:
        events.extend(
            [
                (
                    "WIRE_REQUEST_RECEIVED",
                    {
                        "path": FORMAL_INFERENCE_PATH_V4,
                        "signed_wire": cycle.inference_request.model_dump(mode="json"),
                    },
                ),
                (
                    "WIRE_RESPONSE_COMMITTED",
                    {
                        "path": FORMAL_INFERENCE_PATH_V4,
                        "signed_wire": cycle.inference_response.model_dump(mode="json"),
                    },
                ),
            ]
        )
    if len(evidence.wire_cycles) == 8:
        events.append(
            (
                "SERVICE_COMPLETED",
                {
                    "service_id": service_id,
                    "run_id": evidence.run_id,
                    "protocol": FORMAL_WIRE_PROTOCOL_V4,
                    "responses_committed": 8,
                    "formal_evidence_complete": True,
                },
            )
        )
    events.append(
        (
            "SERVICE_STOPPED",
            {
                "service_id": service_id,
                "run_id": evidence.run_id,
                "protocol": FORMAL_WIRE_PROTOCOL_V4,
                "responses_committed": len(evidence.wire_cycles),
                "completed": len(evidence.wire_cycles) == 8,
                "poisoned": False,
                "rejections_recorded": 0,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
        )
    )
    records = [
        {
            "schema_version": "FormalQwenAuditEventV4",
            "sequence": sequence,
            "recorded_at_ns": 100 + sequence,
            "event_type": event_type,
            "payload": payload,
        }
        for sequence, (event_type, payload) in enumerate(events, start=1)
    ]
    return b"".join(canonical_json_bytes(record) + b"\n" for record in records)


def _rewrite_audit(
    data: bytes,
    mutator: Any,
) -> bytes:
    records = [json.loads(line) for line in data.splitlines()]
    mutator(records)
    return b"".join(canonical_json_bytes(record) + b"\n" for record in records)


def _episode(
    tmp_path: Path,
    *,
    terminal: bool = False,
    consumed_at_ns: int = 1,
) -> tuple[bytes, bytes, bytes, bytes, bytes]:
    endpoint, _, _ = _endpoint(tmp_path / "isaac")
    endpoint.audit.append(
        "HTTP_SERVER_READY_V4",
        {
            "listen_host": "127.0.0.1",
            "listen_port": 48134,
            "formal_execution_started": False,
        },
    )
    base_inputs = _inputs(endpoint)
    consumption_bytes, consumption = _consumption_bytes(
        base_inputs=base_inputs,
        consumed_at_ns=consumed_at_ns,
    )
    inputs_raw = base_inputs.model_dump(mode="json")
    inputs_raw.update(
        {
            "challenge_consumption_receipt_path": str(
                wire_challenge_consumption_path(
                    Path(CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT),
                    consumption.challenge_nonce,
                )
            ),
            "challenge_consumption_receipt_sha256": _sha256(consumption_bytes),
            "challenge_consumption_id": consumption.consumption_id,
        }
    )
    evidence = run_formal_v4_episode(
        inputs=FormalV4RunInputs.model_validate(inputs_raw),
        registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        qwen_secret=QWEN_SECRET,
        isaac_secret=ISAAC_SECRET,
        transport=_InMemoryTransport(
            endpoint,
            selected_pointers=((8,) + (0,) * 7) if terminal else (0,) * 8,
        ),
    )
    endpoint.audit.append("SERVICE_STOPPED", {"clean_shutdown": True})
    assert endpoint.session_audit_path is not None
    formal_bytes = canonical_json_bytes(evidence) + b"\n"
    return (
        formal_bytes,
        consumption_bytes,
        _qwen_audit(evidence),
        endpoint.audit.service_path.read_bytes(),
        endpoint.session_audit_path.read_bytes(),
    )


def _implementation_bytes() -> bytes:
    return (ROOT / HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH).read_bytes()


@pytest.mark.parametrize(
    ("terminal", "node_counts", "lab_counts", "completion"),
    [
        (False, (16, 8, 8), (36, 18, 18), "FINALIZED"),
        (True, (2, 1, 1), (6, 3, 3), "TERMINAL_NO_PHYSICAL_EXECUTION"),
    ],
)
def test_v4_host_local_hmac_receipts_replay_finalized_and_terminalized_runs(
    tmp_path: Path,
    terminal: bool,
    node_counts: tuple[int, int, int],
    lab_counts: tuple[int, int, int],
    completion: str,
) -> None:
    formal, consumption, qwen, service, session = _episode(
        tmp_path,
        terminal=terminal,
    )
    implementation = _implementation_bytes()
    node = build_hmac_verification_receipt_v4(
        host_role="NODE2_QWEN",
        formal_evidence_bytes=formal,
        challenge_consumption_bytes=consumption,
        service_audit_bytes=qwen,
        session_audit_bytes=None,
        secret=QWEN_SECRET,
        verifier_implementation_bytes=implementation,
    )
    lab = build_hmac_verification_receipt_v4(
        host_role="LABSERVER_ISAAC",
        formal_evidence_bytes=formal,
        challenge_consumption_bytes=consumption,
        service_audit_bytes=service,
        session_audit_bytes=session,
        secret=ISAAC_SECRET,
        verifier_implementation_bytes=implementation,
    )

    assert (
        node.core.authenticated_envelope_count,
        node.core.request_envelope_count,
        node.core.response_envelope_count,
    ) == node_counts
    assert (
        lab.core.authenticated_envelope_count,
        lab.core.request_envelope_count,
        lab.core.response_envelope_count,
    ) == lab_counts
    assert node.core.completion_kind == lab.core.completion_kind == completion
    assert node.core.formal_evidence_sha256 == lab.core.formal_evidence_sha256
    assert node.core.challenge_consumption_receipt_sha256 == _sha256(consumption)
    serialized = canonical_json_bytes([node, lab])
    assert QWEN_SECRET not in serialized
    assert ISAAC_SECRET not in serialized
    assert b"signature" not in serialized
    assert b"trust_root" not in serialized
    assert b"principal" not in serialized


def test_v4_hmac_verifier_rejects_qwen_hmac_and_isaac_lifecycle_tamper(
    tmp_path: Path,
) -> None:
    formal, consumption, qwen, service, session = _episode(tmp_path)
    implementation = _implementation_bytes()

    with pytest.raises(ValueError, match="HMAC mismatch"):
        build_hmac_verification_receipt_v4(
            host_role="NODE2_QWEN",
            formal_evidence_bytes=formal,
            challenge_consumption_bytes=consumption,
            service_audit_bytes=qwen,
            session_audit_bytes=None,
            secret=b"wrong-formal-v4-qwen-secret-at-least-32-bytes",
            verifier_implementation_bytes=implementation,
        )

    def tamper_lifecycle(records: list[dict[str, Any]]) -> None:
        event = next(
            item for item in records if item["event_type"] == "EXACT_EXECUTION_PLAN_EXECUTED_V4"
        )
        event["payload"]["decision_index"] = 7

    tampered_service = _rewrite_audit(service, tamper_lifecycle)
    tampered_session = _rewrite_audit(session, tamper_lifecycle)
    with pytest.raises(ValueError, match="lifecycle payload differs"):
        build_hmac_verification_receipt_v4(
            host_role="LABSERVER_ISAAC",
            formal_evidence_bytes=formal,
            challenge_consumption_bytes=consumption,
            service_audit_bytes=tampered_service,
            session_audit_bytes=tampered_session,
            secret=ISAAC_SECRET,
            verifier_implementation_bytes=implementation,
        )


def test_v4_hmac_verifier_rejects_late_consumption_and_non_suffix_session(
    tmp_path: Path,
) -> None:
    formal, consumption, qwen, service, session = _episode(
        tmp_path,
        consumed_at_ns=102,
    )
    with pytest.raises(ValueError, match="before Qwen contact"):
        build_hmac_verification_receipt_v4(
            host_role="NODE2_QWEN",
            formal_evidence_bytes=formal,
            challenge_consumption_bytes=consumption,
            service_audit_bytes=qwen,
            session_audit_bytes=None,
            secret=QWEN_SECRET,
            verifier_implementation_bytes=_implementation_bytes(),
        )

    good_formal, good_consumption, _, good_service, good_session = _episode(tmp_path / "suffix")
    truncated_session = b"\n".join(good_session.splitlines()[:-1]) + b"\n"
    with pytest.raises(ValueError, match="exact service suffix"):
        build_hmac_verification_receipt_v4(
            host_role="LABSERVER_ISAAC",
            formal_evidence_bytes=good_formal,
            challenge_consumption_bytes=good_consumption,
            service_audit_bytes=good_service,
            session_audit_bytes=truncated_session,
            secret=ISAAC_SECRET,
            verifier_implementation_bytes=_implementation_bytes(),
        )


def test_v4_receipt_schema_rejects_claimed_count_inflation(tmp_path: Path) -> None:
    formal, consumption, qwen, _, _ = _episode(tmp_path, terminal=True)
    receipt = build_hmac_verification_receipt_v4(
        host_role="NODE2_QWEN",
        formal_evidence_bytes=formal,
        challenge_consumption_bytes=consumption,
        service_audit_bytes=qwen,
        session_audit_bytes=None,
        secret=QWEN_SECRET,
        verifier_implementation_bytes=_implementation_bytes(),
    )
    raw = receipt.model_dump(mode="json")
    raw["core"]["authenticated_envelope_count"] = 16
    raw["core"]["request_envelope_count"] = 8
    raw["core"]["response_envelope_count"] = 8
    with pytest.raises(ValidationError, match="count/session contract differs"):
        HostWireHMACVerificationReceiptV4.model_validate(raw)
    with pytest.raises(ValueError, match="at least 32 bytes"):
        build_hmac_verification_receipt_v4(
            host_role="NODE2_QWEN",
            formal_evidence_bytes=formal,
            challenge_consumption_bytes=consumption,
            service_audit_bytes=qwen,
            session_audit_bytes=None,
            secret=b"short",
            verifier_implementation_bytes=_implementation_bytes(),
        )


def test_v4_host_local_cli_publishes_create_only_receipt_without_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    formal, consumption, qwen, _, _ = _episode(tmp_path / "episode", terminal=True)
    evidence_path = tmp_path / "formal.json"
    consumption_path = tmp_path / "consumption.json"
    audit_path = tmp_path / "qwen.jsonl"
    key_path = tmp_path / "qwen.key"
    output_path = tmp_path / "receipts" / "node2.json"
    evidence_path.write_bytes(formal)
    consumption_path.write_bytes(consumption)
    audit_path.write_bytes(qwen)
    key_path.write_bytes(QWEN_SECRET)
    key_path.chmod(0o600)
    argv = [
        "--host-role",
        "NODE2_QWEN",
        "--formal-evidence",
        str(evidence_path),
        "--challenge-consumption-receipt",
        str(consumption_path),
        "--service-audit",
        str(audit_path),
        "--hmac-key-file",
        str(key_path),
        "--project-root",
        str(ROOT),
        "--output",
        str(output_path),
    ]

    assert verifier_cli.main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == ("PASS_HOST_LOCAL_V4_HMAC_VERIFICATION_NOT_FORMAL_AUTHORIZATION")
    assert summary["decision_count"] == 1
    assert output_path.stat().st_mode & 0o777 == 0o400
    assert QWEN_SECRET not in output_path.read_bytes()
    with pytest.raises(FileExistsError):
        verifier_cli.main(argv)
