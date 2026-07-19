#!/usr/bin/env python3
"""Generate seed-specific industrial SDF worlds and offline-only labels."""
from __future__ import annotations

import argparse
import json
import math
import random
from functools import lru_cache
from pathlib import Path

from sample_panda_fk_workspace import Model, load_model, position_only_reachability_gate


COLORS = [(0.8, 0.1, 0.1), (0.1, 0.7, 0.2), (0.1, 0.2, 0.8), (0.8, 0.6, 0.1), (0.7, 0.1, 0.7), (0.1, 0.7, 0.7)]
ORIENTATIONS = ("normal", "inverted", "tilted")
TABLE_TOP_Z = 0.45
CYLINDER_RADIUS_M = 0.015
CYLINDER_HALF_LENGTH_M = 0.040
CYLINDER_MASS_KG = 0.045
CALIBRATION_PEDESTAL_RADIUS_M = 0.020
# Keep a small positive gap so Gazebo does not begin a reset with a cylinder
# already intersecting the tabletop.  The physical-reset check remains the
# authority on whether the object has subsequently settled.
SPAWN_CLEARANCE_M = 0.0001
# Low residual velocity decay prevents a settled free cylinder from drifting
# numerically during the reset jog while preserving normal gravity/contact and
# detachable-joint transport dynamics.
LINEAR_VELOCITY_DECAY = 0.5
ANGULAR_VELOCITY_DECAY = 0.5
# The controlled Panda is mounted at this fixed world pose.  Free cylinders
# inside this footprint collide with link0 before any perception/grasp action,
# which makes a calibration trial measure spawn interference rather than
# centre-offset tolerance.  Keep the physical cylinder envelope outside it.
ROBOT_BASE_XY = (-0.35, 0.0)
ROBOT_BASE_KEEP_OUT_RADIUS_M = 0.19
# These targets are intentionally checked with the controlled-URDF FK/DLS
# sampler before writing any scene.  This is a layout prefilter only; it does
# not claim orientation feasibility or collision-free MoveIt execution.
LAYOUT_REACHABILITY_SAMPLES = 512
LAYOUT_REACHABILITY_MAX_DISTANCE_M = 0.002
LAYOUT_REACHABILITY_SEED = 20260719
BIN_CENTER_XY = (0.20, 0.0)
BIN_YAW_RAD = math.pi / 2
BIN_CELL_LOCAL_X_M = (-0.14, 0.0, 0.14)
BIN_CELL_LOCAL_Y_M = (-0.075, 0.075)
BIN_DROP_TARGET_Z_M = 0.56
# A finite lattice makes every possible spawn target independently auditable
# before it is selected.  Its 7 cm pitch exceeds the 6 cm object separation
# rule and it retains seed-randomized subsets without making FK acceptance a
# stochastic property of arbitrary floating-point coordinates.
INCOMING_GRID_X_M = (-0.53, -0.46, -0.39, -0.32, -0.25, -0.18, -0.11)
INCOMING_GRID_Y_BY_LANE_M = ((-0.34, -0.27, -0.20, -0.13), (0.13, 0.20, 0.27, 0.34))


@lru_cache(maxsize=1)
def controlled_urdf_model() -> Model:
    return load_model()


def bin_cell_targets() -> tuple[tuple[float, float, float], ...]:
    """Return all six partition-cell drop targets after the tangential rotation."""
    cosine, sine = math.cos(BIN_YAW_RAD), math.sin(BIN_YAW_RAD)
    return tuple(
        (
            BIN_CENTER_XY[0] + cosine * local_x - sine * local_y,
            BIN_CENTER_XY[1] + sine * local_x + cosine * local_y,
            BIN_DROP_TARGET_Z_M,
        )
        for local_x in BIN_CELL_LOCAL_X_M
        for local_y in BIN_CELL_LOCAL_Y_M
    )


@lru_cache(maxsize=256)
def cached_layout_reachability(target_xyz: tuple[float, float, float]) -> dict[str, object]:
    """Evaluate one member of the finite approved layout target set once."""
    evidence = position_only_reachability_gate(
        controlled_urdf_model(),
        target_xyz=target_xyz,
        samples=LAYOUT_REACHABILITY_SAMPLES,
        # The same deterministic covering set is used for every target.  A
        # target-specific random stream can put a perfectly valid point in a
        # poor DLS basin and turn layout acceptance into seed luck.
        seed=LAYOUT_REACHABILITY_SEED,
        maximum_target_distance_m=LAYOUT_REACHABILITY_MAX_DISTANCE_M,
    )
    if not evidence["passed"]:
        raise RuntimeError(
            "ADR-0014 layout reachability gate rejected "
            f"{target_xyz}: final distance {evidence['final_target_distance_m']} m"
        )
    return evidence


def layout_reachability(target_xyz: tuple[float, float, float], *, gate_index: int) -> dict[str, object]:
    """Expose the cached FK result with the scene-local point identifier."""
    return {**cached_layout_reachability(target_xyz), "layout_gate_index": gate_index}


def split(seed: int) -> str:
    return "train" if seed % 20 < 14 else "val" if seed % 20 < 17 else "test"


def cylinder_pose(state: str, *, pedestal_lift_m: float = 0.0) -> tuple[float, float, float]:
    roll, pitch = (0.0, 0.0) if state == "normal" else (3.14159, 0.0) if state == "inverted" else (0.45, -0.30)
    # A cylinder's local Z axis has vertical component cos(roll)*cos(pitch).
    # Its support extent is the projected half-length plus the projected
    # radius, so its centre must be above the tabletop by that amount.
    vertical_axis = abs(math.cos(roll) * math.cos(pitch))
    support = CYLINDER_HALF_LENGTH_M * vertical_axis + CYLINDER_RADIUS_M * math.sqrt(1.0 - vertical_axis ** 2)
    z = TABLE_TOP_Z + pedestal_lift_m + support + SPAWN_CLEARANCE_M
    return roll, pitch, z


def pedestal_sdf(index: int, x: float, y: float, lift_m: float) -> str:
    """Return the static, narrow calibration support below one normal cylinder."""
    if lift_m <= 0.0:
        return ""
    z = TABLE_TOP_Z + lift_m / 2.0
    return f'''    <model name="cylinder_pedestal_{index:02d}"><static>true</static><pose>{x:.4f} {y:.4f} {z:.4f} 0 0 0</pose><link name="link"><collision name="collision"><geometry><cylinder><radius>{CALIBRATION_PEDESTAL_RADIUS_M}</radius><length>{lift_m:.4f}</length></cylinder></geometry></collision><visual name="visual"><geometry><cylinder><radius>{CALIBRATION_PEDESTAL_RADIUS_M}</radius><length>{lift_m:.4f}</length></cylinder></geometry><material><diffuse>0.18 0.18 0.18 1</diffuse></material></visual></link></model>'''


def part_sdf(
    index: int,
    state: str,
    x: float,
    y: float,
    color: tuple[float, float, float],
    yaw: float,
    *,
    pedestal_lift_m: float = 0.0,
) -> str:
    roll, pitch, z = cylinder_pose(state, pedestal_lift_m=pedestal_lift_m)
    red, green, blue = color
    return f'''    <model name="cylinder_{index:02d}"><pose>{x:.4f} {y:.4f} {z:.4f} {roll:.4f} {pitch:.4f} {yaw:.4f}</pose><link name="link"><inertial><mass>{CYLINDER_MASS_KG}</mass></inertial><velocity_decay><linear>{LINEAR_VELOCITY_DECAY}</linear><angular>{ANGULAR_VELOCITY_DECAY}</angular></velocity_decay><collision name="collision"><geometry><cylinder><radius>{CYLINDER_RADIUS_M}</radius><length>{2 * CYLINDER_HALF_LENGTH_M}</length></cylinder></geometry></collision><visual name="visual"><geometry><cylinder><radius>{CYLINDER_RADIUS_M}</radius><length>{2 * CYLINDER_HALF_LENGTH_M}</length></cylinder></geometry><material><diffuse>{red:.3f} {green:.3f} {blue:.3f} 1</diffuse><specular>0.15 0.15 0.15 1</specular></material></visual><sensor name="contact" type="contact"><always_on>1</always_on><update_rate>30</update_rate><topic>/xh/actuation_internal/cylinders/cylinder_{index:02d}/contacts</topic><contact><collision>collision</collision></contact></sensor></link></model>'''


def render(
    template: str,
    seed: int,
    *,
    orientations: tuple[str, ...] = ORIENTATIONS,
    pedestal_lift_m: float = 0.0,
) -> tuple[str, dict[str, object]]:
    if pedestal_lift_m < 0.0:
        raise ValueError("pedestal_lift_m must be non-negative")
    if pedestal_lift_m and orientations != ("normal",):
        raise ValueError("a calibration pedestal is only defined for normal cylinders")
    rng = random.Random(seed)
    bin_evidence = [
        layout_reachability(target, gate_index=10_000 + index)
        for index, target in enumerate(bin_cell_targets())
    ]
    count = rng.randint(6, 12)
    parts = []
    labels = []
    spawn_evidence = []
    positions: list[tuple[float, float]] = []
    for index in range(count):
        state = orientations[index % len(orientations)]
        # Split two incoming zones and enforce a 6 cm centre separation. This
        # prevents the simulator generator from creating unobservable stacks.
        lane = index % 2
        candidates = [
            (x, y)
            for x in INCOMING_GRID_X_M
            for y in INCOMING_GRID_Y_BY_LANE_M[lane]
        ]
        rng.shuffle(candidates)
        for x, y in candidates:
            clear_of_base = math.dist((x, y), ROBOT_BASE_XY) >= ROBOT_BASE_KEEP_OUT_RADIUS_M
            target = (x, y, cylinder_pose(state, pedestal_lift_m=pedestal_lift_m)[2])
            evidence = layout_reachability(target, gate_index=seed * 100 + index)
            if (
                clear_of_base
                and all((x - other_x) ** 2 + (y - other_y) ** 2 >= 0.06 ** 2 for other_x, other_y in positions)
                and evidence["passed"]
            ):
                positions.append((x, y))
                spawn_evidence.append(evidence)
                break
        else:
            raise RuntimeError(f"could not place non-overlapping cylinder for seed {seed}")
        yaw = rng.uniform(-3.14159, 3.14159)
        color = COLORS[index % len(COLORS)]
        _, _, z = cylinder_pose(state, pedestal_lift_m=pedestal_lift_m)
        parts.append(pedestal_sdf(index + 1, x, y, pedestal_lift_m))
        parts.append(part_sdf(index + 1, state, x, y, color, yaw, pedestal_lift_m=pedestal_lift_m))
        labels.append({"actual_sim_entity_id": f"cylinder_{index + 1:02d}", "category": "industrial_cylinder", "orientation_state": state, "position_3d_world": [x, y, z], "incoming_region": "incoming_a" if index % 2 == 0 else "incoming_b", "yaw": yaw, "layout_reachability": spawn_evidence[index]})
    begin, end = "<!-- M1B_RANDOM_PARTS_BEGIN -->", "<!-- M1B_RANDOM_PARTS_END -->"
    start, finish = template.index(begin) + len(begin), template.index(end)
    scene = template[:start] + "\n" + "\n".join(parts) + "\n    " + template[finish:]
    return scene, {"scene_id": "IndustrialCylinderBenchmarkV1", "seed": seed, "split": split(seed), "part_count": count, "randomization": {"material": "reflective_metal" if split(seed) == "test" else "matte_metal", "camera_offset_m": 0.02 if split(seed) == "test" else 0.0, "light_intensity": rng.uniform(0.7, 1.3)}, "calibration_fixture": {"kind": "static_narrow_pedestal" if pedestal_lift_m else None, "pedestal_lift_m": pedestal_lift_m, "calibration_only": bool(pedestal_lift_m)}, "layout_reachability": {"bin_cells": bin_evidence, "scope": "generation_prefilter_only; orientation_and_collision_remain_for_MoveIt"}, "simulator_supervision": {"training_and_evaluation_only": True, "objects": labels}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=Path("robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated/m1b_alpha_v1/scenes"))
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--orientation-mode", choices=("mixed", "normal"), default="mixed")
    parser.add_argument("--pedestal-lift-m", type=float, default=0.0)
    args = parser.parse_args()
    if args.count < 150:
        raise SystemExit("--count must be at least 150")
    if args.pedestal_lift_m < 0.0:
        raise SystemExit("--pedestal-lift-m must be non-negative")
    if args.pedestal_lift_m and args.orientation_mode != "normal":
        raise SystemExit("--pedestal-lift-m requires --orientation-mode normal")
    template = args.template.read_text(encoding="utf-8")
    orientations = ORIENTATIONS if args.orientation_mode == "mixed" else ("normal",)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for offset in range(args.count):
        seed = args.seed_start + offset
        scene, supervision = render(template, seed, orientations=orientations, pedestal_lift_m=args.pedestal_lift_m)
        (args.output_dir / f"scene-{seed}.sdf").write_text(scene, encoding="utf-8")
        (args.output_dir / f"scene-{seed}.supervision.json").write_text(json.dumps(supervision, indent=2) + "\n", encoding="utf-8")
        manifest.append({"seed": seed, "split": supervision["split"], "sdf": str(args.output_dir / f"scene-{seed}.sdf"), "supervision": str(args.output_dir / f"scene-{seed}.supervision.json"), "part_count": supervision["part_count"]})
    print(json.dumps({"status": "GENERATED_SCENE_SPECS", "scenes": len(manifest), "heldout": sum(item["split"] == "test" for item in manifest), "pedestal_lift_m": args.pedestal_lift_m, "output": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
