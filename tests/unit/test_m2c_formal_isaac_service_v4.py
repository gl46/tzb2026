from __future__ import annotations

import ast
import hashlib
import http.client
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from typing import Any, Mapping

import pytest

from m2c import serve_formal_isaac_endpoint_v4 as service
from test_m2c_formal_isaac_endpoint_v4 import _endpoint
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    FORMAL_ISAAC_EXECUTE_PATH_V4,
    IsaacEndpointBindingV4,
)


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class _FakeEndpoint:
    def __init__(self, *, terminal: bool) -> None:
        self.audit = _Audit()
        self.state = SimpleNamespace(phase="READY_EXECUTE")
        self.terminal = terminal
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def handle(self, path: str, raw: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append((path, raw))
        if self.terminal:
            self.state.phase = "TERMINAL_FAILURE"
        return {"schema_version": "test-only", "accepted": True}


def _request(server: service._Server, path: str) -> tuple[int, dict[str, Any]]:
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=5.0)
    try:
        body = json.dumps({"schema_version": "test-only"})
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _argv(tmp_path: Path, *, contract: bool = False) -> list[str]:
    values = [
        "--project-root",
        str(tmp_path),
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        "48134",
        "--hmac-key-file",
        str(tmp_path / "isaac.key"),
        "--endpoint-binding",
        str(tmp_path / "binding.json"),
        "--runtime-registry",
        str(tmp_path / "registry.yaml"),
        "--output",
        str(tmp_path / "output"),
    ]
    if contract:
        values.append("--contract-check-only")
    return values


def test_v4_http_service_flushes_terminal_response_then_stops() -> None:
    endpoint = _FakeEndpoint(terminal=True)
    server = service._Server(("127.0.0.1", 0), endpoint)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        status, payload = _request(server, FORMAL_ISAAC_EXECUTE_PATH_V4)
        assert status == 200
        assert payload == {"accepted": True, "schema_version": "test-only"}
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert endpoint.calls == [(FORMAL_ISAAC_EXECUTE_PATH_V4, {"schema_version": "test-only"})]
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join(timeout=5.0)
        server.server_close()


def test_v4_http_service_rejects_unknown_path_without_endpoint_contact() -> None:
    endpoint = _FakeEndpoint(terminal=False)
    server = service._Server(("127.0.0.1", 0), endpoint)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        status, payload = _request(server, "/unknown")
        assert status == 404
        assert payload["error"] == "unknown formal V4 Isaac path"
        assert endpoint.calls == []
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()


def test_v4_service_contract_check_is_nonexecuting_and_factory_stays_unbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    monkeypatch.setattr(service, "_read_binding", lambda _path: endpoint.binding)
    monkeypatch.setattr(service, "validate_deployment", lambda *_args: None)
    monkeypatch.setattr(
        service,
        "read_hmac_secret",
        lambda _path: pytest.fail("contract check read the HMAC key"),
    )

    assert service.FORMAL_V4_BACKEND_FACTORY_BINDING is None
    assert service.FORMAL_V4_BACKEND_FACTORY is None
    assert service.main(_argv(tmp_path, contract=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FORMAL_V4_HTTP_SERVICE_SHELL_ONLY_BACKEND_FACTORY_UNBOUND"
    assert payload["formal_execution_eligible"] is False
    assert payload["output_written"] is False
    assert not (tmp_path / "output").exists()

    source = Path(service.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    binding_assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "FORMAL_V4_BACKEND_FACTORY_BINDING"
    ]
    assert len(binding_assignments) == 1
    assert isinstance(binding_assignments[0].value, ast.Constant)
    assert binding_assignments[0].value.value is None


def test_v4_service_real_start_fails_before_secret_or_output_when_factory_unbound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    events: list[str] = []
    monkeypatch.setattr(
        service,
        "require_pre_freeze",
        lambda _action: events.append("hard-freeze"),
    )
    monkeypatch.setattr(service, "_read_binding", lambda _path: endpoint.binding)
    monkeypatch.setattr(service, "validate_deployment", lambda *_args: events.append("binding"))
    monkeypatch.setattr(
        service,
        "read_hmac_secret",
        lambda _path: pytest.fail("unbound service read the HMAC key"),
    )

    with pytest.raises(RuntimeError, match="backend factory is not bound"):
        service.main(_argv(tmp_path))
    assert events == ["hard-freeze", "binding"]
    assert not (tmp_path / "output").exists()


def test_v4_service_deployment_validation_replays_all_bound_sources(tmp_path: Path) -> None:
    endpoint, _, _ = _endpoint(tmp_path / "endpoint")
    project = tmp_path / "project"
    source_paths = {
        "src/endpoint.py": b"endpoint\n",
        "src/backend.py": b"backend\n",
        "src/observation.py": b"observation\n",
        "src/runtime.py": b"runtime\n",
        "src/provider.py": b"provider\n",
        "src/bundle.py": b"bundle\n",
    }
    for raw_path, content in source_paths.items():
        path = project / raw_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    registry = project / "configs/qrm_runtime_mapping_v2.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_bytes(b"registry\n")
    digest = lambda value: hashlib.sha256(value).hexdigest()  # noqa: E731
    binding = IsaacEndpointBindingV4.model_validate(
        {
            **endpoint.binding.model_dump(mode="json"),
            "endpoint_base_url": "http://127.0.0.1:48134",
            "implementation_path": "src/endpoint.py",
            "implementation_sha256": digest(source_paths["src/endpoint.py"]),
            "physical_backend_path": "src/backend.py",
            "physical_backend_sha256": digest(source_paths["src/backend.py"]),
            "public_observation_provider_path": "src/observation.py",
            "public_observation_provider_sha256": digest(source_paths["src/observation.py"]),
            "formal_exact_plan_runtime_path": "src/runtime.py",
            "formal_exact_plan_runtime_sha256": digest(source_paths["src/runtime.py"]),
            "bound_plan_provider_path": "src/provider.py",
            "bound_plan_provider_sha256": digest(source_paths["src/provider.py"]),
            "primitive_bundle_path": "src/bundle.py",
            "primitive_bundle_sha256": digest(source_paths["src/bundle.py"]),
            "runtime_registry_path": "configs/qrm_runtime_mapping_v2.yaml",
            "runtime_registry_sha256": digest(b"registry\n"),
        }
    )
    args = service.parse_args(
        [
            "--project-root",
            str(project),
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            "48134",
            "--hmac-key-file",
            str(tmp_path / "key"),
            "--endpoint-binding",
            str(tmp_path / "binding"),
            "--runtime-registry",
            str(registry),
            "--output",
            str(tmp_path / "output"),
            "--contract-check-only",
        ]
    )

    service.validate_deployment(args, binding)
    (project / "src/backend.py").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="deployed source differs"):
        service.validate_deployment(args, binding)

    (project / "src/backend.py").unlink()
    (project / "src/backend-real.py").write_bytes(source_paths["src/backend.py"])
    (project / "src/backend.py").symlink_to("backend-real.py")
    with pytest.raises(ValueError, match="contains a symlink"):
        service.validate_deployment(args, binding)
