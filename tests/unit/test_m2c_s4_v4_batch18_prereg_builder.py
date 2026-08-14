from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch18_prereg import (
    BATCH18_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH18_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch18_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_forty_six_attempted_keys() -> None:
    assert BATCH18_PRIOR_ATTEMPT_KEY_COUNT == 46
    assert len(BATCH18_PRIOR_ATTEMPT_SOURCE_PATHS) == 15
    assert BATCH18_PRIOR_ATTEMPT_KEY_COUNT < authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT
    assert set(BATCH18_PRIOR_ATTEMPT_SOURCE_PATHS) < set(
        authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES
    )
    assert "reports/m2c-s4-v4-batch17-collection.json" in BATCH18_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch18_selects_the_only_remaining_identity_outcome_blind() -> None:
    selected = select_batch18_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 1
    assert selected == [
        {
            "scene_seed": 19307,
            "failure_seed": 193077,
            "matched_key": (
                "m2c-s4-v4-train-6949eeadc340f2ac8bd0627c43334c3849d024904f6b4ddec54bf66ecdc6062b"
            ),
            "sdf_sha256": ("e30efb66aef4ff948e48551cb26d03990c14b6bb25813b9a8fd6e8b7c9831cf7"),
            "supervision_sha256": (
                "d637b0843352bbc346704ac0c10fc0e4b908443775b4668c8fdf1747ef66db30"
            ),
        }
    ]
