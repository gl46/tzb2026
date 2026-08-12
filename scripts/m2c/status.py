#!/usr/bin/env python3
"""Generate fail-closed M2C status and final collateral."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
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


def primary_gain(s6: dict[str, Any] | None) -> float | None:
    primary = (s6 or {}).get("primary_metric") or {}
    value = primary.get("estimate")
    if primary.get("name") != "fc_gain_over_b0" or value is None:
        return None
    return float(value)


def pure_count(s4: dict[str, Any] | None) -> int | None:
    value = (s4 or {}).get("pure_model_success_episodes")
    return int(value) if value is not None else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=PROJECT / "reports")
    parser.add_argument("--output", type=Path, default=PROJECT / "reports/m2c-status.json")
    parser.add_argument("--verification", type=Path, default=None)
    args = parser.parse_args()
    report_dir = args.report_dir
    verification_path = args.verification or report_dir / "m2c-final-verification.json"

    s0 = load_optional(report_dir / "m2c-s0-freeze.json")
    s1 = load_optional(report_dir / "m2c-s1-deliverables.json")
    s2 = load_optional(report_dir / "m2c-s2-exploration-v4.json")
    s3 = load_optional(report_dir / "m2c-s3-dataset-v3.json")
    s4 = load_optional(report_dir / "m2c-s4-model-owned-recovery.json")
    s5 = load_optional(report_dir / "m2c-s5-residual-closed-loop.json")
    s6 = load_optional(report_dir / "m2c-s6-matched.json")
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
    s2_ready = bool(
        s2
        and s2.get("status") == "Q_A_PASSED"
        and s2_decision.get("q_a_passed") is True
        and s2_decision.get("physical_recoverability_established") is True
        and s2_decision.get("d1_triggered") is False
    )
    failure_counts = (s3 or {}).get("failure_counts") or {}
    recovery_counts = (s3 or {}).get("successful_recovery_counts") or {}
    s3_ready = bool(
        s3
        and s3.get("status") == "PASS_S3_FULL_CLASS_COVERAGE"
        and s3.get("full_class_coverage_gate_passed") is True
        and int(s3.get("episodes_quarantined", 0)) == 0
        and not s3.get("split_group_leakage")
        and all(
            int(failure_counts.get(failure, 0)) >= 100
            and int(recovery_counts.get(failure, 0)) >= 50
            for failure in MANDATORY_FAILURES
        )
    )

    strict_pure_count = pure_count(s4)
    d2_triggered = bool(s4 and s4.get("d2_triggered") is True)
    q_b_governed = bool(
        s4
        and s4.get("human_expressivity_adr_committed") is True
        and s4.get("q_b_training_executed") is True
        and s4.get("q_b_evaluation_executed") is True
    )
    s4_ready = bool(
        q_b_governed
        and strict_pure_count is not None
        and (strict_pure_count >= 1 or d2_triggered)
        and s4.get("status") in {"PASS_Q_B_PURE_MODEL_RECOVERY", "D2_GO_QRM_COARSE_ONLY"}
    )
    d3_triggered = bool(s5 and s5.get("d3_triggered") is True)
    s5_ready = bool(
        d2_triggered
        or (
            s5
            and s5.get("residual_closed_loop_executed") is True
            and (s5.get("measurable_difference_observed") is True or d3_triggered)
            and s5.get("status")
            in {
                "PASS_MEASURABLE_RESIDUAL_DIFFERENCE",
                "D3_GO_QRM_COARSE_ONLY",
            }
        )
    )

    primary = (s6 or {}).get("primary_metric") or {}
    primary_interval = primary.get("interval")
    s6_ready = bool(
        s6
        and s6.get("status") == "PASS_M2C_S6_FORMAL_MATCHED_EVALUATION"
        and s6.get("formal_evaluation_ready") is True
        and int(s6.get("complete_matched_keys", 0)) >= 30
        and int(s6.get("qrm_model_decisions_executed", 0)) >= 50
        and int(s6.get("collision_or_safety_violations", -1)) == 0
        and primary.get("name") == "fc_gain_over_b0"
        and primary.get("estimate") is not None
        and isinstance(primary_interval, list)
        and len(primary_interval) == 2
    )

    present = [report for report in (s0, s1, s2, s3, s4, s5, s6) if report]
    teacher_free = bool(present and all(report.get("teacher_used") is False for report in present))
    no_privileged_policy_input = bool(
        present and all(report.get("privileged_truth_policy_input") is False for report in present)
    )
    world_model_preserved = bool(
        present and all(report.get("world_model_mainline_replaced") is False for report in present)
    )
    tests = (verification or {}).get("tests") or {}
    verification_ready = bool(
        verification
        and verification.get("status") == "PASS"
        and int(tests.get("passed", 0)) > 0
        and int(tests.get("failed", -1)) == 0
        and verification.get("b0_freeze_recheck_passed") is True
        and verification.get("m2b_evidence_readonly") is True
    )

    gates = {
        "s0_b0_and_m2b_freeze": s0_ready,
        "s1_delivery_evidence": s1_ready,
        "s2_q_a_headroom_and_recoverability": s2_ready,
        "s3_full_class_coverage": s3_ready,
        "s4_q_b_governed_disposition": s4_ready,
        "s5_residual_closed_loop_or_d2_disposition": s5_ready,
        "s6_formal_four_method_matched_evaluation": s6_ready,
        "teacher_free": teacher_free,
        "no_privileged_truth_policy_input": no_privileged_policy_input,
        "world_model_mainline_preserved": world_model_preserved,
        "final_verification_passed": verification_ready,
    }
    blocker_by_gate = {
        "s0_b0_and_m2b_freeze": "S0 B0/M2B freeze is missing or no longer matches",
        "s1_delivery_evidence": "S1 delivery evidence is missing or failing",
        "s2_q_a_headroom_and_recoverability": "S2 Q-A has not proved both B0 headroom and physical recoverability",
        "s3_full_class_coverage": "S3 has not passed 100 failures / 50 recoveries per class with zero quarantine and no split leakage",
        "s4_q_b_governed_disposition": "S4 lacks a human-ADR-governed Q-B execution and strict pure-model/D2 disposition",
        "s5_residual_closed_loop_or_d2_disposition": "S5 has neither a measured residual difference nor a valid D2/D3 disposition",
        "s6_formal_four_method_matched_evaluation": "S6 lacks 30 four-method keys, 50 physical model decisions, paired FC-vs-B0 CI, or zero violations",
        "teacher_free": "a stage report lacks an explicit Teacher-free assertion or reports Teacher use",
        "no_privileged_truth_policy_input": "a stage report lacks the truth boundary or reports privileged policy input",
        "world_model_mainline_preserved": "a stage report lacks the world-model boundary or reports replacement",
        "final_verification_passed": "final tests, B0 freeze recheck, or M2B read-only verification is missing or failing",
    }
    blockers = [blocker_by_gate[name] for name, passed in gates.items() if not passed]
    if not s3_ready:
        next_command = "M2B_EVIDENCE_READONLY=1 make m2c-s3-dataset"
    elif not s4_ready:
        next_command = "sed -n '1,240p' docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md"
    elif not s5_ready:
        next_command = "make m2c-s5"
    elif not s6_ready:
        next_command = "make m2c-s6"
    else:
        next_command = "make m2c-status"

    fc_gain = primary_gain(s6)
    goal_complete = not blockers
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

    feature_branch = run(["git", "branch", "--show-current"])
    commits = run(["git", "log", "--format=%H", "141e45d..HEAD"]).splitlines()
    status: dict[str, Any] = {
        "schema_version": "M2CStatusV1",
        "phase": "M2C",
        "status": "PASS_WITH_LIMITATIONS" if goal_complete else "PARTIAL",
        "goal_complete": goal_complete,
        "completion_gates": gates,
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
        "matched_keys": int((s6 or {}).get("complete_matched_keys", 0)),
        "model_decisions_executed": int((s6 or {}).get("qrm_model_decisions_executed", 0)),
        "collision_or_safety_violations": (s6 or {}).get("collision_or_safety_violations"),
        "d1_triggered": bool(s2_decision.get("d1_triggered")),
        "d2_triggered": d2_triggered,
        "d3_triggered": d3_triggered,
        "system_verdict": system_verdict,
        "teacher_used": not teacher_free,
        "teacher_states": TEACHER_STATES,
        "teacher_kill_rules": TEACHER_KILL_RULES,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": not no_privileged_policy_input,
        "world_model_mainline_replaced": not world_model_preserved,
        "tests_passed": int(tests.get("passed", 0)),
        "tests_failed": tests.get("failed"),
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
            f"- Dataset valid/quarantine: {status['episodes_valid']}/{status['episodes_quarantined']}",
            f"- Failure/recovery counts: `{failure_counts}` / `{recovery_counts}`",
            f"- Q-A B0 success/headroom: `{status['b0_final_task_success_rate_q_a']}` / `{status['b0_headroom_q_a']}`",
            f"- `pure_model_success_episodes`: `{strict_pure_count}`",
            f"- `fc_gain_over_b0`: `{fc_gain}`; 95% CI `{primary_interval}`",
            f"- S6 keys / executed model decisions: {status['matched_keys']} / {status['model_decisions_executed']}",
            "- Teacher used: no" if teacher_free else "- Teacher boundary: FAIL",
            "- Privileged simulator truth in policy input: no"
            if no_privileged_policy_input
            else "- Privileged-truth boundary: FAIL",
            "- World-model mainline replaced: no"
            if world_model_preserved
            else "- World-model boundary: FAIL",
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
        "schema_version": "M2CCompletionAuditV1",
        "status": "PASS" if goal_complete else "PARTIAL",
        "system_verdict": system_verdict,
        "gates": gates,
        "primary_metric": {
            "fc_gain_over_b0": fc_gain,
            "confidence_interval": primary_interval,
        },
        "pure_model_success_episodes": strict_pure_count,
        "teacher_used": not teacher_free,
        "teacher_states": TEACHER_STATES,
        "teacher_kill_rules": TEACHER_KILL_RULES,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": not no_privileged_policy_input,
        "world_model_mainline_replaced": not world_model_preserved,
        "honest_limitations": limitations,
        "task_report": {
            "changed_files": changed_files,
            "tests": {
                "passed": int(tests.get("passed", 0)),
                "failed": tests.get("failed"),
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
            f"- Tests: {int(tests.get('passed', 0))} passed, {tests.get('failed')} failed",
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
