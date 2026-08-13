from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from m2c.derive_model_owned_chain_probe import derive_probe_bytes_v3
from m2c.package_path_blocked_collection import package_collection
from m2c.run_path_blocked_collection_worker import (
    _preimport_v3_checkout_guard,
    _run_probe_command,
    _run_stage_command,
    prepare_job,
    probe_command,
    run,
    stage_command,
)
from xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1 import (
    CANONICAL_COLLECTION_LEDGER_ROOT,
    CollectionAuthorizationError,
    M2CS4V3CollectionConsumptionReceiptV1,
    M2CS4V3RawAuthorizationBindingV1,
    M2CS4V3SelectedKeyCollectionPreregV1,
    ResolvedCollectionPreregV1,
    SelectedV3TrainKeyV1,
    V3_HOST_RUNTIME_LAUNCHER_BINDING,
    authorize_probe_start,
    canonical_sha256,
    canonical_path_sha256,
    consume_probe_launch,
    issue_probe_start_capability,
    materialize_committed_source_snapshot,
    probe_entry_broker_socket_path,
    probe_entry_broker_token_path,
    terminalize_probe_launch,
    start_probe_entry_broker,
    verify_materialized_source_snapshot,
    verify_packaging_authorization,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (
    M2CS4V3TrainingKeyManifestV1,
)


ROOT = Path(__file__).parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
V3_MANIFEST = ROOT / "configs/m2c_s4_v3_training_keys.json"


def _write_canonical(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def _authorization_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ResolvedCollectionPreregV1, Path, Path, list[str], dict[str, str | int]]:
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1."
        "CANONICAL_COLLECTION_LEDGER_ROOT",
        str(ledger),
    )
    manifest = M2CS4V3TrainingKeyManifestV1.model_validate(json.loads(V3_MANIFEST.read_text()))
    record = manifest.training_keys[0]
    selected = SelectedV3TrainKeyV1(
        scene_seed=record.scene_seed,
        failure_seed=record.failure_seed,
        matched_key=record.matched_key,
        sdf_sha256=record.sdf_sha256,
        supervision_sha256=record.supervision_sha256,
    )
    prereg_payload = {
        "schema_version": "M2CS4V3SelectedKeyCollectionPreregV1",
        "status": "FROZEN_BEFORE_ANY_SELECTED_KEY_EXECUTION_OR_RESULT",
        "repository_relative_path": "configs/unit-prereg.json",
        "introduction_commit_paths": ["configs/unit-prereg.json"],
        "batch_id": "m2c-s4-v3-train-batch-99",
        "registered_before_selected_key_execution": True,
        "selected_key_outcome_observed_before_registration": False,
        "governing_adr": {
            "path": "docs/decisions/ADR-0021-m2c-public-semantic-candidate-contract.md",
            "sha256": "a" * 64,
            "status": "ACCEPTED_HUMAN_ADR",
            "introduced_commit": "b" * 40,
            "selected_option": "A",
        },
        "candidate_contract_revision": "PublicTrackCandidateV3",
        "checkpoint_architecture_revision": "M2C_Q012_V3",
        "candidate_count_bound": 8,
        "recapture_policy": "NONE",
        "training_manifest": {"path": "configs/train.json", "sha256": "c" * 64},
        "training_manifest_content_sha256": (
            "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
        ),
        "s6_exclusion_manifest": {"path": "configs/s6.json", "sha256": "d" * 64},
        "runtime_registry": {"path": "configs/runtime.yaml", "sha256": "e" * 64},
        "semantic_source_bindings": [{"path": "src/x.py", "sha256": "f" * 64}],
        "committed_source_snapshot": {
            "commit": "c" * 40,
            "tree": "d" * 40,
            "file_count": 1,
            "total_bytes": 1,
            "inventory_sha256": "e" * 64,
        },
        "prior_attempt_identity_sources": [{"path": "reports/x.json", "sha256": "1" * 64}],
        "container_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
        "container_image_id": (
            "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
        ),
        "upstream_v4_probe_sha256": (
            "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
        ),
        "selection_rule": "manifest_order_first_unattempted_per_sdf_v1",
        "selection_inputs": ["manifest_order", "prior_attempted_identity", "sdf_sha256"],
        "selection_uses_outcomes": False,
        "selected_keys": [selected.model_dump(mode="json")],
        "stop_after_selected_keys": 1,
        "attempt_each_selected_key_at_most_once": True,
        "retry_authorized": False,
        "replacement_authorized": False,
        "ledger_namespace": "M2C_S4_V3_COLLECTION_UNIT",
        "ledger_root": str(ledger),
        "scope": {
            "role": "TRAIN",
            "split": "train",
            "scripted_public_physical_supervision_collection": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "model_rollout": False,
            "training_execution": False,
            "q_b_evaluation": False,
        },
    }
    # The canonical root is patched for this unit-only isolated ledger.
    prereg_payload["prereg_sha256"] = canonical_sha256(prereg_payload)
    prereg = M2CS4V3SelectedKeyCollectionPreregV1.model_validate(prereg_payload)
    resolved = ResolvedCollectionPreregV1(
        path=tmp_path / "prereg.json",
        file_sha256="2" * 64,
        raw_bytes=b"unit fixture",
        prereg=prereg,
        manifest=manifest,
        introduced_commit="3" * 40,
    )
    destination = record.destination_cell
    common: dict[str, str | int] = {
        "matched_key": record.matched_key,
        "failure_seed": record.failure_seed,
        "source_sdf_sha256": record.sdf_sha256,
        "source_supervision_sha256": record.supervision_sha256,
        "source_urdf_sha256": "4" * 64,
        "upstream_v4_probe_sha256": prereg.upstream_v4_probe_sha256,
        "stage_usdc_sha256": "5" * 64,
        "stage_metrics_sha256": "a" * 64,
        "stage_command_sha256": "b" * 64,
        "derived_probe_sha256": "6" * 64,
        "container_image_id": prereg.container_image_id,
        "job_root_sha256": canonical_path_sha256(tmp_path / "job"),
        "probe_output_root_sha256": canonical_path_sha256(tmp_path / "job/probe"),
        "role": "TRAIN",
        "split": "train",
        "declared_target_attribute": "yellow",
        "destination_cell": destination,
    }
    claim_core = {
        "schema_version": "M2CS4V3CollectionConsumptionReceiptV1",
        "event": "CONSUMED_BEFORE_STAGE",
        "ledger_namespace": prereg.ledger_namespace,
        "ledger_sequence": 0,
        "batch_id": prereg.batch_id,
        "ordinal": 0,
        "consumption_id": "7" * 64,
        "challenge_nonce": "8" * 64,
        "prereg_repository_path": prereg.repository_relative_path,
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": prereg.prereg_sha256,
        "prereg_introduced_commit": resolved.introduced_commit,
        "selected_key": selected.model_dump(mode="json"),
        "selected_key_sha256": canonical_sha256(selected.model_dump(mode="json")),
        "source_sdf_sha256": common["source_sdf_sha256"],
        "source_supervision_sha256": common["source_supervision_sha256"],
        "source_urdf_sha256": common["source_urdf_sha256"],
        "upstream_v4_probe_sha256": common["upstream_v4_probe_sha256"],
        "committed_source_snapshot": prereg.committed_source_snapshot.model_dump(mode="json"),
        "derived_probe_sha256": common["derived_probe_sha256"],
        "container_image": prereg.container_image,
        "container_image_id": prereg.container_image_id,
        "role": "TRAIN",
        "split": "train",
        "declared_target_attribute": "yellow",
        "destination_cell": destination,
        "candidate_contract_revision": "PublicTrackCandidateV3",
        "checkpoint_architecture_revision": "M2C_Q012_V3",
        "previous_receipt_sha256": None,
        "consumed_at_ns": 1,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "model_rollout": False,
        "training_executed": False,
        "formal_q_b_evaluation": False,
    }
    claim = M2CS4V3CollectionConsumptionReceiptV1.model_validate(
        {**claim_core, "receipt_sha256": canonical_sha256(claim_core)}
    )
    claim_path = ledger / "claim-00000000.json"
    _write_canonical(claim_path, claim.model_dump(mode="json"))
    argv = [
        "/workspace/derived/probe.py",
        "--stage",
        "/workspace/stage/scene.usdc",
        "--m2c-docker-command-sha256",
        "9" * 64,
        "--m2c-job-root-sha256",
        str(common["job_root_sha256"]),
        "--m2c-probe-output-root-sha256",
        str(common["probe_output_root_sha256"]),
    ]
    return resolved, claim_path, ledger, argv, common


def _allow_unit_snapshot_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1."
        "verify_materialized_source_snapshot",
        lambda *_args, **_kwargs: None,
    )


def _v3_args(tmp_path: Path) -> argparse.Namespace:
    record = json.loads(V3_MANIFEST.read_text())["training_keys"][0]
    return argparse.Namespace(
        project_root=ROOT,
        source_root=tmp_path / "missing-source",
        sdf=tmp_path / "missing-source/scene.sdf",
        supervision=tmp_path / "missing-source/scene.supervision.json",
        urdf=tmp_path / "missing-source/panda_controlled.urdf",
        upstream_v4_probe=UPSTREAM,
        output_root=tmp_path / "jobs",
        packaged_output_root=tmp_path / "bundles",
        role="TRAIN",
        revision="V3",
        matched_key=record["matched_key"],
        gpu=0,
        image="nvcr.io/nvidia/isaac-sim:6.0.1",
        container_prefix="m2c-auth-test",
        stage_timeout_s=1.0,
        probe_timeout_s=1.0,
        dry_run=False,
        training_keys=V3_MANIFEST,
        s6_keys=ROOT / "configs/m2c_s6_evaluation_keys.json",
        runtime_registry=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        collection_prereg=None,
        collection_ledger_root=None,
    )


def test_complete_committed_source_snapshot_binds_unlisted_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "M2C Unit"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "m2c-unit@example.invalid"],
        check=True,
    )
    (repository / "scripts").mkdir()
    (repository / "scripts/stage.py").write_text("print('stage-v1')\n")
    # This path is intentionally absent from the old eight-file allowlist.
    (repository / "transitive_dependency.py").write_text("VALUE = 'v1'\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "runtime v1"], check=True)
    commit_v1 = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    from xh_agent.policy.qrm_lite import s4_v3_collection_authorization_v1 as authorization

    identity_v1, payloads_v1 = authorization._source_snapshot_payloads(  # noqa: SLF001
        repository,
        commit=commit_v1,
    )
    assert {entry["path"] for entry, _payload in payloads_v1} == {
        "scripts/stage.py",
        "transitive_dependency.py",
    }
    snapshot_parent = tmp_path / "snapshots"
    monkeypatch.setattr(authorization, "CANONICAL_SOURCE_SNAPSHOT_ROOT", str(snapshot_parent))
    snapshot = materialize_committed_source_snapshot(
        project_root=repository,
        expected=identity_v1,
    )
    verify_materialized_source_snapshot(snapshot, identity_v1)
    assert (snapshot / "transitive_dependency.py").read_text() == "VALUE = 'v1'\n"
    renamed = snapshot_parent / ("f" * 64)
    snapshot.rename(renamed)
    with pytest.raises(CollectionAuthorizationError, match="differs"):
        verify_materialized_source_snapshot(renamed, identity_v1)
    verify_materialized_source_snapshot(
        renamed,
        identity_v1,
        require_content_addressed_name=False,
    )
    renamed.rename(snapshot)

    (repository / "transitive_dependency.py").write_text("VALUE = 'v2'\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "runtime v2"], check=True)
    commit_v2 = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    identity_v2, _payloads_v2 = authorization._source_snapshot_payloads(  # noqa: SLF001
        repository,
        commit=commit_v2,
    )
    assert identity_v2.inventory_sha256 != identity_v1.inventory_sha256
    assert identity_v2.tree != identity_v1.tree

    snapshot_file = snapshot / "transitive_dependency.py"
    snapshot_file.chmod(0o644)
    snapshot_file.write_text("tampered\n")
    snapshot_file.chmod(0o444)
    with pytest.raises(CollectionAuthorizationError, match="differs"):
        verify_materialized_source_snapshot(snapshot, identity_v1)


def test_host_checkout_rejects_any_post_prereg_dependency_or_commit(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "M2C Unit"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "m2c-unit@example.invalid"],
        check=True,
    )
    (repository / "transitive_dependency.py").write_text("VALUE = 'frozen'\n")
    (repository / ".gitignore").write_text("__pycache__/\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "runtime"], check=True)
    (repository / "prereg.json").write_text("{}\n")
    subprocess.run(["git", "-C", str(repository), "add", "prereg.json"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "preregister"], check=True)
    prereg_commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    from xh_agent.policy.qrm_lite import s4_v3_collection_authorization_v1 as authorization

    authorization._require_prereg_execution_checkout(  # noqa: SLF001
        repository,
        introduced_commit=prereg_commit,
    )
    (repository / "transitive_dependency.py").write_text("VALUE = 'post-outcome'\n")
    with pytest.raises(CollectionAuthorizationError, match="clean host checkout"):
        authorization._require_prereg_execution_checkout(  # noqa: SLF001
            repository,
            introduced_commit=prereg_commit,
        )
    subprocess.run(
        ["git", "-C", str(repository), "restore", "transitive_dependency.py"],
        check=True,
    )
    (repository / "untracked_shadow.py").write_text("VALUE = 'shadow'\n")
    with pytest.raises(CollectionAuthorizationError, match="clean host checkout"):
        authorization._require_prereg_execution_checkout(  # noqa: SLF001
            repository,
            introduced_commit=prereg_commit,
        )
    (repository / "untracked_shadow.py").unlink()
    runtime_cache = repository / "src/xh_agent/__pycache__/shadow.pyc"
    runtime_cache.parent.mkdir(parents=True)
    runtime_cache.write_bytes(b"unchecked-bytecode-shadow")
    with pytest.raises(CollectionAuthorizationError, match="ignored shadow bytes"):
        authorization._require_prereg_execution_checkout(  # noqa: SLF001
            repository,
            introduced_commit=prereg_commit,
        )
    runtime_cache.unlink()
    runtime_cache.parent.rmdir()
    runtime_cache.parent.parent.rmdir()
    runtime_cache.parent.parent.parent.rmdir()
    (repository / "unrelated.txt").write_text("later commit\n")
    subprocess.run(["git", "-C", str(repository), "add", "unrelated.txt"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "later"], check=True)
    with pytest.raises(CollectionAuthorizationError, match="current checkout HEAD"):
        authorization._require_prereg_execution_checkout(  # noqa: SLF001
            repository,
            introduced_commit=prereg_commit,
        )


def test_cli_preimport_gate_precedes_all_project_imports_and_rejects_runtime_cache() -> None:
    worker_source = (ROOT / "scripts/m2c/run_path_blocked_collection_worker.py").read_text()
    package_source = (ROOT / "scripts/m2c/package_path_blocked_collection.py").read_text()
    for source in (worker_source, package_source):
        guard = source.index("_run_cli_preimport_guard()")
        first_project_import = min(
            source.index("from m2c."),
            source.index("from xh_agent."),
        )
        assert guard < first_project_import
        assert '"src/xh_agent"' in source
        assert '"scripts/m2c"' in source
        assert '"--ignored"' in source
    # Keep a direct reference so import sorting/refactoring cannot silently
    # drop the tested stdlib gate from the canonical worker module.
    assert callable(_preimport_v3_checkout_guard)


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--revision", "V2", "--revision", "V3"],
        ["--project-root", "/safe", "--project-root=/evil"],
        ["--collection-prereg=/safe.json", "--collection-prereg", "/evil.json"],
    ],
)
def test_cli_preimport_gate_rejects_duplicate_security_options_before_import(
    tmp_path: Path,
    extra_args: list[str],
) -> None:
    copied_worker = tmp_path / "run_path_blocked_collection_worker.py"
    copied_worker.write_bytes(
        (ROOT / "scripts/m2c/run_path_blocked_collection_worker.py").read_bytes()
    )
    sentinel = tmp_path / "project-imported"
    malicious_package = tmp_path / "m2c"
    malicious_package.mkdir()
    (malicious_package / "__init__.py").write_text("")
    (malicious_package / "derive_model_owned_chain_probe.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('imported')\n"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(copied_worker),
            "--revision",
            "V3",
            "--project-root",
            str(tmp_path),
            "--collection-prereg",
            str(tmp_path / "prereg.json"),
            *extra_args,
        ],
        env={"PYTHONPATH": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "is repeated" in completed.stderr
    assert not sentinel.exists()


def test_v3_cli_rejects_nonisolated_python_before_malicious_pythonpath_import(
    tmp_path: Path,
) -> None:
    copied_worker = tmp_path / "run_path_blocked_collection_worker.py"
    copied_worker.write_bytes(
        (ROOT / "scripts/m2c/run_path_blocked_collection_worker.py").read_bytes()
    )
    sentinel = tmp_path / "project-imported"
    malicious_package = tmp_path / "m2c"
    malicious_package.mkdir()
    (malicious_package / "__init__.py").write_text("")
    (malicious_package / "derive_model_owned_chain_probe.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('imported')\n"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            str(copied_worker),
            "--revision",
            "V3",
            "--project-root",
            str(tmp_path),
            "--collection-prereg",
            str(tmp_path / "prereg.json"),
        ],
        env={"PYTHONPATH": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "must use the project venv Python with -I -S -B" in completed.stderr
    assert not sentinel.exists()


def test_v3_cli_isolated_mode_ignores_malicious_pythonpath_before_import(
    tmp_path: Path,
) -> None:
    copied_worker = tmp_path / "run_path_blocked_collection_worker.py"
    copied_worker.write_bytes(
        (ROOT / "scripts/m2c/run_path_blocked_collection_worker.py").read_bytes()
    )
    sentinel = tmp_path / "project-imported"
    malicious_package = tmp_path / "m2c"
    malicious_package.mkdir()
    (malicious_package / "__init__.py").write_text("")
    (malicious_package / "derive_model_owned_chain_probe.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('imported')\n"
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(copied_worker),
            "--revision",
            "V3",
            "--project-root",
            str(tmp_path),
            "--collection-prereg",
            str(tmp_path / "missing-prereg.json"),
        ],
        env={"PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "pre-import gate blocked" in completed.stderr
    assert not sentinel.exists()


def test_worker_v3_requires_authorization_before_any_output_or_source_read(
    tmp_path: Path,
) -> None:
    args = _v3_args(tmp_path)
    with pytest.raises(CollectionAuthorizationError, match="no active committed"):
        run(args)
    assert not args.output_root.exists()
    assert not args.packaged_output_root.exists()

    with pytest.raises(CollectionAuthorizationError, match="committed preregistration"):
        prepare_job(args)
    assert not args.output_root.exists()


def test_worker_v3_dry_run_cannot_emit_executable_probe(tmp_path: Path) -> None:
    args = _v3_args(tmp_path)
    args.dry_run = True
    args.collection_prereg = tmp_path / "uncommitted.json"
    args.collection_ledger_root = tmp_path / "ledger"
    with pytest.raises(CollectionAuthorizationError):
        run(args)
    assert not args.output_root.exists()


def test_v3_programmatic_worker_and_packager_require_frozen_host_launcher(
    tmp_path: Path,
) -> None:
    assert V3_HOST_RUNTIME_LAUNCHER_BINDING is None
    args = _v3_args(tmp_path)
    args.collection_prereg = tmp_path / "prereg.json"
    args.collection_ledger_root = Path(CANONICAL_COLLECTION_LEDGER_ROOT)
    with pytest.raises(CollectionAuthorizationError, match="host runtime launcher"):
        run(args)
    assert not args.output_root.exists()

    with pytest.raises(CollectionAuthorizationError, match="host runtime launcher"):
        package_collection(
            raw_probe_path=tmp_path / "raw.json",
            evidence_root=tmp_path / "evidence",
            output_root=tmp_path / "packaged",
            role="TRAIN",
            matched_key=args.matched_key,
            training_keys_path=args.training_keys,
            s6_keys_path=args.s6_keys,
            runtime_registry_path=args.runtime_registry,
            derived_probe_path=tmp_path / "derived.py",
            upstream_v4_probe_path=args.upstream_v4_probe,
            revision="V3",
            collection_prereg_path=args.collection_prereg,
            collection_claim_path=tmp_path / "claim.json",
        )
    assert not (tmp_path / "packaged").exists()


def test_worker_consumes_claim_before_docker_or_snapshot_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved, claim_path, ledger, _argv, _common = _authorization_fixture(
        tmp_path,
        monkeypatch,
    )
    args = _v3_args(tmp_path)
    args.collection_prereg = tmp_path / "committed-prereg.json"
    args.collection_ledger_root = ledger
    args.urdf.parent.mkdir(parents=True)
    args.urdf.write_text("<robot/>\n")
    events: list[str] = []

    monkeypatch.setattr(
        "m2c.run_path_blocked_collection_worker.load_committed_collection_prereg",
        lambda **_kwargs: resolved,
    )
    monkeypatch.setattr(
        "m2c.run_path_blocked_collection_worker.require_pre_freeze",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "m2c.run_path_blocked_collection_worker.require_v3_host_runtime_launcher",
        lambda: None,
    )

    def consume_stub(**_kwargs: object) -> Path:
        events.append("claim")
        return claim_path

    def image_stub(**_kwargs: object) -> str:
        events.append("docker-inspect")
        return resolved.prereg.container_image_id

    def snapshot_stub(**_kwargs: object) -> Path:
        events.append("snapshot")
        raise RuntimeError("stop after ordering boundary")

    monkeypatch.setattr(
        "m2c.run_path_blocked_collection_worker.consume_collection_key",
        consume_stub,
    )
    monkeypatch.setattr(
        "m2c.run_path_blocked_collection_worker.resolve_docker_image_id",
        image_stub,
    )
    monkeypatch.setattr(
        "m2c.run_path_blocked_collection_worker.materialize_committed_source_snapshot",
        snapshot_stub,
    )
    with pytest.raises(RuntimeError, match="ordering boundary"):
        run(args)
    assert events == ["claim", "docker-inspect", "snapshot"]
    assert not args.output_root.exists()


def test_v3_commands_execute_immutable_image_and_mount_ledger_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved, claim_path, ledger, _argv, common = _authorization_fixture(
        tmp_path,
        monkeypatch,
    )
    args = _v3_args(tmp_path)
    args.source_root.mkdir()
    image_id = str(common["container_image_id"])
    stage = stage_command(
        args,
        output=tmp_path / "job/stage",
        image_reference=image_id,
    )
    assert image_id in stage
    assert args.image not in stage

    start_path = ledger / "probe-start-placeholder.json"
    broker_socket = probe_entry_broker_socket_path("7" * 64)
    broker_token = probe_entry_broker_token_path("7" * 64)
    command = probe_command(
        args,
        derived_probe=tmp_path / "job/derived.py",
        stage=tmp_path / "job/stage/scene.usdc",
        output=tmp_path / "job/probe",
        source_record={
            "destination_cell": "BIN_CELL_0",
            "split": "train",
            "failure_seed": int(common["failure_seed"]),
            "declared_target_attribute": "yellow",
        },
        container_image_id=image_id,
        collection_prereg=resolved,
        collection_claim=claim_path,
        collection_start_capability=start_path,
        collection_probe_entry_broker_socket=broker_socket,
        collection_probe_entry_token_file=broker_token,
        source_snapshot_root=tmp_path / "source-snapshot",
    )
    assert image_id in command
    assert args.image not in command
    assert f"{ledger}:{ledger}:ro" in command
    assert f"{ledger}:{ledger}:rw" not in command
    assert not any(value.endswith(":rw") for value in command)
    assert f"{broker_socket.parent}:{broker_socket.parent}:ro" in command


def test_derived_v3_probe_checks_hard_freeze_then_claim_before_kit() -> None:
    source = derive_probe_bytes_v3(UPSTREAM.read_bytes()).decode("utf-8")
    ast.parse(source)
    authorization = source.index("M2C_V3_COLLECTION_AUTHORIZATION = authorize_probe_start(")
    hard_freeze = source.index("else M2CExperimentAction.ISAAC_COLLECTION")
    kit = source.index("from isaacsim import SimulationApp")
    assert hard_freeze < authorization < kit
    assert 'parser.add_argument("--m2c-collection-claim", type=Path, required=True)' in source
    assert 'parser.add_argument("--m2c-probe-start-capability", type=Path, required=True)' in source
    assert (
        'parser.add_argument("--m2c-probe-entry-broker-socket", type=Path, required=True)' in source
    )
    assert 'parser.add_argument("--m2c-probe-entry-token-file", type=Path, required=True)' in source
    assert "stage_usdc_sha256=sha256_file(ARGS.stage)" in source
    assert '"m2c_v3_collection_authorization": M2C_V3_COLLECTION_AUTHORIZATION' in source


def test_v3_packager_rejects_before_parsing_or_publishing_without_claim(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw/actuation-probe.json"
    raw.parent.mkdir(parents=True)
    raw.write_text("{}\n")
    derived = tmp_path / "derived.py"
    derived.write_bytes(derive_probe_bytes_v3(UPSTREAM.read_bytes()))
    record = json.loads(V3_MANIFEST.read_text())["training_keys"][0]
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match="committed preregistration"):
        package_collection(
            raw_probe_path=raw,
            evidence_root=raw.parent,
            output_root=output,
            role="TRAIN",
            matched_key=record["matched_key"],
            training_keys_path=V3_MANIFEST,
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
            derived_probe_path=derived,
            upstream_v4_probe_path=UPSTREAM,
            revision="V3",
        )
    assert not output.exists()

    missing_raw = tmp_path / "missing/actuation-probe.json"
    with pytest.raises(ValueError, match="committed preregistration"):
        package_collection(
            raw_probe_path=missing_raw,
            evidence_root=missing_raw.parent,
            output_root=tmp_path / "other-output",
            role="TRAIN",
            matched_key=record["matched_key"],
            training_keys_path=V3_MANIFEST,
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
            derived_probe_path=tmp_path / "missing-derived.py",
            upstream_v4_probe_path=UPSTREAM,
            revision="V3",
        )


def test_prereg_schema_rejects_outcome_inputs_and_unapproved_scope() -> None:
    base = {
        "schema_version": "M2CS4V3SelectedKeyCollectionPreregV1",
        "status": "FROZEN_BEFORE_ANY_SELECTED_KEY_EXECUTION_OR_RESULT",
        "repository_relative_path": "configs/example.json",
        "introduction_commit_paths": ["configs/example.json"],
        "batch_id": "m2c-s4-v3-train-batch-04",
        "registered_before_selected_key_execution": True,
        "selected_key_outcome_observed_before_registration": False,
        "governing_adr": {
            "path": "docs/decisions/ADR-0021-m2c-public-semantic-candidate-contract.md",
            "sha256": "b" * 64,
            "status": "ACCEPTED_HUMAN_ADR",
            "introduced_commit": "c" * 40,
            "selected_option": "A",
        },
        "candidate_contract_revision": "PublicTrackCandidateV3",
        "checkpoint_architecture_revision": "M2C_Q012_V3",
        "candidate_count_bound": 8,
        "recapture_policy": "NONE",
        "training_manifest": {"path": "configs/train.json", "sha256": "d" * 64},
        "training_manifest_content_sha256": (
            "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
        ),
        "s6_exclusion_manifest": {"path": "configs/s6.json", "sha256": "e" * 64},
        "runtime_registry": {"path": "configs/runtime.yaml", "sha256": "f" * 64},
        "semantic_source_bindings": [{"path": "src/x.py", "sha256": "1" * 64}],
        "committed_source_snapshot": {
            "commit": "1" * 40,
            "tree": "2" * 40,
            "file_count": 1,
            "total_bytes": 1,
            "inventory_sha256": "3" * 64,
        },
        "prior_attempt_identity_sources": [{"path": "reports/prior.json", "sha256": "2" * 64}],
        "container_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
        "container_image_id": (
            "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
        ),
        "upstream_v4_probe_sha256": (
            "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
        ),
        "selection_rule": "manifest_order_first_unattempted_per_sdf_v1",
        "selection_inputs": ["manifest_order", "prior_attempted_identity", "sdf_sha256"],
        "selection_uses_outcomes": False,
        "selected_keys": [
            {
                "scene_seed": 1,
                "failure_seed": 2,
                "matched_key": "m2c-s4-v3-train-" + "4" * 64,
                "sdf_sha256": "5" * 64,
                "supervision_sha256": "6" * 64,
            }
        ],
        "stop_after_selected_keys": 1,
        "attempt_each_selected_key_at_most_once": True,
        "retry_authorized": False,
        "replacement_authorized": False,
        "ledger_namespace": "M2C_S4_V3_COLLECTION_BATCH_04",
        "ledger_root": CANONICAL_COLLECTION_LEDGER_ROOT,
        "scope": {
            "role": "TRAIN",
            "split": "train",
            "scripted_public_physical_supervision_collection": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "model_rollout": False,
            "training_execution": False,
            "q_b_evaluation": False,
        },
    }
    base["prereg_sha256"] = canonical_sha256(base)
    M2CS4V3SelectedKeyCollectionPreregV1.model_validate(base)

    forged = json.loads(json.dumps(base))
    forged["selection_inputs"].append("outcome")
    forged["prereg_sha256"] = canonical_sha256(
        {key: value for key, value in forged.items() if key != "prereg_sha256"}
    )
    with pytest.raises(Exception):
        M2CS4V3SelectedKeyCollectionPreregV1.model_validate(forged)

    forged = json.loads(json.dumps(base))
    forged["scope"]["teacher_used"] = True
    forged["prereg_sha256"] = canonical_sha256(
        {key: value for key, value in forged.items() if key != "prereg_sha256"}
    )
    with pytest.raises(Exception):
        M2CS4V3SelectedKeyCollectionPreregV1.model_validate(forged)


def test_host_capability_binds_stage_image_argv_and_is_single_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved, claim_path, ledger, argv, common = _authorization_fixture(
        tmp_path,
        monkeypatch,
    )
    _allow_unit_snapshot_verification(monkeypatch)
    issued = issue_probe_start_capability(
        resolved=resolved,
        claim_path=claim_path,
        probe_argv_sha256=canonical_sha256(argv),
        docker_command_sha256="9" * 64,
        now_ns=2,
        **common,
    )
    assert issued.path.parent == ledger
    assert issued.path.stat().st_mode & 0o777 == 0o600

    launch = consume_probe_launch(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
    )
    broker = start_probe_entry_broker(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
        issued=issued,
        accept_timeout_s=2.0,
    )

    binding = authorize_probe_start(
        claim_path=claim_path,
        start_capability_path=issued.path,
        probe_entry_broker_socket=issued.broker_socket_path,
        probe_entry_token_file=issued.broker_token_path,
        source_snapshot_root=tmp_path / "snapshot",
        probe_argv=argv,
        **common,
    )
    broker.wait()
    assert isinstance(binding, M2CS4V3RawAuthorizationBindingV1)
    assert binding.stage_usdc_sha256 == common["stage_usdc_sha256"]
    with pytest.raises(CollectionAuthorizationError, match="cannot securely open|unavailable"):
        authorize_probe_start(
            claim_path=claim_path,
            start_capability_path=issued.path,
            probe_entry_broker_socket=issued.broker_socket_path,
            probe_entry_token_file=issued.broker_token_path,
            source_snapshot_root=tmp_path / "snapshot",
            probe_argv=argv,
            **common,
        )

    with pytest.raises(CollectionAuthorizationError, match="stage_usdc_sha256"):
        authorize_probe_start(
            claim_path=claim_path,
            start_capability_path=issued.path,
            probe_entry_broker_socket=issued.broker_socket_path,
            probe_entry_token_file=issued.broker_token_path,
            source_snapshot_root=tmp_path / "snapshot",
            probe_argv=argv,
            **{**common, "stage_usdc_sha256": "a" * 64},
        )
    with pytest.raises(CollectionAuthorizationError, match="probe_argv_sha256"):
        authorize_probe_start(
            claim_path=claim_path,
            start_capability_path=issued.path,
            probe_entry_broker_socket=issued.broker_socket_path,
            probe_entry_token_file=issued.broker_token_path,
            source_snapshot_root=tmp_path / "snapshot",
            probe_argv=[*argv, "--tampered"],
            **common,
        )

    assert launch.stat().st_mode & 0o777 == 0o600
    with pytest.raises(CollectionAuthorizationError, match="concurrently consumed"):
        consume_probe_launch(
            resolved=resolved,
            claim_path=claim_path,
            matched_key=str(common["matched_key"]),
        )


def test_copied_capability_cannot_replay_without_host_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved, claim_path, _ledger, argv, common = _authorization_fixture(
        tmp_path,
        monkeypatch,
    )
    _allow_unit_snapshot_verification(monkeypatch)
    issued = issue_probe_start_capability(
        resolved=resolved,
        claim_path=claim_path,
        probe_argv_sha256=canonical_sha256(argv),
        docker_command_sha256="9" * 64,
        now_ns=2,
        **common,
    )
    consume_probe_launch(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
    )
    broker = start_probe_entry_broker(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
        issued=issued,
        accept_timeout_s=2.0,
    )
    authorize_probe_start(
        claim_path=claim_path,
        start_capability_path=issued.path,
        probe_entry_broker_socket=issued.broker_socket_path,
        probe_entry_token_file=issued.broker_token_path,
        source_snapshot_root=tmp_path / "snapshot",
        probe_argv=argv,
        **common,
    )
    broker.wait()
    assert not issued.broker_socket_path.exists()
    assert not issued.broker_token_path.exists()

    # The signed/canonical claim and start bytes remain readable, but a fresh
    # private directory or copied mount cannot recreate the host listener or
    # its never-persisted token.
    replica_token = tmp_path / "replica.token"
    replica_token.write_bytes(b"x" * 32)
    replica_token.chmod(0o600)
    with pytest.raises(CollectionAuthorizationError, match="probe-start capability differs"):
        authorize_probe_start(
            claim_path=claim_path,
            start_capability_path=issued.path,
            probe_entry_broker_socket=issued.broker_socket_path,
            probe_entry_token_file=replica_token,
            source_snapshot_root=tmp_path / "snapshot",
            probe_argv=argv,
            **common,
        )


def test_probe_timeout_removes_named_container_before_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run_stub(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, "removed\n", "")
        raise subprocess.TimeoutExpired(command, timeout=1, output="partial", stderr="timeout")

    monkeypatch.setattr("m2c.run_path_blocked_collection_worker.subprocess.run", run_stub)
    result = _run_probe_command(
        ["docker", "run", "immutable-image-id"],
        container_name="m2c-unit-probe",
        timeout_s=1,
    )
    assert calls[-1] == ["docker", "rm", "-f", "m2c-unit-probe"]
    assert result.returncode == 124
    assert "M2C_PROBE_TIMEOUT_TERMINALIZED" in result.stderr


def test_stage_timeout_removes_named_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run_stub(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, "removed\n", "")
        raise subprocess.TimeoutExpired(command, timeout=1)

    monkeypatch.setattr("m2c.run_path_blocked_collection_worker.subprocess.run", run_stub)
    with pytest.raises(subprocess.TimeoutExpired):
        _run_stage_command(
            ["docker", "run", "immutable-image-id"],
            container_name="m2c-unit-stage",
            timeout_s=1,
        )
    assert calls[-1] == ["docker", "rm", "-f", "m2c-unit-stage"]


def test_stage_timeout_fails_closed_when_container_absence_is_unproven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_stub(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 1, "", "daemon unavailable")
        raise OSError("docker spawn failed")

    monkeypatch.setattr("m2c.run_path_blocked_collection_worker.subprocess.run", run_stub)
    with pytest.raises(CollectionAuthorizationError, match="could not be stopped"):
        _run_stage_command(
            ["docker", "run", "immutable-image-id"],
            container_name="m2c-unit-stage",
            timeout_s=1,
        )


def test_packaging_authorization_requires_launch_receipt_and_rejects_splice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved, claim_path, _ledger, argv, common = _authorization_fixture(
        tmp_path,
        monkeypatch,
    )
    _allow_unit_snapshot_verification(monkeypatch)
    issued = issue_probe_start_capability(
        resolved=resolved,
        claim_path=claim_path,
        probe_argv_sha256=canonical_sha256(argv),
        docker_command_sha256="9" * 64,
        now_ns=2,
        **common,
    )
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1."
        "load_committed_collection_prereg",
        lambda **_kwargs: resolved,
    )
    with pytest.raises(CollectionAuthorizationError, match="launch-consumption"):
        verify_packaging_authorization(
            project_root=ROOT,
            prereg_path=resolved.path,
            claim_path=claim_path,
            matched_key=str(common["matched_key"]),
            raw_binding={},
            raw_probe_sha256="0" * 64,
            console_sha256="0" * 64,
            job_root=tmp_path / "job",
            probe_output_root=tmp_path / "job/probe",
        )

    consume_probe_launch(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
    )
    broker = start_probe_entry_broker(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
        issued=issued,
        accept_timeout_s=2.0,
    )
    binding = authorize_probe_start(
        claim_path=claim_path,
        start_capability_path=issued.path,
        probe_entry_broker_socket=issued.broker_socket_path,
        probe_entry_token_file=issued.broker_token_path,
        source_snapshot_root=tmp_path / "snapshot",
        probe_argv=argv,
        **common,
    )
    broker.wait()
    probe_root = tmp_path / "job/probe"
    probe_root.mkdir(parents=True)
    console_path = probe_root / "console.log"
    raw_path = probe_root / "actuation-probe.json"
    console_path.write_text("unit\n")
    raw_path.write_text("{}\n")
    terminalize_probe_launch(
        resolved=resolved,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
        job_root=tmp_path / "job",
        probe_output_root=probe_root,
        returncode=0,
        console_path=console_path,
        raw_probe_path=raw_path,
        now_ns=3,
    )
    _resolved, _claim, packaged_binding = verify_packaging_authorization(
        project_root=ROOT,
        prereg_path=resolved.path,
        claim_path=claim_path,
        matched_key=str(common["matched_key"]),
        raw_binding=binding.model_dump(mode="json"),
        raw_probe_sha256=__import__("hashlib").sha256(raw_path.read_bytes()).hexdigest(),
        console_sha256=__import__("hashlib").sha256(console_path.read_bytes()).hexdigest(),
        job_root=tmp_path / "job",
        probe_output_root=probe_root,
    )
    assert packaged_binding.probe_terminal_receipt_sha256 != "0" * 64
    with pytest.raises(CollectionAuthorizationError, match="exact raw output"):
        verify_packaging_authorization(
            project_root=ROOT,
            prereg_path=resolved.path,
            claim_path=claim_path,
            matched_key=str(common["matched_key"]),
            raw_binding=binding.model_dump(mode="json"),
            raw_probe_sha256="f" * 64,
            console_sha256=__import__("hashlib").sha256(console_path.read_bytes()).hexdigest(),
            job_root=tmp_path / "job",
            probe_output_root=probe_root,
        )
    tampered = binding.model_dump(mode="json")
    tampered["stage_usdc_sha256"] = "a" * 64
    with pytest.raises(CollectionAuthorizationError, match="not exact"):
        verify_packaging_authorization(
            project_root=ROOT,
            prereg_path=resolved.path,
            claim_path=claim_path,
            matched_key=str(common["matched_key"]),
            raw_binding=tampered,
            raw_probe_sha256=__import__("hashlib").sha256(raw_path.read_bytes()).hexdigest(),
            console_sha256=__import__("hashlib").sha256(console_path.read_bytes()).hexdigest(),
            job_root=tmp_path / "job",
            probe_output_root=probe_root,
        )
