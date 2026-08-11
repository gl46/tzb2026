#!/usr/bin/env python3
"""Pre-register a scene-only M2C domain before observing Isaac outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from generate_industrial_scenes import (
    CYLINDER_RADIUS_M,
    SPAWN_CLEARANCE_M,
    TABLE_TOP_Z,
    render,
    split,
)
from xh_agent.grasp.free_gap import (
    FREE_GAP_MIN_CLEARANCE_M,
    select_free_gap_yaw_from_xy,
)


PROJECT = Path(__file__).resolve().parents[2]
BASELINE_COMMIT = "141e45dabddcaf59bb49ab958d9d5273d1f54d88"
DATASET_VERSION = "isaac-industrial-v3-headroom"
PUBLIC_TARGET_RGB = (0.8, 0.6, 0.1)
HORIZONTAL_TARGET_LENGTH_M = 0.09
HORIZONTAL_TARGET_HALF_SEGMENT_M = HORIZONTAL_TARGET_LENGTH_M / 2.0
MINIMUM_INITIAL_GEOMETRY_CLEARANCE_M = 0.005
DEFAULT_SEED_START = 6000
DEFAULT_SEED_STOP = 6400
DEFAULT_KEY_COUNT = 10


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(payload: object) -> str:
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )


def _models(root: ET.Element) -> list[ET.Element]:
    return [
        model
        for model in root.findall(".//world/model")
        if (model.get("name") or "").startswith("cylinder_")
    ]


def _pose(model: ET.Element) -> list[float]:
    values = [float(value) for value in (model.findtext("pose") or "").split()]
    if len(values) != 6:
        raise ValueError(f"{model.get('name')}: expected a six-value model pose")
    return values


def _rgb(model: ET.Element) -> tuple[float, float, float]:
    text = model.findtext(".//visual/material/diffuse") or ""
    values = tuple(float(value) for value in text.split()[:3])
    if len(values) != 3:
        raise ValueError(f"{model.get('name')}: missing public RGB material")
    return values


def public_yellow_max_x_target(models: list[ET.Element]) -> ET.Element:
    candidates = [
        model
        for model in models
        if all(
            math.isclose(value, wanted, abs_tol=1e-6)
            for value, wanted in zip(_rgb(model), PUBLIC_TARGET_RGB)
        )
    ]
    if not candidates:
        raise ValueError("scene has no public yellow cylinder")
    return max(candidates, key=lambda model: _pose(model)[0])


def orthogonal_grid_yaw(yaw_rad: float) -> float:
    """Return the same undirected gripper yaw rotated by exactly 90 degrees."""

    return (yaw_rad + math.pi / 2.0) % math.pi


def capsule_clearance_m(
    target_xy: list[float],
    neighbor_xy: list[list[float]],
    *,
    axis_yaw_rad: float,
) -> float:
    """Conservative target-capsule clearance from upright neighbour cylinders."""

    axis = (math.cos(axis_yaw_rad), math.sin(axis_yaw_rad))
    minimum = math.inf
    for neighbor in neighbor_xy:
        delta = (
            float(neighbor[0]) - float(target_xy[0]),
            float(neighbor[1]) - float(target_xy[1]),
        )
        along = max(
            -HORIZONTAL_TARGET_HALF_SEGMENT_M,
            min(
                HORIZONTAL_TARGET_HALF_SEGMENT_M,
                delta[0] * axis[0] + delta[1] * axis[1],
            ),
        )
        closest = (
            float(target_xy[0]) + along * axis[0],
            float(target_xy[1]) + along * axis[1],
        )
        distance = math.hypot(
            float(neighbor[0]) - closest[0],
            float(neighbor[1]) - closest[1],
        )
        # The horizontal target and each upright neighbour both have the
        # unchanged 15 mm physical radius.
        minimum = min(minimum, distance - 2.0 * CYLINDER_RADIUS_M)
    return minimum


def _candidate(
    template: str,
    seed: int,
) -> tuple[bytes, bytes, dict[str, Any]] | None:
    if split(seed) != "test":
        return None
    scene, supervision = render(template, seed, orientations=("normal",))
    root = ET.fromstring(scene)
    models = _models(root)
    target = public_yellow_max_x_target(models)
    target_name = str(target.get("name"))
    target_pose = _pose(target)
    target_xy = target_pose[:2]
    neighbor_xy = [
        _pose(model)[:2] for model in models if model is not target
    ]
    free_gap = select_free_gap_yaw_from_xy(
        target_xy,
        neighbor_xy,
        source="M2C_PREREGISTERED_SCENE_GEOMETRY_ONLY",
    )
    b0_yaw_rad = float(free_gap["selected_yaw_rad"])
    scripted_yaw_rad = orthogonal_grid_yaw(b0_yaw_rad)
    scripted_candidate = next(
        (
            candidate
            for candidate in free_gap["candidates"]
            if math.isclose(
                float(candidate["yaw_rad"]), scripted_yaw_rad, abs_tol=1e-9
            )
        ),
        None,
    )
    if scripted_candidate is None:
        raise AssertionError("orthogonal yaw is absent from the frozen 15 degree grid")
    initial_clearance_m = capsule_clearance_m(
        target_xy,
        neighbor_xy,
        axis_yaw_rad=scripted_yaw_rad,
    )
    if (
        not bool(free_gap["clearance_ok"])
        or float(scripted_candidate["min_clearance_m"])
        < FREE_GAP_MIN_CLEARANCE_M
        or initial_clearance_m < MINIMUM_INITIAL_GEOMETRY_CLEARANCE_M
    ):
        return None

    # SDF applies Rz(yaw) Ry(pitch) Rx(roll).  At roll=pi/2, the cylinder's
    # local-Z axis lies at yaw-pi/2 in the world XY plane.  Setting the SDF
    # yaw to B0's clearance yaw therefore makes B0 close along the 90 mm long
    # axis, while the pre-registered orthogonal yaw closes across the unchanged
    # 30 mm diameter.  No B0 source, parameter, retry, or gate is changed.
    horizontal_center_z = (
        TABLE_TOP_Z + CYLINDER_RADIUS_M + SPAWN_CLEARANCE_M
    )
    target_pose = [
        target_pose[0],
        target_pose[1],
        horizontal_center_z,
        math.pi / 2.0,
        0.0,
        b0_yaw_rad,
    ]
    target.find("pose").text = " ".join(f"{value:.9f}" for value in target_pose)
    length_nodes = target.findall("./link/collision/geometry/cylinder/length")
    length_nodes += target.findall("./link/visual/geometry/cylinder/length")
    if len(length_nodes) != 2:
        raise ValueError(f"{target_name}: expected collision and visual lengths")
    for node in length_nodes:
        node.text = f"{HORIZONTAL_TARGET_LENGTH_M:.4f}"

    labels = supervision["simulator_supervision"]["objects"]
    label = next(
        item for item in labels if item["actual_sim_entity_id"] == target_name
    )
    label["orientation_state"] = "tilted"
    label["position_3d_world"] = target_pose[:3]
    label["yaw"] = b0_yaw_rad
    label["m2c_scene_geometry"] = {
        "cylinder_axis_world_xy_yaw_rad": scripted_yaw_rad,
        "length_m": HORIZONTAL_TARGET_LENGTH_M,
        "radius_m": CYLINDER_RADIUS_M,
        "roll_rad": math.pi / 2.0,
        "pitch_rad": 0.0,
        "domain_only": True,
    }
    supervision["m2c_headroom_domain"] = {
        "schema_version": "M2CHeadroomSceneV1",
        "dataset_version": DATASET_VERSION,
        "failure_type": "EMPTY_GRASP",
        "target_selector": "visual_color=yellow,top_z_band=0.02m,world_x=max",
        "target_entity_evaluator_only": target_name,
        "b0_yaw_rad": b0_yaw_rad,
        "scripted_existence_yaw_rad": scripted_yaw_rad,
        "b0_modified": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }

    ET.indent(root, space="  ")
    sdf_bytes = (ET.tostring(root, encoding="unicode") + "\n").encode()
    supervision_bytes = (
        json.dumps(supervision, indent=2, sort_keys=True) + "\n"
    ).encode()
    record = {
        "scene_seed": seed,
        "split": "test",
        "failure_type": "EMPTY_GRASP",
        "target_entity_evaluator_only": target_name,
        "target_selector_policy_input": (
            "visual_color=yellow,top_z_band=0.02m,world_x=max"
        ),
        "part_count": len(models),
        "b0_selected_yaw_rad": b0_yaw_rad,
        "scripted_existence_yaw_rad": scripted_yaw_rad,
        "b0_yaw_clearance_m": float(free_gap["min_clearance_m"]),
        "scripted_yaw_clearance_m": float(
            scripted_candidate["min_clearance_m"]
        ),
        "minimum_initial_geometry_clearance_m": initial_clearance_m,
        "horizontal_target_length_m": HORIZONTAL_TARGET_LENGTH_M,
        "horizontal_target_radius_m": CYLINDER_RADIUS_M,
        "sdf_sha256": sha256_bytes(sdf_bytes),
        "supervision_sha256": sha256_bytes(supervision_bytes),
        "outcome_observed_during_selection": False,
    }
    record["matched_key"] = "m2c-headroom-" + canonical_sha256(record)
    return sdf_bytes, supervision_bytes, record


def generate_domain(
    *,
    template_path: Path,
    output_root: Path,
    key_count: int = DEFAULT_KEY_COUNT,
    seed_start: int = DEFAULT_SEED_START,
    seed_stop: int = DEFAULT_SEED_STOP,
) -> dict[str, Any]:
    if key_count <= 0:
        raise ValueError("key_count must be positive")
    if seed_stop <= seed_start:
        raise ValueError("seed_stop must be greater than seed_start")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration: {output_root}")
    template = template_path.read_text(encoding="utf-8")
    selected: list[tuple[bytes, bytes, dict[str, Any]]] = []
    for seed in range(seed_start, seed_stop):
        candidate = _candidate(template, seed)
        if candidate is not None:
            selected.append(candidate)
        if len(selected) == key_count:
            break
    if len(selected) != key_count:
        raise ValueError(
            f"only {len(selected)} geometry-admissible test keys; need {key_count}"
        )

    output_root.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for sdf_bytes, supervision_bytes, record in selected:
        seed = int(record["scene_seed"])
        sdf = output_root / f"scene-{seed}.sdf"
        supervision = output_root / f"scene-{seed}.supervision.json"
        sdf.write_bytes(sdf_bytes)
        supervision.write_bytes(supervision_bytes)
        records.append(
            {
                **record,
                "sdf": str(sdf.resolve()),
                "supervision": str(supervision.resolve()),
            }
        )

    b0_freeze = PROJECT / "configs/m2c_b0_freeze.json"
    manifest: dict[str, Any] = {
        "schema_version": "M2CHeadroomDomainManifestV1",
        "status": "PREREGISTERED_NOT_EVALUATED",
        "dataset_version": DATASET_VERSION,
        "baseline_commit": BASELINE_COMMIT,
        "b0_freeze_manifest": str(b0_freeze),
        "b0_freeze_manifest_sha256": sha256_file(b0_freeze),
        "source_generator": "scripts/generate_industrial_scenes.py",
        "source_generator_sha256": sha256_file(
            PROJECT / "scripts/generate_industrial_scenes.py"
        ),
        "template": str(template_path),
        "template_sha256": sha256_file(template_path),
        "selection_protocol": {
            "observes_isaac_outcomes": False,
            "seed_range_half_open": [seed_start, seed_stop],
            "split": "test",
            "key_count": key_count,
            "candidate_order": "ascending_seed_first_geometry_admissible",
            "public_target": "yellow world_x=max",
            "all_non_target_orientations": "normal",
            "target_pose": "horizontal roll=pi/2",
            "target_length_m": HORIZONTAL_TARGET_LENGTH_M,
            "target_radius_m": CYLINDER_RADIUS_M,
            "minimum_initial_geometry_clearance_m": (
                MINIMUM_INITIAL_GEOMETRY_CLEARANCE_M
            ),
            "b0_selected_yaw": "unchanged maximum-clearance ADR-0016 grid",
            "target_sdf_yaw": (
                "equal to B0 selected yaw, making cylinder axis orthogonal"
            ),
        },
        "baseline_protocol": {
            "runner": "scripts/m2b/run_physical_failure_smoke.py",
            "probe": "scripts/isaac_m1b_actuation_probe.py",
            "failure_type": "EMPTY_GRASP",
            "max_attempts": 1,
            "capture_public_rgbd": True,
            "calibration_free_gap_yaw_override": None,
            "implementation_parameters_retries_and_gates_changed": False,
            "final_success_definition": (
                "M2B accepted EMPTY_GRASP: injection physical_state_passed and "
                "public training_eligible and recovery "
                "physical_regrasp_and_lift_passed/training_eligible"
            ),
        },
        "existence_proof_protocol": {
            "purpose": "physical recoverability only; never counted as B0",
            "probe": "scripts/isaac_m1b_actuation_probe.py",
            "only_difference": (
                "pre-existing calibration-only safe-grid "
                "--calibration-free-gap-yaw-override-rad"
            ),
            "scripted_yaw_source": "scene geometry frozen before outcomes",
            "same_ik_collision_safety_and_schema_gates": True,
            "policy_input_simulator_truth": False,
        },
        "keys": records,
        "outcomes_observed": False,
        "q_a_decision": None,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }
    manifest["domain_sha256"] = canonical_sha256(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT
        / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--key-count", type=int, default=DEFAULT_KEY_COUNT)
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--seed-stop", type=int, default=DEFAULT_SEED_STOP)
    args = parser.parse_args()
    if args.manifest.exists():
        raise FileExistsError(
            f"refusing to overwrite pre-registration: {args.manifest}"
        )
    manifest = generate_domain(
        template_path=args.template,
        output_root=args.output_root,
        key_count=args.key_count,
        seed_start=args.seed_start,
        seed_stop=args.seed_stop,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "keys": len(manifest["keys"]),
                "domain_sha256": manifest["domain_sha256"],
                "manifest": str(args.manifest),
                "output_root": str(args.output_root),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
