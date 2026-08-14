#!/usr/bin/env python3
"""Build the outcome-blind, prereg-only Batch-20 V4 collection contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    validate_v4_training_manifest_payload,
)


ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = Path("docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-20-PREREG.json")
BATCH_ID = "m2c-s4-v4-train-batch-20"
LEDGER_NAMESPACE = "M2C_S4_V4_COLLECTION_BATCH20"
STOP_AFTER = 3
TRAINING_MANIFEST_PATH = "configs/m2c_s4_v4_training_keys_extension1.json"
YIELD_REPORT_PATH = Path("reports/m2c-s4-training-eligibility-yield-adr0025.json")
YIELD_REPORT_SHA256 = "9b59249db6def3800f1af03d26e915f77aade29f7c295bcfb679559f3f3ffee0"
ADR0025_PATH = Path("docs/decisions/ADR-0025-m2c-raw-capacity-acm-and-yield.md")
ADR0025_SHA256 = "6f27171d319e3f966c652ca9f8c0fe7c641f4bf420de58642869f9c9c805c3aa"
BATCH20_PRIOR_ATTEMPT_SOURCE_PATHS = tuple(
    sorted(authorization.BATCH20_AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES)
)
BATCH20_PRIOR_ATTEMPT_KEY_COUNT = authorization.BATCH20_AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT


class Batch20PreregBuildError(ValueError):
    """The frozen inputs cannot produce the Batch-20 preregistration."""


def _git(project_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise Batch20PreregBuildError(
            f"git {' '.join(args)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def _git_blob(project_root: Path, commit: str, path: str) -> bytes:
    return _git(project_root, "show", f"{commit}:{path}")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Batch20PreregBuildError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise Batch20PreregBuildError(f"{label} is not an object")
    return value


def _identity(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scene_seed": record["scene_seed"],
        "failure_seed": record["failure_seed"],
        "matched_key": record["matched_key"],
        "sdf_sha256": record["sdf_sha256"],
        "supervision_sha256": record["supervision_sha256"],
    }


def select_batch20_keys(*, project_root: Path, source_commit: str = "HEAD") -> list[dict[str, Any]]:
    manifest = validate_v4_training_manifest_payload(
        _json_object(
            _git_blob(project_root, source_commit, TRAINING_MANIFEST_PATH),
            label="V4 extension TRAIN manifest",
        )
    )
    prior_keys: set[str] = set()
    for path in BATCH20_PRIOR_ATTEMPT_SOURCE_PATHS:
        expected_sha256, expected_schema, expected_unique = (
            authorization.BATCH20_AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[path]
        )
        raw = _git_blob(project_root, source_commit, path)
        if _sha256(raw) != expected_sha256:
            raise Batch20PreregBuildError(f"prior report SHA-256 differs: {path}")
        report = _json_object(raw, label=path)
        if report.get("schema_version") != expected_schema:
            raise Batch20PreregBuildError(f"prior report schema differs: {path}")
        attempts = report.get("attempts")
        if not isinstance(attempts, list):
            raise Batch20PreregBuildError(f"prior report lacks attempts: {path}")
        source_keys = {
            item["identity"]["matched_key"]
            for item in attempts
            if isinstance(item, dict) and isinstance(item.get("identity"), dict)
        }
        if len(source_keys) != expected_unique:
            raise Batch20PreregBuildError(f"prior report unique-key count differs: {path}")
        if prior_keys & source_keys:
            raise Batch20PreregBuildError("authoritative prior report identity sets overlap")
        prior_keys |= source_keys
    if len(prior_keys) != BATCH20_PRIOR_ATTEMPT_KEY_COUNT:
        raise Batch20PreregBuildError("authoritative prior identity union differs")

    selected: list[dict[str, Any]] = []
    selected_sdfs: set[str] = set()
    for key in manifest.training_keys:
        if key.matched_key in prior_keys or key.sdf_sha256 in selected_sdfs:
            continue
        selected.append(_identity(key.model_dump(mode="json")))
        selected_sdfs.add(key.sdf_sha256)
        if len(selected) == STOP_AFTER:
            break
    if len(selected) != STOP_AFTER or len(selected_sdfs) != STOP_AFTER:
        raise Batch20PreregBuildError("extension cannot supply three new SDF-balanced identities")
    return selected


def build_prereg(*, project_root: Path, source_commit: str = "HEAD") -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    commit = _git(root, "rev-parse", f"{source_commit}^{{commit}}").decode().strip()
    if _sha256(_git_blob(root, commit, YIELD_REPORT_PATH.as_posix())) != YIELD_REPORT_SHA256:
        raise Batch20PreregBuildError("ADR-0025 yield report is not frozen in parent")
    if _sha256(_git_blob(root, commit, ADR0025_PATH.as_posix())) != ADR0025_SHA256:
        raise Batch20PreregBuildError("accepted ADR-0025 is not frozen in parent")

    source_snapshot, _payloads = authorization._source_snapshot_payloads(  # noqa: SLF001
        root,
        commit=commit,
    )
    profile = authorization.V4_TRAIN_MANIFEST_PROFILES[TRAINING_MANIFEST_PATH]
    manifest_file_sha256, manifest_content_sha256, required_sources = profile
    semantic_bindings = [
        {"path": path, "sha256": _sha256(_git_blob(root, commit, path))}
        for path in sorted(required_sources)
    ]
    prior_bindings = [
        {
            "path": path,
            "sha256": authorization.BATCH20_AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES[path][0],
        }
        for path in BATCH20_PRIOR_ATTEMPT_SOURCE_PATHS
    ]
    core: dict[str, Any] = {
        "attempt_each_selected_key_at_most_once": True,
        "batch_id": BATCH_ID,
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "candidate_count_bound": 8,
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "committed_source_snapshot": source_snapshot.model_dump(mode="json"),
        "container_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
        "container_image_id": (
            "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
        ),
        "governing_adr": {
            "introduced_commit": authorization.ACCEPTED_ADR_INTRODUCED_COMMIT,
            "path": authorization.ACCEPTED_ADR_PATH,
            "selected_option": "A",
            "sha256": authorization.ACCEPTED_ADR_SHA256,
            "status": "ACCEPTED_HUMAN_ADR",
        },
        "introduction_commit_paths": [PREREG_PATH.as_posix()],
        "ledger_namespace": LEDGER_NAMESPACE,
        "ledger_root": authorization.CANONICAL_COLLECTION_LEDGER_ROOT,
        "prior_attempt_identity_sources": prior_bindings,
        "recapture_policy": "NONE",
        "registered_before_selected_key_execution": True,
        "replacement_authorized": False,
        "repository_relative_path": PREREG_PATH.as_posix(),
        "retry_authorized": False,
        "runtime_registry": {
            "path": "configs/qrm_runtime_mapping_v2.yaml",
            "sha256": authorization.RUNTIME_REGISTRY_FILE_SHA256,
        },
        "s6_exclusion_manifest": {
            "path": "configs/m2c_s6_evaluation_keys.json",
            "sha256": authorization.S6_MANIFEST_FILE_SHA256,
        },
        "schema_version": "M2CS4V4SelectedKeyCollectionPreregV1",
        "scope": {
            "model_rollout": False,
            "privileged_truth_policy_input": False,
            "q_b_evaluation": False,
            "role": "TRAIN",
            "scripted_public_physical_supervision_collection": True,
            "split": "train",
            "teacher_used": False,
            "training_execution": False,
        },
        "selected_key_outcome_observed_before_registration": False,
        "selected_keys": select_batch20_keys(project_root=root, source_commit=commit),
        "selection_inputs": ["manifest_order", "prior_attempted_identity", "sdf_sha256"],
        "selection_rule": "manifest_order_first_unattempted_per_sdf_v1",
        "selection_uses_outcomes": False,
        "semantic_source_bindings": semantic_bindings,
        "status": "FROZEN_BEFORE_ANY_SELECTED_KEY_EXECUTION_OR_RESULT",
        "stop_after_selected_keys": STOP_AFTER,
        "training_manifest": {
            "path": TRAINING_MANIFEST_PATH,
            "sha256": manifest_file_sha256,
        },
        "training_manifest_content_sha256": manifest_content_sha256,
        "upstream_v4_probe_sha256": authorization.FROZEN_UPSTREAM_V4_PROBE_SHA256,
    }
    prereg = {**core, "prereg_sha256": authorization.canonical_sha256(core)}
    authorization.M2CS4V4SelectedKeyCollectionPreregV1.model_validate(prereg)
    return prereg


def prereg_bytes(prereg: Mapping[str, Any]) -> bytes:
    return (json.dumps(prereg, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o644)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("failed to publish Batch-20 preregistration")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--source-commit", default="HEAD")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = prereg_bytes(
        build_prereg(project_root=args.project_root, source_commit=args.source_commit)
    )
    if args.output is not None:
        write_create_only(args.output, payload)
    else:
        print(payload.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
