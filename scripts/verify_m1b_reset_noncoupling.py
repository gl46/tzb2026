#!/usr/bin/env python3
"""Amendment-1 reset verification via physical non-coupling evidence.

Gazebo model poses in this file are evaluator-side supervision.  They are
sampled only to validate reset and never enter perception, planning, or the
online grasp policy.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import rclpy

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from m1a_contact_calibration_client import CalibrationClient  # noqa: E402
from m1a_moveit_execution_client import JOINTS  # noqa: E402
from m1a_home_self_collision_client import HOME_ARM_POSITIONS  # noqa: E402

POSE_RE = re.compile(
    r"Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*"
    r"\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
)
SETTLE_S = 2.0
MAX_OBJECT_DISPLACEMENT_M = 0.001
MIN_EE_DISPLACEMENT_M = 0.02
# The positive-Y panda_joint4 jog contacted a positive-Y cylinder.  A 50 mrad
# negative panda_joint3 jog moves the hand about 24 mm toward negative Y from
# S1 home, away from that incoming zone while retaining a measurable path.
HOME_JOG_JOINT_INDEX = 2
HOME_JOG_DELTA_RAD = -0.05
POSE_SNAPSHOT_ATTEMPTS = 3
POSE_QUERY_TIMEOUT_S = 5


def supervision_model_position(name: str) -> list[float] | None:
    try:
        result = subprocess.run(
            ["timeout", str(POSE_QUERY_TIMEOUT_S), "gz", "model", "-m", name, "-p"],
            check=False, capture_output=True, text=True, timeout=POSE_QUERY_TIMEOUT_S + 2.0,
        )
    except subprocess.TimeoutExpired:
        # A supervision-query timeout is not evidence that the object stayed
        # still.  Return a missing sample so the final physical-reset gate
        # fails closed while still emitting a reviewable JSON record.
        return None
    match = POSE_RE.search(result.stdout)
    return [float(value) for value in match.groups()] if match else None


def positions(names: list[str]) -> tuple[dict[str, list[float] | None], int]:
    # Each snapshot is taken only while the world is paused.  Sequential CLI
    # reads are therefore one frozen observation and avoid transport-query
    # loss observed when twelve independent `gz model` clients start together.
    final: dict[str, list[float] | None] = {name: None for name in names}
    for attempt in range(1, POSE_SNAPSHOT_ATTEMPTS + 1):
        final = {name: supervision_model_position(name) for name in names}
        # Never combine an object sampled in one CLI snapshot with objects
        # sampled in another.  A complete attempt is one atomic evaluator-side
        # before/after observation; incomplete attempts are discarded.
        if all(sample is not None for sample in final.values()):
            return final, attempt
    return final, POSE_SNAPSHOT_ATTEMPTS


def set_world_pause(world_name: str, paused: bool) -> dict[str, object]:
    try:
        result = subprocess.run(
            [
                "gz", "service", "--service", f"/world/{world_name}/control",
                "--reqtype", "gz.msgs.WorldControl", "--reptype", "gz.msgs.Boolean",
                "--timeout", "5000", "--req", f"pause: {'true' if paused else 'false'}",
            ],
            check=False, capture_output=True, text=True, timeout=7.0,
        )
    except subprocess.TimeoutExpired:
        return {"paused": paused, "returncode": None, "stdout": "", "stderr": "timeout", "succeeded": False}
    return {
        "paused": paused,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "succeeded": result.returncode == 0 and "data: true" in result.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spawn-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--world-name", default="industrial_cylinder_v1")
    args = parser.parse_args()
    manifest = json.loads(args.spawn_manifest.read_text(encoding="utf-8"))
    names = manifest.get("per_object_detachables", {}).get("objects", [])
    if not names or any(not isinstance(name, str) or not name.startswith("cylinder_") for name in names):
        raise SystemExit("spawn manifest lacks generated cylinder list")
    rclpy.init()
    client = CalibrationClient()
    try:
        ready = client.wait_calibration_ready()
        for _ in range(20):
            rclpy.spin_once(client, timeout_sec=0.05)
        home = client.move_joint_target(HOME_ARM_POSITIONS) if ready else {"executed": False}
        time.sleep(SETTLE_S)
        before_pause = set_world_pause(args.world_name, True)
        before, before_attempts = positions(names)
        before_joints = [client.latest.get(name, math.nan) for name in JOINTS]
        before_fk = client.fk(before_joints) if all(math.isfinite(value) for value in before_joints) else None
        jog_target = list(HOME_ARM_POSITIONS)
        jog_target[HOME_JOG_JOINT_INDEX] += HOME_JOG_DELTA_RAD
        before_unpause = set_world_pause(args.world_name, False)
        jog = client.move_joint_target(jog_target) if home.get("executed") and before_unpause["succeeded"] else {"executed": False}
        time.sleep(SETTLE_S)
        after_pause = set_world_pause(args.world_name, True)
        after, after_attempts = positions(names)
        after_joints = [client.latest.get(name, math.nan) for name in JOINTS]
        after_fk = client.fk(after_joints) if all(math.isfinite(value) for value in after_joints) else None
        displacements = {
            name: (math.dist(before[name], after[name]) if before[name] is not None and after[name] is not None else None)
            for name in names
        }
        ee_displacement = math.dist(before_fk[:3], after_fk[:3]) if before_fk and after_fk else None
        passed = bool(
            home.get("executed") and jog.get("executed")
            and before_pause["succeeded"] and before_unpause["succeeded"] and after_pause["succeeded"]
            and ee_displacement is not None and ee_displacement >= MIN_EE_DISPLACEMENT_M
            and all(value is not None and value <= MAX_OBJECT_DISPLACEMENT_M for value in displacements.values())
        )
        payload = {
            "schema_version": "M1BPhysicalNonCouplingResetEvidenceV1",
            "provenance": "RESET_INFRASTRUCTURE_SUPERVISION_ONLY",
            "online_truth_access": False,
            "settle_window_s": SETTLE_S,
            "pose_snapshot_max_attempts": POSE_SNAPSHOT_ATTEMPTS,
            "pose_snapshot_attempts": {"before": before_attempts, "after": after_attempts},
            "world_pause_controls": {
                "before_snapshot": before_pause,
                "before_jog": before_unpause,
                "after_snapshot": after_pause,
            },
            "home_pose_source": "S1 HOME_ARM_POSITIONS through MoveIt execution chain",
            "jog_joint_delta_rad": {JOINTS[HOME_JOG_JOINT_INDEX]: HOME_JOG_DELTA_RAD},
            "minimum_ee_displacement_m": MIN_EE_DISPLACEMENT_M,
            "maximum_object_displacement_m": MAX_OBJECT_DISPLACEMENT_M,
            "home": home,
            "jog": jog,
            "ee_displacement_m": ee_displacement,
            "object_positions_before_m": before,
            "object_positions_after_m": after,
            "object_displacements_m": displacements,
            "status": "RESET_PHYSICAL_NONCOUPLING_VERIFIED" if passed else "INVALID_RESET",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": payload["status"], "ee_displacement_m": ee_displacement}))
        return 0 if passed else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
