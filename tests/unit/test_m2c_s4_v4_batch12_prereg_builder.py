from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch12_prereg import (
    BATCH12_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH12_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch12_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_twenty_eight_attempted_keys() -> None:
    assert BATCH12_PRIOR_ATTEMPT_KEY_COUNT == 28
    assert authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT == 28
    assert len(BATCH12_PRIOR_ATTEMPT_SOURCE_PATHS) == 9
    assert len(authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES) == 9
    assert "reports/m2c-s4-v4-batch11-collection.json" in BATCH12_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch12_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch12_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19189, 191897),
        (19190, 191907),
        (19191, 191917),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-4ee9077a9da143d86d146a90b1117a8a077d70fe42457dc601693391e05f2ce1",
        "m2c-s4-v4-train-d1ce5eda6f56ac40a09f7513804c3909d2395a8cb28679c8d294c225a84dcbb5",
        "m2c-s4-v4-train-29be2b36f9cf5648edd36d72250effd09001b825e2bcb712a58ce63ca22c9237",
    ]
