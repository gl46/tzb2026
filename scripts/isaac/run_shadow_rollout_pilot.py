#!/usr/bin/env python3
"""Run limited Isaac counterfactual probes from public perceived states."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

from xh_agent.data.shadow_isaac import SHADOW_CANDIDATES


EPISODE_PATTERN = re.compile(r"isaac-s(?P<seed>\d+)-w(?P<worker>\d+)-t(?P<step>\d+)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def episode_coordinates(sample: dict[str, Any]) -> tuple[int, int, int]:
    episode_id = sample["observation"]["episode_id"]
    match = EPISODE_PATTERN.fullmatch(episode_id)
    if match is None:
        raise ValueError(f"unsupported Pilot episode id: {episode_id}")
    return tuple(int(match.group(name)) for name in ("seed", "worker", "step"))


def select_public_states(
    samples: list[dict[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    candidates = [
        sample
        for sample in samples
        if len(sample["observation"]["perception_tracks"]) >= 6
    ]
    candidates.sort(key=episode_coordinates)
    selected: list[dict[str, Any]] = []
    used_seeds: set[int] = set()
    for sample in candidates:
        seed, _, _ = episode_coordinates(sample)
        if seed not in used_seeds:
            selected.append(sample)
            used_seeds.add(seed)
            if len(selected) == count:
                return selected
    used_ids = {sample["sample_id"] for sample in selected}
    selected.extend(
        sample
        for sample in candidates
        if sample["sample_id"] not in used_ids
    )
    if len(selected) < count:
        raise ValueError(
            f"only {len(selected)} public states have at least six tracks"
        )
    return selected[:count]


def public_tracks(sample: dict[str, Any]) -> list[dict[str, Any]]:
    tracks = sorted(
        sample["observation"]["perception_tracks"],
        key=lambda item: (-float(item["confidence"]), item["track_id"]),
    )[:6]
    tracks.sort(
        key=lambda item: (
            float(item["pose_xyzquat"][0]),
            float(item["pose_xyzquat"][1]),
            item["track_id"],
        )
    )
    return tracks


def build_estimated_scene(
    template_sdf: Path,
    output_sdf: Path,
    output_supervision: Path,
    sample: dict[str, Any],
) -> dict[str, Any]:
    tracks = public_tracks(sample)
    tree = ET.parse(template_sdf)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise ValueError("shadow template has no SDF world")
    cylinders = [
        model
        for model in world.findall("model")
        if str(model.get("name", "")).startswith("cylinder_")
    ]
    if len(cylinders) < 6:
        raise ValueError("shadow template has fewer than six cylinders")
    insertion_index = min(list(world).index(model) for model in cylinders)
    templates = [copy.deepcopy(model) for model in cylinders[:6]]
    for model in cylinders:
        world.remove(model)
    objects = []
    for index, (model, track) in enumerate(zip(templates, tracks), start=1):
        name = f"cylinder_{index:02d}"
        model.set("name", name)
        pose = model.find("pose")
        if pose is None:
            pose = ET.Element("pose")
            model.insert(0, pose)
        xyz = [float(value) for value in track["pose_xyzquat"][:3]]
        pose.text = " ".join(f"{value:.9f}" for value in [*xyz, 0.0, 0.0, 0.0])
        world.insert(insertion_index + index - 1, model)
        objects.append(
            {
                "actual_sim_entity_id": name,
                "estimated_from_public_track_id": track["track_id"],
                "estimated_pose_world_xyz": xyz,
                "confidence": float(track["confidence"]),
            }
        )
    output_sdf.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_sdf, encoding="utf-8", xml_declaration=True)
    seed, _, _ = episode_coordinates(sample)
    supervision = {
        "scene_id": "IndustrialCylinderBenchmarkV1",
        "seed": seed,
        "split": "shadow_eval",
        "part_count": 6,
        "simulator_supervision": {
            "training_and_evaluation_only": True,
            "policy_input": False,
            "source": "PUBLIC_PERCEPTION_RECONSTRUCTION",
            "objects": objects,
        },
    }
    output_supervision.write_text(
        json.dumps(supervision, indent=2, sort_keys=True) + "\n"
    )
    return {
        "estimated_objects": objects,
        "sdf_sha256": sha256(output_sdf),
        "supervision_sha256": sha256(output_supervision),
        "template_sdf_sha256": sha256(template_sdf),
    }


def minimum_assignment_errors(
    estimated_xyz: list[list[float]],
    truth_xyz: list[list[float]],
) -> list[float]:
    if not estimated_xyz or len(estimated_xyz) > len(truth_xyz):
        raise ValueError("assignment requires 1..N estimates for N truths")
    distances = [
        [
            math.dist(tuple(estimate), tuple(truth))
            for truth in truth_xyz
        ]
        for estimate in estimated_xyz
    ]

    @lru_cache(maxsize=None)
    def solve(index: int, mask: int) -> tuple[float, tuple[float, ...]]:
        if index == len(estimated_xyz):
            return 0.0, ()
        best: tuple[float, tuple[float, ...]] | None = None
        for truth_index, distance in enumerate(distances[index]):
            if mask & (1 << truth_index):
                continue
            tail_cost, tail_errors = solve(
                index + 1,
                mask | (1 << truth_index),
            )
            candidate = (distance + tail_cost, (distance, *tail_errors))
            if best is None or candidate[0] < best[0]:
                best = candidate
        assert best is not None
        return best

    return list(solve(0, 0)[1])


def load_truth(
    data_root: Path,
    sample: dict[str, Any],
) -> list[list[float]]:
    seed, worker, step = episode_coordinates(sample)
    pair_start = seed if seed % 2 == 0 else seed - 1
    path = (
        data_root
        / "raw"
        / f"seeds-{pair_start}-{pair_start + 1}"
        / f"worker{worker}"
        / "output"
        / "supervision_frames.jsonl"
    )
    if not path.is_file():
        raise FileNotFoundError(path)
    lines = path.read_text().splitlines()
    if step >= len(lines):
        raise ValueError(f"truth step {step} absent from {path}")
    payload = json.loads(lines[step])
    poses = payload["perfect_object_poses_world_xyzw"]
    return [list(map(float, poses[name][:3])) for name in sorted(poses)]


def quarantine(run_root: Path, attempt: int) -> Path:
    quarantine_root = run_root.parent / "quarantine"
    quarantine_root.mkdir(exist_ok=True)
    candidate = quarantine_root / f"{run_root.name}-attempt-{attempt:02d}"
    while candidate.exists():
        attempt += 1
        candidate = quarantine_root / f"{run_root.name}-attempt-{attempt:02d}"
    run_root.rename(candidate)
    return candidate


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return float(ordered[index])


def rank_candidates(profiles: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(
        profiles,
        key=lambda item: (
            bool(item["public_visibility_predicate"]),
            int(
                item["semantic_pixel_counts"].get(
                    "industrial_cylinder",
                    0,
                )
            ),
            -float(item["rollout_latency_s"]),
            item["candidate"],
        ),
        reverse=True,
    )
    return [str(item["candidate"]) for item in ranked]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    parser.add_argument("--state-count", type=int, default=10)
    parser.add_argument("--frames-per-candidate", type=int, default=4)
    parser.add_argument("--warmup-frames", type=int, default=3)
    parser.add_argument("--settle-s", type=float, default=120.0)
    parser.add_argument("--max-attempts", type=int, default=6)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.state_count != 10:
        parser.error("the formal shadow pilot requires exactly ten states")
    if args.frames_per_candidate < 2:
        parser.error("--frames-per-candidate must be at least two")
    samples = [
        json.loads(line)
        for line in args.dataset.read_text().splitlines()
        if line.strip()
    ]
    states = select_public_states(samples, args.state_count)
    source_dir = args.source_root / "shadow-pilot-v1"
    source_dir.mkdir(parents=True, exist_ok=True)
    prepared = []
    for index, sample in enumerate(states):
        seed, worker, step = episode_coordinates(sample)
        sdf_path = source_dir / f"state-{index:02d}.sdf"
        supervision_path = source_dir / f"state-{index:02d}.supervision.json"
        scene = build_estimated_scene(
            args.source_root / f"scene-{seed}.sdf",
            sdf_path,
            supervision_path,
            sample,
        )
        truth = load_truth(args.data_root, sample)
        estimated = [
            list(map(float, item["estimated_pose_world_xyz"]))
            for item in scene["estimated_objects"]
        ]
        initialization_errors = minimum_assignment_errors(estimated, truth)
        prepared.append(
            {
                "state_index": index,
                "sample_id": sample["sample_id"],
                "episode_id": sample["observation"]["episode_id"],
                "seed": seed,
                "worker": worker,
                "step": step,
                "sdf_relative": str(sdf_path.relative_to(args.source_root)),
                "supervision_relative": str(
                    supervision_path.relative_to(args.source_root)
                ),
                "public_joint_position": sample["observation"]["joint_position"],
                "public_track_count": len(
                    sample["observation"]["perception_tracks"]
                ),
                "selected_public_track_count": 6,
                "scene_initialization_errors_m": initialization_errors,
                "scene_initialization_error_mean_m": statistics.fmean(
                    initialization_errors
                ),
                "scene_initialization_error_max_m": max(
                    initialization_errors
                ),
                "original_coarse_intent": sample["coarse_intent"][
                    "skill_type"
                ],
                "public_failure_type": sample["observation"][
                    "failure_context"
                ]["failure_type"],
                **scene,
            }
        )
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "prepared-states.json").write_text(
        json.dumps(prepared, indent=2, sort_keys=True) + "\n"
    )
    if args.prepare_only:
        print(json.dumps({"status": "PREPARED", "states": len(prepared)}))
        return 0

    batch_roots = []
    for batch_index in range(0, len(prepared), 2):
        pair = prepared[batch_index : batch_index + 2]
        run_root = args.output_root / f"batch-{batch_index // 2:02d}"
        passed = False
        for attempt in range(1, args.max_attempts + 1):
            if run_root.exists():
                quarantine(run_root, attempt)
            time.sleep(args.settle_s)
            command = [
                "python3",
                str(
                    args.project_root
                    / "scripts"
                    / "run_isaac_m1b_dual_benchmark.py"
                ),
                "--project-root",
                str(args.project_root),
                "--source-root",
                str(args.source_root),
                "--output",
                str(run_root),
                "--frames",
                str(args.frames_per_candidate * len(SHADOW_CANDIDATES)),
                "--warmup-frames",
                str(args.warmup_frames),
                "--shadow-rollout",
                "--shadow-frames-per-candidate",
                str(args.frames_per_candidate),
                "--container-prefix",
                f"m2a-shadow-b{batch_index // 2:02d}-a{attempt}",
            ]
            for state in pair:
                command.extend(["--worker-sdf", state["sdf_relative"]])
            for state in pair:
                command.extend(
                    ["--worker-supervision", state["supervision_relative"]]
                )
            for state in pair:
                command.extend(
                    [
                        "--worker-initial-joint-position",
                        ",".join(
                            str(value)
                            for value in state["public_joint_position"]
                        ),
                    ]
                )
            completed = subprocess.run(command, check=False)
            if completed.returncode == 0:
                passed = True
                break
        if not passed:
            raise RuntimeError(f"shadow batch {batch_index // 2} exhausted retries")
        batch_roots.append(run_root)

    state_reports = []
    latencies = []
    for batch_index, run_root in enumerate(batch_roots):
        for worker_id in range(2):
            state = prepared[batch_index * 2 + worker_id]
            metrics = json.loads(
                (
                    run_root
                    / f"worker{worker_id}"
                    / "output"
                    / "metrics.json"
                ).read_text()
            )
            profiles = metrics["shadow_counterfactual"]["profiles"]
            ranking = rank_candidates(profiles)
            latencies.extend(
                float(profile["rollout_latency_s"]) for profile in profiles
            )
            selected_skill = (
                "REOBSERVE"
                if ranking[0] == "reobserve_hold"
                else "APPROACH"
            )
            state_reports.append(
                {
                    **state,
                    "profiles": profiles,
                    "ranking": ranking,
                    "selected_candidate": ranking[0],
                    "selected_candidate_coarse_skill": selected_skill,
                    "coarse_intent_consistent": (
                        selected_skill == state["original_coarse_intent"]
                    ),
                    "main_execution_result_consistency": None,
                    "main_public_visibility_predicate": True,
                    "selected_public_visibility_predicate": next(
                        profile["public_visibility_predicate"]
                        for profile in profiles
                        if profile["candidate"] == ranking[0]
                    ),
                }
            )
    quarantine_root = args.output_root / "quarantine"
    quarantine_count = (
        sum(path.is_dir() for path in quarantine_root.iterdir())
        if quarantine_root.is_dir()
        else 0
    )
    initialization_means = [
        state["scene_initialization_error_mean_m"] for state in state_reports
    ]
    report = {
        "schema_version": "M2AShadowIsaacPilotV1",
        "status": "OFFLINE_COUNTERFACTUAL_TOOL_ONLY",
        "online_suitable": False,
        "states": len(state_reports),
        "candidates_per_state": len(SHADOW_CANDIDATES),
        "rollouts": len(state_reports) * len(SHADOW_CANDIDATES),
        "candidate_profiles": list(SHADOW_CANDIDATES),
        "scene_initialization_error_mean_m": statistics.fmean(
            initialization_means
        ),
        "scene_initialization_error_max_m": max(
            state["scene_initialization_error_max_m"]
            for state in state_reports
        ),
        "rollout_latency_s_p50": statistics.median(latencies),
        "rollout_latency_s_p90": percentile(latencies, 0.90),
        "coarse_intent_consistency_rate": sum(
            state["coarse_intent_consistent"] for state in state_reports
        )
        / len(state_reports),
        "infrastructure_attempts_quarantined": quarantine_count,
        "collision_evidence_available": False,
        "task_success_evidence_available": False,
        "main_execution_result_consistency_available": False,
        "privileged_truth_policy_input": False,
        "privileged_truth_offline_initialization_evaluation": True,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "model_action_mapping_used": False,
        "training_eligible": False,
        "state_reports": state_reports,
        "limitations": [
            "Candidate success is limited to a public visibility predicate; task success is unavailable.",
            "The current Isaac runner does not expose authoritative collision events, so collision is null.",
            "Main-environment task-success consistency is unavailable for the articulation Pilot.",
            "Candidates are explicit joint-space physics probes, not learned action mappings or grasp plans.",
            "Startup and rollout latency make this tool unsuitable for online control.",
        ],
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.report_md.write_text(
        "\n".join(
            [
                "# M2A S6 Shadow Isaac pilot",
                "",
                "- status: **OFFLINE_COUNTERFACTUAL_TOOL_ONLY**",
                f"- perceived states: {report['states']}",
                f"- physical rollouts: {report['rollouts']}",
                "- initialization source: public tracks + public robot state",
                "- privileged truth policy input: false",
                f"- initialization error mean/max: "
                f"{report['scene_initialization_error_mean_m']:.6f}/"
                f"{report['scene_initialization_error_max_m']:.6f} m",
                f"- rollout latency p50/p90: "
                f"{report['rollout_latency_s_p50']:.3f}/"
                f"{report['rollout_latency_s_p90']:.3f} s",
                f"- infrastructure attempts quarantined: {quarantine_count}",
                "- collision/task-success evidence: unavailable",
                "- online suitability: false",
                "",
                "The three candidates are explicit evaluation-only Panda "
                "joint-space probes. They are not a model action mapping and "
                "cannot replace the QRM/B0 control selection path.",
                "",
            ]
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
