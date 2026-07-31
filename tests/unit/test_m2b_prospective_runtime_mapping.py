from __future__ import annotations

from pathlib import Path
import hashlib

import pytest
from pydantic import ValidationError

from m2b.build_prospective_runtime_decisions import (
    IsolatedIsaacPreflightManifestV1,
    build_records,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    PhysicalRuntimeGateReceiptV1,
)
from xh_agent.policy.qrm_lite.prospective_mapping import (
    M2BProspectiveRuntimeDecisionV1,
    summarize_prospective_runtime_mapping,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    RuntimeSkillRequestV1,
    load_registry,
    validate_runtime_mapping,
)


ROOT = Path(__file__).parents[2]
REGISTRY = load_registry(ROOT / "configs/qrm_runtime_mapping.yaml")


def request() -> RuntimeSkillRequestV1:
    return RuntimeSkillRequestV1(
        model_class_id="coarse.skill.APPROACH",
        skill="APPROACH",
        task_target_track_id="track-01",
        available_track_ids=["track-01"],
        coordinate_frame="world",
        units="m",
        current_phase="APPROACH",
        confidence=0.9,
    )


def record(
    index: int,
    *,
    failure_type: str,
) -> M2BProspectiveRuntimeDecisionV1:
    mapping = validate_runtime_mapping(
        request(),
        REGISTRY,
        ik_check=lambda _action, _parameters: (True, None),
        collision_check=lambda _action, _parameters: (True, None),
        safety_check=lambda _action, _parameters: (True, None),
    )
    return M2BProspectiveRuntimeDecisionV1(
        decision_id=f"decision-{index}",
        sample_id=f"sample-{index}",
        failure_type=failure_type,
        request=request(),
        mapping=mapping,
        ik_gate="PASS",
        collision_gate="PASS",
        safety_gate="PASS",
        registry_sha256="a" * 64,
        model_checkpoint_sha256="b" * 64,
        model_input_sha256=f"{index + 1:064x}",
        model_output_sha256=f"{index + 101:064x}",
        request_sha256=f"{index + 201:064x}",
        structural_mapping_result_sha256=f"{index + 251:064x}",
        mapping_result_sha256=f"{index + 301:064x}",
        source_hashes={"scene.sdf": f"{index + 401:064x}"},
        isolated_preflight_evidence_path=f"/evidence/{index}.json",
        isolated_preflight_evidence_sha256=f"{index + 501:064x}",
        prospective_planning_check=True,
        isolated_from_evaluation_rollout=True,
        evaluation_execution_started=False,
    )


def test_twenty_unique_three_class_prospective_mappings_pass() -> None:
    failures = (
        "EMPTY_GRASP",
        "WRONG_OBJECT",
        "RELEASE_FAILURE",
    )
    records = [
        record(index, failure_type=failures[index % len(failures)])
        for index in range(20)
    ]
    report = summarize_prospective_runtime_mapping(records)
    assert report["formal_mapping_ready"] is True
    assert report["runtime_mapping_rate"] == 1.0
    assert report["planning_checks_complete"] is True
    assert report["post_execution_receipts_promoted"] is False
    assert report["teacher_used"] is False


def test_post_execution_receipt_cannot_claim_prospective_mapping() -> None:
    payload = record(0, failure_type="EMPTY_GRASP").model_dump(
        mode="json"
    )
    payload["prospective_planning_check"] = False
    with pytest.raises(
        ValidationError,
        match="not prospective to evaluation execution",
    ):
        M2BProspectiveRuntimeDecisionV1.model_validate(payload)


def test_duplicate_model_sample_does_not_satisfy_scale_gate() -> None:
    failures = (
        "EMPTY_GRASP",
        "WRONG_OBJECT",
        "RELEASE_FAILURE",
    )
    records = [
        record(index, failure_type=failures[index % len(failures)])
        for index in range(20)
    ]
    records[-1] = records[-1].model_copy(
        update={"sample_id": records[0].sample_id}
    )
    report = summarize_prospective_runtime_mapping(records)
    assert report["formal_mapping_ready"] is False
    assert report["findings"] == ["duplicate sample_id"]


def test_heldout_record_binds_to_matching_isolated_preflight() -> None:
    runtime_request = request()
    structural = validate_runtime_mapping(runtime_request, REGISTRY)
    model_input = {"observation": {"sample": 1}, "rgb_sha256": "f" * 64}
    model_output = {"skill": "APPROACH", "confidence": 0.9}
    request_payload = runtime_request.model_dump(mode="json")
    mapping_payload = structural.model_dump(mode="json")
    model_record = {
        "sample_id": "sample-1",
        "failure_type": "EMPTY_GRASP",
        "model_input": model_input,
        "model_output": model_output,
        "request": request_payload,
        "mapping": mapping_payload,
        "registry_sha256": hashlib.sha256(
            (ROOT / "configs/qrm_runtime_mapping.yaml").read_bytes()
        ).hexdigest(),
        "model_checkpoint_sha256": "b" * 64,
        "model_input_sha256": canonical_sha256(model_input),
        "model_output_sha256": canonical_sha256(model_output),
        "request_sha256": canonical_sha256(request_payload),
        "mapping_result_sha256": canonical_sha256(mapping_payload),
    }
    preflight = IsolatedIsaacPreflightManifestV1(
        sample_id="sample-1",
        failure_type="EMPTY_GRASP",
        source_hashes={"scene.sdf": "c" * 64},
        preflight_evidence_path="/evidence/preflight.json",
        preflight_evidence_sha256="d" * 64,
        receipt=PhysicalRuntimeGateReceiptV1(
            failure_type="EMPTY_GRASP",
            recovery_skill="APPROACH",
            runtime_action="B0_PUBLIC_GEOMETRY_APPROACH",
            ik_gate="PASS",
            collision_gate="PASS",
            safety_gate="PASS",
            physical_recovery_success=True,
            details={"source": "ISOLATED_PREFLIGHT"},
        ),
    )
    records = build_records(
        [model_record],
        [preflight],
        registry_path=ROOT / "configs/qrm_runtime_mapping.yaml",
    )
    assert len(records) == 1
    assert records[0].mapping.status == "VALID"
    assert records[0].executable_mapping is True
    assert records[0].prospective_planning_check is True
    assert records[0].isolated_preflight_evidence_sha256 == "d" * 64
