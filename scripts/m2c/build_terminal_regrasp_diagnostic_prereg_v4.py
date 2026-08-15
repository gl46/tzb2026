#!/usr/bin/env python3
"""Build the fresh ADR-0026 V4 terminal-diagnostic preregistration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from m2c import build_terminal_regrasp_diagnostic_prereg_v3 as v3_builder
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
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v4 import (
    CAMPAIGN_ID,
    DIRECT_PUBLIC_RGBD_CONTRACT,
    EXCLUSION_PATHS,
    IMPLEMENTATION_PATHS,
    LEDGER_NAMESPACE,
    M2CTerminalRegraspDiagnosticPreregV4,
    PREREG_REPOSITORY_PATH,
    V3_INCOMPLETE_REPORT_PATH,
    V3_PREREG_PATH,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = Path(PREREG_REPOSITORY_PATH)
LEDGER_ROOT = "/var/tmp/xh-data/isaac-industrial/m2c/s4-terminal-regrasp-diagnostic-ledger-v4"
TEMPLATE_PATH = "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
CANDIDATE_BASE_SEED_START = 300100


class DiagnosticV4PreregBuildError(ValueError):
    """Frozen inputs cannot produce the V4 preregistration."""


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
        raw = v3_builder._git_blob(project_root, commit, path)  # noqa: SLF001
        bindings.append({"path": path, "sha256": v3_builder._sha256(raw)})  # noqa: SLF001
        payload = v3_builder._json_object(raw, label=path)  # noqa: SLF001
        for record in v3_builder._walk_dicts(payload):  # noqa: SLF001
            for axis in axes:
                value = record.get(axis)
                if value is not None:
                    axes[axis].add(int(value) if axis != "matched_key" else str(value))
    if any(not values for values in axes.values()):
        raise DiagnosticV4PreregBuildError("external identity inventory is incomplete")
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
                        sdf_sha256=v3_builder._sha256(sdf),  # noqa: SLF001
                        supervision_sha256=v3_builder._sha256(  # noqa: SLF001
                            supervision
                        ),
                    )
                )
            if not any(record[axis] in external[axis] for record in candidate for axis in external):
                runs.extend(candidate)
        source_seed += 1
        if source_seed >= CANDIDATE_BASE_SEED_START + 10_000:
            raise DiagnosticV4PreregBuildError("cannot find twelve fresh V4 seeds")
    return runs


def build_prereg(*, project_root: Path, source_commit: str = "HEAD") -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    commit = (
        v3_builder._git(  # noqa: SLF001
            root, "rev-parse", f"{source_commit}^{{commit}}"
        )
        .decode()
        .strip()
    )
    adr = v3_builder._git_blob(root, commit, ADR_PATH)  # noqa: SLF001
    if v3_builder._sha256(adr) != ADR_SHA256:  # noqa: SLF001
        raise DiagnosticV4PreregBuildError("accepted ADR-0026 bytes changed")
    if (
        v3_builder._git_blob(  # noqa: SLF001
            root, ADR_INTRODUCED_COMMIT, ADR_PATH
        )
        != adr
    ):
        raise DiagnosticV4PreregBuildError("accepted ADR-0026 binding changed")
    for path in IMPLEMENTATION_PATHS:
        current = (root / path).read_bytes()
        if current != v3_builder._git_blob(root, commit, path):  # noqa: SLF001
            raise DiagnosticV4PreregBuildError(
                f"V4 implementation is not exact source commit: {path}"
            )
    snapshot, _payloads = v4_auth._source_snapshot_payloads(  # noqa: SLF001
        root, commit=commit
    )
    external, exclusions = _external_identities(project_root=root, commit=commit)
    template = v3_builder._git_blob(root, commit, TEMPLATE_PATH).decode()  # noqa: SLF001
    runs = _select_runs(template=template, external=external)
    v3_report_raw = v3_builder._git_blob(  # noqa: SLF001
        root, commit, V3_INCOMPLETE_REPORT_PATH
    )
    v3_report = v3_builder._json_object(  # noqa: SLF001
        v3_report_raw, label=V3_INCOMPLETE_REPORT_PATH
    )
    failed = v3_report.get("failed_run", {})
    if (
        v3_report.get("status") != "BLOCKED_INCOMPLETE_INHERITED_V4_CHAIN_PRECONDITION"
        or v3_report.get("valid_terminal_measurements") != 0
        or failed.get("stage_completed") is not True
        or failed.get("kit_started") is not True
        or failed.get("controller_initialized") is not True
        or failed.get("neutral_reset_and_open_gripper_initialization_executed") is not True
        or failed.get("terminal_primitive_called") is not False
        or failed.get("terminal_regrasp_action_outcome") != "NOT_AVAILABLE"
    ):
        raise DiagnosticV4PreregBuildError("V3 invalidation evidence changed")
    core: dict[str, Any] = {
        "schema_version": "M2CTerminalRegraspDiagnosticPreregV4",
        "status": ("FROZEN_AFTER_V3_PRE_TERMINAL_INVALIDATION_BEFORE_ANY_VALID_DIAGNOSTIC_OUTCOME"),
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
        "prior_v3_invalidation": {
            "preregistration": {
                "path": V3_PREREG_PATH,
                "sha256": v3_builder._sha256(  # noqa: SLF001
                    v3_builder._git_blob(root, commit, V3_PREREG_PATH)  # noqa: SLF001
                ),
            },
            "incomplete_audit": {
                "path": V3_INCOMPLETE_REPORT_PATH,
                "sha256": v3_builder._sha256(v3_report_raw),  # noqa: SLF001
            },
            "valid_terminal_measurements": 0,
            "stage_completed": True,
            "kit_started": True,
            "controller_initialized": True,
            "neutral_reset_and_open_gripper_initialization_executed": True,
            "terminal_primitive_called": False,
            "terminal_regrasp_action_outcome": "NOT_AVAILABLE",
            "v3_claim_reused": False,
            "v3_identity_reused": False,
        },
        "restart_basis": (
            "NEW_CAMPAIGN_ALL_FRESH_IDENTITIES_NO_V1_V2_OR_V3_CLAIM_OR_IDENTITY_REUSE"
        ),
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
        "direct_branch_precedes_inherited_v4_chain": True,
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
            {
                "path": path,
                "sha256": v3_builder._sha256(  # noqa: SLF001
                    v3_builder._git_blob(root, commit, path)  # noqa: SLF001
                ),
            }
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
    M2CTerminalRegraspDiagnosticPreregV4.model_validate(prereg)
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
                raise OSError("failed to publish V4 diagnostic preregistration")
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
