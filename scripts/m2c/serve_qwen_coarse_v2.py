#!/usr/bin/env python3
"""Serve the trained M2C Qwen V2 world model on a hash-bound private endpoint.

This is a real inference service: startup loads a trained LoRA adapter and all
three M2C heads, verifies the explicit offline cache tree, then performs one
temperature-zero prediction per authenticated request.  It does not expose a
Teacher, structured-policy substitute, scripted chain, or physical executor.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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

from m2c.qwen_coarse_v2 import (
    BUNDLE_MANIFEST_NAME,
    load_bundle,
    sha256_file,
    sha256_tree,
)
from m2c.qwen_coarse_v2 import qwen_coarse_v2_prompt
from m2c.train_qwen_coarse_v2 import _resolve_local_revision_snapshot
from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FORMAL_INFERENCE_PATH,
    QWEN_ARCHITECTURE_REVISION,
    QWEN_MODEL_ID,
    QWEN_MODEL_REVISION,
    FormalInferenceRequestV2,
    FormalInferenceResponseV2,
    QwenBundleRuntimeBindingV2,
    build_inference_response_from_logits,
    canonical_json_bytes,
    canonical_sha256,
    named_array_sha256,
    qwen_head_tensor_sha256,
    read_hmac_secret,
    sign_inference_response,
    verify_inference_request,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import canonical_track_slots
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)


@dataclass
class Runtime:
    binding: QwenBundleRuntimeBindingV2
    heads: Any
    metadata: Any
    backbone: Qwen35Backbone
    head_hashes: dict[str, str]
    secret: bytes
    inference_lock: threading.Lock


class AppendOnlyQwenAuditLogV2:
    """Create-only, durable canonical journal for one Qwen service process."""

    def __init__(self, root: Path) -> None:
        if root.is_symlink():
            raise ValueError("formal Qwen audit root may not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir() or root.is_symlink():
            raise NotADirectoryError(root)
        root_metadata = root.stat()
        if (
            root_metadata.st_uid != os.geteuid()
            or root_metadata.st_mode & 0o022
            or not stat.S_ISDIR(root_metadata.st_mode)
        ):
            raise PermissionError(
                "formal Qwen audit root must be current-user and not group/world writable"
            )
        self.root = root
        self.service_id = uuid.uuid4().hex
        self.service_path = root / f"qwen-service-{self.service_id}.jsonl"
        self._lock = threading.Lock()
        self._sequence = 0
        self._stopped = False
        self._descriptor = self._create_exclusive(self.service_path)
        self._identity = self._descriptor_identity()
        self.append(
            "SERVICE_STARTED",
            {
                "service_id": self.service_id,
                "path": FORMAL_INFERENCE_PATH,
                "expected_decisions": 8,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
        )

    @staticmethod
    def _open_flags(base: int) -> int:
        flags = base
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        return flags

    @classmethod
    def _create_exclusive(cls, path: Path) -> int:
        descriptor = os.open(
            path,
            cls._open_flags(os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL),
            0o600,
        )
        os.fsync(descriptor)
        directory = os.open(path.parent, cls._open_flags(os.O_RDONLY))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return descriptor

    def _descriptor_identity(self) -> tuple[int, int, int, int, int]:
        metadata = os.fstat(self._descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or metadata.st_nlink != 1
        ):
            raise PermissionError("formal Qwen audit file identity/permissions changed")
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
                raise OSError("formal Qwen audit append made no progress")
            view = view[written:]

    def append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("formal Qwen audit is already stopped")
            sequence = self._sequence + 1
            record = {
                "schema_version": "FormalQwenAuditEventV2",
                "sequence": sequence,
                "recorded_at_ns": time.time_ns(),
                "event_type": event_type,
                "payload": dict(payload),
            }
            line = canonical_json_bytes(record) + b"\n"
            if self._descriptor_identity() != self._identity:
                raise RuntimeError("formal Qwen audit descriptor identity changed")
            self._write_all(self._descriptor, line)
            os.fsync(self._descriptor)
            self._sequence = sequence

    def stop(self, payload: Mapping[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                return
        self.append("SERVICE_STOPPED", payload)
        with self._lock:
            self._stopped = True
            os.close(self._descriptor)


class FormalQwenServiceSessionV2:
    """Serialize and durably attest one exact eight-decision model run."""

    def __init__(
        self,
        *,
        runtime: Runtime,
        audit: AppendOnlyQwenAuditLogV2,
        predictor: Callable[[Runtime, FormalInferenceRequestV2], FormalInferenceResponseV2]
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
        self.completed = False
        self.poisoned = False
        self.rejections_recorded = 0
        self.stopped = False

    def handle(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Verify, infer, sign and journal one request before releasing it."""

        with self._lock:
            try:
                # Preserve the exact received envelope before any validation.
                self.audit.append(
                    "WIRE_REQUEST_RECEIVED",
                    {"path": FORMAL_INFERENCE_PATH, "signed_wire": dict(raw)},
                )
                # A service created before the cutoff may not infer after it.
                require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
                if self.poisoned:
                    raise RuntimeError("formal Qwen session is poisoned after a rejection")
                if self.completed:
                    raise RuntimeError("formal Qwen session already committed eight responses")
                signed = verify_inference_request(raw, self.runtime.secret)
                request = signed.payload
                if request.decision_index != self.next_decision_index:
                    raise ValueError("formal Qwen decision index is not the exact 0..7 sequence")
                if self.run_id is None:
                    if request.decision_index != 0:
                        raise ValueError("formal Qwen first decision must be zero")
                    self.run_id = request.run_id
                    self.challenge_nonce = request.challenge_nonce
                elif request.run_id != self.run_id:
                    raise ValueError("formal Qwen request crossed the locked run_id")
                elif request.challenge_nonce != self.challenge_nonce:
                    raise ValueError("formal Qwen request crossed the locked challenge nonce")
                response_payload = self._predictor(self.runtime, request)
                if (
                    response_payload.run_id != request.run_id
                    or response_payload.request_id != request.request_id
                    or response_payload.decision_index != request.decision_index
                    or response_payload.request_payload_sha256 != signed.payload_sha256
                    or response_payload.bundle != self.runtime.binding
                ):
                    raise ValueError("formal Qwen response is not bound to the active request")
                response = sign_inference_response(response_payload, self.runtime.secret)
                dumped = response.model_dump(mode="json")
                # The complete signed response is fsync'd before HTTP can expose it.
                self.audit.append(
                    "WIRE_RESPONSE_COMMITTED",
                    {"path": FORMAL_INFERENCE_PATH, "signed_wire": dumped},
                )
                self.responses_committed += 1
                self.next_decision_index += 1
                if self.responses_committed == 8:
                    self.audit.append(
                        "SERVICE_COMPLETED",
                        {
                            "service_id": self.audit.service_id,
                            "run_id": self.run_id,
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
                    # Do not duplicate assets or exception strings outside the
                    # already journaled signed envelope; never persist secrets.
                    self.audit.append(
                        "WIRE_REQUEST_REJECTED",
                        {
                            "path": FORMAL_INFERENCE_PATH,
                            "error_type": type(exc).__name__,
                            "formal_evidence_accepted": False,
                        },
                    )
                except Exception:
                    pass
                raise

    def reject_transport(self, *, path: str, error_type: str) -> None:
        """Poison and attest a request that could not yield a JSON envelope."""

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
                "responses_committed": self.responses_committed,
                "completed": self.completed,
                "poisoned": self.poisoned,
                "rejections_recorded": self.rejections_recorded,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            self.audit.stop(payload)
            self.stopped = True


def _resolve_materialized_model_snapshot(cache_dir: Path) -> Path:
    """Require a fixed, symlink-free revision view for formal inference.

    Ordinary Hugging Face caches may use mutable symlinks into a blob store.
    Training and offline evaluation can use that standard layout, but the
    formal service accepts only a separately materialized snapshot so the
    bytes hashed here are the exact bytes passed to Transformers.
    """

    if cache_dir.is_symlink():
        raise ValueError("formal Qwen cache root may not be a symlink")
    snapshot = _resolve_local_revision_snapshot(cache_dir)
    if snapshot.is_symlink():
        raise ValueError("formal Qwen revision snapshot may not be a symlink")
    resolved_cache = cache_dir.resolve(strict=True)
    resolved_snapshot = snapshot.resolve(strict=True)
    if resolved_cache not in resolved_snapshot.parents:
        raise ValueError("formal Qwen revision snapshot escapes its cache root")
    for path in (resolved_snapshot, *snapshot.rglob("*")):
        if path.is_symlink():
            raise ValueError("formal Qwen revision snapshot must be fully materialized")
        resolved_path = path.resolve(strict=True)
        if resolved_path != resolved_snapshot and resolved_snapshot not in resolved_path.parents:
            raise ValueError("formal Qwen revision asset escapes its snapshot")
    return resolved_snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C Qwen V2 formal inference endpoint")
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--model-id", default=QWEN_MODEL_ID, choices=(QWEN_MODEL_ID,))
    parser.add_argument("--revision", default=QWEN_MODEL_REVISION, choices=(QWEN_MODEL_REVISION,))
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--cache-tree-sha256", required=True)
    parser.add_argument("--local-files-only", action="store_true", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--binding-output", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-request-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--startup-check-only", action="store_true")
    return parser.parse_args(argv)


def _binding_from_verified_bundle(
    args: argparse.Namespace,
    *,
    heads: Any,
    metadata: Any,
    manifest: Any,
    model_snapshot: Path,
) -> QwenBundleRuntimeBindingV2:
    if metadata.architecture_revision != QWEN_ARCHITECTURE_REVISION:
        raise ValueError("bundle is not M2C_Q012_V2")
    if metadata.model_id != args.model_id or metadata.model_revision != args.revision:
        raise ValueError("bundle base model ID/revision differs from formal service")
    if (
        metadata.initialization_source != "NONE"
        or metadata.initialization_adapter_sha256 is not None
        or metadata.adapter_source_architecture_revision is not None
    ):
        raise ValueError("formal world-model bundle must use NONE initialization provenance")
    if manifest.status != "TRAINED_QWEN_LORA_THREE_HEADS":
        raise ValueError("formal endpoint requires a trained Qwen LoRA bundle")
    bundle_manifest = args.bundle_root / BUNDLE_MANIFEST_NAME
    actual_cache_sha = sha256_tree(model_snapshot)
    if actual_cache_sha != args.cache_tree_sha256:
        raise ValueError(
            f"offline model cache tree mismatch: {actual_cache_sha} != {args.cache_tree_sha256}"
        )
    head_hashes = qwen_head_tensor_sha256(heads)
    if len(head_hashes) != 6:
        raise ValueError("formal endpoint did not load the exact three heads")
    return QwenBundleRuntimeBindingV2(
        bundle_manifest_sha256=sha256_file(bundle_manifest),
        head_checkpoint_sha256=manifest.head_checkpoint_sha256,
        adapter_tree_sha256=manifest.adapter_tree_sha256,
        model_cache_dir=str(model_snapshot),
        model_cache_tree_sha256=actual_cache_sha,
        failure_context=metadata.failure_context,
    )


def load_runtime(args: argparse.Namespace) -> Runtime:
    if args.model_id != QWEN_MODEL_ID or args.revision != QWEN_MODEL_REVISION:
        raise ValueError("formal service requires the canonical model ID and frozen revision")
    if not args.local_files_only:
        raise ValueError("formal inference must be local-files-only")
    heads, metadata, manifest = load_bundle(
        args.bundle_root,
        require_adapter=True,
        expected_model_id=args.model_id,
        expected_model_revision=args.revision,
    )
    model_snapshot = _resolve_materialized_model_snapshot(args.cache_dir)
    binding = _binding_from_verified_bundle(
        args,
        heads=heads,
        metadata=metadata,
        manifest=manifest,
        model_snapshot=model_snapshot,
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
    if _resolve_materialized_model_snapshot(args.cache_dir) != model_snapshot:
        raise ValueError("offline Qwen snapshot changed while formal runtime loaded")
    if sha256_tree(model_snapshot) != binding.model_cache_tree_sha256:
        raise ValueError("offline Qwen snapshot bytes changed while formal runtime loaded")
    return Runtime(
        binding=binding,
        heads=heads,
        metadata=metadata,
        backbone=backbone,
        head_hashes=qwen_head_tensor_sha256(heads),
        secret=read_hmac_secret(args.hmac_key_file),
        inference_lock=threading.Lock(),
    )


def predict(runtime: Runtime, request: FormalInferenceRequestV2):
    if request.bundle != runtime.binding:
        raise ValueError("inference request bundle/cache binding differs from loaded runtime")
    if request.sent_at_ns <= request.observation.captured_at_ns:
        raise ValueError("inference request precedes its public capture")
    from PIL import Image

    image = Image.open(io.BytesIO(request.observation.rgb.decoded())).convert("RGB")
    depth = np.load(io.BytesIO(request.observation.depth.decoded()), allow_pickle=False)
    if not isinstance(depth, np.ndarray):
        depth.close()
        raise ValueError("public depth must be one np.save ndarray, not an archive")
    if depth.size == 0 or not np.isfinite(depth).all():
        raise ValueError("public depth contains an empty/non-finite array")

    # Reuse the exact training prompt builder with a strict public-only sample
    # projection.  This avoids any silent train/runtime prompt drift.
    sample = type("FormalRuntimePromptSample", (), {})()
    sample.decision_index = request.decision_index
    sample.observation = type("FormalRuntimePromptObservation", (), {})()
    sample.observation.source = "PUBLIC_RGBD"
    sample.observation.fresh = True
    sample.observation.teacher_used = False
    sample.observation.privileged_truth_policy_input = False
    sample.observation.perception_tracks = request.observation.perception_tracks
    sample.observation.canonical_slots = request.observation.canonical_slots
    prompt = qwen_coarse_v2_prompt(
        sample,
        executed_intent_history=request.executed_intent_history,
        use_failure_context=runtime.metadata.failure_context == "on",
    )
    with runtime.inference_lock:
        features = (
            runtime.backbone.encode_multimodal({"texts": [prompt], "images": [image]})
            .pooled.detach()
            .cpu()
            .float()
            .numpy()[0]
        )
        slots = canonical_track_slots(request.observation.perception_tracks)
        skill, pointer, destination = runtime.heads.logits(features, slots.valid_mask)
    completed_at_ns = time.time_ns()
    if completed_at_ns <= request.sent_at_ns:
        completed_at_ns = request.sent_at_ns + 1
    return build_inference_response_from_logits(
        request,
        skill_logits=skill,
        pointer_logits=pointer,
        destination_logits=destination,
        prompt_sha256=canonical_sha256(prompt),
        pooled_feature_sha256=named_array_sha256("qwen_pooled_feature", features),
        head_tensor_sha256=runtime.head_hashes,
        completed_at_ns=completed_at_ns,
    )


def serve(
    runtime: Runtime,
    args: argparse.Namespace,
    audit: AppendOnlyQwenAuditLogV2,
) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    session = FormalQwenServiceSessionV2(runtime=runtime, audit=audit)
    server_holder: dict[str, ThreadingHTTPServer] = {}

    class Handler(BaseHTTPRequestHandler):
        server_version = "M2CQwenFormalV2"

        def log_message(self, format: str, *values: object) -> None:
            print(
                json.dumps(
                    {"event": "HTTP", "message": format % values, "time_ns": time.time_ns()},
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != FORMAL_INFERENCE_PATH:
                try:
                    session.reject_transport(path=self.path, error_type="UnknownEndpoint")
                except Exception:
                    pass
                self.send_error(404)
                return
            try:
                # Preserve the per-request cutoff check even for malformed or
                # oversized bodies that never reach authenticated dispatch.
                require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= args.max_request_bytes:
                    raise ValueError("formal inference request size is invalid")
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError("formal inference request must be one JSON object")
                response = session.handle(raw)
                payload = canonical_json_bytes(response)
            except Exception as exc:
                if "raw" not in locals() or not isinstance(raw, dict):
                    try:
                        session.reject_transport(
                            path=self.path,
                            error_type=type(exc).__name__,
                        )
                    except Exception:
                        pass
                # Fail closed without echoing request assets or secrets.
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
            if self.path == FORMAL_INFERENCE_PATH and session.completed:
                # shutdown() must run outside the handler thread.  It is
                # scheduled only after the eighth authenticated response has
                # been written, so SERVICE_STOPPED cannot precede publication.
                threading.Thread(
                    target=server_holder["server"].shutdown,
                    name="m2c-qwen-graceful-stop",
                    daemon=True,
                ).start()

    server = ThreadingHTTPServer((args.bind_host, args.port), Handler)
    server_holder["server"] = server
    print(
        json.dumps(
            {
                "status": "READY_REAL_QWEN_INFERENCE",
                "endpoint": FORMAL_INFERENCE_PATH,
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


def write_binding_create_only(path: Path, binding: QwenBundleRuntimeBindingV2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(binding.model_dump_json(indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Startup-check loads the real model and creates a binding, so it is not a
    # read-only/status exception to the experiment freeze.
    require_pre_freeze(M2CExperimentAction.FORMAL_MODEL_SERVICE)
    runtime = load_runtime(args)
    write_binding_create_only(args.binding_output, runtime.binding)
    audit = AppendOnlyQwenAuditLogV2(args.audit_dir)
    if args.startup_check_only:
        audit.stop(
            {
                "service_id": audit.service_id,
                "run_id": None,
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
                    "status": "READY_REAL_QWEN_INFERENCE",
                    "endpoint": FORMAL_INFERENCE_PATH,
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
