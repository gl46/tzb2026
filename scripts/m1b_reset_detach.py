#!/usr/bin/env python3
"""Broadcast M1B detach to every generated cylinder and verify each state.

This is an actuation-internal reset utility.  It gets the object list only from
the generated Panda spawn manifest; neither task specs nor perception need see
the simulator entity names used to address the detachable joints.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import select
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from xh_agent.grasp.reset import M1BResetVerificationV1, validate_reset_records  # noqa: E402


def detach_and_observe(object_name: str, timeout_s: float) -> M1BResetVerificationV1:
    detach_topic = f"/xh/m1b/{object_name}/detach"
    state_topic = f"/xh/m1b/{object_name}/grasp_state"
    monitor = subprocess.Popen(
        ["gz", "topic", "-e", "-t", state_topic],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []
    try:
        time.sleep(0.10)
        command = subprocess.run(
            ["gz", "topic", "-t", detach_topic, "-m", "gz.msgs.Empty", "-p", "unused: true"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if command.returncode != 0:
            lines.extend(line for line in (command.stdout, command.stderr) if line)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and monitor.stdout is not None:
            ready, _, _ = select.select([monitor.stdout], [], [], 0.05)
            if not ready:
                continue
            line = monitor.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())
            if "detached" in line:
                break
    finally:
        monitor.terminate()
        try:
            monitor.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            monitor.kill()
            monitor.wait(timeout=1.0)
    return M1BResetVerificationV1(object_name, detach_topic, state_topic, any("detached" in line for line in lines), tuple(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spawn-manifest", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument("--world-name", help="Required with --resume-world after a paused M1B reset")
    parser.add_argument("--resume-world", action="store_true", help="Resume Gazebo only after RESET_VERIFIED")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    manifest = json.loads(args.spawn_manifest.read_text(encoding="utf-8"))
    per_object = manifest.get("per_object_detachables")
    if not isinstance(per_object, dict) or not isinstance(per_object.get("objects"), list):
        raise SystemExit("spawn manifest lacks per_object_detachables")
    objects = per_object["objects"]
    if not objects or any(not isinstance(name, str) or not name.startswith("cylinder_") for name in objects):
        raise SystemExit("spawn manifest has invalid detachable object list")
    records = [detach_and_observe(name, args.timeout_s) for name in objects]
    status, reasons = validate_reset_records(records, objects)
    payload = {
        "schema_version": "M1BResetDetachEvidenceV1",
        "status": status,
        "reasons": list(reasons),
        "spawn_manifest": str(args.spawn_manifest),
        "objects": [record.object_name for record in records],
        "records": [
            {
                "object_name": record.object_name,
                "detach_topic": record.detach_topic,
                "grasp_state_topic": record.grasp_state_topic,
                "detached_observed": record.detached_observed,
                "state_lines": list(record.state_lines),
            }
            for record in records
        ],
    }
    if args.resume_world:
        if not args.world_name:
            raise SystemExit("--resume-world requires --world-name")
        if status != "RESET_VERIFIED":
            payload["world_resume"] = {"attempted": False, "reason": "RESET_NOT_VERIFIED"}
        else:
            result = subprocess.run(
                [
                    "gz", "service", "--service", f"/world/{args.world_name}/control",
                    "--reqtype", "gz.msgs.WorldControl", "--reptype", "gz.msgs.Boolean",
                    "--timeout", "3000", "--req", "pause: false",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload["world_resume"] = {
                "attempted": True,
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "resumed": result.returncode == 0 and "data: true" in result.stdout,
            }
            if not payload["world_resume"]["resumed"]:
                status = "INVALID_RESET"
                payload["status"] = status
                payload["reasons"].append("WORLD_RESUME_FAILED")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "objects": len(objects), "reasons": payload["reasons"]}))
    return 0 if status == "RESET_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
