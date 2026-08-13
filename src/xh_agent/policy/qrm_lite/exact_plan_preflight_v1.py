"""Non-actuating ADR-0022 A.3 preflight for an immutable exact plan.

The coordinator in this module performs no Isaac update, controller command,
articulation-target write, attachment mutation, capture, or physical action.
It consumes only hash-bound results from a separately reviewed read-only
Isaac/Lula callback implementation.  Every phase is checked before a single
``ExactPlanPreflightReceiptV1`` is released.  A missing callback result,
incomplete path sample, failed limit, collision outside the phase allowlist,
stale state, controller mismatch, or safety-state mismatch rejects the whole
plan.

Isaac Sim 6's convenient ``Franka.set_end_effector_pose`` is intentionally
not used here: that method writes articulation targets.  A production binding
must instead supply a source-frozen callback that invokes only query APIs
(for example, a reviewed Lula kinematics solver and a read-only swept-volume
checker) and whose startup introspection receipt proves zero target writes,
zero physics steps, and zero scene mutation.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import stat
from typing import Any, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


MOTION_COMMANDS = frozenset({"CARTESIAN_POSE", "GRIPPER_POSITION"})
PHYSICAL_MUTATION_COMMANDS = frozenset(
    {"CARTESIAN_POSE", "GRIPPER_POSITION", "ATTACH_CONTACT_ENTITY", "REMOVE_ATTACHMENT"}
)
EXPECTED_COMMAND_DIMENSIONS: Mapping[str, int] = {
    "CARTESIAN_POSE": 7,
    "GRIPPER_POSITION": 1,
    "ATTACH_CONTACT_ENTITY": 0,
    "REMOVE_ATTACHMENT": 0,
    "PUBLIC_RGBD_CAPTURE": 0,
    "PUBLIC_TRACK_REASSOCIATION": 0,
}


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactPlanPreflightRejected(RuntimeError):
    """The complete exact plan is invalid; no phase is authorized."""


def _canonical_model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _read_regular_file_sha256(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ExactPlanPreflightRejected(
                f"preflight implementation is not a single-link regular file: {path}"
            )
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
            raise ExactPlanPreflightRejected("preflight implementation changed while hashing")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


class IKPreflightConfigurationV1(FrozenModel):
    schema_version: Literal["IKPreflightConfigurationV1"] = "IKPreflightConfigurationV1"
    algorithm_id: str = Field(pattern=r"^[A-Z][A-Z0-9_.-]+$")
    algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    robot_description_sha256: str = Field(pattern=SHA256_PATTERN)
    base_frame: str = Field(min_length=1)
    end_effector_frame: str = Field(min_length=1)
    maximum_position_residual_m: float = Field(gt=0.0)
    maximum_orientation_residual_rad: float = Field(gt=0.0)
    maximum_iterations_per_sample: int = Field(gt=0)
    timeout_ns_per_phase: int = Field(gt=0)
    deterministic_seed: Literal[0] = 0
    query_only_required: Literal[True] = True
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def finite_and_canonical(self) -> "IKPreflightConfigurationV1":
        if not all(
            math.isfinite(value)
            for value in (
                self.maximum_position_residual_m,
                self.maximum_orientation_residual_rad,
            )
        ):
            raise ValueError("IK configuration contains NaN/Inf")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("IK configuration digest differs")
        return self


class JointLimitConfigurationV1(FrozenModel):
    schema_version: Literal["JointLimitConfigurationV1"] = "JointLimitConfigurationV1"
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_names: tuple[str, ...] = Field(min_length=1)
    lower_position: tuple[float, ...]
    upper_position: tuple[float, ...]
    maximum_velocity_per_s: tuple[float, ...]
    maximum_abs_effort: tuple[float, ...]
    sample_rate_hz: Literal[60.0] = 60.0
    position_tolerance: Literal[0.0] = 0.0
    velocity_tolerance: Literal[0.0] = 0.0
    effort_tolerance: Literal[0.0] = 0.0
    effort_estimator_sha256: str = Field(pattern=SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def vectors_are_exact(self) -> "JointLimitConfigurationV1":
        width = len(self.joint_names)
        vectors = (
            self.lower_position,
            self.upper_position,
            self.maximum_velocity_per_s,
            self.maximum_abs_effort,
        )
        if len(set(self.joint_names)) != width or any(len(item) != width for item in vectors):
            raise ValueError("joint-limit vectors differ from the unique joint-name width")
        if not all(math.isfinite(float(value)) for item in vectors for value in item):
            raise ValueError("joint-limit configuration contains NaN/Inf")
        if any(low >= high for low, high in zip(self.lower_position, self.upper_position)):
            raise ValueError("joint position interval is empty")
        if any(value <= 0.0 for value in (*self.maximum_velocity_per_s, *self.maximum_abs_effort)):
            raise ValueError("joint velocity/effort limit is non-positive")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("joint-limit configuration digest differs")
        return self


class GripperLimitConfigurationV1(FrozenModel):
    """Explicit gripper trajectory domain; no arm-joint limit is reused."""

    schema_version: Literal["GripperLimitConfigurationV1"] = "GripperLimitConfigurationV1"
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    minimum_position_m: float = Field(ge=0.0)
    maximum_position_m: float = Field(gt=0.0)
    maximum_velocity_m_per_s: float = Field(gt=0.0)
    target_tolerance_m: float = Field(ge=0.0)
    sample_rate_hz: Literal[60.0] = 60.0
    timeout_ns_per_phase: int = Field(gt=0)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def finite_and_canonical(self) -> "GripperLimitConfigurationV1":
        values = (
            self.minimum_position_m,
            self.maximum_position_m,
            self.maximum_velocity_m_per_s,
            self.target_tolerance_m,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("gripper-limit configuration contains NaN/Inf")
        if self.minimum_position_m >= self.maximum_position_m:
            raise ValueError("gripper position interval is empty")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("gripper-limit configuration digest differs")
        return self


class SweptCollisionConfigurationV1(FrozenModel):
    schema_version: Literal["SweptCollisionConfigurationV1"] = "SweptCollisionConfigurationV1"
    algorithm_id: str = Field(pattern=r"^[A-Z][A-Z0-9_.-]+$")
    algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    collision_geometry_sha256: str = Field(pattern=SHA256_PATTERN)
    robot_root_path: str = Field(pattern=r"^/[^\s]+$")
    continuous_between_samples: Literal[True] = True
    subsamples_per_segment: int = Field(gt=0)
    timeout_ns_per_phase: int = Field(gt=0)
    fail_on_unknown_pair: Literal[True] = True
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "SweptCollisionConfigurationV1":
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("swept-collision configuration digest differs")
        return self


class ControllerPreflightConfigurationV1(FrozenModel):
    schema_version: Literal["ControllerPreflightConfigurationV1"] = (
        "ControllerPreflightConfigurationV1"
    )
    controller_id: str = Field(min_length=1)
    controller_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    required_rate_hz: Literal[60.0] = 60.0
    cartesian_command_dimensions: Literal[7] = 7
    gripper_command_dimensions: Literal[1] = 1
    non_motion_command_dimensions: Literal[0] = 0
    readiness_timeout_ns: int = Field(gt=0)
    target_writes_before_authorization: Literal[0] = 0
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "ControllerPreflightConfigurationV1":
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("controller configuration digest differs")
        return self


class SafetyPreflightConfigurationV1(FrozenModel):
    schema_version: Literal["SafetyPreflightConfigurationV1"] = "SafetyPreflightConfigurationV1"
    safety_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    workspace_min_world_m: tuple[float, float, float]
    workspace_max_world_m: tuple[float, float, float]
    maximum_state_age_ns: int = Field(gt=0)
    contact_monitor_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_monitor_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    require_collision_world_ready: Literal[True] = True
    require_contact_monitor_ready: Literal[True] = True
    require_attachment_monitor_ready: Literal[True] = True
    fail_on_emergency_stop: Literal[True] = True
    teacher_allowed: Literal[False] = False
    privileged_truth_policy_input_allowed: Literal[False] = False
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def workspace_is_finite_and_canonical(self) -> "SafetyPreflightConfigurationV1":
        values = (*self.workspace_min_world_m, *self.workspace_max_world_m)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("workspace configuration contains NaN/Inf")
        if any(
            low >= high for low, high in zip(self.workspace_min_world_m, self.workspace_max_world_m)
        ):
            raise ValueError("workspace interval is empty")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("safety configuration digest differs")
        return self


class AttachmentPreflightConfigurationV1(FrozenModel):
    """Complete query-only contact/attachment feasibility configuration."""

    schema_version: Literal["AttachmentPreflightConfigurationV1"] = (
        "AttachmentPreflightConfigurationV1"
    )
    algorithm_id: str = Field(pattern=r"^[A-Z][A-Z0-9_.-]+$")
    algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    contact_monitor_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_monitor_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    timeout_ns_per_phase: int = Field(gt=0)
    require_unique_bilateral_contact_pair: Literal[True] = True
    require_terminal_bilateral_contact_selector: Literal[True] = True
    query_only_required: Literal[True] = True
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "AttachmentPreflightConfigurationV1":
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("attachment preflight configuration digest differs")
        return self


class ExactPlanPreflightConfigurationV1(FrozenModel):
    schema_version: Literal["ExactPlanPreflightConfigurationV1"] = (
        "ExactPlanPreflightConfigurationV1"
    )
    ik: IKPreflightConfigurationV1
    joint_limits: JointLimitConfigurationV1
    gripper_limits: GripperLimitConfigurationV1
    swept_collision: SweptCollisionConfigurationV1
    controller: ControllerPreflightConfigurationV1
    safety: SafetyPreflightConfigurationV1
    attachment: AttachmentPreflightConfigurationV1
    callback_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    total_timeout_ns: int = Field(gt=0)
    incomplete_or_timeout_is_invalid: Literal[True] = True
    all_phases_before_first_command: Literal[True] = True
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "ExactPlanPreflightConfigurationV1":
        if (
            self.gripper_limits.sample_rate_hz != self.controller.required_rate_hz
            or self.joint_limits.sample_rate_hz != self.controller.required_rate_hz
            or self.attachment.contact_monitor_configuration_sha256
            != self.safety.contact_monitor_configuration_sha256
            or self.attachment.attachment_monitor_configuration_sha256
            != self.safety.attachment_monitor_configuration_sha256
        ):
            raise ValueError("complete preflight configurations disagree")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("complete preflight configuration digest differs")
        return self


class ControllerCommandShapeV1(FrozenModel):
    command: Literal[
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "REMOVE_ATTACHMENT",
        "PUBLIC_RGBD_CAPTURE",
        "PUBLIC_TRACK_REASSOCIATION",
    ]
    dimensions: int = Field(ge=0)


class PreflightRuntimeSnapshotV1(FrozenModel):
    schema_version: Literal["PreflightRuntimeSnapshotV1"] = "PreflightRuntimeSnapshotV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_sha256: str = Field(pattern=SHA256_PATTERN)
    observed_at_ns: int = Field(gt=0)
    checked_at_ns: int = Field(gt=0)
    controller_id: str = Field(min_length=1)
    controller_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    controller_ready: bool
    controller_readiness_query_duration_ns: int = Field(ge=0)
    controller_rate_hz: float = Field(gt=0.0)
    command_shapes: tuple[ControllerCommandShapeV1, ...] = Field(min_length=6)
    collision_world_ready: bool
    contact_monitor_ready: bool
    attachment_monitor_ready: bool
    terminal_bilateral_contact_broker_ready: bool
    active_attachment_present: bool
    active_attachment_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    emergency_stop_active: bool
    state_stale: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def shape_and_digest(self) -> "PreflightRuntimeSnapshotV1":
        commands = tuple(item.command for item in self.command_shapes)
        if len(commands) != len(set(commands)) or set(commands) != set(EXPECTED_COMMAND_DIMENSIONS):
            raise ValueError("runtime snapshot command-shape set differs")
        if not math.isfinite(self.controller_rate_hz):
            raise ValueError("runtime controller rate is NaN/Inf")
        if self.checked_at_ns < self.observed_at_ns:
            raise ValueError("runtime snapshot was checked before observation")
        if self.active_attachment_present != (self.active_attachment_sha256 is not None):
            raise ValueError("runtime attachment presence/identity differs")
        if self.snapshot_sha256 != _canonical_model_sha256(self, "snapshot_sha256"):
            raise ValueError("runtime snapshot digest differs")
        return self


class NonActuatingJointSampleV1(FrozenModel):
    schema_version: Literal["NonActuatingJointSampleV1"] = "NonActuatingJointSampleV1"
    sample_index: int = Field(ge=0)
    joint_positions: tuple[float, ...]
    estimated_abs_efforts: tuple[float, ...]
    end_effector_world_m: tuple[float, float, float]
    end_effector_world_wxyz: tuple[float, float, float, float]
    gripper_position_m: float = Field(ge=0.0)
    ik_applicable: bool
    ik_converged: bool
    ik_position_residual_m: float = Field(ge=0.0)
    ik_orientation_residual_rad: float = Field(ge=0.0)
    iterations: int = Field(ge=0)
    state_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def finite(self) -> "NonActuatingJointSampleV1":
        values = (
            *self.joint_positions,
            *self.estimated_abs_efforts,
            *self.end_effector_world_m,
            *self.end_effector_world_wxyz,
            self.ik_position_residual_m,
            self.ik_orientation_residual_rad,
            self.gripper_position_m,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("joint-path sample contains NaN/Inf")
        norm = math.sqrt(sum(value * value for value in self.end_effector_world_wxyz))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("joint-path sample orientation is not normalized wxyz")
        if self.state_sha256 != canonical_non_actuating_state_sha256(self):
            raise ValueError("joint-path sample state digest differs")
        return self


def non_actuating_physical_state_payload(
    sample: NonActuatingJointSampleV1 | Mapping[str, Any],
) -> dict[str, Any]:
    """Canonical physical state shared by adjacent preflight phases.

    Gate metadata (sample index, IK iterations/residuals, and estimated effort)
    remains covered by the enclosing path digest, but is intentionally not a
    physical-state identity: applicability and effort estimates can differ
    when the next command kind changes at the same robot state.
    """

    if isinstance(sample, BaseModel):
        value = sample.model_dump(mode="json")
    else:
        value = dict(sample)
    return {
        "schema_version": "NonActuatingPhysicalStateV1",
        "joint_positions": value["joint_positions"],
        "end_effector_world_m": value["end_effector_world_m"],
        "end_effector_world_wxyz": value["end_effector_world_wxyz"],
        "gripper_position_m": value.get("gripper_position_m"),
    }


def canonical_non_actuating_state_sha256(
    sample: NonActuatingJointSampleV1 | Mapping[str, Any],
) -> str:
    """Return the canonical digest of one query-only physical state."""

    return canonical_sha256(non_actuating_physical_state_payload(sample))


def _same_non_actuating_physical_state(
    left: NonActuatingJointSampleV1,
    right: NonActuatingJointSampleV1,
) -> bool:
    return left.state_sha256 == right.state_sha256 and non_actuating_physical_state_payload(
        left
    ) == non_actuating_physical_state_payload(right)


class NonActuatingPhasePathV1(FrozenModel):
    schema_version: Literal["NonActuatingPhasePathV1"] = "NonActuatingPhasePathV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    start_state_sha256: str = Field(pattern=SHA256_PATTERN)
    terminal_state_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_names: tuple[str, ...] = Field(min_length=1)
    sample_rate_hz: Literal[60.0] = 60.0
    samples: tuple[NonActuatingJointSampleV1, ...] = Field(min_length=1)
    ik_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    ik_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_limit_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    gripper_limit_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    effort_estimator_sha256: str = Field(pattern=SHA256_PATTERN)
    query_duration_ns: int = Field(ge=0)
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    path_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest(self) -> "NonActuatingPhasePathV1":
        if self.path_sha256 != _canonical_model_sha256(self, "path_sha256"):
            raise ValueError("non-actuating path digest differs")
        return self


class SweptCollisionPairV1(FrozenModel):
    path0: str = Field(pattern=r"^/[^\s]+$")
    path1: str = Field(pattern=r"^/[^\s]+$")


class SweptCollisionSegmentV1(FrozenModel):
    segment_index: int = Field(ge=0)
    subsamples_checked: int = Field(gt=0)
    complete: Literal[True] = True
    collision_pairs: tuple[SweptCollisionPairV1, ...] = ()


class NonActuatingSweptCollisionV1(FrozenModel):
    schema_version: Literal["NonActuatingSweptCollisionV1"] = "NonActuatingSweptCollisionV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    segments: tuple[SweptCollisionSegmentV1, ...]
    query_duration_ns: int = Field(ge=0)
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest(self) -> "NonActuatingSweptCollisionV1":
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("swept-collision query digest differs")
        return self


class PlannedBilateralContactPairV1(FrozenModel):
    left_robot_path: str = Field(pattern=r"^/[^\s]+$")
    right_robot_path: str = Field(pattern=r"^/[^\s]+$")
    external_path: str = Field(pattern=r"^/[^\s]+$")

    @model_validator(mode="after")
    def robot_sides_are_distinct(self) -> "PlannedBilateralContactPairV1":
        if self.left_robot_path == self.right_robot_path:
            raise ValueError("bilateral contact pair repeats one robot path")
        return self


class NonActuatingAttachmentTransitionV1(FrozenModel):
    """Read-only feasibility query; it never creates or removes an attachment."""

    schema_version: Literal["NonActuatingAttachmentTransitionV1"] = (
        "NonActuatingAttachmentTransitionV1"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    command: Literal[
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "REMOVE_ATTACHMENT",
        "PUBLIC_RGBD_CAPTURE",
        "PUBLIC_TRACK_REASSOCIATION",
    ]
    transition: Literal["NONE", "ATTACH", "REMOVE"]
    attachment_or_removal_selector: Literal[
        "NONE",
        "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST",
        "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT",
    ]
    allowed_robot_contact_paths: tuple[str, ...]
    allowed_external_contact_paths: tuple[str, ...]
    bilateral_contact_pairs: tuple[PlannedBilateralContactPairV1, ...] = ()
    attachment_present_before: bool
    attachment_sha256_before: str | None = Field(default=None, pattern=SHA256_PATTERN)
    attachment_present_after: bool
    attachment_sha256_after: str | None = Field(default=None, pattern=SHA256_PATTERN)
    complete: Literal[True] = True
    algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    query_duration_ns: int = Field(ge=0)
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def state_and_digest(self) -> "NonActuatingAttachmentTransitionV1":
        if self.attachment_present_before != (self.attachment_sha256_before is not None):
            raise ValueError("attachment before-state/identity differs")
        if self.attachment_present_after != (self.attachment_sha256_after is not None):
            raise ValueError("attachment after-state/identity differs")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("attachment-transition query digest differs")
        return self


class IsaacLulaStartupIntrospectionReceiptV1(FrozenModel):
    """Startup-only proof used before binding a production query callback."""

    schema_version: Literal["IsaacLulaStartupIntrospectionReceiptV1"] = (
        "IsaacLulaStartupIntrospectionReceiptV1"
    )
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    isaac_runtime_version: str = Field(min_length=1)
    franka_class_path: str = Field(min_length=1)
    set_end_effector_pose_source_sha256: str = Field(pattern=SHA256_PATTERN)
    set_end_effector_pose_writes_dof_targets: Literal[True] = True
    query_callback_path: str | None = None
    query_callback_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    query_callback_proven_non_actuating: bool
    scene_created: Literal[False] = False
    physics_steps: Literal[0] = 0
    articulation_target_writes: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    smoke_or_evaluation_executed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def callback_and_digest(self) -> "IsaacLulaStartupIntrospectionReceiptV1":
        bound = self.query_callback_path is not None and self.query_callback_sha256 is not None
        if self.query_callback_proven_non_actuating != bound:
            raise ValueError("startup receipt callback proof/binding differs")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("startup introspection receipt digest differs")
        return self


class ExactPlanA3ConfigurationReceiptV1(FrozenModel):
    """Bind complete A.3 configuration without overloading a source role.

    The current 12-role exact-plan schema binds implementation/algorithm
    sources and selected configurations, but has no distinct role for the
    complete IK tolerance bundle or collision geometry.  This receipt makes
    those hashes explicit.  Until a reviewed addendum binds this receipt's
    digest, it is audit-only and cannot authorize execution.
    """

    schema_version: Literal["ExactPlanA3ConfigurationReceiptV1"] = (
        "ExactPlanA3ConfigurationReceiptV1"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_source_bindings_sha256: str = Field(pattern=SHA256_PATTERN)
    complete_preflight_configuration: ExactPlanPreflightConfigurationV1
    complete_preflight_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    callback_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    ik_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    ik_complete_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    ik_robot_description_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_limit_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    gripper_limit_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    swept_collision_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    swept_collision_complete_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    collision_geometry_sha256: str = Field(pattern=SHA256_PATTERN)
    controller_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    safety_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_complete_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    current_plan_role_schema_covers_complete_a3_configuration: Literal[False] = False
    binding_addendum_required: Literal[True] = True
    binding_addendum_sha256: None = None
    formal_execution_eligible: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "ExactPlanA3ConfigurationReceiptV1":
        config = self.complete_preflight_configuration
        if (
            self.complete_preflight_configuration_sha256 != config.configuration_sha256
            or self.callback_implementation_sha256 != config.callback_implementation_sha256
            or self.ik_algorithm_sha256 != config.ik.algorithm_sha256
            or self.ik_complete_configuration_sha256 != config.ik.configuration_sha256
            or self.ik_robot_description_sha256 != config.ik.robot_description_sha256
            or self.joint_limit_configuration_sha256 != config.joint_limits.configuration_sha256
            or self.gripper_limit_configuration_sha256 != config.gripper_limits.configuration_sha256
            or self.swept_collision_algorithm_sha256 != config.swept_collision.algorithm_sha256
            or self.swept_collision_complete_configuration_sha256
            != config.swept_collision.configuration_sha256
            or self.collision_geometry_sha256 != config.swept_collision.collision_geometry_sha256
            or self.controller_configuration_sha256 != config.controller.configuration_sha256
            or self.safety_configuration_sha256 != config.safety.configuration_sha256
            or self.attachment_algorithm_sha256 != config.attachment.algorithm_sha256
            or self.attachment_complete_configuration_sha256
            != config.attachment.configuration_sha256
        ):
            raise ValueError("A.3 configuration receipt projection differs")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 configuration receipt digest differs")
        return self


class ExactPlanA3PhaseAuditEvidenceV1(FrozenModel):
    """Immutable replay inputs for every explicit A.3 phase gate."""

    schema_version: Literal["ExactPlanA3PhaseAuditEvidenceV1"] = "ExactPlanA3PhaseAuditEvidenceV1"
    preflight_result: ExactPlanPhasePreflightV1
    path: NonActuatingPhasePathV1
    swept_collision: NonActuatingSweptCollisionV1
    attachment_transition: NonActuatingAttachmentTransitionV1
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def crossed_and_canonical(self) -> "ExactPlanA3PhaseAuditEvidenceV1":
        result = self.preflight_result
        path = self.path
        collision = self.swept_collision
        attachment = self.attachment_transition
        if (
            path.bound_plan_sha256 != result.bound_plan_sha256
            or collision.bound_plan_sha256 != result.bound_plan_sha256
            or attachment.bound_plan_sha256 != result.bound_plan_sha256
            or path.phase_index != result.phase_index
            or collision.phase_index != result.phase_index
            or attachment.phase_index != result.phase_index
            or path.phase_sha256 != result.phase_sha256
            or collision.phase_sha256 != result.phase_sha256
            or attachment.phase_sha256 != result.phase_sha256
            or collision.path_sha256 != path.path_sha256
            or attachment.path_sha256 != path.path_sha256
        ):
            raise ValueError("A.3 phase audit evidence crossed plan/phase/path")
        if self.evidence_sha256 != _canonical_model_sha256(self, "evidence_sha256"):
            raise ValueError("A.3 phase audit evidence digest differs")
        return self


class ExactPlanA3AuditReceiptV1(FrozenModel):
    schema_version: Literal["ExactPlanA3AuditReceiptV1"] = "ExactPlanA3AuditReceiptV1"
    standard_preflight_receipt: ExactPlanPreflightReceiptV1
    configuration_receipt: ExactPlanA3ConfigurationReceiptV1
    runtime_snapshot: PreflightRuntimeSnapshotV1
    phase_audit_evidence: tuple[ExactPlanA3PhaseAuditEvidenceV1, ...] = Field(min_length=1)
    formal_execution_eligible: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def crossed_and_canonical(self) -> "ExactPlanA3AuditReceiptV1":
        if (
            self.standard_preflight_receipt.bound_plan_sha256
            != self.configuration_receipt.bound_plan_sha256
        ):
            raise ValueError("A.3 receipts crossed exact plans")
        phases = self.standard_preflight_receipt.phase_results
        evidence = self.phase_audit_evidence
        config = self.configuration_receipt.complete_preflight_configuration
        if (
            self.runtime_snapshot.bound_plan_sha256 != self.configuration_receipt.bound_plan_sha256
            or self.runtime_snapshot.preplan_state_sha256 != phases[0].preplan_state_sha256
            or len(phases) != len(evidence)
            or tuple(item.preflight_result for item in evidence) != phases
            or any(
                item.preflight_result.phase_index != index
                or item.path.ik_algorithm_sha256 != config.ik.algorithm_sha256
                or item.path.ik_configuration_sha256 != config.ik.configuration_sha256
                or item.path.joint_limit_configuration_sha256
                != config.joint_limits.configuration_sha256
                or item.path.gripper_limit_configuration_sha256
                != config.gripper_limits.configuration_sha256
                or item.swept_collision.algorithm_sha256 != config.swept_collision.algorithm_sha256
                or item.swept_collision.configuration_sha256
                != config.swept_collision.configuration_sha256
                or item.attachment_transition.algorithm_sha256 != config.attachment.algorithm_sha256
                or item.attachment_transition.configuration_sha256
                != config.attachment.configuration_sha256
                for index, item in enumerate(evidence)
            )
        ):
            raise ValueError("A.3 aggregate evidence crossed plan/order/configuration")
        expected_state = self.runtime_snapshot.preplan_state_sha256
        expected_attachment_present = self.runtime_snapshot.active_attachment_present
        expected_attachment_sha256 = self.runtime_snapshot.active_attachment_sha256
        for item in evidence:
            transition = item.attachment_transition
            if (
                item.path.start_state_sha256 != expected_state
                or transition.attachment_present_before != expected_attachment_present
                or transition.attachment_sha256_before != expected_attachment_sha256
            ):
                raise ValueError("A.3 aggregate evidence broke state/attachment chain")
            expected_state = item.path.terminal_state_sha256
            expected_attachment_present = transition.attachment_present_after
            expected_attachment_sha256 = transition.attachment_sha256_after
        for previous, current in zip(evidence, evidence[1:]):
            if not _same_non_actuating_physical_state(
                previous.path.samples[-1],
                current.path.samples[0],
            ):
                raise ValueError("A.3 aggregate evidence broke physical-state continuity")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 audit receipt digest differs")
        return self


class HostSignedAppendOnlyA3VerifierReceiptV1(FrozenModel):
    """Schema reserved for a real host verifier; no producer exists here.

    A Phase-2 implementation must verify this receipt against the separately
    frozen host signer and append-only audit before it can authorize formal
    execution.  This non-actuating module neither owns a signing key nor
    invents such proof.
    """

    schema_version: Literal["HostSignedAppendOnlyA3VerifierReceiptV1"] = (
        "HostSignedAppendOnlyA3VerifierReceiptV1"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    a3_audit_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    challenge_nonce: str = Field(min_length=32)
    append_only_audit_sha256: str = Field(pattern=SHA256_PATTERN)
    verifier_key_id: str = Field(min_length=1)
    signature_algorithm: Literal["ED25519"] = "ED25519"
    signature_base64: str = Field(min_length=1)
    verified_against_frozen_allowed_signer: bool
    append_only_lifecycle_verified: bool
    all_gate_evidence_precedes_execution_start: bool
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical(self) -> "HostSignedAppendOnlyA3VerifierReceiptV1":
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("host A.3 verifier receipt digest differs")
        return self


def require_formal_a3_execution_authorization(
    audit_receipt: ExactPlanA3AuditReceiptV1,
    *,
    host_verifier_receipt: HostSignedAppendOnlyA3VerifierReceiptV1 | None,
) -> None:
    """Always fail closed until a reviewed host-signature verifier is bound."""

    if audit_receipt.formal_execution_eligible:
        raise ExactPlanPreflightRejected("unreviewed A.3 receipt claimed formal eligibility")
    if host_verifier_receipt is None:
        raise ExactPlanPreflightRejected("host-signed append-only A.3 verifier receipt is absent")
    if (
        host_verifier_receipt.bound_plan_sha256
        != audit_receipt.standard_preflight_receipt.bound_plan_sha256
        or host_verifier_receipt.a3_audit_receipt_sha256 != audit_receipt.receipt_sha256
        or not host_verifier_receipt.verified_against_frozen_allowed_signer
        or not host_verifier_receipt.append_only_lifecycle_verified
        or not host_verifier_receipt.all_gate_evidence_precedes_execution_start
    ):
        raise ExactPlanPreflightRejected(
            "host-signed append-only A.3 verifier receipt is invalid or crossed"
        )
    raise ExactPlanPreflightRejected(
        "host A.3 verifier signature verification is not implemented/bound"
    )


class ExactPlanNonActuatingCallbacksV1(Protocol):
    """A real implementation may call Isaac/Lula query APIs only."""

    implementation_sha256: str
    ik_algorithm_sha256: str
    swept_collision_algorithm_sha256: str
    attachment_algorithm_sha256: str
    non_actuating: Literal[True]

    def snapshot_runtime(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> PreflightRuntimeSnapshotV1: ...

    def solve_phase_path(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        *,
        start_state_sha256: str,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingPhasePathV1: ...

    def check_swept_collision(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingSweptCollisionV1: ...

    def check_attachment_transition(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        *,
        expected_attachment_present: bool,
        expected_attachment_sha256: str | None,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingAttachmentTransitionV1: ...


def _matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


class ExactPlanPreflightV1:
    """All-phase fail-closed coordinator implementing the bundle protocol."""

    def __init__(
        self,
        *,
        configuration: ExactPlanPreflightConfigurationV1,
        callbacks: ExactPlanNonActuatingCallbacksV1,
    ) -> None:
        self.configuration = configuration
        self.callbacks = callbacks
        self.implementation_sha256 = _read_regular_file_sha256(Path(__file__))
        self._cache: dict[str, ExactPlanA3AuditReceiptV1] = {}
        if getattr(callbacks, "non_actuating", None) is not True:
            raise ExactPlanPreflightRejected("preflight callback is not query-only")
        if callbacks.ik_algorithm_sha256 != configuration.ik.algorithm_sha256:
            raise ExactPlanPreflightRejected("IK callback implementation digest differs")
        if (
            callbacks.swept_collision_algorithm_sha256
            != configuration.swept_collision.algorithm_sha256
        ):
            raise ExactPlanPreflightRejected("collision callback implementation digest differs")
        if callbacks.attachment_algorithm_sha256 != configuration.attachment.algorithm_sha256:
            raise ExactPlanPreflightRejected("attachment callback implementation digest differs")
        if callbacks.implementation_sha256 != configuration.callback_implementation_sha256:
            raise ExactPlanPreflightRejected("preflight callback implementation digest differs")

    def _validate_plan_source_bindings(self, plan: M2CExactPlanPrimitivePlanV1) -> None:
        roles = {item.role: item.sha256 for item in plan.source_bindings}
        expected = {
            "PREFLIGHT_IMPLEMENTATION": self.implementation_sha256,
            "IK_ALGORITHM": self.configuration.ik.algorithm_sha256,
            "ROBOT_ASSET": self.configuration.ik.robot_description_sha256,
            "JOINT_LIMIT_CONFIGURATION": (self.configuration.joint_limits.configuration_sha256),
            "SWEPT_COLLISION_ALGORITHM": (self.configuration.swept_collision.algorithm_sha256),
            "CONTROLLER_CONFIGURATION": self.configuration.controller.configuration_sha256,
            "SAFETY_CONFIGURATION": self.configuration.safety.configuration_sha256,
        }
        if any(roles.get(role) != digest for role, digest in expected.items()):
            raise ExactPlanPreflightRejected(
                "preflight algorithm/configuration differs from plan source bindings"
            )

    @staticmethod
    def _validate_phase_allowlist_digests(phase: ExactPlanPhaseContractV1) -> None:
        wire = phase.phase
        if (
            phase.allowed_robot_links_sha256 != canonical_sha256(wire.allowed_robot_contact_paths)
            or phase.allowed_environment_paths_sha256
            # ExactExecutionPhaseV2 has no environment-path tuple.  Its exact
            # representable value is therefore the empty tuple; a later wire
            # revision must add an explicit tuple before allowing any entry.
            != canonical_sha256(())
            or phase.allowed_external_contact_paths_sha256
            != canonical_sha256(wire.allowed_external_contact_paths)
        ):
            raise ExactPlanPreflightRejected(
                "phase allowlist digest differs from immutable wire tuples"
            )

    def _validate_snapshot(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        snapshot: PreflightRuntimeSnapshotV1,
    ) -> None:
        config = self.configuration
        if (
            snapshot.bound_plan_sha256 != plan.bound_plan_sha256
            or snapshot.preplan_state_sha256 != plan.inputs.preplan_state_sha256
            or snapshot.observed_at_ns != plan.inputs.preplan_state_timestamp_ns
        ):
            raise ExactPlanPreflightRejected("runtime snapshot crossed plan/preplan state")
        if (
            snapshot.checked_at_ns - snapshot.observed_at_ns > config.safety.maximum_state_age_ns
            or snapshot.state_stale
        ):
            raise ExactPlanPreflightRejected("preplan state is stale")
        expected_shapes = EXPECTED_COMMAND_DIMENSIONS
        actual_shapes = {item.command: item.dimensions for item in snapshot.command_shapes}
        if actual_shapes != expected_shapes:
            raise ExactPlanPreflightRejected("controller command shapes differ")
        if (
            not snapshot.controller_ready
            or snapshot.controller_id != config.controller.controller_id
            or snapshot.controller_configuration_sha256
            != config.controller.controller_configuration_sha256
            or snapshot.controller_rate_hz != config.controller.required_rate_hz
            or snapshot.controller_readiness_query_duration_ns
            > config.controller.readiness_timeout_ns
        ):
            raise ExactPlanPreflightRejected("controller readiness/config/rate differs")
        if (
            not snapshot.collision_world_ready
            or not snapshot.contact_monitor_ready
            or not snapshot.attachment_monitor_ready
            or not snapshot.terminal_bilateral_contact_broker_ready
            or snapshot.emergency_stop_active
        ):
            raise ExactPlanPreflightRejected("safety/contact/attachment monitor is not ready")

    def _validate_path(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        start_state_sha256: str,
    ) -> None:
        config = self.configuration
        wire = phase.phase
        expected_sample_count = wire.steps + 1 if wire.command in MOTION_COMMANDS else 1
        if (
            path.bound_plan_sha256 != plan.bound_plan_sha256
            or path.phase_index != wire.phase_index
            or path.phase_sha256 != phase.phase_sha256
            or path.start_state_sha256 != start_state_sha256
            or path.joint_names != config.joint_limits.joint_names
            or path.sample_rate_hz != config.joint_limits.sample_rate_hz
            or path.ik_algorithm_sha256 != config.ik.algorithm_sha256
            or path.ik_configuration_sha256 != config.ik.configuration_sha256
            or path.joint_limit_configuration_sha256 != config.joint_limits.configuration_sha256
            or path.gripper_limit_configuration_sha256 != config.gripper_limits.configuration_sha256
            or path.effort_estimator_sha256 != config.joint_limits.effort_estimator_sha256
            or path.query_duration_ns
            > min(
                phase.timeout_ns,
                config.gripper_limits.timeout_ns_per_phase
                if wire.command == "GRIPPER_POSITION"
                else config.ik.timeout_ns_per_phase,
            )
            or len(path.samples) != expected_sample_count
            or tuple(item.sample_index for item in path.samples)
            != tuple(range(expected_sample_count))
            or path.samples[0].state_sha256 != path.start_state_sha256
            or path.samples[-1].state_sha256 != path.terminal_state_sha256
        ):
            raise ExactPlanPreflightRejected("non-actuating path is incomplete or crossed")

        limits = config.joint_limits
        width = len(limits.joint_names)
        cartesian = wire.command == "CARTESIAN_POSE"
        gripper = wire.command == "GRIPPER_POSITION"
        initial_gripper_position = path.samples[0].gripper_position_m
        for sample in path.samples:
            if (
                len(sample.joint_positions) != width
                or len(sample.estimated_abs_efforts) != width
                or sample.ik_applicable != cartesian
                or (cartesian and not sample.ik_converged)
                or sample.ik_position_residual_m
                > (config.ik.maximum_position_residual_m if cartesian else 0.0)
                or sample.ik_orientation_residual_rad
                > (config.ik.maximum_orientation_residual_rad if cartesian else 0.0)
                or sample.iterations > (config.ik.maximum_iterations_per_sample if cartesian else 0)
            ):
                raise ExactPlanPreflightRejected("IK sample is inapplicable, incomplete, or failed")
            if any(
                position < lower or position > upper
                for position, lower, upper in zip(
                    sample.joint_positions,
                    limits.lower_position,
                    limits.upper_position,
                )
            ):
                raise ExactPlanPreflightRejected("joint position limit rejected path")
            if any(
                effort > maximum
                for effort, maximum in zip(
                    sample.estimated_abs_efforts,
                    limits.maximum_abs_effort,
                )
            ):
                raise ExactPlanPreflightRejected("joint effort limit rejected path")
            if any(
                value < lower or value > upper
                for value, lower, upper in zip(
                    sample.end_effector_world_m,
                    config.safety.workspace_min_world_m,
                    config.safety.workspace_max_world_m,
                )
            ):
                raise ExactPlanPreflightRejected("workspace gate rejected path")
            gripper_limits = config.gripper_limits
            if not (
                gripper_limits.minimum_position_m
                <= sample.gripper_position_m
                <= gripper_limits.maximum_position_m
            ):
                raise ExactPlanPreflightRejected("gripper position limit rejected path")
            if not gripper and sample.gripper_position_m != initial_gripper_position:
                raise ExactPlanPreflightRejected(
                    "non-gripper phase changes the physical gripper state"
                )
        if cartesian:
            terminal = path.samples[-1]
            assert wire.goal_position_world_m is not None
            assert wire.orientation_world_wxyz is not None
            terminal_position_error = math.sqrt(
                sum(
                    (observed - expected) ** 2
                    for observed, expected in zip(
                        terminal.end_effector_world_m,
                        wire.goal_position_world_m,
                    )
                )
            )
            quaternion_dot = abs(
                sum(
                    observed * expected
                    for observed, expected in zip(
                        terminal.end_effector_world_wxyz,
                        wire.orientation_world_wxyz,
                    )
                )
            )
            terminal_orientation_error = 2.0 * math.acos(min(1.0, quaternion_dot))
            if (
                terminal_position_error
                > min(
                    config.ik.maximum_position_residual_m,
                    phase.convergence_tolerance_m,
                )
                or terminal_orientation_error > config.ik.maximum_orientation_residual_rad
            ):
                raise ExactPlanPreflightRejected(
                    "terminal FK pose differs from frozen Cartesian goal"
                )
        elif gripper:
            terminal_gripper_position = path.samples[-1].gripper_position_m
            assert wire.gripper_position_m is not None
            if (
                abs(terminal_gripper_position - wire.gripper_position_m)
                > config.gripper_limits.target_tolerance_m
            ):
                raise ExactPlanPreflightRejected(
                    "terminal gripper position differs from frozen target"
                )
        for previous, current in zip(path.samples, path.samples[1:]):
            derived_velocity = tuple(
                abs(second - first) * limits.sample_rate_hz
                for first, second in zip(previous.joint_positions, current.joint_positions)
            )
            if any(
                velocity > maximum
                for velocity, maximum in zip(
                    derived_velocity,
                    limits.maximum_velocity_per_s,
                )
            ):
                raise ExactPlanPreflightRejected("joint velocity limit rejected sampled path")
            gripper_velocity = (
                abs(current.gripper_position_m - previous.gripper_position_m)
                * config.gripper_limits.sample_rate_hz
            )
            if gripper_velocity > config.gripper_limits.maximum_velocity_m_per_s:
                raise ExactPlanPreflightRejected("gripper velocity limit rejected sampled path")

    def _validate_collision(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        collision: NonActuatingSweptCollisionV1,
    ) -> None:
        config = self.configuration.swept_collision
        wire = phase.phase
        expected_segments = wire.steps if wire.command in MOTION_COMMANDS else 0
        if (
            collision.bound_plan_sha256 != plan.bound_plan_sha256
            or collision.phase_index != wire.phase_index
            or collision.phase_sha256 != phase.phase_sha256
            or collision.path_sha256 != path.path_sha256
            or collision.algorithm_sha256 != config.algorithm_sha256
            or collision.configuration_sha256 != config.configuration_sha256
            or collision.query_duration_ns > min(phase.timeout_ns, config.timeout_ns_per_phase)
            or len(collision.segments) != expected_segments
            or tuple(item.segment_index for item in collision.segments)
            != tuple(range(expected_segments))
            or any(
                item.subsamples_checked != config.subsamples_per_segment
                for item in collision.segments
            )
        ):
            raise ExactPlanPreflightRejected("swept-collision coverage is incomplete or crossed")
        robot_root = config.robot_root_path
        for segment in collision.segments:
            for pair in segment.collision_pairs:
                side0_robot = _matches(pair.path0, (robot_root,))
                side1_robot = _matches(pair.path1, (robot_root,))
                if side0_robot == side1_robot:
                    raise ExactPlanPreflightRejected("unknown or robot-self collision pair")
                robot_path, external_path = (
                    (pair.path0, pair.path1) if side0_robot else (pair.path1, pair.path0)
                )
                if not (
                    _matches(robot_path, wire.allowed_robot_contact_paths)
                    and _matches(external_path, wire.allowed_external_contact_paths)
                ):
                    raise ExactPlanPreflightRejected(
                        "swept collision lies outside frozen phase allowlists"
                    )

    def _validate_attachment_transition(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        path: NonActuatingPhasePathV1,
        transition: NonActuatingAttachmentTransitionV1,
        *,
        expected_attachment_present: bool,
        expected_attachment_sha256: str | None,
    ) -> tuple[bool, str | None]:
        wire = phase.phase
        config = self.configuration.attachment
        expected_transition = {
            "ATTACH_CONTACT_ENTITY": "ATTACH",
            "REMOVE_ATTACHMENT": "REMOVE",
        }.get(wire.command, "NONE")
        if (
            transition.bound_plan_sha256 != plan.bound_plan_sha256
            or transition.phase_index != wire.phase_index
            or transition.phase_sha256 != phase.phase_sha256
            or transition.path_sha256 != path.path_sha256
            or transition.command != wire.command
            or transition.transition != expected_transition
            or transition.attachment_or_removal_selector != phase.attachment_or_removal_selector
            or transition.allowed_robot_contact_paths != wire.allowed_robot_contact_paths
            or transition.allowed_external_contact_paths != wire.allowed_external_contact_paths
            or transition.attachment_present_before != expected_attachment_present
            or transition.attachment_sha256_before != expected_attachment_sha256
            or transition.algorithm_sha256 != config.algorithm_sha256
            or transition.configuration_sha256 != config.configuration_sha256
            or transition.query_duration_ns > min(phase.timeout_ns, config.timeout_ns_per_phase)
        ):
            raise ExactPlanPreflightRejected(
                "attachment/contact query is incomplete, crossed, or uses the wrong transition"
            )

        if expected_transition == "ATTACH":
            pairs = transition.bilateral_contact_pairs
            if (
                expected_attachment_present
                or len(pairs) != 1
                or not transition.attachment_present_after
                or transition.attachment_sha256_after is None
            ):
                raise ExactPlanPreflightRejected(
                    "attachment query lacks one feasible bilateral transition"
                )
            pair = pairs[0]
            if not (
                _matches(pair.left_robot_path, wire.allowed_robot_contact_paths)
                and _matches(pair.right_robot_path, wire.allowed_robot_contact_paths)
                and _matches(pair.external_path, wire.allowed_external_contact_paths)
            ):
                raise ExactPlanPreflightRejected(
                    "bilateral contact pair lies outside frozen phase allowlists"
                )
        elif expected_transition == "REMOVE":
            if (
                not expected_attachment_present
                or expected_attachment_sha256 is None
                or transition.bilateral_contact_pairs
                or transition.attachment_present_after
                or transition.attachment_sha256_after is not None
            ):
                raise ExactPlanPreflightRejected(
                    "removal query does not bind the existing attachment"
                )
        elif (
            transition.bilateral_contact_pairs
            or transition.attachment_present_after != expected_attachment_present
            or transition.attachment_sha256_after != expected_attachment_sha256
        ):
            raise ExactPlanPreflightRejected(
                "non-transition phase changes attachment feasibility state"
            )
        return transition.attachment_present_after, transition.attachment_sha256_after

    def preflight_plan(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> ExactPlanA3AuditReceiptV1:
        cached = self._cache.get(plan.bound_plan_sha256)
        if cached is not None:
            return cached
        self._validate_plan_source_bindings(plan)
        try:
            snapshot = self.callbacks.snapshot_runtime(plan)
        except Exception as exc:
            raise ExactPlanPreflightRejected("runtime snapshot callback failed") from exc
        self._validate_snapshot(plan, snapshot)
        expected_initial_attachment = {
            "MOVE": True,
            "LIFT": True,
            "PLACE": True,
            "RELEASE": True,
            "GRASP": False,
            "REGRASP": False,
            "REOBSERVE": False,
            "REASSOCIATE_TARGET": False,
        }.get(plan.exact_execution_plan.canonical_skill)
        if expected_initial_attachment is None:
            raise ExactPlanPreflightRejected("canonical skill is outside ADR-0022 A.3")
        if snapshot.active_attachment_present != expected_initial_attachment:
            raise ExactPlanPreflightRejected(
                "initial attachment state differs from canonical skill semantics"
            )
        start_state_sha256 = plan.inputs.preplan_state_sha256
        attachment_present = snapshot.active_attachment_present
        attachment_sha256 = snapshot.active_attachment_sha256
        results: list[ExactPlanPhasePreflightV1] = []
        raw_phase_results: list[
            tuple[
                NonActuatingPhasePathV1,
                NonActuatingSweptCollisionV1,
                NonActuatingAttachmentTransitionV1,
            ]
        ] = []
        total_query_ns = 0
        for phase in plan.phases:
            wire = phase.phase
            self._validate_phase_allowlist_digests(phase)
            if (
                phase.command_rate_hz != self.configuration.controller.required_rate_hz
                or phase.command_dimensions != EXPECTED_COMMAND_DIMENSIONS[wire.command]
            ):
                raise ExactPlanPreflightRejected("phase controller shape/rate differs")
            try:
                path = self.callbacks.solve_phase_path(
                    plan,
                    phase,
                    start_state_sha256=start_state_sha256,
                    configuration=self.configuration,
                )
            except Exception as exc:
                raise ExactPlanPreflightRejected("IK/path callback failed") from exc
            self._validate_path(plan, phase, path, start_state_sha256)
            try:
                collision = self.callbacks.check_swept_collision(
                    plan,
                    phase,
                    path,
                    configuration=self.configuration,
                )
            except Exception as exc:
                raise ExactPlanPreflightRejected("swept-collision callback failed") from exc
            self._validate_collision(plan, phase, path, collision)
            try:
                attachment = self.callbacks.check_attachment_transition(
                    plan,
                    phase,
                    path,
                    expected_attachment_present=attachment_present,
                    expected_attachment_sha256=attachment_sha256,
                    configuration=self.configuration,
                )
            except Exception as exc:
                raise ExactPlanPreflightRejected(
                    "attachment/contact query callback failed"
                ) from exc
            attachment_present, attachment_sha256 = self._validate_attachment_transition(
                plan,
                phase,
                path,
                attachment,
                expected_attachment_present=attachment_present,
                expected_attachment_sha256=attachment_sha256,
            )
            raw_phase_results.append((path, collision, attachment))
            total_query_ns += (
                path.query_duration_ns + collision.query_duration_ns + attachment.query_duration_ns
            )
            if total_query_ns > self.configuration.total_timeout_ns:
                raise ExactPlanPreflightRejected("complete preflight timeout exceeded")
            results.append(
                ExactPlanPhasePreflightV1(
                    bound_plan_sha256=plan.bound_plan_sha256,
                    phase_index=wire.phase_index,
                    phase_sha256=phase.phase_sha256,
                    preplan_state_sha256=plan.inputs.preplan_state_sha256,
                    ik_algorithm_sha256=self.configuration.ik.algorithm_sha256,
                    limits_configuration_sha256=(
                        self.configuration.joint_limits.configuration_sha256
                    ),
                    swept_collision_algorithm_sha256=(
                        self.configuration.swept_collision.algorithm_sha256
                    ),
                    controller_configuration_sha256=(
                        self.configuration.controller.configuration_sha256
                    ),
                    safety_configuration_sha256=(self.configuration.safety.configuration_sha256),
                )
            )
            start_state_sha256 = path.terminal_state_sha256
        payload: dict[str, Any] = {
            "schema_version": "ExactPlanPreflightReceiptV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_results": [item.model_dump(mode="json") for item in results],
            "all_phases_passed_before_any_command": True,
        }
        standard_receipt = ExactPlanPreflightReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
        configuration_payload: dict[str, Any] = {
            "schema_version": "ExactPlanA3ConfigurationReceiptV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "plan_source_bindings_sha256": canonical_sha256(plan.source_bindings),
            "complete_preflight_configuration": self.configuration.model_dump(mode="json"),
            "complete_preflight_configuration_sha256": (self.configuration.configuration_sha256),
            "callback_implementation_sha256": self.callbacks.implementation_sha256,
            "ik_algorithm_sha256": self.configuration.ik.algorithm_sha256,
            "ik_complete_configuration_sha256": (self.configuration.ik.configuration_sha256),
            "ik_robot_description_sha256": (self.configuration.ik.robot_description_sha256),
            "joint_limit_configuration_sha256": (
                self.configuration.joint_limits.configuration_sha256
            ),
            "gripper_limit_configuration_sha256": (
                self.configuration.gripper_limits.configuration_sha256
            ),
            "swept_collision_algorithm_sha256": (
                self.configuration.swept_collision.algorithm_sha256
            ),
            "swept_collision_complete_configuration_sha256": (
                self.configuration.swept_collision.configuration_sha256
            ),
            "collision_geometry_sha256": (
                self.configuration.swept_collision.collision_geometry_sha256
            ),
            "controller_configuration_sha256": (self.configuration.controller.configuration_sha256),
            "safety_configuration_sha256": (self.configuration.safety.configuration_sha256),
            "attachment_algorithm_sha256": (self.configuration.attachment.algorithm_sha256),
            "attachment_complete_configuration_sha256": (
                self.configuration.attachment.configuration_sha256
            ),
            "current_plan_role_schema_covers_complete_a3_configuration": False,
            "binding_addendum_required": True,
            "binding_addendum_sha256": None,
            "formal_execution_eligible": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        configuration_receipt = ExactPlanA3ConfigurationReceiptV1(
            **configuration_payload,
            receipt_sha256=canonical_sha256(configuration_payload),
        )
        phase_evidence: list[ExactPlanA3PhaseAuditEvidenceV1] = []
        for result, (path, collision, attachment) in zip(results, raw_phase_results):
            phase_payload: dict[str, Any] = {
                "schema_version": "ExactPlanA3PhaseAuditEvidenceV1",
                "preflight_result": result.model_dump(mode="json"),
                "path": path.model_dump(mode="json"),
                "swept_collision": collision.model_dump(mode="json"),
                "attachment_transition": attachment.model_dump(mode="json"),
            }
            phase_evidence.append(
                ExactPlanA3PhaseAuditEvidenceV1(
                    **phase_payload,
                    evidence_sha256=canonical_sha256(phase_payload),
                )
            )
        audit_payload: dict[str, Any] = {
            "schema_version": "ExactPlanA3AuditReceiptV1",
            "standard_preflight_receipt": standard_receipt.model_dump(mode="json"),
            "configuration_receipt": configuration_receipt.model_dump(mode="json"),
            "runtime_snapshot": snapshot.model_dump(mode="json"),
            "phase_audit_evidence": [item.model_dump(mode="json") for item in phase_evidence],
            "formal_execution_eligible": False,
        }
        audit_receipt = ExactPlanA3AuditReceiptV1(
            **audit_payload,
            receipt_sha256=canonical_sha256(audit_payload),
        )
        self._cache[plan.bound_plan_sha256] = audit_receipt
        return audit_receipt

    def verify_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> ExactPlanPhasePreflightV1:
        """Bundle-compatible adapter; first call validates the entire plan."""

        receipt = self.preflight_plan(plan)
        if not receipt.formal_execution_eligible:
            raise ExactPlanPreflightRejected(
                "complete A.3 configuration is not bound by the Phase-2 addendum"
            )
        index = phase.phase.phase_index
        standard = receipt.standard_preflight_receipt
        if index >= len(standard.phase_results):
            raise ExactPlanPreflightRejected("requested phase is absent from full preflight")
        result = standard.phase_results[index]
        if result.phase_sha256 != phase.phase_sha256:
            raise ExactPlanPreflightRejected("requested phase differs from cached full preflight")
        return result


def strict_replay_a3_audit_receipt_v1(
    plan: M2CExactPlanPrimitivePlanV1,
    audit_receipt: ExactPlanA3AuditReceiptV1,
) -> ExactPlanA3AuditReceiptV1:
    """Independently replay every A.3 predicate over immutable evidence.

    This is an offline integrity verifier, not an authenticity oracle.  A
    successful return means the supplied canonical samples satisfy the bound
    limits/gates when replayed; formal execution still requires the separately
    frozen host signer and append-only lifecycle verifier, which this module
    deliberately cannot provide.
    """

    try:
        plan = M2CExactPlanPrimitivePlanV1.model_validate(plan.model_dump(mode="json"))
        audit_receipt = ExactPlanA3AuditReceiptV1.model_validate(
            audit_receipt.model_dump(mode="json")
        )
    except ValueError as exc:
        raise ExactPlanPreflightRejected(
            "offline replay evidence is not canonical and complete"
        ) from exc

    configuration_receipt = audit_receipt.configuration_receipt
    configuration = configuration_receipt.complete_preflight_configuration
    if (
        audit_receipt.standard_preflight_receipt.bound_plan_sha256 != plan.bound_plan_sha256
        or configuration_receipt.bound_plan_sha256 != plan.bound_plan_sha256
        or audit_receipt.runtime_snapshot.bound_plan_sha256 != plan.bound_plan_sha256
        or configuration_receipt.plan_source_bindings_sha256
        != canonical_sha256(plan.source_bindings)
    ):
        raise ExactPlanPreflightRejected("offline replay crossed plan/source bindings")

    # Construct only the pure validation surface.  No callback object exists
    # in replay mode, so replay cannot query or mutate Isaac.
    replay = object.__new__(ExactPlanPreflightV1)
    replay.configuration = configuration
    replay.implementation_sha256 = _read_regular_file_sha256(Path(__file__))
    replay._validate_plan_source_bindings(plan)
    replay._validate_snapshot(plan, audit_receipt.runtime_snapshot)

    expected_initial_attachment = {
        "MOVE": True,
        "LIFT": True,
        "PLACE": True,
        "RELEASE": True,
        "GRASP": False,
        "REGRASP": False,
        "REOBSERVE": False,
        "REASSOCIATE_TARGET": False,
    }.get(plan.exact_execution_plan.canonical_skill)
    if (
        expected_initial_attachment is None
        or audit_receipt.runtime_snapshot.active_attachment_present != expected_initial_attachment
    ):
        raise ExactPlanPreflightRejected(
            "offline replay initial attachment differs from canonical skill"
        )

    evidence = audit_receipt.phase_audit_evidence
    if len(evidence) != len(plan.phases):
        raise ExactPlanPreflightRejected("offline replay phase evidence is incomplete")
    start_state_sha256 = plan.inputs.preplan_state_sha256
    attachment_present = audit_receipt.runtime_snapshot.active_attachment_present
    attachment_sha256 = audit_receipt.runtime_snapshot.active_attachment_sha256
    expected_results: list[ExactPlanPhasePreflightV1] = []
    total_query_ns = 0
    previous_terminal: NonActuatingJointSampleV1 | None = None
    for index, (phase, item) in enumerate(zip(plan.phases, evidence)):
        wire = phase.phase
        if wire.phase_index != index:
            raise ExactPlanPreflightRejected("offline replay phase order differs")
        replay._validate_phase_allowlist_digests(phase)
        if (
            phase.command_rate_hz != configuration.controller.required_rate_hz
            or phase.command_dimensions != EXPECTED_COMMAND_DIMENSIONS[wire.command]
        ):
            raise ExactPlanPreflightRejected("offline replay controller shape/rate differs")
        path = item.path
        if previous_terminal is not None and not _same_non_actuating_physical_state(
            previous_terminal,
            path.samples[0],
        ):
            raise ExactPlanPreflightRejected("offline replay physical-state continuity differs")
        replay._validate_path(plan, phase, path, start_state_sha256)
        replay._validate_collision(plan, phase, path, item.swept_collision)
        attachment_present, attachment_sha256 = replay._validate_attachment_transition(
            plan,
            phase,
            path,
            item.attachment_transition,
            expected_attachment_present=attachment_present,
            expected_attachment_sha256=attachment_sha256,
        )
        total_query_ns += (
            path.query_duration_ns
            + item.swept_collision.query_duration_ns
            + item.attachment_transition.query_duration_ns
        )
        if total_query_ns > configuration.total_timeout_ns:
            raise ExactPlanPreflightRejected("offline replay complete timeout exceeded")
        expected_result = ExactPlanPhasePreflightV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=wire.phase_index,
            phase_sha256=phase.phase_sha256,
            preplan_state_sha256=plan.inputs.preplan_state_sha256,
            ik_algorithm_sha256=configuration.ik.algorithm_sha256,
            limits_configuration_sha256=configuration.joint_limits.configuration_sha256,
            swept_collision_algorithm_sha256=configuration.swept_collision.algorithm_sha256,
            controller_configuration_sha256=configuration.controller.configuration_sha256,
            safety_configuration_sha256=configuration.safety.configuration_sha256,
        )
        if item.preflight_result != expected_result:
            raise ExactPlanPreflightRejected("offline replay PASS projection differs")
        expected_results.append(expected_result)
        start_state_sha256 = path.terminal_state_sha256
        previous_terminal = path.samples[-1]

    if tuple(expected_results) != audit_receipt.standard_preflight_receipt.phase_results:
        raise ExactPlanPreflightRejected("offline replay standard receipt differs")
    return audit_receipt
