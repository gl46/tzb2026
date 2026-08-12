"""Contract-only tests for the formal Qwen service journal; no model is loaded."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from m2c.serve_qwen_coarse_v2 import (
    AppendOnlyQwenAuditLogV2,
    FormalQwenServiceSessionV2,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FORMAL_INFERENCE_PATH,
    FormalInferenceRequestV2,
    QwenBundleRuntimeBindingV2,
    build_inference_response_from_logits,
    canonical_json_bytes,
    canonical_sha256,
    sign_inference_request,
    verify_inference_response,
)


SECRET = b"formal-qwen-audit-contract-key-32-bytes!!"
CHALLENGE = "c" * 64


def _asset(raw: bytes, *, uri: str, media_type: str) -> dict[str, object]:
    return {
        "uri": uri,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "media_type": media_type,
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }


def _rgb() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(stream, "PNG")
    return stream.getvalue()


def _depth() -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.ones((2, 2), dtype=np.float32), allow_pickle=False)
    return stream.getvalue()


def _bundle() -> QwenBundleRuntimeBindingV2:
    return QwenBundleRuntimeBindingV2(
        bundle_manifest_sha256="1" * 64,
        head_checkpoint_sha256="2" * 64,
        adapter_tree_sha256="3" * 64,
        model_cache_dir=(
            "/verified/cache/models--Qwen--Qwen3.5-4B/snapshots/"
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
        ),
        model_cache_tree_sha256="4" * 64,
        failure_context="on",
    )


def _history(index: int) -> list[PublicExecutedIntentHistoryItemV2]:
    return [
        PublicExecutedIntentHistoryItemV2(
            decision_index=prior,
            selected_skill="GRASP",
            target_track_id="track-blocker",
            physical_receipt_sha256=f"{prior + 1:x}" * 64,
            execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        )
        for prior in range(index)
    ]


def _request(
    index: int,
    *,
    run_id: str = "formal-run-1",
    challenge_nonce: str = CHALLENGE,
) -> FormalInferenceRequestV2:
    previous_ns = 100 + index * 100
    captured_ns = previous_ns + 10
    history = _history(index)
    return FormalInferenceRequestV2(
        run_id=run_id,
        challenge_nonce=challenge_nonce,
        request_id=f"{run_id}-decision-{index}",
        decision_index=index,
        sent_at_ns=captured_ns + 10,
        executed_intent_history=history,
        prior_decisions_sha256=canonical_sha256(history),
        bundle=_bundle(),
        observation={
            "observation_id": f"public-observation-{index}",
            "captured_at_ns": captured_ns,
            "previous_physical_completed_at_ns": previous_ns,
            "rgb": _asset(
                _rgb(),
                uri=f"dataset://public/rgb-{index}.png",
                media_type="image/png",
            ),
            "depth": _asset(
                _depth(),
                uri=f"dataset://public/depth-{index}.npy",
                media_type="application/x-npy",
            ),
            "capture_receipt_sha256": f"{index + 8:x}" * 64,
            "perception_tracks": [
                {
                    "track_id": "track-blocker",
                    "category": "industrial_cylinder:red",
                    "confidence": 0.99,
                    "pose_xyzquat": [0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0],
                },
                {
                    "track_id": "track-task",
                    "category": "industrial_cylinder:yellow",
                    "confidence": 0.98,
                    "pose_xyzquat": [0.4, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0],
                },
            ],
            "canonical_slots": [
                "track-blocker",
                "track-task",
                None,
                None,
                None,
                None,
                None,
                None,
            ],
        },
    )


def _predict(_runtime: object, request: FormalInferenceRequestV2):
    skill = np.full(17, -10.0)
    skill[2] = 10.0
    pointer = np.full(9, -10.0)
    pointer[0] = 10.0
    destination = np.full(7, -10.0)
    destination[6] = 10.0
    return build_inference_response_from_logits(
        request,
        skill_logits=skill,
        pointer_logits=pointer,
        destination_logits=destination,
        prompt_sha256="5" * 64,
        pooled_feature_sha256="6" * 64,
        head_tensor_sha256={
            name: "7" * 64
            for name in (
                "skill_w",
                "skill_b",
                "pointer_w",
                "pointer_b",
                "destination_w",
                "destination_b",
            )
        },
        completed_at_ns=request.sent_at_ns + 10,
    )


def _session(tmp_path: Path):
    audit = AppendOnlyQwenAuditLogV2(tmp_path / "audit")
    runtime = SimpleNamespace(binding=_bundle(), secret=SECRET)
    session = FormalQwenServiceSessionV2(
        runtime=runtime,  # type: ignore[arg-type]
        audit=audit,
        predictor=_predict,  # type: ignore[arg-type]
    )
    return session, audit


def _records(path: Path) -> list[dict[str, object]]:
    lines = path.read_bytes().splitlines()
    records = [json.loads(line) for line in lines]
    assert all(canonical_json_bytes(record) == line for record, line in zip(records, lines))
    assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
    assert all(record["schema_version"] == "FormalQwenAuditEventV2" for record in records)
    return records


def test_journal_is_create_only_canonical_and_fsyncs_each_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fsync_calls: list[int] = []
    monkeypatch.setattr("m2c.serve_qwen_coarse_v2.os.fsync", fsync_calls.append)
    audit = AppendOnlyQwenAuditLogV2(tmp_path / "audit")
    audit.append("CONTRACT_ONLY", {"z": 1, "a": 2})
    records = _records(audit.service_path)
    assert [record["event_type"] for record in records] == [
        "SERVICE_STARTED",
        "CONTRACT_ONLY",
    ]
    assert len(fsync_calls) >= 4  # create, parent directory, and both records
    assert audit.service_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        AppendOnlyQwenAuditLogV2._create_exclusive(audit.service_path)


def test_exact_eight_signed_pairs_are_committed_then_cleanly_stopped(tmp_path: Path) -> None:
    session, audit = _session(tmp_path)
    requests: list[dict[str, object]] = []
    responses: list[dict[str, object]] = []
    for index in range(8):
        signed = sign_inference_request(_request(index), SECRET).model_dump(mode="json")
        requests.append(signed)
        response = session.handle(signed)
        responses.append(response)
        assert verify_inference_response(response, SECRET).payload.decision_index == index
    assert session.completed is True
    assert session.responses_committed == 8
    session.stop()

    records = _records(audit.service_path)
    assert [record["event_type"] for record in records] == [
        "SERVICE_STARTED",
        *[
            event
            for _ in range(8)
            for event in ("WIRE_REQUEST_RECEIVED", "WIRE_RESPONSE_COMMITTED")
        ],
        "SERVICE_COMPLETED",
        "SERVICE_STOPPED",
    ]
    audited_requests = [
        record["payload"]["signed_wire"]
        for record in records
        if record["event_type"] == "WIRE_REQUEST_RECEIVED"
    ]
    audited_responses = [
        record["payload"]["signed_wire"]
        for record in records
        if record["event_type"] == "WIRE_RESPONSE_COMMITTED"
    ]
    assert audited_requests == requests
    assert audited_responses == responses
    completed = records[-2]["payload"]
    assert completed == {
        "formal_evidence_complete": True,
        "responses_committed": 8,
        "run_id": "formal-run-1",
        "service_id": audit.service_id,
    }
    assert records[-1]["payload"]["completed"] is True
    assert records[-1]["payload"]["poisoned"] is False


@pytest.mark.parametrize(
    ("first", "second", "match"),
    [
        (_request(1), None, "exact 0..7"),
        (_request(0), _request(1, run_id="crossed-run"), "run_id"),
        (
            _request(0),
            _request(1, challenge_nonce="d" * 64),
            "challenge nonce",
        ),
    ],
)
def test_invalid_sequence_or_identity_is_rejected_and_poisons_session(
    tmp_path: Path,
    first: FormalInferenceRequestV2,
    second: FormalInferenceRequestV2 | None,
    match: str,
) -> None:
    session, audit = _session(tmp_path)
    if second is None:
        attempted = first
    else:
        session.handle(sign_inference_request(first, SECRET).model_dump(mode="json"))
        attempted = second
    with pytest.raises((RuntimeError, ValueError), match=match):
        session.handle(sign_inference_request(attempted, SECRET).model_dump(mode="json"))
    assert session.poisoned is True
    records = _records(audit.service_path)
    assert records[-1]["event_type"] == "WIRE_REQUEST_REJECTED"
    assert records[-1]["payload"]["formal_evidence_accepted"] is False
    assert "signed_wire" not in records[-1]["payload"]
    assert SECRET.decode("ascii") not in audit.service_path.read_text()

    with pytest.raises(RuntimeError, match="poisoned"):
        session.handle(
            sign_inference_request(_request(session.next_decision_index), SECRET).model_dump(
                mode="json"
            )
        )
    assert _records(audit.service_path)[-1]["event_type"] == "WIRE_REQUEST_REJECTED"


def test_request_after_eight_responses_is_rejected_and_never_inferred(tmp_path: Path) -> None:
    calls: list[int] = []

    def counted(runtime: object, request: FormalInferenceRequestV2):
        calls.append(request.decision_index)
        return _predict(runtime, request)

    audit = AppendOnlyQwenAuditLogV2(tmp_path / "audit")
    session = FormalQwenServiceSessionV2(
        runtime=SimpleNamespace(binding=_bundle(), secret=SECRET),  # type: ignore[arg-type]
        audit=audit,
        predictor=counted,  # type: ignore[arg-type]
    )
    for index in range(8):
        session.handle(sign_inference_request(_request(index), SECRET).model_dump(mode="json"))
    with pytest.raises(RuntimeError, match="eight responses"):
        session.handle(sign_inference_request(_request(7), SECRET).model_dump(mode="json"))
    assert calls == list(range(8))
    assert _records(audit.service_path)[-1]["event_type"] == "WIRE_REQUEST_REJECTED"


def test_transport_rejection_has_no_wire_or_secret_and_service_stop_is_idempotent(
    tmp_path: Path,
) -> None:
    session, audit = _session(tmp_path)
    session.reject_transport(path="/not-formal", error_type="UnknownEndpoint")
    session.stop()
    session.stop()
    records = _records(audit.service_path)
    assert [record["event_type"] for record in records] == [
        "SERVICE_STARTED",
        "WIRE_REQUEST_REJECTED",
        "SERVICE_STOPPED",
    ]
    assert records[1]["payload"] == {
        "error_type": "UnknownEndpoint",
        "formal_evidence_accepted": False,
        "path": "/not-formal",
    }
    assert SECRET.decode("ascii") not in audit.service_path.read_text()
    assert records[-1]["payload"]["rejections_recorded"] == 1
    assert records[-1]["payload"]["teacher_used"] is False
    assert records[-1]["payload"]["privileged_truth_policy_input"] is False
    assert FORMAL_INFERENCE_PATH in audit.service_path.read_text()


def test_service_source_stops_only_after_flushing_completed_response() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts/m2c/serve_qwen_coarse_v2.py"
    ).read_text()
    flush = source.index("self.wfile.flush()")
    completed = source.index("if self.path == FORMAL_INFERENCE_PATH and session.completed:")
    shutdown = source.index('target=server_holder["server"].shutdown')
    assert flush < completed < shutdown
