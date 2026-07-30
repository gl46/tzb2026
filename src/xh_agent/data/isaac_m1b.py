from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


M1B_SDF_SHA256 = "1eea1b34b832d858ba9a4adec775018e807061b54cb1afff19d710d848ad926d"
M1B_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
OFFICIAL_ISAAC_FRANKA_RELATIVE_USD = (
    "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
)
SDF_DEFAULT_SURFACE_FRICTION = 1.0
SDF_DEFAULT_SURFACE_RESTITUTION = 0.0
# The accepted Gazebo path uses gz-physics' Bullet-Featherstone backend.
# Bullet's btMultiBody sleeps when squared motion stays below this threshold;
# PhysX's default is materially lower, so port the source-engine value.
BULLET_FEATHERSTONE_SLEEP_THRESHOLD = 0.05


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
class CollisionPrimitive:
    name: str
    shape: str
    pose: Pose
    size: tuple[float, float, float] | None
    radius: float | None
    length: float | None


@dataclass(frozen=True)
class LinkVisuals:
    name: str
    pose: Pose
    visuals: tuple[VisualPrimitive, ...]
    collisions: tuple[CollisionPrimitive, ...]
    mass_kg: float | None
    linear_velocity_decay: float | None
    angular_velocity_decay: float | None


@dataclass(frozen=True)
class SceneModel:
    name: str
    pose: Pose
    semantic_class: str
    static: bool
    links: tuple[LinkVisuals, ...]


@dataclass(frozen=True)
class CameraSpec:
    name: str
    position: tuple[float, float, float]
    look_at: tuple[float, float, float]
    resolution: tuple[int, int]
    horizontal_fov_rad: float
    clipping_range_m: tuple[float, float]
    provenance: str


@dataclass(frozen=True)
class M1BIsaacScene:
    models: tuple[SceneModel, ...]
    cameras: tuple[CameraSpec, ...]
    source_sdf_sha256: str
    source_supervision_sha256: str | None = None
    scene_seed: int | None = None

    @property
    def cylinder_count(self) -> int:
        return sum(model.semantic_class == "industrial_cylinder" for model in self.models)

    @property
    def dynamic_models(self) -> tuple[SceneModel, ...]:
        return tuple(model for model in self.models if not model.static)


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


def load_robot_base_pose(urdf_path: str | Path) -> Pose:
    root = ET.parse(urdf_path).getroot()
    joint = root.find("./joint[@name='world_to_panda']")
    if joint is None or joint.get("type") != "fixed":
        raise ValueError("expected fixed world_to_panda joint")
    parent = joint.find("parent")
    child = joint.find("child")
    if (
        parent is None
        or parent.get("link") != "world"
        or child is None
        or child.get("link") != "panda_link0"
    ):
        raise ValueError("world_to_panda must connect world to panda_link0")
    origin = joint.find("origin")
    if origin is None:
        raise ValueError("world_to_panda has no origin")
    xyz = tuple(float(value) for value in origin.get("xyz", "").split())
    rpy = tuple(float(value) for value in origin.get("rpy", "0 0 0").split())
    if len(xyz) != 3 or len(rpy) != 3:
        raise ValueError("world_to_panda origin must contain xyz and rpy triples")
    return Pose(xyz=xyz, rpy=rpy)


def load_m1b_gripper_effort_limit(urdf_path: str | Path) -> float:
    """Return the production gripper leader's effort limit in newtons.

    Gazebo drives ``panda_finger_joint2`` and structurally mimics it from
    joint1.  NVIDIA's official Isaac Franka drives joint1 and makes joint2 its
    mimic.  Validate the source relationship here so the simulator adapter
    transfers the symmetric aperture contract without guessing a mapping.
    """

    root = ET.parse(urdf_path).getroot()
    leader = root.find("./joint[@name='panda_finger_joint2']")
    follower = root.find("./joint[@name='panda_finger_joint1']")
    if (
        leader is None
        or follower is None
        or leader.get("type") != "prismatic"
        or follower.get("type") != "prismatic"
    ):
        raise ValueError("expected the two production prismatic finger joints")
    leader_limit = leader.find("limit")
    follower_limit = follower.find("limit")
    mimic = follower.find("mimic")
    if (
        leader_limit is None
        or follower_limit is None
        or mimic is None
        or mimic.get("joint") != "panda_finger_joint2"
        or float(mimic.get("multiplier", "nan")) != 1.0
        or float(mimic.get("offset", "nan")) != 0.0
    ):
        raise ValueError("production finger mimic contract is invalid")
    leader_effort = float(leader_limit.get("effort", "nan"))
    follower_effort = float(follower_limit.get("effort", "nan"))
    if (
        not math.isfinite(leader_effort)
        or leader_effort <= 0.0
        or not math.isclose(follower_effort, leader_effort, abs_tol=1e-12)
    ):
        raise ValueError("production finger effort limits are invalid")
    return leader_effort


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


def _parse_geometry(
    element: ET.Element,
) -> tuple[
    str,
    tuple[float, float, float] | None,
    float | None,
    float | None,
]:
    geometry = element.find("geometry")
    if geometry is None:
        raise ValueError(f"geometry element {element.get('name')} has no geometry")
    box = geometry.find("box")
    cylinder = geometry.find("cylinder")
    if box is not None:
        size = tuple(float(value) for value in box.findtext("size", default="").split())
        if len(size) != 3:
            raise ValueError(f"box {element.get('name')} has invalid size {size}")
        shape, radius, length = "box", None, None
    elif cylinder is not None:
        size = None
        radius = float(cylinder.findtext("radius", default="nan"))
        length = float(cylinder.findtext("length", default="nan"))
        if not math.isfinite(radius) or not math.isfinite(length):
            raise ValueError(f"cylinder {element.get('name')} has invalid dimensions")
        shape = "cylinder"
    else:
        raise ValueError(f"unsupported geometry in {element.get('name')}")
    return shape, size, radius, length


def _parse_visual(visual: ET.Element) -> VisualPrimitive:
    shape, size, radius, length = _parse_geometry(visual)
    return VisualPrimitive(
        name=visual.get("name", "visual"),
        shape=shape,
        pose=parse_pose(visual.findtext("pose")),
        size=size,
        radius=radius,
        length=length,
        color_rgba=_parse_color(visual),
    )


def _parse_collision(collision: ET.Element) -> CollisionPrimitive:
    shape, size, radius, length = _parse_geometry(collision)
    return CollisionPrimitive(
        name=collision.get("name", "collision"),
        shape=shape,
        pose=parse_pose(collision.findtext("pose")),
        size=size,
        radius=radius,
        length=length,
    )


def _parse_mass(link: ET.Element) -> float | None:
    text = link.findtext("./inertial/mass")
    if text is None:
        return None
    mass_kg = float(text)
    if not math.isfinite(mass_kg) or mass_kg <= 0:
        raise ValueError(f"link {link.get('name')} has invalid mass {mass_kg}")
    return mass_kg


def _parse_velocity_decay(link: ET.Element, field: str) -> float | None:
    text = link.findtext(f"./velocity_decay/{field}")
    if text is None:
        return None
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise ValueError(
            f"link {link.get('name')} has invalid {field} velocity decay {value}"
        )
    return value


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
            collisions = tuple(
                _parse_collision(collision) for collision in link.findall("collision")
            )
            if visuals or collisions:
                links.append(
                    LinkVisuals(
                        name=link.get("name", "link"),
                        pose=parse_pose(link.findtext("pose")),
                        visuals=visuals,
                        collisions=collisions,
                        mass_kg=_parse_mass(link),
                        linear_velocity_decay=_parse_velocity_decay(link, "linear"),
                        angular_velocity_decay=_parse_velocity_decay(link, "angular"),
                    )
                )
        if not links:
            raise ValueError(f"M1B model {name} has no supported geometry")
        models.append(
            SceneModel(
                name=name,
                pose=parse_pose(model.findtext("pose")),
                semantic_class=semantic_class,
                static=model.findtext("static", default="false").strip().lower()
                in {"1", "true"},
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
    camera = fixture.find("./sensor[@name='front_rgbd']/camera")
    if camera is None:
        raise ValueError("M1B source SDF has no front_rgbd camera contract")
    horizontal_fov_rad = float(camera.findtext("horizontal_fov", default="nan"))
    clipping_range_m = (
        float(camera.findtext("./clip/near", default="nan")),
        float(camera.findtext("./clip/far", default="nan")),
    )
    if (
        not math.isfinite(horizontal_fov_rad)
        or not 0 < horizontal_fov_rad < math.pi
        or not all(math.isfinite(value) for value in clipping_range_m)
        or not 0 < clipping_range_m[0] < clipping_range_m[1]
    ):
        raise ValueError("M1B source SDF has invalid camera optics")
    look_at = (-0.05, 0.0, 0.55)
    return (
        CameraSpec(
            name="policy_rgbd",
            position=source_pose.xyz,
            look_at=look_at,
            resolution=resolution,
            horizontal_fov_rad=horizontal_fov_rad,
            clipping_range_m=clipping_range_m,
            provenance="M1B_SOURCE_FIXED_PUBLIC_POLICY_RGBD_INPUT",
        ),
        CameraSpec(
            name="front_rgbd",
            position=(-source_pose.xyz[0], -source_pose.xyz[1], source_pose.xyz[2]),
            look_at=look_at,
            resolution=resolution,
            horizontal_fov_rad=horizontal_fov_rad,
            clipping_range_m=clipping_range_m,
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
            horizontal_fov_rad=horizontal_fov_rad,
            clipping_range_m=clipping_range_m,
            provenance="ISAAC_DATASET_AUXILIARY_NOT_POLICY_INPUT",
        ),
        CameraSpec(
            name="side_rgbd",
            position=(0.65, -0.75, 1.05),
            look_at=look_at,
            resolution=resolution,
            horizontal_fov_rad=horizontal_fov_rad,
            clipping_range_m=clipping_range_m,
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
    validate_m1b_physics_contract(scene)
    return scene


def load_m1b_isaac_generated_scene(
    sdf_path: str | Path,
    supervision_path: str | Path,
) -> M1BIsaacScene:
    sdf = Path(sdf_path)
    supervision = Path(supervision_path)
    root = ET.parse(sdf).getroot()
    world = root.find("world")
    if world is None or world.get("name") != "industrial_cylinder_v1":
        raise ValueError("expected the industrial_cylinder_v1 SDF world")
    payload = json.loads(supervision.read_text(encoding="utf-8"))
    if payload.get("scene_id") != "IndustrialCylinderBenchmarkV1":
        raise ValueError("generated M1B supervision has the wrong scene_id")
    simulator_supervision = payload.get("simulator_supervision")
    if not isinstance(simulator_supervision, dict):
        raise ValueError("generated M1B supervision has no simulator_supervision")
    if simulator_supervision.get("training_and_evaluation_only") is not True:
        raise ValueError("generated M1B supervision must be evaluation-only")
    objects = simulator_supervision.get("objects")
    if not isinstance(objects, list):
        raise ValueError("generated M1B supervision objects must be a list")
    expected_names = tuple(str(item.get("actual_sim_entity_id", "")) for item in objects)
    if not 6 <= len(expected_names) <= 12:
        raise ValueError(f"generated M1B scene must contain 6..12 objects, got {len(expected_names)}")
    if expected_names != tuple(f"cylinder_{index:02d}" for index in range(1, len(expected_names) + 1)):
        raise ValueError(f"generated M1B object IDs are not canonical: {expected_names}")
    models = _parse_models(world)
    actual_names = tuple(
        model.name for model in models if model.semantic_class == "industrial_cylinder"
    )
    if actual_names != expected_names:
        raise ValueError(
            "generated M1B SDF/supervision object mismatch: "
            f"sdf={actual_names}, supervision={expected_names}"
        )
    scene = M1BIsaacScene(
        models=models,
        cameras=_parse_cameras(world),
        source_sdf_sha256=sha256_file(sdf),
        source_supervision_sha256=sha256_file(supervision),
        scene_seed=int(payload["seed"]),
    )
    validate_m1b_physics_contract(scene)
    partition_bin = next(
        (model for model in scene.models if model.name == "blue_partition_bin"),
        None,
    )
    if partition_bin is None or partition_bin.pose.xyz[:2] != (0.2, 0.15):
        raise ValueError(
            "generated M1B partition bin must match the ADR-0016 center (0.20, 0.15)"
        )
    return scene


def scene_primitive_count(models: Iterable[SceneModel]) -> int:
    return sum(len(link.visuals) for model in models for link in model.links)


def scene_collision_primitive_count(models: Iterable[SceneModel]) -> int:
    return sum(len(link.collisions) for model in models for link in model.links)


def validate_m1b_physics_contract(scene: M1BIsaacScene) -> dict[str, object]:
    dynamic_names = tuple(model.name for model in scene.dynamic_models)
    cylinder_names = tuple(
        model.name
        for model in scene.models
        if model.semantic_class == "industrial_cylinder"
    )
    if dynamic_names != cylinder_names:
        raise ValueError(
            "only the six industrial cylinders may be dynamic: "
            f"dynamic={dynamic_names}, cylinders={cylinder_names}"
        )
    cylinder_masses: dict[str, float] = {}
    cylinder_velocity_decay: dict[str, dict[str, float | None]] = {}
    for model in scene.dynamic_models:
        if len(model.links) != 1:
            raise ValueError(f"dynamic model {model.name} must have exactly one link")
        link = model.links[0]
        if len(link.collisions) != 1:
            raise ValueError(f"dynamic model {model.name} must have one collision")
        if link.mass_kg is None:
            raise ValueError(f"dynamic model {model.name} has no mass")
        if (link.linear_velocity_decay is None) != (
            link.angular_velocity_decay is None
        ):
            raise ValueError(
                f"dynamic model {model.name} has a partial velocity-decay contract"
            )
        cylinder_masses[model.name] = link.mass_kg
        cylinder_velocity_decay[model.name] = {
            "linear": link.linear_velocity_decay,
            "angular": link.angular_velocity_decay,
        }
    static_collision_names = tuple(
        model.name
        for model in scene.models
        if model.static and any(link.collisions for link in model.links)
    )
    if static_collision_names != ("industrial_work_table", "blue_partition_bin"):
        raise ValueError(
            "unexpected static collision models: "
            f"{static_collision_names}"
        )
    return {
        "dynamic_model_names": dynamic_names,
        "dynamic_model_count": len(dynamic_names),
        "static_collision_model_names": static_collision_names,
        "collision_primitive_count": scene_collision_primitive_count(scene.models),
        "cylinder_masses_kg": cylinder_masses,
        "cylinder_velocity_decay": cylinder_velocity_decay,
        "sdf_default_surface": {
            "static_friction": SDF_DEFAULT_SURFACE_FRICTION,
            "dynamic_friction": SDF_DEFAULT_SURFACE_FRICTION,
            "restitution": SDF_DEFAULT_SURFACE_RESTITUTION,
        },
        "source_engine_sleep_threshold": {
            "value": BULLET_FEATHERSTONE_SLEEP_THRESHOLD,
            "source": (
                "gz-physics/bullet-featherstone btMultiBody "
                "INITIAL_SLEEP_EPSILON"
            ),
        },
    }
