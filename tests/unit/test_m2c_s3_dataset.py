from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from m2c.build_s3_dataset import (
    accepted_evidence,
    coverage_summary,
    fourth_class_records,
    load_jsonl,
    merge_episodes,
    write_outputs,
)


PROJECT = Path(__file__).resolve().parents[2]
BASE = load_jsonl(PROJECT / "artifacts/m2b/dataset-v2.jsonl")
PLAN = json.loads((PROJECT / "configs/m2c_s3_collection_plan.json").read_text())


def clone_episode(source: dict, *, index: int) -> dict:
    item = deepcopy(source)
    digest = f"{index:064x}"
    scene = 20000 + index
    failure = item["failure_context"]["failure_type"]
    item["episode_id"] = f"m2c-test-{index}"
    item["scene_seed"] = scene
    item["split"] = "train"
    item["split_group"] = f"scene-{scene}"
    item["injection_seed"] = index
    item["group_key"] = f"scene-{scene}:failure-{failure}:injection-{index}"
    item["provenance"]["evidence_sha256"] = digest
    item["provenance"]["evidence_path"] = f"/remote/evidence-{index}.json"
    return item


def test_worker_status_extracts_accepted_and_records_rejections() -> None:
    statuses = [
        {
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "records": [
                {
                    "scene_seed": 1,
                    "failure_type": "EMPTY_GRASP",
                    "accepted": True,
                    "evidence": "/accepted.json",
                },
                {
                    "scene_seed": 2,
                    "failure_type": "WRONG_OBJECT",
                    "accepted": False,
                    "status": "PARTIAL",
                },
                {"scene_seed": 3, "status": "STAGE_FAILED"},
            ],
        }
    ]
    evidence, rejected = accepted_evidence(statuses)
    assert evidence == [("EMPTY_GRASP", "/accepted.json")]
    assert len(rejected) == 2
    assert all(item["reason"] for item in rejected)


def test_merge_promotes_version_and_deduplicates_evidence() -> None:
    base = [BASE[0]]
    duplicate = deepcopy(BASE[0])
    addition = clone_episode(BASE[1], index=1)
    merged, quarantine = merge_episodes(base, [duplicate, addition])
    assert quarantine == []
    assert len(merged) == 2
    assert {item["dataset_version"] for item in merged} == {"isaac-industrial-v3-headroom"}
    assert {item["m2c_s3_source"] for item in merged} == {
        "FROZEN_M2B_DATASET_V2",
        "M2C_S3_ACCEPTED_PHYSICAL_EVIDENCE",
    }
    assert all(item["teacher_used"] is False for item in merged)


def test_full_coverage_gate_and_scene_group_leakage() -> None:
    by_failure = {}
    for item in BASE:
        by_failure.setdefault(item["failure_context"]["failure_type"], item)
    episodes = []
    index = 1
    for failure, source in by_failure.items():
        for _ in range(100):
            episodes.append(clone_episode(source, index=index))
            index += 1
    coverage = coverage_summary(episodes)
    assert coverage["failure_counts"] == {
        "EMPTY_GRASP": 100,
        "WRONG_OBJECT": 100,
        "RELEASE_FAILURE": 100,
    }
    assert coverage["full_class_coverage_gate_passed"] is True
    episodes[-1]["split_group"] = episodes[0]["split_group"]
    episodes[-1]["split"] = "val"
    leaked = coverage_summary(episodes)
    assert leaked["split_group_leakage"]
    assert leaked["full_class_coverage_gate_passed"] is False


def test_path_blocked_records_remain_raw_and_unlabelled() -> None:
    records = fourth_class_records(PLAN)
    assert len(records) == 3
    assert sum(item["strict_complete_existence_proof"] for item in records) == 1
    assert all(item["failure_type"] == "PATH_BLOCKED" for item in records)
    assert all(item["model_training_eligible"] is False for item in records)
    assert all(item["new_skill_label_created"] is False for item in records)


def test_output_report_fails_closed_on_packaging_quarantine(
    tmp_path: Path,
) -> None:
    report = write_outputs(
        base=BASE,
        additions=[],
        package_quarantine=[{"reason": "synthetic invalid record"}],
        collection_rejections=[
            {
                "scene_seed": 7,
                "failure_type": "WRONG_OBJECT",
                "status": "PARTIAL",
                "reason": "frozen predicate rejected",
            }
        ],
        plan=PLAN,
        output=tmp_path / "dataset.jsonl",
        quarantine_path=tmp_path / "quarantine.jsonl",
        fourth_class_path=tmp_path / "path-blocked.jsonl",
        report_path=tmp_path / "report.json",
    )
    assert report["status"] == "IN_PROGRESS_S3_FULL_CLASS_COVERAGE"
    assert report["episodes_quarantined"] == 1
    assert report["collection_rejections"] == 1
    assert report["fourth_class"]["model_training_eligible"] is False
