from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from m2c import run_formal_model_owned_chain_v4 as host_cli
from m2c.qwen_coarse_v4 import initialize_numpy_heads_v4, sha256_tree_v4
from m2c.qwen_decision_level_v4 import (
    DECISION_BUNDLE_MANIFEST_NAME,
    load_adr0026_decision_bundle_v4,
    write_adr0026_decision_bundle_v4,
)
from m2c.serve_qwen_coarse_v4 import _binding_from_verified_bundle_v4
from test_m2c_formal_isaac_endpoint_v4 import (
    SECRET as ISAAC_SECRET,
    _endpoint,
)
from test_m2c_formal_split_runner_v4 import (
    HASH,
    _bundle,
    _logits,
)
from test_m2c_qwen_decision_level_v4 import _dataset_report
from xh_agent.policy.qrm_lite.formal_split_host_v4 import (
    FormalV4RunInputs,
    M2CFormalSplitRunnerEvidenceV4,
    run_formal_v4_episode,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    ADR0026_DECISION_BUNDLE_CONTRACT_V4,
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_ISAAC_CAPTURE_PATH_V4,
    FORMAL_ISAAC_EXECUTE_PATH_V4,
    FORMAL_ISAAC_FINALIZE_PATH_V4,
    FORMAL_ISAAC_START_PATH_V4,
    IsaacFinalizeRequestV4,
    IsaacFinalizeResponseV4,
    build_inference_response_from_logits_v4,
    sign_inference_response_v4,
    verify_inference_request_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


ROOT = Path(__file__).resolve().parents[2]
QWEN_SECRET = b"formal-v4-host-qwen-test-key-at-least-32-bytes"


class _InMemoryTransport:
    def __init__(
        self,
        endpoint: Any,
        *,
        selected_skills: tuple[str, ...] = ("LIFT",) * 8,
        selected_pointers: tuple[int, ...] = (0,) * 8,
        tamper_qwen_hmac: bool = False,
        cross_qwen_request: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.selected_skills = selected_skills
        self.selected_pointers = selected_pointers
        self.tamper_qwen_hmac = tamper_qwen_hmac
        self.cross_qwen_request = cross_qwen_request
        self.qwen_paths: list[str] = []
        self.isaac_paths: list[str] = []

    def post_isaac(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.isaac_paths.append(path)
        return self.endpoint.handle(path, payload)

    def post_qwen(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.qwen_paths.append(path)
        assert path == FORMAL_INFERENCE_PATH_V4
        signed = verify_inference_request_v4(payload, QWEN_SECRET)
        request = signed.payload
        if self.cross_qwen_request:
            request = request.model_copy(update={"request_id": request.request_id + "-crossed"})
        skill = self.selected_skills[signed.payload.decision_index]
        pointer = self.selected_pointers[signed.payload.decision_index]
        skills, pointers, destinations = _logits(skill=skill, pointer=pointer)
        response = build_inference_response_from_logits_v4(
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
        dumped = sign_inference_response_v4(response, QWEN_SECRET).model_dump(mode="json")
        if self.tamper_qwen_hmac:
            dumped["hmac_sha256"] = "0" * 64
        return dumped


def _inputs(endpoint: Any) -> FormalV4RunInputs:
    observation = endpoint.backend.observations[0]
    return FormalV4RunInputs(
        run_id="formal-v4-host-contract-run",
        challenge_nonce="c" * 64,
        challenge_consumption_receipt_path=(
            "/var/lib/xh-agent/m2c-s4-wire-challenge-consumption-v1/consumed-contract.json"
        ),
        challenge_consumption_receipt_sha256="d" * 64,
        challenge_consumption_id="e" * 64,
        matched_key="formal-v4-host-contract-key",
        scene_seed=1,
        failure_seed=2,
        sdf_sha256="f" * 64,
        supervision_sha256="0" * 64,
        declared_target_attribute="yellow",
        declared_attribute_binding_sha256=(observation.declared_attribute_binding_sha256),
        bundle=_bundle(),
        isaac_endpoint_binding=endpoint.binding,
    )


def _configuration(endpoint: Any) -> host_cli.ValidatedConfigurationV4:
    observation = endpoint.backend.observations[0]
    return host_cli.ValidatedConfigurationV4(
        bundle=_bundle(),
        endpoint=endpoint.binding,
        attribute_binding=observation.declared_attribute_binding,
        registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        registry_sha256="8" * 64,
    )


def _cli_argv(tmp_path: Path, *, contract_check_only: bool = False) -> list[str]:
    values = [
        "--run-id",
        "formal-v4-host-contract-run",
        "--challenge-nonce",
        "c" * 64,
        "--wire-challenge-manifest",
        str(tmp_path / "challenge.json"),
        "--matched-key",
        "formal-v4-host-contract-key",
        "--scene-seed",
        "1",
        "--failure-seed",
        "2",
        "--sdf",
        str(tmp_path / "scene.sdf"),
        "--supervision",
        str(tmp_path / "supervision.json"),
        "--registry",
        str(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        "--bundle-root",
        str(tmp_path / "bundle"),
        "--expected-bundle-sha256",
        "2" * 64,
        "--qwen-runtime-binding",
        str(tmp_path / "qwen-binding.json"),
        "--local-files-only",
        "--qwen-endpoint",
        "http://node2:8766",
        "--qwen-hmac-key-file",
        str(tmp_path / "qwen.key"),
        "--isaac-endpoint-binding",
        str(tmp_path / "isaac-binding.json"),
        "--isaac-hmac-key-file",
        str(tmp_path / "isaac.key"),
        "--declared-target-attribute",
        "yellow",
        "--declared-attribute-binding",
        str(tmp_path / "attribute.json"),
        "--output",
        str(tmp_path / "formal.json"),
    ]
    if contract_check_only:
        values.append("--contract-check-only")
    return values


def _run(tmp_path: Path, **transport_kwargs: Any):  # noqa: ANN202
    endpoint, backend, _ = _endpoint(tmp_path)
    transport = _InMemoryTransport(endpoint, **transport_kwargs)
    evidence = run_formal_v4_episode(
        inputs=_inputs(endpoint),
        registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        qwen_secret=QWEN_SECRET,
        isaac_secret=ISAAC_SECRET,
        transport=transport,
    )
    return evidence, endpoint, backend, transport


def test_formal_v4_host_runs_exact_eight_model_cycles_and_finalizes(tmp_path: Path) -> None:
    evidence, endpoint, _, transport = _run(tmp_path)

    assert evidence.completion_kind == "FINALIZED"
    assert evidence.final_task_success is False
    assert evidence.model_decision_count == 8
    assert evidence.real_model_operation_count == 8
    assert evidence.robot_actuation_operation_count == 8
    assert evidence.strict_pure_model_success is False
    assert evidence.collision_or_safety_violation is False
    assert len(evidence.wire_cycles) == 8
    assert transport.qwen_paths == [FORMAL_INFERENCE_PATH_V4] * 8
    assert transport.isaac_paths == [
        FORMAL_ISAAC_START_PATH_V4,
        *(
            path
            for _ in range(8)
            for path in (FORMAL_ISAAC_CAPTURE_PATH_V4, FORMAL_ISAAC_EXECUTE_PATH_V4)
        ),
        FORMAL_ISAAC_FINALIZE_PATH_V4,
    ]
    assert endpoint.state.phase == "FINALIZED"
    assert (
        M2CFormalSplitRunnerEvidenceV4.model_validate_json(evidence.model_dump_json()) == evidence
    )


def test_formal_v4_host_derives_strict_pure_success_only_from_signed_finalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, backend, _ = _endpoint(tmp_path)

    def successful_finalize(request: IsaacFinalizeRequestV4) -> IsaacFinalizeResponseV4:
        return IsaacFinalizeResponseV4(
            run_id=request.run_id,
            session_id=request.session_id,
            evaluated_at_ns=backend.observations[-1].captured_at_ns + 30,
            final_task_success=True,
        )

    monkeypatch.setattr(backend, "finalize", successful_finalize)
    evidence = run_formal_v4_episode(
        inputs=_inputs(endpoint),
        registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
        qwen_secret=QWEN_SECRET,
        isaac_secret=ISAAC_SECRET,
        transport=_InMemoryTransport(endpoint),
    )

    assert evidence.final_task_success is True
    assert evidence.strict_pure_model_success is True
    assert evidence.real_model_operation_count == 8


def test_formal_v4_host_keeps_invalid_model_choice_as_terminal_false_without_retry(
    tmp_path: Path,
) -> None:
    evidence, endpoint, _, transport = _run(
        tmp_path,
        # LIFT with a model-selected NONE pointer is an invalid registry
        # request.  The host must forward it unchanged and stop on the Isaac
        # terminal-no-action response instead of substituting a target.
        selected_pointers=(8,) + (0,) * 7,
    )

    assert evidence.completion_kind == "TERMINAL_NO_PHYSICAL_EXECUTION"
    assert evidence.final_task_success is False
    assert evidence.model_decision_count == 1
    assert evidence.real_model_operation_count == 0
    assert evidence.robot_actuation_operation_count == 0
    assert evidence.finalize_request is None
    assert evidence.finalize_response is None
    assert evidence.strict_pure_model_success is False
    assert transport.qwen_paths == [FORMAL_INFERENCE_PATH_V4]
    assert transport.isaac_paths == [
        FORMAL_ISAAC_START_PATH_V4,
        FORMAL_ISAAC_CAPTURE_PATH_V4,
        FORMAL_ISAAC_EXECUTE_PATH_V4,
    ]
    assert endpoint.state.phase == "TERMINAL_FAILURE"


def test_formal_v4_host_rejects_hmac_tamper_and_crossed_qwen_response(tmp_path: Path) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "hmac")
    with pytest.raises(ValueError, match="HMAC mismatch"):
        run_formal_v4_episode(
            inputs=_inputs(endpoint),
            registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
            qwen_secret=QWEN_SECRET,
            isaac_secret=ISAAC_SECRET,
            transport=_InMemoryTransport(endpoint, tamper_qwen_hmac=True),
        )

    crossed_endpoint, _, _ = _endpoint(tmp_path / "crossed")
    with pytest.raises(ValueError, match="crosses request"):
        run_formal_v4_episode(
            inputs=_inputs(crossed_endpoint),
            registry=load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml"),
            qwen_secret=QWEN_SECRET,
            isaac_secret=ISAAC_SECRET,
            transport=_InMemoryTransport(crossed_endpoint, cross_qwen_request=True),
        )


def test_formal_v4_evidence_rejects_posthoc_wire_or_summary_tamper(tmp_path: Path) -> None:
    evidence, _, _, _ = _run(tmp_path)
    wire_tamper = evidence.model_dump(mode="json")
    wire_tamper["wire_cycles"][0]["inference_response"]["payload"]["request_id"] = "crossed"
    with pytest.raises((ValidationError, ValueError)):
        M2CFormalSplitRunnerEvidenceV4.model_validate(wire_tamper)

    summary_tamper = evidence.model_dump(mode="json")
    summary_tamper["strict_pure_model_success"] = True
    summary_tamper["evidence_sha256"] = "0" * 64
    with pytest.raises((ValidationError, ValueError)):
        M2CFormalSplitRunnerEvidenceV4.model_validate(summary_tamper)


def test_formal_v4_host_has_no_expected_skill_sequence_selector() -> None:
    import inspect

    from xh_agent.policy.qrm_lite import formal_split_host_v4

    source = inspect.getsource(formal_split_host_v4)
    assert "EXPECTED_CHAIN" not in source
    assert "expected_skill" not in source
    assert "B0_FALLBACK" not in source
    assert "validate_expected_chain" not in source
    assert "FormalInferenceRequestV4" in source


def test_formal_v4_cli_contract_check_contacts_nothing_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    configuration = _configuration(endpoint)
    monkeypatch.setattr(host_cli, "validate_configuration", lambda _args: configuration)
    monkeypatch.setattr(
        host_cli,
        "consume_wire_challenge_create_only",
        lambda **_kwargs: pytest.fail("contract check consumed a challenge"),
    )
    monkeypatch.setattr(
        host_cli,
        "run_real",
        lambda *_args, **_kwargs: pytest.fail("contract check contacted endpoints"),
    )

    assert host_cli.main(_cli_argv(tmp_path, contract_check_only=True)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "CONTRACT_ONLY_NO_ENDPOINT_CONTACT_NO_PHYSICAL_RECEIPT"
    assert output["output_written"] is False
    assert not (tmp_path / "formal.json").exists()


def test_formal_v4_cli_validates_adr0026_decision_bundle_contract(
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
        failure_context="off",
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
        bundle_root=bundle_root,
        bundle_contract=ADR0026_DECISION_BUNDLE_CONTRACT_V4,
        expected_bundle_sha256=manifest.bundle_sha256,
        model_id=manifest.model_id,
        revision=manifest.model_revision,
        cache_tree_sha256=cache_sha,
        association_deployment_sha256="1" * 64,
        capture_source_implementation_sha256="2" * 64,
        declared_attribute_selector_implementation_sha256="3" * 64,
    )
    binding = _binding_from_verified_bundle_v4(
        args,
        loaded=loaded,
        model_snapshot=model_snapshot,
        bundle_manifest_raw=(bundle_root / DECISION_BUNDLE_MANIFEST_NAME).read_bytes(),
        bundle_tree_sha256=sha256_tree_v4(bundle_root),
    )

    host_cli._validate_loaded_bundle(args=args, loaded=loaded, binding=binding)
    crossed = binding.model_copy(update={"training_dataset_report_sha256": "0" * 64})
    with pytest.raises(ValueError, match="runtime binding differs"):
        host_cli._validate_loaded_bundle(args=args, loaded=loaded, binding=crossed)


def test_formal_v4_cli_run_real_reloads_ledger_before_keys_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    configuration = _configuration(endpoint)
    inputs = _inputs(endpoint)
    args = host_cli.parse_args(_cli_argv(tmp_path))
    events: list[str] = []

    def ledger(*_args: Any, **_kwargs: Any) -> FormalV4RunInputs:
        events.append("ledger")
        return inputs

    def secret(_path: Path) -> bytes:
        events.append("secret")
        return QWEN_SECRET

    class Transport:
        def __init__(self, **_kwargs: Any) -> None:
            events.append("transport")

    sentinel = SimpleNamespace(status="evidence")
    monkeypatch.setattr(host_cli, "_inputs_from_canonical_ledger", ledger)
    monkeypatch.setattr(host_cli, "read_hmac_secret", secret)
    monkeypatch.setattr(host_cli, "HttpFormalV4Transport", Transport)
    monkeypatch.setattr(
        host_cli,
        "run_formal_v4_episode",
        lambda **_kwargs: events.append("episode") or sentinel,
    )

    assert host_cli.run_real(args, configuration=configuration) is sentinel
    assert events == ["ledger", "secret", "secret", "transport", "episode"]


def test_formal_v4_cli_refuses_existing_output_before_consuming_challenge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    configuration = _configuration(endpoint)
    output = tmp_path / "formal.json"
    output.write_text("existing\n", encoding="utf-8")
    monkeypatch.setattr(host_cli, "validate_configuration", lambda _args: configuration)
    monkeypatch.setattr(
        host_cli,
        "consume_wire_challenge_create_only",
        lambda **_kwargs: pytest.fail("existing output consumed the one-shot challenge"),
    )

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        host_cli.main(_cli_argv(tmp_path))


def test_formal_v4_registry_path_match_is_component_exact(tmp_path: Path) -> None:
    registry = tmp_path / "project" / "configs" / "qrm_runtime_mapping_v2.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("contract\n", encoding="utf-8")

    assert host_cli._registry_path_matches(
        registry,
        "configs/qrm_runtime_mapping_v2.yaml",
    )
    assert not host_cli._registry_path_matches(
        registry,
        "figs/qrm_runtime_mapping_v2.yaml",
    )
    assert not host_cli._registry_path_matches(registry, "../qrm_runtime_mapping_v2.yaml")


def test_formal_v4_cli_unexpected_failure_writes_only_ineligible_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    configuration = _configuration(endpoint)
    inputs = _inputs(endpoint)
    monkeypatch.setattr(host_cli, "validate_configuration", lambda _args: configuration)
    monkeypatch.setattr(host_cli, "consume_wire_challenge_create_only", lambda **_kwargs: None)
    monkeypatch.setattr(
        host_cli,
        "_inputs_from_canonical_ledger",
        lambda *_args, **_kwargs: inputs,
    )

    def fail(
        _args: Any,
        *,
        configuration: Any,
        audit: host_cli.HostPartialRunAuditV4,
    ) -> Any:
        del configuration
        audit.record("DECISION_0_CAPTURE_REQUEST", {"schema_version": "test-only"})
        raise RuntimeError("transport failed closed")

    monkeypatch.setattr(host_cli, "run_real", fail)
    with pytest.raises(RuntimeError, match="transport failed closed"):
        host_cli.main(_cli_argv(tmp_path))

    assert not (tmp_path / "formal.json").exists()
    sidecar = host_cli.partial_failure_output_path(tmp_path / "formal.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["status"] == "ABORTED_PARTIAL_RUN_NOT_ENTRY_EVIDENCE"
    assert payload["entry_evidence_eligible"] is False
    assert payload["continue_or_retry_after_error"] is False
    assert payload["formal_output_written"] is False


def test_formal_v4_cli_create_only_publication_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "evidence" / "formal.json"
    host_cli.publish_create_only(output, {"status": "first"})
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "first"}
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        host_cli.publish_create_only(output, {"status": "second"})
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "first"}
