from __future__ import annotations

import hashlib
import json
from pathlib import Path

from m2c.qwen_decision_level_v4 import load_adr0026_decision_bundle_v4


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/m2c-s4-qwen-adr0026-training.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict[str, object]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_adr0026_two_arm_training_report_is_source_bound_and_honest() -> None:
    report = _report()
    assert report["schema_version"] == "M2CS4QwenADR0026TwoArmTrainingReportV1"
    assert report["status"] == "PASS_TWO_ARM_A100_TRAINING_NOT_Q_B"
    assert report["training_source_commit"] == ("81dbb5efe4010fc34162f4113122d11feed04165")

    for binding in report["source_bindings"]:
        path = ROOT / binding["path"]
        assert path.is_file()
        assert _sha256(path) == binding["sha256"]

    dataset = report["dataset"]
    assert dataset == {
        "manifest_file_sha256": (
            "9d1b15412b193ef2662ce518fc2bf19016116c70ab026c581c68bb40cb10e03a"
        ),
        "manifest_sha256": ("9e2e93b2b9fb95dcf632a8a6350b6fc6f70c2eb5de1cd8ae2bea5041f4b1dcbb"),
        "v4_shard_sha256": ("78c28350fd59c74df018724c44aa6705785909fcc7607d0ad0e27d7148efd86d"),
        "rows": 273,
        "episodes": 39,
        "decision_indices": "0-6",
        "pointer_supervised_rows": 259,
        "pointer_masked_rows": 14,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }

    contract = report["common_training_contract"]
    assert contract == {
        "seed": 20260815,
        "epochs": 1,
        "learning_rate": 0.0001,
        "optimizer_steps": 273,
        "wall_budget_seconds": 21600.0,
        "only_intended_arm_difference": "failure_context",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "physical_evaluation_executed": False,
    }

    arms = report["arms"]
    assert set(arms) == {"FC", "NO_FC"}
    assert arms["FC"]["failure_context"] == "on"
    assert arms["NO_FC"]["failure_context"] == "off"
    assert arms["FC"]["bundle_sha256"] == (
        "6e7cb272445a64413d6adbe687431172816148f2bd571ada28ec7075fc2dd2a2"
    )
    assert arms["NO_FC"]["bundle_sha256"] == (
        "1b6757dc66bbabc939858f477537e18ef9797edce2c57c95f7ae6f4423c72138"
    )
    assert arms["FC"]["head_checkpoint_sha256"] != arms["NO_FC"]["head_checkpoint_sha256"]
    assert arms["FC"]["adapter_tree_sha256"] != arms["NO_FC"]["adapter_tree_sha256"]
    assert (
        arms["FC"]["training_dataset_report_sha256"]
        == arms["NO_FC"]["training_dataset_report_sha256"]
    )

    claims = report["claims"]
    assert claims == {
        "training_performed": True,
        "two_arm_bundle_load_replay_passed": True,
        "training_fit_metrics_are_held_out": False,
        "model_rollout_performed": False,
        "formal_q_b_evaluation_performed": False,
        "physical_execution_performed": False,
        "pure_model_success_episodes": None,
        "d2_triggered": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    assert report["failures"] == []
    assert report["blockers"] == [
        "ADR0026_DECISION_BUNDLE_RUNTIME_NOT_IN_FORMAL_DEPLOYMENT_CLOSURE",
        "FORMAL_Q_B_PHYSICAL_EVALUATION_NOT_RUN",
        "PURE_MODEL_SUCCESS_REMAINS_UNMEASURED",
    ]


def test_local_two_arm_mirrors_replay_when_available() -> None:
    report = _report()
    for arm in report["arms"].values():
        root = Path(arm["local_mirror_root"])
        if not root.is_dir():
            continue
        loaded = load_adr0026_decision_bundle_v4(
            root,
            expected_bundle_sha256=arm["bundle_sha256"],
        )
        assert loaded.manifest.failure_context == arm["failure_context"]
        assert loaded.manifest.train_samples == 273
        assert loaded.manifest.train_episodes == 39
        assert _sha256(root / "train_report.json") == arm["train_report_file_sha256"]
        assert (
            _sha256(root / "qwen_adr0026_decision_v4_bundle.json")
            == arm["bundle_manifest_file_sha256"]
        )
        assert _sha256(root / "qwen_coarse_v4_heads.npz") == arm["head_checkpoint_sha256"]
        assert (
            _sha256(root / "qwen_coarse_v4_checkpoint_deployment.json")
            == arm["head_deployment_file_sha256"]
        )
        for relative, expected in arm["adapter_files"].items():
            assert _sha256(root / "adapter" / relative) == expected
