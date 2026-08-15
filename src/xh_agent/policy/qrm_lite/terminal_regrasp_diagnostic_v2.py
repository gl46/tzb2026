"""Corrected, six-object ADR-0026 terminal-regrasp diagnostic contract.

V1 removed one or two local blockers and was rejected by the unchanged M1B
six-object scene schema before Kit started.  V2 preserves all six canonical
objects and parks only the condition-excluded blockers at frozen distant
locations.  The V1 claim and its pre-action failure remain immutable; V2 uses
an entirely fresh identity set and an independent create-only ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Literal, Sequence
import xml.etree.ElementTree as ET

from pydantic import Field, model_validator

from xh_agent.policy.qrm_lite.contracts import StrictModel
from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    CommittedSourceSnapshotV1,
    read_regular_file_once,
    verify_materialized_source_snapshot,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ADR_INTRODUCED_COMMIT,
    ADR_PATH,
    ADR_SHA256,
    CONTROLLED_URDF_SHA256,
    DIAGNOSTIC_CONDITIONS,
    FIXED_ANCHOR_XY_M,
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    M2CTerminalDiagnosticAttemptV1,
    RETAINED_BLOCKER_ENTITY,
    RETAINED_BLOCKER_SURFACE_GAP_M,
    RUNS_PER_CONDITION,
    SCRIPTED_BLOCKER_ENTITY,
    TOTAL_RUNS,
    TerminalDiagnosticDecisionTreeV1,
    TerminalDiagnosticError,
    TerminalDiagnosticRunV1,
    _git,
    _json_object,
    _ledger_lock,
    _secure_ledger_root,
    _walk_mappings,
    _write_create_only,
    canonical_sha256,
    evaluate_preregistered_decision_tree,
    sha256_bytes,
)


CAMPAIGN_ID = "m2c-s4-terminal-regrasp-diagnostic-v2"
PREREG_REPOSITORY_PATH = "docs/decisions/M2C-S4-TERMINAL-REGRASP-DIAGNOSTIC-V2-PREREG.json"
LEDGER_NAMESPACE = "M2C_S4_TERMINAL_REGRASP_DIAGNOSTIC_V2"
V1_PREREG_PATH = "docs/decisions/M2C-S4-TERMINAL-REGRASP-DIAGNOSTIC-PREREG.json"
V1_INCOMPLETE_REPORT_PATH = "reports/m2c-s4-terminal-regrasp-diagnostic-adr0026.json"
UPSTREAM_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"

# Both positions are members of the frozen industrial scene lattice, remain
# far from the terminal anchor, and are distinct from the three V4 distractor
# positions.  They are not policy inputs and are fixed before all V2 outcomes.
PARKING_XY_M: dict[str, tuple[float, float]] = {
    SCRIPTED_BLOCKER_ENTITY: (-0.53, 0.34),
    RETAINED_BLOCKER_ENTITY: (-0.25, 0.34),
}

IMPLEMENTATION_PATHS = (
    "scripts/generate_industrial_scenes.py",
    "scripts/isaac_m1b_actuation_probe.py",
    "scripts/isaac_m1b_dataset_benchmark.py",
    "scripts/m2c/s4_scene_family.py",
    "scripts/m2c/build_terminal_regrasp_diagnostic_prereg_v2.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe_v2.py",
    "scripts/m2c/materialize_terminal_regrasp_diagnostic_scenes_v2.py",
    "scripts/m2c/run_terminal_regrasp_diagnostic.py",
    "scripts/m2c/run_terminal_regrasp_diagnostic_v2.py",
    "scripts/m2c/audit_terminal_regrasp_diagnostic_v2.py",
    "src/xh_agent/data/isaac_m1b.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v1.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v2.py",
)

EXCLUSION_PATHS = (
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
    V1_PREREG_PATH,
    V1_INCOMPLETE_REPORT_PATH,
)


class BoundRepositoryFileV2(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class V1InvalidationV2(StrictModel):
    preregistration: BoundRepositoryFileV2
    incomplete_audit: BoundRepositoryFileV2
    valid_terminal_measurements: Literal[0]
    probe_launched: Literal[False]
    physical_action_outcome: Literal["NOT_AVAILABLE"]
    failed_before_kit: Literal[True]
    v1_claim_reused: Literal[False]
    v1_identity_reused: Literal[False]


class M2CTerminalRegraspDiagnosticPreregV2(StrictModel):
    schema_version: Literal["M2CTerminalRegraspDiagnosticPreregV2"]
    status: Literal["FROZEN_AFTER_V1_PRE_ACTION_INVALIDATION_BEFORE_ANY_VALID_DIAGNOSTIC_OUTCOME"]
    repository_relative_path: Literal[PREREG_REPOSITORY_PATH]
    introduction_commit_paths: list[str] = Field(min_length=1, max_length=1)
    campaign_id: Literal[CAMPAIGN_ID]
    governing_adr: dict[str, Any]
    written_date_asia_shanghai: Literal["2026-08-15"]
    diagnostic_outcomes_observed_before_freeze: Literal[False]
    v1_pre_action_infrastructure_failure_observed: Literal[True]
    v1_invalidation: V1InvalidationV2
    restart_basis: Literal["NEW_CAMPAIGN_ALL_FRESH_IDENTITIES_NO_V1_CLAIM_OR_IDENTITY_REUSE"]
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
    unchanged_six_object_schema: Literal[True]
    excluded_blockers_are_parked_not_removed: Literal[True]
    no_gate_threshold_b0_or_predicate_change: Literal[True]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    container_image: Literal[ISAAC_IMAGE]
    container_image_id: Literal[ISAAC_IMAGE_ID]
    upstream_v4_probe_sha256: Literal[UPSTREAM_V4_PROBE_SHA256]
    controlled_urdf_sha256: Literal[CONTROLLED_URDF_SHA256]
    ledger_root: str
    ledger_namespace: Literal[LEDGER_NAMESPACE]
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    committed_source_snapshot: CommittedSourceSnapshotV1
    implementation_bindings: list[BoundRepositoryFileV2]
    exclusion_sources: list[BoundRepositoryFileV2]
    external_identity_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parking_xy_m: dict[str, list[float]]
    runs: list[TerminalDiagnosticRunV1] = Field(
        min_length=TOTAL_RUNS,
        max_length=TOTAL_RUNS,
    )
    decision_tree: TerminalDiagnosticDecisionTreeV1
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def campaign_is_exact(self) -> "M2CTerminalRegraspDiagnosticPreregV2":
        if self.introduction_commit_paths != [self.repository_relative_path]:
            raise ValueError("V2 diagnostic introduction path is not singleton-exact")
        if self.governing_adr != {
            "path": ADR_PATH,
            "sha256": ADR_SHA256,
            "introduced_commit": ADR_INTRODUCED_COMMIT,
            "status": "ACCEPTED_HUMAN_ADR",
        }:
            raise ValueError("V2 diagnostic governing ADR binding changed")
        if [item.path for item in self.implementation_bindings] != list(IMPLEMENTATION_PATHS):
            raise ValueError("V2 diagnostic implementation closure is not exact")
        if [item.path for item in self.exclusion_sources] != list(EXCLUSION_PATHS):
            raise ValueError("V2 diagnostic exclusion inventory is not exact")
        if self.committed_source_snapshot.commit != self.implementation_commit:
            raise ValueError("V2 diagnostic source snapshot differs from implementation")
        expected_parking = {key: list(value) for key, value in PARKING_XY_M.items()}
        if self.parking_xy_m != expected_parking:
            raise ValueError("V2 diagnostic parking geometry changed")
        if [run.ordinal for run in self.runs] != list(range(TOTAL_RUNS)):
            raise ValueError("V2 diagnostic run order is not exact")
        expected_conditions = [
            condition for _ in range(RUNS_PER_CONDITION) for condition in DIAGNOSTIC_CONDITIONS
        ]
        if [run.condition for run in self.runs] != expected_conditions:
            raise ValueError("V2 diagnostic paired condition order changed")
        grouped: dict[int, list[TerminalDiagnosticRunV1]] = {}
        for run in self.runs:
            grouped.setdefault(run.source_base_seed, []).append(run)
        if len(grouped) != RUNS_PER_CONDITION or any(
            [run.condition for run in group] != list(DIAGNOSTIC_CONDITIONS)
            for group in grouped.values()
        ):
            raise ValueError("V2 diagnostic source-seed pairing changed")
        for field in ("scene_seed", "failure_seed", "run_id", "matched_key"):
            values = [getattr(run, field) for run in self.runs]
            if len(set(values)) != TOTAL_RUNS:
                raise ValueError(f"V2 diagnostic campaign repeats {field}")
        payload = self.model_dump(mode="json", exclude={"prereg_sha256"})
        if self.prereg_sha256 != canonical_sha256(payload):
            raise ValueError("V2 diagnostic prereg canonical digest mismatch")
        return self


@dataclass(frozen=True)
class ResolvedTerminalDiagnosticPreregV2:
    path: Path
    file_sha256: str
    raw_bytes: bytes
    prereg: M2CTerminalRegraspDiagnosticPreregV2
    introduced_commit: str


class M2CTerminalDiagnosticConsumptionReceiptV2(StrictModel):
    schema_version: Literal["M2CTerminalDiagnosticConsumptionReceiptV2"]
    event: Literal["CONSUMED_BEFORE_STAGE"]
    campaign_id: Literal[CAMPAIGN_ID]
    ledger_namespace: Literal[LEDGER_NAMESPACE]
    ordinal: int = Field(ge=0, lt=TOTAL_RUNS)
    run: TerminalDiagnosticRunV1
    prereg_repository_path: Literal[PREREG_REPOSITORY_PATH]
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
    def receipt_hash_is_exact(self) -> "M2CTerminalDiagnosticConsumptionReceiptV2":
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(payload):
            raise ValueError("V2 diagnostic consumption digest mismatch")
        if self.ordinal != self.run.ordinal:
            raise ValueError("V2 diagnostic consumption ordinal mismatch")
        return self


class M2CTerminalDiagnosticAuthorizationBindingV2(StrictModel):
    schema_version: Literal["M2CTerminalDiagnosticAuthorizationBindingV2"]
    campaign_id: Literal[CAMPAIGN_ID]
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


class M2CTerminalRegraspDiagnosticRawV2(StrictModel):
    schema_version: Literal["M2CTerminalRegraspDiagnosticRawV2"]
    authorization: M2CTerminalDiagnosticAuthorizationBindingV2
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
    def raw_projection_is_exact(self) -> "M2CTerminalRegraspDiagnosticRawV2":
        auth = self.authorization
        if (
            self.run_id != auth.run_id
            or self.matched_key != auth.matched_key
            or self.scene_seed != auth.scene_seed
            or self.failure_seed != auth.failure_seed
            or self.condition != auth.condition
            or self.actuation_probe_source_sha256 != auth.derived_probe_sha256
        ):
            raise ValueError("V2 diagnostic raw identity differs from authorization")
        valid = self.terminal_regrasp_execution is not None
        if self.terminal_measurement_valid is not valid:
            raise ValueError("V2 diagnostic terminal-valid projection mismatch")
        if (self.terminal_execution_status == "NO_TERMINAL_ATTEMPT") is valid:
            raise ValueError("V2 diagnostic terminal status/evidence mismatch")
        success = (
            self.terminal_execution_status == "LIFTED"
            and {"grasped=true", "lifted=true"}.issubset(self.public_predicates)
            and self.collision_or_safety_violations == 0
        )
        if self.terminal_success is not success:
            raise ValueError("V2 diagnostic terminal-success projection mismatch")
        if self.pregrasp_ik_passed is not (
            self.terminal_execution_status
            not in {"PREGRASP_IK_GATE_REJECTED", "NO_TERMINAL_ATTEMPT"}
        ):
            raise ValueError("V2 diagnostic pregrasp projection mismatch")
        if self.contact_gate_passed is not (self.terminal_execution_status == "LIFTED"):
            raise ValueError("V2 diagnostic contact projection mismatch")
        gap = auth.terminal_target_blocker_surface_gap_m
        if gap is None:
            if self.terminal_target_blocker_surface_gap_m is not None:
                raise ValueError("V2 diagnostic C1 raw must have no blocker gap")
        elif self.terminal_target_blocker_surface_gap_m is None or not math.isclose(
            self.terminal_target_blocker_surface_gap_m,
            gap,
            abs_tol=1e-12,
        ):
            raise ValueError("V2 diagnostic raw blocker gap changed")
        return self


def parse_diagnostic_raw_bytes_v2(raw: bytes) -> M2CTerminalRegraspDiagnosticRawV2:
    return M2CTerminalRegraspDiagnosticRawV2.model_validate(
        _json_object(raw, label="V2 terminal diagnostic raw evidence")
    )


def load_committed_diagnostic_prereg_v2(
    *, project_root: Path, prereg_path: Path
) -> ResolvedTerminalDiagnosticPreregV2:
    root = project_root.resolve(strict=True)
    path = prereg_path.resolve(strict=True)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise TerminalDiagnosticError("V2 diagnostic prereg escapes project root") from error
    raw = read_regular_file_once(path)
    prereg = M2CTerminalRegraspDiagnosticPreregV2.model_validate(
        _json_object(raw, label="V2 terminal diagnostic prereg")
    )
    if relative != prereg.repository_relative_path:
        raise TerminalDiagnosticError("V2 diagnostic repository path mismatch")
    if _git(root, "show", f"HEAD:{relative}") != raw:
        raise TerminalDiagnosticError("V2 diagnostic prereg is not current HEAD bytes")
    introduced = (
        _git(root, "log", "--diff-filter=A", "--format=%H", "--", relative).decode().splitlines()
    )
    if len(introduced) != 1 or _git(root, "show", f"{introduced[0]}:{relative}") != raw:
        raise TerminalDiagnosticError("V2 diagnostic introduction binding changed")
    changed = set(
        _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", introduced[0])
        .decode()
        .splitlines()
    )
    if changed != {relative}:
        raise TerminalDiagnosticError("V2 diagnostic prereg commit is not single-purpose")
    adr = read_regular_file_once(root / ADR_PATH)
    if (
        sha256_bytes(adr) != ADR_SHA256
        or _git(root, "show", f"{ADR_INTRODUCED_COMMIT}:{ADR_PATH}") != adr
    ):
        raise TerminalDiagnosticError("accepted ADR-0026 binding changed")
    external_payloads: list[dict[str, Any]] = []
    for binding in prereg.implementation_bindings + prereg.exclusion_sources:
        current = read_regular_file_once(root / binding.path)
        committed = _git(root, "show", f"{prereg.implementation_commit}:{binding.path}")
        if current != committed or sha256_bytes(current) != binding.sha256:
            raise TerminalDiagnosticError(f"V2 source binding changed: {binding.path}")
        if binding in prereg.exclusion_sources:
            external_payloads.append(_json_object(current, label=binding.path))
    if _git(
        root,
        "merge-base",
        "--is-ancestor",
        prereg.implementation_commit,
        introduced[0],
    ).strip():
        raise TerminalDiagnosticError("V2 implementation is not a prereg ancestor")
    axes: dict[str, set[Any]] = {
        "scene_seed": set(),
        "failure_seed": set(),
        "matched_key": set(),
    }
    for payload in external_payloads:
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
        raise TerminalDiagnosticError("V2 external identity inventory changed")
    for run in prereg.runs:
        if any(getattr(run, axis) in values for axis, values in axes.items()):
            raise TerminalDiagnosticError("V2 identity overlaps frozen external inventory")
    return ResolvedTerminalDiagnosticPreregV2(
        path=path,
        file_sha256=sha256_bytes(raw),
        raw_bytes=raw,
        prereg=prereg,
        introduced_commit=introduced[0],
    )


def _read_existing_claims_v2(
    *,
    ledger_root: Path,
    prereg: M2CTerminalRegraspDiagnosticPreregV2,
    expected_count: int,
) -> list[M2CTerminalDiagnosticConsumptionReceiptV2]:
    names = sorted(path.name for path in ledger_root.glob("claim-*.json"))
    expected = [f"claim-{ordinal:02d}.json" for ordinal in range(expected_count)]
    if names != expected:
        raise TerminalDiagnosticError("V2 diagnostic claims are not in frozen order")
    claims: list[M2CTerminalDiagnosticConsumptionReceiptV2] = []
    for ordinal, name in enumerate(names):
        claim = M2CTerminalDiagnosticConsumptionReceiptV2.model_validate(
            _json_object(
                read_regular_file_once(ledger_root / name),
                label=f"V2 diagnostic claim {name}",
            )
        )
        if claim.ordinal != ordinal or claim.run != prereg.runs[ordinal]:
            raise TerminalDiagnosticError("V2 diagnostic ledger prefix changed")
        claims.append(claim)
    return claims


def consume_diagnostic_run_v2(
    *,
    resolved: ResolvedTerminalDiagnosticPreregV2,
    run_id: str,
    ledger_root: Path,
    derived_probe_sha256: str,
    consumed_at_ns: int,
) -> Path:
    prereg = resolved.prereg
    if str(ledger_root.resolve(strict=True)) != prereg.ledger_root:
        raise TerminalDiagnosticError("V2 diagnostic ledger root differs from prereg")
    _secure_ledger_root(ledger_root)
    selected = [run for run in prereg.runs if run.run_id == run_id]
    if len(selected) != 1:
        raise TerminalDiagnosticError("V2 diagnostic run is not uniquely preregistered")
    run = selected[0]
    with _ledger_lock(ledger_root):
        _read_existing_claims_v2(
            ledger_root=ledger_root,
            prereg=prereg,
            expected_count=run.ordinal,
        )
        payload: dict[str, Any] = {
            "schema_version": "M2CTerminalDiagnosticConsumptionReceiptV2",
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
        receipt = M2CTerminalDiagnosticConsumptionReceiptV2.model_validate(payload)
        path = ledger_root / f"claim-{run.ordinal:02d}.json"
        _write_create_only(
            path,
            json.dumps(
                receipt.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
            + b"\n",
        )
    return path


def bind_diagnostic_claim_to_raw_session_v2(
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
) -> M2CTerminalDiagnosticAuthorizationBindingV2:
    claim = M2CTerminalDiagnosticConsumptionReceiptV2.model_validate(
        _json_object(read_regular_file_once(claim_path), label="V2 diagnostic claim")
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
        raise TerminalDiagnosticError("V2 probe inputs differ from consumed claim")
    verify_materialized_source_snapshot(
        source_snapshot_root,
        claim.committed_source_snapshot,
        require_content_addressed_name=False,
        allow_root_owned_read_only_mount=True,
    )
    return M2CTerminalDiagnosticAuthorizationBindingV2(
        schema_version="M2CTerminalDiagnosticAuthorizationBindingV2",
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


def _set_model_xy(root: ET.Element, name: str, xy: tuple[float, float]) -> None:
    world = root.find("world")
    if world is None:
        raise TerminalDiagnosticError("V2 diagnostic SDF has no world")
    models = [model for model in world.findall("model") if model.get("name") == name]
    if len(models) != 1:
        raise TerminalDiagnosticError(f"V2 diagnostic SDF does not contain {name} once")
    pose = models[0].find("pose")
    if pose is None or not pose.text:
        raise TerminalDiagnosticError(f"V2 diagnostic model {name} has no pose")
    values = [float(value) for value in pose.text.split()]
    if len(values) != 6:
        raise TerminalDiagnosticError(f"V2 diagnostic model {name} pose is not 6D")
    values[0], values[1] = xy
    pose.text = " ".join(f"{value:.9f}" for value in values)


def materialize_diagnostic_scene_v2(
    *,
    full_v4_sdf_bytes: bytes,
    full_v4_supervision_bytes: bytes,
    scene_seed: int,
    source_base_seed: int,
    condition: str,
) -> tuple[bytes, bytes]:
    if condition not in DIAGNOSTIC_CONDITIONS:
        raise TerminalDiagnosticError("unknown V2 diagnostic condition")
    root = ET.fromstring(full_v4_sdf_bytes)
    parked = {
        "C1_NO_BLOCKER": (SCRIPTED_BLOCKER_ENTITY, RETAINED_BLOCKER_ENTITY),
        "C2_RETAINED_BLOCKER": (SCRIPTED_BLOCKER_ENTITY,),
        "C3_FULL_V4": (),
    }[condition]
    for name in parked:
        _set_model_xy(root, name, PARKING_XY_M[name])
    world = root.find("world")
    if world is None:
        raise TerminalDiagnosticError("V2 diagnostic SDF has no world")
    cylinder_names = [
        model.get("name")
        for model in world.findall("model")
        if str(model.get("name", "")).startswith("cylinder_")
    ]
    if cylinder_names != [f"cylinder_{index:02d}" for index in range(1, 7)]:
        raise TerminalDiagnosticError("V2 diagnostic must retain six canonical cylinders")
    ET.indent(root, space="  ")
    sdf_bytes = (ET.tostring(root, encoding="unicode") + "\n").encode()
    supervision = _json_object(full_v4_supervision_bytes, label="full V4 supervision")
    objects = supervision.get("simulator_supervision", {}).get("objects")
    if not isinstance(objects, list) or len(objects) != 6:
        raise TerminalDiagnosticError("V2 diagnostic supervision must retain six objects")
    by_name = {str(item.get("actual_sim_entity_id")): item for item in objects}
    if set(by_name) != {f"cylinder_{index:02d}" for index in range(1, 7)}:
        raise TerminalDiagnosticError("V2 supervision object identities changed")
    for name in parked:
        record = by_name[name]
        position = record.get("position_3d_world")
        if not isinstance(position, list) or len(position) != 3:
            raise TerminalDiagnosticError("V2 supervision position is not 3D")
        record["position_3d_world"] = [
            PARKING_XY_M[name][0],
            PARKING_XY_M[name][1],
            float(position[2]),
        ]
        record["m2c_layout_role"] = "DIAGNOSTIC_DISTANT_PARKED_OBJECT"
        record.pop("layout_reachability", None)
    supervision["seed"] = scene_seed
    supervision["part_count"] = 6
    supervision["m2c_terminal_regrasp_diagnostic"] = {
        "schema_version": "M2CTerminalRegraspSceneV2",
        "condition": condition,
        "source_base_seed": source_base_seed,
        "scene_seed": scene_seed,
        "anchor_xy_m": list(FIXED_ANCHOR_XY_M),
        "parked_nonlocal_blockers": list(parked),
        "parking_xy_m": {name: list(PARKING_XY_M[name]) for name in parked},
        "six_canonical_objects_retained": True,
        "terminal_target_blocker_surface_gap_m": (
            None if condition == "C1_NO_BLOCKER" else RETAINED_BLOCKER_SURFACE_GAP_M
        ),
        "outcome_observed_during_materialization": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return sdf_bytes, (
        json.dumps(supervision, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def evaluate_preregistered_decision_tree_v2(
    *,
    prereg: M2CTerminalRegraspDiagnosticPreregV2,
    attempts: Sequence[M2CTerminalDiagnosticAttemptV1],
):
    return evaluate_preregistered_decision_tree(prereg=prereg, attempts=attempts)
