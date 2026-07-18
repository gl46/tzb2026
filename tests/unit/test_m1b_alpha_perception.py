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
from xh_agent.perception.tracker import PublicTrackAssociator
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


def test_public_temporal_tracker_survives_bounded_rgbd_motion_without_entity_ids() -> None:
    tracker = PublicTrackAssociator(maximum_association_distance_m=0.05)
    initial = tracker.associate([([0.10, -0.02, 1.00], "industrial_cylinder", "red")], timestamp_ns=1)
    moved = tracker.associate([([0.11, -0.018, 1.004], "industrial_cylinder", "red")], timestamp_ns=2)
    distinct = tracker.associate([([0.11, -0.018, 1.004], "industrial_cylinder", "blue")], timestamp_ns=3)
    assert initial == moved
    assert distinct[0] != initial[0]


def test_geometric_baseline_keeps_track_id_across_small_public_frame_shift() -> None:
    first = np.ones((24, 24), dtype=float)
    first[6:16, 5:15] = 0.8
    second = np.ones((24, 24), dtype=float)
    second[6:16, 6:16] = 0.8
    baseline = GeometricRGBDBaseline(min_component_pixels=12)
    initial = baseline.infer(observation(), first)[0]
    later = baseline.infer(observation().model_copy(update={"timestamp_ns": 2}), second)[0]
    assert later.track_id == initial.track_id
    assert "public_temporal_tracker_v1" in later.source_components


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
    depth[4:14, 3:13] = 0.8
    rgb = np.full((30, 30, 3), 120, dtype=np.uint8)
    rgb[4:14, 3:13] = [255, 0, 0]
    rgb[4:20, 16:29] = [0, 0, 255]
    results = GeometricRGBDBaseline(min_component_pixels=12).infer(observation(), depth, rgb)
    assert len(results) == 1
    assert results[0].bbox_or_mask.width == 10


def test_color_prototypes_keep_adjacent_differently_colored_objects_separate() -> None:
    depth = np.ones((30, 30), dtype=float)
    depth[5:15, 4:14] = 0.8
    depth[5:15, 14:24] = 0.8
    rgb = np.full((30, 30, 3), 120, dtype=np.uint8)
    rgb[5:15, 4:14] = [220, 30, 30]
    rgb[5:15, 14:24] = [30, 190, 60]
    results = GeometricRGBDBaseline(min_component_pixels=12).infer(observation(), depth, rgb)
    assert len(results) == 2
    assert {result.attributes["visual_color"] for result in results} == {"red", "green"}
    assert all("color_prototype_v1" in result.source_components for result in results)


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
    positions = [item["position_3d_world"][:2] for item in labels["simulator_supervision"]["objects"]]
    assert all((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2 >= 0.09 ** 2 for index, first in enumerate(positions) for second in positions[index + 1:])
    by_orientation = {item["orientation_state"]: item["position_3d_world"][2] for item in labels["simulator_supervision"]["objects"]}
    assert min(by_orientation.values()) > 0.45
    assert by_orientation["tilted"] > by_orientation["normal"]
    scene = (output / "scene-1000.sdf").read_text()
    assert "/xh/actuation_internal/cylinders/cylinder_01/contacts" in scene
    assert 'type="contact"' in scene
    assert "<velocity_decay><linear>0.5</linear><angular>0.5</angular></velocity_decay>" in scene
    normal_output = tmp_path / "normal-scenes"
    subprocess.run([sys.executable, "scripts/generate_industrial_scenes.py", "--count", "150", "--orientation-mode", "normal", "--output-dir", str(normal_output)], check=True)
    normal_labels = json.loads((normal_output / "scene-1000.supervision.json").read_text())
    assert {item["orientation_state"] for item in normal_labels["simulator_supervision"]["objects"]} == {"normal"}


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


def test_open_vocab_cli_has_a_dependency_free_help_path() -> None:
    subprocess.run([sys.executable, "scripts/run_open_vocab.py", "--help"], check=True, stdout=subprocess.DEVNULL)


def test_geometric_evaluator_cli_has_a_help_path() -> None:
    subprocess.run([sys.executable, "scripts/evaluate_captured_geometric.py", "--help"], check=True, stdout=subprocess.DEVNULL)


def test_color_prototype_calibration_cli_has_a_help_path() -> None:
    subprocess.run([sys.executable, "scripts/train_perception.py", "--help"], check=True, stdout=subprocess.DEVNULL)
