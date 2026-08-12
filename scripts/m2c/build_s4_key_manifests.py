#!/usr/bin/env python3
"""Freeze disjoint M2C S4 train/smoke and S6 evaluation key identities.

This script performs no Isaac execution and consumes no rollout outcome.  It
binds deterministic scene/failure seeds, roles, and the already accepted V4
geometry family before any S4 training-data collection or S6 evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from m2c.s4_scene_family import materialize_scene


PROJECT = Path(__file__).resolve().parents[2]
KEY_BUILDER = Path(__file__).resolve()
V4_MANIFEST = PROJECT / "configs/m2c_headroom_domain_v4.json"
V4_MANIFEST_SHA256 = "4e78c044b68b11c1d871ecb90e65c7e2dfc616c8971abb89cb9969d2d48f738b"
S6_PREREGISTRATION = PROJECT / "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md"
S6_PREREGISTRATION_SHA256 = "01786e2c40d18a82c75a32d20dce4755f7ee9f0f00b05b623f8bdd7672462dae"
HUMAN_ADR = PROJECT / "docs/decisions/ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md"
HUMAN_ADR_SHA256 = "5a0aecc1c31a1aca7a48150ec0792df13aa041c5e0802382b9c1432a012598c3"
GENERATOR = PROJECT / "scripts/generate_industrial_scenes.py"
GENERATOR_SHA256 = "e9f9e20106a05dbec24453ce39422d57aa212709567fb7eba7f8d9beb03cd6c5"
V4_BUILDER = PROJECT / "scripts/m2c/build_final_headroom_domain.py"
V4_BUILDER_SHA256 = "cbfa3e88cd184138b91681db53a124646d10b4b90bf1b470866a83d66dd3da7a"
SCENE_FAMILY = PROJECT / "scripts/m2c/s4_scene_family.py"
SCENE_FAMILY_SHA256 = "07361871ca695a59a12b17877eddf15c6807fdf38f4e1a7067be15a4e2060fa6"
FREE_GAP = PROJECT / "src/xh_agent/grasp/free_gap.py"
FREE_GAP_SHA256 = "2d85ddf87611d8593f4a4abc76d1e34a6aed2e805437c7a55f7b4f77184a5cd0"
TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
TEMPLATE_SHA256 = "1eea1b34b832d858ba9a4adec775018e807061b54cb1afff19d710d848ad926d"
SCRIPTED_BIN_CELL = "BIN_CELL_3"
SCRIPTED_BIN_CELL_INDEX = 3
ANCHOR_XY_M = (-0.110, 0.130)
ANCHOR_JITTER_X_M = (-0.005, 0.0, 0.005)
TRAIN_KEY_COUNT = 36
SMOKE_KEY_COUNT = 3
S6_KEY_COUNT = 30
TRAIN_SEED_RANGE = range(12_000, 15_000)
SMOKE_SEED_RANGE = range(15_000, 16_000)
S6_SEED_RANGE = range(20_000, 24_000)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(payload: object) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def split(seed: int) -> Literal["train", "val", "test"]:
    return "train" if seed % 20 < 14 else "val" if seed % 20 < 17 else "test"


def key_record(
    seed: int,
    *,
    role: Literal["TRAIN", "SMOKE", "EVALUATION"],
    ordinal: int,
    template: str,
) -> dict[str, Any] | None:
    expected_split = {
        "TRAIN": "train",
        "SMOKE": "val",
        "EVALUATION": "test",
    }[role]
    actual_split = split(seed)
    if actual_split != expected_split:
        raise ValueError(f"seed {seed}: split {actual_split} does not match role {role}")
    anchor_x = ANCHOR_XY_M[0] + ANCHOR_JITTER_X_M[ordinal % 3]
    materialized = materialize_scene(
        template,
        seed,
        (anchor_x, ANCHOR_XY_M[1]),
    )
    if materialized is None:
        return None
    _, _, receipt = materialized
    if receipt["split"] != actual_split or receipt["part_count"] != 6:
        raise AssertionError(f"seed {seed}: invalid offline materialization receipt")
    identity = {
        "scene_seed": seed,
        "failure_seed": seed * 10 + 7,
        "split": actual_split,
        "role": role,
        "failure_type": "PATH_BLOCKED",
        "layout_family": "M2C_V4_ACCEPTED_BLOCKER_GEOMETRY",
        "anchor_xy_m": [anchor_x, ANCHOR_XY_M[1]],
        "blocker_distance_m": 0.040,
        "retained_blocker_distance_m": 0.062,
        "blocker_selector_policy_input": ("visual_color=red,top_z_band=0.02m,world_x=max"),
        "target_selector_policy_input": ("visual_color=yellow,top_z_band=0.02m,world_x=max"),
        "destination_cell": SCRIPTED_BIN_CELL,
        "sdf_sha256": receipt["sdf_sha256"],
        "supervision_sha256": receipt["supervision_sha256"],
        "offline_geometry_admission": {
            "part_count": receipt["part_count"],
            "minimum_surface_gap_m": receipt["minimum_surface_gap_m"],
            "target_clearance_before_m": receipt["target_clearance_before_m"],
            "target_clearance_before_ok": receipt["target_clearance_before_ok"],
            "scripted_blocker_clearance_m": receipt["scripted_blocker_clearance_m"],
            "scripted_blocker_clearance_ok": receipt["scripted_blocker_clearance_ok"],
            "target_clearance_after_relocation_m": receipt["target_clearance_after_relocation_m"],
            "target_clearance_after_relocation_ok": receipt["target_clearance_after_relocation_ok"],
        },
        "offline_scene_materialized_during_selection": True,
        "outcome_observed_during_selection": False,
    }
    return {
        **identity,
        "matched_key": "m2c-s4-s6-" + canonical_sha256(identity),
    }


def selected_records(
    seeds: range,
    *,
    role: Literal["TRAIN", "SMOKE", "EVALUATION"],
    count: int,
    template: str,
) -> list[dict[str, Any]]:
    expected_split = {
        "TRAIN": "train",
        "SMOKE": "val",
        "EVALUATION": "test",
    }[role]
    records: list[dict[str, Any]] = []
    for seed in seeds:
        if split(seed) != expected_split:
            continue
        record = key_record(
            seed,
            role=role,
            ordinal=len(records),
            template=template,
        )
        if record is not None:
            records.append(record)
        if len(records) == count:
            break
    if len(records) != count:
        raise ValueError(
            f"seed range produced only {len(records)} admissible {role} keys; need {count}"
        )
    return records


def build_manifests() -> tuple[dict[str, Any], dict[str, Any]]:
    frozen_files = {
        str(V4_MANIFEST.relative_to(PROJECT)): V4_MANIFEST_SHA256,
        str(S6_PREREGISTRATION.relative_to(PROJECT)): S6_PREREGISTRATION_SHA256,
        str(HUMAN_ADR.relative_to(PROJECT)): HUMAN_ADR_SHA256,
        str(GENERATOR.relative_to(PROJECT)): GENERATOR_SHA256,
        str(V4_BUILDER.relative_to(PROJECT)): V4_BUILDER_SHA256,
        str(SCENE_FAMILY.relative_to(PROJECT)): SCENE_FAMILY_SHA256,
        str(FREE_GAP.relative_to(PROJECT)): FREE_GAP_SHA256,
        str(TEMPLATE.relative_to(PROJECT)): TEMPLATE_SHA256,
    }
    mismatches = {
        path: {"expected": expected, "actual": sha256_file(PROJECT / path)}
        for path, expected in frozen_files.items()
        if sha256_file(PROJECT / path) != expected
    }
    if mismatches:
        raise ValueError(f"frozen input SHA-256 mismatch: {mismatches}")

    v4 = json.loads(V4_MANIFEST.read_text())
    v4_keys = sorted(str(record["matched_key"]) for record in v4["keys"])
    v4_seeds = sorted(int(record["scene_seed"]) for record in v4["keys"])
    template = TEMPLATE.read_text(encoding="utf-8")
    train_records = selected_records(
        TRAIN_SEED_RANGE,
        role="TRAIN",
        count=TRAIN_KEY_COUNT,
        template=template,
    )
    smoke_records = selected_records(
        SMOKE_SEED_RANGE,
        role="SMOKE",
        count=SMOKE_KEY_COUNT,
        template=template,
    )
    evaluation_records = selected_records(
        S6_SEED_RANGE,
        role="EVALUATION",
        count=S6_KEY_COUNT,
        template=template,
    )

    all_records = [*train_records, *smoke_records, *evaluation_records]
    seeds = [int(record["scene_seed"]) for record in all_records]
    keys = [str(record["matched_key"]) for record in all_records]
    if len(seeds) != len(set(seeds)) or len(keys) != len(set(keys)):
        raise AssertionError("train/smoke/S6 key manifests are not disjoint")
    if set(seeds) & set(v4_seeds) or set(keys) & set(v4_keys):
        raise AssertionError("new key manifests overlap frozen V4 Q-A keys")

    shared = {
        "schema_version": "M2CKeySelectionProtocolV1",
        "status": "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION",
        "written_date_asia_shanghai": "2026-08-12",
        "selection_uses_rollout_outcomes": False,
        "selection_implementation": {
            "path": str(KEY_BUILDER.relative_to(PROJECT)),
            "sha256": sha256_file(KEY_BUILDER),
        },
        "selection_protocol": {
            "candidate_order": (
                "ascending seed, required generator split, exactly six objects, "
                "all offline accepted-family geometry gates pass"
            ),
            "training_seed_range_half_open": [
                TRAIN_SEED_RANGE.start,
                TRAIN_SEED_RANGE.stop,
            ],
            "smoke_seed_range_half_open": [
                SMOKE_SEED_RANGE.start,
                SMOKE_SEED_RANGE.stop,
            ],
            "evaluation_seed_range_half_open": [
                S6_SEED_RANGE.start,
                S6_SEED_RANGE.stop,
            ],
            "training_key_count": TRAIN_KEY_COUNT,
            "smoke_key_count": SMOKE_KEY_COUNT,
            "evaluation_key_count": S6_KEY_COUNT,
        },
        "source_bindings": frozen_files,
        "v4_excluded_scene_seeds": v4_seeds,
        "v4_excluded_matched_keys": v4_keys,
        "layout_contract": {
            "source": "accepted M2C V4 geometry family",
            "offline_materialization_required": True,
            "exactly_six_objects_required": True,
            "anchor_xy_m": list(ANCHOR_XY_M),
            "anchor_jitter_x_m": list(ANCHOR_JITTER_X_M),
            "blocker_distance_m": 0.040,
            "retained_blocker_distance_m": 0.062,
            "destination_cell": SCRIPTED_BIN_CELL,
            "destination_cell_index": SCRIPTED_BIN_CELL_INDEX,
            "object_geometry_mass_material_and_dynamics": "unchanged M2B",
            "b0_or_gate_changes": False,
        },
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    training = {
        **shared,
        "schema_version": "M2CS4TrainingAndSmokeKeyManifestV1",
        "training_keys": train_records,
        "physical_prerequisite_smoke_keys": smoke_records,
        "exclusions": {
            "all_v4_keys": True,
            "all_s6_keys": True,
            "frozen_s3_path_blocked_raw_v1": (
                "evaluator-only; contains V4 keys; zero training labels"
            ),
        },
    }
    evaluation = {
        **shared,
        "schema_version": "M2CS6FrozenEvaluationKeyManifestV1",
        "minimum_complete_matched_keys": 30,
        "evaluation_keys": evaluation_records,
        "excluded_from_all_training": True,
        "methods": [
            "B0",
            "QRM_COARSE_NO_FC",
            "QRM_COARSE_FC",
            "QRM_COARSE_FC_MLP",
        ],
    }
    training["s6_evaluation_key_digest"] = canonical_sha256(evaluation_records)
    evaluation["training_and_smoke_key_digest"] = canonical_sha256([*train_records, *smoke_records])
    training["manifest_sha256"] = canonical_sha256(training)
    evaluation["manifest_sha256"] = canonical_sha256(evaluation)
    return training, evaluation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--training-output",
        type=Path,
        default=PROJECT / "configs/m2c_s4_training_keys.json",
    )
    parser.add_argument(
        "--evaluation-output",
        type=Path,
        default=PROJECT / "configs/m2c_s6_evaluation_keys.json",
    )
    args = parser.parse_args()
    for output in (args.training_output, args.evaluation_output):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite frozen manifest: {output}")
    training, evaluation = build_manifests()
    for output, payload in (
        (args.training_output, training),
        (args.evaluation_output, evaluation),
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION",
                "training_keys": len(training["training_keys"]),
                "smoke_keys": len(training["physical_prerequisite_smoke_keys"]),
                "evaluation_keys": len(evaluation["evaluation_keys"]),
                "training_output": str(args.training_output),
                "evaluation_output": str(args.evaluation_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
