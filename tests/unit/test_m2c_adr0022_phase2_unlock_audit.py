from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from m2c.audit_adr0022_phase2_unlock import (
    AuditFailure,
    BLOCKERS,
    EXPECTED_APPLIED_BINDINGS,
    FROZEN_SOURCE_SHA256,
    UNLOCK_BINDING_NAMES,
    _verify_frozen_sources,
    build_audit,
    main,
    parse_unlock_bindings,
    render_json,
    render_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_phase2_contract_smoke_passes_and_source_unlock_is_applied() -> None:
    report = build_audit(PROJECT_ROOT)

    assert report["status"] == "SOURCE_BINDINGS_APPLIED_Q_B_BLOCKED"
    assert report["unlock_authorized"] is True
    assert report["contract_smoke_status"] == "PASS_CONTRACT_ONLY"
    assert report["contract_smoke_is_physical_evidence"] is False
    assert [item["name"] for item in report["contract_smokes"]] == [
        "EXACT_PLAN_DIGEST_IDENTITY",
        "ALL_PHASE_GATE_IMMUTABILITY",
        "MID_PLAN_FAILURE_NO_REPLAN",
        "FROZEN_B0_DIGEST_AND_ATTRIBUTION",
    ]
    assert all(item["status"] == "PASS_CONTRACT_ONLY" for item in report["contract_smokes"])
    assert report["contract_smokes"][-1]["fallback_status"] == ("NO_PHYSICAL_EXECUTION")
    assert report["contract_smokes"][-1]["execution_source"] == ("NO_PHYSICAL_EXECUTION")
    assert report["contract_smokes"][-1]["false_physical_b0_attribution_rejected"]
    assert report["blockers"] == list(BLOCKERS)
    assert report["phase_2_files"] == {
        "binding_addendum_present": True,
        "unlock_config_present": True,
        "generated_by_this_audit": False,
    }
    assert report["entry_gate"]["bindings"] == {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in EXPECTED_APPLIED_BINDINGS.items()
    }
    assert report["governance"] == {
        "training_executed": False,
        "isaac_executed": False,
        "formal_smoke_executed": False,
        "q_b_evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "b0_modified": False,
        "safety_gate_weakened": False,
        "binding_changed": True,
        "addendum_or_unlock_config_generated": False,
        "contract_fixture_counted_as_model_owned_physical_evidence": False,
    }


def test_unlock_binding_parser_rejects_non_none_or_duplicate_assignment() -> None:
    valid = "\n".join(f"{name}: object | None = None" for name in UNLOCK_BINDING_NAMES)
    assert parse_unlock_bindings(valid.encode()) == {name: None for name in UNLOCK_BINDING_NAMES}

    non_none = valid.replace(
        "FORMAL_PHYSICAL_RUNNER_BINDING: object | None = None",
        "FORMAL_PHYSICAL_RUNNER_BINDING: object | None = ('runner', 'digest')",
    )
    with pytest.raises(AuditFailure, match="FORMAL_PHYSICAL_RUNNER_BINDING"):
        parse_unlock_bindings(non_none.encode())

    duplicate = valid + "\nFORMAL_PHYSICAL_RUNNER_BINDING = None\n"
    with pytest.raises(AuditFailure, match="duplicated"):
        parse_unlock_bindings(duplicate.encode())


def test_frozen_source_tamper_is_rejected(tmp_path: Path) -> None:
    for relative in FROZEN_SOURCE_SHA256:
        source = PROJECT_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    first = tmp_path / next(iter(FROZEN_SOURCE_SHA256))
    first.write_bytes(first.read_bytes() + b"tamper")

    with pytest.raises(AuditFailure, match="source SHA-256 differs"):
        _verify_frozen_sources(tmp_path)


def test_json_and_markdown_reports_are_deterministic_and_keep_q_b_blocked() -> None:
    report = build_audit(PROJECT_ROOT)
    parsed = json.loads(render_json(report))
    markdown = render_markdown(report).decode()

    assert parsed == report
    assert "Status: **SOURCE_BINDINGS_APPLIED_Q_B_BLOCKED**" in markdown
    assert "PASS_CONTRACT_ONLY" in markdown
    assert "Physical or formal evidence produced: **false**" in markdown
    assert (
        "`FORMAL_PHYSICAL_RUNNER_BINDING = ['scripts/m2c/run_formal_model_owned_chain_v4.py'"
        in markdown
    )
    assert "`EIGHT_SKILL_PHYSICAL_PHASE_VALIDATION_MISSING`" in markdown


def test_cli_create_only_then_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    json_output = tmp_path / "audit.json"
    markdown_output = tmp_path / "audit.md"
    argv = [
        "audit_adr0022_phase2_unlock.py",
        "--project-root",
        str(PROJECT_ROOT),
        "--json-output",
        str(json_output),
        "--markdown-output",
        str(markdown_output),
    ]
    monkeypatch.setattr("sys.argv", argv)
    assert main() == 0
    assert stat_mode(json_output) & 0o222 == 0
    assert stat_mode(markdown_output) & 0o222 == 0

    with pytest.raises(FileExistsError):
        main()

    monkeypatch.setattr("sys.argv", [*argv, "--check"])
    assert main() == 0


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode
