from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch13_prereg import (
    BATCH13_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH13_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch13_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_thirty_one_attempted_keys() -> None:
    assert BATCH13_PRIOR_ATTEMPT_KEY_COUNT == 31
    assert authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT == 31
    assert len(BATCH13_PRIOR_ATTEMPT_SOURCE_PATHS) == 10
    assert len(authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES) == 10
    assert "reports/m2c-s4-v4-batch12-collection.json" in BATCH13_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch13_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch13_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19200, 192007),
        (19213, 192137),
        (19220, 192207),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-4bb5c7348bd29eb602c492e8f16f75db422702eab693186cdf98107e9fee4e49",
        "m2c-s4-v4-train-963eb50a09d38052d0f1201f0f0907c6847c1ec9b84bc1ada1f92dba1addcc3a",
        "m2c-s4-v4-train-ca56489f299f1b00e7df84e73cfb18628315581ab2656ce00d5ed41268a531a7",
    ]
