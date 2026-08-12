from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import m2c.build_s3_dataset as s3_dataset
from m2c.build_s3_dataset import (
    FROZEN_PHYSICAL_RUNNER,
    FROZEN_PHYSICAL_RUNNER_SHA256,
    accepted_evidence,
    audit_accepted_evidence,
    audit_accepted_payload,
    coverage_summary,
    fourth_class_records,
    load_stable_worker_status,
    load_jsonl,
    merge_episodes,
    validate_evidence_freeze,
    verify_remote_evidence_ledger,
    validate_frozen_acceptance_predicate,
    write_outputs,
)


PROJECT = Path(__file__).resolve().parents[2]
BASE = load_jsonl(PROJECT / "artifacts/m2b/dataset-v2.jsonl")
PLAN = json.loads((PROJECT / "configs/m2c_s3_collection_plan.json").read_text())
WORKER_STATUS_SNAPSHOT = {
    "host": "root@labserver",
    "path": "/remote/worker-status.json",
    "sha256": "a" * 64,
    "schema_version": "M2BFailureEvidenceWorkerStatusV1",
    "status": "COMPLETE_ACCEPTED_TARGET",
    "accepted_counts": {
        "EMPTY_GRASP": 25,
        "WRONG_OBJECT": 25,
        "RELEASE_FAILURE": 25,
    },
    "record_count": 75,
    "teacher_used": False,
    "privileged_truth_policy_input": False,
}
EVIDENCE_FREEZE = {
    "report_path": "/local/m2c-s3-evidence-freeze.json",
    "report_sha256": "b" * 64,
    "host": "root@labserver",
    "remote_root": "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1",
    "ledger": "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/evidence-sha256.txt",
    "ledger_sha256": "c" * 64,
    "files_hashed": 10,
    "evidence_tree_readonly": True,
}
ACCEPTED_EVIDENCE_AUDIT = {
    "schema_version": "M2CS3AcceptedEvidenceAuditV1",
    "status": "PASS",
    "records_audited": 150,
    "counts_by_failure": {
        "EMPTY_GRASP": 50,
        "WRONG_OBJECT": 50,
        "RELEASE_FAILURE": 50,
    },
    "evidence_sha256_matches": 150,
    "strict_physical_public_predicates_passed": 150,
    "public_predicate_results_checked": 300,
    "collision_gates_checked": 550,
    "collision_or_safety_violations": 0,
    "teacher_used": False,
    "privileged_truth_policy_input": False,
    "acceptance_predicate": {
        "path": FROZEN_PHYSICAL_RUNNER,
        "sha256": FROZEN_PHYSICAL_RUNNER_SHA256,
        "public_rgbd_required": True,
        "predicate": "m2b.run_physical_failure_smoke.accepted",
    },
    "records": [{} for _ in range(150)],
}


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


def accepted_payload(failure: str, *, scene_seed: int = 10000) -> dict:
    public_result = {
        "schema_version": "PublicFailurePredicateResultV2",
        "source": "PUBLIC_RGBD_TEMPORAL_TRACKS_ONLY",
        "predicates": ["observed=true"],
        "simulator_truth_used": False,
    }
    injection_key = {
        "EMPTY_GRASP": "m2b_empty_grasp_injection",
        "WRONG_OBJECT": "m2b_wrong_object_injection",
        "RELEASE_FAILURE": "m2b_release_failure_injection",
    }[failure]
    recovery_key = {
        "EMPTY_GRASP": "public_final_predicates",
        "WRONG_OBJECT": "public_regrasp_predicates",
        "RELEASE_FAILURE": "public_final_predicates",
    }[failure]
    recovery = {
        "training_eligible": True,
        recovery_key: deepcopy(public_result),
    }
    if failure == "EMPTY_GRASP":
        recovery["physical_regrasp_and_lift_passed"] = True
    elif failure == "WRONG_OBJECT":
        recovery.update(
            {
                "safe_place_non_target_passed": True,
                "reassociate_target_executed": True,
                "regrasp_target_executed": True,
            }
        )
    else:
        recovery["retry_detach_and_retreat_passed"] = True
    collision_gate = {
        "schema_version": "M2BIsaacCollisionGateV1",
        "status": "PASS",
        "contact_reporting_required": True,
        "unexpected_robot_contact_events": 0,
        "unexpected_contacts": [],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    payload = {
        "status": "PASS",
        "scene_seed": scene_seed,
        "m2b_injection_pass": True,
        injection_key: {
            "failure_type": failure,
            "physical_state_passed": True,
            "training_eligible": True,
            "public_predicates": deepcopy(public_result),
        },
        "m2b_recovery": {failure.lower(): recovery},
        "m2b_public_rgbd": {
            "schema_version": "M2BPublicRGBDEvidenceV2",
            "simulator_truth_policy_input": False,
            "task_spec": {"target_track_id": "track-public"},
        },
        "action_protocol": {
            "frame": "PANDA_JOINT_ORDER_BY_NAME",
            "units": "radian_arm_metre_finger",
            "dimensions": 9,
            "frequency_hz": 60,
            "normalization": "none",
        },
        "phases": {
            "detach_retreat": {"collision_gate": deepcopy(collision_gate)},
            "lift": {"collision_gate": deepcopy(collision_gate)},
        },
    }
    if failure == "RELEASE_FAILURE":
        payload["m2b_release_failure_injection"]["follow_motion"] = {
            "collision_gate": deepcopy(collision_gate)
        }
    elif failure == "WRONG_OBJECT":
        payload["m2b_recovery"]["wrong_object"]["regrasp_execution"] = {
            "attempts": [
                {"contact_motion": {"collision_gate": deepcopy(collision_gate)}}
            ],
            "ik_reachability_scan": {
                "trials": [
                    {
                        "pregrasp_motion": {
                            "collision_gate": deepcopy(collision_gate)
                        }
                    }
                ]
            },
            "lift_motion": {"collision_gate": deepcopy(collision_gate)},
            "pregrasp_motion": {"collision_gate": deepcopy(collision_gate)},
        }
    return payload


def audit_one(payload: dict, failure: str) -> dict:
    return audit_accepted_payload(
        payload,
        failure=failure,
        evidence_path=f"/remote/{failure}.json",
        declared_sha256="a" * 64,
        actual_sha256="a" * 64,
        scene_seed=10000,
    )


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


def test_strict_accepted_payload_audit_rechecks_all_three_failure_classes() -> None:
    audited = {
        failure: audit_one(accepted_payload(failure), failure)
        for failure in ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
    }
    assert {
        failure: item["collision_gates_checked"]
        for failure, item in audited.items()
    } == {"EMPTY_GRASP": 2, "WRONG_OBJECT": 6, "RELEASE_FAILURE": 3}
    assert all(item["strict_physical_public_predicate_passed"] for item in audited.values())
    assert all(item["collision_or_safety_violations"] == 0 for item in audited.values())


def test_strict_accepted_payload_audit_rejects_predicate_and_collision_drift() -> None:
    predicate_drift = accepted_payload("EMPTY_GRASP")
    predicate_drift["m2b_empty_grasp_injection"]["physical_state_passed"] = False
    try:
        audit_one(predicate_drift, "EMPTY_GRASP")
    except ValueError as error:
        assert "strict physical/public predicate failed" in str(error)
    else:
        raise AssertionError("failed physical predicate was accepted")

    collision_drift = accepted_payload("WRONG_OBJECT")
    collision_drift["phases"]["lift"]["collision_gate"]["status"] = "REJECTED"
    try:
        audit_one(collision_drift, "WRONG_OBJECT")
    except ValueError as error:
        assert "collision/safety gate failed" in str(error)
    else:
        raise AssertionError("failed collision gate was accepted")


def test_strict_accepted_payload_audit_rejects_teacher_truth_and_hash_drift() -> None:
    teacher_drift = accepted_payload("RELEASE_FAILURE")
    teacher_drift["nested"] = {"teacher_used": True}
    try:
        audit_one(teacher_drift, "RELEASE_FAILURE")
    except ValueError as error:
        assert "Teacher boundary violation" in str(error)
    else:
        raise AssertionError("Teacher boundary violation was accepted")

    truth_drift = accepted_payload("RELEASE_FAILURE")
    truth_drift["nested"] = {"privileged_truth_policy_input": True}
    try:
        audit_one(truth_drift, "RELEASE_FAILURE")
    except ValueError as error:
        assert "privileged truth policy-input violation" in str(error)
    else:
        raise AssertionError("privileged truth policy input was accepted")

    try:
        audit_accepted_payload(
            accepted_payload("EMPTY_GRASP"),
            failure="EMPTY_GRASP",
            evidence_path="/remote/evidence.json",
            declared_sha256="a" * 64,
            actual_sha256="b" * 64,
            scene_seed=10000,
        )
    except ValueError as error:
        assert "SHA-256 mismatch" in str(error)
    else:
        raise AssertionError("evidence hash drift was accepted")


def test_accepted_evidence_audit_requires_exact_per_class_target(monkeypatch) -> None:
    statuses = [
        {
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "records": [
                {
                    "accepted": True,
                    "failure_type": failure,
                    "scene_seed": 10000,
                    "evidence": f"/remote/{failure}.json",
                    "evidence_sha256": "a" * 64,
                }
                for failure in ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
            ],
        }
    ]
    payloads = {
        f"/remote/{failure}.json": accepted_payload(failure)
        for failure in ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE")
    }
    monkeypatch.setattr(s3_dataset, "remote_sha256", lambda host, path: "a" * 64)
    monkeypatch.setattr(s3_dataset, "remote_json", lambda host, path: payloads[path])

    audit = audit_accepted_evidence(
        statuses,
        host="root@labserver",
        predicate_binding=ACCEPTED_EVIDENCE_AUDIT["acceptance_predicate"],
        expected_per_failure=1,
    )
    assert audit["records_audited"] == 3
    assert audit["strict_physical_public_predicates_passed"] == 3
    assert audit["collision_gates_checked"] == 11

    statuses[0]["records"].pop()
    try:
        audit_accepted_evidence(
            statuses,
            host="root@labserver",
            predicate_binding=ACCEPTED_EVIDENCE_AUDIT["acceptance_predicate"],
            expected_per_failure=1,
        )
    except ValueError as error:
        assert "exact frozen S3 target" in str(error)
    else:
        raise AssertionError("incomplete per-class evidence target was accepted")


def test_stable_worker_status_snapshot_binds_remote_bytes(monkeypatch) -> None:
    payload = {
        "schema_version": "M2BFailureEvidenceWorkerStatusV1",
        "status": "COMPLETE_ACCEPTED_TARGET",
        "accepted_counts": {"EMPTY_GRASP": 25},
        "records": [{"accepted": True}],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    hashes = iter(["b" * 64, "b" * 64])
    monkeypatch.setattr(s3_dataset, "remote_sha256", lambda host, path: next(hashes))
    monkeypatch.setattr(s3_dataset, "remote_json", lambda host, path: payload)

    status, snapshot = load_stable_worker_status("root@labserver", "/status.json")

    assert status is payload
    assert snapshot["sha256"] == "b" * 64
    assert snapshot["record_count"] == 1
    assert snapshot["teacher_used"] is False


def test_worker_status_snapshot_rejects_mid_read_change(monkeypatch) -> None:
    hashes = iter(["b" * 64, "c" * 64])
    monkeypatch.setattr(s3_dataset, "remote_sha256", lambda host, path: next(hashes))
    monkeypatch.setattr(s3_dataset, "remote_json", lambda host, path: {})

    try:
        load_stable_worker_status("root@labserver", "/status.json")
    except ValueError as error:
        assert "changed while being read" in str(error)
    else:
        raise AssertionError("changing worker status was accepted")


def test_acceptance_predicate_is_bound_to_frozen_collection_source() -> None:
    binding = validate_frozen_acceptance_predicate(PLAN)
    assert binding == ACCEPTED_EVIDENCE_AUDIT["acceptance_predicate"]

    changed = deepcopy(PLAN)
    changed["frozen_collection_runtime"]["physical_runner_sha256"] = "0" * 64
    try:
        validate_frozen_acceptance_predicate(changed)
    except ValueError as error:
        assert "predicate SHA-256 changed" in str(error)
    else:
        raise AssertionError("changed physical acceptance predicate was accepted")


def test_evidence_freeze_binds_exact_worker_status_snapshots(tmp_path: Path) -> None:
    frozen_snapshot = {key: value for key, value in WORKER_STATUS_SNAPSHOT.items() if key != "host"}
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(
        json.dumps(
            {
                "schema_version": "M2CS3EvidenceFreezeV1",
                "status": "PASS",
                "host": "root@labserver",
                "remote_root": "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1",
                "ledger": "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/evidence-sha256.txt",
                "ledger_sha256": "c" * 64,
                "files_hashed": 10,
                "evidence_tree_readonly": True,
                "worker_status_snapshots": [frozen_snapshot],
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        ),
        encoding="utf-8",
    )

    binding = validate_evidence_freeze(
        freeze_path,
        host="root@labserver",
        worker_status_snapshots=[WORKER_STATUS_SNAPSHOT],
    )

    assert binding["ledger_sha256"] == "c" * 64
    assert binding["evidence_tree_readonly"] is True


def test_evidence_freeze_rejects_changed_worker_status(tmp_path: Path) -> None:
    frozen_snapshot = {key: value for key, value in WORKER_STATUS_SNAPSHOT.items() if key != "host"}
    frozen_snapshot["sha256"] = "d" * 64
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(
        json.dumps(
            {
                "schema_version": "M2CS3EvidenceFreezeV1",
                "status": "PASS",
                "host": "root@labserver",
                "remote_root": "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1",
                "ledger": "/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/evidence-sha256.txt",
                "ledger_sha256": "c" * 64,
                "files_hashed": 10,
                "evidence_tree_readonly": True,
                "worker_status_snapshots": [frozen_snapshot],
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
        ),
        encoding="utf-8",
    )

    try:
        validate_evidence_freeze(
            freeze_path,
            host="root@labserver",
            worker_status_snapshots=[WORKER_STATUS_SNAPSHOT],
        )
    except ValueError as error:
        assert "differs" in str(error)
    else:
        raise AssertionError("changed worker status was accepted")


def test_remote_evidence_ledger_rechecks_digest_and_tree(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        s3_dataset,
        "remote_sha256",
        lambda host, path: EVIDENCE_FREEZE["ledger_sha256"],
    )

    class Completed:
        returncode = 0
        stdout = "all files OK"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    monkeypatch.setattr(s3_dataset.subprocess, "run", fake_run)

    verify_remote_evidence_ledger("root@labserver", EVIDENCE_FREEZE)

    assert len(calls) == 1
    assert calls[0][0][:4] == ["ssh", "-o", "BatchMode=yes", "root@labserver"]
    assert "sha256sum --check --strict evidence-sha256.txt" in calls[0][0][4]


def test_remote_evidence_ledger_rejects_digest_drift(monkeypatch) -> None:
    monkeypatch.setattr(s3_dataset, "remote_sha256", lambda host, path: "d" * 64)

    try:
        verify_remote_evidence_ledger("root@labserver", EVIDENCE_FREEZE)
    except ValueError as error:
        assert "changed after freeze" in str(error)
    else:
        raise AssertionError("changed remote ledger was accepted")


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
        worker_status_snapshots=[WORKER_STATUS_SNAPSHOT],
        evidence_freeze=EVIDENCE_FREEZE,
        accepted_evidence_audit=ACCEPTED_EVIDENCE_AUDIT,
        plan=PLAN,
        output=tmp_path / "dataset.jsonl",
        quarantine_path=tmp_path / "quarantine.jsonl",
        fourth_class_path=tmp_path / "path-blocked.jsonl",
        report_path=tmp_path / "report.json",
    )
    assert report["status"] == "IN_PROGRESS_S3_FULL_CLASS_COVERAGE"
    assert report["episodes_quarantined"] == 1
    assert report["collection_rejections"] == 1
    assert report["worker_status_snapshots"] == [WORKER_STATUS_SNAPSHOT]
    assert report["evidence_freeze"] == EVIDENCE_FREEZE
    assert report["fourth_class"]["model_training_eligible"] is False


def test_output_report_passes_full_gate_and_keeps_fourth_class_raw_only(
    tmp_path: Path,
) -> None:
    by_failure = {}
    for item in BASE:
        by_failure.setdefault(item["failure_context"]["failure_type"], item)
    additions = []
    index = 1
    for failure in ("EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"):
        for _ in range(50):
            additions.append(clone_episode(by_failure[failure], index=index))
            index += 1

    output = tmp_path / "dataset.jsonl"
    quarantine = tmp_path / "quarantine.jsonl"
    fourth = tmp_path / "path-blocked.jsonl"
    report = write_outputs(
        base=BASE,
        additions=additions,
        package_quarantine=[],
        collection_rejections=[],
        worker_status_snapshots=[WORKER_STATUS_SNAPSHOT],
        evidence_freeze=EVIDENCE_FREEZE,
        accepted_evidence_audit=ACCEPTED_EVIDENCE_AUDIT,
        plan=PLAN,
        output=output,
        quarantine_path=quarantine,
        fourth_class_path=fourth,
        report_path=tmp_path / "report.json",
        report_md_path=tmp_path / "report.md",
    )

    assert report["status"] == "PASS_S3_FULL_CLASS_COVERAGE"
    assert report["failure_counts"] == {
        "EMPTY_GRASP": 101,
        "WRONG_OBJECT": 100,
        "RELEASE_FAILURE": 111,
    }
    assert report["successful_recovery_counts"] == report["failure_counts"]
    assert report["episodes_quarantined"] == 0
    assert report["worker_status_snapshots"] == [WORKER_STATUS_SNAPSHOT]
    assert quarantine.read_text() == ""
    assert report["task_report"]["tests"][0]["status"] == "PASS"
    assert report["task_report"]["failures"] == {
        "collection_attempts_rejected": 0,
        "packaging_quarantine": 0,
    }
    assert report["task_report"]["blockers"] == [
        "Q-B is forbidden until a separate human expressivity ADR is committed."
    ]
    assert report["task_report"]["next_command"].startswith("sed -n")
    assert len(load_jsonl(fourth)) == 3
    assert all(
        item["failure_context"]["failure_type"] != "PATH_BLOCKED" for item in load_jsonl(output)
    )
    markdown = (tmp_path / "report.md").read_text()
    assert "# M2C S3 Dataset V3" in markdown
    assert "Teacher used: no" in markdown
    assert "150/150 records" in markdown
    assert "- Tests:" in markdown
    assert "Q-B remains forbidden" in markdown
    assert EVIDENCE_FREEZE["ledger_sha256"] in markdown
