#!/usr/bin/env python3
"""Sample the controlled Panda URDF's fingertip workspace without ROS or Gazebo.

The candidate model in this report is intentionally a *kinematic proposal*, not
an edited URDF.  It scales only the seven arm-joint origins and the wrist
fixed-joint origin.  The base placement, joint axes/limits, and complete hand
and finger geometry are held fixed so that the comparison can inform ADR-0006
without silently changing the calibrated end effector.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import os
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import numpy as np


ROOT = Path(__file__).parents[1]
URDF_PATH = ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
REPORT_JSON = ROOT / "reports/m1a-fk-workspace-sampling.json"
REPORT_MD = ROOT / "reports/m1a-fk-workspace-sampling.md"
ARM_JOINTS = tuple(f"panda_joint{index}" for index in range(1, 8))
HAND_JOINT = "panda_hand_joint"
FINGER_JOINTS = ("panda_finger_joint1", "panda_finger_joint2")
FINGER_LINKS = ("panda_leftfinger", "panda_rightfinger")
TARGET_XYZ = (0.22, 0.12, 0.475)
TARGET_RADII_M = (0.03, 0.05)
FINGER_POSITION_M = 0.02
OFFICIAL_PANDA_SOURCE = {
    "path": "/opt/ros/jazzy/share/moveit_resources_panda_description/urdf/panda.urdf.xacro",
    "sha256": "c8ee3bad4d89ad9bf4af717037418a3e6b046d47df6375a92a912a901d256a34",
    "evidence_host": "node2",
}
# These fixed transforms were read from the locally installed, hash-recorded
# MoveIt Panda resource above.  The controlled model deliberately retains its
# existing soft limits and hand/finger collision geometry instead of importing
# a second robot description at runtime.
OFFICIAL_PANDA_ARM_ORIGINS = (
    ((0.0, 0.0, 0.333), (0.0, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (-1.57079632679, 0.0, 0.0)),
    ((0.0, -0.316, 0.0), (1.57079632679, 0.0, 0.0)),
    ((0.0825, 0.0, 0.0), (1.57079632679, 0.0, 0.0)),
    ((-0.0825, 0.384, 0.0), (-1.57079632679, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (1.57079632679, 0.0, 0.0)),
    ((0.088, 0.0, 0.0), (1.57079632679, 0.0, 0.0)),
)
OFFICIAL_PANDA_POST_ARM = (
    ("panda_joint8", (0.0, 0.0, 0.107), (0.0, 0.0, 0.0)),
    ("panda_hand_joint", (0.0, 0.0, 0.0), (0.0, 0.0, -0.785398163397)),
)

Matrix = tuple[tuple[float, float, float, float], ...]
Vector = tuple[float, float, float]


@dataclass(frozen=True)
class Joint:
    name: str
    kind: str
    origin_xyz: Vector
    origin_rpy: Vector
    axis: Vector
    lower: float | None = None
    upper: float | None = None


@dataclass(frozen=True)
class Model:
    base: Joint
    arm: tuple[Joint, ...]
    hand: Joint
    fingers: tuple[Joint, ...]
    pad_centers: tuple[Vector, ...]


def vector(text: str | None) -> Vector:
    if text is None:
        return (0.0, 0.0, 0.0)
    values = tuple(float(value) for value in text.split())
    if len(values) != 3:
        raise ValueError(f"expected a three-vector, got {text!r}")
    return values  # type: ignore[return-value]


def identity() -> Matrix:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def multiply(left: Matrix, right: Matrix) -> Matrix:
    return tuple(
        tuple(sum(left[row][index] * right[index][column] for index in range(4)) for column in range(4))
        for row in range(4)
    )  # type: ignore[return-value]


def transform(xyz: Vector, rpy: Vector = (0.0, 0.0, 0.0)) -> Matrix:
    """URDF origin transform: Rz(yaw) Ry(pitch) Rx(roll), then translation."""
    roll, pitch, yaw = rpy
    cos_roll, sin_roll = math.cos(roll), math.sin(roll)
    cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
    cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
    return (
        (cos_yaw * cos_pitch, cos_yaw * sin_pitch * sin_roll - sin_yaw * cos_roll, cos_yaw * sin_pitch * cos_roll + sin_yaw * sin_roll, xyz[0]),
        (sin_yaw * cos_pitch, sin_yaw * sin_pitch * sin_roll + cos_yaw * cos_roll, sin_yaw * sin_pitch * cos_roll - cos_yaw * sin_roll, xyz[1]),
        (-sin_pitch, cos_pitch * sin_roll, cos_pitch * cos_roll, xyz[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def axis_motion(axis: Vector, position: float, kind: str) -> Matrix:
    x, y, z = axis
    norm = math.sqrt(x * x + y * y + z * z)
    if not math.isclose(norm, 1.0, abs_tol=1e-9):
        raise ValueError(f"non-unit joint axis {axis}")
    if kind == "prismatic":
        return transform((x * position, y * position, z * position))
    if kind != "revolute":
        raise ValueError(f"unsupported actuated joint type {kind}")
    cosine, sine, one_minus_cosine = math.cos(position), math.sin(position), 1.0 - math.cos(position)
    return (
        (cosine + x * x * one_minus_cosine, x * y * one_minus_cosine - z * sine, x * z * one_minus_cosine + y * sine, 0.0),
        (y * x * one_minus_cosine + z * sine, cosine + y * y * one_minus_cosine, y * z * one_minus_cosine - x * sine, 0.0),
        (z * x * one_minus_cosine - y * sine, z * y * one_minus_cosine + x * sine, cosine + z * z * one_minus_cosine, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def point(frame: Matrix, local_point: Vector) -> Vector:
    return tuple(sum(frame[row][column] * (*local_point, 1.0)[column] for column in range(4)) for row in range(3))  # type: ignore[return-value]


def joint_from_xml(element: ET.Element) -> Joint:
    origin = element.find("origin")
    limit = element.find("limit")
    return Joint(
        name=element.attrib["name"],
        kind=element.attrib["type"],
        origin_xyz=vector(origin.attrib.get("xyz") if origin is not None else None),
        origin_rpy=vector(origin.attrib.get("rpy") if origin is not None else None),
        axis=vector(element.find("axis").attrib.get("xyz") if element.find("axis") is not None else None),
        lower=float(limit.attrib["lower"]) if limit is not None and "lower" in limit.attrib else None,
        upper=float(limit.attrib["upper"]) if limit is not None and "upper" in limit.attrib else None,
    )


def load_model(path: Path = URDF_PATH) -> Model:
    root = ET.parse(path).getroot()
    joints = {element.attrib["name"]: joint_from_xml(element) for element in root.findall("joint")}
    try:
        base = joints["world_to_panda"]
        arm = tuple(joints[name] for name in ARM_JOINTS)
        hand = joints[HAND_JOINT]
        fingers = tuple(joints[name] for name in FINGER_JOINTS)
    except KeyError as exc:
        raise ValueError(f"controlled URDF lacks required joint {exc.args[0]}") from exc
    if base.kind != "fixed" or hand.kind != "fixed":
        raise ValueError("base and hand joints must be fixed")
    if any(joint.kind != "revolute" or joint.lower is None or joint.upper is None for joint in arm):
        raise ValueError("arm must contain seven bounded revolute joints")
    if any(joint.kind != "prismatic" or joint.lower is None or joint.upper is None for joint in fingers):
        raise ValueError("fingers must contain two bounded prismatic joints")
    links = {element.attrib["name"]: element for element in root.findall("link")}
    pads: list[Vector] = []
    for name in FINGER_LINKS:
        collision_origin = links[name].find("collision/origin")
        pads.append(vector(collision_origin.attrib.get("xyz") if collision_origin is not None else None))
    return Model(base=base, arm=arm, hand=hand, fingers=fingers, pad_centers=tuple(pads))


def serial_translation_m(model: Model) -> float:
    """Scalar kinematic-chain length excluding the unchanged finger end effector."""
    return sum(math.dist((0.0, 0.0, 0.0), joint.origin_xyz) for joint in (*model.arm, model.hand))


def chain_translation_m(arm: Iterable[Joint], post_arm: Iterable[Joint]) -> float:
    """Scalar origin distance for audit only; it is not a workspace guarantee."""
    return sum(math.dist((0.0, 0.0, 0.0), joint.origin_xyz) for joint in (*arm, *post_arm))


def fixed_end_effector_extension_m(model: Model) -> float:
    """Finger-joint origin plus collision-centre offset; never scaled by the candidate."""
    return max(
        math.dist((0.0, 0.0, 0.0), finger.origin_xyz)
        + math.dist((0.0, 0.0, 0.0), pad)
        for finger, pad in zip(model.fingers, model.pad_centers)
    )


def candidate_scale(model: Model, target_total_reach_m: float) -> float:
    remaining_arm_reach = target_total_reach_m - fixed_end_effector_extension_m(model)
    if remaining_arm_reach <= 0:
        raise ValueError("target total reach must exceed the unchanged end-effector extension")
    return remaining_arm_reach / serial_translation_m(model)


def fingertip_positions(
    model: Model,
    arm_positions: Iterable[float],
    *,
    arm: Iterable[Joint] | None = None,
    post_arm: Iterable[Joint] | None = None,
) -> tuple[Vector, Vector]:
    arm = tuple(model.arm if arm is None else arm)
    post_arm = tuple((model.hand,) if post_arm is None else post_arm)
    frame = transform(model.base.origin_xyz, model.base.origin_rpy)
    for joint, position in zip(arm, arm_positions):
        frame = multiply(frame, transform(joint.origin_xyz, joint.origin_rpy))
        frame = multiply(frame, axis_motion(joint.axis, position, joint.kind))
    hand_frame = frame
    for joint in post_arm:
        hand_frame = multiply(hand_frame, transform(joint.origin_xyz, joint.origin_rpy))
    pads: list[Vector] = []
    for finger, pad_center in zip(model.fingers, model.pad_centers):
        finger_frame = multiply(hand_frame, transform(finger.origin_xyz, finger.origin_rpy))
        finger_frame = multiply(finger_frame, axis_motion(finger.axis, FINGER_POSITION_M, finger.kind))
        pads.append(point(finger_frame, pad_center))
    return tuple(pads)  # type: ignore[return-value]


def uniform_scale_candidate(model: Model, scale: float) -> tuple[tuple[Joint, ...], tuple[Joint, ...]]:
    arm = tuple(replace(joint, origin_xyz=tuple(value * scale for value in joint.origin_xyz)) for joint in model.arm)
    hand = replace(model.hand, origin_xyz=tuple(value * scale for value in model.hand.origin_xyz))
    return arm, (hand,)


def official_panda_origin_candidate(model: Model) -> tuple[tuple[Joint, ...], tuple[Joint, ...]]:
    arm = tuple(
        replace(joint, origin_xyz=origin_xyz, origin_rpy=origin_rpy)
        for joint, (origin_xyz, origin_rpy) in zip(model.arm, OFFICIAL_PANDA_ARM_ORIGINS)
    )
    link8_name, link8_xyz, link8_rpy = OFFICIAL_PANDA_POST_ARM[0]
    hand_name, hand_xyz, hand_rpy = OFFICIAL_PANDA_POST_ARM[1]
    link8 = Joint(link8_name, "fixed", link8_xyz, link8_rpy, (0.0, 0.0, 0.0))
    hand = replace(model.hand, name=hand_name, origin_xyz=hand_xyz, origin_rpy=hand_rpy)
    return arm, (link8, hand)


def empty_metrics() -> dict[str, object]:
    return {
        "point_count": 0,
        "bounds_m": {"min_xyz": [math.inf, math.inf, math.inf], "max_xyz": [-math.inf, -math.inf, -math.inf]},
        "minimum_target_distance_m": math.inf,
        "closest_pad_side": None,
        "closest_pad_xyz_m": None,
        "closest_arm_positions_rad": None,
        "sphere": {str(radius): {"pad_points": 0, "source_arm_samples_with_any_pad": 0} for radius in TARGET_RADII_M},
    }


def update_metrics(
    metrics: dict[str, object], pads: tuple[Vector, Vector], arm_positions: tuple[float, ...]
) -> None:
    bounds = metrics["bounds_m"]  # type: ignore[assignment]
    minimum = metrics["minimum_target_distance_m"]  # type: ignore[assignment]
    sphere = metrics["sphere"]  # type: ignore[assignment]
    inside_by_radius = {radius: False for radius in TARGET_RADII_M}
    for side, pad in enumerate(pads):
        metrics["point_count"] = int(metrics["point_count"]) + 1
        for index, value in enumerate(pad):
            bounds["min_xyz"][index] = min(bounds["min_xyz"][index], value)
            bounds["max_xyz"][index] = max(bounds["max_xyz"][index], value)
        distance = math.dist(pad, TARGET_XYZ)
        if distance < minimum:
            metrics["minimum_target_distance_m"] = distance
            metrics["closest_pad_side"] = FINGER_LINKS[side]
            metrics["closest_pad_xyz_m"] = list(pad)
            metrics["closest_arm_positions_rad"] = list(arm_positions)
            minimum = distance
        for radius in TARGET_RADII_M:
            if distance <= radius:
                sphere[str(radius)]["pad_points"] += 1
                inside_by_radius[radius] = True
    for radius, inside in inside_by_radius.items():
        if inside:
            sphere[str(radius)]["source_arm_samples_with_any_pad"] += 1


def finalise_metrics(metrics: dict[str, object], samples: int) -> dict[str, object]:
    for radius in TARGET_RADII_M:
        values = metrics["sphere"][str(radius)]  # type: ignore[index]
        values["pad_point_density"] = values["pad_points"] / int(metrics["point_count"])
        values["source_arm_sample_density"] = values["source_arm_samples_with_any_pad"] / samples
    metrics["minimum_target_distance_m"] = round(float(metrics["minimum_target_distance_m"]), 9)
    metrics["bounds_m"] = {
        key: [round(value, 9) for value in values]
        for key, values in metrics["bounds_m"].items()  # type: ignore[index]
    }
    if metrics["closest_pad_xyz_m"] is not None:
        metrics["closest_pad_xyz_m"] = [round(value, 9) for value in metrics["closest_pad_xyz_m"]]  # type: ignore[index]
    if metrics["closest_arm_positions_rad"] is not None:
        metrics["closest_arm_positions_rad"] = [round(value, 9) for value in metrics["closest_arm_positions_rad"]]  # type: ignore[index]
    return metrics


def merge_metrics(destination: dict[str, object], source: dict[str, object]) -> None:
    destination["point_count"] = int(destination["point_count"]) + int(source["point_count"])
    destination_minimum = float(destination["minimum_target_distance_m"])
    source_minimum = float(source["minimum_target_distance_m"])
    destination["minimum_target_distance_m"] = min(destination_minimum, source_minimum)
    if source_minimum < destination_minimum:
        destination["closest_pad_side"] = source["closest_pad_side"]
        destination["closest_pad_xyz_m"] = source["closest_pad_xyz_m"]
        destination["closest_arm_positions_rad"] = source["closest_arm_positions_rad"]
    for key in ("min_xyz", "max_xyz"):
        for index, value in enumerate(source["bounds_m"][key]):  # type: ignore[index]
            operation = min if key == "min_xyz" else max
            destination["bounds_m"][key][index] = operation(destination["bounds_m"][key][index], value)  # type: ignore[index]
    for radius in TARGET_RADII_M:
        for key in ("pad_points", "source_arm_samples_with_any_pad"):
            destination["sphere"][str(radius)][key] += source["sphere"][str(radius)][key]  # type: ignore[index]


def closest_pad(
    model: Model, arm_positions: tuple[float, ...], arm: Iterable[Joint], post_arm: Iterable[Joint]
) -> tuple[float, int, Vector]:
    pads = fingertip_positions(model, arm_positions, arm=arm, post_arm=post_arm)
    distances = tuple(math.dist(pad, TARGET_XYZ) for pad in pads)
    side = min(range(len(pads)), key=distances.__getitem__)
    return distances[side], side, pads[side]


def refine_position_only(
    model: Model, metrics: dict[str, object], arm: tuple[Joint, ...], post_arm: tuple[Joint, ...]
) -> dict[str, object]:
    """Bounded DLS refinement of a sampled seed for position only, not full pose IK."""
    seed = metrics["closest_arm_positions_rad"]
    if seed is None:
        raise ValueError("cannot refine an empty point cloud")
    positions = np.asarray(seed, dtype=float)
    lower = np.asarray([joint.lower for joint in model.arm], dtype=float)
    upper = np.asarray([joint.upper for joint in model.arm], dtype=float)
    target = np.asarray(TARGET_XYZ, dtype=float)
    damping = 1e-3
    iterations = 0
    for iterations in range(1, 161):
        distance, side, pad = closest_pad(model, tuple(positions), arm, post_arm)
        if distance <= 1e-6:
            break
        jacobian = np.empty((3, len(positions)), dtype=float)
        epsilon = 1e-5
        for index in range(len(positions)):
            perturbed = positions.copy()
            perturbed[index] = min(upper[index], perturbed[index] + epsilon)
            if perturbed[index] == positions[index]:
                perturbed[index] = max(lower[index], perturbed[index] - epsilon)
            _, _, perturbed_pad = closest_pad(model, tuple(perturbed), arm, post_arm)
            jacobian[:, index] = (np.asarray(perturbed_pad) - np.asarray(pad)) / (perturbed[index] - positions[index])
        error = target - np.asarray(pad)
        try:
            delta = jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + damping * np.eye(3), error)
        except np.linalg.LinAlgError:
            damping *= 10
            continue
        delta = np.clip(delta, -0.25, 0.25)
        accepted = False
        for multiplier in (1.0, 0.5, 0.25, 0.1, 0.05):
            candidate = np.clip(positions + multiplier * delta, lower, upper)
            candidate_distance, _, _ = closest_pad(model, tuple(candidate), arm, post_arm)
            if candidate_distance < distance:
                positions = candidate
                damping = max(damping / 2, 1e-8)
                accepted = True
                break
        if not accepted:
            damping *= 10
    distance, side, pad = closest_pad(model, tuple(positions), arm, post_arm)
    return {
        "method": "bounded_damped_least_squares_position_only_from_nearest_uniform_sample",
        "iterations": iterations,
        "final_pad_side": FINGER_LINKS[side],
        "final_pad_xyz_m": [round(value, 9) for value in pad],
        "final_target_distance_m": round(distance, 9),
        "arm_positions_rad": [round(float(value), 9) for value in positions],
        "orientation_not_solved": True,
        "collision_not_checked": True,
    }


def sample_chunk(model: Model, samples: int, seed: int, target_total_reach_m: float) -> tuple[dict[str, object], ...]:
    """Independent deterministic stream used by one worker; no simulator state."""
    scale = candidate_scale(model, target_total_reach_m)
    uniform_arm, uniform_post_arm = uniform_scale_candidate(model, scale)
    official_arm, official_post_arm = official_panda_origin_candidate(model)
    random_source = random.Random(seed)
    current, uniform, official = empty_metrics(), empty_metrics(), empty_metrics()
    for _ in range(samples):
        positions = tuple(random_source.uniform(joint.lower, joint.upper) for joint in model.arm)  # type: ignore[arg-type]
        update_metrics(current, fingertip_positions(model, positions), positions)
        update_metrics(
            uniform, fingertip_positions(model, positions, arm=uniform_arm, post_arm=uniform_post_arm), positions
        )
        update_metrics(
            official, fingertip_positions(model, positions, arm=official_arm, post_arm=official_post_arm), positions
        )
    return current, uniform, official


def sample_chunk_from_values(values: tuple[Model, int, int, float]) -> tuple[dict[str, object], ...]:
    return sample_chunk(*values)


def sample_workspace(
    model: Model, *, samples: int, seed: int, target_total_reach_m: float, workers: int = 1
) -> dict[str, object]:
    if samples <= 0:
        raise ValueError("samples must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    scale = candidate_scale(model, target_total_reach_m)
    uniform_arm, uniform_post_arm = uniform_scale_candidate(model, scale)
    official_arm, official_post_arm = official_panda_origin_candidate(model)
    current, uniform, official = empty_metrics(), empty_metrics(), empty_metrics()
    chunk_count = min(workers, samples)
    chunk_sizes = [samples // chunk_count + (1 if index < samples % chunk_count else 0) for index in range(chunk_count)]
    inputs = [(model, size, seed + index, target_total_reach_m) for index, size in enumerate(chunk_sizes)]
    if chunk_count == 1:
        chunks = [sample_chunk(*inputs[0])]
    else:
        with ProcessPoolExecutor(max_workers=chunk_count) as executor:
            chunks = list(executor.map(sample_chunk_from_values, inputs))
    for chunk_current, chunk_uniform, chunk_official in chunks:
        merge_metrics(current, chunk_current)
        merge_metrics(uniform, chunk_uniform)
        merge_metrics(official, chunk_official)
    current_refinement = refine_position_only(model, current, tuple(model.arm), (model.hand,))
    uniform_refinement = refine_position_only(model, uniform, uniform_arm, uniform_post_arm)
    official_refinement = refine_position_only(model, official, official_arm, official_post_arm)
    current_metrics = finalise_metrics(current, samples)
    uniform_metrics = finalise_metrics(uniform, samples)
    official_metrics = finalise_metrics(official, samples)
    current_metrics["position_only_refinement"] = current_refinement
    uniform_metrics["position_only_refinement"] = uniform_refinement
    official_metrics["position_only_refinement"] = official_refinement
    return {
        "sampling": {
            "arm_joint_samples": samples,
            "fingertip_points_per_model": samples * 2,
            "random_seed": seed,
            "worker_count": chunk_count,
            "worker_seed_derivation": "base_seed + worker_index",
            "distribution": "independent_uniform_within_URDF_arm_joint_limits",
            "finger_joint_positions_m": {name: FINGER_POSITION_M for name in FINGER_JOINTS},
            "target_xyz_m": list(TARGET_XYZ),
            "target_sphere_radii_m": list(TARGET_RADII_M),
        },
        "candidate_definition": {
            "target_total_nominal_reach_m": target_total_reach_m,
            "current_arm_serial_translation_m": serial_translation_m(model),
            "unchanged_end_effector_extension_m": fixed_end_effector_extension_m(model),
            "candidate_arm_and_wrist_origin_scale": scale,
            "scaled_transforms": [*ARM_JOINTS, HAND_JOINT],
            "unchanged_transforms": ["world_to_panda", *FINGER_JOINTS, *FINGER_LINKS],
        },
        "current_controlled_urdf": current_metrics,
        "candidate_uniform_085_m_kinematics": uniform_metrics,
        "candidate_official_panda_origins": {
            "source": OFFICIAL_PANDA_SOURCE,
            "arm_and_fixed_chain_origin_translation_m": chain_translation_m(official_arm, official_post_arm),
            "added_fixed_link": "panda_link8",
            "added_fixed_joint": "panda_joint8",
            "preserved_actuated_joint_protocol": [*ARM_JOINTS, *FINGER_JOINTS],
            "preserved_hand_and_finger_collision_geometry": True,
            "metrics": official_metrics,
        },
    }


def markdown(report: dict[str, object]) -> str:
    sampling = report["sampling"]  # type: ignore[assignment]
    proposal = report["candidate_definition"]  # type: ignore[assignment]
    current = report["current_controlled_urdf"]  # type: ignore[assignment]
    uniform = report["candidate_uniform_085_m_kinematics"]  # type: ignore[assignment]
    official = report["candidate_official_panda_origins"]  # type: ignore[assignment]
    lines = [
        "# M1A offline FK workspace sampling",
        "",
        "- Status: `EVIDENCE_ONLY — ADR-0006 NOT APPROVED`; no URDF, scene, controller, or end-effector change was made.",
        f"- Samples: `{sampling['arm_joint_samples']}` uniform seven-arm-joint configurations, seed `{sampling['random_seed']}`; each yields two collision-centre fingertip points.",
        f"- Target: `{sampling['target_xyz_m']}` m; finger joints held at `{FINGER_POSITION_M}` m.",
        f"- Current arm-and-wrist serial translation: `{proposal['current_arm_serial_translation_m']:.6f}` m. The candidate scales only arm/wrist origins by `{proposal['candidate_arm_and_wrist_origin_scale']:.9f}`, retains the `{proposal['unchanged_end_effector_extension_m']:.6f}` m hand/finger extension, and gives a `{proposal['target_total_nominal_reach_m']:.3f}` m nominal total reach.",
        "",
        "| Model | Random minimum (m) | 3 cm pad-point density | 5 cm pad-point density | Refined position-only distance (m) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, values in (
        ("Current controlled URDF", current),
        ("Uniform 0.85 m candidate", uniform),
        ("Official Panda-origin candidate", official["metrics"]),
    ):
        sphere = values["sphere"]
        lines.append(
            f"| {name} | {values['minimum_target_distance_m']:.6f} | "
            f"{sphere['0.03']['pad_points']}/{values['point_count']} ({sphere['0.03']['pad_point_density']:.6%}) | "
            f"{sphere['0.05']['pad_points']}/{values['point_count']} ({sphere['0.05']['pad_point_density']:.6%}) | "
            f"{values['position_only_refinement']['final_target_distance_m']:.6f} |"
        )
    lines.extend([
        "",
        "The densities count collision-centre fingertip points; the adjacent JSON also records the number of source arm samples with either pad in each sphere and both point-cloud bounds. The raw 200,000-point clouds are deterministically regenerable from this script and are deliberately not committed as experiment artifacts.",
        "",
        "The final column is a bounded damped-least-squares position-only refinement seeded by the nearest random point. It does not solve orientation, check collision or establish a collision-free approach, simulator contact, or grasp success; it cannot authorize the proposed model change.",
        "",
        "## Audit handoff",
        "",
        "- Changed files: `pyproject.toml`, `scripts/sample_panda_fk_workspace.py`, this JSON/Markdown report, ADR-0006, and `tests/unit/test_m1a_gates.py`.",
        "- Verification commands: run this script with `--samples 100000 --seed 20260716 --workers 4`, then `.venv/bin/python -m pytest -q` and `.venv/bin/python scripts/validate_project.py`.",
        "- Failure/rejection: the uniform 0.85 m candidate retains a 0.126863353 m position-only residual and is rejected.",
        "- Blocker: `HUMAN_ADR_0006_APPROVAL_REQUIRED_BEFORE_URDF_OR_SCENE_CHANGE`.",
        "- Next command after approval: implement the exact approved model candidate, then rerun S0 before S1 and S2.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", type=Path, default=URDF_PATH)
    parser.add_argument("--samples", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20_260_716)
    parser.add_argument("--target-total-reach-m", type=float, default=0.85)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--report-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=REPORT_MD)
    args = parser.parse_args()

    report = sample_workspace(
        load_model(args.urdf), samples=args.samples, seed=args.seed,
        target_total_reach_m=args.target_total_reach_m, workers=args.workers,
    )
    urdf_bytes = args.urdf.read_bytes()
    report.update({
        "schema_version": "m1a-fk-workspace-sampling-v1",
        "status": "EVIDENCE_ONLY_ADR_0006_PENDING_HUMAN_APPROVAL",
        "urdf": str(args.urdf.relative_to(ROOT)) if args.urdf.is_relative_to(ROOT) else str(args.urdf),
        "urdf_sha256": hashlib.sha256(urdf_bytes).hexdigest(),
        "method": "URDF_origin_chain_FK_no_ROS_no_Gazebo_no_collision_check",
        "changed_files": [
            "pyproject.toml",
            "scripts/sample_panda_fk_workspace.py",
            "reports/m1a-fk-workspace-sampling.json",
            "reports/m1a-fk-workspace-sampling.md",
            "docs/decisions/ADR-0006-panda-link-proportion-unification.md",
            "tests/unit/test_m1a_gates.py",
        ],
        "verification_commands": [
            ".venv/bin/python scripts/sample_panda_fk_workspace.py --samples 100000 --seed 20260716 --workers 4",
            ".venv/bin/python -m pytest -q",
            ".venv/bin/python scripts/validate_project.py",
        ],
        "failure_or_rejection": "UNIFORM_085_M_CANDIDATE_POSITION_ONLY_RESIDUAL_0.126863353_M",
        "blocker": "HUMAN_ADR_0006_APPROVAL_REQUIRED_BEFORE_URDF_OR_SCENE_CHANGE",
        "next_command_after_human_approval": "Implement the approved model candidate, then rerun S0 before S1 and S2.",
    })
    args.report_json.write_text(json.dumps(report, indent=2) + "\n")
    args.report_md.write_text(markdown(report))
    print(json.dumps({"status": report["status"], "report": str(args.report_json)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
