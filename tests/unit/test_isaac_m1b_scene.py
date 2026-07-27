import json
from pathlib import Path
import sys

import pytest

from xh_agent.data.isaac_m1b import (
    M1B_SDF_SHA256,
    M1B_URDF_SHA256,
    OFFICIAL_ISAAC_FRANKA_RELATIVE_USD,
    load_m1b_isaac_generated_scene,
    load_m1b_isaac_scene,
    load_robot_base_pose,
    resolve_official_franka_asset,
    scene_collision_primitive_count,
    scene_primitive_count,
    validate_m1b_physics_contract,
    verify_source_hashes,
)


ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from generate_industrial_scenes import render  # noqa: E402

SDF = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
URDF = ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"


def test_isaac_m1b_adapter_is_hash_bound_to_accepted_sources() -> None:
    assert verify_source_hashes(SDF, URDF) == {
        "industrial_cylinder_v1.sdf": M1B_SDF_SHA256,
        "panda_controlled.urdf": M1B_URDF_SHA256,
    }


def test_isaac_m1b_adapter_preserves_scene_geometry_and_camera_contract() -> None:
    scene = load_m1b_isaac_scene(SDF)

    assert scene.cylinder_count == 6
    assert len(scene.models) == 10
    assert scene_primitive_count(scene.models) == 13
    assert scene_collision_primitive_count(scene.models) == 8
    assert [camera.name for camera in scene.cameras] == [
        "front_rgbd",
        "overhead_rgbd",
        "side_rgbd",
    ]
    assert scene.cameras[0].position == (0.8, 0.8, 1.4)
    assert "ROTATED_180_DEG" in scene.cameras[0].provenance
    assert all(camera.resolution == (640, 480) for camera in scene.cameras)
    cylinders = [model for model in scene.models if model.semantic_class == "industrial_cylinder"]
    for cylinder in cylinders:
        assert cylinder.static is False
        visual = cylinder.links[0].visuals[0]
        collision = cylinder.links[0].collisions[0]
        assert visual.shape == "cylinder"
        assert visual.radius == pytest.approx(0.015)
        assert visual.length == pytest.approx(0.08)
        assert collision.shape == visual.shape
        assert collision.radius == visual.radius
        assert collision.length == visual.length
        assert cylinder.links[0].mass_kg == pytest.approx(0.045)

    table = next(model for model in scene.models if model.name == "industrial_work_table")
    assert table.static is True
    assert table.links[0].collisions[0].size == (1.5, 1.0, 0.1)

    partition_bin = next(model for model in scene.models if model.name == "blue_partition_bin")
    assert partition_bin.static is True
    assert partition_bin.pose.xyz == (0.2, 0.15, 0.45)
    assert [collision.name for collision in partition_bin.links[0].collisions] == ["floor"]

    physics = validate_m1b_physics_contract(scene)
    assert physics["dynamic_model_count"] == 6
    assert physics["collision_primitive_count"] == 8
    assert physics["static_collision_model_names"] == (
        "industrial_work_table",
        "blue_partition_bin",
    )
    assert set(physics["cylinder_masses_kg"].values()) == {0.045}


def test_isaac_m1b_adapter_fails_closed_if_source_changes(tmp_path: Path) -> None:
    changed = tmp_path / "industrial_cylinder_v1.sdf"
    changed.write_text(SDF.read_text().replace("0.015", "0.016", 1))

    with pytest.raises(ValueError, match="hash mismatch"):
        load_m1b_isaac_scene(changed)


def test_official_isaac_franka_asset_is_fixed_and_resolved_from_assets_root() -> None:
    assert (
        OFFICIAL_ISAAC_FRANKA_RELATIVE_USD
        == "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
    )
    assert resolve_official_franka_asset("https://assets.example/Isaac/6.0/") == (
        "https://assets.example/Isaac/6.0/"
        "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
    )
    with pytest.raises(ValueError, match="assets root is empty"):
        resolve_official_franka_asset(" ")


def test_official_franka_uses_hash_bound_production_robot_base_pose() -> None:
    pose = load_robot_base_pose(URDF)
    assert pose.xyz == (-0.35, 0.0, 0.45)
    assert pose.rpy == (0.0, 0.0, 0.0)


def test_generated_scene_loader_binds_canonical_objects_and_supervision(
    tmp_path: Path,
) -> None:
    generated_sdf, supervision = render(SDF.read_text(), 3001)
    sdf_path = tmp_path / "scene-3001.sdf"
    supervision_path = tmp_path / "scene-3001.supervision.json"
    sdf_path.write_text(generated_sdf)
    supervision_path.write_text(json.dumps(supervision))

    scene = load_m1b_isaac_generated_scene(sdf_path, supervision_path)

    assert scene.scene_seed == 3001
    assert scene.source_supervision_sha256 is not None
    assert 6 <= scene.cylinder_count <= 12
    assert [model.name for model in scene.dynamic_models] == [
        f"cylinder_{index:02d}" for index in range(1, scene.cylinder_count + 1)
    ]


def test_generated_scene_loader_rejects_sdf_supervision_mismatch(
    tmp_path: Path,
) -> None:
    generated_sdf, supervision = render(SDF.read_text(), 3001)
    supervision["simulator_supervision"]["objects"][0]["actual_sim_entity_id"] = "cylinder_99"
    sdf_path = tmp_path / "scene-3001.sdf"
    supervision_path = tmp_path / "scene-3001.supervision.json"
    sdf_path.write_text(generated_sdf)
    supervision_path.write_text(json.dumps(supervision))

    with pytest.raises(ValueError, match="not canonical"):
        load_m1b_isaac_generated_scene(sdf_path, supervision_path)
