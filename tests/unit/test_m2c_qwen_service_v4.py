"""Contract tests for the real-bundle-only formal Qwen V4 service."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from m2c.qwen_coarse_v4 import (
    BUNDLE_MANIFEST_NAME,
    initialize_numpy_heads_v4,
    sha256_tree_v4,
)
from m2c.qwen_decision_level_v4 import (
    DECISION_BUNDLE_MANIFEST_NAME,
    load_adr0026_decision_bundle_v4,
    write_adr0026_decision_bundle_v4,
)
from m2c.serve_qwen_coarse_v4 import (
    AppendOnlyQwenAuditLogV4,
    FormalQwenServiceSessionV4,
    _binding_from_verified_bundle_v4,
)
from test_m2c_path_blocked_supervision_v4 import (
    associated_tracks_to_perception_tracks_v4,
    attribute_binding,
    canonical_sha256,
    capture,
    deployment,
    journal,
    session_receipt,
)
from test_m2c_qwen_decision_level_v4 import _dataset_report
from xh_agent.perception.public_track_associator_v2 import PublicTrackAssociatorV2
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
    formal_public_capture_receipt_v4,
    public_asset_inline_v4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    ADR0026_DECISION_BUNDLE_CONTRACT_V4,
    FormalInferenceRequestV4,
    build_inference_response_from_logits_v4,
    sign_inference_request_v4,
    verify_inference_response_v4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    canonical_json_bytes,
    canonical_sha256 as wire_canonical_sha256,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import EXPECTED_PATH_BLOCKED_CHAIN
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2C_Q012_V4_SKILL_LABELS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
    PublicAssociationReplayFrameV4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)

from test_m2c_formal_split_runner_v4 import HASH, SECRET, _bundle


def _rgb() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), (40, 50, 60)).save(stream, "PNG")
    return stream.getvalue()


def _depth() -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.ones((2, 2), dtype=np.float32), allow_pickle=False)
    return stream.getvalue()


def _observations() -> list[FormalPublicObservationV4]:
    frozen_deployment = deployment()
    frozen_attribute = attribute_binding()
    captures = []
    previous = None
    for index in range(8):
        current = capture(
            100 + index * 100,
            [(0.01 + index * 0.001, "yellow", 0.90), (0.31, "blue", 0.94)],
            previous=previous,
        )
        captures.append(current)
        previous = current

    rgb = _rgb()
    depth = _depth()
    observations: list[FormalPublicObservationV4] = []
    for index in range(8):
        prefix = captures[: index + 1]
        frozen_journal = journal(prefix)
        frozen_session = session_receipt(frozen_journal, frozen_deployment)
        associator = PublicTrackAssociatorV2(
            expected_deployment=frozen_deployment,
            expected_deployment_binding_sha256=frozen_deployment.deployment_binding_sha256,
            expected_journal=frozen_journal,
            expected_session_receipt=frozen_session,
            expected_session_receipt_sha256=frozen_session.session_receipt_sha256,
        )
        frames: list[PublicAssociationReplayFrameV4] = []
        for item in prefix:
            associated = associator.associate(item)
            frames.append(
                PublicAssociationReplayFrameV4(
                    capture=item,
                    associated_tracks=associated,
                    associated_tracks_sha256=canonical_sha256(
                        [track.model_dump(mode="json") for track in associated]
                    ),
                )
            )
        tracks = associated_tracks_to_perception_tracks_v4(frames[-1].associated_tracks)
        candidates = build_public_track_candidates_v4(
            tracks,
            declared_target_attribute="yellow",
        )
        current = prefix[-1]
        public = PathBlockedPublicObservationV4(
            schema_version="PathBlockedPublicObservationV4",
            observation_id=f"formal-v4-observation-{index}",
            captured_at_ns=current.timestamp_ns,
            source="PUBLIC_RGBD",
            fresh=True,
            rgb_uri=f"dataset://formal-v4/rgb-{index}.png",
            depth_uri=f"dataset://formal-v4/depth-{index}.npy",
            rgb_sha256=hashlib.sha256(rgb).hexdigest(),
            depth_sha256=hashlib.sha256(depth).hexdigest(),
            capture_receipt_sha256=current.capture_receipt_sha256,
            public_track_associator_revision="PublicTrackAssociatorV2",
            camera_frame=frozen_deployment.protocol.declared_camera_frame,
            position_units="m",
            calibration_sha256=frozen_deployment.protocol.calibration_sha256,
            association_history=frames,
            perception_tracks=tracks,
            declared_target_attribute="yellow",
            candidate_payload=canonical_candidate_payload_v4(candidates),
            candidate_payload_sha256=canonical_candidate_sha256_v4(candidates),
            teacher_used=False,
            privileged_truth_policy_input=False,
            task_target_track_id_used_for_candidates=False,
        )
        capture_receipt = formal_public_capture_receipt_v4(
            observation=public,
            association_deployment_sha256=frozen_deployment.deployment_binding_sha256,
            proprioception_journal_sha256=frozen_journal.journal_sha256,
            association_session_receipt_sha256=frozen_session.session_receipt_sha256,
            declared_attribute_binding_sha256=frozen_attribute.binding_sha256,
        )
        observations.append(
            FormalPublicObservationV4(
                observation=public,
                previous_physical_completed_at_ns=current.timestamp_ns - 50,
                rgb=public_asset_inline_v4(
                    uri=public.rgb_uri,
                    sha256=public.rgb_sha256,
                    media_type="image/png",
                    data=rgb,
                ),
                depth=public_asset_inline_v4(
                    uri=public.depth_uri,
                    sha256=public.depth_sha256,
                    media_type="application/x-npy",
                    data=depth,
                ),
                canonical_slots=[
                    *[item.track_id for item in candidates],
                    *([None] * (8 - len(candidates))),
                ],
                association_deployment=frozen_deployment,
                association_deployment_sha256=frozen_deployment.deployment_binding_sha256,
                proprioception_journal=frozen_journal,
                proprioception_journal_sha256=frozen_journal.journal_sha256,
                association_session_receipt=frozen_session,
                association_session_receipt_sha256=frozen_session.session_receipt_sha256,
                declared_attribute_binding=frozen_attribute,
                declared_attribute_binding_sha256=frozen_attribute.binding_sha256,
                formal_capture_receipt=capture_receipt,
            )
        )
    return observations


def _history(index: int, target: str) -> list[PublicExecutedIntentHistoryItemV2]:
    items: list[PublicExecutedIntentHistoryItemV2] = []
    for decision_index, skill in enumerate(EXPECTED_PATH_BLOCKED_CHAIN[:index]):
        items.append(
            PublicExecutedIntentHistoryItemV2(
                decision_index=decision_index,
                selected_skill=skill,
                target_track_id=None if skill == "REOBSERVE" else target,
                destination_cell=("BIN_CELL_0" if skill in {"MOVE", "PLACE"} else None),
                physical_receipt_sha256=f"{decision_index + 1:064x}",
                execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
            )
        )
    return items


def _requests() -> list[FormalInferenceRequestV4]:
    observations = _observations()
    target = observations[0].canonical_slots[0]
    assert target is not None
    requests: list[FormalInferenceRequestV4] = []
    for index, observation in enumerate(observations):
        history = _history(index, target)
        requests.append(
            FormalInferenceRequestV4(
                run_id="formal-v4-service-run",
                challenge_nonce="e" * 64,
                request_id=f"formal-v4-service-run-decision-{index}",
                decision_index=index,
                sent_at_ns=observation.captured_at_ns + 10,
                executed_intent_history=history,
                prior_decisions_sha256=wire_canonical_sha256(history),
                bundle=_bundle(),
                observation=observation,
            )
        )
    return requests


def _predict(_runtime: object, request: FormalInferenceRequestV4):  # noqa: ANN202
    skills = np.full(17, -10.0)
    skills[M2C_Q012_V4_SKILL_LABELS.index(EXPECTED_PATH_BLOCKED_CHAIN[request.decision_index])] = (
        10.0
    )
    pointers = np.full(9, -10.0)
    pointers[8 if request.decision_index == 5 else 0] = 10.0
    destinations = np.full(7, -10.0)
    destinations[0 if request.decision_index in {2, 3} else 6] = 10.0
    return build_inference_response_from_logits_v4(
        request,
        skill_logits=skills,
        pointer_logits=pointers,
        destination_logits=destinations,
        prompt_sha256=HASH,
        pooled_feature_sha256=HASH,
        head_tensor_sha256={
            name: HASH
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


def _records(path: Path) -> list[dict[str, object]]:
    lines = path.read_bytes().splitlines()
    records = [json.loads(line) for line in lines]
    assert all(canonical_json_bytes(record) == line for record, line in zip(records, lines))
    assert [record["sequence"] for record in records] == list(range(1, len(records) + 1))
    return records


def test_v4_service_commits_exact_eight_pairs_and_clean_stop(tmp_path: Path) -> None:
    requests = _requests()
    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    runtime = SimpleNamespace(binding=_bundle(), secret=SECRET)
    session = FormalQwenServiceSessionV4(
        runtime=runtime,  # type: ignore[arg-type]
        audit=audit,
        predictor=_predict,  # type: ignore[arg-type]
    )
    for index, request in enumerate(requests):
        raw = sign_inference_request_v4(request, SECRET).model_dump(mode="json")
        response = session.handle(raw)
        assert verify_inference_response_v4(response, SECRET).payload.decision_index == index
    assert session.completed is True
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
    assert records[-2]["payload"]["protocol"] == "M2C_FORMAL_SPLIT_RUNNER_V4"
    assert records[-1]["payload"]["completed"] is True
    assert records[-1]["payload"]["poisoned"] is False


def test_v4_service_rejects_reused_capture_before_predictor(tmp_path: Path) -> None:
    requests = _requests()
    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    calls: list[int] = []

    def counted(runtime: object, request: FormalInferenceRequestV4):  # noqa: ANN202
        calls.append(request.decision_index)
        return _predict(runtime, request)

    session = FormalQwenServiceSessionV4(
        runtime=SimpleNamespace(binding=_bundle(), secret=SECRET),  # type: ignore[arg-type]
        audit=audit,
        predictor=counted,  # type: ignore[arg-type]
    )
    session.handle(sign_inference_request_v4(requests[0], SECRET).model_dump(mode="json"))
    crossed = requests[1].model_copy(
        update={
            "observation": requests[0].observation,
            "sent_at_ns": requests[1].sent_at_ns,
        }
    )
    with pytest.raises(ValueError, match="reuses a public capture"):
        session.handle(sign_inference_request_v4(crossed, SECRET).model_dump(mode="json"))
    assert calls == [0]
    assert session.poisoned is True
    assert _records(audit.service_path)[-1]["event_type"] == "WIRE_REQUEST_REJECTED"


def test_v4_service_rejects_request_bundle_before_predictor(tmp_path: Path) -> None:
    request = _requests()[0]
    payload = request.model_dump(mode="json")
    payload["bundle"]["bundle_sha256"] = "f" * 64
    crossed = FormalInferenceRequestV4.model_validate(payload)
    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    session = FormalQwenServiceSessionV4(
        runtime=SimpleNamespace(binding=_bundle(), secret=SECRET),  # type: ignore[arg-type]
        audit=audit,
        predictor=lambda *_args: pytest.fail("predictor must not run"),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="loaded runtime binding"):
        session.handle(sign_inference_request_v4(crossed, SECRET).model_dump(mode="json"))


def test_v4_service_rejects_history_that_does_not_extend_prior_response(
    tmp_path: Path,
) -> None:
    requests = _requests()
    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    calls: list[int] = []

    def counted(runtime: object, request: FormalInferenceRequestV4):  # noqa: ANN202
        calls.append(request.decision_index)
        return _predict(runtime, request)

    session = FormalQwenServiceSessionV4(
        runtime=SimpleNamespace(binding=_bundle(), secret=SECRET),  # type: ignore[arg-type]
        audit=audit,
        predictor=counted,  # type: ignore[arg-type]
    )
    session.handle(sign_inference_request_v4(requests[0], SECRET).model_dump(mode="json"))
    payload = requests[1].model_dump(mode="json")
    payload["executed_intent_history"][0]["selected_skill"] = "LIFT"
    payload["prior_decisions_sha256"] = wire_canonical_sha256(payload["executed_intent_history"])
    crossed = FormalInferenceRequestV4.model_validate(payload)
    with pytest.raises(ValueError, match="differs from prior model response"):
        session.handle(sign_inference_request_v4(crossed, SECRET).model_dump(mode="json"))
    assert calls == [0]


def test_v4_service_rejects_predictor_pointer_splice_before_audit_commit(
    tmp_path: Path,
) -> None:
    request = _requests()[0]

    def crossed_predictor(runtime: object, active: FormalInferenceRequestV4):  # noqa: ANN202
        response = _predict(runtime, active)
        payload = response.model_dump(mode="json")
        payload["intent"]["target_track_id"] = active.observation.canonical_slots[1]
        return response.model_validate(payload)

    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    session = FormalQwenServiceSessionV4(
        runtime=SimpleNamespace(binding=_bundle(), secret=SECRET),  # type: ignore[arg-type]
        audit=audit,
        predictor=crossed_predictor,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="decoded pointer differs"):
        session.handle(sign_inference_request_v4(request, SECRET).model_dump(mode="json"))
    events = [record["event_type"] for record in _records(audit.service_path)]
    assert "WIRE_RESPONSE_COMMITTED" not in events
    assert events[-1] == "WIRE_REQUEST_REJECTED"


def test_v4_service_builds_binding_only_from_exact_manifest_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    (bundle_root / BUNDLE_MANIFEST_NAME).write_bytes(b"exact-v4-bundle-manifest")
    model_snapshot = (
        tmp_path
        / "cache/models--Qwen--Qwen3.5-4B/snapshots/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
    )
    model_snapshot.mkdir(parents=True)
    cache_sha = "d" * 64
    monkeypatch.setattr("m2c.serve_qwen_coarse_v4.sha256_tree", lambda _path: cache_sha)
    frozen = _bundle()
    manifest = SimpleNamespace(
        schema_version="M2CQwenCoarseV4BundleManifestV1",
        model_id=frozen.model_id,
        model_revision=frozen.model_revision,
        bundle_sha256=frozen.bundle_sha256,
        base_model_snapshot_tree_sha256=cache_sha,
        head_checkpoint_sha256=frozen.head_checkpoint_sha256,
        head_deployment_file_sha256=frozen.head_deployment_file_sha256,
        head_deployment=SimpleNamespace(
            deployment_manifest_sha256=frozen.head_deployment_manifest_sha256,
            checkpoint_binding_sha256=frozen.checkpoint_binding_sha256,
        ),
        adapter_tree_sha256=frozen.adapter_tree_sha256,
        training_dataset_sha256=frozen.training_dataset_sha256,
        training_manifest_file_sha256=frozen.training_manifest_file_sha256,
        training_manifest_sha256=frozen.training_manifest_sha256,
        s6_manifest_file_sha256=frozen.s6_manifest_file_sha256,
        s6_manifest_sha256=frozen.s6_manifest_sha256,
        failure_context=frozen.failure_context,
    )
    args = SimpleNamespace(
        bundle_root=bundle_root,
        expected_bundle_sha256=frozen.bundle_sha256,
        model_id=frozen.model_id,
        revision=frozen.model_revision,
        cache_tree_sha256=cache_sha,
        association_deployment_sha256=frozen.association_deployment_sha256,
        capture_source_implementation_sha256=frozen.capture_source_implementation_sha256,
        declared_attribute_selector_implementation_sha256=(
            frozen.declared_attribute_selector_implementation_sha256
        ),
    )
    binding = _binding_from_verified_bundle_v4(
        args,
        loaded=SimpleNamespace(
            manifest=manifest,
            heads=initialize_numpy_heads_v4(4, 7),
        ),
        model_snapshot=model_snapshot,
        bundle_manifest_raw=b"exact-v4-bundle-manifest",
        bundle_tree_sha256="e" * 64,
    )
    assert binding.bundle_sha256 == frozen.bundle_sha256
    assert (
        binding.bundle_manifest_file_sha256
        == hashlib.sha256(b"exact-v4-bundle-manifest").hexdigest()
    )
    assert binding.association_deployment_sha256 == frozen.association_deployment_sha256

    args.expected_bundle_sha256 = "f" * 64
    with pytest.raises(ValueError, match="canonical digest"):
        _binding_from_verified_bundle_v4(
            args,
            loaded=SimpleNamespace(
                manifest=manifest,
                heads=initialize_numpy_heads_v4(4, 7),
            ),
            model_snapshot=model_snapshot,
            bundle_manifest_raw=b"exact-v4-bundle-manifest",
            bundle_tree_sha256="e" * 64,
        )


def test_v4_service_binds_exact_adr0026_decision_bundle_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "decision-bundle"
    (bundle_root / "adapter").mkdir(parents=True)
    (bundle_root / "adapter" / "adapter.bin").write_bytes(b"decision-adapter")
    cache_sha = "8" * 64
    manifest = write_adr0026_decision_bundle_v4(
        bundle_root,
        heads=initialize_numpy_heads_v4(16, 20260815),
        model_id="Qwen/Qwen3.5-4B",
        model_revision="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
        base_model_snapshot_tree_sha256=cache_sha,
        failure_context="on",
        dataset_report=_dataset_report(),
        seed=20260815,
        optimizer_steps=7,
    )
    loaded = load_adr0026_decision_bundle_v4(
        bundle_root,
        expected_bundle_sha256=manifest.bundle_sha256,
    )
    model_snapshot = (
        tmp_path
        / "cache/models--Qwen--Qwen3.5-4B/snapshots/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
    )
    model_snapshot.mkdir(parents=True)
    monkeypatch.setattr("m2c.serve_qwen_coarse_v4.sha256_tree", lambda _path: cache_sha)
    args = SimpleNamespace(
        bundle_contract=ADR0026_DECISION_BUNDLE_CONTRACT_V4,
        expected_bundle_sha256=manifest.bundle_sha256,
        model_id=manifest.model_id,
        revision=manifest.model_revision,
        cache_tree_sha256=cache_sha,
        association_deployment_sha256="1" * 64,
        capture_source_implementation_sha256="2" * 64,
        declared_attribute_selector_implementation_sha256="3" * 64,
    )
    raw = (bundle_root / DECISION_BUNDLE_MANIFEST_NAME).read_bytes()
    binding = _binding_from_verified_bundle_v4(
        args,
        loaded=loaded,
        model_snapshot=model_snapshot,
        bundle_manifest_raw=raw,
        bundle_tree_sha256=sha256_tree_v4(bundle_root),
    )

    assert binding.bundle_manifest_schema_version == ("M2CQwenADR0026DecisionBundleManifestV1")
    assert binding.training_contract_revision == ADR0026_DECISION_BUNDLE_CONTRACT_V4
    assert binding.training_manifest_file_sha256 == (manifest.training_dataset_manifest_file_sha256)
    assert binding.training_manifest_sha256 == manifest.training_dataset_manifest_sha256
    assert binding.training_dataset_report_file_sha256 == (
        manifest.training_dataset_report_file_sha256
    )
    assert binding.training_dataset_report_sha256 == (manifest.training_dataset_report_sha256)
    assert [item.model_dump(mode="json") for item in binding.source_training_manifests] == [
        item.model_dump(mode="json") for item in manifest.source_training_manifests
    ]

    args.bundle_contract = "EPISODE_ATOMIC_V4_V1"
    with pytest.raises(ValueError, match="explicit runtime contract"):
        _binding_from_verified_bundle_v4(
            args,
            loaded=loaded,
            model_snapshot=model_snapshot,
            bundle_manifest_raw=raw,
            bundle_tree_sha256=sha256_tree_v4(bundle_root),
        )


def test_v4_audit_rejects_path_replacement_and_stop_is_idempotent(tmp_path: Path) -> None:
    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    original = audit.service_path
    moved = original.with_suffix(".moved")
    original.rename(moved)
    original.write_bytes(b"")
    with pytest.raises(RuntimeError, match="descriptor identity changed"):
        audit.append("CONTRACT_ONLY", {})
    assert moved.read_text().count("SERVICE_STARTED") == 1
    assert original.read_bytes() == b""


def test_v4_session_checks_hard_freeze_before_verification_or_predictor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _requests()[0]
    audit = AppendOnlyQwenAuditLogV4(tmp_path / "audit")
    session = FormalQwenServiceSessionV4(
        runtime=SimpleNamespace(binding=_bundle(), secret=SECRET),  # type: ignore[arg-type]
        audit=audit,
        predictor=lambda *_args: pytest.fail("predictor must not run after freeze"),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "m2c.serve_qwen_coarse_v4.require_pre_freeze",
        lambda _action: (_ for _ in ()).throw(RuntimeError("frozen")),
    )
    with pytest.raises(RuntimeError, match="frozen"):
        session.handle(sign_inference_request_v4(request, SECRET).model_dump(mode="json"))
    events = [record["event_type"] for record in _records(audit.service_path)]
    assert events == ["SERVICE_STARTED", "WIRE_REQUEST_RECEIVED", "WIRE_REQUEST_REJECTED"]


def test_v4_service_source_flushes_eighth_response_before_shutdown() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts/m2c/serve_qwen_coarse_v4.py"
    ).read_text()
    flush = source.index("self.wfile.flush()")
    completed = source.index("if self.path == FORMAL_INFERENCE_PATH_V4 and session.completed:")
    shutdown = source.index('target=server_holder["server"].shutdown')
    assert flush < completed < shutdown
