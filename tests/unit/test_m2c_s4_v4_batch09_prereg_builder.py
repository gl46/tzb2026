from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch09_prereg import (
    BATCH09_PRIOR_ATTEMPT_KEY_COUNT,
    BATCH09_PRIOR_ATTEMPT_SOURCES,
    STOP_AFTER,
    select_batch09_keys,
)

ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_nineteen_attempted_keys() -> None:
    assert BATCH09_PRIOR_ATTEMPT_KEY_COUNT == 19
    assert len(BATCH09_PRIOR_ATTEMPT_SOURCES) == 6
    assert "reports/m2c-s4-v4-batch08-collection.json" in (BATCH09_PRIOR_ATTEMPT_SOURCES)
    assert "reports/m2c-s4-v4-batch09-collection.json" not in BATCH09_PRIOR_ATTEMPT_SOURCES


def test_batch09_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch09_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19085, 190857),
        (19120, 191207),
        (19121, 191217),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-b43875023d3317faeb203415a9db3fc3ffa9f81c0e5a0a787cd5b2da954ee030",
        "m2c-s4-v4-train-684c8ad0c426156e1fcd136e4a5fcbc249d85817a7a81b557699d397c54783a4",
        "m2c-s4-v4-train-bcfcf461c4f4071abaf657c174371d8dbc106396fe6602a480189cb3305875cf",
    ]
