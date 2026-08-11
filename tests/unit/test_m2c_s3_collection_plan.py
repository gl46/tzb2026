from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from m2c.build_s3_collection_plan import (
    PROJECT,
    TEMPLATE,
    URDF,
    generate_plan,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_s3_plan_is_deterministic_outcome_blind_and_full_coverage_bound(
    tmp_path: Path,
) -> None:
    output = tmp_path / "source"
    plan = generate_plan(
        template_path=TEMPLATE,
        urdf_path=URDF,
        output_root=output,
    )
    assert plan["status"] == "PREREGISTERED_NOT_LAUNCHED"
    assert plan["outcomes_observed"] is False
    assert plan["collection_launched"] is False
    assert plan["preregistration_timing"]["written_before_any_s3_collection_execution"] is True
    assert len(plan["scenes"]) == 150
    assert [item["scene_seed"] for item in plan["scenes"][:3]] == [
        10000,
        10001,
        10002,
    ]
    assert [item["scene_seed"] for item in plan["scenes"][-3:]] == [
        10147,
        10148,
        10149,
    ]
    assert {item["worker_id"] for item in plan["scenes"]} == {0, 1}
    assert [item["scene_count"] for item in plan["workers"]] == [75, 75]
    assert all(item["accepted_target_per_failure"] == 25 for item in plan["workers"])
    assert plan["coverage_gate"]["projected_failure_counts_if_targets_pass"] == {
        "EMPTY_GRASP": 101,
        "WRONG_OBJECT": 100,
        "RELEASE_FAILURE": 111,
    }
    assert all(
        value >= 50
        for value in plan["coverage_gate"][
            "projected_successful_recovery_counts_if_targets_pass"
        ].values()
    )
    assert plan["base_dataset"]["readonly"] is True
    assert plan["plan_builder_sha256"] == sha256(
        PROJECT / "scripts/m2c/build_s3_collection_plan.py"
    )
    assert plan["q_b_training_or_evaluation_authorized"] is False
    assert plan["teacher_used"] is False


def test_s3_plan_hashes_every_source_and_keeps_path_blocked_raw(
    tmp_path: Path,
) -> None:
    plan = generate_plan(
        template_path=TEMPLATE,
        urdf_path=URDF,
        output_root=tmp_path / "source",
    )
    for record in plan["scenes"]:
        assert sha256(Path(record["sdf"])) == record["sdf_sha256"]
        assert sha256(Path(record["supervision"])) == record["supervision_sha256"]
        assert record["outcome_observed_during_selection"] is False
    fourth = plan["fourth_class"]
    assert fourth["failure_type"] == "PATH_BLOCKED"
    assert fourth["failure_observations"] == 3
    assert fourth["successful_recoveries"] == 1
    assert fourth["model_training_eligible"] is False
    assert fourth["new_skill_label_created"] is False
    assert fourth["human_adr_required_before_model_label_or_q_b"] is True
    assert len(fourth["evidence"]) == 3


def test_s3_plan_refuses_overwrite_or_changed_scene_count(tmp_path: Path) -> None:
    output = tmp_path / "source"
    output.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_plan(
            template_path=TEMPLATE,
            urdf_path=URDF,
            output_root=output,
        )
    with pytest.raises(ValueError, match="scene_count is frozen at 150"):
        generate_plan(
            template_path=TEMPLATE,
            urdf_path=URDF,
            output_root=tmp_path / "wrong-count",
            scene_count=149,
        )


def test_s3_plan_pins_frozen_runtime_hashes(tmp_path: Path) -> None:
    plan = generate_plan(
        template_path=TEMPLATE,
        urdf_path=URDF,
        output_root=tmp_path / "source",
    )
    runtime = plan["frozen_collection_runtime"]
    assert runtime["physical_probe_sha256"] == sha256(
        PROJECT / "scripts/isaac_m1b_actuation_probe.py"
    )
    assert runtime["physical_runner_sha256"] == sha256(
        PROJECT / "scripts/m2b/run_physical_failure_smoke.py"
    )
    assert runtime["gates_or_success_predicates_changed"] is False
