#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import argparse
import ast
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from xh_agent.data.isaac_m1b import (
    CameraSpec,
    CollisionPrimitive,
    LinkVisuals,
    M1B_URDF_SHA256,
    M1BIsaacScene,
    Pose,
    SceneModel,
    VisualPrimitive,
    load_m1b_isaac_generated_scene,
    load_m1b_isaac_scene,
    load_robot_base_pose,
    resolve_official_franka_asset,
    scene_collision_primitive_count,
    sha256_file,
    validate_m1b_physics_contract,
    verify_source_hashes,
)


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Generate and benchmark M1B Isaac RGB-D labels.")
    parser.add_argument("--sdf", required=True)
    parser.add_argument("--supervision")
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--physical-gpu-index", type=int, required=True)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument("--ready-file")
    parser.add_argument("--start-file")
    parser.add_argument("--barrier-timeout-s", type=float, default=600.0)
    args, unknown = parser.parse_known_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if args.warmup_frames < 1:
        parser.error("--warmup-frames must be at least one")
    if bool(args.ready_file) != bool(args.start_file):
        parser.error("--ready-file and --start-file must be provided together")
    if args.barrier_timeout_s <= 0:
        parser.error("--barrier-timeout-s must be positive")
    return args, unknown


ARGS, _UNKNOWN = parse_args()
if ARGS.supervision:
    SCENE = load_m1b_isaac_generated_scene(ARGS.sdf, ARGS.supervision)
    observed_urdf_hash = sha256_file(ARGS.urdf)
    if observed_urdf_hash != M1B_URDF_SHA256:
        raise ValueError(
            f"M1B Isaac URDF source hash mismatch: "
            f"{observed_urdf_hash} != {M1B_URDF_SHA256}"
        )
    SOURCE_HASHES = {
        Path(ARGS.sdf).name: SCENE.source_sdf_sha256,
        Path(ARGS.supervision).name: SCENE.source_supervision_sha256,
        "panda_controlled.urdf": observed_urdf_hash,
    }
else:
    SOURCE_HASHES = verify_source_hashes(ARGS.sdf, ARGS.urdf)
    SCENE = load_m1b_isaac_scene(ARGS.sdf)
ROBOT_BASE_POSE = load_robot_base_pose(ARGS.urdf)
PHYSICS_CONTRACT = validate_m1b_physics_contract(SCENE)
if any(camera.resolution != (640, 480) for camera in SCENE.cameras):
    raise RuntimeError("M1B Isaac benchmark requires the accepted 640x480 camera contract")

from isaacsim import SimulationApp


APP_START = time.perf_counter()
simulation_app = SimulationApp(
    {
        "headless": True,
        "renderer": "RaytracedLighting",
        "width": 640,
        "height": 480,
        "active_gpu": 0,
        "physics_gpu": 0,
        "multi_gpu": False,
    }
)

import numpy as np
import omni.replicator.core as rep
import omni.timeline
import omni.usd
from isaacsim.core.experimental.prims import Articulation
from isaacsim.core.simulation_manager import SimulationManager
from isaacsim.storage.native import get_assets_root_path
from PIL import Image
from pxr import Gf, Sdf, Semantics, Usd, UsdGeom, UsdPhysics, UsdShade


HOME_JOINTS = {
    "panda_joint1": 0.0,
    "panda_joint2": -0.5,
    "panda_joint3": 0.0,
    "panda_joint4": -1.5,
    "panda_joint5": 0.0,
    "panda_joint6": 1.0,
    "panda_joint7": 0.0,
    "panda_finger_joint2": 0.02,
    "panda_finger_joint1": 0.02,
}
ANNOTATORS = ("rgb", "distance_to_camera", "semantic_segmentation", "instance_segmentation")


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile from no values")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def _apply_pose(xformable: UsdGeom.Xformable, pose: Pose) -> None:
    xformable.AddTranslateOp().Set(Gf.Vec3d(*pose.xyz))
    xformable.AddRotateXYZOp().Set(
        Gf.Vec3f(*(math.degrees(angle) for angle in pose.rpy))
    )


def _apply_semantics(prim: Usd.Prim, label: str) -> None:
    semantic = Semantics.SemanticsAPI.Apply(prim, "Semantics")
    semantic.CreateSemanticTypeAttr().Set("class")
    semantic.CreateSemanticDataAttr().Set(label)


def _material(
    stage: Usd.Stage,
    material_path: str,
    rgba: tuple[float, float, float, float],
) -> UsdShade.Material:
    material = UsdShade.Material.Define(stage, material_path)
    shader = UsdShade.Shader.Define(stage, material_path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgba[:3]))
    shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(float(rgba[3]))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _create_visual(
    stage: Usd.Stage,
    path: str,
    visual: VisualPrimitive,
    semantic_class: str,
) -> Usd.Prim:
    if visual.shape == "box":
        assert visual.size is not None
        geometry = UsdGeom.Cube.Define(stage, path)
        geometry.CreateSizeAttr(1.0)
        geometry.AddScaleOp().Set(Gf.Vec3f(*visual.size))
    elif visual.shape == "cylinder":
        assert visual.radius is not None and visual.length is not None
        geometry = UsdGeom.Cylinder.Define(stage, path)
        geometry.CreateAxisAttr("Z")
        geometry.CreateRadiusAttr(visual.radius)
        geometry.CreateHeightAttr(visual.length)
    else:
        raise ValueError(f"unsupported visual shape: {visual.shape}")
    _apply_pose(geometry, visual.pose)
    material = _material(stage, path + "_Material", visual.color_rgba)
    UsdShade.MaterialBindingAPI.Apply(geometry.GetPrim()).Bind(material)
    _apply_semantics(geometry.GetPrim(), semantic_class)
    return geometry.GetPrim()


def _create_collision(
    stage: Usd.Stage,
    path: str,
    collision: CollisionPrimitive,
) -> Usd.Prim:
    if collision.shape == "box":
        assert collision.size is not None
        geometry = UsdGeom.Cube.Define(stage, path)
        geometry.CreateSizeAttr(1.0)
        geometry.AddScaleOp().Set(Gf.Vec3f(*collision.size))
    elif collision.shape == "cylinder":
        assert collision.radius is not None and collision.length is not None
        geometry = UsdGeom.Cylinder.Define(stage, path)
        geometry.CreateAxisAttr("Z")
        geometry.CreateRadiusAttr(collision.radius)
        geometry.CreateHeightAttr(collision.length)
    else:
        raise ValueError(f"unsupported collision shape: {collision.shape}")
    _apply_pose(geometry, collision.pose)
    geometry.MakeInvisible()
    UsdPhysics.CollisionAPI.Apply(geometry.GetPrim())
    return geometry.GetPrim()


def _create_link(
    stage: Usd.Stage,
    model_path: str,
    link: LinkVisuals,
    semantic_class: str,
) -> None:
    link_path = f"{model_path}/{link.name}"
    link_xform = UsdGeom.Xform.Define(stage, link_path)
    _apply_pose(link_xform, link.pose)
    if link.mass_kg is not None:
        mass_api = UsdPhysics.MassAPI.Apply(link_xform.GetPrim())
        mass_api.CreateMassAttr(link.mass_kg)
    for visual in link.visuals:
        _create_visual(stage, f"{link_path}/{visual.name}", visual, semantic_class)
    for collision in link.collisions:
        _create_collision(
            stage,
            f"{link_path}/Collision_{collision.name}",
            collision,
        )


def _create_model(stage: Usd.Stage, model: SceneModel) -> None:
    model_path = f"/World/M1B/{model.name}"
    model_xform = UsdGeom.Xform.Define(stage, model_path)
    _apply_pose(model_xform, model.pose)
    _apply_semantics(model_xform.GetPrim(), model.semantic_class)
    for link in model.links:
        _create_link(stage, model_path, link, model.semantic_class)
        if not model.static:
            link_prim = stage.GetPrimAtPath(f"{model_path}/{link.name}")
            UsdPhysics.RigidBodyAPI.Apply(link_prim)


def _validate_stage_physics(stage: Usd.Stage) -> dict[str, list[str]]:
    collision_paths: list[str] = []
    rigid_body_paths: list[str] = []
    mass_paths: list[str] = []
    for model in SCENE.models:
        for link in model.links:
            link_path = f"/World/M1B/{model.name}/{link.name}"
            link_prim = stage.GetPrimAtPath(link_path)
            if not model.static:
                if not link_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    raise RuntimeError(f"missing rigid-body API on {link_path}")
                rigid_body_paths.append(link_path)
            if link.mass_kg is not None:
                if not link_prim.HasAPI(UsdPhysics.MassAPI):
                    raise RuntimeError(f"missing mass API on {link_path}")
                mass_paths.append(link_path)
            for collision in link.collisions:
                collision_path = f"{link_path}/Collision_{collision.name}"
                collision_prim = stage.GetPrimAtPath(collision_path)
                if not collision_prim.HasAPI(UsdPhysics.CollisionAPI):
                    raise RuntimeError(f"missing collision API on {collision_path}")
                collision_paths.append(collision_path)
    if len(collision_paths) != int(PHYSICS_CONTRACT["collision_primitive_count"]):
        raise RuntimeError("stage collision count does not match the SDF physics contract")
    return {
        "collision_paths": collision_paths,
        "rigid_body_paths": rigid_body_paths,
        "mass_paths": mass_paths,
    }


def _create_robot(
    stage: Usd.Stage,
    robot_usd: str,
    base_pose: Pose,
) -> tuple[int, dict[str, str]]:
    robot_xform = UsdGeom.Xform.Define(stage, "/World/Robot")
    _apply_pose(robot_xform, base_pose)
    if not robot_xform.GetPrim().GetReferences().AddReference(robot_usd):
        raise RuntimeError(f"failed to reference robot USD: {robot_usd}")
    stage.Load(robot_xform.GetPath())
    for _ in range(3):
        simulation_app.update()
    robot_prim = stage.GetPrimAtPath("/World/Robot")
    if not robot_prim.IsValid():
        raise RuntimeError("robot reference did not create /World/Robot")
    variants = {
        "Gripper": "AlternateFinger",
        "Mesh": "Performance",
    }
    for set_name, selection in variants.items():
        variant_set = robot_prim.GetVariantSets().GetVariantSet(set_name)
        if not variant_set.IsValid() or selection not in variant_set.GetVariantNames():
            raise RuntimeError(
                f"official Franka asset is missing variant {set_name}={selection}"
            )
        if not variant_set.SetVariantSelection(selection):
            raise RuntimeError(
                f"failed to select official Franka variant {set_name}={selection}"
            )
    for _ in range(3):
        simulation_app.update()
    _apply_semantics(robot_prim, "panda_robot")
    geometry_count = 0
    for prim in Usd.PrimRange(robot_prim):
        if prim.IsA(UsdGeom.Gprim):
            geometry_count += 1
    return geometry_count, variants


def _create_cameras(scene: M1BIsaacScene) -> tuple[list[Any], list[Any]]:
    cameras, render_products = [], []
    for camera_spec in scene.cameras:
        camera = rep.functional.create.camera(
            position=camera_spec.position,
            look_at=camera_spec.look_at,
            parent="/World",
            name=camera_spec.name,
        )
        render_product = rep.create.render_product(
            camera,
            resolution=camera_spec.resolution,
            name=f"{camera_spec.name}_RenderProduct",
        )
        cameras.append(camera)
        render_products.append(render_product)
    return cameras, render_products


def _create_annotators(
    cameras: tuple[CameraSpec, ...],
    render_products: list[Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for camera_spec, render_product in zip(cameras, render_products, strict=True):
        camera_annotators = {
            "rgb": rep.AnnotatorRegistry.get_annotator("rgb"),
            "distance_to_camera": rep.AnnotatorRegistry.get_annotator("distance_to_camera"),
            "semantic_segmentation": rep.AnnotatorRegistry.get_annotator(
                "semantic_segmentation", init_params={"colorize": True}
            ),
            "instance_segmentation": rep.AnnotatorRegistry.get_annotator(
                "instance_segmentation", init_params={"colorize": True}
            ),
        }
        for annotator in camera_annotators.values():
            annotator.attach(render_product)
        result[camera_spec.name] = camera_annotators
    return result


def _annotator_array_and_info(data: Any) -> tuple[np.ndarray, dict[str, Any]]:
    if isinstance(data, dict):
        return np.asarray(data["data"]), dict(data.get("info", {}))
    return np.asarray(data), {}


def _semantic_pixel_counts(array: np.ndarray, info: dict[str, Any]) -> dict[str, int]:
    if array.ndim != 3 or array.shape[2] != 4:
        raise RuntimeError(f"colorized semantic segmentation has invalid shape {array.shape}")
    counts: dict[str, int] = {}
    for encoded_color, labels in info.get("idToLabels", {}).items():
        if not isinstance(labels, dict):
            continue
        semantic_class = labels.get("class")
        if not isinstance(semantic_class, str):
            continue
        color = ast.literal_eval(encoded_color)
        if not isinstance(color, tuple) or len(color) != 4:
            raise RuntimeError(f"invalid semantic color key: {encoded_color}")
        pixels = int(np.all(array == np.asarray(color, dtype=array.dtype), axis=2).sum())
        counts[semantic_class] = counts.get(semantic_class, 0) + pixels
    return counts


def _save_image(path: Path, array: np.ndarray) -> None:
    values = np.asarray(array)
    if values.dtype != np.uint8:
        values = values.astype(np.uint8)
    if values.ndim == 2:
        image = Image.fromarray(values, mode="L")
    elif values.shape[2] == 4:
        image = Image.fromarray(values, mode="RGBA")
    elif values.shape[2] == 3:
        image = Image.fromarray(values, mode="RGB")
    else:
        raise ValueError(f"unsupported image shape {values.shape}")
    image.save(path)


def _prepare_output(output: Path, cameras: tuple[CameraSpec, ...]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for camera in cameras:
        for folder in ("rgb", "depth", "semantic", "instance"):
            (output / camera.name / folder).mkdir(parents=True, exist_ok=True)


def _tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _count_outputs(output: Path, cameras: tuple[CameraSpec, ...]) -> dict[str, int]:
    result = {}
    for kind, extension in (
        ("rgb", ".png"),
        ("depth", ".npy"),
        ("semantic", ".png"),
        ("instance", ".png"),
    ):
        result[kind] = sum(
            1 for camera in cameras for _ in (output / camera.name / kind).glob(f"*{extension}")
        )
    result["label_json"] = sum(
        1 for camera in cameras for _ in (output / camera.name).glob("*_labels.json")
    )
    return result


def _configure_articulation() -> tuple[Articulation, list[float], dict[str, int]]:
    robot = Articulation("/World/Robot")
    indices: dict[str, int] = {}
    for name in HOME_JOINTS:
        values = robot.get_dof_indices(name)
        array = values.numpy() if hasattr(values, "numpy") else values
        index = int(array[0])
        if index < 0:
            raise RuntimeError(f"imported Panda is missing DOF {name}")
        indices[name] = index
    if len(set(indices.values())) != len(HOME_JOINTS):
        raise RuntimeError(f"imported Panda DOF mapping is not one-to-one: {indices}")
    dof_count = max(indices.values()) + 1
    if dof_count != 9:
        raise RuntimeError(f"expected nine Panda DOFs, got {dof_count}: {indices}")
    home = [0.0] * dof_count
    for name, value in HOME_JOINTS.items():
        home[indices[name]] = value
    robot.set_default_state(dof_positions=home)
    return robot, home, indices


def _target_positions(
    home: list[float],
    indices: dict[str, int],
    frame_index: int,
    worker_id: int,
) -> list[float]:
    phase = 2.0 * math.pi * frame_index / 100.0 + worker_id * 0.37
    target = list(home)
    target[indices["panda_joint1"]] += 0.20 * math.sin(phase)
    target[indices["panda_joint2"]] += 0.10 * math.sin(phase * 0.7)
    target[indices["panda_joint4"]] += 0.12 * math.cos(phase * 0.5)
    target[indices["panda_joint6"]] += 0.15 * math.sin(phase * 0.9)
    return target


def _wait_at_start_barrier() -> float:
    if ARGS.ready_file is None:
        return 0.0
    ready_file = Path(ARGS.ready_file)
    start_file = Path(ARGS.start_file)
    ready_file.parent.mkdir(parents=True, exist_ok=True)
    if start_file.exists():
        raise RuntimeError(f"start barrier already exists before READY: {start_file}")
    omni.timeline.get_timeline_interface().pause()
    ready_file.write_text(
        json.dumps(
            {
                "worker_id": ARGS.worker_id,
                "physical_gpu_index": ARGS.physical_gpu_index,
                "state": "READY_AFTER_SCENE_ARTICULATION_AND_WARMUP",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    wait_start = time.perf_counter()
    deadline = wait_start + ARGS.barrier_timeout_s
    while not start_file.exists():
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"start barrier timed out: {start_file}")
        time.sleep(0.1)
    omni.timeline.get_timeline_interface().play()
    simulation_app.update()
    return time.perf_counter() - wait_start


def main() -> int:
    output = Path(ARGS.output)
    _prepare_output(output, SCENE.cameras)
    assets_root = get_assets_root_path()
    if assets_root is None:
        raise RuntimeError("Isaac official assets root is unavailable")
    robot_asset_uri = resolve_official_franka_asset(assets_root)

    omni.usd.get_context().new_stage()
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    rep.orchestrator.set_capture_on_play(False)
    rep.functional.create.dome_light(intensity=1000, parent="/World", name="DomeLight")

    UsdGeom.Xform.Define(stage, "/World/M1B")
    for model in SCENE.models:
        _create_model(stage, model)
    stage_physics = _validate_stage_physics(stage)
    robot_geometry_prim_count, robot_variants = _create_robot(
        stage,
        robot_asset_uri,
        ROBOT_BASE_POSE,
    )
    physics_stage_path = output / "m1b_physics_scene.usdc"
    if not stage.Export(str(physics_stage_path)):
        raise RuntimeError(f"failed to export clean physics stage: {physics_stage_path}")
    _, render_products = _create_cameras(SCENE)
    annotators = _create_annotators(SCENE.cameras, render_products)

    robot, home, dof_indices = _configure_articulation()
    SimulationManager.initialize_physics()
    omni.timeline.get_timeline_interface().play()
    simulation_app.update()
    robot.reset_to_default_state()
    simulation_app.update()

    stage_path = output / "m1b_scene.usda"
    stage.Export(str(stage_path))

    warmup_times: list[float] = []
    for frame in range(ARGS.warmup_frames):
        robot.set_dof_position_targets(
            _target_positions(home, dof_indices, frame, ARGS.worker_id)
        )
        start = time.perf_counter()
        rep.orchestrator.step(rt_subframes=1, delta_time=1.0 / 30.0, pause_timeline=False)
        warmup_times.append(time.perf_counter() - start)

    barrier_wait_s = _wait_at_start_barrier()
    capture_times: list[float] = []
    readback_write_times: list[float] = []
    finite_depth_samples = 0
    label_classes: set[str] = set()
    semantic_pixel_counts: dict[str, int] = {}
    benchmark_start = time.perf_counter()
    for frame in range(ARGS.frames):
        robot.set_dof_position_targets(
            _target_positions(home, dof_indices, frame + ARGS.warmup_frames, ARGS.worker_id)
        )
        capture_start = time.perf_counter()
        rep.orchestrator.step(rt_subframes=1, delta_time=1.0 / 30.0, pause_timeline=False)
        capture_times.append(time.perf_counter() - capture_start)

        write_start = time.perf_counter()
        for camera in SCENE.cameras:
            camera_root = output / camera.name
            camera_annotators = annotators[camera.name]
            rgb, _ = _annotator_array_and_info(camera_annotators["rgb"].get_data())
            depth, _ = _annotator_array_and_info(
                camera_annotators["distance_to_camera"].get_data()
            )
            semantic, semantic_info = _annotator_array_and_info(
                camera_annotators["semantic_segmentation"].get_data()
            )
            instance, instance_info = _annotator_array_and_info(
                camera_annotators["instance_segmentation"].get_data()
            )
            if rgb.shape[:2] != (480, 640) or depth.shape[:2] != (480, 640):
                raise RuntimeError(
                    f"{camera.name} frame {frame} shape mismatch: rgb={rgb.shape}, depth={depth.shape}"
                )
            finite_depth_samples += int(np.isfinite(depth).sum())
            for semantic_class, pixels in _semantic_pixel_counts(
                semantic, semantic_info
            ).items():
                semantic_pixel_counts[semantic_class] = (
                    semantic_pixel_counts.get(semantic_class, 0) + pixels
                )
            stem = f"{frame:06d}"
            _save_image(camera_root / "rgb" / f"{stem}.png", rgb[:, :, :3])
            np.save(camera_root / "depth" / f"{stem}.npy", depth.astype(np.float32))
            _save_image(camera_root / "semantic" / f"{stem}.png", semantic)
            _save_image(camera_root / "instance" / f"{stem}.png", instance)
            if frame == 0:
                for kind, info in (
                    ("semantic", semantic_info),
                    ("instance", instance_info),
                ):
                    with (camera_root / f"{kind}_labels.json").open(
                        "w", encoding="utf-8"
                    ) as stream:
                        json.dump(_json_ready(info), stream, indent=2, sort_keys=True)
                    label_classes.update(
                        str(value) for value in _json_ready(info).values()
                    )
        readback_write_times.append(time.perf_counter() - write_start)

    rep.orchestrator.wait_until_complete()
    benchmark_wall_s = time.perf_counter() - benchmark_start
    output_counts = _count_outputs(output, SCENE.cameras)
    expected_images = ARGS.frames * len(SCENE.cameras)
    expected_counts = {
        "rgb": expected_images,
        "depth": expected_images,
        "semantic": expected_images,
        "instance": expected_images,
        "label_json": len(SCENE.cameras) * 2,
    }
    if output_counts != expected_counts:
        raise RuntimeError(f"dataset file count mismatch: {output_counts} != {expected_counts}")
    if finite_depth_samples <= 0:
        raise RuntimeError("dataset contains no finite depth samples")
    joined_labels = " ".join(sorted(label_classes))
    for required in ("industrial_cylinder", "panda_robot"):
        if required not in joined_labels:
            raise RuntimeError(f"segmentation labels are missing {required}: {joined_labels}")
        required_pixels = ARGS.frames * 100
        if semantic_pixel_counts.get(required, 0) < required_pixels:
            raise RuntimeError(
                f"segmentation has only {semantic_pixel_counts.get(required, 0)} "
                f"{required} pixels; expected at least {required_pixels}"
            )

    final_dof_positions = robot.get_dof_positions()
    final_array = (
        final_dof_positions.numpy()
        if hasattr(final_dof_positions, "numpy")
        else np.asarray(final_dof_positions)
    )
    metrics = {
        "status": "PASS",
        "worker_id": ARGS.worker_id,
        "physical_gpu_index": ARGS.physical_gpu_index,
        "renderer": "RaytracedLighting",
        "multi_gpu": False,
        "frames": ARGS.frames,
        "warmup_frames": ARGS.warmup_frames,
        "camera_count": len(SCENE.cameras),
        "cameras": [_json_ready(camera.__dict__) for camera in SCENE.cameras],
        "annotators": list(ANNOTATORS),
        "source_hashes": SOURCE_HASHES,
        "robot_asset": {
            "uri": robot_asset_uri,
            "provenance": "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD",
            "local_simplified_robot_used": False,
            "directly_traversable_geometry_prim_count": robot_geometry_prim_count,
            "variants": robot_variants,
            "base_pose": _json_ready(ROBOT_BASE_POSE.__dict__),
            "base_pose_source": "HASH_BOUND_PRODUCTION_URDF_WORLD_TO_PANDA",
        },
        "source_scene_id": "IndustrialCylinderBenchmarkV1",
        "source_collision_primitive_count": scene_collision_primitive_count(SCENE.models),
        "physics_contract": _json_ready(PHYSICS_CONTRACT),
        "stage_physics": stage_physics,
        "clean_physics_stage": {
            "filename": physics_stage_path.name,
            "sha256": sha256_file(physics_stage_path),
            "contains_render_products": False,
        },
        "privileged_truth_use": "OFFLINE_DATASET_LABEL_ONLY_NOT_POLICY_INPUT",
        "action_protocol": {
            "frame": "PANDA_JOINT_ORDER_BY_NAME",
            "units": "radian_arm_metre_finger",
            "dimensions": 9,
            "frequency_hz": 30,
            "normalization": "none",
            "source": "deterministic_dataset_excitation_not_policy_action",
        },
        "dof_indices": dof_indices,
        "final_dof_positions": _json_ready(final_array),
        "benchmark_wall_s": benchmark_wall_s,
        "sensor_frames": expected_images,
        "sensor_frames_per_s": expected_images / benchmark_wall_s,
        "capture_steps_per_s": ARGS.frames / benchmark_wall_s,
        "capture_step_s_p50": statistics.median(capture_times),
        "capture_step_s_p90": _percentile(capture_times, 0.90),
        "readback_write_s_p50": statistics.median(readback_write_times),
        "readback_write_s_p90": _percentile(readback_write_times, 0.90),
        "warmup_s": sum(warmup_times),
        "warmup_frame_s": warmup_times,
        "start_barrier": {
            "enabled": ARGS.ready_file is not None,
            "wait_s": barrier_wait_s,
            "release_provenance": "EXTERNAL_ALL_WORKERS_READY_FILE",
        },
        "finite_depth_samples": finite_depth_samples,
        "semantic_pixel_counts": semantic_pixel_counts,
        "output_counts": output_counts,
        "output_bytes_before_metrics": _tree_bytes(output),
        "app_elapsed_s": time.perf_counter() - APP_START,
    }
    with (output / "metrics.json").open("w", encoding="utf-8") as stream:
        json.dump(_json_ready(metrics), stream, indent=2, sort_keys=True)
    print("M1B_ISAAC_DATASET_PASS " + json.dumps(_json_ready(metrics), sort_keys=True))

    for camera_annotators in annotators.values():
        for annotator in camera_annotators.values():
            annotator.detach()
    for render_product in render_products:
        render_product.destroy()
    simulation_app.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"M1B_ISAAC_DATASET_FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        simulation_app.close()
        raise
