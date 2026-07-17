from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from xh_agent.grasp.non_oracle_broker import NonOracleGraspBroker
from xh_agent.perception.evaluator import SimulatorLabel, evaluate
from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline
from xh_agent.perception.interfaces import PerceptionInputV1
from xh_agent.perception.pose_state import orientation_state
from xh_agent.recording.episode_recorder import EpisodeRecorder


def observation() -> PerceptionInputV1:
    return PerceptionInputV1(frame_id="frame-1", timestamp_ns=1, rgb_uri="rgb.png", depth_uri="depth.npy", camera_intrinsics=[100.0, 0, 5.0, 0, 100.0, 5.0, 0, 0, 1], camera_frame="camera_rgbd")


def test_geometric_baseline_backprojects_and_excludes_oracle() -> None:
    depth = np.ones((12, 12), dtype=float)
    depth[3:8, 2:7] = 0.8
    results = GeometricRGBDBaseline(min_component_pixels=12).infer(observation(), depth)
    assert len(results) == 1
    assert results[0].position_3d[2] == pytest.approx(0.8)
    assert results[0].track_id.startswith("track-")
    assert "entity" not in results[0].model_dump_json()


def test_online_input_and_result_reject_oracle_or_nan() -> None:
    data = observation().model_dump()
    data["perfect_object_poses"] = {"x": [0]}
    with pytest.raises(ValidationError):
        PerceptionInputV1.model_validate(data)
    with pytest.raises(ValueError):
        GeometricRGBDBaseline().infer(observation(), np.array([[float("nan")]]))


def test_geometric_baseline_treats_partial_depth_dropout_as_background() -> None:
    depth = np.ones((12, 12), dtype=float)
    depth[3:8, 2:7] = 0.8
    depth[0, 0] = float("nan")
    assert len(GeometricRGBDBaseline(min_component_pixels=12).infer(observation(), depth)) == 1


def test_geometric_baseline_removes_a_sloped_table_plane() -> None:
    rows, cols = np.indices((40, 40))
    table = 1.0 + rows * 0.004 + cols * 0.001
    depth = table.copy()
    depth[12:22, 15:25] -= 0.08
    results = GeometricRGBDBaseline(min_component_pixels=20).infer(observation(), depth)
    assert len(results) == 1
    assert results[0].bbox_or_mask.width == 10


def test_geometric_baseline_uses_aligned_rgb_to_reject_blue_fixture_regions() -> None:
    depth = np.ones((30, 30), dtype=float)
    rgb = np.full((30, 30, 3), 120, dtype=np.uint8)
    rgb[4:14, 3:13] = [255, 0, 0]
    rgb[4:20, 16:29] = [0, 0, 255]
    results = GeometricRGBDBaseline(min_component_pixels=12).infer(observation(), depth, rgb)
    assert len(results) == 1
    assert results[0].bbox_or_mask.width == 10


def test_pose_state_and_offline_evaluator() -> None:
    assert orientation_state(0.02, 0.08) == "tilted"
    depth = np.ones((12, 12), dtype=float)
    depth[3:8, 2:7] = 0.8
    prediction = GeometricRGBDBaseline(min_component_pixels=12).infer(observation(), depth)[0]
    metrics = evaluate([prediction], [SimulatorLabel("private_entity", tuple(prediction.position_3d), prediction.orientation_state)])
    assert metrics["position_median_error_m"] == 0


def test_recorder_keeps_supervision_separate(tmp_path: Path) -> None:
    recorder = EpisodeRecorder("episode", 4)
    recorder.add(1, "rgb", "rgb.png")
    recorder.add(2, "depth", "depth.npy")
    recorder.write(tmp_path / "timeline.json")
    with pytest.raises(ValueError):
        recorder.add(3, "simulator_supervision", "truth.json")
    assert json.loads((tmp_path / "timeline.json").read_text())["scene_seed"] == 4


def test_broker_never_returns_entity_to_high_level() -> None:
    feedback, supervision = NonOracleGraspBroker().route_contact(contacted_entity="gazebo_cylinder_1", contact_verified=True, carried_track_id="track-deadbeef")
    assert feedback.carried_track_id == "track-deadbeef"
    assert not hasattr(feedback, "actual_sim_entity_id")
    assert supervision["actual_sim_entity_id"] == "gazebo_cylinder_1"


def test_dataset_split_is_seed_disjoint_and_has_30_heldout(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    subprocess.run(["python3", "scripts/generate_perception_dataset.py", "--count", "200", "--output", str(output)], check=True)
    samples = json.loads(output.read_text())["samples"]
    seeds = {split: {sample["seed"] for sample in samples if sample["split"] == split} for split in ("train", "val", "test")}
    assert not (seeds["train"] & seeds["val"] or seeds["train"] & seeds["test"] or seeds["val"] & seeds["test"])
    assert len(seeds["test"]) >= 30


def test_random_scene_generator_makes_seed_specific_six_to_twelve_part_scenes(tmp_path: Path) -> None:
    output = tmp_path / "scenes"
    subprocess.run([sys.executable, "scripts/generate_industrial_scenes.py", "--count", "150", "--output-dir", str(output)], check=True)
    labels = json.loads((output / "scene-1000.supervision.json").read_text())
    assert 6 <= labels["part_count"] <= 12
    assert labels["simulator_supervision"]["training_and_evaluation_only"] is True
    assert not (output / "scene-1000.sdf").read_text().count("M1B_RANDOM_PARTS_BEGIN") > 1


def test_captured_manifest_excludes_incomplete_frames(tmp_path: Path) -> None:
    root = tmp_path / "generated"
    frame = root / "frames" / "1000"
    scene = root / "scenes"
    frame.mkdir(parents=True)
    scene.mkdir()
    for name in ("rgb.ppm", "depth.bin", "camera_info.json"):
        (frame / name).write_text("x")
    (frame / "recording.json").write_text(json.dumps({"rgb": {"uri": "rgb.ppm"}, "depth": {"uri": "depth.bin"}, "camera_info": {"uri": "camera_info.json"}, "max_stream_skew_ns": 0}))
    (scene / "scene-1000.supervision.json").write_text(json.dumps({"split": "train"}))
    output = tmp_path / "manifest.json"
    subprocess.run([sys.executable, "scripts/build_captured_dataset_manifest.py", "--root", str(root), "--output", str(output)], check=True)
    assert json.loads(output.read_text())["counts"]["train"] == 1
