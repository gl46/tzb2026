from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports/m2c-s4-qwen-adr0026-runtime-smoke.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict[str, object]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_runtime_smoke_report_is_source_bound_and_withholds_q_b_claims() -> None:
    report = _report()
    assert report["schema_version"] == "M2CS4QwenADR0026RuntimeStartupSmokeReportV1"
    assert report["status"] == "PASS_TWO_ARM_REAL_QWEN_RUNTIME_STARTUP_NOT_Q_B"
    assert report["implementation_commit"] == ("01883be7f976810b2850c43fb956d764e8df496f")
    for binding in report["source_bindings"]:
        path = ROOT / binding["path"]
        assert path.is_file()
        assert _sha256(path) == binding["sha256"]

    command = report["command_contract"]
    assert command["bundle_contract"] == "ADR0026_DECISION_LEVEL_PREFIX_0_6_V1"
    assert command["startup_check_only"] is True
    assert command["http_service_started"] is False
    assert command["wire_requests_received"] == 0
    assert command["isaac_started"] is False
    assert command["physical_execution_performed"] is False
    assert command["formal_q_b_evaluation_performed"] is False
    assert command["teacher_used"] is False
    assert command["privileged_truth_policy_input"] is False

    smoke_inputs = report["contract_smoke_only_inputs"]
    assert smoke_inputs["production_deployment_evidence"] is False
    assert smoke_inputs["physical_policy_input_used"] is False

    arms = report["arms"]
    assert set(arms) == {"FC", "NO_FC"}
    assert arms["FC"]["failure_context"] == "on"
    assert arms["NO_FC"]["failure_context"] == "off"
    assert arms["FC"]["bundle_sha256"] != arms["NO_FC"]["bundle_sha256"]
    assert arms["FC"]["exit_code"] == arms["NO_FC"]["exit_code"] == 0

    claims = report["claims"]
    assert claims["both_trained_bundles_loaded"] is True
    assert claims["real_qwen_backbone_loaded"] is True
    assert claims["real_lora_adapter_loaded"] is True
    assert claims["three_heads_loaded"] is True
    assert claims["model_rollout_performed"] is False
    assert claims["formal_q_b_evaluation_performed"] is False
    assert claims["physical_execution_performed"] is False
    assert claims["pure_model_success_episodes"] is None
    assert claims["d2_triggered"] is False
    assert report["failures"] == []


def test_runtime_smoke_external_bindings_and_audits_replay_when_available() -> None:
    report = _report()
    shared = report["shared_runtime_binding"]
    for arm_name, arm in report["arms"].items():
        binding_path = Path(arm["binding_path"])
        audit_path = Path(arm["audit_path"])
        if not binding_path.is_file() or not audit_path.is_file():
            continue
        assert _sha256(binding_path) == arm["binding_file_sha256"]
        assert _sha256(audit_path) == arm["audit_file_sha256"]

        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        for key, expected in shared.items():
            assert binding[key] == expected
        assert binding["failure_context"] == arm["failure_context"]
        assert binding["bundle_sha256"] == arm["bundle_sha256"]
        assert binding["bundle_tree_sha256"] == arm["bundle_tree_sha256"]
        assert binding["training_complete"] is True
        assert binding["local_files_only"] is True
        assert binding["teacher_used"] is False
        assert binding["privileged_truth_policy_input"] is False
        assert binding["physical_evaluation_executed"] is False

        events = [json.loads(line) for line in audit_path.read_text().splitlines()]
        assert [event["sequence"] for event in events] == [1, 2]
        assert [event["event_type"] for event in events] == [
            "SERVICE_STARTED",
            "SERVICE_STOPPED",
        ]
        assert {event["schema_version"] for event in events} == {"FormalQwenAuditEventV4"}
        assert events[0]["payload"]["service_id"] == arm["service_id"]
        assert events[1]["payload"]["service_id"] == arm["service_id"]
        assert events[1]["payload"] == {
            "completed": False,
            "poisoned": False,
            "privileged_truth_policy_input": False,
            "protocol": "M2C_FORMAL_SPLIT_RUNNER_V4",
            "rejections_recorded": 0,
            "responses_committed": 0,
            "run_id": None,
            "service_id": arm["service_id"],
            "startup_check_only": True,
            "teacher_used": False,
        }
        assert arm_name in {"FC", "NO_FC"}
