#!/usr/bin/env python3
"""Pre-register M2C's stable upright tall-cylinder headroom domain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from generate_industrial_scenes import (
    CYLINDER_RADIUS_M,
    SPAWN_CLEARANCE_M,
    TABLE_TOP_Z,
    render,
    split,
)
from m2c.build_headroom_domain import (
    BASELINE_COMMIT,
    DATASET_VERSION,
    PROJECT,
    _models,
    _pose,
    canonical_sha256,
    public_yellow_max_x_target,
    sha256_bytes,
    sha256_file,
)
from xh_agent.grasp.free_gap import select_free_gap_yaw_from_xy


TALL_TARGET_LENGTH_M = 0.12
BASELINE_CONTACT_CENTERLINE_M = 0.12
SCRIPTED_EXISTENCE_CONTACT_CENTERLINE_M = 0.10
MAXIMUM_PART_COUNT = 9
DEFAULT_SEED_START = 7000
DEFAULT_SEED_STOP = 7400
DEFAULT_KEY_COUNT = 10
V1_EXPLORATION_REPORT = PROJECT / "reports/m2c-s2-exploration-v1.json"
HEIGHT_CALIBRATION_REPORTS = (
    PROJECT / "reports/m1b-adr0016-top-contact-height-calibration.json",
    PROJECT / "reports/m1b-adr0016b-top-contact-height-calibration.json",
)


def _candidate(
    template: str,
    seed: int,
) -> tuple[bytes, bytes, dict[str, Any]] | None:
    if split(seed) != "test":
        return None
    scene, supervision = render(template, seed, orientations=("normal",))
    root = ET.fromstring(scene)
    models = _models(root)
    # The generator repeats yellow at cylinder_10.  Keeping at most nine
    # objects makes the TaskSpec target unique without using entity identity.
    if len(models) > MAXIMUM_PART_COUNT:
        return None
    target = public_yellow_max_x_target(models)
    target_name = str(target.get("name"))
    target_pose = _pose(target)
    target_xy = target_pose[:2]
    neighbors = [_pose(model)[:2] for model in models if model is not target]
    free_gap = select_free_gap_yaw_from_xy(
        target_xy,
        neighbors,
        source="M2C_V2_PREREGISTERED_SCENE_GEOMETRY_ONLY",
    )
    if not bool(free_gap["clearance_ok"]):
        return None

    # Keep the target upright and free-standing.  Only its length and the
    # corresponding table-supported centre height change.  The +40 mm length
    # moves frozen B0's H=120 mm hand pose to the previously measured H=140 mm
    # world-height regime (no contact), while the separately labelled H=100 mm
    # scripted proof returns to the measured production world hand height.
    target_pose[2] = (
        TABLE_TOP_Z + TALL_TARGET_LENGTH_M / 2.0 + SPAWN_CLEARANCE_M
    )
    target.find("pose").text = " ".join(f"{value:.9f}" for value in target_pose)
    length_nodes = target.findall("./link/collision/geometry/cylinder/length")
    length_nodes += target.findall("./link/visual/geometry/cylinder/length")
    if len(length_nodes) != 2:
        raise ValueError(f"{target_name}: expected collision and visual lengths")
    for node in length_nodes:
        node.text = f"{TALL_TARGET_LENGTH_M:.4f}"

    labels = supervision["simulator_supervision"]["objects"]
    label = next(
        item for item in labels if item["actual_sim_entity_id"] == target_name
    )
    label["position_3d_world"] = target_pose[:3]
    label["orientation_state"] = "normal"
    label["m2c_scene_geometry"] = {
        "length_m": TALL_TARGET_LENGTH_M,
        "radius_m": CYLINDER_RADIUS_M,
        "roll_rad": 0.0,
        "pitch_rad": 0.0,
        "upright_free_standing": True,
        "domain_only": True,
    }
    supervision["m2c_headroom_domain"] = {
        "schema_version": "M2CHeadroomSceneV2",
        "dataset_version": DATASET_VERSION,
        "failure_type": "EMPTY_GRASP",
        "target_selector": "visual_color=yellow,top_z_band=0.02m,world_x=max",
        "target_entity_evaluator_only": target_name,
        "baseline_contact_centerline_m": BASELINE_CONTACT_CENTERLINE_M,
        "scripted_existence_contact_centerline_m": (
            SCRIPTED_EXISTENCE_CONTACT_CENTERLINE_M
        ),
        "b0_modified": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }

    ET.indent(root, space="  ")
    sdf_bytes = (ET.tostring(root, encoding="unicode") + "\n").encode()
    supervision_bytes = (
        json.dumps(supervision, indent=2, sort_keys=True) + "\n"
    ).encode()
    record = {
        "scene_seed": seed,
        "split": "test",
        "failure_type": "EMPTY_GRASP",
        "target_entity_evaluator_only": target_name,
        "target_selector_policy_input": (
            "visual_color=yellow,top_z_band=0.02m,world_x=max"
        ),
        "part_count": len(models),
        "b0_selected_yaw_rad": float(free_gap["selected_yaw_rad"]),
        "b0_yaw_clearance_m": float(free_gap["min_clearance_m"]),
        "target_length_m": TALL_TARGET_LENGTH_M,
        "target_radius_m": CYLINDER_RADIUS_M,
        "baseline_contact_centerline_m": BASELINE_CONTACT_CENTERLINE_M,
        "scripted_existence_contact_centerline_m": (
            SCRIPTED_EXISTENCE_CONTACT_CENTERLINE_M
        ),
        "sdf_sha256": sha256_bytes(sdf_bytes),
        "supervision_sha256": sha256_bytes(supervision_bytes),
        "outcome_observed_during_selection": False,
    }
    record["matched_key"] = "m2c-headroom-v2-" + canonical_sha256(record)
    return sdf_bytes, supervision_bytes, record


def generate_domain(
    *,
    template_path: Path,
    output_root: Path,
    key_count: int = DEFAULT_KEY_COUNT,
    seed_start: int = DEFAULT_SEED_START,
    seed_stop: int = DEFAULT_SEED_STOP,
) -> dict[str, Any]:
    if key_count <= 0:
        raise ValueError("key_count must be positive")
    if seed_stop <= seed_start:
        raise ValueError("seed_stop must be greater than seed_start")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration: {output_root}")
    template = template_path.read_text(encoding="utf-8")
    selected: list[tuple[bytes, bytes, dict[str, Any]]] = []
    for seed in range(seed_start, seed_stop):
        candidate = _candidate(template, seed)
        if candidate is not None:
            selected.append(candidate)
        if len(selected) == key_count:
            break
    if len(selected) != key_count:
        raise ValueError(
            f"only {len(selected)} geometry-admissible test keys; need {key_count}"
        )

    output_root.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    for sdf_bytes, supervision_bytes, record in selected:
        seed = int(record["scene_seed"])
        sdf = output_root / f"scene-{seed}.sdf"
        supervision = output_root / f"scene-{seed}.supervision.json"
        sdf.write_bytes(sdf_bytes)
        supervision.write_bytes(supervision_bytes)
        records.append(
            {
                **record,
                "sdf": str(sdf.resolve()),
                "supervision": str(supervision.resolve()),
            }
        )

    b0_freeze = PROJECT / "configs/m2c_b0_freeze.json"
    manifest: dict[str, Any] = {
        "schema_version": "M2CHeadroomDomainManifestV2",
        "status": "PREREGISTERED_NOT_EVALUATED",
        "dataset_version": DATASET_VERSION,
        "baseline_commit": BASELINE_COMMIT,
        "supersedes_invalid_candidate": {
            "manifest": "configs/m2c_headroom_domain.json",
            "domain_sha256": (
                "6630402d9e5ee4762cfef468f391af691dcef57b96bf8d2e2ac8b35cca337dd2"
            ),
            "exploration_report": str(V1_EXPLORATION_REPORT),
            "exploration_report_sha256": sha256_file(V1_EXPLORATION_REPORT),
            "reason": "horizontal free target was not publicly observable/stable",
        },
        "b0_freeze_manifest": str(b0_freeze),
        "b0_freeze_manifest_sha256": sha256_file(b0_freeze),
        "source_generator": "scripts/generate_industrial_scenes.py",
        "source_generator_sha256": sha256_file(
            PROJECT / "scripts/generate_industrial_scenes.py"
        ),
        "domain_builder": "scripts/m2c/build_tall_headroom_domain.py",
        "template": str(template_path),
        "template_sha256": sha256_file(template_path),
        "historical_physical_basis": [
            {
                "path": str(path.relative_to(PROJECT)),
                "sha256": sha256_file(path),
                "policy": (
                    "120 mm was the measured production contact; 140 mm "
                    "executed without contact; 100 mm failed at the lower "
                    "world-height IK pose"
                ),
            }
            for path in HEIGHT_CALIBRATION_REPORTS
        ],
        "selection_protocol": {
            "observes_isaac_outcomes": False,
            "seed_range_half_open": [seed_start, seed_stop],
            "split": "test",
            "key_count": key_count,
            "candidate_order": "ascending_seed_first_geometry_admissible",
            "public_target": "unique yellow world_x=max",
            "maximum_part_count": MAXIMUM_PART_COUNT,
            "all_orientations": "normal upright",
            "target_length_m": TALL_TARGET_LENGTH_M,
            "target_radius_m": CYLINDER_RADIUS_M,
            "mass_material_friction_and_velocity_decay_changed": False,
        },
        "baseline_protocol": {
            "runner": "scripts/m2b/run_physical_failure_smoke.py",
            "probe": "scripts/isaac_m1b_actuation_probe.py",
            "failure_type": "EMPTY_GRASP",
            "max_attempts": 1,
            "capture_public_rgbd": True,
            "contact_centerline_m": BASELINE_CONTACT_CENTERLINE_M,
            "implementation_parameters_retries_and_gates_changed": False,
            "final_success_definition": (
                "M2B accepted EMPTY_GRASP: injection physical_state_passed and "
                "public training_eligible and recovery "
                "physical_regrasp_and_lift_passed/training_eligible"
            ),
        },
        "existence_proof_protocol": {
            "purpose": "physical recoverability only; never counted as B0",
            "probe": "scripts/isaac_m1b_actuation_probe.py",
            "only_difference": (
                "pre-existing --contact-centerlines-m set to one "
                "pre-registered lower contact height"
            ),
            "contact_centerline_m": SCRIPTED_EXISTENCE_CONTACT_CENTERLINE_M,
            "same_ik_collision_safety_and_schema_gates": True,
            "policy_input_simulator_truth": False,
        },
        "keys": records,
        "outcomes_observed": False,
        "q_a_decision": None,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }
    manifest["domain_sha256"] = canonical_sha256(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT
        / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--key-count", type=int, default=DEFAULT_KEY_COUNT)
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--seed-stop", type=int, default=DEFAULT_SEED_STOP)
    args = parser.parse_args()
    if args.manifest.exists():
        raise FileExistsError(
            f"refusing to overwrite pre-registration: {args.manifest}"
        )
    manifest = generate_domain(
        template_path=args.template,
        output_root=args.output_root,
        key_count=args.key_count,
        seed_start=args.seed_start,
        seed_stop=args.seed_stop,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "keys": len(manifest["keys"]),
                "domain_sha256": manifest["domain_sha256"],
                "manifest": str(args.manifest),
                "output_root": str(args.output_root),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
