#!/usr/bin/env python3
"""Broadcast M1B detach to every generated cylinder and verify each state.

This is an actuation-internal reset utility.  It gets the object list only from
the generated Panda spawn manifest; neither task specs nor perception need see
the simulator entity names used to address the detachable joints.
"""
from __future__ import annotations

import argparse
import json
import os
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
        # Gazebo transport subscriptions are established asynchronously.  The
        # state topic is one-shot, so wait for the monitor subscription before
        # publishing detach; this is delivery ordering, not a retry or a
        # weakened RESET_VERIFIED criterion.
        time.sleep(0.40)
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


def detach_all_and_observe(object_names: list[str], timeout_s: float) -> list[M1BResetVerificationV1]:
    """Arm every one-shot state monitor before broadcasting the N detaches."""
    monitors: dict[str, subprocess.Popen[str]] = {}
    lines: dict[str, list[str]] = {name: [] for name in object_names}
    try:
        for name in object_names:
            monitors[name] = subprocess.Popen(
                ["gz", "topic", "-e", "-t", f"/xh/m1b/{name}/grasp_state"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
        # The N observers must all exist before the first detach is published.
        # This protects the whole reset transaction from one-shot state loss.
        time.sleep(1.0)
        commands = {}
        for name in object_names:
            commands[name] = subprocess.run(
                ["gz", "topic", "-t", f"/xh/m1b/{name}/detach", "-m", "gz.msgs.Empty", "-p", "unused: true"],
                check=False, capture_output=True, text=True, timeout=timeout_s,
            )
        observed = {name: False for name in object_names}
        def collect(deadline: float) -> None:
            while time.monotonic() < deadline and not all(observed.values()):
                for name, monitor in monitors.items():
                    if observed[name] or monitor.stdout is None:
                        continue
                    ready, _, _ = select.select([monitor.stdout], [], [], 0.01)
                    if not ready:
                        continue
                    line = monitor.stdout.readline()
                    if not line:
                        continue
                    lines[name].append(line.rstrip())
                    observed[name] = "detached" in line

        collect(time.monotonic() + timeout_s)
        missing = [name for name in object_names if not observed[name]]
        if missing:
            # A DetachableJoint emits its state on transition.  If the initial
            # transition was lost despite all monitors being armed, force one
            # explicit attach→detach transition while those same monitors stay
            # live, then require the new final `detached` evidence.  This is a
            # repair of transport observability, never a bypass of the final
            # all-N detached requirement.
            for name in missing:
                lines[name].append("repair_cycle: attach_then_detach")
                subprocess.run(
                    ["gz", "topic", "-t", f"/xh/m1b/{name}/attach", "-m", "gz.msgs.Empty", "-p", "unused: true"],
                    check=False, capture_output=True, text=True, timeout=timeout_s,
                )
            # `gz topic -e` exits after printing a one-shot state on this
            # Gazebo build.  Replace the monitor after the attach transition
            # so the final detach has a fresh subscriber.
            for name in missing:
                monitors[name].terminate()
                try:
                    monitors[name].wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    monitors[name].kill()
                    monitors[name].wait(timeout=1.0)
                monitors[name] = subprocess.Popen(
                    ["gz", "topic", "-e", "-t", f"/xh/m1b/{name}/grasp_state"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
            time.sleep(1.0)
            for name in missing:
                subprocess.run(
                    ["gz", "topic", "-t", f"/xh/m1b/{name}/detach", "-m", "gz.msgs.Empty", "-p", "unused: true"],
                    check=False, capture_output=True, text=True, timeout=timeout_s,
                )
            collect(time.monotonic() + timeout_s)
        records = []
        for name in object_names:
            command = commands[name]
            if command.returncode != 0:
                lines[name].extend(value for value in (command.stdout, command.stderr) if value)
            records.append(M1BResetVerificationV1(
                name, f"/xh/m1b/{name}/detach", f"/xh/m1b/{name}/grasp_state",
                observed[name], tuple(lines[name]),
            ))
        return records
    finally:
        for monitor in monitors.values():
            monitor.terminate()
        for monitor in monitors.values():
            try:
                monitor.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                monitor.kill()
                monitor.wait(timeout=1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spawn-manifest", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument("--world-name", help="Required with --resume-world after a paused M1B reset")
    parser.add_argument("--resume-world", action="store_true", help="Resume Gazebo only after RESET_VERIFIED")
    parser.add_argument(
        "--activate-controllers",
        action="store_true",
        help="Activate the preloaded Panda controllers only after a successful world resume",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout_s <= 0:
        raise SystemExit("--timeout-s must be positive")
    if args.activate_controllers and not args.resume_world:
        raise SystemExit("--activate-controllers requires --resume-world")
    manifest = json.loads(args.spawn_manifest.read_text(encoding="utf-8"))
    per_object = manifest.get("per_object_detachables")
    if not isinstance(per_object, dict) or not isinstance(per_object.get("objects"), list):
        raise SystemExit("spawn manifest lacks per_object_detachables")
    objects = per_object["objects"]
    if not objects or any(not isinstance(name, str) or not name.startswith("cylinder_") for name in objects):
        raise SystemExit("spawn manifest has invalid detachable object list")
    records = detach_all_and_observe(objects, args.timeout_s)
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
                env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
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
    if args.activate_controllers:
        if status != "RESET_VERIFIED":
            payload["controller_activation"] = {"attempted": False, "reason": "WORLD_NOT_RESUMED"}
        else:
            attempts = []
            for attempt in range(1, 4):
                result = subprocess.run(
                    [
                        "bash", "-lc",
                        "source /opt/ros/jazzy/setup.bash && "
                        "required=(joint_state_broadcaster panda_arm_controller panda_hand_physical_controller); "
                        "pending=(); "
                        "for controller in \"${required[@]}\"; do "
                        "state=$(ros2 control list_controllers | awk -v name=\"$controller\" '$1 == name {print $NF}'); "
                        "if [ \"$state\" != active ]; then pending+=(\"$controller\"); fi; "
                        "done; "
                        "if [ ${#pending[@]} -eq 0 ]; then echo CONTROLLERS_ALREADY_ACTIVE; "
                        "else ros2 control switch_controllers --activate \"${pending[@]}\" --strict; fi",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    env={
                        key: value
                        for key, value in os.environ.items()
                        if key not in {"PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME"}
                    },
                )
                attempts.append({
                    "attempt": attempt,
                    "returncode": result.returncode,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                })
                if result.returncode == 0:
                    break
                # Gazebo resumes asynchronously.  Controller-manager services
                # may exist before the paused-world spawners have loaded all
                # controllers, so retry only this post-resume lifecycle step.
                time.sleep(1.0)
            assert attempts
            last = attempts[-1]
            payload["controller_activation"] = {
                "attempted": True,
                "attempts": attempts,
                "returncode": last["returncode"],
                "stdout": last["stdout"],
                "stderr": last["stderr"],
                "activated": last["returncode"] == 0,
            }
            if not payload["controller_activation"]["activated"]:
                status = "INVALID_RESET"
                payload["status"] = status
                payload["reasons"].append("CONTROLLER_ACTIVATION_FAILED")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "objects": len(objects), "reasons": payload["reasons"]}))
    return 0 if status == "RESET_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
