#!/usr/bin/env python3
"""Serve one persistent real-Isaac M2C episode over the four formal APIs.

Run this file with Isaac Sim's Python, never ordinary CPython.  The service is
single-session by design and serializes all calls into the same Kit process.
It does not expose fixtures, dry-run responses, or scripted decision sources.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from m2c.formal_isaac_v4_backend import (
    FROZEN_V4_PROBE_SHA256,
    FormalIsaacV4BackendV2,
)
from xh_agent.policy.qrm_lite.formal_isaac_endpoint_v2 import (
    AppendOnlyIsaacAuditLogV2,
    FormalIsaacEndpointStateMachineV2,
    read_json_object,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FORMAL_ISAAC_CAPTURE_PATH,
    FORMAL_ISAAC_EXECUTE_PATH,
    FORMAL_ISAAC_FINALIZE_PATH,
    FORMAL_ISAAC_START_PATH,
    IsaacEndpointBindingV2,
    read_hmac_secret,
    sha256_file,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)


FORMAL_PATHS = frozenset(
    {
        FORMAL_ISAAC_START_PATH,
        FORMAL_ISAAC_CAPTURE_PATH,
        FORMAL_ISAAC_EXECUTE_PATH,
        FORMAL_ISAAC_FINALIZE_PATH,
    }
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persistent real M2C Isaac endpoint")
    parser.add_argument("--listen-host", required=True)
    parser.add_argument("--listen-port", required=True, type=int)
    parser.add_argument("--hmac-key-file", required=True, type=Path)
    parser.add_argument("--endpoint-binding", required=True, type=Path)
    parser.add_argument("--runtime-registry", required=True, type=Path)
    parser.add_argument("--frozen-v4-probe", required=True, type=Path)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--stage-sha256", required=True)
    parser.add_argument("--sdf", required=True, type=Path)
    parser.add_argument("--supervision", required=True, type=Path)
    parser.add_argument("--urdf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--physics-device", choices=("cpu", "cuda"), required=True)
    # These frozen V4 arguments are required because the imported module parses
    # this same argv before starting SimulationApp.  No destination/chain source
    # argument is offered to the formal service.
    parser.add_argument("--target-object", choices=("cylinder_01",), required=True)
    parser.add_argument("--m2b-task-target-object", choices=("cylinder_04",), required=True)
    parser.add_argument("--m2b-capture-public-rgbd", action="store_true", required=True)
    parser.add_argument(
        "--m2b-task-target-public-color",
        choices=("yellow",),
        required=True,
    )
    parser.add_argument(
        "--m2b-injected-public-grasp-color",
        choices=("red",),
        required=True,
    )
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        parser.error(f"unknown/formal-forbidden arguments: {unknown}")
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be in [1, 65535]")
    return args


def _read_binding(path: Path) -> IsaacEndpointBindingV2:
    value = json.loads(path.read_text(encoding="utf-8"))
    return IsaacEndpointBindingV2.model_validate(value)


def _validate_deployment(
    args: argparse.Namespace,
    binding: IsaacEndpointBindingV2,
) -> None:
    if binding.frozen_v4_probe_sha256 != FROZEN_V4_PROBE_SHA256:
        raise ValueError("endpoint binding does not pin the frozen V4 probe")
    declared_url = binding.endpoint_base_url.rstrip("/")
    expected_url = f"http://{args.listen_host}:{args.listen_port}"
    if declared_url != expected_url:
        raise ValueError("listen address differs from endpoint binding")
    expected_paths = {
        binding.implementation_path: binding.implementation_sha256,
        binding.physical_backend_path: binding.physical_backend_sha256,
        binding.public_role_selector_path: binding.public_role_selector_sha256,
    }
    for raw_path, expected_sha in expected_paths.items():
        path = Path(raw_path)
        if not path.is_file() or sha256_file(path) != expected_sha:
            raise ValueError(f"deployed source differs from endpoint binding: {path}")
    if sha256_file(args.frozen_v4_probe) != FROZEN_V4_PROBE_SHA256:
        raise ValueError("deployed V4 source differs from frozen probe")
    if not args.output.parent.is_dir():
        raise FileNotFoundError(args.output.parent)


class _Handler(BaseHTTPRequestHandler):
    server_version = "M2CFormalIsaacV2"
    protocol_version = "HTTP/1.1"

    @property
    def endpoint(self) -> FormalIsaacEndpointStateMachineV2:
        return self.server.endpoint  # type: ignore[attr-defined,no-any-return]

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP API
        if self.path not in FORMAL_PATHS:
            self._json(404, {"error": "unknown formal Isaac path"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return
        if not 0 < length <= 32 * 1024 * 1024:
            self._json(413, {"error": "formal request size is outside bounds"})
            return
        try:
            raw = read_json_object(self.rfile.read(length))
            response = self.endpoint.handle(self.path, raw)
        except Exception as exc:
            # The durable Isaac audit has the exact rejection.  HTTP only gets
            # a non-sensitive type/message and never a synthetic signed reply.
            self._json(
                409,
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
            return
        self._json(200, response)

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


class _Server(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        address: tuple[str, int],
        endpoint: FormalIsaacEndpointStateMachineV2,
    ) -> None:
        self.endpoint = endpoint
        super().__init__(address, _Handler)


def main() -> int:
    args = parse_args()
    require_pre_freeze(M2CExperimentAction.FORMAL_ISAAC_SERVICE)
    binding = _read_binding(args.endpoint_binding)
    _validate_deployment(args, binding)
    secret = read_hmac_secret(args.hmac_key_file)
    registry = load_registry_v2(args.runtime_registry)
    if args.output.exists():
        raise FileExistsError(f"refusing to reuse Isaac output root: {args.output}")
    args.output.mkdir(mode=0o700, exist_ok=False)
    audit = AppendOnlyIsaacAuditLogV2(args.output / "audit")
    backend = FormalIsaacV4BackendV2(
        frozen_v4_probe_path=args.frozen_v4_probe,
        stage_path=args.stage,
        sdf_path=args.sdf,
        supervision_path=args.supervision,
        urdf_path=args.urdf,
        capture_root=args.output / "captures",
        endpoint_binding=binding,
        runtime_registry_sha256=sha256_file(args.runtime_registry),
        public_role_selector_sha256=binding.public_role_selector_sha256,
        stage_sha256=args.stage_sha256,
    )
    endpoint = FormalIsaacEndpointStateMachineV2(
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
        backend.close()
        raise
    audit.append(
        "HTTP_SERVER_READY",
        {
            "listen_host": args.listen_host,
            "listen_port": args.listen_port,
            "formal_execution_started": False,
        },
    )
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        # ``shutdown`` may only be called from a different thread than
        # ``serve_forever``; here the loop has already returned.
        server.server_close()
        backend.close()
        audit.append("SERVICE_STOPPED", {"clean_shutdown": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
