from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch23_prereg import (
    BATCH23_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH23_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    TRAINING_MANIFEST_PATH,
    build_prereg,
    prereg_bytes,
    select_batch23_keys,
    write_create_only,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]
SOURCE_COMMIT = "HEAD"


def test_batch23_binds_complete_fifty_nine_identity_prior_inventory() -> None:
    assert BATCH23_PRIOR_ATTEMPT_KEY_COUNT == 59
    assert set(BATCH23_PRIOR_ATTEMPT_SOURCE_PATHS) == set(
        authorization.BATCH23_AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES
    )
    assert "reports/m2c-s4-v4-batch22-collection.json" in BATCH23_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch23_selects_three_new_sdf_balanced_keys_without_outcomes() -> None:
    selected = select_batch23_keys(project_root=ROOT, source_commit=SOURCE_COMMIT)
    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (22112, 221127),
        (22141, 221417),
        (22163, 221637),
    ]


def test_batch23_prereg_binds_extension_yield_and_no_retry_contract() -> None:
    prereg = build_prereg(project_root=ROOT, source_commit=SOURCE_COMMIT)
    profile = authorization.V4_TRAIN_MANIFEST_PROFILES[TRAINING_MANIFEST_PATH]
    assert prereg["training_manifest"] == {
        "path": TRAINING_MANIFEST_PATH,
        "sha256": profile[0],
    }
    assert prereg["training_manifest_content_sha256"] == profile[1]
    assert prereg["selected_keys"] == select_batch23_keys(
        project_root=ROOT,
        source_commit=SOURCE_COMMIT,
    )
    assert prereg["selection_uses_outcomes"] is False
    assert prereg["selected_key_outcome_observed_before_registration"] is False
    assert prereg["attempt_each_selected_key_at_most_once"] is True
    assert prereg["retry_authorized"] is False
    assert prereg["replacement_authorized"] is False
    assert prereg["scope"]["teacher_used"] is False
    assert prereg["scope"]["privileged_truth_policy_input"] is False
    assert "scripts/m2c/build_s4_v4_training_extension1_manifest.py" in {
        item["path"] for item in prereg["semantic_source_bindings"]
    }


def test_batch23_prereg_publish_is_create_only(tmp_path: Path) -> None:
    output = tmp_path / "prereg.json"
    payload = prereg_bytes(build_prereg(project_root=ROOT, source_commit=SOURCE_COMMIT))
    write_create_only(output, payload)
    assert output.read_bytes() == payload
    try:
        write_create_only(output, payload)
    except FileExistsError:
        pass
    else:
        raise AssertionError("Batch-23 prereg writer overwrote an existing file")
