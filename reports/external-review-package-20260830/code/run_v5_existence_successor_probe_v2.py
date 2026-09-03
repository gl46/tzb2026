#!/usr/bin/env python3
"""Run exactly one consumed V5 existence successor probe."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __name__ == "__main__" and not sys.dont_write_bytecode:
    raise SystemExit("formal successor execution requires Python bytecode writes disabled")

from m2c import run_v5_existence_probe_v1 as inherited_runner
from m2c.derive_v5_existence_successor_probe_v2 import (
    derive_v5_existence_successor_probe_bytes,
)
from m2c.run_terminal_regrasp_diagnostic import RUNTIME_GID, RUNTIME_UID
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    canonical_sha256,
    sha256_bytes,
)
from xh_agent.policy.qrm_lite.v5_existence_probe_campaign_v1 import (
    ARGV_PRECONSUMPTION_IDENTITY_SENTINEL,
    existence_inventory_commitment_sha256,
)
from xh_agent.policy.qrm_lite.v5_existence_successor_campaign_v2 import (
    CANONICAL_SOURCE_SNAPSHOT_ROOT,
    SUCCESSOR_CONSOLE_NAME,
    SUCCESSOR_CONTAINER_AUTHORIZATION_PATH,
    SUCCESSOR_CONTAINER_ID_NAME,
    SUCCESSOR_CONTAINER_RECEIPT_NAME,
    SUCCESSOR_DERIVED_PROBE_NAME,
    SUCCESSOR_EVIDENCE_ROOT,
    SUCCESSOR_HOST_AUTHORIZATION_NAME,
    SUCCESSOR_JOB_RECEIPT_NAME,
    SUCCESSOR_LEDGER_ROOT,
    SUCCESSOR_LIFECYCLE_CAPTURE_NAME,
    SUCCESSOR_PHYSICAL_ORDINALS,
    SUCCESSOR_PREREG_REPOSITORY_PATH,
    SUCCESSOR_PROJECTED_AUTHORIZATION_NAME,
    SUCCESSOR_R3_COMBINED_COMPLETION_NAME,
    SUCCESSOR_R3_EVIDENCE_ROOT,
    SUCCESSOR_R3_LEDGER_ROOT,
    SUCCESSOR_R3_PHYSICAL_ORDINALS,
    SUCCESSOR_R3_SOURCE_ROOT,
    SUCCESSOR_RAW_EVIDENCE_NAME,
    M2CV5ExistenceSuccessorError,
    bind_successor_claim_to_raw_session_locked,
    bind_successor_r3_claim_to_physical_session_locked,
    build_native_effective_predecessor,
    build_successor_job_receipt,
    build_successor_job_receipt_v3,
    build_successor_lifecycle_capture,
    build_successor_lifecycle_capture_v3,
    build_successor_native_effective_predecessor_v3,
    build_successor_probe_command,
    build_successor_terminal_receipt,
    build_successor_terminal_receipt_v3,
    canonical_successor_authorization_bytes,
    canonical_successor_container_receipt_bytes,
    canonical_successor_job_receipt_bytes,
    canonical_successor_job_receipt_v3_bytes,
    canonical_successor_lifecycle_capture_bytes,
    canonical_successor_lifecycle_capture_v3_bytes,
    canonical_successor_runtime_authorization_v3_bytes,
    durable_successor_claim_state_locked,
    durable_successor_preflight_argv_shape_locked,
    durable_successor_r3_preflight_argv_shape_locked,
    existence_argv_stable_digest_allowlist,
    existence_docker_command_self_sha256,
    load_committed_successor_prereg,
    parse_successor_container_receipt_bytes,
    parse_successor_job_receipt_bytes,
    parse_successor_job_receipt_v3_bytes,
    parse_successor_lifecycle_capture_bytes,
    parse_successor_lifecycle_capture_v3_bytes,
    publish_successor_authorization_projection,
    publish_successor_claim_locked,
    publish_successor_create_only,
    publish_successor_r3_claim_locked,
    publish_successor_r3_terminal_locked,
    publish_successor_terminal_locked,
    read_durable_successor_claim_locked,
    read_durable_successor_preflight_attestation_locked,
    read_successor_campaign_snapshot_locked,
    read_successor_r3_campaign_snapshot_locked,
    read_successor_scripted_bin_cell,
    read_successor_scripted_bin_cell_at,
    successor_campaign_lifecycle_lock,
    successor_r3_campaign_lifecycle_lock,
    validate_complete_successor_evidence,
    validate_successor_authorization_for_runtime,
    validate_successor_probe_argv_binding,
    validate_successor_runtime_authorization_v3_for_runtime,
    validate_successor_source_tree,
    validate_successor_source_tree_at,
    verify_successor_stage_template_bundle,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class _PreparedSuccessorRun:
    root: Path
    resolved: Any
    run: Any
    stage_root: Path
    stage: Any
    source_snapshot_root: Path
    source_root: Path
    evidence_root: Path
    ledger_root: Path
    sdf: Path
    supervision: Path
    urdf: Path
    scripted_bin_cell: int
    derived_bytes: bytes
    derived_sha256: str


def _require_formal_root() -> None:
    if os.geteuid() != 0:
        raise M2CV5ExistenceSuccessorError(
            "formal successor execution must run as root"
        )


def _require_successor_runtime_identity(image_id: str) -> None:
    if RUNTIME_UID != 1234 or RUNTIME_GID != 1234:
        raise M2CV5ExistenceSuccessorError(
            "successor runtime numeric identity differs from the freeze"
        )
    inherited_runner._require_image_runtime_user(image_id)


def _prepare_before_claim(args: argparse.Namespace) -> _PreparedSuccessorRun:
    if not sys.dont_write_bytecode:
        raise M2CV5ExistenceSuccessorError(
            "formal successor execution requires Python bytecode writes disabled"
        )
    _require_formal_root()
    r3 = getattr(args, "r3", False)
    container_prefix = "m2c-v5-existence-r3" if r3 else "m2c-v5-existence"
    physical_ordinals = (
        SUCCESSOR_R3_PHYSICAL_ORDINALS if r3 else SUCCESSOR_PHYSICAL_ORDINALS
    )
    if (
        not isinstance(r3, bool)
        or not isinstance(args.gpu, int)
        or isinstance(args.gpu, bool)
        or args.gpu < 0
        or not isinstance(args.timeout_s, (int, float))
        or isinstance(args.timeout_s, bool)
        or not math.isfinite(float(args.timeout_s))
        or float(args.timeout_s) <= 0.0
        or args.container_prefix != container_prefix
        or args.image != ISAAC_IMAGE
    ):
        raise M2CV5ExistenceSuccessorError(
            "successor physical runtime arguments differ from the freeze"
        )

    root = args.project_root.resolve(strict=True)
    resolved = load_committed_successor_prereg(
        project_root=root,
        prereg_path=args.prereg,
    )
    prereg = resolved.prereg
    selected = [run for run in prereg.run_plan.runs if run.run_id == args.run_id]
    if len(selected) != 1 or selected[0].ordinal not in physical_ordinals:
        raise M2CV5ExistenceSuccessorError(
            "successor run selection is not one remaining physical ordinal"
        )
    run = selected[0]
    if prereg.run_plan.runs[run.ordinal] != run:
        raise M2CV5ExistenceSuccessorError(
            "successor selected run differs from its frozen ordinal"
        )
    expected_source_root = (
        Path(SUCCESSOR_R3_SOURCE_ROOT) if r3 else Path(prereg.source_root)
    )
    expected_evidence_root = (
        Path(SUCCESSOR_R3_EVIDENCE_ROOT) if r3 else Path(prereg.evidence_root)
    )
    expected_ledger_root = (
        Path(SUCCESSOR_R3_LEDGER_ROOT) if r3 else Path(prereg.ledger_root)
    )
    if (
        (not r3 and prereg.evidence_root != SUCCESSOR_EVIDENCE_ROOT)
        or (not r3 and prereg.ledger_root != SUCCESSOR_LEDGER_ROOT)
        or Path(args.source_root).absolute() != expected_source_root
        or Path(args.output_root).absolute() != expected_evidence_root
        or Path(args.ledger_root).absolute() != expected_ledger_root
    ):
        raise M2CV5ExistenceSuccessorError(
            "successor physical roots differ from preregistration"
        )

    source_root = (
        validate_successor_source_tree_at(
            prereg=prereg,
            source_root=expected_source_root,
        )
        if r3
        else validate_successor_source_tree(prereg=prereg)
    )
    evidence_root = inherited_runner._require_root_owned_directory(
        args.output_root,
        mode=0o700,
        label="successor evidence root",
    )
    ledger_root = inherited_runner._require_root_owned_directory(
        args.ledger_root,
        mode=0o700,
        label="successor ledger root",
    )
    if evidence_root != expected_evidence_root.resolve(strict=True):
        raise M2CV5ExistenceSuccessorError(
            "successor evidence root is not the canonical frozen root"
        )
    if ledger_root != expected_ledger_root.resolve(strict=True):
        raise M2CV5ExistenceSuccessorError(
            "successor ledger root is not the canonical frozen root"
        )

    sdf = inherited_runner._require_root_owned_source_file(
        args.sdf,
        source_root=source_root,
        expected_sha256=run.sdf_sha256,
        label="successor SDF",
    )
    supervision = inherited_runner._require_root_owned_source_file(
        args.supervision,
        source_root=source_root,
        expected_sha256=run.supervision_sha256,
        label="successor supervision",
    )
    urdf = inherited_runner._require_root_owned_source_file(
        args.urdf,
        source_root=source_root,
        expected_sha256=prereg.controlled_urdf_sha256,
        label="successor URDF",
    )
    if (
        sdf != source_root / f"run-{run.ordinal:02d}.sdf"
        or supervision
        != source_root / f"run-{run.ordinal:02d}.supervision.json"
        or urdf != source_root / "panda_controlled.urdf"
    ):
        raise M2CV5ExistenceSuccessorError(
            "successor source arguments differ from the selected ordinal"
        )

    stage_roots = verify_successor_stage_template_bundle(prereg=prereg)
    stage = prereg.direct_stage_adoption.physical_stage.templates[run.ordinal]
    stage_root = stage_roots[run.family_ordinal]
    source_snapshot_root = Path(CANONICAL_SOURCE_SNAPSHOT_ROOT) / (
        prereg.committed_source_snapshot.inventory_sha256
    )
    v4_auth.verify_materialized_source_snapshot(
        source_snapshot_root,
        prereg.committed_source_snapshot,
        require_content_addressed_name=True,
        allow_root_owned_read_only_mount=True,
    )
    upstream = v4_auth.read_regular_file_once(args.upstream_v4_probe)
    if sha256_bytes(upstream) != prereg.upstream_v4_probe_sha256:
        raise M2CV5ExistenceSuccessorError(
            "successor upstream probe differs from preregistration"
        )
    derived_bytes = derive_v5_existence_successor_probe_bytes(upstream)
    derived_sha256 = sha256_bytes(derived_bytes)
    if derived_sha256 != prereg.derived_probe_sha256:
        raise M2CV5ExistenceSuccessorError(
            "successor derived probe differs from preregistration"
        )

    return _PreparedSuccessorRun(
        root=root,
        resolved=resolved,
        run=run,
        stage_root=stage_root,
        stage=stage,
        source_snapshot_root=source_snapshot_root,
        source_root=source_root,
        evidence_root=evidence_root,
        ledger_root=ledger_root,
        sdf=sdf,
        supervision=supervision,
        urdf=urdf,
        scripted_bin_cell=(
            read_successor_scripted_bin_cell_at(
                resolved=resolved,
                ordinal=run.ordinal,
                source_root=source_root,
            )
            if r3
            else read_successor_scripted_bin_cell(
                resolved=resolved,
                ordinal=run.ordinal,
            )
        ),
        derived_bytes=derived_bytes,
        derived_sha256=derived_sha256,
    )


def _command_identity_values(
    *,
    prepared: _PreparedSuccessorRun,
    job_root: Path,
    probe_root: Path,
    command: list[str],
    consumption_receipt_sha256: str,
    ledger_root_sha256: str,
    claim_path_sha256: str,
) -> dict[str, str]:
    prereg = prepared.resolved.prereg
    return {
        "--m2c-active-prereg-file-sha256": prepared.resolved.file_sha256,
        "--m2c-active-prereg-sha256": prereg.prereg_sha256,
        "--m2c-expected-consumption-receipt-sha256": (
            consumption_receipt_sha256
        ),
        "--m2c-authorization-ledger-root-sha256": ledger_root_sha256,
        "--m2c-authorization-claim-path-sha256": claim_path_sha256,
        "--m2c-job-root-sha256": canonical_sha256(str(job_root)),
        "--m2c-probe-output-root-sha256": canonical_sha256(str(probe_root)),
        "--m2c-docker-command-sha256": (
            existence_docker_command_self_sha256(command)
        ),
        "--m2c-stage-metrics-sha256": prepared.stage.stage_metrics_sha256,
        "--m2c-stage-command-sha256": prepared.stage.stage_command_sha256,
    }


def _next_preclaim_effective_predecessor_sha256_locked(
    *,
    lock_token: Any,
    prepared: _PreparedSuccessorRun,
    snapshot: Any,
    r3: bool = False,
) -> str:
    if r3:
        if not snapshot.terminals:
            predecessor = snapshot.closure_predecessor
        else:
            predecessor = build_successor_native_effective_predecessor_v3(
                terminal=snapshot.terminals[-1],
                terminal_file_sha256=sha256_bytes(snapshot.terminal_bytes[-1]),
            )
    else:
        _, recovered, _ = read_durable_successor_preflight_attestation_locked(
            lock_token=lock_token,
            resolved=prepared.resolved,
        )
        if not snapshot.terminals:
            predecessor = recovered
        else:
            terminal = snapshot.terminals[-1]
            predecessor = build_native_effective_predecessor(
                ordinal=terminal.ordinal,
                successor_terminal_receipt_sha256=(
                    terminal.terminal_receipt_sha256
                ),
            )
    if predecessor.ordinal != prepared.run.ordinal - 1:
        raise M2CV5ExistenceSuccessorError(
            "successor preclaim predecessor is not adjacent"
        )
    return predecessor.effective_predecessor_sha256


def _build_and_validate_command(
    *,
    prepared: _PreparedSuccessorRun,
    gpu: int,
    r3: bool = False,
    job_root: Path,
    derived_probe: Path,
    probe_root: Path,
    projected_authorization: Path,
    effective_predecessor_sha256: str,
    consumption_receipt_sha256: str,
    ledger_root_sha256: str,
    claim_path_sha256: str,
) -> tuple[list[str], list[str]]:
    run = prepared.run
    prereg = prepared.resolved.prereg
    stage_bundle = prereg.direct_stage_adoption.physical_stage
    container_prefix = "m2c-v5-existence-r3" if r3 else "m2c-v5-existence"
    container_name = f"{container_prefix}-{run.ordinal:02d}-{run.run_id}"
    command = build_successor_probe_command(
        expected_effective_predecessor_sha256=(
            effective_predecessor_sha256
        ),
        image_id=prereg.container_image_id,
        gpu=gpu,
        container_name=container_name,
        snapshot_root=prepared.source_snapshot_root,
        source_root=prepared.source_root,
        derived_probe=derived_probe,
        stage_root=prepared.stage_root,
        probe_root=probe_root,
        authorization_projection=projected_authorization,
        run=run,
        sdf=prepared.sdf,
        supervision=prepared.supervision,
        urdf=prepared.urdf,
        scripted_bin_cell=prepared.scripted_bin_cell,
        stage_template_manifest_sha256=stage_bundle.manifest_sha256,
        stage_metrics_sha256=prepared.stage.stage_metrics_sha256,
        stage_command_sha256=prepared.stage.stage_command_sha256,
        prereg_file_sha256=prepared.resolved.file_sha256,
        prereg_sha256=prereg.prereg_sha256,
        consumption_receipt_sha256=consumption_receipt_sha256,
        authorization_ledger_root_sha256=ledger_root_sha256,
        authorization_claim_path_sha256=claim_path_sha256,
    )
    normalized = validate_successor_probe_argv_binding(
        command,
        evidence_root=prepared.evidence_root,
        expected_effective_predecessor_sha256=(
            effective_predecessor_sha256
        ),
        expected_identity_values=_command_identity_values(
            prepared=prepared,
            job_root=job_root,
            probe_root=probe_root,
            command=command,
            consumption_receipt_sha256=consumption_receipt_sha256,
            ledger_root_sha256=ledger_root_sha256,
            claim_path_sha256=claim_path_sha256,
        ),
        expected_ordinal_values={
            "--name": container_name,
            "--m2c-diagnostic-run-id": run.run_id,
            "--m2c-matched-key": run.matched_key,
            "--m2c-failure-seed": str(run.failure_seed),
            "--sdf": f"/workspace/source/run-{run.ordinal:02d}.sdf",
            "--supervision": (
                f"/workspace/source/run-{run.ordinal:02d}.supervision.json"
            ),
            "--m2c-scripted-safe-place-bin-cell": str(
                prepared.scripted_bin_cell
            ),
        },
        expected_mount_values={
            "/workspace/project": str(prepared.source_snapshot_root),
            "/workspace/source": str(prepared.source_root),
            "/workspace/derived": str(derived_probe.parent),
            "/workspace/stage": str(prepared.stage_root),
            "/workspace/output": str(probe_root),
            SUCCESSOR_CONTAINER_AUTHORIZATION_PATH: str(
                projected_authorization
            ),
        },
        forbidden_absolute_roots=(
            prepared.evidence_root,
            prepared.source_root,
            prepared.ledger_root,
            Path(CANONICAL_SOURCE_SNAPSHOT_ROOT),
            Path(stage_bundle.evidence_root),
        ),
        stable_digest_allowlist=existence_argv_stable_digest_allowlist(
            stage_metrics_sha256=prepared.stage.stage_metrics_sha256,
            stage_command_sha256=prepared.stage.stage_command_sha256,
            stage_template_manifest_sha256=stage_bundle.manifest_sha256,
        ),
    )
    return command, normalized


def _prepare_unconsumed_job(
    *,
    prepared: _PreparedSuccessorRun,
) -> tuple[Path, Path, Path, Path, Path, tuple[int, int]]:
    run = prepared.run
    job_root = prepared.evidence_root / (
        f"run-{run.ordinal:02d}-family-{run.family_ordinal:02d}"
    )
    if os.path.lexists(job_root):
        raise FileExistsError(f"refusing to overwrite a successor job: {job_root}")
    job_root.mkdir(mode=0o700)
    info = job_root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise M2CV5ExistenceSuccessorError(
            "successor unconsumed job root metadata is unsafe"
        )
    derived_root = job_root / "derived"
    authorization_root = job_root / "authorization"
    derived_root.mkdir(mode=0o700)
    authorization_root.mkdir(mode=0o700)
    derived_probe = derived_root / SUCCESSOR_DERIVED_PROBE_NAME
    inherited_runner._write_create_only(
        derived_probe,
        prepared.derived_bytes,
        mode=0o555,
    )
    derived_root.chmod(0o555)
    probe_root = job_root / "probe"
    inherited_runner._prepare_container_output(probe_root)
    public_root = probe_root / "m2b_public_rgbd"
    inherited_runner._prepare_container_output(public_root)
    inherited_runner._prepare_container_output(public_root / "depth")
    inherited_runner._prepare_container_output(public_root / "rgb")
    return (
        job_root,
        derived_probe,
        authorization_root,
        probe_root,
        authorization_root / SUCCESSOR_PROJECTED_AUTHORIZATION_NAME,
        (info.st_dev, info.st_ino),
    )


def _remove_proven_unconsumed_job(
    *,
    job_root: Path,
    created_identity: tuple[int, int],
) -> None:
    try:
        info = job_root.stat(follow_symlinks=False)
        canonical = job_root.resolve(strict=True)
    except OSError as error:
        raise M2CV5ExistenceSuccessorError(
            "successor unconsumed job cannot be recaptured"
        ) from error
    if (
        canonical != job_root.absolute()
        or not stat.S_ISDIR(info.st_mode)
        or (info.st_dev, info.st_ino) != created_identity
    ):
        raise M2CV5ExistenceSuccessorError(
            "successor unconsumed job identity changed before removal"
        )
    shutil.rmtree(job_root)
    if os.path.lexists(job_root):
        raise M2CV5ExistenceSuccessorError(
            "successor unconsumed job remains after preclaim rejection"
        )


def _validate_projected_authorization(
    *,
    prepared: _PreparedSuccessorRun,
    authorization_path: Path,
    authorization: Any,
    r3: bool = False,
) -> None:
    run = prepared.run
    prereg = prepared.resolved.prereg
    stage_bundle = prereg.direct_stage_adoption.physical_stage
    validator = (
        validate_successor_runtime_authorization_v3_for_runtime
        if r3
        else validate_successor_authorization_for_runtime
    )
    observed = validator(
        authorization_path=authorization_path,
        run_id=run.run_id,
        matched_key=run.matched_key,
        scene_seed=run.scene_seed,
        failure_seed=run.failure_seed,
        condition=run.probe_condition,
        source_sdf_sha256=run.sdf_sha256,
        source_supervision_sha256=run.supervision_sha256,
        source_urdf_sha256=prereg.controlled_urdf_sha256,
        upstream_v4_probe_sha256=prereg.upstream_v4_probe_sha256,
        derived_probe_sha256=prereg.derived_probe_sha256,
        container_image_id=prereg.container_image_id,
        direct_public_rgbd_enabled=False,
        stage_template_manifest_sha256=stage_bundle.manifest_sha256,
        stage_usdc_sha256=prepared.stage.stage_usdc_sha256,
        stage_metrics_sha256=prepared.stage.stage_metrics_sha256,
        active_prereg_file_sha256=authorization.prereg_file_sha256,
        active_prereg_sha256=authorization.prereg_sha256,
        expected_consumption_receipt_sha256=(
            authorization.consumption_receipt_sha256
        ),
        expected_effective_predecessor_sha256=(
            authorization.effective_predecessor_sha256
        ),
        authorization_ledger_root_sha256=authorization.ledger_root_sha256,
        authorization_claim_path_sha256=authorization.claim_path_sha256,
    )
    if observed != authorization:
        raise M2CV5ExistenceSuccessorError(
            "successor projected authorization changed at runtime"
        )


def _publish_job_receipt(
    *,
    prepared: _PreparedSuccessorRun,
    claim: Any,
    claim_path: Path,
    claim_bytes: bytes,
    authorization: Any,
    authorization_bytes: bytes,
    host_authorization: Path,
    projected_authorization: Path,
    job_root: Path,
    gpu: int,
    container_name: str,
    command: list[str],
    normalized: list[str],
    preflight_bundle_sha256: str,
) -> tuple[Any, bytes]:
    receipt = build_successor_job_receipt(
        claim=claim,
        claim_path=claim_path,
        claim_file_sha256=sha256_bytes(claim_bytes),
        authorization=authorization,
        authorization_file_sha256=sha256_bytes(authorization_bytes),
        host_authorization_path=host_authorization,
        projected_authorization_path=projected_authorization,
        derived_probe_sha256=prepared.derived_sha256,
        source_snapshot=prepared.resolved.prereg.committed_source_snapshot,
        source_root=prepared.source_root,
        output_root=prepared.evidence_root,
        ledger_root=prepared.ledger_root,
        source_sdf_path=prepared.sdf,
        source_supervision_path=prepared.supervision,
        source_urdf_path=prepared.urdf,
        scripted_bin_cell=prepared.scripted_bin_cell,
        gpu=gpu,
        container_name=container_name,
        image_id=prepared.resolved.prereg.container_image_id,
        stage_template=prepared.stage,
        stage_template_manifest_sha256=(
            prepared.resolved.prereg.direct_stage_adoption.physical_stage.manifest_sha256
        ),
        probe_command=command,
        normalized_argv=normalized,
        preflight_bundle_sha256=preflight_bundle_sha256,
    )
    payload = canonical_successor_job_receipt_bytes(receipt)
    durable = publish_successor_create_only(
        job_root / SUCCESSOR_JOB_RECEIPT_NAME,
        payload,
        label="successor job receipt",
    )
    if parse_successor_job_receipt_bytes(durable) != receipt:
        raise M2CV5ExistenceSuccessorError(
            "successor durable job receipt changed"
        )
    return receipt, payload


def _inventory_commitment(root: Path) -> str:
    return existence_inventory_commitment_sha256(inherited_runner._inventory(root))


def _durable_r3_claim_state_locked(
    *,
    lock_token: Any,
    prepared: _PreparedSuccessorRun,
) -> str:
    snapshot = read_successor_r3_campaign_snapshot_locked(
        lock_token=lock_token,
        resolved_r2=prepared.resolved,
    )
    matching_claims = [
        claim for claim in snapshot.claims if claim.ordinal == prepared.run.ordinal
    ]
    matching_terminals = [
        terminal
        for terminal in snapshot.terminals
        if terminal.ordinal == prepared.run.ordinal
    ]
    if not matching_claims:
        return "ABSENT"
    return "PRESENT_TERMINALIZED" if matching_terminals else "PRESENT_ORPHAN"


def _publish_r3_job_receipt(
    *,
    prepared: _PreparedSuccessorRun,
    claim: Any,
    claim_path: Path,
    claim_bytes: bytes,
    authorization: Any,
    authorization_bytes: bytes,
    projected_authorization_bytes: bytes,
    host_authorization: Path,
    projected_authorization: Path,
    job_root: Path,
    gpu: int,
    container_name: str,
    command: list[str],
    normalized: list[str],
    preflight_bundle_sha256: str,
) -> tuple[Any, bytes]:
    receipt = build_successor_job_receipt_v3(
        claim=claim,
        claim_path=claim_path,
        claim_file_sha256=sha256_bytes(claim_bytes),
        authorization=authorization,
        authorization_file_sha256=sha256_bytes(authorization_bytes),
        host_authorization_path=host_authorization,
        projected_authorization_path=projected_authorization,
        projected_authorization_file_sha256=sha256_bytes(
            projected_authorization_bytes
        ),
        derived_probe_sha256=prepared.derived_sha256,
        source_snapshot=prepared.resolved.prereg.committed_source_snapshot,
        source_root=prepared.source_root,
        output_root=prepared.evidence_root,
        ledger_root=prepared.ledger_root,
        source_sdf_path=prepared.sdf,
        source_supervision_path=prepared.supervision,
        source_urdf_path=prepared.urdf,
        scripted_bin_cell=prepared.scripted_bin_cell,
        gpu=gpu,
        container_name=container_name,
        image_id=prepared.resolved.prereg.container_image_id,
        stage_template=prepared.stage,
        stage_template_manifest_sha256=(
            prepared.resolved.prereg.direct_stage_adoption.physical_stage.manifest_sha256
        ),
        probe_command=command,
        normalized_argv=normalized,
        preflight_bundle_sha256=preflight_bundle_sha256,
    )
    payload = canonical_successor_job_receipt_v3_bytes(receipt)
    durable = publish_successor_create_only(
        job_root / SUCCESSOR_JOB_RECEIPT_NAME,
        payload,
        label="successor R3 job receipt",
    )
    if parse_successor_job_receipt_v3_bytes(durable) != receipt:
        raise M2CV5ExistenceSuccessorError(
            "successor R3 durable job receipt changed"
        )
    return receipt, payload


def run_one_v5_existence_successor(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "r3", False):
        return _run_one_v5_existence_successor_r3(args)
    prepared = _prepare_before_claim(args)
    run = prepared.run
    probe_name = f"m2c-v5-existence-{run.ordinal:02d}-{run.run_id}"
    job_root: Path | None = None
    created_identity: tuple[int, int] | None = None

    with successor_campaign_lifecycle_lock(
        ledger_root=prepared.ledger_root,
        resolved=prepared.resolved,
    ) as lock_token:
        snapshot = read_successor_campaign_snapshot_locked(
            lock_token=lock_token,
            resolved=prepared.resolved,
        )
        expected_ordinal = (
            SUCCESSOR_PHYSICAL_ORDINALS[len(snapshot.claims)]
            if len(snapshot.claims) < len(SUCCESSOR_PHYSICAL_ORDINALS)
            else None
        )
        if (
            snapshot.complete is not None
            or len(snapshot.claims) != len(snapshot.terminals)
            or run.ordinal != expected_ordinal
            or durable_successor_claim_state_locked(
                lock_token=lock_token,
                resolved=prepared.resolved,
                ordinal=run.ordinal,
            )
            != "ABSENT"
        ):
            raise M2CV5ExistenceSuccessorError(
                "successor selected run is not the next unconsumed ordinal"
            )
        try:
            (
                job_root,
                derived_probe,
                authorization_root,
                probe_root,
                projected_authorization_path,
                created_identity,
            ) = _prepare_unconsumed_job(prepared=prepared)
            require_pre_freeze(M2CExperimentAction.ISAAC_COLLECTION)
            image_id = v4_auth.resolve_docker_image_id(image=args.image)
            if (
                image_id != ISAAC_IMAGE_ID
                or image_id != prepared.resolved.prereg.container_image_id
            ):
                raise M2CV5ExistenceSuccessorError(
                    "successor live image differs from frozen authority"
                )
            _require_successor_runtime_identity(image_id)
            inherited_runner._require_container_name_available(probe_name)
            preflight_shape, preflight_bundle_sha256 = (
                durable_successor_preflight_argv_shape_locked(
                    lock_token=lock_token,
                    resolved=prepared.resolved,
                )
            )
            preclaim_predecessor_sha256 = (
                _next_preclaim_effective_predecessor_sha256_locked(
                    lock_token=lock_token,
                    prepared=prepared,
                    snapshot=snapshot,
                )
            )
            _, sentinel_shape = _build_and_validate_command(
                prepared=prepared,
                gpu=args.gpu,
                job_root=job_root,
                derived_probe=derived_probe,
                probe_root=probe_root,
                projected_authorization=projected_authorization_path,
                effective_predecessor_sha256=preclaim_predecessor_sha256,
                consumption_receipt_sha256=(
                    ARGV_PRECONSUMPTION_IDENTITY_SENTINEL
                ),
                ledger_root_sha256=ARGV_PRECONSUMPTION_IDENTITY_SENTINEL,
                claim_path_sha256=ARGV_PRECONSUMPTION_IDENTITY_SENTINEL,
            )
            if sentinel_shape != preflight_shape:
                raise M2CV5ExistenceSuccessorError(
                    "successor preclaim Docker argv shape differs from preflight"
                )
        except BaseException:
            state = durable_successor_claim_state_locked(
                lock_token=lock_token,
                resolved=prepared.resolved,
                ordinal=run.ordinal,
            )
            if state == "ABSENT" and job_root is not None and created_identity is not None:
                _remove_proven_unconsumed_job(
                    job_root=job_root,
                    created_identity=created_identity,
                )
            raise

        try:
            claim_path = publish_successor_claim_locked(
                lock_token=lock_token,
                resolved=prepared.resolved,
                ordinal=run.ordinal,
                consumed_at_ns=time.time_ns(),
            )
        except BaseException:
            if (
                durable_successor_claim_state_locked(
                    lock_token=lock_token,
                    resolved=prepared.resolved,
                    ordinal=run.ordinal,
                )
                == "ABSENT"
            ):
                _remove_proven_unconsumed_job(
                    job_root=job_root,
                    created_identity=created_identity,
                )
            raise
        claim, claim_bytes = read_durable_successor_claim_locked(
            lock_token=lock_token,
            resolved=prepared.resolved,
            ordinal=run.ordinal,
        )
        authorization = bind_successor_claim_to_raw_session_locked(
            lock_token=lock_token,
            resolved=prepared.resolved,
            claim_path=claim_path,
            source_snapshot_root=prepared.source_snapshot_root,
        )
        authorization_bytes = canonical_successor_authorization_bytes(authorization)
        host_authorization = publish_successor_authorization_projection(
            path=authorization_root / SUCCESSOR_HOST_AUTHORIZATION_NAME,
            payload=authorization_bytes,
            uid=0,
            gid=0,
            label="successor host authorization",
        )
        projected_authorization = publish_successor_authorization_projection(
            path=projected_authorization_path,
            payload=authorization_bytes,
            uid=RUNTIME_UID,
            gid=RUNTIME_GID,
            label="successor projected authorization",
        )
        _validate_projected_authorization(
            prepared=prepared,
            authorization_path=projected_authorization,
            authorization=authorization,
        )
        probe_command, normalized = _build_and_validate_command(
            prepared=prepared,
            gpu=args.gpu,
            job_root=job_root,
            derived_probe=derived_probe,
            probe_root=probe_root,
            projected_authorization=projected_authorization,
            effective_predecessor_sha256=(
                authorization.effective_predecessor_sha256
            ),
            consumption_receipt_sha256=(
                authorization.consumption_receipt_sha256
            ),
            ledger_root_sha256=authorization.ledger_root_sha256,
            claim_path_sha256=authorization.claim_path_sha256,
        )
        if normalized != preflight_shape:
            raise M2CV5ExistenceSuccessorError(
                "successor postclaim Docker argv shape differs from preflight"
            )
        job_receipt, job_receipt_bytes = _publish_job_receipt(
            prepared=prepared,
            claim=claim,
            claim_path=claim_path,
            claim_bytes=claim_bytes,
            authorization=authorization,
            authorization_bytes=authorization_bytes,
            host_authorization=host_authorization,
            projected_authorization=projected_authorization,
            job_root=job_root,
            gpu=args.gpu,
            container_name=probe_name,
            command=probe_command,
            normalized=normalized,
            preflight_bundle_sha256=preflight_bundle_sha256,
        )

        capture_started_at_ns = time.time_ns()
        capture = inherited_runner._capture_existence_container(
            probe_command,
            name=probe_name,
            timeout_s=args.timeout_s,
        )
        if capture.primary_error is not None:
            raise capture.primary_error
        if (
            capture.observation is None
            or capture.inspect_evidence is None
            or capture.container_id is None
            or capture.probe_started is not True
            or capture.completed.returncode != 0
        ):
            raise M2CV5ExistenceSuccessorError(
                "successor container did not yield a complete rc0 pre-cleanup capture"
            )
        observation = capture.observation
        lifecycle = build_successor_lifecycle_capture(
            claim=claim,
            claim_file_sha256=sha256_bytes(claim_bytes),
            authorization_file_sha256=sha256_bytes(authorization_bytes),
            container_name=probe_name,
            container_id=capture.container_id,
            image_id=observation.image_id,
            docker_path=observation.docker_path,
            docker_args=observation.docker_args,
            raw_inspect=capture.inspect_evidence,
            capture_started_at_ns=capture_started_at_ns,
            captured_at_ns=time.time_ns(),
        )
        lifecycle_bytes = canonical_successor_lifecycle_capture_bytes(lifecycle)
        durable_lifecycle = publish_successor_create_only(
            probe_root / SUCCESSOR_LIFECYCLE_CAPTURE_NAME,
            lifecycle_bytes,
            label="successor container lifecycle capture",
        )
        if parse_successor_lifecycle_capture_bytes(durable_lifecycle) != lifecycle:
            raise M2CV5ExistenceSuccessorError(
                "successor durable lifecycle capture changed"
            )

        cleanup = inherited_runner._cleanup_existence_container(
            name=probe_name,
            container_id=capture.container_id,
        )
        if (
            cleanup.error is not None
            or cleanup.observed_id_absence != "OBSERVED_ABSENT"
            or cleanup.exact_name_absence != "OBSERVED_ABSENT"
        ):
            raise M2CV5ExistenceSuccessorError(
                "successor container absence was not completely proven"
            ) from cleanup.error
        container_receipt = inherited_runner._complete_container_receipt(
            observation=observation,
            inspect_evidence=capture.inspect_evidence,
            cleanup=cleanup,
            probe_command=probe_command,
            image_id=image_id,
        )
        container_receipt_bytes = canonical_successor_container_receipt_bytes(
            container_receipt
        )
        durable_container = publish_successor_create_only(
            probe_root / SUCCESSOR_CONTAINER_RECEIPT_NAME,
            container_receipt_bytes,
            label="successor container receipt",
        )
        if parse_successor_container_receipt_bytes(durable_container) != container_receipt:
            raise M2CV5ExistenceSuccessorError(
                "successor durable container receipt changed"
            )
        publish_successor_create_only(
            probe_root / SUCCESSOR_CONTAINER_ID_NAME,
            (capture.container_id + "\n").encode("ascii"),
            label="successor container ID",
        )
        publish_successor_create_only(
            probe_root / SUCCESSOR_CONSOLE_NAME,
            capture.completed.stdout + capture.completed.stderr,
            label="successor console capture",
        )

        raw = validate_complete_successor_evidence(
            output_root=probe_root,
            authorization=authorization,
        )
        raw_bytes = v4_auth.read_regular_file_once(
            probe_root / SUCCESSOR_RAW_EVIDENCE_NAME
        )
        inherited_runner._seal_root_owned_read_only(probe_root)
        inherited_runner._seal_root_owned_read_only(job_root)
        probe_inventory_sha256 = _inventory_commitment(probe_root)
        job_inventory_sha256 = _inventory_commitment(job_root)
        terminal = build_successor_terminal_receipt(
            claim=claim,
            claim_file_sha256=sha256_bytes(claim_bytes),
            authorization=authorization,
            authorization_file_sha256=sha256_bytes(authorization_bytes),
            job_receipt=job_receipt,
            job_receipt_file_sha256=sha256_bytes(job_receipt_bytes),
            lifecycle_capture=lifecycle,
            lifecycle_capture_file_sha256=sha256_bytes(lifecycle_bytes),
            container_receipt=container_receipt,
            container_receipt_file_sha256=sha256_bytes(container_receipt_bytes),
            raw=raw,
            raw_evidence_sha256=sha256_bytes(raw_bytes),
            probe_inventory_sha256=probe_inventory_sha256,
            job_inventory_sha256=job_inventory_sha256,
            terminalized_at_ns=time.time_ns(),
        )
        terminal_path = publish_successor_terminal_locked(
            lock_token=lock_token,
            resolved=prepared.resolved,
            terminal=terminal,
        )
        return {
            "job_root": str(job_root),
            "terminal_path": str(terminal_path),
            "ordinal": run.ordinal,
            "run_id": run.run_id,
            "status": terminal.status,
            "task_outcome": terminal.task_outcome,
            "task_success": terminal.task_success,
            "terminal_receipt_sha256": terminal.terminal_receipt_sha256,
        }


def _run_one_v5_existence_successor_r3(
    args: argparse.Namespace,
) -> dict[str, Any]:
    prepared = _prepare_before_claim(args)
    run = prepared.run
    probe_name = f"m2c-v5-existence-r3-{run.ordinal:02d}-{run.run_id}"
    job_root: Path | None = None
    created_identity: tuple[int, int] | None = None

    with successor_r3_campaign_lifecycle_lock(
        ledger_root=prepared.ledger_root,
    ) as lock_token:
        snapshot = read_successor_r3_campaign_snapshot_locked(
            lock_token=lock_token,
            resolved_r2=prepared.resolved,
        )
        expected_ordinal = (
            SUCCESSOR_R3_PHYSICAL_ORDINALS[len(snapshot.claims)]
            if len(snapshot.claims) < len(SUCCESSOR_R3_PHYSICAL_ORDINALS)
            else None
        )
        if (
            (prepared.ledger_root / SUCCESSOR_R3_COMBINED_COMPLETION_NAME).exists()
            or len(snapshot.claims) != len(snapshot.terminals)
            or run.ordinal != expected_ordinal
            or _durable_r3_claim_state_locked(
                lock_token=lock_token,
                prepared=prepared,
            )
            != "ABSENT"
        ):
            raise M2CV5ExistenceSuccessorError(
                "successor R3 selected run is not the next unconsumed ordinal"
            )
        try:
            (
                job_root,
                derived_probe,
                authorization_root,
                probe_root,
                projected_authorization_path,
                created_identity,
            ) = _prepare_unconsumed_job(prepared=prepared)
            require_pre_freeze(M2CExperimentAction.ISAAC_COLLECTION)
            image_id = v4_auth.resolve_docker_image_id(image=args.image)
            if (
                image_id != ISAAC_IMAGE_ID
                or image_id != prepared.resolved.prereg.container_image_id
            ):
                raise M2CV5ExistenceSuccessorError(
                    "successor R3 live image differs from frozen authority"
                )
            _require_successor_runtime_identity(image_id)
            inherited_runner._require_container_name_available(probe_name)
            preflight_shape, preflight_bundle_sha256 = (
                durable_successor_r3_preflight_argv_shape_locked(
                    lock_token=lock_token,
                    resolved_r2=prepared.resolved,
                )
            )
            preclaim_predecessor_sha256 = (
                _next_preclaim_effective_predecessor_sha256_locked(
                    lock_token=lock_token,
                    prepared=prepared,
                    snapshot=snapshot,
                    r3=True,
                )
            )
            _, sentinel_shape = _build_and_validate_command(
                prepared=prepared,
                gpu=args.gpu,
                r3=True,
                job_root=job_root,
                derived_probe=derived_probe,
                probe_root=probe_root,
                projected_authorization=projected_authorization_path,
                effective_predecessor_sha256=preclaim_predecessor_sha256,
                consumption_receipt_sha256=(
                    ARGV_PRECONSUMPTION_IDENTITY_SENTINEL
                ),
                ledger_root_sha256=ARGV_PRECONSUMPTION_IDENTITY_SENTINEL,
                claim_path_sha256=ARGV_PRECONSUMPTION_IDENTITY_SENTINEL,
            )
            if sentinel_shape != preflight_shape:
                raise M2CV5ExistenceSuccessorError(
                    "successor R3 preclaim Docker argv shape differs from preflight"
                )
        except BaseException:
            state = _durable_r3_claim_state_locked(
                lock_token=lock_token,
                prepared=prepared,
            )
            if state == "ABSENT" and job_root is not None and created_identity is not None:
                _remove_proven_unconsumed_job(
                    job_root=job_root,
                    created_identity=created_identity,
                )
            raise

        try:
            claim_path = publish_successor_r3_claim_locked(
                lock_token=lock_token,
                resolved_r2=prepared.resolved,
                ordinal=run.ordinal,
                consumed_at_ns=time.time_ns(),
            )
        except BaseException:
            if (
                _durable_r3_claim_state_locked(
                    lock_token=lock_token,
                    prepared=prepared,
                )
                == "ABSENT"
            ):
                _remove_proven_unconsumed_job(
                    job_root=job_root,
                    created_identity=created_identity,
                )
            raise
        claim, claim_bytes, authorization, compatibility = (
            bind_successor_r3_claim_to_physical_session_locked(
                lock_token=lock_token,
                resolved_r2=prepared.resolved,
                claim_path=claim_path,
                source_snapshot_root=prepared.source_snapshot_root,
                source_root=prepared.source_root,
            )
        )
        authorization_bytes = (
            canonical_successor_runtime_authorization_v3_bytes(authorization)
        )
        compatibility_bytes = canonical_successor_authorization_bytes(compatibility)
        host_authorization = publish_successor_authorization_projection(
            path=authorization_root / SUCCESSOR_HOST_AUTHORIZATION_NAME,
            payload=authorization_bytes,
            uid=0,
            gid=0,
            label="successor R3 host authorization",
        )
        projected_authorization = publish_successor_authorization_projection(
            path=projected_authorization_path,
            payload=compatibility_bytes,
            uid=RUNTIME_UID,
            gid=RUNTIME_GID,
            label="successor R3 physical compatibility authorization",
        )
        _validate_projected_authorization(
            prepared=prepared,
            authorization_path=host_authorization,
            authorization=authorization,
            r3=True,
        )
        _validate_projected_authorization(
            prepared=prepared,
            authorization_path=projected_authorization,
            authorization=compatibility,
        )
        probe_command, normalized = _build_and_validate_command(
            prepared=prepared,
            gpu=args.gpu,
            r3=True,
            job_root=job_root,
            derived_probe=derived_probe,
            probe_root=probe_root,
            projected_authorization=projected_authorization,
            effective_predecessor_sha256=(
                authorization.effective_predecessor_sha256
            ),
            consumption_receipt_sha256=(
                authorization.consumption_receipt_sha256
            ),
            ledger_root_sha256=authorization.ledger_root_sha256,
            claim_path_sha256=authorization.claim_path_sha256,
        )
        if normalized != preflight_shape:
            raise M2CV5ExistenceSuccessorError(
                "successor R3 postclaim Docker argv shape differs from preflight"
            )
        job_receipt, job_receipt_bytes = _publish_r3_job_receipt(
            prepared=prepared,
            claim=claim,
            claim_path=claim_path,
            claim_bytes=claim_bytes,
            authorization=authorization,
            authorization_bytes=authorization_bytes,
            projected_authorization_bytes=compatibility_bytes,
            host_authorization=host_authorization,
            projected_authorization=projected_authorization,
            job_root=job_root,
            gpu=args.gpu,
            container_name=probe_name,
            command=probe_command,
            normalized=normalized,
            preflight_bundle_sha256=preflight_bundle_sha256,
        )

        capture_started_at_ns = time.time_ns()
        capture = inherited_runner._capture_existence_container(
            probe_command,
            name=probe_name,
            timeout_s=args.timeout_s,
        )
        if capture.primary_error is not None:
            raise capture.primary_error
        if (
            capture.observation is None
            or capture.inspect_evidence is None
            or capture.container_id is None
            or capture.probe_started is not True
            or capture.completed.returncode != 0
        ):
            raise M2CV5ExistenceSuccessorError(
                "successor R3 container did not yield a complete rc0 pre-cleanup capture"
            )
        observation = capture.observation
        lifecycle = build_successor_lifecycle_capture_v3(
            claim=claim,
            claim_file_sha256=sha256_bytes(claim_bytes),
            authorization=authorization,
            authorization_file_sha256=sha256_bytes(authorization_bytes),
            projected_authorization_file_sha256=sha256_bytes(
                compatibility_bytes
            ),
            container_name=probe_name,
            container_id=capture.container_id,
            image_id=observation.image_id,
            docker_path=observation.docker_path,
            docker_args=observation.docker_args,
            probe_command=probe_command,
            raw_inspect=capture.inspect_evidence,
            capture_started_at_ns=capture_started_at_ns,
            captured_at_ns=time.time_ns(),
        )
        lifecycle_bytes = canonical_successor_lifecycle_capture_v3_bytes(lifecycle)
        durable_lifecycle = publish_successor_create_only(
            probe_root / SUCCESSOR_LIFECYCLE_CAPTURE_NAME,
            lifecycle_bytes,
            label="successor R3 container lifecycle capture",
        )
        if parse_successor_lifecycle_capture_v3_bytes(durable_lifecycle) != lifecycle:
            raise M2CV5ExistenceSuccessorError(
                "successor R3 durable lifecycle capture changed"
            )

        cleanup = inherited_runner._cleanup_existence_container(
            name=probe_name,
            container_id=capture.container_id,
        )
        if (
            cleanup.error is not None
            or cleanup.observed_id_absence != "OBSERVED_ABSENT"
            or cleanup.exact_name_absence != "OBSERVED_ABSENT"
        ):
            raise M2CV5ExistenceSuccessorError(
                "successor R3 container absence was not completely proven"
            ) from cleanup.error
        container_receipt = inherited_runner._complete_container_receipt(
            observation=observation,
            inspect_evidence=capture.inspect_evidence,
            cleanup=cleanup,
            probe_command=probe_command,
            image_id=image_id,
        )
        container_receipt_bytes = canonical_successor_container_receipt_bytes(
            container_receipt
        )
        durable_container = publish_successor_create_only(
            probe_root / SUCCESSOR_CONTAINER_RECEIPT_NAME,
            container_receipt_bytes,
            label="successor R3 container receipt",
        )
        if parse_successor_container_receipt_bytes(durable_container) != container_receipt:
            raise M2CV5ExistenceSuccessorError(
                "successor R3 durable container receipt changed"
            )
        publish_successor_create_only(
            probe_root / SUCCESSOR_CONTAINER_ID_NAME,
            (capture.container_id + "\n").encode("ascii"),
            label="successor R3 container ID",
        )
        publish_successor_create_only(
            probe_root / SUCCESSOR_CONSOLE_NAME,
            capture.completed.stdout + capture.completed.stderr,
            label="successor R3 console capture",
        )

        raw = validate_complete_successor_evidence(
            output_root=probe_root,
            authorization=compatibility,
        )
        raw_bytes = v4_auth.read_regular_file_once(
            probe_root / SUCCESSOR_RAW_EVIDENCE_NAME
        )
        inherited_runner._seal_root_owned_read_only(probe_root)
        inherited_runner._seal_root_owned_read_only(job_root)
        probe_inventory_sha256 = _inventory_commitment(probe_root)
        job_inventory_sha256 = _inventory_commitment(job_root)
        terminal = build_successor_terminal_receipt_v3(
            claim=claim,
            claim_file_sha256=sha256_bytes(claim_bytes),
            authorization=authorization,
            authorization_file_sha256=sha256_bytes(authorization_bytes),
            projected_authorization_file_sha256=sha256_bytes(
                compatibility_bytes
            ),
            job_receipt=job_receipt,
            job_receipt_file_sha256=sha256_bytes(job_receipt_bytes),
            lifecycle_capture=lifecycle,
            lifecycle_capture_file_sha256=sha256_bytes(lifecycle_bytes),
            container_receipt=container_receipt,
            container_receipt_file_sha256=sha256_bytes(container_receipt_bytes),
            raw=raw,
            raw_evidence_sha256=sha256_bytes(raw_bytes),
            probe_inventory_sha256=probe_inventory_sha256,
            job_inventory_sha256=job_inventory_sha256,
            terminalized_at_ns=time.time_ns(),
        )
        terminal_path = publish_successor_r3_terminal_locked(
            lock_token=lock_token,
            resolved_r2=prepared.resolved,
            terminal=terminal,
        )
        return {
            "job_root": str(job_root),
            "terminal_path": str(terminal_path),
            "ordinal": run.ordinal,
            "run_id": run.run_id,
            "status": terminal.status,
            "task_outcome": terminal.task_outcome,
            "task_success": terminal.task_success,
            "terminal_receipt_sha256": terminal.terminal_receipt_sha256,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument(
        "--prereg",
        type=Path,
        default=ROOT / SUCCESSOR_PREREG_REPOSITORY_PATH,
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--sdf", type=Path, required=True)
    parser.add_argument("--supervision", type=Path, required=True)
    parser.add_argument("--urdf", type=Path, required=True)
    parser.add_argument("--upstream-v4-probe", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--image", default=ISAAC_IMAGE)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--container-prefix")
    parser.add_argument("--timeout-s", type=float, default=5400.0)
    parser.add_argument("--r3", action="store_true")
    args = parser.parse_args()
    if args.container_prefix is None:
        args.container_prefix = (
            "m2c-v5-existence-r3" if args.r3 else "m2c-v5-existence"
        )
    result = run_one_v5_existence_successor(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
