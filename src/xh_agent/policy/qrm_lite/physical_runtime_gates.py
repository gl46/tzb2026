"""Extract conservative runtime-gate receipts from physical Isaac evidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


GateStatus = Literal["PASS", "REJECTED", "NOT_APPLICABLE", "NOT_RUN"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhysicalRuntimeGateReceiptV1(StrictModel):
    schema_version: Literal["PhysicalRuntimeGateReceiptV1"] = (
        "PhysicalRuntimeGateReceiptV1"
    )
    failure_type: Literal["EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"]
    recovery_skill: str
    runtime_action: str
    ik_gate: GateStatus
    collision_gate: GateStatus
    safety_gate: GateStatus
    physical_recovery_success: bool
    prospective_planning_check: Literal[False] = False
    model_selected: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False
    details: dict[str, Any]

    @property
    def complete_and_passing(self) -> bool:
        return all(
            gate in {"PASS", "NOT_APPLICABLE"}
            for gate in (self.ik_gate, self.collision_gate, self.safety_gate)
        ) and self.physical_recovery_success


def _motion_gate(motion: dict[str, Any]) -> tuple[GateStatus, GateStatus]:
    final_error = motion.get("final_error_m")
    ik = (
        "PASS"
        if isinstance(final_error, (int, float)) and float(final_error) <= 0.020
        else "REJECTED"
    )
    collision = (motion.get("collision_gate") or {}).get("status", "NOT_RUN")
    if collision not in {"PASS", "REJECTED"}:
        collision = "NOT_RUN"
    return ik, collision


def extract_physical_runtime_gate_receipt(
    payload: dict[str, Any],
    *,
    failure_type: str,
) -> PhysicalRuntimeGateReceiptV1:
    """Build a post-execution receipt; never promote it to model attribution."""

    public = payload.get("m2b_public_rgbd") or {}
    if public.get("simulator_truth_policy_input") is not False:
        raise ValueError("physical runtime evidence lacks a public-only policy input declaration")
    recovery = payload.get("m2b_recovery") or {}
    if failure_type == "EMPTY_GRASP":
        item = recovery.get("empty_grasp") or {}
        labels = {
            capture.get("label") for capture in public.get("captures", [])
        }
        observed = "empty_grasp_reobserve" in labels
        success = bool(item.get("training_eligible") is True and observed)
        return PhysicalRuntimeGateReceiptV1(
            failure_type="EMPTY_GRASP",
            recovery_skill="REOBSERVE",
            runtime_action="HOLD_AND_CAPTURE_PUBLIC_RGBD",
            ik_gate="NOT_APPLICABLE",
            collision_gate="NOT_APPLICABLE",
            safety_gate="PASS" if observed else "REJECTED",
            physical_recovery_success=success,
            details={
                "capture_observed": observed,
                "source": "PUBLIC_RGBD_CAPTURE_POST_EXECUTION_RECEIPT",
            },
        )

    retreat = (payload.get("phases") or {}).get("detach_retreat") or {}
    ik, collision = _motion_gate(retreat)
    detached = payload.get("detached_noncoupling") or {}
    safety = "PASS" if detached.get("passed") is True else "REJECTED"
    if failure_type == "WRONG_OBJECT":
        item = recovery.get("wrong_object") or {}
        success = bool(
            item.get("training_eligible") is True
            and item.get("safe_place_non_target_passed") is True
        )
        return PhysicalRuntimeGateReceiptV1(
            failure_type="WRONG_OBJECT",
            recovery_skill="SAFE_PLACE_NON_TARGET",
            runtime_action="B0_SAFE_PLACE_NON_TARGET",
            ik_gate=ik,
            collision_gate=collision,
            safety_gate=safety,
            physical_recovery_success=success,
            details={
                "detach_retreat": retreat,
                "detached_noncoupling": detached,
                "source": "ISAAC_DLS_PHYSX_POST_EXECUTION_RECEIPT",
            },
        )
    if failure_type == "RELEASE_FAILURE":
        item = recovery.get("release_failure") or {}
        success = bool(
            item.get("training_eligible") is True
            and item.get("retry_detach_and_retreat_passed") is True
        )
        return PhysicalRuntimeGateReceiptV1(
            failure_type="RELEASE_FAILURE",
            recovery_skill="RETRY_RELEASE",
            runtime_action="B0_RELEASE_RETRY",
            ik_gate=ik,
            collision_gate=collision,
            safety_gate=safety,
            physical_recovery_success=success,
            details={
                "detach_retreat": retreat,
                "detached_noncoupling": detached,
                "source": "ISAAC_DLS_PHYSX_POST_EXECUTION_RECEIPT",
            },
        )
    raise ValueError(f"unsupported failure type: {failure_type}")
