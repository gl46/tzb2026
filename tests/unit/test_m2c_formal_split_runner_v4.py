from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from test_m2c_formal_public_observation_v4 import _formal
from test_m2c_path_blocked_supervision_v4 import attribute_binding
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_WIRE_PROTOCOL_V4,
    FormalInferenceRequestV4,
    IsaacCaptureResponseV4,
    IsaacExecuteRequestV4,
    QwenBundleRuntimeBindingV4,
    RuntimeSkillRequestV4,
    build_inference_response_from_logits_v4,
    runtime_qwen_prompt_v4,
    runtime_request_from_inference_v4,
    sign_inference_request_v4,
    sign_inference_response_v4,
    sign_isaac_wire_message_v4,
    validate_runtime_mapping_v4,
    validate_inference_response_binding_v4,
    verify_inference_request_v4,
    verify_inference_response_v4,
    verify_isaac_wire_message_v4,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2C_Q012_V4_SKILL_LABELS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml")
SECRET = b"formal-v4-wire-test-key-is-at-least-32-bytes"
HASH = "a" * 64


def _bundle() -> QwenBundleRuntimeBindingV4:
    observation = _formal()
    return QwenBundleRuntimeBindingV4(
        bundle_manifest_file_sha256="1" * 64,
        bundle_tree_sha256="0" * 64,
        bundle_sha256="2" * 64,
        head_checkpoint_sha256="3" * 64,
        head_deployment_file_sha256="4" * 64,
        head_deployment_manifest_sha256="5" * 64,
        checkpoint_binding_sha256="6" * 64,
        adapter_tree_sha256="7" * 64,
        training_dataset_sha256="8" * 64,
        training_manifest_file_sha256="9" * 64,
        training_manifest_sha256="a" * 64,
        s6_manifest_file_sha256="b" * 64,
        s6_manifest_sha256="c" * 64,
        association_deployment_sha256=observation.association_deployment_sha256,
        capture_source_implementation_sha256=(
            observation.association_deployment.capture_source_implementation_sha256
        ),
        declared_attribute_selector_implementation_sha256=(
            observation.declared_attribute_binding.selector_source_implementation_sha256
        ),
        model_cache_dir=(
            "/verified/hf-cache/models--Qwen--Qwen3.5-4B/snapshots/"
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
        ),
        model_cache_tree_sha256="d" * 64,
        failure_context="on",
    )


def test_v4_runtime_binding_discriminates_adr0026_dataset_sources() -> None:
    payload = _bundle().model_dump(mode="json")
    payload.update(
        {
            "bundle_manifest_schema_version": ("M2CQwenADR0026DecisionBundleManifestV1"),
            "training_contract_revision": "ADR0026_DECISION_LEVEL_PREFIX_0_6_V1",
            "training_dataset_report_file_sha256": "e" * 64,
            "training_dataset_report_sha256": "f" * 64,
            "source_training_manifests": [
                {"file_sha256": "1" * 64, "canonical_sha256": "2" * 64},
                {"file_sha256": "3" * 64, "canonical_sha256": "4" * 64},
            ],
        }
    )
    decision = QwenBundleRuntimeBindingV4.model_validate(payload)
    assert decision.training_contract_revision == ("ADR0026_DECISION_LEVEL_PREFIX_0_6_V1")
    assert len(decision.source_training_manifests) == 2

    payload["training_contract_revision"] = "EPISODE_ATOMIC_V4_V1"
    with pytest.raises(ValueError, match="schema and training contract differ"):
        QwenBundleRuntimeBindingV4.model_validate(payload)

    payload = _bundle().model_dump(mode="json")
    payload["training_dataset_report_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="ADR-0026-only sources"):
        QwenBundleRuntimeBindingV4.model_validate(payload)


def _request(
    observation: FormalPublicObservationV4 | None = None,
) -> FormalInferenceRequestV4:
    observation = observation or _formal()
    return FormalInferenceRequestV4(
        run_id="formal-v4-run",
        challenge_nonce="e" * 64,
        request_id="formal-v4-run-decision-0",
        decision_index=0,
        sent_at_ns=observation.captured_at_ns + 10,
        executed_intent_history=[],
        prior_decisions_sha256=canonical_sha256([]),
        bundle=_bundle(),
        observation=observation,
    )


def _logits(
    *,
    skill: str = "LIFT",
    pointer: int = 0,
    destination: str = "NONE",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    skills = np.full(len(M2C_Q012_V4_SKILL_LABELS), -10.0)
    skills[M2C_Q012_V4_SKILL_LABELS.index(skill)] = 10.0
    pointers = np.full(9, -10.0)
    pointers[pointer] = 10.0
    destinations = np.full(len(DESTINATION_CLASS_LABELS), -10.0)
    destinations[DESTINATION_CLASS_LABELS.index(destination)] = 10.0
    return skills, pointers, destinations


def _response(request: FormalInferenceRequestV4):  # noqa: ANN202
    skills, pointers, destinations = _logits()
    return build_inference_response_from_logits_v4(
        request,
        skill_logits=skills,
        pointer_logits=pointers,
        destination_logits=destinations,
        prompt_sha256="f" * 64,
        pooled_feature_sha256="0" * 64,
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


def _role_ranked_nonlexical_observation() -> FormalPublicObservationV4:
    payload = _formal().model_dump(mode="json")
    observation = payload["observation"]
    tracks = observation["perception_tracks"]
    candidates = build_public_track_candidates_v4(
        [
            {key: track[key] for key in ("track_id", "category", "confidence", "pose_xyzquat")}
            for track in tracks
        ],
        declared_target_attribute="blue",
    )
    attribute = attribute_binding("blue")
    observation["declared_target_attribute"] = "blue"
    observation["candidate_payload"] = canonical_candidate_payload_v4(candidates)
    observation["candidate_payload_sha256"] = canonical_candidate_sha256_v4(candidates)
    payload["canonical_slots"] = [
        *[item.track_id for item in candidates],
        *([None] * (8 - len(candidates))),
    ]
    payload["declared_attribute_binding"] = attribute.model_dump(mode="json")
    payload["declared_attribute_binding_sha256"] = attribute.binding_sha256
    capture = payload["formal_capture_receipt"]
    capture["candidate_payload_sha256"] = observation["candidate_payload_sha256"]
    capture["declared_attribute_binding_sha256"] = attribute.binding_sha256
    capture["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in capture.items() if key != "receipt_sha256"}
    )
    formal = FormalPublicObservationV4.model_validate(payload)
    populated = [item for item in formal.canonical_slots if item is not None]
    assert populated != sorted(populated)
    return formal


def test_v4_wire_is_versioned_and_hmac_binds_complete_replayed_observation() -> None:
    request = _request()
    signed = sign_inference_request_v4(request, SECRET)
    restored = verify_inference_request_v4(signed.model_dump(mode="json"), SECRET)

    assert FORMAL_WIRE_PROTOCOL_V4 == "M2C_FORMAL_SPLIT_RUNNER_V4"
    assert FORMAL_INFERENCE_PATH_V4 == "/v1/m2c/qwen-coarse-v4/predict"
    assert restored.payload.observation.wire_sha256 == request.observation.wire_sha256
    assert restored.payload.bundle.architecture_revision == "M2C_Q012_V4"
    assert restored.payload.bundle.training_complete is True
    assert restored.payload.teacher_used is False
    assert restored.payload.privileged_truth_policy_input is False

    tampered = signed.model_dump(mode="json")
    tampered["payload"]["observation"]["canonical_slots"][0] = "track-deadbeef"
    with pytest.raises((ValidationError, ValueError)):
        verify_inference_request_v4(tampered, SECRET)


def test_v4_prompt_and_decode_use_exact_replayed_candidate_payload() -> None:
    request = _request()
    prompt = runtime_qwen_prompt_v4(request)
    response = _response(request)

    assert '"checkpoint_architecture_revision":"M2C_Q012_V4"' in prompt
    assert request.observation.canonical_public_tracks_sha256 == canonical_sha256(
        request.observation.observation.candidate_payload
    )
    assert response.intent.target_track_id == request.observation.canonical_slots[0]
    assert response.candidate_payload_sha256 == (request.observation.canonical_public_tracks_sha256)
    assert response.formal_observation_sha256 == request.observation.wire_sha256
    assert (
        verify_inference_response_v4(
            sign_inference_response_v4(response, SECRET).model_dump(mode="json"),
            SECRET,
        ).payload
        == response
    )


def test_v4_decode_masks_padded_pointer_slots_and_rejects_wrong_shapes() -> None:
    request = _request()
    skills, pointers, destinations = _logits(pointer=7)
    response = build_inference_response_from_logits_v4(
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
        completed_at_ns=request.sent_at_ns + 1,
    )
    assert response.pointer.selected_index == 0
    assert response.pointer.logits[7] is None

    with pytest.raises(ValueError, match="wrong shape"):
        build_inference_response_from_logits_v4(
            request,
            skill_logits=np.zeros(1),
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
            completed_at_ns=request.sent_at_ns + 1,
        )


def test_v4_runtime_mapping_preserves_role_ranked_nonlexical_slot() -> None:
    observation = _role_ranked_nonlexical_observation()
    request = _request(observation)
    response = _response(request)
    runtime = runtime_request_from_inference_v4(request, response, REGISTRY)
    mapping = validate_runtime_mapping_v4(runtime, observation, REGISTRY)

    assert runtime.canonical_track_ids[:2] != sorted(runtime.canonical_track_ids[:2])
    assert runtime.model_target_slot == 0
    assert mapping.status == "VALID"
    assert mapping.fallback_action == "NO_PHYSICAL_EXECUTION"
    assert mapping.target_track_id == observation.canonical_slots[0]
    assert mapping.target_track_slot == 0
    assert next(item for item in mapping.gate_trace if item["gate"] == "track")["slot"] == 0


def test_v4_execute_request_and_isaac_hmac_bind_full_observation() -> None:
    request = _request()
    response = _response(request)
    signed_response = sign_inference_response_v4(response, SECRET)
    runtime = runtime_request_from_inference_v4(request, response, REGISTRY)
    execute = IsaacExecuteRequestV4(
        run_id=request.run_id,
        session_id="isaac-v4-session",
        decision_index=request.decision_index,
        observation_id=request.observation.observation_id,
        capture_receipt_sha256=request.observation.capture_receipt_sha256,
        formal_observation_sha256=request.observation.wire_sha256,
        canonical_public_tracks_sha256=request.observation.canonical_public_tracks_sha256,
        inference_response_sha256=signed_response.payload_sha256,
        executed_intent_history_sha256=request.prior_decisions_sha256,
        observation=request.observation,
        runtime_request=runtime,
    )
    signed = sign_isaac_wire_message_v4("ISAAC_EXECUTE_REQUEST_V4", execute, SECRET)
    _, restored = verify_isaac_wire_message_v4(
        signed.model_dump(mode="json"),
        SECRET,
        expected_type="ISAAC_EXECUTE_REQUEST_V4",
        model=IsaacExecuteRequestV4,
    )
    assert restored == execute

    tampered = execute.model_dump(mode="json")
    tampered["canonical_public_tracks_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="crosses its replayed observation"):
        IsaacExecuteRequestV4.model_validate(tampered)


def test_v4_capture_wire_and_protocol_cannot_be_silently_downgraded() -> None:
    observation = _formal()
    capture = IsaacCaptureResponseV4(
        run_id="formal-v4-run",
        session_id="isaac-v4-session",
        decision_index=0,
        observation=observation,
        formal_observation_sha256=observation.wire_sha256,
    )
    signed = sign_isaac_wire_message_v4("ISAAC_CAPTURE_RESPONSE_V4", capture, SECRET)
    _, restored = verify_isaac_wire_message_v4(
        signed.model_dump(mode="json"),
        SECRET,
        expected_type="ISAAC_CAPTURE_RESPONSE_V4",
        model=IsaacCaptureResponseV4,
    )
    assert restored.protocol == "M2C_FORMAL_SPLIT_RUNNER_V4"

    downgraded = copy.deepcopy(capture.model_dump(mode="json"))
    downgraded["protocol"] = "M2C_FORMAL_SPLIT_RUNNER_V2"
    with pytest.raises(ValidationError):
        IsaacCaptureResponseV4.model_validate(downgraded)


def test_v4_bundle_rejects_unfrozen_model_cache() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["model_cache_dir"] = "/tmp/current"
    with pytest.raises(ValidationError, match="frozen revision snapshot"):
        QwenBundleRuntimeBindingV4.model_validate(payload)


def test_v4_runtime_request_rejects_task_spec_or_candidate_splice() -> None:
    request = _request()
    response = _response(request)
    runtime = runtime_request_from_inference_v4(request, response, REGISTRY)

    payload = runtime.model_dump(mode="json")
    payload["task_target_track_id"] = "track-deadbeef"
    with pytest.raises(ValidationError):
        RuntimeSkillRequestV4.model_validate(payload)

    payload = runtime.model_dump(mode="json")
    payload["canonical_public_tracks_sha256"] = "f" * 64
    crossed = RuntimeSkillRequestV4.model_validate(payload)
    with pytest.raises(ValueError, match="differs from replayed candidates"):
        validate_runtime_mapping_v4(crossed, request.observation, REGISTRY)


def test_v4_response_binding_rejects_wrong_nonempty_pointer_literal() -> None:
    request = _request()
    response = _response(request)
    payload = response.model_dump(mode="json")
    payload["intent"]["target_track_id"] = request.observation.canonical_slots[1]
    crossed = response.model_validate(payload)
    with pytest.raises(ValueError, match="decoded pointer differs"):
        validate_inference_response_binding_v4(request, crossed)
