#!/usr/bin/env python3
"""Materialize outcome-blind S4/S6 scenes in the accepted M2C V4 family."""

from __future__ import annotations

import json
from typing import Any
import xml.etree.ElementTree as ET

from generate_industrial_scenes import bin_cell_targets, cylinder_pose, render
from m2c.build_final_headroom_domain import (
    BLOCKER_DISTANCE_M,
    RETAINED_BLOCKER_DISTANCE_M,
    SCRIPTED_BIN_CELL_INDEX,
    SCRIPTED_BLOCKER_ENTITY,
    TARGET_ENTITY,
    _gap_receipts,
    _layout,
    _minimum_surface_gap,
    _reachability,
)
from m2c.build_headroom_domain import DATASET_VERSION, _models, sha256_bytes


CANONICAL_ENTITY_NAMES = frozenset(f"cylinder_{index:02d}" for index in range(1, 7))


def materialize_scene(
    template: str,
    seed: int,
    anchor: tuple[float, float],
) -> tuple[bytes, bytes, dict[str, Any]] | None:
    """Return one six-object scene without reading any simulator outcome.

    The transformation intentionally mirrors the frozen V4 candidate builder.
    It is split-agnostic so disjoint train, validation-smoke, and test keys can
    share the accepted geometry while retaining the generator's public split.
    """

    scene, supervision = render(template, seed, orientations=("normal",))
    root = ET.fromstring(scene)
    models = _models(root)
    if len(models) != 6:
        return None
    by_name = {str(model.get("name")): model for model in models}
    if set(by_name) != CANONICAL_ENTITY_NAMES:
        raise ValueError("six-object source scene is not canonical")

    layout = _layout(anchor)
    reachability = {name: _reachability(xy) for name, xy in layout.items()}
    if not all(
        receipt["passed"] and receipt["top_grasp_corridor_radius_ok"]
        for receipt in reachability.values()
    ):
        raise ValueError(f"seed {seed}: accepted-family layout is not reachable")
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
        pose = [x, y, z, 0.0, 0.0, 0.0]
        by_name[name].find("pose").text = " ".join(f"{value:.9f}" for value in pose)
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
            if name == "cylinder_02"
            else "DISTANT_DISTRACTOR"
        )

    supervision["m2c_headroom_domain"] = {
        "schema_version": "M2CHeadroomSceneV4",
        "dataset_version": DATASET_VERSION,
        "failure_type": "PATH_BLOCKED",
        "target_selector": "visual_color=yellow,top_z_band=0.02m,world_x=max",
        "scripted_blocker_selector": ("visual_color=red,top_z_band=0.02m,world_x=max"),
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
    receipt = {
        "scene_seed": seed,
        "split": str(supervision["split"]),
        "failure_type": "PATH_BLOCKED",
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
        "outcome_observed_during_materialization": False,
    }
    return sdf_bytes, supervision_bytes, receipt
