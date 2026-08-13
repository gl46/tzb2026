from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
PREREG = ROOT / "docs/decisions/M2C-S4-V3-TRAIN-COLLECTION-BATCH-03-PREREG.md"
PREREG_SOURCE_COMMIT = "373c9ddc18e64c856964f362d87b5a68f5d2ba0b"
RUNTIME_COMMIT = "60b9578f3a20aab434d3bcb8d03e63c21ea09f01"
EXPECTED_ATTEMPTED_SCENES = [16012, 16022, 16025, 16026, 16047, 16063, 16066, 16081]
IDENTITY_FIELDS = (
    "scene_seed",
    "failure_seed",
    "matched_key",
    "sdf_sha256",
    "supervision_sha256",
)


def _payload() -> dict[str, object]:
    match = re.search(r"```json\n(.*?)\n```", PREREG.read_text(), re.DOTALL)
    assert match is not None
    payload = json.loads(match.group(1))
    assert isinstance(payload, dict)
    return payload


def _git_bytes(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_timing_stop_retry_and_scope_are_fail_closed() -> None:
    payload = _payload()
    assert payload["schema_version"] == "M2CS4V3TrainCollectionBatch03PreregV1"
    assert payload["registered_after_observed_unique_train_keys"] == 8
    assert payload["registered_before_any_selected_key_result"] is True
    assert payload["selected_key_result_observed_before_registration"] is False
    assert payload["preregistration_source_commit"] == PREREG_SOURCE_COMMIT
    assert payload["authorized_runtime_commit"] == RUNTIME_COMMIT
    assert payload["selection_uses_attempt_outcomes"] is False
    assert payload["maximum_selected_keys"] == payload["stop_after_selected_keys"] == 3
    assert payload["attempt_each_selected_key_at_most_once"] is True
    assert payload["retry_authorized"] is False
    assert payload["replacement_authorized"] is False
    assert payload["collection_executed_by_preregistration"] is False
    assert payload["runtime_changed_by_preregistration"] is False
    assert payload["scope"] == {
        "role": "TRAIN",
        "split": "train",
        "scripted_public_physical_supervision_collection": True,
        "teacher_used": False,
        "model_rollout": False,
        "training_execution": False,
        "q_b_evaluation": False,
        "privileged_truth_policy_input": False,
    }


def test_selection_recomputes_from_manifest_and_eight_identities_without_outcomes() -> None:
    payload = _payload()
    manifest_binding = payload["manifest"]
    manifest_bytes = _git_bytes(PREREG_SOURCE_COMMIT, manifest_binding["path"])
    assert _sha256(manifest_bytes) == manifest_binding["file_sha256"]
    manifest = json.loads(manifest_bytes)
    assert manifest["manifest_sha256"] == manifest_binding["embedded_manifest_sha256"]

    audit_binding = payload["attempt_identity_audit"]
    audit_bytes = _git_bytes(PREREG_SOURCE_COMMIT, audit_binding["path"])
    assert _sha256(audit_bytes) == audit_binding["file_sha256"]
    audit = json.loads(audit_bytes)
    assert audit["schema_version"] == audit_binding["schema_version"]
    assert audit["scope"]["unique_train_keys_attempted"] == 8
    attempted_scenes = {attempt["identity"]["scene_seed"] for attempt in audit["attempts"]}
    attempted_keys = {attempt["identity"]["matched_key"] for attempt in audit["attempts"]}
    assert sorted(attempted_scenes) == EXPECTED_ATTEMPTED_SCENES
    assert len(attempted_keys) == audit_binding["unique_train_keys_attempted"] == 8
    assert payload["attempted_scene_seed_exclusions"] == EXPECTED_ATTEMPTED_SCENES
    assert payload["selection_rule"] == "manifest_order_first_unattempted_per_sdf_v1"
    assert payload["selection_inputs"] == [
        "manifest_order",
        "attempted_key_identity",
        "sdf_sha256",
    ]

    selected: list[dict[str, object]] = []
    selected_sdfs: set[str] = set()
    for record in manifest["training_keys"]:
        if record["scene_seed"] in attempted_scenes:
            continue
        if record["sdf_sha256"] in selected_sdfs:
            continue
        selected.append({field: record[field] for field in IDENTITY_FIELDS})
        selected_sdfs.add(record["sdf_sha256"])
        if len(selected) == payload["maximum_selected_keys"]:
            break

    assert payload["selected_keys"] == selected
    assert [record["scene_seed"] for record in selected] == [16073, 16085, 16102]
    assert len(selected_sdfs) == len(selected) == 3
    assert not {record["matched_key"] for record in selected} & attempted_keys
    manifest_by_scene = {record["scene_seed"]: record for record in manifest["training_keys"]}
    for selected_record in selected:
        source = manifest_by_scene[selected_record["scene_seed"]]
        assert source["role"] == "TRAIN"
        assert source["split"] == "train"
        assert source["teacher_used"] is False
        assert source["privileged_truth_policy_input"] is False
        assert source["outcome_observed_during_selection"] is False


def test_runtime_bytes_are_unchanged_between_runtime_and_prereg_source_commits() -> None:
    paths = (
        "src/xh_agent/policy/qrm_lite/public_tracks_v3.py",
        "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py",
        "scripts/m2c/derive_model_owned_chain_probe.py",
        "scripts/m2c/materialize_s4_s6_scenes.py",
        "scripts/m2c/run_path_blocked_collection_worker.py",
        "scripts/m2c/package_path_blocked_collection.py",
    )
    for path in paths:
        runtime_bytes = _git_bytes(RUNTIME_COMMIT, path)
        assert _git_bytes(PREREG_SOURCE_COMMIT, path) == runtime_bytes
        assert (ROOT / path).read_bytes() == runtime_bytes
