"""ADR-0022 Phase-2 exact-plan primitive bundle contract.

This module contains no robot motion and is not a deployment binding.  It
turns the already frozen :class:`ExactExecutionPlanV2` wire object into the
larger, immutable A.1--A.4 record required by ADR-0022, verifies every phase
before an executor is called, and then gives a hash-bound executor only the
precomputed phases in their original order.  A real executor remains
unavailable until the separately reviewed binding addendum exists.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import re
import stat
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    SHA256_PATTERN,
    canonical_sha256,
)


ADR_0022_PATH = "docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"
PHYSICAL_COMMANDS = frozenset(
    {
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "REMOVE_ATTACHMENT",
    }
)
_REQUIRED_SOURCE_ROLES = frozenset(
    {
        "PRIMITIVE_ENTRYPOINT",
        "PREFLIGHT_IMPLEMENTATION",
        "EXECUTOR_IMPLEMENTATION",
        "TRANSITIVE_DEPENDENCY_MANIFEST",
        "ISAAC_RUNTIME",
        "IK_ALGORITHM",
        "JOINT_LIMIT_CONFIGURATION",
        "SWEPT_COLLISION_ALGORITHM",
        "ROBOT_ASSET",
        "CONTROLLER_CONFIGURATION",
        "SAFETY_CONFIGURATION",
        "SCENE_ASSET",
    }
)


class FrozenModel(BaseModel):
    """A recursively immutable strict contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactPlanUnavailable(RuntimeError):
    """Raised before actuation when the Phase-2 binding is incomplete."""


def _read_regular_file_sha256(path: Path) -> str:
    """Hash one stable regular file through one non-following descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ExactPlanUnavailable(f"binding source is not a single-link regular file: {path}")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise ExactPlanUnavailable(f"binding source changed while hashing: {path}")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


class ExactPlanSourceBindingV1(FrozenModel):
    schema_version: Literal["ExactPlanSourceBindingV1"] = "ExactPlanSourceBindingV1"
    role: Literal[
        "PRIMITIVE_ENTRYPOINT",
        "PREFLIGHT_IMPLEMENTATION",
        "EXECUTOR_IMPLEMENTATION",
        "TRANSITIVE_DEPENDENCY_MANIFEST",
        "ISAAC_RUNTIME",
        "IK_ALGORITHM",
        "JOINT_LIMIT_CONFIGURATION",
        "SWEPT_COLLISION_ALGORITHM",
        "ROBOT_ASSET",
        "CONTROLLER_CONFIGURATION",
        "SAFETY_CONFIGURATION",
        "SCENE_ASSET",
    ]
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    audit_only: Literal[True] = True


class ExactPlanA1InputsV1(FrozenModel):
    """All planning and audit inputs adopted from ADR-0022 A.1."""

    schema_version: Literal["ExactPlanA1InputsV1"] = "ExactPlanA1InputsV1"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    rgb_sha256: str = Field(pattern=SHA256_PATTERN)
    depth_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_public_tracks_sha256: str = Field(pattern=SHA256_PATTERN)
    signed_model_inference_response_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_mapping_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_skill: str = Field(min_length=1)
    runtime_action: str = Field(min_length=1)
    target_track_id: str | None = None
    destination_cell: str | None = Field(default=None, pattern=r"^BIN_CELL_[0-5]$")
    resolved_execution_parameters_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_frame: Literal["world"] = "world"
    preplan_state_dimensions: int = Field(gt=0)
    preplan_state_units: str = Field(min_length=1)
    preplan_state_timestamp_ns: int = Field(gt=0)
    preplan_state_freshness_limit_ns: int = Field(gt=0)
    plan_constructed_at_ns: int = Field(gt=0)
    action_frame: Literal["world"] = "world"
    position_units: Literal["m"] = "m"
    angular_units: Literal["rad_and_normalized_wxyz"] = "rad_and_normalized_wxyz"
    controller_frequency_hz: float = Field(gt=0.0)
    command_dimensions: int = Field(gt=0)
    convergence_tolerance_m: float = Field(gt=0.0)
    normalization: Literal["none"] = "none"
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    task_spec_fallback_used: Literal[False] = False
    privileged_identity_or_pose_used: Literal[False] = False
    privileged_contact_or_success_truth_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def state_is_fresh_and_finite(self) -> "ExactPlanA1InputsV1":
        values = (
            self.controller_frequency_hz,
            self.convergence_tolerance_m,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A.1 numeric contract contains NaN/Inf")
        if (
            self.plan_constructed_at_ns < self.preplan_state_timestamp_ns
            or self.plan_constructed_at_ns - self.preplan_state_timestamp_ns
            > self.preplan_state_freshness_limit_ns
        ):
            raise ValueError("pre-plan state is stale at plan construction")
        return self


class ExactGraspGeometryV1(FrozenModel):
    """Every runtime-selectable GRASP/REGRASP parameter, frozen pre-actuation."""

    schema_version: Literal["ExactGraspGeometryV1"] = "ExactGraspGeometryV1"
    selected_yaw_rad: float
    contact_centerline_m: float = Field(gt=0.0)
    finger_target_m: float = Field(ge=0.0, le=0.08)
    approach_phase_index: int = Field(ge=0)
    contact_phase_indices: tuple[int, ...] = Field(min_length=1)
    close_phase_index: int = Field(ge=0)
    attach_phase_index: int = Field(ge=0)
    lift_phase_index: int = Field(ge=0)
    retreat_phase_index: int = Field(ge=0)
    contact_allowlist_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def finite_geometry(self) -> "ExactGraspGeometryV1":
        if not all(
            math.isfinite(value)
            for value in (self.selected_yaw_rad, self.contact_centerline_m, self.finger_target_m)
        ):
            raise ValueError("grasp geometry contains NaN/Inf")
        return self


class ExactPlanPhaseContractV1(FrozenModel):
    """A.2 parameters missing from the legacy wire phase, now hash-bound."""

    schema_version: Literal["ExactPlanPhaseContractV1"] = "ExactPlanPhaseContractV1"
    phase: ExactExecutionPhaseV2
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    command_rate_hz: float = Field(gt=0.0)
    command_dimensions: int = Field(ge=0)
    position_units: Literal["m"] = "m"
    angular_units: Literal["rad_and_normalized_wxyz"] = "rad_and_normalized_wxyz"
    interpolation_rule: Literal["LINEAR_FIXED_STEPS", "NONE"]
    convergence_tolerance_m: float = Field(gt=0.0)
    timeout_ns: int = Field(gt=0)
    permitted_retry_count: Literal[0] = 0
    retry_phase_sha256_sequence: tuple[()] = ()
    allowed_robot_links_sha256: str = Field(pattern=SHA256_PATTERN)
    allowed_environment_paths_sha256: str = Field(pattern=SHA256_PATTERN)
    allowed_external_contact_paths_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_or_removal_selector: Literal[
        "NONE",
        "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST",
        "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT",
    ] = "NONE"
    freshness_transition: Literal[
        "NONE",
        "CAPTURE_RECEIPT_ADVANCES",
        "PUBLIC_ASSOCIATION_RECEIPT_ADVANCES",
    ] = "NONE"

    @model_validator(mode="after")
    def phase_is_exact(self) -> "ExactPlanPhaseContractV1":
        if self.phase_sha256 != canonical_sha256(self.phase):
            raise ValueError("phase digest differs from the immutable wire phase")
        if not all(
            math.isfinite(value) for value in (self.command_rate_hz, self.convergence_tolerance_m)
        ):
            raise ValueError("phase numeric contract contains NaN/Inf")
        expected_dimensions = {
            "CARTESIAN_POSE": 7,
            "GRIPPER_POSITION": 1,
            "ATTACH_CONTACT_ENTITY": 0,
            "REMOVE_ATTACHMENT": 0,
            "PUBLIC_RGBD_CAPTURE": 0,
            "PUBLIC_TRACK_REASSOCIATION": 0,
        }[self.phase.command]
        if self.command_dimensions != expected_dimensions:
            raise ValueError("phase command dimensions differ from the frozen command")
        expected_interpolation = (
            "LINEAR_FIXED_STEPS" if self.phase.command in PHYSICAL_COMMANDS else "NONE"
        )
        if self.interpolation_rule != expected_interpolation:
            raise ValueError("phase interpolation differs from its command kind")
        external_hash = canonical_sha256(self.phase.allowed_external_contact_paths)
        if self.allowed_external_contact_paths_sha256 != external_hash:
            raise ValueError("phase external-contact allowlist digest differs")
        if self.phase.command == "ATTACH_CONTACT_ENTITY":
            expected_selector = "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"
        elif self.phase.command == "REMOVE_ATTACHMENT":
            expected_selector = "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT"
        else:
            expected_selector = "NONE"
        if self.attachment_or_removal_selector != expected_selector:
            raise ValueError("phase attachment/removal selector differs")
        expected_freshness = {
            "PUBLIC_RGBD_CAPTURE": "CAPTURE_RECEIPT_ADVANCES",
            "PUBLIC_TRACK_REASSOCIATION": "PUBLIC_ASSOCIATION_RECEIPT_ADVANCES",
        }.get(self.phase.command, "NONE")
        if self.freshness_transition != expected_freshness:
            raise ValueError("phase freshness transition differs")
        return self


class M2CExactPlanPrimitivePlanV1(FrozenModel):
    """Canonical ADR envelope around one legacy ``ExactExecutionPlanV2``."""

    schema_version: Literal["M2CExactPlanPrimitivePlanV1"] = "M2CExactPlanPrimitivePlanV1"
    bundle_name: Literal["M2CExactPlanPrimitiveBundleV1"] = "M2CExactPlanPrimitiveBundleV1"
    exact_execution_plan: ExactExecutionPlanV2
    exact_execution_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    inputs: ExactPlanA1InputsV1
    source_bindings: tuple[ExactPlanSourceBindingV1, ...] = Field(min_length=12)
    phases: tuple[ExactPlanPhaseContractV1, ...] = Field(min_length=1)
    grasp_geometry: ExactGraspGeometryV1 | None = None
    phase_schema_sha256: str = Field(pattern=SHA256_PATTERN)
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    constructed_before_physical_execution: Literal[True] = True
    executor_parameter_adaptation_allowed: Literal[False] = False
    hidden_replan_allowed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    def semantic_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"bound_plan_sha256"})

    @model_validator(mode="after")
    def all_bindings_are_exact(self) -> "M2CExactPlanPrimitivePlanV1":
        plan = self.exact_execution_plan
        inputs = self.inputs
        if self.exact_execution_plan_sha256 != canonical_sha256(plan):
            raise ValueError("legacy exact-plan digest differs")
        if self.bound_plan_sha256 != canonical_sha256(self.semantic_payload()):
            raise ValueError("ADR envelope canonical digest differs")
        if (
            inputs.run_id != plan.run_id
            or inputs.session_id != plan.session_id
            or inputs.decision_index != plan.decision_index
            or inputs.observation_id != plan.observation_id
            or inputs.capture_receipt_sha256 != plan.capture_receipt_sha256
            or inputs.canonical_skill != plan.canonical_skill
            or inputs.runtime_action != plan.runtime_action
            or inputs.target_track_id != plan.target_track_id
            or inputs.resolved_execution_parameters_sha256 != plan.execution_parameters_sha256
        ):
            raise ValueError("A.1 inputs differ from the exact wire plan")
        roles = tuple(item.role for item in self.source_bindings)
        if len(roles) != len(set(roles)) or frozenset(roles) != _REQUIRED_SOURCE_ROLES:
            raise ValueError("source bindings are not the exact A.1 role set")
        if len(self.phases) != len(plan.phases):
            raise ValueError("phase-contract count differs from exact plan")
        if tuple(item.phase for item in self.phases) != plan.phases:
            raise ValueError("phase contracts differ from the exact plan sequence")
        schema_projection = tuple(
            {
                "phase_index": item.phase.phase_index,
                "phase_name": item.phase.phase_name,
                "command": item.phase.command,
                "phase_sha256": item.phase_sha256,
                "command_rate_hz": item.command_rate_hz,
                "command_dimensions": item.command_dimensions,
                "interpolation_rule": item.interpolation_rule,
                "timeout_ns": item.timeout_ns,
                "permitted_retry_count": item.permitted_retry_count,
                "attachment_or_removal_selector": item.attachment_or_removal_selector,
                "freshness_transition": item.freshness_transition,
            }
            for item in self.phases
        )
        if self.phase_schema_sha256 != canonical_sha256(schema_projection):
            raise ValueError("phase schema digest differs")
        commands = tuple(phase.command for phase in plan.phases)
        if plan.canonical_skill in {"GRASP", "REGRASP"}:
            geometry = self.grasp_geometry
            if geometry is None:
                raise ValueError("GRASP/REGRASP lacks frozen yaw/centerline/finger geometry")
            indices = (
                geometry.approach_phase_index,
                *geometry.contact_phase_indices,
                geometry.close_phase_index,
                geometry.attach_phase_index,
                geometry.lift_phase_index,
                geometry.retreat_phase_index,
            )
            if any(index >= len(commands) for index in indices):
                raise ValueError("grasp geometry references an absent phase")
            if commands[geometry.close_phase_index] != "GRIPPER_POSITION":
                raise ValueError("grasp close phase is not the bound gripper command")
            if commands[geometry.attach_phase_index] != "ATTACH_CONTACT_ENTITY":
                raise ValueError("grasp attach phase is not the bound attachment command")
            for index in (
                geometry.approach_phase_index,
                *geometry.contact_phase_indices,
                geometry.lift_phase_index,
                geometry.retreat_phase_index,
            ):
                if commands[index] != "CARTESIAN_POSE":
                    raise ValueError("grasp waypoint phase is not Cartesian")
        elif self.grasp_geometry is not None:
            raise ValueError("non-grasp skill contains grasp-only runtime parameters")
        if plan.canonical_skill in {"MOVE", "LIFT"} and "CARTESIAN_POSE" not in commands:
            raise ValueError("MOVE/LIFT lacks a complete bound Cartesian trajectory")
        if plan.canonical_skill in {"PLACE", "RELEASE"} and not {
            "CARTESIAN_POSE",
            "GRIPPER_POSITION",
        }.issubset(commands):
            raise ValueError("PLACE/RELEASE lacks its bound open-and-retreat sequence")
        if plan.canonical_skill == "REOBSERVE" and commands != ("PUBLIC_RGBD_CAPTURE",):
            raise ValueError("REOBSERVE is not exactly one fresh public capture")
        if plan.canonical_skill == "REASSOCIATE_TARGET" and commands != (
            "PUBLIC_TRACK_REASSOCIATION",
        ):
            raise ValueError("REASSOCIATE_TARGET is not exactly one public association")
        return self


class ExactPlanPhasePreflightV1(FrozenModel):
    schema_version: Literal["ExactPlanPhasePreflightV1"] = "ExactPlanPhasePreflightV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_sha256: str = Field(pattern=SHA256_PATTERN)
    ik: Literal["PASS"] = "PASS"
    joint_limits: Literal["PASS"] = "PASS"
    swept_collision: Literal["PASS"] = "PASS"
    controller: Literal["PASS"] = "PASS"
    safety: Literal["PASS"] = "PASS"
    ik_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    limits_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    swept_collision_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    controller_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    safety_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    checked_before_any_command: Literal[True] = True
    immutable: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class ExactPlanPreflightReceiptV1(FrozenModel):
    schema_version: Literal["ExactPlanPreflightReceiptV1"] = "ExactPlanPreflightReceiptV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_results: tuple[ExactPlanPhasePreflightV1, ...] = Field(min_length=1)
    all_phases_passed_before_any_command: Literal[True] = True
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def receipt_is_canonical(self) -> "ExactPlanPreflightReceiptV1":
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(payload):
            raise ValueError("preflight receipt digest differs")
        return self


class ExactPlanPhaseExecutionV1(FrozenModel):
    schema_version: Literal["ExactPlanPhaseExecutionV1"] = "ExactPlanPhaseExecutionV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    started_at_ns: int = Field(gt=0)
    completed_at_ns: int = Field(gt=0)
    status: Literal["PASS", "FAILED"]
    operation_executed: bool
    controller_outcome: str = Field(min_length=1)
    observed_collision: Literal[False] = False
    observed_safety_violation: Literal[False] = False
    replanned: Literal[False] = False
    inserted_or_altered_command: Literal[False] = False
    retry_selected_at_runtime: Literal[False] = False
    real_isaac: bool
    contract_test_only: bool
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def timing_and_mode_are_valid(self) -> "ExactPlanPhaseExecutionV1":
        if self.completed_at_ns <= self.started_at_ns:
            raise ValueError("phase completion is not after phase start")
        if self.real_isaac == self.contract_test_only:
            raise ValueError("phase receipt must be exactly real-Isaac or contract-test")
        if self.contract_test_only and self.operation_executed:
            raise ValueError("contract test may not claim an executed physical operation")
        return self


class ExactPlanBundleExecutionReceiptV1(FrozenModel):
    schema_version: Literal["ExactPlanBundleExecutionReceiptV1"] = (
        "ExactPlanBundleExecutionReceiptV1"
    )
    bundle_name: Literal["M2CExactPlanPrimitiveBundleV1"] = "M2CExactPlanPrimitiveBundleV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    preflight_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_receipts: tuple[ExactPlanPhaseExecutionV1, ...]
    status: Literal["PASS", "PARTIAL_FAILURE"]
    terminated_without_replan: Literal[True] = True
    execution_attribution: Literal["MODEL_SELECTED_REGISTERED_SKILL"] = (
        "MODEL_SELECTED_REGISTERED_SKILL"
    )
    real_isaac: bool
    formal_evidence: bool
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def evidence_mode_is_honest(self) -> "ExactPlanBundleExecutionReceiptV1":
        if self.formal_evidence != self.real_isaac:
            raise ValueError("contract-test execution may not be formal physical evidence")
        if self.status == "PASS" and any(item.status != "PASS" for item in self.phase_receipts):
            raise ValueError("PASS bundle receipt contains a failed phase")
        if self.status == "PARTIAL_FAILURE":
            if not self.phase_receipts or self.phase_receipts[-1].status != "FAILED":
                raise ValueError("partial failure does not terminate at a failed phase")
        return self


class ExactPlanPrimitiveDeploymentBindingV1(FrozenModel):
    """Future addendum binding; no production instance is shipped here."""

    schema_version: Literal["ExactPlanPrimitiveDeploymentBindingV1"] = (
        "ExactPlanPrimitiveDeploymentBindingV1"
    )
    adr_path: Literal["docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"] = (
        ADR_0022_PATH
    )
    adr_sha256: str = Field(pattern=SHA256_PATTERN)
    binding_addendum_sha256: str = Field(pattern=SHA256_PATTERN)
    unlock_config_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_bindings: tuple[ExactPlanSourceBindingV1, ...] = Field(min_length=12)
    phase_schema_by_skill: tuple[tuple[str, str], ...] = Field(min_length=8)
    execution_mode: Literal["REAL_ISAAC", "CONTRACT_TEST"]
    reviewed_addendum_accepted: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def source_and_skill_sets_are_exact(self) -> "ExactPlanPrimitiveDeploymentBindingV1":
        roles = tuple(item.role for item in self.source_bindings)
        if len(roles) != len(set(roles)) or frozenset(roles) != _REQUIRED_SOURCE_ROLES:
            raise ValueError("deployment source role set is incomplete or duplicated")
        skills = tuple(skill for skill, _ in self.phase_schema_by_skill)
        expected = {
            "GRASP",
            "LIFT",
            "MOVE",
            "PLACE",
            "RELEASE",
            "REOBSERVE",
            "REASSOCIATE_TARGET",
            "REGRASP",
        }
        if len(skills) != len(set(skills)) or set(skills) != expected:
            raise ValueError("deployment phase-schema skill set is not exact")
        if any(
            not re.fullmatch(SHA256_PATTERN, digest) for _, digest in self.phase_schema_by_skill
        ):
            raise ValueError("deployment phase schema contains a malformed digest")
        return self


class ExactPlanPreflightVerifierV1(Protocol):
    implementation_sha256: str

    def verify_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> ExactPlanPhasePreflightV1: ...


class ExactPlanPhaseExecutorV1(Protocol):
    implementation_sha256: str
    real_isaac: bool

    def verify_bound_plan_before_execution(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        preflight: ExactPlanPreflightReceiptV1,
    ) -> str: ...

    def execute_precomputed_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        preflight: ExactPlanPhasePreflightV1,
    ) -> ExactPlanPhaseExecutionV1: ...


class M2CExactPlanPrimitiveBundleV1:
    """Fail-closed preflight/execution coordinator with no planning callback."""

    def __init__(
        self,
        *,
        project_root: Path,
        binding: ExactPlanPrimitiveDeploymentBindingV1 | None,
        preflight_verifier: ExactPlanPreflightVerifierV1 | None,
        executor: ExactPlanPhaseExecutorV1 | None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.binding = binding
        self.preflight_verifier = preflight_verifier
        self.executor = executor

    def _require_binding(self, plan: M2CExactPlanPrimitivePlanV1) -> None:
        binding = self.binding
        if binding is None or self.preflight_verifier is None or self.executor is None:
            raise ExactPlanUnavailable(
                "ADR-0022 binding addendum/preflight/executor is absent; no physical command"
            )
        if _read_regular_file_sha256(self.project_root / binding.adr_path) != binding.adr_sha256:
            raise ExactPlanUnavailable("accepted ADR-0022 digest differs from deployment binding")
        addendum_path = self.project_root / "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"
        unlock_path = self.project_root / "configs/m2c_s4_unlock_bindings.json"
        if (
            _read_regular_file_sha256(addendum_path) != binding.binding_addendum_sha256
            or _read_regular_file_sha256(unlock_path) != binding.unlock_config_sha256
        ):
            raise ExactPlanUnavailable("Phase-2 addendum/config digest differs")
        if plan.inputs.immutable_commit != binding.immutable_commit:
            raise ExactPlanUnavailable("plan commit differs from deployment binding")
        if plan.inputs.container_image_digest != binding.container_image_digest:
            raise ExactPlanUnavailable("plan container differs from deployment binding")
        if plan.source_bindings != binding.source_bindings:
            raise ExactPlanUnavailable("plan source bindings differ from deployment binding")
        phase_schemas = dict(binding.phase_schema_by_skill)
        if phase_schemas.get(plan.exact_execution_plan.canonical_skill) != plan.phase_schema_sha256:
            raise ExactPlanUnavailable("plan phase schema is not frozen for this skill")
        role_hashes = {item.role: item.sha256 for item in binding.source_bindings}
        if self.preflight_verifier.implementation_sha256 != role_hashes["PREFLIGHT_IMPLEMENTATION"]:
            raise ExactPlanUnavailable("preflight verifier implementation digest differs")
        if self.executor.implementation_sha256 != role_hashes["EXECUTOR_IMPLEMENTATION"]:
            raise ExactPlanUnavailable("executor implementation digest differs")
        if self.executor.real_isaac != (binding.execution_mode == "REAL_ISAAC"):
            raise ExactPlanUnavailable("executor mode differs from deployment binding")
        for source in binding.source_bindings:
            path = Path(source.path)
            resolved = path if path.is_absolute() else self.project_root / path
            if _read_regular_file_sha256(resolved) != source.sha256:
                raise ExactPlanUnavailable(f"deployment source digest differs: {source.role}")

    def preflight(self, plan: M2CExactPlanPrimitivePlanV1) -> ExactPlanPreflightReceiptV1:
        self._require_binding(plan)
        assert self.preflight_verifier is not None
        results: list[ExactPlanPhasePreflightV1] = []
        for phase in plan.phases:
            result = self.preflight_verifier.verify_phase(plan, phase)
            if (
                result.bound_plan_sha256 != plan.bound_plan_sha256
                or result.phase_index != phase.phase.phase_index
                or result.phase_sha256 != phase.phase_sha256
                or result.preplan_state_sha256 != plan.inputs.preplan_state_sha256
            ):
                raise ExactPlanUnavailable("phase preflight receipt crossed plan/phase/state")
            role_hashes = {item.role: item.sha256 for item in plan.source_bindings}
            expected_gate_hashes = {
                "ik_algorithm_sha256": role_hashes["IK_ALGORITHM"],
                "limits_configuration_sha256": role_hashes["JOINT_LIMIT_CONFIGURATION"],
                "swept_collision_algorithm_sha256": role_hashes["SWEPT_COLLISION_ALGORITHM"],
                "controller_configuration_sha256": role_hashes["CONTROLLER_CONFIGURATION"],
                "safety_configuration_sha256": role_hashes["SAFETY_CONFIGURATION"],
            }
            if any(
                getattr(result, name) != expected for name, expected in expected_gate_hashes.items()
            ):
                raise ExactPlanUnavailable("phase preflight gate implementation digest differs")
            results.append(result)
        payload: dict[str, object] = {
            "schema_version": "ExactPlanPreflightReceiptV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_results": [item.model_dump(mode="json") for item in results],
            "all_phases_passed_before_any_command": True,
        }
        return ExactPlanPreflightReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )

    def execute(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        preflight: ExactPlanPreflightReceiptV1,
    ) -> ExactPlanBundleExecutionReceiptV1:
        """Execute only the already preflighted sequence; never plan or retry."""

        self._require_binding(plan)
        assert self.binding is not None and self.executor is not None
        if preflight.bound_plan_sha256 != plan.bound_plan_sha256:
            raise ExactPlanUnavailable("preflight receipt differs from bound plan")
        if len(preflight.phase_results) != len(plan.phases):
            raise ExactPlanUnavailable("preflight did not cover every phase")
        for expected, result in zip(plan.phases, preflight.phase_results):
            if result.phase_sha256 != expected.phase_sha256:
                raise ExactPlanUnavailable("preflight phase order/digest differs")
        independently_verified = self.executor.verify_bound_plan_before_execution(
            plan,
            preflight,
        )
        if independently_verified != plan.bound_plan_sha256:
            raise ExactPlanUnavailable("executor independently rejected bound-plan digest")
        receipts: list[ExactPlanPhaseExecutionV1] = []
        for phase, gate_result in zip(plan.phases, preflight.phase_results):
            result = self.executor.execute_precomputed_phase(plan, phase, gate_result)
            if (
                result.bound_plan_sha256 != plan.bound_plan_sha256
                or result.phase_index != phase.phase.phase_index
                or result.phase_sha256 != phase.phase_sha256
            ):
                raise ExactPlanUnavailable("executor receipt differs from precomputed phase")
            if result.real_isaac != (self.binding.execution_mode == "REAL_ISAAC"):
                raise ExactPlanUnavailable("phase receipt execution mode differs")
            receipts.append(result)
            if result.status == "FAILED":
                return ExactPlanBundleExecutionReceiptV1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    preflight_receipt_sha256=preflight.receipt_sha256,
                    phase_receipts=tuple(receipts),
                    status="PARTIAL_FAILURE",
                    real_isaac=result.real_isaac,
                    formal_evidence=result.real_isaac,
                )
        return ExactPlanBundleExecutionReceiptV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            preflight_receipt_sha256=preflight.receipt_sha256,
            phase_receipts=tuple(receipts),
            status="PASS",
            real_isaac=self.binding.execution_mode == "REAL_ISAAC",
            formal_evidence=self.binding.execution_mode == "REAL_ISAAC",
        )
