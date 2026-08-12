"""Fail-closed tests for the replayable S4 TRAIN collection audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/m2c/audit_path_blocked_train_collection.py"
SPEC = importlib.util.spec_from_file_location("m2c_train_collection_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
TRAINING = ROOT / "configs/m2c_s4_training_keys.json"
S6 = ROOT / "configs/m2c_s6_evaluation_keys.json"
PREREG = ROOT / "docs/decisions/M2C-S4-TRAIN-COLLECTION-BATCH-02-PREREG.md"
URDF_SHA = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
DERIVED_SHA = "9c7a309bdddfac8853818b53cc84501c4f2da9baf02478d10a1025c03d4a4ee9"
UPSTREAM_SHA = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _job(record: dict) -> dict:
    return {
        "schema_version": AUDIT.JOB_SCHEMA,
        "status": "PREPARED_NOT_EXECUTED",
        "collection_role": "TRAIN",
        "split": "train",
        "matched_key": record["matched_key"],
        "scene_seed": record["scene_seed"],
        "failure_seed": record["failure_seed"],
        "sdf_sha256": record["sdf_sha256"],
        "supervision_sha256": record["supervision_sha256"],
        "decision_source": AUDIT.DECISION_SOURCE,
        "model_owned": False,
        "model_rollout": False,
        "training_executed": False,
        "evaluation_executed": False,
        "formal_q_b_evaluation": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "derived_probe_sha256": DERIVED_SHA,
        "upstream_v4_probe_sha256": UPSTREAM_SHA,
        "runtime_registry_sha256": "3" * 64,
        "urdf_sha256": URDF_SHA,
        "training_key_manifest_sha256": AUDIT.sha256_file(TRAINING),
        "s6_key_manifest_sha256": AUDIT.sha256_file(S6),
    }


def _receipt(index: int, *, matched_key: str) -> dict:
    controller = "REJECTED" if index == 7 else "PASS"
    frame, units, dimensions = AUDIT.EXPECTED_PROTOCOLS[index]
    measurements = (
        {"status": "CONTACT_GATE_REJECTED", "object_lift_m": 0.0, "follow_error_m": None}
        if index == 7
        else {"status": "PASS"}
    )
    receipt = {
        "schema_version": "PathBlockedPhysicalSkillReceiptV2",
        "receipt_id": f"{matched_key}-physical-{index}",
        "executed_skill": AUDIT.EXPECTED_SKILLS[index],
        "physically_executed": True,
        "controller_gate": controller,
        "execution_measurements": measurements,
        "execution_source": AUDIT.DECISION_SOURCE,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "action_protocol": {
            "schema_version": "PhysicalActionProtocolV2",
            "coordinate_frame": frame,
            "units": units,
            "dimensions": dimensions,
            "frequency_hz": 60,
            "normalization": "none",
        },
    }
    receipt["receipt_sha256"] = AUDIT.canonical_sha256(receipt)
    return receipt


def _raw(record: dict) -> dict:
    key = record["matched_key"]
    steps = []
    for index in range(8):
        steps.append(
            {
                "decision_index": index,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
                "observation": {
                    "observation_id": f"{key}-observation-{index}",
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                },
                "physical_receipts": [_receipt(index, matched_key=key)],
            }
        )
    return {
        "schema_version": AUDIT.RAW_SCHEMA,
        "status": "PASS",
        "not_policy_rollout": True,
        "m2c_path_blocked_physical_chain": {
            "schema_version": AUDIT.CHAIN_SCHEMA,
            "collection_role": "TRAIN",
            "split": "train",
            "failure_type": "PATH_BLOCKED",
            "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
            "matched_key": key,
            "scene_seed": record["scene_seed"],
            "failure_seed": record["failure_seed"],
            "sdf_sha256": record["sdf_sha256"],
            "supervision_sha256": record["supervision_sha256"],
            "model_rollout": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "final_task_success": False,
            "steps": steps,
        },
    }


def _attempt(root: Path, record: dict, *, classification: str) -> Path:
    root.mkdir(parents=True)
    _write_json(root / "collection-job-v2.json", _job(record))
    if classification == AUDIT.INFRASTRUCTURE_EXIT_139:
        console = root / "stage/console.log"
        console.parent.mkdir(parents=True, exist_ok=True)
        console.write_text(
            f"[Fatal] [carb.crashreporter-breakpad.plugin] crash\n{AUDIT.STAGE_EXIT_139_SUFFIX}\n",
            encoding="utf-8",
        )
        return root
    _write_json(
        root / "stage/metrics.json",
        {
            "status": "PASS",
            "source_hashes": {
                f"scene-{record['scene_seed']}.sdf": record["sdf_sha256"],
                f"scene-{record['scene_seed']}.supervision.json": record["supervision_sha256"],
                "panda_controlled.urdf": URDF_SHA,
            },
        },
    )
    console = root / "probe/console.log"
    console.parent.mkdir(parents=True, exist_ok=True)
    if classification == AUDIT.CONTACT_REJECTION:
        console.write_text("complete scripted probe\n", encoding="utf-8")
        _write_json(root / "probe/actuation-probe.json", _raw(record))
    else:
        console.write_text(f"traceback\n{AUDIT.K8_CONSOLE_SUFFIX}\n", encoding="utf-8")
    return root


def _fixture(tmp_path: Path) -> tuple[list[tuple[Path, str]], list[Path]]:
    training = json.loads(TRAINING.read_text())
    by_scene = {item["scene_seed"]: item for item in training["training_keys"]}
    scenes = (*AUDIT.INITIAL_ATTEMPTED_SCENE_SEEDS, *AUDIT.BATCH02_SELECTED_SCENE_SEEDS)
    roots: list[Path] = []
    specs: list[tuple[Path, str]] = []
    for index, scene in enumerate(scenes):
        record = by_scene[scene]
        classification = (
            AUDIT.CONTACT_REJECTION
            if scene in {12050, 12086}
            else AUDIT.INFRASTRUCTURE_EXIT_139
            if scene == 12169
            else AUDIT.K8_REJECTION
        )
        attempt = _attempt(tmp_path / f"attempt-{index}", record, classification=classification)
        roots.append(attempt)
        specs.append((attempt, classification))
    return specs, roots


def _frozen() -> dict:
    return AUDIT.load_frozen_manifests(TRAINING, S6)


def test_audit_reports_only_observed_fail_closed_collection_facts(tmp_path: Path) -> None:
    specs, _roots = _fixture(tmp_path)
    report = AUDIT.build_report(
        specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG
    )

    assert report["status"] == "BLOCKED_ZERO_ELIGIBLE_TRAIN_SAMPLES"
    assert report["scope"] == {
        "frozen_training_keys": 36,
        "unique_training_keys_audited": 11,
        "unobserved_training_keys": 25,
        "inference_about_unobserved_training_keys": None,
        "smoke_keys_used": 0,
        "s6_evaluation_keys_used": 0,
        "v4_keys_used": 0,
    }
    assert report["observed_counts"] == {
        "public_target_outside_canonical_k8": 8,
        "raw_pass_final_false_regrasp_contact_gate_rejected": 2,
        "infrastructure_stage_exit_139": 1,
        "training_samples_packaged": 0,
        "training_samples_eligible": 0,
    }
    assert report["execution_boundaries"] == {
        "training_executed": False,
        "model_rollout_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_q_b_evaluation_executed": False,
        "scripted_collection_counted_as_pure_model_success": False,
        "pure_model_success_episodes": None,
    }
    assert len({item["identity"]["matched_key"] for item in report["attempts"]}) == 11
    assert all(not item["training_sample_eligible"] for item in report["attempts"])
    assert all(not item["counted_as_pure_model_success"] for item in report["attempts"])


def test_audit_rejects_duplicate_key_and_wrong_classification(tmp_path: Path) -> None:
    specs, roots = _fixture(tmp_path)
    duplicate = tmp_path / "duplicate"
    shutil.copytree(roots[0], duplicate)
    duplicate_specs = specs[:10] + [(duplicate, AUDIT.K8_REJECTION)]
    with pytest.raises(ValueError, match="duplicated"):
        AUDIT.build_report(
            duplicate_specs,
            training_path=TRAINING,
            s6_path=S6,
            batch02_prereg_path=PREREG,
        )

    with pytest.raises(ValueError, match="forbids a raw probe envelope"):
        AUDIT.audit_attempt(
            roots[4],
            AUDIT.K8_REJECTION,
            frozen=_frozen(),
            training_path=TRAINING,
            s6_path=S6,
        )
    with pytest.raises(ValueError, match="requires a raw probe"):
        AUDIT.audit_attempt(
            roots[0],
            AUDIT.CONTACT_REJECTION,
            frozen=_frozen(),
            training_path=TRAINING,
            s6_path=S6,
        )
    with pytest.raises(ValueError, match="classification console"):
        AUDIT.audit_attempt(
            roots[9],
            AUDIT.K8_REJECTION,
            frozen=_frozen(),
            training_path=TRAINING,
            s6_path=S6,
        )
    with pytest.raises(ValueError, match="classification console"):
        AUDIT.audit_attempt(
            roots[8],
            AUDIT.INFRASTRUCTURE_EXIT_139,
            frozen=_frozen(),
            training_path=TRAINING,
            s6_path=S6,
        )


def test_audit_rejects_console_and_raw_semantic_tampering(tmp_path: Path) -> None:
    specs, roots = _fixture(tmp_path)
    (roots[0] / "probe/console.log").write_text("probe stopped for another reason\n")
    with pytest.raises(ValueError, match="exact canonical K8 rejection"):
        AUDIT.build_report(specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG)

    specs, roots = _fixture(tmp_path / "raw")
    raw_path = roots[4] / "probe/actuation-probe.json"
    raw = json.loads(raw_path.read_text())
    receipt = raw["m2c_path_blocked_physical_chain"]["steps"][-1]["physical_receipts"][0]
    receipt["execution_measurements"]["status"] = "PASS"
    receipt_core = dict(receipt)
    receipt_core.pop("receipt_sha256")
    receipt["receipt_sha256"] = AUDIT.canonical_sha256(receipt_core)
    _write_json(raw_path, raw)
    with pytest.raises(ValueError, match="not CONTACT_GATE_REJECTED"):
        AUDIT.build_report(specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG)

    specs, roots = _fixture(tmp_path / "infra")
    (roots[9] / "stage/console.log").write_text(
        "[Fatal] [carb.crashreporter-breakpad.plugin] crash\nexit code 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exact exit-139 receipt"):
        AUDIT.build_report(specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG)


def test_frozen_report_replay_detects_nonsemantic_byte_tampering(tmp_path: Path) -> None:
    specs, roots = _fixture(tmp_path)
    report = AUDIT.build_report(
        specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG
    )
    expected = tmp_path / "expected.json"
    _write_json(expected, report)

    console = roots[1] / "probe/console.log"
    console.write_text("extra nonsemantic line\n" + console.read_text(), encoding="utf-8")
    replay = AUDIT.build_report(
        specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG
    )
    with pytest.raises(ValueError, match="differs from the frozen expected report"):
        AUDIT.verify_expected_report(replay, expected)

    raw_path = roots[4] / "probe/actuation-probe.json"
    raw_path.write_text(raw_path.read_text() + " \n", encoding="utf-8")
    replay = AUDIT.build_report(
        specs, training_path=TRAINING, s6_path=S6, batch02_prereg_path=PREREG
    )
    with pytest.raises(ValueError, match="differs from the frozen expected report"):
        AUDIT.verify_expected_report(replay, expected)


def test_job_validator_rejects_smoke_s6_and_v4_inputs() -> None:
    frozen = _frozen()
    training = json.loads(TRAINING.read_text())
    s6 = json.loads(S6.read_text())

    smoke = _job(training["physical_prerequisite_smoke_keys"][0])
    with pytest.raises(ValueError, match="SMOKE key"):
        AUDIT._validate_job(smoke, frozen, training_path=TRAINING, s6_path=S6)

    evaluation = _job(s6["evaluation_keys"][0])
    with pytest.raises(ValueError, match="S6 evaluation key"):
        AUDIT._validate_job(evaluation, frozen, training_path=TRAINING, s6_path=S6)

    v4 = dict(_job(training["training_keys"][0]))
    v4["matched_key"] = training["v4_excluded_matched_keys"][0]
    v4["scene_seed"] = training["v4_excluded_scene_seeds"][0]
    with pytest.raises(ValueError, match="V4 key or scene"):
        AUDIT._validate_job(v4, frozen, training_path=TRAINING, s6_path=S6)
