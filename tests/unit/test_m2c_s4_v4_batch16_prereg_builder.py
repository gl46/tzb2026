from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch16_prereg import (
    BATCH16_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH16_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch16_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_forty_attempted_keys() -> None:
    assert BATCH16_PRIOR_ATTEMPT_KEY_COUNT == 40
    assert len(BATCH16_PRIOR_ATTEMPT_SOURCE_PATHS) == 13
    assert set(BATCH16_PRIOR_ATTEMPT_SOURCE_PATHS) < set(
        authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES
    )
    assert "reports/m2c-s4-v4-batch15-collection.json" in BATCH16_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch16_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch16_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19267, 192677),
        (19285, 192857),
        (19291, 192917),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-df99e5f881cb4d2ac3d225e27d8a33a73c5e2fbd7abbeae41445ea0816f50a3b",
        "m2c-s4-v4-train-2e785b390214b45000f930988d27b7eee2624dcbf059fccad95524a7702ee1b2",
        "m2c-s4-v4-train-ac9592dd1891a0259a09097606871c8668224881b6db63316dfe8b087f83b406",
    ]
