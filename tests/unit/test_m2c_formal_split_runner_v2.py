from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from pydantic_core import ValidationError as PydanticCoreValidationError

from m2c.run_formal_model_owned_chain import (
    HostPartialRunAuditV2,
    partial_failure_output_path,
    publish_create_only,
    run_real,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    FormalInferenceRequestV2,
    IsaacCaptureResponseV2,
    IsaacExecuteRequestV2,
    IsaacExecuteResponseV2,
    PhysicalSkillReceiptV2,
    QwenBundleRuntimeBindingV2,
    append_public_executed_intent_history,
    build_inference_response_from_logits,
    canonical_sha256,
    physical_receipt_sha256,
    runtime_qwen_prompt,
    runtime_request_from_inference,
    sign_inference_request,
    sign_inference_response,
    verify_inference_request,
    verify_inference_response,
    sign_wire_message,
    verify_wire_message,
    validate_isaac_execute_request_mapping_v2,
    validate_expected_chain_is_not_runner_selected,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    ParameterProvenanceV2,
    RuntimeSkillMappingResultV2,
    load_registry_v2,
)


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "configs/qrm_runtime_mapping_v2.yaml"
DIGEST = "a" * 64
SECRET = b"formal-split-runner-unit-key-32-bytes!!"


def _asset(data: bytes, media_type: str, uri: str) -> dict[str, object]:
    return {
        "uri": uri,
        "sha256": hashlib.sha256(data).hexdigest(),
        "media_type": media_type,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def _rgb_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(stream, format="PNG")
    return stream.getvalue()


def _depth_bytes() -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.ones((2, 2), dtype=np.float32), allow_pickle=False)
    return stream.getvalue()


def _tracks() -> list[dict[str, object]]:
    return [
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
    ]


def _observation(previous: int = 100, captured: int = 110) -> dict[str, object]:
    return {
        "observation_id": f"observation-{captured}",
        "captured_at_ns": captured,
        "previous_physical_completed_at_ns": previous,
        "rgb": _asset(_rgb_bytes(), "image/png", "dataset://public/rgb.png"),
        "depth": _asset(_depth_bytes(), "application/x-npy", "dataset://public/depth.npy"),
        "capture_receipt_sha256": "b" * 64,
        "perception_tracks": _tracks(),
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
    }


def _bundle() -> QwenBundleRuntimeBindingV2:
    return QwenBundleRuntimeBindingV2(
        bundle_manifest_sha256="1" * 64,
        head_checkpoint_sha256="2" * 64,
        adapter_tree_sha256="3" * 64,
        model_cache_dir=(
            "/verified/hf-cache/models--Qwen--Qwen3.5-4B/snapshots/"
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
        ),
        model_cache_tree_sha256="4" * 64,
        failure_context="on",
    )


def _request(
    *,
    index: int = 0,
    history: list[PublicExecutedIntentHistoryItemV2] | None = None,
) -> FormalInferenceRequestV2:
    history = history or []
    return FormalInferenceRequestV2(
        run_id="run-1",
        challenge_nonce="c" * 64,
        request_id=f"run-1-decision-{index}",
        decision_index=index,
        sent_at_ns=120,
        executed_intent_history=history,
        prior_decisions_sha256=canonical_sha256(history),
        bundle=_bundle(),
        observation=_observation(),
    )


def _response(request: FormalInferenceRequestV2, *, skill: str = "GRASP"):
    skills = np.full(17, -10.0)
    skills[
        (
            "OBSERVE",
            "APPROACH",
            "GRASP",
            "LIFT",
            "MOVE",
            "PLACE",
            "RELEASE",
            "REGRASP",
            "REOBSERVE",
            "SAFE_PLACE_NON_TARGET",
            "REASSOCIATE_TARGET",
            "RETRY_RELEASE",
            "STOP",
            "RETRY_TOP",
            "ALTERNATE_OBLIQUE",
            "ALTERNATE_SIDE",
            "ABORT_SAFE",
        ).index(skill)
    ] = 10.0
    pointer = np.full(9, -10.0)
    pointer[0] = 10.0
    destination = np.full(7, -10.0)
    destination[6] = 10.0
    return build_inference_response_from_logits(
        request,
        skill_logits=skills,
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
        completed_at_ns=130,
    )


def _physical_receipt(skill: str = "GRASP") -> dict[str, object]:
    core: dict[str, object] = {
        "receipt_id": "physical-0",
        "executed_skill": skill,
        "execution_source": "MODEL_SELECTED_REGISTERED_SKILL",
        "physically_executed": True,
        "started_at_ns": 140,
        "completed_at_ns": 150,
        "schema_gate": "PASS",
        "stale_track_gate": "PASS",
        "frame_unit_gate": "PASS",
        "ik_gate": "PASS",
        "collision_gate": "PASS",
        "controller_gate": "PASS",
        "safety_gate": "PASS",
    }
    from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2

    provisional = PhysicalSkillReceiptV2(receipt_sha256="0" * 64, **core)
    return {**core, "receipt_sha256": physical_receipt_sha256(provisional)}


def _exact_plan(
    *,
    canonical_skill: str = "GRASP",
    runtime_action: str = "B0_PUBLIC_GEOMETRY_GRASP",
    execution_parameters: dict[str, object] | None = None,
) -> ExactExecutionPlanV2:
    parameters = execution_parameters or {
        "target_track_id": "track-blocker",
        "grasp_family": "top_down",
    }
    phase = ExactExecutionPhaseV2(
        phase_index=0,
        phase_name="PREBOUND_CARTESIAN",
        command="CARTESIAN_POSE",
        goal_position_world_m=(0.1, 0.2, 0.57),
        orientation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        steps=150,
        collision_phase="CONTRACT_ONLY_EXACT_PLAN",
        gates=ExactExecutionPhaseGatesV2(
            ik_detail="contract-only exact IK gate passed",
            joint_limits_detail="contract-only joint limits passed",
            swept_collision_detail="contract-only exact sweep passed",
            controller_detail="contract-only controller gate passed",
            safety_detail="contract-only safety gate passed",
        ),
    )
    return ExactExecutionPlanV2(
        run_id="run-1",
        session_id="isaac-session",
        decision_index=0,
        observation_id="observation-110",
        capture_receipt_sha256="b" * 64,
        canonical_skill=canonical_skill,
        runtime_action=runtime_action,
        execution_parameters_sha256=canonical_sha256(parameters),
        target_track_id="track-blocker",
        phases=(phase,),
    )


def test_signed_request_binds_fresh_public_rgbd_and_rejects_tamper() -> None:
    signed = sign_inference_request(_request(), SECRET)
    restored = verify_inference_request(signed.model_dump(mode="json"), SECRET)
    assert restored.payload.observation.canonical_slots[:2] == [
        "track-blocker",
        "track-task",
    ]

    tampered = signed.model_dump(mode="json")
    tampered["payload"]["observation"]["perception_tracks"][0]["confidence"] = 0.1
    with pytest.raises(ValueError, match="SHA-256"):
        verify_inference_request(tampered, SECRET)


def test_hmac_secret_reader_rejects_symlink_or_hardlink(tmp_path: Path) -> None:
    from xh_agent.policy.qrm_lite.formal_split_runner_v2 import read_hmac_secret

    secret = tmp_path / "secret"
    secret.write_bytes(SECRET)
    secret.chmod(0o600)
    assert read_hmac_secret(secret) == SECRET

    symlink = tmp_path / "secret-symlink"
    symlink.symlink_to(secret)
    with pytest.raises(ValueError, match="non-symlink regular file"):
        read_hmac_secret(symlink)

    hardlink = tmp_path / "secret-hardlink"
    hardlink.hardlink_to(secret)
    with pytest.raises(PermissionError, match="exactly one hard link"):
        read_hmac_secret(secret)


def test_isaac_wire_hmac_binds_message_type() -> None:
    from xh_agent.policy.qrm_lite.formal_split_runner_v2 import IsaacCaptureRequestV2

    payload = IsaacCaptureRequestV2(
        run_id="run-1",
        session_id="session-1",
        decision_index=0,
    )
    signed = sign_wire_message("ISAAC_CAPTURE_REQUEST", payload, SECRET)
    tampered = signed.model_dump(mode="json")
    tampered["message_type"] = "ISAAC_FINALIZE_REQUEST"
    with pytest.raises(ValueError, match="HMAC"):
        verify_wire_message(
            tampered,
            expected_type="ISAAC_FINALIZE_REQUEST",
            payload_model=IsaacCaptureRequestV2,
            secret=SECRET,
        )


def test_public_observation_rejects_stale_capture_or_simulator_identity() -> None:
    stale = _request().model_dump(mode="json")
    stale["observation"]["captured_at_ns"] = 100
    with pytest.raises(ValidationError, match="not newer"):
        FormalInferenceRequestV2.model_validate(stale)

    oracle = _request().model_dump(mode="json")
    oracle["observation"]["perception_tracks"][0]["track_id"] = "cylinder_01"
    with pytest.raises(ValidationError, match="non-public track"):
        FormalInferenceRequestV2.model_validate(oracle)


def test_history_requires_complete_prefix_and_hash_and_enters_prompt() -> None:
    history = [
        PublicExecutedIntentHistoryItemV2(
            decision_index=0,
            selected_skill="GRASP",
            target_track_id="track-blocker",
            physical_receipt_sha256="8" * 64,
            execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        )
    ]
    request = _request(index=1, history=history)
    prompt = runtime_qwen_prompt(
        request.observation,
        use_failure_context=True,
        executed_intent_history=request.executed_intent_history,
        expected_history_length=request.decision_index,
    )
    assert '"public_executed_intent_history"' in prompt
    assert '"selected_skill":"GRASP"' in prompt
    assert '"expected_next"' not in prompt
    assert '"next_skill"' not in prompt

    gap = request.model_dump(mode="json")
    gap["executed_intent_history"][0]["decision_index"] = 1
    gap["prior_decisions_sha256"] = canonical_sha256(gap["executed_intent_history"])
    with pytest.raises(ValidationError, match="gap, reorder, or future"):
        FormalInferenceRequestV2.model_validate(gap)

    bad_hash = request.model_dump(mode="json")
    bad_hash["prior_decisions_sha256"] = "9" * 64
    with pytest.raises(ValidationError, match="prior-decisions hash"):
        FormalInferenceRequestV2.model_validate(bad_hash)

    scripted = request.model_dump(mode="json")
    scripted["executed_intent_history"][0]["execution_attribution"] = (
        "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
    )
    scripted["prior_decisions_sha256"] = canonical_sha256(scripted["executed_intent_history"])
    with pytest.raises(ValidationError, match="scripted supervision"):
        FormalInferenceRequestV2.model_validate(scripted)


def test_deterministic_heads_mask_padded_pointer_and_bind_literal() -> None:
    request = _request()
    skills = np.zeros(17)
    skills[2] = 5.0
    pointers = np.zeros(9)
    pointers[7] = 99.0  # padded, therefore masked despite being largest
    pointers[0] = 5.0
    destinations = np.zeros(7)
    destinations[6] = 5.0
    response = build_inference_response_from_logits(
        request,
        skill_logits=skills,
        pointer_logits=pointers,
        destination_logits=destinations,
        prompt_sha256=DIGEST,
        pooled_feature_sha256=DIGEST,
        head_tensor_sha256={
            name: DIGEST
            for name in (
                "skill_w",
                "skill_b",
                "pointer_w",
                "pointer_b",
                "destination_w",
                "destination_b",
            )
        },
        completed_at_ns=130,
    )
    assert response.pointer.selected_index == 0
    assert response.pointer.logits[7] is None
    assert response.intent.target_track_id == "track-blocker"
    signed = sign_inference_response(response, SECRET)
    assert verify_inference_response(signed.model_dump(mode="json"), SECRET).payload == response


def test_runtime_request_never_uses_taskspec_fallback() -> None:
    request = _request()
    response = _response(request)
    registry = load_registry_v2(REGISTRY_PATH)
    runtime = runtime_request_from_inference(request, response, registry)
    assert runtime.current_phase == "RECOVERY"
    assert runtime.task_target_track_id is None
    assert runtime.target_track_provenance == ParameterProvenanceV2.MODEL
    assert runtime.model_target_track_id == "track-blocker"


def test_expected_chain_is_only_posthoc_and_never_changes_model_intent() -> None:
    request = _request()
    response = _response(request, skill="LIFT")
    with pytest.raises(ValueError, match="model selected LIFT"):
        validate_expected_chain_is_not_runner_selected(response)
    assert response.intent.skill_type == "LIFT"
    assert "expected" not in request.model_dump(mode="json")


def test_isaac_execute_response_requires_real_one_skill_and_internal_gates() -> None:
    request = _request()
    response = _response(request)
    signed = sign_inference_response(response, SECRET)
    registry = load_registry_v2(REGISTRY_PATH)
    runtime_request = runtime_request_from_inference(request, response, registry)
    execute_request = IsaacExecuteRequestV2(
        run_id="run-1",
        session_id="isaac-session",
        decision_index=0,
        observation_id="observation-110",
        capture_receipt_sha256="b" * 64,
        inference_response_sha256=signed.payload_sha256,
        executed_intent_history_sha256=request.prior_decisions_sha256,
        runtime_request=runtime_request,
    )
    assert execute_request.task_spec_fallback_allowed is False
    exact_plan = _exact_plan()

    with pytest.raises(ValueError, match="did not inject the ik gate"):
        validate_isaac_execute_request_mapping_v2(
            execute_request,
            registry,
            ik_check=None,
            collision_check=lambda _action, _parameters: (True, "PASS"),
            controller_check=lambda _action, _parameters: (True, "PASS"),
            safety_check=lambda _action, _parameters: (True, "PASS"),
            exact_plan_getter=lambda _action, _parameters: exact_plan,
        )
    recomputed = validate_isaac_execute_request_mapping_v2(
        execute_request,
        registry,
        ik_check=lambda _action, _parameters: (True, "PASS"),
        collision_check=lambda _action, _parameters: (True, "PASS"),
        controller_check=lambda _action, _parameters: (True, "PASS"),
        safety_check=lambda _action, _parameters: (True, "PASS"),
        exact_plan_getter=lambda _action, _parameters: exact_plan,
    )
    assert recomputed.status == "VALID"

    controller_rejected = validate_isaac_execute_request_mapping_v2(
        execute_request,
        registry,
        ik_check=lambda _action, _parameters: (True, "PASS"),
        collision_check=lambda _action, _parameters: (True, "PASS"),
        controller_check=lambda _action, _parameters: (False, "NOT_READY"),
        safety_check=lambda _action, _parameters: (True, "PASS"),
        exact_plan_getter=lambda _action, _parameters: exact_plan,
    )
    assert controller_rejected.status == "INVALID"
    assert controller_rejected.fallback_required is True
    assert controller_rejected.execution_attribution == "NO_PHYSICAL_EXECUTION"

    no_action_receipt = PhysicalSkillReceiptV2(
        receipt_id="adr0024-terminal-no-action",
        receipt_sha256="0" * 64,
        executed_skill="NO_PHYSICAL_EXECUTION",
        execution_source="NO_PHYSICAL_EXECUTION",
        physically_executed=False,
        started_at_ns=120,
        completed_at_ns=121,
        schema_gate="PASS",
        stale_track_gate="PASS",
        frame_unit_gate="PASS",
        ik_gate="PASS",
        collision_gate="PASS",
        controller_gate="REJECTED",
        safety_gate="NOT_RUN",
        fallback_reason="PHYSICAL_FALLBACK_NOT_EXECUTED:ADR0024_TERMINAL_NO_ACTION",
    )
    no_action_receipt = no_action_receipt.model_copy(
        update={"receipt_sha256": physical_receipt_sha256(no_action_receipt)}
    )
    terminal = IsaacExecuteResponseV2(
        run_id=execute_request.run_id,
        session_id=execute_request.session_id,
        decision_index=execute_request.decision_index,
        observation_id=execute_request.observation_id,
        inference_response_sha256=execute_request.inference_response_sha256,
        mapping=controller_rejected,
        physical_skill_receipts=[no_action_receipt],
        requested_skill_was_physically_executed=False,
    )
    assert terminal.physical_skill_receipts[0].execution_source == "NO_PHYSICAL_EXECUTION"
    assert not terminal.physical_skill_receipts[0].physically_executed
    assert terminal.exact_execution_plan is None

    mapping = RuntimeSkillMappingResultV2(
        status="VALID",
        canonical_skill="GRASP",
        runtime_action="B0_PUBLIC_GEOMETRY_GRASP",
        target_track_id="track-blocker",
        target_track_slot=0,
        parameters={"target_track_id": "track-blocker", "grasp_family": "top_down"},
        execution_parameters={
            "target_track_id": "track-blocker",
            "grasp_family": "top_down",
        },
        parameter_provenance={
            "target_track_id": "MODEL",
            "grasp_family": "MODEL",
        },
        fallback_action="B0_SAFE_HOLD",
        fallback_required=False,
        execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        gate_trace=[
            {"gate": "schema", "status": "PASS"},
            {"gate": "track", "status": "PASS"},
            {"gate": "protocol", "status": "PASS"},
            {"gate": "ik", "status": "PASS"},
            {"gate": "collision", "status": "PASS"},
            {"gate": "controller", "status": "PASS"},
            {"gate": "safety", "status": "PASS"},
            {
                "gate": "exact_plan",
                "status": "PASS",
                "plan_sha256": canonical_sha256(exact_plan),
            },
        ],
    )
    execute = IsaacExecuteResponseV2(
        run_id="run-1",
        session_id="isaac-session",
        decision_index=0,
        observation_id="observation-110",
        inference_response_sha256=signed.payload_sha256,
        mapping=mapping,
        exact_execution_plan=exact_plan,
        exact_execution_plan_sha256=canonical_sha256(exact_plan),
        executed_exact_execution_plan_sha256=canonical_sha256(exact_plan),
        requested_skill_was_physically_executed=True,
        physical_skill_receipts=[_physical_receipt()],
    )
    history = append_public_executed_intent_history([], signed, execute)
    assert history[0].execution_attribution == "MODEL_SELECTED_REGISTERED_SKILL"

    missing_collision = execute.model_dump(mode="json")
    missing_collision["mapping"]["gate_trace"] = [
        entry
        for entry in missing_collision["mapping"]["gate_trace"]
        if entry["gate"] != "collision"
    ]
    with pytest.raises(ValidationError, match="collision"):
        IsaacExecuteResponseV2.model_validate(missing_collision)


def test_exact_plan_is_deeply_immutable_and_hash_tamper_is_rejected() -> None:
    plan = _exact_plan()
    original_sha = canonical_sha256(plan)
    with pytest.raises(PydanticCoreValidationError, match="frozen"):
        plan.phases[0].steps = 2
    assert canonical_sha256(plan) == original_sha

    request = _request()
    signed = sign_inference_response(_response(request), SECRET)
    mapping = RuntimeSkillMappingResultV2(
        status="VALID",
        canonical_skill="GRASP",
        runtime_action="B0_PUBLIC_GEOMETRY_GRASP",
        target_track_id="track-blocker",
        target_track_slot=0,
        parameters={"target_track_id": "track-blocker", "grasp_family": "top_down"},
        execution_parameters={
            "target_track_id": "track-blocker",
            "grasp_family": "top_down",
        },
        parameter_provenance={
            "target_track_id": "MODEL",
            "grasp_family": "MODEL",
        },
        fallback_action="B0_SAFE_HOLD",
        fallback_required=False,
        execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        gate_trace=[
            {"gate": gate, "status": "PASS"}
            for gate in (
                "schema",
                "track",
                "protocol",
                "ik",
                "collision",
                "controller",
                "safety",
            )
        ]
        + [
            {
                "gate": "exact_plan",
                "status": "PASS",
                "plan_sha256": original_sha,
            }
        ],
    )
    response = IsaacExecuteResponseV2(
        run_id="run-1",
        session_id="isaac-session",
        decision_index=0,
        observation_id="observation-110",
        inference_response_sha256=signed.payload_sha256,
        mapping=mapping,
        exact_execution_plan=plan,
        exact_execution_plan_sha256=original_sha,
        executed_exact_execution_plan_sha256=original_sha,
        requested_skill_was_physically_executed=True,
        physical_skill_receipts=[_physical_receipt()],
    )
    tampered = response.model_dump(mode="json")
    tampered["exact_execution_plan"]["phases"][0]["steps"] = 2
    with pytest.raises(ValidationError, match="plan hash/execution binding"):
        IsaacExecuteResponseV2.model_validate(tampered)


def test_exact_plan_construction_failure_forces_invalid_mapping() -> None:
    request = _request()
    response = _response(request)
    registry = load_registry_v2(REGISTRY_PATH)
    runtime = runtime_request_from_inference(request, response, registry)
    execute_request = IsaacExecuteRequestV2(
        run_id="run-1",
        session_id="isaac-session",
        decision_index=0,
        observation_id="observation-110",
        capture_receipt_sha256="b" * 64,
        inference_response_sha256=sign_inference_response(response, SECRET).payload_sha256,
        executed_intent_history_sha256=request.prior_decisions_sha256,
        runtime_request=runtime,
    )

    def reject_exact_plan(_action: str, _parameters: dict[str, object]) -> None:
        raise RuntimeError("no ADR-approved exact-plan physical primitive")

    mapping = validate_isaac_execute_request_mapping_v2(
        execute_request,
        registry,
        ik_check=lambda _action, _parameters: (True, "PASS"),
        collision_check=lambda _action, _parameters: (True, "PASS"),
        controller_check=lambda _action, _parameters: (True, "PASS"),
        safety_check=lambda _action, _parameters: (True, "PASS"),
        exact_plan_getter=reject_exact_plan,
    )
    assert mapping.status == "INVALID"
    assert mapping.fallback_required is True
    exact_plan_trace = next(entry for entry in mapping.gate_trace if entry["gate"] == "exact_plan")
    assert exact_plan_trace["status"] == "INVALID"
    assert "ADR-approved" in exact_plan_trace["detail"]


def test_invalid_mapping_cannot_claim_physical_b0_fallback() -> None:
    request = _request()
    signed = sign_inference_response(_response(request), SECRET)
    mapping = RuntimeSkillMappingResultV2(
        status="INVALID",
        rejection_reason="SAFETY_REJECTION",
        fallback_action="B0_SAFE_HOLD",
        fallback_required=True,
        gate_trace=[{"gate": "exact_plan", "status": "INVALID"}],
    )
    receipt = _physical_receipt()
    receipt["execution_source"] = "B0_FALLBACK"
    receipt["fallback_reason"] = "SAFETY_REJECTION"
    from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2

    provisional = PhysicalSkillReceiptV2.model_validate({**receipt, "receipt_sha256": "0" * 64})
    receipt["receipt_sha256"] = physical_receipt_sha256(provisional)
    with pytest.raises(ValidationError, match="falsely attributes an unexecuted fallback"):
        IsaacExecuteResponseV2(
            run_id="run-1",
            session_id="isaac-session",
            decision_index=0,
            observation_id="observation-110",
            inference_response_sha256=signed.payload_sha256,
            mapping=mapping,
            requested_skill_was_physically_executed=False,
            physical_skill_receipts=[receipt],
        )


def test_fallback_cannot_enter_model_owned_history() -> None:
    request = _request()
    response = _response(request)
    signed = sign_inference_response(response, SECRET)
    mapping = RuntimeSkillMappingResultV2(
        status="INVALID",
        rejection_reason="STALE_TRACK",
        fallback_action="B0_SAFE_HOLD",
        fallback_required=True,
        gate_trace=[{"gate": "track", "status": "INVALID"}],
    )
    receipt = _physical_receipt()
    receipt["execution_source"] = "NO_PHYSICAL_EXECUTION"
    receipt["executed_skill"] = "NO_PHYSICAL_EXECUTION"
    receipt["physically_executed"] = False
    receipt["ik_gate"] = "NOT_RUN"
    receipt["collision_gate"] = "NOT_RUN"
    receipt["controller_gate"] = "NOT_RUN"
    receipt["safety_gate"] = "NOT_RUN"
    receipt["fallback_reason"] = (
        "PHYSICAL_FALLBACK_NOT_EXECUTED:NO_HASH_FROZEN_UNCHANGED_B0_ACTION_WRAPPER; STALE_TRACK"
    )
    from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2

    provisional = PhysicalSkillReceiptV2.model_validate({**receipt, "receipt_sha256": "0" * 64})
    receipt["receipt_sha256"] = physical_receipt_sha256(provisional)
    execute = IsaacExecuteResponseV2(
        run_id="run-1",
        session_id="isaac-session",
        decision_index=0,
        observation_id="observation-110",
        inference_response_sha256=signed.payload_sha256,
        mapping=mapping,
        requested_skill_was_physically_executed=False,
        physical_skill_receipts=[receipt],
    )
    with pytest.raises(ValueError, match="fallback/INVALID"):
        append_public_executed_intent_history([], signed, execute)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("physically_executed", False, "non-executed physical receipt"),
        ("controller_gate", "REJECTED", "non-passing physical receipt"),
        ("collision_gate", "REJECTED", "non-passing physical receipt"),
        ("safety_gate", "REJECTED", "non-passing physical receipt"),
        ("collision_or_safety_violation", True, "unsafe physical receipt"),
    ],
)
def test_failed_physical_receipt_cannot_enter_model_owned_history(
    field: str,
    value: object,
    message: str,
) -> None:
    request = _request()
    response = _response(request)
    signed = sign_inference_response(response, SECRET)
    execution_parameters = {
        "target_track_id": "track-blocker",
        "grasp_family": "top_down",
    }
    exact_plan = _exact_plan(
        runtime_action="GRASP",
        execution_parameters=execution_parameters,
    )
    mapping = RuntimeSkillMappingResultV2(
        status="VALID",
        canonical_skill="GRASP",
        runtime_action="GRASP",
        target_track_id="track-blocker",
        target_track_slot=0,
        parameters={"target_track_id": "track-blocker", "grasp_family": "top_down"},
        execution_parameters=execution_parameters,
        parameter_provenance={
            "target_track_id": "MODEL",
            "grasp_family": "MODEL",
        },
        fallback_action="B0_SAFE_HOLD",
        fallback_required=False,
        execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
        gate_trace=[
            {"gate": "schema", "status": "PASS"},
            {"gate": "track", "status": "PASS"},
            {"gate": "protocol", "status": "PASS"},
            {"gate": "ik", "status": "PASS"},
            {"gate": "collision", "status": "PASS"},
            {"gate": "controller", "status": "PASS"},
            {"gate": "safety", "status": "PASS"},
            {
                "gate": "exact_plan",
                "status": "PASS",
                "plan_sha256": canonical_sha256(exact_plan),
            },
        ],
    )
    receipt = _physical_receipt()
    receipt[field] = value
    from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2

    provisional = PhysicalSkillReceiptV2.model_validate({**receipt, "receipt_sha256": "0" * 64})
    receipt["receipt_sha256"] = physical_receipt_sha256(provisional)
    payload = {
        "run_id": "run-1",
        "session_id": "isaac-session",
        "decision_index": 0,
        "observation_id": "observation-110",
        "inference_response_sha256": signed.payload_sha256,
        "mapping": mapping,
        "exact_execution_plan": exact_plan,
        "exact_execution_plan_sha256": canonical_sha256(exact_plan),
        "executed_exact_execution_plan_sha256": canonical_sha256(exact_plan),
        "requested_skill_was_physically_executed": field != "physically_executed",
        "physical_skill_receipts": [receipt],
    }
    if field == "physically_executed":
        with pytest.raises(ValidationError, match="receipt attribution differs"):
            IsaacExecuteResponseV2(**payload)
        return
    execute = IsaacExecuteResponseV2(**payload)

    with pytest.raises(ValueError, match=message):
        append_public_executed_intent_history([], signed, execute)


def test_public_roles_never_enter_inference_request() -> None:
    capture = IsaacCaptureResponseV2(
        run_id="run-1",
        session_id="session",
        decision_index=0,
        observation=_observation(),
        public_roles={
            "blocker_track_id": "track-blocker",
            "task_target_track_id": "track-task",
            "selector_contract_sha256": DIGEST,
        },
    )
    request = _request()
    dumped = request.model_dump(mode="json")
    assert "public_roles" not in dumped
    assert "blocker_track_id" not in dumped["observation"]
    assert capture.public_roles.blocker_track_id == "track-blocker"


def test_publish_is_create_only_and_contract_tests_cannot_make_receipt(tmp_path: Path) -> None:
    output = tmp_path / "formal.json"
    publish_create_only(output, {"status": "COMPLETE_REAL_PHYSICAL_EPISODE"})
    assert output.is_file()
    with pytest.raises(FileExistsError):
        publish_create_only(output, {"status": "OVERWRITE"})


def test_adr0024_does_not_add_a_split_proxy_unlock_binding() -> None:
    import m2c.run_formal_model_owned_chain as runner

    assert not hasattr(runner, "FORMAL_SPLIT_HMAC_PROXY_BINDING")
    assert not hasattr(runner, "require_formal_split_hmac_proxy")


def test_run_real_reloads_canonical_ledger_before_keys_or_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Args:
        challenge_consumption_ledger = Path("/canonical-ledger")
        challenge_nonce = "c" * 64
        run_id = "run"
        matched_key = "key"
        scene_seed = 1
        failure_seed = 2

    calls: list[str] = []

    def absent_ledger(**_: object) -> object:
        calls.append("ledger")
        raise FileNotFoundError("no canonical receipt")

    monkeypatch.setattr(
        "m2c.run_formal_model_owned_chain.load_consumed_wire_challenge_from_canonical_ledger",
        absent_ledger,
    )
    monkeypatch.setattr(
        "m2c.run_formal_model_owned_chain.read_hmac_secret",
        lambda _: calls.append("secret"),
    )
    monkeypatch.setattr(
        "m2c.run_formal_model_owned_chain._post_json",
        lambda *_args, **_kwargs: calls.append("endpoint"),
    )
    with pytest.raises(FileNotFoundError, match="canonical"):
        run_real(Args(), bundle=_bundle(), endpoint=object())  # type: ignore[arg-type]
    assert calls == ["ledger"]


def test_partial_failure_audit_is_never_entry_evidence_and_preserves_active_wire(
    tmp_path: Path,
) -> None:
    audit = HostPartialRunAuditV2(
        run_id="run-partial",
        matched_key="key-partial",
        scene_seed=1,
        failure_seed=2,
        bundle=_bundle().model_dump(mode="json"),
        isaac_endpoint_binding={"endpoint_base_url": "http://labserver:48132"},
    )
    audit.start_response = {"session_id": "session-real"}
    audit.begin_cycle(0)
    audit.record("capture_response", {"payload_sha256": "1" * 64})
    audit.record("inference_response", {"selected_skill": "LIFT"})
    audit.record("execute_response", {"receipt_sha256": "2" * 64})
    audit.accepted_physical_receipt_count = 1
    audit.last_physical_receipt_sha256 = "2" * 64
    payload = audit.failure_payload(ValueError("model selected LIFT; expected GRASP"))

    assert payload["status"] == "ABORTED_PARTIAL_RUN_NOT_ENTRY_EVIDENCE"
    assert payload["strict_pure_model_success"] is False
    assert payload["entry_evidence_eligible"] is False
    assert payload["continue_fixed_chain_after_error"] is False
    assert payload["accepted_physical_receipt_count"] == 1
    assert payload["wire_cycles"][0]["cycle_complete"] is False
    assert "episode" not in payload

    formal = tmp_path / "formal.json"
    sidecar = partial_failure_output_path(formal)
    publish_create_only(sidecar, payload)
    assert sidecar.name.endswith(".partial-failure.json")
    assert not formal.exists()
