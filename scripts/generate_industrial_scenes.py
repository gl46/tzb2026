#!/usr/bin/env python3
"""Generate seed-specific industrial SDF worlds and offline-only labels."""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path


COLORS = [(0.8, 0.1, 0.1), (0.1, 0.7, 0.2), (0.1, 0.2, 0.8), (0.8, 0.6, 0.1), (0.7, 0.1, 0.7), (0.1, 0.7, 0.7)]
ORIENTATIONS = ("normal", "inverted", "tilted")
TABLE_TOP_Z = 0.45
CYLINDER_RADIUS_M = 0.025
CYLINDER_HALF_LENGTH_M = 0.045
# Keep a small positive gap so Gazebo does not begin a reset with a cylinder
# already intersecting the tabletop.  The physical-reset check remains the
# authority on whether the object has subsequently settled.
SPAWN_CLEARANCE_M = 0.0001
# Low residual velocity decay prevents a settled free cylinder from drifting
# numerically during the reset jog while preserving normal gravity/contact and
# detachable-joint transport dynamics.
LINEAR_VELOCITY_DECAY = 0.5
ANGULAR_VELOCITY_DECAY = 0.5


def split(seed: int) -> str:
    return "train" if seed % 20 < 14 else "val" if seed % 20 < 17 else "test"


def cylinder_pose(state: str) -> tuple[float, float, float]:
    roll, pitch = (0.0, 0.0) if state == "normal" else (3.14159, 0.0) if state == "inverted" else (0.45, -0.30)
    # A cylinder's local Z axis has vertical component cos(roll)*cos(pitch).
    # Its support extent is the projected half-length plus the projected
    # radius, so its centre must be above the tabletop by that amount.
    vertical_axis = abs(math.cos(roll) * math.cos(pitch))
    support = CYLINDER_HALF_LENGTH_M * vertical_axis + CYLINDER_RADIUS_M * math.sqrt(1.0 - vertical_axis ** 2)
    z = TABLE_TOP_Z + support + SPAWN_CLEARANCE_M
    return roll, pitch, z


def part_sdf(index: int, state: str, x: float, y: float, color: tuple[float, float, float], yaw: float) -> str:
    roll, pitch, z = cylinder_pose(state)
    red, green, blue = color
    return f'''    <model name="cylinder_{index:02d}"><pose>{x:.4f} {y:.4f} {z:.4f} {roll:.4f} {pitch:.4f} {yaw:.4f}</pose><link name="link"><inertial><mass>0.06</mass></inertial><velocity_decay><linear>{LINEAR_VELOCITY_DECAY}</linear><angular>{ANGULAR_VELOCITY_DECAY}</angular></velocity_decay><collision name="collision"><geometry><cylinder><radius>0.025</radius><length>0.09</length></cylinder></geometry></collision><visual name="visual"><geometry><cylinder><radius>0.025</radius><length>0.09</length></cylinder></geometry><material><diffuse>{red:.3f} {green:.3f} {blue:.3f} 1</diffuse><specular>0.15 0.15 0.15 1</specular></material></visual><sensor name="contact" type="contact"><always_on>1</always_on><update_rate>30</update_rate><topic>/xh/actuation_internal/cylinders/cylinder_{index:02d}/contacts</topic><contact><collision>collision</collision></contact></sensor></link></model>'''


def render(template: str, seed: int, *, orientations: tuple[str, ...] = ORIENTATIONS) -> tuple[str, dict[str, object]]:
    rng = random.Random(seed)
    count = rng.randint(6, 12)
    parts = []
    labels = []
    positions: list[tuple[float, float]] = []
    for index in range(count):
        state = orientations[index % len(orientations)]
        # Split two incoming zones and enforce a 9 cm centre separation. This
        # prevents the simulator generator from creating unobservable stacks.
        for _ in range(500):
            x = rng.uniform(-0.43, -0.10)
            y = rng.uniform(-0.31, -0.08) if index % 2 == 0 else rng.uniform(0.08, 0.31)
            if all((x - other_x) ** 2 + (y - other_y) ** 2 >= 0.09 ** 2 for other_x, other_y in positions):
                positions.append((x, y))
                break
        else:
            raise RuntimeError(f"could not place non-overlapping cylinder for seed {seed}")
        yaw = rng.uniform(-3.14159, 3.14159)
        color = COLORS[index % len(COLORS)]
        _, _, z = cylinder_pose(state)
        parts.append(part_sdf(index + 1, state, x, y, color, yaw))
        labels.append({"actual_sim_entity_id": f"cylinder_{index + 1:02d}", "category": "industrial_cylinder", "orientation_state": state, "position_3d_world": [x, y, z], "incoming_region": "incoming_a" if index % 2 == 0 else "incoming_b", "yaw": yaw})
    begin, end = "<!-- M1B_RANDOM_PARTS_BEGIN -->", "<!-- M1B_RANDOM_PARTS_END -->"
    start, finish = template.index(begin) + len(begin), template.index(end)
    scene = template[:start] + "\n" + "\n".join(parts) + "\n    " + template[finish:]
    return scene, {"scene_id": "IndustrialCylinderBenchmarkV1", "seed": seed, "split": split(seed), "part_count": count, "randomization": {"material": "reflective_metal" if split(seed) == "test" else "matte_metal", "camera_offset_m": 0.02 if split(seed) == "test" else 0.0, "light_intensity": rng.uniform(0.7, 1.3)}, "simulator_supervision": {"training_and_evaluation_only": True, "objects": labels}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=Path("robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated/m1b_alpha_v1/scenes"))
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--orientation-mode", choices=("mixed", "normal"), default="mixed")
    args = parser.parse_args()
    if args.count < 150:
        raise SystemExit("--count must be at least 150")
    template = args.template.read_text(encoding="utf-8")
    orientations = ORIENTATIONS if args.orientation_mode == "mixed" else ("normal",)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for offset in range(args.count):
        seed = args.seed_start + offset
        scene, supervision = render(template, seed, orientations=orientations)
        (args.output_dir / f"scene-{seed}.sdf").write_text(scene, encoding="utf-8")
        (args.output_dir / f"scene-{seed}.supervision.json").write_text(json.dumps(supervision, indent=2) + "\n", encoding="utf-8")
        manifest.append({"seed": seed, "split": supervision["split"], "sdf": str(args.output_dir / f"scene-{seed}.sdf"), "supervision": str(args.output_dir / f"scene-{seed}.supervision.json"), "part_count": supervision["part_count"]})
    print(json.dumps({"status": "GENERATED_SCENE_SPECS", "scenes": len(manifest), "heldout": sum(item["split"] == "test" for item in manifest), "output": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
