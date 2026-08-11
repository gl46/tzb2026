#!/usr/bin/env python3
"""Pre-register M2C's final, V3-informed PATH_BLOCKED candidate (V4)."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from generate_industrial_scenes import (
    CYLINDER_RADIUS_M,
    MIN_TOP_GRASP_CORRIDOR_RADIUS_M,
    ROBOT_BASE_XY,
    bin_cell_targets,
    cached_layout_reachability,
    cylinder_pose,
    render,
    split,
)
from m2c.build_headroom_domain import (
    BASELINE_COMMIT,
    DATASET_VERSION,
    PROJECT,
    _models,
    canonical_sha256,
    sha256_bytes,
    sha256_file,
)
from m2c.derive_blocker_probe import (
    UPSTREAM_B0_PROBE_SHA256,
    derive_probe_bytes,
)
from m2c.s2_decision import (
    CandidateStatus,
    DomainCandidateDecision,
    S2Disposition,
    decide_s2_stop_loss,
)
from xh_agent.grasp.free_gap import (
    FREE_GAP_MIN_CLEARANCE_M,
    select_free_gap_yaw_from_xy,
)


DEFAULT_SEED_START = 9000
DEFAULT_SEED_STOP = 9400
DEFAULT_KEY_COUNT = 3
BLOCKER_DISTANCE_M = 0.040
RETAINED_BLOCKER_DISTANCE_M = 0.062
SCRIPTED_BIN_CELL_INDEX = 3
TARGET_ENTITY = "cylinder_04"  # public yellow, evaluator-only provenance
SCRIPTED_BLOCKER_ENTITY = "cylinder_01"  # public red
RETAINED_BLOCKER_ENTITY = "cylinder_02"  # public green
ANCHORS_XY_M = (
    (-0.110, 0.130),
    (-0.105, 0.130),
    (-0.115, 0.130),
)
FAR_OBJECT_XY_M = {
    "cylinder_03": (-0.53, -0.34),
    "cylinder_05": (-0.25, -0.34),
    "cylinder_06": (-0.11, -0.34),
}
V1_EXPLORATION_REPORT = PROJECT / "reports/m2c-s2-exploration-v1.json"
V2_EXPLORATION_REPORT = PROJECT / "reports/m2c-s2-exploration-v2.json"
V3_EXPLORATION_REPORT = PROJECT / "reports/m2c-s2-exploration-v3.json"
V3_MANIFEST = PROJECT / "configs/m2c_headroom_domain_v3.json"
B0_RUNNER = PROJECT / "scripts/m2b/run_physical_failure_smoke.py"


def _final_candidate_stop_loss_receipt() -> dict[str, object]:
    records = [
        DomainCandidateDecision(
            1,
            CandidateStatus.INVALID_PUBLIC_CONTRACT,
            "no public target and natural instability",
        ),
        DomainCandidateDecision(
            2,
            CandidateStatus.INVALID_PUBLIC_CONTRACT,
            "public predicate rejected physical EMPTY_GRASP and no public target",
        ),
        DomainCandidateDecision(
            3,
            CandidateStatus.INVALID_PUBLIC_CONTRACT,
            "public target/blocker selection was not stable across frozen keys",
        ),
    ]
    decision = decide_s2_stop_loss(records)
    if (
        decision.disposition != S2Disposition.ALLOW_FINAL_DOMAIN_CANDIDATE
        or decision.next_candidate_number != 4
    ):
        raise RuntimeError("frozen stop-loss does not authorize final candidate V4")
    return {
        "records": [
            {
                "candidate_number": record.candidate_number,
                "status": record.status.value,
                "reason": record.reason,
            }
            for record in records
        ],
        "disposition": decision.disposition.value,
        "authorized_candidate_number": decision.next_candidate_number,
        "max_domain_candidates": 4,
        "v5_and_later_forbidden": True,
        "v4_nonpass_disposition": S2Disposition.TRIGGER_D1.value,
    }


def _reachability(xy: tuple[float, float]) -> dict[str, Any]:
    z = cylinder_pose("normal")[2]
    report = dict(cached_layout_reachability((xy[0], xy[1], z)))
    base_axis_radius_m = math.dist(xy, ROBOT_BASE_XY)
    report.update(
        {
            "base_axis_radius_m": base_axis_radius_m,
            "top_grasp_corridor_radius_ok": (base_axis_radius_m >= MIN_TOP_GRASP_CORRIDOR_RADIUS_M),
            "min_top_grasp_corridor_radius_m": (MIN_TOP_GRASP_CORRIDOR_RADIUS_M),
            "m2c_preregistered_layout_only": True,
        }
    )
    return report


def _layout(anchor: tuple[float, float]) -> dict[str, tuple[float, float]]:
    return {
        TARGET_ENTITY: anchor,
        SCRIPTED_BLOCKER_ENTITY: (
            anchor[0] + BLOCKER_DISTANCE_M,
            anchor[1],
        ),
        RETAINED_BLOCKER_ENTITY: (
            anchor[0],
            anchor[1] + RETAINED_BLOCKER_DISTANCE_M,
        ),
        **FAR_OBJECT_XY_M,
    }


def _minimum_surface_gap(layout: dict[str, tuple[float, float]]) -> float:
    positions = list(layout.values())
    return min(
        math.dist(first, second) - 2.0 * CYLINDER_RADIUS_M
        for index, first in enumerate(positions)
        for second in positions[index + 1 :]
    )


def _gap_receipts(
    layout: dict[str, tuple[float, float]],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    target = layout[TARGET_ENTITY]
    blocker = layout[SCRIPTED_BLOCKER_ENTITY]
    target_before = select_free_gap_yaw_from_xy(
        target,
        [value for name, value in layout.items() if name != TARGET_ENTITY],
        source="M2C_V4_FINAL_PREREGISTERED_LAYOUT_ONLY",
    )
    blocker_before = select_free_gap_yaw_from_xy(
        blocker,
        [value for name, value in layout.items() if name != SCRIPTED_BLOCKER_ENTITY],
        source="M2C_V4_FINAL_PREREGISTERED_LAYOUT_ONLY",
    )
    target_after = select_free_gap_yaw_from_xy(
        target,
        [
            value
            for name, value in layout.items()
            if name not in {TARGET_ENTITY, SCRIPTED_BLOCKER_ENTITY}
        ],
        source="M2C_V4_FINAL_AFTER_SCRIPTED_RELOCATION",
    )
    return target_before, blocker_before, target_after


def _candidate(
    template: str,
    seed: int,
    anchor: tuple[float, float],
) -> tuple[bytes, bytes, dict[str, Any]] | None:
    if split(seed) != "test":
        return None
    scene, supervision = render(template, seed, orientations=("normal",))
    root = ET.fromstring(scene)
    models = _models(root)
    if len(models) != 6:
        return None
    by_name = {str(model.get("name")): model for model in models}
    if set(by_name) != {f"cylinder_{index:02d}" for index in range(1, 7)}:
        raise ValueError("six-object source scene is not canonical")

    layout = _layout(anchor)
    reachability = {name: _reachability(xy) for name, xy in layout.items()}
    if not all(
        receipt["passed"] and receipt["top_grasp_corridor_radius_ok"]
        for receipt in reachability.values()
    ):
        raise ValueError(f"seed {seed}: pre-registered layout is not reachable")
    minimum_surface_gap_m = _minimum_surface_gap(layout)
    if minimum_surface_gap_m < 0.005:
        raise ValueError(f"seed {seed}: layout has less than 5 mm surface gap")
    target_before, blocker_before, target_after = _gap_receipts(layout)
    if (
        target_before["clearance_ok"] is not False
        or blocker_before["clearance_ok"] is not True
        or target_after["clearance_ok"] is not True
    ):
        raise ValueError(f"seed {seed}: blocked/unblocked geometry contract failed")

    z = cylinder_pose("normal")[2]
    labels = {
        str(item["actual_sim_entity_id"]): item
        for item in supervision["simulator_supervision"]["objects"]
    }
    for name, (x, y) in layout.items():
        model = by_name[name]
        pose = [x, y, z, 0.0, 0.0, 0.0]
        model.find("pose").text = " ".join(f"{value:.9f}" for value in pose)
        label = labels[name]
        label["position_3d_world"] = pose[:3]
        label["orientation_state"] = "normal"
        label["yaw"] = 0.0
        label["layout_reachability"] = reachability[name]
        label["m2c_layout_role"] = (
            "TASK_TARGET"
            if name == TARGET_ENTITY
            else "SCRIPTED_RELOCATION_BLOCKER"
            if name == SCRIPTED_BLOCKER_ENTITY
            else "RETAINED_BLOCKER"
            if name == RETAINED_BLOCKER_ENTITY
            else "DISTANT_DISTRACTOR"
        )

    supervision["m2c_headroom_domain"] = {
        "schema_version": "M2CHeadroomSceneV4",
        "dataset_version": DATASET_VERSION,
        "failure_type": "PATH_BLOCKED",
        "target_selector": "visual_color=yellow,top_z_band=0.02m,world_x=max",
        "scripted_blocker_selector": "visual_color=red,top_z_band=0.02m,world_x=max",
        "target_entity_evaluator_only": TARGET_ENTITY,
        "scripted_blocker_entity_evaluator_only": SCRIPTED_BLOCKER_ENTITY,
        "scripted_bin_cell_index": SCRIPTED_BIN_CELL_INDEX,
        "scripted_bin_cell_world_m": list(bin_cell_targets()[SCRIPTED_BIN_CELL_INDEX]),
        "target_clearance_before_m": target_before["min_clearance_m"],
        "blocker_clearance_before_m": blocker_before["min_clearance_m"],
        "target_clearance_after_relocation_m": target_after["min_clearance_m"],
        "b0_modified": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    ET.indent(root, space="  ")
    sdf_bytes = (ET.tostring(root, encoding="unicode") + "\n").encode()
    supervision_bytes = (json.dumps(supervision, indent=2, sort_keys=True) + "\n").encode()
    record = {
        "scene_seed": seed,
        "split": "test",
        "failure_type": "PATH_BLOCKED",
        "target_entity_evaluator_only": TARGET_ENTITY,
        "scripted_blocker_entity_evaluator_only": SCRIPTED_BLOCKER_ENTITY,
        "target_selector_policy_input": ("visual_color=yellow,top_z_band=0.02m,world_x=max"),
        "scripted_blocker_selector_policy_input": ("visual_color=red,top_z_band=0.02m,world_x=max"),
        "part_count": 6,
        "anchor_xy_m": list(anchor),
        "blocker_distance_m": BLOCKER_DISTANCE_M,
        "retained_blocker_distance_m": RETAINED_BLOCKER_DISTANCE_M,
        "minimum_surface_gap_m": minimum_surface_gap_m,
        "target_clearance_before_m": float(target_before["min_clearance_m"]),
        "target_clearance_before_ok": bool(target_before["clearance_ok"]),
        "scripted_blocker_clearance_m": float(blocker_before["min_clearance_m"]),
        "scripted_blocker_clearance_ok": bool(blocker_before["clearance_ok"]),
        "target_clearance_after_relocation_m": float(target_after["min_clearance_m"]),
        "target_clearance_after_relocation_ok": bool(target_after["clearance_ok"]),
        "scripted_bin_cell_index": SCRIPTED_BIN_CELL_INDEX,
        "scripted_bin_cell_world_m": list(bin_cell_targets()[SCRIPTED_BIN_CELL_INDEX]),
        "sdf_sha256": sha256_bytes(sdf_bytes),
        "supervision_sha256": sha256_bytes(supervision_bytes),
        "v4_outcome_observed_during_selection": False,
    }
    record["matched_key"] = "m2c-headroom-v4-" + canonical_sha256(record)
    return sdf_bytes, supervision_bytes, record


def generate_domain(
    *,
    template_path: Path,
    upstream_probe: Path,
    output_root: Path,
    key_count: int = DEFAULT_KEY_COUNT,
    seed_start: int = DEFAULT_SEED_START,
    seed_stop: int = DEFAULT_SEED_STOP,
) -> dict[str, Any]:
    if key_count <= 0 or key_count > len(ANCHORS_XY_M):
        raise ValueError(f"key_count must be in [1, {len(ANCHORS_XY_M)}]")
    if seed_stop <= seed_start:
        raise ValueError("seed_stop must be greater than seed_start")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration: {output_root}")
    stop_loss_receipt = _final_candidate_stop_loss_receipt()
    upstream_bytes = upstream_probe.read_bytes()
    if sha256_bytes(upstream_bytes) != UPSTREAM_B0_PROBE_SHA256:
        raise ValueError("frozen B0 probe hash mismatch")
    derived_probe = derive_probe_bytes(upstream_bytes)
    template = template_path.read_text(encoding="utf-8")

    selected: list[tuple[bytes, bytes, dict[str, Any]]] = []
    for seed in range(seed_start, seed_stop):
        anchor = ANCHORS_XY_M[len(selected)]
        candidate = _candidate(template, seed, anchor)
        if candidate is not None:
            selected.append(candidate)
        if len(selected) == key_count:
            break
    if len(selected) != key_count:
        raise ValueError(f"only {len(selected)} six-object test keys; need {key_count}")

    output_root.mkdir(parents=True, exist_ok=False)
    derived_path = output_root / "isaac_m2c_blocker_probe.py"
    derived_path.write_bytes(derived_probe)
    derived_path.chmod(0o555)
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
        "schema_version": "M2CHeadroomDomainManifestV4",
        "status": "FINAL_CANDIDATE_PREREGISTERED_NOT_EVALUATED",
        "candidate_number": 4,
        "final_domain_candidate": True,
        "further_domain_iterations_forbidden": True,
        "dataset_version": DATASET_VERSION,
        "baseline_commit": BASELINE_COMMIT,
        "preregistration_timing": {
            "date_asia_shanghai": "2026-08-12",
            "written_after_v3_results": True,
            "written_before_any_v4_isaac_execution": True,
            "statement": (
                "V1-V3 outcomes informed this layout; no V4 Isaac result was "
                "observed before this manifest was generated and committed."
            ),
        },
        "outcome_informed_design": {
            "uses_v3_results": True,
            "v3_report": str(V3_EXPLORATION_REPORT),
            "v3_report_sha256": sha256_file(V3_EXPLORATION_REPORT),
            "v3_manifest": str(V3_MANIFEST),
            "v3_manifest_sha256": sha256_file(V3_MANIFEST),
            "changes_from_v3": [
                (
                    "retain the proven public-camera-region target anchor and "
                    "use only +/-5 mm x micro-jitter across three keys"
                ),
                (
                    "keep the red blocker 40 mm from the target so frozen B0 "
                    "still fails the unchanged 5 mm free-gap gate"
                ),
                (
                    "move the retained green blocker from 40 mm at 105 degrees "
                    "to 62 mm at 90 degrees, increasing post-relocation target "
                    "clearance from about 29.6 mm to about 46.2 mm"
                ),
                "reuse the unchanged V3 derived existence probe and bin cell",
            ],
            "v4_results_used_for_design": False,
        },
        "stop_loss": stop_loss_receipt,
        "supersedes_v3_nonpass": {
            "manifest": "configs/m2c_headroom_domain_v3.json",
            "manifest_sha256": sha256_file(V3_MANIFEST),
            "domain_sha256": ("7ed332bd0761a06ce4276ff7ae8eeb689d0d84cbecf54633a066f918c764a775"),
            "exploration_report": "reports/m2c-s2-exploration-v3.json",
            "exploration_report_sha256": sha256_file(V3_EXPLORATION_REPORT),
        },
        "prior_candidate_reports": [
            {
                "candidate_number": number,
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for number, path in (
                (1, V1_EXPLORATION_REPORT),
                (2, V2_EXPLORATION_REPORT),
                (3, V3_EXPLORATION_REPORT),
            )
        ],
        "b0_freeze_manifest": str(b0_freeze),
        "b0_freeze_manifest_sha256": sha256_file(b0_freeze),
        "baseline_protocol": {
            "probe": "scripts/isaac_m1b_actuation_probe.py",
            "probe_sha256": UPSTREAM_B0_PROBE_SHA256,
            "runner": "scripts/m2b/run_physical_failure_smoke.py",
            "runner_sha256": sha256_file(B0_RUNNER),
            "retry_count": 2,
            "target": "public yellow world_x=max",
            "expected_result": "safe free-gap rejection before physical action",
            "implementation_parameters_retries_and_gates_changed": False,
            "final_success": (
                "true only if the frozen probe physically lifts the public "
                "task target; a safety rejection is false"
            ),
        },
        "domain_builder": "scripts/m2c/build_final_headroom_domain.py",
        "domain_builder_sha256": sha256_file(
            PROJECT / "scripts/m2c/build_final_headroom_domain.py"
        ),
        "source_generator": "scripts/generate_industrial_scenes.py",
        "source_generator_sha256": sha256_file(PROJECT / "scripts/generate_industrial_scenes.py"),
        "template": str(template_path),
        "template_sha256": sha256_file(template_path),
        "derived_existence_probe": {
            "path": str(derived_path.resolve()),
            "sha256": sha256_bytes(derived_probe),
            "builder": "scripts/m2c/derive_blocker_probe.py",
            "builder_sha256": sha256_file(PROJECT / "scripts/m2c/derive_blocker_probe.py"),
            "upstream_b0_probe": "scripts/isaac_m1b_actuation_probe.py",
            "upstream_b0_probe_sha256": UPSTREAM_B0_PROBE_SHA256,
            "counted_as_b0": False,
            "changed_since_v3": False,
        },
        "selection_protocol": {
            "observes_v4_isaac_outcomes": False,
            "uses_prior_v3_outcomes": True,
            "seed_range_half_open": [seed_start, seed_stop],
            "split": "test",
            "key_count": key_count,
            "candidate_order": "ascending_seed_with_exactly_six_objects",
            "anchor_order": [list(anchor) for anchor in ANCHORS_XY_M[:key_count]],
            "failure_type": "PATH_BLOCKED",
            "object_geometry_mass_material_and_dynamics": "unchanged M2B",
            "target_blocker_center_distance_m": BLOCKER_DISTANCE_M,
            "retained_blocker_center_distance_m": RETAINED_BLOCKER_DISTANCE_M,
            "minimum_physical_surface_gap_m": 0.005,
            "clearance_gate_m": FREE_GAP_MIN_CLEARANCE_M,
        },
        "public_contract_gate": {
            "required_before_counting_b0": [
                "public yellow target selected",
                "two frozen B0 attempts completed",
            ],
            "required_before_counting_existence_proof": [
                "public red blocker selected",
                "public yellow target selected or publicly reassociated",
            ],
            "missing_required_public_track": "INVALID_DOMAIN_AND_TRIGGER_D1",
        },
        "existence_proof_protocol": {
            "purpose": "physical recoverability only; never counted as B0",
            "probe_sha256": sha256_bytes(derived_probe),
            "sequence": [
                "PUBLIC_RED_BLOCKER_GRASP",
                "LIFT",
                "COLLISION_GATED_MOVE_TO_OFFICIAL_BIN_CELL",
                "RELEASE",
                "PUBLIC_REASSOCIATE_YELLOW_TARGET",
                "PUBLIC_REGRASP_YELLOW_TARGET",
            ],
            "strict_success_predicate_all_required": [
                "m2c_scripted_safe_place.passed == true",
                "m2c_scripted_safe_place.motion.collision_gate.status == PASS",
                "m2b_wrong_object_injection.training_eligible == true",
                "m2b_recovery.wrong_object.reassociate_target_executed == true",
                "m2b_recovery.wrong_object.regrasp_target_executed == true",
                (
                    "m2b_recovery.wrong_object.public_regrasp_predicates contains "
                    "grasped=true and lifted=true"
                ),
                "m2b_recovery.wrong_object.training_eligible == true",
            ],
            "top_level_probe_pass_alone_is_insufficient": True,
            "collision_violations_required": 0,
            "same_ik_collision_safety_contact_and_schema_gates": True,
            "policy_input_simulator_truth": False,
            "live_pose_used_only_for_evaluator_scripted_transport": True,
        },
        "q_a_acceptance": {
            "b0_final_task_success_rate_lt": 0.8,
            "minimum_complete_existence_proofs": 1,
            "both_conditions_required": True,
            "v4_nonpass": "TRIGGER_D1_WITHOUT_V5",
        },
        "keys": records,
        "v4_outcomes_observed": False,
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
        default=PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf",
    )
    parser.add_argument(
        "--upstream-probe",
        type=Path,
        default=PROJECT / "scripts/isaac_m1b_actuation_probe.py",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--key-count", type=int, default=DEFAULT_KEY_COUNT)
    parser.add_argument("--seed-start", type=int, default=DEFAULT_SEED_START)
    parser.add_argument("--seed-stop", type=int, default=DEFAULT_SEED_STOP)
    args = parser.parse_args()
    if args.manifest.exists():
        raise FileExistsError(f"refusing to overwrite pre-registration: {args.manifest}")
    manifest = generate_domain(
        template_path=args.template,
        upstream_probe=args.upstream_probe,
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
                "derived_probe_sha256": manifest["derived_existence_probe"]["sha256"],
                "manifest": str(args.manifest),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
