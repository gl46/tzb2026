#!/usr/bin/env python3
"""Verify and summarize the pre-registered M2C S6 matched evaluation.

This command is deliberately evidence-only.  It never starts Isaac, a model
server, training, or an evaluation run.  A formal report is possible only
from the exact frozen 30-key manifest and hash-addressed physical receipts.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    Method,
    M2BClosedLoopEpisodeV1,
    fc_gain_over_b0,
    pure_model_success_exclusion_reasons,
    pure_model_success_episode,
    summarize_matched,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import physical_receipt_sha256
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2


PROJECT = Path(__file__).resolve().parents[2]
EXPECTED_METHODS: tuple[Method, ...] = (
    "B0",
    "QRM_COARSE_NO_FC",
    "QRM_COARSE_FC",
    "QRM_COARSE_FC_MLP",
)
MINIMUM_MATCHED_KEYS = 30
MINIMUM_MODEL_DECISIONS_EXECUTED = 50
BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 20_260_812
DEFAULT_PREREGISTRATION = PROJECT / "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md"
DEFAULT_FROZEN_KEYS = PROJECT / "configs/m2c_s6_evaluation_keys.json"
DEFAULT_REPORT = PROJECT / "reports/m2c-s6-matched.json"
DEFAULT_REPORT_MD = PROJECT / "reports/m2c-s6-matched.md"
FROZEN_KEYS_FILE_SHA256 = "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
FROZEN_KEYS_CONTENT_SHA256 = "0ce322d948dac851d7a26053af0207e563a69bb0127c462312cdad9badafe419"
PREREGISTRATION_SHA256 = "01786e2c40d18a82c75a32d20dce4755f7ee9f0f00b05b623f8bdd7672462dae"
# A hash-addressed PhysicalSkillReceiptV2 proves internal consistency, not that
# bytes came from the reviewed labserver deployment.  Formal S6 authorization
# therefore remains fail-closed until an independent verifier is implemented,
# reviewed, frozen here, and made to authenticate all 120 episode-level chains
# (including B0, non-model continuations, and the signed finalize outcome).
S6_AUTHENTICATED_EPISODE_EVIDENCE_VERIFIER_BINDING: tuple[str, str] | None = None
TEACHER_KILL_RULES = (
    "kill the run if Teacher soft labels enter Student training or evaluation",
    "kill the run if a Teacher response or adapter enters the control stack",
    "kill the run if a Teacher is silently replaced or upgraded",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FROZEN_KEY_FIELDS = {
    "anchor_xy_m",
    "blocker_distance_m",
    "blocker_selector_policy_input",
    "destination_cell",
    "failure_seed",
    "failure_type",
    "layout_family",
    "matched_key",
    "offline_geometry_admission",
    "offline_scene_materialized_during_selection",
    "outcome_observed_during_selection",
    "retained_blocker_distance_m",
    "role",
    "scene_seed",
    "sdf_sha256",
    "split",
    "supervision_sha256",
    "target_selector_policy_input",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class M2CS6EpisodeEvidenceV1(StrictModel):
    """One method outcome bound to the complete frozen key identity."""

    schema_version: Literal["M2CS6EpisodeEvidenceV1"] = "M2CS6EpisodeEvidenceV1"
    episode: M2BClosedLoopEpisodeV1
    frozen_key_identity: dict[str, Any]
    evidence_origin: Literal["ISAAC_PHYSICAL_MATCHED_EVALUATION"] = (
        "ISAAC_PHYSICAL_MATCHED_EVALUATION"
    )
    real_physics: Literal[True] = True
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    world_model_mainline_replaced: Literal[False] = False


class M2CS6PhysicalExecutionReceiptV1(StrictModel):
    """Hash-addressed evidence for one QRM model decision.

    The outer envelope binds the frozen S6 identity and model provenance.  The
    inner receipt is the strict formal-Isaac physical skill receipt and carries
    its own canonical semantic hash.
    """

    schema_version: Literal["M2CS6PhysicalExecutionReceiptV1"] = "M2CS6PhysicalExecutionReceiptV1"
    evidence_origin: Literal["FORMAL_ISAAC_PHYSICAL_EXECUTION"] = "FORMAL_ISAAC_PHYSICAL_EXECUTION"
    execution_mode: Literal["REAL_PHYSICS_NO_MOCKS"] = "REAL_PHYSICS_NO_MOCKS"
    host: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    collected_at_ns: int = Field(gt=0)
    episode_id: str = Field(min_length=1)
    matched_key: str = Field(min_length=1)
    method: Method
    frozen_key_identity: dict[str, Any]
    decision_id: str = Field(min_length=1)
    step_id: int = Field(ge=0)
    decision_outcome: Literal["SUCCESS", "FAILURE", "UNKNOWN"]
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_receipt: PhysicalSkillReceiptV2
    real_physics: Literal[True] = True
    synthetic: Literal[False] = False
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    world_model_mainline_replaced: Literal[False] = False


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_sha256(payload: object) -> str:
    return _sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _nearest_rank(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot take a percentile of an empty sample")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(probability * len(ordered) + 0.999999999999)))
    return ordered[rank - 1]


def paired_bootstrap_difference(
    pairs: list[tuple[bool, bool]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Return a deterministic percentile CI for first-minus-second success."""

    if not pairs:
        raise ValueError("paired bootstrap requires at least one matched key")
    if resamples < 1:
        raise ValueError("paired bootstrap requires a positive resample count")
    rng = random.Random(seed)
    count = len(pairs)
    differences = []
    for _ in range(resamples):
        total = 0
        for _ in range(count):
            first, second = pairs[rng.randrange(count)]
            total += int(first) - int(second)
        differences.append(total / count)
    point = sum(int(first) - int(second) for first, second in pairs) / count
    return {
        "estimate": point,
        "confidence_level": 0.95,
        "interval": [
            _nearest_rank(differences, 0.025),
            _nearest_rank(differences, 0.975),
        ],
        "method": "PAIRED_NONPARAMETRIC_BOOTSTRAP_PERCENTILE",
        "resamples": resamples,
        "seed": seed,
        "matched_keys": count,
        "discordance": {
            "first_only_success": sum(first and not second for first, second in pairs),
            "second_only_success": sum(second and not first for first, second in pairs),
            "both_success": sum(first and second for first, second in pairs),
            "neither_success": sum(not first and not second for first, second in pairs),
        },
    }


def _resolve_project_file(project_root: Path, raw: str) -> Path:
    if not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        raise ValueError(f"frozen source binding is not a safe project-relative path: {raw}")
    root = project_root.resolve()
    path = (root / raw).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"frozen source binding escapes project root: {raw}")
    return path


def load_and_verify_frozen_inputs(
    frozen_keys_path: Path,
    preregistration_path: Path,
    *,
    project_root: Path = PROJECT,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Load the exact pre-execution S6 manifest and verify every source binding."""

    manifest_file_sha256 = _sha256_file(frozen_keys_path)
    if manifest_file_sha256 != FROZEN_KEYS_FILE_SHA256:
        raise ValueError(
            "frozen S6 key manifest file SHA-256 mismatch: "
            f"{manifest_file_sha256} != {FROZEN_KEYS_FILE_SHA256}"
        )
    preregistration_sha256 = _sha256_file(preregistration_path)
    if preregistration_sha256 != PREREGISTRATION_SHA256:
        raise ValueError(
            "S6 pre-registration SHA-256 mismatch: "
            f"{preregistration_sha256} != {PREREGISTRATION_SHA256}"
        )
    manifest = json.loads(frozen_keys_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("frozen S6 key manifest is not an object")
    if manifest.get("schema_version") != "M2CS6FrozenEvaluationKeyManifestV1":
        raise ValueError("unsupported frozen S6 key manifest schema")
    if manifest.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION":
        raise ValueError("S6 key manifest was not frozen before execution")
    if manifest.get("methods") != list(EXPECTED_METHODS):
        raise ValueError("frozen S6 methods differ from the four pre-registered methods")
    if manifest.get("minimum_complete_matched_keys") != MINIMUM_MATCHED_KEYS:
        raise ValueError("frozen S6 minimum matched-key gate changed")
    if manifest.get("selection_uses_rollout_outcomes") is not False:
        raise ValueError("frozen S6 key selection used rollout outcomes")
    if manifest.get("excluded_from_all_training") is not True:
        raise ValueError("frozen S6 keys were not excluded from training")
    if manifest.get("teacher_used") is not False:
        raise ValueError("frozen S6 key selection used a Teacher")
    if manifest.get("privileged_truth_policy_input") is not False:
        raise ValueError("frozen S6 key selection used privileged policy input")

    content = dict(manifest)
    declared_content_sha256 = content.pop("manifest_sha256", None)
    actual_content_sha256 = _canonical_sha256(content)
    if (
        declared_content_sha256 != FROZEN_KEYS_CONTENT_SHA256
        or actual_content_sha256 != FROZEN_KEYS_CONTENT_SHA256
    ):
        raise ValueError("frozen S6 key manifest canonical content SHA-256 mismatch")

    records = manifest.get("evaluation_keys")
    if not isinstance(records, list) or len(records) != MINIMUM_MATCHED_KEYS:
        raise ValueError("frozen S6 manifest must contain exactly 30 evaluation keys")
    matched_keys: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != FROZEN_KEY_FIELDS:
            raise ValueError(f"frozen S6 key {index} does not have the exact identity schema")
        matched_key = record.get("matched_key")
        identity = dict(record)
        identity.pop("matched_key")
        expected_matched_key = "m2c-s4-s6-" + _canonical_sha256(identity)
        if matched_key != expected_matched_key:
            raise ValueError(f"frozen S6 key {index} canonical identity digest mismatch")
        if matched_key in matched_keys:
            raise ValueError(f"duplicate frozen S6 matched key: {matched_key}")
        matched_keys.add(str(matched_key))
        if (
            record.get("role") != "EVALUATION"
            or record.get("split") != "test"
            or record.get("failure_type") != "PATH_BLOCKED"
            or record.get("offline_scene_materialized_during_selection") is not True
            or record.get("outcome_observed_during_selection") is not False
        ):
            raise ValueError(f"frozen S6 key {index} violates the evaluation identity contract")
        for field in ("sdf_sha256", "supervision_sha256"):
            if not isinstance(record.get(field), str) or not SHA256_PATTERN.fullmatch(
                record[field]
            ):
                raise ValueError(f"frozen S6 key {index} has malformed {field}")

    source_bindings = manifest.get("source_bindings")
    if not isinstance(source_bindings, dict) or not source_bindings:
        raise ValueError("frozen S6 manifest has no source bindings")
    prereg_relative = "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md"
    if source_bindings.get(prereg_relative) != PREREGISTRATION_SHA256:
        raise ValueError("frozen S6 manifest does not bind the exact pre-registration")
    for raw_path, expected_sha256 in source_bindings.items():
        if not isinstance(raw_path, str) or not isinstance(expected_sha256, str):
            raise ValueError("frozen S6 source binding is malformed")
        source = _resolve_project_file(project_root, raw_path)
        if not source.is_file() or _sha256_file(source) != expected_sha256:
            raise ValueError(f"frozen S6 source binding mismatch: {raw_path}")
    selection = manifest.get("selection_implementation")
    if not isinstance(selection, dict) or set(selection) != {"path", "sha256"}:
        raise ValueError("frozen S6 selection implementation binding is malformed")
    selection_path = _resolve_project_file(project_root, str(selection["path"]))
    if not selection_path.is_file() or _sha256_file(selection_path) != selection["sha256"]:
        raise ValueError("frozen S6 selection implementation SHA-256 mismatch")

    return manifest, {
        "frozen_key_manifest_file_sha256": manifest_file_sha256,
        "frozen_key_manifest_content_sha256": actual_content_sha256,
        "preregistration_sha256": preregistration_sha256,
    }


def _complete_outcomes(
    episodes: list[M2BClosedLoopEpisodeV1],
) -> dict[str, dict[str, bool]]:
    by_key: dict[str, dict[str, bool]] = {}
    duplicate_methods: set[str] = set()
    for episode in episodes:
        outcomes = by_key.setdefault(episode.matched_key, {})
        if episode.method in outcomes:
            duplicate_methods.add(episode.matched_key)
        outcomes[episode.method] = episode.final_success
    expected = set(EXPECTED_METHODS)
    return {
        key: outcomes
        for key, outcomes in by_key.items()
        if key not in duplicate_methods and set(outcomes) == expected
    }


def _method_pairs(
    outcomes: dict[str, dict[str, bool]],
    first: Method,
    second: Method,
) -> list[tuple[bool, bool]]:
    return [(outcomes[key][first], outcomes[key][second]) for key in sorted(outcomes)]


def _append_finding(findings: list[str], finding: str) -> None:
    if finding not in findings:
        findings.append(finding)


def _validate_episode_identities(
    evidence: list[M2CS6EpisodeEvidenceV1],
    frozen_manifest: Mapping[str, Any],
) -> tuple[list[M2BClosedLoopEpisodeV1], list[str]]:
    findings: list[str] = []
    frozen_records = {
        str(record["matched_key"]): record for record in frozen_manifest["evaluation_keys"]
    }
    valid: list[M2BClosedLoopEpisodeV1] = []
    for item in evidence:
        episode = item.episode
        frozen = frozen_records.get(episode.matched_key)
        if frozen is None:
            _append_finding(findings, f"episode {episode.episode_id}: matched key is not frozen S6")
            continue
        if item.frozen_key_identity != frozen:
            _append_finding(
                findings,
                f"episode {episode.episode_id}: complete frozen key identity mismatch",
            )
            continue
        if episode.scene_seed != frozen["scene_seed"]:
            _append_finding(findings, f"episode {episode.episode_id}: frozen scene seed mismatch")
            continue
        if episode.failure_type != frozen["failure_type"]:
            _append_finding(findings, f"episode {episode.episode_id}: frozen failure type mismatch")
            continue
        valid.append(episode)

    by_key: dict[str, list[M2BClosedLoopEpisodeV1]] = defaultdict(list)
    for episode in valid:
        by_key[episode.matched_key].append(episode)
    expected_key_set = set(frozen_records)
    observed_key_set = set(by_key)
    missing_keys = sorted(expected_key_set - observed_key_set)
    extra_keys = sorted(observed_key_set - expected_key_set)
    if missing_keys:
        _append_finding(findings, f"missing frozen S6 keys: {missing_keys}")
    if extra_keys:
        _append_finding(findings, f"non-frozen S6 keys observed: {extra_keys}")
    for matched_key in sorted(expected_key_set):
        methods = [episode.method for episode in by_key.get(matched_key, [])]
        counts = Counter(methods)
        if counts != Counter(EXPECTED_METHODS):
            _append_finding(
                findings,
                f"{matched_key}: requires exactly one episode for each four-method arm; "
                f"observed {dict(sorted(counts.items()))}",
            )
    expected_episode_count = MINIMUM_MATCHED_KEYS * len(EXPECTED_METHODS)
    if len(valid) != expected_episode_count:
        _append_finding(
            findings,
            f"identity-valid episodes {len(valid)} != exact required {expected_episode_count}",
        )
    return valid, findings


def _receipt_file(root: Path, digest: str) -> Path:
    if not SHA256_PATTERN.fullmatch(digest):
        raise ValueError("execution_outcome is not a SHA-256")
    resolved_root = root.resolve()
    path = (resolved_root / f"{digest}.json").resolve()
    if path.parent != resolved_root:
        raise ValueError("physical receipt path escapes receipt root")
    if not path.is_file():
        raise FileNotFoundError(path)
    if _sha256_file(path) != digest:
        raise ValueError("physical receipt file SHA-256 mismatch")
    return path


def _validate_receipt_binding(
    receipt: M2CS6PhysicalExecutionReceiptV1,
    *,
    episode: M2BClosedLoopEpisodeV1,
    decision: Any,
    frozen_identity: Mapping[str, Any],
) -> tuple[bool, int]:
    if receipt.run_id != episode.episode_id or receipt.episode_id != episode.episode_id:
        raise ValueError("physical receipt run/episode binding mismatch")
    if receipt.matched_key != episode.matched_key or receipt.method != episode.method:
        raise ValueError("physical receipt matched-key/method binding mismatch")
    if receipt.frozen_key_identity != frozen_identity:
        raise ValueError("physical receipt complete frozen identity mismatch")
    if receipt.decision_id != decision.decision_id or receipt.step_id != decision.step_id:
        raise ValueError("physical receipt decision binding mismatch")
    if receipt.decision_outcome != decision.outcome:
        raise ValueError("physical receipt decision outcome mismatch")
    for field in (
        "registry_sha256",
        "model_checkpoint_sha256",
        "model_input_sha256",
        "model_output_sha256",
        "mapping_result_sha256",
    ):
        if getattr(receipt, field) != getattr(decision, field):
            raise ValueError(f"physical receipt model provenance mismatch: {field}")

    physical = receipt.physical_receipt
    if physical.receipt_sha256 != physical_receipt_sha256(physical):
        raise ValueError("physical skill receipt canonical SHA-256 mismatch")
    if physical.teacher_used or physical.privileged_truth_policy_input:
        raise ValueError("physical skill receipt violates Teacher/truth boundary")
    if physical.collision_or_safety_violation:
        return False, 1

    expected_source = {
        "MODEL_SELECTED_B0_SKILL": "MODEL_SELECTED_REGISTERED_SKILL",
        "B0_FALLBACK": "B0_FALLBACK",
        "NONE": "NO_PHYSICAL_EXECUTION",
    }.get(decision.execution_source)
    if physical.execution_source != expected_source:
        raise ValueError("physical receipt execution source differs from attribution")
    if decision.execution_source == "NONE":
        if physical.physically_executed:
            raise ValueError("non-execution decision has a physical execution claim")
        return False, 0
    if not physical.physically_executed:
        raise ValueError("physical receipt does not prove physical execution")
    if decision.executed_skill is None or physical.executed_skill != decision.executed_skill:
        raise ValueError("physical receipt executed skill mismatch")
    if decision.execution_source == "B0_FALLBACK":
        if not physical.fallback_reason or physical.fallback_reason != decision.fallback_reason:
            raise ValueError("physical B0 fallback reason mismatch")
        return False, 0
    if physical.fallback_reason is not None:
        raise ValueError("model-owned physical receipt carries a fallback reason")
    for gate in (
        "schema_gate",
        "stale_track_gate",
        "frame_unit_gate",
        "ik_gate",
        "collision_gate",
        "controller_gate",
        "safety_gate",
    ):
        if getattr(physical, gate) != "PASS":
            raise ValueError(f"model physical receipt has non-passing {gate}")
    if decision.mapping_status != "VALID":
        raise ValueError("model physical receipt is attached to an invalid mapping")
    return True, 0


def _verify_qrm_physical_receipts(
    episodes: list[M2BClosedLoopEpisodeV1],
    *,
    frozen_manifest: Mapping[str, Any],
    physical_receipts_root: Path,
) -> dict[str, Any]:
    frozen_records = {
        str(record["matched_key"]): record for record in frozen_manifest["evaluation_keys"]
    }
    findings: list[str] = []
    seen_file_hashes: set[str] = set()
    seen_semantic_hashes: set[str] = set()
    seen_receipt_ids: set[str] = set()
    verified_receipts = 0
    verified_model_executions = 0
    physical_violations = 0
    qrm_model_decisions = 0
    for episode in episodes:
        if episode.method == "B0":
            continue
        for decision in episode.decisions:
            if not decision.model_decision:
                continue
            qrm_model_decisions += 1
            digest = decision.gate_evidence_sha256.get("execution_outcome", "")
            label = f"{episode.episode_id}/{decision.decision_id}"
            if digest in seen_file_hashes:
                _append_finding(findings, f"{label}: physical receipt file reused: {digest}")
                continue
            try:
                path = _receipt_file(physical_receipts_root, digest)
                parsed = M2CS6PhysicalExecutionReceiptV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                physical = parsed.physical_receipt
                if physical.receipt_sha256 in seen_semantic_hashes:
                    raise ValueError("physical skill receipt semantic hash reused")
                if physical.receipt_id in seen_receipt_ids:
                    raise ValueError("physical skill receipt ID reused")
                model_owned, violations = _validate_receipt_binding(
                    parsed,
                    episode=episode,
                    decision=decision,
                    frozen_identity=frozen_records[episode.matched_key],
                )
            except (OSError, ValueError, KeyError) as error:
                _append_finding(
                    findings,
                    f"{label}: invalid physical execution receipt: {type(error).__name__}: {error}",
                )
                continue
            seen_file_hashes.add(digest)
            seen_semantic_hashes.add(physical.receipt_sha256)
            seen_receipt_ids.add(physical.receipt_id)
            verified_receipts += 1
            verified_model_executions += int(model_owned)
            physical_violations += violations
            if decision.execution_source == "NONE":
                _append_finding(findings, f"{label}: model decision was not physically executed")
    return {
        "qrm_model_decisions": qrm_model_decisions,
        "physical_execution_receipts_verified": verified_receipts,
        "verified_model_decisions_executed": verified_model_executions,
        "physical_receipt_collision_or_safety_violations": physical_violations,
        "unique_receipt_file_hashes": len(seen_file_hashes),
        "unique_physical_receipt_hashes": len(seen_semantic_hashes),
        "findings": findings,
    }


def summarize_s6(
    evidence: list[M2CS6EpisodeEvidenceV1],
    *,
    frozen_manifest: Mapping[str, Any],
    frozen_bindings: Mapping[str, str],
    physical_receipts_root: Path,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    valid_episodes, identity_findings = _validate_episode_identities(evidence, frozen_manifest)
    base = summarize_matched(valid_episodes, expected_methods=EXPECTED_METHODS)
    findings = [*identity_findings, *base["findings"]]
    complete_outcomes = _complete_outcomes(valid_episodes)
    complete_keys = len(complete_outcomes)
    frozen_keys = {str(item["matched_key"]) for item in frozen_manifest["evaluation_keys"]}
    if set(complete_outcomes) != frozen_keys or complete_keys != MINIMUM_MATCHED_KEYS:
        _append_finding(
            findings,
            f"complete frozen four-method keys {complete_keys} != exact required {MINIMUM_MATCHED_KEYS}",
        )

    physical = _verify_qrm_physical_receipts(
        valid_episodes,
        frozen_manifest=frozen_manifest,
        physical_receipts_root=physical_receipts_root,
    )
    for finding in physical["findings"]:
        _append_finding(findings, str(finding))
    authenticated_episode_evidence_verified = 0
    if S6_AUTHENTICATED_EPISODE_EVIDENCE_VERIFIER_BINDING is None:
        _append_finding(
            findings,
            "S6 authenticated episode-level evidence verifier is not frozen; "
            "B0 execution, complete action chains, arm provenance, labserver origin, "
            "and signed finalize outcomes remain unverified",
        )
    authenticated_evidence_ready = bool(
        S6_AUTHENTICATED_EPISODE_EVIDENCE_VERIFIER_BINDING is not None
        and authenticated_episode_evidence_verified == MINIMUM_MATCHED_KEYS * len(EXPECTED_METHODS)
    )
    verified_executed = int(physical["verified_model_decisions_executed"])
    claimed_executed = int(base["qrm_model_decisions_executed"])
    if verified_executed != claimed_executed:
        _append_finding(
            findings,
            "episode-attributed model executions differ from independently verified physical "
            f"receipts: {claimed_executed} != {verified_executed}",
        )
    if verified_executed < MINIMUM_MODEL_DECISIONS_EXECUTED:
        _append_finding(
            findings,
            "verified physically executed model decisions "
            f"{verified_executed} < {MINIMUM_MODEL_DECISIONS_EXECUTED}",
        )

    episode_violations = sum(
        int(metrics["collision_or_safety_violations"])
        for metrics in base["method_metrics"].values()
    )
    receipt_violations = int(physical["physical_receipt_collision_or_safety_violations"])
    total_violations = episode_violations + receipt_violations
    if total_violations:
        _append_finding(
            findings,
            "collision or safety violations in episode/receipt evidence: "
            f"{episode_violations}/{receipt_violations}",
        )

    primary = None
    secondary_fc_over_no_fc = None
    secondary_mlp_over_b0 = None
    if set(complete_outcomes) == frozen_keys and complete_keys == MINIMUM_MATCHED_KEYS:
        primary = paired_bootstrap_difference(
            _method_pairs(complete_outcomes, "QRM_COARSE_FC", "B0"),
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        primary["name"] = "fc_gain_over_b0"
        primary["estimate_crosscheck"] = fc_gain_over_b0(
            float(base["method_metrics"]["QRM_COARSE_FC"]["final_task_success_rate"]),
            float(base["method_metrics"]["B0"]["final_task_success_rate"]),
        )
        secondary_fc_over_no_fc = paired_bootstrap_difference(
            _method_pairs(complete_outcomes, "QRM_COARSE_FC", "QRM_COARSE_NO_FC"),
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        secondary_fc_over_no_fc["name"] = "fc_gain_over_no_fc"
        secondary_mlp_over_b0 = paired_bootstrap_difference(
            _method_pairs(complete_outcomes, "QRM_COARSE_FC_MLP", "B0"),
            resamples=bootstrap_resamples,
            seed=bootstrap_seed,
        )
        secondary_mlp_over_b0["name"] = "fc_mlp_gain_over_b0"

    # The statistics above are useful only as an internal consistency replay.
    # Do not emit them as experiment metrics until all 120 complete physical
    # chains and finalize outcomes have independent deployment authentication.
    if not authenticated_evidence_ready:
        primary = None
        secondary_fc_over_no_fc = None
        secondary_mlp_over_b0 = None

    formal_ready = bool(
        not findings
        and authenticated_evidence_ready
        and primary is not None
        and verified_executed >= MINIMUM_MODEL_DECISIONS_EXECUTED
        and total_violations == 0
    )
    locally_replayed_successful_any_model = sum(
        episode.final_success and any(decision.model_decision for decision in episode.decisions)
        for episode in valid_episodes
    )
    locally_replayed_pure_model_success = sum(
        pure_model_success_episode(episode) for episode in valid_episodes
    )
    locally_replayed_pure_exclusions = [
        {
            "episode_id": episode.episode_id,
            "matched_key": episode.matched_key,
            "reasons": pure_model_success_exclusion_reasons(episode),
        }
        for episode in valid_episodes
        if episode.final_success and not pure_model_success_episode(episode)
    ]
    if locally_replayed_pure_model_success > locally_replayed_successful_any_model:
        raise AssertionError("pure model success exceeds successful any-model episodes")
    if any(not item["reasons"] for item in locally_replayed_pure_exclusions):
        raise AssertionError("successful non-pure S6 episode lacks exclusion reasons")
    next_command = (
        "make m2c-status"
        if formal_ready
        else ("sed -n '1,260p' docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md")
    )
    return {
        "schema_version": "M2CS6MatchedEvaluationReportV2",
        "status": (
            "PASS_M2C_S6_FORMAL_MATCHED_EVALUATION"
            if formal_ready
            else "BLOCKED_INVALID_OR_INCOMPLETE_S6_EVIDENCE"
        ),
        "evidence_mode": "READ_ONLY_EXISTING_EVIDENCE_SUMMARY",
        "experiment_executed_by_this_command": False,
        "expected_methods": list(EXPECTED_METHODS),
        "episodes": len(valid_episodes),
        "expected_exact_episodes": MINIMUM_MATCHED_KEYS * len(EXPECTED_METHODS),
        "matched_keys": int(base["matched_keys"]),
        "complete_matched_keys": complete_keys,
        "required_exact_complete_matched_keys": MINIMUM_MATCHED_KEYS,
        "frozen_key_identity_records_verified": len(valid_episodes),
        "frozen_bindings": dict(frozen_bindings),
        "frozen_evaluation_key_digest": frozen_manifest["manifest_sha256"],
        "qrm_model_decisions_observed": int(physical["qrm_model_decisions"]),
        "qrm_model_decisions_claimed_executed": claimed_executed,
        "qrm_model_decisions_executed": (verified_executed if authenticated_evidence_ready else 0),
        "locally_replayed_model_decisions": verified_executed,
        "minimum_model_decisions_executed": MINIMUM_MODEL_DECISIONS_EXECUTED,
        "physical_execution_receipts_verified": (
            int(physical["physical_execution_receipts_verified"])
            if authenticated_evidence_ready
            else 0
        ),
        "locally_replayed_physical_receipts": int(physical["physical_execution_receipts_verified"]),
        "authenticated_episode_evidence_verifier_binding": (
            list(S6_AUTHENTICATED_EPISODE_EVIDENCE_VERIFIER_BINDING)
            if S6_AUTHENTICATED_EPISODE_EVIDENCE_VERIFIER_BINDING is not None
            else None
        ),
        "authenticated_episode_evidence_verified": authenticated_episode_evidence_verified,
        "required_authenticated_episode_evidence": (MINIMUM_MATCHED_KEYS * len(EXPECTED_METHODS)),
        "unique_receipt_file_hashes": int(physical["unique_receipt_file_hashes"]),
        "unique_physical_receipt_hashes": int(physical["unique_physical_receipt_hashes"]),
        "episode_collision_or_safety_violations": episode_violations,
        "physical_receipt_collision_or_safety_violations": receipt_violations,
        "collision_or_safety_violations": (
            total_violations if authenticated_evidence_ready else None
        ),
        "locally_replayed_collision_or_safety_violations": total_violations,
        "successful_episodes_with_any_model_decision": (
            locally_replayed_successful_any_model if authenticated_evidence_ready else None
        ),
        "pure_model_success_episodes": (
            locally_replayed_pure_model_success if authenticated_evidence_ready else None
        ),
        "pure_model_success_exclusions": (
            locally_replayed_pure_exclusions if authenticated_evidence_ready else []
        ),
        "method_metrics": base["method_metrics"] if authenticated_evidence_ready else {},
        "primary_metric": primary,
        "secondary_metrics": [
            metric
            for metric in (secondary_fc_over_no_fc, secondary_mlp_over_b0)
            if metric is not None
        ],
        "findings": findings,
        "formal_evaluation_ready": formal_ready,
        "teacher_used": False,
        "teacher_kill_rules": list(TEACHER_KILL_RULES),
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
        "task_report": {
            "changed_files": ["reports/m2c-s6-matched.json", "reports/m2c-s6-matched.md"],
            "tests": [
                "frozen manifest and pre-registration SHA replay",
                "exact 30-key/four-method identity replay",
                "hash-addressed strict physical receipt replay",
                "independent authenticated episode evidence gate",
                "paired FC-vs-B0 bootstrap",
            ],
            "failures": findings,
            "blockers": findings,
            "next_command": next_command,
        },
        "next_command": next_command,
    }


def _blocked_report(error: Exception) -> dict[str, Any]:
    finding = f"S6 evidence input failed closed: {type(error).__name__}: {error}"
    return {
        "schema_version": "M2CS6MatchedEvaluationReportV2",
        "status": "BLOCKED_INVALID_OR_INCOMPLETE_S6_EVIDENCE",
        "evidence_mode": "READ_ONLY_EXISTING_EVIDENCE_SUMMARY",
        "experiment_executed_by_this_command": False,
        "formal_evaluation_ready": False,
        "complete_matched_keys": 0,
        "qrm_model_decisions_executed": 0,
        "collision_or_safety_violations": None,
        "primary_metric": None,
        "findings": [finding],
        "teacher_used": False,
        "teacher_kill_rules": list(TEACHER_KILL_RULES),
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
        "task_report": {
            "changed_files": ["reports/m2c-s6-matched.json", "reports/m2c-s6-matched.md"],
            "tests": [],
            "failures": [finding],
            "blockers": [finding],
            "next_command": (
                "provide the exact frozen evidence inputs and rerun make m2c-s6; "
                "do not start an experiment from this target"
            ),
        },
        "next_command": (
            "provide the exact frozen evidence inputs and rerun make m2c-s6; "
            "do not start an experiment from this target"
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    findings = [str(item) for item in payload.get("findings", [])]
    primary = payload.get("primary_metric")
    lines = [
        "# M2C S6 matched evaluation",
        "",
        f"- Status: **{payload['status']}**",
        "- Evidence mode: read-only summary of existing evidence.",
        "- Experiment, training, remote execution, or model rollout started by this command: `false`.",
        f"- Complete frozen keys: `{payload.get('complete_matched_keys', 0)}/30`.",
        f"- Verified physical model decisions: `{payload.get('qrm_model_decisions_executed', 0)}/50`.",
        f"- Collision/safety violations: `{payload.get('collision_or_safety_violations')}`.",
        f"- Primary `fc_gain_over_b0`: `{primary}`.",
        "- Teacher used: `false`.",
        "- Privileged simulator truth used as policy input: `false`.",
        "- World-model mainline replaced: `false`.",
        "",
        "## Findings / blockers",
        "",
        *([f"- {item}" for item in findings] or ["- None."]),
        "",
        "## Task report",
        "",
        "- Changed files: this JSON report and Markdown companion only.",
        "- Tests: frozen identity, receipt hash/provenance, safety, and paired-statistic replay.",
        f"- Failures: `{findings}`.",
        f"- Blockers: `{findings}`.",
        f"- Next command: `{payload['next_command']}`",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verify_terminal_evidence_manifest(
    manifest_path: Path,
    *,
    episodes_path: Path,
    physical_receipts_root: Path,
) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("S6 terminal evidence manifest is not an object")
    if payload.get("schema_version") != "M2CTerminalRawEvidenceManifestV1":
        raise ValueError("S6 terminal evidence manifest schema is not frozen V1")
    if payload.get("teacher_used") is not False:
        raise ValueError("S6 terminal evidence manifest reports Teacher use")
    if payload.get("privileged_truth_policy_input") is not False:
        raise ValueError("S6 terminal evidence manifest reports privileged policy input")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("S6 terminal evidence manifest has no files")
    digests: dict[str, Path] = {}
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("S6 terminal evidence manifest file binding is malformed")
        raw_path = item["path"]
        expected = item["sha256"]
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            raise ValueError("S6 terminal evidence manifest file binding is malformed")
        candidate = Path(raw_path)
        candidate = candidate if candidate.is_absolute() else PROJECT / candidate
        if candidate.is_symlink():
            raise ValueError("S6 terminal evidence manifest may not bind symlinks")
        resolved = candidate.resolve()
        if not resolved.is_file() or _sha256_file(resolved) != expected:
            raise ValueError(f"S6 terminal evidence file SHA-256 mismatch: {raw_path}")
        if expected in digests or resolved in digests.values():
            raise ValueError("S6 terminal evidence manifest reuses a file or digest")
        digests[expected] = resolved
    episodes_digest = _sha256_file(episodes_path)
    if digests.get(episodes_digest) != episodes_path.resolve():
        raise ValueError("S6 episode JSONL is absent from the terminal evidence manifest")
    receipt_root = physical_receipts_root.resolve()
    if not receipt_root.is_dir():
        raise ValueError("S6 physical receipt root is absent")
    for receipt_path in receipt_root.glob("*.json"):
        digest = _sha256_file(receipt_path)
        if receipt_path.name != f"{digest}.json" or digests.get(digest) != receipt_path.resolve():
            raise ValueError("S6 physical receipt is absent from the terminal evidence manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--evidence-manifest", required=True, type=Path)
    parser.add_argument("--physical-receipts-root", required=True, type=Path)
    parser.add_argument("--frozen-keys", type=Path, default=DEFAULT_FROZEN_KEYS)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args()
    try:
        _verify_terminal_evidence_manifest(
            args.evidence_manifest,
            episodes_path=args.episodes,
            physical_receipts_root=args.physical_receipts_root,
        )
        frozen_manifest, frozen_bindings = load_and_verify_frozen_inputs(
            args.frozen_keys,
            args.preregistration,
        )
        evidence = [
            M2CS6EpisodeEvidenceV1.model_validate_json(line)
            for line in args.episodes.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report = summarize_s6(
            evidence,
            frozen_manifest=frozen_manifest,
            frozen_bindings=frozen_bindings,
            physical_receipts_root=args.physical_receipts_root,
        )
        report.update(
            {
                "episodes_path": str(args.episodes),
                "episodes_sha256": _sha256_file(args.episodes),
                "terminal_evidence": {
                    "schema_version": "M2CS6TerminalEvidenceBindingV1",
                    "episodes": {
                        "path": str(args.episodes),
                        "sha256": _sha256_file(args.episodes),
                    },
                    "evidence_manifest": {
                        "path": str(args.evidence_manifest),
                        "sha256": _sha256_file(args.evidence_manifest),
                    },
                    "preregistration": {
                        "path": str(args.preregistration),
                        "sha256": _sha256_file(args.preregistration),
                    },
                    "evaluation_key_manifest": {
                        "path": str(args.frozen_keys),
                        "sha256": _sha256_file(args.frozen_keys),
                    },
                },
                "physical_receipts_root": str(args.physical_receipts_root),
                "frozen_keys_path": str(args.frozen_keys),
                "preregistration_path": str(args.preregistration),
            }
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        report = _blocked_report(error)
    _write_json(args.report, report)
    _write_markdown(args.report_md, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["formal_evaluation_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
