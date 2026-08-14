#!/usr/bin/env python3
"""Serve one authenticated ADR-0024 V4 Isaac episode.

This module supplies the HTTP/lifecycle shell around
``FormalIsaacEndpointStateMachineV4``.  The production backend factory is
deliberately unbound until the Phase-2 addendum freezes a real episode
lifecycle, public capture provider, exact-plan provider, and executor.  The
shell can therefore be contract-tested locally but cannot open Kit or execute
physics in the current repository state.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from typing import Any

from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v2 import (
    AppendOnlyIsaacAuditLogV2,
    read_json_object,
)
from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v4 import (
    FORMAL_ISAAC_PATHS_V4,
    FormalIsaacEndpointStateMachineV4,
    RealIsaacBackendV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import read_hmac_secret
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacEndpointBindingV4
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


BackendFactoryV4 = Callable[
    [argparse.Namespace, IsaacEndpointBindingV4, AppendOnlyIsaacAuditLogV2],
    RealIsaacBackendV4,
]

# This is an execution authorization boundary, not a feature toggle.  A future
# accepted Phase-2 binding commit must replace it with one fixed factory and
# bind that factory's source/deployment closure.  No CLI or environment value
# can override it.
FORMAL_V4_BACKEND_FACTORY_BINDING: tuple[str, str] | None = None
FORMAL_V4_BACKEND_FACTORY: BackendFactoryV4 | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persistent formal V4 Isaac service")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--endpoint-binding", type=Path, required=True)
    parser.add_argument("--runtime-registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract-check-only", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be in [1, 65535]")
    return args


def _read_binding(path: Path) -> IsaacEndpointBindingV4:
    return IsaacEndpointBindingV4.model_validate_json(read_regular_file_once(path))


def _resolve_bound_source(project_root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"formal V4 endpoint binding path is not repo-relative: {raw_path}")
    root = project_root.resolve()
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"formal V4 endpoint binding path contains a symlink: {raw_path}")
    resolved = (root / relative).resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"formal V4 endpoint binding path escapes project: {raw_path}")
    return resolved


def _sha256_regular(path: Path) -> str:
    import hashlib

    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def validate_deployment(
    args: argparse.Namespace,
    binding: IsaacEndpointBindingV4,
) -> None:
    expected_url = f"http://{args.listen_host}:{args.listen_port}"
    if binding.endpoint_base_url.rstrip("/") != expected_url:
        raise ValueError("formal V4 listen address differs from endpoint binding")
    expected_sources = {
        binding.implementation_path: binding.implementation_sha256,
        binding.physical_backend_path: binding.physical_backend_sha256,
        binding.public_observation_provider_path: binding.public_observation_provider_sha256,
        binding.formal_exact_plan_runtime_path: binding.formal_exact_plan_runtime_sha256,
        binding.bound_plan_provider_path: binding.bound_plan_provider_sha256,
        binding.primitive_bundle_path: binding.primitive_bundle_sha256,
    }
    for raw_path, expected_sha256 in expected_sources.items():
        path = _resolve_bound_source(args.project_root, raw_path)
        if _sha256_regular(path) != expected_sha256:
            raise ValueError(f"formal V4 deployed source differs from binding: {raw_path}")
    expected_registry = _resolve_bound_source(args.project_root, binding.runtime_registry_path)
    if args.runtime_registry.resolve() != expected_registry or (
        _sha256_regular(args.runtime_registry) != binding.runtime_registry_sha256
    ):
        raise ValueError("formal V4 runtime registry differs from endpoint binding")


def _require_bound_backend_factory() -> BackendFactoryV4:
    if FORMAL_V4_BACKEND_FACTORY_BINDING is None or FORMAL_V4_BACKEND_FACTORY is None:
        raise RuntimeError(
            "formal V4 backend factory is not bound by the Phase-2 deployment addendum"
        )
    return FORMAL_V4_BACKEND_FACTORY


class _Handler(BaseHTTPRequestHandler):
    server_version = "M2CFormalIsaacV4"
    protocol_version = "HTTP/1.1"

    @property
    def endpoint(self) -> FormalIsaacEndpointStateMachineV4:
        return self.server.endpoint  # type: ignore[attr-defined,no-any-return]

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP API
        if self.path not in FORMAL_ISAAC_PATHS_V4:
            self._json(404, {"error": "unknown formal V4 Isaac path"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return
        if not 0 < length <= 32 * 1024 * 1024:
            self._json(413, {"error": "formal V4 request size is outside bounds"})
            return
        try:
            raw = read_json_object(self.rfile.read(length))
            response = self.endpoint.handle(self.path, raw)
        except Exception as exc:
            self._json(409, {"error_type": type(exc).__name__, "error": str(exc)})
            return
        self._json(200, response)
        if self.endpoint.state.phase in {"FINALIZED", "TERMINAL_FAILURE"}:
            # The response bytes are flushed before shutdown is scheduled.  A
            # terminal no-action episode therefore gets the same clean audit
            # close as an eight-cycle finalized episode.
            threading.Thread(
                target=self.server.shutdown,
                name="m2c-isaac-v4-graceful-stop",
                daemon=True,
            ).start()

    def log_message(self, format: str, *args: Any) -> None:
        self.endpoint.audit.append(
            "HTTP_ACCESS",
            {"client": self.client_address[0], "message": format % args},
        )

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


class _Server(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        address: tuple[str, int],
        endpoint: FormalIsaacEndpointStateMachineV4,
    ) -> None:
        self.endpoint = endpoint
        super().__init__(address, _Handler)


def _close_backend(backend: RealIsaacBackendV4) -> None:
    close = getattr(backend, "close", None)
    if callable(close):
        close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.contract_check_only:
        require_pre_freeze(M2CExperimentAction.FORMAL_ISAAC_SERVICE)
    binding = _read_binding(args.endpoint_binding)
    validate_deployment(args, binding)
    if args.contract_check_only:
        print(
            json.dumps(
                {
                    "status": "FORMAL_V4_HTTP_SERVICE_SHELL_ONLY_BACKEND_FACTORY_UNBOUND",
                    "backend_factory_binding": FORMAL_V4_BACKEND_FACTORY_BINDING,
                    "formal_execution_eligible": False,
                    "output_written": False,
                    "isaac_started": False,
                    "physical_execution_performed": False,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    factory = _require_bound_backend_factory()
    secret = read_hmac_secret(args.hmac_key_file)
    registry = load_registry_v2(args.runtime_registry)
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(f"refusing to reuse formal V4 Isaac output root: {args.output}")
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    audit = AppendOnlyIsaacAuditLogV2(args.output / "audit")
    backend = factory(args, binding, audit)
    endpoint = FormalIsaacEndpointStateMachineV4(
        secret=secret,
        endpoint_binding=binding,
        registry=registry,
        backend=backend,
        audit=audit,
    )
    try:
        server = _Server((args.listen_host, args.listen_port), endpoint)
    except Exception as exc:
        audit.append(
            "HTTP_SERVER_BIND_FAILED",
            {"error_type": type(exc).__name__, "error": str(exc)},
        )
        _close_backend(backend)
        raise
    audit.append(
        "HTTP_SERVER_READY_V4",
        {
            "listen_host": args.listen_host,
            "listen_port": args.listen_port,
            "formal_execution_started": False,
        },
    )
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        _close_backend(backend)
        audit.append("SERVICE_STOPPED", {"clean_shutdown": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
