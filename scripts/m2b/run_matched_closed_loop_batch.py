#!/usr/bin/env python3
"""Execute matched B0/NoFC/FC recovery episodes from the same Isaac scenes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shlex
import subprocess
from typing import Any, cast

from m2b.run_prospective_preflight_batch import (
    EXPECTED_FIRST_RECOVERY_SKILL,
    expected_first_runtime_action,
    preflight_command,
    remote_bytes,
    remote_json,
    remote_stage,
    scene_root_from_evidence,
    target_entities,
    validated_source_hashes,
    verify_bytes_sha256,
)
from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    Method,
    M2BClosedLoopDecisionV1,
    M2BClosedLoopEpisodeV1,
)
from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    PhysicalRuntimeGateReceiptV1,
    extract_physical_runtime_gate_receipt,
)
from xh_agent.policy.qrm_lite.prospective_mapping import (
    M2BProspectiveRuntimeDecisionV1,
)
from xh_agent.policy.qrm_lite.skill_registry import load_registry


METHODS: tuple[Method, ...] = (
    "B0",
    "QRM_COARSE_NO_FC",
    "QRM_COARSE_FC",
)
SAMPLE_SUFFIX = ":coarse-recovery-0"


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_decisions(
    path: Path,
) -> dict[str, M2BProspectiveRuntimeDecisionV1]:
    records = [
        M2BProspectiveRuntimeDecisionV1.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    by_sample = {record.sample_id: record for record in records}
    if len(by_sample) != len(records):
        raise ValueError(f"{path}: duplicate sample_id")
    if len({record.registry_sha256 for record in records}) != 1:
        raise ValueError(f"{path}: mixed runtime registries")
    if len({record.model_checkpoint_sha256 for record in records}) != 1:
        raise ValueError(f"{path}: mixed model checkpoints")
    return by_sample


def matched_pairs(
    no_fc: dict[str, M2BProspectiveRuntimeDecisionV1],
    fc: dict[str, M2BProspectiveRuntimeDecisionV1],
    *,
    max_keys: int,
    require_count: bool = True,
) -> list[
    tuple[
        M2BProspectiveRuntimeDecisionV1,
        M2BProspectiveRuntimeDecisionV1,
    ]
]:
    if set(no_fc) != set(fc):
        missing_no_fc = sorted(set(fc) - set(no_fc))
        missing_fc = sorted(set(no_fc) - set(fc))
        raise ValueError(
            "adapter held-out samples differ: "
            f"missing_no_fc={missing_no_fc}, missing_fc={missing_fc}"
        )
    pairs = []
    for sample_id in sorted(no_fc):
        first = no_fc[sample_id]
        second = fc[sample_id]
        if first.failure_type != second.failure_type:
            raise ValueError(f"{sample_id}: adapter failure types differ")
        if first.registry_sha256 != second.registry_sha256:
            raise ValueError(f"{sample_id}: adapter registries differ")
        pairs.append((first, second))
    buckets = {
        failure: [pair for pair in pairs if pair[0].failure_type == failure]
        for failure in EXPECTED_FIRST_RECOVERY_SKILL
    }
    empty = sorted(failure for failure, items in buckets.items() if not items)
    if empty:
        raise ValueError(f"held-out decisions lack failure classes: {empty}")
    selected = []
    while len(selected) < max_keys and any(buckets.values()):
        for failure in EXPECTED_FIRST_RECOVERY_SKILL:
            if buckets[failure] and len(selected) < max_keys:
                selected.append(buckets[failure].pop(0))
    if require_count and len(selected) < max_keys:
        raise ValueError(f"only {len(selected)} matched keys available; need {max_keys}")
    return selected


def episode_id_from_sample(sample_id: str) -> str:
    if not sample_id.endswith(SAMPLE_SUFFIX):
        raise ValueError(f"{sample_id}: unexpected held-out sample ID")
    return sample_id[: -len(SAMPLE_SUFFIX)]


def matched_key(
    *,
    sample_id: str,
    scene_seed: int,
    failure_type: str,
    source_hashes: dict[str, str],
) -> str:
    digest = canonical_sha256(
        {
            "sample_id": sample_id,
            "scene_seed": scene_seed,
            "failure_type": failure_type,
            "source_hashes": source_hashes,
        }
    )
    return f"m2b-match-{digest}"


def remote_exists(host: str, path: str) -> bool:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "test", "-f", path],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def injection_is_valid(payload: dict[str, Any], failure_type: str) -> bool:
    key = {
        "EMPTY_GRASP": "m2b_empty_grasp_injection",
        "WRONG_OBJECT": "m2b_wrong_object_injection",
        "RELEASE_FAILURE": "m2b_release_failure_injection",
    }[failure_type]
    injection = payload.get(key) or {}
    return bool(
        payload.get("m2b_injection_pass") is True and injection.get("training_eligible") is True
    )


def run_or_load_execution(
    *,
    host: str,
    command: list[str],
    summary_path: str,
    failure_type: str,
    expected_runtime_action: str,
    expected_source_hashes: dict[str, str],
) -> tuple[PhysicalRuntimeGateReceiptV1, str, str, float, int]:
    returncode = 0
    if not remote_exists(host, summary_path):
        completed = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                host,
                shlex.join(command),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        returncode = completed.returncode
    summary = remote_json(host, summary_path)
    attempts = [item for item in summary.get("attempts", []) if item.get("evidence")]
    if not attempts:
        raise RuntimeError(f"evaluation evidence missing: {summary_path}")
    attempt = attempts[-1]
    evidence_path = str(attempt["evidence"])
    summary_root = PurePosixPath(summary_path).parent
    if not PurePosixPath(evidence_path).is_relative_to(summary_root):
        raise ValueError("evaluation evidence escapes its output root")
    evidence_bytes = remote_bytes(host, evidence_path)
    payload = json.loads(evidence_bytes)
    if validated_source_hashes(payload) != expected_source_hashes:
        raise ValueError(f"{evidence_path}: evaluation scene sources changed")
    if not injection_is_valid(payload, failure_type):
        raise RuntimeError(f"{evidence_path}: requested failure was not physically established")
    receipt = extract_physical_runtime_gate_receipt(
        payload,
        failure_type=failure_type,
    )
    if receipt.runtime_action != expected_runtime_action:
        raise ValueError(f"{evidence_path}: wrong recovery action executed")
    elapsed_s = float(attempt.get("elapsed_s") or 0.0)
    return (
        receipt,
        evidence_path,
        hashlib.sha256(evidence_bytes).hexdigest(),
        elapsed_s,
        returncode,
    )


def violation_from_receipt(
    receipt: PhysicalRuntimeGateReceiptV1,
) -> bool:
    return bool(
        receipt.collision_gate == "REJECTED"
        or (receipt.failure_type != "EMPTY_GRASP" and receipt.safety_gate == "REJECTED")
    )


def baseline_episode(
    *,
    key: str,
    scene_seed: int,
    failure_type: str,
    recovery_sequence: list[str],
    previous_failed_skill: str | None,
    receipt: PhysicalRuntimeGateReceiptV1,
    evidence_sha256: str,
    elapsed_s: float,
) -> M2BClosedLoopEpisodeV1:
    skill = EXPECTED_FIRST_RECOVERY_SKILL[failure_type]
    if not recovery_sequence or recovery_sequence[0] != skill:
        raise ValueError("B0 recovery sequence differs from declared first skill")
    violation = violation_from_receipt(receipt)
    success = receipt.physical_recovery_success and not violation
    decisions = [
        M2BClosedLoopDecisionV1(
            decision_id=f"{key}:B0:decision-{index}",
            step_id=index,
            selected_skill=recovery_skill,
            previous_failed_skill=(
                previous_failed_skill if index == 0 else recovery_sequence[index - 1]
            ),
            model_decision=False,
            mapping_status="NOT_APPLICABLE",
            ik_gate=receipt.ik_gate,
            collision_gate=receipt.collision_gate,
            safety_gate=receipt.safety_gate,
            execution_source="B0_BASELINE",
            executed_skill=recovery_skill,
            outcome=(
                ("SUCCESS" if success else "FAILURE")
                if index == len(recovery_sequence) - 1
                else "UNKNOWN"
            ),
            collision_or_safety_violation=(
                violation if index == len(recovery_sequence) - 1 else False
            ),
            gate_evidence_sha256={
                "ik": evidence_sha256,
                "collision": evidence_sha256,
                "safety": evidence_sha256,
                "execution_outcome": evidence_sha256,
            },
        )
        for index, recovery_skill in enumerate(recovery_sequence)
    ]
    return M2BClosedLoopEpisodeV1(
        episode_id=f"{key}:B0",
        matched_key=key,
        method="B0",
        scene_seed=scene_seed,
        failure_type=failure_type,
        initial_success=False,
        final_success=success,
        recovery_attempted=True,
        recovery_success=success,
        retries=0,
        task_time_s=elapsed_s,
        decisions=decisions,
        collision_or_safety_violation=violation,
    )


def qrm_nonexecution_episode(
    *,
    key: str,
    method: Method,
    scene_seed: int,
    failure_type: str,
    previous_failed_skill: str | None,
    prospective: M2BProspectiveRuntimeDecisionV1,
) -> M2BClosedLoopEpisodeV1:
    decision = M2BClosedLoopDecisionV1(
        decision_id=f"{key}:{method}:decision-0",
        step_id=0,
        selected_skill=prospective.request.skill,
        previous_failed_skill=previous_failed_skill,
        model_decision=True,
        mapping_status=prospective.mapping.status,
        ik_gate=prospective.ik_gate,
        collision_gate=prospective.collision_gate,
        safety_gate=prospective.safety_gate,
        execution_source="NONE",
        executed_skill=None,
        outcome="FAILURE",
        registry_sha256=prospective.registry_sha256,
        model_checkpoint_sha256=prospective.model_checkpoint_sha256,
        model_input_sha256=prospective.model_input_sha256,
        model_output_sha256=prospective.model_output_sha256,
        mapping_result_sha256=prospective.mapping_result_sha256,
    )
    return M2BClosedLoopEpisodeV1(
        episode_id=f"{key}:{method}",
        matched_key=key,
        method=method,
        scene_seed=scene_seed,
        failure_type=failure_type,
        initial_success=False,
        final_success=False,
        recovery_attempted=False,
        recovery_success=None,
        retries=0,
        task_time_s=0.0,
        decisions=[decision],
        collision_or_safety_violation=False,
    )


def qrm_execution_episode(
    *,
    key: str,
    method: Method,
    scene_seed: int,
    failure_type: str,
    recovery_sequence: list[str],
    previous_failed_skill: str | None,
    prospective: M2BProspectiveRuntimeDecisionV1,
    receipt: PhysicalRuntimeGateReceiptV1,
    execution_evidence_sha256: str,
    elapsed_s: float,
) -> M2BClosedLoopEpisodeV1:
    if not prospective.executable_mapping:
        raise ValueError("non-executable model mapping reached execution")
    if not recovery_sequence or recovery_sequence[0] != prospective.request.skill:
        raise ValueError("model skill differs from executed recovery sequence")
    violation = violation_from_receipt(receipt)
    success = receipt.physical_recovery_success and not violation
    gate_hash = cast(str, prospective.isolated_preflight_evidence_sha256)
    model_decision = M2BClosedLoopDecisionV1(
        decision_id=f"{key}:{method}:decision-0",
        step_id=0,
        selected_skill=prospective.request.skill,
        previous_failed_skill=previous_failed_skill,
        model_decision=True,
        mapping_status="VALID",
        ik_gate=prospective.ik_gate,
        collision_gate=prospective.collision_gate,
        safety_gate=prospective.safety_gate,
        execution_source="MODEL_SELECTED_B0_SKILL",
        executed_skill=prospective.request.skill,
        outcome=("SUCCESS" if success else "FAILURE") if len(recovery_sequence) == 1 else "UNKNOWN",
        collision_or_safety_violation=(violation if len(recovery_sequence) == 1 else False),
        registry_sha256=prospective.registry_sha256,
        model_checkpoint_sha256=prospective.model_checkpoint_sha256,
        model_input_sha256=prospective.model_input_sha256,
        model_output_sha256=prospective.model_output_sha256,
        mapping_result_sha256=prospective.mapping_result_sha256,
        gate_evidence_sha256={
            "ik": gate_hash,
            "collision": gate_hash,
            "safety": gate_hash,
            "execution_outcome": execution_evidence_sha256,
        },
    )
    continuations = [
        M2BClosedLoopDecisionV1(
            decision_id=f"{key}:{method}:decision-{index}",
            step_id=index,
            selected_skill=recovery_skill,
            previous_failed_skill=recovery_sequence[index - 1],
            model_decision=False,
            mapping_status="NOT_APPLICABLE",
            ik_gate=receipt.ik_gate,
            collision_gate=receipt.collision_gate,
            safety_gate=receipt.safety_gate,
            execution_source="B0_BASELINE",
            executed_skill=recovery_skill,
            outcome=(
                ("SUCCESS" if success else "FAILURE")
                if index == len(recovery_sequence) - 1
                else "UNKNOWN"
            ),
            collision_or_safety_violation=(
                violation if index == len(recovery_sequence) - 1 else False
            ),
            gate_evidence_sha256={
                "ik": execution_evidence_sha256,
                "collision": execution_evidence_sha256,
                "safety": execution_evidence_sha256,
                "execution_outcome": execution_evidence_sha256,
            },
        )
        for index, recovery_skill in enumerate(recovery_sequence[1:], start=1)
    ]
    return M2BClosedLoopEpisodeV1(
        episode_id=f"{key}:{method}",
        matched_key=key,
        method=method,
        scene_seed=scene_seed,
        failure_type=failure_type,
        initial_success=False,
        final_success=success,
        recovery_attempted=True,
        recovery_success=success,
        retries=0,
        task_time_s=elapsed_s,
        decisions=[model_decision, *continuations],
        collision_or_safety_violation=violation,
    )


def append_episode(path: Path, episode: M2BClosedLoopEpisodeV1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(episode.model_dump_json() + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def append_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_journal_episode(journal: dict[str, Any], episode: M2BClosedLoopEpisodeV1) -> None:
    if journal.get("schema_version") != "M2BClosedLoopExecutionJournalV1":
        raise ValueError("invalid execution journal schema")
    if journal.get("teacher_used") is not False:
        raise ValueError("execution journal does not exclude Teacher")
    if journal.get("privileged_truth_policy_input") is not False:
        raise ValueError("execution journal used privileged policy input")
    if journal.get("matched_key") != episode.matched_key:
        raise ValueError("execution journal matched key differs")
    digest = journal.get("execution_evidence_sha256")
    if journal.get("status") == "EVALUATION_EXECUTION_RECORDED":
        if re.fullmatch(r"[0-9a-f]{64}", str(digest or "")) is None:
            raise ValueError("execution journal evidence hash missing")
        if not journal.get("execution_evidence_path"):
            raise ValueError("execution journal evidence path missing")
        if not any(
            decision.gate_evidence_sha256.get("execution_outcome") == digest
            for decision in episode.decisions
        ):
            raise ValueError("episode is not bound to execution evidence")
    elif journal.get("status") == "NOT_EXECUTED_MAPPING_REJECTED":
        if episode.recovery_attempted or digest is not None:
            raise ValueError("non-execution journal contradicts episode")
    else:
        raise ValueError("unknown execution journal status")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fc-decisions", required=True, type=Path)
    parser.add_argument("--fc-decisions", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument(
        "--project-root",
        default="/var/tmp/m2a-isaac-project-20260731",
    )
    parser.add_argument(
        "--source-root",
        default="/var/tmp/m2b-heldout-source-copy-20260731",
    )
    parser.add_argument(
        "--remote-output-root",
        default=("/var/tmp/xh-data/isaac-industrial/m2b/matched-closed-loop-v1"),
    )
    parser.add_argument("--gpu", type=int, choices=(0, 1), default=None)
    parser.add_argument("--max-matched-keys", type=int, default=10)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.gpu is None and args.max_matched_keys < 10:
        raise ValueError("formal matched evaluation requires at least 10 keys")
    registry = load_registry(args.registry)
    registry_sha256 = hashlib.sha256(args.registry.read_bytes()).hexdigest()
    no_fc = load_decisions(args.no_fc_decisions)
    fc = load_decisions(args.fc_decisions)
    pairs = matched_pairs(
        no_fc,
        fc,
        max_keys=args.max_matched_keys,
        require_count=args.gpu is None,
    )
    if any(decision.registry_sha256 != registry_sha256 for pair in pairs for decision in pair):
        raise ValueError("prospective decisions use a different registry")
    rows = [json.loads(line) for line in args.dataset.read_text().splitlines() if line.strip()]
    episodes = {str(row["episode_id"]): row for row in rows}
    if len(episodes) != len(rows):
        raise ValueError("duplicate dataset episode_id")
    existing = (
        [
            M2BClosedLoopEpisodeV1.model_validate_json(line)
            for line in args.output.read_text().splitlines()
            if line.strip()
        ]
        if args.output.is_file()
        else []
    )
    existing_by_id = {item.episode_id: item for item in existing}
    if len(existing_by_id) != len(existing):
        raise ValueError("output contains duplicate episode_id")
    journal_rows = (
        [json.loads(line) for line in args.journal.read_text().splitlines() if line.strip()]
        if args.journal.is_file()
        else []
    )
    journal_by_id = {str(item["episode_id"]): item for item in journal_rows}
    if len(journal_by_id) != len(journal_rows):
        raise ValueError("journal contains duplicate episode_id")
    orphaned = sorted(set(existing_by_id) - set(journal_by_id))
    if orphaned:
        raise ValueError(f"episodes lack execution journal records: {orphaned}")
    for episode_id, episode in existing_by_id.items():
        validate_journal_episode(journal_by_id[episode_id], episode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.touch(exist_ok=True)
    args.journal.parent.mkdir(parents=True, exist_ok=True)
    args.journal.touch(exist_ok=True)
    run_records = []
    expected_episode_ids: set[str] = set()
    expected_matched_keys: set[str] = set()
    for no_fc_decision, fc_decision in pairs:
        sample_id = no_fc_decision.sample_id
        episode_id = episode_id_from_sample(sample_id)
        if episode_id not in episodes:
            raise ValueError(f"{sample_id}: dataset episode missing")
        dataset_episode = episodes[episode_id]
        failure_type = str(dataset_episode["failure_context"]["failure_type"])
        if failure_type != no_fc_decision.failure_type:
            raise ValueError(f"{sample_id}: dataset failure type mismatch")
        scene_seed = int(dataset_episode["scene_seed"])
        gpu = scene_seed % 2
        if args.gpu is not None and gpu != args.gpu:
            continue
        evidence_path = str(dataset_episode["provenance"]["evidence_path"])
        evidence_bytes = remote_bytes(args.host, evidence_path)
        verify_bytes_sha256(
            evidence_bytes,
            str(dataset_episode["provenance"]["evidence_sha256"]),
            f"{sample_id}: source evidence",
        )
        source_payload = json.loads(evidence_bytes)
        source_hashes = validated_source_hashes(source_payload)
        for prospective in (no_fc_decision, fc_decision):
            if prospective.source_hashes and (prospective.source_hashes != source_hashes):
                raise ValueError(f"{sample_id}: preflight scene sources differ")
        scene_root = scene_root_from_evidence(evidence_path, scene_seed)
        stage_hash = source_hashes.get("m1b_physics_scene.usdc")
        if stage_hash is None:
            raise ValueError(f"{sample_id}: m1b_physics_scene.usdc hash missing")
        stage = remote_stage(
            args.host,
            scene_root,
            expected_sha256=stage_hash,
        )
        required_sources = {
            "m1b_physics_scene.usdc": stage,
            f"scene-{scene_seed}.sdf": (f"{args.source_root}/scene-{scene_seed}.sdf"),
            f"scene-{scene_seed}.supervision.json": (
                f"{args.source_root}/scene-{scene_seed}.supervision.json"
            ),
        }
        for name, path in required_sources.items():
            if name not in source_hashes:
                raise ValueError(f"{sample_id}: {name} hash missing")
            verify_bytes_sha256(
                remote_bytes(args.host, path),
                source_hashes[name],
                f"{sample_id}: {name}",
            )
        key = matched_key(
            sample_id=sample_id,
            scene_seed=scene_seed,
            failure_type=failure_type,
            source_hashes=source_hashes,
        )
        expected_matched_keys.add(key)
        injection_entity, task_target_entity = target_entities(source_payload, failure_type)
        expected_action = expected_first_runtime_action(registry, failure_type)
        previous_failed_skill = dataset_episode["failure_context"].get("last_skill")
        recovery_sequence = [str(skill) for skill in dataset_episode["recovery_sequence"]]
        method_decisions = {
            "QRM_COARSE_NO_FC": no_fc_decision,
            "QRM_COARSE_FC": fc_decision,
        }
        for method in METHODS:
            output_episode_id = f"{key}:{method}"
            expected_episode_ids.add(output_episode_id)
            if output_episode_id in existing_by_id:
                continue
            prospective = method_decisions.get(method)
            if prospective is not None and not prospective.executable_mapping:
                episode = qrm_nonexecution_episode(
                    key=key,
                    method=method,
                    scene_seed=scene_seed,
                    failure_type=failure_type,
                    previous_failed_skill=previous_failed_skill,
                    prospective=prospective,
                )
                journal = {
                    "schema_version": "M2BClosedLoopExecutionJournalV1",
                    "episode_id": episode.episode_id,
                    "method": method,
                    "matched_key": key,
                    "status": "NOT_EXECUTED_MAPPING_REJECTED",
                    "summary_path": None,
                    "execution_evidence_path": None,
                    "execution_evidence_sha256": None,
                    "privileged_truth_policy_input": False,
                    "teacher_used": False,
                }
                if episode.episode_id not in journal_by_id:
                    append_json(args.journal, journal)
                    journal_by_id[episode.episode_id] = journal
                validate_journal_episode(journal_by_id[episode.episode_id], episode)
                append_episode(args.output, episode)
                existing_by_id[episode.episode_id] = episode
                run_records.append(journal)
                continue
            checkpoint_key = (
                prospective.model_checkpoint_sha256[:16] if prospective is not None else "baseline"
            )
            remote_output = (
                f"{args.remote_output_root}/gpu{gpu}/{key[10:30]}/{method.lower()}-{checkpoint_key}"
            )
            command = preflight_command(
                project_root=args.project_root,
                source_root=args.source_root,
                stage=stage,
                scene_seed=scene_seed,
                failure_type=failure_type,
                gpu=gpu,
                output_root=remote_output,
                injection_entity=injection_entity,
                task_target_entity=task_target_entity,
                container_prefix=(f"m2b-loop-g{gpu}-{key[10:22]}-{method.lower()}"),
            )
            summary_path = f"{remote_output}/physical-failure-smoke.json"
            (
                receipt,
                execution_evidence_path,
                execution_sha256,
                elapsed_s,
                returncode,
            ) = run_or_load_execution(
                host=args.host,
                command=command,
                summary_path=summary_path,
                failure_type=failure_type,
                expected_runtime_action=expected_action,
                expected_source_hashes=source_hashes,
            )
            if prospective is None:
                episode = baseline_episode(
                    key=key,
                    scene_seed=scene_seed,
                    failure_type=failure_type,
                    recovery_sequence=recovery_sequence,
                    previous_failed_skill=previous_failed_skill,
                    receipt=receipt,
                    evidence_sha256=execution_sha256,
                    elapsed_s=elapsed_s,
                )
            else:
                if prospective.mapping.runtime_action != expected_action:
                    raise ValueError(f"{sample_id}: model action differs from executed action")
                episode = qrm_execution_episode(
                    key=key,
                    method=method,
                    scene_seed=scene_seed,
                    failure_type=failure_type,
                    recovery_sequence=recovery_sequence,
                    previous_failed_skill=previous_failed_skill,
                    prospective=prospective,
                    receipt=receipt,
                    execution_evidence_sha256=execution_sha256,
                    elapsed_s=elapsed_s,
                )
            journal = {
                "schema_version": "M2BClosedLoopExecutionJournalV1",
                "episode_id": episode.episode_id,
                "method": method,
                "matched_key": key,
                "status": "EVALUATION_EXECUTION_RECORDED",
                "runner_returncode": returncode,
                "summary_path": summary_path,
                "execution_evidence_path": execution_evidence_path,
                "execution_evidence_sha256": execution_sha256,
                "privileged_truth_policy_input": False,
                "teacher_used": False,
            }
            if episode.episode_id not in journal_by_id:
                append_json(args.journal, journal)
                journal_by_id[episode.episode_id] = journal
            else:
                validate_journal_episode(journal_by_id[episode.episode_id], episode)
            append_episode(args.output, episode)
            existing_by_id[episode.episode_id] = episode
            run_records.append(journal)
    if set(existing_by_id) != expected_episode_ids:
        raise ValueError("closed-loop output differs from selected matched shard")
    if set(journal_by_id) != expected_episode_ids:
        raise ValueError("execution journal differs from selected matched shard")
    report = {
        "schema_version": "M2BMatchedClosedLoopBatchReportV1",
        "selected_matched_keys": len(pairs),
        "matched_keys_in_output": len(expected_matched_keys),
        "gpu_filter": args.gpu,
        "episodes_in_output": len(existing_by_id),
        "new_records": len(run_records),
        "runs": run_records,
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "journal": str(args.journal),
        "journal_records": len(journal_by_id),
        "journal_sha256": hashlib.sha256(args.journal.read_bytes()).hexdigest(),
        "model_decisions_executed": sum(
            decision.execution_source == "MODEL_SELECTED_B0_SKILL"
            for episode in existing_by_id.values()
            for decision in episode.decisions
        ),
        "post_execution_receipts_promoted_to_preflight": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
