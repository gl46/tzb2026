#!/usr/bin/env python3
"""Generate seed-specific industrial SDF worlds and offline-only labels."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


COLORS = [(0.8, 0.1, 0.1), (0.1, 0.7, 0.2), (0.1, 0.2, 0.8), (0.8, 0.6, 0.1), (0.7, 0.1, 0.7), (0.1, 0.7, 0.7)]
ORIENTATIONS = ("normal", "inverted", "tilted")


def split(seed: int) -> str:
    return "train" if seed % 20 < 14 else "val" if seed % 20 < 17 else "test"


def part_sdf(index: int, state: str, x: float, y: float, color: tuple[float, float, float], yaw: float) -> str:
    roll, pitch = (0.0, 0.0) if state == "normal" else (3.14159, 0.0) if state == "inverted" else (0.45, -0.30)
    z = 0.50 if state != "tilted" else 0.48
    red, green, blue = color
    return f'''    <model name="cylinder_{index:02d}"><pose>{x:.4f} {y:.4f} {z:.4f} {roll:.4f} {pitch:.4f} {yaw:.4f}</pose><link name="link"><inertial><mass>0.06</mass></inertial><collision name="collision"><geometry><cylinder><radius>0.025</radius><length>0.09</length></cylinder></geometry></collision><visual name="visual"><geometry><cylinder><radius>0.025</radius><length>0.09</length></cylinder></geometry><material><diffuse>{red:.3f} {green:.3f} {blue:.3f} 1</diffuse><specular>0.15 0.15 0.15 1</specular></material></visual></link></model>'''


def render(template: str, seed: int) -> tuple[str, dict[str, object]]:
    rng = random.Random(seed)
    count = rng.randint(6, 12)
    parts = []
    labels = []
    for index in range(count):
        state = ORIENTATIONS[index % len(ORIENTATIONS)]
        x = rng.uniform(-0.43, -0.08)
        y = rng.uniform(-0.28, 0.28)
        yaw = rng.uniform(-3.14159, 3.14159)
        color = COLORS[index % len(COLORS)]
        parts.append(part_sdf(index + 1, state, x, y, color, yaw))
        labels.append({"actual_sim_entity_id": f"cylinder_{index + 1:02d}", "category": "industrial_cylinder", "orientation_state": state, "position_3d_world": [x, y, 0.50 if state != "tilted" else 0.48], "yaw": yaw})
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
    args = parser.parse_args()
    if args.count < 150:
        raise SystemExit("--count must be at least 150")
    template = args.template.read_text(encoding="utf-8")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for offset in range(args.count):
        seed = args.seed_start + offset
        scene, supervision = render(template, seed)
        (args.output_dir / f"scene-{seed}.sdf").write_text(scene, encoding="utf-8")
        (args.output_dir / f"scene-{seed}.supervision.json").write_text(json.dumps(supervision, indent=2) + "\n", encoding="utf-8")
        manifest.append({"seed": seed, "split": supervision["split"], "sdf": str(args.output_dir / f"scene-{seed}.sdf"), "supervision": str(args.output_dir / f"scene-{seed}.supervision.json"), "part_count": supervision["part_count"]})
    print(json.dumps({"status": "GENERATED_SCENE_SPECS", "scenes": len(manifest), "heldout": sum(item["split"] == "test" for item in manifest), "output": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
