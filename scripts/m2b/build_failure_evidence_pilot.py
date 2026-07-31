#!/usr/bin/env python3
"""Pack accepted Isaac smokes into validated failure/recovery evidence records.

These records intentionally remain a pre-Dataset-V2 pilot: the actuation probe
is not a model rollout and does not log the complete action trajectory required
for the final dataset.  They validate the public/supervision boundary and the
FailureContext/recovery contract before scale generation begins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from xh_agent.data_engine.isaac.failure_rich import (
    failure_rich_group_key,
    validate_failure_recovery_episode,
)
from xh_agent.policy.qrm_lite.contracts import FailureContextV1, FailureType


RECOVERY = {
    "EMPTY_GRASP": ["REOBSERVE", "REGRASP"],
    "WRONG_OBJECT": [
        "SAFE_PLACE_NON_TARGET",
        "REASSOCIATE_TARGET",
        "REGRASP",
    ],
    "RELEASE_FAILURE": ["RETRY_RELEASE", "RETREAT", "REOBSERVE"],
}
EXPECTED = {
    "EMPTY_GRASP": ["grasped=true", "lifted=true"],
    "WRONG_OBJECT": ["carried_target_match=true"],
    "RELEASE_FAILURE": ["released=true"],
}
AFTER_CAPTURE = {
    "EMPTY_GRASP": "empty_grasp_reobserve",
    "WRONG_OBJECT": "after_physical_lift",
    "RELEASE_FAILURE": "release_failure_after_follow",
}
INJECTION_KEY = {
    "EMPTY_GRASP": "m2b_empty_grasp_injection",
    "WRONG_OBJECT": "m2b_wrong_object_injection",
    "RELEASE_FAILURE": "m2b_release_failure_injection",
}


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


def _capture(payload: dict[str, Any], label: str) -> dict[str, Any]:
    matches = [
        capture
        for capture in payload["m2b_public_rgbd"]["captures"]
        if capture["label"] == label
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one public capture {label!r}")
    return matches[0]


def build_episode(
    payload: dict[str, Any],
    *,
    failure_type: str,
    evidence_path: str,
    evidence_sha256: str,
    injection_seed: int,
) -> dict[str, Any]:
    injection = payload[INJECTION_KEY[failure_type]]
    recovery = payload["m2b_recovery"][failure_type.lower()]
    if not injection.get("training_eligible") or not recovery.get(
        "training_eligible"
    ):
        raise ValueError(f"{failure_type} evidence/recovery is not eligible")
    before = _capture(payload, "before_failure")
    after = _capture(payload, AFTER_CAPTURE[failure_type])
    public_predicates = injection["public_predicates"]
    observed = list(public_predicates["predicates"])
    expected = EXPECTED[failure_type]
    residual = [
        f"expected:{item};observed:{observed[index]}"
        for index, item in enumerate(expected)
    ]
    sequence = RECOVERY[failure_type]
    target_track_id = payload["m2b_public_rgbd"]["task_spec"][
        "target_track_id"
    ]
    context = FailureContextV1(
        last_skill="GRASP" if failure_type != "RELEASE_FAILURE" else "RELEASE",
        previous_skill=(
            "GRASP" if failure_type != "RELEASE_FAILURE" else "RELEASE"
        ),
        expected_predicates=expected,
        observed_predicates=observed,
        predicate_residual=residual,
        failure_type=FailureType(failure_type),
        retry_count=1,
        attempted_recoveries=sequence,
        last_recovery_result="SUCCESS",
        last_action_summary="physical failure injection followed by recovery",
        last_target_track_id=target_track_id,
        last_carried_track_id=public_predicates.get(
            "carried_public_track_id"
        ),
    )
    physical: dict[str, Any] = {
        "schema_version": "PhysicalFailureEvidenceV2",
        "failure_type": failure_type,
        "injection_commanded": injection["injection_commanded"],
        "close_command_issued": injection.get("close_command_issued", False),
        "release_command_issued": injection.get(
            "release_command_issued", False
        ),
        "bilateral_grasp_observed": injection.get(
            "bilateral_grasp_observed"
        )
        if failure_type != "WRONG_OBJECT"
        else bool(injection.get("broker_attached_actual_contact")),
        "attachment_created": injection.get("attachment_created"),
        "attachment_remained_after_release": injection.get(
            "attachment_remained_after_release"
        ),
        "contacted_entity_id": injection.get("contacted_entity_id"),
        "attached_entity_id": injection.get("attached_entity_id"),
        "task_target_entity_id": injection.get("task_target_entity_id"),
        "task_target_track_id": public_predicates.get(
            "task_target_track_id"
        ),
        "carried_public_track_id": public_predicates.get(
            "carried_public_track_id"
        ),
        "target_lift_delta_m": injection.get("target_lift_delta_m"),
        "carried_follow_delta_m": injection.get("carried_follow_delta_m"),
        "public_observed_predicates": observed,
        "supervision_only": True,
    }
    physical = {key: value for key, value in physical.items() if value is not None}
    scene_seed = int(payload["scene_seed"])
    episode = {
        "schema_version": "M2BFailureRecoveryEvidenceV2",
        "dataset_version": "isaac-industrial-v2-failure-rich-pilot",
        "episode_id": (
            f"m2b-{scene_seed}-{failure_type.lower()}-{injection_seed:06d}"
        ),
        "scene_seed": scene_seed,
        "injection_seed": injection_seed,
        "group_key": failure_rich_group_key(
            scene_seed, failure_type, injection_seed
        ),
        "observation_before": before,
        "observation_after": after,
        "recovery_observations": payload["m2b_public_rgbd"]["captures"],
        "public_camera": {
            "camera_frame": payload["m2b_public_rgbd"]["camera_frame"],
            "camera_intrinsics": payload["m2b_public_rgbd"][
                "camera_intrinsics"
            ],
            "camera_to_world_optical": payload["m2b_public_rgbd"][
                "camera_to_world_optical"
            ],
            "depth_semantics": payload["m2b_public_rgbd"][
                "depth_semantics"
            ],
            "base_to_camera_status": "NOT_AVAILABLE_NOT_GUESSED",
        },
        "task_spec": {
            **payload["m2b_public_rgbd"]["task_spec"],
            "instruction": "Recover the public TaskSpec target safely.",
        },
        "executed_skill_action": {
            "skill": context.previous_skill,
            "mode": "PHYSICAL_INJECTION_PROBE_NOT_MODEL_ROLLOUT",
            "action_protocol": payload["action_protocol"],
        },
        "expected_predicates": expected,
        "observed_predicates": observed,
        "failure_context": context.model_dump(mode="json"),
        "recovery_sequence": sequence,
        "recovery_execution": {
            "schema_version": "RecoveryExecutionV2",
            "sequence": sequence,
            "steps_executed": sequence,
            "public_final_predicates": _recovery_predicates(recovery),
            "successful": True,
            "cleanup_only": False,
            "retry_count": 1,
        },
        "recovery_result": "SUCCESS",
        "simulator_supervision": {
            "training_and_evaluation_only": True,
            "physical_failure_evidence": physical,
        },
        "teacher_response": None,
        "teacher_used": False,
        "policy_input_simulator_truth": False,
        "eligible_training_targets": ["failure_context", "coarse_skill"],
        "residual_training_eligible": False,
        "provenance": {
            "evidence_path": evidence_path,
            "evidence_sha256": evidence_sha256,
            "code_revision": payload["actuation_probe_source_sha256"],
        },
    }
    errors = validate_failure_recovery_episode(episode)
    if errors:
        raise ValueError(f"invalid packed episode: {errors}")
    return episode


def _recovery_predicates(recovery: dict[str, Any]) -> list[str]:
    for key in ("public_final_predicates", "public_regrasp_predicates"):
        if recovery.get(key):
            return list(recovery[key]["predicates"])
    raise ValueError("recovery lacks public final predicates")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument(
        "--evidence",
        action="append",
        required=True,
        help="FAILURE_TYPE=/absolute/remote/actuation-probe.json",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    episodes = []
    for index, item in enumerate(args.evidence, start=1):
        failure_type, path = item.split("=", 1)
        payload = remote_json(args.host, path)
        # Hash is computed remotely without copying the large RGB-D evidence.
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.host, "sha256sum", path],
            capture_output=True,
            text=True,
            check=True,
        )
        digest = completed.stdout.split()[0]
        episodes.append(
            build_episode(
                payload,
                failure_type=failure_type,
                evidence_path=path,
                evidence_sha256=digest,
                injection_seed=index,
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in episodes)
    )
    output_sha256 = hashlib.sha256(args.output.read_bytes()).hexdigest()
    report = {
        "schema_version": "M2BFailureEvidencePilotReportV1",
        "status": "PASS_PRE_DATASET_EVIDENCE_ONLY",
        "records_valid": len(episodes),
        "failure_counts": {
            failure: sum(
                episode["failure_context"]["failure_type"] == failure
                for episode in episodes
            )
            for failure in sorted(RECOVERY)
        },
        "dataset_v2_episodes_admitted": 0,
        "output_path": str(args.output),
        "output_bytes": args.output.stat().st_size,
        "output_sha256": output_sha256,
        "reason": "complete model/runtime action trajectories are not logged by the calibration probe",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
