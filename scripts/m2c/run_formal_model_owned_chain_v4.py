#!/usr/bin/env python3
"""Run one preregistered ADR-0024 V4 model-owned Q-B episode.

This host only orders authenticated endpoint calls.  It never selects a
recovery skill, synthesizes an exact plan, or executes physics.  A terminal
no-action/execution failure is published as a complete false episode; an
unexpected transport or contract failure is published only as a create-only
partial-failure sidecar that is ineligible for formal entry evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from m2c.qwen_coarse_v4 import (
    BUNDLE_MANIFEST_NAME,
    LoadedM2CQwenCoarseV4Bundle,
    load_bundle_v4,
    sha256_tree_v4,
)
from m2c.qwen_decision_level_v4 import (
    DECISION_BUNDLE_MANIFEST_NAME,
    LoadedADR0026DecisionBundleV4,
    load_adr0026_decision_bundle_v4,
)
from xh_agent.policy.qrm_lite.formal_split_host_v4 import (
    FormalV4RunInputs,
    M2CFormalSplitRunnerEvidenceV4,
    run_formal_v4_episode,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    QWEN_MODEL_ID,
    QWEN_MODEL_REVISION,
    read_hmac_secret,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    ADR0026_DECISION_BUNDLE_CONTRACT_V4,
    BUNDLE_CONTRACT_CHOICES_V4,
    EPISODE_ATOMIC_BUNDLE_CONTRACT_V4,
    FORMAL_INFERENCE_PATH_V4,
    IsaacEndpointBindingV4,
    QwenBundleRuntimeBindingV4,
    QwenSourceTrainingManifestBindingV4,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT,
    consume_wire_challenge_create_only,
    load_consumed_wire_challenge_from_canonical_ledger,
    read_regular_file_once,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PublicDeclaredTargetAttributeBindingV4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    RuntimeSkillRegistryV2,
    load_registry_v2,
)


WIRE_CHALLENGE_MANIFEST_SCHEMA = "M2CS4WireChallengeManifestV1"
FormalLoadedQwenBundleV4 = LoadedM2CQwenCoarseV4Bundle | LoadedADR0026DecisionBundleV4


def partial_failure_output_path(formal_output: Path) -> Path:
    return formal_output.with_name(formal_output.name + ".partial-failure.json")


@dataclass
class HostPartialRunAuditV4:
    """Progress journal used only when the formal V4 host aborts unexpectedly."""

    inputs: dict[str, Any]
    stage: str = "CONFIGURATION_VALIDATED"
    wire_events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, stage: str, payload: Mapping[str, Any]) -> None:
        self.stage = stage
        self.wire_events.append({"stage": stage, "signed_wire": dict(payload)})

    def failure_payload(self, error: Exception) -> dict[str, Any]:
        return {
            "schema_version": "M2CFormalSplitRunnerPartialFailureAuditV4",
            "status": "ABORTED_PARTIAL_RUN_NOT_ENTRY_EVIDENCE",
            "aborted_stage": self.stage,
            "error_type": type(error).__name__,
            "error": str(error),
            "inputs": self.inputs,
            "wire_events": self.wire_events,
            "formal_output_written": False,
            "entry_evidence_eligible": False,
            "final_task_success": False,
            "strict_pure_model_success": False,
            "continue_or_retry_after_error": False,
            "synthetic": False,
            "mocked_physics": False,
            "scripted_decision_source": False,
            "b0_runtime_fallback_present": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }


@dataclass(frozen=True)
class ValidatedConfigurationV4:
    bundle: QwenBundleRuntimeBindingV4
    endpoint: IsaacEndpointBindingV4
    attribute_binding: PublicDeclaredTargetAttributeBindingV4
    registry: RuntimeSkillRegistryV2
    registry_sha256: str


class HttpFormalV4Transport:
    def __init__(
        self,
        *,
        qwen_endpoint: str,
        isaac_endpoint: str,
        timeout_seconds: float,
    ) -> None:
        if timeout_seconds <= 0.0:
            raise ValueError("formal V4 request timeout must be positive")
        self.qwen_endpoint = qwen_endpoint.rstrip("/")
        self.isaac_endpoint = isaac_endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def post_qwen(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if path != FORMAL_INFERENCE_PATH_V4:
            raise ValueError("formal V4 host attempted an unknown Qwen path")
        return _post_json(
            _endpoint(self.qwen_endpoint, path),
            payload,
            timeout=self.timeout_seconds,
        )

    def post_isaac(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return _post_json(
            _endpoint(self.isaac_endpoint, path),
            payload,
            timeout=self.timeout_seconds,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C formal V4 model-owned chain runner")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--challenge-nonce", required=True)
    parser.add_argument("--wire-challenge-manifest", type=Path, required=True)
    parser.add_argument(
        "--challenge-consumption-ledger",
        type=Path,
        default=Path(CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT),
    )
    parser.add_argument("--matched-key", required=True)
    parser.add_argument("--scene-seed", type=int, required=True)
    parser.add_argument("--failure-seed", type=int, required=True)
    parser.add_argument("--sdf", type=Path, required=True)
    parser.add_argument("--supervision", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument(
        "--bundle-contract",
        choices=BUNDLE_CONTRACT_CHOICES_V4,
        default=EPISODE_ATOMIC_BUNDLE_CONTRACT_V4,
    )
    parser.add_argument("--model-id", default=QWEN_MODEL_ID, choices=(QWEN_MODEL_ID,))
    parser.add_argument("--revision", default=QWEN_MODEL_REVISION, choices=(QWEN_MODEL_REVISION,))
    parser.add_argument("--qwen-runtime-binding", type=Path, required=True)
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--qwen-endpoint", required=True)
    parser.add_argument("--qwen-hmac-key-file", type=Path, required=True)
    parser.add_argument("--isaac-endpoint-binding", type=Path, required=True)
    parser.add_argument("--isaac-hmac-key-file", type=Path, required=True)
    parser.add_argument("--declared-target-attribute", required=True)
    parser.add_argument("--declared-attribute-binding", type=Path, required=True)
    parser.add_argument("--request-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract-check-only", action="store_true")
    return parser.parse_args(argv)


def _sha256_regular(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(read_regular_file_once(path))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _registry_path_matches(actual: Path, expected_repo_path: str) -> bool:
    expected = Path(expected_repo_path)
    if expected.is_absolute() or ".." in expected.parts or not expected.parts:
        return False
    actual_parts = actual.resolve().parts
    expected_parts = expected.parts
    return len(actual_parts) >= len(expected_parts) and (
        actual_parts[-len(expected_parts) :] == expected_parts
    )


def _require_unused_outputs(output: Path) -> None:
    for candidate in (output, partial_failure_output_path(output)):
        if candidate.exists() or candidate.is_symlink():
            raise FileExistsError(f"refusing to overwrite formal V4 evidence: {candidate}")


def _validate_challenge(args: argparse.Namespace) -> None:
    manifest = _json_object(args.wire_challenge_manifest)
    if (
        manifest.get("schema_version") != WIRE_CHALLENGE_MANIFEST_SCHEMA
        or manifest.get("formal_q_b_evaluation_authorized") is not False
        or manifest.get("teacher_used") is not False
        or manifest.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("formal V4 wire challenge manifest governance differs")
    matches = [
        item
        for item in manifest.get("challenge_records", [])
        if isinstance(item, dict)
        and item.get("run_id") == args.run_id
        and item.get("challenge_nonce") == args.challenge_nonce
        and item.get("matched_key") == args.matched_key
        and item.get("scene_seed") == args.scene_seed
        and item.get("failure_seed") == args.failure_seed
    ]
    if len(matches) != 1:
        raise ValueError("formal V4 runner does not bind exactly one challenge record")


def _validate_loaded_bundle(
    *,
    args: argparse.Namespace,
    loaded: FormalLoadedQwenBundleV4,
    binding: QwenBundleRuntimeBindingV4,
) -> None:
    manifest = loaded.manifest
    decision_contract = args.bundle_contract == ADR0026_DECISION_BUNDLE_CONTRACT_V4
    if decision_contract != (manifest.schema_version == "M2CQwenADR0026DecisionBundleManifestV1"):
        raise ValueError("formal V4 runner bundle schema differs from explicit contract")
    if decision_contract:
        manifest_path = args.bundle_root / DECISION_BUNDLE_MANIFEST_NAME
        training_manifest_file_sha256 = manifest.training_dataset_manifest_file_sha256
        training_manifest_sha256 = manifest.training_dataset_manifest_sha256
        training_dataset_report_file_sha256 = manifest.training_dataset_report_file_sha256
        training_dataset_report_sha256 = manifest.training_dataset_report_sha256
        source_training_manifests = tuple(
            QwenSourceTrainingManifestBindingV4.model_validate(item.model_dump(mode="json"))
            for item in manifest.source_training_manifests
        )
        expected_status = "TRAINED_QWEN_LORA_M2C_Q012_V4_ADR0026_DECISION_LEVEL"
    else:
        manifest_path = args.bundle_root / BUNDLE_MANIFEST_NAME
        training_manifest_file_sha256 = manifest.training_manifest_file_sha256
        training_manifest_sha256 = manifest.training_manifest_sha256
        training_dataset_report_file_sha256 = None
        training_dataset_report_sha256 = None
        source_training_manifests = ()
        expected_status = "TRAINED_QWEN_LORA_M2C_Q012_V4"
    expected = {
        "bundle_manifest_schema_version": manifest.schema_version,
        "training_contract_revision": args.bundle_contract,
        "bundle_manifest_file_sha256": _sha256_regular(manifest_path),
        "bundle_tree_sha256": sha256_tree_v4(args.bundle_root),
        "bundle_sha256": manifest.bundle_sha256,
        "head_checkpoint_sha256": manifest.head_checkpoint_sha256,
        "head_deployment_file_sha256": manifest.head_deployment_file_sha256,
        "head_deployment_manifest_sha256": (manifest.head_deployment.deployment_manifest_sha256),
        "checkpoint_binding_sha256": manifest.head_deployment.checkpoint_binding_sha256,
        "adapter_tree_sha256": manifest.adapter_tree_sha256,
        "training_dataset_sha256": manifest.training_dataset_sha256,
        "training_manifest_file_sha256": training_manifest_file_sha256,
        "training_manifest_sha256": training_manifest_sha256,
        "training_dataset_report_file_sha256": training_dataset_report_file_sha256,
        "training_dataset_report_sha256": training_dataset_report_sha256,
        "source_training_manifests": source_training_manifests,
        "s6_manifest_file_sha256": manifest.s6_manifest_file_sha256,
        "s6_manifest_sha256": manifest.s6_manifest_sha256,
        "failure_context": manifest.failure_context,
    }
    mismatches = sorted(
        name
        for name, expected_value in expected.items()
        if getattr(binding, name) != expected_value
    )
    if mismatches:
        raise ValueError(f"formal V4 runtime binding differs from trained bundle: {mismatches}")
    if (
        manifest.status != expected_status
        or manifest.model_id != args.model_id
        or manifest.model_revision != args.revision
        or manifest.bundle_sha256 != args.expected_bundle_sha256
    ):
        raise ValueError("formal V4 runner refuses a noncanonical or nontrained bundle")


def validate_configuration(args: argparse.Namespace) -> ValidatedConfigurationV4:
    if args.model_id != QWEN_MODEL_ID or args.revision != QWEN_MODEL_REVISION:
        raise ValueError("formal V4 runner requires the canonical Qwen revision")
    if not args.local_files_only:
        raise ValueError("formal V4 runner requires local-files-only inference")
    if not 0.0 < args.request_timeout_seconds <= 300.0:
        raise ValueError("formal V4 request timeout must be in (0, 300] seconds")
    _validate_challenge(args)
    if args.bundle_contract == ADR0026_DECISION_BUNDLE_CONTRACT_V4:
        loaded = load_adr0026_decision_bundle_v4(
            args.bundle_root,
            expected_bundle_sha256=args.expected_bundle_sha256,
        )
    else:
        loaded = load_bundle_v4(
            args.bundle_root,
            expected_bundle_sha256=args.expected_bundle_sha256,
        )
    bundle = QwenBundleRuntimeBindingV4.model_validate(_json_object(args.qwen_runtime_binding))
    _validate_loaded_bundle(args=args, loaded=loaded, binding=bundle)
    endpoint = IsaacEndpointBindingV4.model_validate(_json_object(args.isaac_endpoint_binding))
    attribute_binding = PublicDeclaredTargetAttributeBindingV4.model_validate(
        _json_object(args.declared_attribute_binding)
    )
    if (
        attribute_binding.declared_target_attribute != args.declared_target_attribute
        or attribute_binding.selector_source_implementation_sha256
        != bundle.declared_attribute_selector_implementation_sha256
        or attribute_binding.selector_source_implementation_sha256
        != endpoint.declared_attribute_selector_implementation_sha256
    ):
        raise ValueError("formal V4 declared attribute differs from public deployments")
    registry_sha256 = _sha256_regular(args.registry)
    registry = load_registry_v2(args.registry)
    if registry_sha256 != endpoint.runtime_registry_sha256:
        raise ValueError("formal V4 registry differs from Isaac deployment")
    if not _registry_path_matches(args.registry, endpoint.runtime_registry_path):
        raise ValueError("formal V4 registry path differs from Isaac deployment")
    if args.qwen_endpoint.rstrip("/") == endpoint.endpoint_base_url.rstrip("/"):
        raise ValueError("formal V4 Qwen and Isaac endpoints must be separate services")
    _sha256_regular(args.sdf)
    _sha256_regular(args.supervision)
    return ValidatedConfigurationV4(
        bundle=bundle,
        endpoint=endpoint,
        attribute_binding=attribute_binding,
        registry=registry,
        registry_sha256=registry_sha256,
    )


def _post_json(url: str, payload: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - private bound URL
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f"formal V4 endpoint returned HTTP {response.status}")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("formal V4 endpoint request failed closed") from exc
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("formal V4 endpoint response is not a JSON object")
    return parsed


def _endpoint(base: str, path: str) -> str:
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def _inputs_from_canonical_ledger(
    args: argparse.Namespace,
    configuration: ValidatedConfigurationV4,
) -> FormalV4RunInputs:
    consumption_path, consumption, receipt_sha256 = (
        load_consumed_wire_challenge_from_canonical_ledger(
            ledger_directory=args.challenge_consumption_ledger,
            challenge_nonce=args.challenge_nonce,
            run_id=args.run_id,
            matched_key=args.matched_key,
            scene_seed=args.scene_seed,
            failure_seed=args.failure_seed,
        )
    )
    return FormalV4RunInputs(
        run_id=args.run_id,
        challenge_nonce=args.challenge_nonce,
        challenge_consumption_receipt_path=str(consumption_path),
        challenge_consumption_receipt_sha256=receipt_sha256,
        challenge_consumption_id=consumption.consumption_id,
        matched_key=args.matched_key,
        scene_seed=args.scene_seed,
        failure_seed=args.failure_seed,
        sdf_sha256=_sha256_regular(args.sdf),
        supervision_sha256=_sha256_regular(args.supervision),
        declared_target_attribute=args.declared_target_attribute,
        declared_attribute_binding_sha256=(configuration.attribute_binding.binding_sha256),
        bundle=configuration.bundle,
        isaac_endpoint_binding=configuration.endpoint,
    )


def run_real(
    args: argparse.Namespace,
    *,
    configuration: ValidatedConfigurationV4,
    audit: HostPartialRunAuditV4 | None = None,
) -> M2CFormalSplitRunnerEvidenceV4:
    # Reload the canonical, immutable receipt before reading either HMAC key
    # or contacting either service.  Callers cannot inject an in-memory claim.
    inputs = _inputs_from_canonical_ledger(args, configuration)
    audit = audit or HostPartialRunAuditV4(inputs=inputs.model_dump(mode="json"))
    qwen_secret = read_hmac_secret(args.qwen_hmac_key_file)
    isaac_secret = read_hmac_secret(args.isaac_hmac_key_file)
    transport = HttpFormalV4Transport(
        qwen_endpoint=args.qwen_endpoint,
        isaac_endpoint=configuration.endpoint.endpoint_base_url,
        timeout_seconds=args.request_timeout_seconds,
    )
    return run_formal_v4_episode(
        inputs=inputs,
        registry=configuration.registry,
        qwen_secret=qwen_secret,
        isaac_secret=isaac_secret,
        transport=transport,
        event_sink=audit.record,
    )


def publish_create_only(output: Path, payload: Mapping[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite formal V4 evidence: {output}")
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
        os.link(temporary, output)
        temporary.unlink()
        directory_fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.contract_check_only:
        require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
    configuration = validate_configuration(args)
    if args.contract_check_only:
        print(
            json.dumps(
                {
                    "status": "CONTRACT_ONLY_NO_ENDPOINT_CONTACT_NO_PHYSICAL_RECEIPT",
                    "bundle": configuration.bundle.model_dump(mode="json"),
                    "isaac_endpoint_binding": configuration.endpoint.model_dump(mode="json"),
                    "declared_attribute_binding_sha256": (
                        configuration.attribute_binding.binding_sha256
                    ),
                    "output_written": False,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    # Reject before consuming the one-shot challenge or contacting either endpoint.
    _require_unused_outputs(args.output)
    consume_wire_challenge_create_only(
        ledger_directory=args.challenge_consumption_ledger,
        challenge_manifest_path=args.wire_challenge_manifest,
        run_id=args.run_id,
        challenge_nonce=args.challenge_nonce,
        matched_key=args.matched_key,
        scene_seed=args.scene_seed,
        failure_seed=args.failure_seed,
        consumed_at_ns=time.time_ns(),
    )
    inputs = _inputs_from_canonical_ledger(args, configuration)
    audit = HostPartialRunAuditV4(inputs=inputs.model_dump(mode="json"))
    try:
        evidence = run_real(args, configuration=configuration, audit=audit)
    except Exception as exc:
        failure_output = partial_failure_output_path(args.output)
        try:
            publish_create_only(failure_output, audit.failure_payload(exc))
        except Exception as publish_error:
            raise RuntimeError(
                "formal V4 run aborted and partial audit publication failed; "
                f"original={type(exc).__name__}: {exc}; "
                f"audit={type(publish_error).__name__}: {publish_error}"
            ) from publish_error
        raise
    publish_create_only(args.output, evidence.model_dump(mode="json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
