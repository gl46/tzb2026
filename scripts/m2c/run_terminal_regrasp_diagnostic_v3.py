#!/usr/bin/env python3
"""Run exactly one consumed ADR-0026 V3 terminal diagnostic attempt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import time
from typing import Any

from m2c.derive_terminal_regrasp_diagnostic_probe_v3 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v3,
)
from m2c.run_terminal_regrasp_diagnostic import (
    _prepare_container_output,
    _probe_command,
    _project_claim,
    _require_image_runtime_user,
    _run_container,
    _scripted_bin_cell,
    _seal_container_output,
    _sha256_file,
    _stage_command,
    _stage_is_valid,
    _write_create_only,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    TerminalDiagnosticError,
    canonical_json_bytes,
    canonical_sha256,
    sha256_bytes,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    consume_diagnostic_run_v3,
    load_committed_diagnostic_prereg_v3,
    parse_diagnostic_raw_bytes_v3,
)


ROOT = Path(__file__).resolve().parents[2]


def _probe_command_v3(**kwargs: Any) -> list[str]:
    command = _probe_command(**kwargs)
    run = kwargs["run"]
    if run.condition in {"C1_NO_BLOCKER", "C2_RETAINED_BLOCKER"}:
        command.append("--m2c-direct-terminal-public-rgbd")
    digest_index = command.index("--m2c-docker-command-sha256") + 1
    command[digest_index] = "0" * 64
    command[digest_index] = canonical_sha256(command)
    return command


def run_one_v3(args: argparse.Namespace) -> dict[str, Any]:
    root = args.project_root.resolve(strict=True)
    resolved = load_committed_diagnostic_prereg_v3(
        project_root=root,
        prereg_path=args.prereg,
    )
    selected = [run for run in resolved.prereg.runs if run.run_id == args.run_id]
    if len(selected) != 1:
        raise TerminalDiagnosticError("V3 run ID is not uniquely preregistered")
    run = selected[0]
    if args.image != ISAAC_IMAGE:
        raise TerminalDiagnosticError("V3 image tag differs from preregistration")
    source_info = args.source_root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(source_info.st_mode)
        or stat.S_IMODE(source_info.st_mode) != 0o555
        or source_info.st_uid != 0
    ):
        raise TerminalDiagnosticError("V3 source root must be root-owned 0555 evidence")
    for path, expected, label in (
        (args.sdf, run.sdf_sha256, "SDF"),
        (args.supervision, run.supervision_sha256, "supervision"),
        (args.urdf, resolved.prereg.controlled_urdf_sha256, "URDF"),
    ):
        if path.parent.resolve(strict=True) != args.source_root.resolve(strict=True):
            raise TerminalDiagnosticError(f"V3 {label} is not under source root")
        if _sha256_file(path) != expected:
            raise TerminalDiagnosticError(f"V3 {label} digest differs from prereg")
    if _sha256_file(args.upstream_v4_probe) != resolved.prereg.upstream_v4_probe_sha256:
        raise TerminalDiagnosticError("V3 upstream probe digest differs from freeze")
    derived_bytes = derive_terminal_regrasp_diagnostic_probe_bytes_v3(
        v4_auth.read_regular_file_once(args.upstream_v4_probe)
    )
    derived_sha = sha256_bytes(derived_bytes)
    image_id = v4_auth.resolve_docker_image_id(image=args.image)
    if image_id != ISAAC_IMAGE_ID:
        raise TerminalDiagnosticError("V3 image ID differs from preregistration")
    _require_image_runtime_user(image_id)
    snapshot_root = v4_auth.materialize_committed_source_snapshot(
        project_root=root,
        expected=resolved.prereg.committed_source_snapshot,
    )
    require_pre_freeze(M2CExperimentAction.ISAAC_COLLECTION)

    output_info = args.output_root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(output_info.st_mode)
        or output_info.st_uid != 0
        or stat.S_IMODE(output_info.st_mode) != 0o700
    ):
        raise TerminalDiagnosticError("V3 output root must be root-owned 0700")
    job_root = args.output_root / (
        f"run-{run.ordinal:02d}-{run.run_id.removeprefix('m2c-s4-terminal-diagnostic-')[:16]}"
    )
    if job_root.exists():
        raise FileExistsError(f"refusing to overwrite V3 diagnostic job: {job_root}")
    job_root.mkdir(mode=0o700)
    derived_root = job_root / "derived"
    authorization_root = job_root / "authorization"
    derived_root.mkdir(mode=0o700)
    authorization_root.mkdir(mode=0o700)
    derived_probe = derived_root / "terminal-regrasp-diagnostic-probe-v3.py"
    _write_create_only(derived_probe, derived_bytes, mode=0o555)
    derived_root.chmod(0o555)
    stage_root = job_root / "stage"
    probe_root = job_root / "probe"
    _prepare_container_output(stage_root)
    _prepare_container_output(probe_root)

    claim = consume_diagnostic_run_v3(
        resolved=resolved,
        run_id=run.run_id,
        ledger_root=args.ledger_root,
        derived_probe_sha256=derived_sha,
        consumed_at_ns=time.time_ns(),
    )
    claim_projection = _project_claim(claim, authorization_root)
    stage_name = f"{args.container_prefix}-{run.ordinal:02d}-stage"
    probe_name = f"{args.container_prefix}-{run.ordinal:02d}-probe"
    stage_command = _stage_command(
        image_id=image_id,
        gpu=args.gpu,
        container_name=stage_name,
        snapshot_root=snapshot_root,
        source_root=args.source_root,
        stage_root=stage_root,
        sdf=args.sdf,
        supervision=args.supervision,
        urdf=args.urdf,
    )
    job_receipt: dict[str, Any] = {
        "schema_version": "M2CTerminalDiagnosticJobReceiptV3",
        "status": "CONSUMED_V3_DIAGNOSTIC_ONLY_BEFORE_STAGE",
        "campaign_id": resolved.prereg.campaign_id,
        "run": run.model_dump(mode="json"),
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": resolved.prereg.prereg_sha256,
        "claim_path": str(claim),
        "claim_sha256": _sha256_file(claim),
        "derived_probe_sha256": derived_sha,
        "source_snapshot": resolved.prereg.committed_source_snapshot.model_dump(mode="json"),
        "image_id": image_id,
        "direct_public_rgbd_setup_contract": (resolved.prereg.direct_public_rgbd_setup_contract),
        "stage_command_sha256": canonical_sha256(stage_command),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    job_receipt["receipt_sha256"] = canonical_sha256(job_receipt)
    _write_create_only(
        job_root / "job-receipt.json",
        canonical_json_bytes(job_receipt) + b"\n",
    )
    terminal: dict[str, Any] = {
        "schema_version": "M2CTerminalDiagnosticRunTerminalV3",
        "run_id": run.run_id,
        "ordinal": run.ordinal,
        "condition": run.condition,
        "claim_sha256": job_receipt["claim_sha256"],
        "stage_completed": False,
        "probe_returncode": None,
        "raw_evidence_sha256": None,
        "status": "INCOMPLETE",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    error: BaseException | None = None
    try:
        stage = _run_container(
            stage_command,
            name=stage_name,
            timeout_s=args.stage_timeout_s,
        )
        (stage_root / "console.log").write_text(
            stage.stdout + stage.stderr,
            encoding="utf-8",
        )
        if stage.returncode != 0 or not _stage_is_valid(
            stage_root=stage_root,
            sdf=args.sdf,
            supervision=args.supervision,
            urdf=args.urdf,
        ):
            raise TerminalDiagnosticError("V3 stage failed its source-hash gate")
        terminal["stage_completed"] = True
        for member in (stage_root / "metrics.json", stage_root / "m1b_physics_scene.usdc"):
            member.chmod(0o400)
        probe_command = _probe_command_v3(
            image_id=image_id,
            gpu=args.gpu,
            container_name=probe_name,
            snapshot_root=snapshot_root,
            source_root=args.source_root,
            derived_probe=derived_probe,
            stage_root=stage_root,
            probe_root=probe_root,
            claim_projection=claim_projection,
            run=run,
            sdf=args.sdf,
            supervision=args.supervision,
            urdf=args.urdf,
            stage_command=stage_command,
            scripted_bin_cell=_scripted_bin_cell(args.supervision),
        )
        terminal["probe_command_sha256"] = canonical_sha256(probe_command)
        probe = _run_container(
            probe_command,
            name=probe_name,
            timeout_s=args.probe_timeout_s,
        )
        terminal["probe_returncode"] = probe.returncode
        (probe_root / "console.log").write_text(
            probe.stdout + probe.stderr,
            encoding="utf-8",
        )
        raw_path = probe_root / "terminal-regrasp-diagnostic.json"
        if not raw_path.is_file():
            raise TerminalDiagnosticError("V3 probe emitted no terminal raw evidence")
        raw = parse_diagnostic_raw_bytes_v3(v4_auth.read_regular_file_once(raw_path))
        if raw.run_id != run.run_id:
            raise TerminalDiagnosticError("V3 raw evidence belongs to another run")
        terminal["raw_evidence_sha256"] = _sha256_file(raw_path)
        terminal["status"] = (
            "COMPLETE_VALID_TERMINAL_MEASUREMENT"
            if raw.terminal_measurement_valid
            else "COMPLETE_NO_VALID_TERMINAL_MEASUREMENT"
        )
    except BaseException as caught:
        error = caught
        terminal["error_type"] = type(caught).__name__
    finally:
        terminal["terminalized_at_ns"] = time.time_ns()
        terminal["terminal_receipt_sha256"] = canonical_sha256(terminal)
        _write_create_only(
            job_root / "terminal-receipt.json",
            canonical_json_bytes(terminal) + b"\n",
        )
        _seal_container_output(stage_root)
        _seal_container_output(probe_root)
    if error is not None:
        raise error
    return terminal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--upstream-v4-probe", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sdf", type=Path, required=True)
    parser.add_argument("--supervision", type=Path, required=True)
    parser.add_argument("--urdf", type=Path, required=True)
    parser.add_argument("--image", default=ISAAC_IMAGE)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--container-prefix", default="m2c-terminal-diagnostic-v3")
    parser.add_argument("--stage-timeout-s", type=float, default=900.0)
    parser.add_argument("--probe-timeout-s", type=float, default=5400.0)
    args = parser.parse_args()
    result = run_one_v3(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
