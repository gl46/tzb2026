from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch14_prereg import (
    BATCH14_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH14_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch14_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_thirty_four_attempted_keys() -> None:
    assert BATCH14_PRIOR_ATTEMPT_KEY_COUNT == 34
    assert authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT == 34
    assert len(BATCH14_PRIOR_ATTEMPT_SOURCE_PATHS) == 11
    assert len(authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES) == 11
    assert "reports/m2c-s4-v4-batch13-collection.json" in BATCH14_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch14_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch14_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19227, 192277),
        (19229, 192297),
        (19231, 192317),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-0086f022b69efe337c121a246a14b15395ba904a96e4b7e973a20599c8b70eb3",
        "m2c-s4-v4-train-3abd3168887126661a7bc521fcf8cc6f923e8932ccebf0397e13f5234e9adaf1",
        "m2c-s4-v4-train-3ad162004af4415bae3ac4f4f937d4d6799abed4e4e5df6b06fa426a64eb7aee",
    ]
