#!/usr/bin/env python3
"""Run restart-safe M2B physical injection probes on one Isaac GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(
    args: argparse.Namespace,
    *,
    failure: str,
    attempt: int,
    output: Path,
) -> list[str]:
    name = f"{args.container_prefix}-{failure.lower()}-a{attempt}"
    target_object = (
        args.public_target_object
        if args.capture_public_rgbd and failure != "WRONG_OBJECT"
        else args.target_object
    )
    flags = {
        "EMPTY_GRASP": ["--m2b-inject-empty-grasp"],
        "WRONG_OBJECT": [
            "--m2b-task-target-object",
            args.wrong_object_task_target,
        ],
        "RELEASE_FAILURE": ["--m2b-inject-release-failure"],
    }[failure]
    if args.capture_public_rgbd:
        flags.extend(
            [
                "--m2b-capture-public-rgbd",
                "--m2b-task-target-public-color",
                "red" if failure == "WRONG_OBJECT" else "yellow",
            ]
        )
        if failure == "WRONG_OBJECT":
            flags.extend(
                ["--m2b-injected-public-grasp-color", "yellow"]
            )
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--gpus",
        f"device={args.gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{args.project_root}:/workspace/project:ro",
        "-v",
        f"{args.source_root}:/workspace/source:ro",
        "-v",
        f"{args.stage.parent}:/workspace/stage:ro",
        "-v",
        f"{output}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        args.image,
        "scripts/isaac_m1b_actuation_probe.py",
        "--stage",
        f"/workspace/stage/{args.stage.name}",
        "--sdf",
        "/workspace/source/scene-3000.sdf",
        "--supervision",
        "/workspace/source/scene-3000.supervision.json",
        "--urdf",
        "/workspace/source/panda_controlled.urdf",
        "--output",
        "/workspace/output",
        "--target-object",
        target_object,
        "--physics-device",
        "cuda",
        "--contact-centerlines-m",
        str(args.contact_centerline_m),
        "--gripper-close-steps",
        "132",
        "--calibration-free-gap-yaw",
        *flags,
    ]


def accepted(
    payload: dict[str, Any],
    failure: str,
    *,
    public_rgbd_required: bool = False,
) -> bool:
    if payload.get("status") != "PASS" or not payload.get("m2b_injection_pass"):
        return False
    if failure == "EMPTY_GRASP":
        evidence = payload.get("m2b_empty_grasp_injection") or {}
        recovery = payload.get("m2b_recovery", {}).get("empty_grasp") or {}
        result = bool(
            evidence.get("failure_type") == failure
            and evidence.get("physical_state_passed")
            and recovery.get("physical_regrasp_and_lift_passed")
        )
        if public_rgbd_required:
            return bool(
                result
                and evidence.get("training_eligible") is True
                and recovery.get("training_eligible") is True
            )
        return result and evidence.get("training_eligible") is False
    if failure == "WRONG_OBJECT":
        evidence = payload.get("m2b_wrong_object_injection") or {}
        recovery = payload.get("m2b_recovery", {}).get("wrong_object") or {}
        result = bool(
            evidence.get("failure_type") == failure
            and evidence.get("physical_state_passed")
            and recovery.get("safe_place_non_target_passed")
            and recovery.get("reassociate_target_executed") is False
            and recovery.get("regrasp_target_executed") is False
        )
        if public_rgbd_required:
            return bool(result and evidence.get("training_eligible") is True)
        return result and evidence.get("training_eligible") is False
    evidence = payload.get("m2b_release_failure_injection") or {}
    recovery = payload.get("m2b_recovery", {}).get("release_failure") or {}
    result = bool(
        evidence.get("failure_type") == failure
        and evidence.get("physical_state_passed")
        and recovery.get("retry_detach_and_retreat_passed")
    )
    if public_rgbd_required:
        return bool(
            result
            and evidence.get("training_eligible") is True
            and recovery.get("training_eligible") is True
        )
    return result and evidence.get("training_eligible") is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--target-object", default="cylinder_04")
    parser.add_argument("--public-target-object", default="cylinder_04")
    parser.add_argument("--wrong-object-task-target", default="cylinder_07")
    parser.add_argument("--contact-centerline-m", default="0.120")
    parser.add_argument(
        "--image", default="nvcr.io/nvidia/isaac-sim:6.0.1"
    )
    parser.add_argument("--container-prefix", default="m2b-physical-smoke")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout-s", type=float, default=1800.0)
    parser.add_argument("--settle-s", type=float, default=30.0)
    parser.add_argument("--capture-public-rgbd", action="store_true")
    parser.add_argument(
        "--failures",
        default="EMPTY_GRASP,WRONG_OBJECT,RELEASE_FAILURE",
        help="Comma-separated subset for restart-safe targeted reruns.",
    )
    args = parser.parse_args()
    failures = tuple(
        failure.strip() for failure in args.failures.split(",") if failure.strip()
    )
    supported_failures = {"EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"}
    if not failures or not set(failures).issubset(supported_failures):
        parser.error(f"--failures must be a subset of {sorted(supported_failures)}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    results = []
    for failure in failures:
        accepted_record = None
        for attempt in range(1, args.max_attempts + 1):
            output = args.output_root / failure.lower() / f"attempt-{attempt:02d}"
            output.mkdir(parents=True, exist_ok=False)
            output.chmod(0o777)
            started = time.monotonic()
            completed = subprocess.run(
                command(
                    args,
                    failure=failure,
                    attempt=attempt,
                    output=output,
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=args.timeout_s,
            )
            (output / "console.log").write_text(
                completed.stdout + completed.stderr
            )
            evidence_path = output / "actuation-probe.json"
            payload = (
                json.loads(evidence_path.read_text())
                if evidence_path.is_file()
                else None
            )
            record = {
                "failure_type": failure,
                "attempt": attempt,
                "returncode": completed.returncode,
                "elapsed_s": time.monotonic() - started,
                "evidence": str(evidence_path),
                "evidence_sha256": (
                    sha256(evidence_path) if evidence_path.is_file() else None
                ),
                "accepted": bool(
                    payload
                    and accepted(
                        payload,
                        failure,
                        public_rgbd_required=args.capture_public_rgbd,
                    )
                ),
            }
            results.append(record)
            if record["accepted"]:
                accepted_record = record
                break
            if attempt < args.max_attempts:
                time.sleep(args.settle_s)
        if accepted_record is None:
            break
        time.sleep(args.settle_s)
    accepted_failures = {
        item["failure_type"] for item in results if item["accepted"]
    }
    summary = {
        "schema_version": "M2BPhysicalFailureSmokeV1",
        "status": (
            "PASS"
            if accepted_failures == set(failures)
            else "PARTIAL"
        ),
        "training_eligible": False,
        "reason": (
            "WRONG_OBJECT target reassociation/regrasp remains pending"
            if args.capture_public_rgbd
            else "public RGB-D predicates are not captured by this probe"
        ),
        "public_rgbd_required": args.capture_public_rgbd,
        "accepted_failures": sorted(accepted_failures),
        "requested_failures": list(failures),
        "attempts": results,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    summary_path = args.output_root / "physical-failure-smoke.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
