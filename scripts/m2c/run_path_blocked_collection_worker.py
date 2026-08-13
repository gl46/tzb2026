#!/usr/bin/env python3
"""Build or run one frozen M2C PATH_BLOCKED TRAIN/SMOKE collection job.

The worker is deliberately single-key and create-only.  Historical V2
``--dry-run`` emits exact commands without launching Docker; V3 dry-run is
fail-closed because an executable probe must never exist outside a consumed
preregistration.  A live run first builds a clean Isaac stage, then executes
the derived public scripted chain; it never loads a model checkpoint and never
counts as model-owned Q-B eval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
from typing import Any


def _bootstrap_option(argv: list[str], name: str) -> str | None:
    """Parse one non-repeatable long option without project imports."""

    prefix = f"{name}="
    matches: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value.startswith(prefix):
            candidate = value[len(prefix) :]
            if not candidate:
                raise RuntimeError(f"pre-import option {name} has an empty value")
            matches.append(candidate)
        elif value == name:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise RuntimeError(f"pre-import option {name} lacks a value")
            matches.append(argv[index + 1])
            index += 1
        index += 1
    if len(matches) > 1:
        raise RuntimeError(f"pre-import option {name} is repeated")
    return matches[0] if matches else None


def _bootstrap_git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pre-import git {' '.join(args)} failed")
    return completed.stdout


def _bootstrap_read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("pre-import preregistration is not a single regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _preimport_v3_checkout_guard(*, project_root: Path, prereg_path: Path) -> None:
    """Freeze the host import tree before any M2C project module executes."""

    root = project_root.resolve(strict=True)
    prereg = prereg_path.resolve(strict=True)
    try:
        relative = prereg.relative_to(root).as_posix()
    except ValueError as error:
        raise RuntimeError("pre-import preregistration escapes the project root") from error
    raw = _bootstrap_read_regular(prereg)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("pre-import preregistration is not strict JSON") from error
    if not isinstance(payload, dict) or payload.get("repository_relative_path") != relative:
        raise RuntimeError("pre-import preregistration path binding is invalid")
    head = _bootstrap_git(root, "rev-parse", "HEAD").decode().strip()
    introductions = (
        _bootstrap_git(root, "log", "--diff-filter=A", "--format=%H", "--", relative)
        .decode()
        .splitlines()
    )
    if not introductions or head != introductions[0]:
        raise RuntimeError("pre-import preregistration must be the current HEAD")
    if _bootstrap_git(root, "show", f"HEAD:{relative}") != raw:
        raise RuntimeError("pre-import preregistration differs from HEAD bytes")
    changed = set(
        _bootstrap_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head)
        .decode()
        .splitlines()
    )
    if changed != {relative}:
        raise RuntimeError("pre-import preregistration commit is not prereg-only")
    if _bootstrap_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ):
        raise RuntimeError("pre-import host checkout is not clean")
    ignored_runtime = _bootstrap_git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        "src/xh_agent",
        "scripts/m2c",
    )
    if ignored_runtime:
        raise RuntimeError("pre-import runtime roots contain ignored shadow bytes")
    # Imports that follow are compiled only in memory; no unchecked bytecode
    # may appear between this gate and the later full-tree replay.
    sys.dont_write_bytecode = True


def _run_cli_preimport_guard() -> None:
    argv = sys.argv[1:]
    revision = _bootstrap_option(argv, "--revision") or "V4"
    if revision in {"V2", "V4"}:
        return
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.dont_write_bytecode
        and sys.flags.safe_path
    ):
        raise RuntimeError("V3 CLI must use the project venv Python with -I -S -B")
    project = _bootstrap_option(argv, "--project-root")
    prereg = _bootstrap_option(argv, "--collection-prereg")
    if not project or not prereg:
        raise RuntimeError("V3 CLI requires project root and committed preregistration")
    _preimport_v3_checkout_guard(
        project_root=Path(project),
        prereg_path=Path(prereg),
    )
    root = Path(project).resolve(strict=True)
    venv_root = Path(sys.executable).absolute().parent.parent
    site_packages = (
        venv_root
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    if not site_packages.is_dir():
        raise RuntimeError("V3 isolated host dependency directory is unavailable")
    # Plain path insertion deliberately avoids site.addsitedir: no .pth or
    # sitecustomize code executes. Project roots were just verified clean.
    sys.path[:0] = [str(root / "scripts"), str(root / "src"), str(site_packages)]


if __name__ == "__main__":
    try:
        _run_cli_preimport_guard()
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"M2C V3 pre-import gate blocked: {error}") from error


from m2c.derive_model_owned_chain_probe import (  # noqa: E402
    derive_probe_bytes,
    derive_probe_bytes_v3,
    derive_probe_bytes_v4,
)
from m2c.s4_scene_family import SCRIPTED_BLOCKER_ENTITY, TARGET_ENTITY  # noqa: E402
from m2c.package_path_blocked_collection import (  # noqa: E402
    DECISION_SOURCE,
    frozen_source_record,
    load_json_object,
    package_collection,
    project_frozen_manifests,
    sha256_file,
)
from xh_agent.data.isaac_m1b import M1B_URDF_SHA256  # noqa: E402
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (  # noqa: E402
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (  # noqa: E402
    load_v3_training_manifest,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (  # noqa: E402
    load_v4_training_manifest,
)
from xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1 import (  # noqa: E402
    CollectionAuthorizationError,
    FROZEN_UPSTREAM_V4_PROBE_SHA256,
    ResolvedCollectionPreregV1,
    canonical_path_sha256,
    canonical_sha256,
    consume_collection_key,
    consume_probe_launch,
    issue_probe_start_capability,
    load_committed_collection_prereg,
    materialize_committed_source_snapshot,
    probe_entry_broker_socket_path,
    probe_entry_broker_token_path,
    probe_start_capability_path,
    resolve_docker_image_id,
    start_probe_entry_broker,
    terminalize_probe_launch,
    verify_consumed_collection_key,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as v4_auth  # noqa: E402


ISAAC_IMAGE = "nvcr.io/nvidia/isaac-sim:6.0.1"
V4_ISAAC_RUNTIME_USER = "isaac-sim"
V4_ISAAC_RUNTIME_UID = 1234
V4_ISAAC_RUNTIME_GID = 1234
TASK_TARGET_PUBLIC_COLOR = "yellow"
BLOCKER_PUBLIC_COLOR = "red"


def _revision(args: argparse.Namespace) -> str:
    # Programmatic V2 callers predate the CLI revision flag; preserving that
    # default keeps historical evidence semantics unchanged.
    return str(getattr(args, "revision", "V2"))


def _validate_direct_source(path: Path, root: Path, *, label: str) -> None:
    if not path.is_file() or path.parent.resolve() != root.resolve():
        raise ValueError(f"{label} must be a direct file under source root: {path}")


def validate_frozen_scene_semantics(
    supervision: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Cross-check evaluator-only roles against the frozen public selectors."""

    headroom = supervision.get("m2c_headroom_domain")
    if not isinstance(headroom, dict):
        raise ValueError("scene lacks the frozen M2C headroom domain contract")
    if (
        headroom.get("target_entity_evaluator_only") != TARGET_ENTITY
        or headroom.get("scripted_blocker_entity_evaluator_only") != SCRIPTED_BLOCKER_ENTITY
        or headroom.get("target_selector") != record["target_selector_policy_input"]
        or headroom.get("scripted_blocker_selector") != record["blocker_selector_policy_input"]
        or headroom.get("scripted_bin_cell_index")
        != int(str(record["destination_cell"]).removeprefix("BIN_CELL_"))
    ):
        raise ValueError("scene roles, public selectors, or destination differ from frozen key")


def stage_command(
    args: argparse.Namespace,
    *,
    output: Path,
    image_reference: str | None = None,
    project_mount: Path | None = None,
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{args.container_prefix}-stage",
        "--gpus",
        f"device={args.gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{project_mount or args.project_root}:/workspace/project:ro",
        "-v",
        f"{args.source_root}:/workspace/source:ro",
        "-v",
        f"{output}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        image_reference or args.image,
        "scripts/isaac_m1b_dataset_benchmark.py",
        "--sdf",
        f"/workspace/source/{args.sdf.name}",
        "--supervision",
        f"/workspace/source/{args.supervision.name}",
        "--urdf",
        f"/workspace/source/{args.urdf.name}",
        "--output",
        "/workspace/output",
        "--worker-id",
        "0",
        "--physical-gpu-index",
        # Docker remaps the selected host device to cuda:0 inside the
        # single-GPU container.  Passing the host ordinal here makes a
        # host-GPU-1 worker request a nonexistent in-container cuda:1.
        "0",
        "--frames",
        "1",
        "--warmup-frames",
        "1",
    ]


def probe_command(
    args: argparse.Namespace,
    *,
    derived_probe: Path,
    stage: Path,
    output: Path,
    source_record: dict[str, Any],
    container_image_id: str | None = None,
    collection_prereg: ResolvedCollectionPreregV1 | None = None,
    collection_claim: Path | None = None,
    collection_start_capability: Path | None = None,
    collection_probe_entry_broker_socket: Path | None = None,
    collection_probe_entry_token_file: Path | None = None,
    source_snapshot_root: Path | None = None,
) -> list[str]:
    protected = _revision(args) in {"V3", "V4"}
    image_reference = container_image_id if protected and container_image_id else args.image
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{args.container_prefix}-probe",
        "--gpus",
        f"device={args.gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{args.project_root}:/workspace/project:ro",
        "-v",
        f"{args.source_root}:/workspace/source:ro",
        "-v",
        f"{derived_probe.parent}:/workspace/derived:ro",
        "-v",
        f"{stage.parent}:/workspace/stage:ro",
        "-v",
        f"{output}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        image_reference,
        f"/workspace/derived/{derived_probe.name}",
        "--stage",
        f"/workspace/stage/{stage.name}",
        "--sdf",
        f"/workspace/source/{args.sdf.name}",
        "--supervision",
        f"/workspace/source/{args.supervision.name}",
        "--urdf",
        f"/workspace/source/{args.urdf.name}",
        "--output",
        "/workspace/output",
        "--target-object",
        SCRIPTED_BLOCKER_ENTITY,
        "--m2b-task-target-object",
        TARGET_ENTITY,
        "--physics-device",
        "cuda",
        "--contact-centerlines-m",
        "0.12,0.11,0.10,0.09,0.08",
        "--gripper-close-steps",
        "132",
        "--calibration-free-gap-yaw",
        "--m2b-capture-public-rgbd",
        "--m2b-task-target-public-color",
        TASK_TARGET_PUBLIC_COLOR,
        "--m2b-injected-public-grasp-color",
        BLOCKER_PUBLIC_COLOR,
        "--m2c-scripted-safe-place-bin-cell",
        str(source_record["destination_cell"]).removeprefix("BIN_CELL_"),
        "--m2c-chain-role",
        args.role,
        "--m2c-split",
        str(source_record["split"]),
        "--m2c-matched-key",
        args.matched_key,
        "--m2c-failure-seed",
        str(source_record["failure_seed"]),
        "--m2c-decision-source",
        DECISION_SOURCE,
        *(
            [
                "--m2c-declared-target-attribute",
                str(source_record["declared_target_attribute"]),
            ]
            if protected
            else []
        ),
    ]
    if protected:
        revision = _revision(args)
        if (
            collection_prereg is None
            or collection_claim is None
            or source_snapshot_root is None
            or (
                revision == "V3"
                and (
                    collection_start_capability is None
                    or collection_probe_entry_broker_socket is None
                    or collection_probe_entry_token_file is None
                )
            )
        ):
            raise CollectionAuthorizationError(
                f"{_revision(args)} probe command lacks collection authorization"
            )
        if container_image_id is None:
            raise CollectionAuthorizationError(
                f"{_revision(args)} probe command lacks the resolved image ID"
            )
        # V4 uses ADR-0024's accepted immutable-snapshot + create-only claim
        # evidence bar. V3 retains its historical launcher/broker plumbing.
        command[command.index(f"{args.project_root}:/workspace/project:ro")] = (
            f"{source_snapshot_root}:/workspace/project:ro"
        )
        mounts: list[str] = []
        if revision == "V3":
            ledger_root = Path(collection_prereg.prereg.ledger_root)
            mounts.extend(
                [
                    "-v",
                    f"{ledger_root}:{ledger_root}:ro",
                    "-v",
                    f"{Path(collection_probe_entry_broker_socket).parent}:"
                    f"{Path(collection_probe_entry_broker_socket).parent}:ro",
                ]
            )
        else:
            mounts.extend(
                [
                    "-v",
                    f"{collection_claim}:/workspace/authorization/collection-claim-v4.json:ro",
                ]
            )
        command[command.index("-w") : command.index("-w")] = mounts
        command.extend(
            [
                "--m2c-collection-claim",
                (
                    "/workspace/authorization/collection-claim-v4.json"
                    if revision == "V4"
                    else str(collection_claim)
                ),
                "--m2c-source-snapshot-root",
                "/workspace/project",
                "--m2c-container-image-id",
                container_image_id,
                "--m2c-docker-command-sha256",
                "0" * 64,
                "--m2c-stage-metrics-sha256",
                "0" * 64,
                "--m2c-stage-command-sha256",
                canonical_sha256(
                    stage_command(
                        args,
                        output=stage.parent,
                        image_reference=container_image_id,
                        project_mount=source_snapshot_root,
                    )
                ),
                "--m2c-job-root-sha256",
                canonical_path_sha256(output.parent),
                "--m2c-probe-output-root-sha256",
                canonical_path_sha256(output),
            ]
        )
        if revision == "V3":
            command.extend(
                [
                    "--m2c-probe-start-capability",
                    str(collection_start_capability),
                    "--m2c-probe-entry-broker-socket",
                    str(collection_probe_entry_broker_socket),
                    "--m2c-probe-entry-token-file",
                    str(collection_probe_entry_token_file),
                ]
            )
        digest_index = command.index("--m2c-docker-command-sha256") + 1
        command[digest_index] = canonical_sha256(command)
    return command


def stage_is_valid(
    stage_root: Path,
    *,
    sdf: Path,
    supervision: Path,
    urdf: Path,
) -> bool:
    metrics_path = stage_root / "metrics.json"
    stage_path = stage_root / "m1b_physics_scene.usdc"
    if not metrics_path.is_file() or not stage_path.is_file():
        return False
    metrics = load_json_object(metrics_path, label="Isaac stage metrics")
    hashes = metrics.get("source_hashes")
    clean = metrics.get("clean_physics_stage")
    return bool(
        metrics.get("status") == "PASS"
        and isinstance(hashes, dict)
        and hashes.get(sdf.name) == sha256_file(sdf)
        and hashes.get(supervision.name) == sha256_file(supervision)
        and hashes.get(urdf.name) == sha256_file(urdf)
        and isinstance(clean, dict)
        and clean.get("sha256") == sha256_file(stage_path)
    )


def _write_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _run_probe_command(
    command: list[str],
    *,
    container_name: str,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    """Run one probe and prove a timed-out named container was removed."""

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as error:
        removal = subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if removal.returncode != 0:
            raise CollectionAuthorizationError(
                "timed-out probe container could not be stopped and removed"
            ) from error
        stdout = (
            error.stdout.decode(errors="replace")
            if isinstance(error.stdout, bytes)
            else (error.stdout or "")
        )
        stderr = (
            error.stderr.decode(errors="replace")
            if isinstance(error.stderr, bytes)
            else (error.stderr or "")
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=stdout,
            stderr=stderr + "\nM2C_PROBE_TIMEOUT_TERMINALIZED\n",
        )


def _remove_named_container(*, container_name: str) -> None:
    """Fail closed unless Docker proves a named experimental container is gone."""

    removal = subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if removal.returncode != 0:
        raise CollectionAuthorizationError(
            f"experimental container could not be stopped and removed: {container_name}"
        )


def _run_stage_command(
    command: list[str],
    *,
    container_name: str,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    """Run stage generation and contain timeout/spawn failures."""

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        _remove_named_container(container_name=container_name)
        raise


def _require_v4_image_runtime_user(*, image_reference: str) -> None:
    """Bind writable output ownership to the frozen Isaac image user."""

    completed = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Config.User}}",
            image_reference,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    values = completed.stdout.splitlines()
    if completed.returncode != 0 or len(values) != 1 or values[0].strip() != V4_ISAAC_RUNTIME_USER:
        raise CollectionAuthorizationError("frozen V4 Isaac image runtime user is not isaac-sim")


def _prepare_v4_container_output_directory(
    path: Path,
    *,
    owner_uid: int = V4_ISAAC_RUNTIME_UID,
    owner_gid: int = V4_ISAAC_RUNTIME_GID,
) -> None:
    """Create one private output mount writable by the frozen image user."""

    path.mkdir()
    os.chown(path, owner_uid, owner_gid)
    path.chmod(0o700)
    info = path.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != owner_uid
        or info.st_gid != owner_gid
    ):
        raise CollectionAuthorizationError(
            "V4 container output directory ownership or mode is unsafe"
        )


def _project_v4_claim_for_container(
    *,
    canonical_claim: Path,
    job_root: Path,
    owner_uid: int = V4_ISAAC_RUNTIME_UID,
    owner_gid: int = V4_ISAAC_RUNTIME_GID,
) -> Path:
    """Publish an exact read-only claim projection for the image user.

    The canonical append-only ledger remains root-only. The probe sees only
    this byte-identical file; host packaging later reopens the canonical
    ledger claim and verifies its semantic receipt hash.
    """

    raw = v4_auth.read_regular_file_once(canonical_claim)
    v4_auth.M2CS4V4CollectionConsumptionReceiptV1.model_validate_json(raw)
    projection_root = job_root / "authorization"
    projection_root.mkdir()
    projection = projection_root / "collection-claim-v4.json"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(projection, flags, 0o400)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise CollectionAuthorizationError("short write publishing V4 claim projection")
            offset += written
        os.fsync(descriptor)
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fchmod(descriptor, 0o400)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o400
            or info.st_uid != owner_uid
            or info.st_gid != owner_gid
            or info.st_nlink != 1
        ):
            raise CollectionAuthorizationError("V4 claim projection metadata is unsafe")
    finally:
        os.close(descriptor)
    os.chown(projection_root, owner_uid, owner_gid)
    projection_root.chmod(0o500)
    root_info = projection_root.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_IMODE(root_info.st_mode) != 0o500
        or root_info.st_uid != owner_uid
        or root_info.st_gid != owner_gid
        or v4_auth.read_regular_file_once(projection) != raw
    ):
        raise CollectionAuthorizationError("V4 claim projection differs from canonical ledger")
    directory_fd = os.open(projection_root, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return projection


def _seal_v4_container_output_directory(path: Path) -> None:
    """Make a completed V4 container output tree host-read-only."""

    root = path.resolve(strict=True)
    allowed_owners = {os.geteuid(), V4_ISAAC_RUNTIME_UID}
    directories = [root]
    for member in root.rglob("*"):
        info = member.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or info.st_uid not in allowed_owners:
            raise CollectionAuthorizationError(
                "V4 container output contains unsafe ownership or a symlink"
            )
        if stat.S_ISDIR(info.st_mode):
            directories.append(member)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            member.chmod(0o400)
        else:
            raise CollectionAuthorizationError(
                "V4 container output contains a special or multiply-linked file"
            )
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        directory.chmod(0o500)


def prepare_job(
    args: argparse.Namespace,
    *,
    collection_prereg: ResolvedCollectionPreregV1 | None = None,
    collection_claim: Path | None = None,
    container_image_id: str | None = None,
    derived_probe_bytes: bytes | None = None,
    source_snapshot_root: Path | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Fail closed on sources/key, derive the probe, and return exact commands."""

    revision = _revision(args)
    protected = revision in {"V3", "V4"}
    if protected and (
        collection_prereg is None or collection_claim is None or source_snapshot_root is None
    ):
        raise CollectionAuthorizationError(
            f"{revision} collection requires a committed preregistration and consumed key claim"
        )
    for root, label in (
        (args.project_root, "project root"),
        (args.source_root, "source root"),
    ):
        if not root.is_dir():
            raise ValueError(f"{label} is not a directory: {root}")
    for source, label in (
        (args.sdf, "SDF"),
        (args.supervision, "supervision"),
        (args.urdf, "URDF"),
    ):
        _validate_direct_source(source, args.source_root, label=label)
    for source, label in (
        (args.upstream_v4_probe, "frozen V4 probe"),
        (args.training_keys, "training key manifest"),
        (args.s6_keys, "S6 key manifest"),
        (args.runtime_registry, "runtime registry"),
    ):
        if not source.is_file():
            raise ValueError(f"{label} is missing: {source}")

    if protected:
        expected_derived = derived_probe_bytes or (
            derive_probe_bytes_v4(args.upstream_v4_probe.read_bytes())
            if revision == "V4"
            else derive_probe_bytes_v3(args.upstream_v4_probe.read_bytes())
        )
        verify_claim = (
            v4_auth.verify_consumed_collection_key
            if revision == "V4"
            else verify_consumed_collection_key
        )
        claim = verify_claim(
            resolved=collection_prereg,
            claim_path=collection_claim,
            matched_key=args.matched_key,
            source_sdf_sha256=sha256_file(args.sdf),
            source_supervision_sha256=sha256_file(args.supervision),
            source_urdf_sha256=sha256_file(args.urdf),
            upstream_v4_probe_sha256=sha256_file(args.upstream_v4_probe),
            derived_probe_sha256=hashlib.sha256(expected_derived).hexdigest(),
            container_image_id=container_image_id,
            role=args.role,
            split="train",
            declared_target_attribute="yellow",
        )
        if args.role != "TRAIN":
            raise ValueError(f"{revision} collection authorizes TRAIN only; SMOKE is excluded")
        manifest = (
            load_v4_training_manifest(args.training_keys)
            if revision == "V4"
            else load_v3_training_manifest(args.training_keys)
        )
        matches = [item for item in manifest.training_keys if item.matched_key == args.matched_key]
        if len(matches) != 1:
            raise ValueError(f"worker key is not exactly once in frozen {revision} TRAIN manifest")
        record = matches[0].model_dump(mode="json")
        s6_payload = load_json_object(args.s6_keys, label="S6 key manifest")
        s6_records = s6_payload.get("evaluation_keys", [])
        if any(
            isinstance(item, dict)
            and (
                item.get("matched_key") == args.matched_key
                or int(item.get("scene_seed", -1)) == int(record["scene_seed"])
            )
            for item in s6_records
        ) or int(record["scene_seed"]) in {9038, 9057, 9077}:
            raise ValueError("worker request overlaps V4 Q-A or frozen S6")
    else:
        expected_derived = derive_probe_bytes(args.upstream_v4_probe.read_bytes())
        training, _s6, collection, s6 = project_frozen_manifests(
            args.training_keys,
            args.s6_keys,
            args.runtime_registry,
        )
        record = frozen_source_record(training, role=args.role, matched_key=args.matched_key)
        if int(record["scene_seed"]) in {9038, 9057, 9077} or any(
            key.matched_key == args.matched_key or key.scene_seed == int(record["scene_seed"])
            for key in s6.keys
        ):
            raise ValueError("worker request overlaps V4 or frozen S6")
        collection_matches = [key for key in collection.keys if key.matched_key == args.matched_key]
        if len(collection_matches) != 1 or collection_matches[0].collection_role != args.role:
            raise ValueError("worker key is not exactly once in projected collection manifest")
    if sha256_file(args.sdf) != record["sdf_sha256"]:
        raise ValueError("SDF SHA-256 differs from frozen key")
    if sha256_file(args.supervision) != record["supervision_sha256"]:
        raise ValueError("supervision SHA-256 differs from frozen key")
    if args.urdf.name != "panda_controlled.urdf" or sha256_file(args.urdf) != M1B_URDF_SHA256:
        raise ValueError("URDF name or SHA-256 differs from the production Isaac contract")
    validate_frozen_scene_semantics(
        load_json_object(args.supervision, label="scene supervision"),
        record,
    )

    job_root = args.output_root / args.role.lower() / args.matched_key
    if job_root.exists():
        raise FileExistsError(f"refusing to overwrite collection job: {job_root}")
    job_root.mkdir(parents=True, exist_ok=False)
    derived = job_root / "derived-path-blocked-probe.py"
    derived.write_bytes(expected_derived)
    derived.chmod(0o555)
    if protected:
        # The exact derived source is part of the consumed capability. It is
        # checked again by the probe before Kit and by the packager.
        if claim.derived_probe_sha256 != sha256_file(derived):
            raise CollectionAuthorizationError("derived probe differs from consumed claim")
    stage_root = job_root / "stage"
    probe_root = job_root / "probe"
    if revision == "V4":
        _prepare_v4_container_output_directory(stage_root)
        _prepare_v4_container_output_directory(probe_root)
    else:
        stage_root.mkdir()
        probe_root.mkdir()
        stage_root.chmod(0o700 if protected else 0o777)
        probe_root.chmod(0o700 if protected else 0o777)
    probe_claim = (
        _project_v4_claim_for_container(
            canonical_claim=collection_claim,
            job_root=job_root,
        )
        if revision == "V4"
        else collection_claim
    )
    stage_cmd = stage_command(
        args,
        output=stage_root,
        image_reference=container_image_id if protected else None,
        project_mount=source_snapshot_root if protected else None,
    )
    collection_start = (
        probe_start_capability_path(
            resolved=collection_prereg,
            claim_path=collection_claim,
            matched_key=args.matched_key,
        )
        if revision == "V3"
        else None
    )
    collection_probe_entry_broker = (
        probe_entry_broker_socket_path(claim.consumption_id) if revision == "V3" else None
    )
    collection_probe_entry_token = (
        probe_entry_broker_token_path(claim.consumption_id) if revision == "V3" else None
    )
    probe_cmd = probe_command(
        args,
        derived_probe=derived,
        stage=stage_root / "m1b_physics_scene.usdc",
        output=probe_root,
        source_record=record,
        collection_prereg=collection_prereg,
        collection_claim=probe_claim,
        collection_start_capability=collection_start,
        collection_probe_entry_broker_socket=collection_probe_entry_broker,
        collection_probe_entry_token_file=collection_probe_entry_token,
        source_snapshot_root=source_snapshot_root,
        container_image_id=container_image_id,
    )
    job_receipt: dict[str, Any] = {
        "schema_version": (f"M2CPathBlockedCollectionJob{revision}"),
        "collection_contract_revision": revision,
        "candidate_contract_revision": (f"PublicTrackCandidate{revision}" if protected else None),
        "checkpoint_architecture_revision": f"M2C_Q012_{revision}",
        "status": "DRY_RUN_NOT_EXECUTED" if args.dry_run else "PREPARED_NOT_EXECUTED",
        "matched_key": args.matched_key,
        "scene_seed": record["scene_seed"],
        "failure_seed": record["failure_seed"],
        "split": record["split"],
        "collection_role": args.role,
        "decision_source": DECISION_SOURCE,
        "model_owned": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
        "derived_probe": str(derived),
        "derived_probe_sha256": sha256_file(derived),
        "upstream_v4_probe_sha256": sha256_file(args.upstream_v4_probe),
        "sdf_sha256": sha256_file(args.sdf),
        "supervision_sha256": sha256_file(args.supervision),
        "urdf_sha256": sha256_file(args.urdf),
        "training_key_manifest_sha256": sha256_file(args.training_keys),
        "s6_key_manifest_sha256": sha256_file(args.s6_keys),
        "runtime_registry_sha256": sha256_file(args.runtime_registry),
        "committed_source_snapshot": (
            claim.committed_source_snapshot.model_dump(mode="json") if protected else None
        ),
        "container_runtime_identity": (
            {
                "user": V4_ISAAC_RUNTIME_USER,
                "uid": V4_ISAAC_RUNTIME_UID,
                "gid": V4_ISAAC_RUNTIME_GID,
                "writable_output_mode": "0700",
                "completed_output_mode": "0500_DIRECTORIES_0400_FILES",
            }
            if revision == "V4"
            else None
        ),
        "stage_command": stage_cmd,
        "probe_command": probe_cmd,
        "stage_command_shell": shlex.join(stage_cmd),
        "probe_command_shell": shlex.join(probe_cmd),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_executed": False,
        "evaluation_executed": False,
    }
    if protected:
        job_receipt["collection_authorization"] = {
            "schema_version": f"M2CS4{revision}JobAuthorizationBindingV1",
            "prereg_repository_path": collection_prereg.prereg.repository_relative_path,
            "prereg_file_sha256": collection_prereg.file_sha256,
            "prereg_sha256": collection_prereg.prereg.prereg_sha256,
            "prereg_introduced_commit": collection_prereg.introduced_commit,
            "consumption_receipt_path": str(collection_claim),
            "consumption_receipt_sha256": claim.receipt_sha256,
            "container_claim_projection_path": (str(probe_claim) if revision == "V4" else None),
            "container_claim_projection_sha256": (
                sha256_file(probe_claim) if revision == "V4" else None
            ),
            "consumption_id": claim.consumption_id,
            "challenge_nonce": claim.challenge_nonce,
            "committed_source_snapshot": claim.committed_source_snapshot.model_dump(mode="json"),
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "model_rollout": False,
            "formal_q_b_evaluation": False,
        }
    _write_new(
        job_root / f"collection-job-{revision.lower()}.json",
        job_receipt,
    )
    return job_receipt, stage_cmd, probe_cmd


def run(args: argparse.Namespace) -> dict[str, Any]:
    revision = _revision(args)
    protected = revision in {"V3", "V4"}
    collection_prereg: ResolvedCollectionPreregV1 | None = None
    collection_claim: Path | None = None
    container_image_id: str | None = None
    derived_probe_bytes: bytes | None = None
    source_snapshot_root: Path | None = None
    if protected:
        if args.collection_prereg is None or args.collection_ledger_root is None:
            raise CollectionAuthorizationError(
                f"{revision} collection has no active committed preregistration/ledger"
            )
        auth = v4_auth if revision == "V4" else None
        collection_prereg = (
            auth.load_committed_collection_prereg(
                project_root=args.project_root,
                prereg_path=args.collection_prereg,
            )
            if auth is not None
            else load_committed_collection_prereg(
                project_root=args.project_root,
                prereg_path=args.collection_prereg,
            )
        )
        if Path(collection_prereg.prereg.ledger_root) != args.collection_ledger_root:
            raise CollectionAuthorizationError(
                "CLI ledger root differs from committed preregistration"
            )
        if args.image != collection_prereg.prereg.container_image:
            raise CollectionAuthorizationError(
                "CLI Isaac image differs from the preregistered image"
            )
        # Planning must not spend the one physical-attempt authorization or
        # emit a directly executable probe.  Use explicit contract tests for
        # dry validation; a V3 worker dry-run is intentionally unavailable.
        if args.dry_run:
            raise CollectionAuthorizationError(
                f"{revision} dry-run is disabled because it would emit an executable unconsumed probe"
            )
        require_pre_freeze(M2CExperimentAction.ISAAC_COLLECTION)
        if sha256_file(args.upstream_v4_probe) != FROZEN_UPSTREAM_V4_PROBE_SHA256:
            raise CollectionAuthorizationError("upstream V4 probe identity is not frozen")
        derived_probe_bytes = (
            derive_probe_bytes_v4(args.upstream_v4_probe.read_bytes())
            if revision == "V4"
            else derive_probe_bytes_v3(args.upstream_v4_probe.read_bytes())
        )
        # Consume the one physical-attempt authorization before any Docker
        # access or source-snapshot materialization.  The immutable image ID
        # is already part of the human-visible preregistration; resolving the
        # local tag after the claim is a fail-closed availability check and a
        # failure never refunds or replaces the selected key.
        container_image_id = collection_prereg.prereg.container_image_id
        consume_claim = (
            v4_auth.consume_collection_key if revision == "V4" else consume_collection_key
        )
        collection_claim = consume_claim(
            resolved=collection_prereg,
            matched_key=args.matched_key,
            source_urdf_sha256=sha256_file(args.urdf),
            upstream_v4_probe_sha256=sha256_file(args.upstream_v4_probe),
            derived_probe_sha256=hashlib.sha256(derived_probe_bytes).hexdigest(),
            container_image_id=container_image_id,
        )
        resolve_image = (
            v4_auth.resolve_docker_image_id if revision == "V4" else resolve_docker_image_id
        )
        if resolve_image(image=args.image) != container_image_id:
            raise CollectionAuthorizationError(
                "resolved Isaac image differs from the consumed claim"
            )
        if revision == "V4":
            _require_v4_image_runtime_user(image_reference=container_image_id)
        materialize_snapshot = (
            v4_auth.materialize_committed_source_snapshot
            if revision == "V4"
            else materialize_committed_source_snapshot
        )
        source_snapshot_root = materialize_snapshot(
            project_root=args.project_root,
            expected=collection_prereg.prereg.committed_source_snapshot,
        )
    else:
        # V2 remains a historical helper and retains its original hard-freeze
        # boundary.  It is not upgraded into the V3 authorization contract.
        require_pre_freeze(
            M2CExperimentAction.SMOKE
            if args.role == "SMOKE"
            else M2CExperimentAction.ISAAC_COLLECTION
        )
    receipt, stage_cmd, probe_cmd = prepare_job(
        args,
        collection_prereg=collection_prereg,
        collection_claim=collection_claim,
        container_image_id=container_image_id,
        derived_probe_bytes=derived_probe_bytes,
        source_snapshot_root=source_snapshot_root,
    )
    job_root = args.output_root / args.role.lower() / args.matched_key
    if args.dry_run:
        return {**receipt, "job_root": str(job_root)}

    stage_completed = _run_stage_command(
        stage_cmd,
        container_name=f"{args.container_prefix}-stage",
        timeout_s=args.stage_timeout_s,
    )
    (job_root / "stage" / "console.log").write_text(
        stage_completed.stdout + stage_completed.stderr,
        encoding="utf-8",
    )
    if revision == "V4":
        _seal_v4_container_output_directory(job_root / "stage")
    if stage_completed.returncode != 0 or not stage_is_valid(
        job_root / "stage",
        sdf=args.sdf,
        supervision=args.supervision,
        urdf=args.urdf,
    ):
        raise RuntimeError("Isaac stage builder failed its hash-bound acceptance gate")
    broker = None
    if revision == "V3":
        assert collection_prereg is not None
        assert collection_claim is not None
        assert container_image_id is not None
        stage_path = job_root / "stage" / "m1b_physics_scene.usdc"
        metrics_path = job_root / "stage" / "metrics.json"
        metrics_digest = sha256_file(metrics_path)
        probe_cmd[probe_cmd.index("--m2c-stage-metrics-sha256") + 1] = metrics_digest
        # The command digest is computed last over a representation with its
        # own digest slot zeroed. This binds every Docker flag/mount/argument
        # without a self-referential hash.
        command_digest_index = probe_cmd.index("--m2c-docker-command-sha256") + 1
        probe_cmd[command_digest_index] = "0" * 64
        probe_cmd[command_digest_index] = canonical_sha256(probe_cmd)
        python_argv = probe_cmd[probe_cmd.index(container_image_id) + 1 :]
        command_digest_index = python_argv.index("--m2c-docker-command-sha256") + 1
        command_digest = python_argv[command_digest_index]
        issued_start = issue_probe_start_capability(
            resolved=collection_prereg,
            claim_path=collection_claim,
            matched_key=args.matched_key,
            failure_seed=int(receipt["failure_seed"]),
            source_sdf_sha256=sha256_file(args.sdf),
            source_supervision_sha256=sha256_file(args.supervision),
            source_urdf_sha256=sha256_file(args.urdf),
            upstream_v4_probe_sha256=sha256_file(args.upstream_v4_probe),
            stage_usdc_sha256=sha256_file(stage_path),
            stage_metrics_sha256=metrics_digest,
            stage_command_sha256=canonical_sha256(stage_cmd),
            derived_probe_sha256=str(receipt["derived_probe_sha256"]),
            container_image_id=container_image_id,
            probe_argv_sha256=canonical_sha256(python_argv),
            docker_command_sha256=command_digest,
            job_root_sha256=canonical_path_sha256(job_root),
            probe_output_root_sha256=canonical_path_sha256(job_root / "probe"),
            role=args.role,
            split=str(receipt["split"]),
            declared_target_attribute="yellow",
            destination_cell=str(
                next(
                    item.destination_cell
                    for item in collection_prereg.manifest.training_keys
                    if item.matched_key == args.matched_key
                )
            ),
        )
        if (
            str(issued_start.path) not in probe_cmd
            or str(issued_start.broker_socket_path) not in probe_cmd
            or str(issued_start.broker_token_path) not in probe_cmd
        ):
            raise CollectionAuthorizationError(
                "probe command does not reference the issued one-shot capability"
            )
        # The stage is mounted read-only into the probe container. Remove host
        # write bits after publishing the capability so the bytes cannot drift
        # between host validation and the probe's pre-Kit rehash.
        for stage_member in (stage_path, job_root / "stage" / "metrics.json"):
            stage_member.chmod(0o400)
        launch_path = consume_probe_launch(
            resolved=collection_prereg,
            claim_path=collection_claim,
            matched_key=args.matched_key,
        )
        if not launch_path.is_file():
            raise CollectionAuthorizationError("probe launch was not atomically consumed")
        broker = start_probe_entry_broker(
            resolved=collection_prereg,
            claim_path=collection_claim,
            matched_key=args.matched_key,
            issued=issued_start,
            accept_timeout_s=args.probe_timeout_s,
        )
    elif revision == "V4":
        for stage_member in (
            job_root / "stage" / "m1b_physics_scene.usdc",
            job_root / "stage" / "metrics.json",
        ):
            stage_member.chmod(0o400)
    probe_console = job_root / "probe" / "console.log"
    raw_probe = job_root / "probe" / "actuation-probe.json"
    probe_completed: subprocess.CompletedProcess[str] | None = None
    probe_error: BaseException | None = None
    containment_proven = False
    try:
        probe_completed = _run_probe_command(
            probe_cmd,
            container_name=f"{args.container_prefix}-probe",
            timeout_s=args.probe_timeout_s,
        )
        containment_proven = True
        probe_console.write_text(
            probe_completed.stdout + probe_completed.stderr,
            encoding="utf-8",
        )
    except BaseException as error:
        probe_error = error
        if revision == "V3":
            try:
                _remove_named_container(container_name=f"{args.container_prefix}-probe")
                containment_proven = True
            except BaseException as containment_error:
                probe_error = CollectionAuthorizationError(
                    "probe failed and container absence could not be proven"
                )
                probe_error.__cause__ = containment_error
        probe_console.write_text(
            f"M2C_PROBE_SPAWN_OR_CONTAINMENT_FAILURE: {type(error).__name__}\n",
            encoding="utf-8",
        )
    finally:
        if revision == "V3":
            assert collection_prereg is not None
            assert collection_claim is not None
            assert broker is not None
            cleanup_error: BaseException | None = None
            try:
                if containment_proven:
                    terminalize_probe_launch(
                        resolved=collection_prereg,
                        claim_path=collection_claim,
                        matched_key=args.matched_key,
                        job_root=job_root,
                        probe_output_root=job_root / "probe",
                        returncode=(
                            probe_completed.returncode if probe_completed is not None else 125
                        ),
                        console_path=probe_console,
                        raw_probe_path=raw_probe,
                    )
            except BaseException as error:
                cleanup_error = error
            finally:
                try:
                    if broker.completed.is_set():
                        broker.wait(timeout_s=5.0)
                    else:
                        broker.cancel(timeout_s=5.0)
                except BaseException as error:
                    cleanup_error = cleanup_error or error
            if cleanup_error is not None:
                probe_error = cleanup_error
    if revision == "V4":
        try:
            _seal_v4_container_output_directory(job_root / "probe")
        except BaseException as error:
            probe_error = probe_error or error
    if probe_error is not None:
        raise probe_error
    assert probe_completed is not None
    if probe_completed.returncode != 0 or not raw_probe.is_file():
        raise RuntimeError("Isaac PATH_BLOCKED probe failed or emitted no raw evidence")
    packaged = package_collection(
        raw_probe_path=raw_probe,
        evidence_root=job_root / "probe",
        output_root=args.packaged_output_root,
        role=args.role,
        matched_key=args.matched_key,
        training_keys_path=args.training_keys,
        s6_keys_path=args.s6_keys,
        runtime_registry_path=args.runtime_registry,
        derived_probe_path=job_root / "derived-path-blocked-probe.py",
        upstream_v4_probe_path=args.upstream_v4_probe,
        revision=_revision(args),
        collection_prereg_path=(getattr(args, "collection_prereg", None) if protected else None),
        collection_claim_path=collection_claim,
    )
    return {
        **receipt,
        "status": "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION_PACKAGED",
        "job_root": str(job_root),
        "package": packaged,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--sdf", required=True, type=Path)
    parser.add_argument("--supervision", required=True, type=Path)
    parser.add_argument("--urdf", required=True, type=Path)
    parser.add_argument("--upstream-v4-probe", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--packaged-output-root", required=True, type=Path)
    parser.add_argument("--role", choices=("TRAIN", "SMOKE"), required=True)
    parser.add_argument("--revision", choices=("V2", "V3", "V4"), default="V4")
    parser.add_argument("--matched-key", required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--image", default=ISAAC_IMAGE)
    parser.add_argument("--container-prefix", default="m2c-path-blocked")
    parser.add_argument("--stage-timeout-s", type=float, default=1200.0)
    parser.add_argument("--probe-timeout-s", type=float, default=5400.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--collection-prereg", type=Path)
    parser.add_argument("--collection-ledger-root", type=Path)
    parser.add_argument(
        "--training-keys",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--s6-keys",
        type=Path,
        default=project / "configs/m2c_s6_evaluation_keys.json",
    )
    parser.add_argument(
        "--runtime-registry",
        type=Path,
        default=project / "configs/qrm_runtime_mapping_v2.yaml",
    )
    args = parser.parse_args(argv)
    if args.training_keys is None:
        args.training_keys = project / (
            "configs/m2c_s4_v4_training_keys.json"
            if args.revision == "V4"
            else "configs/m2c_s4_v3_training_keys.json"
            if args.revision == "V3"
            else "configs/m2c_s4_training_keys.json"
        )
    if args.gpu < 0 or args.stage_timeout_s <= 0 or args.probe_timeout_s <= 0:
        parser.error("GPU and timeout values are invalid")
    return args


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
