#!/usr/bin/env python3
"""One non-counting Bullet controller capability segment for ADR-0009."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import rclpy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from m1a_moveit_execution_client import EvidenceClient, TARGETS, segment_evidence  # noqa: E402


def main() -> int:
    rclpy.init()
    client = EvidenceClient()
    try:
        if not client.wait_ready():
            print(json.dumps({"status": "M1A_BULLET_CONTROLLER_BLOCKED", "reason": "MOVEIT_ENDPOINTS_UNAVAILABLE"}))
            return 2
        deadline = time.monotonic() + 10.0
        while not client.latest and time.monotonic() < deadline:
            rclpy.spin_once(client, timeout_sec=0.1)
        if not client.latest or not client.apply_scene():
            print(json.dumps({"status": "M1A_BULLET_CONTROLLER_BLOCKED", "reason": "JOINT_STATE_OR_SCENE_UNAVAILABLE"}))
            return 2
        segment = segment_evidence(client, 0, "bullet_capability_single_segment", TARGETS[0][1])
        print(json.dumps({
            "status": "M1A_BULLET_CONTROLLER_VERIFIED" if segment.get("success") else "M1A_BULLET_CONTROLLER_BLOCKED",
            "scope": "ADR-0009 capability probe; not an S1 trial",
            "segment": segment,
            "success": bool(segment.get("success")),
        }))
        return 0 if segment.get("success") else 2
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
