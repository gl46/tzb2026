#!/usr/bin/env python3
"""Offline public-RGB-D audit and optional Isaac tolerance-envelope gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from xh_agent.contracts.models import EpisodeTransitionV0, ObjectTrackV0, ObservationV0
from xh_agent.data.isaac_m1b_episode import IsaacM1BSupervisionFrameV1


AXES = ("x", "y", "z")
OFFICIAL_ROBOT = "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)])


def _distance(track: ObjectTrackV0, truth_pose: list[float]) -> float:
    return math.sqrt(
        sum((float(track.pose[index]) - float(truth_pose[index])) ** 2 for index in range(3))
    )


def optimal_public_truth_assignment(
    tracks: list[ObjectTrackV0],
    truth: dict[str, list[float]],
    *,
    max_distance_m: float,
) -> list[tuple[ObjectTrackV0, str, float]]:
    """Maximum-cardinality, minimum-distance assignment for offline evaluation."""

    if max_distance_m <= 0:
        raise ValueError("max association distance must be positive")
    entities = sorted(truth)
    # mask -> (cost, [(track_index, entity_index, distance), ...])
    states: dict[int, tuple[float, list[tuple[int, int, float]]]] = {0: (0.0, [])}
    for track_index, track in enumerate(tracks):
        next_states = dict(states)
        for mask, (cost, assignments) in states.items():
            for entity_index, entity in enumerate(entities):
                bit = 1 << entity_index
                if mask & bit:
                    continue
                distance = _distance(track, truth[entity])
                if distance > max_distance_m:
                    continue
                new_mask = mask | bit
                new_cost = cost + distance
                current = next_states.get(new_mask)
                if current is None or new_cost < current[0]:
                    next_states[new_mask] = (
                        new_cost,
                        [*assignments, (track_index, entity_index, distance)],
                    )
        states = next_states
    _, assignments = min(
        states.values(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    return [
        (tracks[track_index], entities[entity_index], distance)
        for track_index, entity_index, distance in assignments
    ]


def _read_transitions(path: Path) -> list[EpisodeTransitionV0]:
    output = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                transition = EpisodeTransitionV0.model_validate_json(line)
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            if transition.teacher_response is not None:
                raise ValueError(
                    f"{path}:{line_number}: TeacherResponse is forbidden "
                    "in the Student evaluation stream"
                )
            if any(
                observation.segmentation_uri is not None
                for observation in (
                    transition.observation_before,
                    transition.observation_after,
                )
            ):
                raise ValueError(
                    f"{path}:{line_number}: policy segmentation is forbidden"
                )
            output.append(transition)
    if not output:
        raise ValueError("transition stream is empty")
    return output


def _read_supervision(path: Path) -> list[IsaacM1BSupervisionFrameV1]:
    output = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                output.append(IsaacM1BSupervisionFrameV1.model_validate_json(line))
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    if not output:
        raise ValueError("supervision stream is empty")
    return output


def _validate_transition_metrics(
    dataset_root: Path,
    transitions_path: Path,
) -> dict[str, object]:
    metrics_path = dataset_root / "transition_metrics.json"
    if not metrics_path.is_file():
        raise FileNotFoundError(metrics_path)
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    if (
        payload.get("status") != "PASS"
        or payload.get("episode_transitions_sha256")
        != _sha256(transitions_path)
        or payload.get("teacher_response_nonnull") != 0
        or payload.get("policy_segmentation_uri_nonnull") != 0
        or payload.get("capture_mode")
        not in {
            "DYNAMIC_STUDENT_DATASET",
            "CALIBRATION_ONLY_STATIC_PERCEPTION",
        }
        or payload.get("student_training_eligible")
        is not (
            payload.get("capture_mode") == "DYNAMIC_STUDENT_DATASET"
        )
        or not isinstance(
            payload.get("public_xy_correction_runtime_enabled"),
            bool,
        )
        or (
            payload.get("public_xy_correction_runtime_enabled") is True
            and not isinstance(
                payload.get("public_xy_correction_fingerprint"),
                str,
            )
        )
        or payload.get("tilted_center_support_offset")
        != "PUBLIC_PERCEIVED_RADIUS"
        or payload.get("center_xy_projection")
        != (
            "PUBLIC_RAY_PLANE_WORLD_X_PLUS_"
            "VISIBLE_SURFACE_RADIUS_WORLD_Y"
        )
        or payload.get("robot_asset_required") != OFFICIAL_ROBOT
        or payload.get("official_robot_variants")
        != {"Gripper": "Default", "Mesh": "Performance"}
        or payload.get("local_simplified_robot_used") is not False
    ):
        raise ValueError(
            "transition metrics do not prove a Teacher-free official "
            "Isaac M1B stream"
        )
    return payload


def _unique_observations(
    transitions: list[EpisodeTransitionV0],
) -> dict[tuple[str, int, int], ObservationV0]:
    observations: dict[tuple[str, int, int], ObservationV0] = {}
    for transition in transitions:
        for observation in (
            transition.observation_before,
            transition.observation_after,
        ):
            key = (
                observation.episode_id,
                observation.step_id,
                observation.timestamp_ns,
            )
            existing = observations.get(key)
            if existing is not None and existing.model_dump() != observation.model_dump():
                raise ValueError(f"conflicting duplicate observation: {key}")
            observations[key] = observation
    return observations


def _load_isaac_envelope(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "IsaacM1BToleranceEnvelopeV1":
        raise ValueError("gate requires an IsaacM1BToleranceEnvelopeV1 artifact")
    if (
        payload.get("status") != "COMPLETE_CALIBRATION_ONLY"
        or payload.get("trial_count_valid") != 81
        or payload.get("trial_count_expected") != 81
    ):
        raise ValueError("Isaac tolerance envelope campaign is incomplete")
    if payload.get("simulator") != "Isaac Sim" or payload.get("robot_asset") != OFFICIAL_ROBOT:
        raise ValueError("tolerance envelope is not bound to the official Isaac Franka")
    envelope = payload.get("tolerance_envelope_m")
    if not isinstance(envelope, dict):
        raise ValueError("Isaac tolerance envelope has no axis values")
    values = {axis: float(envelope[axis]) for axis in AXES}
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError(
            "Isaac tolerance envelope axes must be finite and nonnegative"
        )
    return values


def evaluate(
    transitions: list[EpisodeTransitionV0],
    supervision: list[IsaacM1BSupervisionFrameV1],
    *,
    max_association_distance_m: float,
    tolerance_envelope_m: dict[str, float] | None,
) -> dict[str, Any]:
    observations = _unique_observations(transitions)
    truth_by_key = {
        (frame.episode_id, frame.step_id, frame.timestamp_ns): frame
        for frame in supervision
    }
    if set(observations) != set(truth_by_key):
        raise ValueError("public observation and supervision frame keys do not match")
    matches = []
    absolute_axis_errors = {axis: [] for axis in AXES}
    truth_instances = 0
    public_instances = 0
    globally_leftmost_correct = 0
    globally_leftmost_evaluated = 0
    for key in sorted(observations):
        observation = observations[key]
        frame_truth = truth_by_key[key].perfect_object_poses_world_xyzw
        assignments = optimal_public_truth_assignment(
            observation.object_tracks,
            frame_truth,
            max_distance_m=max_association_distance_m,
        )
        assignment_by_track = {track.object_id: entity for track, entity, _ in assignments}
        truth_instances += len(frame_truth)
        public_instances += len(observation.object_tracks)
        if observation.object_tracks:
            globally_leftmost_evaluated += 1
            selected = min(observation.object_tracks, key=lambda track: track.pose[0])
            truth_leftmost = min(frame_truth, key=lambda entity: frame_truth[entity][0])
            globally_leftmost_correct += assignment_by_track.get(selected.object_id) == truth_leftmost
        for track, entity, distance in assignments:
            signed = [
                float(track.pose[index]) - float(frame_truth[entity][index])
                for index in range(3)
            ]
            for axis, error in zip(AXES, signed):
                absolute_axis_errors[axis].append(abs(error))
            matches.append(
                {
                    "episode_id": observation.episode_id,
                    "step_id": observation.step_id,
                    "public_track_id": track.object_id,
                    "offline_truth_entity": entity,
                    "error_world_xyz_m": signed,
                    "euclidean_error_m": distance,
                }
            )
    p90 = {
        axis: _nearest_rank(absolute_axis_errors[axis], 0.90) for axis in AXES
    }
    median = {
        axis: _nearest_rank(absolute_axis_errors[axis], 0.50) for axis in AXES
    }
    if tolerance_envelope_m is None:
        gate = {
            "status": "AUDIT_ONLY_NO_ISAAC_TOLERANCE_ENVELOPE",
            "reason": (
                "Gazebo envelope reuse is forbidden; run the official-Isaac "
                "calibration campaign before GO/NO_GO"
            ),
        }
        status = "ACTUAL_ISAAC_RGBD_AUDIT_COMPLETE_GATE_PENDING"
    else:
        limits = {axis: 0.6 * tolerance_envelope_m[axis] for axis in AXES}
        all_envelope_axes_nonzero = all(
            value > 0 for value in tolerance_envelope_m.values()
        )
        axis_pass = {
            axis: (
                p90[axis] is not None
                and float(p90[axis]) <= limits[axis] + 1e-12
            )
            for axis in AXES
        }
        gate = {
            "status": (
                "GO"
                if all_envelope_axes_nonzero and all(axis_pass.values())
                else "NO_GO"
            ),
            "margin_factor": 0.6,
            "tolerance_envelope_m": tolerance_envelope_m,
            "all_envelope_axes_nonzero": all_envelope_axes_nonzero,
            "p90_limits_m": limits,
            "axis_pass": axis_pass,
        }
        status = gate["status"]
    return {
        "schema_version": "IsaacM1BPublicPerceptionAuditV1",
        "status": status,
        "frames": len(observations),
        "truth_instances": truth_instances,
        "public_instances": public_instances,
        "matched_instances": len(matches),
        "matched_truth_recall": len(matches) / truth_instances if truth_instances else 0.0,
        "matched_public_precision": len(matches) / public_instances if public_instances else 0.0,
        "median_abs_error_world_xyz_m": median,
        "p90_abs_error_world_xyz_m": p90,
        "global_leftmost_target_accuracy": (
            globally_leftmost_correct / globally_leftmost_evaluated
            if globally_leftmost_evaluated
            else None
        ),
        "max_association_distance_m": max_association_distance_m,
        "gate": gate,
        "matches": matches,
        "truth_boundary": (
            "public ObservationV0 tracks are produced before this evaluator "
            "loads offline Isaac supervision; truth is never a Student input"
        ),
        "robot_asset_required": OFFICIAL_ROBOT,
        "local_simplified_robot_used": False,
    }


def gate_exit_code(payload: dict[str, Any]) -> int:
    """Make a measured NO_GO observable to shell orchestration."""
    return 1 if payload.get("status") == "NO_GO" else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        required=True,
        type=Path,
        action="append",
        help="One or more independently captured Isaac worker datasets.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-association-distance-m", type=float, default=0.06)
    parser.add_argument("--isaac-tolerance-envelope", type=Path)
    parser.add_argument(
        "--require-static-perception-audit",
        action="store_true",
        help=(
            "Fail closed unless every input was captured as calibration-only "
            "static perception evidence and is ineligible for Student training."
        ),
    )
    args = parser.parse_args()
    dataset_roots = args.dataset_root
    transitions_paths = [
        root / "episode_transitions.jsonl" for root in dataset_roots
    ]
    supervision_paths = [
        root / "supervision_frames.jsonl" for root in dataset_roots
    ]
    envelope = (
        _load_isaac_envelope(args.isaac_tolerance_envelope)
        if args.isaac_tolerance_envelope
        else None
    )
    transition_metrics = [
        _validate_transition_metrics(root, path)
        for root, path in zip(dataset_roots, transitions_paths)
    ]
    if args.require_static_perception_audit and any(
        metrics.get("capture_mode")
        != "CALIBRATION_ONLY_STATIC_PERCEPTION"
        or metrics.get("student_training_eligible") is not False
        for metrics in transition_metrics
    ):
        raise ValueError(
            "static perception gate requires calibration-only, "
            "training-ineligible captures"
        )
    payload = evaluate(
        [
            transition
            for path in transitions_paths
            for transition in _read_transitions(path)
        ],
        [
            frame
            for path in supervision_paths
            for frame in _read_supervision(path)
        ],
        max_association_distance_m=args.max_association_distance_m,
        tolerance_envelope_m=envelope,
    )
    payload["perception_gate_source_sha256"] = _sha256(Path(__file__))
    payload["evaluation_scope"] = (
        "CALIBRATION_ONLY_STATIC_PERCEPTION"
        if args.require_static_perception_audit
        else "CAPTURE_DECLARED_MODE"
    )
    payload["inputs"] = {
        "datasets": [
            {
                "dataset_root": str(root),
                "episode_transitions": str(transitions_path),
                "episode_transitions_sha256": _sha256(transitions_path),
                "transition_metrics": str(root / "transition_metrics.json"),
                "transition_metrics_sha256": _sha256(
                    root / "transition_metrics.json"
                ),
                "supervision_frames": str(supervision_path),
                "supervision_frames_sha256": _sha256(supervision_path),
            }
            for root, transitions_path, supervision_path in zip(
                dataset_roots,
                transitions_paths,
                supervision_paths,
            )
        ],
        "isaac_tolerance_envelope": (
            str(args.isaac_tolerance_envelope)
            if args.isaac_tolerance_envelope
            else None
        ),
        "isaac_tolerance_envelope_sha256": (
            _sha256(args.isaac_tolerance_envelope)
            if args.isaac_tolerance_envelope
            else None
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {key: value for key, value in payload.items() if key != "matches"}
    print(json.dumps(summary, sort_keys=True))
    return gate_exit_code(payload)


if __name__ == "__main__":
    raise SystemExit(main())
