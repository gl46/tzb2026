#!/usr/bin/env python3
"""Pre-register M2C S3 failure-rich collection without new model labels."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
from typing import Any

from generate_industrial_scenes import ORIENTATIONS, render
from m2b.build_dataset_v2 import scene_split
from m2c.build_headroom_domain import (
    DATASET_VERSION,
    PROJECT,
    canonical_sha256,
    sha256_bytes,
    sha256_file,
)
from m2c.derive_blocker_probe import UPSTREAM_B0_PROBE_SHA256


DEFAULT_SEED_START = 10000
DEFAULT_SCENE_COUNT = 150
ACCEPTED_TARGET_PER_FAILURE_PER_WORKER = 25
MANDATORY_FAILURES = ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
FULL_FAILURE_MINIMUM = 100
FULL_RECOVERY_MINIMUM = 50
REMOTE_SOURCE_ROOT = "/var/tmp/xh-data/isaac-industrial/m2c/s3-source-v1"
REMOTE_OUTPUT_ROOT = "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1"
BASE_DATASET = PROJECT / "artifacts/m2b/dataset-v2.jsonl"
BASE_REPORT = PROJECT / "reports/m2b-s2-dataset-v2.json"
S2_REPORT = PROJECT / "reports/m2c-s2-exploration-v4.json"
TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
URDF = PROJECT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"


def _base_counts() -> tuple[dict[str, int], dict[str, int]]:
    report = json.loads(BASE_REPORT.read_text())
    return (
        {failure: int(report["failure_counts"][failure]) for failure in MANDATORY_FAILURES},
        {
            failure: int(report["successful_recovery_counts"][failure])
            for failure in MANDATORY_FAILURES
        },
    )


def _fourth_class_receipt() -> dict[str, object]:
    report = json.loads(S2_REPORT.read_text())
    evidence = report["existence_proof_executions"]
    return {
        "failure_type": "PATH_BLOCKED",
        "collection_role": "RAW_EVALUATOR_EVIDENCE_ONLY",
        "failure_observations": len(report["b0_executions"]),
        "successful_recoveries": sum(item["strict_complete_existence_proof"] for item in evidence),
        "source_report": "reports/m2c-s2-exploration-v4.json",
        "source_report_sha256": sha256_file(S2_REPORT),
        "evidence": [
            {
                "scene_seed": int(item["scene_seed"]),
                "strict_complete_existence_proof": bool(item["strict_complete_existence_proof"]),
                "evidence_path": str(item["evidence_path"]),
                "evidence_sha256": str(item["evidence_sha256"]),
            }
            for item in evidence
        ],
        "model_training_eligible": False,
        "new_skill_label_created": False,
        "human_adr_required_before_model_label_or_q_b": True,
    }


def generate_plan(
    *,
    template_path: Path,
    urdf_path: Path,
    output_root: Path,
    seed_start: int = DEFAULT_SEED_START,
    scene_count: int = DEFAULT_SCENE_COUNT,
) -> dict[str, Any]:
    if scene_count != DEFAULT_SCENE_COUNT:
        raise ValueError(f"scene_count is frozen at {DEFAULT_SCENE_COUNT} for S3")
    if seed_start < 0:
        raise ValueError("seed_start must be nonnegative")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration: {output_root}")
    if sha256_file(BASE_DATASET) != (
        "c24e34493ba2226c1aa691c1b1c43993fbecdff5ad74b291e08c4913efc71362"
    ):
        raise ValueError("frozen M2B Dataset V2 hash mismatch")
    if sha256_file(urdf_path) != (
        "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
    ):
        raise ValueError("frozen Panda URDF hash mismatch")

    template = template_path.read_text(encoding="utf-8")
    generated: list[tuple[int, bytes, bytes, dict[str, object]]] = []
    for seed in range(seed_start, seed_start + scene_count):
        scene, supervision = render(
            template,
            seed,
            orientations=ORIENTATIONS,
        )
        scene_bytes = scene.encode()
        supervision_bytes = (json.dumps(supervision, indent=2, sort_keys=True) + "\n").encode()
        generated.append((seed, scene_bytes, supervision_bytes, supervision))

    output_root.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(urdf_path, output_root / "panda_controlled.urdf")
    records: list[dict[str, object]] = []
    for seed, scene_bytes, supervision_bytes, supervision in generated:
        sdf = output_root / f"scene-{seed}.sdf"
        supervision_path = output_root / f"scene-{seed}.supervision.json"
        sdf.write_bytes(scene_bytes)
        supervision_path.write_bytes(supervision_bytes)
        records.append(
            {
                "scene_seed": seed,
                "worker_id": seed % 2,
                "generator_split": str(supervision["split"]),
                "dataset_group_split": scene_split(seed),
                "part_count": int(supervision["part_count"]),
                "sdf": str(sdf.resolve()),
                "sdf_sha256": sha256_bytes(scene_bytes),
                "supervision": str(supervision_path.resolve()),
                "supervision_sha256": sha256_bytes(supervision_bytes),
                "outcome_observed_during_selection": False,
            }
        )

    workers = []
    for worker_id in (0, 1):
        seeds = [int(item["scene_seed"]) for item in records if item["worker_id"] == worker_id]
        workers.append(
            {
                "worker_id": worker_id,
                "gpu": worker_id,
                "scene_seeds": seeds,
                "scene_count": len(seeds),
                "failures": list(MANDATORY_FAILURES),
                "accepted_target_per_failure": (ACCEPTED_TARGET_PER_FAILURE_PER_WORKER),
                "output_root": f"{REMOTE_OUTPUT_ROOT}/worker{worker_id}",
                "container_prefix": f"m2c-s3-v1-g{worker_id}",
            }
        )

    base_failures, base_recoveries = _base_counts()
    planned_additions = {
        failure: ACCEPTED_TARGET_PER_FAILURE_PER_WORKER * len(workers)
        for failure in MANDATORY_FAILURES
    }
    projected_failures = {
        failure: base_failures[failure] + planned_additions[failure]
        for failure in MANDATORY_FAILURES
    }
    projected_recoveries = {
        failure: base_recoveries[failure] + planned_additions[failure]
        for failure in MANDATORY_FAILURES
    }
    dataset_splits = Counter(str(record["dataset_group_split"]) for record in records)

    manifest: dict[str, Any] = {
        "schema_version": "M2CS3CollectionPlanV1",
        "status": "PREREGISTERED_NOT_LAUNCHED",
        "dataset_version": DATASET_VERSION,
        "preregistration_timing": {
            "date_asia_shanghai": "2026-08-12",
            "written_before_any_s3_collection_execution": True,
            "s2_results_observed": True,
        },
        "plan_builder": "scripts/m2c/build_s3_collection_plan.py",
        "plan_builder_sha256": sha256_file(PROJECT / "scripts/m2c/build_s3_collection_plan.py"),
        "source_protocol": {
            "source_generator": "scripts/generate_industrial_scenes.py",
            "source_generator_sha256": sha256_file(
                PROJECT / "scripts/generate_industrial_scenes.py"
            ),
            "template": str(template_path),
            "template_sha256": sha256_file(template_path),
            "orientation_mode": "mixed",
            "seed_range_half_open": [seed_start, seed_start + scene_count],
            "scene_count": scene_count,
            "selection_order": "ascending_seed_without_isaac_outcomes",
            "local_source_root": str(output_root.resolve()),
            "remote_source_root": REMOTE_SOURCE_ROOT,
            "urdf_sha256": sha256_file(urdf_path),
            "dataset_group_split_counts": dict(sorted(dataset_splits.items())),
        },
        "frozen_collection_runtime": {
            "worker": "scripts/m2b/run_failure_evidence_worker.py",
            "worker_sha256": sha256_file(PROJECT / "scripts/m2b/run_failure_evidence_worker.py"),
            "stage_builder": "scripts/isaac_m1b_dataset_benchmark.py",
            "stage_builder_sha256": sha256_file(PROJECT / "scripts/isaac_m1b_dataset_benchmark.py"),
            "physical_runner": "scripts/m2b/run_physical_failure_smoke.py",
            "physical_runner_sha256": sha256_file(
                PROJECT / "scripts/m2b/run_physical_failure_smoke.py"
            ),
            "physical_probe": "scripts/isaac_m1b_actuation_probe.py",
            "physical_probe_sha256": UPSTREAM_B0_PROBE_SHA256,
            "isaac_sim_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
            "isaac_sim_image_id": (
                "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
            ),
            "max_stage_attempts": 2,
            "max_failure_attempts": 2,
            "settle_s": 10,
            "gates_or_success_predicates_changed": False,
        },
        "base_dataset": {
            "path": "artifacts/m2b/dataset-v2.jsonl",
            "sha256": sha256_file(BASE_DATASET),
            "report": "reports/m2b-s2-dataset-v2.json",
            "report_sha256": sha256_file(BASE_REPORT),
            "readonly": True,
            "failure_counts": base_failures,
            "successful_recovery_counts": base_recoveries,
        },
        "coverage_gate": {
            "mandatory_failures": list(MANDATORY_FAILURES),
            "minimum_failure_count_per_class": FULL_FAILURE_MINIMUM,
            "minimum_successful_recovery_count_per_class": (FULL_RECOVERY_MINIMUM),
            "planned_accepted_additions": planned_additions,
            "projected_failure_counts_if_targets_pass": projected_failures,
            "projected_successful_recovery_counts_if_targets_pass": (projected_recoveries),
            "zero_packaging_quarantine_required": True,
            "scene_group_split_leakage_allowed": False,
        },
        "workers": workers,
        "fourth_class": _fourth_class_receipt(),
        "scenes": records,
        "outcomes_observed": False,
        "collection_launched": False,
        "q_b_training_or_evaluation_authorized": False,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }
    manifest["plan_sha256"] = canonical_sha256(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    parser.add_argument("--urdf", type=Path, default=URDF)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--scene-count", type=int, default=DEFAULT_SCENE_COUNT)
    args = parser.parse_args()
    if args.manifest.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration: {args.manifest}")
    plan = generate_plan(
        template_path=args.template,
        urdf_path=args.urdf,
        output_root=args.output_root,
        seed_start=args.seed_start,
        scene_count=args.scene_count,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": plan["status"],
                "scenes": len(plan["scenes"]),
                "plan_sha256": plan["plan_sha256"],
                "manifest": str(args.manifest),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
