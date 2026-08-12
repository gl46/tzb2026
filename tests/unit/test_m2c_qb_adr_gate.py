from __future__ import annotations

import hashlib
from pathlib import Path

from xh_agent.policy.qrm_lite import qb_adr_gate


ROOT = Path(__file__).parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_human_adr_and_all_frozen_bindings_authorize_qb() -> None:
    result = qb_adr_gate.evaluate_qb_adr_gate(ROOT)
    assert result["status"] == "PASS_Q_B_HUMAN_ADR_GATE"
    assert result["q_b_authorized"] is True
    assert result["blockers"] == []
    assert result["adr"]["sha256"] == qb_adr_gate.ADR_SHA256
    assert result["adr"]["introduced_in_adr_only_commit"] is True
    assert result["governance_commit"] == (
        "dbe4219497dc748af82af92ca9d20914bd2e847a"
    )
    assert result["frozen_bindings"]["b0_files_verified"] == 12
    assert all(result["frozen_bindings"]["artifact_matches"].values())
    assert result["q_b_training_executed"] is False
    assert result["q_b_evaluation_executed"] is False
    assert result["teacher_used"] is False


def test_gate_constants_equal_the_committed_and_local_evidence_bytes() -> None:
    assert sha256(ROOT / qb_adr_gate.ADR_PATH) == qb_adr_gate.ADR_SHA256
    assert (
        sha256(ROOT / qb_adr_gate.PREREGISTRATION_PATH)
        == qb_adr_gate.PREREGISTRATION_SHA256
    )
    assert sha256(ROOT / qb_adr_gate.B0_FREEZE_PATH) == qb_adr_gate.B0_FREEZE_SHA256
    assert (
        sha256(ROOT / qb_adr_gate.V4_MANIFEST_PATH)
        == qb_adr_gate.V4_MANIFEST_SHA256
    )
    assert sha256(ROOT / qb_adr_gate.DATASET_PATH) == qb_adr_gate.DATASET_SHA256
    assert (
        sha256(ROOT / qb_adr_gate.PATH_BLOCKED_PATH)
        == qb_adr_gate.PATH_BLOCKED_SHA256
    )
    assert sha256(ROOT / qb_adr_gate.GENERATOR_PATH) == qb_adr_gate.GENERATOR_SHA256
    assert sha256(ROOT / qb_adr_gate.B0_PROBE_PATH) == qb_adr_gate.B0_PROBE_SHA256


def test_gate_fail_closes_when_exact_adr_hash_is_not_expected(monkeypatch) -> None:
    monkeypatch.setattr(qb_adr_gate, "ADR_SHA256", "0" * 64)
    result = qb_adr_gate.evaluate_qb_adr_gate(ROOT)
    assert result["q_b_authorized"] is False
    assert result["status"] == "BLOCKED_HUMAN_ADR_REQUIRED"
    assert any("human-approved Q-B ADR SHA-256 mismatch" in item for item in result["blockers"])


def test_relative_path_guard_rejects_escape_and_absolute_paths() -> None:
    assert qb_adr_gate._safe_relative_path("docs/decisions/ADR.md") == (
        "docs/decisions/ADR.md"
    )
    assert qb_adr_gate._safe_relative_path("../ADR.md") is None
    assert qb_adr_gate._safe_relative_path("/tmp/ADR.md") is None
