#!/usr/bin/env python3
"""Replay the A.3 query-only deployment smoke before/after margin correction.

This audit reads two immutable, canonical smoke receipts plus the governed
SRDF and the historical no-motion MoveIt home-state result.  It records the
deployment improvement without converting a remaining collision rejection
into authorization.  It never imports Isaac, loads the native module, starts
a simulator, or performs training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "M2CPhase2A3QueryOnlyDeploymentComparisonAuditV1"
SMOKE_SCHEMA_VERSION = "M2CA3QueryOnlyDeploymentSmokeV1"
SMOKE_STATUS = "PASS_QUERY_ONLY_DEPLOYMENT_SMOKE_FAIL_CLOSED_COLLISION_REJECTION"
BEFORE_RECEIPT_SHA256 = "a4035dc3fd122fcbbbe077d235d6c0276634b40cb7d4fdfd7aab5d69a697d602"
AFTER_RECEIPT_SHA256 = "6515bec6249318596a6023e92556cfbf2351c9bd0b1bd43fe8d635800b02cbb6"
BEFORE_COMMIT = "fcccc9c1d656133b95b0cbe213a944c980d54fb0"
AFTER_COMMIT = "7ea1b4319236a7e30e8a999f883b3b7fbaf30238"
RUNTIME_IMAGE_ID = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
BEFORE_NUMERIC_CONFIGURATION_SHA256 = (
    "1193e1bfab421cc69373e6e41b350c26e69a4a07ca17e66f92271aea365427d0"
)
AFTER_NUMERIC_CONFIGURATION_SHA256 = (
    "a8a041e7054442cbb8b1b8102a474331430015ed58dd2aae9c61339ec9a5883f"
)
CONTROLLED_PANDA_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
CONTROLLED_PANDA_SRDF_SHA256 = "80948370d547cb320e49d42ffc0467e082112c09f2984700b489def88526a386"
MOVEIT_HOME_REPORT_SHA256 = "6494f629b476770ed90862bef234789a06787f43d5b49e89c2cc3b1aec135537"
JOINT_STATE_SEQUENCE_SHA256 = "a9987a164b4ed7598f2b581c15cf9125f50b442489cd2002b429deb248927e23"
REMAINING_REJECTED_PAIRS = (
    ("/World/Robot/panda_hand", 0, "/World/Robot/panda_link7", 0),
    ("/World/Robot/panda_link2", 0, "/World/Robot/panda_link4", 0),
    ("/World/Robot/panda_link5", 0, "/World/Robot/panda_link7", 0),
)
REMAINING_BLOCKERS = (
    "A3_STATIC_HOME_SELF_COLLISION_PREFLIGHT_REJECTED",
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
)


class ComparisonAuditFailure(RuntimeError):
    """The query-only smoke receipts differ, drifted, or overclaim readiness."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ComparisonAuditFailure(f"audit input is not single-link regular: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise ComparisonAuditFailure(f"audit input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonAuditFailure(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict) or raw != canonical_json_bytes(value) + b"\n":
        raise ComparisonAuditFailure(f"{label} is not canonical object JSON")
    return value


def _pair_identity(item: dict[str, Any]) -> tuple[str, int, str, int]:
    try:
        return (
            str(item["link_a"]),
            int(item["child_a"]),
            str(item["link_b"]),
            int(item["child_b"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ComparisonAuditFailure("rejected pair identity is malformed") from exc


def _validate_smoke(
    value: dict[str, Any],
    *,
    label: str,
    expected_commit: str,
    expected_numeric_sha256: str,
    expected_clear: int,
    expected_rejected: int,
) -> tuple[tuple[str, int, str, int], ...]:
    exact_top_level = {
        "schema_version",
        "status",
        "immutable_commit",
        "runtime",
        "source_bindings",
        "native_closure",
        "query",
        "evidence_claims",
        "remaining_blockers",
    }
    if set(value) != exact_top_level:
        raise ComparisonAuditFailure(f"{label} smoke fields differ")
    runtime = value["runtime"]
    claims = value["evidence_claims"]
    query = value["query"]
    if (
        value["schema_version"] != SMOKE_SCHEMA_VERSION
        or value["status"] != SMOKE_STATUS
        or value["immutable_commit"] != expected_commit
        or runtime.get("container_image_id") != RUNTIME_IMAGE_ID
        or runtime.get("platform_system") != "Linux"
        or runtime.get("platform_machine") != "x86_64"
        or runtime.get("isaac_or_kit_module_loaded") is not False
        or claims
        != {
            "deployment_query_completed": True,
            "static_state_preflight_clear": False,
            "formal_execution_eligible": False,
            "isaac_started": False,
            "physical_execution_performed": False,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "training_performed": False,
            "q_b_evaluation_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        or query.get("joint_state_sequence_sha256") != JOINT_STATE_SEQUENCE_SHA256
        or query.get("numeric_configuration_sha256") != expected_numeric_sha256
        or query.get("request_segment_count") != 76
        or query.get("clear_result_count") != expected_clear
        or query.get("collision_rejection_count") != expected_rejected
        or query.get("query_failure_count") != 0
        or query.get("receipt_status") != "REJECT"
        or expected_clear + expected_rejected != 76
    ):
        raise ComparisonAuditFailure(f"{label} smoke contract/result differs")
    source_bindings = value["source_bindings"]
    if (
        source_bindings.get("robot_ws/src/xh_sim/urdf/panda_controlled.urdf")
        != CONTROLLED_PANDA_URDF_SHA256
        or source_bindings.get("robot_ws/src/xh_sim/config/m1a_panda.srdf")
        != CONTROLLED_PANDA_SRDF_SHA256
    ):
        raise ComparisonAuditFailure(f"{label} governed robot model differs")
    rejected = query.get("rejected_pairs")
    if not isinstance(rejected, list) or len(rejected) != expected_rejected:
        raise ComparisonAuditFailure(f"{label} rejected-pair count differs")
    identities = tuple(_pair_identity(item) for item in rejected)
    if len(set(identities)) != len(identities):
        raise ComparisonAuditFailure(f"{label} rejected pair repeats")
    for item in rejected:
        if (
            item.get("status") != "REJECT_COLLISION"
            or item.get("failure_code") != -1
            or item.get("time_of_impact") is not None
            or item.get("discrete_start_clear") is not False
            or item.get("discrete_end_clear") is not False
            or item.get("continuous_query_completed") is not False
        ):
            raise ComparisonAuditFailure(f"{label} rejection semantics differ")
    return identities


def _srdf_disabled_pairs(srdf_raw: bytes) -> set[tuple[str, str]]:
    try:
        root = ET.fromstring(srdf_raw)
    except ET.ParseError as exc:
        raise ComparisonAuditFailure("controlled Panda SRDF is malformed") from exc
    pairs = {
        tuple(sorted((item.attrib["link1"], item.attrib["link2"])))
        for item in root.findall("disable_collisions")
    }
    if len(pairs) != 11:
        raise ComparisonAuditFailure("controlled Panda SRDF ACM pair count differs")
    return pairs


def build_report(
    project_root: Path,
    before_receipt_path: Path,
    after_receipt_path: Path,
) -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    before_raw = read_regular_file_once(before_receipt_path.resolve(strict=True))
    after_raw = read_regular_file_once(after_receipt_path.resolve(strict=True))
    if _sha256(before_raw) != BEFORE_RECEIPT_SHA256:
        raise ComparisonAuditFailure("before smoke receipt SHA-256 differs")
    if _sha256(after_raw) != AFTER_RECEIPT_SHA256:
        raise ComparisonAuditFailure("after smoke receipt SHA-256 differs")
    before = _canonical_object(before_raw, label="before smoke receipt")
    after = _canonical_object(after_raw, label="after smoke receipt")
    before_pairs = _validate_smoke(
        before,
        label="before",
        expected_commit=BEFORE_COMMIT,
        expected_numeric_sha256=BEFORE_NUMERIC_CONFIGURATION_SHA256,
        expected_clear=61,
        expected_rejected=15,
    )
    after_pairs = _validate_smoke(
        after,
        label="after",
        expected_commit=AFTER_COMMIT,
        expected_numeric_sha256=AFTER_NUMERIC_CONFIGURATION_SHA256,
        expected_clear=73,
        expected_rejected=3,
    )
    if after_pairs != REMAINING_REJECTED_PAIRS or not set(after_pairs).issubset(before_pairs):
        raise ComparisonAuditFailure("remaining rejection set differs")

    srdf_path = root / "robot_ws/src/xh_sim/config/m1a_panda.srdf"
    srdf_raw = read_regular_file_once(srdf_path)
    if _sha256(srdf_raw) != CONTROLLED_PANDA_SRDF_SHA256:
        raise ComparisonAuditFailure("controlled Panda SRDF SHA-256 differs")
    disabled = _srdf_disabled_pairs(srdf_raw)
    remaining_link_pairs = {
        tuple(sorted((left.rsplit("/", 1)[-1], right.rsplit("/", 1)[-1])))
        for left, _, right, _ in after_pairs
    }
    if disabled.intersection(remaining_link_pairs):
        raise ComparisonAuditFailure("remaining rejection was incorrectly ACM-disabled")

    moveit_path = root / "reports/m1a-home-self-collision.json"
    moveit_raw = read_regular_file_once(moveit_path)
    if _sha256(moveit_raw) != MOVEIT_HOME_REPORT_SHA256:
        raise ComparisonAuditFailure("MoveIt home-state report SHA-256 differs")
    try:
        moveit = json.loads(moveit_raw)
    except json.JSONDecodeError as exc:
        raise ComparisonAuditFailure("MoveIt home-state report is unreadable") from exc
    runtime = moveit.get("runtime", {})
    if (
        moveit.get("status") != "HOME_SELF_COLLISION_VERIFIED"
        or moveit.get("local_gazebo_urdf_sha256") != CONTROLLED_PANDA_URDF_SHA256
        or runtime.get("valid") is not True
        or runtime.get("contacts") != []
        or runtime.get("arm_joint_positions_rad") != [0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0]
        or runtime.get("finger_joint_positions_m") != [0.02, 0.02]
        or runtime.get("method") != "MOVEIT_CHECK_STATE_VALIDITY_NO_MOTION_COMMAND"
    ):
        raise ComparisonAuditFailure("MoveIt home-state evidence differs")
    if any("finger" in left or "finger" in right for left, _, right, _ in after_pairs):
        raise ComparisonAuditFailure("remaining pair unexpectedly depends on finger opening")

    removed_pairs = tuple(item for item in before_pairs if item not in set(after_pairs))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_DEPLOYMENT_QUERY_REPLAY_BLOCKED_STATIC_HOME_COLLISION",
        "evidence_bindings": {
            "before_smoke_receipt_sha256": BEFORE_RECEIPT_SHA256,
            "after_smoke_receipt_sha256": AFTER_RECEIPT_SHA256,
            "controlled_panda_srdf_sha256": CONTROLLED_PANDA_SRDF_SHA256,
            "moveit_home_report_sha256": MOVEIT_HOME_REPORT_SHA256,
        },
        "before": {
            "immutable_commit": BEFORE_COMMIT,
            "numeric_configuration_sha256": BEFORE_NUMERIC_CONFIGURATION_SHA256,
            "builder_image_id": before["native_closure"]["builder_image_id"],
            "native_shared_object_sha256": before["native_closure"]["native_shared_object_sha256"],
            "request_segment_count": 76,
            "clear_result_count": 61,
            "collision_rejection_count": 15,
        },
        "after": {
            "immutable_commit": AFTER_COMMIT,
            "numeric_configuration_sha256": AFTER_NUMERIC_CONFIGURATION_SHA256,
            "builder_image_id": after["native_closure"]["builder_image_id"],
            "native_shared_object_sha256": after["native_closure"]["native_shared_object_sha256"],
            "request_segment_count": 76,
            "clear_result_count": 73,
            "collision_rejection_count": 3,
            "remaining_rejected_pairs": [
                {
                    "link_a": left,
                    "child_a": child_a,
                    "link_b": right,
                    "child_b": child_b,
                }
                for left, child_a, right, child_b in after_pairs
            ],
        },
        "comparison": {
            "same_runtime_image": before["runtime"]["container_image_id"]
            == after["runtime"]["container_image_id"]
            == RUNTIME_IMAGE_ID,
            "same_joint_state_sequence": before["query"]["joint_state_sequence_sha256"]
            == after["query"]["joint_state_sequence_sha256"]
            == JOINT_STATE_SEQUENCE_SHA256,
            "rejection_count_reduction": 12,
            "removed_rejected_pairs": [
                {
                    "link_a": left,
                    "child_a": child_a,
                    "link_b": right,
                    "child_b": child_b,
                }
                for left, child_a, right, child_b in removed_pairs
            ],
            "remaining_pairs_are_not_srdf_acm_disabled": True,
            "moveit_same_arm_state_reports_clear": True,
            "moveit_finger_state_m": [0.02, 0.02],
            "smoke_finger_state_m": [0.04, 0.04],
            "remaining_pairs_are_finger_independent": True,
        },
        "evidence_claims": {
            "permission_and_query_deployment_path_completed": True,
            "static_state_preflight_clear": False,
            "formal_execution_eligible": False,
            "isaac_started_in_accepted_receipt": False,
            "physical_execution_performed": False,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "training_performed": False,
            "q_b_evaluation_performed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "production_binding_set": False,
        },
        "remaining_blockers": list(REMAINING_BLOCKERS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--before-receipt", type=Path, required=True)
    parser.add_argument("--after-receipt", type=Path, required=True)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.project_root, args.before_receipt, args.after_receipt)
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.expected_json is not None:
            if read_regular_file_once(args.expected_json).decode("utf-8") != payload:
                raise ComparisonAuditFailure("expected comparison JSON differs from replay")
    except (ComparisonAuditFailure, OSError) as exc:
        print(f"BLOCKED: {exc}")
        return 2
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
