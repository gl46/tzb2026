from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch17_prereg import (
    BATCH17_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH17_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch17_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_forty_three_attempted_keys() -> None:
    assert BATCH17_PRIOR_ATTEMPT_KEY_COUNT == 43
    assert len(BATCH17_PRIOR_ATTEMPT_SOURCE_PATHS) == 14
    assert BATCH17_PRIOR_ATTEMPT_KEY_COUNT < authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT
    assert set(BATCH17_PRIOR_ATTEMPT_SOURCE_PATHS) < set(
        authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES
    )
    assert "reports/m2c-s4-v4-batch16-collection.json" in BATCH17_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch17_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch17_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19292, 192927),
        (19293, 192937),
        (19305, 193057),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-6e8670d3cc6cbc5048e964c39b132e564d5d198d6363012e50db1d18f33c8b26",
        "m2c-s4-v4-train-3ccd668c8496ab513b315fa982c75efe9c3815bf6deeb7cf973e072ce91f99d5",
        "m2c-s4-v4-train-a6eb7a686719d35ba032874a82c81370572244245607c1d77ebc07dca3d4d8f6",
    ]
