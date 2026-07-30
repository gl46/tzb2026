"""Frozen public-geometry centre corrections for M1B RGB-D tracks.

Coefficients are fitted offline from simulator supervision on a training split.
At runtime the correction consumes only public RGB-D geometry, the public
orientation classifier, and the versioned static camera transform.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path


_FEATURE_ORDER = (
    "bias",
    "surface_optical_x_m",
    "surface_optical_y_m",
    "surface_optical_z_m",
    "perceived_diameter_m",
    "public_orientation_is_tilted",
)


def public_xy_feature_vector(
    surface_optical_m: tuple[float, float, float], perceived_diameter_m: float, orientation_state: str,
) -> tuple[float, ...]:
    if len(surface_optical_m) != 3 or not all(math.isfinite(value) for value in surface_optical_m):
        raise ValueError("public surface point must be a finite three-vector")
    if not 0.01 <= perceived_diameter_m <= 0.12:
        raise ValueError("public perceived diameter is outside the contract")
    if orientation_state not in {"normal", "inverted", "tilted"}:
        raise ValueError("public orientation_state is not admissible")
    return (1.0, *surface_optical_m, perceived_diameter_m, float(orientation_state == "tilted"))


@dataclass(frozen=True)
class M1BPublicGeometryXYCorrectionV1:
    """Two public-feature affine residuals to subtract from baseline X/Y."""

    residual_coefficients_world_xy: tuple[tuple[float, ...], tuple[float, ...]]
    training_input_sha256: str

    @classmethod
    def from_file(cls, path: Path) -> "M1BPublicGeometryXYCorrectionV1":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "M1BPublicGeometryXYCorrectionV1":
            raise ValueError("unsupported M1B public-geometry XY correction schema")
        if payload.get("feature_order") != list(_FEATURE_ORDER):
            raise ValueError("public-geometry XY correction feature protocol mismatch")
        if payload.get("truth_boundary") != "simulator supervision is training-only; runtime uses public RGB-D geometry and public orientation_state only":
            raise ValueError("public-geometry XY correction has an invalid truth boundary")
        raw = payload.get("signed_residual_coefficients_world_xy")
        if not isinstance(raw, dict) or set(raw) != {"x", "y"}:
            raise ValueError("public-geometry XY correction must contain x and y coefficient vectors")
        vectors: list[tuple[float, ...]] = []
        for axis in ("x", "y"):
            vector = raw[axis]
            if not isinstance(vector, list) or len(vector) != len(_FEATURE_ORDER):
                raise ValueError(f"public-geometry XY correction {axis} has an invalid coefficient vector")
            parsed = tuple(float(value) for value in vector)
            if not all(math.isfinite(value) and abs(value) <= 5.0 for value in parsed):
                raise ValueError(f"public-geometry XY correction {axis} exceeds coefficient bounds")
            vectors.append(parsed)
        training_sha = payload.get("training_input_sha256")
        if not isinstance(training_sha, str) or len(training_sha) != 64:
            raise ValueError("public-geometry XY correction must record its training input SHA-256")
        return cls((vectors[0], vectors[1]), training_sha)

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": "M1BPublicGeometryXYCorrectionV1",
            "feature_order": _FEATURE_ORDER,
            "signed_residual_coefficients_world_xy": self.residual_coefficients_world_xy,
            "training_input_sha256": self.training_input_sha256,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def correct_xy(
        self, centre_world_m: tuple[float, float, float], *,
        surface_optical_m: tuple[float, float, float], perceived_diameter_m: float, orientation_state: str,
    ) -> tuple[float, float, float]:
        if len(centre_world_m) != 3 or not all(math.isfinite(value) for value in centre_world_m):
            raise ValueError("baseline centre must be a finite three-vector")
        features = public_xy_feature_vector(surface_optical_m, perceived_diameter_m, orientation_state)
        residual_x = sum(weight * feature for weight, feature in zip(self.residual_coefficients_world_xy[0], features))
        residual_y = sum(weight * feature for weight, feature in zip(self.residual_coefficients_world_xy[1], features))
        if not (math.isfinite(residual_x) and math.isfinite(residual_y)) or max(abs(residual_x), abs(residual_y)) > 0.05:
            raise ValueError("public-geometry XY residual exceeds the 50 mm safety bound")
        return centre_world_m[0] - residual_x, centre_world_m[1] - residual_y, centre_world_m[2]


@dataclass(frozen=True)
class M1BTableSupportedCylinderCenterV1:
    """Replace depth-biased centre Z using a public RGB-D support-plane point."""

    center_offset_above_support_m: float
    support_world_z_bounds_m: tuple[float, float]

    @classmethod
    def from_file(cls, path: Path) -> "M1BTableSupportedCylinderCenterV1":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "M1BTableSupportedCylinderCenterV1":
            raise ValueError("unsupported M1B table-supported-centre schema")
        if payload.get("truth_boundary") != "runtime support plane comes from public RGB-D; dimensions come from the versioned industrial-cylinder class contract":
            raise ValueError("table-supported centre has an invalid truth boundary")
        offset = float(payload.get("center_offset_above_support_m", float("nan")))
        bounds = payload.get("support_world_z_bounds_m")
        if not math.isfinite(offset) or not 0.02 <= offset <= 0.06 or not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError("table-supported centre has invalid bounds")
        lower, upper = (float(value) for value in bounds)
        if not (math.isfinite(lower) and math.isfinite(upper) and lower < upper):
            raise ValueError("table-supported centre support bounds must be finite and ordered")
        return cls(offset, (lower, upper))

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps({
            "schema_version": "M1BTableSupportedCylinderCenterV1",
            "center_offset_above_support_m": self.center_offset_above_support_m,
            "support_world_z_bounds_m": self.support_world_z_bounds_m,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def correct_z(self, centre_world_m: tuple[float, float, float], support_world_m: tuple[float, float, float]) -> tuple[float, float, float]:
        if len(support_world_m) != 3 or not all(math.isfinite(value) for value in support_world_m):
            raise ValueError("public support-plane point must be finite")
        if not self.support_world_z_bounds_m[0] <= support_world_m[2] <= self.support_world_z_bounds_m[1]:
            raise ValueError("public support-plane Z is outside the admitted workspace")
        return centre_world_m[0], centre_world_m[1], support_world_m[2] + self.center_offset_above_support_m
