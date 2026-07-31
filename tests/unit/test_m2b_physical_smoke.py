from __future__ import annotations

import json
from types import SimpleNamespace

from m2b.run_physical_failure_smoke import (
    accepted,
    command,
    retained_attempt_record,
    same_color_entity_schedule,
    scheduled_entity,
)


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
    assert "configured_injection_entity" in record


def test_wrong_recovery_forwards_explicit_bounded_training_offset(
    tmp_path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "scene.sdf").write_text(
        """<sdf><world>
        <model name="cylinder_04"><pose>-0.10 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.6 0.1 1</diffuse></material>
        </visual></link></model>
        <model name="cylinder_05"><pose>-0.20 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.6 0.1 1</diffuse></material>
        </visual></link></model>
        <model name="cylinder_07"><pose>-0.12 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.1 0.1 1</diffuse></material>
        </visual></link></model>
        <model name="cylinder_01"><pose>-0.30 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.1 0.1 1</diffuse></material>
        </visual></link></model>
        </world></sdf>"""
    )
    args = SimpleNamespace(
        container_prefix="m2b-test",
        public_target_object="cylinder_04",
        capture_public_rgbd=True,
        target_object="cylinder_04",
        wrong_object_task_target="cylinder_07",
        release_follow_delta_z_m=0.08,
        public_regrasp_offset_camera_xyz_m="0.006,-0.002,0.003",
        gpu=0,
        project_root=tmp_path / "project",
        source_root=source_root,
        stage=tmp_path / "stage" / "scene.usdc",
        sdf=tmp_path / "source" / "scene.sdf",
        supervision=tmp_path / "source" / "scene.supervision.json",
        image="isaac:test",
        contact_centerline_m="0.12",
    )
    invocation = command(
        args,
        failure="WRONG_OBJECT",
        attempt=1,
        output=tmp_path / "output",
    )
    offset_index = (
        invocation.index("--m2b-public-regrasp-offset-camera-xyz-m") + 1
    )
    assert invocation[offset_index] == "0.006,-0.002,0.003"
    second_invocation = command(
        args,
        failure="WRONG_OBJECT",
        attempt=2,
        output=tmp_path / "output-2",
    )
    assert second_invocation[second_invocation.index("--target-object") + 1] == (
        "cylinder_05"
    )
    assert second_invocation[
        second_invocation.index("--m2b-task-target-object") + 1
    ] == "cylinder_07"


def test_physical_retry_rotates_same_color_supervision_entity(tmp_path) -> None:
    sdf = tmp_path / "scene.sdf"
    sdf.write_text(
        """<sdf><world>
        <model name="cylinder_10"><pose>-0.10 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.6 0.1 1</diffuse></material>
        </visual></link></model>
        <model name="cylinder_04"><pose>-0.25 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.6 0.1 1</diffuse></material>
        </visual></link></model>
        <model name="cylinder_01"><pose>-0.30 0 0 0 0 0</pose><link><visual>
        <material><diffuse>0.8 0.1 0.1 1</diffuse></material>
        </visual></link></model>
        </world></sdf>"""
    )
    assert same_color_entity_schedule(sdf, "cylinder_10") == (
        "cylinder_10",
        "cylinder_04",
    )
    assert scheduled_entity(sdf, "cylinder_10", 1) == "cylinder_10"
    assert scheduled_entity(sdf, "cylinder_10", 2) == "cylinder_04"
    assert scheduled_entity(sdf, "cylinder_10", 3) == "cylinder_04"
