from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from m2c.train_qwen_decision_level_v4 import (
    MAX_TRAINING_WALL_SECONDS,
    _supervised_targets,
    _validate_args,
    main,
    parse_args,
)
from test_m2c_train_qwen_coarse_v4 import _cache_snapshot


ROOT = Path(__file__).resolve().parents[2]


def _base_args(tmp_path: Path) -> list[str]:
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    return [
        "--decision-dataset-manifest",
        str(tmp_path / "dataset-manifest.json"),
        "--decision-packaging-report",
        str(ROOT / "reports/m2c-s4-decision-level-supervision-adr0026.json"),
        "--evidence-base",
        str(tmp_path / "evidence"),
        "--training-keys",
        str(ROOT / "configs/m2c_s4_v4_training_keys.json"),
        "--training-keys",
        str(ROOT / "configs/m2c_s4_v4_training_keys_extension1.json"),
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


def test_decision_train_cli_has_no_dry_run_and_requires_both_v4_manifests(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit):
        parse_args([*_base_args(tmp_path), "--dry-run"])
    args = parse_args(_base_args(tmp_path))
    assert len(args.training_keys) == 2
    args.training_keys.pop()
    with pytest.raises(ValueError, match="two frozen V4 TRAIN manifests"):
        _validate_args(args)


def test_decision_train_args_bind_model_revision_budget_and_output(tmp_path: Path) -> None:
    base = _base_args(tmp_path)
    with pytest.raises(ValueError, match="canonical Qwen model revision"):
        _validate_args(parse_args([*base, "--revision", "main"]))
    with pytest.raises(ValueError, match="six hours"):
        _validate_args(
            parse_args([*base, "--max-wall-seconds", str(MAX_TRAINING_WALL_SECONDS + 1)])
        )
    (tmp_path / "output").mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _validate_args(parse_args(base))


def test_decision_train_hard_freeze_precedes_bindings_and_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[str] = []

    def frozen(_action: object) -> None:
        entered.append("freeze")
        raise RuntimeError("cutoff")

    monkeypatch.setattr("m2c.train_qwen_decision_level_v4.require_pre_freeze", frozen)
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4._require_phase2_training_bindings",
        lambda: entered.append("bindings"),
    )
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4.load_adr0026_decision_dataset_v4",
        lambda **_kwargs: entered.append("data"),
    )
    with pytest.raises(RuntimeError, match="cutoff"):
        main(_base_args(tmp_path))
    assert entered == ["freeze"]


def test_decision_train_requires_bindings_before_replaying_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[str] = []

    def blocked() -> None:
        entered.append("bindings")
        raise RuntimeError("active Phase-2 bindings")

    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4._require_phase2_training_bindings", blocked
    )
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4.load_adr0026_decision_dataset_v4",
        lambda **_kwargs: entered.append("data"),
    )
    with pytest.raises(RuntimeError, match="active Phase-2 bindings"):
        main(_base_args(tmp_path))
    assert entered == ["bindings"]


def test_decision_train_replays_data_before_model_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[str] = []

    def loader(**_kwargs: object) -> None:
        entered.append("data")
        raise ValueError("replay failure")

    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4._require_phase2_training_bindings",
        lambda: None,
    )
    monkeypatch.setattr("m2c.train_qwen_decision_level_v4.load_adr0026_decision_dataset_v4", loader)
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4._resolve_local_revision_snapshot",
        lambda *_args: entered.append("model"),
    )
    with pytest.raises(ValueError, match="replay failure"):
        main(_base_args(tmp_path))
    assert entered == ["data"]
    assert not (tmp_path / "output").exists()


def test_decision_train_masks_only_pointer_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = SimpleNamespace(pointer_head_supervision_eligible=True)
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4.decision_head_targets_v4",
        lambda _sample: {"skill": 1, "pointer": 2, "destination": 3},
    )
    assert set(_supervised_targets(sample)) == {"skill", "pointer", "destination"}
    sample.pointer_head_supervision_eligible = False
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4.decision_head_targets_v4",
        lambda _sample: {"skill": 1, "pointer": None, "destination": 3},
    )
    assert set(_supervised_targets(sample)) == {"skill", "destination"}
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4.decision_head_targets_v4",
        lambda _sample: {"skill": 1, "pointer": None, "destination": None},
    )
    with pytest.raises(ValueError, match="outside the pointer head"):
        _supervised_targets(sample)


def test_decision_train_publishes_only_complete_create_only_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache, _snapshot = _cache_snapshot(tmp_path)
    args = [*_base_args(tmp_path), "--cache-dir", str(cache)]
    loaded = object()
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4._require_phase2_training_bindings",
        lambda: None,
    )
    monkeypatch.setattr(
        "m2c.train_qwen_decision_level_v4.load_adr0026_decision_dataset_v4",
        lambda **_kwargs: loaded,
    )

    def fake_train(
        _args: object,
        replayed: object,
        *,
        snapshot: Path,
        expected_snapshot_tree_sha256: str,
        staging_root: Path,
        started: float,
        deadline: float,
    ) -> dict[str, object]:
        assert replayed is loaded
        assert snapshot == snapshot.resolve()
        assert len(expected_snapshot_tree_sha256) == 64
        assert started < deadline
        assert not staging_root.exists()
        staging_root.mkdir(parents=True)
        (staging_root / "qwen_adr0026_decision_v4_bundle.json").write_text('{"complete":true}\n')
        return {
            "schema_version": "M2CQwenCoarseV4ADR0026TrainReportV1",
            "status": "PASS_TRAINED_QWEN_LORA_M2C_Q012_V4_ADR0026_NOT_PHYSICAL_EVALUATION",
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }

    monkeypatch.setattr("m2c.train_qwen_decision_level_v4._train", fake_train)
    assert main(args) == 0
    output = tmp_path / "output"
    report = json.loads((output / "train_report.json").read_text())
    assert (output / "qwen_adr0026_decision_v4_bundle.json").is_file()
    assert report["teacher_used"] is False
    assert json.loads(capsys.readouterr().out) == report
    assert not list(tmp_path.glob(".output.incomplete-*"))
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        main(args)
