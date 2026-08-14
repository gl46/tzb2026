from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch15_prereg import (
    BATCH15_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH15_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch15_keys,
)
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_thirty_seven_attempted_keys() -> None:
    assert BATCH15_PRIOR_ATTEMPT_KEY_COUNT == 37
    assert len(BATCH15_PRIOR_ATTEMPT_SOURCE_PATHS) == 12
    assert BATCH15_PRIOR_ATTEMPT_KEY_COUNT == authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT
    assert set(BATCH15_PRIOR_ATTEMPT_SOURCE_PATHS) == set(
        authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES
    )
    assert "reports/m2c-s4-v4-batch14-collection.json" in BATCH15_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch15_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch15_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19233, 192337),
        (19244, 192447),
        (19265, 192657),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-77abe312423d07d84ae43a8ef2784f0df12390371ff082c497a9a157606a056c",
        "m2c-s4-v4-train-2c8a30ea003bf8d7673204d73fa628f7180059a1aa9bed66f1821f08537e0e0a",
        "m2c-s4-v4-train-b9215a0c744235f6357a769655cb38d63192a4b9bd434f56d408bb733e72c182",
    ]
