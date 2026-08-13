"""Deterministic query-only FK for the byte-bound controlled Panda URDF.

This provider exists only to turn an executor's complete nine-DOF physical
state sequence into link-frame transforms for ADR-0024 A.3 collision queries.
It reads the frozen URDF once, validates the complete joint/link topology and
limits, and performs pure double-precision rigid-transform arithmetic.  It
does not import Isaac/ROS, write targets, step a simulator, or infer a missing
finger state.  The two physical finger coordinates must satisfy the frozen
URDF mimic relation exactly enough for a planned path; disagreement fails
closed before a collision query.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import stat
from typing import Mapping, Sequence
import xml.etree.ElementTree as ET

from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3RigidTransformV1
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


SCHEMA_VERSION = "ControlledPandaReadOnlyFKProviderV1"
IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/controlled_panda_fk_v1.py"
CONTROLLED_PANDA_URDF_PATH = "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
CONTROLLED_PANDA_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
ROOT_LINK = "world"
ROBOT_PATH_PREFIX = "/World/Robot"
ARM_JOINT_NAMES = tuple(f"panda_joint{index}" for index in range(1, 8))
FINGER_JOINT_NAMES = ("panda_finger_joint1", "panda_finger_joint2")
EXECUTOR_JOINT_NAMES = (*ARM_JOINT_NAMES, *FINGER_JOINT_NAMES)
EXPECTED_JOINT_NAMES = (
    "world_to_panda",
    *ARM_JOINT_NAMES,
    "panda_joint8",
    "panda_hand_joint",
    "panda_finger_joint2",
    "panda_finger_joint1",
)
EXPECTED_COLLISION_LINKS = (
    "panda_hand",
    "panda_leftfinger",
    "panda_link0",
    "panda_link1",
    "panda_link2",
    "panda_link3",
    "panda_link4",
    "panda_link5",
    "panda_link6",
    "panda_link7",
    "panda_link8",
    "panda_rightfinger",
)
EXPECTED_LINK_PATHS = tuple(f"{ROBOT_PATH_PREFIX}/{name}" for name in EXPECTED_COLLISION_LINKS)
MIMIC_ABS_TOLERANCE_M = 1e-12

Vector3 = tuple[float, float, float]
Matrix4 = tuple[tuple[float, float, float, float], ...]


class ControlledPandaFKUnavailable(RuntimeError):
    """The exact read-only FK closure or query input is unavailable."""


@dataclass(frozen=True)
class _Mimic:
    joint: str
    multiplier: float
    offset: float


@dataclass(frozen=True)
class _Joint:
    name: str
    kind: str
    parent: str
    child: str
    origin_xyz: Vector3
    origin_rpy: Vector3
    axis: Vector3
    lower: float | None
    upper: float | None
    mimic: _Mimic | None


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ControlledPandaFKUnavailable(
                f"FK input is not a single-link regular file: {path}"
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise ControlledPandaFKUnavailable(f"FK input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _vector(raw: str | None, *, default: Vector3 = (0.0, 0.0, 0.0)) -> Vector3:
    if raw is None:
        return default
    try:
        values = tuple(float(value) for value in raw.split())
    except ValueError as exc:
        raise ControlledPandaFKUnavailable("FK URDF contains a malformed vector") from exc
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ControlledPandaFKUnavailable("FK URDF vector width/value differs")
    return values  # type: ignore[return-value]


def _identity() -> Matrix4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        )
        for row in range(4)
    )  # type: ignore[return-value]


def _origin_transform(xyz: Vector3, rpy: Vector3) -> Matrix4:
    """URDF origin convention: translation with Rz(yaw) Ry(pitch) Rx(roll)."""

    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, xyz[0]),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, xyz[1]),
        (-sp, cp * sr, cp * cr, xyz[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def _joint_motion(axis: Vector3, position: float, kind: str) -> Matrix4:
    norm = math.sqrt(sum(value * value for value in axis))
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ControlledPandaFKUnavailable("FK URDF joint axis is not unit length")
    x, y, z = (value / norm for value in axis)
    if kind == "prismatic":
        return _origin_transform(
            (x * position, y * position, z * position),
            (0.0, 0.0, 0.0),
        )
    if kind not in {"revolute", "continuous"}:
        raise ControlledPandaFKUnavailable(f"FK joint motion kind is unsupported: {kind}")
    cosine = math.cos(position)
    sine = math.sin(position)
    one_minus = 1.0 - cosine
    return (
        (
            cosine + x * x * one_minus,
            x * y * one_minus - z * sine,
            x * z * one_minus + y * sine,
            0.0,
        ),
        (
            y * x * one_minus + z * sine,
            cosine + y * y * one_minus,
            y * z * one_minus - x * sine,
            0.0,
        ),
        (
            z * x * one_minus - y * sine,
            z * y * one_minus + x * sine,
            cosine + z * z * one_minus,
            0.0,
        ),
        (0.0, 0.0, 0.0, 1.0),
    )


def _matrix_to_transform(matrix: Matrix4) -> A3RigidTransformV1:
    r00, r01, r02 = matrix[0][:3]
    r10, r11, r12 = matrix[1][:3]
    r20, r21, r22 = matrix[2][:3]
    trace = r00 + r11 + r22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = (0.25 * scale, (r21 - r12) / scale, (r02 - r20) / scale, (r10 - r01) / scale)
    elif r00 > r11 and r00 > r22:
        scale = math.sqrt(max(0.0, 1.0 + r00 - r11 - r22)) * 2.0
        quaternion = ((r21 - r12) / scale, 0.25 * scale, (r01 + r10) / scale, (r02 + r20) / scale)
    elif r11 > r22:
        scale = math.sqrt(max(0.0, 1.0 + r11 - r00 - r22)) * 2.0
        quaternion = ((r02 - r20) / scale, (r01 + r10) / scale, 0.25 * scale, (r12 + r21) / scale)
    else:
        scale = math.sqrt(max(0.0, 1.0 + r22 - r00 - r11)) * 2.0
        quaternion = ((r10 - r01) / scale, (r02 + r20) / scale, (r12 + r21) / scale, 0.25 * scale)
    norm = math.sqrt(sum(value * value for value in quaternion))
    if norm == 0.0 or not math.isfinite(norm):
        raise ControlledPandaFKUnavailable("FK rotation could not be normalized")
    quaternion = tuple(value / norm for value in quaternion)
    if quaternion[0] < 0.0 or (
        quaternion[0] == 0.0
        and next((value for value in quaternion[1:] if value != 0.0), 1.0) < 0.0
    ):
        quaternion = tuple(-value for value in quaternion)
    return A3RigidTransformV1(
        translation_world_m=(matrix[0][3], matrix[1][3], matrix[2][3]),
        rotation_world_wxyz=quaternion,  # type: ignore[arg-type]
    )


def _parse_joint(element: ET.Element) -> _Joint:
    try:
        name = element.attrib["name"]
        kind = element.attrib["type"]
        parent = element.find("parent").attrib["link"]  # type: ignore[union-attr]
        child = element.find("child").attrib["link"]  # type: ignore[union-attr]
    except (KeyError, TypeError) as exc:
        raise ControlledPandaFKUnavailable("FK URDF joint identity is malformed") from exc
    origin = element.find("origin")
    axis = element.find("axis")
    limit = element.find("limit")
    mimic_element = element.find("mimic")
    mimic = None
    if mimic_element is not None:
        try:
            mimic = _Mimic(
                joint=mimic_element.attrib["joint"],
                multiplier=float(mimic_element.attrib.get("multiplier", "1")),
                offset=float(mimic_element.attrib.get("offset", "0")),
            )
        except (KeyError, ValueError) as exc:
            raise ControlledPandaFKUnavailable("FK URDF mimic relation is malformed") from exc
    lower = upper = None
    if kind in {"revolute", "prismatic"}:
        if limit is None:
            raise ControlledPandaFKUnavailable("FK bounded joint lacks limits")
        try:
            lower = float(limit.attrib["lower"])
            upper = float(limit.attrib["upper"])
        except (KeyError, ValueError) as exc:
            raise ControlledPandaFKUnavailable("FK joint limits are malformed") from exc
    joint = _Joint(
        name=name,
        kind=kind,
        parent=parent,
        child=child,
        origin_xyz=_vector(None if origin is None else origin.attrib.get("xyz")),
        origin_rpy=_vector(None if origin is None else origin.attrib.get("rpy")),
        axis=_vector(None if axis is None else axis.attrib.get("xyz")),
        lower=lower,
        upper=upper,
        mimic=mimic,
    )
    numeric = (*joint.origin_xyz, *joint.origin_rpy, *joint.axis)
    if not all(math.isfinite(value) for value in numeric) or (
        joint.lower is not None
        and (
            joint.upper is None or not math.isfinite(joint.lower) or not math.isfinite(joint.upper)
        )
    ):
        raise ControlledPandaFKUnavailable("FK URDF joint contains NaN/Inf")
    return joint


def expand_controlled_panda_executor_states_v1(
    *,
    arm_joint_names: tuple[str, ...],
    arm_joint_state_sequence: tuple[tuple[float, ...], ...],
    gripper_position_sequence_m: tuple[float, ...],
) -> tuple[tuple[float, ...], ...]:
    """Bind seven-arm-joint A.3 samples to the two physical finger states."""

    if arm_joint_names != ARM_JOINT_NAMES or len(arm_joint_state_sequence) < 2:
        raise ControlledPandaFKUnavailable("preflight arm joint order/state coverage differs")
    if len(gripper_position_sequence_m) != len(arm_joint_state_sequence):
        raise ControlledPandaFKUnavailable("preflight arm/gripper state coverage differs")
    output: list[tuple[float, ...]] = []
    for arm_state, gripper_position in zip(
        arm_joint_state_sequence,
        gripper_position_sequence_m,
        strict=True,
    ):
        if len(arm_state) != len(ARM_JOINT_NAMES) or not all(
            math.isfinite(value) for value in (*arm_state, gripper_position)
        ):
            raise ControlledPandaFKUnavailable("preflight physical state is malformed")
        output.append((*arm_state, gripper_position, gripper_position))
    return tuple(output)


class ControlledPandaReadOnlyFKProviderV1:
    """Pure production FK provider for the exact controlled-Panda bytes."""

    real_runtime_provider = True
    query_only = True

    def __init__(self, *, project_root: Path) -> None:
        root = project_root.resolve()
        # Keep the leaf unresolved so O_NOFOLLOW below can reject substitution
        # by a symlink instead of silently opening its target.
        implementation = root / IMPLEMENTATION_REPO_PATH
        urdf_path = root / CONTROLLED_PANDA_URDF_PATH
        implementation_raw = _read_regular_file_once(implementation)
        urdf_raw = _read_regular_file_once(urdf_path)
        if hashlib.sha256(urdf_raw).hexdigest() != CONTROLLED_PANDA_URDF_SHA256:
            raise ControlledPandaFKUnavailable("controlled Panda URDF digest differs")
        try:
            xml_root = ET.fromstring(urdf_raw)
        except ET.ParseError as exc:
            raise ControlledPandaFKUnavailable("controlled Panda URDF XML is malformed") from exc
        if xml_root.tag != "robot" or xml_root.attrib.get("name") != "xh_panda_controlled":
            raise ControlledPandaFKUnavailable("controlled Panda URDF root identity differs")
        links = tuple(element.attrib.get("name", "") for element in xml_root.findall("link"))
        if not links or len(set(links)) != len(links) or "" in links or ROOT_LINK not in links:
            raise ControlledPandaFKUnavailable("controlled Panda link set is malformed")
        joints = tuple(_parse_joint(element) for element in xml_root.findall("joint"))
        if tuple(joint.name for joint in joints) != EXPECTED_JOINT_NAMES:
            raise ControlledPandaFKUnavailable("controlled Panda joint order/set differs")
        if len({joint.child for joint in joints}) != len(joints):
            raise ControlledPandaFKUnavailable("controlled Panda link has multiple parents")
        if any(joint.parent not in links or joint.child not in links for joint in joints):
            raise ControlledPandaFKUnavailable("controlled Panda joint references an unknown link")
        by_parent: dict[str, list[_Joint]] = {}
        for joint in joints:
            by_parent.setdefault(joint.parent, []).append(joint)
        collision_links = tuple(
            sorted(
                element.attrib["name"]
                for element in xml_root.findall("link")
                if element.findall("collision")
            )
        )
        if collision_links != EXPECTED_COLLISION_LINKS:
            raise ControlledPandaFKUnavailable("controlled Panda collision-link set differs")
        follower = next(joint for joint in joints if joint.name == "panda_finger_joint1")
        if follower.mimic != _Mimic("panda_finger_joint2", 1.0, 0.0):
            raise ControlledPandaFKUnavailable("controlled Panda finger mimic relation differs")
        if any(
            joint.kind not in {"fixed", "revolute", "prismatic"}
            or (joint.kind == "fixed" and joint.mimic is not None)
            for joint in joints
        ):
            raise ControlledPandaFKUnavailable("controlled Panda joint type differs")
        self._joints = joints
        self._joints_by_parent = {key: tuple(value) for key, value in by_parent.items()}
        self.implementation_path = str(implementation)
        self.implementation_sha256 = hashlib.sha256(implementation_raw).hexdigest()
        configuration = {
            "schema_version": SCHEMA_VERSION,
            "implementation_repo_path": IMPLEMENTATION_REPO_PATH,
            "robot_description_path": CONTROLLED_PANDA_URDF_PATH,
            "robot_description_sha256": CONTROLLED_PANDA_URDF_SHA256,
            "root_link": ROOT_LINK,
            "robot_path_prefix": ROBOT_PATH_PREFIX,
            "executor_joint_names": EXECUTOR_JOINT_NAMES,
            "expected_collision_link_paths": EXPECTED_LINK_PATHS,
            "urdf_origin_convention": "T_xyz_Rz_yaw_Ry_pitch_Rx_roll_THEN_JOINT_MOTION",
            "quaternion_order": "WXYZ_CANONICAL_NONNEGATIVE_FIRST_NONZERO",
            "finger_mimic_relation": "panda_finger_joint1=1*panda_finger_joint2+0",
            "mimic_abs_tolerance_m": MIMIC_ABS_TOLERANCE_M,
            "numeric_precision": "PYTHON_IEEE754_BINARY64",
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        self.configuration_sha256 = canonical_sha256(configuration)

    def _state_transforms(self, positions: Mapping[str, float]) -> dict[str, Matrix4]:
        result: dict[str, Matrix4] = {ROOT_LINK: _identity()}
        pending = [ROOT_LINK]
        visited_joints: list[str] = []
        while pending:
            parent = pending.pop(0)
            parent_transform = result[parent]
            for joint in self._joints_by_parent.get(parent, ()):
                child_transform = _multiply(
                    parent_transform,
                    _origin_transform(joint.origin_xyz, joint.origin_rpy),
                )
                if joint.kind != "fixed":
                    child_transform = _multiply(
                        child_transform,
                        _joint_motion(joint.axis, positions[joint.name], joint.kind),
                    )
                result[joint.child] = child_transform
                visited_joints.append(joint.name)
                pending.append(joint.child)
        if tuple(visited_joints) != EXPECTED_JOINT_NAMES or len(result) != len(self._joints) + 1:
            raise ControlledPandaFKUnavailable("controlled Panda kinematic tree is incomplete")
        return result

    def query_link_transforms(
        self,
        *,
        joint_names: tuple[str, ...],
        joint_state_sequence: tuple[tuple[float, ...], ...],
        link_paths: tuple[str, ...],
    ) -> Mapping[str, Sequence[A3RigidTransformV1]]:
        if joint_names != EXECUTOR_JOINT_NAMES:
            raise ControlledPandaFKUnavailable("executor joint order differs")
        if link_paths != EXPECTED_LINK_PATHS:
            raise ControlledPandaFKUnavailable("collision link-path coverage differs")
        if len(joint_state_sequence) < 2:
            raise ControlledPandaFKUnavailable("executor state coverage differs")
        output: dict[str, list[A3RigidTransformV1]] = {path: [] for path in link_paths}
        bounded = {joint.name: joint for joint in self._joints if joint.lower is not None}
        for state in joint_state_sequence:
            if len(state) != len(EXECUTOR_JOINT_NAMES) or not all(
                math.isfinite(value) for value in state
            ):
                raise ControlledPandaFKUnavailable("executor joint state is malformed")
            positions = dict(zip(EXECUTOR_JOINT_NAMES, state, strict=True))
            if not math.isclose(
                positions["panda_finger_joint1"],
                positions["panda_finger_joint2"],
                rel_tol=0.0,
                abs_tol=MIMIC_ABS_TOLERANCE_M,
            ):
                raise ControlledPandaFKUnavailable("executor finger state violates mimic relation")
            for name, joint in bounded.items():
                value = positions[name]
                assert joint.lower is not None and joint.upper is not None
                if value < joint.lower or value > joint.upper:
                    raise ControlledPandaFKUnavailable(
                        f"executor joint state exceeds limit: {name}"
                    )
            transforms = self._state_transforms(positions)
            for path in link_paths:
                output[path].append(_matrix_to_transform(transforms[path.rsplit("/", 1)[1]]))
        return {path: tuple(values) for path, values in output.items()}
