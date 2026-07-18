#!/usr/bin/env python3
"""Verify an already broker-attached M1B cylinder follows, detaches, and decouples.

This is an acceptance/evaluation utility, not a control-stack component.  It
reads Gazebo poses only after the broker has selected and attached the entity,
and records them as simulator-supervision evidence.  No queried pose is fed
back into grasp selection, planning, or attachment.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import rclpy

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from m1a_contact_calibration_client import CalibrationClient  # noqa: E402
from m1b_reset_detach import detach_and_observe  # noqa: E402
from m1a_moveit_execution_client import JOINTS  # noqa: E402


POSE_RE = re.compile(
    r"Pose \[ XYZ \(m\) \] \[ RPY \(rad\) \]:\s*"
    r"\[\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\]"
)


def gazebo_position(model: str, *, link: str | None = None) -> list[float] | None:
    command = ["timeout", "2", "gz", "model", "-m", model]
    command.extend(["-l", link] if link else ["-p"])
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=4.0)
    match = POSE_RE.search(result.stdout)
    return [float(value) for value in match.groups()] if match else None


def distance(first: list[float] | None, second: list[float] | None) -> float | None:
    if first is None or second is None:
        return None
    return math.dist(first, second)


def relative(cylinder: list[float] | None, link: list[float] | None) -> list[float] | None:
    return [a - b for a, b in zip(cylinder, link)] if cylinder is not None and link is not None else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", required=True, help="Actuation-internal entity selected by the broker")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"cylinder_[0-9]{2}", args.entity):
        raise SystemExit("entity must be a generated cylinder id")

    rclpy.init()
    client = CalibrationClient()
    try:
        ready = client.wait_calibration_ready()
        for _ in range(20):
            rclpy.spin_once(client, timeout_sec=0.05)
        current = [client.latest.get(name, math.nan) for name in JOINTS]
        before_link = gazebo_position("panda_controller", link="panda_link7")
        before_cylinder = gazebo_position(args.entity)
        move_target = list(current)
        # A small base-axis transport displacement gives the constraint a
        # measurable follow test while remaining far inside Panda limits.
        move_target[0] += 0.10
        attached_move = client.move_joint_target(move_target) if ready and all(math.isfinite(v) for v in current) else {"executed": False}
        after_link = gazebo_position("panda_controller", link="panda_link7")
        after_cylinder = gazebo_position(args.entity)
        link_motion = distance(before_link, after_link)
        cylinder_motion = distance(before_cylinder, after_cylinder)
        relative_drift = distance(relative(before_cylinder, before_link), relative(after_cylinder, after_link))
        attached_follow = bool(
            attached_move.get("executed")
            and link_motion is not None and link_motion >= 0.01
            and cylinder_motion is not None and cylinder_motion >= 0.01
            and relative_drift is not None and relative_drift <= 0.01
        )
        detach = detach_and_observe(args.entity, 2.0) if attached_follow else None
        detach_verified = bool(detach and detach.detached_observed)
        before_decouple_link = gazebo_position("panda_controller", link="panda_link7")
        before_decouple_cylinder = gazebo_position(args.entity)
        decouple_target = list(move_target)
        decouple_target[0] -= 0.12
        detached_move = client.move_joint_target(decouple_target) if detach_verified else {"executed": False}
        after_decouple_link = gazebo_position("panda_controller", link="panda_link7")
        after_decouple_cylinder = gazebo_position(args.entity)
        decouple_link_motion = distance(before_decouple_link, after_decouple_link)
        decouple_relative_change = distance(
            relative(before_decouple_cylinder, before_decouple_link),
            relative(after_decouple_cylinder, after_decouple_link),
        )
        detached_decoupled = bool(
            detached_move.get("executed")
            and decouple_link_motion is not None and decouple_link_motion >= 0.01
            and decouple_relative_change is not None and decouple_relative_change >= 0.01
        )
        payload = {
            "schema_version": "M1BAttachedRoundTripEvidenceV1",
            "provenance": "SUPERVISION_EVALUATION_ONLY",
            "online_truth_access": False,
            "entity_source": "actuation_internal_broker_attach_record",
            "entity": args.entity,
            "attached_move": attached_move,
            "attached_follow": attached_follow,
            "attached_follow_metrics": {"link_motion_m": link_motion, "cylinder_motion_m": cylinder_motion, "relative_drift_m": relative_drift},
            "detach": None if detach is None else {"topic": detach.detach_topic, "state_topic": detach.grasp_state_topic, "detached_observed": detach.detached_observed, "state_lines": list(detach.state_lines)},
            "detached_move": detached_move,
            "detached_decoupled": detached_decoupled,
            "detached_decouple_metrics": {"link_motion_m": decouple_link_motion, "relative_change_m": decouple_relative_change},
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"attached_follow": attached_follow, "detach_verified": detach_verified, "detached_decoupled": detached_decoupled}))
        return 0 if attached_follow and detach_verified and detached_decoupled else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
