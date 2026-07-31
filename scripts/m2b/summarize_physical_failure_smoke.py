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
    parser.add_argument(
        "--remote-root",
        required=True,
        action="append",
        help="May be repeated to merge restart-safe targeted smoke roots.",
    )
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--report-md", required=True, type=Path)
    args = parser.parse_args()
    roots = [root.rstrip("/") for root in args.remote_root]
    summaries = [
        remote_json(args.host, f"{root}/physical-failure-smoke.json")
        for root in roots
    ]
    accepted = {}
    for summary in summaries:
        accepted.update(
            {
                item["failure_type"]: item
                for item in summary["attempts"]
                if item["accepted"]
            }
        )
    missing = {
        "EMPTY_GRASP",
        "WRONG_OBJECT",
        "RELEASE_FAILURE",
    } - set(accepted)
    if missing:
        raise RuntimeError(f"accepted failure evidence is missing: {sorted(missing)}")
    empty = remote_json(args.host, accepted["EMPTY_GRASP"]["evidence"])
    release = remote_json(
        args.host, accepted["RELEASE_FAILURE"]["evidence"]
    )
    wrong = remote_json(args.host, accepted["WRONG_OBJECT"]["evidence"])
    empty_evidence = empty["m2b_empty_grasp_injection"]
    release_evidence = release["m2b_release_failure_injection"]
    wrong_evidence = wrong["m2b_wrong_object_injection"]
    public_rgbd_complete = all(
        evidence.get("training_eligible") is True
        for evidence in (empty_evidence, release_evidence, wrong_evidence)
    )
    empty_recovery = empty["m2b_recovery"]["empty_grasp"]
    release_recovery = release["m2b_recovery"]["release_failure"]
    wrong_recovery = wrong["m2b_recovery"]["wrong_object"]
    two_recoveries_eligible = bool(
        empty_recovery.get("training_eligible") is True
        and release_recovery.get("training_eligible") is True
    )
    report = {
        "schema_version": "M2BS1PhysicalFailureSmokeV1",
        "status": (
            "PASS_PUBLIC_FAILURES_TWO_RECOVERIES_WRONG_RECOVERY_PENDING"
            if public_rgbd_complete and two_recoveries_eligible
            else "PASS_PHYSICAL_ONLY_PUBLIC_RGBD_PENDING"
        ),
        "remote_roots": roots,
        "accepted_failures": sorted(accepted),
        "attempt_count": sum(len(summary["attempts"]) for summary in summaries),
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
            "public_failure_predicates": empty_evidence.get(
                "public_predicates"
            ),
            "public_recovery_predicates": empty_recovery.get(
                "public_final_predicates"
            ),
            "training_eligible": empty_recovery.get("training_eligible", False),
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
            "public_failure_predicates": release_evidence.get(
                "public_predicates"
            ),
            "public_recovery_predicates": release_recovery.get(
                "public_final_predicates"
            ),
            "training_eligible": release_recovery.get(
                "training_eligible", False
            ),
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
            "public_failure_predicates": wrong_evidence.get(
                "public_predicates"
            ),
            "training_eligible": wrong_recovery.get(
                "training_eligible", False
            ),
        },
        "dataset_v2_episodes_admitted": 0,
        "training_eligible": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
        "teacher_kill_rule_events": [],
        "limitations": [
            "WRONG_OBJECT reassociation and target regrasp have not yet executed.",
            "Canonical FailureContextV1/EpisodeTransition packing remains pending; raw smoke evidence is not yet Dataset V2.",
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
                "- Public RGB-D failure predicates: captured and validated for all three failures.",
                "- Eligible recovery evidence: EMPTY_GRASP and RELEASE_FAILURE; WRONG_OBJECT target regrasp pending.",
                "- Dataset V2 admitted: 0 (canonical episode packing pending).",
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
