from __future__ import annotations

import json
from pathlib import Path

import pytest

from m2c.audit_terminal_regrasp_diagnostic_incomplete import (
    EXPECTED_STAGE_ERROR,
    IMPLEMENTATION_PATH,
    audit_incomplete_campaign,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    CONTROLLED_URDF_SHA256,
    ISAAC_IMAGE_ID,
    UPSTREAM_V4_PROBE_SHA256,
    TerminalDiagnosticError,
    canonical_json_bytes,
    canonical_sha256,
    load_committed_diagnostic_prereg,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/decisions/M2C-S4-TERMINAL-REGRASP-DIAGNOSTIC-PREREG.json"


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    resolved = load_committed_diagnostic_prereg(project_root=ROOT, prereg_path=PREREG)
    prereg = resolved.prereg
    run = prereg.runs[0]
    derived = b"# exact derived diagnostic fixture\n"
    claim: dict[str, object] = {
        "schema_version": "M2CTerminalDiagnosticConsumptionReceiptV1",
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
        "source_urdf_sha256": CONTROLLED_URDF_SHA256,
        "upstream_v4_probe_sha256": UPSTREAM_V4_PROBE_SHA256,
        "derived_probe_sha256": sha256_bytes(derived),
        "container_image_id": ISAAC_IMAGE_ID,
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
    _write(job_root / "derived" / "terminal-regrasp-diagnostic-probe.py", derived)
    (job_root / "probe").mkdir(parents=True)

    job: dict[str, object] = {
        "schema_version": "M2CTerminalDiagnosticJobReceiptV1",
        "status": "CONSUMED_DIAGNOSTIC_ONLY_BEFORE_STAGE",
        "campaign_id": prereg.campaign_id,
        "run": run.model_dump(mode="json"),
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": prereg.prereg_sha256,
        "claim_path": str(ledger / "claim-00.json"),
        "claim_sha256": sha256_bytes(claim_raw),
        "derived_probe_sha256": sha256_bytes(derived),
        "source_snapshot": prereg.committed_source_snapshot.model_dump(mode="json"),
        "image_id": ISAAC_IMAGE_ID,
        "stage_command_sha256": "1" * 64,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    job["receipt_sha256"] = canonical_sha256(job)
    _write(job_root / "job-receipt.json", canonical_json_bytes(job) + b"\n")

    terminal: dict[str, object] = {
        "schema_version": "M2CTerminalDiagnosticRunTerminalV1",
        "run_id": run.run_id,
        "ordinal": 0,
        "condition": run.condition,
        "claim_sha256": sha256_bytes(claim_raw),
        "stage_completed": False,
        "probe_returncode": None,
        "raw_evidence_sha256": None,
        "status": "INCOMPLETE",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "error_type": "TerminalDiagnosticError",
        "terminalized_at_ns": 200,
    }
    terminal["terminal_receipt_sha256"] = canonical_sha256(terminal)
    _write(job_root / "terminal-receipt.json", canonical_json_bytes(terminal) + b"\n")
    console = (
        "Traceback (most recent call last):\n"
        '  File "x", line 1, in load_m1b_isaac_generated_scene\n'
        f"ValueError: {EXPECTED_STAGE_ERROR}\n"
    )
    _write(job_root / "stage" / "console.log", console.encode())
    return ledger, evidence


def test_incomplete_audit_withholds_the_preregistered_decision(tmp_path: Path) -> None:
    ledger, evidence = _fixture(tmp_path)
    report = audit_incomplete_campaign(
        project_root=ROOT,
        prereg_path=PREREG,
        ledger_root=ledger,
        evidence_root=evidence,
    )
    assert report["status"] == "BLOCKED_INCOMPLETE_PRE_ACTION_SCHEMA_MISMATCH"
    assert report["consumed_run_count"] == 1
    assert report["unrun_count"] == 35
    assert report["valid_terminal_measurements"] == 0
    assert report["decision"] is None
    assert report["r1_r2_r3_evaluation_allowed"] is False
    assert report["implementation"]["path"] == IMPLEMENTATION_PATH
    assert report["failed_run"]["probe_launched"] is False
    assert report["failed_run"]["physical_action_outcome"] == "NOT_AVAILABLE"
    assert report["retry_or_replacement_authorized"] is False


def test_incomplete_audit_rejects_a_spliced_raw_outcome(tmp_path: Path) -> None:
    ledger, evidence = _fixture(tmp_path)
    job = next(evidence.glob("run-*"))
    _write(job / "probe" / "terminal-regrasp-diagnostic.json", b"{}\n")
    with pytest.raises(TerminalDiagnosticError, match="unexpectedly contains raw"):
        audit_incomplete_campaign(
            project_root=ROOT,
            prereg_path=PREREG,
            ledger_root=ledger,
            evidence_root=evidence,
        )


def test_incomplete_audit_rejects_an_unbound_console_reason(tmp_path: Path) -> None:
    ledger, evidence = _fixture(tmp_path)
    job = next(evidence.glob("run-*"))
    (job / "stage" / "console.log").write_text("different failure\n")
    with pytest.raises(TerminalDiagnosticError, match="schema mismatch"):
        audit_incomplete_campaign(
            project_root=ROOT,
            prereg_path=PREREG,
            ledger_root=ledger,
            evidence_root=evidence,
        )


def test_published_incomplete_report_is_not_an_ablation_outcome() -> None:
    report_path = ROOT / "reports/m2c-s4-terminal-regrasp-diagnostic-adr0026.json"
    if not report_path.exists():
        pytest.skip("create-only real-evidence report has not been published")
    report = json.loads(report_path.read_text())
    assert report["status"] == "BLOCKED_INCOMPLETE_PRE_ACTION_SCHEMA_MISMATCH"
    assert report["decision"] is None
    assert report["valid_terminal_measurements"] == 0
    assert report["further_diagnostic_execution_authorized"] is False
