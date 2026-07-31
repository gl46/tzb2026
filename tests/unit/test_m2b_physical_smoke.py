from __future__ import annotations

import json

from m2b.run_physical_failure_smoke import accepted, retained_attempt_record


def test_empty_grasp_smoke_requires_failure_and_real_regrasp() -> None:
    payload = {
        "status": "PASS",
        "m2b_injection_pass": True,
        "m2b_empty_grasp_injection": {
            "failure_type": "EMPTY_GRASP",
            "physical_state_passed": True,
            "training_eligible": False,
        },
        "m2b_recovery": {
            "empty_grasp": {"physical_regrasp_and_lift_passed": True}
        },
    }
    assert accepted(payload, "EMPTY_GRASP") is True
    payload["m2b_empty_grasp_injection"]["physical_state_passed"] = False
    assert accepted(payload, "EMPTY_GRASP") is False


def test_release_smoke_requires_failed_release_then_real_retry() -> None:
    payload = {
        "status": "PASS",
        "m2b_injection_pass": True,
        "m2b_release_failure_injection": {
            "failure_type": "RELEASE_FAILURE",
            "physical_state_passed": True,
            "training_eligible": False,
        },
        "m2b_recovery": {
            "release_failure": {"retry_detach_and_retreat_passed": True}
        },
    }
    assert accepted(payload, "RELEASE_FAILURE") is True
    payload["m2b_recovery"]["release_failure"][
        "retry_detach_and_retreat_passed"
    ] = False
    assert accepted(payload, "RELEASE_FAILURE") is False


def test_wrong_object_smoke_requires_contact_mismatch_and_safe_place() -> None:
    payload = {
        "status": "PASS",
        "m2b_injection_pass": True,
        "m2b_wrong_object_injection": {
            "failure_type": "WRONG_OBJECT",
            "physical_state_passed": True,
            "training_eligible": False,
        },
        "m2b_recovery": {
            "wrong_object": {
                "safe_place_non_target_passed": True,
                "reassociate_target_executed": False,
                "regrasp_target_executed": False,
            }
        },
    }
    assert accepted(payload, "WRONG_OBJECT") is True
    payload["m2b_recovery"]["wrong_object"]["safe_place_non_target_passed"] = False
    assert accepted(payload, "WRONG_OBJECT") is False


def test_public_rgbd_smoke_requires_public_failure_and_recovery_gates() -> None:
    empty = {
        "status": "PASS",
        "m2b_injection_pass": True,
        "m2b_empty_grasp_injection": {
            "failure_type": "EMPTY_GRASP",
            "physical_state_passed": True,
            "training_eligible": True,
        },
        "m2b_recovery": {
            "empty_grasp": {
                "physical_regrasp_and_lift_passed": True,
                "training_eligible": True,
            }
        },
    }
    assert accepted(
        empty, "EMPTY_GRASP", public_rgbd_required=True
    ) is True
    empty["m2b_recovery"]["empty_grasp"]["training_eligible"] = False
    assert accepted(
        empty, "EMPTY_GRASP", public_rgbd_required=True
    ) is False


def test_restart_retains_hash_bound_accepted_attempt(tmp_path) -> None:
    output = tmp_path / "attempt-01"
    output.mkdir()
    payload = {
        "status": "PASS",
        "m2b_injection_pass": True,
        "m2b_empty_grasp_injection": {
            "failure_type": "EMPTY_GRASP",
            "physical_state_passed": True,
            "training_eligible": True,
        },
        "m2b_recovery": {
            "empty_grasp": {
                "physical_regrasp_and_lift_passed": True,
                "training_eligible": True,
            }
        },
    }
    evidence = output / "actuation-probe.json"
    evidence.write_text(json.dumps(payload))
    record = retained_attempt_record(
        output,
        failure="EMPTY_GRASP",
        attempt=1,
        public_rgbd_required=True,
    )
    assert record is not None
    assert record["accepted"] is True
    assert record["resumed_existing_attempt"] is True
    assert len(record["evidence_sha256"]) == 64
