from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from m2c.audit_phase2_a3_query_only_deployment_comparison import (
    AFTER_RECEIPT_SHA256,
    BEFORE_RECEIPT_SHA256,
    INTERMEDIATE_RECEIPT_SHA256,
    ComparisonAuditFailure,
    REMAINING_BLOCKERS,
    REMAINING_REJECTED_PAIRS,
    build_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BEFORE = Path(
    "/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-query-only-smoke-fcccc9c/"
    "query-only-deployment-smoke.json"
)
AFTER = Path(
    "/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-query-only-smoke-cf522c9/"
    "output/query-only-deployment-smoke.json"
)
INTERMEDIATE = Path(
    "/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-query-only-smoke-7ea1b43/"
    "query-only-deployment-smoke.json"
)


@pytest.mark.skipif(
    not BEFORE.is_file() or not INTERMEDIATE.is_file() or not AFTER.is_file(),
    reason="external comparison evidence is absent",
)
def test_query_only_before_after_replay_remains_fail_closed() -> None:
    report = build_report(PROJECT_ROOT, BEFORE, INTERMEDIATE, AFTER)

    assert report["status"] == "PASS_DEPLOYMENT_QUERY_REPLAY_BLOCKED_STATIC_HOME_COLLISION"
    assert report["evidence_bindings"]["before_smoke_receipt_sha256"] == BEFORE_RECEIPT_SHA256
    assert (
        report["evidence_bindings"]["intermediate_smoke_receipt_sha256"]
        == INTERMEDIATE_RECEIPT_SHA256
    )
    assert report["evidence_bindings"]["after_smoke_receipt_sha256"] == AFTER_RECEIPT_SHA256
    assert report["before"]["collision_rejection_count"] == 15
    assert report["after"]["collision_rejection_count"] == 2
    assert report["comparison"]["rejection_count_reduction"] == 13
    assert report["comparison"]["per_instance_margin_rejection_reduction"] == 1
    assert report["comparison"]["remaining_pairs_are_not_srdf_acm_disabled"]
    assert report["comparison"]["moveit_same_arm_state_reports_clear"]
    assert report["comparison"]["remaining_pairs_are_finger_independent"]
    observed = tuple(
        (item["link_a"], item["child_a"], item["link_b"], item["child_b"])
        for item in report["after"]["remaining_rejected_pairs"]
    )
    assert observed == REMAINING_REJECTED_PAIRS
    assert report["remaining_blockers"] == list(REMAINING_BLOCKERS)
    assert report["evidence_claims"]["permission_and_query_deployment_path_completed"]
    assert not report["evidence_claims"]["static_state_preflight_clear"]
    assert not report["evidence_claims"]["formal_execution_eligible"]
    assert not report["evidence_claims"]["physical_execution_performed"]
    assert not report["evidence_claims"]["teacher_used"]


@pytest.mark.skipif(
    not BEFORE.is_file() or not INTERMEDIATE.is_file() or not AFTER.is_file(),
    reason="external comparison evidence is absent",
)
def test_after_receipt_tamper_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "after.json"
    shutil.copyfile(AFTER, copied)
    value = json.loads(copied.read_text())
    value["evidence_claims"]["static_state_preflight_clear"] = True
    copied.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(ComparisonAuditFailure, match="SHA-256"):
        build_report(PROJECT_ROOT, BEFORE, INTERMEDIATE, copied)


def test_remaining_pairs_are_explicit_and_do_not_include_fingers() -> None:
    assert len(REMAINING_REJECTED_PAIRS) == 2
    assert all(
        "finger" not in left and "finger" not in right
        for left, _, right, _ in REMAINING_REJECTED_PAIRS
    )
    assert REMAINING_BLOCKERS[0] == "A3_STATIC_HOME_SELF_COLLISION_PREFLIGHT_REJECTED"
