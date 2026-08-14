"""Create-only Phase-2 Git-tree and deployment-asset closure.

The Phase-2 readiness verifier consumes two manifests: one covering the
complete repository import surface and one covering every byte mounted from
outside the bound container image.  This module produces those manifests from
an exact clean Git commit and a reviewed asset inventory.  It intentionally
does not produce formal/physical evidence and cannot apply an entry binding.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_json_bytes,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.phase2_binding_readiness_v2 import (
    DeploymentAssetBindingV2,
    Phase2DeploymentAssetManifestV2,
)
from xh_agent.policy.qrm_lite.s4_entry_gate import (
    FormalTransitiveImportClosureManifestV1,
)


SCHEMA_VERSION = "M2CPhase2DeploymentClosureBuildRequestV2"
RECEIPT_SCHEMA_VERSION = "M2CPhase2DeploymentClosureBuildReceiptV2"
TRANSITIVE_MANIFEST_NAME = "transitive-import-manifest.json"
ASSET_MANIFEST_NAME = "deployment-asset-manifest.json"
RECEIPT_NAME = "closure-build-receipt.json"
SHA1_PATTERN = r"^[0-9a-f]{40}$"
IMAGE_PATTERN = r"^sha256:[0-9a-f]{64}$"
SAFE_BASENAME = re.compile(r"[^A-Za-z0-9._-]+")


class DeploymentClosureFailure(RuntimeError):
    """A Git, filesystem, or asset-closure invariant failed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Phase2DeploymentAssetSourceV2(_FrozenModel):
    deployment_path: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    kind: Literal[
        "ROBOT_ASSET",
        "SCENE_ASSET",
        "ISAAC_RUNTIME",
        "NATIVE_RUNTIME",
        "CONFIGURATION",
    ]

    @model_validator(mode="after")
    def paths_are_unambiguous(self) -> "Phase2DeploymentAssetSourceV2":
        deployment = PurePosixPath(self.deployment_path)
        if not deployment.is_absolute() or ".." in deployment.parts:
            raise ValueError("deployment asset path must be an absolute POSIX path")
        source = Path(self.source_path)
        if ".." in source.parts:
            raise ValueError("deployment asset source may not contain '..'")
        return self


class Phase2DeploymentClosureBuildRequestV2(_FrozenModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    implementation_commit: str = Field(pattern=SHA1_PATTERN)
    repository_tree_sha1: str = Field(pattern=SHA1_PATTERN)
    container_image_digest: str = Field(pattern=IMAGE_PATTERN)
    assets: tuple[Phase2DeploymentAssetSourceV2, ...] = Field(min_length=1)
    complete_runtime_and_asset_closure: Literal[True] = True
    content_addressed_immutable_snapshot: Literal[True] = True
    generated_inside_bound_container: Literal[True] = True
    physical_execution_performed: Literal[False] = False
    training_performed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    request_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_sets_and_digest(self) -> "Phase2DeploymentClosureBuildRequestV2":
        deployment_paths = tuple(item.deployment_path for item in self.assets)
        source_paths = tuple(item.source_path for item in self.assets)
        if len(deployment_paths) != len(set(deployment_paths)):
            raise ValueError("deployment asset paths are duplicated")
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("deployment asset sources are duplicated")
        payload = self.model_dump(mode="json", exclude={"request_sha256"})
        if self.request_sha256 != canonical_sha256(payload):
            raise ValueError("deployment closure request digest differs")
        return self


class Phase2DeploymentClosureBuildReceiptV2(_FrozenModel):
    schema_version: Literal[RECEIPT_SCHEMA_VERSION] = RECEIPT_SCHEMA_VERSION
    implementation_commit: str = Field(pattern=SHA1_PATTERN)
    repository_tree_sha1: str = Field(pattern=SHA1_PATTERN)
    container_image_digest: str = Field(pattern=IMAGE_PATTERN)
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    tracked_file_count: int = Field(gt=0)
    executable_file_count: int = Field(ge=0)
    git_mode_map_sha256: str = Field(pattern=SHA256_PATTERN)
    transitive_import_manifest_path: Literal[TRANSITIVE_MANIFEST_NAME] = TRANSITIVE_MANIFEST_NAME
    transitive_import_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    deployment_asset_manifest_path: Literal[ASSET_MANIFEST_NAME] = ASSET_MANIFEST_NAME
    deployment_asset_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    asset_file_count: int = Field(gt=0)
    asset_binding_set_sha256: str = Field(pattern=SHA256_PATTERN)
    complete_git_tree_replayed: Literal[True] = True
    complete_runtime_and_asset_closure: Literal[True] = True
    create_only_publication: Literal[True] = True
    sealed_read_only: Literal[True] = True
    physical_execution_performed: Literal[False] = False
    training_performed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical_digest(self) -> "Phase2DeploymentClosureBuildReceiptV2":
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(payload):
            raise ValueError("deployment closure receipt digest differs")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise DeploymentClosureFailure(f"closure input is not one regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda item: (  # noqa: E731
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise DeploymentClosureFailure(f"closure input changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _run_git(project_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise DeploymentClosureFailure(f"Git closure command failed: {detail}")
    return completed.stdout


def _require_no_symlink_components(path: Path) -> Path:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise DeploymentClosureFailure(f"closure input contains a symlink: {path}")
    return absolute.resolve(strict=True)


def _clean_git_tree(
    project_root: Path,
    request: Phase2DeploymentClosureBuildRequestV2,
) -> tuple[dict[str, str], dict[str, str]]:
    head = _run_git(project_root, "rev-parse", "HEAD").decode("ascii").strip()
    tree = (
        _run_git(
            project_root,
            "rev-parse",
            f"{request.implementation_commit}^{{tree}}",
        )
        .decode("ascii")
        .strip()
    )
    if head != request.implementation_commit or tree != request.repository_tree_sha1:
        raise DeploymentClosureFailure("closure project HEAD/tree differs from request")
    dirty = _run_git(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=matching",
    )
    if dirty:
        raise DeploymentClosureFailure("closure project contains dirty/untracked/ignored files")
    raw = _run_git(
        project_root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        request.implementation_commit,
    )
    files: dict[str, str] = {}
    modes: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, encoded_path = entry.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
            relative_path = encoded_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise DeploymentClosureFailure("Git tree entry is malformed") from error
        relative = PurePosixPath(relative_path)
        if (
            kind != "blob"
            or mode not in {"100644", "100755"}
            or relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
        ):
            raise DeploymentClosureFailure("Git tree contains an unsupported entry")
        worktree_path = project_root.joinpath(*relative.parts)
        if worktree_path.is_symlink():
            raise DeploymentClosureFailure("Git closure worktree contains a symlink")
        worktree_bytes = _read_regular_file_once(worktree_path)
        committed_bytes = _run_git(project_root, "cat-file", "blob", object_id)
        if worktree_bytes != committed_bytes:
            raise DeploymentClosureFailure(f"Git closure byte drift: {relative_path}")
        files[relative_path] = sha256_bytes(worktree_bytes)
        modes[relative_path] = mode
    if not files:
        raise DeploymentClosureFailure("Git closure is empty")
    return files, modes


def _resolve_asset_source(project_root: Path, raw_path: str) -> Path:
    source = Path(raw_path)
    candidate = source if source.is_absolute() else project_root / source
    return _require_no_symlink_components(candidate)


def _safe_asset_name(index: int, source: Path, digest: str) -> str:
    basename = SAFE_BASENAME.sub("_", source.name).strip("._-") or "asset"
    return f"assets/{index:04d}-{digest}-{basename}"


def _write_create_only(path: Path, data: bytes, *, mode: int = 0o444) -> None:
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
                raise DeploymentClosureFailure(f"short write publishing closure: {path}")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_file_bytes(model: BaseModel) -> bytes:
    return canonical_json_bytes(model.model_dump(mode="json")) + b"\n"


def build_phase2_deployment_closure_v2(
    *,
    project_root: Path,
    request: Phase2DeploymentClosureBuildRequestV2,
    output_root: Path,
) -> Phase2DeploymentClosureBuildReceiptV2:
    """Build one sealed create-only closure; never delete an incomplete root."""

    project_root = _require_no_symlink_components(project_root)
    files, modes = _clean_git_tree(project_root, request)
    parent = _require_no_symlink_components(output_root.parent)
    parent_stat = parent.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.geteuid()
        or stat.S_IMODE(parent_stat.st_mode) & 0o022
    ):
        raise DeploymentClosureFailure("closure output parent is not a private owned directory")
    output_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    assets_root = output_root / "assets"
    assets_root.mkdir(mode=0o700, parents=False, exist_ok=False)

    asset_bindings: list[DeploymentAssetBindingV2] = []
    for index, source in enumerate(request.assets):
        source_path = _resolve_asset_source(project_root, source.source_path)
        payload = _read_regular_file_once(source_path)
        actual = sha256_bytes(payload)
        if actual != source.sha256:
            raise DeploymentClosureFailure(
                f"deployment asset digest differs: {source.deployment_path}"
            )
        evidence_path = _safe_asset_name(index, source_path, actual)
        destination = output_root / evidence_path
        _write_create_only(destination, payload)
        asset_bindings.append(
            DeploymentAssetBindingV2(
                deployment_path=source.deployment_path,
                evidence_path=evidence_path,
                sha256=actual,
                kind=source.kind,
            )
        )

    transitive = FormalTransitiveImportClosureManifestV1(
        implementation_commit=request.implementation_commit,
        container_image_digest=request.container_image_digest,
        files=files,
        complete_transitive_import_closure=True,
        generated_inside_bound_container=True,
        teacher_used=False,
    )
    assets = Phase2DeploymentAssetManifestV2(
        implementation_commit=request.implementation_commit,
        container_image_digest=request.container_image_digest,
        bindings=tuple(asset_bindings),
        complete_runtime_and_asset_closure=True,
        content_addressed_immutable_snapshot=True,
        generated_inside_bound_container=True,
        teacher_used=False,
        privileged_truth_policy_input=False,
    )
    transitive_bytes = _canonical_file_bytes(transitive)
    asset_bytes = _canonical_file_bytes(assets)
    _write_create_only(output_root / TRANSITIVE_MANIFEST_NAME, transitive_bytes)
    _write_create_only(output_root / ASSET_MANIFEST_NAME, asset_bytes)

    receipt_payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "implementation_commit": request.implementation_commit,
        "repository_tree_sha1": request.repository_tree_sha1,
        "container_image_digest": request.container_image_digest,
        "request_sha256": request.request_sha256,
        "tracked_file_count": len(files),
        "executable_file_count": sum(mode == "100755" for mode in modes.values()),
        "git_mode_map_sha256": canonical_sha256(modes),
        "transitive_import_manifest_path": TRANSITIVE_MANIFEST_NAME,
        "transitive_import_manifest_sha256": sha256_bytes(transitive_bytes),
        "deployment_asset_manifest_path": ASSET_MANIFEST_NAME,
        "deployment_asset_manifest_sha256": sha256_bytes(asset_bytes),
        "asset_file_count": len(asset_bindings),
        "asset_binding_set_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in asset_bindings]
        ),
        "complete_git_tree_replayed": True,
        "complete_runtime_and_asset_closure": True,
        "create_only_publication": True,
        "sealed_read_only": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    receipt = Phase2DeploymentClosureBuildReceiptV2(
        **receipt_payload,
        receipt_sha256=canonical_sha256(receipt_payload),
    )
    _write_create_only(output_root / RECEIPT_NAME, _canonical_file_bytes(receipt))
    os.chmod(assets_root, 0o555)
    os.chmod(output_root, 0o555)
    descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return receipt


def replay_phase2_deployment_closure_v2(
    *,
    project_root: Path,
    request: Phase2DeploymentClosureBuildRequestV2,
    output_root: Path,
) -> Phase2DeploymentClosureBuildReceiptV2:
    """Recompute the Git tree and every published asset binding."""

    project_root = _require_no_symlink_components(project_root)
    output_root = _require_no_symlink_components(output_root)
    files, modes = _clean_git_tree(project_root, request)
    receipt_raw = _read_regular_file_once(output_root / RECEIPT_NAME)
    transitive_raw = _read_regular_file_once(output_root / TRANSITIVE_MANIFEST_NAME)
    assets_raw = _read_regular_file_once(output_root / ASSET_MANIFEST_NAME)
    try:
        receipt = Phase2DeploymentClosureBuildReceiptV2.model_validate_json(receipt_raw)
        transitive = FormalTransitiveImportClosureManifestV1.model_validate_json(transitive_raw)
        assets = Phase2DeploymentAssetManifestV2.model_validate_json(assets_raw)
    except (ValueError, json.JSONDecodeError) as error:
        raise DeploymentClosureFailure("deployment closure JSON is invalid") from error
    if (
        receipt.implementation_commit != request.implementation_commit
        or receipt.repository_tree_sha1 != request.repository_tree_sha1
        or receipt.container_image_digest != request.container_image_digest
        or receipt.request_sha256 != request.request_sha256
        or receipt.tracked_file_count != len(files)
        or receipt.executable_file_count != sum(mode == "100755" for mode in modes.values())
        or receipt.git_mode_map_sha256 != canonical_sha256(modes)
        or receipt.transitive_import_manifest_sha256 != sha256_bytes(transitive_raw)
        or receipt.deployment_asset_manifest_sha256 != sha256_bytes(assets_raw)
        or transitive.implementation_commit != request.implementation_commit
        or transitive.container_image_digest != request.container_image_digest
        or transitive.files != files
        or assets.implementation_commit != request.implementation_commit
        or assets.container_image_digest != request.container_image_digest
    ):
        raise DeploymentClosureFailure("deployment closure receipt/manifests differ")
    source_by_deployment = {item.deployment_path: item for item in request.assets}
    if set(source_by_deployment) != {item.deployment_path for item in assets.bindings}:
        raise DeploymentClosureFailure("deployment closure asset set differs")
    for binding in assets.bindings:
        source = source_by_deployment[binding.deployment_path]
        if binding.sha256 != source.sha256 or binding.kind != source.kind:
            raise DeploymentClosureFailure("deployment closure asset binding differs")
        evidence = output_root / binding.evidence_path
        evidence_stat = evidence.stat(follow_symlinks=False)
        if (
            evidence.is_symlink()
            or evidence_stat.st_uid != os.geteuid()
            or stat.S_IMODE(evidence_stat.st_mode) & 0o222
            or sha256_bytes(_read_regular_file_once(evidence)) != binding.sha256
        ):
            raise DeploymentClosureFailure("deployment closure asset evidence differs")
    if receipt.asset_file_count != len(
        assets.bindings
    ) or receipt.asset_binding_set_sha256 != canonical_sha256(
        [item.model_dump(mode="json") for item in assets.bindings]
    ):
        raise DeploymentClosureFailure("deployment closure asset aggregate differs")
    for path in (
        output_root,
        output_root / "assets",
        output_root / RECEIPT_NAME,
        output_root / TRANSITIVE_MANIFEST_NAME,
        output_root / ASSET_MANIFEST_NAME,
    ):
        metadata = path.stat(follow_symlinks=False)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o222:
            raise DeploymentClosureFailure("deployment closure path is writable or foreign")
    return receipt


def load_build_request_v2(
    path: Path,
    *,
    expected_file_sha256: str | None = None,
) -> Phase2DeploymentClosureBuildRequestV2:
    raw = _read_regular_file_once(path)
    if expected_file_sha256 is not None and sha256_bytes(raw) != expected_file_sha256:
        raise DeploymentClosureFailure("deployment closure request file SHA-256 differs")
    return Phase2DeploymentClosureBuildRequestV2.model_validate_json(raw)
