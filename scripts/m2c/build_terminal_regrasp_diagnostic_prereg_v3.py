#!/usr/bin/env python3
"""Build the fresh ADR-0026 V3 terminal-diagnostic preregistration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

from m2c.s4_scene_family import materialize_scene
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ADR_INTRODUCED_COMMIT,
    ADR_PATH,
    ADR_SHA256,
    CONDITION_INDEX,
    CONTROLLED_URDF_SHA256,
    DIAGNOSTIC_CONDITIONS,
    FIXED_ANCHOR_XY_M,
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    RETAINED_BLOCKER_ENTITY,
    RETAINED_BLOCKER_SURFACE_GAP_M,
    RUNS_PER_CONDITION,
    SCRIPTED_BLOCKER_ENTITY,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    PARKING_XY_M,
    UPSTREAM_V4_PROBE_SHA256,
    materialize_diagnostic_scene_v2,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    CAMPAIGN_ID,
    DIRECT_PUBLIC_RGBD_CONTRACT,
    EXCLUSION_PATHS,
    IMPLEMENTATION_PATHS,
    LEDGER_NAMESPACE,
    M2CTerminalRegraspDiagnosticPreregV3,
    PREREG_REPOSITORY_PATH,
    V2_INCOMPLETE_REPORT_PATH,
    V2_PREREG_PATH,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = Path(PREREG_REPOSITORY_PATH)
LEDGER_ROOT = "/var/tmp/xh-data/isaac-industrial/m2c/s4-terminal-regrasp-diagnostic-ledger-v3"
TEMPLATE_PATH = "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
CANDIDATE_BASE_SEED_START = 280100


class DiagnosticV3PreregBuildError(ValueError):
    """Frozen inputs cannot produce the V3 preregistration."""


def _git(project_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise DiagnosticV3PreregBuildError(
            f"git {' '.join(args)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def _git_blob(project_root: Path, commit: str, path: str) -> bytes:
    return _git(project_root, "show", f"{commit}:{path}")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiagnosticV3PreregBuildError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise DiagnosticV3PreregBuildError(f"{label} is not a JSON object")
    return value


def _walk_dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _external_identities(
    *, project_root: Path, commit: str
) -> tuple[dict[str, set[Any]], list[dict[str, str]]]:
    axes: dict[str, set[Any]] = {
        "scene_seed": set(),
        "failure_seed": set(),
        "matched_key": set(),
    }
    bindings: list[dict[str, str]] = []
    for path in EXCLUSION_PATHS:
        raw = _git_blob(project_root, commit, path)
        bindings.append({"path": path, "sha256": _sha256(raw)})
        payload = _json_object(raw, label=path)
        for record in _walk_dicts(payload):
            for axis in axes:
                value = record.get(axis)
                if value is not None:
                    axes[axis].add(int(value) if axis != "matched_key" else str(value))
    if any(not values for values in axes.values()):
        raise DiagnosticV3PreregBuildError("external identity inventory is incomplete")
    return axes, bindings


def _run_record(
    *,
    ordinal: int,
    source_base_seed: int,
    condition: str,
    sdf_sha256: str,
    supervision_sha256: str,
) -> dict[str, Any]:
    condition_index = CONDITION_INDEX[condition]
    scene_seed = source_base_seed * 10 + condition_index
    identity: dict[str, Any] = {
        "ordinal": ordinal,
        "source_base_seed": source_base_seed,
        "scene_seed": scene_seed,
        "failure_seed": scene_seed * 10 + 7,
        "condition": condition,
        "condition_index": condition_index,
        "probe_mode": (
            "FULL_V4_PREAMBLE_TERMINAL" if condition == "C3_FULL_V4" else "DIRECT_TERMINAL"
        ),
        "anchor_xy_m": list(FIXED_ANCHOR_XY_M),
        "sdf_sha256": sdf_sha256,
        "supervision_sha256": supervision_sha256,
        "expected_local_blockers": {
            "C1_NO_BLOCKER": [],
            "C2_RETAINED_BLOCKER": [RETAINED_BLOCKER_ENTITY],
            "C3_FULL_V4": [SCRIPTED_BLOCKER_ENTITY, RETAINED_BLOCKER_ENTITY],
        }[condition],
        "terminal_target_blocker_surface_gap_m": (
            None if condition == "C1_NO_BLOCKER" else RETAINED_BLOCKER_SURFACE_GAP_M
        ),
        "retry_authorized": False,
        "replacement_authorized": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    run_id = f"m2c-s4-terminal-diagnostic-{canonical_sha256(identity)}"
    return {**identity, "run_id": run_id, "matched_key": run_id}


def _select_runs(*, template: str, external: Mapping[str, set[Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    source_seed = CANDIDATE_BASE_SEED_START
    while len(runs) < RUNS_PER_CONDITION * len(DIAGNOSTIC_CONDITIONS):
        full = materialize_scene(template, source_seed, FIXED_ANCHOR_XY_M)
        if full is not None:
            candidate: list[dict[str, Any]] = []
            for condition in DIAGNOSTIC_CONDITIONS:
                scene_seed = source_seed * 10 + CONDITION_INDEX[condition]
                sdf, supervision = materialize_diagnostic_scene_v2(
                    full_v4_sdf_bytes=full[0],
                    full_v4_supervision_bytes=full[1],
                    scene_seed=scene_seed,
                    source_base_seed=source_seed,
                    condition=condition,
                )
                candidate.append(
                    _run_record(
                        ordinal=len(runs) + len(candidate),
                        source_base_seed=source_seed,
                        condition=condition,
                        sdf_sha256=_sha256(sdf),
                        supervision_sha256=_sha256(supervision),
                    )
                )
            if not any(record[axis] in external[axis] for record in candidate for axis in external):
                runs.extend(candidate)
        source_seed += 1
        if source_seed >= CANDIDATE_BASE_SEED_START + 10_000:
            raise DiagnosticV3PreregBuildError("cannot find twelve fresh V3 seeds")
    return runs


def build_prereg(*, project_root: Path, source_commit: str = "HEAD") -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    commit = _git(root, "rev-parse", f"{source_commit}^{{commit}}").decode().strip()
    if _sha256(_git_blob(root, commit, ADR_PATH)) != ADR_SHA256:
        raise DiagnosticV3PreregBuildError("accepted ADR-0026 bytes changed")
    if _git_blob(root, ADR_INTRODUCED_COMMIT, ADR_PATH) != _git_blob(root, commit, ADR_PATH):
        raise DiagnosticV3PreregBuildError("accepted ADR-0026 binding changed")
    for path in IMPLEMENTATION_PATHS:
        current = (root / path).read_bytes()
        if current != _git_blob(root, commit, path):
            raise DiagnosticV3PreregBuildError(
                f"V3 implementation is not exact source commit: {path}"
            )
    snapshot, _payloads = v4_auth._source_snapshot_payloads(  # noqa: SLF001
        root, commit=commit
    )
    external, exclusions = _external_identities(project_root=root, commit=commit)
    template = _git_blob(root, commit, TEMPLATE_PATH).decode("utf-8")
    runs = _select_runs(template=template, external=external)
    v2_report_raw = _git_blob(root, commit, V2_INCOMPLETE_REPORT_PATH)
    v2_report = _json_object(v2_report_raw, label=V2_INCOMPLETE_REPORT_PATH)
    failed = v2_report.get("failed_run", {})
    if (
        v2_report.get("status") != "BLOCKED_INCOMPLETE_PUBLIC_CAPTURE_SETUP_MISMATCH"
        or v2_report.get("valid_terminal_measurements") != 0
        or failed.get("stage_completed") is not True
        or failed.get("kit_started") is not True
        or failed.get("controller_initialized") is not False
        or failed.get("terminal_primitive_called") is not False
        or failed.get("physical_action_outcome") != "NOT_AVAILABLE"
    ):
        raise DiagnosticV3PreregBuildError("V2 invalidation evidence changed")
    core: dict[str, Any] = {
        "schema_version": "M2CTerminalRegraspDiagnosticPreregV3",
        "status": ("FROZEN_AFTER_V2_PRE_TERMINAL_INVALIDATION_BEFORE_ANY_VALID_DIAGNOSTIC_OUTCOME"),
        "repository_relative_path": PREREG_PATH.as_posix(),
        "introduction_commit_paths": [PREREG_PATH.as_posix()],
        "campaign_id": CAMPAIGN_ID,
        "governing_adr": {
            "path": ADR_PATH,
            "sha256": ADR_SHA256,
            "introduced_commit": ADR_INTRODUCED_COMMIT,
            "status": "ACCEPTED_HUMAN_ADR",
        },
        "written_date_asia_shanghai": "2026-08-15",
        "diagnostic_outcomes_observed_before_freeze": False,
        "prior_v2_invalidation": {
            "preregistration": {
                "path": V2_PREREG_PATH,
                "sha256": _sha256(_git_blob(root, commit, V2_PREREG_PATH)),
            },
            "incomplete_audit": {
                "path": V2_INCOMPLETE_REPORT_PATH,
                "sha256": _sha256(v2_report_raw),
            },
            "valid_terminal_measurements": 0,
            "stage_completed": True,
            "kit_started": True,
            "controller_initialized": False,
            "terminal_primitive_called": False,
            "physical_action_outcome": "NOT_AVAILABLE",
            "v2_claim_reused": False,
            "v2_identity_reused": False,
        },
        "restart_basis": ("NEW_CAMPAIGN_ALL_FRESH_IDENTITIES_NO_V1_OR_V2_CLAIM_OR_IDENTITY_REUSE"),
        "collection_halted": True,
        "training_collection_authorized": False,
        "diagnostic_only": True,
        "fixed_order": True,
        "paired_source_seeds": True,
        "runs_per_condition": RUNS_PER_CONDITION,
        "total_runs": len(runs),
        "retry_authorized": False,
        "replacement_authorized": False,
        "terminal_only_estimand": True,
        "unchanged_six_object_scene_contract": True,
        "direct_public_rgbd_setup_contract": DIRECT_PUBLIC_RGBD_CONTRACT,
        "public_rgbd_pixels_tracker_predicates_unchanged": True,
        "no_gate_threshold_b0_or_predicate_change": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "container_image": ISAAC_IMAGE,
        "container_image_id": ISAAC_IMAGE_ID,
        "upstream_v4_probe_sha256": UPSTREAM_V4_PROBE_SHA256,
        "controlled_urdf_sha256": CONTROLLED_URDF_SHA256,
        "ledger_root": LEDGER_ROOT,
        "ledger_namespace": LEDGER_NAMESPACE,
        "implementation_commit": commit,
        "committed_source_snapshot": snapshot.model_dump(mode="json"),
        "implementation_bindings": [
            {"path": path, "sha256": _sha256(_git_blob(root, commit, path))}
            for path in IMPLEMENTATION_PATHS
        ],
        "exclusion_sources": exclusions,
        "external_identity_digest": canonical_sha256(
            {axis: sorted(values) for axis, values in external.items()}
        ),
        "parking_xy_m": {key: list(value) for key, value in PARKING_XY_M.items()},
        "runs": runs,
        "decision_tree": {
            "schema_version": "M2CTerminalRegraspDecisionTreeV1",
            "success_definition": (
                "PHYSICAL_LIFTED_AND_PUBLIC_GRASPED_TRUE_AND_LIFTED_TRUE_AND_ZERO_SAFETY_VIOLATIONS"
            ),
            "denominator_policy": "EXACTLY_12_VALID_TERMINAL_MEASUREMENTS_PER_CONDITION",
            "incomplete_policy": "NO_BRANCH_UNTIL_ALL_36_RUNS_HAVE_VALID_MEASUREMENTS",
            "r1_c1_min_successes": 9,
            "r1_c3_max_successes": 3,
            "r2_c1_min_failures": 6,
            "r3_policy": "ALL_COMPLETE_OUTCOMES_NOT_MATCHING_R1_OR_R2",
            "no_retry_or_replacement": True,
        },
    }
    prereg = {**core, "prereg_sha256": canonical_sha256(core)}
    M2CTerminalRegraspDiagnosticPreregV3.model_validate(prereg)
    return prereg


def prereg_bytes(prereg: Mapping[str, Any]) -> bytes:
    return (json.dumps(prereg, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("failed to publish V3 diagnostic preregistration")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--source-commit", default="HEAD")
    parser.add_argument("--output", type=Path, default=PREREG_PATH)
    args = parser.parse_args()
    prereg = build_prereg(
        project_root=args.project_root,
        source_commit=args.source_commit,
    )
    write_create_only(args.output, prereg_bytes(prereg))
    print(
        json.dumps(
            {
                "status": prereg["status"],
                "runs": len(prereg["runs"]),
                "prereg_sha256": prereg["prereg_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
