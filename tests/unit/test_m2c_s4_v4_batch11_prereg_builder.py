from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch11_prereg import (
    BATCH11_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH11_PRIOR_ATTEMPT_SOURCE_PATHS,
    STOP_AFTER,
    select_batch11_keys,
)


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_twenty_five_attempted_keys() -> None:
    assert BATCH11_PRIOR_ATTEMPT_KEY_COUNT == 25
    assert len(BATCH11_PRIOR_ATTEMPT_SOURCE_PATHS) == 8
    assert "reports/m2c-s4-v4-batch10-collection.json" in BATCH11_PRIOR_ATTEMPT_SOURCE_PATHS


def test_batch11_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch11_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19162, 191627),
        (19167, 191677),
        (19173, 191737),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-44d03f8a5ac3cc97658a4055f143a67feda2ddbc2833c90fbdca2993b3480405",
        "m2c-s4-v4-train-c22f9f1fbcf4912fc8a18cd6f758c6249e6dc35bfff6b99bfd65a57a7226301e",
        "m2c-s4-v4-train-94ddb675ff2e5e7354554cbf45941ae35e161c525842538f8659c31bc7c96733",
    ]
