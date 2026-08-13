from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess

import pytest

from m2c.qwen_coarse_v2 import sha256_tree
from m2c.train_qwen_coarse_v4 import (
    MAX_TRAINING_WALL_SECONDS,
    _build_backbone,
    _publish_staging,
    _require_phase2_training_bindings,
    _require_snapshot_unchanged,
    _resolve_local_revision_snapshot,
    _validate_args,
    main,
    parse_args,
)
from xh_agent.policy.qrm_lite.backbone import DEFAULT_MODEL_ID, DEFAULT_REVISION


ROOT = Path(__file__).resolve().parents[2]


def _base_args(tmp_path: Path) -> list[str]:
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    return [
        "--package-root",
        str(tmp_path / "missing-package"),
        "--training-keys",
        str(ROOT / "configs/m2c_s4_v4_training_keys.json"),
        "--evaluation-keys",
        str(ROOT / "configs/m2c_s6_evaluation_keys.json"),
        "--output-root",
        str(tmp_path / "output"),
        "--cache-dir",
        str(cache),
        "--local-files-only",
        "--failure-context",
        "on",
    ]


def _cache_snapshot(tmp_path: Path) -> tuple[Path, Path]:
    cache = tmp_path / "cache"
    snapshot = cache / "models--Qwen--Qwen3.5-4B" / "snapshots" / DEFAULT_REVISION
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    (snapshot / "model-00001-of-00001.safetensors").write_bytes(b"weights")
    (snapshot / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"model.layer": "model-00001-of-00001.safetensors"}})
    )
    return cache, snapshot


def test_v4_train_cli_has_no_dry_run_and_requires_packages(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_args([*_base_args(tmp_path), "--dry-run"])
    args = parse_args(_base_args(tmp_path))
    assert args.package_root == [tmp_path / "missing-package"]
    assert args.local_files_only is True


def test_v4_train_args_bind_model_revision_budget_and_complete_episodes(tmp_path: Path) -> None:
    base = _base_args(tmp_path)
    with pytest.raises(ValueError, match="canonical Qwen model ID"):
        _validate_args(parse_args([*base, "--model-id", "/tmp/model"]))
    with pytest.raises(ValueError, match="canonical Qwen revision"):
        _validate_args(parse_args([*base, "--revision", "main"]))
    with pytest.raises(ValueError, match="complete eight-step"):
        _validate_args(parse_args([*base, "--max-train", "7"]))
    with pytest.raises(ValueError, match="six hours"):
        _validate_args(
            parse_args([*base, "--max-wall-seconds", str(MAX_TRAINING_WALL_SECONDS + 1)])
        )


def test_v4_train_replays_data_before_model_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[str] = []

    def fake_loader(*_args: object, **_kwargs: object) -> None:
        entered.append("data")
        raise ValueError("BLOCKED_ZERO_ELIGIBLE_V4_PACKAGES")

    def forbidden_snapshot(*_args: object, **_kwargs: object) -> None:
        entered.append("model")
        raise AssertionError("model cache resolved before data replay")

    monkeypatch.setattr("m2c.train_qwen_coarse_v4.load_training_packages_v4", fake_loader)
    monkeypatch.setattr("m2c.train_qwen_coarse_v4._require_phase2_training_bindings", lambda: None)
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v4._resolve_local_revision_snapshot",
        forbidden_snapshot,
    )
    with pytest.raises(ValueError, match="BLOCKED_ZERO_ELIGIBLE_V4_PACKAGES"):
        main(_base_args(tmp_path))
    assert entered == ["data"]
    assert not (tmp_path / "output").exists()


def test_v4_train_requires_only_active_adr0024_phase2_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import s4_entry_gate

    monkeypatch.setattr(s4_entry_gate, "FORMAL_PHYSICAL_RUNNER_BINDING", None)
    monkeypatch.setattr(s4_entry_gate, "FORMAL_DEPLOYMENT_CLOSURE_BINDING", None)
    with pytest.raises(RuntimeError, match="active Phase-2 bindings"):
        _require_phase2_training_bindings()
    runner_relative = "scripts/m2c/run_formal_model_owned_chain.py"
    runner_sha256 = hashlib.sha256((ROOT / runner_relative).read_bytes()).hexdigest()
    head = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    monkeypatch.setattr(
        s4_entry_gate,
        "FORMAL_PHYSICAL_RUNNER_BINDING",
        (runner_relative, runner_sha256),
    )
    monkeypatch.setattr(
        s4_entry_gate,
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
        (head, "sha256:" + "b" * 64, "c" * 64),
    )
    monkeypatch.setattr(s4_entry_gate, "FROZEN_B0_RUNTIME_WRAPPER_BINDING", None)
    monkeypatch.setattr(s4_entry_gate, "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING", None)
    _require_phase2_training_bindings()
    monkeypatch.setattr(
        s4_entry_gate,
        "FORMAL_PHYSICAL_RUNNER_BINDING",
        (runner_relative, "0" * 64),
    )
    with pytest.raises(RuntimeError, match="current bytes differ"):
        _require_phase2_training_bindings()
    monkeypatch.setattr(
        s4_entry_gate,
        "FORMAL_PHYSICAL_RUNNER_BINDING",
        (runner_relative, runner_sha256),
    )
    monkeypatch.setattr(s4_entry_gate, "FROZEN_B0_RUNTIME_WRAPPER_BINDING", ("old", "d" * 64))
    with pytest.raises(RuntimeError, match="withdrawn bindings"):
        _require_phase2_training_bindings()


def test_v4_train_hard_freeze_precedes_data_and_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[str] = []

    def frozen(_action: object) -> None:
        entered.append("freeze")
        raise RuntimeError("cutoff")

    monkeypatch.setattr("m2c.train_qwen_coarse_v4.require_pre_freeze", frozen)
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v4.load_training_packages_v4",
        lambda *_args, **_kwargs: entered.append("data"),
    )
    with pytest.raises(RuntimeError, match="cutoff"):
        main(_base_args(tmp_path))
    assert entered == ["freeze"]


def test_v4_staging_publish_rolls_back_when_deadline_crosses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    staging.mkdir()
    calls = 0

    def budget(_deadline: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError("deadline")

    monkeypatch.setattr("m2c.train_qwen_coarse_v4._require_budget", budget)
    with pytest.raises(TimeoutError, match="deadline"):
        _publish_staging(staging, output, 1.0)
    assert staging.is_dir()
    assert not output.exists()


def test_v4_local_snapshot_is_exact_and_backbone_uses_resolved_path(tmp_path: Path) -> None:
    cache, snapshot = _cache_snapshot(tmp_path)
    args = parse_args(
        [
            *_base_args(tmp_path),
            "--cache-dir",
            str(cache),
        ]
    )
    _validate_args(args)
    assert _resolve_local_revision_snapshot(cache) == snapshot
    backbone = _build_backbone(args, snapshot)
    assert backbone.model_id == DEFAULT_MODEL_ID
    assert backbone.revision == DEFAULT_REVISION
    assert backbone.local_files_only is True
    assert backbone.resolved_model_path == str(snapshot.resolve())


def test_v4_local_snapshot_rejects_missing_lfs_and_symlink(tmp_path: Path) -> None:
    cache, snapshot = _cache_snapshot(tmp_path)
    weight = snapshot / "model-00001-of-00001.safetensors"
    weight.unlink()
    with pytest.raises(ValueError, match="absent or empty"):
        _resolve_local_revision_snapshot(cache)
    weight.write_text("version https://git-lfs.github.com/spec/v1\n")
    with pytest.raises(ValueError, match="LFS pointer"):
        _resolve_local_revision_snapshot(cache)
    real = tmp_path / "real-cache"
    real.mkdir()
    linked = tmp_path / "linked-cache"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="may not be a symlink"):
        _resolve_local_revision_snapshot(linked)


def test_v4_snapshot_bytes_cannot_change_across_model_loading(tmp_path: Path) -> None:
    cache, snapshot = _cache_snapshot(tmp_path)
    expected = sha256_tree(snapshot)
    _require_snapshot_unchanged(cache, snapshot, expected)
    (snapshot / "config.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="snapshot changed while model loaded"):
        _require_snapshot_unchanged(cache, snapshot, expected)


def test_v4_main_publishes_only_a_complete_create_only_training_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache, snapshot = _cache_snapshot(tmp_path)
    args = [*_base_args(tmp_path), "--cache-dir", str(cache)]
    entered: list[str] = []

    monkeypatch.setattr("m2c.train_qwen_coarse_v4._require_phase2_training_bindings", lambda: None)
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v4.load_training_packages_v4",
        lambda *_args, **_kwargs: ([], object()),
    )

    def fake_train(
        _args: object,
        _samples: object,
        _dataset_report: object,
        *,
        snapshot: Path,
        expected_snapshot_tree_sha256: str,
        staging_root: Path,
        started: float,
        deadline: float,
    ) -> dict[str, object]:
        assert snapshot == snapshot.resolve()
        assert len(expected_snapshot_tree_sha256) == 64
        assert started < deadline
        assert not staging_root.exists()
        staging_root.mkdir(parents=True)
        (staging_root / "qwen_coarse_v4_bundle.json").write_text('{"complete":true}\n')
        entered.append("train")
        return {
            "schema_version": "M2CQwenCoarseV4TrainReportV1",
            "status": "PASS_TRAINED_QWEN_LORA_M2C_Q012_V4_NOT_PHYSICAL_EVALUATION",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }

    monkeypatch.setattr("m2c.train_qwen_coarse_v4._train", fake_train)
    assert main(args) == 0
    output = tmp_path / "output"
    assert entered == ["train"]
    assert (output / "qwen_coarse_v4_bundle.json").is_file()
    report = json.loads((output / "train_report.json").read_text())
    assert report["teacher_used"] is False
    assert json.loads(capsys.readouterr().out) == report
    assert not list(tmp_path.glob(".output.incomplete-*"))

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        main(args)


def test_v4_main_never_publishes_training_failure_or_deadline_crossing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache, _snapshot = _cache_snapshot(tmp_path)
    args = [*_base_args(tmp_path), "--cache-dir", str(cache)]
    monkeypatch.setattr("m2c.train_qwen_coarse_v4._require_phase2_training_bindings", lambda: None)
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v4.load_training_packages_v4",
        lambda *_args, **_kwargs: ([], object()),
    )

    def failed_train(*_args: object, staging_root: Path, **_kwargs: object) -> None:
        staging_root.mkdir(parents=True)
        (staging_root / "partial.bin").write_bytes(b"partial")
        raise RuntimeError("optimizer failure")

    monkeypatch.setattr("m2c.train_qwen_coarse_v4._train", failed_train)
    with pytest.raises(RuntimeError, match="optimizer failure"):
        main(args)
    assert not (tmp_path / "output").exists()
    incomplete = list(tmp_path.glob(".output.incomplete-*"))
    assert len(incomplete) == 1 and (incomplete[0] / "partial.bin").is_file()

    late_output = tmp_path / "late-output"
    late_args = [*args[:-1], args[-1], "--output-root", str(late_output)]
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v4._train",
        lambda *_args, staging_root, **_kwargs: (
            staging_root.mkdir(parents=True)
            or {
                "schema_version": "M2CQwenCoarseV4TrainReportV1",
                "status": "PASS_TRAINED_QWEN_LORA_M2C_Q012_V4_NOT_PHYSICAL_EVALUATION",
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        ),
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v4._publish_staging",
        lambda _staging, _output, _deadline: (_ for _ in ()).throw(TimeoutError("deadline")),
    )
    with pytest.raises(TimeoutError, match="deadline"):
        main(late_args)
    assert not late_output.exists()
