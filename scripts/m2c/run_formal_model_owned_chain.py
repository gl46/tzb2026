#!/usr/bin/env python3
"""Run the real split-host M2C model-owned PATH_BLOCKED chain.

The host connects to a trained Qwen endpoint on node2 and a separately frozen,
persistent real-Isaac endpoint on labserver.  It never chooses a chain skill,
executes physics, or creates a physical receipt.  Formal evidence is published
create-only after every response has been authenticated and the strict episode
journal has been constructed from the external physical receipts.

``--contract-check-only`` validates configuration shape and deliberately exits
without contacting endpoints or writing evidence.  It is not Q-B evaluation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from m2c.qwen_coarse_v2 import BUNDLE_MANIFEST_NAME, load_bundle, sha256_file
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FORMAL_INFERENCE_PATH,
    FORMAL_ISAAC_CAPTURE_PATH,
    FORMAL_ISAAC_EXECUTE_PATH,
    FORMAL_ISAAC_FINALIZE_PATH,
    FORMAL_ISAAC_START_PATH,
    QWEN_ARCHITECTURE_REVISION,
    QWEN_MODEL_ID,
    QWEN_MODEL_REVISION,
    FormalInferenceRequestV2,
    IsaacCaptureRequestV2,
    IsaacCaptureResponseV2,
    IsaacEndpointBindingV2,
    IsaacExecuteRequestV2,
    IsaacExecuteResponseV2,
    IsaacFinalizeRequestV2,
    IsaacFinalizeResponseV2,
    IsaacStartRequestV2,
    IsaacStartResponseV2,
    QwenBundleRuntimeBindingV2,
    append_public_executed_intent_history,
    build_episode_from_external_evidence,
    canonical_sha256,
    journal_decision_from_wire,
    qwen_head_tensor_sha256,
    read_hmac_secret,
    runtime_request_from_inference,
    sign_inference_request,
    sign_wire_message,
    validate_expected_chain_is_not_runner_selected,
    verify_inference_response,
    verify_wire_message,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    ModelOwnedChainDecisionV2,
    validate_model_owned_chain_episode,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


def partial_failure_output_path(formal_output: Path) -> Path:
    """Return a deterministic sidecar that can never look like entry evidence."""

    return formal_output.with_name(formal_output.name + ".partial-failure.json")


@dataclass
class HostPartialRunAuditV2:
    """In-memory wire audit published create-only if the formal run aborts."""

    run_id: str
    matched_key: str
    scene_seed: int
    failure_seed: int
    bundle: dict[str, Any]
    isaac_endpoint_binding: dict[str, Any]
    stage: str = "CONFIGURATION_VALIDATED"
    start_request: dict[str, Any] | None = None
    start_response: dict[str, Any] | None = None
    wire_cycles: list[dict[str, Any]] = field(default_factory=list)
    active_cycle: dict[str, Any] | None = None
    finalize_request: dict[str, Any] | None = None
    finalize_response: dict[str, Any] | None = None
    accepted_physical_receipt_count: int = 0
    last_physical_receipt_sha256: str | None = None

    def begin_cycle(self, decision_index: int) -> None:
        if self.active_cycle is not None:
            raise RuntimeError("host audit already has an active decision cycle")
        self.active_cycle = {"decision_index": decision_index}
        self.stage = f"DECISION_{decision_index}_CAPTURE"

    def record(self, name: str, value: Any) -> None:
        dumped = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        if self.active_cycle is not None and name in {
            "capture_request",
            "capture_response",
            "inference_request",
            "inference_response",
            "execute_request",
            "execute_response",
            "post_execution_attribution",
        }:
            self.active_cycle[name] = dumped
        else:
            setattr(self, name, dumped)
        self.stage = name.upper()

    def commit_cycle(self) -> None:
        if self.active_cycle is None:
            raise RuntimeError("host audit has no active decision cycle")
        self.wire_cycles.append(self.active_cycle)
        self.active_cycle = None

    def failure_payload(self, error: Exception) -> dict[str, Any]:
        completed = list(self.wire_cycles)
        if self.active_cycle is not None:
            completed.append({**self.active_cycle, "cycle_complete": False})
        return {
            "schema_version": "M2CFormalSplitRunnerPartialFailureAuditV2",
            "status": "ABORTED_PARTIAL_RUN_NOT_ENTRY_EVIDENCE",
            "run_id": self.run_id,
            "matched_key": self.matched_key,
            "scene_seed": self.scene_seed,
            "failure_seed": self.failure_seed,
            "aborted_stage": self.stage,
            "error_type": type(error).__name__,
            "error": str(error),
            "bundle": self.bundle,
            "isaac_endpoint_binding": self.isaac_endpoint_binding,
            "start_request": self.start_request,
            "start_response": self.start_response,
            "wire_cycles": completed,
            "finalize_request": self.finalize_request,
            "finalize_response": self.finalize_response,
            "accepted_physical_receipt_count": self.accepted_physical_receipt_count,
            "last_physical_receipt_sha256": self.last_physical_receipt_sha256,
            "formal_output_written": False,
            "final_task_success_evaluated": self.finalize_response is not None,
            "strict_pure_model_success": False,
            "entry_evidence_eligible": False,
            "continue_fixed_chain_after_error": False,
            "synthetic": False,
            "mocked_physics": False,
            "scripted_decision_source": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C formal split model-owned chain runner")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--matched-key", required=True)
    parser.add_argument("--scene-seed", type=int, required=True)
    parser.add_argument("--failure-seed", type=int, required=True)
    parser.add_argument("--sdf", type=Path, required=True)
    parser.add_argument("--supervision", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--model-id", default=QWEN_MODEL_ID, choices=(QWEN_MODEL_ID,))
    parser.add_argument("--revision", default=QWEN_MODEL_REVISION, choices=(QWEN_MODEL_REVISION,))
    parser.add_argument("--qwen-runtime-binding", type=Path, required=True)
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--qwen-endpoint", required=True)
    parser.add_argument("--qwen-hmac-key-file", type=Path, required=True)
    parser.add_argument("--isaac-endpoint-binding", type=Path, required=True)
    parser.add_argument("--isaac-hmac-key-file", type=Path, required=True)
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract-check-only", action="store_true")
    return parser.parse_args(argv)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def validate_configuration(
    args: argparse.Namespace,
) -> tuple[
    QwenBundleRuntimeBindingV2,
    IsaacEndpointBindingV2,
]:
    if args.model_id != QWEN_MODEL_ID or args.revision != QWEN_MODEL_REVISION:
        raise ValueError("formal runner requires canonical Qwen model ID/revision")
    if not args.local_files_only:
        raise ValueError("formal runner requires --local-files-only")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite formal evidence: {args.output}")
    failure_output = partial_failure_output_path(args.output)
    if failure_output.exists():
        raise FileExistsError(f"refusing to overwrite partial failure audit: {failure_output}")
    for path in (
        args.sdf,
        args.supervision,
        args.registry,
        args.bundle_root / BUNDLE_MANIFEST_NAME,
        args.qwen_runtime_binding,
        args.isaac_endpoint_binding,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    if not 0.0 < args.request_timeout_seconds <= 300.0:
        raise ValueError("formal request timeout must be in (0, 300] seconds")
    heads, metadata, manifest = load_bundle(
        args.bundle_root,
        require_adapter=True,
        expected_model_id=args.model_id,
        expected_model_revision=args.revision,
    )
    if metadata.architecture_revision != QWEN_ARCHITECTURE_REVISION:
        raise ValueError("formal runner bundle is not M2C_Q012_V2")
    if manifest.status != "TRAINED_QWEN_LORA_THREE_HEADS":
        raise ValueError("formal runner refuses offline-smoke bundle")
    bundle = QwenBundleRuntimeBindingV2.model_validate(_read_json(args.qwen_runtime_binding))
    local_bundle_fields = {
        "bundle_manifest_sha256": sha256_file(args.bundle_root / BUNDLE_MANIFEST_NAME),
        "head_checkpoint_sha256": manifest.head_checkpoint_sha256,
        "adapter_tree_sha256": manifest.adapter_tree_sha256,
        "failure_context": metadata.failure_context,
    }
    for name, expected in local_bundle_fields.items():
        if getattr(bundle, name) != expected:
            raise ValueError(f"node2 runtime binding differs from local trained bundle: {name}")
    # This recomputation deliberately forces all six exact tensors to load and validate.
    qwen_head_tensor_sha256(heads)
    endpoint = IsaacEndpointBindingV2.model_validate(_read_json(args.isaac_endpoint_binding))
    endpoint_sha = canonical_sha256(endpoint)
    if endpoint_sha == "0" * 64:  # impossible guard keeps the binding visibly consumed
        raise ValueError("invalid Isaac endpoint binding")
    if args.qwen_endpoint.rstrip("/") == endpoint.endpoint_base_url.rstrip("/"):
        raise ValueError("Qwen and Isaac endpoints may not be the same service")
    # Keys are opened before network or evidence mutation.  Missing/permissive keys fail closed.
    read_hmac_secret(args.qwen_hmac_key_file)
    read_hmac_secret(args.isaac_hmac_key_file)
    return bundle, endpoint


def _post_json(url: str, payload: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured private URL
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f"formal endpoint returned HTTP {response.status}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("formal endpoint request failed closed") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("formal endpoint response is not a JSON object")
    return parsed


def _endpoint(base: str, path: str) -> str:
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def run_real(
    args: argparse.Namespace,
    *,
    bundle: QwenBundleRuntimeBindingV2,
    endpoint: IsaacEndpointBindingV2,
    audit: HostPartialRunAuditV2 | None = None,
) -> dict[str, Any]:
    audit = audit or HostPartialRunAuditV2(
        run_id=args.run_id,
        matched_key=args.matched_key,
        scene_seed=args.scene_seed,
        failure_seed=args.failure_seed,
        bundle=bundle.model_dump(mode="json"),
        isaac_endpoint_binding=endpoint.model_dump(mode="json"),
    )
    qwen_secret = read_hmac_secret(args.qwen_hmac_key_file)
    isaac_secret = read_hmac_secret(args.isaac_hmac_key_file)
    endpoint_sha = canonical_sha256(endpoint)
    registry = load_registry_v2(args.registry)
    registry_sha = sha256_file(args.registry)

    start_request = IsaacStartRequestV2(
        run_id=args.run_id,
        matched_key=args.matched_key,
        scene_seed=args.scene_seed,
        failure_seed=args.failure_seed,
        sdf_sha256=sha256_file(args.sdf),
        supervision_sha256=sha256_file(args.supervision),
        runtime_registry_sha256=registry_sha,
        endpoint_binding_sha256=endpoint_sha,
        bundle=bundle,
    )
    signed_start_request = sign_wire_message(
        "ISAAC_START_REQUEST",
        start_request,
        isaac_secret,
    )
    audit.record("start_request", signed_start_request)
    signed_start, start = verify_wire_message(
        _post_json(
            _endpoint(endpoint.endpoint_base_url, FORMAL_ISAAC_START_PATH),
            signed_start_request.model_dump(mode="json"),
            timeout=args.request_timeout_seconds,
        ),
        expected_type="ISAAC_START_RESPONSE",
        payload_model=IsaacStartResponseV2,
        secret=isaac_secret,
    )
    audit.record("start_response", signed_start)
    if (
        start.run_id != args.run_id
        or start.start_request_sha256 != canonical_sha256(start_request)
        or start.endpoint_binding_sha256 != endpoint_sha
        or start.implementation_sha256 != endpoint.implementation_sha256
        or start.physical_backend_sha256 != endpoint.physical_backend_sha256
    ):
        raise ValueError("Isaac start response differs from frozen deployment binding")

    decisions: list[ModelOwnedChainDecisionV2] = []
    history: list[PublicExecutedIntentHistoryItemV2] = []
    wire_log: list[dict[str, Any]] = []
    previous_receipt_sha: str | None = None
    previous_completed_at_ns = start.failure_observed_at_ns
    for decision_index in range(8):
        audit.begin_cycle(decision_index)
        capture_request = IsaacCaptureRequestV2(
            run_id=args.run_id,
            session_id=start.session_id,
            decision_index=decision_index,
            previous_physical_receipt_sha256=previous_receipt_sha,
        )
        signed_capture_request = sign_wire_message(
            "ISAAC_CAPTURE_REQUEST", capture_request, isaac_secret
        )
        audit.record("capture_request", signed_capture_request)
        signed_capture, capture = verify_wire_message(
            _post_json(
                _endpoint(endpoint.endpoint_base_url, FORMAL_ISAAC_CAPTURE_PATH),
                signed_capture_request.model_dump(mode="json"),
                timeout=args.request_timeout_seconds,
            ),
            expected_type="ISAAC_CAPTURE_RESPONSE",
            payload_model=IsaacCaptureResponseV2,
            secret=isaac_secret,
        )
        audit.record("capture_response", signed_capture)
        if (
            capture.run_id != args.run_id
            or capture.session_id != start.session_id
            or capture.decision_index != decision_index
            or capture.observation.previous_physical_completed_at_ns != previous_completed_at_ns
            or capture.public_roles.selector_contract_sha256 != endpoint.public_role_selector_sha256
        ):
            raise ValueError("Isaac capture response is not the next fresh decision cycle")

        sent_at_ns = time.time_ns()
        if sent_at_ns <= capture.observation.captured_at_ns:
            sent_at_ns = capture.observation.captured_at_ns + 1
        inference_request = FormalInferenceRequestV2(
            run_id=args.run_id,
            request_id=f"{args.run_id}-decision-{decision_index}",
            decision_index=decision_index,
            sent_at_ns=sent_at_ns,
            executed_intent_history=history,
            prior_decisions_sha256=canonical_sha256(history),
            bundle=bundle,
            observation=capture.observation,
        )
        signed_inference_request = sign_inference_request(inference_request, qwen_secret)
        audit.record("inference_request", signed_inference_request)
        inference = verify_inference_response(
            _post_json(
                _endpoint(args.qwen_endpoint, FORMAL_INFERENCE_PATH),
                signed_inference_request.model_dump(mode="json"),
                timeout=args.request_timeout_seconds,
            ),
            qwen_secret,
        )
        audit.record("inference_response", inference)
        if (
            inference.payload.run_id != args.run_id
            or inference.payload.request_id != inference_request.request_id
            or inference.payload.decision_index != decision_index
            or inference.payload.request_payload_sha256 != signed_inference_request.payload_sha256
        ):
            raise ValueError("Qwen response is not bound to the current public capture")
        runtime_request = runtime_request_from_inference(
            inference_request,
            inference.payload,
            registry,
        )
        execute_request = IsaacExecuteRequestV2(
            run_id=args.run_id,
            session_id=start.session_id,
            decision_index=decision_index,
            observation_id=capture.observation.observation_id,
            capture_receipt_sha256=capture.observation.capture_receipt_sha256,
            inference_response_sha256=inference.payload_sha256,
            executed_intent_history_sha256=inference_request.prior_decisions_sha256,
            runtime_request=runtime_request,
        )
        signed_execute_request = sign_wire_message(
            "ISAAC_EXECUTE_REQUEST", execute_request, isaac_secret
        )
        audit.record("execute_request", signed_execute_request)
        signed_execute, execute = verify_wire_message(
            _post_json(
                _endpoint(endpoint.endpoint_base_url, FORMAL_ISAAC_EXECUTE_PATH),
                signed_execute_request.model_dump(mode="json"),
                timeout=args.request_timeout_seconds,
            ),
            expected_type="ISAAC_EXECUTE_RESPONSE",
            payload_model=IsaacExecuteResponseV2,
            secret=isaac_secret,
        )
        audit.record("execute_response", signed_execute)
        decision = journal_decision_from_wire(inference, capture, execute)
        decisions.append(decision)
        receipt = execute.physical_skill_receipts[0]
        previous_receipt_sha = receipt.receipt_sha256
        previous_completed_at_ns = receipt.completed_at_ns
        audit.accepted_physical_receipt_count += 1
        audit.last_physical_receipt_sha256 = previous_receipt_sha
        wire_log.append(
            {
                "decision_index": decision_index,
                "capture_request": signed_capture_request.model_dump(mode="json"),
                "capture_response": signed_capture.model_dump(mode="json"),
                "inference_request": signed_inference_request.model_dump(mode="json"),
                "inference_response": inference.model_dump(mode="json"),
                "execute_request": signed_execute_request.model_dump(mode="json"),
                "execute_response": signed_execute.model_dump(mode="json"),
            }
        )
        try:
            history = append_public_executed_intent_history(
                history,
                inference,
                execute,
            )
        except ValueError as exc:
            audit.record(
                "post_execution_attribution",
                {
                    "status": "INVALID_OR_FALLBACK_ABORT_AFTER_EXECUTION",
                    "error": str(exc),
                    "execution_source": receipt.execution_source,
                    "mapping_status": execute.mapping.status,
                    "continued": False,
                },
            )
            raise
        # This check is strictly post-execution attribution.  A wrong model
        # action remains the one physical action for this cycle; the host never
        # substitutes the preregistered next skill or fixed continuation.
        try:
            validate_expected_chain_is_not_runner_selected(inference.payload)
        except ValueError as exc:
            audit.record(
                "post_execution_attribution",
                {
                    "status": "WRONG_MODEL_SELECTED_SKILL_ABORT_AFTER_EXECUTION",
                    "error": str(exc),
                    "continued": False,
                },
            )
            raise
        audit.record(
            "post_execution_attribution",
            {"status": "EXPECTED_CHAIN_STEP", "continued": decision_index < 7},
        )
        audit.commit_cycle()

    if previous_receipt_sha is None:
        raise RuntimeError("formal chain executed no physical skill")
    finalize_request = IsaacFinalizeRequestV2(
        run_id=args.run_id,
        session_id=start.session_id,
        last_physical_receipt_sha256=previous_receipt_sha,
    )
    signed_finalize_request = sign_wire_message(
        "ISAAC_FINALIZE_REQUEST", finalize_request, isaac_secret
    )
    audit.record("finalize_request", signed_finalize_request)
    signed_finalize, finalize = verify_wire_message(
        _post_json(
            _endpoint(endpoint.endpoint_base_url, FORMAL_ISAAC_FINALIZE_PATH),
            signed_finalize_request.model_dump(mode="json"),
            timeout=args.request_timeout_seconds,
        ),
        expected_type="ISAAC_FINALIZE_RESPONSE",
        payload_model=IsaacFinalizeResponseV2,
        secret=isaac_secret,
    )
    audit.record("finalize_response", signed_finalize)
    if finalize.run_id != args.run_id or finalize.session_id != start.session_id:
        raise ValueError("Isaac final outcome is not bound to this physical session")
    episode = build_episode_from_external_evidence(
        run_id=args.run_id,
        failure_observed_at_ns=start.failure_observed_at_ns,
        final_task_success=finalize.final_task_success,
        decisions=decisions,
    )
    validation = validate_model_owned_chain_episode(episode)
    return {
        "schema_version": "M2CFormalSplitRunnerEvidenceV2",
        "status": "COMPLETE_REAL_PHYSICAL_EPISODE",
        "run_id": args.run_id,
        "bundle": bundle.model_dump(mode="json"),
        "isaac_endpoint_binding": endpoint.model_dump(mode="json"),
        "start_response": start.model_dump(mode="json"),
        "wire_cycles": wire_log,
        "finalize_request": signed_finalize_request.model_dump(mode="json"),
        "finalize_response": signed_finalize.model_dump(mode="json"),
        "episode": episode.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "synthetic": False,
        "mocked_physics": False,
        "scripted_decision_source": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def publish_create_only(output: Path, payload: Mapping[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite formal evidence: {output}")
    with tempfile.NamedTemporaryFile(
        mode="x",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.incomplete-",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # ``link`` is atomic and fails if a concurrent publisher won the path.
        os.link(temporary, output)
        temporary.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundle, endpoint = validate_configuration(args)
    if args.contract_check_only:
        print(
            json.dumps(
                {
                    "status": "CONTRACT_ONLY_NO_ENDPOINT_CONTACT_NO_PHYSICAL_RECEIPT",
                    "bundle": bundle.model_dump(mode="json"),
                    "isaac_endpoint_binding": endpoint.model_dump(mode="json"),
                    "output_written": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    audit = HostPartialRunAuditV2(
        run_id=args.run_id,
        matched_key=args.matched_key,
        scene_seed=args.scene_seed,
        failure_seed=args.failure_seed,
        bundle=bundle.model_dump(mode="json"),
        isaac_endpoint_binding=endpoint.model_dump(mode="json"),
    )
    try:
        payload = run_real(
            args,
            bundle=bundle,
            endpoint=endpoint,
            audit=audit,
        )
    except Exception as exc:
        failure_output = partial_failure_output_path(args.output)
        try:
            publish_create_only(failure_output, audit.failure_payload(exc))
        except Exception as publish_error:
            raise RuntimeError(
                "formal run aborted and create-only partial audit publication failed; "
                f"original={type(exc).__name__}: {exc}; "
                f"audit={type(publish_error).__name__}: {publish_error}"
            ) from publish_error
        raise
    publish_create_only(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
