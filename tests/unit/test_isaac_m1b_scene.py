from pathlib import Path

import pytest

from xh_agent.data.isaac_m1b import (
    M1B_SDF_SHA256,
    M1B_URDF_SHA256,
    OFFICIAL_ISAAC_FRANKA_RELATIVE_USD,
    load_m1b_isaac_scene,
    resolve_official_franka_asset,
    scene_primitive_count,
    verify_source_hashes,
)


ROOT = Path(__file__).parents[2]
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
        visual = cylinder.links[0].visuals[0]
        assert visual.shape == "cylinder"
        assert visual.radius == pytest.approx(0.015)
        assert visual.length == pytest.approx(0.08)


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
