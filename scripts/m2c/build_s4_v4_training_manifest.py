#!/usr/bin/env python3
"""Freeze 36 outcome-blind, TRAIN-only ADR-0024 V4 collection keys.

No collection, simulator launch, training, or remote access occurs here.  The
builder materializes the accepted V4 geometry offline and rejects any identity
overlap with every frozen V2 TRAIN/SMOKE, complete V3 TRAIN, V4 Q-A, or S6
evaluation key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))

from m2c.s4_scene_family import materialize_scene  # noqa: E402


OUTPUT = PROJECT / "configs/m2c_s4_v4_training_keys.json"
ADR = PROJECT / "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"
CATEGORY_AUDIT = PROJECT / "reports/m2c-s3-public-category-vocabulary-audit.json"
OLD_TRAINING = PROJECT / "configs/m2c_s4_training_keys.json"
V3_TRAINING = PROJECT / "configs/m2c_s4_v3_training_keys.json"
V4_MANIFEST = PROJECT / "configs/m2c_headroom_domain_v4.json"
S6_MANIFEST = PROJECT / "configs/m2c_s6_evaluation_keys.json"
GENERATOR = PROJECT / "scripts/generate_industrial_scenes.py"
SCENE_FAMILY = PROJECT / "scripts/m2c/s4_scene_family.py"
TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
PUBLIC_TRACKS_V4 = PROJECT / "src/xh_agent/policy/qrm_lite/public_tracks_v4.py"
PUBLIC_ASSOCIATOR_V2 = PROJECT / "src/xh_agent/perception/public_track_associator_v2.py"
PATH_BLOCKED_V4 = PROJECT / "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v4.py"
EXPECTED_SOURCE_HASHES = {
    "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md": (
        "62c14028df1ad91e4d3c4282c4775e33149292e9bcf10add2d505be8c7424689"
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
SCHEMA_VERSION = "M2CS4V4TrainingKeyManifestV1"
TRAIN_KEY_COUNT = 36
TRAIN_SEED_RANGE = range(19_000, 22_000)
ANCHOR_XY_M = (-0.110, 0.130)
ANCHOR_JITTER_X_M = (-0.005, 0.0, 0.005)
DESTINATION_CELL = "BIN_CELL_3"
DESTINATION_CELL_INDEX = 3
DECLARED_TARGET_ATTRIBUTE = "yellow"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_file(path: Path) -> str:
    return sha256_bytes(read_regular_file_once(path))


def canonical_sha256(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii"))


def split(seed: int) -> str:
    return "train" if seed % 20 < 14 else "val" if seed % 20 < 17 else "test"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(read_regular_file_once(path))
    if not isinstance(value, dict):
        raise ValueError(f"frozen input is not a JSON object: {path}")
    return value


def _identities(value: object) -> tuple[set[int], set[int], set[str]]:
    scene_seeds: set[int] = set()
    failure_seeds: set[int] = set()
    matched_keys: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            if isinstance(item.get("scene_seed"), int):
                scene_seeds.add(int(item["scene_seed"]))
            if isinstance(item.get("failure_seed"), int):
                failure_seeds.add(int(item["failure_seed"]))
            if isinstance(item.get("matched_key"), str):
                matched_keys.add(str(item["matched_key"]))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return scene_seeds, failure_seeds, matched_keys


def _excluded_identities() -> tuple[set[int], set[int], set[str], dict[str, object]]:
    sources = {
        "V2_TRAIN_AND_SMOKE": _json(OLD_TRAINING),
        "V3_TRAIN_COMPLETE": _json(V3_TRAINING),
        "V4_Q_A": _json(V4_MANIFEST),
        "S6_EVALUATION": _json(S6_MANIFEST),
    }
    scenes: set[int] = set()
    failures: set[int] = set()
    keys: set[str] = set()
    report: dict[str, object] = {}
    for name, payload in sources.items():
        source_scenes, source_failures, source_keys = _identities(payload)
        scenes |= source_scenes
        failures |= source_failures
        keys |= source_keys
        report[name] = {
            "scene_seed_count": len(source_scenes),
            "failure_seed_count": len(source_failures),
            "matched_key_count": len(source_keys),
            "identity_digest": canonical_sha256(
                {
                    "scene_seeds": sorted(source_scenes),
                    "failure_seeds": sorted(source_failures),
                    "matched_keys": sorted(source_keys),
                }
            ),
        }
    return scenes, failures, keys, report


def _key_record(seed: int, ordinal: int, template: str) -> dict[str, Any] | None:
    if split(seed) != "train":
        raise ValueError(f"V4 TRAIN seed {seed} is not generator split train")
    anchor_x = ANCHOR_XY_M[0] + ANCHOR_JITTER_X_M[ordinal % 3]
    materialized = materialize_scene(template, seed, (anchor_x, ANCHOR_XY_M[1]))
    if materialized is None:
        return None
    _, _, receipt = materialized
    if receipt["split"] != "train" or receipt["part_count"] != 6:
        raise ValueError(f"V4 TRAIN seed {seed} failed offline geometry contract")
    identity = {
        "scene_seed": seed,
        "failure_seed": seed * 10 + 7,
        "split": "train",
        "role": "TRAIN",
        "failure_type": "PATH_BLOCKED",
        "layout_family": "M2C_V4_ACCEPTED_BLOCKER_GEOMETRY",
        "anchor_xy_m": [anchor_x, ANCHOR_XY_M[1]],
        "blocker_distance_m": 0.040,
        "retained_blocker_distance_m": 0.062,
        "blocker_selector_policy_input": ("visual_color=red,top_z_band=0.02m,world_x=max"),
        "target_selector_policy_input": ("visual_color=yellow,top_z_band=0.02m,world_x=max"),
        "declared_target_attribute": DECLARED_TARGET_ATTRIBUTE,
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "candidate_count_bound": 8,
        "recapture_policy": "NONE",
        "destination_cell": DESTINATION_CELL,
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
        "previously_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return {**identity, "matched_key": "m2c-s4-v4-train-" + canonical_sha256(identity)}


def build_manifest() -> dict[str, Any]:
    actual_bindings = {path: sha256_file(PROJECT / path) for path in EXPECTED_SOURCE_HASHES}
    mismatches = {
        path: {"expected": EXPECTED_SOURCE_HASHES[path], "actual": actual}
        for path, actual in actual_bindings.items()
        if actual != EXPECTED_SOURCE_HASHES[path]
    }
    if mismatches:
        raise ValueError(f"frozen V4 manifest source hash mismatch: {mismatches}")
    category_audit = _json(CATEGORY_AUDIT)
    if (
        category_audit.get("status") != "PASS_CATEGORY_CARRIES_DECLARED_ATTRIBUTE_VOCABULARY"
        or category_audit.get("task_spec_target_track_id_read") is not False
        or category_audit.get("teacher_used") is not False
        or category_audit.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("ADR-0024 category-vocabulary prerequisite is not passing")

    excluded_scenes, excluded_failures, excluded_keys, exclusions = _excluded_identities()
    template = read_regular_file_once(TEMPLATE).decode("utf-8")
    records: list[dict[str, Any]] = []
    for seed in TRAIN_SEED_RANGE:
        if split(seed) != "train":
            continue
        record = _key_record(seed, len(records), template)
        if record is None:
            continue
        if (
            record["scene_seed"] in excluded_scenes
            or record["failure_seed"] in excluded_failures
            or record["matched_key"] in excluded_keys
        ):
            raise AssertionError("V4 TRAIN key overlaps a frozen excluded identity")
        records.append(record)
        if len(records) == TRAIN_KEY_COUNT:
            break
    if len(records) != TRAIN_KEY_COUNT:
        raise ValueError("V4 seed range produced fewer than 36 admissible TRAIN keys")
    scenes = [record["scene_seed"] for record in records]
    failures = [record["failure_seed"] for record in records]
    keys = [record["matched_key"] for record in records]
    if (
        len(scenes) != len(set(scenes))
        or len(failures) != len(set(failures))
        or len(keys) != len(set(keys))
    ):
        raise AssertionError("V4 TRAIN identities are not internally unique")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_TRAIN_ONLY_BEFORE_ANY_V4_COLLECTION",
        "written_date_asia_shanghai": "2026-08-13",
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "candidate_count_bound": 8,
        "pointer_class_count": 9,
        "declared_target_attribute": DECLARED_TARGET_ATTRIBUTE,
        "recapture_policy": "NONE",
        "training_keys": records,
        "physical_prerequisite_smoke_keys": [],
        "smoke_collection_authorized": False,
        "evaluation_collection_authorized": False,
        "train_only": True,
        "selection_uses_rollout_outcomes": False,
        "any_v4_collection_observed_before_freeze": False,
        "selection_implementation": {
            "path": str(Path(__file__).resolve().relative_to(PROJECT)),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "candidate_implementation": {
            "path": str(PUBLIC_TRACKS_V4.relative_to(PROJECT)),
            "sha256": sha256_file(PUBLIC_TRACKS_V4),
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
        "accepted_implementation_commit": ("abc08e63de85263f781b458ac50b3644f806ec6c"),
        "v4_implementation_bindings": {
            str(PUBLIC_ASSOCIATOR_V2.relative_to(PROJECT)): sha256_file(PUBLIC_ASSOCIATOR_V2),
            str(PUBLIC_TRACKS_V4.relative_to(PROJECT)): sha256_file(PUBLIC_TRACKS_V4),
            str(PATH_BLOCKED_V4.relative_to(PROJECT)): sha256_file(PATH_BLOCKED_V4),
        },
        "exclusions": exclusions,
        "exclusion_contract": {
            "old_v2_train_and_smoke": True,
            "complete_v3_train": True,
            "v4_q_a": True,
            "all_s6_evaluation": True,
            "identity_dimensions": ["scene_seed", "failure_seed", "matched_key"],
            "excluded_scene_seed_count": len(excluded_scenes),
            "excluded_failure_seed_count": len(excluded_failures),
            "excluded_matched_key_count": len(excluded_keys),
            "excluded_identity_digest": canonical_sha256(
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
            "anchor_xy_m": list(ANCHOR_XY_M),
            "anchor_jitter_x_m": list(ANCHOR_JITTER_X_M),
            "destination_cell": DESTINATION_CELL,
            "destination_cell_index": DESTINATION_CELL_INDEX,
            "b0_or_gate_changes": False,
        },
        "collection_executed": False,
        "training_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["training_key_digest"] = canonical_sha256(records)
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("failed to publish V4 training manifest")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    manifest = build_manifest()
    write_create_only(args.output, manifest)
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
