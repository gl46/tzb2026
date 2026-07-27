from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


M1B_SDF_SHA256 = "6193afa73331afa7409ab42256a716a47bd686b3ecd55098e60e7687bc6058bd"
M1B_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
OFFICIAL_ISAAC_FRANKA_RELATIVE_USD = (
    "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
)


@dataclass(frozen=True)
class Pose:
    xyz: tuple[float, float, float]
    rpy: tuple[float, float, float]


@dataclass(frozen=True)
class VisualPrimitive:
    name: str
    shape: str
    pose: Pose
    size: tuple[float, float, float] | None
    radius: float | None
    length: float | None
    color_rgba: tuple[float, float, float, float]


@dataclass(frozen=True)
class LinkVisuals:
    name: str
    pose: Pose
    visuals: tuple[VisualPrimitive, ...]


@dataclass(frozen=True)
class SceneModel:
    name: str
    pose: Pose
    semantic_class: str
    links: tuple[LinkVisuals, ...]


@dataclass(frozen=True)
class CameraSpec:
    name: str
    position: tuple[float, float, float]
    look_at: tuple[float, float, float]
    resolution: tuple[int, int]
    provenance: str


@dataclass(frozen=True)
class M1BIsaacScene:
    models: tuple[SceneModel, ...]
    cameras: tuple[CameraSpec, ...]
    source_sdf_sha256: str

    @property
    def cylinder_count(self) -> int:
        return sum(model.semantic_class == "industrial_cylinder" for model in self.models)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_hashes(sdf_path: str | Path, urdf_path: str | Path) -> dict[str, str]:
    observed = {
        "industrial_cylinder_v1.sdf": sha256_file(sdf_path),
        "panda_controlled.urdf": sha256_file(urdf_path),
    }
    expected = {
        "industrial_cylinder_v1.sdf": M1B_SDF_SHA256,
        "panda_controlled.urdf": M1B_URDF_SHA256,
    }
    if observed != expected:
        raise ValueError(f"M1B Isaac source hash mismatch: observed={observed}, expected={expected}")
    return observed


def resolve_official_franka_asset(assets_root: str) -> str:
    root = assets_root.strip()
    if not root:
        raise ValueError("Isaac assets root is empty")
    return f"{root.rstrip('/')}/{OFFICIAL_ISAAC_FRANKA_RELATIVE_USD}"


def parse_pose(text: str | None) -> Pose:
    values = [float(value) for value in (text or "0 0 0 0 0 0").split()]
    if len(values) != 6:
        raise ValueError(f"expected six SDF pose values, got {values}")
    return Pose(tuple(values[:3]), tuple(values[3:]))


def _parse_color(visual: ET.Element) -> tuple[float, float, float, float]:
    diffuse = visual.findtext("./material/diffuse", default="0.7 0.7 0.7 1")
    values = tuple(float(value) for value in diffuse.split())
    if len(values) != 4:
        raise ValueError(f"expected RGBA color, got {values}")
    return values


def _parse_visual(visual: ET.Element) -> VisualPrimitive:
    geometry = visual.find("geometry")
    if geometry is None:
        raise ValueError(f"visual {visual.get('name')} has no geometry")
    box = geometry.find("box")
    cylinder = geometry.find("cylinder")
    if box is not None:
        size = tuple(float(value) for value in box.findtext("size", default="").split())
        if len(size) != 3:
            raise ValueError(f"box visual {visual.get('name')} has invalid size {size}")
        shape, radius, length = "box", None, None
    elif cylinder is not None:
        size = None
        radius = float(cylinder.findtext("radius", default="nan"))
        length = float(cylinder.findtext("length", default="nan"))
        if not math.isfinite(radius) or not math.isfinite(length):
            raise ValueError(f"cylinder visual {visual.get('name')} has invalid dimensions")
        shape = "cylinder"
    else:
        raise ValueError(f"unsupported visual geometry in {visual.get('name')}")
    return VisualPrimitive(
        name=visual.get("name", "visual"),
        shape=shape,
        pose=parse_pose(visual.findtext("pose")),
        size=size,
        radius=radius,
        length=length,
        color_rgba=_parse_color(visual),
    )


def _semantic_class(model_name: str) -> str | None:
    if model_name == "industrial_work_table":
        return "work_table"
    if model_name.startswith("incoming_zone_"):
        return "incoming_zone"
    if model_name.startswith("cylinder_"):
        return "industrial_cylinder"
    if model_name == "blue_partition_bin":
        return "partition_bin"
    return None


def _parse_models(world: ET.Element) -> tuple[SceneModel, ...]:
    models: list[SceneModel] = []
    for model in world.findall("model"):
        name = model.get("name", "")
        semantic_class = _semantic_class(name)
        if semantic_class is None:
            continue
        links: list[LinkVisuals] = []
        for link in model.findall("link"):
            visuals = tuple(_parse_visual(visual) for visual in link.findall("visual"))
            if visuals:
                links.append(
                    LinkVisuals(
                        name=link.get("name", "link"),
                        pose=parse_pose(link.findtext("pose")),
                        visuals=visuals,
                    )
                )
        if not links:
            raise ValueError(f"M1B model {name} has no supported visual geometry")
        models.append(
            SceneModel(
                name=name,
                pose=parse_pose(model.findtext("pose")),
                semantic_class=semantic_class,
                links=tuple(links),
            )
        )
    return tuple(models)


def _parse_cameras(world: ET.Element) -> tuple[CameraSpec, ...]:
    fixture = world.find("./model[@name='camera_fixture']/link[@name='camera_rgbd']")
    if fixture is None:
        raise ValueError("M1B source SDF has no camera_fixture/camera_rgbd")
    source_pose = parse_pose(fixture.findtext("pose"))
    sensor = fixture.find("./sensor[@name='front_rgbd']/camera/image")
    if sensor is None:
        raise ValueError("M1B source SDF has no front_rgbd image specification")
    resolution = (
        int(sensor.findtext("width", default="0")),
        int(sensor.findtext("height", default="0")),
    )
    look_at = (-0.05, 0.0, 0.55)
    return (
        CameraSpec(
            name="front_rgbd",
            position=(-source_pose.xyz[0], -source_pose.xyz[1], source_pose.xyz[2]),
            look_at=look_at,
            resolution=resolution,
            provenance=(
                "M1B_SOURCE_FIXTURE_ROTATED_180_DEG_ABOUT_TARGET_PER_REVIEW_"
                "DATASET_VIEW_NOT_POLICY_INPUT"
            ),
        ),
        CameraSpec(
            name="overhead_rgbd",
            position=(-0.05, 0.0, 1.70),
            look_at=(-0.05, 0.0, 0.45),
            resolution=resolution,
            provenance="ISAAC_DATASET_AUXILIARY_NOT_POLICY_INPUT",
        ),
        CameraSpec(
            name="side_rgbd",
            position=(0.65, -0.75, 1.05),
            look_at=look_at,
            resolution=resolution,
            provenance="ISAAC_DATASET_AUXILIARY_NOT_POLICY_INPUT",
        ),
    )


def load_m1b_isaac_scene(sdf_path: str | Path) -> M1BIsaacScene:
    path = Path(sdf_path)
    root = ET.parse(path).getroot()
    world = root.find("world")
    if world is None or world.get("name") != "industrial_cylinder_v1":
        raise ValueError("expected the industrial_cylinder_v1 SDF world")
    scene = M1BIsaacScene(
        models=_parse_models(world),
        cameras=_parse_cameras(world),
        source_sdf_sha256=sha256_file(path),
    )
    if scene.source_sdf_sha256 != M1B_SDF_SHA256:
        raise ValueError(
            f"M1B SDF hash mismatch: {scene.source_sdf_sha256} != {M1B_SDF_SHA256}"
        )
    if scene.cylinder_count != 6:
        raise ValueError(f"expected six M1B cylinders, got {scene.cylinder_count}")
    return scene


def scene_primitive_count(models: Iterable[SceneModel]) -> int:
    return sum(len(link.visuals) for model in models for link in model.links)
