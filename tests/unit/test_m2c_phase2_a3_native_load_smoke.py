from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

import pytest

from m2c import audit_phase2_a3_native_load_smoke as audit


DEPENDENCY_ROOT = Path(
    "/Users/gl/tzb-m2c-evidence/"
    "phase2-a3-runtime-deps-v3-3641a84b2e0befd0225f6127fd613c10bbc2b2abe615bce1fc28491e4533586d"
)
SMOKE_ROOT = Path("/Users/gl/tzb-m2c-evidence/phase2-a3-native-load-smoke-a64ee76")


@pytest.fixture(autouse=True)
def _restore_permissions(tmp_path: Path):
    yield
    for path in tmp_path.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
        elif path.is_file() and not path.is_symlink():
            path.chmod(0o644)
    tmp_path.chmod(0o755)


def test_immutable_tree_reader_rejects_writable_or_tampered_payload(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir(mode=0o755)
    payload = root / "receipt.json"
    raw = b'{"status":"PASS"}\n'
    payload.write_bytes(raw)
    payload.chmod(0o444)
    root.chmod(0o555)
    expected = {"receipt.json": hashlib.sha256(raw).hexdigest()}

    assert audit._validate_tree(root, expected) == {"receipt.json": raw}

    payload.chmod(0o644)
    with pytest.raises(audit.NativeLoadSmokeAuditFailure, match="not immutable"):
        audit._validate_tree(root, expected)
    payload.write_bytes(b'{"status":"FAKE"}\n')
    payload.chmod(0o444)
    with pytest.raises(audit.NativeLoadSmokeAuditFailure, match="digest differs"):
        audit._validate_tree(root, expected)


def test_native_load_contract_binds_all_build_headers_and_stays_non_authorizing() -> None:
    header_paths = {
        path for path in audit.DEPENDENCY_SHA256 if path.startswith("usr/include/bullet/")
    }
    assert len(header_paths) == 12
    assert audit.IMMUTABLE_COMMIT == "a64ee76ec298a025f4021245211e1208847bebf0"
    assert audit.RUNTIME_IMAGE_ID.startswith("sha256:")
    assert audit.SMOKE_REPORT_SHA256 == audit.SMOKE_FILE_SHA256["container-stdout.log"]


@pytest.mark.skipif(
    not DEPENDENCY_ROOT.is_dir() or not SMOKE_ROOT.is_dir(),
    reason="external query-only smoke evidence is not installed",
)
def test_external_native_load_smoke_replays_exactly() -> None:
    project = Path(__file__).resolve().parents[2]

    report = audit.build_report(project, DEPENDENCY_ROOT, SMOKE_ROOT)

    assert report["status"] == "PASS_QUERY_ONLY_NATIVE_LOAD_IN_FROZEN_ISAAC_IMAGE"
    assert report["query"]["clear_result_count"] == 74
    assert report["evidence_claims"]["formal_execution_eligible"] is False
    assert report["evidence_claims"]["isaac_started"] is False
    assert report["evidence_claims"]["physical_execution_performed"] is False


@pytest.mark.skipif(
    not DEPENDENCY_ROOT.is_dir() or not SMOKE_ROOT.is_dir(),
    reason="external query-only smoke evidence is not installed",
)
def test_external_native_load_smoke_rejects_report_tamper(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    copied = tmp_path / "smoke"
    shutil.copytree(SMOKE_ROOT, copied)
    copied.chmod(0o755)
    target = copied / "query-only-deployment-smoke.json"
    target.chmod(0o644)
    target.write_bytes(b'{"status":"PASS_QUERY_ONLY_DEPLOYMENT_SMOKE_CLEAR"}\n')
    target.chmod(0o444)
    copied.chmod(0o555)

    with pytest.raises(audit.NativeLoadSmokeAuditFailure, match="digest differs"):
        audit.build_report(project, DEPENDENCY_ROOT, copied)
