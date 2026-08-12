from __future__ import annotations

import json
from pathlib import Path

from m2c.build_s4_key_manifests import build_manifests, canonical_sha256
from m2c.s4_scene_family import materialize_scene


ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"


def test_key_manifests_are_frozen_disjoint_and_outcome_blind() -> None:
    training, evaluation = build_manifests()
    assert len(training["training_keys"]) == 36
    assert len(training["physical_prerequisite_smoke_keys"]) == 3
    assert len(evaluation["evaluation_keys"]) == 30
    train_and_smoke = [
        *training["training_keys"],
        *training["physical_prerequisite_smoke_keys"],
    ]
    all_records = [*train_and_smoke, *evaluation["evaluation_keys"]]
    assert len({record["matched_key"] for record in all_records}) == len(all_records)
    assert len({record["scene_seed"] for record in all_records}) == len(all_records)
    assert not (
        {record["matched_key"] for record in all_records}
        & set(training["v4_excluded_matched_keys"])
    )
    assert not (
        {record["scene_seed"] for record in all_records} & set(training["v4_excluded_scene_seeds"])
    )
    assert all(record["outcome_observed_during_selection"] is False for record in all_records)
    assert all(
        record["offline_scene_materialized_during_selection"] is True
        and record["offline_geometry_admission"]["part_count"] == 6
        and record["offline_geometry_admission"]["minimum_surface_gap_m"] >= 0.005
        and record["offline_geometry_admission"]["target_clearance_before_ok"] is False
        and record["offline_geometry_admission"]["scripted_blocker_clearance_ok"] is True
        and record["offline_geometry_admission"]["target_clearance_after_relocation_ok"] is True
        for record in all_records
    )
    assert training["s6_evaluation_key_digest"] == canonical_sha256(evaluation["evaluation_keys"])
    assert evaluation["training_and_smoke_key_digest"] == canonical_sha256(train_and_smoke)


def test_checked_in_manifests_equal_the_deterministic_builder() -> None:
    expected_training, expected_evaluation = build_manifests()
    actual_training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    actual_evaluation = json.loads((ROOT / "configs/m2c_s6_evaluation_keys.json").read_text())
    assert actual_training == expected_training
    assert actual_evaluation == expected_evaluation
    assert actual_training["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in actual_training.items() if key != "manifest_sha256"}
    )
    assert actual_evaluation["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in actual_evaluation.items() if key != "manifest_sha256"}
    )


def test_scene_family_exactly_reproduces_frozen_v4_bytes() -> None:
    frozen_v4 = json.loads((ROOT / "configs/m2c_headroom_domain_v4.json").read_text())
    template = TEMPLATE.read_text(encoding="utf-8")
    for frozen in frozen_v4["keys"]:
        candidate = materialize_scene(
            template,
            int(frozen["scene_seed"]),
            tuple(frozen["anchor_xy_m"]),
        )
        assert candidate is not None
        _, _, receipt = candidate
        assert receipt["sdf_sha256"] == frozen["sdf_sha256"]
        assert receipt["supervision_sha256"] == frozen["supervision_sha256"]
