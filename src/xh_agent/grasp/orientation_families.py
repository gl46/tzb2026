"""Geometry-only M1A production-table grasp-orientation candidates.

This module deliberately contains no ROS or simulator dependency.  It maps a
runtime target pose into a small, auditable candidate family before MoveIt is
asked for collision-checked IK.  The target pose itself remains oracle-only
calibration / B1 input; orientation selection is not a policy input.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence


# ADR-0016's inline hand has each finger joint at panda_hand +Z=58.4 mm and
# its physical contact plate spans +Z=58.4..112.2 mm.  These are geometry
# measurements from ``panda_controlled.urdf``, not a motion-policy parameter.
FINGER_TIP_Z_M = 0.1122
FINGER_CONTACT_CENTER_Z_M = 0.0853


@dataclass(frozen=True)
class PoseCandidate:
    """A hand-frame pose plus the geometry used to produce it."""

    candidate_id: str
    family: str
    position_xyz_m: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]
    finger_axis_world: tuple[float, float, float]
    closing_axis_world: tuple[float, float, float]
    fingertip_lowest_z_m: float
    target_center_gripper_frame_m: tuple[float, float, float]


def _as_vector(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("expected a three-dimensional vector")
    return tuple(float(value) for value in values)


def _dot(first: Sequence[float], second: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _cross(first: Sequence[float], second: Sequence[float]) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _norm(values: Sequence[float]) -> float:
    return math.sqrt(_dot(values, values))


def _unit(values: Sequence[float]) -> tuple[float, float, float]:
    length = _norm(values)
    if length <= 1e-9:
        raise ValueError("zero-length orientation axis")
    return tuple(value / length for value in values)


def quaternion_rotate(quaternion_xyzw: Sequence[float], point: Sequence[float]) -> tuple[float, float, float]:
    """Rotate ``point`` by a normalized XYZW quaternion."""

    x, y, z, w = quaternion_xyzw
    px, py, pz = point
    tx, ty, tz = 2 * (y * pz - z * py), 2 * (z * px - x * pz), 2 * (x * py - y * px)
    return (
        px + w * tx + y * tz - z * ty,
        py + w * ty + z * tx - x * tz,
        pz + w * tz + x * ty - y * tx,
    )


def inverse_quaternion_rotate(quaternion_xyzw: Sequence[float], point: Sequence[float]) -> tuple[float, float, float]:
    x, y, z, w = quaternion_xyzw
    return quaternion_rotate((-x, -y, -z, w), point)


def _quaternion_from_tool_axes(
    local_z_world: Sequence[float], local_y_world: Sequence[float]
) -> tuple[float, float, float, float]:
    """Return a quaternion whose inline local +Z/+Y axes map as specified."""

    z_axis = _unit(local_z_world)
    y_axis = _unit(local_y_world)
    if abs(_dot(z_axis, y_axis)) > 1e-6:
        raise ValueError("finger and closing axes must be orthogonal")
    # The rotation is right handed: local X × local Y = local Z.
    x_axis = _unit(_cross(y_axis, z_axis))
    # Rotation matrix columns are world coordinates of local basis vectors.
    m00, m01, m02 = x_axis[0], y_axis[0], z_axis[0]
    m10, m11, m12 = x_axis[1], y_axis[1], z_axis[1]
    m20, m21, m22 = x_axis[2], y_axis[2], z_axis[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = ((m21 - m12) / scale, (m02 - m20) / scale, (m10 - m01) / scale, 0.25 * scale)
    elif m00 > m11 and m00 > m22:
        scale = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        quaternion = (0.25 * scale, (m01 + m10) / scale, (m02 + m20) / scale, (m21 - m12) / scale)
    elif m11 > m22:
        scale = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        quaternion = ((m01 + m10) / scale, 0.25 * scale, (m12 + m21) / scale, (m02 - m20) / scale)
    else:
        scale = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        quaternion = ((m02 + m20) / scale, (m12 + m21) / scale, 0.25 * scale, (m10 - m01) / scale)
    length = math.sqrt(sum(value * value for value in quaternion))
    return tuple(value / length for value in quaternion)


def candidate_is_eligible(
    cube_xyz_m: Sequence[float], candidate: Mapping[str, object], *, table_top_z_m: float
) -> tuple[bool, str | None]:
    """Apply explicit, pose-family eligibility constraints before asking IK."""

    minimum_height = candidate.get("minimum_target_center_above_table_m")
    if minimum_height is not None and cube_xyz_m[2] < table_top_z_m + float(minimum_height):
        return False, "TARGET_CENTER_BELOW_SIDE_GRASP_MINIMUM_HEIGHT"
    return True, None


def candidate_pose(
    cube_xyz_m: Sequence[float], candidate: Mapping[str, object], *, table_top_z_m: float,
    fingertip_table_clearance_m: float,
) -> PoseCandidate:
    """Construct one pose with finger tips clear of the table by construction.

    Local +Z is the inline finger-board axis and local Y is the gripper closing
    axis. The hand origin comes directly from the measured distal endpoint,
    which makes the table-clearance invariant explicit.
    """

    cube = _as_vector(cube_xyz_m)
    horizontal_axis = _unit(_as_vector(candidate["finger_horizontal_axis_world"]))
    closing_axis = _unit(_as_vector(candidate["closing_axis_world"]))
    down_angle_rad = math.radians(float(candidate["finger_down_angle_deg"]))
    finger_axis = _unit(
        tuple(
            math.cos(down_angle_rad) * horizontal + math.sin(down_angle_rad) * vertical
            for horizontal, vertical in zip(horizontal_axis, (0.0, 0.0, -1.0))
        )
    )
    orientation = _quaternion_from_tool_axes(finger_axis, closing_axis)
    fingertip = (cube[0], cube[1], table_top_z_m + fingertip_table_clearance_m)
    hand_position = tuple(
        tip - FINGER_TIP_Z_M * axis for tip, axis in zip(fingertip, finger_axis)
    )
    target_center_gripper_frame = inverse_quaternion_rotate(
        orientation, tuple(target - hand for target, hand in zip(cube, hand_position))
    )
    return PoseCandidate(
        candidate_id=str(candidate["id"]),
        family=str(candidate["family"]),
        position_xyz_m=hand_position,
        orientation_xyzw=orientation,
        finger_axis_world=finger_axis,
        closing_axis_world=closing_axis,
        fingertip_lowest_z_m=fingertip[2],
        target_center_gripper_frame_m=target_center_gripper_frame,
    )


def gripper_frame_corridor(
    hand_position_xyz_m: Sequence[float], hand_orientation_xyzw: Sequence[float], cube_xyz_m: Sequence[float],
    *, threshold_m: float = 0.02, finger_center_line_anchor_m: Sequence[float] | None = None,
) -> dict[str, object]:
    """Evaluate the target-to-finger-line corridor entirely in ``panda_hand``.

    The line joining the two pads is local Y through the selected contact
    cross-section.  Its transverse error is therefore local X/Z only; no
    world-vertical assumption is present in this calculation.
    """

    relative_world = tuple(cube - hand for cube, hand in zip(cube_xyz_m, hand_position_xyz_m))
    cube_in_hand = inverse_quaternion_rotate(hand_orientation_xyzw, relative_world)
    anchor = _as_vector(finger_center_line_anchor_m or (0.0, 0.0, FINGER_CONTACT_CENTER_Z_M))
    transverse_error = math.hypot(
        cube_in_hand[0] - anchor[0],
        cube_in_hand[2] - anchor[2],
    )
    return {
        "coordinate_frame": "panda_hand",
        "cube_center_in_gripper_frame_m": list(cube_in_hand),
        "finger_center_line_anchor_m": list(anchor),
        "transverse_error_to_finger_center_line_m": transverse_error,
        "maximum_transverse_error_m": threshold_m,
        "target_in_grasp_corridor": transverse_error < threshold_m,
    }
