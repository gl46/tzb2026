#!/usr/bin/env python3
"""Serve a trained M2C_Q012_V4 bundle on the versioned formal endpoint.

Startup verifies the complete V4 bundle, the materialized offline base-model
snapshot, and the host-local HMAC key before publishing a create-only runtime
binding.  Each request is revalidated against the full replayed public V4
observation and is durably journaled before its response is released.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
from typing import Any, Callable, Mapping
import uuid

import numpy as np

from m2c.qwen_coarse_v2 import sha256_tree
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
from m2c.serve_qwen_coarse_v2 import _resolve_materialized_model_snapshot
from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    QWEN_MODEL_ID,
    QWEN_MODEL_REVISION,
    canonical_json_bytes,
    canonical_sha256,
    named_array_sha256,
    qwen_head_tensor_sha256,
    read_hmac_secret,
)
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    ADR0026_DECISION_BUNDLE_CONTRACT_V4,
    BUNDLE_CONTRACT_CHOICES_V4,
    EPISODE_ATOMIC_BUNDLE_CONTRACT_V4,
    FORMAL_INFERENCE_PATH_V4,
    FORMAL_WIRE_PROTOCOL_V4,
    FormalInferenceRequestV4,
    FormalInferenceResponseV4,
    QwenBundleRuntimeBindingV4,
    build_inference_response_from_logits_v4,
    runtime_qwen_prompt_v4,
    sign_inference_response_v4,
    validate_inference_response_binding_v4,
    verify_inference_request_v4,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
FormalLoadedQwenBundleV4 = LoadedM2CQwenCoarseV4Bundle | LoadedADR0026DecisionBundleV4


def _sha256_argument(raw: str) -> str:
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise argparse.ArgumentTypeError("expected one lowercase SHA-256 digest")
    return raw


@dataclass
class RuntimeV4:
    binding: QwenBundleRuntimeBindingV4
    bundle: FormalLoadedQwenBundleV4
    backbone: Qwen35Backbone
    head_hashes: dict[str, str]
    secret: bytes
    inference_lock: threading.Lock


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_mode & 0o022
        ):
            raise PermissionError("formal V4 runtime file identity/permissions are unsafe")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise RuntimeError("formal V4 runtime file changed while read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _create_only_file(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError("formal V4 output parent must pre-exist as a real directory")
    parent = path.parent.stat(follow_symlinks=False)
    if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise PermissionError("formal V4 output parent permissions are unsafe")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("formal V4 create-only write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class AppendOnlyQwenAuditLogV4:
    """Persistent-FD, create-only canonical audit for one V4 service."""

    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise ValueError("formal V4 Qwen audit root may not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        metadata = root.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
        ):
            raise PermissionError("formal V4 Qwen audit root permissions are unsafe")
        self.root = root
        self.service_id = uuid.uuid4().hex
        self.service_path = root / f"qwen-v4-service-{self.service_id}.jsonl"
        flags = (
            os.O_WRONLY
            | os.O_APPEND
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        self._descriptor = os.open(self.service_path, flags, 0o600)
        self._identity = self._descriptor_identity()
        self._lock = threading.RLock()
        self._sequence = 0
        self._stopped = False
        os.fsync(self._descriptor)
        directory = os.open(
            root,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        self.append(
            "SERVICE_STARTED",
            {
                "service_id": self.service_id,
                "path": FORMAL_INFERENCE_PATH_V4,
                "protocol": FORMAL_WIRE_PROTOCOL_V4,
                "architecture_revision": "M2C_Q012_V4",
                "expected_decisions": 8,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
        )

    def _descriptor_identity(self) -> tuple[int, int, int, int, int]:
        metadata = os.fstat(self._descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_nlink != 1
        ):
            raise PermissionError("formal V4 Qwen audit descriptor identity changed")
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_uid,
            metadata.st_mode & 0o777,
            metadata.st_nlink,
        )

    def _path_identity(self) -> tuple[int, int, int, int, int]:
        metadata = self.service_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("formal V4 Qwen audit path is no longer a regular file")
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_uid,
            metadata.st_mode & 0o777,
            metadata.st_nlink,
        )

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("formal V4 Qwen audit append made no progress")
            view = view[written:]

    def append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("formal V4 Qwen audit is stopped")
            record = {
                "schema_version": "FormalQwenAuditEventV4",
                "sequence": self._sequence + 1,
                "recorded_at_ns": time.time_ns(),
                "event_type": event_type,
                "payload": dict(payload),
            }
            if (
                self._descriptor_identity() != self._identity
                or self._path_identity() != self._identity
            ):
                raise RuntimeError("formal V4 Qwen audit descriptor identity changed")
            self._write_all(self._descriptor, canonical_json_bytes(record) + b"\n")
            os.fsync(self._descriptor)
            self._sequence += 1

    def stop(self, payload: Mapping[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                return
            self.append("SERVICE_STOPPED", payload)
            self._stopped = True
            os.close(self._descriptor)


class FormalQwenServiceSessionV4:
    """Serialize exactly eight authenticated V4 model decisions."""

    def __init__(
        self,
        *,
        runtime: RuntimeV4,
        audit: AppendOnlyQwenAuditLogV4,
        predictor: Callable[[RuntimeV4, FormalInferenceRequestV4], FormalInferenceResponseV4]
        | None = None,
    ) -> None:
        self.runtime = runtime
        self.audit = audit
        self._predictor = predictor or predict
        self._lock = threading.Lock()
        self.run_id: str | None = None
        self.challenge_nonce: str | None = None
        self.next_decision_index = 0
        self.responses_committed = 0
        self.last_captured_at_ns: int | None = None
        self.seen_observation_ids: set[str] = set()
        self.seen_capture_receipts: set[str] = set()
        self.last_request_history: tuple[PublicExecutedIntentHistoryItemV2, ...] = ()
        self.last_response: FormalInferenceResponseV4 | None = None
        self.completed = False
        self.poisoned = False
        self.rejections_recorded = 0
        self.stopped = False

    def handle(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            try:
                self.audit.append(
                    "WIRE_REQUEST_RECEIVED",
                    {"path": FORMAL_INFERENCE_PATH_V4, "signed_wire": dict(raw)},
                )
                require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
                if self.poisoned:
                    raise RuntimeError("formal V4 Qwen session is poisoned")
                if self.completed:
                    raise RuntimeError("formal V4 Qwen session already committed eight responses")
                signed = verify_inference_request_v4(raw, self.runtime.secret)
                request = signed.payload
                if request.bundle != self.runtime.binding:
                    raise ValueError("formal V4 Qwen request differs from loaded runtime binding")
                if request.decision_index != self.next_decision_index:
                    raise ValueError("formal V4 Qwen decision index is not exact 0..7")
                if self.run_id is None:
                    if request.decision_index != 0:
                        raise ValueError("formal V4 Qwen first decision must be zero")
                    self.run_id = request.run_id
                    self.challenge_nonce = request.challenge_nonce
                elif request.run_id != self.run_id:
                    raise ValueError("formal V4 Qwen request crossed run_id")
                elif request.challenge_nonce != self.challenge_nonce:
                    raise ValueError("formal V4 Qwen request crossed challenge nonce")
                observation = request.observation
                if (
                    observation.observation_id in self.seen_observation_ids
                    or observation.capture_receipt_sha256 in self.seen_capture_receipts
                ):
                    raise ValueError("formal V4 Qwen request reuses a public capture")
                if self.last_captured_at_ns is not None and (
                    observation.captured_at_ns <= self.last_captured_at_ns
                    or observation.previous_physical_completed_at_ns <= self.last_captured_at_ns
                ):
                    raise ValueError("formal V4 Qwen request is not fresh after prior execution")
                history = tuple(request.executed_intent_history)
                if request.decision_index == 0:
                    if history or self.last_response is not None:
                        raise ValueError("formal V4 first request contains prior execution history")
                else:
                    if self.last_response is None or history[:-1] != self.last_request_history:
                        raise ValueError("formal V4 executed history does not extend exact prefix")
                    latest = history[-1]
                    prior_intent = self.last_response.intent
                    if (
                        latest.decision_index != self.last_response.decision_index
                        or latest.selected_skill != prior_intent.skill_type
                        or latest.target_track_id != prior_intent.target_track_id
                        or latest.destination_cell != prior_intent.destination_cell
                    ):
                        raise ValueError(
                            "formal V4 executed history differs from prior model response"
                        )
                response_payload = self._predictor(self.runtime, request)
                validate_inference_response_binding_v4(request, response_payload)
                if response_payload.request_payload_sha256 != signed.payload_sha256:
                    raise ValueError("formal V4 Qwen response differs from signed request")
                response = sign_inference_response_v4(response_payload, self.runtime.secret)
                dumped = response.model_dump(mode="json")
                self.audit.append(
                    "WIRE_RESPONSE_COMMITTED",
                    {"path": FORMAL_INFERENCE_PATH_V4, "signed_wire": dumped},
                )
                self.responses_committed += 1
                self.next_decision_index += 1
                self.last_captured_at_ns = observation.captured_at_ns
                self.seen_observation_ids.add(observation.observation_id)
                self.seen_capture_receipts.add(observation.capture_receipt_sha256)
                self.last_request_history = history
                self.last_response = response_payload
                if self.responses_committed == 8:
                    self.audit.append(
                        "SERVICE_COMPLETED",
                        {
                            "service_id": self.audit.service_id,
                            "run_id": self.run_id,
                            "protocol": FORMAL_WIRE_PROTOCOL_V4,
                            "responses_committed": 8,
                            "formal_evidence_complete": True,
                        },
                    )
                    self.completed = True
                return dumped
            except Exception as exc:
                self.poisoned = True
                self.rejections_recorded += 1
                try:
                    self.audit.append(
                        "WIRE_REQUEST_REJECTED",
                        {
                            "path": FORMAL_INFERENCE_PATH_V4,
                            "error_type": type(exc).__name__,
                            "formal_evidence_accepted": False,
                        },
                    )
                except Exception:
                    pass
                raise

    def reject_transport(self, *, path: str, error_type: str) -> None:
        with self._lock:
            self.poisoned = True
            self.rejections_recorded += 1
            self.audit.append(
                "WIRE_REQUEST_REJECTED",
                {
                    "path": path,
                    "error_type": error_type,
                    "formal_evidence_accepted": False,
                },
            )

    def stop(self) -> None:
        with self._lock:
            if self.stopped:
                return
            payload = {
                "service_id": self.audit.service_id,
                "run_id": self.run_id,
                "protocol": FORMAL_WIRE_PROTOCOL_V4,
                "responses_committed": self.responses_committed,
                "completed": self.completed,
                "poisoned": self.poisoned,
                "rejections_recorded": self.rejections_recorded,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            self.audit.stop(payload)
            self.stopped = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C Qwen V4 formal inference endpoint")
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", type=_sha256_argument, required=True)
    parser.add_argument(
        "--bundle-contract",
        choices=BUNDLE_CONTRACT_CHOICES_V4,
        default=EPISODE_ATOMIC_BUNDLE_CONTRACT_V4,
    )
    parser.add_argument("--model-id", default=QWEN_MODEL_ID, choices=(QWEN_MODEL_ID,))
    parser.add_argument("--revision", default=QWEN_MODEL_REVISION, choices=(QWEN_MODEL_REVISION,))
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--cache-tree-sha256", type=_sha256_argument, required=True)
    parser.add_argument("--association-deployment-sha256", type=_sha256_argument, required=True)
    parser.add_argument(
        "--capture-source-implementation-sha256",
        type=_sha256_argument,
        required=True,
    )
    parser.add_argument(
        "--declared-attribute-selector-implementation-sha256",
        type=_sha256_argument,
        required=True,
    )
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--binding-output", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--max-request-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--startup-check-only", action="store_true")
    return parser.parse_args(argv)


def _binding_from_verified_bundle_v4(
    args: argparse.Namespace,
    *,
    loaded: FormalLoadedQwenBundleV4,
    model_snapshot: Path,
    bundle_manifest_raw: bytes,
    bundle_tree_sha256: str,
) -> QwenBundleRuntimeBindingV4:
    manifest = loaded.manifest
    bundle_contract = getattr(
        args,
        "bundle_contract",
        EPISODE_ATOMIC_BUNDLE_CONTRACT_V4,
    )
    decision_contract = manifest.schema_version == "M2CQwenADR0026DecisionBundleManifestV1"
    if decision_contract != (bundle_contract == ADR0026_DECISION_BUNDLE_CONTRACT_V4):
        raise ValueError("V4 bundle schema differs from the explicit runtime contract")
    if manifest.model_id != args.model_id or manifest.model_revision != args.revision:
        raise ValueError("V4 bundle base model differs from formal service")
    if manifest.bundle_sha256 != args.expected_bundle_sha256:
        raise ValueError("V4 bundle canonical digest differs from CLI binding")
    actual_cache_sha = sha256_tree(model_snapshot)
    if actual_cache_sha != args.cache_tree_sha256:
        raise ValueError("V4 offline model cache tree differs from CLI binding")
    if manifest.base_model_snapshot_tree_sha256 != actual_cache_sha:
        raise ValueError("V4 trained bundle used a different base-model snapshot")
    if qwen_head_tensor_sha256(loaded.heads).keys() != {
        "skill_w",
        "skill_b",
        "pointer_w",
        "pointer_b",
        "destination_w",
        "destination_b",
    }:
        raise ValueError("V4 runtime did not load the exact three heads")
    if decision_contract:
        training_manifest_file_sha256 = manifest.training_dataset_manifest_file_sha256
        training_manifest_sha256 = manifest.training_dataset_manifest_sha256
        training_dataset_report_file_sha256 = manifest.training_dataset_report_file_sha256
        training_dataset_report_sha256 = manifest.training_dataset_report_sha256
        source_training_manifests = tuple(
            item.model_dump(mode="json") for item in manifest.source_training_manifests
        )
    else:
        training_manifest_file_sha256 = manifest.training_manifest_file_sha256
        training_manifest_sha256 = manifest.training_manifest_sha256
        training_dataset_report_file_sha256 = None
        training_dataset_report_sha256 = None
        source_training_manifests = ()
    return QwenBundleRuntimeBindingV4(
        bundle_manifest_schema_version=manifest.schema_version,
        training_contract_revision=bundle_contract,
        bundle_manifest_file_sha256=hashlib.sha256(bundle_manifest_raw).hexdigest(),
        bundle_tree_sha256=bundle_tree_sha256,
        bundle_sha256=manifest.bundle_sha256,
        head_checkpoint_sha256=manifest.head_checkpoint_sha256,
        head_deployment_file_sha256=manifest.head_deployment_file_sha256,
        head_deployment_manifest_sha256=(manifest.head_deployment.deployment_manifest_sha256),
        checkpoint_binding_sha256=manifest.head_deployment.checkpoint_binding_sha256,
        adapter_tree_sha256=manifest.adapter_tree_sha256,
        training_dataset_sha256=manifest.training_dataset_sha256,
        training_manifest_file_sha256=training_manifest_file_sha256,
        training_manifest_sha256=training_manifest_sha256,
        training_dataset_report_file_sha256=training_dataset_report_file_sha256,
        training_dataset_report_sha256=training_dataset_report_sha256,
        source_training_manifests=source_training_manifests,
        s6_manifest_file_sha256=manifest.s6_manifest_file_sha256,
        s6_manifest_sha256=manifest.s6_manifest_sha256,
        association_deployment_sha256=args.association_deployment_sha256,
        capture_source_implementation_sha256=args.capture_source_implementation_sha256,
        declared_attribute_selector_implementation_sha256=(
            args.declared_attribute_selector_implementation_sha256
        ),
        model_cache_dir=str(model_snapshot),
        model_cache_tree_sha256=actual_cache_sha,
        failure_context=manifest.failure_context,
    )


def load_runtime(args: argparse.Namespace) -> RuntimeV4:
    if args.model_id != QWEN_MODEL_ID or args.revision != QWEN_MODEL_REVISION:
        raise ValueError("formal V4 service requires the canonical Qwen revision")
    if not args.local_files_only:
        raise ValueError("formal V4 inference must be local-files-only")
    decision_contract = args.bundle_contract == ADR0026_DECISION_BUNDLE_CONTRACT_V4
    manifest_path = args.bundle_root / (
        DECISION_BUNDLE_MANIFEST_NAME if decision_contract else BUNDLE_MANIFEST_NAME
    )
    manifest_before = _read_regular_file_once(manifest_path)
    tree_before = sha256_tree_v4(args.bundle_root)
    if decision_contract:
        loaded = load_adr0026_decision_bundle_v4(
            args.bundle_root,
            expected_bundle_sha256=args.expected_bundle_sha256,
        )
    else:
        loaded = load_bundle_v4(
            args.bundle_root,
            expected_bundle_sha256=args.expected_bundle_sha256,
        )
    manifest_after = _read_regular_file_once(manifest_path)
    tree_after = sha256_tree_v4(args.bundle_root)
    if manifest_before != manifest_after or tree_before != tree_after:
        raise RuntimeError("V4 bundle tree changed while runtime loaded it")
    model_snapshot = _resolve_materialized_model_snapshot(args.cache_dir)
    binding = _binding_from_verified_bundle_v4(
        args,
        loaded=loaded,
        model_snapshot=model_snapshot,
        bundle_manifest_raw=manifest_before,
        bundle_tree_sha256=tree_before,
    )
    backbone = Qwen35Backbone(
        model_id=args.model_id,
        revision=args.revision,
        device=args.device,
        dtype=args.dtype,
        cache_dir=str(args.cache_dir),
        local_files_only=True,
        resolved_model_path=str(model_snapshot),
    )
    backbone.load_adapter(args.bundle_root / "adapter")
    if sha256_tree_v4(args.bundle_root) != binding.bundle_tree_sha256:
        raise ValueError("V4 bundle bytes changed while backbone loaded the adapter")
    if _resolve_materialized_model_snapshot(args.cache_dir) != model_snapshot:
        raise ValueError("V4 model snapshot path changed while runtime loaded")
    if sha256_tree(model_snapshot) != binding.model_cache_tree_sha256:
        raise ValueError("V4 model snapshot bytes changed while runtime loaded")
    return RuntimeV4(
        binding=binding,
        bundle=loaded,
        backbone=backbone,
        head_hashes=qwen_head_tensor_sha256(loaded.heads),
        secret=read_hmac_secret(args.hmac_key_file),
        inference_lock=threading.Lock(),
    )


def predict(runtime: RuntimeV4, request: FormalInferenceRequestV4) -> FormalInferenceResponseV4:
    if request.bundle != runtime.binding:
        raise ValueError("V4 inference request bundle differs from loaded runtime")
    from PIL import Image

    image = Image.open(io.BytesIO(request.observation.rgb.decoded())).convert("RGB")
    depth = np.load(io.BytesIO(request.observation.depth.decoded()), allow_pickle=False)
    if not isinstance(depth, np.ndarray):
        depth.close()
        raise ValueError("formal V4 depth must be one ndarray")
    if depth.size == 0 or not np.isfinite(depth).all():
        raise ValueError("formal V4 depth is empty or non-finite")
    prompt = runtime_qwen_prompt_v4(request)
    with runtime.inference_lock:
        features = (
            runtime.backbone.encode_multimodal({"texts": [prompt], "images": [image]})
            .pooled.detach()
            .cpu()
            .float()
            .numpy()[0]
        )
        skill, pointer, destination = runtime.bundle.heads.logits(
            features,
            request.observation.observation.candidate_payload.valid_mask,
        )
    completed_at_ns = max(time.time_ns(), request.sent_at_ns + 1)
    return build_inference_response_from_logits_v4(
        request,
        skill_logits=skill,
        pointer_logits=pointer,
        destination_logits=destination,
        prompt_sha256=canonical_sha256(prompt),
        pooled_feature_sha256=named_array_sha256("qwen_v4_pooled_feature", features),
        head_tensor_sha256=runtime.head_hashes,
        completed_at_ns=completed_at_ns,
    )


def serve(runtime: RuntimeV4, args: argparse.Namespace, audit: AppendOnlyQwenAuditLogV4) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    session = FormalQwenServiceSessionV4(runtime=runtime, audit=audit)
    server_holder: dict[str, ThreadingHTTPServer] = {}

    class Handler(BaseHTTPRequestHandler):
        server_version = "M2CQwenFormalV4"

        def log_message(self, format: str, *values: object) -> None:
            print(
                json.dumps(
                    {"event": "HTTP", "message": format % values, "time_ns": time.time_ns()},
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )

        def do_POST(self) -> None:  # noqa: N802
            raw: object = None
            if self.path != FORMAL_INFERENCE_PATH_V4:
                try:
                    session.reject_transport(path=self.path, error_type="UnknownEndpoint")
                except Exception:
                    pass
                self.send_error(404)
                return
            try:
                require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= args.max_request_bytes:
                    raise ValueError("formal V4 request size is invalid")
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError("formal V4 request must be one JSON object")
                response = session.handle(raw)
                payload = canonical_json_bytes(response)
            except Exception as exc:
                if not isinstance(raw, dict):
                    try:
                        session.reject_transport(path=self.path, error_type=type(exc).__name__)
                    except Exception:
                        pass
                payload = json.dumps(
                    {"error": type(exc).__name__, "status": "REJECTED"},
                    sort_keys=True,
                ).encode("utf-8")
                self.send_response(422)
            else:
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()
            if self.path == FORMAL_INFERENCE_PATH_V4 and session.completed:
                threading.Thread(
                    target=server_holder["server"].shutdown,
                    name="m2c-qwen-v4-graceful-stop",
                    daemon=True,
                ).start()

    server = ThreadingHTTPServer((args.bind_host, args.port), Handler)
    server_holder["server"] = server
    print(
        json.dumps(
            {
                "status": "READY_REAL_QWEN_V4_INFERENCE",
                "endpoint": FORMAL_INFERENCE_PATH_V4,
                "audit_service_path": str(audit.service_path),
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        session.stop()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_pre_freeze(M2CExperimentAction.FORMAL_MODEL_SERVICE)
    runtime = load_runtime(args)
    binding_bytes = (
        json.dumps(runtime.binding.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _create_only_file(args.binding_output, binding_bytes)
    audit = AppendOnlyQwenAuditLogV4(args.audit_dir)
    if args.startup_check_only:
        audit.stop(
            {
                "service_id": audit.service_id,
                "run_id": None,
                "protocol": FORMAL_WIRE_PROTOCOL_V4,
                "responses_committed": 0,
                "completed": False,
                "poisoned": False,
                "rejections_recorded": 0,
                "startup_check_only": True,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        )
        print(
            json.dumps(
                {
                    "status": "READY_REAL_QWEN_V4_INFERENCE",
                    "endpoint": FORMAL_INFERENCE_PATH_V4,
                    "audit_service_path": str(audit.service_path),
                    "binding": runtime.binding.model_dump(mode="json"),
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    serve(runtime, args, audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
