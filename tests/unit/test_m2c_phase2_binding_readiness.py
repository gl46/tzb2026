from __future__ import annotations

import json
from pathlib import Path

import pytest

from m2c.check_adr0022_binding_addendum_readiness import main
from xh_agent.policy.qrm_lite.phase2_binding_readiness_v1 import (
    ARTIFACT_NAMES,
    EvidenceFileBindingV1,
    Phase2EvidenceIndexV1,
    ReadinessFailure,
    _read_bound_files,
    build_readiness_report,
    read_regular_file_once,
    render_binding_addendum,
    render_binding_proposal,
)


ROOT = Path(__file__).parents[2]


def test_missing_real_phase2_evidence_is_explicitly_blocked() -> None:
    report, verified = build_readiness_report(ROOT, None)

    assert report["status"] == "BLOCKED"
    assert report["ready"] is False
    assert report["binding_addendum_generation_authorized"] is False
    assert report["source_binding_application_authorized"] is False
    assert verified is None
    assert report["blockers"] == [
        "PHASE2_EVIDENCE_INDEX_MISSING",
        "REAL_EXACT_PLAN_EIGHT_SKILL_RECEIPTS_MISSING",
        "FORMAL_V4_BOUND_PLAN_PROVIDER_EVIDENCE_MISSING",
        "SESSION_BOUND_STARTUP_AND_DEPLOYMENT_EVIDENCE_MISSING",
        "NODE2_LABSERVER_HOST_HMAC_RECEIPTS_MISSING",
        "CONTAINER_TRANSITIVE_IMPORT_CLOSURE_MISSING",
        "PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE",
    ]
    assert report["governance"]["four_source_bindings_changed"] is False
    assert report["governance"]["training_executed"] is False
    assert report["governance"]["formal_q_b_evaluation_executed"] is False


def test_generate_is_refused_and_creates_no_files_while_blocked(tmp_path: Path) -> None:
    addendum = tmp_path / "ADR-0022-BINDING-ADDENDUM.md"
    proposal = tmp_path / "m2c_s4_unlock_bindings.json"

    with pytest.raises(ReadinessFailure, match="BLOCKED"):
        main(
            [
                "--project-root",
                str(ROOT),
                "--generate",
                "--addendum-output",
                str(addendum),
                "--binding-proposal-output",
                str(proposal),
            ]
        )

    assert not addendum.exists()
    assert not proposal.exists()


def test_historical_renderers_cannot_bypass_v2_migration_blocker() -> None:
    with pytest.raises(ReadinessFailure, match="ADR0024_V2_MIGRATION_INCOMPLETE"):
        render_binding_addendum({"fabricated": True})
    with pytest.raises(ReadinessFailure, match="ADR0024_V2_MIGRATION_INCOMPLETE"):
        render_binding_proposal({"fabricated": True}, addendum_sha256="a" * 64)


def test_index_rejects_missing_artifact_role_before_reading_evidence() -> None:
    digest = "a" * 64
    common = {"path": "evidence.json", "sha256": digest}
    project = {
        "formal_runner": {
            "path": "scripts/m2c/run_formal_model_owned_chain.py",
            "sha256": digest,
        },
        "primitive_bundle": {
            "path": "src/xh_agent/policy/qrm_lite/exact_plan_primitive_bundle_v1.py",
            "sha256": digest,
        },
        "b0_runtime_wrapper": {
            "path": "src/xh_agent/policy/qrm_lite/frozen_b0_fallback_wrapper_v1.py",
            "sha256": digest,
        },
        "offline_wire_verifier": {
            "path": "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py",
            "sha256": digest,
        },
        "node2_trust_root": {
            "path": "configs/m2c_phase2_node2_allowed_signers",
            "sha256": digest,
        },
        "labserver_trust_root": {
            "path": "configs/m2c_phase2_labserver_allowed_signers",
            "sha256": digest,
        },
    }
    artifacts = {name: common for name in ARTIFACT_NAMES - {"b0_validation_audit"}}
    with pytest.raises(ValueError, match="artifact set"):
        Phase2EvidenceIndexV1.model_validate(
            {
                "schema_version": "M2CADR0022Phase2EvidenceIndexV1",
                "status": "COLLECTED_REAL_PHASE2_EVIDENCE",
                "implementation_commit": "b" * 40,
                "container_image_digest": "sha256:" + "c" * 64,
                **project,
                "artifacts": artifacts,
                "deployment_attestation": common,
                "source_bindings_independently_reviewed": True,
                "container_digest_observed_on_labserver": True,
                "no_binding_applied_by_collector": True,
                "training_executed": False,
                "q_b_evaluation_executed": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        )


def test_evidence_paths_and_single_link_reads_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contained relative path"):
        EvidenceFileBindingV1(path="../escape", sha256="a" * 64)

    source = tmp_path / "source"
    alias = tmp_path / "alias"
    source.write_bytes(json.dumps({"status": "fake"}).encode())
    alias.hardlink_to(source)
    with pytest.raises(ReadinessFailure, match="single-link"):
        read_regular_file_once(source)


def test_two_evidence_roles_may_not_alias_one_inode(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    alias = tmp_path / "alias.json"
    source.write_bytes(b"{}\n")
    alias.hardlink_to(source)
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()

    with pytest.raises(ReadinessFailure, match="single-link|alias"):
        _read_bound_files(
            tmp_path,
            {
                "first": EvidenceFileBindingV1(path=source.name, sha256=digest),
                "second": EvidenceFileBindingV1(path=alias.name, sha256=digest),
            },
        )
