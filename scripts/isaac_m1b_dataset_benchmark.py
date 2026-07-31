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
    BULLET_FEATHERSTONE_SLEEP_THRESHOLD,
    CameraSpec,
    CollisionPrimitive,
    LinkVisuals,
    M1B_URDF_SHA256,
    M1BIsaacScene,
    Pose,
    SDF_DEFAULT_SURFACE_FRICTION,
    SDF_DEFAULT_SURFACE_RESTITUTION,
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
from xh_agent.data.shadow_isaac import (
    SHADOW_CANDIDATES,
    shadow_target_positions,
    validate_initial_joint_position,
)


def _parse_joint_position(value: str) -> tuple[float, ...]:
    try:
        return validate_initial_joint_position(value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Generate and benchmark M1B Isaac RGB-D labels.")
    parser.add_argument("--sdf", required=True)
    parser.add_argument("--supervision")
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--worker-id", type=int, required=True)
    parser.add_argument("--physical-gpu-index", type=int, required=True)
    parser.add_argument(
        "--gripper-variant",
        choices=("AlternateFinger", "Default"),
        default="Default",
        help="Explicit NVIDIA official Franka gripper variant.",
    )
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--warmup-frames", type=int, default=5)
    parser.add_argument(
        "--static-perception-audit",
        action="store_true",
        help=(
            "Freeze only industrial-cylinder rigid bodies after exporting the "
            "unaltered physics stage. This is calibration-only static "
            "perception evidence and is not Student-training data."
        ),
    )
    parser.add_argument("--ready-file")
    parser.add_argument("--start-file")
    parser.add_argument("--barrier-timeout-s", type=float, default=600.0)
    parser.add_argument("--qrm-checkpoint")
    parser.add_argument(
        "--initial-joint-position",
        type=_parse_joint_position,
        help="public nine-DOF Panda observation used to initialize a shadow scene",
    )
    parser.add_argument(
        "--shadow-rollout",
        action="store_true",
        help="run all three explicit evaluation-only counterfactual probes",
    )
    parser.add_argument("--shadow-frames-per-candidate", type=int, default=4)
    parser.add_argument(
        "--qrm-model-id",
        choices=(
            "Q0_COARSE_ONLY",
            "Q1_COARSE_MLP_RESIDUAL",
            "Q2_COARSE_MLP_FAILURE_CONTEXT",
        ),
        default="Q2_COARSE_MLP_FAILURE_CONTEXT",
    )
    args, unknown = parser.parse_known_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if args.warmup_frames < 1:
        parser.error("--warmup-frames must be at least one")
    if bool(args.ready_file) != bool(args.start_file):
        parser.error("--ready-file and --start-file must be provided together")
    if args.barrier_timeout_s <= 0:
        parser.error("--barrier-timeout-s must be positive")
    if args.shadow_rollout:
        if args.initial_joint_position is None:
            parser.error("--shadow-rollout requires --initial-joint-position")
        if args.shadow_frames_per_candidate < 2:
            parser.error("--shadow-frames-per-candidate must be at least two")
        expected_frames = args.shadow_frames_per_candidate * len(
            SHADOW_CANDIDATES
        )
        if args.frames != expected_frames:
            parser.error(
                f"shadow rollout requires --frames {expected_frames}, got "
                f"{args.frames}"
            )
        if args.qrm_checkpoint:
            parser.error("shadow physics probes cannot load a QRM checkpoint")
    elif args.initial_joint_position is not None:
        parser.error("--initial-joint-position is shadow-rollout only")
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
from pxr import Gf, PhysxSchema, Sdf, Semantics, Usd, UsdGeom, UsdPhysics, UsdShade


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
ANNOTATORS = (
    "rgb",
    "distance_to_image_plane",
    "semantic_segmentation",
    "instance_segmentation",
)
PANDA_DOF_NAMES = tuple(
    [f"panda_joint{index}" for index in range(1, 8)]
    + ["panda_finger_joint1", "panda_finger_joint2"]
)


def _load_qrm_checkpoint(path: str, expected_model_id: str):
    from xh_agent.policy.qrm_lite.models_q012 import build_formal_model

    payload = np.load(path)
    observed_model_id = str(payload["model_id"])
    if observed_model_id != expected_model_id:
        raise ValueError(
            f"QRM checkpoint model mismatch: {observed_model_id} != {expected_model_id}"
        )
    model = build_formal_model(observed_model_id)
    for name in ("w1", "b1", "w2", "b2"):
        setattr(model.coarse, name, np.asarray(payload[f"coarse_{name}"]))
        setattr(model.mlp, name, np.asarray(payload[f"mlp_{name}"]))
    return model


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
    physics_material: UsdShade.Material,
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
    UsdShade.MaterialBindingAPI.Apply(geometry.GetPrim()).Bind(
        physics_material,
        UsdShade.Tokens.weakerThanDescendants,
        "physics",
    )
    return geometry.GetPrim()


def _create_link(
    stage: Usd.Stage,
    model_path: str,
    link: LinkVisuals,
    semantic_class: str,
    physics_material: UsdShade.Material,
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
            physics_material,
        )


def _create_model(
    stage: Usd.Stage,
    model: SceneModel,
    physics_material: UsdShade.Material,
) -> None:
    model_path = f"/World/M1B/{model.name}"
    model_xform = UsdGeom.Xform.Define(stage, model_path)
    _apply_pose(model_xform, model.pose)
    _apply_semantics(model_xform.GetPrim(), model.semantic_class)
    for link in model.links:
        _create_link(
            stage,
            model_path,
            link,
            model.semantic_class,
            physics_material,
        )
        if not model.static:
            link_prim = stage.GetPrimAtPath(f"{model_path}/{link.name}")
            UsdPhysics.RigidBodyAPI.Apply(link_prim)
            physx_rigid_body = PhysxSchema.PhysxRigidBodyAPI.Apply(link_prim)
            physx_rigid_body.CreateSleepThresholdAttr().Set(
                BULLET_FEATHERSTONE_SLEEP_THRESHOLD
            )
            if (link.linear_velocity_decay is None) != (
                link.angular_velocity_decay is None
            ):
                raise RuntimeError(
                    f"dynamic link {model.name}/{link.name} has a partial "
                    "SDF velocity-decay contract"
                )
            if link.linear_velocity_decay is not None:
                assert link.angular_velocity_decay is not None
                physx_rigid_body.CreateLinearDampingAttr().Set(
                    link.linear_velocity_decay
                )
                physx_rigid_body.CreateAngularDampingAttr().Set(
                    link.angular_velocity_decay
                )


def _create_sdf_default_physics_material(
    stage: Usd.Stage,
) -> UsdShade.Material:
    """Port SDFormat's default rigid-contact surface coefficients explicitly."""

    material = UsdShade.Material.Define(
        stage,
        "/World/M1B/SDFDefaultPhysicsMaterial",
    )
    physics_material = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics_material.CreateStaticFrictionAttr().Set(
        SDF_DEFAULT_SURFACE_FRICTION
    )
    physics_material.CreateDynamicFrictionAttr().Set(
        SDF_DEFAULT_SURFACE_FRICTION
    )
    physics_material.CreateRestitutionAttr().Set(
        SDF_DEFAULT_SURFACE_RESTITUTION
    )
    return material


def _validate_stage_physics(stage: Usd.Stage) -> dict[str, object]:
    collision_paths: list[str] = []
    rigid_body_paths: list[str] = []
    mass_paths: list[str] = []
    rigid_body_damping: dict[str, dict[str, float]] = {}
    rigid_body_sleep_thresholds: dict[str, float] = {}
    for model in SCENE.models:
        for link in model.links:
            link_path = f"/World/M1B/{model.name}/{link.name}"
            link_prim = stage.GetPrimAtPath(link_path)
            if not model.static:
                if not link_prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    raise RuntimeError(f"missing rigid-body API on {link_path}")
                rigid_body_paths.append(link_path)
                physx_rigid_body = PhysxSchema.PhysxRigidBodyAPI(link_prim)
                sleep_threshold = float(
                    physx_rigid_body.GetSleepThresholdAttr().Get()
                )
                expected_sleep_threshold = float(
                    PHYSICS_CONTRACT["source_engine_sleep_threshold"]["value"]
                )
                if not math.isclose(
                    sleep_threshold,
                    expected_sleep_threshold,
                    abs_tol=1e-9,
                ):
                    raise RuntimeError(
                        f"PhysX sleep threshold mismatch on {link_path}: "
                        f"{sleep_threshold}"
                    )
                rigid_body_sleep_thresholds[link_path] = sleep_threshold
                if link.linear_velocity_decay is not None:
                    assert link.angular_velocity_decay is not None
                    linear_damping = float(
                        physx_rigid_body.GetLinearDampingAttr().Get()
                    )
                    angular_damping = float(
                        physx_rigid_body.GetAngularDampingAttr().Get()
                    )
                    if not math.isclose(
                        linear_damping,
                        link.linear_velocity_decay,
                        abs_tol=1e-9,
                    ) or not math.isclose(
                        angular_damping,
                        link.angular_velocity_decay,
                        abs_tol=1e-9,
                    ):
                        raise RuntimeError(
                            f"PhysX damping mismatch on {link_path}: "
                            f"{linear_damping}/{angular_damping}"
                        )
                    rigid_body_damping[link_path] = {
                        "linear": linear_damping,
                        "angular": angular_damping,
                    }
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
    material_prim = stage.GetPrimAtPath("/World/M1B/SDFDefaultPhysicsMaterial")
    material_api = UsdPhysics.MaterialAPI(material_prim)
    sdf_default_surface = {
        "static_friction": float(material_api.GetStaticFrictionAttr().Get()),
        "dynamic_friction": float(material_api.GetDynamicFrictionAttr().Get()),
        "restitution": float(material_api.GetRestitutionAttr().Get()),
    }
    if sdf_default_surface != PHYSICS_CONTRACT["sdf_default_surface"]:
        raise RuntimeError(
            "stage physics material does not match the SDF default surface"
        )
    return {
        "collision_paths": collision_paths,
        "rigid_body_paths": rigid_body_paths,
        "mass_paths": mass_paths,
        "rigid_body_damping": rigid_body_damping,
        "rigid_body_sleep_thresholds": rigid_body_sleep_thresholds,
        "sdf_default_surface": sdf_default_surface,
    }


def _freeze_cylinders_for_static_perception_audit(
    stage: Usd.Stage,
) -> list[str]:
    """Make source poses kinematic for an explicitly offline static audit.

    The production-equivalent physics stage is exported before this function
    runs. No simulator truth is read and the resulting capture is marked
    ineligible for Student training.
    """

    frozen_paths: list[str] = []
    for model in SCENE.models:
        if model.semantic_class != "industrial_cylinder":
            continue
        if model.static:
            raise RuntimeError(
                f"static-perception audit expected dynamic cylinder {model.name}"
            )
        for link in model.links:
            link_path = f"/World/M1B/{model.name}/{link.name}"
            prim = stage.GetPrimAtPath(link_path)
            if not prim.HasAPI(UsdPhysics.RigidBodyAPI):
                raise RuntimeError(
                    f"static-perception audit cannot freeze {link_path}"
                )
            rigid_body = UsdPhysics.RigidBodyAPI(prim)
            rigid_body.CreateKinematicEnabledAttr().Set(True)
            frozen_paths.append(link_path)
    if len(frozen_paths) != SCENE.cylinder_count:
        raise RuntimeError(
            "static-perception audit did not freeze exactly one body per cylinder"
        )
    return frozen_paths


def _create_robot(
    stage: Usd.Stage,
    robot_usd: str,
    base_pose: Pose,
    gripper_variant: str,
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
    available_variants = {
        set_name: list(
            robot_prim.GetVariantSets()
            .GetVariantSet(set_name)
            .GetVariantNames()
        )
        for set_name in ("Gripper", "Mesh")
    }
    variants = {
        "Gripper": gripper_variant,
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
    robot_prim.SetCustomDataByKey(
        "xhM1BOfficialAssetContract",
        {
            "asset": "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd",
            "provenance": "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD",
            "variants": variants,
            "available_variants": available_variants,
            "local_simplified_robot_used": False,
        },
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


def _configure_camera_optics(
    stage: Usd.Stage,
    camera_specs: tuple[CameraSpec, ...],
) -> None:
    for camera_spec in camera_specs:
        matches = [
            prim
            for prim in stage.Traverse()
            if prim.IsA(UsdGeom.Camera) and prim.GetName() == camera_spec.name
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one USD camera named {camera_spec.name}, got "
                f"{[str(prim.GetPath()) for prim in matches]}"
            )
        camera = UsdGeom.Camera(matches[0])
        horizontal_aperture_mm = float(camera.GetHorizontalApertureAttr().Get())
        if horizontal_aperture_mm <= 0:
            raise RuntimeError("Isaac camera horizontal aperture is invalid")
        width, height = camera_spec.resolution
        vertical_aperture_mm = horizontal_aperture_mm * height / width
        focal_length_mm = horizontal_aperture_mm / (
            2.0 * math.tan(camera_spec.horizontal_fov_rad / 2.0)
        )
        camera.GetVerticalApertureAttr().Set(vertical_aperture_mm)
        camera.GetFocalLengthAttr().Set(focal_length_mm)
        camera.GetHorizontalApertureOffsetAttr().Set(0.0)
        camera.GetVerticalApertureOffsetAttr().Set(0.0)
        camera.GetClippingRangeAttr().Set(Gf.Vec2f(*camera_spec.clipping_range_m))


def _create_annotators(
    cameras: tuple[CameraSpec, ...],
    render_products: list[Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if len(cameras) != len(render_products):
        raise RuntimeError("camera/render-product count mismatch")
    for camera_spec, render_product in zip(cameras, render_products):
        camera_annotators = {
            "rgb": rep.AnnotatorRegistry.get_annotator("rgb"),
            "distance_to_image_plane": rep.AnnotatorRegistry.get_annotator(
                "distance_to_image_plane"
            ),
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
    if ARGS.initial_joint_position is not None:
        home = list(ARGS.initial_joint_position)
    else:
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
    if ARGS.shadow_rollout:
        candidate_index = min(
            frame_index // ARGS.shadow_frames_per_candidate,
            len(SHADOW_CANDIDATES) - 1,
        )
        return shadow_target_positions(
            home,
            indices,
            frame_index % ARGS.shadow_frames_per_candidate,
            worker_id,
            SHADOW_CANDIDATES[candidate_index],
        )
    phase = 2.0 * math.pi * frame_index / 100.0 + worker_id * 0.37
    target = list(home)
    target[indices["panda_joint1"]] += 0.20 * math.sin(phase)
    target[indices["panda_joint2"]] += 0.10 * math.sin(phase * 0.7)
    target[indices["panda_joint4"]] += 0.12 * math.cos(phase * 0.5)
    target[indices["panda_joint6"]] += 0.15 * math.sin(phase * 0.9)
    return target


def _numpy_values(values: Any) -> np.ndarray:
    array = values.numpy() if hasattr(values, "numpy") else np.asarray(values)
    return np.asarray(array, dtype=float).reshape(-1)


def _world_pose_xyzw(stage: Usd.Stage, prim_path: str) -> list[float]:
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        raise RuntimeError(f"missing pose prim: {prim_path}")
    transform = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
    translation = transform.ExtractTranslation()
    quaternion = transform.ExtractRotationQuat()
    imaginary = quaternion.GetImaginary()
    return [
        float(translation[0]),
        float(translation[1]),
        float(translation[2]),
        float(imaginary[0]),
        float(imaginary[1]),
        float(imaginary[2]),
        float(quaternion.GetReal()),
    ]


def _policy_camera_calibration(
    stage: Usd.Stage,
    camera_spec: CameraSpec,
) -> dict[str, Any]:
    matches = [
        prim
        for prim in stage.Traverse()
        if prim.IsA(UsdGeom.Camera) and prim.GetName() == camera_spec.name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one USD camera named {camera_spec.name}, got "
            f"{[str(prim.GetPath()) for prim in matches]}"
        )
    prim = matches[0]
    camera = UsdGeom.Camera(prim)
    focal_length_mm = float(camera.GetFocalLengthAttr().Get())
    horizontal_aperture_mm = float(camera.GetHorizontalApertureAttr().Get())
    vertical_aperture_mm = float(camera.GetVerticalApertureAttr().Get())
    horizontal_offset_mm = float(camera.GetHorizontalApertureOffsetAttr().Get())
    vertical_offset_mm = float(camera.GetVerticalApertureOffsetAttr().Get())
    width, height = camera_spec.resolution
    if min(
        focal_length_mm,
        horizontal_aperture_mm,
        vertical_aperture_mm,
        width,
        height,
    ) <= 0:
        raise RuntimeError("official Isaac camera has invalid calibrated aperture")
    fx = width * focal_length_mm / horizontal_aperture_mm
    fy = height * focal_length_mm / vertical_aperture_mm
    cx = width / 2.0 + width * horizontal_offset_mm / horizontal_aperture_mm
    cy = height / 2.0 - height * vertical_offset_mm / vertical_aperture_mm

    # USD cameras look along local -Z with local +Y up.  Public RGB-D uses the
    # conventional optical frame +X right, +Y down, +Z forward.  TransformDir
    # avoids depending on USD's internal row-vector matrix storage.
    transform = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
    origin = transform.Transform(Gf.Vec3d(0.0, 0.0, 0.0))
    optical_x = transform.TransformDir(Gf.Vec3d(1.0, 0.0, 0.0)).GetNormalized()
    optical_y = transform.TransformDir(Gf.Vec3d(0.0, -1.0, 0.0)).GetNormalized()
    optical_z = transform.TransformDir(Gf.Vec3d(0.0, 0.0, -1.0)).GetNormalized()
    camera_to_world_optical = [
        float(optical_x[0]),
        float(optical_y[0]),
        float(optical_z[0]),
        float(origin[0]),
        float(optical_x[1]),
        float(optical_y[1]),
        float(optical_z[1]),
        float(origin[1]),
        float(optical_x[2]),
        float(optical_y[2]),
        float(optical_z[2]),
        float(origin[2]),
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    return {
        "name": camera_spec.name,
        "prim_path": str(prim.GetPath()),
        "rgb_uri_prefix": f"dataset://{camera_spec.name}/rgb/",
        "depth_uri_prefix": f"dataset://{camera_spec.name}/depth/",
        "camera_intrinsics": [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0],
        "camera_to_world_optical": camera_to_world_optical,
        "depth_semantics": "METRIC_DISTANCE_TO_IMAGE_PLANE",
        "usd_camera_parameters_mm": {
            "focal_length": focal_length_mm,
            "horizontal_aperture": horizontal_aperture_mm,
            "vertical_aperture": vertical_aperture_mm,
            "horizontal_aperture_offset": horizontal_offset_mm,
            "vertical_aperture_offset": vertical_offset_mm,
        },
    }


def _gripper_state(dof_positions: np.ndarray, dof_indices: dict[str, int]) -> str:
    width = sum(
        abs(float(dof_positions[dof_indices[name]]))
        for name in ("panda_finger_joint1", "panda_finger_joint2")
    )
    if width >= 0.03:
        return "open"
    if width <= 0.005:
        return "closed"
    return "partially_open"


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
    physics_material = _create_sdf_default_physics_material(stage)
    for model in SCENE.models:
        _create_model(stage, model, physics_material)
    stage_physics = _validate_stage_physics(stage)
    robot_geometry_prim_count, robot_variants = _create_robot(
        stage,
        robot_asset_uri,
        ROBOT_BASE_POSE,
        ARGS.gripper_variant,
    )
    physics_stage_path = output / "m1b_physics_scene.usdc"
    if not stage.Export(str(physics_stage_path)):
        raise RuntimeError(f"failed to export clean physics stage: {physics_stage_path}")
    static_audit_frozen_paths = (
        _freeze_cylinders_for_static_perception_audit(stage)
        if ARGS.static_perception_audit
        else []
    )
    _, render_products = _create_cameras(SCENE)
    _configure_camera_optics(stage, SCENE.cameras)
    annotators = _create_annotators(SCENE.cameras, render_products)
    policy_camera_spec = next(
        camera for camera in SCENE.cameras if camera.name == "policy_rgbd"
    )
    policy_camera_calibration = _policy_camera_calibration(
        stage,
        policy_camera_spec,
    )
    qrm_model = (
        _load_qrm_checkpoint(ARGS.qrm_checkpoint, ARGS.qrm_model_id)
        if ARGS.qrm_checkpoint
        else None
    )
    if qrm_model is not None:
        from xh_agent.perception.geometric_rgbd import GeometricRGBDBaseline

        qrm_public_perception = GeometricRGBDBaseline()
    else:
        qrm_public_perception = None

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
    runtime_frames_path = output / "runtime_frames.jsonl"
    supervision_frames_path = output / "supervision_frames.jsonl"
    runtime_stream = runtime_frames_path.open("w", encoding="utf-8")
    supervision_stream = supervision_frames_path.open("w", encoding="utf-8")
    episode_id = f"isaac-m1b-worker-{ARGS.worker_id}"
    qrm_decisions: list[dict[str, object]] = []
    shadow_rollouts: list[dict[str, object]] = []
    shadow_semantic_pixel_counts: dict[str, dict[str, int]] = {
        candidate: {} for candidate in SHADOW_CANDIDATES
    }
    shadow_rollout_started = 0.0
    benchmark_start = time.perf_counter()
    for frame in range(ARGS.frames):
        shadow_candidate = (
            SHADOW_CANDIDATES[
                frame // ARGS.shadow_frames_per_candidate
            ]
            if ARGS.shadow_rollout
            else None
        )
        if (
            ARGS.shadow_rollout
            and frame % ARGS.shadow_frames_per_candidate == 0
        ):
            timeline = omni.timeline.get_timeline_interface()
            timeline.stop()
            simulation_app.update()
            timeline.play()
            # A stop invalidates articulation physics tensors.  Advance Kit
            # once after play so the existing Articulation view is rebound
            # before reset_to_default_state touches that tensor entity.
            simulation_app.update()
            robot.reset_to_default_state()
            simulation_app.update()
            for warmup_frame in range(ARGS.warmup_frames):
                robot.set_dof_position_targets(
                    shadow_target_positions(
                        home,
                        dof_indices,
                        warmup_frame,
                        ARGS.worker_id,
                        shadow_candidate,
                    )
                )
                rep.orchestrator.step(
                    rt_subframes=1,
                    delta_time=1.0 / 30.0,
                    pause_timeline=False,
                )
            shadow_rollout_started = time.perf_counter()
        action_target = _target_positions(
            home,
            dof_indices,
            frame if ARGS.shadow_rollout else frame + ARGS.warmup_frames,
            ARGS.worker_id,
        )
        robot.set_dof_position_targets(action_target)
        capture_start = time.perf_counter()
        rep.orchestrator.step(rt_subframes=1, delta_time=1.0 / 30.0, pause_timeline=False)
        capture_times.append(time.perf_counter() - capture_start)

        write_start = time.perf_counter()
        policy_rgb = None
        policy_depth = None
        for camera in SCENE.cameras:
            camera_root = output / camera.name
            camera_annotators = annotators[camera.name]
            rgb, _ = _annotator_array_and_info(camera_annotators["rgb"].get_data())
            depth, _ = _annotator_array_and_info(
                camera_annotators["distance_to_image_plane"].get_data()
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
            if camera.name == "policy_rgbd":
                policy_rgb = rgb[:, :, :3].copy()
                policy_depth = depth.copy()
            for semantic_class, pixels in _semantic_pixel_counts(
                semantic, semantic_info
            ).items():
                semantic_pixel_counts[semantic_class] = (
                    semantic_pixel_counts.get(semantic_class, 0) + pixels
                )
                if shadow_candidate is not None:
                    candidate_counts = shadow_semantic_pixel_counts[
                        shadow_candidate
                    ]
                    candidate_counts[semantic_class] = (
                        candidate_counts.get(semantic_class, 0) + pixels
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

        timestamp_ns = int(
            round(omni.timeline.get_timeline_interface().get_current_time() * 1e9)
        )
        dof_positions = _numpy_values(robot.get_dof_positions())
        dof_velocities = _numpy_values(robot.get_dof_velocities())
        if len(dof_positions) != len(PANDA_DOF_NAMES) or len(dof_velocities) != len(
            PANDA_DOF_NAMES
        ):
            raise RuntimeError("official Franka runtime state is not nine-dimensional")
        stem = f"{frame:06d}"
        runtime_record = {
            "schema_version": "IsaacM1BRuntimeFrameV1",
            "episode_id": episode_id,
            "step_id": frame,
            "timestamp_ns": timestamp_ns,
            "policy_camera": {
                "schema_version": "IsaacM1BPolicyCameraFrameV1",
                "name": "policy_rgbd",
                "rgb_uri": f"dataset://policy_rgbd/rgb/{stem}.png",
                "depth_uri": f"dataset://policy_rgbd/depth/{stem}.npy",
                "camera_intrinsics": policy_camera_calibration["camera_intrinsics"],
                "camera_to_world_optical": policy_camera_calibration[
                    "camera_to_world_optical"
                ],
                "depth_semantics": "METRIC_DISTANCE_TO_IMAGE_PLANE",
            },
            "joint_names": list(PANDA_DOF_NAMES),
            "joint_position": dof_positions.tolist(),
            "joint_velocity": dof_velocities.tolist(),
            "end_effector_pose_world_xyzw": _world_pose_xyzw(
                stage,
                "/World/Robot/panda_hand",
            ),
            "gripper_state": _gripper_state(dof_positions, dof_indices),
            "action_target_joint_position": action_target,
            "action_frequency_hz": 30.0,
            "action_normalization": "identity",
            "shadow_candidate": shadow_candidate,
        }
        simulator_poses = {
            model.name: _world_pose_xyzw(
                stage,
                f"/World/M1B/{model.name}/{model.links[0].name}",
            )
            for model in SCENE.dynamic_models
        }
        supervision_record = {
            "schema_version": "IsaacM1BSupervisionFrameV1",
            "training_and_evaluation_only": True,
            "episode_id": episode_id,
            "step_id": frame,
            "timestamp_ns": timestamp_ns,
            "perfect_object_poses_world_xyzw": simulator_poses,
            "contacts": [],
            "collisions": [],
            "grasp_states": {},
            "slip_events": [],
            "task_success": False,
            "physical_parameters": {
                "industrial_cylinder_mass_kg": float(
                    SCENE.dynamic_models[0].links[0].mass_kg or 0.0
                ),
                "industrial_cylinder_count": float(SCENE.cylinder_count),
                "static_perception_audit_kinematic_freeze": float(
                    ARGS.static_perception_audit
                ),
            },
            "failure_injection": {},
            "shadow_candidate": shadow_candidate,
            "simulator": "Isaac Sim",
            "simulator_version": "6.0.1",
        }
        runtime_stream.write(json.dumps(runtime_record, sort_keys=True) + "\n")
        supervision_stream.write(json.dumps(supervision_record, sort_keys=True) + "\n")
        if qrm_model is not None:
            if (
                policy_rgb is None
                or policy_depth is None
                or qrm_public_perception is None
            ):
                raise RuntimeError("QRM closed-loop smoke lacks public RGB-D")
            from xh_agent.perception.interfaces import PerceptionInputV1
            from xh_agent.policy.qrm_lite.contracts import (
                FailureContextV1,
                FailureType,
                PerceptionTrackV1,
                QRMObservationV1,
            )
            from xh_agent.policy.qrm_lite.transforms import (
                build_identity_action_chunk,
            )

            public_results = qrm_public_perception.infer(
                PerceptionInputV1(
                    frame_id="policy_rgbd",
                    timestamp_ns=timestamp_ns,
                    rgb_uri=runtime_record["policy_camera"]["rgb_uri"],
                    depth_uri=runtime_record["policy_camera"]["depth_uri"],
                    camera_intrinsics=policy_camera_calibration[
                        "camera_intrinsics"
                    ],
                    camera_frame="policy_rgbd_optical",
                ),
                policy_depth,
                policy_rgb,
            )
            public_missing = not public_results
            observation = QRMObservationV1(
                episode_id=f"{episode_id}-qrm-{frame:06d}",
                step_id=frame,
                timestamp_ns=timestamp_ns,
                instruction=(
                    "Choose a safe coarse skill for the publicly observed "
                    "industrial cylinder scene."
                ),
                rgb_uri=runtime_record["policy_camera"]["rgb_uri"],
                depth_uri=runtime_record["policy_camera"]["depth_uri"],
                camera_frame="policy_rgbd_optical",
                camera_intrinsics=policy_camera_calibration[
                    "camera_intrinsics"
                ],
                joint_position=dof_positions.tolist(),
                joint_velocity=dof_velocities.tolist(),
                gripper_state={
                    "open": 0.0,
                    "partially_open": 0.5,
                    "closed": 1.0,
                }[runtime_record["gripper_state"]],
                current_skill_stage=(
                    "REOBSERVE" if public_missing else "APPROACH"
                ),
                perception_tracks=[
                    PerceptionTrackV1(
                        track_id=result.track_id,
                        category=result.category,
                        confidence=result.confidence,
                        pose_xyzquat=[
                            *result.position_3d,
                            0.0,
                            0.0,
                            0.0,
                            1.0,
                        ],
                    )
                    for result in public_results
                ],
                failure_context=FailureContextV1(
                    last_skill="OBSERVE",
                    expected_predicates=["public_track_observed"],
                    observed_predicates=(
                        [] if public_missing else ["public_track_observed"]
                    ),
                    predicate_residual=(
                        ["missing:public_track_observed"]
                        if public_missing
                        else []
                    ),
                    failure_type=(
                        FailureType.TRACKING_LOST
                        if public_missing
                        else FailureType.NONE
                    ),
                    retry_count=0,
                ),
            )
            nominal = build_identity_action_chunk(4)
            decision_output = qrm_model.predict(
                observation,
                nominal=nominal if qrm_model.uses_residual else None,
                moveit_accept_fn=lambda _: (
                    False,
                    "UNVERIFIED_CAMERA_RESIDUAL_TO_JOINT_MAPPING",
                ),
            )
            qrm_decisions.append(
                {
                    "step_id": frame,
                    "model_id": qrm_model.model_id.value,
                    "public_track_count": len(public_results),
                    "failure_context": observation.failure_context.model_dump(
                        mode="json"
                    ),
                    "coarse_skill": decision_output.coarse.skill_type,
                    "used_failure_context": decision_output.used_failure_context,
                    "residual_proposed": decision_output.residual is not None,
                    "mapping_validation": (
                        "REJECTED_NO_OFFICIAL_EVIDENCE"
                    ),
                    "fallback": "B0_DATASET_EXCITATION",
                    "applies_to_step": (
                        frame + 1 if frame + 1 < ARGS.frames else None
                    ),
                }
            )
        if (
            shadow_candidate is not None
            and (frame + 1) % ARGS.shadow_frames_per_candidate == 0
        ):
            final_shadow_positions = _numpy_values(robot.get_dof_positions())
            shadow_rollouts.append(
                {
                    "candidate": shadow_candidate,
                    "frames": ARGS.shadow_frames_per_candidate,
                    "rollout_latency_s": (
                        time.perf_counter() - shadow_rollout_started
                    ),
                    "final_joint_position": final_shadow_positions.tolist(),
                    "final_end_effector_pose_world_xyzw": _world_pose_xyzw(
                        stage,
                        "/World/Robot/panda_hand",
                    ),
                    "semantic_pixel_counts": dict(
                        shadow_semantic_pixel_counts[shadow_candidate]
                    ),
                    "collision_observed": None,
                    "collision_evidence_available": False,
                    "task_success": None,
                    "public_visibility_predicate": (
                        shadow_semantic_pixel_counts[shadow_candidate].get(
                            "industrial_cylinder",
                            0,
                        )
                        >= ARGS.shadow_frames_per_candidate * 100
                    ),
                }
            )
        readback_write_times.append(time.perf_counter() - write_start)

    runtime_stream.close()
    supervision_stream.close()
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
        "dataset_benchmark_source_sha256": sha256_file(__file__),
        "capture_mode": (
            "CALIBRATION_ONLY_STATIC_PERCEPTION"
            if ARGS.static_perception_audit
            else (
                "SHADOW_COUNTERFACTUAL_EVAL_ONLY"
                if ARGS.shadow_rollout
                else "DYNAMIC_STUDENT_DATASET"
            )
        ),
        "worker_id": ARGS.worker_id,
        "physical_gpu_index": ARGS.physical_gpu_index,
        "renderer": "RaytracedLighting",
        "multi_gpu": False,
        "frames": ARGS.frames,
        "warmup_frames": ARGS.warmup_frames,
        "camera_count": len(SCENE.cameras),
        "cameras": [_json_ready(camera.__dict__) for camera in SCENE.cameras],
        "annotators": list(ANNOTATORS),
        "policy_camera_calibration": policy_camera_calibration,
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
        "static_perception_audit": {
            "enabled": ARGS.static_perception_audit,
            "frozen_rigid_body_paths": static_audit_frozen_paths,
            "clean_physics_stage_exported_before_freeze": True,
            "simulator_truth_read_for_freeze": False,
            "student_training_eligible": (
                not ARGS.static_perception_audit
                and not ARGS.shadow_rollout
            ),
            "scope": (
                "CALIBRATION_ONLY_STATIC_PERCEPTION_NOT_CONTROL_OR_TRAINING"
                if ARGS.static_perception_audit
                else "NOT_APPLICABLE"
            ),
        },
        "student_dataset_protocol": {
            "runtime_frames": runtime_frames_path.name,
            "runtime_frames_sha256": sha256_file(runtime_frames_path),
            "supervision_frames": supervision_frames_path.name,
            "supervision_frames_sha256": sha256_file(supervision_frames_path),
            "streams_physically_separate": True,
            "policy_camera": "policy_rgbd",
            "policy_segmentation_input": False,
            "teacher_required": False,
            "training_eligible": (
                not ARGS.static_perception_audit
                and not ARGS.shadow_rollout
            ),
            "offline_transition_builder": "scripts/build_isaac_m1b_transitions.py",
        },
        "action_protocol": {
            "frame": "PANDA_JOINT_ORDER_BY_NAME",
            "units": "radian_arm_metre_finger",
            "dimensions": 9,
            "frequency_hz": 30,
            "normalization": "none",
            "source": (
                "explicit_shadow_joint_space_physics_probe_not_policy_action"
                if ARGS.shadow_rollout
                else "deterministic_dataset_excitation_not_policy_action"
            ),
        },
        "shadow_counterfactual": {
            "enabled": ARGS.shadow_rollout,
            "initial_joint_position": (
                list(ARGS.initial_joint_position)
                if ARGS.initial_joint_position is not None
                else None
            ),
            "initialization_source": (
                "PUBLIC_QRM_OBSERVATION"
                if ARGS.shadow_rollout
                else None
            ),
            "profiles": shadow_rollouts,
            "candidate_order": (
                list(SHADOW_CANDIDATES)
                if ARGS.shadow_rollout
                else []
            ),
            "reset_method": (
                "TIMELINE_STOP_PLAY_PLUS_PUBLIC_ROBOT_STATE"
                if ARGS.shadow_rollout
                else None
            ),
            "privileged_truth_policy_input": False,
            "model_action_mapping_used": False,
            "training_eligible": False,
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
        "qrm_closed_loop_smoke": {
            "enabled": qrm_model is not None,
            "checkpoint": ARGS.qrm_checkpoint,
            "model_id": (
                ARGS.qrm_model_id if qrm_model is not None else None
            ),
            "decisions": qrm_decisions,
            "decision_count": len(qrm_decisions),
            "fallback_count": len(qrm_decisions),
            "fallback_rate": 1.0 if qrm_decisions else None,
            "model_action_mapping": (
                "REJECTED_NO_OFFICIAL_EVIDENCE"
            ),
            "b0_executed_after_rejection": bool(qrm_decisions),
        },
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
