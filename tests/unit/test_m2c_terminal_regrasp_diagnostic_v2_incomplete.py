from __future__ import annotations

import json
from pathlib import Path

import pytest

from m2c.audit_terminal_regrasp_diagnostic_v2_incomplete import (
    EXPECTED_PROBE_ERROR,
    audit_v2_incomplete_campaign,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    TerminalDiagnosticError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    load_committed_diagnostic_prereg_v2,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/decisions/M2C-S4-TERMINAL-REGRASP-DIAGNOSTIC-V2-PREREG.json"


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    resolved = load_committed_diagnostic_prereg_v2(
        project_root=ROOT,
        prereg_path=PREREG,
    )
    prereg = resolved.prereg
    run = prereg.runs[0]
    upstream = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
    from m2c.derive_terminal_regrasp_diagnostic_probe_v2 import (
        derive_terminal_regrasp_diagnostic_probe_bytes_v2,
    )

    derived = derive_terminal_regrasp_diagnostic_probe_bytes_v2(upstream.read_bytes())
    claim: dict[str, object] = {
        "schema_version": "M2CTerminalDiagnosticConsumptionReceiptV2",
        "event": "CONSUMED_BEFORE_STAGE",
        "campaign_id": prereg.campaign_id,
        "ledger_namespace": prereg.ledger_namespace,
        "ordinal": 0,
        "run": run.model_dump(mode="json"),
        "prereg_repository_path": prereg.repository_relative_path,
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": prereg.prereg_sha256,
        "prereg_introduced_commit": resolved.introduced_commit,
        "committed_source_snapshot": prereg.committed_source_snapshot.model_dump(mode="json"),
        "source_urdf_sha256": prereg.controlled_urdf_sha256,
        "upstream_v4_probe_sha256": prereg.upstream_v4_probe_sha256,
        "derived_probe_sha256": sha256_bytes(derived),
        "container_image_id": prereg.container_image_id,
        "consumed_at_ns": 100,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    claim["receipt_sha256"] = canonical_sha256(claim)
    claim_raw = canonical_json_bytes(claim) + b"\n"
    ledger = tmp_path / "ledger"
    evidence = tmp_path / "evidence"
    suffix = run.run_id.removeprefix("m2c-s4-terminal-diagnostic-")[:16]
    job_root = evidence / f"run-00-{suffix}"
    _write(ledger / ".diagnostic-ledger.lock", b"")
    _write(ledger / "claim-00.json", claim_raw)
    _write(job_root / "authorization" / "diagnostic-claim.json", claim_raw)
    _write(job_root / "derived" / "terminal-regrasp-diagnostic-probe-v2.py", derived)

    job: dict[str, object] = {
        "schema_version": "M2CTerminalDiagnosticJobReceiptV2",
        "status": "CONSUMED_V2_DIAGNOSTIC_ONLY_BEFORE_STAGE",
        "campaign_id": prereg.campaign_id,
        "run": run.model_dump(mode="json"),
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": prereg.prereg_sha256,
        "claim_path": str(ledger / "claim-00.json"),
        "claim_sha256": sha256_bytes(claim_raw),
        "derived_probe_sha256": sha256_bytes(derived),
        "source_snapshot": prereg.committed_source_snapshot.model_dump(mode="json"),
        "image_id": prereg.container_image_id,
        "stage_command_sha256": "1" * 64,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    job["receipt_sha256"] = canonical_sha256(job)
    _write(job_root / "job-receipt.json", canonical_json_bytes(job) + b"\n")
    terminal: dict[str, object] = {
        "schema_version": "M2CTerminalDiagnosticRunTerminalV2",
        "run_id": run.run_id,
        "ordinal": 0,
        "condition": run.condition,
        "claim_sha256": sha256_bytes(claim_raw),
        "stage_completed": True,
        "probe_returncode": 0,
        "raw_evidence_sha256": None,
        "status": "INCOMPLETE",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "probe_command_sha256": "2" * 64,
        "error_type": "TerminalDiagnosticError",
        "terminalized_at_ns": 200,
    }
    terminal["terminal_receipt_sha256"] = canonical_sha256(terminal)
    _write(job_root / "terminal-receipt.json", canonical_json_bytes(terminal) + b"\n")
    console = (
        f'M1B_ISAAC_ACTUATION_PROBE_FATAL {{"error_type": "ValueError", '
        f'"message": "{EXPECTED_PROBE_ERROR}"}}\n'
        '  File "probe", line 1, in _setup_m2b_public_rgbd\n'
        f'    raise ValueError("{EXPECTED_PROBE_ERROR}")\n'
    )
    _write(job_root / "probe" / "console.log", console.encode())
    _write(job_root / "stage" / "console.log", b"stage complete\n")
    return ledger, evidence


def test_v2_incomplete_audit_proves_pre_controller_failure(tmp_path: Path) -> None:
    ledger, evidence = _fixture(tmp_path)
    report = audit_v2_incomplete_campaign(
        project_root=ROOT,
        prereg_path=PREREG,
        ledger_root=ledger,
        evidence_root=evidence,
    )
    assert report["status"] == "BLOCKED_INCOMPLETE_PUBLIC_CAPTURE_SETUP_MISMATCH"
    assert report["valid_terminal_measurements"] == 0
    assert report["decision"] is None
    assert report["failed_run"]["kit_started"] is True
    assert report["failed_run"]["controller_initialized"] is False
    assert report["failed_run"]["terminal_primitive_called"] is False
    assert report["retry_or_replacement_authorized"] is False


def test_v2_incomplete_audit_rejects_spliced_raw(tmp_path: Path) -> None:
    ledger, evidence = _fixture(tmp_path)
    job = next(evidence.glob("run-*"))
    _write(job / "probe" / "terminal-regrasp-diagnostic.json", b"{}\n")
    with pytest.raises(TerminalDiagnosticError, match="unexpectedly has raw"):
        audit_v2_incomplete_campaign(
            project_root=ROOT,
            prereg_path=PREREG,
            ledger_root=ledger,
            evidence_root=evidence,
        )


def test_v2_incomplete_audit_rejects_other_console_failure(tmp_path: Path) -> None:
    ledger, evidence = _fixture(tmp_path)
    job = next(evidence.glob("run-*"))
    (job / "probe" / "console.log").write_text("different failure\n")
    with pytest.raises(TerminalDiagnosticError, match="public-capture mismatch"):
        audit_v2_incomplete_campaign(
            project_root=ROOT,
            prereg_path=PREREG,
            ledger_root=ledger,
            evidence_root=evidence,
        )


def test_published_v2_incomplete_report_withholds_ablation_decision() -> None:
    path = ROOT / "reports/m2c-s4-terminal-regrasp-diagnostic-v2-incomplete.json"
    report = json.loads(path.read_text())
    assert report["status"] == "BLOCKED_INCOMPLETE_PUBLIC_CAPTURE_SETUP_MISMATCH"
    assert report["valid_terminal_measurements"] == 0
    assert report["decision"] is None
    assert report["failed_run"]["controller_initialized"] is False
    assert report["failed_run"]["terminal_primitive_called"] is False
    assert report["further_v2_execution_authorized"] is False
