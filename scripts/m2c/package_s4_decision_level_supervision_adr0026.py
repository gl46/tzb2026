#!/usr/bin/env python3
"""Replay and package ADR-0026 section 4 decision-level supervision.

The command is offline-only.  It reads the immutable V3/V4 evidence roots,
recomputes every public candidate/association input and physical receipt,
and publishes revision-separated JSONL shards.  It never launches Isaac,
collects, trains, runs a model, or changes the Q-B success definition.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from xh_agent.policy.qrm_lite.contracts import CoarseIntentV2, FailureType
from xh_agent.policy.qrm_lite.decision_level_supervision_v1 import (
    ADR0026_PATH,
    ADR0026_SHA256,
    DecisionGateSummaryV1,
    M2CS4DecisionLevelDatasetManifestV1,
    M2CS4DecisionLevelSupervisionRowV1,
    M2CS4DecisionLevelTrainingSampleV1,
    canonical_json_bytes,
    canonical_sha256,
    decide_adr0026_episode_eligibility,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    EXPECTED_PATH_BLOCKED_CHAIN,
    NONE_DESTINATION_CLASS,
    NONE_POINTER_CLASS,
    REGISTERED_DESTINATION_CELLS,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2C_Q012_V4_SKILL_LABELS,
    M2CPathBlockedProbeChainV4,
    M2CV4RawPublicAssociationCaptureV1,
    M2CV4RawPublicAssociationCaptureV2,
    V4TrainingKeyManifest,
    host_replay_probe_chain_v4,
    load_v4_training_manifest,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    PathBlockedPhysicalSkillReceiptV2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    M2C_Q012_V3_SKILL_LABELS,
    M2CPathBlockedProbeChainV3,
    M2CS4V3TrainingKeyManifestV1,
    load_v3_training_manifest,
    recompute_candidate_payload_v3,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    recompute_candidate_payload_v4,
)


ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_PATH = Path("scripts/m2c/package_s4_decision_level_supervision_adr0026.py")
YIELD_AUDIT_PATH = Path("reports/m2c-s4-training-eligibility-yield-adr0025.json")
YIELD_AUDIT_SHA256 = "d5d4a524f391b1bdd24706fb02f92f867862d229b764400453124725e55cc78f"
OFFLINE_19083_PATH = Path("reports/m2c-s4-v4-scene19083-offline-raw-capacity-replay.json")
OFFLINE_19083_SHA256 = "d467216f96d0e0cbb3ba307faa8dcc3d76fe602be70903f59e7e7321ebf09736"

V3_REPORT_ROOTS: dict[str, Path] = {
    "reports/m2c-s4-v3-path-blocked-train-collection.json": Path(
        "m2c-s4-v3-complete-U3F4Hj/evidence"
    ),
    "reports/m2c-s4-v3-path-blocked-train-collection-batch03.json": Path(
        "m2c-s4-v3-batch03-complete-uKktog"
    ),
}
V4_REPORTS = tuple(f"reports/m2c-s4-v4-batch{batch:02d}-collection.json" for batch in range(9, 24))
V4_EVIDENCE_ROOTS = {
    path: Path(f"m2c-s4-v4-batch{int(path.split('batch')[1][:2]):02d}-complete")
    for path in V4_REPORTS
}
V4_19083_EVIDENCE_ROOT = Path("m2c-s4-v4-batch08-complete")
V4_19083_MATCHED_KEY = (
    "m2c-s4-v4-train-dc5715316cad6e42faf074a9b6715f76e2df7bd0d267c3cf88037fdc5f8c50a7"
)
V4_19083_RAW_RELATIVE = Path("raw/train") / V4_19083_MATCHED_KEY / "probe/actuation-probe.json"
V4_19083_RAW_SHA256 = "9f3144467f247131240c5e152a8317e578e69c4c29192e0b64e4ddb78e5fef89"

TERMINAL_CLASSIFICATION = {
    "RAW_V3_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": (
        "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"
    ),
    "RAW_V3_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": ("TERMINAL_PREGRASP_IK_GATE_REJECTED"),
    "RAW_V3_REGRASP_LIFTED_PUBLIC_PREDICATE_REJECTED": (
        "LIFTED_BUT_PUBLIC_SUCCESS_PREDICATE_REJECTED"
    ),
    "RAW_V4_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED": (
        "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"
    ),
    "RAW_V4_FINAL_FALSE_REGRASP_PREGRASP_IK_GATE_REJECTED": ("TERMINAL_PREGRASP_IK_GATE_REJECTED"),
}


class DecisionPackagingError(ValueError):
    """Immutable evidence does not support the requested package."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise DecisionPackagingError(f"evidence is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after:
            raise DecisionPackagingError(f"evidence changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def read_bound_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = read_regular_file_once(path)
    if sha256_bytes(raw) != expected_sha256:
        raise DecisionPackagingError(f"bound JSON SHA-256 differs: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise DecisionPackagingError(f"bound JSON is not an object: {path}")
    return value


def _receipt_is_canonical(receipt: PathBlockedPhysicalSkillReceiptV2) -> bool:
    payload = receipt.model_dump(mode="json")
    reported = payload.pop("receipt_sha256")
    return reported == canonical_sha256(payload)


def _asset_path(probe_path: Path, uri: str) -> Path:
    if not uri.startswith("dataset://"):
        raise DecisionPackagingError("public observation asset is not dataset://")
    relative = Path(uri.removeprefix("dataset://"))
    if relative.is_absolute() or ".." in relative.parts:
        raise DecisionPackagingError("public observation asset escapes probe root")
    path = probe_path.parent / relative
    resolved_parent = probe_path.parent.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(resolved_parent):
        raise DecisionPackagingError("public observation asset resolves outside probe root")
    return resolved


def _verify_observation_assets(probe_path: Path, observation: Any) -> None:
    for uri, expected in (
        (observation.rgb_uri, observation.rgb_sha256),
        (observation.depth_uri, observation.depth_sha256),
    ):
        if sha256_bytes(read_regular_file_once(_asset_path(probe_path, uri))) != expected:
            raise DecisionPackagingError(f"public observation asset SHA-256 differs: {uri}")


def _target_for_step(step: Any, index: int) -> str | None:
    if index <= 4:
        return step.public_blocker_track_id
    if index >= 6:
        return step.public_task_target_track_id
    return None


def _candidate_track_ids(step: Any) -> list[str]:
    return [item.track_id for item in step.observation.candidate_payload.candidates]


def _destination_index(value: str | None) -> int | None:
    if value is None:
        return NONE_DESTINATION_CLASS
    try:
        return REGISTERED_DESTINATION_CELLS.index(value)
    except ValueError:
        return None


def _pointer_index(target: str | None, step: Any) -> int | None:
    if target is None:
        return NONE_POINTER_CLASS
    candidates = _candidate_track_ids(step)
    try:
        return candidates.index(target)
    except ValueError:
        return None


def _terminal_status(receipt: PathBlockedPhysicalSkillReceiptV2) -> str | None:
    value = receipt.execution_measurements.get("status")
    return value if isinstance(value, str) else None


def _gate_summaries(
    chain: M2CPathBlockedProbeChainV3 | M2CPathBlockedProbeChainV4,
    *,
    probe_path: Path,
    raw_chain: Mapping[str, Any],
) -> tuple[list[DecisionGateSummaryV1], list[str]]:
    if len(chain.steps) != 8:
        raise DecisionPackagingError("decision-level replay requires exactly eight steps")
    seen_observations: set[str] = set()
    seen_captures: set[str] = set()
    seen_receipts: set[str] = set()
    freshness_floor = chain.failure_observed_at_ns
    chosen_destination: str | None = None
    summaries: list[DecisionGateSummaryV1] = []
    prefix_reasons: list[str] = []
    raw_steps = raw_chain.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) != 8:
        raise DecisionPackagingError("raw decision evidence is not the exact eight-step chain")
    for index, step in enumerate(chain.steps):
        observation = step.observation
        _verify_observation_assets(probe_path, observation)
        canonical_index = step.decision_index == index
        observation_unique = observation.observation_id not in seen_observations
        capture_unique = observation.capture_receipt_sha256 not in seen_captures
        seen_observations.add(observation.observation_id)
        seen_captures.add(observation.capture_receipt_sha256)
        observation_fresh = observation.captured_at_ns > freshness_floor
        if isinstance(chain, M2CPathBlockedProbeChainV3):
            expected_payload, expected_payload_sha = recompute_candidate_payload_v3(observation)
        else:
            expected_payload, expected_payload_sha = recompute_candidate_payload_v4(observation)
        target = _target_for_step(step, index)
        pointer = _pointer_index(target, step)
        target_required = index <= 4 or index >= 6
        target_contract_passed = (target is not None) if target_required else (target is None)
        candidate_replay_passed = (
            observation.candidate_payload.model_dump(mode="json") == expected_payload
            and observation.candidate_payload_sha256 == expected_payload_sha
            and bool(observation.candidate_payload.candidates)
            and target_contract_passed
        )
        pointer_encodable = pointer is not None
        destination = _destination_index(step.destination_cell_label)
        if index in {2, 3}:
            destination_passed = destination is not None and step.destination_cell_label is not None
            if destination_passed and chosen_destination is None:
                chosen_destination = step.destination_cell_label
            elif destination_passed and chosen_destination != step.destination_cell_label:
                destination_passed = False
        else:
            destination_passed = step.destination_cell_label is None and destination is not None
        one_receipt = len(step.physical_receipts) == 1
        receipt = step.physical_receipts[0] if one_receipt else None
        raw_step = raw_steps[index]
        raw_receipts = raw_step.get("physical_receipts") if isinstance(raw_step, Mapping) else None
        raw_receipt = (
            raw_receipts[0] if isinstance(raw_receipts, list) and len(raw_receipts) == 1 else None
        )
        raw_receipt_core = dict(raw_receipt) if isinstance(raw_receipt, Mapping) else {}
        raw_reported_sha256 = raw_receipt_core.pop("receipt_sha256", None)
        canonical_receipt = bool(
            receipt is not None
            and receipt.receipt_sha256 not in seen_receipts
            and isinstance(raw_receipt, Mapping)
            and raw_reported_sha256 == canonical_sha256(raw_receipt_core)
            and PathBlockedPhysicalSkillReceiptV2.model_validate(raw_receipt) == receipt
        )
        if receipt is not None:
            seen_receipts.add(receipt.receipt_sha256)
        expected_skill = bool(
            receipt is not None and receipt.executed_skill == EXPECTED_PATH_BLOCKED_CHAIN[index]
        )
        timing = bool(
            receipt is not None
            and receipt.physically_executed
            and receipt.started_at_ns > observation.captured_at_ns
            and receipt.completed_at_ns > receipt.started_at_ns
        )
        terminal_status = _terminal_status(receipt) if index == 7 and receipt else None
        gate_values = {
            name: bool(receipt is not None and getattr(receipt, name) == "PASS")
            for name in (
                "schema_gate",
                "stale_track_gate",
                "frame_unit_gate",
                "ik_gate",
                "collision_gate",
                "controller_gate",
                "safety_gate",
            )
        }
        no_violation = bool(receipt is not None and not receipt.collision_or_safety_violation)
        no_teacher = bool(
            receipt is not None
            and not receipt.teacher_used
            and not step.teacher_used
            and not observation.teacher_used
        )
        no_truth = bool(
            receipt is not None
            and not receipt.privileged_truth_policy_input
            and not step.privileged_truth_policy_input
            and not observation.privileged_truth_policy_input
        )
        all_gates = all(
            (
                canonical_index,
                observation_unique,
                capture_unique,
                observation_fresh,
                candidate_replay_passed,
                destination_passed,
                one_receipt,
                canonical_receipt,
                expected_skill,
                timing,
                *gate_values.values(),
                no_violation,
                no_teacher,
                no_truth,
            )
        )
        terminal_success = index == 7 and all_gates and terminal_status == "LIFTED"
        summary = DecisionGateSummaryV1(
            decision_index=index,
            canonical_decision_index=canonical_index,
            public_observation_fresh_and_unique=observation_unique and observation_fresh,
            public_capture_unique=capture_unique,
            public_candidate_replay_passed=candidate_replay_passed,
            selected_target_encodable_in_k8=pointer_encodable,
            destination_contract_passed=destination_passed,
            exactly_one_canonical_physical_receipt=one_receipt and canonical_receipt,
            expected_skill_executed=expected_skill,
            physical_timing_passed=timing,
            schema_gate_passed=gate_values["schema_gate"],
            stale_track_gate_passed=gate_values["stale_track_gate"],
            frame_unit_gate_passed=gate_values["frame_unit_gate"],
            ik_gate_passed=gate_values["ik_gate"],
            collision_gate_passed=gate_values["collision_gate"],
            controller_gate_passed=gate_values["controller_gate"],
            safety_gate_passed=gate_values["safety_gate"],
            collision_or_safety_violation=False,
            teacher_used=False,
            privileged_truth_policy_input=False,
            terminal_execution_status=terminal_status,
            terminal_step_physically_succeeded=terminal_success,
            all_adr0026_admission_gates_passed=all_gates,
        )
        summaries.append(summary)
        if index <= 6 and not all_gates:
            prefix_reasons.append(f"STEP_{index}:ADR0026_ADMISSION_GATE_NOT_PASSING")
        if receipt is not None:
            freshness_floor = max(freshness_floor, receipt.completed_at_ns)
    return summaries, prefix_reasons


def _build_sample_v3(
    chain: M2CPathBlockedProbeChainV3,
    index: int,
    *,
    source_sha256: str,
) -> M2CS4DecisionLevelTrainingSampleV1:
    step = chain.steps[index]
    skill = EXPECTED_PATH_BLOCKED_CHAIN[index]
    target = _target_for_step(step, index)
    pointer = _pointer_index(target, step)
    destination = _destination_index(step.destination_cell_label)
    if destination is None:
        raise DecisionPackagingError("admitted V3 destination label is not encodable")
    payload = {
        "schema_version": "M2CS4DecisionLevelTrainingSampleV1",
        "evidence_revision": "V3",
        "sample_id": f"{chain.episode_id}:path-blocked-v3:{index}:adr0026",
        "episode_id": chain.episode_id,
        "decision_index": index,
        "split": "train",
        "split_group": chain.split_group,
        "matched_key": chain.matched_key,
        "observation": step.observation.model_dump(mode="json"),
        "model_label": CoarseIntentV2(
            skill_type=skill,
            target_track_id=target,
            grasp_family="top_down" if skill in {"GRASP", "REGRASP"} else "unknown",
            recovery_mode="path_blocked",
            reobserve_flag=skill == "REOBSERVE",
            destination_cell=step.destination_cell_label,
            failure_type_aux=FailureType.PATH_BLOCKED,
        ).model_dump(mode="json"),
        "skill_label_index": M2C_Q012_V3_SKILL_LABELS.index(skill),
        "pointer_class_index": pointer,
        "destination_class_index": destination,
        "source_evidence_sha256": source_sha256,
        "physical_receipt_sha256": step.physical_receipts[0].receipt_sha256,
        "label_source": "EXECUTED_PUBLIC_PHYSICAL_CHAIN_ADR0026",
        "skill_provenance": "MODEL",
        "target_provenance": "NONE" if index == 5 else "MODEL",
        "destination_provenance": "MODEL" if index in {2, 3} else "NONE",
        "skill_head_supervision_eligible": True,
        "pointer_head_supervision_eligible": pointer is not None,
        "destination_head_supervision_eligible": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "decision_level_training_eligible": True,
    }
    payload["sample_sha256"] = canonical_sha256(payload)
    return M2CS4DecisionLevelTrainingSampleV1.model_validate(payload)


def _build_sample_v4(
    chain: M2CPathBlockedProbeChainV4,
    index: int,
    *,
    source_sha256: str,
) -> M2CS4DecisionLevelTrainingSampleV1:
    step = chain.steps[index]
    skill = EXPECTED_PATH_BLOCKED_CHAIN[index]
    target = _target_for_step(step, index)
    pointer = _pointer_index(target, step)
    destination = _destination_index(step.destination_cell_label)
    if destination is None:
        raise DecisionPackagingError("admitted V4 destination label is not encodable")
    payload = {
        "schema_version": "M2CS4DecisionLevelTrainingSampleV1",
        "evidence_revision": "V4",
        "sample_id": f"{chain.episode_id}:path-blocked-v4:{index}:adr0026",
        "episode_id": chain.episode_id,
        "decision_index": index,
        "split": "train",
        "split_group": chain.split_group,
        "matched_key": chain.matched_key,
        "observation": step.observation.model_dump(mode="json"),
        "model_label": CoarseIntentV2(
            skill_type=skill,
            target_track_id=target,
            grasp_family="top_down" if skill in {"GRASP", "REGRASP"} else "unknown",
            recovery_mode="path_blocked",
            reobserve_flag=skill == "REOBSERVE",
            destination_cell=step.destination_cell_label,
            failure_type_aux=FailureType.PATH_BLOCKED,
        ).model_dump(mode="json"),
        "skill_label_index": M2C_Q012_V4_SKILL_LABELS.index(skill),
        "pointer_class_index": pointer,
        "destination_class_index": destination,
        "source_evidence_sha256": source_sha256,
        "physical_receipt_sha256": step.physical_receipts[0].receipt_sha256,
        "label_source": "EXECUTED_PUBLIC_PHYSICAL_CHAIN_ADR0026",
        "skill_provenance": "MODEL",
        "target_provenance": "NONE" if index == 5 else "MODEL",
        "destination_provenance": "MODEL" if index in {2, 3} else "NONE",
        "skill_head_supervision_eligible": True,
        "pointer_head_supervision_eligible": pointer is not None,
        "destination_head_supervision_eligible": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "decision_level_training_eligible": True,
    }
    payload["sample_sha256"] = canonical_sha256(payload)
    return M2CS4DecisionLevelTrainingSampleV1.model_validate(payload)


def _row(
    *,
    revision: str,
    sample: M2CS4DecisionLevelTrainingSampleV1,
    eligibility_sha256: str,
    terminal_outcome: str,
    terminal_succeeded: bool,
    source_report_path: str,
    source_report_sha256: str,
    raw_evidence_uri: str,
    raw_evidence_sha256: str,
) -> M2CS4DecisionLevelSupervisionRowV1:
    payload = {
        "schema_version": "M2CS4DecisionLevelSupervisionRowV1",
        "row_id": sample.sample_id,
        "evidence_revision": revision,
        "episode_id": sample.episode_id,
        "matched_key": sample.matched_key,
        "decision_index": sample.decision_index,
        "episode_terminal_outcome": terminal_outcome,
        "episode_final_task_success": False,
        "terminal_step_physically_succeeded": terminal_succeeded,
        "terminal_step_row": sample.decision_index == 7,
        "source_report": {"path": source_report_path, "sha256": source_report_sha256},
        "source_raw_evidence": {
            "path": raw_evidence_uri,
            "sha256": raw_evidence_sha256,
        },
        "eligibility_sha256": eligibility_sha256,
        "training_sample": sample.model_dump(mode="json"),
        "episode_level_training_eligible": False,
        "decision_level_training_eligible": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["row_sha256"] = canonical_sha256(payload)
    return M2CS4DecisionLevelSupervisionRowV1.model_validate(payload)


def _attempt_raw_sha_v3(attempt: Mapping[str, Any]) -> str:
    mapping = attempt.get("evidence_file_sha256")
    if not isinstance(mapping, Mapping):
        raise DecisionPackagingError("V3 attempt lacks an evidence hash map")
    candidates = [
        str(value)
        for key, value in mapping.items()
        if str(key).endswith("probe/actuation-probe.json")
    ]
    if len(candidates) != 1:
        raise DecisionPackagingError("V3 attempt does not bind one raw probe")
    return candidates[0]


def _verify_identity(chain: Any, attempt: Mapping[str, Any]) -> None:
    identity = attempt.get("identity")
    if not isinstance(identity, Mapping):
        raise DecisionPackagingError("source attempt lacks identity")
    observed = (
        chain.scene_seed,
        chain.failure_seed,
        chain.matched_key,
        chain.sdf_sha256,
        chain.supervision_sha256,
    )
    expected = (
        identity.get("scene_seed"),
        identity.get("failure_seed"),
        identity.get("matched_key"),
        identity.get("sdf_sha256"),
        identity.get("supervision_sha256"),
    )
    if observed != expected:
        raise DecisionPackagingError("source report identity differs from raw chain")


def _load_raw_probe(path: Path, *, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    raw = read_regular_file_once(path)
    if sha256_bytes(raw) != expected_sha256:
        raise DecisionPackagingError(f"raw probe SHA-256 differs: {path}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise DecisionPackagingError("raw probe is not an object")
    if payload.get("status") != "PASS" or payload.get("not_policy_rollout") is not True:
        raise DecisionPackagingError("raw probe is not a passing scripted collection")
    return payload, raw


def _manifest_key(
    manifests: Sequence[V4TrainingKeyManifest], matched_key: str
) -> tuple[Any, V4TrainingKeyManifest]:
    found = [
        (item, manifest)
        for manifest in manifests
        for item in manifest.training_keys
        if item.matched_key == matched_key
    ]
    if len(found) != 1:
        raise DecisionPackagingError("V4 key is not present exactly once across frozen manifests")
    return found[0]


def _upgrade_scene19083(
    raw_chain: Mapping[str, Any], raw_captures: list[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(raw_captures) != 8:
        raise DecisionPackagingError("scene 19083 raw capture count differs")
    chain = copy.deepcopy(dict(raw_chain))
    steps = chain.get("steps")
    if not isinstance(steps, list) or len(steps) != 8:
        raise DecisionPackagingError("scene 19083 raw step count differs")
    upgraded: list[dict[str, Any]] = []
    counts: list[int] = []
    for raw_capture, step in zip(raw_captures, steps, strict=True):
        original = dict(raw_capture)
        observation = step.get("observation") if isinstance(step, Mapping) else None
        if not isinstance(observation, dict) or observation.get(
            "capture_receipt_sha256"
        ) != canonical_sha256(original):
            raise DecisionPackagingError("scene 19083 step does not bind original capture")
        M2CV4RawPublicAssociationCaptureV1.model_validate({**original, "detections": []})
        current = M2CV4RawPublicAssociationCaptureV2.model_validate(
            {
                **original,
                "schema_version": "M2CV4RawPublicAssociationCaptureV2",
                "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
                "max_raw_public_detections": 32,
            }
        ).model_dump(mode="json")
        observation["capture_receipt_sha256"] = canonical_sha256(current)
        upgraded.append(current)
        counts.append(len(current["detections"]))
    if counts != [7, 13, 11, 7, 8, 9, 10, 10]:
        raise DecisionPackagingError("scene 19083 raw detection counts differ")
    return chain, upgraded


def _replay_v3_sources(
    *,
    project_root: Path,
    evidence_base: Path,
    yield_audit: Mapping[str, Any],
    manifest: M2CS4V3TrainingKeyManifestV1,
) -> tuple[list[M2CS4DecisionLevelSupervisionRowV1], list[dict[str, Any]]]:
    source_specs = {item["path"]: item for item in yield_audit["source_reports"]}
    rows: list[M2CS4DecisionLevelSupervisionRowV1] = []
    episodes: list[dict[str, Any]] = []
    manifest_keys = {item.matched_key: item for item in manifest.training_keys}
    for source_path, relative_root in V3_REPORT_ROOTS.items():
        spec = source_specs[source_path]
        report = read_bound_json(project_root / source_path, str(spec["sha256"]))
        for attempt in report["attempts"]:
            classification = str(attempt.get("classification"))
            if classification not in TERMINAL_CLASSIFICATION:
                continue
            relative = Path(str(attempt["evidence_relative_root"])) / "probe/actuation-probe.json"
            probe_path = evidence_base / relative_root / relative
            raw_sha256 = _attempt_raw_sha_v3(attempt)
            raw_probe, _ = _load_raw_probe(probe_path, expected_sha256=raw_sha256)
            try:
                chain = M2CPathBlockedProbeChainV3.model_validate(
                    raw_probe["m2c_path_blocked_physical_chain"]
                )
            except (KeyError, ValidationError) as error:
                raise DecisionPackagingError("V3 raw chain schema validation failed") from error
            _verify_identity(chain, attempt)
            key = manifest_keys.get(chain.matched_key)
            if key is None or (
                chain.scene_seed,
                chain.failure_seed,
                chain.sdf_sha256,
                chain.supervision_sha256,
            ) != (key.scene_seed, key.failure_seed, key.sdf_sha256, key.supervision_sha256):
                raise DecisionPackagingError("V3 raw chain differs from frozen TRAIN key")
            if (
                chain.final_task_success
                or chain.teacher_used
                or chain.privileged_truth_policy_input
            ):
                raise DecisionPackagingError("V3 raw chain outcome/public-only boundary differs")
            gates, reasons = _gate_summaries(
                chain,
                probe_path=probe_path,
                raw_chain=raw_probe["m2c_path_blocked_physical_chain"],
            )
            terminal_outcome = TERMINAL_CLASSIFICATION[classification]
            eligibility = decide_adr0026_episode_eligibility(
                episode_id=chain.episode_id,
                matched_key=chain.matched_key,
                evidence_revision="V3",
                episode_terminal_outcome=terminal_outcome,
                episode_final_task_success=chain.final_task_success,
                decision_gates=gates,
                exclusion_reasons=reasons,
            )
            for index in eligibility.admitted_decision_indices:
                sample = _build_sample_v3(chain, index, source_sha256=raw_sha256)
                rows.append(
                    _row(
                        revision="V3",
                        sample=sample,
                        eligibility_sha256=eligibility.eligibility_sha256,
                        terminal_outcome=terminal_outcome,
                        terminal_succeeded=eligibility.terminal_step_physically_succeeded,
                        source_report_path=source_path,
                        source_report_sha256=str(spec["sha256"]),
                        raw_evidence_uri=f"evidence://{relative_root.as_posix()}/{relative.as_posix()}",
                        raw_evidence_sha256=raw_sha256,
                    )
                )
            episodes.append(
                {
                    "revision": "V3",
                    "episode_id": chain.episode_id,
                    "matched_key": chain.matched_key,
                    "scene_seed": chain.scene_seed,
                    "terminal_outcome": terminal_outcome,
                    "final_task_success": chain.final_task_success,
                    "terminal_step_physically_succeeded": (
                        eligibility.terminal_step_physically_succeeded
                    ),
                    "admitted_decision_indices": eligibility.admitted_decision_indices,
                    "pointer_head_masked_decision_indices": (
                        eligibility.pointer_head_masked_decision_indices
                    ),
                    "eligibility_sha256": eligibility.eligibility_sha256,
                    "exclusion_reasons": eligibility.exclusion_reasons,
                    "source_raw_evidence_sha256": raw_sha256,
                }
            )
    return rows, episodes


def _replay_v4_attempt(
    *,
    attempt: Mapping[str, Any],
    report_path: str,
    report_sha256: str,
    evidence_root: Path,
    manifests: Sequence[V4TrainingKeyManifest],
) -> tuple[list[M2CS4DecisionLevelSupervisionRowV1], dict[str, Any]]:
    classification = str(attempt["classification"])
    terminal_outcome = TERMINAL_CLASSIFICATION[classification]
    identity = attempt["identity"]
    matched_key = str(identity["matched_key"])
    relative = Path("raw/train") / matched_key / "probe/actuation-probe.json"
    probe_path = evidence_root / relative
    raw_sha256 = str(attempt["raw_probe_sha256"])
    raw_probe, _ = _load_raw_probe(probe_path, expected_sha256=raw_sha256)
    raw_chain = raw_probe.get("m2c_path_blocked_physical_chain")
    raw_captures = raw_probe.get("m2c_v4_raw_association_captures")
    authorization = raw_probe.get("m2c_v4_collection_authorization")
    if not isinstance(raw_chain, Mapping) or not isinstance(raw_captures, list):
        raise DecisionPackagingError("V4 raw chain or capture history is absent")
    if not isinstance(authorization, Mapping):
        raise DecisionPackagingError("V4 raw collection authorization is absent")
    key, manifest = _manifest_key(manifests, matched_key)
    capture_source = str(authorization.get("derived_probe_sha256"))
    replayed = host_replay_probe_chain_v4(
        raw_chain,
        raw_captures,
        training_key=key,
        training_manifest=manifest,
        capture_source_implementation_sha256=capture_source,
    )
    _verify_identity(replayed, attempt)
    if (
        replayed.final_task_success
        or replayed.teacher_used
        or replayed.privileged_truth_policy_input
    ):
        raise DecisionPackagingError("V4 raw chain outcome/public-only boundary differs")
    gates, reasons = _gate_summaries(replayed, probe_path=probe_path, raw_chain=raw_chain)
    eligibility = decide_adr0026_episode_eligibility(
        episode_id=replayed.episode_id,
        matched_key=replayed.matched_key,
        evidence_revision="V4",
        episode_terminal_outcome=terminal_outcome,
        episode_final_task_success=replayed.final_task_success,
        decision_gates=gates,
        exclusion_reasons=reasons,
    )
    rows = [
        _row(
            revision="V4",
            sample=_build_sample_v4(replayed, index, source_sha256=raw_sha256),
            eligibility_sha256=eligibility.eligibility_sha256,
            terminal_outcome=terminal_outcome,
            terminal_succeeded=eligibility.terminal_step_physically_succeeded,
            source_report_path=report_path,
            source_report_sha256=report_sha256,
            raw_evidence_uri=f"evidence://{evidence_root.name}/{relative.as_posix()}",
            raw_evidence_sha256=raw_sha256,
        )
        for index in eligibility.admitted_decision_indices
    ]
    episode = {
        "revision": "V4",
        "episode_id": replayed.episode_id,
        "matched_key": replayed.matched_key,
        "scene_seed": replayed.scene_seed,
        "terminal_outcome": terminal_outcome,
        "final_task_success": replayed.final_task_success,
        "terminal_step_physically_succeeded": eligibility.terminal_step_physically_succeeded,
        "admitted_decision_indices": eligibility.admitted_decision_indices,
        "pointer_head_masked_decision_indices": (eligibility.pointer_head_masked_decision_indices),
        "eligibility_sha256": eligibility.eligibility_sha256,
        "exclusion_reasons": eligibility.exclusion_reasons,
        "source_raw_evidence_sha256": raw_sha256,
    }
    return rows, episode


def _replay_v4_sources(
    *,
    project_root: Path,
    evidence_base: Path,
    yield_audit: Mapping[str, Any],
    manifests: Sequence[V4TrainingKeyManifest],
) -> tuple[list[M2CS4DecisionLevelSupervisionRowV1], list[dict[str, Any]]]:
    source_specs = {item["path"]: item for item in yield_audit["source_reports"]}
    rows: list[M2CS4DecisionLevelSupervisionRowV1] = []
    episodes: list[dict[str, Any]] = []
    for source_path in V4_REPORTS:
        spec = source_specs[source_path]
        report = read_bound_json(project_root / source_path, str(spec["sha256"]))
        verified = 0
        for attempt in report["attempts"]:
            classification = str(attempt.get("classification"))
            if classification not in TERMINAL_CLASSIFICATION:
                continue
            attempt_rows, episode = _replay_v4_attempt(
                attempt=attempt,
                report_path=source_path,
                report_sha256=str(spec["sha256"]),
                evidence_root=evidence_base / V4_EVIDENCE_ROOTS[source_path],
                manifests=manifests,
            )
            rows.extend(attempt_rows)
            episodes.append(episode)
            verified += 1
        if verified != int(spec["complete_eight_step_chains"]):
            raise DecisionPackagingError("V4 source report complete-chain count differs")
    return rows, episodes


def _replay_scene19083(
    *,
    project_root: Path,
    evidence_base: Path,
    manifests: Sequence[V4TrainingKeyManifest],
) -> tuple[list[M2CS4DecisionLevelSupervisionRowV1], dict[str, Any]]:
    report = read_bound_json(project_root / OFFLINE_19083_PATH, OFFLINE_19083_SHA256)
    source = report.get("source_evidence")
    if not isinstance(source, Mapping) or source.get("raw_probe_sha256") != V4_19083_RAW_SHA256:
        raise DecisionPackagingError("scene 19083 replay source binding differs")
    probe_path = evidence_base / V4_19083_EVIDENCE_ROOT / V4_19083_RAW_RELATIVE
    raw_probe, _ = _load_raw_probe(probe_path, expected_sha256=V4_19083_RAW_SHA256)
    raw_chain = raw_probe.get("m2c_path_blocked_physical_chain")
    raw_captures = raw_probe.get("m2c_v4_raw_association_captures")
    authorization = raw_probe.get("m2c_v4_collection_authorization")
    if (
        not isinstance(raw_chain, Mapping)
        or not isinstance(raw_captures, list)
        or not isinstance(authorization, Mapping)
    ):
        raise DecisionPackagingError("scene 19083 raw evidence structure differs")
    upgraded_chain, upgraded_captures = _upgrade_scene19083(raw_chain, raw_captures)
    key, manifest = _manifest_key(manifests, V4_19083_MATCHED_KEY)
    replayed = host_replay_probe_chain_v4(
        upgraded_chain,
        upgraded_captures,
        training_key=key,
        training_manifest=manifest,
        capture_source_implementation_sha256=str(authorization.get("derived_probe_sha256")),
    )
    fake_attempt = {
        "identity": {
            "scene_seed": source["scene_seed"],
            "failure_seed": 190837,
            "matched_key": source["matched_key"],
            "sdf_sha256": key.sdf_sha256,
            "supervision_sha256": key.supervision_sha256,
        }
    }
    _verify_identity(replayed, fake_attempt)
    gates, reasons = _gate_summaries(
        replayed,
        probe_path=probe_path,
        raw_chain=upgraded_chain,
    )
    terminal_outcome = "TERMINAL_CONTACT_OR_CONTROLLER_GATE_REJECTED"
    eligibility = decide_adr0026_episode_eligibility(
        episode_id=replayed.episode_id,
        matched_key=replayed.matched_key,
        evidence_revision="V4",
        episode_terminal_outcome=terminal_outcome,
        episode_final_task_success=replayed.final_task_success,
        decision_gates=gates,
        exclusion_reasons=reasons,
    )
    if (
        eligibility.admitted_decision_indices != list(range(7))
        or eligibility.pointer_head_masked_decision_indices != [1]
        or eligibility.exclusion_reasons
    ):
        raise DecisionPackagingError("scene 19083 ADR-0026 head masks differ")
    rows = [
        _row(
            revision="V4",
            sample=_build_sample_v4(replayed, index, source_sha256=V4_19083_RAW_SHA256),
            eligibility_sha256=eligibility.eligibility_sha256,
            terminal_outcome=terminal_outcome,
            terminal_succeeded=eligibility.terminal_step_physically_succeeded,
            source_report_path=OFFLINE_19083_PATH.as_posix(),
            source_report_sha256=OFFLINE_19083_SHA256,
            raw_evidence_uri=(
                f"evidence://{V4_19083_EVIDENCE_ROOT.as_posix()}/{V4_19083_RAW_RELATIVE.as_posix()}"
            ),
            raw_evidence_sha256=V4_19083_RAW_SHA256,
        )
        for index in eligibility.admitted_decision_indices
    ]
    episode = {
        "revision": "V4",
        "episode_id": replayed.episode_id,
        "matched_key": replayed.matched_key,
        "scene_seed": replayed.scene_seed,
        "terminal_outcome": terminal_outcome,
        "final_task_success": replayed.final_task_success,
        "terminal_step_physically_succeeded": eligibility.terminal_step_physically_succeeded,
        "admitted_decision_indices": eligibility.admitted_decision_indices,
        "pointer_head_masked_decision_indices": (eligibility.pointer_head_masked_decision_indices),
        "eligibility_sha256": eligibility.eligibility_sha256,
        "exclusion_reasons": eligibility.exclusion_reasons,
        "source_raw_evidence_sha256": V4_19083_RAW_SHA256,
    }
    return rows, episode


def _jsonl_bytes(rows: Sequence[M2CS4DecisionLevelSupervisionRowV1]) -> bytes:
    return b"".join(canonical_json_bytes(item.model_dump(mode="json")) + b"\n" for item in rows)


def _publish_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o444,
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise DecisionPackagingError(f"short write publishing {path}")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _manifest(
    *,
    project_root: Path,
    artifact_root: Path,
    v3_rows: list[M2CS4DecisionLevelSupervisionRowV1],
    v4_rows: list[M2CS4DecisionLevelSupervisionRowV1],
    episodes: list[dict[str, Any]],
    v3_bytes: bytes,
    v4_bytes: bytes,
) -> M2CS4DecisionLevelDatasetManifestV1:
    qualifying = [item for item in episodes if item["admitted_decision_indices"]]
    excluded = [item for item in episodes if not item["admitted_decision_indices"]]
    pointer_masked = [
        {
            "episode_id": item["episode_id"],
            "matched_key": item["matched_key"],
            "scene_seed": item["scene_seed"],
            "decision_index": index,
            "reason": "PUBLIC_TARGET_OUTSIDE_REPLAYED_K8_POINTER_HEAD_MASKED",
        }
        for item in episodes
        for index in item["pointer_head_masked_decision_indices"]
    ]
    index_counts = Counter(str(item.decision_index) for item in [*v3_rows, *v4_rows])
    episode_outcomes = Counter(str(item["terminal_outcome"]) for item in episodes)
    row_outcomes = Counter(item.episode_terminal_outcome for item in [*v3_rows, *v4_rows])
    relative_root = artifact_root.relative_to(project_root)
    payload = {
        "schema_version": "M2CS4DecisionLevelDatasetManifestV1",
        "status": "PASS_ADR0026_DECISION_LEVEL_DATASET",
        "accepted_adr": {"path": ADR0026_PATH, "sha256": ADR0026_SHA256},
        "source_yield_audit": {
            "path": YIELD_AUDIT_PATH.as_posix(),
            "sha256": YIELD_AUDIT_SHA256,
        },
        "shards": [
            {
                "revision": "V3",
                "path": (relative_root / "decision-level-v3.jsonl").as_posix(),
                "sha256": sha256_bytes(v3_bytes),
                "byte_count": len(v3_bytes),
                "row_count": len(v3_rows),
            },
            {
                "revision": "V4",
                "path": (relative_root / "decision-level-v4.jsonl").as_posix(),
                "sha256": sha256_bytes(v4_bytes),
                "byte_count": len(v4_bytes),
                "row_count": len(v4_rows),
            },
        ],
        "replayed_complete_chains": len(episodes),
        "qualifying_prefix_episodes": len(qualifying),
        "excluded_prefix_episodes": len(excluded),
        "final_successful_episodes": sum(bool(item["final_task_success"]) for item in episodes),
        "final_failed_episodes": sum(not bool(item["final_task_success"]) for item in episodes),
        "terminal_physically_successful_episodes": sum(
            bool(item["terminal_step_physically_succeeded"]) for item in episodes
        ),
        "terminal_physically_failed_episodes": sum(
            not bool(item["terminal_step_physically_succeeded"]) for item in episodes
        ),
        "decision_rows_total": len(v3_rows) + len(v4_rows),
        "decision_rows_v3": len(v3_rows),
        "decision_rows_v4": len(v4_rows),
        "skill_head_supervised_rows": len(v3_rows) + len(v4_rows),
        "pointer_head_supervised_rows": sum(
            item.training_sample.pointer_head_supervision_eligible for item in [*v3_rows, *v4_rows]
        ),
        "pointer_head_masked_rows": sum(
            not item.training_sample.pointer_head_supervision_eligible
            for item in [*v3_rows, *v4_rows]
        ),
        "destination_head_supervised_rows": len(v3_rows) + len(v4_rows),
        "decision_index_counts": dict(sorted(index_counts.items())),
        "terminal_outcome_episode_counts": dict(sorted(episode_outcomes.items())),
        "terminal_outcome_row_counts": dict(sorted(row_outcomes.items())),
        "pointer_masked_decisions": pointer_masked,
        "training_executed": False,
        "model_rollout_executed": False,
        "formal_q_b_evaluation_executed": False,
        "q_b_success_definition_changed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "bundle_smoke_checkpoint_asia_shanghai": "2026-08-20",
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return M2CS4DecisionLevelDatasetManifestV1.model_validate(payload)


def _report(
    *,
    project_root: Path,
    artifact_root: Path,
    manifest: M2CS4DecisionLevelDatasetManifestV1,
    manifest_bytes: bytes,
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    source_inventory = sorted(
        {
            (row.source_report.path, row.source_report.sha256)
            for row in _load_rows_from_manifest(project_root, manifest)
        }
    )
    return {
        "schema_version": "M2CS4ADR0026DecisionLevelPackagingReportV1",
        "status": "PASS_PACKAGED_DECISION_LEVEL_SUPERVISION",
        "accepted_adr": {"path": ADR0026_PATH, "sha256": ADR0026_SHA256, "section": "4"},
        "implementation": {
            "path": IMPLEMENTATION_PATH.as_posix(),
            "sha256": sha256_bytes(read_regular_file_once(project_root / IMPLEMENTATION_PATH)),
        },
        "source_yield_audit": {
            "path": YIELD_AUDIT_PATH.as_posix(),
            "sha256": YIELD_AUDIT_SHA256,
        },
        "source_reports": [{"path": path, "sha256": digest} for path, digest in source_inventory],
        "dataset_manifest": {
            "path": (artifact_root.relative_to(project_root) / "dataset-manifest.json").as_posix(),
            "sha256": sha256_bytes(manifest_bytes),
            "manifest_sha256": manifest.manifest_sha256,
        },
        "replay": {
            "complete_chains_replayed": manifest.replayed_complete_chains,
            "prefix_episodes_admitted": manifest.qualifying_prefix_episodes,
            "prefix_episodes_excluded": manifest.excluded_prefix_episodes,
            "decision_rows_packaged": manifest.decision_rows_total,
            "decision_rows_v3": manifest.decision_rows_v3,
            "decision_rows_v4": manifest.decision_rows_v4,
            "decision_index_counts": manifest.decision_index_counts,
            "episode_terminal_outcomes": manifest.terminal_outcome_episode_counts,
            "row_terminal_outcomes": manifest.terminal_outcome_row_counts,
            "head_supervision": {
                "skill_rows": manifest.skill_head_supervised_rows,
                "pointer_rows": manifest.pointer_head_supervised_rows,
                "pointer_masked_rows": manifest.pointer_head_masked_rows,
                "destination_rows": manifest.destination_head_supervised_rows,
            },
            "pointer_masked_decisions": manifest.pointer_masked_decisions,
        },
        "episode_mix": {
            "successful": manifest.final_successful_episodes,
            "failed": manifest.final_failed_episodes,
            "terminal_physically_successful": manifest.terminal_physically_successful_episodes,
            "terminal_physically_failed": manifest.terminal_physically_failed_episodes,
        },
        "eligibility_amendment": {
            "historical_episode_atomic_predicate_changed_in_place": False,
            "new_versioned_decision_level_predicate": True,
            "steps_0_through_6_require_every_gate_pass": True,
            "terminal_step_requires_physical_success": True,
            "episode_terminal_outcome_label_present_on_every_row": True,
            "q_b_success_definition_changed": False,
        },
        "revision_separation": {
            "mixed_schema_rows_in_one_shard": False,
            "v3_rows": manifest.decision_rows_v3,
            "v4_rows": manifest.decision_rows_v4,
            "silent_v3_to_v4_upgrade_performed": False,
        },
        "episode_inventory_sha256": canonical_sha256(episodes),
        "evidence_claims": {
            "collection_performed": False,
            "physical_execution_performed": False,
            "training_performed": False,
            "model_rollout_performed": False,
            "formal_q_b_evaluation_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "existing_episode_outcomes_reinterpreted": False,
        },
        "checkpoint": {
            "bundle_smoke_asia_shanghai": "2026-08-20",
            "unchanged": True,
        },
        "blockers": [
            "CURRENT_QWEN_LOADERS_REQUIRE_EPISODE_ATOMIC_REVISION_SPECIFIC_INPUT",
            "DIAGNOSTIC_ABLATION_INCOMPLETE_PRE_ACTION_SCHEMA_GATE_NO_RETRY_ALLOWED",
            "FORMAL_Q_B_REMAINS_UNMEASURED",
        ],
        "one_next_command": (
            "PYTHONPATH=src:scripts uv run python "
            "scripts/m2c/package_s4_decision_level_supervision_adr0026.py "
            "--evidence-base /Users/gl/tzb-m2c-evidence "
            "--expected-manifest artifacts/m2c/s4-decision-level-supervision-adr0026-v1/"
            "dataset-manifest.json"
        ),
    }


def _load_rows_from_manifest(
    project_root: Path, manifest: M2CS4DecisionLevelDatasetManifestV1
) -> list[M2CS4DecisionLevelSupervisionRowV1]:
    rows: list[M2CS4DecisionLevelSupervisionRowV1] = []
    for shard in manifest.shards:
        raw = read_regular_file_once(project_root / shard.path)
        if sha256_bytes(raw) != shard.sha256 or len(raw) != shard.byte_count:
            raise DecisionPackagingError("published decision shard differs from manifest")
        lines = raw.splitlines()
        if len(lines) != shard.row_count:
            raise DecisionPackagingError("published decision shard row count differs")
        parsed = [M2CS4DecisionLevelSupervisionRowV1.model_validate_json(line) for line in lines]
        if any(item.evidence_revision != shard.revision for item in parsed):
            raise DecisionPackagingError("decision shard contains another revision")
        rows.extend(parsed)
    if len({item.row_id for item in rows}) != len(rows):
        raise DecisionPackagingError("decision dataset repeats a row identity")
    return rows


def _card(report: Mapping[str, Any]) -> bytes:
    replay = report["replay"]
    mix = report["episode_mix"]
    lines = [
        "# M2C S4 ADR-0026 decision-level supervision dataset card",
        "",
        f"Status: `{report['status']}`",
        "",
        "## Scope and intended use",
        "",
        "This is offline, model-training supervision for the world-model/coarse decision heads.",
        "It is not a safety/controller substitute and does not alter formal Q-B success.",
        "V3 and V4 are separate shards; no historical observation is silently upgraded.",
        "",
        "## Replay and rows",
        "",
        f"- Complete chains replayed: **{replay['complete_chains_replayed']}**",
        f"- Prefix-eligible episodes: **{replay['prefix_episodes_admitted']}**",
        f"- Excluded prefix episodes: **{replay['prefix_episodes_excluded']}**",
        f"- Decision rows: **{replay['decision_rows_packaged']}** "
        f"(V3 {replay['decision_rows_v3']}; V4 {replay['decision_rows_v4']})",
        f"- Decision-index histogram: `{replay['decision_index_counts']}`",
        f"- Skill-head rows: **{replay['head_supervision']['skill_rows']}**",
        f"- Pointer-head rows: **{replay['head_supervision']['pointer_rows']}**; "
        f"masked: **{replay['head_supervision']['pointer_masked_rows']}**",
        f"- Destination-head rows: **{replay['head_supervision']['destination_rows']}**",
        "",
        "## Required episode outcome mix",
        "",
        f"- Final task success: **{mix['successful']} success / {mix['failed']} failed**",
        "- Every row carries its source episode's terminal outcome.",
        f"- Terminal physical execution: **{mix['terminal_physically_successful']} succeeded / "
        f"{mix['terminal_physically_failed']} failed**",
        "- Decision 7 appears only for the one physically successful `LIFTED` terminal step.",
        "",
        "## K8 masking retained without label fabrication",
        "",
        "- Fourteen decisions have a public selected target outside the replayed K8.",
        "- Their skill and destination supervision remains valid under ADR-0026, while pointer",
        "  supervision is masked; no pointer class is guessed or fabricated.",
        "- The approved 32-capacity schema does not change final K=8.",
        "",
        "## Boundaries",
        "",
        "- Teacher used: false",
        "- Privileged simulator truth as policy input: false",
        "- Collection/physics/model rollout/training/Q-B performed by packaging: false",
        "- Existing episode outcomes reinterpreted: false",
        "- Bundle-smoke checkpoint: **2026-08-20 Asia/Shanghai** (unchanged)",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def build_dataset(
    *, project_root: Path, evidence_base: Path, artifact_root: Path
) -> tuple[
    M2CS4DecisionLevelDatasetManifestV1,
    dict[str, Any],
    bytes,
    bytes,
    bytes,
    bytes,
]:
    project_root = project_root.resolve(strict=True)
    evidence_base = evidence_base.resolve(strict=True)
    adr_raw = read_regular_file_once(project_root / ADR0026_PATH)
    if sha256_bytes(adr_raw) != ADR0026_SHA256:
        raise DecisionPackagingError("accepted ADR-0026 bytes changed")
    yield_audit = read_bound_json(project_root / YIELD_AUDIT_PATH, YIELD_AUDIT_SHA256)
    v3_manifest = load_v3_training_manifest(project_root / "configs/m2c_s4_v3_training_keys.json")
    v4_manifests = (
        load_v4_training_manifest(project_root / "configs/m2c_s4_v4_training_keys.json"),
        load_v4_training_manifest(project_root / "configs/m2c_s4_v4_training_keys_extension1.json"),
    )
    v3_rows, v3_episodes = _replay_v3_sources(
        project_root=project_root,
        evidence_base=evidence_base,
        yield_audit=yield_audit,
        manifest=v3_manifest,
    )
    v4_rows, v4_episodes = _replay_v4_sources(
        project_root=project_root,
        evidence_base=evidence_base,
        yield_audit=yield_audit,
        manifests=v4_manifests,
    )
    scene_rows, scene_episode = _replay_scene19083(
        project_root=project_root,
        evidence_base=evidence_base,
        manifests=v4_manifests,
    )
    v4_rows.extend(scene_rows)
    episodes = [*v3_episodes, *v4_episodes, scene_episode]
    if len(episodes) != 49 or len({item["matched_key"] for item in episodes}) != 49:
        raise DecisionPackagingError("replayed episode inventory is not 49 unique chains")
    v3_rows.sort(key=lambda item: (item.matched_key, item.decision_index))
    v4_rows.sort(key=lambda item: (item.matched_key, item.decision_index))
    v3_bytes = _jsonl_bytes(v3_rows)
    v4_bytes = _jsonl_bytes(v4_rows)
    manifest = _manifest(
        project_root=project_root,
        artifact_root=artifact_root,
        v3_rows=v3_rows,
        v4_rows=v4_rows,
        episodes=episodes,
        v3_bytes=v3_bytes,
        v4_bytes=v4_bytes,
    )
    manifest_bytes = (
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    return manifest, {"episodes": episodes}, v3_bytes, v4_bytes, manifest_bytes, adr_raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--evidence-base", type=Path, required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT / "artifacts/m2c/s4-decision-level-supervision-adr0026-v1",
    )
    parser.add_argument("--output-report-json", type=Path)
    parser.add_argument("--output-card", type=Path)
    parser.add_argument("--expected-manifest", type=Path)
    args = parser.parse_args()
    project_root = args.project_root.resolve(strict=True)
    artifact_root = args.artifact_root
    if not artifact_root.is_absolute():
        artifact_root = project_root / artifact_root
    manifest, details, v3_bytes, v4_bytes, manifest_bytes, _ = build_dataset(
        project_root=project_root,
        evidence_base=args.evidence_base,
        artifact_root=artifact_root,
    )
    if args.expected_manifest is not None:
        expected = read_regular_file_once(args.expected_manifest)
        if expected != manifest_bytes:
            raise DecisionPackagingError("replayed manifest differs from expected bytes")
        _load_rows_from_manifest(project_root, manifest)
        print(manifest_bytes.decode("utf-8"), end="")
        return 0
    if artifact_root.exists():
        raise DecisionPackagingError("artifact root already exists; output is create-only")
    artifact_root.mkdir(parents=True, mode=0o755)
    _publish_create_only(artifact_root / "decision-level-v3.jsonl", v3_bytes)
    _publish_create_only(artifact_root / "decision-level-v4.jsonl", v4_bytes)
    _publish_create_only(artifact_root / "dataset-manifest.json", manifest_bytes)
    _load_rows_from_manifest(project_root, manifest)
    report = _report(
        project_root=project_root,
        artifact_root=artifact_root,
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        episodes=details["episodes"],
    )
    report_bytes = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    card_bytes = _card(report)
    if args.output_report_json is not None:
        _publish_create_only(args.output_report_json, report_bytes)
    if args.output_card is not None:
        _publish_create_only(args.output_card, card_bytes)
    print(report_bytes.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
