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
import hashlib
import json
import math
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


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


def fingertip_positions(model: Model, arm_positions: Iterable[float], *, scale: float) -> tuple[Vector, Vector]:
    frame = transform(model.base.origin_xyz, model.base.origin_rpy)
    for joint, position in zip(model.arm, arm_positions):
        scaled_origin = tuple(value * scale for value in joint.origin_xyz)
        frame = multiply(frame, transform(scaled_origin, joint.origin_rpy))
        frame = multiply(frame, axis_motion(joint.axis, position, joint.kind))
    scaled_hand_origin = tuple(value * scale for value in model.hand.origin_xyz)
    hand_frame = multiply(frame, transform(scaled_hand_origin, model.hand.origin_rpy))
    pads: list[Vector] = []
    for finger, pad_center in zip(model.fingers, model.pad_centers):
        finger_frame = multiply(hand_frame, transform(finger.origin_xyz, finger.origin_rpy))
        finger_frame = multiply(finger_frame, axis_motion(finger.axis, FINGER_POSITION_M, finger.kind))
        pads.append(point(finger_frame, pad_center))
    return tuple(pads)  # type: ignore[return-value]


def empty_metrics() -> dict[str, object]:
    return {
        "point_count": 0,
        "bounds_m": {"min_xyz": [math.inf, math.inf, math.inf], "max_xyz": [-math.inf, -math.inf, -math.inf]},
        "minimum_target_distance_m": math.inf,
        "sphere": {str(radius): {"pad_points": 0, "source_arm_samples_with_any_pad": 0} for radius in TARGET_RADII_M},
    }


def update_metrics(metrics: dict[str, object], pads: tuple[Vector, Vector]) -> None:
    bounds = metrics["bounds_m"]  # type: ignore[assignment]
    minimum = metrics["minimum_target_distance_m"]  # type: ignore[assignment]
    sphere = metrics["sphere"]  # type: ignore[assignment]
    inside_by_radius = {radius: False for radius in TARGET_RADII_M}
    for pad in pads:
        metrics["point_count"] = int(metrics["point_count"]) + 1
        for index, value in enumerate(pad):
            bounds["min_xyz"][index] = min(bounds["min_xyz"][index], value)
            bounds["max_xyz"][index] = max(bounds["max_xyz"][index], value)
        distance = math.dist(pad, TARGET_XYZ)
        metrics["minimum_target_distance_m"] = min(minimum, distance)
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
    return metrics


def sample_workspace(model: Model, *, samples: int, seed: int, target_total_reach_m: float) -> dict[str, object]:
    if samples <= 0:
        raise ValueError("samples must be positive")
    scale = candidate_scale(model, target_total_reach_m)
    random_source = random.Random(seed)
    current, candidate = empty_metrics(), empty_metrics()
    for _ in range(samples):
        positions = tuple(random_source.uniform(joint.lower, joint.upper) for joint in model.arm)  # type: ignore[arg-type]
        update_metrics(current, fingertip_positions(model, positions, scale=1.0))
        update_metrics(candidate, fingertip_positions(model, positions, scale=scale))
    return {
        "sampling": {
            "arm_joint_samples": samples,
            "fingertip_points_per_model": samples * 2,
            "random_seed": seed,
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
        "current_controlled_urdf": finalise_metrics(current, samples),
        "candidate_panda_scale_kinematics": finalise_metrics(candidate, samples),
    }


def markdown(report: dict[str, object]) -> str:
    sampling = report["sampling"]  # type: ignore[assignment]
    proposal = report["candidate_definition"]  # type: ignore[assignment]
    current = report["current_controlled_urdf"]  # type: ignore[assignment]
    candidate = report["candidate_panda_scale_kinematics"]  # type: ignore[assignment]
    lines = [
        "# M1A offline FK workspace sampling",
        "",
        "- Status: `EVIDENCE_ONLY — ADR-0006 NOT APPROVED`; no URDF, scene, controller, or end-effector change was made.",
        f"- Samples: `{sampling['arm_joint_samples']}` uniform seven-arm-joint configurations, seed `{sampling['random_seed']}`; each yields two collision-centre fingertip points.",
        f"- Target: `{sampling['target_xyz_m']}` m; finger joints held at `{FINGER_POSITION_M}` m.",
        f"- Current arm-and-wrist serial translation: `{proposal['current_arm_serial_translation_m']:.6f}` m. The candidate scales only arm/wrist origins by `{proposal['candidate_arm_and_wrist_origin_scale']:.9f}`, retains the `{proposal['unchanged_end_effector_extension_m']:.6f}` m hand/finger extension, and gives a `{proposal['target_total_nominal_reach_m']:.3f}` m nominal total reach.",
        "",
        "| Model | Minimum pad-centre distance to target (m) | 3 cm pad-point density | 5 cm pad-point density |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, values in (("Current controlled URDF", current), ("Candidate Panda-scale kinematics", candidate)):
        sphere = values["sphere"]
        lines.append(
            f"| {name} | {values['minimum_target_distance_m']:.6f} | "
            f"{sphere['0.03']['pad_points']}/{values['point_count']} ({sphere['0.03']['pad_point_density']:.6%}) | "
            f"{sphere['0.05']['pad_points']}/{values['point_count']} ({sphere['0.05']['pad_point_density']:.6%}) |"
        )
    lines.extend([
        "",
        "The densities count collision-centre fingertip points; the adjacent JSON also records the number of source arm samples with either pad in each sphere and both point-cloud bounds. The raw 200,000-point clouds are deterministically regenerable from this script and are deliberately not committed as experiment artifacts.",
        "",
        "This is an offline kinematic comparison only. It does not establish collision-free approach, simulator contact, or grasp success, and it cannot authorize the proposed model change.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", type=Path, default=URDF_PATH)
    parser.add_argument("--samples", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20_260_716)
    parser.add_argument("--target-total-reach-m", type=float, default=0.85)
    parser.add_argument("--report-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=REPORT_MD)
    args = parser.parse_args()

    report = sample_workspace(
        load_model(args.urdf), samples=args.samples, seed=args.seed, target_total_reach_m=args.target_total_reach_m
    )
    urdf_bytes = args.urdf.read_bytes()
    report.update({
        "schema_version": "m1a-fk-workspace-sampling-v1",
        "status": "EVIDENCE_ONLY_ADR_0006_PENDING_HUMAN_APPROVAL",
        "urdf": str(args.urdf.relative_to(ROOT)) if args.urdf.is_relative_to(ROOT) else str(args.urdf),
        "urdf_sha256": hashlib.sha256(urdf_bytes).hexdigest(),
        "method": "URDF_origin_chain_FK_no_ROS_no_Gazebo_no_collision_check",
    })
    args.report_json.write_text(json.dumps(report, indent=2) + "\n")
    args.report_md.write_text(markdown(report))
    print(json.dumps({"status": report["status"], "report": str(args.report_json)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
