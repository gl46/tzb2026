from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from m2c.audit_phase2_a3_acm_smoke import (
    A3ACMSmokeAuditError,
    EXPECTED_BLOCKERS,
    SMOKE_RECEIPT_SHA256,
    build_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE = Path(
    "/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-acm-smoke-f4c0ec8/query-only-deployment-smoke.json"
)


@pytest.mark.skipif(not SMOKE.is_file(), reason="immutable A3 ACM smoke receipt is absent")
def test_acm_smoke_replays_74_clear_queries_without_execution() -> None:
    report = build_report(project_root=PROJECT_ROOT, smoke_receipt_path=SMOKE)

    assert report["status"] == "PASS_QUERY_ONLY_A3_ACM_SMOKE_CLEAR"
    assert report["smoke_evidence"]["sha256"] == SMOKE_RECEIPT_SHA256
    assert report["acm_source_audit"]["authorized_pair_count"] == 2
    assert report["acm_source_audit"]["criterion"] == "A_OFFICIAL_UPSTREAM_SRDF"
    assert report["query_result"]["request_segment_count"] == 74
    assert report["query_result"]["clear_result_count"] == 74
    assert report["query_result"]["collision_rejection_count"] == 0
    assert report["query_result"]["query_failure_count"] == 0
    assert report["query_result"]["receipt_status"] == "PASS"
    assert report["evidence_claims"]["static_state_preflight_clear"] is True
    assert report["evidence_claims"]["formal_execution_eligible"] is False
    assert report["evidence_claims"]["isaac_started"] is False
    assert report["evidence_claims"]["physical_execution_performed"] is False
    assert report["evidence_claims"]["articulation_target_writes"] == 0
    assert report["evidence_claims"]["simulation_steps"] == 0
    assert report["evidence_claims"]["scene_mutations"] == 0
    assert report["evidence_claims"]["teacher_used"] is False
    assert report["remaining_blockers"] == list(EXPECTED_BLOCKERS)


@pytest.mark.skipif(not SMOKE.is_file(), reason="immutable A3 ACM smoke receipt is absent")
def test_acm_smoke_tamper_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "smoke.json"
    shutil.copyfile(SMOKE, copied)
    value = json.loads(copied.read_text())
    value["query"]["collision_rejection_count"] = 1
    copied.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(A3ACMSmokeAuditError, match="SHA-256"):
        build_report(project_root=PROJECT_ROOT, smoke_receipt_path=copied)


def test_acm_source_audit_binds_each_pair_and_no_geometry_change() -> None:
    report = json.loads((PROJECT_ROOT / "reports/m2c-phase2-a3-acm-adr0025.json").read_text())
    assert report["controlled_srdf"]["added_pair_count"] == 2
    assert report["controlled_srdf"]["removed_pair_count"] == 0
    assert {tuple(item["link_pair"]) for item in report["pair_evidence"]} == {
        ("panda_hand", "panda_link7"),
        ("panda_link2", "panda_link4"),
    }
    assert all(item["criterion"] == "A_OFFICIAL_UPSTREAM_SRDF" for item in report["pair_evidence"])
    claims = report["evidence_claims"]
    assert claims["collision_margin_changed"] is False
    assert claims["outward_padding_changed"] is False
    assert claims["hull_geometry_changed"] is False
    assert claims["collision_threshold_changed"] is False
