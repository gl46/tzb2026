"""Strict ADR-0026 terminal-regrasp diagnostic contracts.

This module is deliberately separate from TRAIN collection.  It freezes a
paired, outcome-blind C1/C2/C3 campaign, consumes every planned run at most
once, and evaluates only the human-approved R1/R2/R3 decision tree.  It does
not change any controller, IK, contact, safety, B0, or public-predicate gate.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Literal, Mapping, Sequence
import xml.etree.ElementTree as ET

from pydantic import Field, model_validator

from xh_agent.policy.qrm_lite.contracts import StrictModel
from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    CommittedSourceSnapshotV1,
    read_regular_file_once,
    verify_materialized_source_snapshot,
)


ADR_PATH = "docs/decisions/ADR-0026-m2c-terminal-step-diagnosis.md"
ADR_SHA256 = "ba24b65435b19b3a7700bb7caba83a01d98897a8999aee54af5c2370d410c180"
ADR_INTRODUCED_COMMIT = "a87ba0bd6360579ccc1011ecc1f6cc5921c3fa13"
UPSTREAM_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
ISAAC_IMAGE = "nvcr.io/nvidia/isaac-sim:6.0.1"
ISAAC_IMAGE_ID = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
CONTROLLED_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
DIAGNOSTIC_CONDITIONS = ("C1_NO_BLOCKER", "C2_RETAINED_BLOCKER", "C3_FULL_V4")
CONDITION_INDEX = {condition: index + 1 for index, condition in enumerate(DIAGNOSTIC_CONDITIONS)}
RUNS_PER_CONDITION = 12
TOTAL_RUNS = RUNS_PER_CONDITION * len(DIAGNOSTIC_CONDITIONS)
FIXED_ANCHOR_XY_M = (-0.115, 0.13)
CYLINDER_RADIUS_M = 0.015
RETAINED_BLOCKER_CENTER_DISTANCE_M = 0.062
RETAINED_BLOCKER_SURFACE_GAP_M = RETAINED_BLOCKER_CENTER_DISTANCE_M - 2.0 * CYLINDER_RADIUS_M
TARGET_ENTITY = "cylinder_04"
SCRIPTED_BLOCKER_ENTITY = "cylinder_01"
RETAINED_BLOCKER_ENTITY = "cylinder_02"
DIAGNOSTIC_IMPLEMENTATION_PATHS = (
    "scripts/generate_industrial_scenes.py",
    "scripts/m2c/audit_terminal_regrasp_diagnostic.py",
    "scripts/m2c/build_terminal_regrasp_diagnostic_prereg.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe.py",
    "scripts/m2c/materialize_terminal_regrasp_diagnostic_scenes.py",
    "scripts/m2c/run_terminal_regrasp_diagnostic.py",
    "scripts/m2c/s4_scene_family.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v1.py",
)
DIAGNOSTIC_EXCLUSION_PATHS = (
    "configs/m2c_headroom_domain.json",
    "configs/m2c_headroom_domain_v2.json",
    "configs/m2c_headroom_domain_v3.json",
    "configs/m2c_headroom_domain_v4.json",
    "configs/m2c_s4_training_keys.json",
    "configs/m2c_s4_v3_training_keys.json",
    "configs/m2c_s4_v4_training_keys.json",
    "configs/m2c_s4_v4_training_keys_extension1.json",
    "configs/m2c_s6_evaluation_keys.json",
    "docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-24-PREREG.json",
    "reports/m2c-s4-training-eligibility-yield-adr0025.json",
)


class TerminalDiagnosticError(RuntimeError):
    """Fail-closed diagnostic contract error."""


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class BoundRepositoryFileV1(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AcceptedADR0026V1(StrictModel):
    path: Literal[ADR_PATH]
    sha256: Literal[ADR_SHA256]
    introduced_commit: Literal[ADR_INTRODUCED_COMMIT]
    status: Literal["ACCEPTED_HUMAN_ADR"]


class TerminalDiagnosticRunV1(StrictModel):
    ordinal: int = Field(ge=0, lt=TOTAL_RUNS)
    source_base_seed: int = Field(gt=0)
    scene_seed: int = Field(gt=0)
    failure_seed: int = Field(gt=0)
    condition: Literal[
        "C1_NO_BLOCKER",
        "C2_RETAINED_BLOCKER",
        "C3_FULL_V4",
    ]
    condition_index: int = Field(ge=1, le=3)
    probe_mode: Literal["DIRECT_TERMINAL", "FULL_V4_PREAMBLE_TERMINAL"]
    run_id: str = Field(pattern=r"^m2c-s4-terminal-diagnostic-[0-9a-f]{64}$")
    matched_key: str = Field(pattern=r"^m2c-s4-terminal-diagnostic-[0-9a-f]{64}$")
    anchor_xy_m: list[float] = Field(min_length=2, max_length=2)
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_local_blockers: list[str]
    terminal_target_blocker_surface_gap_m: float | None
    retry_authorized: Literal[False]
    replacement_authorized: Literal[False]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]

    @model_validator(mode="after")
    def identity_is_exact(self) -> "TerminalDiagnosticRunV1":
        expected_index = CONDITION_INDEX[self.condition]
        if self.condition_index != expected_index:
            raise ValueError("diagnostic condition index mismatch")
        expected_scene = self.source_base_seed * 10 + expected_index
        if self.scene_seed != expected_scene or self.failure_seed != expected_scene * 10 + 7:
            raise ValueError("diagnostic scene/failure seed derivation changed")
        if any(
            not math.isclose(actual, expected, abs_tol=1e-12)
            for actual, expected in zip(self.anchor_xy_m, FIXED_ANCHOR_XY_M, strict=True)
        ):
            raise ValueError("diagnostic anchor geometry changed")
        expected_mode = (
            "FULL_V4_PREAMBLE_TERMINAL" if self.condition == "C3_FULL_V4" else "DIRECT_TERMINAL"
        )
        if self.probe_mode != expected_mode:
            raise ValueError("diagnostic probe mode differs from condition")
        expected_blockers = {
            "C1_NO_BLOCKER": [],
            "C2_RETAINED_BLOCKER": [RETAINED_BLOCKER_ENTITY],
            "C3_FULL_V4": [SCRIPTED_BLOCKER_ENTITY, RETAINED_BLOCKER_ENTITY],
        }[self.condition]
        if self.expected_local_blockers != expected_blockers:
            raise ValueError("diagnostic local blocker set changed")
        expected_gap = None if self.condition == "C1_NO_BLOCKER" else RETAINED_BLOCKER_SURFACE_GAP_M
        if expected_gap is None:
            if self.terminal_target_blocker_surface_gap_m is not None:
                raise ValueError("C1 must declare no target-blocker surface gap")
        elif self.terminal_target_blocker_surface_gap_m is None or not math.isclose(
            self.terminal_target_blocker_surface_gap_m,
            expected_gap,
            abs_tol=1e-12,
        ):
            raise ValueError("diagnostic target-blocker surface gap changed")
        identity = self.model_dump(
            mode="json",
            exclude={"run_id", "matched_key"},
        )
        expected_id = f"m2c-s4-terminal-diagnostic-{canonical_sha256(identity)}"
        if self.run_id != expected_id or self.matched_key != expected_id:
            raise ValueError("diagnostic run identity digest mismatch")
        return self


class TerminalDiagnosticDecisionTreeV1(StrictModel):
    schema_version: Literal["M2CTerminalRegraspDecisionTreeV1"]
    success_definition: Literal[
        "PHYSICAL_LIFTED_AND_PUBLIC_GRASPED_TRUE_AND_LIFTED_TRUE_AND_ZERO_SAFETY_VIOLATIONS"
    ]
    denominator_policy: Literal["EXACTLY_12_VALID_TERMINAL_MEASUREMENTS_PER_CONDITION"]
    incomplete_policy: Literal["NO_BRANCH_UNTIL_ALL_36_RUNS_HAVE_VALID_MEASUREMENTS"]
    r1_c1_min_successes: Literal[9]
    r1_c3_max_successes: Literal[3]
    r2_c1_min_failures: Literal[6]
    r3_policy: Literal["ALL_COMPLETE_OUTCOMES_NOT_MATCHING_R1_OR_R2"]
    no_retry_or_replacement: Literal[True]


class M2CTerminalRegraspDiagnosticPreregV1(StrictModel):
    schema_version: Literal["M2CTerminalRegraspDiagnosticPreregV1"]
    status: Literal["FROZEN_BEFORE_ANY_DIAGNOSTIC_EXECUTION_OR_RESULT"]
    repository_relative_path: str
    introduction_commit_paths: list[str] = Field(min_length=1, max_length=1)
    campaign_id: Literal["m2c-s4-terminal-regrasp-diagnostic-v1"]
    governing_adr: AcceptedADR0026V1
    written_date_asia_shanghai: Literal["2026-08-15"]
    outcomes_observed_before_freeze: Literal[False]
    collection_halted: Literal[True]
    training_collection_authorized: Literal[False]
    diagnostic_only: Literal[True]
    fixed_order: Literal[True]
    paired_source_seeds: Literal[True]
    runs_per_condition: Literal[RUNS_PER_CONDITION]
    total_runs: Literal[TOTAL_RUNS]
    retry_authorized: Literal[False]
    replacement_authorized: Literal[False]
    terminal_only_estimand: Literal[True]
    no_gate_threshold_b0_or_predicate_change: Literal[True]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    container_image: Literal[ISAAC_IMAGE]
    container_image_id: Literal[ISAAC_IMAGE_ID]
    upstream_v4_probe_sha256: Literal[UPSTREAM_V4_PROBE_SHA256]
    controlled_urdf_sha256: Literal[CONTROLLED_URDF_SHA256]
    ledger_root: str
    ledger_namespace: Literal["M2C_S4_TERMINAL_REGRASP_DIAGNOSTIC_V1"]
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    committed_source_snapshot: CommittedSourceSnapshotV1
    implementation_bindings: list[BoundRepositoryFileV1] = Field(min_length=5)
    exclusion_sources: list[BoundRepositoryFileV1] = Field(min_length=4)
    external_identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runs: list[TerminalDiagnosticRunV1] = Field(
        min_length=TOTAL_RUNS,
        max_length=TOTAL_RUNS,
    )
    decision_tree: TerminalDiagnosticDecisionTreeV1
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def campaign_is_exact(self) -> "M2CTerminalRegraspDiagnosticPreregV1":
        if self.introduction_commit_paths != [self.repository_relative_path]:
            raise ValueError("diagnostic prereg introduction path is not singleton-exact")
        if [run.ordinal for run in self.runs] != list(range(TOTAL_RUNS)):
            raise ValueError("diagnostic run order is not exact")
        if [item.path for item in self.implementation_bindings] != list(
            DIAGNOSTIC_IMPLEMENTATION_PATHS
        ):
            raise ValueError("diagnostic implementation closure is not exact")
        if [item.path for item in self.exclusion_sources] != list(DIAGNOSTIC_EXCLUSION_PATHS):
            raise ValueError("diagnostic exclusion inventory is not exact")
        if self.committed_source_snapshot.commit != self.implementation_commit:
            raise ValueError("diagnostic source snapshot differs from implementation commit")
        expected_conditions = [
            condition for _ in range(RUNS_PER_CONDITION) for condition in DIAGNOSTIC_CONDITIONS
        ]
        if [run.condition for run in self.runs] != expected_conditions:
            raise ValueError("diagnostic paired C1/C2/C3 ordering changed")
        grouped: dict[int, list[TerminalDiagnosticRunV1]] = {}
        for run in self.runs:
            grouped.setdefault(run.source_base_seed, []).append(run)
        if len(grouped) != RUNS_PER_CONDITION or any(
            [run.condition for run in group] != list(DIAGNOSTIC_CONDITIONS)
            for group in grouped.values()
        ):
            raise ValueError("diagnostic source-seed pairing changed")
        for field in ("scene_seed", "failure_seed", "run_id", "matched_key"):
            values = [getattr(run, field) for run in self.runs]
            if len(set(values)) != TOTAL_RUNS:
                raise ValueError(f"diagnostic campaign repeats {field}")
        payload = self.model_dump(mode="json", exclude={"prereg_sha256"})
        if self.prereg_sha256 != canonical_sha256(payload):
            raise ValueError("diagnostic prereg canonical digest mismatch")
        return self


@dataclass(frozen=True)
class ResolvedTerminalDiagnosticPreregV1:
    path: Path
    file_sha256: str
    raw_bytes: bytes
    prereg: M2CTerminalRegraspDiagnosticPreregV1
    introduced_commit: str


class M2CTerminalDiagnosticConsumptionReceiptV1(StrictModel):
    schema_version: Literal["M2CTerminalDiagnosticConsumptionReceiptV1"]
    event: Literal["CONSUMED_BEFORE_STAGE"]
    campaign_id: Literal["m2c-s4-terminal-regrasp-diagnostic-v1"]
    ledger_namespace: Literal["M2C_S4_TERMINAL_REGRASP_DIAGNOSTIC_V1"]
    ordinal: int = Field(ge=0, lt=TOTAL_RUNS)
    run: TerminalDiagnosticRunV1
    prereg_repository_path: str
    prereg_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_introduced_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    committed_source_snapshot: CommittedSourceSnapshotV1
    source_urdf_sha256: Literal[CONTROLLED_URDF_SHA256]
    upstream_v4_probe_sha256: Literal[UPSTREAM_V4_PROBE_SHA256]
    derived_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_image_id: Literal[ISAAC_IMAGE_ID]
    consumed_at_ns: int = Field(gt=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def receipt_hash_is_exact(self) -> "M2CTerminalDiagnosticConsumptionReceiptV1":
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(payload):
            raise ValueError("diagnostic consumption receipt digest mismatch")
        if self.ordinal != self.run.ordinal:
            raise ValueError("diagnostic consumption ordinal mismatch")
        return self


class M2CTerminalDiagnosticAuthorizationBindingV1(StrictModel):
    schema_version: Literal["M2CTerminalDiagnosticAuthorizationBindingV1"]
    campaign_id: Literal["m2c-s4-terminal-regrasp-diagnostic-v1"]
    condition: Literal[
        "C1_NO_BLOCKER",
        "C2_RETAINED_BLOCKER",
        "C3_FULL_V4",
    ]
    run_id: str
    matched_key: str
    ordinal: int
    scene_seed: int
    failure_seed: int
    probe_mode: Literal["DIRECT_TERMINAL", "FULL_V4_PREAMBLE_TERMINAL"]
    expected_local_blockers: list[str]
    terminal_target_blocker_surface_gap_m: float | None
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_urdf_sha256: Literal[CONTROLLED_URDF_SHA256]
    upstream_v4_probe_sha256: Literal[UPSTREAM_V4_PROBE_SHA256]
    derived_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_image_id: Literal[ISAAC_IMAGE_ID]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class M2CTerminalRegraspDiagnosticRawV1(StrictModel):
    schema_version: Literal["M2CTerminalRegraspDiagnosticRawV1"]
    authorization: M2CTerminalDiagnosticAuthorizationBindingV1
    run_id: str
    matched_key: str
    scene_seed: int = Field(gt=0)
    failure_seed: int = Field(gt=0)
    condition: Literal[
        "C1_NO_BLOCKER",
        "C2_RETAINED_BLOCKER",
        "C3_FULL_V4",
    ]
    terminal_measurement_valid: bool
    terminal_execution_status: Literal[
        "LIFTED",
        "PREGRASP_IK_GATE_REJECTED",
        "CONTACT_GATE_REJECTED",
        "NO_TERMINAL_ATTEMPT",
    ]
    pregrasp_ik_passed: bool
    contact_gate_passed: bool
    selected_free_gap_yaw_rad: float | None
    terminal_target_blocker_surface_gap_m: float | None
    public_predicates: list[str]
    terminal_success: bool
    physical_action_executed: bool
    collision_or_safety_violations: int = Field(ge=0)
    public_capture_evidence: list[dict[str, Any]]
    terminal_regrasp_execution: dict[str, Any] | None
    actuation_probe_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]

    @model_validator(mode="after")
    def raw_projection_is_exact(self) -> "M2CTerminalRegraspDiagnosticRawV1":
        auth = self.authorization
        if (
            self.run_id != auth.run_id
            or self.matched_key != auth.matched_key
            or self.scene_seed != auth.scene_seed
            or self.failure_seed != auth.failure_seed
            or self.condition != auth.condition
            or self.actuation_probe_source_sha256 != auth.derived_probe_sha256
        ):
            raise ValueError("diagnostic raw identity differs from its authorization")
        expected_valid = self.terminal_regrasp_execution is not None
        if self.terminal_measurement_valid is not expected_valid:
            raise ValueError("diagnostic terminal-valid projection mismatch")
        if self.terminal_execution_status == "NO_TERMINAL_ATTEMPT" and expected_valid:
            raise ValueError("diagnostic no-terminal status carries execution evidence")
        if self.terminal_execution_status != "NO_TERMINAL_ATTEMPT" and not expected_valid:
            raise ValueError("diagnostic terminal status lacks execution evidence")
        expected_success = (
            self.terminal_execution_status == "LIFTED"
            and {"grasped=true", "lifted=true"}.issubset(self.public_predicates)
            and self.collision_or_safety_violations == 0
        )
        if self.terminal_success is not expected_success:
            raise ValueError("diagnostic raw terminal-success projection mismatch")
        if self.pregrasp_ik_passed is not (
            self.terminal_execution_status
            not in {"PREGRASP_IK_GATE_REJECTED", "NO_TERMINAL_ATTEMPT"}
        ):
            raise ValueError("diagnostic raw pregrasp projection mismatch")
        if self.contact_gate_passed is not (self.terminal_execution_status == "LIFTED"):
            raise ValueError("diagnostic raw contact projection mismatch")
        expected_gap = auth.terminal_target_blocker_surface_gap_m
        if expected_gap is None:
            if self.terminal_target_blocker_surface_gap_m is not None:
                raise ValueError("diagnostic C1 raw must have no blocker gap")
        elif self.terminal_target_blocker_surface_gap_m is None or not math.isclose(
            self.terminal_target_blocker_surface_gap_m,
            expected_gap,
            abs_tol=1e-12,
        ):
            raise ValueError("diagnostic raw blocker gap changed")
        return self


class M2CTerminalDiagnosticAttemptV1(StrictModel):
    schema_version: Literal["M2CTerminalDiagnosticAttemptV1"]
    run_id: str
    ordinal: int
    condition: Literal[
        "C1_NO_BLOCKER",
        "C2_RETAINED_BLOCKER",
        "C3_FULL_V4",
    ]
    terminal_measurement_valid: Literal[True]
    terminal_execution_status: Literal[
        "LIFTED",
        "PREGRASP_IK_GATE_REJECTED",
        "CONTACT_GATE_REJECTED",
        "NO_TERMINAL_ATTEMPT",
    ]
    pregrasp_ik_passed: bool
    contact_gate_passed: bool
    selected_free_gap_yaw_rad: float | None
    terminal_target_blocker_surface_gap_m: float | None
    public_predicates: list[str]
    terminal_success: bool
    physical_action_executed: bool
    collision_or_safety_violations: int = Field(ge=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    raw_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def success_is_exact(self) -> "M2CTerminalDiagnosticAttemptV1":
        expected = (
            self.terminal_execution_status == "LIFTED"
            and {"grasped=true", "lifted=true"}.issubset(self.public_predicates)
            and self.collision_or_safety_violations == 0
        )
        if self.terminal_success is not expected:
            raise ValueError("diagnostic terminal success predicate mismatch")
        if self.pregrasp_ik_passed is not (
            self.terminal_execution_status
            not in {"PREGRASP_IK_GATE_REJECTED", "NO_TERMINAL_ATTEMPT"}
        ):
            raise ValueError("diagnostic pregrasp IK projection mismatch")
        if self.contact_gate_passed is not (self.terminal_execution_status == "LIFTED"):
            raise ValueError("diagnostic contact-gate projection mismatch")
        return self


class M2CTerminalDiagnosticDecisionV1(StrictModel):
    schema_version: Literal["M2CTerminalDiagnosticDecisionV1"]
    status: Literal["COMPLETE"]
    selected_branch: Literal["R1", "R2", "R3"]
    successes_by_condition: dict[str, int]
    failures_by_condition: dict[str, int]
    rates_by_condition: dict[str, float]
    exact_run_count: Literal[TOTAL_RUNS]


def _git(project_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise TerminalDiagnosticError(
            f"git {' '.join(args)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise TerminalDiagnosticError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                TerminalDiagnosticError(f"{label} contains non-finite number {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerminalDiagnosticError(f"{label} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise TerminalDiagnosticError(f"{label} is not a JSON object")
    return payload


def parse_diagnostic_raw_bytes(raw: bytes) -> M2CTerminalRegraspDiagnosticRawV1:
    return M2CTerminalRegraspDiagnosticRawV1.model_validate(
        _json_object(raw, label="terminal diagnostic raw evidence")
    )


def load_committed_diagnostic_prereg(
    *,
    project_root: Path,
    prereg_path: Path,
) -> ResolvedTerminalDiagnosticPreregV1:
    root = project_root.resolve(strict=True)
    path = prereg_path.resolve(strict=True)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise TerminalDiagnosticError("diagnostic prereg escapes project root") from error
    raw = read_regular_file_once(path)
    prereg = M2CTerminalRegraspDiagnosticPreregV1.model_validate(
        _json_object(raw, label="terminal diagnostic prereg")
    )
    if relative != prereg.repository_relative_path:
        raise TerminalDiagnosticError("diagnostic prereg repository path mismatch")
    if _git(root, "show", f"HEAD:{relative}") != raw:
        raise TerminalDiagnosticError("diagnostic prereg is not exact current HEAD bytes")
    lines = (
        _git(root, "log", "--diff-filter=A", "--format=%H", "--", relative).decode().splitlines()
    )
    if len(lines) != 1:
        raise TerminalDiagnosticError("diagnostic prereg introduction is not unique")
    introduced = lines[0]
    if _git(root, "show", f"{introduced}:{relative}") != raw:
        raise TerminalDiagnosticError("diagnostic prereg differs from introduction bytes")
    changed = set(
        _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", introduced)
        .decode()
        .splitlines()
    )
    if changed != {relative}:
        raise TerminalDiagnosticError("diagnostic prereg introduction commit is not single-purpose")
    adr = read_regular_file_once(root / ADR_PATH)
    if (
        sha256_bytes(adr) != ADR_SHA256
        or _git(root, "show", f"{ADR_INTRODUCED_COMMIT}:{ADR_PATH}") != adr
    ):
        raise TerminalDiagnosticError("accepted ADR-0026 bytes or commit binding changed")
    exclusion_payloads: list[dict[str, Any]] = []
    for binding in prereg.implementation_bindings + prereg.exclusion_sources:
        current = read_regular_file_once(root / binding.path)
        committed = _git(root, "show", f"{prereg.implementation_commit}:{binding.path}")
        if current != committed or sha256_bytes(current) != binding.sha256:
            raise TerminalDiagnosticError(f"diagnostic source binding changed: {binding.path}")
        if binding in prereg.exclusion_sources:
            exclusion_payloads.append(_json_object(current, label=binding.path))
    if (
        _git(
            root,
            "merge-base",
            "--is-ancestor",
            prereg.implementation_commit,
            introduced,
        ).strip()
        != b""
    ):
        raise TerminalDiagnosticError("diagnostic implementation commit is not prereg ancestor")
    axes: dict[str, set[Any]] = {
        "scene_seed": set(),
        "failure_seed": set(),
        "matched_key": set(),
    }
    for payload in exclusion_payloads:
        for record in _walk_mappings(payload):
            for axis in axes:
                value = record.get(axis)
                if value is not None:
                    axes[axis].add(int(value) if axis != "matched_key" else str(value))
    if any(
        not values for values in axes.values()
    ) or prereg.external_identity_digest != canonical_sha256(
        {axis: sorted(values) for axis, values in axes.items()}
    ):
        raise TerminalDiagnosticError("diagnostic external identity inventory changed")
    for run in prereg.runs:
        if any(getattr(run, axis) in values for axis, values in axes.items()):
            raise TerminalDiagnosticError("diagnostic identity overlaps frozen external inventory")
    return ResolvedTerminalDiagnosticPreregV1(
        path=path,
        file_sha256=sha256_bytes(raw),
        raw_bytes=raw,
        prereg=prereg,
        introduced_commit=introduced,
    )


def _write_create_only(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise TerminalDiagnosticError("short diagnostic receipt write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _secure_ledger_root(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise TerminalDiagnosticError("diagnostic ledger root must be owned 0700 directory")


@contextmanager
def _ledger_lock(path: Path):
    lock_path = path / ".diagnostic-ledger.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise TerminalDiagnosticError("diagnostic ledger lock metadata is unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _read_existing_claims(
    *,
    ledger_root: Path,
    prereg: M2CTerminalRegraspDiagnosticPreregV1,
    expected_count: int,
) -> list[M2CTerminalDiagnosticConsumptionReceiptV1]:
    names = sorted(path.name for path in ledger_root.glob("claim-*.json"))
    expected_names = [f"claim-{ordinal:02d}.json" for ordinal in range(expected_count)]
    if names != expected_names:
        raise TerminalDiagnosticError("diagnostic claims are not consumed in frozen order")
    claims: list[M2CTerminalDiagnosticConsumptionReceiptV1] = []
    for ordinal, name in enumerate(names):
        raw = read_regular_file_once(ledger_root / name)
        claim = M2CTerminalDiagnosticConsumptionReceiptV1.model_validate(
            _json_object(raw, label=f"diagnostic claim {name}")
        )
        if claim.ordinal != ordinal or claim.run != prereg.runs[ordinal]:
            raise TerminalDiagnosticError("diagnostic ledger prefix differs from preregistration")
        claims.append(claim)
    return claims


def consume_diagnostic_run(
    *,
    resolved: ResolvedTerminalDiagnosticPreregV1,
    run_id: str,
    ledger_root: Path,
    derived_probe_sha256: str,
    consumed_at_ns: int,
) -> Path:
    prereg = resolved.prereg
    if str(ledger_root.resolve(strict=True)) != prereg.ledger_root:
        raise TerminalDiagnosticError("diagnostic ledger root differs from preregistration")
    _secure_ledger_root(ledger_root)
    selected = [run for run in prereg.runs if run.run_id == run_id]
    if len(selected) != 1:
        raise TerminalDiagnosticError("diagnostic run is not uniquely preregistered")
    run = selected[0]
    with _ledger_lock(ledger_root):
        _read_existing_claims(
            ledger_root=ledger_root,
            prereg=prereg,
            expected_count=run.ordinal,
        )
        payload: dict[str, Any] = {
            "schema_version": "M2CTerminalDiagnosticConsumptionReceiptV1",
            "event": "CONSUMED_BEFORE_STAGE",
            "campaign_id": prereg.campaign_id,
            "ledger_namespace": prereg.ledger_namespace,
            "ordinal": run.ordinal,
            "run": run.model_dump(mode="json"),
            "prereg_repository_path": prereg.repository_relative_path,
            "prereg_file_sha256": resolved.file_sha256,
            "prereg_sha256": prereg.prereg_sha256,
            "prereg_introduced_commit": resolved.introduced_commit,
            "committed_source_snapshot": prereg.committed_source_snapshot.model_dump(mode="json"),
            "source_urdf_sha256": CONTROLLED_URDF_SHA256,
            "upstream_v4_probe_sha256": UPSTREAM_V4_PROBE_SHA256,
            "derived_probe_sha256": derived_probe_sha256,
            "container_image_id": ISAAC_IMAGE_ID,
            "consumed_at_ns": consumed_at_ns,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        payload["receipt_sha256"] = canonical_sha256(payload)
        receipt = M2CTerminalDiagnosticConsumptionReceiptV1.model_validate(payload)
        path = ledger_root / f"claim-{run.ordinal:02d}.json"
        _write_create_only(path, canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n")
    return path


def bind_diagnostic_claim_to_raw_session(
    *,
    claim_path: Path,
    source_snapshot_root: Path,
    run_id: str,
    scene_seed: int,
    failure_seed: int,
    condition: str,
    source_sdf_sha256: str,
    source_supervision_sha256: str,
    source_urdf_sha256: str,
    upstream_v4_probe_sha256: str,
    derived_probe_sha256: str,
    container_image_id: str,
) -> M2CTerminalDiagnosticAuthorizationBindingV1:
    claim = M2CTerminalDiagnosticConsumptionReceiptV1.model_validate(
        _json_object(read_regular_file_once(claim_path), label="diagnostic claim")
    )
    run = claim.run
    expected = (
        run.run_id,
        run.scene_seed,
        run.failure_seed,
        run.condition,
        run.sdf_sha256,
        run.supervision_sha256,
        claim.source_urdf_sha256,
        claim.upstream_v4_probe_sha256,
        claim.derived_probe_sha256,
        claim.container_image_id,
    )
    actual = (
        run_id,
        scene_seed,
        failure_seed,
        condition,
        source_sdf_sha256,
        source_supervision_sha256,
        source_urdf_sha256,
        upstream_v4_probe_sha256,
        derived_probe_sha256,
        container_image_id,
    )
    if actual != expected:
        raise TerminalDiagnosticError("diagnostic probe inputs differ from consumed claim")
    verify_materialized_source_snapshot(
        source_snapshot_root,
        claim.committed_source_snapshot,
        require_content_addressed_name=False,
        allow_root_owned_read_only_mount=True,
    )
    return M2CTerminalDiagnosticAuthorizationBindingV1(
        schema_version="M2CTerminalDiagnosticAuthorizationBindingV1",
        campaign_id=claim.campaign_id,
        condition=run.condition,
        run_id=run.run_id,
        matched_key=run.matched_key,
        ordinal=run.ordinal,
        scene_seed=run.scene_seed,
        failure_seed=run.failure_seed,
        probe_mode=run.probe_mode,
        expected_local_blockers=run.expected_local_blockers,
        terminal_target_blocker_surface_gap_m=run.terminal_target_blocker_surface_gap_m,
        consumption_receipt_sha256=claim.receipt_sha256,
        prereg_sha256=claim.prereg_sha256,
        source_sdf_sha256=run.sdf_sha256,
        source_supervision_sha256=run.supervision_sha256,
        source_urdf_sha256=claim.source_urdf_sha256,
        upstream_v4_probe_sha256=claim.upstream_v4_probe_sha256,
        derived_probe_sha256=claim.derived_probe_sha256,
        container_image_id=claim.container_image_id,
        teacher_used=False,
        privileged_truth_policy_input=False,
    )


def _remove_dynamic_model(root: ET.Element, name: str) -> None:
    world = root.find("world")
    if world is None:
        raise TerminalDiagnosticError("diagnostic SDF has no world")
    models = [model for model in world.findall("model") if model.get("name") == name]
    if len(models) != 1:
        raise TerminalDiagnosticError(f"diagnostic SDF does not uniquely contain {name}")
    world.remove(models[0])


def materialize_diagnostic_scene(
    *,
    full_v4_sdf_bytes: bytes,
    full_v4_supervision_bytes: bytes,
    scene_seed: int,
    source_base_seed: int,
    condition: str,
) -> tuple[bytes, bytes]:
    if condition not in DIAGNOSTIC_CONDITIONS:
        raise TerminalDiagnosticError("unknown diagnostic condition")
    root = ET.fromstring(full_v4_sdf_bytes)
    removed = {
        "C1_NO_BLOCKER": (SCRIPTED_BLOCKER_ENTITY, RETAINED_BLOCKER_ENTITY),
        "C2_RETAINED_BLOCKER": (SCRIPTED_BLOCKER_ENTITY,),
        "C3_FULL_V4": (),
    }[condition]
    for name in removed:
        _remove_dynamic_model(root, name)
    ET.indent(root, space="  ")
    sdf_bytes = (ET.tostring(root, encoding="unicode") + "\n").encode()
    supervision = _json_object(full_v4_supervision_bytes, label="full V4 supervision")
    objects = supervision.get("simulator_supervision", {}).get("objects")
    if not isinstance(objects, list):
        raise TerminalDiagnosticError("diagnostic supervision lacks objects")
    supervision["simulator_supervision"]["objects"] = [
        item for item in objects if item.get("actual_sim_entity_id") not in removed
    ]
    supervision["seed"] = scene_seed
    supervision["part_count"] = len(supervision["simulator_supervision"]["objects"])
    supervision["m2c_terminal_regrasp_diagnostic"] = {
        "schema_version": "M2CTerminalRegraspSceneV1",
        "condition": condition,
        "source_base_seed": source_base_seed,
        "scene_seed": scene_seed,
        "anchor_xy_m": list(FIXED_ANCHOR_XY_M),
        "removed_local_blockers": list(removed),
        "terminal_target_blocker_surface_gap_m": (
            None if condition == "C1_NO_BLOCKER" else RETAINED_BLOCKER_SURFACE_GAP_M
        ),
        "outcome_observed_during_materialization": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    supervision_bytes = (
        json.dumps(supervision, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    return sdf_bytes, supervision_bytes


def evaluate_preregistered_decision_tree(
    *,
    prereg: M2CTerminalRegraspDiagnosticPreregV1,
    attempts: Sequence[M2CTerminalDiagnosticAttemptV1],
) -> M2CTerminalDiagnosticDecisionV1:
    if len(attempts) != TOTAL_RUNS:
        raise TerminalDiagnosticError("diagnostic decision requires exactly 36 attempts")
    by_id = {attempt.run_id: attempt for attempt in attempts}
    if len(by_id) != TOTAL_RUNS or set(by_id) != {run.run_id for run in prereg.runs}:
        raise TerminalDiagnosticError("diagnostic attempts do not exactly cover preregistration")
    for run in prereg.runs:
        attempt = by_id[run.run_id]
        if attempt.ordinal != run.ordinal or attempt.condition != run.condition:
            raise TerminalDiagnosticError(
                "diagnostic attempt identity differs from preregistration"
            )
        expected_gap = run.terminal_target_blocker_surface_gap_m
        actual_gap = attempt.terminal_target_blocker_surface_gap_m
        if expected_gap is None:
            if actual_gap is not None:
                raise TerminalDiagnosticError("diagnostic C1 gap projection changed")
        elif actual_gap is None or not math.isclose(actual_gap, expected_gap, abs_tol=1e-12):
            raise TerminalDiagnosticError("diagnostic gap differs from preregistration")
    successes = Counter(attempt.condition for attempt in attempts if attempt.terminal_success)
    successes_by_condition = {
        condition: successes[condition] for condition in DIAGNOSTIC_CONDITIONS
    }
    failures_by_condition = {
        condition: RUNS_PER_CONDITION - successes_by_condition[condition]
        for condition in DIAGNOSTIC_CONDITIONS
    }
    c1_successes = successes_by_condition["C1_NO_BLOCKER"]
    c3_successes = successes_by_condition["C3_FULL_V4"]
    if c1_successes >= 9 and c3_successes <= 3:
        branch = "R1"
    elif failures_by_condition["C1_NO_BLOCKER"] >= 6:
        branch = "R2"
    else:
        branch = "R3"
    return M2CTerminalDiagnosticDecisionV1(
        schema_version="M2CTerminalDiagnosticDecisionV1",
        status="COMPLETE",
        selected_branch=branch,
        successes_by_condition=successes_by_condition,
        failures_by_condition=failures_by_condition,
        rates_by_condition={
            condition: successes_by_condition[condition] / RUNS_PER_CONDITION
            for condition in DIAGNOSTIC_CONDITIONS
        },
        exact_run_count=TOTAL_RUNS,
    )


def external_identity_tuple(record: Mapping[str, Any]) -> tuple[int | None, int | None, str | None]:
    """Return the three identity axes used by the disjointness audit."""

    return (
        int(record["scene_seed"]) if record.get("scene_seed") is not None else None,
        int(record["failure_seed"]) if record.get("failure_seed") is not None else None,
        str(record["matched_key"]) if record.get("matched_key") is not None else None,
    )


def _walk_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)
