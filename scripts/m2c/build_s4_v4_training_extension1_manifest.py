#!/usr/bin/env python3
"""Freeze the first outcome-blind extension of the exhausted V4 TRAIN keys.

This is offline manifest construction only.  It neither authorizes nor starts
Isaac, collection, model training, rollout, or evaluation.  Every selected
identity is disjoint from the immutable original V4 TRAIN manifest and all
older TRAIN/SMOKE, Q-A, and S6 identities.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from m2c import build_s4_v4_training_manifest as base


PROJECT = Path(__file__).resolve().parents[2]
OUTPUT = PROJECT / "configs/m2c_s4_v4_training_keys_extension1.json"
ORIGINAL_V4_TRAINING = PROJECT / "configs/m2c_s4_v4_training_keys.json"
SCHEMA_VERSION = "M2CS4V4TrainingKeyExtensionManifestV1"
TRAIN_KEY_COUNT = 36
TRAIN_SEED_RANGE = range(22_000, 25_000)
EXPECTED_SOURCE_HASHES = {
    "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md": (
        "62c14028df1ad91e4d3c4282c4775e33149292e9bcf10add2d505be8c7424689"
    ),
    "docs/decisions/ADR-0025-m2c-raw-capacity-acm-and-yield.md": (
        "6f27171d319e3f966c652ca9f8c0fe7c641f4bf420de58642869f9c9c805c3aa"
    ),
    "reports/m2c-s3-public-category-vocabulary-audit.json": (
        "7946d610b677981ac56b223067cd63fdd10ccde140ae6dccc13ffb4688b90bfa"
    ),
    "configs/m2c_s4_training_keys.json": (
        "ca2162a898853ee04600aaf9246c121ac0604754638e497d1824b159c161fd94"
    ),
    "configs/m2c_s4_v3_training_keys.json": (
        "b5a2da566f4086724e99cea1664aeeac3b91344a68b72be84bcf6c5d0ddad65c"
    ),
    "configs/m2c_s4_v4_training_keys.json": (
        "83a672f439521dc2c6263225851ec54cbd80de052af835a6590a7e02443b79c4"
    ),
    "configs/m2c_headroom_domain_v4.json": (
        "4e78c044b68b11c1d871ecb90e65c7e2dfc616c8971abb89cb9969d2d48f738b"
    ),
    "configs/m2c_s6_evaluation_keys.json": (
        "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
    ),
    "scripts/generate_industrial_scenes.py": (
        "e9f9e20106a05dbec24453ce39422d57aa212709567fb7eba7f8d9beb03cd6c5"
    ),
    "scripts/m2c/s4_scene_family.py": (
        "07361871ca695a59a12b17877eddf15c6807fdf38f4e1a7067be15a4e2060fa6"
    ),
    "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf": (
        "1eea1b34b832d858ba9a4adec775018e807061b54cb1afff19d710d848ad926d"
    ),
}


def _excluded_identities() -> tuple[set[int], set[int], set[str], dict[str, object]]:
    sources = {
        "V2_TRAIN_AND_SMOKE": base._json(base.OLD_TRAINING),  # noqa: SLF001
        "V3_TRAIN_COMPLETE": base._json(base.V3_TRAINING),  # noqa: SLF001
        "ORIGINAL_V4_TRAIN": base._json(ORIGINAL_V4_TRAINING),  # noqa: SLF001
        "V4_Q_A": base._json(base.V4_MANIFEST),  # noqa: SLF001
        "S6_EVALUATION": base._json(base.S6_MANIFEST),  # noqa: SLF001
    }
    scenes: set[int] = set()
    failures: set[int] = set()
    keys: set[str] = set()
    report: dict[str, object] = {}
    for name, payload in sources.items():
        source_scenes, source_failures, source_keys = base._identities(payload)  # noqa: SLF001
        if scenes & source_scenes or failures & source_failures or keys & source_keys:
            raise ValueError("frozen exclusion identity sources overlap")
        scenes |= source_scenes
        failures |= source_failures
        keys |= source_keys
        report[name] = {
            "scene_seed_count": len(source_scenes),
            "failure_seed_count": len(source_failures),
            "matched_key_count": len(source_keys),
            "identity_digest": base.canonical_sha256(
                {
                    "scene_seeds": sorted(source_scenes),
                    "failure_seeds": sorted(source_failures),
                    "matched_keys": sorted(source_keys),
                }
            ),
        }
    return scenes, failures, keys, report


def build_manifest() -> dict[str, Any]:
    actual_bindings = {path: base.sha256_file(PROJECT / path) for path in EXPECTED_SOURCE_HASHES}
    mismatches = {
        path: {"expected": EXPECTED_SOURCE_HASHES[path], "actual": actual}
        for path, actual in actual_bindings.items()
        if actual != EXPECTED_SOURCE_HASHES[path]
    }
    if mismatches:
        raise ValueError(f"frozen V4 extension source hash mismatch: {mismatches}")
    category_audit = base._json(base.CATEGORY_AUDIT)  # noqa: SLF001
    if (
        category_audit.get("status") != "PASS_CATEGORY_CARRIES_DECLARED_ATTRIBUTE_VOCABULARY"
        or category_audit.get("task_spec_target_track_id_read") is not False
        or category_audit.get("teacher_used") is not False
        or category_audit.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("ADR-0024 category-vocabulary prerequisite is not passing")

    excluded_scenes, excluded_failures, excluded_keys, exclusions = _excluded_identities()
    template = base.read_regular_file_once(base.TEMPLATE).decode("utf-8")
    records: list[dict[str, Any]] = []
    for seed in TRAIN_SEED_RANGE:
        if base.split(seed) != "train":
            continue
        record = base._key_record(seed, len(records), template)  # noqa: SLF001
        if record is None:
            continue
        if (
            record["scene_seed"] in excluded_scenes
            or record["failure_seed"] in excluded_failures
            or record["matched_key"] in excluded_keys
        ):
            raise AssertionError("V4 extension key overlaps a frozen excluded identity")
        records.append(record)
        if len(records) == TRAIN_KEY_COUNT:
            break
    if len(records) != TRAIN_KEY_COUNT:
        raise ValueError("V4 extension seed range produced fewer than 36 admissible keys")
    for field in ("scene_seed", "failure_seed", "matched_key"):
        values = [record[field] for record in records]
        if len(values) != len(set(values)):
            raise AssertionError(f"V4 extension repeats {field}")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_TRAIN_ONLY_BEFORE_ANY_SELECTED_KEY_COLLECTION",
        "written_date_asia_shanghai": "2026-08-15",
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "candidate_count_bound": 8,
        "pointer_class_count": 9,
        "declared_target_attribute": base.DECLARED_TARGET_ATTRIBUTE,
        "recapture_policy": "NONE",
        "training_keys": records,
        "physical_prerequisite_smoke_keys": [],
        "smoke_collection_authorized": False,
        "evaluation_collection_authorized": False,
        "train_only": True,
        "selection_uses_rollout_outcomes": False,
        "any_selected_key_collection_observed_before_freeze": False,
        "selection_implementation": {
            "path": str(Path(__file__).resolve().relative_to(PROJECT)),
            "sha256": base.sha256_file(Path(__file__).resolve()),
        },
        "candidate_implementation": {
            "path": str(base.PUBLIC_TRACKS_V4.relative_to(PROJECT)),
            "sha256": base.sha256_file(base.PUBLIC_TRACKS_V4),
        },
        "selection_protocol": {
            "seed_range_half_open": [TRAIN_SEED_RANGE.start, TRAIN_SEED_RANGE.stop],
            "candidate_order": (
                "ascending never-executed seed, generator split=train, exactly six "
                "objects, accepted V4 offline geometry gates"
            ),
            "training_key_count": TRAIN_KEY_COUNT,
        },
        "source_bindings": actual_bindings,
        "accepted_contract_commits": {
            "adr_0024": "48676d0a59c8adc4e759f9ee21566d97b9a44363",
            "adr_0025": "abf66b1084e3820a327c29cb79ebf68af0252fd0",
            "public_track_associator_v2_and_raw_capacity": (
                "e7d0564cd603cc2b020748aef0534ac0f2a5e5ab"
            ),
            "public_track_candidate_v4": "339212e0b17db63f1e936a59f8314ca8e53bda21",
        },
        "v4_implementation_bindings": {
            str(base.PUBLIC_ASSOCIATOR_V2.relative_to(PROJECT)): base.sha256_file(
                base.PUBLIC_ASSOCIATOR_V2
            ),
            str(base.PUBLIC_TRACKS_V4.relative_to(PROJECT)): base.sha256_file(
                base.PUBLIC_TRACKS_V4
            ),
            str(base.PATH_BLOCKED_V4.relative_to(PROJECT)): base.sha256_file(base.PATH_BLOCKED_V4),
        },
        "exclusions": exclusions,
        "exclusion_contract": {
            "old_v2_train_and_smoke": True,
            "complete_v3_train": True,
            "original_v4_train": True,
            "v4_q_a": True,
            "all_s6_evaluation": True,
            "identity_dimensions": ["scene_seed", "failure_seed", "matched_key"],
            "excluded_scene_seed_count": len(excluded_scenes),
            "excluded_failure_seed_count": len(excluded_failures),
            "excluded_matched_key_count": len(excluded_keys),
            "excluded_identity_digest": base.canonical_sha256(
                {
                    "scene_seeds": sorted(excluded_scenes),
                    "failure_seeds": sorted(excluded_failures),
                    "matched_keys": sorted(excluded_keys),
                }
            ),
        },
        "layout_contract": {
            "source": "accepted M2C V4 geometry family",
            "offline_materialization_required": True,
            "exactly_six_objects_required": True,
            "anchor_xy_m": list(base.ANCHOR_XY_M),
            "anchor_jitter_x_m": list(base.ANCHOR_JITTER_X_M),
            "destination_cell": base.DESTINATION_CELL,
            "destination_cell_index": base.DESTINATION_CELL_INDEX,
            "b0_or_gate_changes": False,
        },
        "collection_executed": False,
        "training_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["training_key_digest"] = base.canonical_sha256(records)
    payload["manifest_sha256"] = base.canonical_sha256(payload)
    return payload


def manifest_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    manifest = build_manifest()
    base.write_create_only(args.output, manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "training_keys": len(manifest["training_keys"]),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
