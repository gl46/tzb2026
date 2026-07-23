#!/usr/bin/env python3
"""Fit a frozen public-RGB-D affine X/Y residual from training-only audit data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from xh_agent.runtime.m1b_center_correction import public_xy_feature_vector


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("training_audit", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ridge", type=float, default=1e-5)
    args = parser.parse_args()
    if args.ridge < 0.0:
        raise SystemExit("ridge must be non-negative")
    raw = args.training_audit.read_bytes()
    audit = json.loads(raw)
    if audit.get("schema_version") != "M1BPublicCenterAuditV1" or audit.get("status") != "ACTUAL_GAZEBO_RGBD_FRAMES_EVALUATED":
        raise SystemExit("training input must be an actual M1B public-centre audit")
    if audit.get("input", {}).get("split") != "train":
        raise SystemExit("public-geometry correction may be fitted only from the train split")
    features, residuals = [], []
    for record in audit.get("matches", []):
        public = record.get("public_geometry", {})
        try:
            features.append(public_xy_feature_vector(
                tuple(float(value) for value in public["surface_optical_m"]),
                float(public["perceived_diameter_m"]), str(public["orientation_state"]),
            ))
            error = record["error_world_xyz_m"]
            residuals.append((float(error[0]), float(error[1])))
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise SystemExit(f"training record lacks public geometry: {error}") from error
    if len(features) < 100:
        raise SystemExit(f"insufficient training matches: {len(features)}")
    matrix = np.asarray(features, dtype=float)
    targets = np.asarray(residuals, dtype=float)
    ridge = np.eye(matrix.shape[1]) * args.ridge
    coefficients = np.linalg.solve(matrix.T @ matrix + ridge, matrix.T @ targets)
    payload = {
        "schema_version": "M1BPublicGeometryXYCorrectionV1",
        "status": "FITTED_TRAINING_ONLY",
        "fit_rule": "ridge_affine_signed_residual_over_public_rgbd_geometry",
        "ridge": args.ridge,
        "feature_order": ["bias", "surface_optical_x_m", "surface_optical_y_m", "surface_optical_z_m", "perceived_diameter_m", "public_orientation_is_tilted"],
        "signed_residual_coefficients_world_xy": {"x": coefficients[:, 0].tolist(), "y": coefficients[:, 1].tolist()},
        "training_input": str(args.training_audit),
        "training_input_sha256": hashlib.sha256(raw).hexdigest(),
        "training_match_count": len(features),
        "truth_boundary": "simulator supervision is training-only; runtime uses public RGB-D geometry and public orientation_state only",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "matches": len(features), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
