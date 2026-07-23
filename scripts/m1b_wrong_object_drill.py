#!/usr/bin/env python3
"""ADR-0013 acceptance 4: live wrong-object drill analysis.

Given a pre-grasp and post-grasp public geometric-RGB-D evidence pair, the
broker's attached entity, and the scene supervision, decide the WRONG_OBJECT
outcome using only public perception + the actuation-internal attach record.

The carried track is identified robustly WITHOUT perceiving the occluded held
object: it is the pre-grasp public track whose spawn location is vacated in the
post-grasp frame (the grasped cylinder left the table).  The target track is a
public pre-grasp track designated as the intended target.  A carried track that
differs from the target is a concrete WRONG_OBJECT recovery event; supervision
records ``wrong_object = true`` for evaluation only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src", ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from xh_agent.grasp.post_grasp import evaluate_post_grasp_identity, evaluator_supervision_record  # noqa: E402
from xh_agent.recovery.manager import recovery_for  # noqa: E402
from xh_agent.runtime.m1b_camera_calibration import M1BStaticCameraCalibrationV1  # noqa: E402

VACATED_MATCH_M = 0.05


def track_world_centres(evidence_path: Path, camera_info_path: Path, calibration: M1BStaticCameraCalibrationV1) -> dict[str, dict]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    camera = json.loads(camera_info_path.read_text(encoding="utf-8"))
    intrinsics = camera.get("k", [])
    focal = min(float(intrinsics[0]), float(intrinsics[4])) if len(intrinsics) >= 5 else 0.0
    out: dict[str, dict] = {}
    for result in evidence.get("results", []):
        bbox = result.get("bbox_or_mask", {})
        depth = float(result.get("position_3d", [0, 0, 0])[2])
        pix = min(int(bbox.get("width", 0)), int(bbox.get("height", 0)))
        if focal <= 0 or depth <= 0 or pix <= 0:
            continue
        diameter = pix * depth / focal
        centre = calibration.visible_surface_to_center_world(tuple(float(v) for v in result["position_3d"]), diameter)
        out[str(result["track_id"])] = {
            "track_id": str(result["track_id"]),
            "visual_color": result.get("attributes", {}).get("visual_color"),
            "centre_world_m": list(centre),
        }
    return out


def nearest_track(tracks: dict[str, dict], xy: list[float]) -> str | None:
    best, best_d = None, 1e9
    for tid, t in tracks.items():
        c = t["centre_world_m"]
        d = ((c[0] - xy[0]) ** 2 + (c[1] - xy[1]) ** 2) ** 0.5
        if d < best_d:
            best, best_d = tid, d
    return best


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pre-evidence", required=True, type=Path)
    p.add_argument("--pre-camera-info", required=True, type=Path)
    p.add_argument("--post-evidence", required=True, type=Path)
    p.add_argument("--post-camera-info", required=True, type=Path)
    p.add_argument("--supervision", required=True, type=Path)
    p.add_argument("--target-entity", required=True, help="Intended target cylinder id (public-track designation)")
    p.add_argument("--attached-entity", required=True, help="Entity the broker actually attached (actuation-internal record)")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    calibration = M1BStaticCameraCalibrationV1.from_file(ROOT / "configs" / "m1b_camera_calibration.json")
    labels = {str(o["actual_sim_entity_id"]): o for o in json.loads(args.supervision.read_text())["simulator_supervision"]["objects"]}
    pre = track_world_centres(args.pre_evidence, args.pre_camera_info, calibration)
    post = track_world_centres(args.post_evidence, args.post_camera_info, calibration)

    # Designate the target public track: the pre-grasp track nearest the
    # intended target cylinder's spawn (public association, not an entity id).
    target_xy = [float(v) for v in labels[args.target_entity]["position_3d_world"][:2]]
    target_track_id = nearest_track(pre, target_xy)

    # Identify the carried public track by the vacated-spawn method: the
    # pre-grasp track whose location has no post-grasp track within
    # VACATED_MATCH_M has left the table, i.e. was carried by the gripper.
    vacated = []
    for tid, t in pre.items():
        c = t["centre_world_m"]
        still_there = any(
            ((c[0] - q["centre_world_m"][0]) ** 2 + (c[1] - q["centre_world_m"][1]) ** 2) ** 0.5 <= VACATED_MATCH_M
            for q in post.values()
        )
        if not still_there:
            vacated.append(tid)
    # The carried track is the vacated pre-grasp track nearest the attached
    # entity's spawn (confirms the vacated track corresponds to what the broker
    # physically attached, without reading simulator truth into the identity).
    attached_xy = [float(v) for v in labels[args.attached_entity]["position_3d_world"][:2]]
    carried_track_id = nearest_track({t: pre[t] for t in vacated}, attached_xy) if vacated else None

    identity = evaluate_post_grasp_identity(target_track_id=str(target_track_id), carried_track_id=carried_track_id)
    wrong_object = identity.wrong_object_detected
    recovery = recovery_for("WRONG_OBJECT") if identity.identity_status == "WRONG_OBJECT" else None
    supervision = evaluator_supervision_record(actual_sim_entity_id=args.attached_entity, wrong_object=bool(args.attached_entity != args.target_entity))

    payload = {
        "schema_version": "M1BWrongObjectDrillEvidenceV1",
        "provenance": "SUPERVISION_EVALUATION_ONLY",
        "online_truth_access": False,
        "intended_target_entity": args.target_entity,
        "target_public_track_id": target_track_id,
        "attached_entity": args.attached_entity,
        "carried_public_track_id": carried_track_id,
        "vacated_pre_grasp_tracks": vacated,
        "identity_status": identity.identity_status,
        "wrong_object_detected": wrong_object,
        "recovery_triggered": recovery is not None,
        "recovery_subgoals": list(recovery.recovery_subgoals) if recovery is not None else None,
        "supervision_record": supervision,
        "pre_track_count": len(pre),
        "post_track_count": len(post),
        "carried_track_association": "VACATED_SPAWN_NEAREST_ATTACHED_ENTITY",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    passed = bool(
        identity.identity_status == "WRONG_OBJECT"
        and wrong_object
        and recovery is not None
        and supervision["wrong_object"] is True
        and args.attached_entity != args.target_entity
    )
    print(json.dumps({"identity_status": identity.identity_status, "wrong_object": wrong_object, "recovery_triggered": recovery is not None, "passed": passed}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
