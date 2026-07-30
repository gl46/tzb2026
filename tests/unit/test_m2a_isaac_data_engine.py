from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

from qrm_lite.summarize_isaac_closed_loop import main as summarize_closed_loop
from qrm_lite.train_qwen_coarse_beta import classification_metrics
from isaac.run_pilot_campaign import (
    prior_worker_order_swapped,
    quarantine_failed_run,
    sha256,
    valid_prior,
)
from xh_agent.data_engine.isaac.contract import (
    ShardState,
    audit_policy_projection,
    canonical_json_sha256,
    stable_split,
    transition_shard_state,
    validate_episode,
)
from xh_agent.policy.qrm_lite.residual_safety import ResidualSafetyFilter
from run_isaac_m1b_dual_benchmark import _worker_command


def _action(width: int = 10) -> dict:
    return {
        "coordinate_frame": "camera_optical",
        "units": "m_rad_norm",
        "frequency_hz": 5.0,
        "chunk_length": 1,
        "dimension_names": [f"d{i}" for i in range(width)],
        "normalization_revision": "test-v1",
        "values": [[0.0] * width],
    }


def _episode() -> dict:
    observation = {
        "episode_id": "isaac-s3100-w0-t000000",
        "step_id": 0,
        "timestamp_ns": 1,
        "rgb_uri": "dataset://shard-00000.READY/media/e/rgb.png",
        "depth_uri": "dataset://shard-00000.READY/media/e/depth.npy",
        "object_tracks": [{"object_id": "track-000", "pose": [0.0] * 7}],
    }
    after = json.loads(json.dumps(observation))
    after["step_id"] = 1
    after["timestamp_ns"] = 2
    split, kind = stable_split(3100)
    return {
        "schema_version": "IsaacIndustrialEpisodeV1",
        "dataset_version": "isaac-industrial-v1-pilot",
        "episode_id": observation["episode_id"],
        "scene_seed": 3100,
        "scene_group_id": "isaac-scene-3100",
        "split": split,
        "split_kind": kind,
        "worker_id": 0,
        "code_revision": "a" * 40,
        "isaac_version": "6.0.1",
        "scene_asset_revision": "b" * 64,
        "config_hash": "c" * 64,
        "observation_before": observation,
        "observation_after": after,
        "task_spec": {"target_object_id": "track-000"},
        "robot_state": {},
        "skill_history": [],
        "failure_context": {"failure_type": "NONE"},
        "nominal_skill": "APPROACH",
        "nominal_action": _action(),
        "executed_action": _action(9),
        "residual_action": _action(),
        "expected_predicates": [],
        "observed_predicates": [],
        "recovery_sequence": [],
        "result": {},
        "simulator_supervision": {
            "training_and_evaluation_only": True,
            "perfect_object_poses": {"cylinder_01": [0.0] * 7},
        },
        "provenance": {},
    }


def test_supervision_entity_truth_is_not_scanned_as_policy_input() -> None:
    assert validate_episode(_episode()) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("prim_path", "/World/M1B/cylinder_01"),
        ("entity_name", "cylinder_01"),
        ("success_oracle", True),
    ],
)
def test_oracle_policy_keys_are_rejected(key: str, value: object) -> None:
    assert audit_policy_projection({"observation": {key: value}})


def test_entity_truth_encoded_in_track_id_is_rejected() -> None:
    assert audit_policy_projection({"track_id": "/World/M1B/cylinder_07"})


def test_public_track_id_is_accepted() -> None:
    assert audit_policy_projection({"track_id": "track-42"}) == []


def test_shard_state_machine_is_fail_closed() -> None:
    assert transition_shard_state("WRITING", "VALIDATING") is ShardState.VALIDATING
    assert transition_shard_state("VALIDATING", "READY") is ShardState.READY
    with pytest.raises(ValueError):
        transition_shard_state("WRITING", "READY")
    with pytest.raises(ValueError):
        transition_shard_state("READY", "WRITING")


def test_scene_seed_split_is_stable_and_group_level() -> None:
    assert stable_split(3100) == stable_split(3100)
    assert stable_split(3114)[0] == "val"
    assert stable_split(3117)[0] == "test"


def test_action_nan_is_rejected() -> None:
    episode = _episode()
    episode["residual_action"]["values"][0][0] = float("nan")
    assert "residual_action contains NaN/Inf" in validate_episode(episode)


def test_manifest_hash_is_order_independent() -> None:
    assert canonical_json_sha256({"a": 1, "b": 2}) == canonical_json_sha256(
        {"b": 2, "a": 1}
    )


def test_mlp_residual_is_clipped_and_moveit_rejection_falls_back() -> None:
    nominal = np.zeros((4, 10))
    raw = np.ones((4, 10))
    result = ResidualSafetyFilter().combine_and_filter(
        nominal,
        raw,
        moveit_accept_fn=lambda _: (False, "collision"),
    )
    assert result.outcome == "fallback_to_nominal"
    assert np.array_equal(result.final_candidate, nominal)
    assert np.max(np.abs(result.residual_clipped[:, :3])) <= 0.03


def test_nonfinite_model_output_is_rejected() -> None:
    with pytest.raises(ValueError, match="NaN/Inf"):
        ResidualSafetyFilter().combine_and_filter(
            np.zeros((4, 10)),
            np.full((4, 10), np.nan),
        )


def test_closed_loop_worker_mounts_checkpoint_read_only() -> None:
    args = Namespace(
        worker_sdf=["scene-1.sdf", "scene-2.sdf"],
        worker_supervision=["scene-1.json", "scene-2.json"],
        container_prefix="test",
        project_root=Path("/project"),
        source_root=Path("/source"),
        image="isaac:6",
        frames=6,
        warmup_frames=1,
        timeout_s=10.0,
        qrm_checkpoint=Path("/checkpoints/Q2.npz"),
        qrm_model_id="Q2_COARSE_MLP_FAILURE_CONTEXT",
    )
    command = _worker_command(
        args,
        worker_id=0,
        gpu_index=0,
        worker_output=Path("/output"),
        control=Path("/control"),
    )
    assert "/checkpoints:/workspace/qrm:ro" in command
    assert "--qrm-checkpoint" in command
    assert "/workspace/qrm/Q2.npz" in command


def test_closed_loop_summary_counts_scene_episodes_not_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_roots = [tmp_path / "run-a", tmp_path / "run-b"]
    for run_root in run_roots:
        run_root.mkdir()
        (run_root / "dual-benchmark-summary.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "qrm_closed_loop_smoke": {
                        "model_id": "Q2_COARSE_MLP_FAILURE_CONTEXT"
                    },
                }
            )
        )
        for worker_id in range(2):
            output = run_root / f"worker{worker_id}" / "output"
            output.mkdir(parents=True)
            decisions = [
                {
                    "applies_to_step": 1,
                    "coarse_skill": "REOBSERVE",
                    "used_failure_context": True,
                    "residual_proposed": True,
                },
                {
                    "applies_to_step": None,
                    "coarse_skill": "REOBSERVE",
                    "used_failure_context": True,
                    "residual_proposed": True,
                },
            ]
            (output / "metrics.json").write_text(
                json.dumps({"qrm_closed_loop_smoke": {"decisions": decisions}})
            )
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "summarize_isaac_closed_loop.py",
            "--run-root",
            str(run_roots[0]),
            "--run-root",
            str(run_roots[1]),
            "--report-json",
            str(report_json),
            "--report-md",
            str(report_md),
        ],
    )
    assert summarize_closed_loop() == 0
    report = json.loads(report_json.read_text())
    assert report["closed_loop_episodes"] == 4
    assert report["applied_live_decisions"] == 4
    assert report["live_qrm_decisions"] == 8


def test_campaign_resume_never_overwrites_prior_quarantine(tmp_path: Path) -> None:
    run_root = tmp_path / "seeds-3110-3111"
    run_root.mkdir()
    first = quarantine_failed_run(run_root, attempt=2)
    assert first.name.endswith("attempt-02")
    run_root.mkdir()
    resumed = quarantine_failed_run(run_root, attempt=2)
    assert resumed.name.endswith("attempt-03")
    assert first.is_dir()
    assert resumed.is_dir()


def test_campaign_accepts_hash_valid_swapped_worker_assignment(
    tmp_path: Path,
) -> None:
    expected = [tmp_path / f"source-{index}" for index in range(4)]
    for index, path in enumerate(expected):
        path.write_text(str(index))
    run_root = tmp_path / "seeds-3122-3123"
    for worker_id in range(2):
        output = run_root / f"worker{worker_id}" / "output"
        output.mkdir(parents=True)
        (output / "metrics.json").write_text("{}")
    (run_root / "dual-benchmark-summary.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "worker_sources": [
                    {
                        "sdf_sha256": sha256(expected[2]),
                        "supervision_sha256": sha256(expected[3]),
                    },
                    {
                        "sdf_sha256": sha256(expected[0]),
                        "supervision_sha256": sha256(expected[1]),
                    },
                ],
            }
        )
    )
    assert valid_prior(run_root, expected)
    assert prior_worker_order_swapped(run_root, expected)


def test_single_worker_uses_the_validated_start_barrier() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "isaac" / "launch_worker.py"
    ).read_text()
    assert '"--ready-file", "/workspace/output/control/worker.READY"' in source
    assert '"--start-file", "/workspace/output/control/START"' in source
    assert "while not ready.is_file():" in source
    assert "start.touch()" in source


def test_worker_benchmark_retries_and_quarantines_infrastructure_failures() -> None:
    source = (
        Path(__file__).parents[2] / "scripts" / "isaac" / "benchmark_workers.sh"
    ).read_text()
    assert 'MAX_ATTEMPTS="${ISAAC_BENCHMARK_MAX_ATTEMPTS:-6}"' in source
    assert "quarantine_failed single" not in source
    assert 'quarantine_failed "$label" "$attempt"' in source
    assert "quarantine_failed dual" in source
    assert "run_single single-gpu0" in source
    assert "run_single single-gpu1" in source


def test_qwen_metrics_retain_absent_class_as_zero_f1() -> None:
    metrics = classification_metrics(
        ["REOBSERVE", "REOBSERVE"],
        ["REOBSERVE", "REOBSERVE"],
        ["APPROACH", "REOBSERVE"],
    )
    assert metrics["accuracy"] == 1.0
    assert metrics["per_class"]["APPROACH"]["support"] == 0
    assert metrics["per_class"]["APPROACH"]["f1"] == 0.0
    assert metrics["macro_f1"] == 0.5
