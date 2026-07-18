"""Versioned static camera calibration for M1B public RGB-D coordinates.

The transform is sourced from the checked-in scene description and is meant to
be published as a static TF edge.  It intentionally has no Gazebo transport,
pose-service, or simulator-entity dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path


_LINK_TO_OPTICAL = (
    (0.0, 0.0, 1.0),
    (-1.0, 0.0, 0.0),
    (0.0, -1.0, 0.0),
)


def _matmul(left: tuple[tuple[float, float, float], ...], right: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(sum(left[row][index] * right[index][column] for index in range(3)) for column in range(3)) for row in range(3))


def _transpose(matrix: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(matrix[column][row] for column in range(3)) for row in range(3))


def _apply(matrix: tuple[tuple[float, float, float], ...], position: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(matrix[row][column] * position[column] for column in range(3)) for row in range(3))


def _rpy_rotation(rpy_rad: tuple[float, float, float]) -> tuple[tuple[float, float, float], ...]:
    roll, pitch, yaw = rpy_rad
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def _quaternion_from_rotation(matrix: tuple[tuple[float, float, float], ...]) -> tuple[float, float, float, float]:
    """Return a normalized xyzw quaternion for a proper 3x3 rotation."""
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2.0
        x = (matrix[2][1] - matrix[1][2]) / scale
        y = (matrix[0][2] - matrix[2][0]) / scale
        z = (matrix[1][0] - matrix[0][1]) / scale
        w = 0.25 * scale
    elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2.0
        x, y, z, w = 0.25 * scale, (matrix[0][1] + matrix[1][0]) / scale, (matrix[0][2] + matrix[2][0]) / scale, (matrix[2][1] - matrix[1][2]) / scale
    elif matrix[1][1] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2.0
        x, y, z, w = (matrix[0][1] + matrix[1][0]) / scale, 0.25 * scale, (matrix[1][2] + matrix[2][1]) / scale, (matrix[0][2] - matrix[2][0]) / scale
    else:
        scale = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2.0
        x, y, z, w = (matrix[0][2] + matrix[2][0]) / scale, (matrix[1][2] + matrix[2][1]) / scale, 0.25 * scale, (matrix[1][0] - matrix[0][1]) / scale
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    return x / norm, y / norm, z / norm, w / norm


@dataclass(frozen=True)
class M1BStaticCameraCalibrationV1:
    parent_frame: str
    camera_link_frame: str
    camera_optical_frame: str
    translation_m: tuple[float, float, float]
    rpy_rad: tuple[float, float, float]
    source_path: str

    @classmethod
    def from_file(cls, path: Path) -> "M1BStaticCameraCalibrationV1":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "M1BStaticCameraCalibrationV1":
            raise ValueError("unsupported M1B camera calibration schema")
        if payload.get("link_to_optical_axes") != "gazebo_camera_link_to_ros_optical_v1":
            raise ValueError("unsupported camera-axis convention")
        source = payload.get("source", {})
        values = ("parent_frame", "camera_link_frame", "camera_optical_frame")
        if not all(isinstance(payload.get(key), str) and payload[key] for key in values):
            raise ValueError("camera frame names must be nonempty strings")
        translation = tuple(float(value) for value in payload["translation_m"])
        rpy = tuple(float(value) for value in payload["rpy_rad"])
        if len(translation) != 3 or len(rpy) != 3 or not all(math.isfinite(value) for value in (*translation, *rpy)):
            raise ValueError("camera transform must contain finite 3-vectors")
        if source.get("kind") != "versioned_scene_sdf" or not isinstance(source.get("path"), str):
            raise ValueError("camera calibration must cite a versioned scene SDF")
        return cls(payload["parent_frame"], payload["camera_link_frame"], payload["camera_optical_frame"], translation, rpy, source["path"])

    @property
    def world_from_optical_rotation(self) -> tuple[tuple[float, float, float], ...]:
        return _matmul(_rpy_rotation(self.rpy_rad), _LINK_TO_OPTICAL)

    @property
    def fingerprint(self) -> str:
        value = {
            "schema_version": "M1BStaticCameraCalibrationV1", "parent_frame": self.parent_frame,
            "camera_link_frame": self.camera_link_frame, "camera_optical_frame": self.camera_optical_frame,
            "translation_m": self.translation_m, "rpy_rad": self.rpy_rad, "source_path": self.source_path,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def optical_to_world(self, position_m: tuple[float, float, float]) -> tuple[float, float, float]:
        rotated = _apply(self.world_from_optical_rotation, position_m)
        return tuple(origin + offset for origin, offset in zip(self.translation_m, rotated))

    def world_to_optical(self, position_m: tuple[float, float, float]) -> tuple[float, float, float]:
        delta = tuple(value - origin for value, origin in zip(position_m, self.translation_m))
        return _apply(_transpose(self.world_from_optical_rotation), delta)

    def visible_surface_to_center_world(
        self, surface_optical_m: tuple[float, float, float], perceived_diameter_m: float,
    ) -> tuple[float, float, float]:
        """Estimate a cylinder centre from its visible RGB-D surface point.

        Metric depth reports the camera-facing surface, not the object centre
        required by the finger geometry.  For the industrial-cylinder class,
        move one *perceived* radius away from the camera along optical +Z,
        then use the approved static TF.  This is a public geometric estimate;
        it accepts neither a simulator pose nor an entity identifier.
        """
        if not 0.01 <= perceived_diameter_m <= 0.12:
            raise ValueError("perceived cylinder diameter must be in [0.01, 0.12] m")
        x, y, z = surface_optical_m
        if not all(math.isfinite(value) for value in surface_optical_m):
            raise ValueError("surface point must be finite")
        return self.optical_to_world((x, y, z + perceived_diameter_m / 2.0))

    def static_tf_arguments(self) -> list[str]:
        """Arguments for tf2_ros/static_transform_publisher, world -> sensor frame."""
        x, y, z, w = _quaternion_from_rotation(self.world_from_optical_rotation)
        return ["--x", str(self.translation_m[0]), "--y", str(self.translation_m[1]), "--z", str(self.translation_m[2]), "--qx", str(x), "--qy", str(y), "--qz", str(z), "--qw", str(w), "--frame-id", self.parent_frame, "--child-frame-id", self.camera_optical_frame]
