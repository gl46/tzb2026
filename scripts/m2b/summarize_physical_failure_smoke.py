#!/usr/bin/env python3
"""Retain concise evidence from the M2B physical-only failure smoke."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def remote_json(host: str, path: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, f"cat '{path}'"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot read {host}:{path}: {completed.stderr}")
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    args = parser.parse_args()
    root = args.remote_root.rstrip("/")
    summary = remote_json(args.host, f"{root}/physical-failure-smoke.json")
    accepted = {
        item["failure_type"]: item
        for item in summary["attempts"]
        if item["accepted"]
    }
    empty = remote_json(args.host, accepted["EMPTY_GRASP"]["evidence"])
    release = remote_json(
        args.host, accepted["RELEASE_FAILURE"]["evidence"]
    )
    wrong = remote_json(args.host, accepted["WRONG_OBJECT"]["evidence"])
    empty_evidence = empty["m2b_empty_grasp_injection"]
    release_evidence = release["m2b_release_failure_injection"]
    wrong_evidence = wrong["m2b_wrong_object_injection"]
    report = {
        "schema_version": "M2BS1PhysicalFailureSmokeV1",
        "status": "PASS_PHYSICAL_ONLY_PUBLIC_RGBD_PENDING",
        "remote_root": root,
        "accepted_failures": summary["accepted_failures"],
        "attempt_count": len(summary["attempts"]),
        "empty_grasp": {
            "evidence_path": accepted["EMPTY_GRASP"]["evidence"],
            "evidence_sha256": accepted["EMPTY_GRASP"]["evidence_sha256"],
            "close_command_issued": empty_evidence["close_command_issued"],
            "bilateral_grasp_observed": empty_evidence[
                "bilateral_grasp_observed"
            ],
            "attachment_created": empty_evidence["attachment_created"],
            "hand_lift_norm_m": sum(
                value**2 for value in empty_evidence["hand_lift_delta_m"]
            )
            ** 0.5,
            "target_lift_delta_m": empty_evidence["target_lift_delta_m"],
            "physical_regrasp_and_lift_passed": empty["m2b_recovery"][
                "empty_grasp"
            ]["physical_regrasp_and_lift_passed"],
        },
        "release_failure": {
            "evidence_path": accepted["RELEASE_FAILURE"]["evidence"],
            "evidence_sha256": accepted["RELEASE_FAILURE"][
                "evidence_sha256"
            ],
            "release_command_issued": release_evidence[
                "release_command_issued"
            ],
            "attachment_remained_after_release": release_evidence[
                "attachment_remained_after_release"
            ],
            "carried_follow_delta_m": release_evidence[
                "carried_follow_delta_m"
            ],
            "follow_error_m": release_evidence["follow_error_m"],
            "retry_detach_and_retreat_passed": release["m2b_recovery"][
                "release_failure"
            ]["retry_detach_and_retreat_passed"],
        },
        "wrong_object": {
            "evidence_path": accepted["WRONG_OBJECT"]["evidence"],
            "evidence_sha256": accepted["WRONG_OBJECT"]["evidence_sha256"],
            "contacted_entity_id": wrong_evidence["contacted_entity_id"],
            "attached_entity_id": wrong_evidence["attached_entity_id"],
            "task_target_entity_id": wrong_evidence[
                "task_target_entity_id"
            ],
            "broker_attached_actual_contact": wrong_evidence[
                "broker_attached_actual_contact"
            ],
            "safe_place_non_target_passed": wrong["m2b_recovery"][
                "wrong_object"
            ]["safe_place_non_target_passed"],
            "reassociate_target_executed": wrong["m2b_recovery"][
                "wrong_object"
            ]["reassociate_target_executed"],
            "regrasp_target_executed": wrong["m2b_recovery"][
                "wrong_object"
            ]["regrasp_target_executed"],
        },
        "dataset_v2_episodes_admitted": 0,
        "training_eligible": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "limitations": [
            "The actuation probe does not capture synchronized public RGB-D predicates.",
            "WRONG_OBJECT reassociation and target regrasp have not yet executed.",
            "These smokes prove physical injection/recovery mechanics only and are not Dataset V2 episodes.",
        ],
        "next_command": "make m2b-generate-failures",
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.report_md.write_text(
        "\n".join(
            [
                "# M2B S1 physical failure smoke",
                "",
                f"- status: **{report['status']}**",
                "- EMPTY_GRASP: close issued, no bilateral grasp/attachment; "
                f"hand lift {report['empty_grasp']['hand_lift_norm_m']:.6f} m, "
                f"target motion {report['empty_grasp']['target_lift_delta_m']:.9f} m; "
                "physical regrasp/lift passed.",
                "- RELEASE_FAILURE: open issued while attachment remained; "
                f"carried follow {report['release_failure']['carried_follow_delta_m']:.6f} m, "
                f"follow error {report['release_failure']['follow_error_m']:.6f} m; "
                "retry detach/retreat passed.",
                "- WRONG_OBJECT: actual contacted entity was attached and "
                "safely placed; public reassociation and target regrasp remain pending.",
                "- Dataset V2 admitted: 0 (public RGB-D pending).",
                "- Teacher used: no.",
                "",
                "## Limitations",
                "",
                *[f"- {item}" for item in report["limitations"]],
                "",
            ]
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
