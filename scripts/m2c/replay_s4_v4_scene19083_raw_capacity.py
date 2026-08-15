#!/usr/bin/env python3
"""Replay immutable scene 19083 under the ADR-0025 raw-capacity schema.

This command is offline-only.  It upgrades the eight in-memory raw capture
envelopes from the historical V1 capacity gate to V2, replays public tracking
and K=8 candidate construction, and then applies the unchanged training
eligibility predicate.  It never writes into the evidence tree and never
changes the recorded physical outcome.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from pydantic import ValidationError

from m2c.audit_s4_v4_batch08_collection import (
    build_report as build_historical_batch08_report,
    read_regular_file_once,
    report_bytes,
    sha256_bytes,
)
from m2c.qwen_coarse_v4 import validate_key_manifests_v4
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2CV4RawPublicAssociationCaptureV1,
    M2CV4RawPublicAssociationCaptureV2,
    build_path_blocked_supervised_dataset_v4,
    canonical_sha256,
    host_replay_probe_chain_v4,
    package_probe_chain_v4,
)


ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = "docs/decisions/ADR-0025-m2c-raw-capacity-acm-and-yield.md"
ADR_SHA256 = "6f27171d319e3f966c652ca9f8c0fe7c641f4bf420de58642869f9c9c805c3aa"
ADR_COMMIT = "abf66b1084e3820a327c29cb79ebf68af0252fd0"
RAW_CAPACITY_IMPLEMENTATION_COMMIT = "e7d0564cd603cc2b020748aef0534ac0f2a5e5ab"
REPORT_IMPLEMENTATION_COMMIT = "93f72126e6f1b831b08852dfb7300f79cabe3aba"
HISTORICAL_REPORT_PATH = "reports/m2c-s4-v4-batch08-collection.json"
HISTORICAL_REPORT_SHA256 = "226761a056c6c3a127784019147e49b3e6e301f72d4b9711e222cd7c939a2894"
RAW_PROBE_RELATIVE = Path(
    "raw/train/"
    "m2c-s4-v4-train-dc5715316cad6e42faf074a9b6715f76e2df7bd0d267c3cf88037fdc5f8c50a7/"
    "probe/actuation-probe.json"
)
RAW_PROBE_SHA256 = "9f3144467f247131240c5e152a8317e578e69c4c29192e0b64e4ddb78e5fef89"
MATCHED_KEY = "m2c-s4-v4-train-dc5715316cad6e42faf074a9b6715f76e2df7bd0d267c3cf88037fdc5f8c50a7"
EXPECTED_DETECTION_COUNTS = [7, 13, 11, 7, 8, 9, 10, 10]
RUNTIME_REGISTRY_SHA256 = "3572f80f1597b7f3bdffb1f8aad90d5baeb086b25c371b88511bc58444813359"
RAW_CAPACITY_SOURCE_BINDINGS = {
    "scripts/m2c/derive_model_owned_chain_probe.py": (
        "847fe5d02008cf6b317789c38d56bec5f7f65ced369f16f8905b8f4575b2ef96"
    ),
    "scripts/m2c/qwen_coarse_v4.py": (
        "dc869c8325dae1c21fd999eff141bb5f2a2b2acb2b644b47067da38c39250298"
    ),
    "src/xh_agent/perception/public_track_associator_v2.py": (
        "1ee6ccaf595a3b74d9762f34721807f7aa107d49237f820a396c846902214964"
    ),
    "src/xh_agent/policy/qrm_lite/path_blocked_collection_v4.py": (
        "467ce96ea2b5db7b84904bbe489e4436f43f82587acefbb56027bd927119216c"
    ),
    "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v4.py": (
        "49e60395a0c31270bd19db48af108f59b2ad6a81a6d53e9b2a096a74b27c2d69"
    ),
}


class Scene19083ReplayError(ValueError):
    """The immutable evidence cannot support the authorized offline replay."""


def _git_blob(*, project_root: Path, commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise Scene19083ReplayError(f"Git blob is unavailable: {commit}:{relative_path}")
    return result.stdout


def _verify_committed_sources(project_root: Path) -> list[dict[str, str]]:
    adr = read_regular_file_once(project_root / ADR_PATH)
    if (
        sha256_bytes(adr) != ADR_SHA256
        or _git_blob(
            project_root=project_root,
            commit=ADR_COMMIT,
            relative_path=ADR_PATH,
        )
        != adr
    ):
        raise Scene19083ReplayError("accepted ADR-0025 bytes or commit binding changed")
    records: list[dict[str, str]] = []
    for path, expected_sha256 in sorted(RAW_CAPACITY_SOURCE_BINDINGS.items()):
        committed = _git_blob(
            project_root=project_root,
            commit=RAW_CAPACITY_IMPLEMENTATION_COMMIT,
            relative_path=path,
        )
        if sha256_bytes(committed) != expected_sha256:
            raise Scene19083ReplayError(f"raw-capacity implementation binding changed: {path}")
        records.append({"path": path, "sha256": expected_sha256})
    return records


def _upgrade_captures(
    raw_chain: Mapping[str, Any],
    raw_captures: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if len(raw_captures) != 8:
        raise Scene19083ReplayError("scene 19083 does not contain exactly eight raw captures")
    chain = copy.deepcopy(dict(raw_chain))
    steps = chain.get("steps")
    if not isinstance(steps, list) or len(steps) != 8:
        raise Scene19083ReplayError("scene 19083 does not contain exactly eight raw steps")
    upgraded: list[dict[str, Any]] = []
    transformations: list[dict[str, Any]] = []
    for index, (raw, step) in enumerate(zip(raw_captures, steps, strict=True)):
        original = dict(raw)
        original_digest = canonical_sha256(original)
        observation = step.get("observation") if isinstance(step, Mapping) else None
        if (
            not isinstance(observation, dict)
            or observation.get("capture_receipt_sha256") != original_digest
        ):
            raise Scene19083ReplayError("raw step does not bind the original V1 capture")
        try:
            # Validate every V1 field without allowing the historical max=8
            # to reinterpret over-capacity captures.
            M2CV4RawPublicAssociationCaptureV1.model_validate({**original, "detections": []})
            payload = {
                **original,
                "schema_version": "M2CV4RawPublicAssociationCaptureV2",
                "raw_detection_capacity_revision": ("M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1"),
                "max_raw_public_detections": 32,
            }
            parsed = M2CV4RawPublicAssociationCaptureV2.model_validate(payload)
        except ValidationError as error:
            raise Scene19083ReplayError("raw capture failed the ADR-0025 schema") from error
        current = parsed.model_dump(mode="json")
        current_digest = canonical_sha256(current)
        observation["capture_receipt_sha256"] = current_digest
        upgraded.append(current)
        transformations.append(
            {
                "capture_index": index,
                "detection_count": len(parsed.detections),
                "original_schema_version": original["schema_version"],
                "original_capture_sha256": original_digest,
                "upgraded_schema_version": parsed.schema_version,
                "upgraded_capture_sha256": current_digest,
                "detections_sha256": canonical_sha256(original["detections"]),
                "proprioception_sha256": canonical_sha256(original["proprioception_interval"]),
                "truncated_or_filtered": False,
            }
        )
    if [item["detection_count"] for item in transformations] != EXPECTED_DETECTION_COUNTS:
        raise Scene19083ReplayError("scene 19083 raw detection counts changed")
    return chain, upgraded, transformations


def _candidate_track_ids(step: Any) -> set[str]:
    return {item.track_id for item in step.observation.candidate_payload.candidates}


def build_report(*, evidence_root: Path, project_root: Path = ROOT) -> dict[str, Any]:
    source_bindings = _verify_committed_sources(project_root)
    historical_bytes = read_regular_file_once(project_root / HISTORICAL_REPORT_PATH)
    if sha256_bytes(historical_bytes) != HISTORICAL_REPORT_SHA256:
        raise Scene19083ReplayError("historical Batch-08 report bytes changed")
    historical = build_historical_batch08_report(
        evidence_root=evidence_root,
        project_root=project_root,
    )
    attempt = historical["attempts"][2]
    if (
        attempt.get("identity", {}).get("matched_key") != MATCHED_KEY
        or attempt.get("raw_probe_sha256") != RAW_PROBE_SHA256
        or attempt.get("raw_chain_final_task_success") is not False
        or attempt.get("final_controller_gate") != "REJECTED"
        or attempt.get("final_execution_status") != "CONTACT_GATE_REJECTED"
        or attempt.get("physical_skill_receipts") != 8
        or attempt.get("collision_or_safety_violations") != 0
    ):
        raise Scene19083ReplayError("historical Batch-08 physical conclusion changed")

    raw_probe_path = evidence_root.resolve(strict=True) / RAW_PROBE_RELATIVE
    raw_probe_bytes = read_regular_file_once(raw_probe_path)
    if sha256_bytes(raw_probe_bytes) != RAW_PROBE_SHA256:
        raise Scene19083ReplayError("scene 19083 immutable raw probe bytes changed")
    raw_probe = json.loads(raw_probe_bytes)
    if not isinstance(raw_probe, dict):
        raise Scene19083ReplayError("scene 19083 raw probe is not an object")
    raw_chain = raw_probe.get("m2c_path_blocked_physical_chain")
    raw_captures = raw_probe.get("m2c_v4_raw_association_captures")
    authorization = raw_probe.get("m2c_v4_collection_authorization")
    if not isinstance(raw_chain, Mapping) or not isinstance(raw_captures, list):
        raise Scene19083ReplayError("scene 19083 raw chain or captures are absent")
    if not isinstance(authorization, Mapping):
        raise Scene19083ReplayError("scene 19083 collection authorization is absent")
    if (
        raw_chain.get("final_task_success") is not False
        or raw_probe.get("not_policy_rollout") is not True
        or authorization.get("teacher_used") is not False
        or authorization.get("privileged_truth_policy_input") is not False
    ):
        raise Scene19083ReplayError("scene 19083 outcome or public-only boundary changed")

    manifest_audit, training_manifest, s6_manifest = validate_key_manifests_v4(
        project_root / "configs/m2c_s4_v4_training_keys.json",
        project_root / "configs/m2c_s6_evaluation_keys.json",
    )
    keys = [item for item in training_manifest.training_keys if item.matched_key == MATCHED_KEY]
    if len(keys) != 1 or keys[0].scene_seed != 19083 or keys[0].failure_seed != 190837:
        raise Scene19083ReplayError("scene 19083 does not match one frozen TRAIN identity")

    replay_chain_raw, upgraded_captures, transformations = _upgrade_captures(
        raw_chain,
        raw_captures,
    )
    capture_source_sha256 = str(authorization.get("derived_probe_sha256"))
    if capture_source_sha256 != "5ce42344184749b3fff627b3a25cd161ef215b155fe7aaafe63b2b30710bc8d1":
        raise Scene19083ReplayError("scene 19083 capture source binding changed")
    replayed = host_replay_probe_chain_v4(
        replay_chain_raw,
        upgraded_captures,
        training_key=keys[0],
        training_manifest=training_manifest,
        capture_source_implementation_sha256=capture_source_sha256,
    )
    if replayed.final_task_success is not False or len(replayed.steps) != 8:
        raise Scene19083ReplayError("offline replay changed the physical outcome or step count")
    candidate_counts = [
        len(step.observation.candidate_payload.candidates) for step in replayed.steps
    ]
    perception_track_counts = [len(step.observation.perception_tracks) for step in replayed.steps]
    if any(count > 8 for count in candidate_counts):
        raise Scene19083ReplayError("offline replay changed the final K=8 candidate bound")

    evidence = package_probe_chain_v4(
        replayed.model_dump(mode="json"),
        training_manifest=training_manifest,
        s6_manifest=s6_manifest,
        runtime_registry_sha256=RUNTIME_REGISTRY_SHA256,
        source_evidence_uri=f"evidence://m2c-s4-v4-batch08-complete/{RAW_PROBE_RELATIVE}",
        source_evidence_sha256=RAW_PROBE_SHA256,
    )
    dataset = build_path_blocked_supervised_dataset_v4(
        evidence,
        training_manifest=training_manifest,
        s6_manifest=s6_manifest,
    )
    if (
        dataset.status != "EMPTY"
        or dataset.validation.model_training_eligible is not False
        or dataset.samples
    ):
        raise Scene19083ReplayError("offline replay improperly created an eligible training row")

    physical_receipts = [receipt for step in replayed.steps for receipt in step.physical_receipts]
    report_script = Path(__file__).resolve()
    return {
        "schema_version": "M2CS4V4Scene19083OfflineRawCapacityReplayV1",
        "status": "PASS_OFFLINE_REPLAY_EXCLUDED_UNCHANGED_PHYSICAL_FAILURE",
        "authorization": {
            "adr_path": ADR_PATH,
            "adr_sha256": ADR_SHA256,
            "adr_commit": ADR_COMMIT,
            "selected_option": "A",
            "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
            "max_raw_public_detections": 32,
            "numeric_provenance": "4_X_FROZEN_INDUSTRIAL_CYLINDER_SCENE_MAX_8_ENTITIES",
            "offline_replay_only": True,
            "physical_retry_or_replacement_authorized": False,
            "outcome_reinterpretation_authorized": False,
        },
        "implementation": {
            "commit": RAW_CAPACITY_IMPLEMENTATION_COMMIT,
            "source_bindings": source_bindings,
            "report_script_path": report_script.relative_to(project_root).as_posix(),
            "report_script_sha256": sha256_bytes(
                _git_blob(
                    project_root=project_root,
                    commit=REPORT_IMPLEMENTATION_COMMIT,
                    relative_path=report_script.relative_to(project_root).as_posix(),
                )
            ),
        },
        "source_evidence": {
            "historical_report_path": HISTORICAL_REPORT_PATH,
            "historical_report_sha256": HISTORICAL_REPORT_SHA256,
            "raw_probe_relative_path": RAW_PROBE_RELATIVE.as_posix(),
            "raw_probe_sha256": RAW_PROBE_SHA256,
            "matched_key": MATCHED_KEY,
            "scene_seed": 19083,
            "failure_seed": 190837,
            "physical_skill_receipt_count": len(physical_receipts),
            "collision_or_safety_violations": sum(
                int(receipt.collision_or_safety_violation) for receipt in physical_receipts
            ),
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        },
        "schema_upgrade": {
            "source_schema": "M2CV4RawPublicAssociationCaptureV1",
            "replay_schema": "M2CV4RawPublicAssociationCaptureV2",
            "capture_count": 8,
            "raw_detection_counts": EXPECTED_DETECTION_COUNTS,
            "all_detections_passed_without_truncation_or_filtering": True,
            "transformations": transformations,
        },
        "host_replay": {
            "passed": True,
            "step_count": len(replayed.steps),
            "deployment_binding_sha256": replayed.expected_association_deployment_sha256,
            "association_session_receipt_sha256": (
                replayed.steps[-1].expected_association_session_receipt_sha256
            ),
            "perception_track_counts": perception_track_counts,
            "candidate_counts": candidate_counts,
            "final_candidate_k": 8,
            "selected_track_in_candidate_k8": [
                (
                    step.public_blocker_track_id
                    if index <= 4
                    else step.public_task_target_track_id
                    if index >= 6
                    else None
                )
                in _candidate_track_ids(step)
                if index <= 4 or index >= 6
                else None
                for index, step in enumerate(replayed.steps)
            ],
            "training_manifest_file_sha256": (manifest_audit.training_manifest_file_sha256),
            "s6_manifest_file_sha256": manifest_audit.s6_manifest_file_sha256,
        },
        "unchanged_outcome": {
            "source_final_task_success": False,
            "replayed_final_task_success": replayed.final_task_success,
            "terminal_controller_gate": physical_receipts[-1].controller_gate,
            "terminal_execution_status": "CONTACT_GATE_REJECTED",
            "training_validation_status": dataset.validation.status,
            "training_sample_eligible": dataset.validation.model_training_eligible,
            "training_sample_packaged": False,
            "persisted_training_sample_count": 0,
            "validation_exclusion_reasons": dataset.validation.exclusion_reasons,
            "offline_dataset_status": dataset.status,
            "offline_dataset_sample_count": len(dataset.samples),
            "offline_dataset_sha256": dataset.dataset_sha256,
            "pure_model_success_episodes": None,
        },
        "model_rollout": False,
        "training_executed": False,
        "formal_q_b_evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def markdown_bytes(report: Mapping[str, Any]) -> bytes:
    outcome = report["unchanged_outcome"]
    replay = report["host_replay"]
    lines = [
        "# M2C S4 V4 scene 19083 offline raw-capacity replay",
        "",
        f"- Status: **{report['status']}**",
        "- Scope: offline replay only; no Isaac launch, retry, replacement, training, or Q-B evaluation",
        "- ADR-0025 Option A: raw capacity 32; final candidate K remains 8",
        "- Immutable raw counts: `7, 13, 11, 7, 8, 9, 10, 10`",
        f"- Host replay: {replay['step_count']} steps, candidate counts `{replay['candidate_counts']}`",
        f"- Physical outcome: `final_task_success={str(outcome['replayed_final_task_success']).lower()}`; terminal `CONTACT_GATE_REJECTED`",
        f"- Training eligibility: `{str(outcome['training_sample_eligible']).lower()}`; persisted samples: 0",
        f"- Exclusion reasons: `{outcome['validation_exclusion_reasons']}`",
        "- Teacher used: false; privileged simulator truth as policy input: false",
        "",
        "The replay makes the immutable public capture history parseable under the approved",
        "32-detection envelope. It does not reinterpret the physical failure or create a",
        "training row. The unchanged K=8 and training predicates remain authoritative.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _publish_create_only(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o444,
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise Scene19083ReplayError("short write publishing replay report")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--expected-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    args = parser.parse_args()
    report = build_report(evidence_root=args.evidence_root)
    encoded = report_bytes(report)
    markdown = markdown_bytes(report)
    if args.expected_json is not None and read_regular_file_once(args.expected_json) != encoded:
        raise SystemExit("scene 19083 replay differs from expected JSON")
    if args.output_json is not None:
        _publish_create_only(args.output_json, encoded)
    if args.output_markdown is not None:
        _publish_create_only(args.output_markdown, markdown)
    if args.output_json is None and args.output_markdown is None:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
