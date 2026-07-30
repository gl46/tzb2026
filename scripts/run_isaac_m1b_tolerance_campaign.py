#!/usr/bin/env python3
"""Run the bounded 81-trial official-Isaac M1B tolerance campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path


AXES = ("x", "y", "z")
OFFSETS_M = (0.0, -0.005, 0.005, -0.010, 0.010, -0.015, 0.015, -0.020, 0.020)
DEFAULT_TARGETS = ("cylinder_01", "cylinder_02", "cylinder_04")
OFFICIAL_ROBOT = "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def worklist(
    *,
    targets: tuple[str, ...] = DEFAULT_TARGETS,
    repetitions: int = 3,
) -> list[dict[str, object]]:
    if repetitions != len(targets):
        raise ValueError("each point must use one distinct target per repetition")
    trials = []
    for axis_index, axis in enumerate(AXES):
        for offset_m in OFFSETS_M:
            offset = [0.0, 0.0, 0.0]
            offset[axis_index] = offset_m
            for repetition, target in enumerate(targets):
                trials.append(
                    {
                        "trial_index": len(trials),
                        "axis": axis,
                        "offset_m": offset_m,
                        "offset_xyz_m": offset,
                        "repetition": repetition,
                        "target_object": target,
                    }
                )
    return trials


def _trial_id(trial: dict[str, object]) -> str:
    millimetres = int(round(float(trial["offset_m"]) * 1000))
    sign = "p" if millimetres >= 0 else "m"
    return (
        f"{int(trial['trial_index']):03d}-{trial['axis']}-{sign}{abs(millimetres):02d}"
        f"-r{int(trial['repetition'])}-{trial['target_object']}"
    )


def valid_orientation_gate_evidence(
    payload: dict[str, object],
    orientation_scan: object,
    first_attempt: dict[str, object],
) -> bool:
    """Accept either a selected safe pose or a clean pre-close pose rejection."""

    if not isinstance(orientation_scan, dict):
        return False
    candidates = orientation_scan.get("candidates")
    if (
        orientation_scan.get("source")
        != (
            "ADR0016_SAFE_FREE_GAP_GRID_PLUS_S1_20MM_"
            "PREGRASP_AND_CONTACT_POSE_GATE"
        )
        or not isinstance(candidates, list)
        or not candidates
        or any(
            not isinstance(candidate, dict)
            or candidate.get("closed_gripper_during_scan") is not False
            for candidate in candidates
        )
    ):
        return False
    if orientation_scan.get("selected") is True:
        return any(candidate.get("passed") is True for candidate in candidates)
    preclose = first_attempt.get("preclose")
    terminal_close = first_attempt.get("terminal_close")
    return bool(
        payload.get("status") == "POSE_GATE_REJECTED"
        and orientation_scan.get("selected") is False
        and all(candidate.get("passed") is False for candidate in candidates)
        and isinstance(preclose, dict)
        and preclose.get("executed") is False
        and isinstance(terminal_close, dict)
        and terminal_close.get("executed") is False
        and payload.get("contact_feedback", {}).get("grasp_success") is False
        and payload.get("attached_entity") is None
        and payload.get("attachment") is None
    )


def _valid_trial_evidence(
    evidence_path: Path,
    trial: dict[str, object],
    *,
    expected_probe_sha256: str,
) -> dict[str, object] | None:
    if not evidence_path.is_file():
        return None
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected_offset = [float(value) for value in trial["offset_xyz_m"]]
    observed_offset = payload.get("calibration_offset_xyz_m")
    free_gap_yaw = payload.get("calibration_free_gap_yaw")
    orientation_scan = payload.get("orientation_feasibility_scan")
    motion_gate = payload.get("motion_gate")
    production_primitive = payload.get("production_grasp_primitive")
    actuation_parity = payload.get("gripper_actuation_parity")
    official_robot = payload.get("official_robot")
    contact_attempts = payload.get("contact_attempts")
    first_attempt = (
        contact_attempts[0]
        if isinstance(contact_attempts, list) and len(contact_attempts) == 1
        else {}
    )
    preclose = first_attempt.get("preclose")
    terminal_close = first_attempt.get("terminal_close")
    if (
        payload.get("schema_version") != "IsaacM1BActuationProbeV1"
        or payload.get("actuation_probe_source_sha256")
        != expected_probe_sha256
        or payload.get("target_object") != trial["target_object"]
        or not isinstance(observed_offset, list)
        or len(observed_offset) != 3
        or any(
            not math.isclose(float(observed), expected, abs_tol=1e-9)
            for observed, expected in zip(observed_offset, expected_offset)
        )
        or not isinstance(free_gap_yaw, dict)
        or free_gap_yaw.get("source")
        != "CALIBRATION_LIVE_SUPERVISION_FREE_GAP_GEOMETRY"
        or free_gap_yaw.get("clearance_ok") is not True
        or not valid_orientation_gate_evidence(
            payload,
            orientation_scan,
            first_attempt,
        )
        or not isinstance(motion_gate, dict)
        or motion_gate.get("source")
        != "S1_VERIFIED_MOVEIT_EXECUTION_EE_POSITION_ERROR_GATE"
        or not isinstance(production_primitive, str)
        or "ADR0016B_two_stage_public_diameter_preclose"
        not in production_primitive
        or "ADR0016B_2mm_window_edge_squeeze" not in production_primitive
        or not isinstance(official_robot, dict)
        or official_robot.get("variants")
        != {"Gripper": "Default", "Mesh": "Performance"}
        or official_robot.get("local_simplified_robot_used") is not False
        or not math.isclose(
            float(first_attempt.get("contact_centerline_m", math.nan)),
            0.120,
            abs_tol=1e-9,
        )
        or not isinstance(preclose, dict)
        or not math.isclose(
            float(preclose.get("per_finger_target_m", math.nan)),
            0.0205,
            abs_tol=1e-9,
        )
        or preclose.get("action_mapping_source")
        != (
            "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q; "
            "SOURCE_FALLBACK_INWARD_PAD_OFFSET_REMOVED"
        )
        or preclose.get("steps") != 48
        or preclose.get("settle_steps") != 24
        or not isinstance(terminal_close, dict)
        or not math.isclose(
            float(terminal_close.get("per_finger_target_m", math.nan)),
            0.014,
            abs_tol=1e-9,
        )
        or terminal_close.get("action_mapping_source")
        != (
            "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q; "
            "SOURCE_FALLBACK_INWARD_PAD_OFFSET_REMOVED"
        )
        or terminal_close.get("close_steps") != 72
        or terminal_close.get("post_close_observation_steps") != 60
        or not isinstance(actuation_parity, dict)
        or not math.isclose(
            float(actuation_parity.get("source_effort_limit_n", math.nan)),
            20.0,
            abs_tol=1e-9,
        )
        or not math.isclose(
            float(
                actuation_parity.get(
                    "isaac_applied_driven_joint_effort_limit_n",
                    math.nan,
                )
            ),
            20.0,
            abs_tol=1e-6,
        )
        or not math.isclose(
            float(
                actuation_parity.get(
                    "isaac_applied_driven_joint_stiffness_n_per_m",
                    math.nan,
                )
            ),
            2_000.0,
            abs_tol=1e-6,
        )
        or not math.isclose(
            float(
                actuation_parity.get(
                    "isaac_applied_driven_joint_damping_n_s_per_m",
                    math.nan,
                )
            ),
            100.0,
            abs_tol=1e-6,
        )
        or (
            (actuation_parity.get("isaaclab_config") or {}).get("commit")
            != "10e969aec0c1da133c13d2b7ff7ff88641c86da6"
        )
        or actuation_parity.get("geometry_or_joint_topology_modified") is not False
    ):
        return None
    return payload


def _docker_command(
    args: argparse.Namespace,
    trial: dict[str, object],
    trial_dir: Path,
    *,
    attempt: int,
) -> list[str]:
    offset = ",".join(f"{float(value):.3f}" for value in trial["offset_xyz_m"])
    container_name = (
        f"{args.container_prefix}-{int(trial['trial_index']):03d}-a{attempt}"
    )
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
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
        f"{trial_dir}:/workspace/output",
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
        str(trial["target_object"]),
        "--physics-device",
        "cuda",
        "--contact-centerlines-m",
        f"{args.contact_centerline_m:.3f}",
        # Use the --option=value spelling because an XYZ string beginning with
        # "-" is otherwise parsed by argparse as another option.
        f"--calibration-offset-xyz-m={offset}",
        "--gripper-close-steps",
        "132",
        "--calibration-free-gap-yaw",
    ]


def summarize(
    trials: list[dict[str, object]],
    records: list[dict[str, object]],
    *,
    stage: Path,
    contact_centerline_m: float,
    probe_sha256: str,
    runner_sha256: str,
) -> dict[str, object]:
    point_results: dict[str, dict[str, object]] = {}
    for axis in AXES:
        for offset_m in OFFSETS_M:
            selected = [
                record
                for record in records
                if record["axis"] == axis
                and math.isclose(float(record["offset_m"]), offset_m, abs_tol=1e-12)
            ]
            successes = sum(bool(record["success"]) for record in selected)
            point_results[f"{axis}:{offset_m:+.3f}"] = {
                "axis": axis,
                "offset_m": offset_m,
                "successes": successes,
                "attempts": len(selected),
                "pass": len(selected) == 3 and successes >= 2,
            }
    envelope = {}
    for axis in AXES:
        admitted = 0.0
        for magnitude in (0.0, 0.005, 0.010, 0.015, 0.020):
            required = [
                point
                for point in point_results.values()
                if point["axis"] == axis
                and abs(float(point["offset_m"])) <= magnitude + 1e-12
            ]
            if required and all(bool(point["pass"]) for point in required):
                admitted = magnitude
            else:
                break
        envelope[axis] = admitted
    complete = len(records) == len(trials) == 81
    return {
        "schema_version": "IsaacM1BToleranceEnvelopeV1",
        "status": "COMPLETE_CALIBRATION_ONLY" if complete else "INCOMPLETE",
        "simulator": "Isaac Sim",
        "simulator_version": "6.0.1",
        "robot_asset": OFFICIAL_ROBOT,
        "local_simplified_robot_used": False,
        "scope": "CALIBRATION_ONLY_INITIALIZATION_NOT_POLICY_INPUT",
        "trial_count_expected": len(trials),
        "trial_count_valid": len(records),
        "calibration_targets": list(DEFAULT_TARGETS),
        "target_admission": (
            "ADR0016B_REPORTED_CORRIDOR_VALID_SCENE3000_SLOTS_1_2_4"
        ),
        "point_pass_rule": "at_least_2_of_3",
        "success_predicate": (
            "S1_20mm_PREGRASP_AND_CONTACT_POSE_GATES_then_POST_CLOSE_"
            "ADR0016B_H120_TWO_STAGE_OFFICIAL_Q20p5_PRECLOSE_then_"
            "OFFICIAL_Q14_2mm_WINDOW_EDGE_SQUEEZE_then_"
            "PINNED_NVIDIA_ISAACLAB_GRIPPER_PD_WITH_"
            "HASH_LOCKED_SOURCE_20N_EFFORT_CAP_then_"
            "BILATERAL_SAME_ENTITY_CONTACT_AND_OBSERVED_FIXED_JOINT_ATTACH"
        ),
        "grasp_yaw_contract": (
            "ADR0016_15_DEGREE_MAX_CLEARANCE_FREE_GAP_FROM_"
            "CALIBRATION_LIVE_SUPERVISION"
        ),
        "monotonic_closure": "both_signed_offsets_and_all_smaller_magnitudes_pass",
        "contact_centerline_m": contact_centerline_m,
        "tolerance_envelope_m": envelope,
        "point_results": point_results,
        "stage": str(stage),
        "stage_sha256": _sha256(stage),
        "actuation_probe_source_sha256": probe_sha256,
        "campaign_runner_source_sha256": runner_sha256,
        "trials": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--contact-centerline-m", type=float, default=0.120)
    parser.add_argument("--timebox-s", type=float, default=10_800.0)
    parser.add_argument("--max-infrastructure-attempts", type=int, default=2)
    parser.add_argument("--image", default="nvcr.io/nvidia/isaac-sim:6.0.1")
    parser.add_argument("--container-prefix", default="m1b-isaac-tol")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.gpu < 0 or args.timebox_s <= 0 or args.max_infrastructure_attempts < 1:
        parser.error("GPU, timebox, or infrastructure retry count is invalid")
    if not args.container_prefix or not all(
        character.isalnum() or character in "_.-"
        for character in args.container_prefix
    ):
        parser.error("container prefix contains unsupported characters")
    if not math.isclose(args.contact_centerline_m, 0.120, abs_tol=1e-12):
        parser.error("formal campaign must use accepted 0.120 m centreline")
    for required in (args.project_root, args.source_root, args.stage):
        if not required.exists():
            parser.error(f"required path does not exist: {required}")
    probe_path = args.project_root / "scripts" / "isaac_m1b_actuation_probe.py"
    if not probe_path.is_file():
        parser.error(f"actuation probe does not exist: {probe_path}")
    probe_sha256 = _sha256(probe_path)
    runner_sha256 = _sha256(Path(__file__))

    trials = worklist()
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "m1b-isaac-tolerance-envelope.json"
    prior_infrastructure_failures: list[dict[str, object]] = []
    if summary_path.is_file():
        try:
            prior_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior_summary = {}
        if prior_summary.get("schema_version") == "IsaacM1BToleranceEnvelopeV1":
            prior_infrastructure_failures = list(
                prior_summary.get("infrastructure_failures", [])
            )
    worklist_path = args.output / "worklist.json"
    worklist_path.write_text(
        json.dumps(trials, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "trials": len(trials),
                    "actuation_probe_source_sha256": probe_sha256,
                    "campaign_runner_source_sha256": runner_sha256,
                },
                sort_keys=True,
            )
        )
        return 0

    started = time.monotonic()
    records = []
    infrastructure_failures = list(prior_infrastructure_failures)
    for trial in trials:
        trial_id = _trial_id(trial)
        trial_dir = args.output / "trials" / trial_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        # Isaac's NGC image runs Kit as a non-host UID.  The campaign directory
        # is calibration evidence under /var/tmp, so make only this per-trial
        # bind mount writable instead of running the entire container as root.
        trial_dir.chmod(0o777)
        evidence_path = trial_dir / "actuation-probe.json"
        evidence = _valid_trial_evidence(
            evidence_path,
            trial,
            expected_probe_sha256=probe_sha256,
        )
        if evidence is None:
            for attempt in range(1, args.max_infrastructure_attempts + 1):
                if time.monotonic() - started > args.timebox_s:
                    break
                command = _docker_command(args, trial, trial_dir, attempt=attempt)
                log_path = trial_dir / f"attempt-{attempt}.log"
                with log_path.open("w", encoding="utf-8") as log:
                    completed = subprocess.run(
                        command,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                evidence = _valid_trial_evidence(
                    evidence_path,
                    trial,
                    expected_probe_sha256=probe_sha256,
                )
                if evidence is not None:
                    break
                infrastructure_failures.append(
                    {
                        "trial_id": trial_id,
                        "attempt": attempt,
                        "returncode": completed.returncode,
                        "log": str(log_path),
                    }
                )
        if evidence is None:
            if time.monotonic() - started > args.timebox_s:
                break
            continue
        contact_grasp_success = bool(
            evidence.get("contact_feedback", {}).get("grasp_success", False)
        )
        attach_observed = bool(
            evidence.get("attached_entity") == trial["target_object"]
            and evidence.get("attachment")
        )
        records.append(
            {
                **trial,
                "trial_id": trial_id,
                "status": str(evidence.get("status")),
                "contact_grasp_success": contact_grasp_success,
                "attach_observed": attach_observed,
                "success": contact_grasp_success and attach_observed,
                "evidence": str(evidence_path),
                "evidence_sha256": _sha256(evidence_path),
            }
        )
        progress = {
            "status": "RUNNING",
            "valid_trials": len(records),
            "expected_trials": len(trials),
            "elapsed_s": time.monotonic() - started,
            "infrastructure_failures": infrastructure_failures,
            "actuation_probe_source_sha256": probe_sha256,
            "campaign_runner_source_sha256": runner_sha256,
        }
        (args.output / "progress.json").write_text(
            json.dumps(progress, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(progress, sort_keys=True), flush=True)

    summary = summarize(
        trials,
        records,
        stage=args.stage,
        contact_centerline_m=args.contact_centerline_m,
        probe_sha256=probe_sha256,
        runner_sha256=runner_sha256,
    )
    summary["worklist_sha256"] = _sha256(worklist_path)
    summary["elapsed_s"] = time.monotonic() - started
    summary["infrastructure_failures"] = infrastructure_failures
    summary["prior_infrastructure_failure_count"] = len(
        prior_infrastructure_failures
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": summary["status"],
                "valid_trials": summary["trial_count_valid"],
                "tolerance_envelope_m": summary["tolerance_envelope_m"],
                "summary": str(summary_path),
            },
            sort_keys=True,
        )
    )
    return 0 if summary["status"] == "COMPLETE_CALIBRATION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
