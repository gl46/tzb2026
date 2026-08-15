from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.phase2_source_binding_closure_v1 import (
    IMPLEMENTATION_REPO_PATH,
    MANIFEST_NAME,
    Phase2SourceBindingClosureRequestV1,
    SourceBindingClosureFailure,
    build_phase2_source_binding_closure_v1,
    load_source_closure_request_v1,
    replay_phase2_source_binding_closure_v1,
)


ROOT = Path(__file__).parents[2]
IMAGE = "sha256:" + "7" * 64


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(
    tmp_path: Path,
) -> tuple[Path, Phase2SourceBindingClosureRequestV1]:
    repo = tmp_path / "repo"
    repo.mkdir()
    builder = repo / IMPLEMENTATION_REPO_PATH
    builder.parent.mkdir(parents=True)
    builder.write_bytes((ROOT / IMPLEMENTATION_REPO_PATH).read_bytes())
    runtime = repo / "src" / "runtime.py"
    runtime.write_text("VALUE = 1\n", encoding="utf-8")
    runner = repo / "scripts" / "runner.sh"
    runner.parent.mkdir(parents=True)
    runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "M2C Source Closure")
    _git(repo, "config", "user.email", "m2c-source-closure@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "freeze source closure fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    payload = {
        "schema_version": "M2CPhase2SourceBindingClosureRequestV1",
        "implementation_commit": commit,
        "repository_tree_sha1": tree,
        "container_image_digest": IMAGE,
        "builder_implementation_path": IMPLEMENTATION_REPO_PATH,
        "builder_implementation_sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
        "complete_git_tree_required": True,
        "generated_inside_bound_container": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    request = Phase2SourceBindingClosureRequestV1(
        **payload,
        request_sha256=canonical_sha256(payload),
    )
    return repo, request


def test_build_and_replay_complete_source_tree(tmp_path: Path) -> None:
    repo, request = _fixture(tmp_path)
    output = tmp_path / "closure"
    receipt = build_phase2_source_binding_closure_v1(
        project_root=repo,
        request=request,
        output_root=output,
    )
    assert receipt.tracked_file_count == 3
    assert receipt.executable_file_count == 1
    assert receipt.complete_git_tree_replayed
    assert receipt.complete_transitive_import_closure
    assert receipt.generated_inside_bound_container
    assert not receipt.physical_execution_performed
    assert not receipt.training_performed
    assert not receipt.q_b_evaluation_performed
    assert not os.stat(output).st_mode & 0o222
    assert (
        replay_phase2_source_binding_closure_v1(
            project_root=repo,
            request=request,
            output_root=output,
        )
        == receipt
    )


def test_dirty_or_ignored_tree_rejected_before_publication(tmp_path: Path) -> None:
    repo, request = _fixture(tmp_path)
    (repo / ".gitignore").write_text("shadow.pyc\n", encoding="utf-8")
    (repo / "shadow.pyc").write_bytes(b"unchecked")
    output = tmp_path / "closure"
    with pytest.raises(SourceBindingClosureFailure, match="dirty/untracked/ignored"):
        build_phase2_source_binding_closure_v1(
            project_root=repo,
            request=request,
            output_root=output,
        )
    assert not output.exists()


def test_tracked_symlink_is_rejected(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path)
    link = repo / "src" / "runtime-link.py"
    link.symlink_to("runtime.py")
    _git(repo, "add", "src/runtime-link.py")
    _git(repo, "commit", "-q", "-m", "add forbidden symlink")
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    builder = repo / IMPLEMENTATION_REPO_PATH
    payload = {
        "schema_version": "M2CPhase2SourceBindingClosureRequestV1",
        "implementation_commit": commit,
        "repository_tree_sha1": tree,
        "container_image_digest": IMAGE,
        "builder_implementation_path": IMPLEMENTATION_REPO_PATH,
        "builder_implementation_sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
        "complete_git_tree_required": True,
        "generated_inside_bound_container": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    request = Phase2SourceBindingClosureRequestV1(
        **payload,
        request_sha256=canonical_sha256(payload),
    )
    with pytest.raises(SourceBindingClosureFailure, match="non-regular"):
        build_phase2_source_binding_closure_v1(
            project_root=repo,
            request=request,
            output_root=tmp_path / "closure",
        )


def test_descendant_head_is_not_the_implementation_snapshot(tmp_path: Path) -> None:
    repo, request = _fixture(tmp_path)
    extra = repo / "binding-only.json"
    extra.write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "binding-only.json")
    _git(repo, "commit", "-q", "-m", "advance head")
    with pytest.raises(SourceBindingClosureFailure, match="HEAD/tree"):
        build_phase2_source_binding_closure_v1(
            project_root=repo,
            request=request,
            output_root=tmp_path / "closure",
        )


def test_tampered_publication_and_request_fail_closed(tmp_path: Path) -> None:
    repo, request = _fixture(tmp_path)
    output = tmp_path / "closure"
    build_phase2_source_binding_closure_v1(
        project_root=repo,
        request=request,
        output_root=output,
    )
    manifest = output / MANIFEST_NAME
    output.chmod(0o700)
    manifest.chmod(0o600)
    manifest.write_bytes(b"{}\n")
    with pytest.raises((SourceBindingClosureFailure, ValueError)):
        replay_phase2_source_binding_closure_v1(
            project_root=repo,
            request=request,
            output_root=output,
        )

    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(SourceBindingClosureFailure, match="file SHA-256"):
        load_source_closure_request_v1(
            request_path,
            expected_file_sha256="0" * 64,
        )
