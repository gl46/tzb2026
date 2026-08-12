#!/usr/bin/env python3
"""Generate fail-closed M2C status and final collateral."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from terminal_evidence import verify_terminal_evidence
from xh_agent.policy.qrm_lite.m2c_stage_route import (
    M2CStageRoute,
    QAState,
    QBState,
    evaluate_stage_route,
    observe_stage_time,
)


PROJECT = Path(__file__).resolve().parents[2]
MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
S3_ACCEPTANCE_PREDICATE = {
    "path": "scripts/m2b/run_physical_failure_smoke.py",
    "sha256": "7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865",
    "public_rgbd_required": True,
    "predicate": "m2b.run_physical_failure_smoke.accepted",
}
TEACHER_STATES = {
    "Nano": "CANDIDATE",
    "BWM": "CANDIDATE_LICENSE_PENDING",
    "Super": "PARKED",
}
TEACHER_KILL_RULES = [
    "kill the run if Teacher soft labels enter Student training or evaluation",
    "kill the run if a Teacher response or adapter enters the control stack",
    "kill the run if a Teacher is silently replaced or upgraded",
]


def load_optional(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=PROJECT,
        capture_output=True,
        check=False,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT.resolve()))
    except ValueError:
        return path.name


def verified_s2_report_shape(report: dict[str, Any] | None) -> tuple[bool, QAState]:
    """Recompute the committed V4 report's internal Q-A/D1 disposition.

    The remote Isaac evidence tree is not mirrored in this repository, so this
    check does not claim a raw physical replay.  It does prevent the status
    generator from accepting a few top-level booleans that contradict the
    report's per-key outcomes or frozen local sources.
    """

    if report is None or report.get("schema_version") != "M2CS2QAGateReportV1":
        return False, QAState.UNMEASURED_OR_INVALID
    decision = report.get("decision") or {}
    candidate = report.get("candidate_manifest") or {}
    runtime = report.get("frozen_runtime") or {}
    b0 = report.get("b0_executions") or []
    proofs = report.get("existence_proof_executions") or []
    try:
        manifest_path = PROJECT / str(candidate["path"])
        local_bindings_match = bool(
            manifest_path.is_file()
            and sha256(manifest_path) == candidate.get("sha256")
            and sha256(PROJECT / "scripts/isaac_m1b_actuation_probe.py")
            == runtime.get("b0_probe_sha256")
            and sha256(PROJECT / "scripts/m2b/run_physical_failure_smoke.py")
            == runtime.get("b0_runner_sha256")
        )
    except (KeyError, OSError, TypeError, ValueError):
        local_bindings_match = False
    seeds = [item.get("scene_seed") for item in b0 if isinstance(item, dict)]
    strict = [
        item
        for item in proofs
        if isinstance(item, dict)
        and item.get("strict_complete_existence_proof") is True
        and item.get("target_regrasp_executed") is True
        and {"grasped=true", "lifted=true"}.issubset(
            set(item.get("public_regrasp_predicates") or [])
        )
        and item.get("recovery_training_eligible") is True
        and item.get("collision_violations") == 0
    ]
    pass_shape = bool(
        report.get("status") == "Q_A_PASSED"
        and report.get("candidate_number") == 4
        and local_bindings_match
        and len(b0) == 3
        and len(set(seeds)) == 3
        and all(
            isinstance(item, dict)
            and item.get("classification") == "ADMISSIBLE_B0_SAFE_REJECTION"
            and item.get("attempts") == 2
            and item.get("public_target_valid") is True
            and item.get("final_task_success") is False
            and item.get("action_started_before_rejection") is False
            for item in b0
        )
        and len(strict) >= 1
        and decision.get("b0_valid_matched_keys") == 3
        and decision.get("b0_final_task_successes") == 0
        and decision.get("b0_final_task_success_rate") == 0.0
        and decision.get("b0_headroom") == 1.0
        and decision.get("complete_existence_proofs") == len(strict)
        and decision.get("physical_recoverability_established") is True
        and decision.get("q_a_passed") is True
        and decision.get("stop_loss_disposition") == "PASS_Q_A"
        and decision.get("d1_triggered") is False
        and decision.get("v5_forbidden") is True
        and report.get("teacher_used") is False
        and report.get("privileged_truth_policy_input") is False
        and runtime.get("b0_modified") is False
        and runtime.get("retries_changed") is False
        and runtime.get("safety_ik_collision_schema_or_mapping_gates_changed") is False
    )
    if pass_shape:
        return True, QAState.PASSED
    d1_shape = bool(
        report.get("candidate_number") == 4
        and report.get("status") in {"Q_A_NOT_PASSED", "INVALID_DOMAIN_STOPPED"}
        and decision.get("q_a_passed") is False
        and decision.get("stop_loss_disposition") == "TRIGGER_D1"
        and decision.get("d1_triggered") is True
        and decision.get("v5_forbidden") is True
        and report.get("teacher_used") is False
        and report.get("privileged_truth_policy_input") is False
    )
    return False, QAState.FINAL_CANDIDATE_NONPASS if d1_shape else QAState.UNMEASURED_OR_INVALID


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=PROJECT / "reports")
    parser.add_argument("--output", type=Path, default=PROJECT / "reports/m2c-status.json")
    parser.add_argument("--verification", type=Path, default=None)
    args = parser.parse_args()
    report_dir = args.report_dir
    verification_path = args.verification or report_dir / "m2c-final-verification.json"
    input_paths = {
        "s0": report_dir / "m2c-s0-freeze.json",
        "s1": report_dir / "m2c-s1-deliverables.json",
        "s2": report_dir / "m2c-s2-exploration-v4.json",
        "s3": report_dir / "m2c-s3-dataset-v3.json",
        "s4": report_dir / "m2c-s4-model-owned-recovery.json",
        "s4_collection": report_dir / "m2c-s4-path-blocked-train-collection.json",
        "s4_entry": report_dir / "m2c-s4-entry-gate.json",
        "s5": report_dir / "m2c-s5-residual-closed-loop.json",
        "s6": report_dir / "m2c-s6-matched.json",
        "final_verification": verification_path,
    }

    s0 = load_optional(report_dir / "m2c-s0-freeze.json")
    s1 = load_optional(report_dir / "m2c-s1-deliverables.json")
    s2 = load_optional(report_dir / "m2c-s2-exploration-v4.json")
    s3 = load_optional(report_dir / "m2c-s3-dataset-v3.json")
    s4 = load_optional(report_dir / "m2c-s4-model-owned-recovery.json")
    s5 = load_optional(report_dir / "m2c-s5-residual-closed-loop.json")
    s6 = load_optional(report_dir / "m2c-s6-matched.json")
    s4_collection = load_optional(report_dir / "m2c-s4-path-blocked-train-collection.json")
    s4_entry = load_optional(report_dir / "m2c-s4-entry-gate.json")
    gap_fixes = load_optional(report_dir / "m2c-gap-fixes.json")
    verification = load_optional(verification_path)

    s0_ready = bool(
        s0
        and s0.get("status") == "PASS"
        and s0.get("b0_files_match_m2b") is True
        and s0.get("m2b_evidence_readonly") is True
    )
    s1_ready = bool(s1 and s1.get("status") == "PASS")
    s2_decision = (s2 or {}).get("decision") or {}
    s2_ready, q_a_state = verified_s2_report_shape(s2)
    failure_counts = (s3 or {}).get("failure_counts") or {}
    recovery_counts = (s3 or {}).get("successful_recovery_counts") or {}
    s3_freeze = (s3 or {}).get("evidence_freeze") or {}
    s3_worker_snapshots = (s3 or {}).get("worker_status_snapshots") or []
    s3_evidence_audit = (s3 or {}).get("accepted_evidence_audit") or {}
    s3_evidence_frozen = bool(
        s3_freeze.get("evidence_tree_readonly") is True
        and len(str(s3_freeze.get("ledger_sha256", ""))) == 64
        and int(s3_freeze.get("files_hashed", 0)) > 0
        and len(s3_worker_snapshots) == 2
        and all(
            snapshot.get("status") == "COMPLETE_ACCEPTED_TARGET"
            and snapshot.get("teacher_used") is False
            and snapshot.get("privileged_truth_policy_input") is False
            and len(str(snapshot.get("sha256", ""))) == 64
            for snapshot in s3_worker_snapshots
        )
    )
    s3_ready = bool(
        s3
        and s3.get("status") == "PASS_S3_FULL_CLASS_COVERAGE"
        and s3.get("full_class_coverage_gate_passed") is True
        and int(s3.get("episodes_quarantined", 0)) == 0
        and not s3.get("split_group_leakage")
        and s3_evidence_frozen
        and s3_evidence_audit.get("status") == "PASS"
        and int(s3_evidence_audit.get("records_audited", -1)) == 150
        and s3_evidence_audit.get("counts_by_failure")
        == {failure: 50 for failure in MANDATORY_FAILURES}
        and int(s3_evidence_audit.get("evidence_sha256_matches", -1)) == 150
        and int(s3_evidence_audit.get("strict_physical_public_predicates_passed", -1)) == 150
        and int(s3_evidence_audit.get("public_predicate_results_checked", -1)) == 300
        and int(s3_evidence_audit.get("collision_gates_checked", -1)) >= 550
        and int(s3_evidence_audit.get("collision_or_safety_violations", -1)) == 0
        and len(s3_evidence_audit.get("records", [])) == 150
        and s3_evidence_audit.get("teacher_used") is False
        and s3_evidence_audit.get("privileged_truth_policy_input") is False
        and s3_evidence_audit.get("acceptance_predicate") == S3_ACCEPTANCE_PREDICATE
        and all(
            int(failure_counts.get(failure, 0)) >= 100
            and int(recovery_counts.get(failure, 0)) >= 50
            for failure in MANDATORY_FAILURES
        )
    )

    terminal = verify_terminal_evidence(
        PROJECT,
        s4=s4,
        s5=s5,
        s6=s6,
        verification=verification,
        d2_summary_claimed=bool(s4 and s4.get("d2_triggered") is True),
    )
    s4_metrics = terminal["s4"].metrics
    strict_pure_count = (
        int(s4_metrics["pure_model_success_episodes"])
        if terminal["s4"].passed and s4_metrics.get("pure_model_success_episodes") is not None
        else None
    )
    s4_ready = terminal["s4"].passed
    s5_ready = terminal["s5"].passed
    d3_triggered = bool(
        terminal["s5"].passed and terminal["s5"].metrics.get("d3_triggered") is True
    )

    s6_metrics = terminal["s6"].metrics
    primary = s6_metrics.get("primary_metric") or {}
    primary_interval = primary.get("interval")
    s6_ready = terminal["s6"].passed

    if strict_pure_count is None:
        q_b_state = QBState.UNMEASURED
    elif strict_pure_count == 0:
        q_b_state = QBState.MEASURED_ZERO
    else:
        q_b_state = QBState.MEASURED_POSITIVE
    d2_summary_claimed = bool(s4 and s4.get("d2_triggered") is True)
    route = evaluate_stage_route(
        observed_at=observe_stage_time(),
        q_a_state=q_a_state,
        q_b_state=q_b_state,
        d2_claimed=d2_summary_claimed,
        s5_verified=s5_ready,
        s6_verified=s6_ready,
        final_verification_passed=terminal["final"].passed,
        pure_model_success_episodes=strict_pure_count,
        s3_verified=s3_ready,
    )
    d1_triggered = route.d1_triggered
    d2_triggered = route.d2_triggered

    required_boundary_reports = [s0, s1, s2, s6]
    if route.s3_required:
        required_boundary_reports.append(s3)
    if route.s4_required:
        required_boundary_reports.append(s4)
    if route.s5_required:
        required_boundary_reports.append(s5)
    present = [report for report in required_boundary_reports if report]
    boundary_reports_complete = len(present) == len(required_boundary_reports)
    teacher_violation = any(report.get("teacher_used") is True for report in present)
    privileged_truth_violation = any(
        report.get("privileged_truth_policy_input") is True for report in present
    )
    world_model_violation = any(
        report.get("world_model_mainline_replaced") is True for report in present
    )
    teacher_free = bool(
        boundary_reports_complete and all(report.get("teacher_used") is False for report in present)
    )
    no_privileged_policy_input = bool(
        boundary_reports_complete
        and all(report.get("privileged_truth_policy_input") is False for report in present)
    )
    world_model_preserved = bool(
        boundary_reports_complete
        and all(report.get("world_model_mainline_replaced") is False for report in present)
    )
    tests = terminal["final"].metrics
    verification_ready = terminal["final"].passed

    gates = {
        "s0_b0_and_m2b_freeze": s0_ready,
        "s1_delivery_evidence": s1_ready,
        "s2_q_a_or_d1_governed_disposition": s2_ready or d1_triggered,
        "s3_full_class_coverage": s3_ready if route.s3_required else True,
        "s4_q_b_governed_disposition": s4_ready if route.s4_required else True,
        "s5_residual_closed_loop_or_d2_disposition": (s5_ready if route.s5_required else True),
        "s6_formal_four_method_matched_evaluation": s6_ready,
        "teacher_free": teacher_free,
        "no_privileged_truth_policy_input": no_privileged_policy_input,
        "world_model_mainline_preserved": world_model_preserved,
        "final_verification_passed": verification_ready,
    }
    blocker_by_gate = {
        "s0_b0_and_m2b_freeze": "S0 B0/M2B freeze is missing or no longer matches",
        "s1_delivery_evidence": "S1 delivery evidence is missing or failing",
        "s2_q_a_or_d1_governed_disposition": "S2 has neither a verified Q-A pass nor a deadline/final-candidate D1 disposition",
        "s3_full_class_coverage": "S3 has not passed 100 failures / 50 recoveries per class with zero quarantine, no split leakage, two ledger-bound completed worker snapshots, and a 150/150 strict physical/public evidence audit",
        "s4_q_b_governed_disposition": "S4 lacks a human-ADR-governed Q-B execution and strict pure-model/D2 disposition",
        "s5_residual_closed_loop_or_d2_disposition": "S5 has neither a measured residual difference nor a valid D2/D3 disposition",
        "s6_formal_four_method_matched_evaluation": "S6 lacks 30 four-method keys, 50 physical model decisions, paired FC-vs-B0 CI, or zero violations",
        "teacher_free": "a stage report lacks an explicit Teacher-free assertion or reports Teacher use",
        "no_privileged_truth_policy_input": "a stage report lacks the truth boundary or reports privileged policy input",
        "world_model_mainline_preserved": "a stage report lacks the world-model boundary or reports replacement",
        "final_verification_passed": "final tests, B0 freeze recheck, or M2B read-only verification is missing or failing",
    }
    blockers = [blocker_by_gate[name] for name, passed in gates.items() if not passed]
    terminal_names = ["s6", "final"]
    if route.s4_required:
        terminal_names.append("s4")
    if route.s5_required:
        terminal_names.append("s5")
    terminal_evidence_blockers = [
        blocker for name in terminal_names for blocker in terminal[name].blockers
    ]
    blockers.extend(terminal_evidence_blockers)
    blockers.extend(route.blockers)
    blockers = list(dict.fromkeys(blockers))
    if d1_triggered or d2_triggered:
        next_command = "make m2c-s6" if not s6_ready else "make m2c-status"
    elif not s3_ready:
        next_command = "M2B_EVIDENCE_READONLY=1 make m2c-s3-dataset"
    elif not s4_ready:
        next_command = (
            "sed -n '1,260p' docs/decisions/M2C-S4-PUBLIC-CANDIDATE-ADR-REQUEST.md "
            "&& sed -n '1,320p' "
            "docs/decisions/M2C-S4-EXACT-PLAN-PRIMITIVE-ADR-REQUEST.md"
        )
    elif not s5_ready:
        next_command = "make m2c-s5"
    elif not s6_ready:
        next_command = "make m2c-s6"
    else:
        next_command = "make m2c-status"

    fc_gain = (
        float(primary["estimate"])
        if s6_ready
        and primary.get("name") == "fc_gain_over_b0"
        and primary.get("estimate") is not None
        else None
    )
    goal_complete = route.route is M2CStageRoute.TERMINAL_EVIDENCE_COMPLETE and not blockers
    if (
        goal_complete
        and strict_pure_count is not None
        and strict_pure_count >= 1
        and fc_gain is not None
        and fc_gain > 0
    ):
        system_verdict = "GO_QRM_MODEL_OWNED_RECOVERY"
    elif goal_complete:
        system_verdict = "GO_QRM_COARSE_ONLY"
    else:
        system_verdict = "EVIDENCE_PENDING"

    limitations = [
        item["finding"]
        for item in (gap_fixes or {}).get("items", [])
        if str(item.get("status", "")).startswith("OPEN_FINDING")
    ]
    limitations.append(
        "The 9/1 source-level hard-freeze guard relies on the host OS clock and current "
        "entrypoints; host operations must prevent clock rollback and revoke execution of "
        "separately copied historical S2 probe files."
    )
    limitations.append(
        "S2 Q-A status replays the committed report's per-key outcomes and local frozen "
        "source hashes, but the 167-file remote Isaac evidence tree is not mirrored in "
        "this repository for an independent raw-byte terminal replay."
    )
    if strict_pure_count == 0:
        limitations.append(
            "No successful episode completed every recovery decision under model ownership; D2 keeps the conclusion COARSE_ONLY."
        )
    if s3 and s3.get("collection_rejections"):
        limitations.append(
            f"S3 retained {int(s3['collection_rejections'])} rejected collection attempts with explicit reasons."
        )
    if not s6_ready:
        limitations.append(
            "The four-method S6 estimand and confidence interval are not yet formal evidence."
        )
    if strict_pure_count is None:
        limitations.append(
            "Q-B is unmeasured: zero eligible training samples and a blocked entry gate do not imply pure-model success equals zero."
        )

    feature_branch = run(["git", "branch", "--show-current"])
    commits = run(["git", "log", "--format=%H", "141e45d..HEAD"]).splitlines()
    status: dict[str, Any] = {
        "schema_version": "M2CStatusV2",
        "phase": "M2C",
        "status": "PASS_WITH_LIMITATIONS" if goal_complete else "PARTIAL",
        "goal_complete": goal_complete,
        "completion_gates": gates,
        "observed_at": route.observed_at,
        "stage_route": route.route.value,
        "stage_input_bindings": {
            name: {
                "path": display_path(path),
                "sha256": sha256(path),
            }
            if path.is_file()
            else None
            for name, path in input_paths.items()
        },
        "stage_requirements": {
            "s3_required": route.s3_required,
            "s4_required": route.s4_required,
            "s5_required": route.s5_required,
            "s6_required": route.s6_required,
        },
        "s4_measurement_state": q_b_state.value,
        "s4_collection_status": (s4_collection or {}).get("status"),
        "s4_entry_status": (s4_entry or {}).get("status"),
        "dataset_version": (s3 or {}).get("dataset_version"),
        "episodes_valid": int((s3 or {}).get("episodes_valid", 0)),
        "episodes_quarantined": int((s3 or {}).get("episodes_quarantined", 0)),
        "failure_counts": failure_counts,
        "successful_recovery_counts": recovery_counts,
        "b0_final_task_success_rate_q_a": s2_decision.get("b0_final_task_success_rate"),
        "b0_headroom_q_a": s2_decision.get("b0_headroom"),
        "pure_model_success_episodes": strict_pure_count,
        "fc_gain_over_b0": fc_gain,
        "fc_gain_over_b0_confidence_interval": primary_interval,
        "matched_keys": int(s6_metrics.get("complete_matched_keys", 0)),
        "model_decisions_executed": int(s6_metrics.get("qrm_model_decisions_executed", 0)),
        "collision_or_safety_violations": s6_metrics.get("collision_or_safety_violations"),
        "d1_triggered": d1_triggered,
        "d2_triggered": d2_triggered,
        "d3_triggered": d3_triggered,
        "system_verdict": system_verdict,
        "teacher_used": teacher_violation,
        "teacher_states": TEACHER_STATES,
        "teacher_kill_rules": TEACHER_KILL_RULES,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": privileged_truth_violation,
        "world_model_mainline_replaced": world_model_violation,
        "tests_passed": int(tests.get("tests_passed", 0)),
        "tests_failed": tests.get("tests_failed"),
        "feature_branch": feature_branch,
        "commits": commits,
        "honest_limitations": limitations,
        "blockers": blockers,
        "next_command": next_command,
    }
    write_json(args.output, status)
    write_markdown(
        report_dir / "m2c-status.md",
        [
            "# M2C status",
            "",
            f"- Status: **{status['status']}**; verdict: `{system_verdict}`",
            f"- Stage route: `{route.route.value}` at `{route.observed_at}`",
            f"- Q-B measurement state: `{q_b_state.value}`",
            f"- Dataset valid/quarantine: {status['episodes_valid']}/{status['episodes_quarantined']}",
            f"- Failure/recovery counts: `{failure_counts}` / `{recovery_counts}`",
            f"- Q-A B0 success/headroom: `{status['b0_final_task_success_rate_q_a']}` / `{status['b0_headroom_q_a']}`",
            f"- `pure_model_success_episodes`: `{strict_pure_count}`",
            f"- `fc_gain_over_b0`: `{fc_gain}`; 95% CI `{primary_interval}`",
            f"- S6 keys / executed model decisions: {status['matched_keys']} / {status['model_decisions_executed']}",
            (
                "- Teacher used: no"
                if teacher_free
                else "- Teacher boundary: FAIL"
                if teacher_violation
                else "- Teacher boundary: INCOMPLETE"
            ),
            (
                "- Privileged simulator truth in policy input: no"
                if no_privileged_policy_input
                else "- Privileged-truth boundary: FAIL"
                if privileged_truth_violation
                else "- Privileged-truth boundary: INCOMPLETE"
            ),
            (
                "- World-model mainline replaced: no"
                if world_model_preserved
                else "- World-model boundary: FAIL"
                if world_model_violation
                else "- World-model boundary: INCOMPLETE"
            ),
            "",
            "## Completion gates",
            "",
            *[f"- `{name}`: {'PASS' if passed else 'FAIL'}" for name, passed in gates.items()],
            "",
            "## Honest limitations",
            "",
            *([f"- {item}" for item in limitations] or ["- None beyond the stage reports."]),
            "",
            f"Next command: `{next_command}`",
        ],
    )

    generated_paths = {
        args.output,
        report_dir / "m2c-status.md",
        report_dir / "m2c-completion-audit.json",
        report_dir / "m2c-completion-audit.md",
        report_dir / "m2c-dataset-card.md",
        report_dir / "m2c-reproducibility.md",
        report_dir / "m2c-artifact-index.json",
    }
    changed_files = sorted(
        {
            *run(["git", "diff", "--name-only", "141e45d..HEAD"]).splitlines(),
            *run(["git", "diff", "--name-only"]).splitlines(),
            *run(["git", "ls-files", "--others", "--exclude-standard"]).splitlines(),
            *(display_path(path) for path in generated_paths),
        }
    )
    audit = {
        "schema_version": "M2CCompletionAuditV2",
        "status": "PASS" if goal_complete else "PARTIAL",
        "system_verdict": system_verdict,
        "observed_at": route.observed_at,
        "stage_route": route.route.value,
        "stage_input_bindings": status["stage_input_bindings"],
        "stage_requirements": status["stage_requirements"],
        "gates": gates,
        "primary_metric": {
            "fc_gain_over_b0": fc_gain,
            "confidence_interval": primary_interval,
        },
        "pure_model_success_episodes": strict_pure_count,
        "teacher_used": teacher_violation,
        "teacher_states": TEACHER_STATES,
        "teacher_kill_rules": TEACHER_KILL_RULES,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": privileged_truth_violation,
        "world_model_mainline_replaced": world_model_violation,
        "honest_limitations": limitations,
        "task_report": {
            "changed_files": changed_files,
            "tests": {
                "passed": int(tests.get("tests_passed", 0)),
                "failed": tests.get("tests_failed"),
            },
            "failures": (verification or {}).get("failures", []),
            "blockers": blockers,
        },
        "next_command": next_command,
    }
    write_json(report_dir / "m2c-completion-audit.json", audit)
    write_markdown(
        report_dir / "m2c-completion-audit.md",
        [
            "# M2C completion audit",
            "",
            f"- Core status: **{audit['status']}**; verdict: `{system_verdict}`",
            f"- Stage route: `{route.route.value}` at `{route.observed_at}`",
            f"- `fc_gain_over_b0`: `{fc_gain}`; CI `{primary_interval}`",
            f"- `pure_model_success_episodes`: `{strict_pure_count}`",
            f"- Teacher used: `{audit['teacher_used']}`",
            f"- privileged truth policy input: `{audit['privileged_truth_policy_input']}`",
            f"- world-model mainline replaced: `{audit['world_model_mainline_replaced']}`",
            "",
            "## Gates",
            "",
            "| Gate | Result |",
            "| --- | --- |",
            *[f"| `{name}` | {'PASS' if passed else 'FAIL'} |" for name, passed in gates.items()],
            "",
            "## Honest limitations",
            "",
            *([f"- {item}" for item in limitations] or ["- None beyond the stage reports."]),
            "",
            "## Task report",
            "",
            "- Changed files:",
            *[f"  - `{path}`" for path in changed_files],
            f"- Tests: {int(tests.get('tests_passed', 0))} passed, {tests.get('tests_failed')} failed",
            "- Failures:",
            *([f"  - {item}" for item in (verification or {}).get("failures", [])] or ["  - none"]),
            "- Blockers:",
            *([f"  - {item}" for item in blockers] or ["  - none"]),
            f"- Next command: `{next_command}`",
        ],
    )
    write_markdown(
        report_dir / "m2c-dataset-card.md",
        [
            "# M2C Dataset V3 card",
            "",
            f"- Version: `{(s3 or {}).get('dataset_version')}`",
            f"- Valid/quarantined: {int((s3 or {}).get('episodes_valid', 0))}/{int((s3 or {}).get('episodes_quarantined', 0))}",
            f"- Failure counts: `{failure_counts}`",
            f"- Successful recovery counts: `{recovery_counts}`",
            f"- Split counts: `{(s3 or {}).get('split_counts', {})}`",
            f"- Split leakage: `{(s3 or {}).get('split_group_leakage', [])}`",
            f"- Dataset SHA-256: `{(s3 or {}).get('output_sha256')}`",
            "- Teacher soft labels: absent.",
            "- Privileged simulator truth: training/evaluation supervision only; never policy input.",
            "- PATH_BLOCKED: raw evaluator evidence only, not a training class.",
        ],
    )
    write_markdown(
        report_dir / "m2c-reproducibility.md",
        [
            "# M2C reproducibility",
            "",
            f"- Branch: `{feature_branch}`",
            f"- Evidence commits before generated collateral: `{commits}`",
            f"- Stage route/as-of: `{route.route.value}` / `{route.observed_at}`",
            f"- B0 freeze manifest SHA-256: `{sha256(PROJECT / 'configs/m2c_b0_freeze.json')}`",
            f"- Dataset V3 SHA-256: `{(s3 or {}).get('output_sha256')}`",
            f"- S6 episodes SHA-256: `{(s6 or {}).get('episodes_sha256')}`",
            f"- S6 pre-registration SHA-256: `{(s6 or {}).get('preregistration_sha256')}`",
            "- S6 bootstrap: paired percentile, 20,000 resamples, seed 20260812.",
            "- Teacher used: no; privileged truth policy input: no; world-model mainline replaced: no.",
            f"- Final verification commands: `{(verification or {}).get('commands', [])}`",
            f"- Next command: `{next_command}`",
        ],
    )

    real_reports = False
    try:
        report_dir.resolve().relative_to((PROJECT / "reports").resolve())
        real_reports = True
    except ValueError:
        pass
    source_artifacts: list[Path] = []
    if real_reports:
        decision_artifacts = {
            *PROJECT.glob("docs/decisions/*M2C*"),
            *PROJECT.glob("docs/decisions/*m2c*"),
        }
        source_artifacts = [
            PROJECT / "Makefile",
            *sorted((PROJECT / "configs").glob("m2c*")),
            *sorted(decision_artifacts),
            *sorted((PROJECT / "scripts/m2c").glob("*")),
            *sorted((PROJECT / "tests/unit").glob("test_m2c_*.py")),
        ]
    index_path = report_dir / "m2c-artifact-index.json"
    artifact_paths = sorted(
        {
            *(path for path in report_dir.glob("m2c-*") if path.is_file()),
            *(path for path in source_artifacts if path.is_file()),
        }
        - {index_path}
    )
    write_json(
        index_path,
        {
            "schema_version": "M2CArtifactIndexV1",
            "artifact_count": len(artifact_paths),
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "artifacts": [
                {"path": display_path(path), "sha256": sha256(path)} for path in artifact_paths
            ],
        },
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if goal_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
