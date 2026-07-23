#!/usr/bin/env python3
"""ADR-0013 acceptance 4: live wrong-object drill analysis.

Given a pre-grasp and post-grasp public geometric-RGB-D evidence pair and the
broker's attach record, decide the WRONG_OBJECT outcome using only public
perception plus that actuation-internal record. Optional simulator supervision
is read only *after* the online decision, to score the drill.

The carried track is identified WITHOUT perceiving the occluded held object: it
is the *unique* public pre-grasp track whose observed table location is vacant
in the post-grasp frame. An ambiguous vacancy fails closed to re-observation;
the attach entity must never be joined to a public track via its simulator
spawn pose. The target is a public pre-grasp track designated before the grasp.
A carried track that differs from that target is a concrete WRONG_OBJECT
recovery event; supervision records the result for evaluation only.
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


def carried_track_from_vacancy(vacated_track_ids: list[str]) -> str | None:
    """Return a public carried track only when observation is unambiguous.

    Two or more disappeared tracks could be occluded by the gripper or a
    viewpoint change. An online recovery decision must request another public
    observation rather than guessing an identity from a simulator label.
    """

    return vacated_track_ids[0] if len(vacated_track_ids) == 1 else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pre-evidence", required=True, type=Path)
    p.add_argument("--pre-camera-info", required=True, type=Path)
    p.add_argument("--post-evidence", required=True, type=Path)
    p.add_argument("--post-camera-info", required=True, type=Path)
    p.add_argument("--target-public-track-id", required=True, help="Public pre-grasp target track chosen before actuation")
    p.add_argument("--attached-entity", required=True, help="Entity the broker actually attached (actuation-internal record)")
    p.add_argument("--supervision", type=Path, help="Optional evaluator-only simulator labels, read after the online decision")
    p.add_argument("--evaluation-target-entity", help="Optional evaluator-only intended entity; requires --supervision")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    calibration = M1BStaticCameraCalibrationV1.from_file(ROOT / "configs" / "m1b_camera_calibration.json")
    if bool(args.supervision) != bool(args.evaluation_target_entity):
        p.error("--supervision and --evaluation-target-entity must be supplied together for evaluator-only scoring")
    pre = track_world_centres(args.pre_evidence, args.pre_camera_info, calibration)
    post = track_world_centres(args.post_evidence, args.post_camera_info, calibration)
    target_track_id = str(args.target_public_track_id)

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
    carried_track_id = carried_track_from_vacancy(vacated)

    identity = evaluate_post_grasp_identity(target_track_id=str(target_track_id), carried_track_id=carried_track_id)
    wrong_object = identity.wrong_object_detected
    recovery = recovery_for("WRONG_OBJECT") if identity.identity_status == "WRONG_OBJECT" else None
    # All evaluator truth reads happen after the online identity/recovery
    # decision. No simulator label is allowed to influence target selection or
    # carried-track association above.
    supervision = None
    if args.supervision is not None:
        labels = {
            str(o["actual_sim_entity_id"]): o
            for o in json.loads(args.supervision.read_text(encoding="utf-8"))["simulator_supervision"]["objects"]
        }
        if args.attached_entity not in labels or args.evaluation_target_entity not in labels:
            p.error("evaluator target/attached entity absent from --supervision")
        supervision = evaluator_supervision_record(
            actual_sim_entity_id=args.attached_entity,
            wrong_object=bool(args.attached_entity != args.evaluation_target_entity),
        )

    payload = {
        "schema_version": "M1BWrongObjectDrillEvidenceV1",
        "provenance": "SUPERVISION_EVALUATION_ONLY",
        "online_truth_access": False,
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
        "carried_track_association": (
            "UNIQUE_VACATED_PUBLIC_TRACK" if carried_track_id is not None
            else "AMBIGUOUS_OR_UNOBSERVED_PUBLIC_VACANCY"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    passed = bool(
        identity.identity_status == "WRONG_OBJECT"
        and wrong_object
        and recovery is not None
        and (supervision is None or supervision["wrong_object"] is True)
    )
    print(json.dumps({"identity_status": identity.identity_status, "wrong_object": wrong_object, "recovery_triggered": recovery is not None, "passed": passed}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
