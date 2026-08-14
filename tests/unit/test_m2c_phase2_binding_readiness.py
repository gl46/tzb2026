from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from m2c.check_adr0022_binding_addendum_readiness import main
from xh_agent.policy.qrm_lite.phase2_binding_readiness_v2 import (
    ADDENDUM_PATH,
    ARTIFACT_NAMES,
    FORMAL_RUNNER_PATH,
    REQUIRED_PROJECT_PATHS,
    DeploymentAssetBindingV3,
    EvidenceFileBindingV2,
    Phase2EvidenceIndexV2,
    ReadinessFailure,
    VerifiedPhase2EvidenceV2,
    _read_bound_artifacts,
    build_readiness_report,
    read_regular_file_once,
    render_binding_addendum,
    render_binding_proposal,
)


ROOT = Path(__file__).parents[2]


def test_missing_real_phase2_evidence_is_explicitly_blocked() -> None:
    report, verified = build_readiness_report(ROOT, None)

    assert report["schema_version"] == "M2CADR0024BindingAddendumReadinessV2"
    assert report["status"] == "BLOCKED"
    assert report["ready"] is False
    assert report["binding_addendum_generation_authorized"] is False
    assert report["source_binding_application_authorized"] is False
    assert verified is None
    assert report["blockers"] == [
        "PHASE2_EVIDENCE_INDEX_MISSING",
        "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
        "REAL_BOUND_PLAN_SYNTHESIS_BACKEND_NOT_BOUND",
        "REAL_ISAAC_EPISODE_LIFECYCLE_AND_CAPTURE_SOURCE_NOT_BOUND",
        "REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND",
        "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
        "REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING",
        "REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING",
        "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
    ]
    assert report["governance"]["two_active_source_bindings_changed"] is False
    assert report["governance"]["withdrawn_compatibility_bindings_remain_none"] is True
    assert report["governance"]["training_executed"] is False
    assert report["governance"]["formal_q_b_evaluation_executed"] is False


def test_generate_is_refused_and_creates_no_files_while_blocked(tmp_path: Path) -> None:
    addendum = tmp_path / "ADR-0024-PHASE2-BINDING-ADDENDUM.md"
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


def test_renderers_require_a_strict_verified_v2_receipt() -> None:
    with pytest.raises(ValidationError):
        render_binding_addendum({"fabricated": True})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        render_binding_proposal(  # type: ignore[arg-type]
            {"fabricated": True},
            addendum_sha256="a" * 64,
        )


def test_verified_renderers_propose_only_two_active_bindings() -> None:
    verified = VerifiedPhase2EvidenceV2(
        implementation_commit="b" * 40,
        container_image_digest="sha256:" + "c" * 64,
        transitive_import_manifest_sha256="d" * 64,
        formal_runner_binding=(FORMAL_RUNNER_PATH, "e" * 64),
        formal_evidence_sha256="f" * 64,
        challenge_consumption_receipt_sha256="1" * 64,
        run_id="formal-v4-fixture",
        challenge_nonce="2" * 64,
        challenge_consumption_id="3" * 64,
        matched_key="m2c-s4-smoke-fixture",
        scene_seed=1,
        failure_seed=2,
        sdf_sha256="4" * 64,
        supervision_sha256="5" * 64,
        final_task_success=False,
        strict_pure_model_success=False,
        exact_plan_skills_verified=(
            "GRASP",
            "LIFT",
            "MOVE",
            "PLACE",
            "RELEASE",
            "REOBSERVE",
            "REASSOCIATE_TARGET",
            "REGRASP",
        ),
        host_hmac_roles_verified=("NODE2_QWEN", "LABSERVER_ISAAC"),
    )

    addendum = render_binding_addendum(verified)
    proposal = json.loads(
        render_binding_proposal(
            verified,
            addendum_sha256=hashlib.sha256(addendum).hexdigest(),
        )
    )

    assert b"active-session B0 fallback and SSH/trusted-host signing" in addendum
    assert proposal["binding_addendum_path"] == ADDENDUM_PATH
    assert proposal["FORMAL_PHYSICAL_RUNNER_BINDING"] == [FORMAL_RUNNER_PATH, "e" * 64]
    assert proposal["FORMAL_DEPLOYMENT_CLOSURE_BINDING"] == [
        "b" * 40,
        "sha256:" + "c" * 64,
        "d" * 64,
    ]
    assert proposal["FROZEN_B0_RUNTIME_WRAPPER_BINDING"] is None
    assert proposal["OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING"] is None
    assert proposal["applied_to_source"] is False


def test_index_rejects_missing_artifact_role_before_reading_evidence() -> None:
    digest = "a" * 64
    project = [{"path": path, "sha256": digest} for path in sorted(REQUIRED_PROJECT_PATHS)]
    artifacts = {
        name: {"path": f"{name}.json", "sha256": digest}
        for name in ARTIFACT_NAMES - {"exact_plan_eight_skill_audit"}
    }
    with pytest.raises(ValueError, match="artifact set"):
        Phase2EvidenceIndexV2.model_validate(
            {
                "schema_version": "M2CADR0024Phase2EvidenceIndexV2",
                "status": "COLLECTED_REAL_ADR0024_PHASE2_EVIDENCE",
                "implementation_commit": "b" * 40,
                "container_image_digest": "sha256:" + "c" * 64,
                "project_bindings": project,
                "artifacts": artifacts,
                "source_bindings_independently_reviewed": True,
                "container_digest_observed_on_labserver": True,
                "no_binding_applied_by_collector": True,
                "b0_runtime_wrapper_present": False,
                "b0_runtime_fallback_invocation_allowed": False,
                "invalid_or_rejected_action_policy": "TERMINAL_NO_PHYSICAL_EXECUTION",
                "training_executed": False,
                "q_b_evaluation_executed": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        )


def test_v2_index_has_no_withdrawn_signature_or_b0_artifact_roles() -> None:
    schema = Phase2EvidenceIndexV2.model_json_schema()
    properties = schema["properties"]

    assert "node2_trust_root" not in properties
    assert "labserver_trust_root" not in properties
    assert "deployment_attestation" not in properties
    assert "b0_runtime_wrapper" not in properties
    assert not ARTIFACT_NAMES.intersection(
        {"b0_active_session_evidence", "b0_validation_audit", "deployment_attestation"}
    )
    assert {"node2_hmac_receipt", "labserver_hmac_receipt"}.issubset(ARTIFACT_NAMES)
    assert "deployment_asset_manifest" in ARTIFACT_NAMES
    assert "src/xh_agent/policy/qrm_lite/s4_entry_gate.py" in REQUIRED_PROJECT_PATHS


def test_deployment_asset_evidence_path_must_be_contained() -> None:
    with pytest.raises(ValueError, match="must be contained"):
        DeploymentAssetBindingV3(
            deployment_path="/World/scene.usd",
            evidence_path="../scene.usd",
            sha256="a" * 64,
            roles=("SCENE_USD",),
            kind="SCENE_ASSET",
        )


def test_evidence_paths_and_single_link_reads_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contained relative path"):
        EvidenceFileBindingV2(path="../escape", sha256="a" * 64)

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
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(ReadinessFailure, match="single-link|alias"):
        _read_bound_artifacts(
            tmp_path,
            {
                "first": EvidenceFileBindingV2(path=source.name, sha256=digest),
                "second": EvidenceFileBindingV2(path=alias.name, sha256=digest),
            },
        )


def test_readiness_report_rejects_a_symlinked_evidence_index(tmp_path: Path) -> None:
    target = tmp_path / "index-target.json"
    link = tmp_path / "index.json"
    target.write_bytes(b"{}\n")
    link.symlink_to(target)

    report, verified = build_readiness_report(ROOT, link)

    assert verified is None
    assert report["ready"] is False
    assert report["blockers"] == [
        "PHASE2_EVIDENCE_FAILED_CLOSED:ReadinessFailure:Phase-2 evidence index may not be a symlink"
    ]
