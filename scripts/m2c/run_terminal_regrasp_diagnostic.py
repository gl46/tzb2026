#!/usr/bin/env python3
"""Run exactly one consumed ADR-0026 terminal-regrasp diagnostic attempt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any

from m2c.derive_terminal_regrasp_diagnostic_probe import (
    derive_terminal_regrasp_diagnostic_probe_bytes,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    TARGET_ENTITY,
    SCRIPTED_BLOCKER_ENTITY,
    TerminalDiagnosticError,
    canonical_json_bytes,
    canonical_sha256,
    consume_diagnostic_run,
    load_committed_diagnostic_prereg,
    parse_diagnostic_raw_bytes,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_USER = "isaac-sim"
RUNTIME_UID = 1234
RUNTIME_GID = 1234
DECISION_SOURCE = "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"


def _sha256_file(path: Path) -> str:
    return sha256_bytes(v4_auth.read_regular_file_once(path))


def _write_create_only(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise TerminalDiagnosticError("short diagnostic artifact write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _prepare_container_output(path: Path) -> None:
    path.mkdir(mode=0o700)
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    path.chmod(0o700)
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != RUNTIME_UID
        or info.st_gid != RUNTIME_GID
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise TerminalDiagnosticError("diagnostic container output metadata is unsafe")


def _seal_container_output(path: Path) -> None:
    root = path.resolve(strict=True)
    allowed_owners = {os.geteuid(), RUNTIME_UID}
    directories = [root]
    for member in root.rglob("*"):
        info = member.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or info.st_uid not in allowed_owners:
            raise TerminalDiagnosticError("diagnostic output contains unsafe ownership or symlink")
        if stat.S_ISDIR(info.st_mode):
            directories.append(member)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            member.chmod(0o400)
        else:
            raise TerminalDiagnosticError("diagnostic output contains a special or hardlinked file")
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        directory.chmod(0o500)


def _require_image_runtime_user(image_id: str) -> None:
    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Config.User}}", image_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0 or completed.stdout.strip() != RUNTIME_USER:
        raise TerminalDiagnosticError("diagnostic image runtime user differs from freeze")


def _remove_named_container(name: str) -> None:
    completed = subprocess.run(
        ["docker", "rm", "-f", name],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise TerminalDiagnosticError(f"cannot prove diagnostic container absent: {name}")


def _run_container(
    command: list[str],
    *,
    name: str,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        _remove_named_container(name)
        raise


def _project_claim(claim: Path, destination: Path) -> Path:
    raw = v4_auth.read_regular_file_once(claim)
    projected = destination / "diagnostic-claim.json"
    _write_create_only(projected, raw, mode=0o400)
    os.chown(projected, RUNTIME_UID, RUNTIME_GID)
    projected.chmod(0o400)
    if v4_auth.read_regular_file_once(projected) != raw:
        raise TerminalDiagnosticError("diagnostic claim projection changed")
    return projected


def _stage_command(
    *,
    image_id: str,
    gpu: int,
    container_name: str,
    snapshot_root: Path,
    source_root: Path,
    stage_root: Path,
    sdf: Path,
    supervision: Path,
    urdf: Path,
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--gpus",
        f"device={gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{snapshot_root}:/workspace/project:ro",
        "-v",
        f"{source_root}:/workspace/source:ro",
        "-v",
        f"{stage_root}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        image_id,
        "scripts/isaac_m1b_dataset_benchmark.py",
        "--sdf",
        f"/workspace/source/{sdf.name}",
        "--supervision",
        f"/workspace/source/{supervision.name}",
        "--urdf",
        f"/workspace/source/{urdf.name}",
        "--output",
        "/workspace/output",
        "--worker-id",
        "0",
        "--physical-gpu-index",
        "0",
        "--frames",
        "1",
        "--warmup-frames",
        "1",
    ]


def _stage_is_valid(*, stage_root: Path, sdf: Path, supervision: Path, urdf: Path) -> bool:
    metrics_path = stage_root / "metrics.json"
    stage_path = stage_root / "m1b_physics_scene.usdc"
    if not metrics_path.is_file() or not stage_path.is_file():
        return False
    try:
        metrics = json.loads(v4_auth.read_regular_file_once(metrics_path))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    hashes = metrics.get("source_hashes") if isinstance(metrics, dict) else None
    clean = metrics.get("clean_physics_stage") if isinstance(metrics, dict) else None
    return bool(
        metrics.get("status") == "PASS"
        and isinstance(hashes, dict)
        and hashes.get(sdf.name) == _sha256_file(sdf)
        and hashes.get(supervision.name) == _sha256_file(supervision)
        and hashes.get(urdf.name) == _sha256_file(urdf)
        and isinstance(clean, dict)
        and clean.get("sha256") == _sha256_file(stage_path)
    )


def _probe_command(
    *,
    image_id: str,
    gpu: int,
    container_name: str,
    snapshot_root: Path,
    source_root: Path,
    derived_probe: Path,
    stage_root: Path,
    probe_root: Path,
    claim_projection: Path,
    run: Any,
    sdf: Path,
    supervision: Path,
    urdf: Path,
    stage_command: list[str],
    scripted_bin_cell: int,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--gpus",
        f"device={gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{snapshot_root}:/workspace/project:ro",
        "-v",
        f"{source_root}:/workspace/source:ro",
        "-v",
        f"{derived_probe.parent}:/workspace/derived:ro",
        "-v",
        f"{stage_root}:/workspace/stage:ro",
        "-v",
        f"{probe_root}:/workspace/output",
        "-v",
        f"{claim_projection}:/workspace/authorization/diagnostic-claim.json:ro",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        image_id,
        f"/workspace/derived/{derived_probe.name}",
        "--stage",
        "/workspace/stage/m1b_physics_scene.usdc",
        "--sdf",
        f"/workspace/source/{sdf.name}",
        "--supervision",
        f"/workspace/source/{supervision.name}",
        "--urdf",
        f"/workspace/source/{urdf.name}",
        "--output",
        "/workspace/output",
        "--physics-device",
        "cuda",
        "--contact-centerlines-m",
        "0.12,0.11,0.10,0.09,0.08",
        "--gripper-close-steps",
        "132",
        "--calibration-free-gap-yaw",
        "--m2b-capture-public-rgbd",
        "--m2b-task-target-public-color",
        "yellow",
        "--m2b-public-regrasp-offset-camera-xyz-m",
        "0,0,0",
        "--m2c-chain-role",
        "DIAGNOSTIC",
        "--m2c-split",
        "test",
        "--m2c-matched-key",
        run.matched_key,
        "--m2c-failure-seed",
        str(run.failure_seed),
        "--m2c-decision-source",
        DECISION_SOURCE,
        "--m2c-declared-target-attribute",
        "yellow",
        "--m2c-diagnostic-condition",
        run.condition,
        "--m2c-diagnostic-run-id",
        run.run_id,
        "--m2c-collection-claim",
        "/workspace/authorization/diagnostic-claim.json",
        "--m2c-source-snapshot-root",
        "/workspace/project",
        "--m2c-container-image-id",
        image_id,
        "--m2c-docker-command-sha256",
        "0" * 64,
        "--m2c-stage-metrics-sha256",
        _sha256_file(stage_root / "metrics.json"),
        "--m2c-stage-command-sha256",
        canonical_sha256(stage_command),
        "--m2c-job-root-sha256",
        canonical_sha256(str(probe_root.parent.resolve(strict=True))),
        "--m2c-probe-output-root-sha256",
        canonical_sha256(str(probe_root.resolve(strict=True))),
    ]
    if run.condition == "C3_FULL_V4":
        command.extend(
            [
                "--target-object",
                SCRIPTED_BLOCKER_ENTITY,
                "--m2b-task-target-object",
                TARGET_ENTITY,
                "--m2b-injected-public-grasp-color",
                "red",
                "--m2c-scripted-safe-place-bin-cell",
                str(scripted_bin_cell),
            ]
        )
    else:
        command.extend(["--target-object", TARGET_ENTITY])
    digest_index = command.index("--m2c-docker-command-sha256") + 1
    command[digest_index] = canonical_sha256(command)
    return command


def _scripted_bin_cell(supervision: Path) -> int:
    payload = json.loads(v4_auth.read_regular_file_once(supervision))
    value = payload.get("m2c_headroom_domain", {}).get("scripted_bin_cell_index")
    if not isinstance(value, int) or value < 0:
        raise TerminalDiagnosticError("diagnostic supervision lacks scripted bin cell")
    return value


def run_one(args: argparse.Namespace) -> dict[str, Any]:
    root = args.project_root.resolve(strict=True)
    resolved = load_committed_diagnostic_prereg(
        project_root=root,
        prereg_path=args.prereg,
    )
    selected = [run for run in resolved.prereg.runs if run.run_id == args.run_id]
    if len(selected) != 1:
        raise TerminalDiagnosticError("diagnostic run ID is not uniquely preregistered")
    run = selected[0]
    if args.image != ISAAC_IMAGE:
        raise TerminalDiagnosticError("diagnostic image tag differs from preregistration")
    source_info = args.source_root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(source_info.st_mode)
        or stat.S_IMODE(source_info.st_mode) != 0o555
        or source_info.st_uid != os.geteuid()
    ):
        raise TerminalDiagnosticError("diagnostic source root is not owned read-only evidence")
    for path, expected, label in (
        (args.sdf, run.sdf_sha256, "SDF"),
        (args.supervision, run.supervision_sha256, "supervision"),
        (args.urdf, resolved.prereg.controlled_urdf_sha256, "URDF"),
    ):
        if path.parent.resolve(strict=True) != args.source_root.resolve(strict=True):
            raise TerminalDiagnosticError(f"diagnostic {label} is not directly under source root")
        if _sha256_file(path) != expected:
            raise TerminalDiagnosticError(f"diagnostic {label} digest differs from preregistration")
    if _sha256_file(args.upstream_v4_probe) != resolved.prereg.upstream_v4_probe_sha256:
        raise TerminalDiagnosticError("diagnostic upstream probe digest differs from freeze")
    derived_bytes = derive_terminal_regrasp_diagnostic_probe_bytes(
        v4_auth.read_regular_file_once(args.upstream_v4_probe)
    )
    derived_sha = sha256_bytes(derived_bytes)
    image_id = v4_auth.resolve_docker_image_id(image=args.image)
    if image_id != ISAAC_IMAGE_ID:
        raise TerminalDiagnosticError("diagnostic image ID differs from preregistration")
    _require_image_runtime_user(image_id)
    snapshot_root = v4_auth.materialize_committed_source_snapshot(
        project_root=root,
        expected=resolved.prereg.committed_source_snapshot,
    )
    require_pre_freeze(M2CExperimentAction.ISAAC_COLLECTION)

    output_info = args.output_root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(output_info.st_mode)
        or output_info.st_uid != os.geteuid()
        or stat.S_IMODE(output_info.st_mode) != 0o700
    ):
        raise TerminalDiagnosticError("diagnostic output root must be an owned 0700 directory")
    job_root = (
        args.output_root
        / f"run-{run.ordinal:02d}-{run.run_id.removeprefix('m2c-s4-terminal-diagnostic-')[:16]}"
    )
    if job_root.exists():
        raise FileExistsError(f"refusing to overwrite diagnostic job: {job_root}")
    job_root.mkdir(mode=0o700)
    derived_root = job_root / "derived"
    authorization_root = job_root / "authorization"
    derived_root.mkdir(mode=0o700)
    authorization_root.mkdir(mode=0o700)
    derived_probe = derived_root / "terminal-regrasp-diagnostic-probe.py"
    _write_create_only(derived_probe, derived_bytes, mode=0o555)
    derived_root.chmod(0o555)
    stage_root = job_root / "stage"
    probe_root = job_root / "probe"
    _prepare_container_output(stage_root)
    _prepare_container_output(probe_root)

    claim = consume_diagnostic_run(
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
        "schema_version": "M2CTerminalDiagnosticJobReceiptV1",
        "status": "CONSUMED_DIAGNOSTIC_ONLY_BEFORE_STAGE",
        "campaign_id": resolved.prereg.campaign_id,
        "run": run.model_dump(mode="json"),
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": resolved.prereg.prereg_sha256,
        "claim_path": str(claim),
        "claim_sha256": _sha256_file(claim),
        "derived_probe_sha256": derived_sha,
        "source_snapshot": resolved.prereg.committed_source_snapshot.model_dump(mode="json"),
        "image_id": image_id,
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
        "schema_version": "M2CTerminalDiagnosticRunTerminalV1",
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
        stage = _run_container(stage_command, name=stage_name, timeout_s=args.stage_timeout_s)
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
            raise TerminalDiagnosticError("diagnostic stage failed its source-hash gate")
        terminal["stage_completed"] = True
        for member in (stage_root / "metrics.json", stage_root / "m1b_physics_scene.usdc"):
            member.chmod(0o400)
        probe_command = _probe_command(
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
        probe = _run_container(probe_command, name=probe_name, timeout_s=args.probe_timeout_s)
        terminal["probe_returncode"] = probe.returncode
        (probe_root / "console.log").write_text(
            probe.stdout + probe.stderr,
            encoding="utf-8",
        )
        raw_path = probe_root / "terminal-regrasp-diagnostic.json"
        if not raw_path.is_file():
            raise TerminalDiagnosticError("diagnostic probe emitted no terminal raw evidence")
        raw = parse_diagnostic_raw_bytes(v4_auth.read_regular_file_once(raw_path))
        if raw.run_id != run.run_id:
            raise TerminalDiagnosticError("diagnostic raw evidence belongs to another run")
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
    parser.add_argument("--container-prefix", default="m2c-terminal-diagnostic")
    parser.add_argument("--stage-timeout-s", type=float, default=900.0)
    parser.add_argument("--probe-timeout-s", type=float, default=5400.0)
    args = parser.parse_args()
    result = run_one(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
