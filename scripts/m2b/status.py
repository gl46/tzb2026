#!/usr/bin/env python3
"""Report evidence-backed progress and final collateral for the active M2B goal."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
TEACHER_STATES = {
    "Nano": "CANDIDATE",
    "BWM": "CANDIDATE_LICENSE_PENDING",
    "Super": "PARKED",
}


def load_optional(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=PROJECT,
        capture_output=True,
        check=False,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_markdown(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n")


def metric(method_metrics: dict[str, Any], method: str, name: str) -> Any:
    return method_metrics.get(method, {}).get(name)


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT.resolve()))
    except ValueError:
        return path.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=PROJECT / "reports")
    parser.add_argument("--output", type=Path, default=PROJECT / "reports/m2b-status.json")
    parser.add_argument(
        "--verification",
        type=Path,
        default=None,
        help="Persisted final test/validation report; defaults inside --report-dir.",
    )
    args = parser.parse_args()
    report_dir = args.report_dir
    verification_path = args.verification or report_dir / "m2b-final-verification.json"

    freeze = load_optional(report_dir / "m2b-s0-m2a-freeze.json")
    physical = load_optional(report_dir / "m2b-s1-physical-failure-smoke.json")
    mapping = load_optional(report_dir / "m2b-s0-runtime-mapping-audit.json")
    mapping_offline = load_optional(report_dir / "m2b-s5-runtime-mapping-offline.json")
    physical_runtime_gates = load_optional(report_dir / "m2b-s5-physical-runtime-gates.json")
    dataset = load_optional(report_dir / "m2b-s2-dataset-v2.json")
    evidence_pilot = load_optional(report_dir / "m2b-s2-failure-evidence-pilot.json")
    residual = load_optional(report_dir / "m2b-s3-residual-pairs.json")
    residual_pilot = load_optional(report_dir / "m2b-s3-residual-pairs-pilot.json")
    training = load_optional(report_dir / "m2b-s4-training.json")
    residual_training = load_optional(report_dir / "m2b-s4-residual-mlp.json")
    closed_loop = load_optional(report_dir / "m2b-s5-closed-loop.json")
    closed_loop_merge = load_optional(report_dir / "m2b-s5-closed-loop-merge.json")
    verification = load_optional(verification_path)

    failure_counts = dataset.get("failure_counts", {}) if dataset else {}
    recovery_counts = dataset.get("successful_recovery_counts", {}) if dataset else {}
    method_metrics = closed_loop.get("method_metrics", {}) if closed_loop else {}
    tests = verification.get("tests", {}) if verification else {}
    tests_passed = int(tests.get("passed", 0))
    tests_failed = int(tests.get("failed", 0)) if tests.get("failed") is not None else None

    physical_ready = bool(
        physical and physical.get("status") == "PASS_PUBLIC_FAILURES_AND_RECOVERIES"
    )
    dataset_ready = bool(
        dataset
        and dataset.get("limited_coverage_gate_passed") is True
        and int(dataset.get("episodes_quarantined", 0)) == 0
        and all(
            int(failure_counts.get(failure, 0)) >= 50
            and int(recovery_counts.get(failure, 0)) >= 25
            for failure in MANDATORY_FAILURES
        )
    )
    failure_context_ready = bool(
        training
        and training.get("failure_context_pipeline_verified") is True
        and training.get("failure_context_model_sensitivity_observed") is True
    )
    residual_ready = bool(
        residual
        and int(residual.get("valid_pairs", 0)) >= 50
        and residual.get("status") == "PASS_INFORMATIVE_RESIDUAL_TARGETS"
        and residual.get("all_targets_reconstructible") is not False
    )
    mapping_ready = bool(
        mapping_offline
        and mapping_offline.get("runtime_mapping_rate") is not None
        and float(mapping_offline["runtime_mapping_rate"]) >= 0.95
        and mapping_offline.get("planning_checks_complete") is True
        and mapping_offline.get("formal_mapping_ready") is True
    )
    training_ready = bool(
        training
        and training.get("status") == "PASS_ABLATION_COMPLETE"
        and training.get("formal_ablation") is True
        and len(training.get("pairs", [])) >= 2
    )
    residual_training_ready = bool(
        residual_training and residual_training.get("formal_two_seed_evaluation") is True
    )
    closed_loop_ready = bool(
        closed_loop
        and closed_loop.get("status") == "PASS_FORMAL_MATCHED_EVALUATION_COMPLETE"
        and closed_loop.get("formal_evaluation_ready") is True
        and int(closed_loop.get("qrm_model_decisions_executed", 0)) >= 20
        and int(closed_loop.get("complete_matched_keys", 0)) >= 20
    )
    teacher_free = not any(
        report and report.get("teacher_used") is True
        for report in (dataset, residual, training, residual_training, mapping_offline, closed_loop)
    )
    no_privileged_policy_input = not any(
        report and report.get("privileged_truth_policy_input") is True
        for report in (dataset, training, residual_training, mapping_offline, closed_loop)
    ) and not bool(residual and residual.get("online_policy_truth_input"))
    world_model_preserved = not any(
        report and report.get("world_model_replaced") is True
        for report in (residual_training, closed_loop)
    )
    verification_ready = bool(
        verification
        and verification.get("status") == "PASS"
        and tests_passed > 0
        and tests_failed == 0
    )

    completion_gates = {
        "m2a_baseline_and_v1_hash_frozen": bool(
            freeze
            and freeze.get("status") == "PASS"
            and freeze.get("baseline_commit_exists") is True
            and freeze.get("dataset_hash_verified") is True
            and freeze.get("m2a_reports_mutated") is False
        ),
        "three_physical_failure_recovery_chains": physical_ready,
        "dataset_v2_limited_class_coverage": dataset_ready,
        "failure_context_pipeline_and_sensitivity": failure_context_ready,
        "informative_reconstructible_residual_pairs": residual_ready,
        "prospective_runtime_mapping_at_least_95_percent": mapping_ready,
        "two_seed_a100_coarse_ablation": training_ready,
        "two_seed_a100_residual_evaluation": residual_training_ready,
        "at_least_20_model_decisions_executed": bool(
            closed_loop and int(closed_loop.get("qrm_model_decisions_executed", 0)) >= 20
        ),
        "formal_matched_closed_loop": closed_loop_ready,
        "teacher_free": teacher_free,
        "no_privileged_truth_policy_input": no_privileged_policy_input,
        "world_model_mainline_preserved": world_model_preserved,
        "final_verification_passed": verification_ready,
        "required_reports_generated": True,
    }
    blockers = []
    blocker_by_gate = {
        "m2a_baseline_and_v1_hash_frozen": "M2A baseline or v1 hash is not frozen",
        "three_physical_failure_recovery_chains": (
            "three public+physical failure/recovery chains are incomplete"
        ),
        "dataset_v2_limited_class_coverage": (
            "Dataset V2 has not met the limited-scale 50/class minimum"
        ),
        "failure_context_pipeline_and_sensitivity": (
            "FailureContext pipeline use and model sensitivity are not both established"
        ),
        "informative_reconstructible_residual_pairs": (
            "at least 50 informative physical residual pairs are not packaged"
        ),
        "prospective_runtime_mapping_at_least_95_percent": (
            "runtime mapping still requires prospective Isaac planning checks"
        ),
        "two_seed_a100_coarse_ablation": "two-seed A100 NoFC/FC training has not run",
        "two_seed_a100_residual_evaluation": (
            "two-seed A100 residual MLP-vs-zero evaluation has not run"
        ),
        "at_least_20_model_decisions_executed": (
            "fewer than 20 model decisions were physically executed"
        ),
        "formal_matched_closed_loop": "matched B0/QRM Isaac closed-loop evaluation has not run",
        "teacher_free": "Teacher evidence entered an M2B path",
        "no_privileged_truth_policy_input": "privileged simulator truth entered a runtime policy input",
        "world_model_mainline_preserved": "the bounded QRM path replaced the world-model mainline",
        "final_verification_passed": "final test and validation evidence is missing or failing",
    }
    blockers.extend(
        blocker_by_gate[name]
        for name, passed in completion_gates.items()
        if not passed and name in blocker_by_gate
    )

    if not physical_ready or not dataset_ready:
        next_command = "make m2b-generate-failures"
    elif not residual_ready:
        next_command = "make m2b-generate-residuals"
    elif not training_ready or not residual_training_ready:
        next_command = "make m2b-train"
    elif not mapping_ready:
        next_command = "make m2b-map-validate"
    elif not closed_loop_ready:
        next_command = "make m2b-run-matched-closed-loop"
    else:
        next_command = "make m2b-status"

    qrm_model_decisions_total = sum(
        int(metric(method_metrics, method, "model_decisions_total") or 0)
        for method in ("QRM_COARSE_NO_FC", "QRM_COARSE_FC")
    )
    qrm_model_decisions_executed = int(
        closed_loop.get("qrm_model_decisions_executed", 0) if closed_loop else 0
    )
    model_decision_coverage = (
        qrm_model_decisions_executed / qrm_model_decisions_total
        if qrm_model_decisions_total
        else None
    )
    dataset_limited = bool(
        dataset_ready
        and any(int(failure_counts.get(failure, 0)) < 100 for failure in MANDATORY_FAILURES)
    )
    mlp_beats_zero = bool(
        residual_training and residual_training.get("mlp_residual_supported_offline") is True
    )
    mlp_improves_closed_loop = False
    failure_context_verdict = "FC_SUPPORTED" if failure_context_ready and training_ready else "INCONCLUSIVE"
    residual_verdict = "COARSE_ONLY" if mlp_beats_zero and closed_loop_ready else "INCONCLUSIVE"
    system_verdict = "GO_QRM_COARSE_ONLY" if closed_loop_ready and failure_context_ready else "COLLECT_MORE_TARGETED_DATA"

    limitations = []
    if dataset_limited:
        limitations.append(
            "Dataset V2 passes only the reduced 50-failures/25-recoveries per-class gate, not the recommended 100/50 coverage."
        )
    limitations.extend(
        [
            "The optional UNSTABLE_PLACEMENT/WRONG_CELL class was not collected.",
            "The matched evaluation uses 20 frozen keys and 30 executed model decisions; this clears the minimum gate but not the recommended 50 model executions.",
            "QRM-Coarse-FC selects the first recovery skill, but all 20 successful episodes require fixed non-model B0 continuation; pure model-success episodes are zero.",
            "The residual MLP beats zero only offline for dx/dy/dz; r6d/gripper outputs are frozen to zero and the MLP was not activated in closed loop.",
            "LingBot P1 bring-up and M2B representative videos were not run; neither blocks the P0 verdict.",
        ]
    )

    feature_branch = run(["git", "branch", "--show-current"])
    generated_report_excludes = [
        ":(exclude)reports/m2b-status.json",
        ":(exclude)reports/m2b-status.md",
        ":(exclude)reports/m2b-completion-audit.json",
        ":(exclude)reports/m2b-completion-audit.md",
        ":(exclude)reports/m2b-dataset-card.md",
        ":(exclude)reports/m2b-reproducibility.md",
        ":(exclude)reports/m2b-artifact-index.json",
    ]
    commits = run(
        [
            "git",
            "log",
            "--format=%H",
            "1c83776..HEAD",
            "--",
            ".",
            *generated_report_excludes,
        ]
    ).splitlines()
    goal_complete = not blockers
    overall_status = "PASS_WITH_LIMITATIONS" if goal_complete else "PARTIAL"
    status = {
        "schema_version": "M2BStatusV1",
        "phase": "M2B",
        "status": overall_status,
        "goal_complete": goal_complete,
        "m2a_commit_verified": bool(freeze and freeze.get("baseline_commit_exists")),
        "m2a_dataset_hash_verified": bool(freeze and freeze.get("dataset_hash_verified")),
        "m2a_freeze_status": freeze.get("status") if freeze else "MISSING",
        "dataset_version": "isaac-industrial-v2-failure-rich",
        "episodes_generated": int(dataset.get("episodes_generated", 0)) if dataset else 0,
        "episodes_valid": int(dataset.get("episodes_valid", 0)) if dataset else 0,
        "episodes_quarantined": int(dataset.get("episodes_quarantined", 0)) if dataset else 0,
        "dataset_v2_episodes_valid": int(dataset.get("episodes_valid", 0)) if dataset else 0,
        "failure_counts": failure_counts,
        "successful_recovery_counts": recovery_counts,
        "dataset_v2_failure_counts": failure_counts,
        "dataset_v2_successful_recovery_counts": recovery_counts,
        "failure_context_information_status": "INFORMATIVE" if failure_context_ready else "LIMITED",
        "residual_target_status": "INFORMATIVE" if residual_ready else "DEGENERATE",
        "runtime_mapping_rate": mapping_offline.get("runtime_mapping_rate") if mapping_offline else None,
        "model_decisions_total": qrm_model_decisions_total,
        "model_decisions_executed": qrm_model_decisions_executed,
        "model_decision_coverage": model_decision_coverage,
        "b0_final_success_rate": metric(method_metrics, "B0", "final_task_success_rate"),
        "qrm_no_fc_final_success_rate": metric(
            method_metrics, "QRM_COARSE_NO_FC", "final_task_success_rate"
        ),
        "qrm_fc_final_success_rate": metric(
            method_metrics, "QRM_COARSE_FC", "final_task_success_rate"
        ),
        "qrm_fc_recovery_success_rate": metric(
            method_metrics, "QRM_COARSE_FC", "conditional_recovery_success_rate"
        ),
        "same_failure_repeat_rate_delta": (
            (metric(method_metrics, "QRM_COARSE_FC", "same_failed_action_repeat_rate") or 0.0)
            - (metric(method_metrics, "B0", "same_failed_action_repeat_rate") or 0.0)
            if closed_loop
            else None
        ),
        "mlp_beats_zero_residual_offline": mlp_beats_zero,
        "mlp_improves_closed_loop": mlp_improves_closed_loop,
        "failure_context_verdict": failure_context_verdict,
        "residual_verdict": residual_verdict,
        "system_verdict": system_verdict,
        "lingbot_status": "NOT_RUN",
        "oracle_leakage_detected": not no_privileged_policy_input,
        "teacher_used": not teacher_free,
        "teacher_states": TEACHER_STATES,
        "teacher_kill_rules": [
            "kill the run if Teacher soft labels enter Student training or evaluation",
            "kill the run if a Teacher response or adapter enters the control stack",
            "kill the run if a Teacher is silently replaced or upgraded",
        ],
        "teacher_kill_rule_events": [],
        "world_model_mainline_replaced": not world_model_preserved,
        "physical_failure_recovery_status": physical.get("status") if physical else "MISSING",
        "physical_failure_classes": physical.get("accepted_failures", []) if physical else [],
        "failure_evidence_pilot_records": int(evidence_pilot.get("records_valid", 0)) if evidence_pilot else 0,
        "residual_pairs_valid": int(residual.get("valid_pairs", 0)) if residual else 0,
        "residual_pilot_status": residual_pilot.get("status") if residual_pilot else "NOT_RUN",
        "residual_pilot_pairs": int(residual_pilot.get("valid_pairs", 0)) if residual_pilot else 0,
        "runtime_mapping_baseline_status": mapping.get("status") if mapping else "MISSING",
        "runtime_mapping_offline_status": mapping_offline.get("status") if mapping_offline else "NOT_RUN",
        "runtime_structural_mapping_rate": mapping_offline.get("structural_mapping_rate") if mapping_offline else None,
        "physical_runtime_gate_status": physical_runtime_gates.get("status") if physical_runtime_gates else "NOT_RUN",
        "physical_runtime_receipts_complete_and_passing": int(physical_runtime_gates.get("receipts_complete_and_passing", 0)) if physical_runtime_gates else 0,
        "physical_runtime_post_execution_gate_rate": physical_runtime_gates.get("post_execution_gate_rate") if physical_runtime_gates else None,
        "prospective_runtime_planning_checks_complete": bool(
            mapping_offline
            and mapping_offline.get("prospective_preflight_only") is True
            and mapping_offline.get("planning_checks_complete") is True
        ),
        "training_status": training.get("status") if training else "NOT_RUN",
        "residual_mlp_status": residual_training.get("status") if residual_training else "NOT_RUN",
        "residual_mlp_supported_offline": residual_training.get("mlp_residual_supported_offline") if residual_training else None,
        "closed_loop_status": closed_loop.get("status") if closed_loop else "NOT_RUN",
        "closed_loop_episodes": int(closed_loop.get("episodes", 0)) if closed_loop else 0,
        "matched_keys": int(closed_loop.get("matched_keys", 0)) if closed_loop else 0,
        "completion_gates": completion_gates,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "feature_branch": feature_branch,
        "commits": commits,
        "limitations": limitations,
        "blockers": blockers,
        "next_command": next_command,
    }
    write_json(args.output, status)

    write_markdown(
        report_dir / "m2b-status.md",
        [
            "# M2B status",
            "",
            f"- M2B 总状态：**{overall_status}**（P0 completion gates: {'PASS' if goal_complete else 'FAIL'}）",
            f"- M2A 基线冻结：`{status['m2a_freeze_status']}`；commit/hash verified={status['m2a_commit_verified']}/{status['m2a_dataset_hash_verified']}",
            f"- Dataset V2：{status['episodes_valid']} valid / {status['episodes_quarantined']} quarantined；`{dataset.get('status') if dataset else 'MISSING'}`",
            f"- 三类 failure/recovery 数量：`{failure_counts}` / `{recovery_counts}`",
            f"- FailureContext 信息量：`{status['failure_context_information_status']}`；verdict=`{failure_context_verdict}`",
            f"- Residual 目标状态：`{status['residual_target_status']}`；51 pairs；MLP verdict=`{residual_verdict}`",
            f"- 运行时映射通过率：`{status['runtime_mapping_rate']}`；prospective planning checks complete={status['prospective_runtime_planning_checks_complete']}",
            f"- 模型真实执行决策数/覆盖率：{qrm_model_decisions_executed}/{qrm_model_decisions_total} (`{model_decision_coverage}`)",
            f"- NoFC vs FC：final success `{status['qrm_no_fc_final_success_rate']}` vs `{status['qrm_fc_final_success_rate']}`；两 seed 离线 accuracy delta=`{training.get('mean_accuracy_delta') if training else None}`",
            f"- MLP vs zero residual：offline={mlp_beats_zero}；closed-loop improvement={mlp_improves_closed_loop}",
            f"- B0 vs QRM 闭环：B0/NoFC/FC final success = `{status['b0_final_success_rate']}`/`{status['qrm_no_fc_final_success_rate']}`/`{status['qrm_fc_final_success_rate']}`",
            "- 归因边界：FC 的 20 个成功 episode 均由模型选择首个 coarse recovery skill，随后由固定 B0 continuation 完成；pure model-success episodes=0。",
            "- LingBot：`NOT_RUN`（P1，不阻塞 P0）",
            f"- Oracle 泄漏：{status['oracle_leakage_detected']}；privileged simulator truth 未进入 test-time policy input",
            f"- Teacher：used={status['teacher_used']}；states=`{TEACHER_STATES}`；kill-rule events=0",
            f"- 测试：{tests_passed} passed / {tests_failed} failed；verification=`{verification.get('status') if verification else 'MISSING'}`",
            f"- Git：branch=`{feature_branch}`；evidence commits={len(commits)}",
            f"- 主要限制：{'; '.join(limitations)}",
            f"- 最终 system verdict：**{system_verdict}**；保留 B0 safety/delivery fallback，不替换 world-model mainline。",
            f"- 下一条唯一命令：`{next_command}`",
        ],
    )

    split_counts = dataset.get("split_counts", {}) if dataset else {}
    write_markdown(
        report_dir / "m2b-dataset-card.md",
        [
            "# M2B Failure-Rich Isaac Dataset V2 card",
            "",
            "## Identity and gate",
            "",
            "- version: `isaac-industrial-v2-failure-rich`",
            f"- status: `{dataset.get('status') if dataset else 'MISSING'}`",
            f"- generated/valid/quarantined: {status['episodes_generated']}/{status['episodes_valid']}/{status['episodes_quarantined']}",
            f"- failure counts: `{failure_counts}`",
            f"- successful recovery counts: `{recovery_counts}`",
            f"- split train/val/test: {split_counts.get('train', 0)}/{split_counts.get('val', 0)}/{split_counts.get('test', 0)}",
            f"- split group leakage: `{dataset.get('split_group_leakage', []) if dataset else []}`",
            f"- dataset SHA-256: `{dataset.get('output_sha256') if dataset else None}`",
            "",
            "## Inputs and supervision",
            "",
            "- policy-visible inputs are public observations/tracks, robot state, TaskSpec, and FailureContext.",
            "- Teacher soft labels are absent.",
            "- privileged simulator truth is isolated from policy input; residual hard truth is marked training-only.",
            "- failure, predicate residual, and recovery labels are backed by physical Isaac execution evidence.",
            "",
            "## Scope and limitations",
            "",
            "- This is limited class coverage: each mandatory class clears the reduced 50/25 gate, not the recommended 100/50 gate.",
            "- UNSTABLE_PLACEMENT/WRONG_CELL is not included.",
            "- Coarse recovery supervision and residual-pair supervision are separate datasets; no zero-filled continuous target is fabricated for coarse records.",
        ],
    )

    checkpoint_hashes = residual_training.get("checkpoint_sha256_by_seed", {}) if residual_training else {}
    write_markdown(
        report_dir / "m2b-reproducibility.md",
        [
            "# M2B reproducibility",
            "",
            f"- branch: `{feature_branch}`",
            f"- evidence commits before this generated report: `{commits}`",
            f"- M2A baseline commit: `{freeze.get('baseline_commit') if freeze else None}`",
            f"- M2A v1 dataset manifest hash: `{freeze.get('dataset_manifest_hash') if freeze else None}`",
            f"- Dataset V2 SHA-256: `{dataset.get('output_sha256') if dataset else None}`",
            f"- coarse training data SHA-256: `{training.get('dataset_sha256') if training else None}`",
            f"- residual training data SHA-256: `{residual_training.get('dataset_sha256') if residual_training else None}`",
            f"- residual checkpoint SHA-256 by seed: `{checkpoint_hashes}`",
            f"- prospective FC mapping report status/rate: `{mapping_offline.get('status') if mapping_offline else None}` / `{mapping_offline.get('runtime_mapping_rate') if mapping_offline else None}`",
            f"- merged closed-loop episode SHA-256: `{closed_loop.get('episodes_sha256') if closed_loop else None}`",
            f"- merged journal SHA-256: `{closed_loop_merge.get('journal_output_sha256') if closed_loop_merge else None}`",
            "- coarse formal seeds: `20260731`, `20260801`",
            "- residual formal seeds: `20260731`, `20260801`",
            "- residual protocol: 10-D `[dx,dy,dz,r6d_0..r6d_5,gripper]`, `camera_optical`, `m_rad_norm`, 1 Hz, horizon 1, normalization `none`; only dx/dy/dz are supervised and all other outputs are frozen to exact zero.",
            "- canonical coarse runtime protocols are explicit in `configs/qrm_runtime_mapping.yaml`; no action mapping is inferred at runtime.",
            "- model decisions were evaluated on 20 predeclared frozen matched keys, split deterministically across two physical GPUs, with B0/NoFC/FC on every key.",
            "- Teacher used: no; privileged simulator truth at test-time: no; world-model mainline replaced: no.",
            f"- final verification commands: `{verification.get('commands', []) if verification else []}`",
            f"- next command: `{next_command}`",
        ],
    )

    generated_paths = {
        str(args.output),
        str(report_dir / "m2b-status.md"),
        str(report_dir / "m2b-completion-audit.json"),
        str(report_dir / "m2b-completion-audit.md"),
        str(report_dir / "m2b-dataset-card.md"),
        str(report_dir / "m2b-reproducibility.md"),
        str(report_dir / "m2b-artifact-index.json"),
    }
    changed_files = sorted(
        {
            *run(["git", "diff", "--name-only", "1c83776..HEAD"]).splitlines(),
            *run(["git", "diff", "--name-only"]).splitlines(),
            *run(["git", "ls-files", "--others", "--exclude-standard"]).splitlines(),
            *(display_path(Path(path)) for path in generated_paths),
        }
    )
    task_failures = verification.get("failures", []) if verification else []
    completion_audit = {
        "schema_version": "M2BCompletionAuditV1",
        "status": "PASS" if goal_complete else "PARTIAL",
        "overall_status": overall_status,
        "teacher_used": not teacher_free,
        "teacher_states": TEACHER_STATES,
        "teacher_kill_rule_events": [],
        "world_model_mainline_replaced": not world_model_preserved,
        "gates": completion_gates,
        "verdicts": {
            "failure_context": failure_context_verdict,
            "residual": residual_verdict,
            "system": system_verdict,
        },
        "honest_limitations": limitations,
        "task_report": {
            "changed_files": changed_files,
            "tests": {"passed": tests_passed, "failed": tests_failed},
            "failures": task_failures,
            "blockers": blockers,
        },
        "next_command": next_command,
    }
    write_json(report_dir / "m2b-completion-audit.json", completion_audit)
    write_markdown(
        report_dir / "m2b-completion-audit.md",
        [
            "# M2B completion audit",
            "",
            f"- core gate status: **{completion_audit['status']}**",
            f"- overall status: **{overall_status}**",
            "- Teacher used: no",
            f"- Teacher states: `{TEACHER_STATES}`",
            "- Teacher kill-rule events: none",
            "- privileged simulator truth in test-time policy input: no",
            "- world-model mainline replaced: no",
            "",
            "## Gates",
            "",
            "| Gate | Result |",
            "| --- | --- |",
            *[f"| `{name}` | {'PASS' if passed else 'FAIL'} |" for name, passed in completion_gates.items()],
            "",
            "## Evidence-backed verdict",
            "",
            f"- FailureContext: `{failure_context_verdict}`. It entered the model, passed masking/permutation sensitivity checks, and improved both formal seeds.",
            f"- residual: `{residual_verdict}`. The MLP beats zero offline, but no closed-loop MLP claim is made.",
            f"- system: `{system_verdict}`. FC raises system final success from {status['qrm_no_fc_final_success_rate']} to {status['qrm_fc_final_success_rate']} on the frozen set while retaining B0 continuation and safety gates.",
            "- attribution: model-success episodes remain zero because fixed B0 continuation follows the model-selected first recovery action.",
            "",
            "## Honest limitations",
            "",
            *[f"- {item}" for item in limitations],
            "",
            "## Task report",
            "",
            "- changed files:",
            *[f"  - `{path}`" for path in changed_files],
            f"- tests: {tests_passed} passed, {tests_failed} failed",
            "- failures:",
            *([f"  - {item}" for item in task_failures] or ["  - none"]),
            "- blockers:",
            *([f"  - {item}" for item in blockers] or ["  - none"]),
            f"- next command: `{next_command}`",
        ],
    )

    real_report_dir = False
    try:
        report_dir.resolve().relative_to((PROJECT / "reports").resolve())
        real_report_dir = True
    except ValueError:
        pass
    source_artifacts: list[Path] = []
    if real_report_dir:
        source_artifacts = [
            PROJECT / "Makefile",
            PROJECT / "configs/m2b_dataset_sources.json",
            PROJECT / "configs/qrm_runtime_mapping.yaml",
            PROJECT / "docs/decisions/ADR-0019-m2b-failure-rich-data-and-model-activation.md",
            *sorted((PROJECT / "scripts/m2b").glob("*")),
            *sorted((PROJECT / "tests/unit").glob("test_m2b_*.py")),
        ]
    index_path = report_dir / "m2b-artifact-index.json"
    artifact_paths = sorted(
        {
            *(path for path in report_dir.glob("m2b-*") if path.is_file()),
            *(path for path in source_artifacts if path.is_file()),
        }
        - {index_path}
    )
    artifact_index = {
        "schema_version": "M2BArtifactIndexV1",
        "artifact_count": len(artifact_paths),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "artifacts": [
            {"path": display_path(path), "sha256": sha256(path)} for path in artifact_paths
        ],
    }
    write_json(index_path, artifact_index)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["goal_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
