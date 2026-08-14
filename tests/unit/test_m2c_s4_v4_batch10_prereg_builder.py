from __future__ import annotations

from pathlib import Path

from m2c.build_s4_v4_batch10_prereg import STOP_AFTER, select_batch10_keys
from xh_agent.policy.qrm_lite import s4_v4_collection_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[2]


def test_authoritative_prior_inventory_contains_all_twenty_two_attempted_keys() -> None:
    assert authorization.AUTHORITATIVE_PRIOR_ATTEMPT_KEY_COUNT == 22
    assert len(authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES) == 7
    assert "reports/m2c-s4-v4-batch09-collection.json" in (
        authorization.AUTHORITATIVE_PRIOR_ATTEMPT_SOURCES
    )


def test_batch10_selection_is_outcome_blind_and_identity_disjoint() -> None:
    selected = select_batch10_keys(project_root=ROOT)

    assert len(selected) == STOP_AFTER == 3
    assert len({item["matched_key"] for item in selected}) == 3
    assert len({item["sdf_sha256"] for item in selected}) == 3
    assert [(item["scene_seed"], item["failure_seed"]) for item in selected] == [
        (19126, 191267),
        (19133, 191337),
        (19146, 191467),
    ]
    assert [item["matched_key"] for item in selected] == [
        "m2c-s4-v4-train-af2092156b05aa0ee4318c8a04607274e9b51a96b69c588ede07a3e7ff4a5e70",
        "m2c-s4-v4-train-dbacb6ef24488f5c481dabe338e58e21ce7e19483515e7cc2208aaa1adb83975",
        "m2c-s4-v4-train-a5b3587fbd26ecf3e82b12ea31f75b820ffcd22a6402fb4488f89451390708aa",
    ]
