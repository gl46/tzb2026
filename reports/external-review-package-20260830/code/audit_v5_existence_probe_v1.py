#!/usr/bin/env python3
"""Strict final auditor for the Amendment 8F/8G-A/8H existence probe.

The auditor accepts a campaign only when all twelve preregistered ordinals have
one canonical ledger claim and one distinct, byte-closed job.  Any missing,
extra, duplicate, or cross-bound artifact is a harness/closure invalidity.  It
halts the campaign and never converts a spent ordinal into a retry.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Literal

from pydantic import ValidationError

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    TerminalDiagnosticError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from xh_agent.policy.qrm_lite.v5_existence_probe_campaign_v1 import (
    ARGV_PRECONSUMPTION_IDENTITY_SENTINEL,
    EXISTENCE_FLOOR_MIN_SUCCESSES,
    PREFLIGHT_ATTESTATION_NAME,
    PROBE_COUNT,
    ExistenceCampaignLedgerSnapshotV1,
    ExistenceProbeAuthorizationBindingV1,
    ExistenceProbeIncompleteTerminalReceiptV1,
    ExistenceProbeJobReceiptV1,
    ExistenceProbePreflightAttestationV1,
    ExistenceProbeTerminalReceiptV1,
    M2CV5ExistenceProbePreregV1,
    ResolvedExistenceProbePrereg,
    V5ExistenceProbeError,
    build_existence_probe_command,
    consumption_ledger_state_sha256,
    derive_existence_preflight_argv_shape,
    existence_argv_identity_values,
    existence_argv_stable_digest_allowlist,
    existence_campaign_audit_lock,
    existence_probe_terminal_success,
    existence_production_argv_forbidden_roots,
    first_existence_argv_divergence,
    load_committed_existence_prereg,
    normalize_existence_probe_argv,
    read_existence_campaign_snapshot_locked,
    validate_complete_existence_probe_evidence,
    validate_existence_preflight_attestation_locked,
    validate_incomplete_existence_probe_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCHEMA_VERSION = "M2CV5ExistenceProbeAuditV1"
JOB_RECEIPT_SCHEMA_VERSION = "M2CV5ExistenceProbeJobReceiptV1"
JOB_RECEIPT_STATUS = "CONSUMED_AND_HOST_AUTHORIZED_BEFORE_PROBE"
TERMINAL_RECEIPT_SCHEMA_VERSION = "M2CV5ExistenceProbeTerminalReceiptV1"
TERMINAL_COMPLETE_STATUS = "COMPLETE_VALID_TERMINAL_MEASUREMENT"
RAW_EVIDENCE_NAME = "terminal-regrasp-diagnostic.json"
DERIVED_PROBE_NAME = "v5-existence-probe.py"
HOST_AUTHORIZATION_NAME = "host-existence-authorization.json"
PROJECTED_AUTHORIZATION_NAME = "projected-existence-authorization.json"
EXPECTED_STRATUM_ALLOCATION = {
    "EXTRAPOLATED_ANCHOR__ESTABLISHED": 4,
    "EXTRAPOLATED_ANCHOR__NEW_TERRITORY": 2,
    "MEASURED_ANCHOR__ESTABLISHED": 4,
    "MEASURED_ANCHOR__NEW_TERRITORY": 2,
}
STRATUM_ORDER = tuple(EXPECTED_STRATUM_ALLOCATION)
SEVERE_INTER_STRATUM_DIVERGENCE_THRESHOLD = 0.75
SEVERE_INTER_STRATUM_DIVERGENCE_RULE = (
    "RATIFIED: severe iff max(stratum success fraction) minus min(stratum success "
    "fraction) >= 0.75 inclusive, over the frozen 4/2/4/2 strata, for every X >= 4"
)
EXACT_BINOMIAL_N = PROBE_COUNT
EXACT_BINOMIAL_P0 = 0.75
EXACT_BINOMIAL_ALPHA = 0.05
THIRD_REGIME_MAX_SUCCESSES = 5

DecisionAction = Literal[
    "HALT_HARNESS_INVALID_NO_RETRY",
    "HALT_CAMPAIGN_RETURN_TO_COORDINATION",
    "FREEZE_KEY_ELIGIBILITY_RETURN_TO_COORDINATION",
    "RETURN_TO_COORDINATION_BEFORE_KEY_FREEZE",
    "ADVANCE_TO_KEY_FREEZE",
]


def exact_binomial_lower_tail(
    successes: int,
    *,
    n: int = EXACT_BINOMIAL_N,
    p0: float = EXACT_BINOMIAL_P0,
) -> float:
    """Return P(X <= successes) for the preregistered exact binomial null."""

    if not 0 <= successes <= n:
        raise V5ExistenceProbeError("existence success count is outside the binomial support")
    return sum(
        math.comb(n, value) * p0**value * (1.0 - p0) ** (n - value)
        for value in range(successes + 1)
    )


def evaluate_existence_outcomes(
    *,
    prereg: M2CV5ExistenceProbePreregV1,
    successes_by_ordinal: Sequence[bool],
) -> dict[str, Any]:
    """Apply only the frozen Amendment 8F/8H outcome rules.

    Severe divergence is code-fixed before outcomes: the maximum minus minimum
    success fraction across the four preregistered strata is severe at >= 0.75.
    """

    if len(successes_by_ordinal) != PROBE_COUNT:
        raise V5ExistenceProbeError("existence decision requires exactly twelve outcomes")
    if len(prereg.runs) != PROBE_COUNT:
        raise V5ExistenceProbeError("existence preregistration does not contain twelve runs")

    counted = {
        name: sum(run.stratum == name for run in prereg.runs) for name in STRATUM_ORDER
    }
    if counted != EXPECTED_STRATUM_ALLOCATION or prereg.stratum_allocation != counted:
        raise V5ExistenceProbeError("existence decision strata are not exact 4/2/4/2")
    if {run.stratum for run in prereg.runs} != set(STRATUM_ORDER):
        raise V5ExistenceProbeError("existence decision contains an unregistered stratum")

    per_stratum: dict[str, dict[str, Any]] = {}
    for name in STRATUM_ORDER:
        rows = [
            bool(successes_by_ordinal[run.ordinal])
            for run in prereg.runs
            if run.stratum == name
        ]
        successes = sum(rows)
        per_stratum[name] = {
            "declared_runs": EXPECTED_STRATUM_ALLOCATION[name],
            "valid_measurements": len(rows),
            "successes": successes,
            "success_fraction": successes / len(rows),
        }

    total_successes = sum(bool(value) for value in successes_by_ordinal)
    successful_strata = [
        name for name in STRATUM_ORDER if per_stratum[name]["successes"] > 0
    ]
    numeric_fractions = [per_stratum[name]["success_fraction"] for name in STRATUM_ORDER]
    divergence_gap = max(numeric_fractions) - min(numeric_fractions)
    severe_divergence = (
        total_successes >= EXISTENCE_FLOOR_MIN_SUCCESSES
        and divergence_gap >= SEVERE_INTER_STRATUM_DIVERGENCE_THRESHOLD
    )

    global_floor_met = total_successes >= EXISTENCE_FLOOR_MIN_SUCCESSES
    floor_representation_met = len(successful_strata) >= 2
    floor_cleared = global_floor_met and floor_representation_met
    third_regime_p_value = exact_binomial_lower_tail(total_successes)
    third_regime_surprise = total_successes <= THIRD_REGIME_MAX_SUCCESSES

    if not floor_cleared:
        action: DecisionAction = "FREEZE_KEY_ELIGIBILITY_RETURN_TO_COORDINATION"
        selected_branch = (
            "X_LE_3_FLOOR_FAIL_RETURN"
            if not global_floor_met
            else "FLOOR_STRATUM_REPRESENTATION_FAIL_RETURN"
        )
    elif severe_divergence:
        action = "FREEZE_KEY_ELIGIBILITY_RETURN_TO_COORDINATION"
        selected_branch = "X_GE_4_RETURN_FOR_STRATUM_STRUCTURE"
    elif total_successes <= THIRD_REGIME_MAX_SUCCESSES:
        action = "RETURN_TO_COORDINATION_BEFORE_KEY_FREEZE"
        selected_branch = "X_4_TO_5_THIRD_REGIME_RETURN"
    else:
        action = "ADVANCE_TO_KEY_FREEZE"
        selected_branch = "X_GE_6_ADVANCE_NO_SEVERE_DIVERGENCE"

    return {
        "successes": total_successes,
        "valid_measurements": PROBE_COUNT,
        "success_fraction": total_successes / PROBE_COUNT,
        "per_stratum": per_stratum,
        "successful_strata": successful_strata,
        "global_floor_min_successes": EXISTENCE_FLOOR_MIN_SUCCESSES,
        "global_floor_met": global_floor_met,
        "floor_requires_successes_in_at_least_two_strata": True,
        "floor_representation_met": floor_representation_met,
        "floor_cleared": floor_cleared,
        "severe_inter_stratum_divergence": severe_divergence,
        "inter_stratum_success_fraction_range": divergence_gap,
        "severe_inter_stratum_divergence_threshold": (
            SEVERE_INTER_STRATUM_DIVERGENCE_THRESHOLD
        ),
        "severe_inter_stratum_divergence_rule": SEVERE_INTER_STRATUM_DIVERGENCE_RULE,
        "severe_inter_stratum_divergence_rule_ratified": True,
        "exact_binomial": {
            "n": EXACT_BINOMIAL_N,
            "p0": EXACT_BINOMIAL_P0,
            "alpha": EXACT_BINOMIAL_ALPHA,
            "lower_tail_p_value": third_regime_p_value,
            "surprise_max_successes": THIRD_REGIME_MAX_SUCCESSES,
            "surprise_triggered": third_regime_surprise,
        },
        "selected_branch": selected_branch,
        "action": action,
        "key_freeze_authorized": action == "ADVANCE_TO_KEY_FREEZE",
        "retry_or_replacement_authorized": False,
    }


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise V5ExistenceProbeError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                V5ExistenceProbeError(f"{label} contains non-finite number {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V5ExistenceProbeError(f"{label} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise V5ExistenceProbeError(f"{label} is not a JSON object")
    return payload


def _verify_self_hash(
    payload: Mapping[str, Any], *, field: str, label: str
) -> None:
    claimed = payload.get(field)
    if not isinstance(claimed, str) or canonical_sha256(
        {key: value for key, value in payload.items() if key != field}
    ) != claimed:
        raise V5ExistenceProbeError(f"{label} semantic hash changed")


def _job_root(evidence_root: Path, *, ordinal: int, family_ordinal: int) -> Path:
    return evidence_root / f"run-{ordinal:02d}-family-{family_ordinal:02d}"


def _require_exact_members(root: Path, *, expected: set[str], label: str) -> None:
    actual = {path.name for path in root.iterdir()}
    if actual != expected:
        raise V5ExistenceProbeError(
            f"{label} members differ: expected {sorted(expected)!r}, got {sorted(actual)!r}"
        )


def _require_real_directory(
    path: Path,
    *,
    within: Path,
    owner: int,
    mode: int,
    label: str,
) -> Path:
    resolved = path.resolve(strict=True)
    canonical_within = within.resolve(strict=True)
    try:
        resolved.relative_to(canonical_within)
    except ValueError as error:
        raise V5ExistenceProbeError(f"{label} escapes its canonical root") from error
    info = path.stat(follow_symlinks=False)
    if (
        resolved != path.absolute()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != owner
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise V5ExistenceProbeError(f"{label} metadata is unsafe")
    return resolved


def _require_regular_metadata(
    path: Path,
    *,
    within: Path,
    owner: int,
    group: int,
    mode: int,
    label: str,
) -> None:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(within.resolve(strict=True))
    except ValueError as error:
        raise V5ExistenceProbeError(f"{label} escapes its canonical root") from error
    info = path.stat(follow_symlinks=False)
    if (
        resolved != path.absolute()
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != owner
        or info.st_gid != group
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != mode
    ):
        raise V5ExistenceProbeError(f"{label} metadata is unsafe")


def _capture_relative_path(uri: str, *, expected_kind: str) -> str:
    prefix = f"dataset://m2b_public_rgbd/{expected_kind}/"
    if not uri.startswith(prefix):
        raise V5ExistenceProbeError("existence capture URI changed")
    name = uri.removeprefix(prefix)
    expected_suffix = ".png" if expected_kind == "rgb" else ".npy"
    if Path(name).name != name or not name.endswith(expected_suffix):
        raise V5ExistenceProbeError("existence capture URI is not canonical")
    return f"m2b_public_rgbd/{expected_kind}/{name}"


def _expected_probe_members(raw: Any) -> dict[str, str]:
    expected = {
        "console.log": "",
        RAW_EVIDENCE_NAME: "",
    }
    seen_labels: set[str] = set()
    for capture in raw.public_capture_evidence:
        if not isinstance(capture, dict):
            raise V5ExistenceProbeError("existence public capture is not an object")
        label = capture.get("label")
        rgb_uri = capture.get("rgb_uri")
        depth_uri = capture.get("depth_uri")
        rgb_sha256 = capture.get("rgb_sha256")
        depth_sha256 = capture.get("depth_sha256")
        if (
            not isinstance(label, str)
            or not label
            or label in seen_labels
            or not isinstance(rgb_uri, str)
            or not isinstance(depth_uri, str)
            or not isinstance(rgb_sha256, str)
            or not isinstance(depth_sha256, str)
        ):
            raise V5ExistenceProbeError("existence public capture binding is incomplete")
        seen_labels.add(label)
        expected[_capture_relative_path(rgb_uri, expected_kind="rgb")] = rgb_sha256
        expected[_capture_relative_path(depth_uri, expected_kind="depth")] = depth_sha256
    return expected


def _read_authorization_pair(job_root: Path) -> tuple[bytes, bytes]:
    authorization_root = job_root / "authorization"
    _require_exact_members(
        authorization_root,
        expected={HOST_AUTHORIZATION_NAME, PROJECTED_AUTHORIZATION_NAME},
        label="existence authorization directory",
    )
    host_raw = v4_auth.read_regular_file_once(
        authorization_root / HOST_AUTHORIZATION_NAME
    )
    projected_raw = v4_auth.read_regular_file_once(
        authorization_root / PROJECTED_AUTHORIZATION_NAME
    )
    if host_raw != projected_raw:
        raise V5ExistenceProbeError("projected authorization differs from host bytes")
    return host_raw, projected_raw


def _authorization_from_bytes(raw: bytes, *, label: str) -> ExistenceProbeAuthorizationBindingV1:
    try:
        return ExistenceProbeAuthorizationBindingV1.model_validate(
            _strict_json_object(raw, label=label)
        )
    except ValidationError as error:
        raise V5ExistenceProbeError(f"{label} does not satisfy the typed contract") from error


def _halt_report(*, blocker: str) -> dict[str, Any]:
    core: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "HALT_HARNESS_OR_CLOSURE_INVALID_NO_RETRY",
        "valid_measurements": 0,
        "decision": None,
        "action": "HALT_HARNESS_INVALID_NO_RETRY",
        "key_freeze_authorized": False,
        "retry_or_replacement_authorized": False,
        "blockers": [blocker],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return {**core, "report_content_sha256": canonical_sha256(core)}


def _governed_halt_status(violation: str) -> str:
    if violation in {
        "ARGV_SHAPE_MISMATCH_ORDINAL_UNCONSUMED",
        "ARGV_SHAPE_MISMATCH_ORDINAL_CONSUMED",
    }:
        return "HALT_GOVERNED_ARGV_SHAPE_MISMATCH_NO_RETRY"
    return f"HALT_GOVERNED_{violation}"


def _governed_halt_report(
    *,
    resolved: ResolvedExistenceProbePrereg,
    ledger: ExistenceCampaignLedgerSnapshotV1,
    attestation: ExistenceProbePreflightAttestationV1,
    evidence_root: Path,
    lock_token: Any,
) -> dict[str, Any]:
    """Independently audit any typed canonical halt without erasing history."""

    halt = ledger.halt
    if halt is None:
        raise V5ExistenceProbeError("canonical ledger has no governed halt")
    if ledger.halt_bytes is None or ledger.complete is not None:
        raise V5ExistenceProbeError("governed halt marker state changed")

    violation = halt.violation
    attempted_ordinal = halt.attempted_ordinal
    durable_claim_count = len(ledger.claims)
    durable_terminal_count = len(ledger.terminals)
    if (
        durable_claim_count != durable_terminal_count
        or [claim.ordinal for claim in ledger.claims]
        != list(range(durable_claim_count))
        or [terminal.ordinal for terminal in ledger.terminals]
        != list(range(durable_terminal_count))
    ):
        raise V5ExistenceProbeError("governed halt durable prefix changed")

    consumed = attempted_ordinal < durable_claim_count
    incomplete_ordinals = [
        terminal.ordinal
        for terminal in ledger.terminals
        if isinstance(terminal, ExistenceProbeIncompleteTerminalReceiptV1)
    ]
    if violation == "ARGV_SHAPE_MISMATCH_ORDINAL_UNCONSUMED":
        if (
            consumed
            or durable_claim_count != attempted_ordinal
            or incomplete_ordinals
            or halt.candidate_identity_material_kind != "SENTINEL_REHEARSAL"
            or halt.prelaunch_host_terminal_receipt_sha256 is not None
        ):
            raise V5ExistenceProbeError(
                "unconsumed argv-shape halt evidence matrix changed"
            )
    elif violation == "ARGV_SHAPE_MISMATCH_ORDINAL_CONSUMED":
        if (
            not consumed
            or durable_claim_count != attempted_ordinal + 1
            or incomplete_ordinals != [attempted_ordinal]
            or halt.candidate_identity_material_kind != "CANONICAL_REAL_IDENTITIES"
            or halt.prelaunch_host_terminal_receipt_sha256 is None
        ):
            raise V5ExistenceProbeError(
                "consumed argv-shape halt evidence matrix changed"
            )
        tip = ledger.terminals[attempted_ordinal]
        if (
            not isinstance(tip, ExistenceProbeIncompleteTerminalReceiptV1)
            or tip.failure_source != "PRE_LAUNCH_HOST"
            or halt.prelaunch_host_terminal_receipt_sha256
            != sha256_bytes(ledger.terminal_bytes[attempted_ordinal])
        ):
            raise V5ExistenceProbeError(
                "consumed argv-shape halt PRE_LAUNCH_HOST binding changed"
            )
    elif violation in {
        "INCOMPLETE_SPENT_NO_RETRY",
        "ORPHAN_CLAIM_RECOVERED_INCOMPLETE",
    }:
        if (
            not consumed
            or durable_claim_count != attempted_ordinal + 1
            or incomplete_ordinals != [attempted_ordinal]
        ):
            raise V5ExistenceProbeError("governed incomplete halt durable tip changed")
        tip = ledger.terminals[attempted_ordinal]
        if (
            not isinstance(tip, ExistenceProbeIncompleteTerminalReceiptV1)
            or halt.detail != f"{tip.error_type}: {tip.error_message}"
            or (
                violation == "ORPHAN_CLAIM_RECOVERED_INCOMPLETE"
                and tip.error_type != "InterruptedProcessRecovery"
            )
        ):
            raise V5ExistenceProbeError("governed incomplete halt detail changed")
    elif violation == "SECOND_TERMINAL_RECEIPT_ATTEMPT":
        if (
            not consumed
            or incomplete_ordinals
            or halt.existing_terminal_sha256
            != sha256_bytes(ledger.terminal_bytes[attempted_ordinal])
        ):
            raise V5ExistenceProbeError(
                "governed second-terminal halt binding changed"
            )
    elif violation == "COMPLETE_EVIDENCE_VALIDATION_FAILED":
        if not consumed or incomplete_ordinals:
            raise V5ExistenceProbeError(
                "governed COMPLETE-validation halt durable prefix changed"
            )
    elif violation == "CAMPAIGN_FINALIZATION_VALIDATION_FAILED":
        if (
            not consumed
            or durable_claim_count != PROBE_COUNT
            or incomplete_ordinals
        ):
            raise V5ExistenceProbeError(
                "governed finalization halt durable campaign changed"
            )
    else:
        raise V5ExistenceProbeError("canonical ledger halt kind is unrecognized")

    is_argv_halt = violation in {
        "ARGV_SHAPE_MISMATCH_ORDINAL_UNCONSUMED",
        "ARGV_SHAPE_MISMATCH_ORDINAL_CONSUMED",
    }
    attested_shape: list[str] | None = None
    candidate_shape = halt.candidate_normalized_argv
    if is_argv_halt:
        attested_shape = derive_existence_preflight_argv_shape(attestation)
        if (
            halt.consumption_ledger_entry_count != durable_claim_count
            or halt.consumption_ledger_state_sha256
            != consumption_ledger_state_sha256(
                claim_bytes=ledger.claim_bytes,
                terminal_bytes=ledger.terminal_bytes,
                complete_bytes=None,
                halt_bytes=None,
            )
            or halt.attested_preflight_bundle_sha256
            != attestation.scratch_authorization_bundle.bundle_sha256
            or halt.attested_preflight_normalized_argv != attested_shape
            or candidate_shape is None
            or halt.first_divergence_index
            != first_existence_argv_divergence(attested_shape, candidate_shape)
        ):
            raise V5ExistenceProbeError(
                "governed argv-shape halt independent evidence binding changed"
            )

    canonical_ledger = ledger.ledger_root
    expected_ledger_members = {
        ".diagnostic-ledger.lock",
        "ledger-bootstrap-record.json",
        PREFLIGHT_ATTESTATION_NAME,
        "campaign-halt.json",
        *(f"claim-{ordinal:02d}.json" for ordinal in range(durable_claim_count)),
        *(f"terminal-{ordinal:02d}.json" for ordinal in range(durable_terminal_count)),
    }
    _require_exact_members(
        canonical_ledger,
        expected=expected_ledger_members | set(ledger.publication_residue_names),
        label="governed halted existence ledger",
    )

    frozen_evidence_root = Path(resolved.prereg.evidence_root).resolve(strict=True)
    supplied_evidence_root = evidence_root.resolve(strict=True)
    if supplied_evidence_root != frozen_evidence_root:
        raise V5ExistenceProbeError(
            "audit evidence root differs from the frozen canonical evidence root"
        )
    canonical_evidence_root = _require_real_directory(
        supplied_evidence_root,
        within=supplied_evidence_root,
        owner=0,
        mode=0o700,
        label="halted existence evidence root",
    )
    expected_job_roots = [
        _job_root(
            canonical_evidence_root,
            ordinal=run.ordinal,
            family_ordinal=run.family_ordinal,
        )
        for run in resolved.prereg.runs[:durable_claim_count]
    ]
    if len(expected_job_roots) != len(set(expected_job_roots)):
        raise V5ExistenceProbeError("governed halted existence job roots repeat")
    _require_exact_members(
        canonical_evidence_root,
        expected={path.name for path in expected_job_roots},
        label="halted existence evidence root",
    )

    expected_complete_validation_failure = violation in {
        "COMPLETE_EVIDENCE_VALIDATION_FAILED",
        "CAMPAIGN_FINALIZATION_VALIDATION_FAILED",
    }
    validated_complete_ordinals: list[int] = []
    reproduced_complete_failure_ordinal: int | None = None
    validated_incomplete_ordinal: int | None = None
    for ordinal, terminal in enumerate(ledger.terminals):
        if isinstance(terminal, ExistenceProbeTerminalReceiptV1):
            try:
                complete_evidence = validate_complete_existence_probe_evidence(
                    resolved=resolved,
                    terminal=terminal,
                    lock_token=lock_token,
                )
            except BaseException as error:
                detail = f"{type(error).__name__}: {error}"
                if (
                    not expected_complete_validation_failure
                    or ordinal != attempted_ordinal
                    or halt.detail != detail
                    or reproduced_complete_failure_ordinal is not None
                ):
                    raise V5ExistenceProbeError(
                        f"governed halt COMPLETE evidence is invalid at ordinal {ordinal}: "
                        f"{detail}"
                    ) from error
                reproduced_complete_failure_ordinal = ordinal
            else:
                if complete_evidence.job_root != expected_job_roots[ordinal]:
                    raise V5ExistenceProbeError(
                        f"governed halt COMPLETE evidence selected wrong job at "
                        f"ordinal {ordinal}"
                    )
                validated_complete_ordinals.append(ordinal)
        else:
            if ordinal != attempted_ordinal or validated_incomplete_ordinal is not None:
                raise V5ExistenceProbeError(
                    "governed halt INCOMPLETE evidence is not the attempted tip"
                )
            incomplete_evidence = validate_incomplete_existence_probe_evidence(
                resolved=resolved,
                terminal=terminal,
                lock_token=lock_token,
            )
            if incomplete_evidence.job_root != expected_job_roots[ordinal]:
                raise V5ExistenceProbeError(
                    "governed halt INCOMPLETE evidence selected the wrong job"
                )
            if violation == "ARGV_SHAPE_MISMATCH_ORDINAL_CONSUMED":
                failure_event = incomplete_evidence.failure_event
                constructed_command = (
                    None
                    if failure_event is None
                    else failure_event.constructed_probe_command
                )
                if (
                    failure_event is None
                    or failure_event.failure_stage != "ARGV_SHAPE_MISMATCH"
                    or constructed_command is None
                ):
                    raise V5ExistenceProbeError(
                        "governed consumed argv-shape halt lacks its event-bound command"
                    )
                stage = resolved.prereg.stage_templates.templates[ordinal]
                event_candidate_shape = normalize_existence_probe_argv(
                    constructed_command.argv,
                    evidence_root=Path(resolved.prereg.evidence_root),
                    forbidden_absolute_roots=(
                        existence_production_argv_forbidden_roots(
                            output_root=Path(resolved.prereg.evidence_root),
                            resolved=resolved,
                        )
                    ),
                    stable_digest_allowlist=(
                        existence_argv_stable_digest_allowlist(
                            stage_metrics_sha256=stage.stage_metrics_sha256,
                            stage_command_sha256=stage.stage_command_sha256,
                            stage_template_manifest_sha256=(
                                resolved.prereg.stage_templates.manifest_sha256
                            ),
                        )
                    ),
                )
                identity_values = existence_argv_identity_values(
                    constructed_command.argv
                )
                if (
                    event_candidate_shape != candidate_shape
                    or ARGV_PRECONSUMPTION_IDENTITY_SENTINEL
                    in identity_values.values()
                ):
                    raise V5ExistenceProbeError(
                        "governed consumed argv-shape halt candidate differs from "
                        "its event-bound command"
                    )
            validated_incomplete_ordinal = ordinal
    if expected_complete_validation_failure is not (
        reproduced_complete_failure_ordinal is not None
    ):
        raise V5ExistenceProbeError(
            "governed COMPLETE-validation halt failure was not reproduced"
        )

    halt_evidence = {
        "marker_file_sha256": sha256_bytes(ledger.halt_bytes),
        "marker_semantic_sha256": halt.marker_sha256,
        "violation": violation,
        "attempted_ordinal": attempted_ordinal,
        "consumed": consumed,
        "existing_terminal_sha256": halt.existing_terminal_sha256,
        "detail": halt.detail,
        "durable_claim_count": durable_claim_count,
        "durable_terminal_count": durable_terminal_count,
        "consumption_ledger_entry_count": halt.consumption_ledger_entry_count,
        "consumption_ledger_state_sha256": halt.consumption_ledger_state_sha256,
        "attested_preflight_bundle_sha256": halt.attested_preflight_bundle_sha256,
        "attested_preflight_normalized_argv_sha256": (
            None if attested_shape is None else canonical_sha256(attested_shape)
        ),
        "candidate_normalized_argv_sha256": (
            None if candidate_shape is None else canonical_sha256(candidate_shape)
        ),
        "first_divergence_index": halt.first_divergence_index,
        "candidate_identity_material_kind": halt.candidate_identity_material_kind,
        "prelaunch_host_terminal_receipt_sha256": (
            halt.prelaunch_host_terminal_receipt_sha256
        ),
        "reproduced_complete_failure_ordinal": (
            reproduced_complete_failure_ordinal
        ),
        "validated_incomplete_ordinal": validated_incomplete_ordinal,
    }
    core: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": _governed_halt_status(violation),
        "campaign_id": resolved.prereg.campaign_id,
        "preregistration": {
            "path": str(resolved.path),
            "file_sha256": resolved.file_sha256,
            "content_sha256": resolved.prereg.prereg_sha256,
            "introduced_commit": resolved.introduced_commit,
        },
        "valid_measurements": len(validated_complete_ordinals),
        "decision": None,
        "action": "HALT_CAMPAIGN_RETURN_TO_COORDINATION",
        "violation": violation,
        "attempted_ordinal": attempted_ordinal,
        "consumed": consumed,
        "durable_claim_count": durable_claim_count,
        "durable_terminal_count": durable_terminal_count,
        "key_freeze_authorized": False,
        "retry_or_replacement_authorized": False,
        "halt_evidence": halt_evidence,
        "validated_complete_ordinals": validated_complete_ordinals,
        "blockers": [],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return {**core, "report_content_sha256": canonical_sha256(core)}


def _governed_argv_shape_halt_report(**kwargs: Any) -> dict[str, Any]:
    """Retain the R70 helper name as a narrow compatibility alias."""

    return _governed_halt_report(**kwargs)


def audit_campaign(
    *,
    project_root: Path,
    prereg_path: Path,
    ledger_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    """Audit all twelve jobs; return a halt report on any closure invalidity."""

    try:
        resolved = load_committed_existence_prereg(
            project_root=project_root,
            prereg_path=prereg_path,
        )
        prereg = resolved.prereg
        canonical_ledger = Path(prereg.ledger_root).resolve(strict=True)
        if ledger_root.resolve(strict=True) != canonical_ledger:
            raise V5ExistenceProbeError("audit ledger differs from the frozen canonical ledger")
        with existence_campaign_audit_lock(
            ledger_root=canonical_ledger,
            resolved=resolved,
        ) as lock_token:
            ledger = read_existence_campaign_snapshot_locked(
                lock_token=lock_token,
                resolved=resolved,
            )
            attestation = validate_existence_preflight_attestation_locked(
                resolved=resolved,
                lock_token=lock_token,
            )
            if ledger.halt is not None:
                return _governed_halt_report(
                    resolved=resolved,
                    ledger=ledger,
                    attestation=attestation,
                    evidence_root=evidence_root,
                    lock_token=lock_token,
                )
            if (
                [claim.ordinal for claim in ledger.claims] != list(range(PROBE_COUNT))
                or [terminal.ordinal for terminal in ledger.terminals]
                != list(range(PROBE_COUNT))
                or ledger.complete is None
                or ledger.halt is not None
                or any(
                    not isinstance(terminal, ExistenceProbeTerminalReceiptV1)
                    for terminal in ledger.terminals
                )
            ):
                raise V5ExistenceProbeError(
                    "canonical ledger is not exactly twelve complete terminal measurements"
                )
            expected_ledger_members = {
                ".diagnostic-ledger.lock",
                "ledger-bootstrap-record.json",
                PREFLIGHT_ATTESTATION_NAME,
                "campaign-complete.json",
                *(f"claim-{ordinal:02d}.json" for ordinal in range(PROBE_COUNT)),
                *(f"terminal-{ordinal:02d}.json" for ordinal in range(PROBE_COUNT)),
            }
            _require_exact_members(
                canonical_ledger,
                expected=expected_ledger_members
                | set(ledger.publication_residue_names),
                label="canonical existence ledger",
            )

            frozen_evidence_root = Path(prereg.evidence_root).resolve(strict=True)
            supplied_evidence_root = evidence_root.resolve(strict=True)
            if supplied_evidence_root != frozen_evidence_root:
                raise V5ExistenceProbeError(
                    "audit evidence root differs from the frozen canonical evidence root"
                )
            canonical_evidence_root = _require_real_directory(
                supplied_evidence_root,
                within=supplied_evidence_root,
                owner=0,
                mode=0o555,
                label="existence evidence root",
            )
            expected_job_roots = [
                _job_root(
                    canonical_evidence_root,
                    ordinal=run.ordinal,
                    family_ordinal=run.family_ordinal,
                )
                for run in prereg.runs
            ]
            if len(expected_job_roots) != PROBE_COUNT or len(set(expected_job_roots)) != PROBE_COUNT:
                raise V5ExistenceProbeError("preregistered existence job roots are not distinct")
            _require_exact_members(
                canonical_evidence_root,
                expected={path.name for path in expected_job_roots},
                label="existence evidence root",
            )
            for path in expected_job_roots:
                _require_real_directory(
                    path,
                    within=canonical_evidence_root,
                    owner=0,
                    mode=0o555,
                    label=f"existence job root {path.name}",
                )

            raw_digests: set[str] = set()
            raw_paths: set[Path] = set()
            successes_by_ordinal = [False] * PROBE_COUNT
            run_audits: list[dict[str, Any]] = []

            for ordinal, (run, job_root) in enumerate(
                zip(prereg.runs, expected_job_roots, strict=True)
            ):
                if run.ordinal != ordinal:
                    raise V5ExistenceProbeError("existence run order differs from fixed ordinals")
                claim_path = canonical_ledger / f"claim-{ordinal:02d}.json"
                claim_raw = ledger.claim_bytes[ordinal]
                claim = ledger.claims[ordinal]
                if claim.run != run:
                    raise V5ExistenceProbeError(f"canonical claim differs at ordinal {ordinal}")
                host_authorization_raw, projected_authorization_raw = _read_authorization_pair(job_root)
                host_authorization = _authorization_from_bytes(
                    host_authorization_raw,
                    label=f"host authorization {ordinal}",
                )
                projected_authorization = _authorization_from_bytes(
                    projected_authorization_raw,
                    label=f"projected authorization {ordinal}",
                )
                if host_authorization != projected_authorization:
                    raise V5ExistenceProbeError(
                        f"typed projected authorization differs at ordinal {ordinal}"
                    )

                derived_path = job_root / "derived" / DERIVED_PROBE_NAME
                derived_raw = v4_auth.read_regular_file_once(derived_path)

                job_raw = v4_auth.read_regular_file_once(job_root / "job-receipt.json")
                job = ExistenceProbeJobReceiptV1.model_validate(
                    _strict_json_object(job_raw, label=f"existence job receipt {ordinal}")
                )
                canonical_job_raw = canonical_json_bytes(job.model_dump(mode="json")) + b"\n"
                if job_raw != canonical_job_raw:
                    raise V5ExistenceProbeError(
                        f"existence job receipt is not canonical at ordinal {ordinal}"
                    )
                terminal_raw = ledger.terminal_bytes[ordinal]
                terminal = ledger.terminals[ordinal]
                if not isinstance(terminal, ExistenceProbeTerminalReceiptV1):
                    raise V5ExistenceProbeError(
                        f"existence terminal receipt is incomplete at ordinal {ordinal}"
                    )
                canonical_terminal_raw = (
                    canonical_json_bytes(terminal.model_dump(mode="json")) + b"\n"
                )
                if terminal_raw != canonical_terminal_raw:
                    raise V5ExistenceProbeError(
                        f"existence terminal receipt is not canonical at ordinal {ordinal}"
                    )

                stage = prereg.stage_templates.templates[ordinal]
                expected_authorization = {
                    "campaign_id": prereg.campaign_id,
                    "stratum": run.stratum,
                    "family_ordinal": run.family_ordinal,
                    "condition": run.probe_condition,
                    "run_id": run.run_id,
                    "matched_key": run.matched_key,
                    "ordinal": ordinal,
                    "scene_seed": run.scene_seed,
                    "failure_seed": run.failure_seed,
                    "consumption_receipt_sha256": claim.receipt_sha256,
                    "prereg_sha256": prereg.prereg_sha256,
                    "source_sdf_sha256": run.sdf_sha256,
                    "source_supervision_sha256": run.supervision_sha256,
                    "source_urdf_sha256": prereg.controlled_urdf_sha256,
                    "upstream_v4_probe_sha256": prereg.upstream_v4_probe_sha256,
                    "derived_probe_sha256": prereg.derived_probe_sha256,
                    "container_image_id": prereg.container_image_id,
                    "stage_template_manifest_sha256": prereg.stage_templates.manifest_sha256,
                    "stage_usdc_sha256": stage.stage_usdc_sha256,
                    "stage_metrics_sha256": stage.stage_metrics_sha256,
                    "prereg_introduced_commit": resolved.introduced_commit,
                }
                authorization_payload = host_authorization.model_dump(mode="json")
                if any(
                    authorization_payload.get(field) != value
                    for field, value in expected_authorization.items()
                ):
                    raise V5ExistenceProbeError(
                        f"existence authorization cross-binding failed at ordinal {ordinal}"
                    )
                expected_job_fields = {
                    "schema_version": JOB_RECEIPT_SCHEMA_VERSION,
                    "status": JOB_RECEIPT_STATUS,
                    "campaign_id": prereg.campaign_id,
                    "run": run.model_dump(mode="json"),
                    "prereg_file_sha256": resolved.file_sha256,
                    "prereg_sha256": prereg.prereg_sha256,
                    "claim_path": str(claim_path),
                    "claim_sha256": sha256_bytes(claim_raw),
                    "host_authorization_path": str(
                        job_root / "authorization" / HOST_AUTHORIZATION_NAME
                    ),
                    "host_authorization_sha256": sha256_bytes(host_authorization_raw),
                    "projected_authorization_path": str(
                        job_root / "authorization" / PROJECTED_AUTHORIZATION_NAME
                    ),
                    "projected_authorization_sha256": sha256_bytes(
                        projected_authorization_raw
                    ),
                    "authorization_sha256": sha256_bytes(host_authorization_raw),
                    "derived_probe_sha256": prereg.derived_probe_sha256,
                    "source_snapshot": prereg.committed_source_snapshot.model_dump(mode="json"),
                    "image_id": prereg.container_image_id,
                    "stage_template": stage.model_dump(mode="json"),
                    "stage_template_manifest_sha256": prereg.stage_templates.manifest_sha256,
                    "probe_command_sha256": job.probe_command_sha256,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                }
                job_payload = job.model_dump(mode="json")
                if any(
                    job_payload.get(field) != value
                    for field, value in expected_job_fields.items()
                ):
                    raise V5ExistenceProbeError(
                        f"existence job receipt cross-binding failed at ordinal {ordinal}"
                    )
                expected_probe_command = build_existence_probe_command(
                    image_id=job.image_id,
                    gpu=job.gpu,
                    container_name=job.container_name,
                    snapshot_root=Path(v4_auth.CANONICAL_SOURCE_SNAPSHOT_ROOT)
                    / job.source_snapshot.inventory_sha256,
                    source_root=Path(job.source_root),
                    derived_probe=derived_path,
                    stage_root=Path(prereg.stage_templates.evidence_root)
                    / stage.relative_root,
                    probe_root=job_root / "probe",
                    authorization_projection=(
                        job_root / "authorization" / PROJECTED_AUTHORIZATION_NAME
                    ),
                    run=run,
                    sdf=Path(job.source_sdf_path),
                    supervision=Path(job.source_supervision_path),
                    urdf=Path(job.source_urdf_path),
                    scripted_bin_cell=job.scripted_bin_cell,
                    stage_template_manifest_sha256=(
                        prereg.stage_templates.manifest_sha256
                    ),
                    stage_metrics_sha256=stage.stage_metrics_sha256,
                    stage_command_sha256=stage.stage_command_sha256,
                    prereg_file_sha256=host_authorization.prereg_file_sha256,
                    prereg_sha256=host_authorization.prereg_sha256,
                    consumption_receipt_sha256=(
                        host_authorization.consumption_receipt_sha256
                    ),
                    authorization_ledger_root_sha256=(
                        host_authorization.ledger_root_sha256
                    ),
                    authorization_claim_path_sha256=(
                        host_authorization.claim_path_sha256
                    ),
                )
                if canonical_sha256(expected_probe_command) != job.probe_command_sha256:
                    raise V5ExistenceProbeError(
                        f"existence probe command changed at ordinal {ordinal}"
                    )
                if sha256_bytes(derived_raw) != prereg.derived_probe_sha256:
                    raise V5ExistenceProbeError(
                        f"existence derived probe bytes differ at ordinal {ordinal}"
                    )
                expected_authorization_bytes = (
                    canonical_json_bytes(host_authorization.model_dump(mode="json")) + b"\n"
                )
                if host_authorization_raw != expected_authorization_bytes:
                    raise V5ExistenceProbeError(
                        f"host authorization is not canonical at ordinal {ordinal}"
                    )
                expected_terminal_fields = {
                    "schema_version": TERMINAL_RECEIPT_SCHEMA_VERSION,
                    "campaign_id": prereg.campaign_id,
                    "run_id": run.run_id,
                    "ordinal": ordinal,
                    "family_ordinal": run.family_ordinal,
                    "claim_file_sha256": sha256_bytes(claim_raw),
                    "authorization_file_sha256": sha256_bytes(host_authorization_raw),
                    "job_receipt_semantic_sha256": job.receipt_sha256,
                    "preconsumption_checks_complete": True,
                    "probe_started": True,
                    "probe_returncode": 0,
                    "byte_closure_verified": "VERIFIED",
                    "status": TERMINAL_COMPLETE_STATUS,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                }
                terminal_payload = terminal.model_dump(mode="json")
                if any(
                    terminal_payload.get(field) != value
                    for field, value in expected_terminal_fields.items()
                ):
                    raise V5ExistenceProbeError(
                        f"existence terminal receipt cross-binding failed at ordinal {ordinal}"
                    )
                complete_evidence = validate_complete_existence_probe_evidence(
                    resolved=resolved,
                    terminal=terminal,
                    lock_token=lock_token,
                )
                if complete_evidence.job_root != job_root:
                    raise V5ExistenceProbeError(
                        f"shared evidence validator selected the wrong job at ordinal {ordinal}"
                    )
                raw = complete_evidence.raw_evidence
                raw_bytes = complete_evidence.raw_evidence_bytes
                raw_path = complete_evidence.job_root / "probe" / RAW_EVIDENCE_NAME
                raw_resolved = raw_path.resolve(strict=True)
                raw_digest = sha256_bytes(raw_bytes)
                if raw_resolved in raw_paths or raw_digest in raw_digests:
                    raise V5ExistenceProbeError("existence campaign repeats raw evidence")
                raw_paths.add(raw_resolved)
                raw_digests.add(raw_digest)
                if terminal.raw_evidence_sha256 != raw_digest:
                    raise V5ExistenceProbeError(
                        f"terminal raw binding differs at ordinal {ordinal}"
                    )
                if complete_evidence.job_receipt != job or (
                    complete_evidence.job_receipt_bytes != job_raw
                ):
                    raise V5ExistenceProbeError(
                        f"shared job receipt authority differs at ordinal {ordinal}"
                    )
                if complete_evidence.authorization != host_authorization or (
                    complete_evidence.authorization_bytes != host_authorization_raw
                ):
                    raise V5ExistenceProbeError(
                        f"shared authorization authority differs at ordinal {ordinal}"
                    )
                if raw.authorization != complete_evidence.authorization:
                    raise V5ExistenceProbeError(
                        f"embedded raw authorization differs at ordinal {ordinal}"
                    )
                if raw.actuation_probe_source_sha256 != prereg.derived_probe_sha256:
                    raise V5ExistenceProbeError(
                        f"raw derived-probe binding differs at ordinal {ordinal}"
                    )
                if not raw.terminal_measurement_valid:
                    raise V5ExistenceProbeError(
                        f"existence raw measurement is invalid at ordinal {ordinal}"
                    )
                if raw.teacher_used or raw.privileged_truth_policy_input:
                    raise V5ExistenceProbeError(
                        f"existence raw evidence uses forbidden information at ordinal {ordinal}"
                    )

                success = existence_probe_terminal_success(raw)
                successes_by_ordinal[ordinal] = success
                run_audits.append(
                    {
                        "ordinal": ordinal,
                        "run_id": run.run_id,
                        "family_ordinal": run.family_ordinal,
                        "stratum": run.stratum,
                        "status": "VALID_TERMINAL_MEASUREMENT",
                        "terminal_success": success,
                        "terminal_execution_status": raw.terminal_execution_status,
                        "physical_action_executed": raw.physical_action_executed,
                        "pregrasp_ik_passed": raw.pregrasp_ik_passed,
                        "contact_gate_passed": raw.contact_gate_passed,
                        "public_predicates": raw.public_predicates,
                        "collision_or_safety_violations": raw.collision_or_safety_violations,
                        "claim_sha256": sha256_bytes(claim_raw),
                        "host_authorization_sha256": sha256_bytes(host_authorization_raw),
                        "projected_authorization_sha256": sha256_bytes(
                            projected_authorization_raw
                        ),
                        "job_receipt_sha256": sha256_bytes(job_raw),
                        "terminal_receipt_sha256": sha256_bytes(terminal_raw),
                        "raw_evidence_sha256": raw_digest,
                    }
                )

            if ledger.complete_bytes is None:
                raise V5ExistenceProbeError(
                    "complete campaign marker lacks canonical durable bytes"
                )
            decision = evaluate_existence_outcomes(
                prereg=prereg,
                successes_by_ordinal=successes_by_ordinal,
            )
            core = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "status": "PASS_COMPLETE_EXISTENCE_PROBE_AUDIT",
                "campaign_id": prereg.campaign_id,
                "preregistration": {
                    "path": str(resolved.path),
                    "file_sha256": resolved.file_sha256,
                    "content_sha256": prereg.prereg_sha256,
                    "introduced_commit": resolved.introduced_commit,
                },
                "valid_measurements": PROBE_COUNT,
                "decision": decision,
                "action": decision["action"],
                "key_freeze_authorized": decision["key_freeze_authorized"],
                "fixed_order": True,
                "canonical_ledger_root": str(canonical_ledger),
                "canonical_evidence_root": str(canonical_evidence_root),
                "campaign_complete_file_sha256": sha256_bytes(
                    ledger.complete_bytes
                ),
                "campaign_complete_semantic_sha256": ledger.complete.marker_sha256,
                "canonical_claims": PROBE_COUNT,
                "distinct_job_roots": PROBE_COUNT,
                "distinct_raw_records": PROBE_COUNT,
                "retry_or_replacement_authorized": False,
                "runs": run_audits,
                "blockers": [],
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            return {**core, "report_content_sha256": canonical_sha256(core)}
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
        TerminalDiagnosticError,
        V5ExistenceProbeError,
        v4_auth.CollectionAuthorizationError,
    ) as error:
        return _halt_report(blocker=f"{type(error).__name__}: {error}")


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# M2C V5 existence-probe audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Action: `{report['action']}`",
        f"- Valid measurements: `{report['valid_measurements']}/{PROBE_COUNT}`",
        f"- Retry/replacement authorized: `{report['retry_or_replacement_authorized']}`",
    ]
    decision = report.get("decision")
    if isinstance(decision, Mapping):
        lines.extend(
            [
                f"- Successes: `{decision['successes']}/{PROBE_COUNT}`",
                f"- Floor cleared: `{decision['floor_cleared']}`",
                f"- Third-regime surprise: `{decision['exact_binomial']['surprise_triggered']}`",
                f"- Severe inter-stratum divergence: "
                f"`{decision['severe_inter_stratum_divergence']}`",
                "",
                "## Preregistered strata",
                "",
                "| stratum | valid | successes | fraction |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for name in STRATUM_ORDER:
            row = decision["per_stratum"][name]
            lines.append(
                f"| {name} | {row['valid_measurements']} | {row['successes']} | "
                f"{row['success_fraction']:.0%} |"
            )
    halt_evidence = report.get("halt_evidence")
    if isinstance(halt_evidence, Mapping):
        lines.extend(
            [
                "",
                "## Governed campaign halt",
                "",
                f"- Violation: `{report['violation']}`",
                f"- Attempted ordinal: `{report['attempted_ordinal']}`",
                f"- Consumed: `{report['consumed']}`",
                f"- Durable claims: `{report['durable_claim_count']}`",
                f"- Durable terminals: `{report['durable_terminal_count']}`",
                f"- Consumption-ledger state SHA-256: "
                f"`{halt_evidence['consumption_ledger_state_sha256']}`",
                f"- Attested preflight bundle SHA-256: "
                f"`{halt_evidence['attested_preflight_bundle_sha256']}`",
                f"- First argv divergence index: "
                f"`{halt_evidence['first_divergence_index']}`",
                f"- Candidate identity material: "
                f"`{halt_evidence['candidate_identity_material_kind']}`",
                f"- PRE_LAUNCH_HOST terminal SHA-256: "
                f"`{halt_evidence['prelaunch_host_terminal_receipt_sha256']}`",
            ]
        )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in report.get("blockers", []))
    if not report.get("blockers"):
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise V5ExistenceProbeError("short existence audit write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()
    report = audit_campaign(
        project_root=args.project_root.resolve(strict=True),
        prereg_path=args.prereg,
        ledger_root=args.ledger_root,
        evidence_root=args.evidence_root.resolve(strict=True),
    )
    if args.output_json is not None:
        _write_create_only(
            args.output_json,
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n",
        )
    if args.output_md is not None:
        _write_create_only(args.output_md, render_markdown(report).encode())
    print(
        json.dumps(
            {
                "status": report["status"],
                "action": report["action"],
                "key_freeze_authorized": report["key_freeze_authorized"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "PASS_COMPLETE_EXISTENCE_PROBE_AUDIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
