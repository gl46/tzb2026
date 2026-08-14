#!/usr/bin/env python3
"""Replay the ADR-0025 section 3 S4 training-eligibility yield audit."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "M2CS4ADR0025TrainingEligibilityYieldAuditV1"
STATUS = "BLOCKED_ZERO_OBSERVED_ELIGIBLE_CHAIN_YIELD"
AUDIT_PATH = Path("scripts/m2c/audit_s4_training_eligibility_yield_adr0025.py")
ADR_PATH = Path("docs/decisions/ADR-0025-m2c-raw-capacity-acm-and-yield.md")
ADR_SHA256 = "6f27171d319e3f966c652ca9f8c0fe7c641f4bf420de58642869f9c9c805c3aa"
OFFLINE_REPLAY_PATH = Path("reports/m2c-s4-v4-scene19083-offline-raw-capacity-replay.json")
OFFLINE_REPLAY_SHA256 = "d467216f96d0e0cbb3ba307faa8dcc3d76fe602be70903f59e7e7321ebf09736"


@dataclass(frozen=True)
class SourceReportSpec:
    path: Path
    sha256: str
    schema_version: str
    status: str
    attempt_count: int
    unique_key_count: int
    complete_chain_count: int
    classifications: Mapping[str, int]


SOURCE_REPORTS: tuple[SourceReportSpec, ...] = (
    SourceReportSpec(
        path=Path("reports/m2c-s4-v3-path-blocked-train-collection.json"),
        sha256="c505ec6517d7a766768f72cd14fc49d1919cff234dc2d8fbee1877104b41480d",
        schema_version="M2CS4V3TrainCollectionAuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES",
        attempt_count=9,
        unique_key_count=8,
        complete_chain_count=7,
        classifications={
            "INFRASTRUCTURE_STAGE_EXIT_139": 1,
            "PRE_KIT_TZDATA_GUARD_FAILURE": 1,
            "RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 5,
            "RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 2,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v3-path-blocked-train-collection-batch03.json"),
        sha256="0fe177565b6d842fa6e1fc80a8d1e0822283d3557aeb41d56c36140e4dbacb57",
        schema_version="M2CS4V3TrainCollectionBatch03AuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V3_TRAIN_SAMPLES_BATCH03",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=3,
        classifications={
            "RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 1,
            "RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
            "RAW_V3_REGRASP_LIFTED_PUBLIC_PREDICATE_REJECTED": 1,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch04-permission-failure.json"),
        sha256="a80cb5891a88bba124725f7588e658eb15282ba38e455bc9befb65ceb39e751a",
        schema_version="M2CS4V4Batch04InfrastructureFailureAuditV1",
        status="BLOCKED_PRE_KIT_STAGE_OUTPUT_PERMISSION_FAILURE",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=0,
        classifications={"PRE_KIT_STAGE_OUTPUT_PERMISSION_FAILURE": 3},
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch06-snapshot-owner-failure.json"),
        sha256="415364cb1478f812da42c9aa4c81f47690348ae53ab9d067d0950c3a19ac9d68",
        schema_version="M2CS4V4Batch06SnapshotOwnerFailureAuditV1",
        status="BLOCKED_PRE_KIT_SOURCE_SNAPSHOT_OWNER_FALSE_REJECTION",
        attempt_count=1,
        unique_key_count=1,
        complete_chain_count=0,
        classifications={"PRE_KIT_SOURCE_SNAPSHOT_OWNER_FALSE_REJECTION": 1},
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch07-pre-timeline-proprio-failure.json"),
        sha256="bf42d1b1d0703c7007255a20e52d0e661bf40461e4ec0ebc52ed053f0bf12fae",
        schema_version="M2CS4V4Batch07PreTimelineProprioFailureAuditV1",
        status="BLOCKED_PRE_TIMELINE_PROPRIOCEPTION_READ",
        attempt_count=1,
        unique_key_count=1,
        complete_chain_count=0,
        classifications={"PRE_TIMELINE_PHYSICS_TENSOR_READ": 1},
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch08-collection.json"),
        sha256="226761a056c6c3a127784019147e49b3e6e301f72d4b9711e222cd7c939a2894",
        schema_version="M2CS4V4Batch08CollectionAuditV1",
        status="BLOCKED_RAW_DETECTION_CAPACITY_SCHEMA_DECISION_REQUIRED",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=1,
        classifications={
            "ISAAC_STAGE_PROCESS_EXIT_139": 2,
            "RAW_CHAIN_COMPLETE_HOST_SCHEMA_CAPACITY_REJECTED": 1,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch09-collection.json"),
        sha256="97a8c00e99d28e6eff306fcdf349e97dff4366508bca79487dce55f37137ac2c",
        schema_version="M2CS4V4Batch09CollectionAuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH09",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=3,
        classifications={
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
            "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch10-collection.json"),
        sha256="ee6414efcf02a71959e501bdd91edf3d86f9003c978a495790d8cfb6fc99b83a",
        schema_version="M2CS4V4Batch10CollectionAuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH10",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=3,
        classifications={
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
            "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch11-collection.json"),
        sha256="c010e89cd457be341a1d8d62d2ef95d98c5a5b81eca8117b0d9d2e130f9a6d19",
        schema_version="M2CS4V4Batch11CollectionAuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH11_WITH_STAGE_FAILURE",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=2,
        classifications={
            "ISAAC_STAGE_PROCESS_EXIT_139": 1,
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch12-collection.json"),
        sha256="405848262c0f3b99d5421d4e37c0c68c58de0a0b2feda3232921c9820cdb2c70",
        schema_version="M2CS4V4Batch12CollectionAuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH12",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=3,
        classifications={
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
            "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
        },
    ),
    SourceReportSpec(
        path=Path("reports/m2c-s4-v4-batch13-collection.json"),
        sha256="117c5f7d3b41e80ad1d41a8c494260b43d325e99166e27793cd660d180971e7b",
        schema_version="M2CS4V4Batch13CollectionAuditV1",
        status="BLOCKED_ZERO_ELIGIBLE_V4_TRAIN_SAMPLES_BATCH13",
        attempt_count=3,
        unique_key_count=3,
        complete_chain_count=3,
        classifications={
            "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": 2,
            "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": 1,
        },
    ),
)


SOURCE_BINDINGS: Mapping[str, str] = {
    "scripts/m2c/package_path_blocked_collection.py": (
        "331a0fbc64411f63e53087e23d051a360ba2d45cc6f1e22504444a4fa8204d46"
    ),
    "scripts/m2c/qwen_coarse_v4.py": (
        "dc869c8325dae1c21fd999eff141bb5f2a2b2acb2b644b47067da38c39250298"
    ),
    "scripts/m2c/train_qwen_coarse_v4.py": (
        "2d4e38e211c492e08f4be53e68e334735776285c0bfe0977ce8e68b7161304a6"
    ),
    "src/xh_agent/policy/qrm_lite/path_blocked_collection_v4.py": (
        "467ce96ea2b5db7b84904bbe489e4436f43f82587acefbb56027bd927119216c"
    ),
    "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py": (
        "915fb2567e86294d38a20d82f75b0728f87558aff89d84bb54ec4c01b1a4f646"
    ),
}


SOURCE_MARKERS: Mapping[str, tuple[bytes, ...]] = {
    "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py": (
        b'if not evidence.final_task_success:\n        reject("FINAL_TASK_NOT_SUCCESSFUL")',
        b'if not validation.model_training_eligible:\n        return PathBlockedSupervisedDatasetV3(\n            status="EMPTY",\n            samples=[]',
    ),
    "src/xh_agent/policy/qrm_lite/path_blocked_collection_v4.py": (
        b'if not evidence.final_task_success:\n        reject("FINAL_TASK_NOT_SUCCESSFUL")',
        b'if not validation.model_training_eligible:\n        return PathBlockedSupervisedDatasetV4(\n            status="EMPTY",\n            samples=[]',
    ),
    "scripts/m2c/package_path_blocked_collection.py": (
        b"or len(dataset.samples) != EXPECTED_STEP_COUNT",
        b'or (role == "TRAIN" and not validation.model_training_eligible)',
    ),
    "scripts/m2c/qwen_coarse_v4.py": (
        b'raise ValueError("V4 Qwen sample is not physically training-eligible")',
        b'raise ValueError("V4 package is not independently physical-training eligible")',
    ),
    "scripts/m2c/train_qwen_coarse_v4.py": (
        b'raise ValueError("V4 real training has zero complete eligible episodes")',
    ),
}


class S4YieldAuditError(ValueError):
    """The immutable source reports or the frozen eligibility predicate drifted."""


def read_regular_file_once(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise S4YieldAuditError(f"audit input is not single-link regular: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise S4YieldAuditError(f"audit input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise S4YieldAuditError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise S4YieldAuditError(f"{label} is not an object")
    return value


def read_bound_json(
    path: Path,
    *,
    expected_sha256: str,
    label: str,
) -> dict[str, Any]:
    raw = read_regular_file_once(path)
    if _sha256(raw) != expected_sha256:
        raise S4YieldAuditError(f"{label} SHA-256 differs")
    return _json_object(raw, label=label)


def _identity_key(attempt: Mapping[str, Any]) -> tuple[int, int, str, str, str]:
    identity = attempt.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "failure_seed",
        "matched_key",
        "scene_seed",
        "sdf_sha256",
        "supervision_sha256",
    }:
        raise S4YieldAuditError("attempt identity fields differ")
    values = (
        identity["scene_seed"],
        identity["failure_seed"],
        identity["matched_key"],
        identity["sdf_sha256"],
        identity["supervision_sha256"],
    )
    if (
        not isinstance(values[0], int)
        or not isinstance(values[1], int)
        or not all(isinstance(value, str) and value for value in values[2:])
    ):
        raise S4YieldAuditError("attempt identity value types differ")
    return values


def _verify_source_report(
    project_root: Path,
    spec: SourceReportSpec,
) -> tuple[dict[str, Any], set[tuple[int, int, str, str, str]]]:
    report = read_bound_json(
        project_root / spec.path,
        expected_sha256=spec.sha256,
        label=spec.path.as_posix(),
    )
    if report.get("schema_version") != spec.schema_version or report.get("status") != spec.status:
        raise S4YieldAuditError(f"source report identity differs: {spec.path}")
    attempts = report.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != spec.attempt_count:
        raise S4YieldAuditError(f"source attempt count differs: {spec.path}")
    if Counter(item.get("classification") for item in attempts) != Counter(spec.classifications):
        raise S4YieldAuditError(f"source classifications differ: {spec.path}")
    identities = {_identity_key(item) for item in attempts}
    if len(identities) != spec.unique_key_count:
        raise S4YieldAuditError(f"source unique identity count differs: {spec.path}")
    if any(
        item.get("training_sample_eligible") is not False
        or item.get("training_sample_packaged") is not False
        or item.get("teacher_used") is not False
        or item.get("privileged_truth_policy_input") is not False
        for item in attempts
    ):
        raise S4YieldAuditError(f"source eligibility or policy-boundary claim differs: {spec.path}")
    counts = report.get("observed_counts")
    if not isinstance(counts, dict):
        raise S4YieldAuditError(f"source observed counts missing: {spec.path}")
    if counts.get("training_samples_eligible") != 0 or counts.get("training_samples_packaged") != 0:
        raise S4YieldAuditError(f"source eligible count differs: {spec.path}")
    return report, identities


def verify_source_binding(path: Path, *, expected_sha256: str, markers: Sequence[bytes]) -> None:
    raw = read_regular_file_once(path)
    if _sha256(raw) != expected_sha256:
        raise S4YieldAuditError(f"eligibility implementation SHA-256 differs: {path}")
    for marker in markers:
        if raw.count(marker) != 1:
            raise S4YieldAuditError(f"eligibility implementation marker differs: {path}")


def _verify_complete_v3_attempt(attempt: Mapping[str, Any]) -> str:
    evidence = attempt.get("classification_evidence")
    if not isinstance(evidence, dict):
        raise S4YieldAuditError("complete V3 chain lacks classification evidence")
    if (
        evidence.get("chain_schema") != "M2CPathBlockedProbeChainV3"
        or evidence.get("physical_chain_steps") != 8
        or evidence.get("raw_probe_status") != "PASS"
        or evidence.get("final_task_success") is not False
        or evidence.get("step_0_through_6_all_gates_pass") is not True
    ):
        raise S4YieldAuditError("complete V3 chain evidence differs")
    classification = attempt["classification"]
    if classification == "RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED":
        return "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"
    if classification == "RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED":
        return "TERMINAL_PREGRASP_IK_GATE_REJECTED"
    if classification == "RAW_V3_REGRASP_LIFTED_PUBLIC_PREDICATE_REJECTED":
        return "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED"
    raise S4YieldAuditError("unexpected complete V3 classification")


def _verify_complete_v4_attempt(attempt: Mapping[str, Any]) -> str:
    if (
        attempt.get("raw_chain_schema") != "M2CPathBlockedRawProbeChainV4"
        or attempt.get("physical_skill_receipts") != 8
        or attempt.get("raw_chain_final_task_success") is not False
        or attempt.get("step_0_through_6_all_gates_pass") is not True
        or attempt.get("host_replay_passed") is not True
        or attempt.get("offline_dataset_status") != "EMPTY"
        or attempt.get("offline_dataset_sample_count") != 0
        or attempt.get("collision_or_safety_violations") != 0
    ):
        raise S4YieldAuditError("complete V4 chain evidence differs")
    classification = attempt["classification"]
    if classification == "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED":
        return "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"
    if classification == "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED":
        return "TERMINAL_PREGRASP_IK_GATE_REJECTED"
    raise S4YieldAuditError("unexpected complete V4 classification")


def build_report(*, project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    adr_raw = read_regular_file_once(project_root / ADR_PATH)
    if _sha256(adr_raw) != ADR_SHA256:
        raise S4YieldAuditError("accepted ADR-0025 SHA-256 differs")

    parsed: list[tuple[SourceReportSpec, dict[str, Any]]] = []
    identity_sets: list[set[tuple[int, int, str, str, str]]] = []
    source_rows: list[dict[str, Any]] = []
    for spec in SOURCE_REPORTS:
        report, identities = _verify_source_report(project_root, spec)
        parsed.append((spec, report))
        identity_sets.append(identities)
        source_rows.append(
            {
                "path": spec.path.as_posix(),
                "sha256": spec.sha256,
                "schema_version": spec.schema_version,
                "status": spec.status,
                "attempt_rows": spec.attempt_count,
                "unique_train_identities": spec.unique_key_count,
                "complete_eight_step_chains": spec.complete_chain_count,
                "eligible_training_episodes": 0,
            }
        )
    for left_index, left in enumerate(identity_sets):
        for right in identity_sets[left_index + 1 :]:
            if left & right:
                raise S4YieldAuditError("source report identity sets are not disjoint")
    all_identities = set().union(*identity_sets)
    if len(all_identities) != 34:
        raise S4YieldAuditError("combined unique TRAIN identity count differs")

    taxonomy: Counter[str] = Counter()
    complete_chain_count = 0
    for spec, report in parsed[:2]:
        for attempt in report["attempts"]:
            if str(attempt["classification"]).startswith("RAW_V3_"):
                taxonomy[_verify_complete_v3_attempt(attempt)] += 1
                complete_chain_count += 1
    for spec, batch_report in parsed[-5:]:
        verified_report_chains = 0
        for attempt in batch_report["attempts"]:
            if attempt.get("raw_chain_schema") != "M2CPathBlockedRawProbeChainV4":
                continue
            taxonomy[_verify_complete_v4_attempt(attempt)] += 1
            complete_chain_count += 1
            verified_report_chains += 1
        if verified_report_chains != spec.complete_chain_count:
            raise S4YieldAuditError("source complete V4 chain count differs")
    if complete_chain_count != 24:
        raise S4YieldAuditError("complete collected chain count differs")

    offline = read_bound_json(
        project_root / OFFLINE_REPLAY_PATH,
        expected_sha256=OFFLINE_REPLAY_SHA256,
        label=OFFLINE_REPLAY_PATH.as_posix(),
    )
    unchanged = offline.get("unchanged_outcome")
    if (
        offline.get("schema_version") != "M2CS4V4Scene19083OfflineRawCapacityReplayV1"
        or offline.get("status") != "PASS_OFFLINE_REPLAY_EXCLUDED_UNCHANGED_PHYSICAL_FAILURE"
        or not isinstance(unchanged, dict)
        or unchanged.get("replayed_final_task_success") is not False
        or unchanged.get("training_sample_eligible") is not False
        or unchanged.get("offline_dataset_status") != "EMPTY"
        or unchanged.get("offline_dataset_sample_count") != 0
        or unchanged.get("terminal_controller_gate") != "REJECTED"
        or unchanged.get("terminal_execution_status") != "CONTACT_GATE_REJECTED"
        or offline.get("training_executed") is not False
        or offline.get("teacher_used") is not False
        or offline.get("privileged_truth_policy_input") is not False
    ):
        raise S4YieldAuditError("scene 19083 offline replay outcome differs")
    taxonomy["TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"] += 1
    complete_chain_count += 1
    if complete_chain_count != 25 or taxonomy != Counter(
        {
            "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED": 17,
            "TERMINAL_PREGRASP_IK_GATE_REJECTED": 7,
            "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED": 1,
        }
    ):
        raise S4YieldAuditError("complete-chain failure taxonomy differs")

    for relative, expected_sha256 in SOURCE_BINDINGS.items():
        verify_source_binding(
            project_root / relative,
            expected_sha256=expected_sha256,
            markers=SOURCE_MARKERS[relative],
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "audit_implementation": {
            "path": AUDIT_PATH.as_posix(),
            "sha256": _sha256(read_regular_file_once(project_root / AUDIT_PATH)),
        },
        "accepted_adr": {
            "path": ADR_PATH.as_posix(),
            "sha256": ADR_SHA256,
            "section": "3",
        },
        "source_reports": source_rows,
        "scene_19083_offline_replay": {
            "path": OFFLINE_REPLAY_PATH.as_posix(),
            "sha256": OFFLINE_REPLAY_SHA256,
            "schema_upgrade_passed": True,
            "source_final_task_success": False,
            "replayed_final_task_success": False,
            "training_sample_eligible": False,
            "offline_dataset_sample_count": 0,
            "terminal_execution_status": "CONTACT_GATE_REJECTED",
        },
        "identity_audit": {
            "attempt_rows": sum(spec.attempt_count for spec in SOURCE_REPORTS),
            "duplicate_attempt_rows_within_first_v3_report": 1,
            "source_identity_sets_pairwise_disjoint": True,
            "unique_v3_train_identities": 11,
            "unique_v4_train_identities": 23,
            "unique_train_identities_total": 34,
        },
        "observed_yield": {
            "complete_eight_step_chains": complete_chain_count,
            "eligible_training_episodes": 0,
            "packaged_training_episodes": 0,
            "eligible_yield_per_unique_train_identity": 0.0,
            "eligible_yield_per_complete_eight_step_chain": 0.0,
            "finite_key_projection_for_one_eligible_episode": None,
            "projection_status": "NO_FINITE_EVIDENCE_BASED_PROJECTION_AT_ZERO_OBSERVED_POINT_YIELD",
        },
        "complete_chain_failure_taxonomy": dict(sorted(taxonomy.items())),
        "frozen_training_predicate": {
            "source_bindings": dict(sorted(SOURCE_BINDINGS.items())),
            "episode_atomic_eligibility": True,
            "final_task_success_required": True,
            "exact_step_count_required": 8,
            "failed_episode_emits_intermediate_training_rows": False,
            "zero_eligible_episode_training_rejected": True,
            "minimum_code_level_eligible_episode_count": 1,
            "predicate_changed_by_this_audit": False,
        },
        "root_cause_finding": {
            "status": "RECURRENT_TERMINAL_REGRASP_APPROACH_OR_CONTACT_ACCEPTANCE_MISMATCH_NOT_CAUSALLY_ISOLATED",
            "complete_v3_chains_with_steps_0_through_6_all_gates_pass": 10,
            "complete_v4_chains_with_steps_0_through_6_all_gates_pass": 14,
            "complete_chains_ending_in_contact_or_controller_rejection": 17,
            "complete_chains_ending_in_pregrasp_ik_rejection": 7,
            "complete_chains_lifted_but_rejected_by_public_success_predicate": 1,
            "causal_attribution_limit": (
                "Evidence does not isolate perception offset, approach geometry, or object state as the cause."
            ),
            "scene_19083_additional_offline_exclusion": "STEP_1_PUBLIC_TARGET_OUTSIDE_V4_K8",
            "safety_gate_or_threshold_change_authorized": False,
        },
        "checkpoint_implication": {
            "bundle_smoke_checkpoint_asia_shanghai": "2026-08-20",
            "s4_pure_model_success_episodes": None,
            "s4_formal_q_b_evaluation_executed": False,
            "pure_zero_claimed": False,
            "unchanged_observed_yield_supports_finite_collection_plan": False,
            "training_authorized_now": False,
            "reason": (
                "Zero eligible episodes provides no finite evidence-based key count even for the code minimum of one eligible episode."
            ),
        },
        "evidence_claims": {
            "collection_performed_by_this_audit": False,
            "physical_execution_performed_by_this_audit": False,
            "training_performed": False,
            "model_rollout_performed": False,
            "formal_q_b_evaluation_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "b0_or_safety_contract_changed": False,
        },
        "blockers": [
            "ZERO_ELIGIBLE_TRAINING_EPISODES_ACROSS_34_UNIQUE_TRAIN_IDENTITIES",
            "NO_FINITE_EVIDENCE_BASED_COLLECTION_SIZE_AT_ZERO_OBSERVED_POINT_YIELD",
            "TRAINING_REQUIRES_AT_LEAST_ONE_COMPLETE_ELIGIBLE_EPISODE",
            "FORMAL_Q_B_REMAINS_UNMEASURED",
        ],
        "one_next_command": (
            "PYTHONPATH=src:scripts uv run python "
            "scripts/m2c/audit_s4_training_eligibility_yield_adr0025.py "
            "--expected-json reports/m2c-s4-training-eligibility-yield-adr0025.json"
        ),
    }


def report_bytes(report: Mapping[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def render_markdown(report: Mapping[str, Any]) -> str:
    yield_data = report["observed_yield"]
    taxonomy = report["complete_chain_failure_taxonomy"]
    return f"""# M2C S4 training-eligibility yield audit (ADR-0025 §3)

Status: `{report["status"]}`

This report replays eleven immutable collection reports plus the governed offline replay of scene 19083. It does not collect, execute physics, train, run a model rollout, or perform formal Q-B evaluation.

## Measured yield

- Unique TRAIN identities: **{report["identity_audit"]["unique_train_identities_total"]}** (V3: 11; V4: 23)
- Complete eight-step physical chains: **{yield_data["complete_eight_step_chains"]}**
- Eligible and packaged training episodes: **0**
- Eligible yield per attempted identity: **0/34 = 0.0**
- Eligible yield conditional on a complete chain: **0/25 = 0.0**
- Finite evidence-based key projection for one eligible episode: **none at the observed zero point yield**

The code-level minimum is one complete eligible episode; the current trainer rejects zero. This is not a claim that model capability is zero: pure model success remains `null` because no formal Q-B evaluation has run.

## Complete-chain failure taxonomy

- Terminal contact/controller rejection: **{taxonomy["TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"]}**
- Terminal pregrasp IK rejection: **{taxonomy["TERMINAL_PREGRASP_IK_GATE_REJECTED"]}**
- Lifted but rejected by the public success predicate: **{taxonomy["LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED"]}**

All ten complete V3 chains and all fourteen newly collected Batch-09/10/11/12/13 V4 chains passed gates for steps 0–6. The evidence supports a recurring terminal regrasp approach/contact-acceptance mismatch, but does not isolate perception offset, approach geometry, or object state as its cause. Scene 19083 passes the 32-detection offline schema replay but remains excluded by its unchanged physical failure; its replay also records a step-1 public-target-outside-K8 exclusion.

## Frozen eligibility consequence

V3 and V4 eligibility are episode-atomic: `final_task_success=true`, an exact eight-step chain, and the remaining physical/public gates are required. A failed episode emits an empty dataset, so intermediate steps from these failed chains are not currently model-supervisable rows. This audit does not change that predicate, B0, a safety gate, or a threshold.

## 2026-08-20 checkpoint

At the unchanged observed point yield, no finite collection size can be justified even for one eligible episode. Training remains unauthorized and formal Q-B remains unmeasured. The Phase-2 bundle-smoke checkpoint stays 2026-08-20 (Asia/Shanghai).

Replay:

```bash
{report["one_next_command"]}
```
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--expected-json", type=Path)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    report = build_report(project_root=args.project_root)
    encoded = report_bytes(report)
    if args.expected_json is not None and read_regular_file_once(args.expected_json) != encoded:
        raise SystemExit("S4 ADR-0025 yield audit differs from expected JSON")
    if args.markdown:
        print(render_markdown(report), end="")
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
