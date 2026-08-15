"""Create-only Git-tree closure used by the two Phase-2 source bindings.

The active source bindings must precede S4 training, so they cannot depend on
the not-yet-trained Qwen bundle or on a formal Q-B episode.  This module binds
the complete clean implementation Git tree to the already frozen Isaac image.
The later Q-B evidence path still requires its separate complete runtime,
model, scene, and audit asset inventory.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_json_bytes,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once
from xh_agent.policy.qrm_lite.s4_entry_gate import (
    FormalTransitiveImportClosureManifestV1,
)


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/phase2_source_binding_closure_v1.py"
REQUEST_SCHEMA = "M2CPhase2SourceBindingClosureRequestV1"
RECEIPT_SCHEMA = "M2CPhase2SourceBindingClosureReceiptV1"
MANIFEST_NAME = "transitive-import-manifest.json"
RECEIPT_NAME = "source-closure-receipt.json"
SHA1_PATTERN = r"^[0-9a-f]{40}$"
IMAGE_PATTERN = r"^sha256:[0-9a-f]{64}$"


class SourceBindingClosureFailure(RuntimeError):
    """The implementation tree cannot be honestly frozen."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Phase2SourceBindingClosureRequestV1(_FrozenModel):
    schema_version: Literal[REQUEST_SCHEMA] = REQUEST_SCHEMA
    implementation_commit: str = Field(pattern=SHA1_PATTERN)
    repository_tree_sha1: str = Field(pattern=SHA1_PATTERN)
    container_image_digest: str = Field(pattern=IMAGE_PATTERN)
    builder_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/phase2_source_binding_closure_v1.py"
    ] = IMPLEMENTATION_REPO_PATH
    builder_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    complete_git_tree_required: Literal[True] = True
    generated_inside_bound_container: Literal[True] = True
    physical_execution_performed: Literal[False] = False
    training_performed: Literal[False] = False
    q_b_evaluation_performed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    request_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "Phase2SourceBindingClosureRequestV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("Phase-2 source-closure request digest differs")
        return self


class Phase2SourceBindingClosureReceiptV1(_FrozenModel):
    schema_version: Literal[RECEIPT_SCHEMA] = RECEIPT_SCHEMA
    implementation_commit: str = Field(pattern=SHA1_PATTERN)
    repository_tree_sha1: str = Field(pattern=SHA1_PATTERN)
    container_image_digest: str = Field(pattern=IMAGE_PATTERN)
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    tracked_file_count: int = Field(gt=0)
    executable_file_count: int = Field(ge=0)
    git_mode_map_sha256: str = Field(pattern=SHA256_PATTERN)
    transitive_import_manifest_path: Literal[MANIFEST_NAME] = MANIFEST_NAME
    transitive_import_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    complete_git_tree_replayed: Literal[True] = True
    complete_transitive_import_closure: Literal[True] = True
    create_only_publication: Literal[True] = True
    sealed_read_only: Literal[True] = True
    generated_inside_bound_container: Literal[True] = True
    physical_execution_performed: Literal[False] = False
    training_performed: Literal[False] = False
    q_b_evaluation_performed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "Phase2SourceBindingClosureReceiptV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("Phase-2 source-closure receipt digest differs")
        return self


def _git(project_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SourceBindingClosureFailure(f"Git source-closure command failed: {detail}")
    return completed.stdout


def _parse_tree(data: bytes) -> tuple[dict[str, str], dict[str, str]]:
    sha_by_path: dict[str, str] = {}
    mode_by_path: dict[str, str] = {}
    for record in data.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, _git_object = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise SourceBindingClosureFailure("Git tree record is malformed") from exc
        if (
            kind != "blob"
            or mode not in {"100644", "100755"}
            or not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or path in sha_by_path
        ):
            raise SourceBindingClosureFailure("Git tree contains a non-regular source entry")
        sha_by_path[path] = ""
        mode_by_path[path] = mode
    if not sha_by_path:
        raise SourceBindingClosureFailure("Git source tree is empty")
    return sha_by_path, mode_by_path


def _read_complete_tree(
    project_root: Path,
    request: Phase2SourceBindingClosureRequestV1,
) -> tuple[dict[str, str], dict[str, str]]:
    head = _git(project_root, "rev-parse", "HEAD").decode("ascii").strip()
    tree = (
        _git(project_root, "rev-parse", f"{request.implementation_commit}^{{tree}}")
        .decode("ascii")
        .strip()
    )
    if head != request.implementation_commit or tree != request.repository_tree_sha1:
        raise SourceBindingClosureFailure("source-closure HEAD/tree differs from request")
    dirty = _git(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=matching",
    )
    if dirty:
        raise SourceBindingClosureFailure(
            "source-closure project contains dirty/untracked/ignored files"
        )
    sha_by_path, mode_by_path = _parse_tree(
        _git(
            project_root,
            "ls-tree",
            "-r",
            "-z",
            request.implementation_commit,
        )
    )
    root = project_root.resolve(strict=True)
    for relative in sorted(sha_by_path):
        unresolved = project_root / relative
        cursor = project_root
        for part in Path(relative).parts:
            cursor /= part
            if cursor.is_symlink():
                raise SourceBindingClosureFailure(
                    f"source-closure path contains a symlink: {relative}"
                )
        path = unresolved.resolve(strict=True)
        if not path.is_relative_to(root):
            raise SourceBindingClosureFailure(f"source-closure path escapes repository: {relative}")
        raw = read_regular_file_once(path)
        committed = _git(project_root, "show", f"{request.implementation_commit}:{relative}")
        if raw != committed:
            raise SourceBindingClosureFailure(
                f"source-closure worktree bytes differ from commit: {relative}"
            )
        actual_mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        executable = bool(actual_mode & 0o111)
        if executable != (mode_by_path[relative] == "100755"):
            raise SourceBindingClosureFailure(
                f"source-closure executable mode differs from Git: {relative}"
            )
        sha_by_path[relative] = hashlib.sha256(raw).hexdigest()
    return sha_by_path, mode_by_path


def _write_create_only(path: Path, data: bytes, *, mode: int = 0o400) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SourceBindingClosureFailure("source-closure write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _directory_fsync(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build_phase2_source_binding_closure_v1(
    *,
    project_root: Path,
    request: Phase2SourceBindingClosureRequestV1,
    output_root: Path,
) -> Phase2SourceBindingClosureReceiptV1:
    """Freeze a complete implementation tree without touching Isaac or Qwen."""

    project_root = project_root.resolve(strict=True)
    request = Phase2SourceBindingClosureRequestV1.model_validate(request)
    builder_path = project_root / request.builder_implementation_path
    if hashlib.sha256(read_regular_file_once(builder_path)).hexdigest() != (
        request.builder_implementation_sha256
    ):
        raise SourceBindingClosureFailure("source-closure builder bytes differ")
    files, modes = _read_complete_tree(project_root, request)
    if files.get(request.builder_implementation_path) != request.builder_implementation_sha256:
        raise SourceBindingClosureFailure("source-closure builder is absent from frozen tree")
    manifest = FormalTransitiveImportClosureManifestV1(
        implementation_commit=request.implementation_commit,
        container_image_digest=request.container_image_digest,
        files=files,
        complete_transitive_import_closure=True,
        generated_inside_bound_container=True,
        teacher_used=False,
    )
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    receipt_payload = {
        "schema_version": RECEIPT_SCHEMA,
        "implementation_commit": request.implementation_commit,
        "repository_tree_sha1": request.repository_tree_sha1,
        "container_image_digest": request.container_image_digest,
        "request_sha256": request.request_sha256,
        "tracked_file_count": len(files),
        "executable_file_count": sum(mode == "100755" for mode in modes.values()),
        "git_mode_map_sha256": canonical_sha256(modes),
        "transitive_import_manifest_path": MANIFEST_NAME,
        "transitive_import_manifest_sha256": manifest_sha256,
        "complete_git_tree_replayed": True,
        "complete_transitive_import_closure": True,
        "create_only_publication": True,
        "sealed_read_only": True,
        "generated_inside_bound_container": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    receipt = Phase2SourceBindingClosureReceiptV1(
        **receipt_payload,
        receipt_sha256=canonical_sha256(receipt_payload),
    )
    receipt_bytes = canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n"
    output_root = output_root.absolute()
    os.mkdir(output_root, 0o700)
    try:
        _write_create_only(output_root / MANIFEST_NAME, manifest_bytes)
        _write_create_only(output_root / RECEIPT_NAME, receipt_bytes)
        _directory_fsync(output_root)
        os.chmod(output_root, 0o500)
        _directory_fsync(output_root.parent)
    except BaseException:
        # Create-only partials remain visible and cannot be mistaken for a
        # successful receipt because replay requires both exact files.
        raise
    return receipt


def replay_phase2_source_binding_closure_v1(
    *,
    project_root: Path,
    request: Phase2SourceBindingClosureRequestV1,
    output_root: Path,
) -> Phase2SourceBindingClosureReceiptV1:
    """Replay the published bytes against the same clean implementation tree."""

    project_root = project_root.resolve(strict=True)
    request = Phase2SourceBindingClosureRequestV1.model_validate(request)
    files, modes = _read_complete_tree(project_root, request)
    manifest_bytes = read_regular_file_once(output_root / MANIFEST_NAME)
    receipt_bytes = read_regular_file_once(output_root / RECEIPT_NAME)
    manifest = FormalTransitiveImportClosureManifestV1.model_validate_json(manifest_bytes)
    receipt = Phase2SourceBindingClosureReceiptV1.model_validate_json(receipt_bytes)
    if (
        manifest.implementation_commit != request.implementation_commit
        or manifest.container_image_digest != request.container_image_digest
        or manifest.files != files
        or receipt.implementation_commit != request.implementation_commit
        or receipt.repository_tree_sha1 != request.repository_tree_sha1
        or receipt.container_image_digest != request.container_image_digest
        or receipt.request_sha256 != request.request_sha256
        or receipt.tracked_file_count != len(files)
        or receipt.executable_file_count != sum(mode == "100755" for mode in modes.values())
        or receipt.git_mode_map_sha256 != canonical_sha256(modes)
        or receipt.transitive_import_manifest_sha256 != hashlib.sha256(manifest_bytes).hexdigest()
        or stat.S_IMODE(output_root.stat(follow_symlinks=False).st_mode) & 0o222
        or stat.S_IMODE((output_root / MANIFEST_NAME).stat().st_mode) & 0o222
        or stat.S_IMODE((output_root / RECEIPT_NAME).stat().st_mode) & 0o222
    ):
        raise SourceBindingClosureFailure("published source closure differs on replay")
    return receipt


def load_source_closure_request_v1(
    path: Path,
    *,
    expected_file_sha256: str | None = None,
) -> Phase2SourceBindingClosureRequestV1:
    raw = read_regular_file_once(path)
    if expected_file_sha256 is not None and hashlib.sha256(raw).hexdigest() != (
        expected_file_sha256
    ):
        raise SourceBindingClosureFailure("source-closure request file SHA-256 differs")
    try:
        return Phase2SourceBindingClosureRequestV1.model_validate_json(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceBindingClosureFailure("source-closure request is invalid") from exc
