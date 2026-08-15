"""Final ADR-0026 diagnostic routing with direct branch before V4-chain gates."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal, Sequence

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
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    M2CTerminalDiagnosticAttemptV1,
    RUNS_PER_CONDITION,
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
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    BoundRepositoryFileV2,
    PARKING_XY_M,
    UPSTREAM_V4_PROBE_SHA256,
    materialize_diagnostic_scene_v2,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    DIRECT_PUBLIC_RGBD_CONTRACT,
    EXCLUSION_PATHS as V3_EXCLUSION_PATHS,
    M2CTerminalDiagnosticAuthorizationBindingV3,
    M2CTerminalDiagnosticConsumptionReceiptV3,
    M2CTerminalRegraspDiagnosticRawV3,
)


CAMPAIGN_ID = "m2c-s4-terminal-regrasp-diagnostic-v4"
PREREG_REPOSITORY_PATH = "docs/decisions/M2C-S4-TERMINAL-REGRASP-DIAGNOSTIC-V4-PREREG.json"
LEDGER_NAMESPACE = "M2C_S4_TERMINAL_REGRASP_DIAGNOSTIC_V4"
V3_PREREG_PATH = "docs/decisions/M2C-S4-TERMINAL-REGRASP-DIAGNOSTIC-V3-PREREG.json"
V3_INCOMPLETE_REPORT_PATH = "reports/m2c-s4-terminal-regrasp-diagnostic-v3-incomplete.json"

IMPLEMENTATION_PATHS = (
    "scripts/generate_industrial_scenes.py",
    "scripts/isaac_m1b_actuation_probe.py",
    "scripts/isaac_m1b_dataset_benchmark.py",
    "scripts/m2c/s4_scene_family.py",
    "scripts/m2c/build_terminal_regrasp_diagnostic_prereg_v4.py",
    "scripts/m2c/derive_model_owned_chain_probe.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe_v2.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe_v3.py",
    "scripts/m2c/derive_terminal_regrasp_diagnostic_probe_v4.py",
    "scripts/m2c/materialize_terminal_regrasp_diagnostic_scenes_v4.py",
    "scripts/m2c/run_terminal_regrasp_diagnostic.py",
    "scripts/m2c/run_terminal_regrasp_diagnostic_v4.py",
    "scripts/m2c/audit_terminal_regrasp_diagnostic_v4.py",
    "scripts/m2c/audit_terminal_regrasp_diagnostic_v3_incomplete.py",
    "src/xh_agent/data/isaac_m1b.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v1.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v2.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v3.py",
    "src/xh_agent/policy/qrm_lite/terminal_regrasp_diagnostic_v4.py",
)

EXCLUSION_PATHS = (*V3_EXCLUSION_PATHS, V3_PREREG_PATH, V3_INCOMPLETE_REPORT_PATH)


class PriorV3InvalidationV4(StrictModel):
    preregistration: BoundRepositoryFileV2
    incomplete_audit: BoundRepositoryFileV2
    valid_terminal_measurements: Literal[0]
    stage_completed: Literal[True]
    kit_started: Literal[True]
    controller_initialized: Literal[True]
    neutral_reset_and_open_gripper_initialization_executed: Literal[True]
    terminal_primitive_called: Literal[False]
    terminal_regrasp_action_outcome: Literal["NOT_AVAILABLE"]
    v3_claim_reused: Literal[False]
    v3_identity_reused: Literal[False]


class M2CTerminalRegraspDiagnosticPreregV4(StrictModel):
    schema_version: Literal["M2CTerminalRegraspDiagnosticPreregV4"]
    status: Literal["FROZEN_AFTER_V3_PRE_TERMINAL_INVALIDATION_BEFORE_ANY_VALID_DIAGNOSTIC_OUTCOME"]
    repository_relative_path: Literal[PREREG_REPOSITORY_PATH]
    introduction_commit_paths: list[str] = Field(min_length=1, max_length=1)
    campaign_id: Literal[CAMPAIGN_ID]
    governing_adr: dict[str, Any]
    written_date_asia_shanghai: Literal["2026-08-15"]
    diagnostic_outcomes_observed_before_freeze: Literal[False]
    prior_v3_invalidation: PriorV3InvalidationV4
    restart_basis: Literal[
        "NEW_CAMPAIGN_ALL_FRESH_IDENTITIES_NO_V1_V2_OR_V3_CLAIM_OR_IDENTITY_REUSE"
    ]
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
    unchanged_six_object_scene_contract: Literal[True]
    direct_branch_precedes_inherited_v4_chain: Literal[True]
    direct_public_rgbd_setup_contract: Literal[DIRECT_PUBLIC_RGBD_CONTRACT]
    public_rgbd_pixels_tracker_predicates_unchanged: Literal[True]
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
    def campaign_is_exact(self) -> "M2CTerminalRegraspDiagnosticPreregV4":
        if self.introduction_commit_paths != [self.repository_relative_path]:
            raise ValueError("V4 diagnostic introduction path is not singleton-exact")
        if self.governing_adr != {
            "path": ADR_PATH,
            "sha256": ADR_SHA256,
            "introduced_commit": ADR_INTRODUCED_COMMIT,
            "status": "ACCEPTED_HUMAN_ADR",
        }:
            raise ValueError("V4 diagnostic governing ADR binding changed")
        if [item.path for item in self.implementation_bindings] != list(IMPLEMENTATION_PATHS):
            raise ValueError("V4 diagnostic implementation closure is not exact")
        if [item.path for item in self.exclusion_sources] != list(EXCLUSION_PATHS):
            raise ValueError("V4 diagnostic exclusion inventory is not exact")
        if self.committed_source_snapshot.commit != self.implementation_commit:
            raise ValueError("V4 diagnostic source snapshot differs from implementation")
        if self.parking_xy_m != {key: list(value) for key, value in PARKING_XY_M.items()}:
            raise ValueError("V4 diagnostic parking geometry changed")
        if [run.ordinal for run in self.runs] != list(range(TOTAL_RUNS)):
            raise ValueError("V4 diagnostic run order is not exact")
        expected_conditions = [
            condition for _ in range(RUNS_PER_CONDITION) for condition in DIAGNOSTIC_CONDITIONS
        ]
        if [run.condition for run in self.runs] != expected_conditions:
            raise ValueError("V4 diagnostic paired condition order changed")
        grouped: dict[int, list[TerminalDiagnosticRunV1]] = {}
        for run in self.runs:
            grouped.setdefault(run.source_base_seed, []).append(run)
        if len(grouped) != RUNS_PER_CONDITION or any(
            [run.condition for run in group] != list(DIAGNOSTIC_CONDITIONS)
            for group in grouped.values()
        ):
            raise ValueError("V4 diagnostic source-seed pairing changed")
        for field in ("scene_seed", "failure_seed", "run_id", "matched_key"):
            values = [getattr(run, field) for run in self.runs]
            if len(set(values)) != TOTAL_RUNS:
                raise ValueError(f"V4 diagnostic campaign repeats {field}")
        core = self.model_dump(mode="json", exclude={"prereg_sha256"})
        if self.prereg_sha256 != canonical_sha256(core):
            raise ValueError("V4 diagnostic prereg canonical digest mismatch")
        return self


@dataclass(frozen=True)
class ResolvedTerminalDiagnosticPreregV4:
    path: Path
    file_sha256: str
    raw_bytes: bytes
    prereg: M2CTerminalRegraspDiagnosticPreregV4
    introduced_commit: str


class M2CTerminalDiagnosticConsumptionReceiptV4(M2CTerminalDiagnosticConsumptionReceiptV3):
    schema_version: Literal["M2CTerminalDiagnosticConsumptionReceiptV4"]
    campaign_id: Literal[CAMPAIGN_ID]
    ledger_namespace: Literal[LEDGER_NAMESPACE]
    prereg_repository_path: Literal[PREREG_REPOSITORY_PATH]


class M2CTerminalDiagnosticAuthorizationBindingV4(M2CTerminalDiagnosticAuthorizationBindingV3):
    schema_version: Literal["M2CTerminalDiagnosticAuthorizationBindingV4"]
    campaign_id: Literal[CAMPAIGN_ID]


class M2CTerminalRegraspDiagnosticRawV4(M2CTerminalRegraspDiagnosticRawV3):
    schema_version: Literal["M2CTerminalRegraspDiagnosticRawV4"]
    authorization: M2CTerminalDiagnosticAuthorizationBindingV4


def parse_diagnostic_raw_bytes_v4(raw: bytes) -> M2CTerminalRegraspDiagnosticRawV4:
    return M2CTerminalRegraspDiagnosticRawV4.model_validate(
        _json_object(raw, label="V4 terminal diagnostic raw evidence")
    )


def load_committed_diagnostic_prereg_v4(
    *, project_root: Path, prereg_path: Path
) -> ResolvedTerminalDiagnosticPreregV4:
    root = project_root.resolve(strict=True)
    path = prereg_path.resolve(strict=True)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise TerminalDiagnosticError("V4 diagnostic prereg escapes project root") from error
    raw = read_regular_file_once(path)
    prereg = M2CTerminalRegraspDiagnosticPreregV4.model_validate(
        _json_object(raw, label="V4 terminal diagnostic prereg")
    )
    if relative != prereg.repository_relative_path:
        raise TerminalDiagnosticError("V4 diagnostic repository path mismatch")
    if _git(root, "show", f"HEAD:{relative}") != raw:
        raise TerminalDiagnosticError("V4 diagnostic prereg is not current HEAD bytes")
    introduced = (
        _git(root, "log", "--diff-filter=A", "--format=%H", "--", relative).decode().splitlines()
    )
    if len(introduced) != 1 or _git(root, "show", f"{introduced[0]}:{relative}") != raw:
        raise TerminalDiagnosticError("V4 diagnostic introduction binding changed")
    changed = set(
        _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", introduced[0])
        .decode()
        .splitlines()
    )
    if changed != {relative}:
        raise TerminalDiagnosticError("V4 diagnostic prereg commit is not single-purpose")
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
            raise TerminalDiagnosticError(f"V4 source binding changed: {binding.path}")
        if binding in prereg.exclusion_sources:
            external_payloads.append(_json_object(current, label=binding.path))
    if _git(
        root,
        "merge-base",
        "--is-ancestor",
        prereg.implementation_commit,
        introduced[0],
    ).strip():
        raise TerminalDiagnosticError("V4 implementation is not a prereg ancestor")
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
    if any(not values for values in axes.values()) or (
        prereg.external_identity_digest
        != canonical_sha256({axis: sorted(values) for axis, values in axes.items()})
    ):
        raise TerminalDiagnosticError("V4 external identity inventory changed")
    for run in prereg.runs:
        if any(getattr(run, axis) in values for axis, values in axes.items()):
            raise TerminalDiagnosticError("V4 identity overlaps frozen external inventory")
    return ResolvedTerminalDiagnosticPreregV4(
        path=path,
        file_sha256=sha256_bytes(raw),
        raw_bytes=raw,
        prereg=prereg,
        introduced_commit=introduced[0],
    )


def _read_existing_claims_v4(
    *,
    ledger_root: Path,
    prereg: M2CTerminalRegraspDiagnosticPreregV4,
    expected_count: int,
) -> list[M2CTerminalDiagnosticConsumptionReceiptV4]:
    names = sorted(path.name for path in ledger_root.glob("claim-*.json"))
    expected = [f"claim-{ordinal:02d}.json" for ordinal in range(expected_count)]
    if names != expected:
        raise TerminalDiagnosticError("V4 diagnostic claims are not in frozen order")
    claims: list[M2CTerminalDiagnosticConsumptionReceiptV4] = []
    for ordinal, name in enumerate(names):
        claim = M2CTerminalDiagnosticConsumptionReceiptV4.model_validate(
            _json_object(
                read_regular_file_once(ledger_root / name),
                label=f"V4 diagnostic claim {name}",
            )
        )
        if claim.ordinal != ordinal or claim.run != prereg.runs[ordinal]:
            raise TerminalDiagnosticError("V4 diagnostic ledger prefix changed")
        claims.append(claim)
    return claims


def consume_diagnostic_run_v4(
    *,
    resolved: ResolvedTerminalDiagnosticPreregV4,
    run_id: str,
    ledger_root: Path,
    derived_probe_sha256: str,
    consumed_at_ns: int,
) -> Path:
    prereg = resolved.prereg
    if str(ledger_root.resolve(strict=True)) != prereg.ledger_root:
        raise TerminalDiagnosticError("V4 diagnostic ledger root differs from prereg")
    _secure_ledger_root(ledger_root)
    selected = [run for run in prereg.runs if run.run_id == run_id]
    if len(selected) != 1:
        raise TerminalDiagnosticError("V4 diagnostic run is not uniquely preregistered")
    run = selected[0]
    with _ledger_lock(ledger_root):
        _read_existing_claims_v4(
            ledger_root=ledger_root,
            prereg=prereg,
            expected_count=run.ordinal,
        )
        payload: dict[str, Any] = {
            "schema_version": "M2CTerminalDiagnosticConsumptionReceiptV4",
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
            "direct_public_rgbd_setup_contract": DIRECT_PUBLIC_RGBD_CONTRACT,
            "consumed_at_ns": consumed_at_ns,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        payload["receipt_sha256"] = canonical_sha256(payload)
        receipt = M2CTerminalDiagnosticConsumptionReceiptV4.model_validate(payload)
        path = ledger_root / f"claim-{run.ordinal:02d}.json"
        _write_create_only(
            path,
            json.dumps(
                receipt.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n",
        )
    return path


def bind_diagnostic_claim_to_raw_session_v4(
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
    direct_public_rgbd_enabled: bool,
) -> M2CTerminalDiagnosticAuthorizationBindingV4:
    claim = M2CTerminalDiagnosticConsumptionReceiptV4.model_validate(
        _json_object(read_regular_file_once(claim_path), label="V4 diagnostic claim")
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
        run.condition in {"C1_NO_BLOCKER", "C2_RETAINED_BLOCKER"},
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
        direct_public_rgbd_enabled,
    )
    if actual != expected:
        raise TerminalDiagnosticError("V4 probe inputs differ from consumed claim")
    verify_materialized_source_snapshot(
        source_snapshot_root,
        claim.committed_source_snapshot,
        require_content_addressed_name=False,
        allow_root_owned_read_only_mount=True,
    )
    return M2CTerminalDiagnosticAuthorizationBindingV4(
        schema_version="M2CTerminalDiagnosticAuthorizationBindingV4",
        campaign_id=claim.campaign_id,
        condition=run.condition,
        run_id=run.run_id,
        matched_key=run.matched_key,
        ordinal=run.ordinal,
        scene_seed=run.scene_seed,
        failure_seed=run.failure_seed,
        probe_mode=run.probe_mode,
        expected_local_blockers=run.expected_local_blockers,
        terminal_target_blocker_surface_gap_m=(run.terminal_target_blocker_surface_gap_m),
        direct_public_rgbd_enabled=direct_public_rgbd_enabled,
        public_rgbd_setup_contract=DIRECT_PUBLIC_RGBD_CONTRACT,
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


def evaluate_preregistered_decision_tree_v4(
    *,
    prereg: M2CTerminalRegraspDiagnosticPreregV4,
    attempts: Sequence[M2CTerminalDiagnosticAttemptV1],
):
    return evaluate_preregistered_decision_tree(prereg=prereg, attempts=attempts)


__all__ = [
    "CAMPAIGN_ID",
    "DIRECT_PUBLIC_RGBD_CONTRACT",
    "EXCLUSION_PATHS",
    "IMPLEMENTATION_PATHS",
    "LEDGER_NAMESPACE",
    "M2CTerminalDiagnosticAuthorizationBindingV4",
    "M2CTerminalDiagnosticConsumptionReceiptV4",
    "M2CTerminalRegraspDiagnosticPreregV4",
    "M2CTerminalRegraspDiagnosticRawV4",
    "PREREG_REPOSITORY_PATH",
    "ResolvedTerminalDiagnosticPreregV4",
    "V3_INCOMPLETE_REPORT_PATH",
    "V3_PREREG_PATH",
    "bind_diagnostic_claim_to_raw_session_v4",
    "consume_diagnostic_run_v4",
    "evaluate_preregistered_decision_tree_v4",
    "load_committed_diagnostic_prereg_v4",
    "materialize_diagnostic_scene_v2",
    "parse_diagnostic_raw_bytes_v4",
]
