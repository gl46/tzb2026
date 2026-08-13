"""Fail-closed authorization for new M2C S4 V3 TRAIN collection attempts.

The frozen 36-key manifest defines identities; it does not authorize an
unbounded number of executions.  This module makes the missing distinction
explicit.  A canonical worker may execute a V3 key only after a separate,
committed, outcome-blind JSON preregistration has selected that exact key and
an immutable host ledger has consumed the selection once.

The receipts in this module are local coordination evidence.  They are not a
remote attestation, a physical receipt, model-owned evidence, or formal Q-B
evidence.  Formal use still requires the independently frozen host-signature
and entry-gate contracts.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    M2CS4V3TrainingKeyManifestV1,
    M2CS4V3TrainingKeyV1,
    V3_MANIFEST_CONTENT_SHA256,
    V3_MANIFEST_FILE_SHA256,
)


ACCEPTED_ADR_PATH = "docs/decisions/ADR-0021-m2c-public-semantic-candidate-contract.md"
ACCEPTED_ADR_SHA256 = "60161eb2b40cdf7e32cd5714ef420b7bfb74d28a4a6b5789eecdd9cc73cba7cf"
ACCEPTED_ADR_INTRODUCED_COMMIT = "18391f66aa2bc2ac25bcf472d352b252e73ff0c1"
S6_MANIFEST_FILE_SHA256 = "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
RUNTIME_REGISTRY_FILE_SHA256 = "3572f80f1597b7f3bdffb1f8aad90d5baeb086b25c371b88511bc58444813359"
FROZEN_UPSTREAM_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
REQUIRED_SEMANTIC_SOURCE_PATHS = frozenset(
    {
        "src/xh_agent/policy/qrm_lite/public_tracks_v3.py",
        "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py",
        "scripts/m2c/build_s4_v3_training_manifest.py",
        "scripts/m2c/materialize_s4_s6_scenes.py",
        "scripts/m2c/derive_model_owned_chain_probe.py",
        "scripts/m2c/run_path_blocked_collection_worker.py",
        "scripts/m2c/package_path_blocked_collection.py",
        "src/xh_agent/policy/qrm_lite/s4_v3_collection_authorization_v1.py",
    }
)
AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES = {
    "reports/m2c-s4-v3-path-blocked-train-collection.json": (
        "c505ec6517d7a766768f72cd14fc49d1919cff234dc2d8fbee1877104b41480d",
        "M2CS4V3TrainCollectionAuditV1",
        8,
    ),
    "reports/m2c-s4-v3-path-blocked-train-collection-batch03.json": (
        "0fe177565b6d842fa6e1fc80a8d1e0822283d3557aeb41d56c36140e4dbacb57",
        "M2CS4V3TrainCollectionBatch03AuditV1",
        3,
    ),
}
CANONICAL_COLLECTION_LEDGER_ROOT = (
    "/var/tmp/xh-data/isaac-industrial/m2c/s4-v3-collection-authorization-ledger-v1"
)
CANONICAL_SOURCE_SNAPSHOT_ROOT = (
    "/var/tmp/xh-data/isaac-industrial/m2c/s4-v3-committed-source-snapshots-v1"
)
LAUNCH_CONSUMPTION_DIRECTORY = ".launch-consumed"
PROBE_ENTRY_DIRECTORY = ".probe-entry-consumed"
PROBE_ENTRY_RECEIPT_NAME = ".m2c-v3-probe-entry.json"
CANONICAL_PROBE_ENTRY_BROKER_ROOT = "/var/tmp/m2c-v3-broker-v1"
OUTCOME_PATH_PREFIXES = ("artifacts/", "reports/", "evidence/", "runs/")


class CollectionAuthorizationError(RuntimeError):
    """A V3 collection request is not authorized by committed evidence."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


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


def canonical_path_sha256(path: Path) -> str:
    """Bind a host path without treating the path string as file evidence."""

    return canonical_sha256({"absolute_path": str(path.resolve())})


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def resolve_docker_image_id(*, image: str) -> str:
    """Resolve the local Docker tag to the exact preregistered image ID."""

    completed = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    values = completed.stdout.splitlines()
    if completed.returncode != 0 or len(values) != 1:
        raise CollectionAuthorizationError("cannot resolve the preregistered Isaac image ID")
    value = values[0].strip()
    if value != ("sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"):
        raise CollectionAuthorizationError("local Isaac image ID differs from preregistration")
    return value


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CollectionAuthorizationError(
            f"cannot securely open authorization file: {path}"
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CollectionAuthorizationError(
                "authorization input is not a single-link regular file"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CollectionAuthorizationError("authorization input changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_regular_file_at(directory_fd: int, filename: str) -> bytes:
    if Path(filename).name != filename or filename in {".", ".."}:
        raise CollectionAuthorizationError("ledger member name is not a basename")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(filename, flags, dir_fd=directory_fd)
    except OSError as error:
        raise CollectionAuthorizationError(
            f"cannot securely open ledger member: {filename}"
        ) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
        ):
            raise CollectionAuthorizationError("ledger member metadata is unsafe")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CollectionAuthorizationError("ledger member changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise CollectionAuthorizationError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(payload, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionAuthorizationError(f"{label} is not strict JSON") from error
    if not isinstance(parsed, dict):
        raise CollectionAuthorizationError(f"{label} must be a JSON object")
    return parsed


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if check and completed.returncode != 0:
        raise CollectionAuthorizationError(
            f"git {' '.join(args)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed


class CommittedSourceSnapshotV1(StrictModel):
    """Content-addressed complete Git tree used inside both Isaac containers."""

    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    tree: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_count: int = Field(gt=0)
    total_bytes: int = Field(gt=0)
    inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _source_snapshot_payloads(
    project_root: Path,
    *,
    commit: str,
) -> tuple[CommittedSourceSnapshotV1, list[tuple[dict[str, Any], bytes]]]:
    """Read every regular blob in one commit without archive attribute filtering."""

    resolved_commit = (
        _git(project_root, "rev-parse", f"{commit}^{{commit}}").stdout.decode().strip()
    )
    if resolved_commit != commit:
        raise CollectionAuthorizationError("source snapshot commit is not canonical")
    tree = _git(project_root, "rev-parse", f"{commit}^{{tree}}").stdout.decode().strip()
    raw_tree = _git(project_root, "ls-tree", "-r", "-z", "--full-tree", commit).stdout
    tree_records: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for record in raw_tree.split(b"\0"):
        if not record:
            continue
        try:
            header, encoded_path = record.split(b"\t", 1)
            mode_bytes, kind, object_id = header.split(b" ", 2)
            normalized = encoded_path.decode("utf-8", errors="strict")
            mode = mode_bytes.decode("ascii")
            object_hex = object_id.decode("ascii")
        except (UnicodeDecodeError, ValueError) as error:
            raise CollectionAuthorizationError("source snapshot tree record is invalid") from error
        path = Path(normalized)
        if (
            path.is_absolute()
            or not normalized
            or ".." in path.parts
            or path.as_posix() != normalized
            or normalized in seen
        ):
            raise CollectionAuthorizationError("source snapshot tree path is unsafe or repeated")
        if kind != b"blob" or mode not in {"100644", "100755"}:
            raise CollectionAuthorizationError(
                "source snapshot contains a symlink, submodule, or special tracked entry"
            )
        seen.add(normalized)
        tree_records.append((normalized, mode, object_hex))
    tree_records.sort(key=lambda item: item[0])
    if not tree_records:
        raise CollectionAuthorizationError("source snapshot is empty")

    batch_input = b"".join(f"{object_id}\n".encode("ascii") for _, _, object_id in tree_records)
    completed = subprocess.run(
        ["git", "-C", str(project_root), "cat-file", "--batch"],
        input=batch_input,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise CollectionAuthorizationError("cannot read the complete source snapshot blob set")
    output = completed.stdout
    cursor = 0
    payloads: list[tuple[dict[str, Any], bytes]] = []
    for normalized, mode, expected_object_id in tree_records:
        header_end = output.find(b"\n", cursor)
        if header_end < 0:
            raise CollectionAuthorizationError("source snapshot batch output is truncated")
        try:
            object_id, kind, size_bytes = output[cursor:header_end].split(b" ", 2)
            size = int(size_bytes)
        except ValueError as error:
            raise CollectionAuthorizationError("source snapshot blob header is invalid") from error
        if object_id.decode("ascii") != expected_object_id or kind != b"blob" or size < 0:
            raise CollectionAuthorizationError("source snapshot blob identity changed")
        start = header_end + 1
        end = start + size
        if end >= len(output) or output[end : end + 1] != b"\n":
            raise CollectionAuthorizationError("source snapshot blob payload is truncated")
        payload = output[start:end]
        cursor = end + 1
        payloads.append(
            (
                {
                    "path": normalized,
                    "mode": mode,
                    "size": len(payload),
                    "sha256": sha256_bytes(payload),
                },
                payload,
            )
        )
    if cursor != len(output):
        raise CollectionAuthorizationError("source snapshot batch output has trailing bytes")
    entries = [entry for entry, _payload in payloads]
    identity = CommittedSourceSnapshotV1(
        commit=commit,
        tree=tree,
        file_count=len(entries),
        total_bytes=sum(int(item["size"]) for item in entries),
        inventory_sha256=canonical_sha256(entries),
    )
    return identity, payloads


def _materialized_snapshot_inventory(snapshot_root: Path) -> list[dict[str, Any]]:
    root_info = snapshot_root.lstat()
    root = snapshot_root.resolve(strict=True)
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or root_info.st_uid != os.geteuid()
        or stat.S_IMODE(root_info.st_mode) != 0o555
    ):
        raise CollectionAuthorizationError("source snapshot root is not a real directory")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o555:
                raise CollectionAuthorizationError("source snapshot directory mode is not frozen")
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise CollectionAuthorizationError("source snapshot contains a non-regular file")
        mode = stat.S_IMODE(info.st_mode)
        if mode not in {0o444, 0o555}:
            raise CollectionAuthorizationError("source snapshot file mode is not frozen")
        payload = read_regular_file_once(path)
        entries.append(
            {
                "path": relative,
                "mode": "100755" if mode == 0o555 else "100644",
                "size": len(payload),
                "sha256": sha256_bytes(payload),
            }
        )
    return entries


def verify_materialized_source_snapshot(
    snapshot_root: Path,
    expected: CommittedSourceSnapshotV1,
    *,
    require_content_addressed_name: bool = True,
) -> None:
    """Replay the complete materialized tree before Kit/SimulationApp starts."""

    entries = _materialized_snapshot_inventory(snapshot_root)
    if (
        (
            require_content_addressed_name
            and snapshot_root.resolve(strict=True).name != expected.inventory_sha256
        )
        or len(entries) != expected.file_count
        or sum(int(item["size"]) for item in entries) != expected.total_bytes
        or canonical_sha256(entries) != expected.inventory_sha256
    ):
        raise CollectionAuthorizationError(
            "materialized source snapshot differs from preregistration"
        )


def materialize_committed_source_snapshot(
    *,
    project_root: Path,
    expected: CommittedSourceSnapshotV1,
) -> Path:
    """Create or verify the exact read-only Git tree mounted into Isaac."""

    actual, payloads = _source_snapshot_payloads(project_root, commit=expected.commit)
    if actual != expected:
        raise CollectionAuthorizationError("Git source snapshot identity changed")
    snapshot_parent = Path(CANONICAL_SOURCE_SNAPSHOT_ROOT)
    snapshot_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = snapshot_parent.lstat()
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != os.geteuid()
        or stat.S_IMODE(parent_info.st_mode) != 0o700
    ):
        raise CollectionAuthorizationError("source snapshot parent is not a private directory")
    target = snapshot_parent / expected.inventory_sha256
    if target.exists():
        verify_materialized_source_snapshot(target, expected)
        return target
    temporary = Path(tempfile.mkdtemp(prefix=".source-snapshot-", dir=snapshot_parent))

    def remove_temporary() -> None:
        if not temporary.exists():
            return
        for member in sorted(
            [temporary, *temporary.rglob("*")],
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                member.chmod(0o700 if member.is_dir() else 0o600)
            except OSError:
                pass
        shutil.rmtree(temporary, ignore_errors=True)

    try:
        for entry, payload in payloads:
            destination = temporary / str(entry["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(destination, flags, 0o600)
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written <= 0:
                        raise CollectionAuthorizationError("short source snapshot write")
                    offset += written
                os.fsync(descriptor)
                os.fchmod(descriptor, 0o555 if entry["mode"] == "100755" else 0o444)
            finally:
                os.close(descriptor)
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o555)
        temporary.chmod(0o555)
        verify_materialized_source_snapshot(
            temporary,
            expected,
            require_content_addressed_name=False,
        )
        try:
            temporary.rename(target)
        except FileExistsError:
            remove_temporary()
            verify_materialized_source_snapshot(target, expected)
        parent_fd = os.open(snapshot_parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return target
    except Exception:
        remove_temporary()
        raise


def _project_relative_path(project_root: Path, path: Path) -> str:
    root = project_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise CollectionAuthorizationError("authorization file escapes the project root") from error


class BoundRepositoryFileV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def path_is_repository_relative(self) -> "BoundRepositoryFileV1":
        path = Path(self.path)
        if path.is_absolute() or self.path.startswith("/") or ".." in path.parts:
            raise ValueError("bound repository path is not repository-relative")
        return self


class AcceptedGoverningADRV1(BoundRepositoryFileV1):
    status: Literal["ACCEPTED_HUMAN_ADR"]
    introduced_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    selected_option: Literal["A"]


class SelectedV3TrainKeyV1(StrictModel):
    scene_seed: int = Field(ge=0)
    failure_seed: int = Field(ge=0)
    matched_key: str = Field(pattern=r"^m2c-s4-v3-train-[0-9a-f]{64}$")
    sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CollectionScopeV1(StrictModel):
    role: Literal["TRAIN"]
    split: Literal["train"]
    scripted_public_physical_supervision_collection: Literal[True]
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    training_execution: Literal[False]
    q_b_evaluation: Literal[False]


class M2CS4V3SelectedKeyCollectionPreregV1(StrictModel):
    schema_version: Literal["M2CS4V3SelectedKeyCollectionPreregV1"]
    status: Literal["FROZEN_BEFORE_ANY_SELECTED_KEY_EXECUTION_OR_RESULT"]
    repository_relative_path: str
    introduction_commit_paths: list[str] = Field(min_length=1)
    batch_id: str = Field(pattern=r"^m2c-s4-v3-train-batch-[0-9]{2,}$")
    registered_before_selected_key_execution: Literal[True]
    selected_key_outcome_observed_before_registration: Literal[False]
    governing_adr: AcceptedGoverningADRV1
    candidate_contract_revision: Literal["PublicTrackCandidateV3"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"]
    candidate_count_bound: Literal[8]
    recapture_policy: Literal["NONE"]
    training_manifest: BoundRepositoryFileV1
    training_manifest_content_sha256: Literal[
        "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
    ]
    s6_exclusion_manifest: BoundRepositoryFileV1
    runtime_registry: BoundRepositoryFileV1
    semantic_source_bindings: list[BoundRepositoryFileV1]
    committed_source_snapshot: CommittedSourceSnapshotV1
    prior_attempt_identity_sources: list[BoundRepositoryFileV1] = Field(min_length=1)
    container_image: Literal["nvcr.io/nvidia/isaac-sim:6.0.1"]
    container_image_id: Literal[
        "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
    ]
    upstream_v4_probe_sha256: Literal[
        "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
    ]
    selection_rule: Literal["manifest_order_first_unattempted_per_sdf_v1"]
    selection_inputs: list[Literal["manifest_order", "prior_attempted_identity", "sdf_sha256"]] = (
        Field(min_length=1)
    )
    selection_uses_outcomes: Literal[False]
    selected_keys: list[SelectedV3TrainKeyV1] = Field(min_length=1)
    stop_after_selected_keys: int = Field(gt=0)
    attempt_each_selected_key_at_most_once: Literal[True]
    retry_authorized: Literal[False]
    replacement_authorized: Literal[False]
    ledger_namespace: str = Field(pattern=r"^M2C_S4_V3_COLLECTION_[A-Z0-9_]+$")
    ledger_root: str
    scope: CollectionScopeV1
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def frozen_contract_is_self_consistent(self) -> "M2CS4V3SelectedKeyCollectionPreregV1":
        payload = self.model_dump(mode="json", exclude={"prereg_sha256"})
        if canonical_sha256(payload) != self.prereg_sha256:
            raise ValueError("prereg canonical SHA-256 mismatch")
        if self.stop_after_selected_keys != len(self.selected_keys):
            raise ValueError("stop count differs from selected-key count")
        if len({item.matched_key for item in self.selected_keys}) != len(self.selected_keys):
            raise ValueError("prereg repeats a selected key")
        if len(self.selection_inputs) != len(set(self.selection_inputs)):
            raise ValueError("prereg repeats a selection input")
        if set(self.selection_inputs) != {
            "manifest_order",
            "prior_attempted_identity",
            "sdf_sha256",
        }:
            raise ValueError("prereg selection inputs are not the outcome-blind allowlist")
        if self.ledger_root != CANONICAL_COLLECTION_LEDGER_ROOT:
            raise ValueError("collection ledger root is not the canonical host ledger")
        if set(self.introduction_commit_paths) != {self.repository_relative_path}:
            raise ValueError("prereg introduction commit must be prereg-only")
        return self


@dataclass(frozen=True)
class ResolvedCollectionPreregV1:
    path: Path
    file_sha256: str
    raw_bytes: bytes
    prereg: M2CS4V3SelectedKeyCollectionPreregV1
    manifest: M2CS4V3TrainingKeyManifestV1
    # Derived from Git history. It cannot be embedded in the newly introduced
    # prereg file because doing so would make the commit hash self-referential.
    introduced_commit: str


def _verify_bound_repository_file(
    project_root: Path,
    binding: BoundRepositoryFileV1,
) -> bytes:
    path = project_root / binding.path
    payload = read_regular_file_once(path)
    if sha256_bytes(payload) != binding.sha256:
        raise CollectionAuthorizationError(f"bound repository file hash changed: {binding.path}")
    head_payload = _git(project_root, "show", f"HEAD:{binding.path}").stdout
    if head_payload != payload:
        raise CollectionAuthorizationError(
            f"bound repository file is not exact HEAD bytes: {binding.path}"
        )
    return payload


def _require_prereg_execution_checkout(
    project_root: Path,
    *,
    introduced_commit: str,
) -> None:
    """Require the prereg-only commit to be the exact clean host checkout.

    The two Isaac containers execute the complete materialized parent tree.
    Host-side validation and packaging import from the checkout, so they may
    run only while the preregistration commit itself is HEAD and no tracked or
    untracked worktree bytes can shadow that frozen parent tree.  This makes a
    later change to *any* project dependency fail before a key claim or process
    launch, not merely changes to a hand-maintained import allowlist.
    """

    current_head = _git(project_root, "rev-parse", "HEAD").stdout.decode().strip()
    if current_head != introduced_commit:
        raise CollectionAuthorizationError(
            "active preregistration must be the current checkout HEAD"
        )
    worktree_status = _git(
        project_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    if worktree_status:
        raise CollectionAuthorizationError(
            "active preregistration requires a completely clean host checkout"
        )
    ignored_runtime = _git(
        project_root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        "src/xh_agent",
        "scripts/m2c",
    ).stdout
    if ignored_runtime:
        raise CollectionAuthorizationError(
            "active preregistration runtime roots contain ignored shadow bytes"
        )


def load_committed_collection_prereg(
    *,
    project_root: Path,
    prereg_path: Path,
) -> ResolvedCollectionPreregV1:
    """Load one strict preregistration and prove it is committed/current."""

    root = project_root.resolve(strict=True)
    raw = read_regular_file_once(prereg_path)
    prereg = M2CS4V3SelectedKeyCollectionPreregV1.model_validate(
        _json_object(raw, label="V3 collection preregistration")
    )
    relative = _project_relative_path(root, prereg_path)
    if relative != prereg.repository_relative_path:
        raise CollectionAuthorizationError("prereg path differs from its frozen repository path")
    if _git(root, "show", f"HEAD:{relative}").stdout != raw:
        raise CollectionAuthorizationError("preregistration is not exact current HEAD bytes")
    introduced_lines = (
        _git(root, "log", "--diff-filter=A", "--format=%H", "--", relative)
        .stdout.decode()
        .splitlines()
    )
    if not introduced_lines:
        raise CollectionAuthorizationError("preregistration has no Git introduction commit")
    introduced_commit = introduced_lines[0]
    introduced_bytes = _git(root, "show", f"{introduced_commit}:{relative}").stdout
    if introduced_bytes != raw:
        raise CollectionAuthorizationError(
            "preregistration differs from its frozen introduction-commit bytes"
        )
    if (
        _git(
            root,
            "merge-base",
            "--is-ancestor",
            introduced_commit,
            "HEAD",
            check=False,
        ).returncode
        != 0
    ):
        raise CollectionAuthorizationError("prereg introduction commit is not a HEAD ancestor")
    parents = _git(root, "show", "-s", "--format=%P", introduced_commit).stdout.decode().split()
    if len(parents) != 1:
        raise CollectionAuthorizationError("prereg introduction commit must have one parent")
    if _git(root, "cat-file", "-e", f"{parents[0]}:{relative}", check=False).returncode == 0:
        raise CollectionAuthorizationError("prereg path existed before its introduction commit")
    changed_paths = set(
        _git(
            root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            introduced_commit,
        )
        .stdout.decode()
        .splitlines()
    )
    if changed_paths != set(prereg.introduction_commit_paths):
        raise CollectionAuthorizationError("prereg introduction commit contains other paths")
    if any(path.startswith(OUTCOME_PATH_PREFIXES) for path in changed_paths):
        raise CollectionAuthorizationError("prereg commit contains outcome/evidence paths")
    _require_prereg_execution_checkout(
        root,
        introduced_commit=introduced_commit,
    )

    if (
        prereg.governing_adr.path != ACCEPTED_ADR_PATH
        or prereg.governing_adr.sha256 != ACCEPTED_ADR_SHA256
        or prereg.governing_adr.introduced_commit != ACCEPTED_ADR_INTRODUCED_COMMIT
    ):
        raise CollectionAuthorizationError("V3 prereg does not bind accepted ADR-0021")
    adr_bytes = _verify_bound_repository_file(root, prereg.governing_adr)
    adr_text = adr_bytes.decode("utf-8", errors="strict")
    if "Status: Accepted" not in adr_text or "Selected option: **A**" not in adr_text:
        raise CollectionAuthorizationError("governing ADR is not the accepted V3 decision")
    if (
        _git(
            root,
            "merge-base",
            "--is-ancestor",
            prereg.governing_adr.introduced_commit,
            introduced_commit,
            check=False,
        ).returncode
        != 0
    ):
        raise CollectionAuthorizationError("governing ADR was not accepted before preregistration")

    if (
        prereg.training_manifest.path != "configs/m2c_s4_v3_training_keys.json"
        or prereg.training_manifest.sha256 != V3_MANIFEST_FILE_SHA256
        or prereg.s6_exclusion_manifest.path != "configs/m2c_s6_evaluation_keys.json"
        or prereg.s6_exclusion_manifest.sha256 != S6_MANIFEST_FILE_SHA256
        or prereg.runtime_registry.path != "configs/qrm_runtime_mapping_v2.yaml"
        or prereg.runtime_registry.sha256 != RUNTIME_REGISTRY_FILE_SHA256
    ):
        raise CollectionAuthorizationError("prereg manifest/runtime identities are not frozen")
    manifest = M2CS4V3TrainingKeyManifestV1.model_validate(
        _json_object(
            _verify_bound_repository_file(root, prereg.training_manifest),
            label="V3 TRAIN manifest",
        )
    )
    _verify_bound_repository_file(root, prereg.s6_exclusion_manifest)
    _verify_bound_repository_file(root, prereg.runtime_registry)
    if manifest.manifest_sha256 != V3_MANIFEST_CONTENT_SHA256:
        raise CollectionAuthorizationError("V3 TRAIN manifest content identity changed")

    bindings = {item.path: item for item in prereg.semantic_source_bindings}
    if set(bindings) != set(REQUIRED_SEMANTIC_SOURCE_PATHS):
        raise CollectionAuthorizationError("prereg semantic source closure is incomplete")
    for binding in bindings.values():
        _verify_bound_repository_file(root, binding)
    # The preregistration commit is prereg-only. Its sole parent is therefore
    # the exact implementation tree frozen before any selected-key result,
    # without embedding a self-referential commit hash in the prereg file.
    source_snapshot, _payloads = _source_snapshot_payloads(root, commit=parents[0])
    if prereg.committed_source_snapshot != source_snapshot:
        raise CollectionAuthorizationError(
            "prereg does not bind its complete introduction-commit source tree"
        )
    prior_bindings = {item.path: item for item in prereg.prior_attempt_identity_sources}
    if set(prior_bindings) != set(AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES):
        raise CollectionAuthorizationError(
            "prereg does not bind the complete authoritative prior-attempt inventory"
        )
    prior_keys: set[str] = set()
    for binding in prereg.prior_attempt_identity_sources:
        source = _json_object(
            _verify_bound_repository_file(root, binding),
            label=f"prior attempt identity source {binding.path}",
        )
        attempts = source.get("attempts")
        expected_sha, expected_schema, expected_unique = AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[
            binding.path
        ]
        if binding.sha256 != expected_sha or source.get("schema_version") != expected_schema:
            raise CollectionAuthorizationError("prior attempt source identity is not frozen")
        if not isinstance(attempts, list):
            raise CollectionAuthorizationError("prior attempt identity source lacks attempts")
        source_keys: set[str] = set()
        for attempt in attempts:
            identity = attempt.get("identity") if isinstance(attempt, dict) else None
            matched_key = identity.get("matched_key") if isinstance(identity, dict) else None
            if not isinstance(matched_key, str):
                raise CollectionAuthorizationError("prior attempt identity is malformed")
            source_keys.add(matched_key)
            prior_keys.add(matched_key)
        if len(source_keys) != expected_unique:
            raise CollectionAuthorizationError(
                "prior attempt source has the wrong unique-key count"
            )
    if len(prior_keys) != 11:
        raise CollectionAuthorizationError("prior attempt inventory must contain 11 unique keys")
    expected: list[SelectedV3TrainKeyV1] = []
    selected_sdfs: set[str] = set()
    for item in manifest.training_keys:
        if item.matched_key in prior_keys or item.sdf_sha256 in selected_sdfs:
            continue
        expected.append(_selected_key(item))
        selected_sdfs.add(item.sdf_sha256)
        if len(expected) == prereg.stop_after_selected_keys:
            break
    if prereg.selected_keys != expected:
        raise CollectionAuthorizationError(
            "selected keys do not recompute from the frozen outcome-blind identity inputs"
        )
    return ResolvedCollectionPreregV1(
        path=prereg_path.resolve(strict=True),
        file_sha256=sha256_bytes(raw),
        raw_bytes=raw,
        prereg=prereg,
        manifest=manifest,
        introduced_commit=introduced_commit,
    )


def _selected_key(key: M2CS4V3TrainingKeyV1) -> SelectedV3TrainKeyV1:
    return SelectedV3TrainKeyV1(
        scene_seed=key.scene_seed,
        failure_seed=key.failure_seed,
        matched_key=key.matched_key,
        sdf_sha256=key.sdf_sha256,
        supervision_sha256=key.supervision_sha256,
    )


def selected_key_ordinal(
    resolved: ResolvedCollectionPreregV1,
    *,
    matched_key: str,
) -> tuple[int, SelectedV3TrainKeyV1]:
    matches = [
        (position, item)
        for position, item in enumerate(resolved.prereg.selected_keys)
        if item.matched_key == matched_key
    ]
    if len(matches) != 1:
        raise CollectionAuthorizationError("key is not selected by the active preregistration")
    return matches[0]


class M2CS4V3CollectionConsumptionReceiptV1(StrictModel):
    schema_version: Literal["M2CS4V3CollectionConsumptionReceiptV1"]
    event: Literal["CONSUMED_BEFORE_STAGE"]
    ledger_namespace: str
    ledger_sequence: int = Field(ge=0)
    batch_id: str
    ordinal: int = Field(ge=0)
    consumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_repository_path: str
    prereg_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_introduced_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    selected_key: SelectedV3TrainKeyV1
    selected_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_urdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    upstream_v4_probe_sha256: Literal[
        "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
    ]
    committed_source_snapshot: CommittedSourceSnapshotV1
    derived_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_image: Literal["nvcr.io/nvidia/isaac-sim:6.0.1"]
    container_image_id: Literal[
        "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
    ]
    role: Literal["TRAIN"]
    split: Literal["train"]
    declared_target_attribute: Literal["yellow"]
    destination_cell: str = Field(pattern=r"^BIN_CELL_[0-5]$")
    candidate_contract_revision: Literal["PublicTrackCandidateV3"]
    checkpoint_architecture_revision: Literal["M2C_Q012_V3"]
    previous_receipt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    consumed_at_ns: int = Field(gt=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    training_executed: Literal[False]
    formal_q_b_evaluation: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_receipt_is_bound(self) -> "M2CS4V3CollectionConsumptionReceiptV1":
        if self.selected_key_sha256 != canonical_sha256(self.selected_key.model_dump(mode="json")):
            raise ValueError("selected-key receipt digest mismatch")
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
            != self.receipt_sha256
        ):
            raise ValueError("consumption receipt canonical digest mismatch")
        return self


def _secure_ledger_directory(path: Path) -> int:
    if not path.is_absolute():
        raise CollectionAuthorizationError("ledger root is not absolute")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CollectionAuthorizationError(
            "ledger root must preexist as a secure directory"
        ) from error
    info = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        os.close(descriptor)
        raise CollectionAuthorizationError("ledger root must be owned by euid with mode 0700")
    return descriptor


def _claim_names(directory_fd: int) -> list[str]:
    allowed_prefixes = ("claim-", "probe-start-")
    names = sorted(
        name
        for name in os.listdir(directory_fd)
        if name
        not in {
            ".ledger.lock",
            LAUNCH_CONSUMPTION_DIRECTORY,
            PROBE_ENTRY_DIRECTORY,
        }
    )
    for private_directory in (
        LAUNCH_CONSUMPTION_DIRECTORY,
        PROBE_ENTRY_DIRECTORY,
    ):
        if private_directory not in os.listdir(directory_fd):
            continue
        private_info = os.stat(private_directory, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(private_info.st_mode)
            or private_info.st_uid != os.geteuid()
            or stat.S_IMODE(private_info.st_mode) != 0o700
        ):
            raise CollectionAuthorizationError(
                f"private ledger directory is unsafe: {private_directory}"
            )
    for name in names:
        if not name.startswith(allowed_prefixes) or not name.endswith(".json"):
            raise CollectionAuthorizationError(f"unexpected file in collection ledger: {name}")
    claims = [name for name in names if name.startswith("claim-")]
    if claims != [f"claim-{index:08d}.json" for index in range(len(claims))]:
        raise CollectionAuthorizationError("collection ledger claim sequence is not contiguous")
    return claims


def _open_launch_consumption_directory(
    directory_fd: int,
    *,
    create: bool,
) -> int:
    if create:
        try:
            os.mkdir(LAUNCH_CONSUMPTION_DIRECTORY, 0o700, dir_fd=directory_fd)
        except FileExistsError:
            pass
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        launch_fd = os.open(LAUNCH_CONSUMPTION_DIRECTORY, flags, dir_fd=directory_fd)
    except OSError as error:
        raise CollectionAuthorizationError("launch-consumption directory is unavailable") from error
    info = os.fstat(launch_fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        os.close(launch_fd)
        raise CollectionAuthorizationError("launch-consumption directory is unsafe")
    return launch_fd


def _open_probe_entry_directory(
    directory_fd: int,
    *,
    consumption_id: str,
    create: bool,
) -> int:
    """Open the claim-scoped directory writable only by the host broker."""

    if create:
        try:
            os.mkdir(PROBE_ENTRY_DIRECTORY, 0o700, dir_fd=directory_fd)
        except FileExistsError:
            pass
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        parent_fd = os.open(PROBE_ENTRY_DIRECTORY, parent_flags, dir_fd=directory_fd)
    except OSError as error:
        raise CollectionAuthorizationError("probe-entry directory is unavailable") from error
    try:
        parent_info = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or parent_info.st_uid != os.geteuid()
            or stat.S_IMODE(parent_info.st_mode) != 0o700
        ):
            raise CollectionAuthorizationError("probe-entry parent directory is unsafe")
        if create:
            try:
                os.mkdir(consumption_id, 0o700, dir_fd=parent_fd)
            except FileExistsError as error:
                raise CollectionAuthorizationError(
                    "probe-entry directory was already allocated"
                ) from error
        try:
            entry_fd = os.open(consumption_id, parent_flags, dir_fd=parent_fd)
        except OSError as error:
            raise CollectionAuthorizationError(
                "claim-scoped probe-entry directory is unavailable"
            ) from error
        entry_info = os.fstat(entry_fd)
        if (
            not stat.S_ISDIR(entry_info.st_mode)
            or entry_info.st_uid != os.geteuid()
            or stat.S_IMODE(entry_info.st_mode) != 0o700
        ):
            os.close(entry_fd)
            raise CollectionAuthorizationError("claim-scoped probe-entry directory is unsafe")
        return entry_fd
    finally:
        os.close(parent_fd)


@contextmanager
def _exclusive_ledger_lock(directory_fd: int):
    """Serialize ledger readers/writers so no process observes a partial file."""

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_fd = os.open(".ledger.lock", flags, 0o600, dir_fd=directory_fd)
    except OSError as error:
        raise CollectionAuthorizationError("cannot securely open ledger lock") from error
    try:
        info = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise CollectionAuthorizationError("ledger lock metadata is unsafe")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _read_claims(directory_fd: int) -> list[M2CS4V3CollectionConsumptionReceiptV1]:
    claims: list[M2CS4V3CollectionConsumptionReceiptV1] = []
    previous: str | None = None
    seen_keys: set[str] = set()
    for index, filename in enumerate(_claim_names(directory_fd)):
        claim = M2CS4V3CollectionConsumptionReceiptV1.model_validate(
            _json_object(
                _read_regular_file_at(directory_fd, filename),
                label=f"collection claim {index}",
            )
        )
        if claim.ledger_sequence != index or claim.previous_receipt_sha256 != previous:
            raise CollectionAuthorizationError("collection ledger hash chain is invalid")
        if claim.selected_key.matched_key in seen_keys:
            raise CollectionAuthorizationError("collection ledger repeats a matched key")
        seen_keys.add(claim.selected_key.matched_key)
        claims.append(claim)
        previous = claim.receipt_sha256
    return claims


def _write_create_only_json(
    *,
    directory_fd: int,
    filename: str,
    payload: dict[str, Any],
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(filename, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError as error:
        raise CollectionAuthorizationError(
            "collection authorization was concurrently consumed"
        ) from error
    try:
        encoded = canonical_json_bytes(payload) + b"\n"
        offset = 0
        while offset < len(encoded):
            written = os.write(descriptor, encoded[offset:])
            if written <= 0:
                raise CollectionAuthorizationError("short write publishing collection receipt")
            offset += written
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise CollectionAuthorizationError("published collection receipt metadata is unsafe")
    finally:
        os.close(descriptor)
    os.fsync(directory_fd)


def consume_collection_key(
    *,
    resolved: ResolvedCollectionPreregV1,
    matched_key: str,
    now_ns: int | None = None,
    challenge_nonce: str | None = None,
    source_urdf_sha256: str,
    upstream_v4_probe_sha256: str,
    derived_probe_sha256: str,
    container_image_id: str,
) -> Path:
    """Atomically consume one selected key before any stage process starts."""

    ordinal, key = selected_key_ordinal(resolved, matched_key=matched_key)
    ledger_root = Path(resolved.prereg.ledger_root)
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            claims = _read_claims(directory_fd)
            if any(item.selected_key.matched_key == matched_key for item in claims):
                raise CollectionAuthorizationError("selected key was already consumed")
            same_batch = [item for item in claims if item.batch_id == resolved.prereg.batch_id]
            if [item.ordinal for item in same_batch] != list(range(len(same_batch))):
                raise CollectionAuthorizationError("current batch ledger prefix is not canonical")
            if len(same_batch) != ordinal:
                raise CollectionAuthorizationError(
                    "selected keys must be consumed in preregistered order"
                )
            for position, prior in enumerate(same_batch):
                if prior.selected_key != resolved.prereg.selected_keys[position]:
                    raise CollectionAuthorizationError(
                        "current batch ledger key differs from preregistration"
                    )
            key_payload = key.model_dump(mode="json")
            consumption_id = canonical_sha256(
                {
                    "prereg_file_sha256": resolved.file_sha256,
                    "prereg_sha256": resolved.prereg.prereg_sha256,
                    "ordinal": ordinal,
                    "selected_key": key_payload,
                }
            )
            nonce = challenge_nonce or secrets.token_hex(32)
            core: dict[str, Any] = {
                "schema_version": "M2CS4V3CollectionConsumptionReceiptV1",
                "event": "CONSUMED_BEFORE_STAGE",
                "ledger_namespace": resolved.prereg.ledger_namespace,
                "ledger_sequence": len(claims),
                "batch_id": resolved.prereg.batch_id,
                "ordinal": ordinal,
                "consumption_id": consumption_id,
                "challenge_nonce": nonce,
                "prereg_repository_path": resolved.prereg.repository_relative_path,
                "prereg_file_sha256": resolved.file_sha256,
                "prereg_sha256": resolved.prereg.prereg_sha256,
                "prereg_introduced_commit": resolved.introduced_commit,
                "selected_key": key_payload,
                "selected_key_sha256": canonical_sha256(key_payload),
                "source_sdf_sha256": key.sdf_sha256,
                "source_supervision_sha256": key.supervision_sha256,
                "source_urdf_sha256": source_urdf_sha256,
                "upstream_v4_probe_sha256": upstream_v4_probe_sha256,
                "committed_source_snapshot": resolved.prereg.committed_source_snapshot.model_dump(
                    mode="json"
                ),
                "derived_probe_sha256": derived_probe_sha256,
                "container_image": resolved.prereg.container_image,
                "container_image_id": container_image_id,
                "role": "TRAIN",
                "split": "train",
                "declared_target_attribute": "yellow",
                "destination_cell": next(
                    item.destination_cell
                    for item in resolved.manifest.training_keys
                    if item.matched_key == matched_key
                ),
                "candidate_contract_revision": resolved.prereg.candidate_contract_revision,
                "checkpoint_architecture_revision": (
                    resolved.prereg.checkpoint_architecture_revision
                ),
                "previous_receipt_sha256": claims[-1].receipt_sha256 if claims else None,
                "consumed_at_ns": now_ns or time.time_ns(),
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "model_rollout": False,
                "training_executed": False,
                "formal_q_b_evaluation": False,
            }
            receipt = M2CS4V3CollectionConsumptionReceiptV1.model_validate(
                {**core, "receipt_sha256": canonical_sha256(core)}
            )
            filename = f"claim-{len(claims):08d}.json"
            _write_create_only_json(
                directory_fd=directory_fd,
                filename=filename,
                payload=receipt.model_dump(mode="json"),
            )
            return ledger_root / filename
    finally:
        os.close(directory_fd)


def verify_consumed_collection_key(
    *,
    resolved: ResolvedCollectionPreregV1,
    claim_path: Path,
    matched_key: str,
    source_sdf_sha256: str | None = None,
    source_supervision_sha256: str | None = None,
    source_urdf_sha256: str | None = None,
    upstream_v4_probe_sha256: str | None = None,
    derived_probe_sha256: str | None = None,
    container_image_id: str | None = None,
    role: str | None = None,
    split: str | None = None,
    declared_target_attribute: str | None = None,
    destination_cell: str | None = None,
) -> M2CS4V3CollectionConsumptionReceiptV1:
    ledger_root = Path(resolved.prereg.ledger_root).resolve(strict=True)
    if claim_path.parent.resolve(strict=True) != ledger_root:
        raise CollectionAuthorizationError("collection claim is outside the frozen ledger root")
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            claims = _read_claims(directory_fd)
            passed_claim = M2CS4V3CollectionConsumptionReceiptV1.model_validate(
                _json_object(
                    _read_regular_file_at(directory_fd, claim_path.name),
                    label="collection claim",
                )
            )
    finally:
        os.close(directory_fd)
    matching = [item for item in claims if item.receipt_sha256 == passed_claim.receipt_sha256]
    if len(matching) != 1:
        raise CollectionAuthorizationError("collection claim is not an exact ledger member")
    claim = matching[0]
    ordinal, key = selected_key_ordinal(resolved, matched_key=matched_key)
    if (
        claim.batch_id != resolved.prereg.batch_id
        or claim.ordinal != ordinal
        or claim.selected_key != key
        or claim.prereg_file_sha256 != resolved.file_sha256
        or claim.prereg_sha256 != resolved.prereg.prereg_sha256
        or claim.prereg_introduced_commit != resolved.introduced_commit
        or claim.ledger_namespace != resolved.prereg.ledger_namespace
        or claim.committed_source_snapshot != resolved.prereg.committed_source_snapshot
    ):
        raise CollectionAuthorizationError(
            "collection claim differs from committed preregistration"
        )
    optional_claims = {
        "source_sdf_sha256": source_sdf_sha256,
        "source_supervision_sha256": source_supervision_sha256,
        "source_urdf_sha256": source_urdf_sha256,
        "upstream_v4_probe_sha256": upstream_v4_probe_sha256,
        "derived_probe_sha256": derived_probe_sha256,
        "container_image_id": container_image_id,
        "role": role,
        "split": split,
        "declared_target_attribute": declared_target_attribute,
        "destination_cell": destination_cell,
    }
    for field, expected in optional_claims.items():
        if expected is not None and getattr(claim, field) != expected:
            raise CollectionAuthorizationError(f"collection claim differs in {field}")
    return claim


class M2CS4V3ProbeStartCapabilityV1(StrictModel):
    """Host-issued, stage-bound capability consumed read-only by the probe."""

    schema_version: Literal["M2CS4V3ProbeStartCapabilityV1"]
    event: Literal["HOST_ISSUED_AFTER_STAGE_VALIDATION_BEFORE_PROBE"]
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_key: str
    failure_seed: int = Field(ge=0)
    source_sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_urdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    upstream_v4_probe_sha256: Literal[
        "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
    ]
    committed_source_snapshot: CommittedSourceSnapshotV1
    stage_usdc_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_image: Literal["nvcr.io/nvidia/isaac-sim:6.0.1"]
    container_image_id: Literal[
        "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
    ]
    probe_argv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    docker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_socket_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_token_path_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_output_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["TRAIN"]
    split: Literal["train"]
    declared_target_attribute: Literal["yellow"]
    destination_cell: str = Field(pattern=r"^BIN_CELL_[0-5]$")
    issued_at_ns: int = Field(gt=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_receipt_is_bound(self) -> "M2CS4V3ProbeStartCapabilityV1":
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
            != self.receipt_sha256
        ):
            raise ValueError("probe-start capability canonical digest mismatch")
        return self


class M2CS4V3RawAuthorizationBindingV1(StrictModel):
    schema_version: Literal["M2CS4V3RawAuthorizationBindingV1"]
    prereg_repository_path: str
    prereg_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_introduced_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_start_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_launch_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_key: str
    failure_seed: int = Field(ge=0)
    source_sdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_supervision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_urdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    upstream_v4_probe_sha256: Literal[
        "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
    ]
    committed_source_snapshot: CommittedSourceSnapshotV1
    stage_usdc_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    derived_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_image: Literal["nvcr.io/nvidia/isaac-sim:6.0.1"]
    container_image_id: Literal[
        "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
    ]
    probe_argv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    docker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_socket_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_token_path_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_output_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal["TRAIN"]
    split: Literal["train"]
    declared_target_attribute: Literal["yellow"]
    destination_cell: str = Field(pattern=r"^BIN_CELL_[0-5]$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]


class M2CS4V3ProbeLaunchConsumptionV1(StrictModel):
    schema_version: Literal["M2CS4V3ProbeLaunchConsumptionV1"]
    event: Literal["HOST_CONSUMED_IMMEDIATELY_BEFORE_DOCKER_SPAWN"]
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_start_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    docker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_output_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumed_at_ns: int = Field(gt=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_receipt_is_bound(self) -> "M2CS4V3ProbeLaunchConsumptionV1":
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
            != self.receipt_sha256
        ):
            raise ValueError("probe-launch receipt canonical digest mismatch")
        return self


class M2CS4V3ProbeEntryReceiptV1(StrictModel):
    """Create-only proof that this process crossed the pre-Kit boundary once."""

    schema_version: Literal["M2CS4V3ProbeEntryReceiptV1"]
    event: Literal["PROBE_ENTRY_CONSUMED_BEFORE_KIT"]
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_start_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_launch_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    docker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_socket_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_token_path_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_output_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entered_at_ns: int = Field(gt=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_receipt_is_bound(self) -> "M2CS4V3ProbeEntryReceiptV1":
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
            != self.receipt_sha256
        ):
            raise ValueError("probe-entry receipt canonical digest mismatch")
        return self


class M2CS4V3ProbeTerminalReceiptV1(StrictModel):
    schema_version: Literal["M2CS4V3ProbeTerminalReceiptV1"]
    event: Literal["HOST_TERMINALIZED_AFTER_DOCKER_EXIT"]
    status: Literal["COMPLETE", "TERMINAL_FAILURE"]
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_start_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_launch_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    consumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    docker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_output_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    returncode: int
    console_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_probe_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    terminalized_at_ns: int = Field(gt=0)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def terminal_claim_is_consistent(self) -> "M2CS4V3ProbeTerminalReceiptV1":
        if self.status == "COMPLETE" and (
            self.returncode != 0
            or self.raw_probe_sha256 is None
            or self.probe_entry_receipt_sha256 is None
        ):
            raise ValueError("complete probe terminal receipt lacks a successful raw output")
        if self.status == "TERMINAL_FAILURE" and (
            self.returncode == 0
            and self.raw_probe_sha256 is not None
            and self.probe_entry_receipt_sha256 is not None
        ):
            raise ValueError("successful raw output cannot be terminalized as failure")
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
            != self.receipt_sha256
        ):
            raise ValueError("probe terminal receipt canonical digest mismatch")
        return self


class M2CS4V3PackagedAuthorizationBindingV1(StrictModel):
    schema_version: Literal["M2CS4V3PackagedAuthorizationBindingV1"]
    prereg_repository_path: str
    prereg_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prereg_introduced_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    matched_key: str
    upstream_v4_probe_sha256: Literal[
        "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
    ]
    committed_source_snapshot: CommittedSourceSnapshotV1
    consumption_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_start_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_launch_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_terminal_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    console_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    docker_command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_socket_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_token_path_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_entry_broker_token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_output_root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]
    model_rollout: Literal[False]
    formal_q_b_evaluation: Literal[False]
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_receipt_is_bound(self) -> "M2CS4V3PackagedAuthorizationBindingV1":
        if (
            canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
            != self.receipt_sha256
        ):
            raise ValueError("packaged authorization canonical digest mismatch")
        return self


@dataclass(frozen=True)
class IssuedProbeStartCapabilityV1:
    """Host-only one-shot material; the token never enters durable evidence."""

    path: Path
    broker_socket_path: Path
    broker_token_path: Path
    broker_token: bytes


@dataclass
class ProbeEntryBrokerV1:
    socket_path: Path
    thread: threading.Thread
    completed: threading.Event
    cancelled: threading.Event
    listener: socket.socket
    errors: list[BaseException]

    def wait(self, *, timeout_s: float = 5.0) -> None:
        self.thread.join(timeout_s)
        if self.thread.is_alive():
            raise CollectionAuthorizationError("probe-entry broker did not terminate")
        if self.errors:
            raise CollectionAuthorizationError(
                "probe-entry broker rejected the launch"
            ) from self.errors[0]

    def cancel(self, *, timeout_s: float = 5.0) -> None:
        self.cancelled.set()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout_s)
                connection.connect(str(self.socket_path))
                connection.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        self.listener.close()
        self.thread.join(timeout_s)
        if self.thread.is_alive():
            raise CollectionAuthorizationError("probe-entry broker did not cancel")


def probe_start_capability_path(
    *,
    resolved: ResolvedCollectionPreregV1,
    claim_path: Path,
    matched_key: str,
) -> Path:
    claim = verify_consumed_collection_key(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=matched_key,
    )
    return Path(resolved.prereg.ledger_root) / f"probe-start-{claim.consumption_id}.json"


def probe_entry_broker_socket_path(consumption_id: str) -> Path:
    if len(consumption_id) != 64 or any(
        character not in "0123456789abcdef" for character in consumption_id
    ):
        raise CollectionAuthorizationError("probe-entry broker consumption ID is invalid")
    return Path(CANONICAL_PROBE_ENTRY_BROKER_ROOT) / consumption_id / "entry.sock"


def probe_entry_broker_token_path(consumption_id: str) -> Path:
    if len(consumption_id) != 64 or any(
        character not in "0123456789abcdef" for character in consumption_id
    ):
        raise CollectionAuthorizationError("probe-entry broker consumption ID is invalid")
    return Path(CANONICAL_PROBE_ENTRY_BROKER_ROOT) / consumption_id / "entry.token"


def issue_probe_start_capability(
    *,
    resolved: ResolvedCollectionPreregV1,
    claim_path: Path,
    matched_key: str,
    failure_seed: int,
    source_sdf_sha256: str,
    source_supervision_sha256: str,
    source_urdf_sha256: str,
    upstream_v4_probe_sha256: str,
    stage_usdc_sha256: str,
    stage_metrics_sha256: str,
    stage_command_sha256: str,
    derived_probe_sha256: str,
    container_image_id: str,
    probe_argv_sha256: str,
    docker_command_sha256: str,
    job_root_sha256: str,
    probe_output_root_sha256: str,
    role: str,
    split: str,
    declared_target_attribute: str,
    destination_cell: str,
    now_ns: int | None = None,
) -> IssuedProbeStartCapabilityV1:
    """Publish one host-owned capability after the exact stage is validated."""

    claim = verify_consumed_collection_key(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=matched_key,
        source_sdf_sha256=source_sdf_sha256,
        source_supervision_sha256=source_supervision_sha256,
        source_urdf_sha256=source_urdf_sha256,
        upstream_v4_probe_sha256=upstream_v4_probe_sha256,
        derived_probe_sha256=derived_probe_sha256,
        container_image_id=container_image_id,
        role=role,
        split=split,
        declared_target_attribute=declared_target_attribute,
        destination_cell=destination_cell,
    )
    if failure_seed != claim.selected_key.failure_seed:
        raise CollectionAuthorizationError("probe failure seed differs from consumed claim")
    broker_socket_path = probe_entry_broker_socket_path(claim.consumption_id)
    broker_token_path = probe_entry_broker_token_path(claim.consumption_id)
    broker_token = secrets.token_bytes(32)
    core: dict[str, Any] = {
        "schema_version": "M2CS4V3ProbeStartCapabilityV1",
        "event": "HOST_ISSUED_AFTER_STAGE_VALIDATION_BEFORE_PROBE",
        "consumption_receipt_sha256": claim.receipt_sha256,
        "consumption_id": claim.consumption_id,
        "challenge_nonce": claim.challenge_nonce,
        "matched_key": matched_key,
        "failure_seed": failure_seed,
        "source_sdf_sha256": claim.source_sdf_sha256,
        "source_supervision_sha256": claim.source_supervision_sha256,
        "source_urdf_sha256": claim.source_urdf_sha256,
        "upstream_v4_probe_sha256": claim.upstream_v4_probe_sha256,
        "committed_source_snapshot": claim.committed_source_snapshot.model_dump(mode="json"),
        "stage_usdc_sha256": stage_usdc_sha256,
        "stage_metrics_sha256": stage_metrics_sha256,
        "stage_command_sha256": stage_command_sha256,
        "derived_probe_sha256": claim.derived_probe_sha256,
        "container_image": claim.container_image,
        "container_image_id": claim.container_image_id,
        "probe_argv_sha256": probe_argv_sha256,
        "docker_command_sha256": docker_command_sha256,
        "probe_entry_broker_socket_sha256": canonical_path_sha256(broker_socket_path),
        "probe_entry_token_path_sha256": canonical_path_sha256(broker_token_path),
        "probe_entry_broker_token_sha256": sha256_bytes(broker_token),
        "job_root_sha256": job_root_sha256,
        "probe_output_root_sha256": probe_output_root_sha256,
        "role": claim.role,
        "split": claim.split,
        "declared_target_attribute": claim.declared_target_attribute,
        "destination_cell": claim.destination_cell,
        "issued_at_ns": now_ns or time.time_ns(),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
    }
    start = M2CS4V3ProbeStartCapabilityV1.model_validate(
        {**core, "receipt_sha256": canonical_sha256(core)}
    )
    ledger_root = Path(resolved.prereg.ledger_root)
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            _write_create_only_json(
                directory_fd=directory_fd,
                filename=f"probe-start-{claim.consumption_id}.json",
                payload=start.model_dump(mode="json"),
            )
            entry_fd = _open_probe_entry_directory(
                directory_fd,
                consumption_id=claim.consumption_id,
                create=True,
            )
            os.close(entry_fd)
    finally:
        os.close(directory_fd)
    return IssuedProbeStartCapabilityV1(
        path=ledger_root / f"probe-start-{claim.consumption_id}.json",
        broker_socket_path=broker_socket_path,
        broker_token_path=broker_token_path,
        broker_token=broker_token,
    )


def consume_probe_launch(
    *,
    resolved: ResolvedCollectionPreregV1,
    claim_path: Path,
    matched_key: str,
) -> Path:
    """Atomically mark the exact host launch immediately before Docker spawn."""

    claim = verify_consumed_collection_key(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=matched_key,
    )
    ledger_root = Path(resolved.prereg.ledger_root)
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            start_name = f"probe-start-{claim.consumption_id}.json"
            start = M2CS4V3ProbeStartCapabilityV1.model_validate(
                _json_object(
                    _read_regular_file_at(directory_fd, start_name),
                    label="probe-start capability",
                )
            )
            launch_fd = _open_launch_consumption_directory(directory_fd, create=True)
            try:
                core: dict[str, Any] = {
                    "schema_version": "M2CS4V3ProbeLaunchConsumptionV1",
                    "event": "HOST_CONSUMED_IMMEDIATELY_BEFORE_DOCKER_SPAWN",
                    "consumption_receipt_sha256": claim.receipt_sha256,
                    "probe_start_receipt_sha256": start.receipt_sha256,
                    "consumption_id": claim.consumption_id,
                    "challenge_nonce": claim.challenge_nonce,
                    "docker_command_sha256": start.docker_command_sha256,
                    "job_root_sha256": start.job_root_sha256,
                    "probe_output_root_sha256": start.probe_output_root_sha256,
                    "consumed_at_ns": time.time_ns(),
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                    "model_rollout": False,
                    "formal_q_b_evaluation": False,
                }
                launch = M2CS4V3ProbeLaunchConsumptionV1.model_validate(
                    {**core, "receipt_sha256": canonical_sha256(core)}
                )
                filename = f"launch-{claim.consumption_id}.json"
                _write_create_only_json(
                    directory_fd=launch_fd,
                    filename=filename,
                    payload=launch.model_dump(mode="json"),
                )
            finally:
                os.close(launch_fd)
    finally:
        os.close(directory_fd)
    return ledger_root / LAUNCH_CONSUMPTION_DIRECTORY / filename


def start_probe_entry_broker(
    *,
    resolved: ResolvedCollectionPreregV1,
    claim_path: Path,
    matched_key: str,
    issued: IssuedProbeStartCapabilityV1,
    accept_timeout_s: float,
) -> ProbeEntryBrokerV1:
    """Start a host-resident one-shot broker after launch consumption.

    The token is placed in one ephemeral private file only after launch
    consumption and is removed after the broker's sole exchange. It never
    enters the durable ledger or evidence. Copying claim/start files or
    substituting a fresh writable mount cannot recreate the host listener or
    mint a second pre-Kit entry receipt.
    """

    if accept_timeout_s <= 0:
        raise CollectionAuthorizationError("probe-entry broker timeout must be positive")
    claim = verify_consumed_collection_key(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=matched_key,
    )
    ledger_root = Path(resolved.prereg.ledger_root)
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            start = M2CS4V3ProbeStartCapabilityV1.model_validate(
                _json_object(
                    _read_regular_file_at(
                        directory_fd,
                        f"probe-start-{claim.consumption_id}.json",
                    ),
                    label="probe-start capability",
                )
            )
            launch_fd = _open_launch_consumption_directory(directory_fd, create=False)
            try:
                launch = M2CS4V3ProbeLaunchConsumptionV1.model_validate(
                    _json_object(
                        _read_regular_file_at(
                            launch_fd,
                            f"launch-{claim.consumption_id}.json",
                        ),
                        label="probe-launch consumption receipt",
                    )
                )
            finally:
                os.close(launch_fd)
    finally:
        os.close(directory_fd)
    if (
        issued.path != ledger_root / f"probe-start-{claim.consumption_id}.json"
        or issued.broker_socket_path != probe_entry_broker_socket_path(claim.consumption_id)
        or issued.broker_token_path != probe_entry_broker_token_path(claim.consumption_id)
        or sha256_bytes(issued.broker_token) != start.probe_entry_broker_token_sha256
        or canonical_path_sha256(issued.broker_socket_path)
        != start.probe_entry_broker_socket_sha256
        or canonical_path_sha256(issued.broker_token_path) != start.probe_entry_token_path_sha256
        or launch.consumption_receipt_sha256 != claim.receipt_sha256
        or launch.probe_start_receipt_sha256 != start.receipt_sha256
        or launch.consumption_id != claim.consumption_id
        or launch.challenge_nonce != claim.challenge_nonce
    ):
        raise CollectionAuthorizationError("probe-entry broker material differs from launch")

    broker_root = Path(CANONICAL_PROBE_ENTRY_BROKER_ROOT)
    broker_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root_info = broker_root.lstat()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or root_info.st_uid != os.geteuid()
        or stat.S_IMODE(root_info.st_mode) != 0o700
    ):
        raise CollectionAuthorizationError("probe-entry broker root is not private")
    session_root = issued.broker_socket_path.parent
    session_root.mkdir(mode=0o700, exist_ok=False)
    session_info = session_root.lstat()
    if (
        not stat.S_ISDIR(session_info.st_mode)
        or session_info.st_uid != os.geteuid()
        or stat.S_IMODE(session_info.st_mode) != 0o700
    ):
        raise CollectionAuthorizationError("probe-entry broker session is not private")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        token_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        token_fd = os.open(issued.broker_token_path, token_flags, 0o600)
        try:
            offset = 0
            while offset < len(issued.broker_token):
                written = os.write(token_fd, issued.broker_token[offset:])
                if written <= 0:
                    raise CollectionAuthorizationError("short probe-entry token write")
                offset += written
            os.fsync(token_fd)
        finally:
            os.close(token_fd)
        listener.bind(str(issued.broker_socket_path))
        os.chmod(issued.broker_socket_path, 0o600)
        listener.listen(1)
        listener.settimeout(accept_timeout_s)
    except BaseException:
        listener.close()
        try:
            issued.broker_socket_path.unlink()
        except FileNotFoundError:
            pass
        try:
            issued.broker_token_path.unlink()
        except FileNotFoundError:
            pass
        try:
            session_root.rmdir()
        except OSError:
            pass
        raise
    completed = threading.Event()
    cancelled = threading.Event()
    errors: list[BaseException] = []

    def serve_once() -> None:
        try:
            connection, _address = listener.accept()
            with connection:
                chunks: list[bytes] = []
                while sum(map(len, chunks)) <= 4096:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
                request_bytes = b"".join(chunks)
                if not request_bytes.endswith(b"\n") or request_bytes.count(b"\n") != 1:
                    raise CollectionAuthorizationError(
                        "probe-entry broker request framing is invalid"
                    )
                request = _json_object(request_bytes[:-1], label="probe-entry broker request")
                expected_request = {
                    "schema_version": "M2CS4V3ProbeEntryBrokerRequestV1",
                    "consumption_id": claim.consumption_id,
                    "probe_start_receipt_sha256": start.receipt_sha256,
                    "probe_launch_receipt_sha256": launch.receipt_sha256,
                    "docker_command_sha256": start.docker_command_sha256,
                    "token": issued.broker_token.hex(),
                }
                if request != expected_request:
                    raise CollectionAuthorizationError("probe-entry broker request is not exact")
                entry_core: dict[str, Any] = {
                    "schema_version": "M2CS4V3ProbeEntryReceiptV1",
                    "event": "PROBE_ENTRY_CONSUMED_BEFORE_KIT",
                    "consumption_receipt_sha256": claim.receipt_sha256,
                    "probe_start_receipt_sha256": start.receipt_sha256,
                    "probe_launch_receipt_sha256": launch.receipt_sha256,
                    "consumption_id": claim.consumption_id,
                    "challenge_nonce": claim.challenge_nonce,
                    "docker_command_sha256": start.docker_command_sha256,
                    "probe_entry_broker_socket_sha256": start.probe_entry_broker_socket_sha256,
                    "probe_entry_token_path_sha256": start.probe_entry_token_path_sha256,
                    "probe_entry_broker_token_sha256": start.probe_entry_broker_token_sha256,
                    "job_root_sha256": start.job_root_sha256,
                    "probe_output_root_sha256": start.probe_output_root_sha256,
                    "entered_at_ns": time.time_ns(),
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                    "model_rollout": False,
                    "formal_q_b_evaluation": False,
                }
                entry = M2CS4V3ProbeEntryReceiptV1.model_validate(
                    {**entry_core, "receipt_sha256": canonical_sha256(entry_core)}
                )
                ledger_fd = _secure_ledger_directory(ledger_root)
                try:
                    with _exclusive_ledger_lock(ledger_fd):
                        entry_fd = _open_probe_entry_directory(
                            ledger_fd,
                            consumption_id=claim.consumption_id,
                            create=False,
                        )
                        try:
                            _write_create_only_json(
                                directory_fd=entry_fd,
                                filename=PROBE_ENTRY_RECEIPT_NAME,
                                payload=entry.model_dump(mode="json"),
                            )
                        finally:
                            os.close(entry_fd)
                finally:
                    os.close(ledger_fd)
                response = (
                    canonical_json_bytes(
                        {
                            "schema_version": "M2CS4V3ProbeEntryBrokerResponseV1",
                            "entry": entry.model_dump(mode="json"),
                        }
                    )
                    + b"\n"
                )
                connection.sendall(response)
        except BaseException as error:  # surfaced synchronously by wait()
            if not cancelled.is_set():
                errors.append(error)
        finally:
            listener.close()
            try:
                issued.broker_socket_path.unlink()
            except FileNotFoundError:
                pass
            try:
                issued.broker_token_path.unlink()
            except FileNotFoundError:
                pass
            try:
                session_root.rmdir()
            except OSError:
                pass
            completed.set()

    thread = threading.Thread(
        target=serve_once,
        name=f"m2c-v3-broker-{claim.consumption_id[:12]}",
        daemon=True,
    )
    thread.start()
    return ProbeEntryBrokerV1(
        socket_path=issued.broker_socket_path,
        thread=thread,
        completed=completed,
        cancelled=cancelled,
        listener=listener,
        errors=errors,
    )


def terminalize_probe_launch(
    *,
    resolved: ResolvedCollectionPreregV1,
    claim_path: Path,
    matched_key: str,
    job_root: Path,
    probe_output_root: Path,
    returncode: int,
    console_path: Path,
    raw_probe_path: Path,
    now_ns: int | None = None,
) -> Path:
    """Publish the sole raw output eligible for packaging after Docker exits."""

    claim = verify_consumed_collection_key(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=matched_key,
    )
    ledger_root = Path(resolved.prereg.ledger_root)
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            start = M2CS4V3ProbeStartCapabilityV1.model_validate(
                _json_object(
                    _read_regular_file_at(
                        directory_fd,
                        f"probe-start-{claim.consumption_id}.json",
                    ),
                    label="probe-start capability",
                )
            )
            launch_fd = _open_launch_consumption_directory(directory_fd, create=False)
            try:
                launch = M2CS4V3ProbeLaunchConsumptionV1.model_validate(
                    _json_object(
                        _read_regular_file_at(
                            launch_fd,
                            f"launch-{claim.consumption_id}.json",
                        ),
                        label="probe-launch consumption receipt",
                    )
                )
                entry_fd = _open_probe_entry_directory(
                    directory_fd,
                    consumption_id=claim.consumption_id,
                    create=False,
                )
                try:
                    try:
                        entry = M2CS4V3ProbeEntryReceiptV1.model_validate(
                            _json_object(
                                _read_regular_file_at(entry_fd, PROBE_ENTRY_RECEIPT_NAME),
                                label="probe-entry receipt",
                            )
                        )
                    except CollectionAuthorizationError:
                        entry = None
                finally:
                    os.close(entry_fd)
                console_bytes = read_regular_file_once(console_path)
                try:
                    raw_sha256 = sha256_bytes(read_regular_file_once(raw_probe_path))
                except CollectionAuthorizationError:
                    raw_sha256 = None
                core: dict[str, Any] = {
                    "schema_version": "M2CS4V3ProbeTerminalReceiptV1",
                    "event": "HOST_TERMINALIZED_AFTER_DOCKER_EXIT",
                    "status": (
                        "COMPLETE"
                        if returncode == 0 and raw_sha256 is not None
                        else "TERMINAL_FAILURE"
                    ),
                    "consumption_receipt_sha256": claim.receipt_sha256,
                    "probe_start_receipt_sha256": start.receipt_sha256,
                    "probe_launch_receipt_sha256": launch.receipt_sha256,
                    "probe_entry_receipt_sha256": (
                        entry.receipt_sha256 if entry is not None else None
                    ),
                    "consumption_id": claim.consumption_id,
                    "challenge_nonce": claim.challenge_nonce,
                    "docker_command_sha256": start.docker_command_sha256,
                    "job_root_sha256": canonical_path_sha256(job_root),
                    "probe_output_root_sha256": canonical_path_sha256(probe_output_root),
                    "returncode": returncode,
                    "console_sha256": sha256_bytes(console_bytes),
                    "raw_probe_sha256": raw_sha256,
                    "terminalized_at_ns": now_ns or time.time_ns(),
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                    "model_rollout": False,
                    "formal_q_b_evaluation": False,
                }
                terminal = M2CS4V3ProbeTerminalReceiptV1.model_validate(
                    {**core, "receipt_sha256": canonical_sha256(core)}
                )
                _write_create_only_json(
                    directory_fd=launch_fd,
                    filename=f"terminal-{claim.consumption_id}.json",
                    payload=terminal.model_dump(mode="json"),
                )
            finally:
                os.close(launch_fd)
    finally:
        os.close(directory_fd)
    return ledger_root / LAUNCH_CONSUMPTION_DIRECTORY / (f"terminal-{claim.consumption_id}.json")


def authorize_probe_start(
    *,
    claim_path: Path,
    start_capability_path: Path,
    probe_entry_broker_socket: Path,
    probe_entry_token_file: Path,
    source_snapshot_root: Path,
    matched_key: str,
    failure_seed: int,
    source_sdf_sha256: str,
    source_supervision_sha256: str,
    source_urdf_sha256: str,
    upstream_v4_probe_sha256: str,
    stage_usdc_sha256: str,
    stage_metrics_sha256: str,
    stage_command_sha256: str,
    derived_probe_sha256: str,
    container_image_id: str,
    probe_argv: list[str],
    job_root_sha256: str,
    probe_output_root_sha256: str,
    role: str,
    split: str,
    declared_target_attribute: str,
    destination_cell: str,
) -> M2CS4V3RawAuthorizationBindingV1:
    """Verify a host-issued capability before importing Isaac/Kit.

    The probe receives read-only capability files and connects once to a
    host-resident broker. The broker token is never persisted, so copied
    capability bytes and a substituted writable mount cannot be replayed.
    """

    ledger_root = Path(CANONICAL_COLLECTION_LEDGER_ROOT)
    if claim_path.parent != ledger_root or start_capability_path.parent != ledger_root:
        raise CollectionAuthorizationError(
            "probe capability paths are outside the canonical host ledger"
        )
    if not claim_path.name.startswith("claim-") or not claim_path.name.endswith(".json"):
        raise CollectionAuthorizationError("probe claim filename is invalid")
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        claim = M2CS4V3CollectionConsumptionReceiptV1.model_validate(
            _json_object(
                _read_regular_file_at(directory_fd, claim_path.name),
                label="collection claim",
            )
        )
        expected_start_name = f"probe-start-{claim.consumption_id}.json"
        if start_capability_path.name != expected_start_name:
            raise CollectionAuthorizationError("probe-start capability filename is invalid")
        start = M2CS4V3ProbeStartCapabilityV1.model_validate(
            _json_object(
                _read_regular_file_at(directory_fd, expected_start_name),
                label="probe-start capability",
            )
        )
        launch_fd = _open_launch_consumption_directory(directory_fd, create=False)
        try:
            launch = M2CS4V3ProbeLaunchConsumptionV1.model_validate(
                _json_object(
                    _read_regular_file_at(
                        launch_fd,
                        f"launch-{claim.consumption_id}.json",
                    ),
                    label="probe-launch consumption receipt",
                )
            )
        finally:
            os.close(launch_fd)
    finally:
        os.close(directory_fd)
    # Docker bind mounts expose the verified host snapshot at the fixed
    # in-container path /workspace/project, so its basename is no longer the
    # host-side content address.  The host materializer and launch capability
    # bind the content-addressed source path; the probe independently replays
    # every byte and mode from that mounted tree here.
    verify_materialized_source_snapshot(
        source_snapshot_root,
        claim.committed_source_snapshot,
        require_content_addressed_name=False,
    )
    try:
        digest_option_index = probe_argv.index("--m2c-docker-command-sha256") + 1
    except (ValueError, IndexError) as error:
        raise CollectionAuthorizationError(
            "probe argv lacks the host-bound Docker command digest"
        ) from error
    docker_command_sha256 = probe_argv[digest_option_index]
    expected_values: dict[str, object] = {
        "consumption_receipt_sha256": claim.receipt_sha256,
        "consumption_id": claim.consumption_id,
        "challenge_nonce": claim.challenge_nonce,
        "matched_key": matched_key,
        "failure_seed": failure_seed,
        "source_sdf_sha256": source_sdf_sha256,
        "source_supervision_sha256": source_supervision_sha256,
        "source_urdf_sha256": source_urdf_sha256,
        "upstream_v4_probe_sha256": upstream_v4_probe_sha256,
        "committed_source_snapshot": claim.committed_source_snapshot,
        "stage_usdc_sha256": stage_usdc_sha256,
        "stage_metrics_sha256": stage_metrics_sha256,
        "stage_command_sha256": stage_command_sha256,
        "derived_probe_sha256": derived_probe_sha256,
        "container_image": claim.container_image,
        "container_image_id": container_image_id,
        "probe_argv_sha256": canonical_sha256(probe_argv),
        "docker_command_sha256": docker_command_sha256,
        "probe_entry_broker_socket_sha256": canonical_path_sha256(probe_entry_broker_socket),
        "probe_entry_token_path_sha256": canonical_path_sha256(probe_entry_token_file),
        "job_root_sha256": job_root_sha256,
        "probe_output_root_sha256": probe_output_root_sha256,
        "role": role,
        "split": split,
        "declared_target_attribute": declared_target_attribute,
        "destination_cell": destination_cell,
    }
    for field, expected in expected_values.items():
        if getattr(start, field) != expected:
            raise CollectionAuthorizationError(f"probe-start capability differs in {field}")
    claim_values = {
        "matched_key": claim.selected_key.matched_key,
        "failure_seed": claim.selected_key.failure_seed,
        "source_sdf_sha256": claim.source_sdf_sha256,
        "source_supervision_sha256": claim.source_supervision_sha256,
        "source_urdf_sha256": claim.source_urdf_sha256,
        "upstream_v4_probe_sha256": claim.upstream_v4_probe_sha256,
        "committed_source_snapshot": claim.committed_source_snapshot,
        "derived_probe_sha256": claim.derived_probe_sha256,
        "container_image_id": claim.container_image_id,
        "role": claim.role,
        "split": claim.split,
        "declared_target_attribute": claim.declared_target_attribute,
        "destination_cell": claim.destination_cell,
    }
    for field, expected in claim_values.items():
        if expected_values[field] != expected:
            raise CollectionAuthorizationError(f"probe arguments differ from claim in {field}")
    if (
        probe_entry_broker_socket != probe_entry_broker_socket_path(claim.consumption_id)
        or launch.consumption_receipt_sha256 != claim.receipt_sha256
        or launch.probe_start_receipt_sha256 != start.receipt_sha256
        or launch.consumption_id != claim.consumption_id
        or launch.challenge_nonce != claim.challenge_nonce
        or launch.docker_command_sha256 != start.docker_command_sha256
    ):
        raise CollectionAuthorizationError(
            "probe launch or broker endpoint differs from capability"
        )
    token_bytes = read_regular_file_once(probe_entry_token_file)
    if len(token_bytes) != 32 or sha256_bytes(token_bytes) != start.probe_entry_broker_token_sha256:
        raise CollectionAuthorizationError("probe-entry token differs from capability")
    request = (
        canonical_json_bytes(
            {
                "schema_version": "M2CS4V3ProbeEntryBrokerRequestV1",
                "consumption_id": claim.consumption_id,
                "probe_start_receipt_sha256": start.receipt_sha256,
                "probe_launch_receipt_sha256": launch.receipt_sha256,
                "docker_command_sha256": start.docker_command_sha256,
                "token": token_bytes.hex(),
            }
        )
        + b"\n"
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(10.0)
            connection.connect(str(probe_entry_broker_socket))
            connection.sendall(request)
            connection.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while sum(map(len, chunks)) <= 65536:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as error:
        raise CollectionAuthorizationError("probe-entry broker is unavailable") from error
    response_bytes = b"".join(chunks)
    if not response_bytes.endswith(b"\n") or response_bytes.count(b"\n") != 1:
        raise CollectionAuthorizationError("probe-entry broker response framing is invalid")
    response = _json_object(response_bytes[:-1], label="probe-entry broker response")
    if set(response) != {"schema_version", "entry"} or response.get("schema_version") != (
        "M2CS4V3ProbeEntryBrokerResponseV1"
    ):
        raise CollectionAuthorizationError("probe-entry broker response schema is invalid")
    entry = M2CS4V3ProbeEntryReceiptV1.model_validate(response["entry"])
    if (
        entry.consumption_receipt_sha256 != claim.receipt_sha256
        or entry.probe_start_receipt_sha256 != start.receipt_sha256
        or entry.probe_launch_receipt_sha256 != launch.receipt_sha256
        or entry.consumption_id != claim.consumption_id
        or entry.challenge_nonce != claim.challenge_nonce
        or entry.docker_command_sha256 != start.docker_command_sha256
        or entry.probe_entry_broker_socket_sha256 != start.probe_entry_broker_socket_sha256
        or entry.probe_entry_token_path_sha256 != start.probe_entry_token_path_sha256
        or entry.probe_entry_broker_token_sha256 != start.probe_entry_broker_token_sha256
        or entry.job_root_sha256 != start.job_root_sha256
        or entry.probe_output_root_sha256 != start.probe_output_root_sha256
    ):
        raise CollectionAuthorizationError("probe-entry broker receipt differs from launch")
    return M2CS4V3RawAuthorizationBindingV1(
        schema_version="M2CS4V3RawAuthorizationBindingV1",
        prereg_repository_path=claim.prereg_repository_path,
        prereg_file_sha256=claim.prereg_file_sha256,
        prereg_sha256=claim.prereg_sha256,
        prereg_introduced_commit=claim.prereg_introduced_commit,
        consumption_receipt_sha256=claim.receipt_sha256,
        consumption_id=claim.consumption_id,
        challenge_nonce=claim.challenge_nonce,
        probe_start_receipt_sha256=start.receipt_sha256,
        probe_launch_receipt_sha256=launch.receipt_sha256,
        probe_entry_receipt_sha256=entry.receipt_sha256,
        matched_key=matched_key,
        failure_seed=failure_seed,
        source_sdf_sha256=claim.source_sdf_sha256,
        source_supervision_sha256=claim.source_supervision_sha256,
        source_urdf_sha256=claim.source_urdf_sha256,
        upstream_v4_probe_sha256=claim.upstream_v4_probe_sha256,
        committed_source_snapshot=claim.committed_source_snapshot,
        stage_usdc_sha256=stage_usdc_sha256,
        stage_metrics_sha256=stage_metrics_sha256,
        stage_command_sha256=stage_command_sha256,
        derived_probe_sha256=claim.derived_probe_sha256,
        container_image=claim.container_image,
        container_image_id=claim.container_image_id,
        probe_argv_sha256=start.probe_argv_sha256,
        docker_command_sha256=start.docker_command_sha256,
        probe_entry_broker_socket_sha256=start.probe_entry_broker_socket_sha256,
        probe_entry_token_path_sha256=start.probe_entry_token_path_sha256,
        probe_entry_broker_token_sha256=start.probe_entry_broker_token_sha256,
        job_root_sha256=start.job_root_sha256,
        probe_output_root_sha256=start.probe_output_root_sha256,
        role=claim.role,
        split=claim.split,
        declared_target_attribute=claim.declared_target_attribute,
        destination_cell=claim.destination_cell,
        teacher_used=False,
        privileged_truth_policy_input=False,
        model_rollout=False,
        formal_q_b_evaluation=False,
    )


def verify_packaging_authorization(
    *,
    project_root: Path,
    prereg_path: Path,
    claim_path: Path,
    matched_key: str,
    raw_binding: dict[str, Any],
    raw_probe_sha256: str,
    console_sha256: str,
    job_root: Path,
    probe_output_root: Path,
) -> tuple[
    ResolvedCollectionPreregV1,
    M2CS4V3CollectionConsumptionReceiptV1,
    M2CS4V3PackagedAuthorizationBindingV1,
]:
    """Verify the raw probe came from the unique authorized probe start."""

    resolved = load_committed_collection_prereg(
        project_root=project_root,
        prereg_path=prereg_path,
    )
    claim = verify_consumed_collection_key(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=matched_key,
    )
    ledger_root = Path(resolved.prereg.ledger_root)
    directory_fd = _secure_ledger_directory(ledger_root)
    try:
        with _exclusive_ledger_lock(directory_fd):
            marker_bytes = _read_regular_file_at(
                directory_fd,
                f"probe-start-{claim.consumption_id}.json",
            )
            launch_fd = _open_launch_consumption_directory(directory_fd, create=False)
            try:
                launch = M2CS4V3ProbeLaunchConsumptionV1.model_validate(
                    _json_object(
                        _read_regular_file_at(
                            launch_fd,
                            f"launch-{claim.consumption_id}.json",
                        ),
                        label="probe-launch consumption receipt",
                    )
                )
                terminal = M2CS4V3ProbeTerminalReceiptV1.model_validate(
                    _json_object(
                        _read_regular_file_at(
                            launch_fd,
                            f"terminal-{claim.consumption_id}.json",
                        ),
                        label="probe terminal receipt",
                    )
                )
                entry_fd = _open_probe_entry_directory(
                    directory_fd,
                    consumption_id=claim.consumption_id,
                    create=False,
                )
                try:
                    entry = M2CS4V3ProbeEntryReceiptV1.model_validate(
                        _json_object(
                            _read_regular_file_at(entry_fd, PROBE_ENTRY_RECEIPT_NAME),
                            label="probe-entry receipt",
                        )
                    )
                finally:
                    os.close(entry_fd)
            finally:
                os.close(launch_fd)
    finally:
        os.close(directory_fd)
    start = M2CS4V3ProbeStartCapabilityV1.model_validate(
        _json_object(marker_bytes, label="probe-start receipt")
    )
    binding = M2CS4V3RawAuthorizationBindingV1.model_validate(raw_binding)
    if (
        launch.consumption_receipt_sha256 != claim.receipt_sha256
        or launch.probe_start_receipt_sha256 != start.receipt_sha256
        or launch.consumption_id != claim.consumption_id
        or launch.challenge_nonce != claim.challenge_nonce
        or launch.docker_command_sha256 != start.docker_command_sha256
        or launch.job_root_sha256 != start.job_root_sha256
        or launch.probe_output_root_sha256 != start.probe_output_root_sha256
    ):
        raise CollectionAuthorizationError("probe-launch receipt differs from capability")
    if (
        entry.consumption_receipt_sha256 != claim.receipt_sha256
        or entry.probe_start_receipt_sha256 != start.receipt_sha256
        or entry.consumption_id != claim.consumption_id
        or entry.challenge_nonce != claim.challenge_nonce
        or entry.docker_command_sha256 != start.docker_command_sha256
        or entry.probe_entry_broker_socket_sha256 != start.probe_entry_broker_socket_sha256
        or entry.probe_entry_token_path_sha256 != start.probe_entry_token_path_sha256
        or entry.probe_entry_broker_token_sha256 != start.probe_entry_broker_token_sha256
        or entry.job_root_sha256 != start.job_root_sha256
        or entry.probe_output_root_sha256 != start.probe_output_root_sha256
    ):
        raise CollectionAuthorizationError("probe-entry receipt differs from capability")
    if (
        terminal.status != "COMPLETE"
        or terminal.returncode != 0
        or terminal.raw_probe_sha256 != raw_probe_sha256
        or terminal.console_sha256 != console_sha256
        or terminal.consumption_receipt_sha256 != claim.receipt_sha256
        or terminal.probe_start_receipt_sha256 != start.receipt_sha256
        or terminal.probe_launch_receipt_sha256 != launch.receipt_sha256
        or terminal.probe_entry_receipt_sha256 != entry.receipt_sha256
        or terminal.consumption_id != claim.consumption_id
        or terminal.challenge_nonce != claim.challenge_nonce
        or terminal.docker_command_sha256 != start.docker_command_sha256
        or terminal.job_root_sha256 != canonical_path_sha256(job_root)
        or terminal.probe_output_root_sha256 != canonical_path_sha256(probe_output_root)
        or terminal.job_root_sha256 != start.job_root_sha256
        or terminal.probe_output_root_sha256 != start.probe_output_root_sha256
    ):
        raise CollectionAuthorizationError(
            "probe terminal receipt does not authorize this exact raw output"
        )
    if (
        start.consumption_receipt_sha256 != claim.receipt_sha256
        or start.consumption_id != claim.consumption_id
        or start.challenge_nonce != claim.challenge_nonce
        or start.matched_key != matched_key
        or start.failure_seed != claim.selected_key.failure_seed
        or start.source_sdf_sha256 != claim.source_sdf_sha256
        or start.source_supervision_sha256 != claim.source_supervision_sha256
        or start.source_urdf_sha256 != claim.source_urdf_sha256
        or start.upstream_v4_probe_sha256 != claim.upstream_v4_probe_sha256
        or start.committed_source_snapshot != claim.committed_source_snapshot
        or start.derived_probe_sha256 != claim.derived_probe_sha256
        or start.container_image != claim.container_image
        or start.container_image_id != claim.container_image_id
        or start.role != claim.role
        or start.split != claim.split
        or start.declared_target_attribute != claim.declared_target_attribute
        or start.destination_cell != claim.destination_cell
    ):
        raise CollectionAuthorizationError("probe-start receipt differs from the consumed claim")
    expected = M2CS4V3RawAuthorizationBindingV1(
        schema_version="M2CS4V3RawAuthorizationBindingV1",
        prereg_repository_path=resolved.prereg.repository_relative_path,
        prereg_file_sha256=resolved.file_sha256,
        prereg_sha256=resolved.prereg.prereg_sha256,
        prereg_introduced_commit=resolved.introduced_commit,
        consumption_receipt_sha256=claim.receipt_sha256,
        consumption_id=claim.consumption_id,
        challenge_nonce=claim.challenge_nonce,
        probe_start_receipt_sha256=start.receipt_sha256,
        probe_launch_receipt_sha256=launch.receipt_sha256,
        probe_entry_receipt_sha256=entry.receipt_sha256,
        matched_key=matched_key,
        failure_seed=start.failure_seed,
        source_sdf_sha256=claim.source_sdf_sha256,
        source_supervision_sha256=claim.source_supervision_sha256,
        source_urdf_sha256=claim.source_urdf_sha256,
        upstream_v4_probe_sha256=claim.upstream_v4_probe_sha256,
        committed_source_snapshot=claim.committed_source_snapshot,
        stage_usdc_sha256=start.stage_usdc_sha256,
        stage_metrics_sha256=start.stage_metrics_sha256,
        stage_command_sha256=start.stage_command_sha256,
        derived_probe_sha256=claim.derived_probe_sha256,
        container_image=claim.container_image,
        container_image_id=claim.container_image_id,
        probe_argv_sha256=start.probe_argv_sha256,
        docker_command_sha256=start.docker_command_sha256,
        probe_entry_broker_socket_sha256=start.probe_entry_broker_socket_sha256,
        probe_entry_token_path_sha256=start.probe_entry_token_path_sha256,
        probe_entry_broker_token_sha256=start.probe_entry_broker_token_sha256,
        job_root_sha256=start.job_root_sha256,
        probe_output_root_sha256=start.probe_output_root_sha256,
        role=claim.role,
        split=claim.split,
        declared_target_attribute=claim.declared_target_attribute,
        destination_cell=claim.destination_cell,
        teacher_used=False,
        privileged_truth_policy_input=False,
        model_rollout=False,
        formal_q_b_evaluation=False,
    )
    if binding != expected:
        raise CollectionAuthorizationError("raw probe authorization binding is not exact")
    package_core: dict[str, Any] = {
        "schema_version": "M2CS4V3PackagedAuthorizationBindingV1",
        "prereg_repository_path": resolved.prereg.repository_relative_path,
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": resolved.prereg.prereg_sha256,
        "prereg_introduced_commit": resolved.introduced_commit,
        "matched_key": matched_key,
        "upstream_v4_probe_sha256": claim.upstream_v4_probe_sha256,
        "committed_source_snapshot": claim.committed_source_snapshot.model_dump(mode="json"),
        "consumption_receipt_sha256": claim.receipt_sha256,
        "probe_start_receipt_sha256": start.receipt_sha256,
        "probe_launch_receipt_sha256": launch.receipt_sha256,
        "probe_entry_receipt_sha256": entry.receipt_sha256,
        "probe_terminal_receipt_sha256": terminal.receipt_sha256,
        "raw_authorization_sha256": canonical_sha256(binding.model_dump(mode="json")),
        "raw_probe_sha256": raw_probe_sha256,
        "console_sha256": console_sha256,
        "docker_command_sha256": start.docker_command_sha256,
        "probe_entry_broker_socket_sha256": start.probe_entry_broker_socket_sha256,
        "probe_entry_token_path_sha256": start.probe_entry_token_path_sha256,
        "probe_entry_broker_token_sha256": start.probe_entry_broker_token_sha256,
        "job_root_sha256": start.job_root_sha256,
        "probe_output_root_sha256": start.probe_output_root_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
    }
    packaged_binding = M2CS4V3PackagedAuthorizationBindingV1.model_validate(
        {**package_core, "receipt_sha256": canonical_sha256(package_core)}
    )
    return resolved, claim, packaged_binding
