"""Fail-closed ADR-0020 section 7 entry gate for formal Q-B evaluation.

The local layer proves deterministic contracts only.  The physical layer
accepts an external Isaac receipt only when its decisions are attributed to a
trained Qwen V2 world-model bundle (LoRA adapter plus the skill, pointer, and
destination heads).  A structured Q0/Q1/Q2 checkpoint is deliberately not a
physical-entry credential.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    EXPECTED_PATH_BLOCKED_CHAIN,
    ModelOwnedChainEpisodeV2,
    ModelOwnedChainValidationV2,
    validate_model_owned_chain_episode,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT,
    HOST_HMAC_VERIFIER_IMPLEMENTATION_PATH,
    HostWireHMACVerificationReceiptV2,
    WireChallengeConsumptionReceiptV1,
    canonical_envelope_set_sha256,
    read_regular_file_once,
    wire_challenge_consumption_path,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FORMAL_INFERENCE_PATH,
    FORMAL_ISAAC_CAPTURE_PATH,
    FORMAL_ISAAC_EXECUTE_PATH,
    FORMAL_ISAAC_FINALIZE_PATH,
    FORMAL_ISAAC_START_PATH,
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
    SignedInferenceRequestV2,
    SignedInferenceResponseV2,
    SignedWireMessageV2,
    append_public_executed_intent_history,
    build_episode_from_external_evidence,
    canonical_sha256 as formal_canonical_sha256,
    journal_decision_from_wire,
    runtime_request_from_inference,
)
from xh_agent.policy.qrm_lite.qb_adr_gate import evaluate_qb_adr_gate
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


ADR_IMPLEMENTATION_COMMIT = "36935f2921c8bc1609ae1711b7246e6f3c7dfb08"
FROZEN_KEY_MANIFEST_COMMIT = "5243ee346309c6b7e15270436bb9bbcab5f7e509"
FROZEN_KEY_MANIFEST_PATH = "configs/m2c_s4_training_keys.json"
FROZEN_KEY_MANIFEST_FILE_SHA256 = "ca2162a898853ee04600aaf9246c121ac0604754638e497d1824b159c161fd94"
FROZEN_KEY_MANIFEST_CONTENT_SHA256 = (
    "f5dc3566d028821f5df48afd07f133ea94af21fae21ec8bd5be63644893145e2"
)
FROZEN_EVALUATION_MANIFEST_PATH = "configs/m2c_s6_evaluation_keys.json"
FROZEN_EVALUATION_MANIFEST_FILE_SHA256 = (
    "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
)
FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256 = (
    "0ce322d948dac851d7a26053af0207e563a69bb0127c462312cdad9badafe419"
)
FROZEN_WIRE_CHALLENGE_MANIFEST_PATH = "configs/m2c_s4_wire_challenges.json"
FROZEN_WIRE_CHALLENGE_MANIFEST_FILE_SHA256 = (
    "06d1811ea45ea24a8e817c38485746b3f4efb07b48c446cd3766008358e5b686"
)
B0_FREEZE_PATH = "configs/m2c_b0_freeze.json"
B0_FREEZE_SHA256 = "4bec9104be849dfd8d71b32b537eb2b5d70ea4d8560b4bdd65b1d1019d3e8d04"

QWEN_MODEL_ID = "Qwen/Qwen3.5-4B"
QWEN_MODEL_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
QWEN_ARCHITECTURE_REVISION = "M2C_Q012_V2"
QWEN_HIDDEN_SIZE = 2560
QWEN_BUNDLE_MANIFEST_NAME = "qwen_coarse_v2_bundle.json"
QWEN_HEAD_CHECKPOINT_NAME = "qwen_coarse_v2_heads.npz"
QWEN_TRAIN_REPORT_NAME = "train_report.json"
# Intentionally unset until the separately reviewed Qwen->V2 mapping->Isaac
# runner is committed, passes a real Isaac 6 contract startup, and is frozen by
# exact path and SHA-256.  This is a source-level freeze rather than an
# environment override, so the current production gate cannot authorize formal
# evaluation regardless of supplied receipts.
FORMAL_PHYSICAL_RUNNER_BINDING: tuple[str, str] | None = None
# A runner/source hash is not a deployment identity. Unlocking this binding
# still requires the immutable implementation commit, container image, and
# complete transitive-import manifest. ADR-0024 withdrew the runtime B0
# wrapper; INVALID/preflight rejection is terminal NO_PHYSICAL_EXECUTION.
FORMAL_DEPLOYMENT_CLOSURE_BINDING: tuple[str, str, str] | None = None
# Compatibility sentinel withdrawn by ADR-0024 section 2. It must remain None
# and is not an unlock requirement or an execution path.
FROZEN_B0_RUNTIME_WRAPPER_BINDING: tuple[str, str] | None = None
# ADR-0024 section 4 rescinded Ed25519/public-trust-root attestation as a
# precondition. This compatibility sentinel stays None and is never an unlock;
# entry accepts only unsigned V2 host-local HMAC receipts and freezes their
# verifier implementation through the deployment closure.
OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING: dict[str, tuple[str, str, str, str]] | None = None
QWEN_HEAD_TENSORS: tuple[str, ...] = (
    "skill_w",
    "skill_b",
    "pointer_w",
    "pointer_b",
    "destination_w",
    "destination_b",
)

# These bytes are the formal runtime contract, not a claim that every file is
# already committed at the report commit.  Receipts name the checked
# implementation commit separately; it may be an ancestor of a later report
# commit, while these worktree bindings must still match exactly.
RUNTIME_BINDINGS: dict[str, str] = {
    "configs/qrm_runtime_mapping_v2.yaml": (
        "3572f80f1597b7f3bdffb1f8aad90d5baeb086b25c371b88511bc58444813359"
    ),
    "configs/qrm_lite/backbone-qwen35-4b.yaml": (
        "694e1ba6ea3731c4389cc14defe372429d3f94a298a1c66a9dfcbc38c44fb2a3"
    ),
    "schemas/coarse-intent-v2.schema.json": (
        "b30d6014b154738a42886f709b072f2e08a792a168570c17b2cf6d20a1c824fe"
    ),
    "schemas/runtime-skill-v2.schema.json": (
        "122f397b422779af4825a202728ec41c8b7ca369591654bdbfb6dbe0de09dda1"
    ),
    "scripts/generate_industrial_scenes.py": (
        "e9f9e20106a05dbec24453ce39422d57aa212709567fb7eba7f8d9beb03cd6c5"
    ),
    "scripts/m2c/qwen_coarse_v2.py": (
        "b6c4e29486941c54a8b4d6c069bd95a625751fff1f17900581ec9b8e0c613ae6"
    ),
    "scripts/m2c/train_qwen_coarse_v2.py": (
        "8b25a36448c57b9744c98c00675978c6ead86ac72cb4840b7ffe224dc9011c76"
    ),
    "scripts/m2c/evaluate_qwen_coarse_v2.py": (
        "ca7de0fac0c143d917c449fb9aba18e8ab26312fd81a401585815a8a89ccd422"
    ),
    "scripts/m2c/serve_qwen_coarse_v2.py": (
        "f1f3448e6ee16747226c6a1e7bf61a08f985a1d3f1aebb739e9650c2596dd7a7"
    ),
    "scripts/m2c/run_formal_model_owned_chain.py": (
        "46ddacecc585bc99efba31a94482c51545c5a82ef3e8e26eaa809b37b203781f"
    ),
    "scripts/m2c/verify_formal_wire_auth.py": (
        "bfd8e049432269b119be2bdb951f42d4e613f6896ef10c90ae817364a92ceb3d"
    ),
    "scripts/m2c/formal_isaac_v4_backend.py": (
        "73ada118846c4392c73aa3f0459195e71a1d54378c549487e1ef3504bc4d79bf"
    ),
    "scripts/m2c/serve_formal_isaac_endpoint.py": (
        "13a9fe4a4666161383c7149785a1035465ab9413e3742bd3b425f054b4f077c8"
    ),
    "src/xh_agent/policy/qrm_lite/backbone.py": (
        "291fe17515e86c75b944849972583f0af4c7c8f2fb5dd0161fe2e34d1ab02375"
    ),
    "src/xh_agent/policy/qrm_lite/closed_loop_metrics.py": (
        "a4cd355fd39c4f2b41d6886c973902ce12cea78b5b5f58f72ced5be9f51c5746"
    ),
    "src/xh_agent/policy/qrm_lite/executed_intent_history_v2.py": (
        "e8d7587c11e23976732c80800481853b8a851eb0a78f40f40f47eb0fb04bb748"
    ),
    "src/xh_agent/policy/qrm_lite/formal_split_runner_v2.py": (
        "f9a48ffaaf548e0de07370cdd4478d744d26f4b0b1c3ed7d07fba992f6759f78"
    ),
    "src/xh_agent/policy/qrm_lite/formal_isaac_endpoint_v2.py": (
        "ce11aa23efd271e85bd6ada98ee336f37bb77319be6cd8a6b0a1059f42dc3c9b"
    ),
    "src/xh_agent/policy/qrm_lite/formal_public_role_selector_v2.py": (
        "4e853dcb86c2bb51a9ca58f8441199e10d85366657669087e5b26a3aaf8a93a4"
    ),
    "src/xh_agent/policy/qrm_lite/m2c_hard_freeze.py": (
        "91c2a6fdb2c1f95e8638e9c08b3ac2977fe39229dcff5f2fa85239c918fe1b09"
    ),
    "src/xh_agent/policy/qrm_lite/model_owned_chain_v2.py": (
        "fd76aebd3d319dd30857a721e89bcb028ae144d4d60b6d761d2d8e04f8614444"
    ),
    "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py": (
        "094800945b945378dc7a937e66ecbe1c2d8a71dbf19ed2b6b78cec6b85a4a767"
    ),
    "src/xh_agent/policy/qrm_lite/models_q012_v2.py": (
        "5334fbee5750fd4df1f6b421eac0336ced98849aa68e1c6948986bdbb15f540c"
    ),
    "src/xh_agent/policy/qrm_lite/public_tracks_v2.py": (
        "0d3f04767fd218f8759d42d58e5507b5f2c2b835e8d6c8c873b086ff7e614f6b"
    ),
    "src/xh_agent/policy/qrm_lite/runtime_adapter_v2.py": (
        "483b0d1f259b5c52e2158686729e0f53c7c2d82a0f350cff789a27ad10983b25"
    ),
    "src/xh_agent/policy/qrm_lite/skill_registry_v2.py": (
        "b12b575c205883f7ae48acf8976df9b38ed9ed47c364acad8521c4d3b6a7e089"
    ),
}

LOCAL_TEST_NODE_IDS: tuple[str, ...] = (
    "tests/unit/test_m2c_coarse_intent_v2.py",
    "tests/unit/test_m2c_public_tracks_v2.py",
    "tests/unit/test_m2c_runtime_mapping_v2.py",
    "tests/unit/test_m2c_model_owned_chain_v2.py",
    "tests/unit/test_m2c_q012_v2_checkpoint.py",
    "tests/unit/test_m2b_checkpoint_compatibility.py",
    "tests/unit/test_m2c_executed_intent_history_v2.py",
    "tests/unit/test_m2c_qwen_coarse_v2.py",
    "tests/unit/test_m2c_formal_split_runner_v2.py",
    "tests/unit/test_m2c_formal_isaac_endpoint_v2.py",
    "tests/unit/test_m2c_qwen_service_audit.py",
    "tests/unit/test_m2c_offline_wire_auth.py",
    "tests/unit/test_m2c_hard_freeze.py",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(encoded)


def _head_tensor_sha256(name: str, value: np.ndarray) -> str:
    """Hash one loaded head tensor with its semantic name, shape, and dtype."""

    array = np.ascontiguousarray(np.asarray(value))
    header = json.dumps(
        {
            "dtype": array.dtype.str,
            "name": name,
            "shape": list(array.shape),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _sha256(header + b"\0" + array.tobytes(order="C"))


def canonical_qwen_head_tensor_hashes(heads: Any) -> dict[str, str]:
    """Return exact hashes for all three Qwen V2 output heads."""

    tensors = heads.tensors()
    if set(tensors) != set(QWEN_HEAD_TENSORS):
        raise ValueError("Qwen V2 head tensor set is not exact")
    return {name: _head_tensor_sha256(name, tensors[name]) for name in QWEN_HEAD_TENSORS}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LocalContractTestReceiptV2(StrictModel):
    """Receipt from the separate local prerequisite-test command only."""

    schema_version: Literal["M2CS4LocalContractTestReceiptV2"] = "M2CS4LocalContractTestReceiptV2"
    evidence_origin: Literal["LOCAL_CONTRACT_TESTS"] = "LOCAL_CONTRACT_TESTS"
    command: list[str] = Field(min_length=4)
    node_ids: list[str] = Field(min_length=len(LOCAL_TEST_NODE_IDS))
    exit_code: int
    tests_passed: int = Field(ge=0)
    tests_failed: int = Field(ge=0)
    tests_skipped: int = Field(ge=0)
    checked_implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_binding_sha256: dict[str, str]
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_local_suite_passed(self) -> "LocalContractTestReceiptV2":
        if self.node_ids != list(LOCAL_TEST_NODE_IDS):
            raise ValueError("local receipt node list is not the frozen prerequisite suite")
        if self.command[:3] != ["python", "-m", "pytest"]:
            raise ValueError("local receipt command is not python -m pytest")
        if self.command[3:] != ["-q", *LOCAL_TEST_NODE_IDS]:
            raise ValueError("local receipt command arguments are not the frozen suite")
        if self.exit_code != 0 or self.tests_passed < 1 or self.tests_failed != 0:
            raise ValueError("local contract suite did not pass")
        if self.runtime_binding_sha256 != RUNTIME_BINDINGS:
            raise ValueError("local receipt runtime bindings do not match the frozen set")
        return self


class QwenWorldModelBundleReceiptV1(StrictModel):
    """Hash-bound trained Qwen LoRA + three-head bundle used by the test model."""

    schema_version: Literal["M2CS4QwenWorldModelBundleReceiptV1"] = (
        "M2CS4QwenWorldModelBundleReceiptV1"
    )
    bundle_root: str = Field(min_length=1)
    bundle_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    train_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    head_checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    head_tensor_sha256: dict[str, str]
    metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architecture_revision: Literal[QWEN_ARCHITECTURE_REVISION] = QWEN_ARCHITECTURE_REVISION
    model_id: Literal[QWEN_MODEL_ID] = QWEN_MODEL_ID
    model_revision: Literal[QWEN_MODEL_REVISION] = QWEN_MODEL_REVISION
    failure_context: Literal["on", "off"]
    hidden_size: Literal[QWEN_HIDDEN_SIZE] = QWEN_HIDDEN_SIZE
    seed: int
    initialization_source: Literal["NONE"] = "NONE"
    initialization_adapter_sha256: Literal[None] = None
    adapter_source_architecture_revision: Literal[None] = None
    dataset_path: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_manifest_path: str = Field(min_length=1)
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_key_manifest_path: Literal[FROZEN_KEY_MANIFEST_PATH] = FROZEN_KEY_MANIFEST_PATH
    training_key_manifest_file_sha256: Literal[FROZEN_KEY_MANIFEST_FILE_SHA256] = (
        FROZEN_KEY_MANIFEST_FILE_SHA256
    )
    training_key_manifest_content_sha256: Literal[FROZEN_KEY_MANIFEST_CONTENT_SHA256] = (
        FROZEN_KEY_MANIFEST_CONTENT_SHA256
    )
    evaluation_key_manifest_path: Literal[FROZEN_EVALUATION_MANIFEST_PATH] = (
        FROZEN_EVALUATION_MANIFEST_PATH
    )
    evaluation_key_manifest_file_sha256: Literal[FROZEN_EVALUATION_MANIFEST_FILE_SHA256] = (
        FROZEN_EVALUATION_MANIFEST_FILE_SHA256
    )
    evaluation_key_manifest_content_sha256: Literal[FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256] = (
        FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256
    )
    world_model_mainline: Literal[True] = True
    structured_q012_control_policy: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    flow_status: Literal["DISABLED"] = "DISABLED"
    physical_evaluation_executed_by_training: Literal[False] = False

    @model_validator(mode="after")
    def exact_three_heads_and_initialization(self) -> "QwenWorldModelBundleReceiptV1":
        if set(self.head_tensor_sha256) != set(QWEN_HEAD_TENSORS):
            raise ValueError("world-model receipt does not bind the exact three heads")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in self.head_tensor_sha256.values()
        ):
            raise ValueError("world-model head tensor SHA-256 is malformed")
        return self


class FormalDeploymentClosureReceiptV1(StrictModel):
    """Immutable deployment identity beyond a few top-level source files."""

    schema_version: Literal["M2CFormalDeploymentClosureReceiptV1"] = (
        "M2CFormalDeploymentClosureReceiptV1"
    )
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    transitive_import_manifest_path: str = Field(min_length=1)
    transitive_import_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    host_hmac_verifier_implementation_path: Literal[HOST_HMAC_VERIFIER_IMPLEMENTATION_PATH] = (
        HOST_HMAC_VERIFIER_IMPLEMENTATION_PATH
    )
    host_hmac_verifier_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    invalid_or_rejected_action_policy: Literal["TERMINAL_NO_PHYSICAL_EXECUTION"] = (
        "TERMINAL_NO_PHYSICAL_EXECUTION"
    )
    b0_runtime_wrapper_present: Literal[False] = False
    b0_runtime_fallback_invocation_allowed: Literal[False] = False
    b0_comparison_freeze_manifest_sha256: Literal[B0_FREEZE_SHA256] = B0_FREEZE_SHA256
    b0_comparison_freeze_file_bindings: dict[str, str] = Field(min_length=1)
    backend_reimplements_b0_fallback: Literal[False] = False
    teacher_used: Literal[False] = False

    @model_validator(mode="after")
    def exact_b0_comparison_freeze_binding_shape(self) -> "FormalDeploymentClosureReceiptV1":
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.b0_comparison_freeze_file_bindings.values()
        ):
            raise ValueError("B0 comparison freeze bindings contain malformed SHA-256")
        return self


class FormalTransitiveImportClosureManifestV1(StrictModel):
    schema_version: Literal["M2CFormalTransitiveImportClosureManifestV1"] = (
        "M2CFormalTransitiveImportClosureManifestV1"
    )
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    files: dict[str, str] = Field(min_length=1)
    complete_transitive_import_closure: Literal[True] = True
    generated_inside_bound_container: Literal[True] = True
    teacher_used: Literal[False] = False

    @model_validator(mode="after")
    def exact_hash_values(self) -> "FormalTransitiveImportClosureManifestV1":
        if any(
            not isinstance(path, str)
            or not path
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for path, digest in self.files.items()
        ):
            raise ValueError("deployment import closure contains malformed file bindings")
        return self


class PhysicalIntegrationReceiptV2(StrictModel):
    """External receipt envelope emitted only by a real Isaac integration run."""

    schema_version: Literal["M2CS4PhysicalIntegrationReceiptV2"] = (
        "M2CS4PhysicalIntegrationReceiptV2"
    )
    evidence_origin: Literal["ISAAC_PHYSICAL_INTEGRATION"] = "ISAAC_PHYSICAL_INTEGRATION"
    execution_mode: Literal["REAL_PHYSICS_NO_MOCKS"] = "REAL_PHYSICS_NO_MOCKS"
    test_model_provenance: Literal["M2C_QWEN_V2_WORLD_MODEL_BUNDLE"] = (
        "M2C_QWEN_V2_WORLD_MODEL_BUNDLE"
    )
    host: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    collected_at_ns: int = Field(gt=0)
    matched_key: str = Field(min_length=1)
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_manifest_commit: Literal[FROZEN_KEY_MANIFEST_COMMIT]
    key_manifest_file_sha256: Literal[FROZEN_KEY_MANIFEST_FILE_SHA256]
    key_manifest_content_sha256: Literal[FROZEN_KEY_MANIFEST_CONTENT_SHA256]
    adr_implementation_commit: Literal[ADR_IMPLEMENTATION_COMMIT]
    checked_implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    runtime_binding_sha256: dict[str, str]
    b0_freeze_sha256: Literal[B0_FREEZE_SHA256]
    runner_implementation_path: str = Field(min_length=1)
    runner_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_closure: FormalDeploymentClosureReceiptV1
    world_model_bundle: QwenWorldModelBundleReceiptV1
    formal_runner_evidence_path: str = Field(min_length=1)
    formal_runner_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_consumption_receipt_path: str = Field(min_length=1)
    challenge_consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node2_wire_authentication_receipt_path: str = Field(min_length=1)
    node2_wire_authentication_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labserver_wire_authentication_receipt_path: str = Field(min_length=1)
    labserver_wire_authentication_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qwen_service_audit_path: str = Field(min_length=1)
    qwen_service_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    isaac_session_audit_path: str = Field(min_length=1)
    isaac_session_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    isaac_service_audit_path: str = Field(min_length=1)
    isaac_service_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    episode: ModelOwnedChainEpisodeV2
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def frozen_runtime_is_exact(self) -> "PhysicalIntegrationReceiptV2":
        if self.runtime_binding_sha256 != RUNTIME_BINDINGS:
            raise ValueError("physical receipt runtime bindings do not match frozen set")
        return self


def _read_json(path: Path) -> Any:
    return json.loads(read_regular_file_once(path))


def _resolve_path(root: Path, raw: str) -> Path:
    candidate = Path(raw)
    return (candidate if candidate.is_absolute() else root / candidate).resolve(strict=True)


def _file_binding_checks(root: Path) -> tuple[dict[str, bool], list[str]]:
    matches: dict[str, bool] = {}
    blockers: list[str] = []
    for relative, expected in {
        **RUNTIME_BINDINGS,
        B0_FREEZE_PATH: B0_FREEZE_SHA256,
        FROZEN_KEY_MANIFEST_PATH: FROZEN_KEY_MANIFEST_FILE_SHA256,
        FROZEN_EVALUATION_MANIFEST_PATH: FROZEN_EVALUATION_MANIFEST_FILE_SHA256,
        FROZEN_WIRE_CHALLENGE_MANIFEST_PATH: FROZEN_WIRE_CHALLENGE_MANIFEST_FILE_SHA256,
    }.items():
        path = root / relative
        actual = _sha256(path.read_bytes()) if path.is_file() else None
        matches[relative] = actual == expected
        if actual != expected:
            blockers.append(f"frozen file mismatch: {relative}: {actual} != {expected}")
    return matches, blockers


def _git_commit_exists(root: Path, commit: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _commit_binding_blockers(root: Path, commit: str) -> list[str]:
    """Require every frozen runtime byte to exist at the checked commit."""

    blockers: list[str] = []
    for relative, expected in RUNTIME_BINDINGS.items():
        completed = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{relative}"],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            blockers.append(f"checked implementation commit lacks runtime binding: {relative}")
            continue
        actual = _sha256(completed.stdout)
        if actual != expected:
            blockers.append(
                "checked implementation commit runtime binding mismatch: "
                f"{relative}: {actual} != {expected}"
            )
    return blockers


def _implementation_commit_blockers(
    root: Path,
    checked_implementation_commit: str,
    head_commit: str | None,
) -> list[str]:
    if not _git_commit_exists(root, checked_implementation_commit):
        return ["checked implementation commit cannot be resolved"]
    blockers: list[str] = []
    if not _git_is_ancestor(
        root,
        FROZEN_KEY_MANIFEST_COMMIT,
        checked_implementation_commit,
    ):
        blockers.append("checked implementation commit predates the frozen S4/S6 keys")
    if not isinstance(head_commit, str) or not _git_is_ancestor(
        root,
        checked_implementation_commit,
        head_commit,
    ):
        blockers.append("checked implementation commit is not an ancestor of report HEAD")
    blockers.extend(_commit_binding_blockers(root, checked_implementation_commit))
    return blockers


def _parse_signed_wire(
    raw: Any,
    *,
    message_type: str,
    payload_model: type[Any],
) -> tuple[SignedWireMessageV2, Any]:
    message = SignedWireMessageV2.model_validate(raw)
    if message.message_type != message_type:
        raise ValueError(f"wire message type differs: {message.message_type} != {message_type}")
    if message.payload_sha256 != formal_canonical_sha256(message.payload):
        raise ValueError(f"{message_type} canonical payload SHA-256 mismatch")
    return message, payload_model.model_validate(message.payload)


def _parse_signed_inference(
    raw: Any,
    *,
    request: bool,
) -> SignedInferenceRequestV2 | SignedInferenceResponseV2:
    model = SignedInferenceRequestV2 if request else SignedInferenceResponseV2
    message = model.model_validate(raw)
    if message.payload_sha256 != formal_canonical_sha256(message.payload):
        raise ValueError("inference canonical payload SHA-256 mismatch")
    return message


def _world_model_runtime_matches_receipt(
    binding: QwenBundleRuntimeBindingV2,
    receipt: QwenWorldModelBundleReceiptV1,
) -> bool:
    return bool(
        binding.model_id == receipt.model_id
        and binding.model_revision == receipt.model_revision
        and binding.architecture_revision == receipt.architecture_revision
        and binding.bundle_manifest_sha256 == receipt.bundle_manifest_sha256
        and binding.head_checkpoint_sha256 == receipt.head_checkpoint_sha256
        and binding.adapter_tree_sha256 == receipt.adapter_tree_sha256
        and binding.failure_context == receipt.failure_context
        and binding.local_files_only
    )


def _verify_formal_runner_evidence(
    raw: Any,
    *,
    receipt: PhysicalIntegrationReceiptV2,
) -> tuple[dict[str, Any], ModelOwnedChainEpisodeV2, ModelOwnedChainValidationV2]:
    """Independently replay the complete runner evidence without endpoint keys."""

    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "status",
        "run_id",
        "challenge_nonce",
        "challenge_consumption_receipt_path",
        "challenge_consumption_receipt_sha256",
        "challenge_consumption_id",
        "bundle",
        "isaac_endpoint_binding",
        "start_response",
        "wire_cycles",
        "finalize_request",
        "finalize_response",
        "episode",
        "validation",
        "synthetic",
        "mocked_physics",
        "scripted_decision_source",
        "teacher_used",
        "privileged_truth_policy_input",
    }:
        raise ValueError("formal runner evidence is not the exact complete V2 schema")
    if raw["schema_version"] != "M2CFormalSplitRunnerEvidenceV2":
        raise ValueError("formal runner evidence schema is not V2")
    if raw["status"] != "COMPLETE_REAL_PHYSICAL_EPISODE":
        raise ValueError("formal runner evidence is not a complete physical episode")
    for field in (
        "synthetic",
        "mocked_physics",
        "scripted_decision_source",
        "teacher_used",
        "privileged_truth_policy_input",
    ):
        if raw[field] is not False:
            raise ValueError(f"formal runner evidence forbidden flag set: {field}")

    run_id = raw["run_id"]
    if run_id != receipt.run_id:
        raise ValueError("formal runner evidence run differs from physical receipt")
    if raw["challenge_nonce"] != receipt.challenge_nonce:
        raise ValueError("formal runner evidence challenge differs from physical receipt")
    if (
        raw["challenge_consumption_receipt_path"] != receipt.challenge_consumption_receipt_path
        or raw["challenge_consumption_receipt_sha256"]
        != receipt.challenge_consumption_receipt_sha256
    ):
        raise ValueError("formal runner consumption binding differs from physical receipt")
    bundle = QwenBundleRuntimeBindingV2.model_validate(raw["bundle"])
    if not _world_model_runtime_matches_receipt(bundle, receipt.world_model_bundle):
        raise ValueError("formal runner runtime bundle differs from trained bundle receipt")
    endpoint = IsaacEndpointBindingV2.model_validate(raw["isaac_endpoint_binding"])
    if endpoint.host != receipt.host:
        raise ValueError("formal endpoint host differs from physical receipt")
    start = IsaacStartResponseV2.model_validate(raw["start_response"])
    endpoint_sha = formal_canonical_sha256(endpoint)
    if (
        start.run_id != run_id
        or start.endpoint_binding_sha256 != endpoint_sha
        or start.implementation_sha256 != endpoint.implementation_sha256
        or start.physical_backend_sha256 != endpoint.physical_backend_sha256
    ):
        raise ValueError("formal start response differs from endpoint deployment")
    session_id = start.session_id
    cycles = raw["wire_cycles"]
    if not isinstance(cycles, list) or len(cycles) != len(EXPECTED_PATH_BLOCKED_CHAIN):
        raise ValueError("formal runner evidence does not contain exactly eight wire cycles")

    registry = load_registry_v2(
        Path(__file__).resolve().parents[4] / "configs/qrm_runtime_mapping_v2.yaml"
    )
    history: list[Any] = []
    decisions = []
    previous_receipt_sha256: str | None = None
    previous_completed_at_ns = start.failure_observed_at_ns
    for index, cycle in enumerate(cycles):
        if not isinstance(cycle, dict) or set(cycle) != {
            "decision_index",
            "capture_request",
            "capture_response",
            "inference_request",
            "inference_response",
            "execute_request",
            "execute_response",
        }:
            raise ValueError(f"wire cycle {index} is incomplete or contains extra fields")
        if cycle["decision_index"] != index:
            raise ValueError("formal wire cycles are reordered")
        _, capture_request = _parse_signed_wire(
            cycle["capture_request"],
            message_type="ISAAC_CAPTURE_REQUEST",
            payload_model=IsaacCaptureRequestV2,
        )
        _, capture = _parse_signed_wire(
            cycle["capture_response"],
            message_type="ISAAC_CAPTURE_RESPONSE",
            payload_model=IsaacCaptureResponseV2,
        )
        inference_request = _parse_signed_inference(cycle["inference_request"], request=True)
        inference = _parse_signed_inference(cycle["inference_response"], request=False)
        _, execute_request = _parse_signed_wire(
            cycle["execute_request"],
            message_type="ISAAC_EXECUTE_REQUEST",
            payload_model=IsaacExecuteRequestV2,
        )
        _, execute = _parse_signed_wire(
            cycle["execute_response"],
            message_type="ISAAC_EXECUTE_RESPONSE",
            payload_model=IsaacExecuteResponseV2,
        )
        if any(
            value != expected
            for value, expected in (
                (capture_request.run_id, run_id),
                (capture_request.session_id, session_id),
                (capture_request.decision_index, index),
                (capture_request.previous_physical_receipt_sha256, previous_receipt_sha256),
                (capture.run_id, run_id),
                (capture.session_id, session_id),
                (capture.decision_index, index),
                (capture.observation.previous_physical_completed_at_ns, previous_completed_at_ns),
                (
                    capture.public_roles.selector_contract_sha256,
                    endpoint.public_role_selector_sha256,
                ),
                (inference_request.payload.run_id, run_id),
                (inference_request.payload.challenge_nonce, receipt.challenge_nonce),
                (inference_request.payload.decision_index, index),
                (inference_request.payload.executed_intent_history, history),
                (
                    inference_request.payload.prior_decisions_sha256,
                    formal_canonical_sha256(history),
                ),
                (inference_request.payload.bundle, bundle),
                (inference_request.payload.observation, capture.observation),
                (inference.payload.run_id, run_id),
                (inference.payload.request_id, inference_request.payload.request_id),
                (inference.payload.decision_index, index),
                (inference.payload.request_payload_sha256, inference_request.payload_sha256),
                (
                    inference.payload.executed_intent_history_sha256,
                    inference_request.payload.prior_decisions_sha256,
                ),
                (inference.payload.bundle, bundle),
                (
                    inference.payload.head_tensor_sha256,
                    receipt.world_model_bundle.head_tensor_sha256,
                ),
                (execute_request.run_id, run_id),
                (execute_request.session_id, session_id),
                (execute_request.decision_index, index),
                (execute_request.observation_id, capture.observation.observation_id),
                (
                    execute_request.capture_receipt_sha256,
                    capture.observation.capture_receipt_sha256,
                ),
                (execute_request.inference_response_sha256, inference.payload_sha256),
                (
                    execute_request.executed_intent_history_sha256,
                    inference_request.payload.prior_decisions_sha256,
                ),
                (execute.run_id, run_id),
                (execute.session_id, session_id),
                (execute.decision_index, index),
                (execute.observation_id, capture.observation.observation_id),
                (execute.inference_response_sha256, inference.payload_sha256),
            )
        ):
            raise ValueError(f"formal wire cycle {index} linkage differs")
        expected_runtime = runtime_request_from_inference(
            inference_request.payload,
            inference.payload,
            registry,
        )
        if execute_request.runtime_request != expected_runtime:
            raise ValueError(f"formal wire cycle {index} runtime mapping request differs")
        decisions.append(journal_decision_from_wire(inference, capture, execute))
        history = append_public_executed_intent_history(history, inference, execute)
        physical = execute.physical_skill_receipts[0]
        previous_receipt_sha256 = physical.receipt_sha256
        previous_completed_at_ns = physical.completed_at_ns

    _, finalize_request = _parse_signed_wire(
        raw["finalize_request"],
        message_type="ISAAC_FINALIZE_REQUEST",
        payload_model=IsaacFinalizeRequestV2,
    )
    _, finalize = _parse_signed_wire(
        raw["finalize_response"],
        message_type="ISAAC_FINALIZE_RESPONSE",
        payload_model=IsaacFinalizeResponseV2,
    )
    if (
        any(
            value != expected
            for value, expected in (
                (finalize_request.run_id, run_id),
                (finalize_request.session_id, session_id),
                (finalize_request.last_physical_receipt_sha256, previous_receipt_sha256),
                (finalize_request.decisions_observed, 8),
                (finalize.run_id, run_id),
                (finalize.session_id, session_id),
            )
        )
        or finalize.evaluated_at_ns <= previous_completed_at_ns
    ):
        raise ValueError("formal finalize linkage differs from the eight-cycle session")
    episode = build_episode_from_external_evidence(
        run_id=run_id,
        failure_observed_at_ns=start.failure_observed_at_ns,
        final_task_success=finalize.final_task_success,
        decisions=decisions,
    )
    validation = validate_model_owned_chain_episode(episode)
    if raw["episode"] != episode.model_dump(mode="json"):
        raise ValueError("formal runner episode is not reconstructed from wire evidence")
    if raw["validation"] != validation.model_dump(mode="json"):
        raise ValueError("formal runner validation differs from independent replay")
    return {"wire_cycles_verified": 8, "session_id": session_id}, episode, validation


def _read_isaac_audit(
    source: Path | bytes,
    *,
    label: str,
) -> list[dict[str, Any]]:
    data = read_regular_file_once(source) if isinstance(source, Path) else source
    if not data.endswith(b"\n"):
        raise ValueError(f"{label} is not newline-terminated")
    lines = data.splitlines()
    records = [json.loads(line) for line in lines]
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError(f"{label} is empty or contains a non-object event")
    first_sequence = records[0].get("sequence")
    if not isinstance(first_sequence, int) or any(
        record.get("schema_version") != "FormalIsaacAuditEventV2"
        or record.get("sequence") != first_sequence + index
        or json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        != lines[index]
        for index, record in enumerate(records)
    ):
        raise ValueError(f"{label} is not a canonical contiguous append-only V2 journal")
    if any(record.get("event_type") == "WIRE_REQUEST_REJECTED" for record in records):
        raise ValueError(f"{label} contains a rejected request")
    return records


def _read_qwen_audit(source: Path | bytes) -> list[dict[str, Any]]:
    data = read_regular_file_once(source) if isinstance(source, Path) else source
    if not data.endswith(b"\n"):
        raise ValueError("Qwen service audit is not newline-terminated")
    lines = data.splitlines()
    records = [json.loads(line) for line in lines]
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError("Qwen service audit is empty or contains a non-object event")
    if any(
        record.get("schema_version") != "FormalQwenAuditEventV2"
        or record.get("sequence") != index
        or json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        != lines[index - 1]
        for index, record in enumerate(records, start=1)
    ):
        raise ValueError("Qwen service audit is not canonical contiguous V2 JSONL")
    if any(record.get("event_type") == "WIRE_REQUEST_REJECTED" for record in records):
        raise ValueError("Qwen service audit contains a rejected request")
    return records


def _verify_isaac_audits(
    service_source: Path | bytes,
    session_source: Path | bytes,
    *,
    evidence: dict[str, Any],
    receipt: PhysicalIntegrationReceiptV2,
) -> None:
    service = _read_isaac_audit(service_source, label="Isaac service audit")
    session = _read_isaac_audit(session_source, label="Isaac session audit")
    service_by_sequence = {record["sequence"]: record for record in service}
    if any(service_by_sequence.get(record["sequence"]) != record for record in session):
        raise ValueError("Isaac session audit is not an exact service-audit suffix")
    if session[0].get("event_type") != "SESSION_AUDIT_CREATED":
        raise ValueError("Isaac session audit does not begin at create-only session creation")

    service_requests = [
        record.get("payload", {}).get("signed_wire")
        for record in service
        if record.get("event_type") == "WIRE_REQUEST_RECEIVED"
    ]
    service_responses = [
        record.get("payload", {}).get("signed_wire")
        for record in service
        if record.get("event_type") == "WIRE_RESPONSE_COMMITTED"
    ]
    if len(service_requests) != 18 or len(service_responses) != 18:
        raise ValueError("Isaac service audit does not contain exactly 18 request/response pairs")
    _, start_request = _parse_signed_wire(
        service_requests[0],
        message_type="ISAAC_START_REQUEST",
        payload_model=IsaacStartRequestV2,
    )
    _, start_response = _parse_signed_wire(
        service_responses[0],
        message_type="ISAAC_START_RESPONSE",
        payload_model=IsaacStartResponseV2,
    )
    endpoint = IsaacEndpointBindingV2.model_validate(evidence["isaac_endpoint_binding"])
    bundle = QwenBundleRuntimeBindingV2.model_validate(evidence["bundle"])
    if any(
        value != expected
        for value, expected in (
            (start_request.run_id, receipt.run_id),
            (start_request.challenge_nonce, receipt.challenge_nonce),
            (
                start_request.challenge_consumption_id,
                evidence["challenge_consumption_id"],
            ),
            (
                start_request.challenge_consumption_receipt_sha256,
                evidence["challenge_consumption_receipt_sha256"],
            ),
            (start_request.matched_key, receipt.matched_key),
            (start_request.scene_seed, receipt.scene_seed),
            (start_request.failure_seed, receipt.failure_seed),
            (start_request.sdf_sha256, receipt.sdf_sha256),
            (start_request.supervision_sha256, receipt.supervision_sha256),
            (
                start_request.runtime_registry_sha256,
                RUNTIME_BINDINGS["configs/qrm_runtime_mapping_v2.yaml"],
            ),
            (start_request.endpoint_binding_sha256, formal_canonical_sha256(endpoint)),
            (start_request.bundle, bundle),
            (start_response.model_dump(mode="json"), evidence["start_response"]),
            (start_response.start_request_sha256, formal_canonical_sha256(start_request)),
        )
    ):
        raise ValueError("Isaac audited start transaction differs from frozen run binding")

    expected_requests = [
        service_requests[0],
        *[
            item
            for cycle in evidence["wire_cycles"]
            for item in (cycle["capture_request"], cycle["execute_request"])
        ],
        evidence["finalize_request"],
    ]
    expected_responses = [
        service_responses[0],
        *[
            item
            for cycle in evidence["wire_cycles"]
            for item in (cycle["capture_response"], cycle["execute_response"])
        ],
        evidence["finalize_response"],
    ]
    if service_requests != expected_requests or service_responses != expected_responses:
        raise ValueError("Isaac service audit wire transaction differs from formal evidence")
    created_payload = session[0].get("payload", {})
    if created_payload.get("run_id") != receipt.run_id or created_payload.get(
        "request_sha256"
    ) != formal_canonical_sha256(start_request):
        raise ValueError("Isaac session audit identity differs from audited start request")
    session_requests = [
        record.get("payload", {}).get("signed_wire")
        for record in session
        if record.get("event_type") == "WIRE_REQUEST_RECEIVED"
    ]
    session_responses = [
        record.get("payload", {}).get("signed_wire")
        for record in session
        if record.get("event_type") == "WIRE_RESPONSE_COMMITTED"
    ]
    if session_requests != expected_requests[1:] or session_responses != expected_responses:
        raise ValueError("Isaac session audit is incomplete or differs from service audit")
    return service, session


def _external_physical_evidence_blockers(
    root: Path,
    receipt: PhysicalIntegrationReceiptV2,
) -> list[str]:
    """Verify files produced by a separately implemented physical runner.

    Until the reviewed runner has passed a real Isaac contract startup and the
    source-level binding above names its exact repository path and bytes, no
    receipt can make this layer pass.
    """

    blockers: list[str] = []
    if FORMAL_PHYSICAL_RUNNER_BINDING is None:
        blockers.append(
            "formal Qwen-to-Isaac runner is not independently reviewed, "
            "real-Isaac contract-verified, and frozen"
        )
    else:
        frozen_runner_path, frozen_runner_sha256 = FORMAL_PHYSICAL_RUNNER_BINDING
        if receipt.runner_implementation_path != frozen_runner_path:
            blockers.append("physical receipt runner implementation path is not the frozen runner")
        if receipt.runner_implementation_sha256 != frozen_runner_sha256:
            blockers.append("physical receipt runner implementation is not the frozen runner")
    if FORMAL_DEPLOYMENT_CLOSURE_BINDING is None:
        blockers.append(
            "formal deployment has no frozen implementation commit, container image, "
            "and complete transitive-import closure"
        )
    else:
        commit, image, manifest_sha = FORMAL_DEPLOYMENT_CLOSURE_BINDING
        closure = receipt.deployment_closure
        if (closure.implementation_commit, closure.container_image_digest) != (commit, image):
            blockers.append("formal deployment commit/image differs from frozen closure")
        if closure.transitive_import_manifest_sha256 != manifest_sha:
            blockers.append("formal deployment transitive-import manifest differs")
    try:
        b0_freeze = _read_json(root / B0_FREEZE_PATH)
        exact_b0 = {item["path"]: item["sha256"] for item in b0_freeze["b0_files"]}
        if receipt.deployment_closure.b0_comparison_freeze_file_bindings != exact_b0:
            blockers.append("formal deployment does not bind the independent B0 comparison arm")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        blockers.append(f"frozen B0 runtime binding failed closed: {type(error).__name__}: {error}")
    challenge_manifest_bytes: bytes | None = None
    try:
        challenge_manifest_bytes = read_regular_file_once(
            root / FROZEN_WIRE_CHALLENGE_MANIFEST_PATH
        )
        challenge_manifest = json.loads(challenge_manifest_bytes)
        if (
            challenge_manifest.get("schema_version") != "M2CS4WireChallengeManifestV1"
            or challenge_manifest.get("formal_q_b_evaluation_authorized") is not False
            or challenge_manifest.get("teacher_used") is not False
            or challenge_manifest.get("privileged_truth_policy_input") is not False
        ):
            raise ValueError("wire challenge manifest governance fields differ")
        matches = [
            item
            for item in challenge_manifest.get("challenge_records", [])
            if isinstance(item, dict)
            and item.get("matched_key") == receipt.matched_key
            and item.get("scene_seed") == receipt.scene_seed
            and item.get("failure_seed") == receipt.failure_seed
            and item.get("run_id") == receipt.run_id
            and item.get("challenge_nonce") == receipt.challenge_nonce
        ]
        if len(matches) != 1:
            blockers.append(
                "formal physical receipt does not consume exactly one preregistered wire challenge"
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        blockers.append(
            f"wire challenge preregistration failed closed: {type(error).__name__}: {error}"
        )

    evidence = {
        "runner implementation": (
            receipt.runner_implementation_path,
            receipt.runner_implementation_sha256,
        ),
        "formal runner evidence": (
            receipt.formal_runner_evidence_path,
            receipt.formal_runner_evidence_sha256,
        ),
        "wire challenge consumption receipt": (
            receipt.challenge_consumption_receipt_path,
            receipt.challenge_consumption_receipt_sha256,
        ),
        "node2 wire authentication receipt": (
            receipt.node2_wire_authentication_receipt_path,
            receipt.node2_wire_authentication_receipt_sha256,
        ),
        "labserver wire authentication receipt": (
            receipt.labserver_wire_authentication_receipt_path,
            receipt.labserver_wire_authentication_receipt_sha256,
        ),
        "Qwen service audit": (
            receipt.qwen_service_audit_path,
            receipt.qwen_service_audit_sha256,
        ),
        "Isaac session audit": (
            receipt.isaac_session_audit_path,
            receipt.isaac_session_audit_sha256,
        ),
        "Isaac service audit": (
            receipt.isaac_service_audit_path,
            receipt.isaac_service_audit_sha256,
        ),
        "deployment import manifest": (
            receipt.deployment_closure.transitive_import_manifest_path,
            receipt.deployment_closure.transitive_import_manifest_sha256,
        ),
    }
    evidence_bytes: dict[str, bytes] = {}
    for label, (raw_path, expected_sha256) in evidence.items():
        try:
            path = _resolve_path(root, raw_path)
            payload = read_regular_file_once(path)
        except (FileNotFoundError, OSError, ValueError):
            blockers.append(f"physical {label} file is absent")
            continue
        evidence_bytes[label] = payload
        actual = _sha256(payload)
        if actual != expected_sha256:
            blockers.append(f"physical {label} SHA-256 mismatch: {actual} != {expected_sha256}")
    try:
        consumption_path = Path(receipt.challenge_consumption_receipt_path)
        if not consumption_path.is_absolute():
            consumption_path = root / consumption_path
        consumption_stat = consumption_path.stat(follow_symlinks=False)
        if (
            consumption_path.is_symlink()
            or not consumption_path.is_file()
            or consumption_stat.st_nlink != 1
            or consumption_stat.st_mode & 0o222
        ):
            blockers.append(
                "wire challenge consumption receipt is not immutable single-link evidence"
            )
        consumption = WireChallengeConsumptionReceiptV1.model_validate(
            json.loads(evidence_bytes["wire challenge consumption receipt"])
        )
        expected_consumption_path = wire_challenge_consumption_path(
            Path(CANONICAL_WIRE_CHALLENGE_CONSUMPTION_ROOT),
            receipt.challenge_nonce,
        )
        if Path(receipt.challenge_consumption_receipt_path) != expected_consumption_path:
            blockers.append("wire challenge consumption receipt path is not canonical")
        if challenge_manifest_bytes is None or any(
            observed != expected
            for observed, expected in (
                (consumption.run_id, receipt.run_id),
                (consumption.challenge_nonce, receipt.challenge_nonce),
                (consumption.matched_key, receipt.matched_key),
                (consumption.scene_seed, receipt.scene_seed),
                (consumption.failure_seed, receipt.failure_seed),
                (consumption.challenge_manifest_sha256, _sha256(challenge_manifest_bytes)),
            )
        ):
            blockers.append("wire challenge consumption receipt differs from preregistered run")
        formal_consumption = json.loads(evidence_bytes["formal runner evidence"])
        if (
            not isinstance(formal_consumption, dict)
            or formal_consumption.get("challenge_consumption_id") != consumption.consumption_id
        ):
            blockers.append("formal evidence consumption ID differs from create-only receipt")
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, KeyError) as error:
        blockers.append(
            f"wire challenge consumption replay failed closed: {type(error).__name__}: {error}"
        )
    try:
        closure_manifest = FormalTransitiveImportClosureManifestV1.model_validate(
            json.loads(evidence_bytes["deployment import manifest"])
        )
        if (
            closure_manifest.implementation_commit
            != receipt.deployment_closure.implementation_commit
            or closure_manifest.container_image_digest
            != receipt.deployment_closure.container_image_digest
        ):
            blockers.append("deployment import manifest identity differs from receipt")
        required_closure_files = {
            receipt.runner_implementation_path: receipt.runner_implementation_sha256,
            receipt.deployment_closure.host_hmac_verifier_implementation_path: (
                receipt.deployment_closure.host_hmac_verifier_implementation_sha256
            ),
            **{
                getattr(
                    IsaacEndpointBindingV2.model_validate(
                        json.loads(evidence_bytes["formal runner evidence"])[
                            "isaac_endpoint_binding"
                        ]
                    ),
                    path_field,
                ): getattr(
                    IsaacEndpointBindingV2.model_validate(
                        json.loads(evidence_bytes["formal runner evidence"])[
                            "isaac_endpoint_binding"
                        ]
                    ),
                    sha_field,
                )
                for path_field, sha_field in (
                    ("implementation_path", "implementation_sha256"),
                    ("physical_backend_path", "physical_backend_sha256"),
                    ("public_role_selector_path", "public_role_selector_sha256"),
                )
            },
        }
        for path, digest in required_closure_files.items():
            if closure_manifest.files.get(path) != digest:
                blockers.append(f"deployment import closure lacks exact runtime file: {path}")
        verifier_path = root / receipt.deployment_closure.host_hmac_verifier_implementation_path
        if verifier_path.is_symlink():
            blockers.append("host HMAC verifier implementation path is a symlink")
        verifier_bytes = read_regular_file_once(verifier_path)
        if _sha256(verifier_bytes) != (
            receipt.deployment_closure.host_hmac_verifier_implementation_sha256
        ):
            blockers.append("host HMAC verifier implementation SHA mismatch")
        for path, digest in receipt.deployment_closure.b0_comparison_freeze_file_bindings.items():
            if closure_manifest.files.get(path) != digest:
                blockers.append(f"deployment import closure lacks B0 comparison file: {path}")
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, KeyError) as error:
        blockers.append(f"deployment import closure failed closed: {type(error).__name__}: {error}")
    try:
        formal_raw = json.loads(evidence_bytes["formal runner evidence"])
        replay, episode, _ = _verify_formal_runner_evidence(formal_raw, receipt=receipt)
        if episode != receipt.episode:
            blockers.append(
                "physical receipt episode differs from independently replayed wire episode"
            )
        isaac_service, _ = _verify_isaac_audits(
            evidence_bytes["Isaac service audit"],
            evidence_bytes["Isaac session audit"],
            evidence=formal_raw,
            receipt=receipt,
        )
        qwen_service = _read_qwen_audit(evidence_bytes["Qwen service audit"])
        auth_receipts = {
            "NODE2_QWEN": HostWireHMACVerificationReceiptV2.model_validate(
                json.loads(evidence_bytes["node2 wire authentication receipt"])
            ),
            "LABSERVER_ISAAC": HostWireHMACVerificationReceiptV2.model_validate(
                json.loads(evidence_bytes["labserver wire authentication receipt"])
            ),
        }
        if any(auth.core.host_role != role for role, auth in auth_receipts.items()):
            blockers.append("offline authentication receipts swap or duplicate host roles")
        for role, auth in auth_receipts.items():
            if (
                auth.core.run_id != receipt.run_id
                or auth.core.challenge_nonce != receipt.challenge_nonce
                or auth.core.formal_evidence_sha256 != receipt.formal_runner_evidence_sha256
                or auth.core.verifier_implementation_path
                != receipt.deployment_closure.host_hmac_verifier_implementation_path
                or auth.core.verifier_implementation_sha256
                != receipt.deployment_closure.host_hmac_verifier_implementation_sha256
            ):
                blockers.append(f"{role} authentication receipt differs from formal evidence")
        node2 = auth_receipts["NODE2_QWEN"].core
        labserver = auth_receipts["LABSERVER_ISAAC"].core
        if node2.service_audit_sha256 != receipt.qwen_service_audit_sha256:
            blockers.append("node2 authentication receipt differs from Qwen service audit")
        if (
            labserver.service_audit_sha256 != receipt.isaac_service_audit_sha256
            or labserver.session_audit_sha256 != receipt.isaac_session_audit_sha256
        ):
            blockers.append("labserver authentication receipt differs from Isaac audits")
        qwen_digest = canonical_envelope_set_sha256(
            qwen_service,
            expected_paths=[FORMAL_INFERENCE_PATH] * 8,
        )
        isaac_paths = [FORMAL_ISAAC_START_PATH]
        for _ in range(8):
            isaac_paths.extend((FORMAL_ISAAC_CAPTURE_PATH, FORMAL_ISAAC_EXECUTE_PATH))
        isaac_paths.append(FORMAL_ISAAC_FINALIZE_PATH)
        isaac_digest = canonical_envelope_set_sha256(
            isaac_service,
            expected_paths=isaac_paths,
        )
        if node2.envelope_set_sha256 != qwen_digest:
            blockers.append("node2 authentication envelope-set digest differs")
        if labserver.envelope_set_sha256 != isaac_digest:
            blockers.append("labserver authentication envelope-set digest differs")
        if replay["wire_cycles_verified"] != 8:
            blockers.append("formal evidence replay did not verify eight cycles")
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, KeyError) as error:
        blockers.append(
            f"formal physical evidence replay failed closed: {type(error).__name__}: {error}"
        )
    return blockers


def _formal_source_unlock_blockers() -> list[str]:
    """List source/governance locks that exist before any physical receipt."""

    blockers: list[str] = []
    if FORMAL_PHYSICAL_RUNNER_BINDING is None:
        blockers.append(
            "formal Qwen-to-Isaac runner is not independently reviewed, "
            "real-Isaac contract-verified, and frozen"
        )
    if FORMAL_DEPLOYMENT_CLOSURE_BINDING is None:
        blockers.append(
            "formal deployment has no frozen implementation commit, container image, "
            "and complete transitive-import closure"
        )
    return blockers


def _load_world_model_bundle(
    root: Path,
    raw: QwenWorldModelBundleReceiptV1,
) -> tuple[dict[str, Any], list[str]]:
    summary: dict[str, Any] = {
        "verified": False,
        "world_model_mainline": True,
        "structured_q012_control_policy_accepted": False,
        "architecture_revision": raw.architecture_revision,
        "model_id": raw.model_id,
        "model_revision": raw.model_revision,
        "head_groups": ["skill", "pointer", "destination"],
    }
    blockers: list[str] = []
    try:
        bundle_root = _resolve_path(root, raw.bundle_root)
        if not bundle_root.is_dir():
            return summary, ["Qwen world-model bundle root is not a directory"]
        bundle_manifest_path = bundle_root / QWEN_BUNDLE_MANIFEST_NAME
        train_report_path = bundle_root / QWEN_TRAIN_REPORT_NAME
        dataset_path = _resolve_path(root, raw.dataset_path)
        dataset_manifest_path = _resolve_path(root, raw.dataset_manifest_path)
        paths = {
            "bundle manifest": (bundle_manifest_path, raw.bundle_manifest_sha256),
            "training report": (train_report_path, raw.train_report_sha256),
            "training dataset": (dataset_path, raw.dataset_sha256),
            "training dataset manifest": (
                dataset_manifest_path,
                raw.dataset_manifest_sha256,
            ),
        }
        for label, (path, expected) in paths.items():
            actual = _sha256(path.read_bytes()) if path.is_file() else None
            if actual != expected:
                blockers.append(f"Qwen {label} SHA-256 mismatch: {actual} != {expected}")

        from m2c.qwen_coarse_v2 import load_bundle

        heads, metadata, manifest = load_bundle(
            bundle_root,
            require_adapter=True,
            expected_model_id=QWEN_MODEL_ID,
            expected_model_revision=QWEN_MODEL_REVISION,
        )
        metadata_payload = metadata.model_dump(mode="json")
        comparisons = {
            "architecture_revision": raw.architecture_revision,
            "model_id": raw.model_id,
            "model_revision": raw.model_revision,
            "failure_context": raw.failure_context,
            "hidden_size": raw.hidden_size,
            "seed": raw.seed,
            "initialization_source": raw.initialization_source,
            "initialization_adapter_sha256": raw.initialization_adapter_sha256,
            "adapter_source_architecture_revision": (raw.adapter_source_architecture_revision),
            "dataset_sha256": raw.dataset_sha256,
            "dataset_manifest_sha256": raw.dataset_manifest_sha256,
            "training_manifest_sha256": raw.training_key_manifest_file_sha256,
            "evaluation_manifest_sha256": raw.evaluation_key_manifest_file_sha256,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "flow_status": "DISABLED",
        }
        for field, expected in comparisons.items():
            if metadata_payload.get(field) != expected:
                blockers.append(f"Qwen world-model metadata {field} mismatch")
        if _canonical_sha256(metadata_payload) != raw.metadata_sha256:
            blockers.append("Qwen world-model metadata SHA-256 mismatch")
        if manifest.status != "TRAINED_QWEN_LORA_THREE_HEADS":
            blockers.append("Qwen bundle is not a trained LoRA plus three-head bundle")
        if manifest.head_checkpoint_sha256 != raw.head_checkpoint_sha256:
            blockers.append("Qwen head checkpoint SHA-256 differs from receipt")
        if manifest.adapter_tree_sha256 != raw.adapter_tree_sha256:
            blockers.append("Qwen adapter tree SHA-256 differs from receipt")
        if canonical_qwen_head_tensor_hashes(heads) != raw.head_tensor_sha256:
            blockers.append("Qwen skill/pointer/destination tensor hashes differ")

        report = _read_json(train_report_path)
        if not isinstance(report, dict):
            blockers.append("Qwen training report is not an object")
        else:
            report_expected = {
                "schema_version": "M2CQwenCoarseV2TrainReportV1",
                "status": "PASS_TRAINED_QWEN_LORA_THREE_HEADS_NOT_PHYSICAL_EVALUATION",
                "model_id": raw.model_id,
                "model_revision": raw.model_revision,
                "failure_context": raw.failure_context,
                "seed": raw.seed,
                "initialization_source": raw.initialization_source,
                "initialization_adapter_sha256": raw.initialization_adapter_sha256,
                "adapter_source_architecture_revision": (raw.adapter_source_architecture_revision),
                "head_checkpoint_sha256": raw.head_checkpoint_sha256,
                "adapter_tree_sha256": raw.adapter_tree_sha256,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "flow_status": "DISABLED",
                "physical_evaluation_executed": False,
            }
            for field, expected in report_expected.items():
                if report.get(field) != expected:
                    blockers.append(f"Qwen training report {field} mismatch")
            if not isinstance(report.get("n_train"), int) or report["n_train"] < 1:
                blockers.append("Qwen training report has no trained samples")
            if not isinstance(report.get("optimizer_steps"), int) or report["optimizer_steps"] < 1:
                blockers.append("Qwen training report has no optimizer steps")
            dataset_report = report.get("dataset_report")
            if not isinstance(dataset_report, dict):
                blockers.append("Qwen training report lacks dataset report")
            else:
                dataset_expected = {
                    "dataset_sha256": raw.dataset_sha256,
                    "dataset_manifest_sha256": raw.dataset_manifest_sha256,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                }
                for field, expected in dataset_expected.items():
                    if dataset_report.get(field) != expected:
                        blockers.append(f"Qwen dataset report {field} mismatch")
                audit = dataset_report.get("key_manifest_audit")
                if not isinstance(audit, dict):
                    blockers.append("Qwen dataset report lacks key-manifest audit")
                else:
                    if (
                        audit.get("training_manifest_sha256")
                        != raw.training_key_manifest_file_sha256
                    ):
                        blockers.append("Qwen dataset report training-key hash mismatch")
                    if (
                        audit.get("evaluation_manifest_sha256")
                        != raw.evaluation_key_manifest_file_sha256
                    ):
                        blockers.append("Qwen dataset report evaluation-key hash mismatch")
                    if audit.get("teacher_used") is not False:
                        blockers.append("Qwen dataset key audit used a Teacher")
                    if audit.get("privileged_truth_policy_input") is not False:
                        blockers.append("Qwen dataset key audit used privileged policy input")
    except (ImportError, OSError, TypeError, ValueError, KeyError) as error:
        blockers.append(f"Qwen world-model bundle failed closed: {type(error).__name__}: {error}")

    blockers = list(dict.fromkeys(blockers))
    summary["verified"] = not blockers
    summary["bundle_root"] = raw.bundle_root
    summary["dataset_sha256"] = raw.dataset_sha256
    summary["dataset_manifest_sha256"] = raw.dataset_manifest_sha256
    summary["head_checkpoint_sha256"] = raw.head_checkpoint_sha256
    summary["adapter_tree_sha256"] = raw.adapter_tree_sha256
    return summary, blockers


def _local_layer(
    root: Path,
    local_receipt_path: Path | None,
    head_commit: str | None,
) -> tuple[dict[str, Any], list[str]]:
    if local_receipt_path is None:
        return (
            {"status": "NOT_PROVIDED", "passed": False, "receipt_path": None},
            ["local ADR section 7 contract-test receipt not provided"],
        )
    try:
        receipt = LocalContractTestReceiptV2.model_validate(_read_json(local_receipt_path))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return (
            {
                "status": "INVALID",
                "passed": False,
                "receipt_path": str(local_receipt_path),
            },
            [f"local test receipt invalid: {type(error).__name__}: {error}"],
        )
    blockers = _implementation_commit_blockers(
        root,
        receipt.checked_implementation_commit,
        head_commit,
    )
    return (
        {
            "status": "PASS" if not blockers else "INVALID",
            "passed": not blockers,
            "receipt_path": str(local_receipt_path),
            "tests_passed": receipt.tests_passed,
            "tests_failed": receipt.tests_failed,
            "tests_skipped": receipt.tests_skipped,
            "evidence_origin": receipt.evidence_origin,
            "checked_implementation_commit": receipt.checked_implementation_commit,
        },
        blockers,
    )


def _physical_layer(
    root: Path,
    physical_receipt_path: Path | None,
    manifest: dict[str, Any] | None,
    head_commit: str | None,
) -> tuple[dict[str, Any], list[str]]:
    if physical_receipt_path is None:
        return (
            {
                "status": "NOT_RUN",
                "passed": False,
                "receipt_path": None,
                "required_model_provenance": "M2C_QWEN_V2_WORLD_MODEL_BUNDLE",
                "world_model_bundle_verified": False,
                "structured_q012_control_policy_accepted": False,
                "synthetic_unit_journal_accepted": False,
            },
            ["real Isaac Qwen-world-model physical integration receipt not provided"],
        )
    try:
        receipt = PhysicalIntegrationReceiptV2.model_validate(_read_json(physical_receipt_path))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        return (
            {
                "status": "INVALID",
                "passed": False,
                "receipt_path": str(physical_receipt_path),
                "required_model_provenance": "M2C_QWEN_V2_WORLD_MODEL_BUNDLE",
                "world_model_bundle_verified": False,
                "structured_q012_control_policy_accepted": False,
                "synthetic_unit_journal_accepted": False,
            },
            [f"physical integration receipt invalid: {type(error).__name__}: {error}"],
        )

    blockers = _implementation_commit_blockers(
        root,
        receipt.checked_implementation_commit,
        head_commit,
    )
    blockers.extend(_external_physical_evidence_blockers(root, receipt))
    smoke_keys = [] if manifest is None else manifest.get("physical_prerequisite_smoke_keys", [])
    matches = [entry for entry in smoke_keys if entry.get("matched_key") == receipt.matched_key]
    if len(matches) != 1:
        blockers.append("physical receipt matched_key is not exactly one frozen SMOKE key")
    else:
        key = matches[0]
        for field in ("scene_seed", "failure_seed", "sdf_sha256", "supervision_sha256"):
            if getattr(receipt, field) != key.get(field):
                blockers.append(f"physical receipt frozen SMOKE {field} mismatch")
        if key.get("role") != "SMOKE" or key.get("split") != "val":
            blockers.append("physical prerequisite key is not frozen SMOKE/val")

    validation = validate_model_owned_chain_episode(receipt.episode)
    if not validation.strict_pure_model_success:
        blockers.extend(f"physical chain: {reason}" for reason in validation.exclusion_reasons)
    if validation.decisions_observed != len(EXPECTED_PATH_BLOCKED_CHAIN):
        blockers.append("physical chain does not contain exactly eight decisions")
    if validation.physical_receipts_observed != len(EXPECTED_PATH_BLOCKED_CHAIN):
        blockers.append("physical chain does not contain eight physical receipts")

    bundle_summary, bundle_blockers = _load_world_model_bundle(
        root,
        receipt.world_model_bundle,
    )
    blockers.extend(bundle_blockers)
    blockers = list(dict.fromkeys(blockers))
    return (
        {
            "status": "PASS" if not blockers else "INVALID",
            "passed": not blockers,
            "receipt_path": str(physical_receipt_path),
            "evidence_origin": receipt.evidence_origin,
            "execution_mode": receipt.execution_mode,
            "test_model_provenance": receipt.test_model_provenance,
            "checked_implementation_commit": receipt.checked_implementation_commit,
            "matched_key": receipt.matched_key,
            "episode_id": receipt.episode.episode_id,
            "decisions_observed": validation.decisions_observed,
            "physical_receipts_observed": validation.physical_receipts_observed,
            "fresh_observations_observed": len(
                {item.observation.observation_id for item in receipt.episode.decisions}
            ),
            "strict_pure_model_success": validation.strict_pure_model_success,
            "world_model_bundle_verified": bundle_summary["verified"],
            "world_model_bundle": bundle_summary,
            "structured_q012_control_policy_accepted": False,
            "synthetic_unit_journal_accepted": False,
        },
        blockers,
    )


def _frozen_manifest_blockers(
    path: Path,
    *,
    expected_schema: str,
    expected_content_sha256: str,
    label: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return None, [f"{label} is not valid JSON"]
    blockers: list[str] = []
    if manifest.get("schema_version") != expected_schema:
        blockers.append(f"{label} schema changed")
    if manifest.get("manifest_sha256") != expected_content_sha256:
        blockers.append(f"{label} content digest mismatch")
    if manifest.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION":
        blockers.append(f"{label} was not frozen before execution")
    if manifest.get("teacher_used") is not False:
        blockers.append(f"{label} uses a Teacher")
    if manifest.get("privileged_truth_policy_input") is not False:
        blockers.append(f"{label} permits privileged policy input")
    return manifest, blockers


def evaluate_s4_entry_gate(
    root: Path,
    *,
    local_receipt_path: Path | None = None,
    physical_receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate local and physical layers without executing tests or rollouts."""

    root = root.resolve()
    governance = evaluate_qb_adr_gate(root)
    head_commit = governance.get("checked_head_commit")
    governance_blockers = [str(item) for item in governance.get("blockers", [])]
    file_matches, binding_blockers = _file_binding_checks(root)
    commit_blockers = [
        f"frozen commit cannot be resolved: {commit}"
        for commit in (ADR_IMPLEMENTATION_COMMIT, FROZEN_KEY_MANIFEST_COMMIT)
        if not _git_commit_exists(root, commit)
    ]
    if not commit_blockers:
        if not _git_is_ancestor(root, ADR_IMPLEMENTATION_COMMIT, FROZEN_KEY_MANIFEST_COMMIT):
            commit_blockers.append("ADR implementation commit does not predate frozen S4/S6 keys")
        if not isinstance(head_commit, str) or not _git_is_ancestor(
            root,
            FROZEN_KEY_MANIFEST_COMMIT,
            head_commit,
        ):
            commit_blockers.append("frozen S4/S6 key commit is not an ancestor of report HEAD")

    training_manifest, training_manifest_blockers = _frozen_manifest_blockers(
        root / FROZEN_KEY_MANIFEST_PATH,
        expected_schema="M2CS4TrainingAndSmokeKeyManifestV1",
        expected_content_sha256=FROZEN_KEY_MANIFEST_CONTENT_SHA256,
        label="frozen S4 key manifest",
    )
    _, evaluation_manifest_blockers = _frozen_manifest_blockers(
        root / FROZEN_EVALUATION_MANIFEST_PATH,
        expected_schema="M2CS6FrozenEvaluationKeyManifestV1",
        expected_content_sha256=FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256,
        label="frozen S6 evaluation manifest",
    )

    local, local_blockers = _local_layer(root, local_receipt_path, head_commit)
    physical, physical_blockers = _physical_layer(
        root,
        physical_receipt_path,
        training_manifest,
        head_commit,
    )
    source_unlock_blockers = _formal_source_unlock_blockers()
    static_blockers = list(
        dict.fromkeys(
            [
                *governance_blockers,
                *binding_blockers,
                *commit_blockers,
                *training_manifest_blockers,
                *evaluation_manifest_blockers,
            ]
        )
    )
    local_contract_tests_passed = bool(local["passed"]) and not static_blockers
    physical_integration_receipt_passed = bool(physical["passed"]) and not static_blockers
    formal_evaluation_authorized = (
        governance.get("q_b_authorized") is True
        and local_contract_tests_passed
        and physical_integration_receipt_passed
    )
    blockers = list(
        dict.fromkeys(
            [
                *static_blockers,
                *local_blockers,
                *source_unlock_blockers,
                *physical_blockers,
            ]
        )
    )
    if not formal_evaluation_authorized:
        blockers.append("formal Q-B evaluation is blocked until every ADR section 7 layer passes")

    training_authorized_by_adr = governance.get("q_b_authorized") is True and not static_blockers
    return {
        "schema_version": "M2CS4EntryGateReportV2",
        "status": (
            "PASS_FORMAL_Q_B_EVALUATION_ENTRY"
            if formal_evaluation_authorized
            else "BLOCKED_FORMAL_Q_B_EVALUATION"
        ),
        "checked_head_commit": head_commit,
        "frozen_commits": {
            "adr_implementation": ADR_IMPLEMENTATION_COMMIT,
            "s4_s6_key_manifest": FROZEN_KEY_MANIFEST_COMMIT,
        },
        "frozen_bindings": {
            "matches": file_matches,
            "training_key_manifest_file_sha256": FROZEN_KEY_MANIFEST_FILE_SHA256,
            "training_key_manifest_content_sha256": FROZEN_KEY_MANIFEST_CONTENT_SHA256,
            "evaluation_key_manifest_file_sha256": (FROZEN_EVALUATION_MANIFEST_FILE_SHA256),
            "evaluation_key_manifest_content_sha256": (FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256),
            "wire_challenge_manifest_path": FROZEN_WIRE_CHALLENGE_MANIFEST_PATH,
            "wire_challenge_manifest_file_sha256": (FROZEN_WIRE_CHALLENGE_MANIFEST_FILE_SHA256),
            "runtime_binding_sha256": RUNTIME_BINDINGS,
            "b0_freeze_sha256": B0_FREEZE_SHA256,
        },
        "required_physical_model_provenance": "M2C_QWEN_V2_WORLD_MODEL_BUNDLE",
        "world_model_mainline_required": True,
        "structured_q012_checkpoint_accepted_as_world_model": False,
        "governance_gate_passed": governance.get("q_b_authorized") is True,
        "local_contract_tests": local,
        "physical_integration": physical,
        "local_contract_tests_passed": local_contract_tests_passed,
        "physical_integration_receipt_passed": physical_integration_receipt_passed,
        "training_authorized_by_adr": training_authorized_by_adr,
        "training_requires_physical_integration_receipt": False,
        "training_scope": (
            "ADR-0020 section 5 authorized, leakage-audited S3/TRAIN labels only; "
            "SMOKE and S6 keys remain excluded. This gate does not run training."
        ),
        "formal_q_b_evaluation_authorized": formal_evaluation_authorized,
        "q_b_training_executed_by_this_gate": False,
        "q_b_evaluation_executed_by_this_gate": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "synthetic_unit_journal_accepted_as_physical": False,
        "blockers": blockers,
        "next_command": (
            "invoke the separately reviewed formal Q-B evaluator"
            if formal_evaluation_authorized
            else (
                "obtain human ADR direction for the frozen K=8 public-input "
                "admissibility blocker before collecting training data; after a "
                "compliant trained bundle and real-Isaac contract startup exist, "
                "collect one frozen-SMOKE-key receipt and rerun make "
                "m2c-s4-entry-gate"
            )
        ),
    }
