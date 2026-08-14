from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import pytest

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.phase2_deployment_closure_v2 import (
    ASSET_MANIFEST_NAME,
    DeploymentClosureFailure,
    Phase2DeploymentAssetSourceV2,
    Phase2DeploymentClosureBuildRequestV2,
    build_phase2_deployment_closure_v2,
    load_build_request_v2,
    replay_phase2_deployment_closure_v2,
)
from xh_agent.policy.qrm_lite.phase2_binding_readiness_v2 import (
    DEPLOYMENT_ASSET_SINGLETON_ROLES_V3,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_json_bytes


IMAGE = "sha256:" + "1" * 64


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Phase2DeploymentClosureBuildRequestV2]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "closure@example.invalid")
    _git(repo, "config", "user.name", "Phase2 Closure Test")
    (repo / "src").mkdir()
    (repo / "src" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    executable = repo / "runner.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    _git(repo, "add", "src/runtime.py", "runner.sh")
    _git(repo, "commit", "-qm", "frozen closure")
    commit = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    bundle_root = "/opt/m2c/qwen/bundle"
    adapter_root = f"{bundle_root}/adapter"
    model_cache_root = "/opt/m2c/qwen/model-cache"
    isaac_root = "/opt/m2c/isaac-assets"
    path_by_role = {
        "QWEN_BUNDLE_MANIFEST": f"{bundle_root}/qwen_coarse_v4_bundle.json",
        "QWEN_HEAD_CHECKPOINT": f"{bundle_root}/qwen_coarse_v4_heads.npz",
        "QWEN_HEAD_DEPLOYMENT": (f"{bundle_root}/qwen_coarse_v4_checkpoint_deployment.json"),
    }
    assets: list[dict[str, object]] = []
    first_asset: Path | None = None
    for index, role in enumerate(sorted(DEPLOYMENT_ASSET_SINGLETON_ROLES_V3)):
        asset = tmp_path / f"asset-{index:02d}-{role.lower()}.bin"
        asset.write_bytes(f"fixture:{role}\n".encode())
        if first_asset is None:
            first_asset = asset
        roles = [role]
        if role in {"QWEN_BUNDLE_MANIFEST", "QWEN_HEAD_CHECKPOINT", "QWEN_HEAD_DEPLOYMENT"}:
            roles.append("QWEN_BUNDLE_FILE")
        assets.append(
            {
                "deployment_path": path_by_role.get(
                    role,
                    f"/opt/m2c/singletons/{role.lower()}.bin",
                ),
                "source_path": str(asset),
                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "roles": sorted(roles),
                "kind": "CONFIGURATION",
            }
        )
    tree_members = (
        ("QWEN_ADAPTER_FILE", f"{adapter_root}/adapter_model.safetensors"),
        ("QWEN_MODEL_CACHE_FILE", f"{model_cache_root}/model.safetensors"),
        ("ISAAC_DEPENDENCY_FILE", f"{isaac_root}/scene.usd"),
    )
    for offset, (role, deployment_path) in enumerate(tree_members, start=len(assets)):
        asset = tmp_path / f"asset-{offset:02d}-{role.lower()}.bin"
        asset.write_bytes(f"fixture:{role}\n".encode())
        roles = [role]
        if role == "QWEN_ADAPTER_FILE":
            roles.append("QWEN_BUNDLE_FILE")
        assets.append(
            {
                "deployment_path": deployment_path,
                "source_path": str(asset),
                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                "roles": sorted(roles),
                "kind": "CONFIGURATION",
            }
        )
    assert first_asset is not None
    payload = {
        "schema_version": "M2CPhase2DeploymentClosureBuildRequestV2",
        "implementation_commit": commit,
        "repository_tree_sha1": tree,
        "container_image_digest": IMAGE,
        "assets": assets,
        "tree_roots": {
            "QWEN_BUNDLE_TREE": bundle_root,
            "QWEN_ADAPTER_TREE": adapter_root,
            "QWEN_MODEL_CACHE_TREE": model_cache_root,
            "ISAAC_DEPENDENCY_TREE": isaac_root,
        },
        "complete_runtime_and_asset_closure": True,
        "content_addressed_immutable_snapshot": True,
        "generated_inside_bound_container": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    request = Phase2DeploymentClosureBuildRequestV2(
        **payload,
        request_sha256=canonical_sha256(payload),
    )
    return repo, first_asset, request


def test_build_and_replay_complete_git_and_asset_closure(tmp_path: Path) -> None:
    repo, _, request = _fixture(tmp_path)
    output = tmp_path / "closure"
    receipt = build_phase2_deployment_closure_v2(
        project_root=repo,
        request=request,
        output_root=output,
    )
    assert receipt.tracked_file_count == 2
    assert receipt.executable_file_count == 1
    assert receipt.asset_file_count == len(request.assets)
    assert receipt.complete_git_tree_replayed
    assert not receipt.physical_execution_performed
    assert not receipt.training_performed
    assert not receipt.teacher_used
    assert not receipt.privileged_truth_policy_input
    replayed = replay_phase2_deployment_closure_v2(
        project_root=repo,
        request=request,
        output_root=output,
    )
    assert replayed == receipt
    assert not os.stat(output).st_mode & 0o222
    assert not os.stat(output / "assets").st_mode & 0o222


def test_dirty_untracked_or_ignored_repo_rejected_before_publication(tmp_path: Path) -> None:
    repo, _, request = _fixture(tmp_path)
    (repo / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
    (repo / "ignored.bin").write_bytes(b"shadow")
    output = tmp_path / "closure"
    with pytest.raises(DeploymentClosureFailure, match="dirty/untracked/ignored"):
        build_phase2_deployment_closure_v2(
            project_root=repo,
            request=request,
            output_root=output,
        )
    assert not output.exists()


def test_symlink_asset_source_is_rejected(tmp_path: Path) -> None:
    repo, asset, request = _fixture(tmp_path)
    link = tmp_path / "linked.so"
    link.symlink_to(asset)
    source = Phase2DeploymentAssetSourceV2(
        deployment_path=request.assets[0].deployment_path,
        source_path=str(link),
        sha256=request.assets[0].sha256,
        roles=request.assets[0].roles,
        kind=request.assets[0].kind,
    )
    payload = request.model_dump(mode="json", exclude={"request_sha256", "assets"})
    payload["assets"] = [
        source.model_dump(mode="json"),
        *[item.model_dump(mode="json") for item in request.assets[1:]],
    ]
    linked_request = Phase2DeploymentClosureBuildRequestV2(
        **payload,
        request_sha256=canonical_sha256(payload),
    )
    with pytest.raises(DeploymentClosureFailure, match="symlink"):
        build_phase2_deployment_closure_v2(
            project_root=repo,
            request=linked_request,
            output_root=tmp_path / "closure",
        )


def test_tampered_published_asset_fails_replay(tmp_path: Path) -> None:
    repo, _, request = _fixture(tmp_path)
    output = tmp_path / "closure"
    build_phase2_deployment_closure_v2(
        project_root=repo,
        request=request,
        output_root=output,
    )
    asset_manifest = (output / ASSET_MANIFEST_NAME).read_text(encoding="utf-8")
    evidence_name = asset_manifest.split('"evidence_path":"', 1)[1].split('"', 1)[0]
    evidence = output / evidence_name
    evidence.chmod(0o600)
    evidence.write_bytes(b"tampered")
    with pytest.raises(DeploymentClosureFailure, match="asset evidence"):
        replay_phase2_deployment_closure_v2(
            project_root=repo,
            request=request,
            output_root=output,
        )


def test_wrong_tree_and_reused_output_fail_closed(tmp_path: Path) -> None:
    repo, _, request = _fixture(tmp_path)
    payload = request.model_dump(mode="json", exclude={"request_sha256"})
    payload["repository_tree_sha1"] = "f" * 40
    wrong = Phase2DeploymentClosureBuildRequestV2(
        **payload,
        request_sha256=canonical_sha256(payload),
    )
    with pytest.raises(DeploymentClosureFailure, match="HEAD/tree"):
        build_phase2_deployment_closure_v2(
            project_root=repo,
            request=wrong,
            output_root=tmp_path / "wrong",
        )
    output = tmp_path / "closure"
    build_phase2_deployment_closure_v2(
        project_root=repo,
        request=request,
        output_root=output,
    )
    with pytest.raises(FileExistsError):
        build_phase2_deployment_closure_v2(
            project_root=repo,
            request=request,
            output_root=output,
        )


def test_request_file_hash_and_single_inode_are_checked_on_same_read(tmp_path: Path) -> None:
    _, _, request = _fixture(tmp_path)
    raw = canonical_json_bytes(request.model_dump(mode="json")) + b"\n"
    path = tmp_path / "request.json"
    path.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()

    assert load_build_request_v2(path, expected_file_sha256=expected) == request
    with pytest.raises(DeploymentClosureFailure, match="request file SHA-256"):
        load_build_request_v2(path, expected_file_sha256="0" * 64)

    alias = tmp_path / "request-alias.json"
    alias.hardlink_to(path)
    with pytest.raises(DeploymentClosureFailure, match="one regular file"):
        load_build_request_v2(path, expected_file_sha256=expected)


def test_partial_or_self_aliased_asset_profile_is_rejected(tmp_path: Path) -> None:
    _, _, request = _fixture(tmp_path)
    missing_payload = request.model_dump(mode="json", exclude={"request_sha256"})
    missing_payload["assets"] = [
        item.model_dump(mode="json")
        for item in request.assets
        if "FORMAL_CHALLENGE_MANIFEST" not in item.roles
    ]
    with pytest.raises(ValueError, match="exact singleton role set"):
        Phase2DeploymentClosureBuildRequestV2(
            **missing_payload,
            request_sha256=canonical_sha256(missing_payload),
        )

    aliased_payload = request.model_dump(mode="json", exclude={"request_sha256"})
    assets = list(aliased_payload["assets"])
    assert isinstance(assets[0], dict) and isinstance(assets[1], dict)
    first_roles = list(assets[0]["roles"])
    second_singleton = next(
        role for role in assets[1]["roles"] if role in DEPLOYMENT_ASSET_SINGLETON_ROLES_V3
    )
    assets[0] = {**assets[0], "roles": sorted([*first_roles, second_singleton])}
    aliased_payload["assets"] = [assets[0], *assets[2:]]
    with pytest.raises(ValueError, match="two singleton roles"):
        Phase2DeploymentClosureBuildRequestV2(
            **aliased_payload,
            request_sha256=canonical_sha256(aliased_payload),
        )
