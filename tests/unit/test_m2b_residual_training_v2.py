from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from m2b.build_residual_training_v2 import _validate_pair, residual_sample
from m2b.train_residual_mlp_v2 import (
    evaluate,
    masked_metrics,
    sample_tensors,
    train_masked_mlp,
    validate_samples,
)
from m2b.summarize_residual_mlp import summarize


def _payload() -> dict:
    return {
        "m2b_public_rgbd": {
            "camera_frame": "m2b_policy_rgbd_optical",
            "camera_intrinsics": [1.0] * 9,
            "camera_to_world_optical": [
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ],
            "captures": [
                {
                    "label": "after_recovery_retreat",
                    "timestamp_ns": 42,
                    "rgb_uri": "dataset://rgb.png",
                    "rgb_sha256": "a" * 64,
                    "depth_uri": "dataset://depth.npy",
                    "depth_sha256": "b" * 64,
                    "tracks": [
                        {
                            "track_id": "target-red",
                            "category": "industrial_cylinder",
                            "visual_color": "red",
                            "confidence": 0.9,
                            "position_world_m": [0.1, 0.2, 0.5],
                        }
                    ],
                }
            ],
        },
        "m2b_recovery": {
            "wrong_object": {
                "reassociated_target_track_id": "target-red"
            }
        },
    }


def _pair(seed: int, offset: tuple[float, float, float]) -> dict:
    nominal = [*offset, *([0.0] * 6), 1.0]
    corrected = [0.0, 0.0, 0.0, *([0.0] * 6), 1.0]
    return {
        "pair_id": f"pair-{seed}",
        "scene_seed": seed,
        "perturbed_nominal": nominal,
        "residual_target": [
            target - source
            for source, target in zip(nominal, corrected)
        ],
        "corrected_action": corrected,
        "physical_correction_evidence": {
            "independent_executions": True,
            "perturbed_evidence_path": "/remote/perturbed.json",
            "perturbed_evidence_sha256": "c" * 64,
            "corrected_evidence_path": "/remote/corrected.json",
            "corrected_evidence_sha256": "d" * 64,
            "policy_input_simulator_truth": False,
        },
        "teacher_used": False,
        "dimension_names": [
            "dx",
            "dy",
            "dz",
            "r6d_0",
            "r6d_1",
            "r6d_2",
            "r6d_3",
            "r6d_4",
            "r6d_5",
            "gripper",
        ],
        "correction_physically_successful": True,
    }


def _sample(seed: int, offset: tuple[float, float, float]):
    return residual_sample(
        _pair(seed, offset),
        _payload(),
        rgb_uri=f"dataset://residual/{seed}/rgb.png",
        depth_uri=f"dataset://residual/{seed}/depth.npy",
    )


def _residual_seed_report(seed: int, beats_zero: bool) -> dict:
    return {
        "schema_version": "M2BMaskedResidualMLPReportV1",
        "seed": seed,
        "dataset_sha256": "a" * 64,
        "eval_split": "val",
        "failure_context": "on",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "validation": {"formal_evaluation_ready": True},
        "beats_zero_residual": beats_zero,
        "model_metrics": {
            "mae": 0.001,
            "rmse": 0.002,
            "mean_l1_per_chunk": 0.003,
        },
        "zero_residual_baseline": {
            "mae": 0.004,
            "rmse": 0.005,
            "mean_l1_per_chunk": 0.012,
        },
    }


def test_residual_converter_supervises_only_physical_translation() -> None:
    sample = _sample(4025, (0.006, -0.002, 0.003))
    assert sample.residual_action_chunk.values == [
        [-0.006, 0.002, -0.003, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ]
    assert sample.residual_action_chunk.action_mask == [
        [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ]
    assert sample.nominal_action_chunk.fps == 1.0
    assert sample.observation.camera_extrinsics_base_T_cam == []
    assert sample.provenance["base_to_camera_extrinsics"] == (
        "ABSENT_NOT_GUESSED"
    )
    assert sample.simulator_supervision["training_and_evaluation_only"] is True


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"teacher_used": True}, "no explicit no-Teacher"),
        ({"corrected_action": [1.0] * 10}, "does not reconstruct"),
    ],
)
def test_residual_converter_rejects_untrusted_pair(
    mutation: dict, message: str
) -> None:
    pair = _pair(4025, (0.006, -0.002, 0.003))
    pair.update(mutation)
    with pytest.raises(ValueError, match=message):
        _validate_pair(pair)


def test_masked_metrics_ignore_unsupervised_outputs() -> None:
    target = np.asarray([[[-0.01, 0.002, 0.0, *([0.0] * 7)]]])
    prediction = target.copy()
    prediction[..., 3:] = 100.0
    mask = np.asarray([[[1.0, 1.0, 1.0, *([0.0] * 7)]]])
    metrics = masked_metrics(prediction, target, mask)
    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert set(metrics["per_axis"]) == {"dx", "dy", "dz"}
    assert metrics["target_exact_zero_value_fraction"] == 1 / 3
    assert metrics["prediction_near_zero_chunk_fraction"] == 0.0


def test_masked_trainer_uses_train_and_evaluates_heldout() -> None:
    train = [
        _sample(seed, (x, y, z))
        for seed, x, y, z in (
            (4000, 0.006, -0.002, 0.003),
            (4001, -0.006, 0.002, -0.003),
            (4002, 0.010, 0.004, 0.002),
            (4003, -0.006, 0.002, -0.003),
        )
    ]
    heldout = [_sample(4005, (0.008, -0.003, 0.002))]
    assert all(sample.split == "train" for sample in train)
    assert heldout[0].split == "val"
    validation = validate_samples([*train, *heldout], eval_split="val")
    assert validation["findings"] == []
    assert validation["formal_evaluation_ready"] is False
    _, _, _, mask = sample_tensors(train, use_failure_context=True)
    assert np.all(mask[..., :3] == 1.0)
    assert np.all(mask[..., 3:] == 0.0)
    model, history = train_masked_mlp(
        train,
        use_failure_context=True,
        seed=7,
        epochs=1000,
        learning_rate=0.1,
        batch_size=4,
        hidden=64,
    )
    model_metrics, zero_metrics = evaluate(
        model, heldout, use_failure_context=True
    )
    context, nominal, _, _ = sample_tensors(
        heldout, use_failure_context=True
    )
    assert np.all(model.forward(context, nominal)[..., 3:] == 0.0)
    assert history[-1]["masked_mse"] < history[0]["masked_mse"]
    assert model_metrics["mae"] < zero_metrics["mae"]


def test_residual_summary_requires_two_formal_consistent_seeds() -> None:
    passed = summarize(
        [_residual_seed_report(1, True), _residual_seed_report(2, True)]
    )
    assert passed["mlp_residual_supported_offline"] is True
    failed = summarize(
        [_residual_seed_report(1, True), _residual_seed_report(2, False)]
    )
    assert failed["mlp_residual_supported_offline"] is False
    assert failed["formal_two_seed_evaluation"] is True


def test_formal_negative_mlp_summary_is_a_completed_experiment(
    tmp_path,
) -> None:
    project = Path(__file__).resolve().parents[2]
    reports = []
    for seed, beats_zero in ((1, True), (2, False)):
        path = tmp_path / f"{seed}.json"
        path.write_text(
            json.dumps(_residual_seed_report(seed, beats_zero))
        )
        reports.extend(["--seed-report", str(path)])
    output = tmp_path / "summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(project / "scripts/m2b/summarize_residual_mlp.py"),
            *reports,
            "--report",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=project,
    )
    payload = json.loads(output.read_text())
    assert completed.returncode == 0
    assert payload["formal_two_seed_evaluation"] is True
    assert payload["mlp_residual_supported_offline"] is False
