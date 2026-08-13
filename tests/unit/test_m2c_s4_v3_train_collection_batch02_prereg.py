from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
PREREG = ROOT / "docs/decisions/M2C-S4-V3-TRAIN-COLLECTION-BATCH-02-PREREG.md"
SOURCE_COMMIT = "60b9578f3a20aab434d3bcb8d03e63c21ea09f01"
EXPECTED_EXCLUSIONS = [16012, 16022, 16025, 16026, 16063]
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


def test_preregistration_timing_stop_and_scope_are_fail_closed() -> None:
    payload = _payload()
    assert payload["schema_version"] == "M2CS4V3TrainCollectionBatch02PreregV1"
    assert payload["registered_before_any_batch02_outcome"] is True
    assert payload["batch02_outcome_observed_before_registration"] is False
    assert payload["source_commit"] == SOURCE_COMMIT
    assert payload["selection_uses_outcomes"] is False
    assert payload["stop_after_selected_keys"] == 3
    assert payload["attempt_each_selected_key_at_most_once"] is True
    assert payload["retry_or_replacement_authorized"] is False

    scope = payload["scope"]
    assert scope == {
        "role": "TRAIN",
        "split": "train",
        "scripted_public_physical_supervision_collection": True,
        "teacher_used": False,
        "model_rollout": False,
        "training_execution": False,
        "q_b_evaluation": False,
        "privileged_truth_policy_input": False,
    }


def test_selected_keys_are_recomputed_without_outcomes_from_frozen_manifest() -> None:
    payload = _payload()
    manifest_freeze = payload["manifest"]
    manifest_bytes = _git_bytes(SOURCE_COMMIT, manifest_freeze["path"])
    assert _sha256(manifest_bytes) == manifest_freeze["file_sha256"]
    manifest = json.loads(manifest_bytes)
    assert manifest["manifest_sha256"] == manifest_freeze["embedded_manifest_sha256"]

    assert payload["attempted_scene_seed_exclusions"] == EXPECTED_EXCLUSIONS
    assert payload["selection_rule"] == "manifest_order_first_unattempted_per_new_sdf_v1"
    assert payload["selection_inputs"] == [
        "manifest_order",
        "scene_seed_exclusion",
        "sdf_sha256",
    ]

    selected: list[dict[str, object]] = []
    selected_sdfs: set[str] = set()
    for record in manifest["training_keys"]:
        if record["scene_seed"] in EXPECTED_EXCLUSIONS:
            continue
        if record["sdf_sha256"] in selected_sdfs:
            continue
        selected.append({field: record[field] for field in IDENTITY_FIELDS})
        selected_sdfs.add(record["sdf_sha256"])
        if len(selected) == 3:
            break

    assert payload["selected_keys"] == selected
    assert [record["scene_seed"] for record in selected] == [16047, 16066, 16081]
    assert len(selected_sdfs) == len(selected) == 3
    manifest_by_scene = {record["scene_seed"]: record for record in manifest["training_keys"]}
    for selected_record in selected:
        source = manifest_by_scene[selected_record["scene_seed"]]
        assert source["role"] == "TRAIN"
        assert source["split"] == "train"
        assert source["teacher_used"] is False
        assert source["privileged_truth_policy_input"] is False
        assert source["outcome_observed_during_selection"] is False


def test_source_commit_matches_every_historical_implementation_binding() -> None:
    payload = _payload()
    bindings = payload["implementation_sha256"]
    assert len(bindings) == 7
    for path, expected_sha256 in bindings.items():
        assert re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
        assert _sha256(_git_bytes(SOURCE_COMMIT, path)) == expected_sha256
