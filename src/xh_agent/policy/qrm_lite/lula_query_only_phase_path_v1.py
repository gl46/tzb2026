"""Query-only 60 Hz phase-path construction for the Phase-2 A.3 gate.

The provider in this module turns one immutable exact-plan phase into the
``NonActuatingPhasePathV1`` consumed by ``ExactPlanPreflightV1``.  Cartesian
phases are interpolated in world coordinates and solved sample-by-sample with
the byte-pinned Lula query kernel; gripper phases interpolate only the two
mirrored fingers; logical phases preserve one physical state.  No method in
this module writes an articulation target, steps a simulator, mutates a scene,
or executes a controller command.

The path is evidence, not authority.  REAL_ISAAC construction requires a real
active-session state source, the exact Lula coordinator, the same mutation
counter source, and a conservative real controller-effort upper-bound
provider.  Contract fixtures cannot claim formal eligibility.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightConfigurationV1,
    NonActuatingJointSampleV1,
    NonActuatingPhasePathV1,
    canonical_non_actuating_state_sha256,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    LULA_END_EFFECTOR_FRAME,
    LULA_JOINT_NAMES,
    ActiveSessionMutationCounterSourceV1,
    ActiveSessionMutationCountersV1,
    LulaQueryOnlyIKCoordinatorV1,
    LulaQueryOnlyIKReceiptV1,
    build_lula_query_only_ik_request_v1,
    canonical_lula_query_only_ik_configuration_v1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/lula_query_only_phase_path_v1.py"
ROBOT_BASE_FRAME = "panda_link0"
SAMPLE_RATE_HZ = 60.0


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LulaPhasePathUnavailable(RuntimeError):
    """A complete query-only path could not be proven."""


def _model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _implementation_sha256(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def _finite(values: tuple[float, ...], *, width: int, label: str) -> None:
    if len(values) != width or not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} is malformed")


def _normalize_quaternion(
    value: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    _finite(value, width=4, label="quaternion")
    norm = math.sqrt(sum(item * item for item in value))
    if norm <= 0.0:
        raise LulaPhasePathUnavailable("zero quaternion is not a valid frame")
    result = tuple(item / norm for item in value)
    if result[0] < 0.0 or (
        result[0] == 0.0 and next((item for item in result[1:] if item != 0.0), 1.0) < 0.0
    ):
        result = tuple(-item for item in result)
    return result  # type: ignore[return-value]


def _quaternion_conjugate(
    value: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    w, x, y, z = value
    return (w, -x, -y, -z)


def _quaternion_multiply(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return _normalize_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )


def _rotate(
    orientation_wxyz: tuple[float, float, float, float],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    w, x, y, z = orientation_wxyz
    vx, vy, vz = vector
    # Equivalent to q * [0,v] * conjugate(q), written without normalizing the
    # intermediate pure quaternion.
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _slerp(
    start: tuple[float, float, float, float],
    goal: tuple[float, float, float, float],
    fraction: float,
) -> tuple[float, float, float, float]:
    q0 = _normalize_quaternion(start)
    q1 = _normalize_quaternion(goal)
    dot = sum(left * right for left, right in zip(q0, q1, strict=True))
    if dot < 0.0:
        q1 = tuple(-value for value in q1)  # type: ignore[assignment]
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 1.0 - 1e-12:
        return _normalize_quaternion(
            tuple(left + fraction * (right - left) for left, right in zip(q0, q1, strict=True))  # type: ignore[arg-type]
        )
    angle = math.acos(dot)
    denominator = math.sin(angle)
    return _normalize_quaternion(
        tuple(
            (math.sin((1.0 - fraction) * angle) * left + math.sin(fraction * angle) * right)
            / denominator
            for left, right in zip(q0, q1, strict=True)
        )  # type: ignore[arg-type]
    )


def _matrix_to_quaternion_wxyz(
    values: tuple[float, ...],
) -> tuple[float, float, float, float]:
    _finite(values, width=9, label="rotation matrix")
    r00, r01, r02, r10, r11, r12, r20, r21, r22 = values
    trace = r00 + r11 + r22
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        raw = (0.25 * scale, (r21 - r12) / scale, (r02 - r20) / scale, (r10 - r01) / scale)
    elif r00 > r11 and r00 > r22:
        scale = math.sqrt(max(0.0, 1.0 + r00 - r11 - r22)) * 2.0
        raw = ((r21 - r12) / scale, 0.25 * scale, (r01 + r10) / scale, (r02 + r20) / scale)
    elif r11 > r22:
        scale = math.sqrt(max(0.0, 1.0 + r11 - r00 - r22)) * 2.0
        raw = ((r02 - r20) / scale, (r01 + r10) / scale, 0.25 * scale, (r12 + r21) / scale)
    else:
        scale = math.sqrt(max(0.0, 1.0 + r22 - r00 - r11)) * 2.0
        raw = ((r10 - r01) / scale, (r02 + r20) / scale, (r12 + r21) / scale, 0.25 * scale)
    return _normalize_quaternion(raw)


class ActiveSessionRobotStateV1(FrozenModel):
    """One immutable, query-only active-session state."""

    schema_version: Literal["ActiveSessionRobotStateV1"] = "ActiveSessionRobotStateV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_names: tuple[str, ...] = LULA_JOINT_NAMES
    joint_positions_rad: tuple[float, ...] = Field(min_length=7, max_length=7)
    gripper_position_m: float = Field(ge=0.0, le=0.04)
    end_effector_world_m: tuple[float, float, float]
    end_effector_world_wxyz: tuple[float, float, float, float]
    robot_base_world_m: tuple[float, float, float]
    robot_base_world_wxyz: tuple[float, float, float, float]
    observed_at_ns: int = Field(gt=0)
    source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    real_active_session_source: bool
    mocked_source: bool
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    query_only: Literal[True] = True
    state_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "ActiveSessionRobotStateV1":
        if self.joint_names != LULA_JOINT_NAMES:
            raise ValueError("active-session joint order differs")
        _finite(self.joint_positions_rad, width=7, label="active-session joints")
        _finite(self.end_effector_world_m, width=3, label="active-session hand position")
        _finite(self.robot_base_world_m, width=3, label="active-session base position")
        hand = _normalize_quaternion(self.end_effector_world_wxyz)
        base = _normalize_quaternion(self.robot_base_world_wxyz)
        if hand != self.end_effector_world_wxyz or base != self.robot_base_world_wxyz:
            raise ValueError("active-session orientation is not canonical normalized wxyz")
        if self.real_active_session_source == self.mocked_source:
            raise ValueError("active-session state must be exactly real or mocked")
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("active-session state read mutated the session")
        expected_state = canonical_non_actuating_state_sha256(
            {
                "joint_positions": self.joint_positions_rad,
                "end_effector_world_m": self.end_effector_world_m,
                "end_effector_world_wxyz": self.end_effector_world_wxyz,
                "gripper_position_m": self.gripper_position_m,
            }
        )
        if self.state_sha256 != expected_state:
            raise ValueError("active-session physical-state digest differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("active-session state receipt digest differs")
        return self


class ActiveSessionRobotStateSourceV1(Protocol):
    implementation_sha256: str
    real_active_session_source: bool
    mocked_source: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1

    def read_active_state(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> ActiveSessionRobotStateV1: ...


class ConservativeEffortUpperBoundReceiptV1(FrozenModel):
    schema_version: Literal["ConservativeEffortUpperBoundReceiptV1"] = (
        "ConservativeEffortUpperBoundReceiptV1"
    )
    joint_names: tuple[str, ...] = LULA_JOINT_NAMES
    joint_positions_sha256: str = Field(pattern=SHA256_PATTERN)
    estimated_abs_efforts: tuple[float, ...] = Field(min_length=7, max_length=7)
    provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    provider_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    real_runtime_provider: bool
    mocked_provider: bool
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    conservative_upper_bound: Literal[True] = True
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "ConservativeEffortUpperBoundReceiptV1":
        if self.joint_names != LULA_JOINT_NAMES:
            raise ValueError("effort upper-bound joint order differs")
        _finite(self.estimated_abs_efforts, width=7, label="effort upper bounds")
        if any(value < 0.0 for value in self.estimated_abs_efforts):
            raise ValueError("effort upper bound is negative")
        if self.real_runtime_provider == self.mocked_provider:
            raise ValueError("effort provider must be exactly real or mocked")
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("effort upper-bound query mutated the active session")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("effort upper-bound receipt digest differs")
        return self


class ConservativeEffortUpperBoundProviderV1(Protocol):
    implementation_sha256: str
    configuration_sha256: str
    joint_limit_source_sha256: str
    controller_configuration_sha256: str
    maximum_abs_effort: tuple[float, ...]
    joint_names: tuple[str, ...]
    real_runtime_provider: bool
    mocked_provider: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1

    def estimate_abs_effort_upper_bound(
        self,
        joint_positions_rad: tuple[float, ...],
    ) -> ConservativeEffortUpperBoundReceiptV1: ...


class LulaQueryOnlyPhasePathEvidenceV1(FrozenModel):
    """Full query evidence retained beside the standard preflight path."""

    schema_version: Literal["LulaQueryOnlyPhasePathEvidenceV1"] = "LulaQueryOnlyPhasePathEvidenceV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_state_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    ik_query_receipts: tuple[LulaQueryOnlyIKReceiptV1, ...]
    effort_receipts: tuple[ConservativeEffortUpperBoundReceiptV1, ...] = Field(min_length=1)
    path_provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_query_evidence_eligible: bool
    all_queries_before_any_command: Literal[True] = True
    physical_execution_claimed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "LulaQueryOnlyPhasePathEvidenceV1":
        if self.evidence_sha256 != _model_sha256(self, "evidence_sha256"):
            raise ValueError("Lula phase-path evidence digest differs")
        return self


class _PredictedState:
    def __init__(
        self,
        *,
        joints: tuple[float, ...],
        gripper: float,
        hand_position: tuple[float, float, float],
        hand_orientation: tuple[float, float, float, float],
        base_position: tuple[float, float, float],
        base_orientation: tuple[float, float, float, float],
        state_sha256: str,
        initial_state_receipt_sha256: str,
    ) -> None:
        self.joints = joints
        self.gripper = gripper
        self.hand_position = hand_position
        self.hand_orientation = hand_orientation
        self.base_position = base_position
        self.base_orientation = base_orientation
        self.state_sha256 = state_sha256
        self.initial_state_receipt_sha256 = initial_state_receipt_sha256


class LulaQueryOnlyPhasePathProviderV1:
    """Single-plan provider for ``ExactPlanNonActuatingCallbacksV1``."""

    non_actuating: Literal[True] = True
    implementation_path = IMPLEMENTATION_REPO_PATH

    def __init__(
        self,
        *,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        state_source: ActiveSessionRobotStateSourceV1,
        ik_coordinator: LulaQueryOnlyIKCoordinatorV1,
        effort_provider: ConservativeEffortUpperBoundProviderV1,
        project_root: Path,
    ) -> None:
        self.mode = mode
        self.state_source = state_source
        self.ik_coordinator = ik_coordinator
        self.effort_provider = effort_provider
        self.implementation_sha256 = _implementation_sha256(
            project_root.resolve() / IMPLEMENTATION_REPO_PATH
        )
        self._lula_configuration = canonical_lula_query_only_ik_configuration_v1()
        self.ik_algorithm_sha256 = canonical_sha256(
            {
                "schema_version": "LulaQueryOnlyPhasePathAlgorithmV1",
                "path_provider_implementation_sha256": self.implementation_sha256,
                "lula_adapter_implementation_sha256": (
                    ik_coordinator.adapter_implementation_sha256
                ),
                "lula_kernel_implementation_sha256": (ik_coordinator.kernel.implementation_sha256),
                "lula_source_closure_sha256": (ik_coordinator.source_closure.source_closure_sha256),
                "lula_configuration_sha256": self._lula_configuration.configuration_sha256,
                "interpolation": "WORLD_LINEAR_POSITION_SHORTEST_ARC_WXYZ",
                "sample_rate_hz": SAMPLE_RATE_HZ,
                "sample_zero": "EXACT_ACTIVE_SESSION_STATE",
            }
        )
        self._states: dict[str, _PredictedState] = {}
        self._active_plan_sha256: str | None = None
        self._evidence: dict[str, LulaQueryOnlyPhasePathEvidenceV1] = {}

        if (
            effort_provider.joint_names != LULA_JOINT_NAMES
            or state_source.mutation_counter_source is not ik_coordinator.counter_source
            or effort_provider.mutation_counter_source is not ik_coordinator.counter_source
        ):
            raise LulaPhasePathUnavailable("phase-path production dependencies disagree")
        if mode == "CONTRACT_TEST":
            if (
                ik_coordinator.mode != "CONTRACT_TEST"
                or state_source.real_active_session_source
                or not state_source.mocked_source
                or effort_provider.real_runtime_provider
                or not effort_provider.mocked_provider
            ):
                raise LulaPhasePathUnavailable(
                    "contract phase path received production dependency claims"
                )
        elif (
            ik_coordinator.mode != "REAL_ISAAC"
            or not state_source.real_active_session_source
            or state_source.mocked_source
            or not effort_provider.real_runtime_provider
            or effort_provider.mocked_provider
        ):
            raise LulaPhasePathUnavailable("REAL_ISAAC phase-path dependency identity differs")

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    def _validate_configuration(self, configuration: ExactPlanPreflightConfigurationV1) -> None:
        ik = configuration.ik
        lula = self._lula_configuration
        if (
            configuration.joint_limits.joint_names != LULA_JOINT_NAMES
            or configuration.joint_limits.sample_rate_hz != SAMPLE_RATE_HZ
            or configuration.controller.required_rate_hz != SAMPLE_RATE_HZ
            or ik.algorithm_id != "LULA_QUERY_ONLY_PHASE_PATH_V1"
            or ik.algorithm_sha256 != self.ik_algorithm_sha256
            or ik.robot_description_sha256
            != next(
                item.sha256
                for item in self.ik_coordinator.source_closure.files
                if item.role == "LULA_ROBOT_DESCRIPTION"
            )
            or ik.base_frame != ROBOT_BASE_FRAME
            or ik.end_effector_frame != LULA_END_EFFECTOR_FRAME
            or ik.maximum_position_residual_m != lula.position_tolerance_m
            or ik.maximum_orientation_residual_rad != lula.orientation_tolerance_rad
            or ik.maximum_iterations_per_sample != lula.certified_iteration_upper_bound
            or ik.deterministic_seed != lula.deterministic_sampling_seed
            or configuration.joint_limits.effort_estimator_sha256
            != self.effort_provider.implementation_sha256
            or configuration.joint_limits.source_sha256
            != self.effort_provider.joint_limit_source_sha256
            or configuration.joint_limits.maximum_abs_effort
            != self.effort_provider.maximum_abs_effort
            or configuration.controller.controller_configuration_sha256
            != self.effort_provider.controller_configuration_sha256
        ):
            raise LulaPhasePathUnavailable("phase-path preflight configuration differs")

    def _initial_state(self, plan: M2CExactPlanPrimitivePlanV1) -> _PredictedState:
        if self._active_plan_sha256 not in {None, plan.bound_plan_sha256}:
            raise LulaPhasePathUnavailable("phase-path provider crossed an active plan")
        self._active_plan_sha256 = plan.bound_plan_sha256
        existing = self._states.get(plan.inputs.preplan_state_sha256)
        if existing is not None:
            return existing
        state = self.state_source.read_active_state(plan)
        if (
            state.bound_plan_sha256 != plan.bound_plan_sha256
            or state.state_sha256 != plan.inputs.preplan_state_sha256
            or state.observed_at_ns != plan.inputs.preplan_state_timestamp_ns
            or state.source_implementation_sha256 != self.state_source.implementation_sha256
            or state.real_active_session_source != self.state_source.real_active_session_source
            or state.mocked_source != self.state_source.mocked_source
        ):
            raise LulaPhasePathUnavailable("active-session state crossed its bound plan")
        result = _PredictedState(
            joints=state.joint_positions_rad,
            gripper=state.gripper_position_m,
            hand_position=state.end_effector_world_m,
            hand_orientation=state.end_effector_world_wxyz,
            base_position=state.robot_base_world_m,
            base_orientation=state.robot_base_world_wxyz,
            state_sha256=state.state_sha256,
            initial_state_receipt_sha256=state.receipt_sha256,
        )
        self._states[state.state_sha256] = result
        return result

    @staticmethod
    def _world_target_in_base(
        state: _PredictedState,
        position_world: tuple[float, float, float],
        orientation_world: tuple[float, float, float, float],
    ) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
        inverse_base = _quaternion_conjugate(state.base_orientation)
        offset = tuple(
            value - base for value, base in zip(position_world, state.base_position, strict=True)
        )
        return (
            _rotate(inverse_base, offset),
            _quaternion_multiply(inverse_base, orientation_world),
        )

    @staticmethod
    def _base_result_in_world(
        state: _PredictedState,
        receipt: LulaQueryOnlyIKReceiptV1,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
        rotated = _rotate(state.base_orientation, receipt.achieved_position_robot_base_m)
        position = tuple(
            base + offset for base, offset in zip(state.base_position, rotated, strict=True)
        )
        orientation_base = _matrix_to_quaternion_wxyz(
            receipt.achieved_orientation_robot_base_matrix
        )
        return position, _quaternion_multiply(state.base_orientation, orientation_base)

    def _effort(self, joints: tuple[float, ...]) -> ConservativeEffortUpperBoundReceiptV1:
        receipt = self.effort_provider.estimate_abs_effort_upper_bound(joints)
        if (
            receipt.joint_positions_sha256
            != canonical_sha256({"joint_names": LULA_JOINT_NAMES, "joint_positions": joints})
            or receipt.provider_implementation_sha256 != self.effort_provider.implementation_sha256
            or receipt.provider_configuration_sha256 != self.effort_provider.configuration_sha256
            or receipt.real_runtime_provider != self.effort_provider.real_runtime_provider
            or receipt.mocked_provider != self.effort_provider.mocked_provider
        ):
            raise LulaPhasePathUnavailable("effort upper-bound receipt crossed path state")
        return receipt

    @staticmethod
    def _sample(
        *,
        index: int,
        joints: tuple[float, ...],
        effort: ConservativeEffortUpperBoundReceiptV1,
        position: tuple[float, float, float],
        orientation: tuple[float, float, float, float],
        gripper: float,
        ik_applicable: bool,
        position_residual: float = 0.0,
        orientation_residual: float = 0.0,
        iterations: int = 0,
    ) -> NonActuatingJointSampleV1:
        payload: dict[str, Any] = {
            "schema_version": "NonActuatingJointSampleV1",
            "sample_index": index,
            "joint_positions": joints,
            "estimated_abs_efforts": effort.estimated_abs_efforts,
            "end_effector_world_m": position,
            "end_effector_world_wxyz": _normalize_quaternion(orientation),
            "gripper_position_m": gripper,
            "ik_applicable": ik_applicable,
            "ik_converged": ik_applicable,
            "ik_position_residual_m": position_residual,
            "ik_orientation_residual_rad": orientation_residual,
            "iterations": iterations,
        }
        return NonActuatingJointSampleV1(
            **payload,
            state_sha256=canonical_non_actuating_state_sha256(payload),
        )

    def solve_phase_path(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        *,
        start_state_sha256: str,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> NonActuatingPhasePathV1:
        self._validate_configuration(configuration)
        if (
            phase.phase.phase_index >= len(plan.phases)
            or plan.phases[phase.phase.phase_index] != phase
        ):
            raise LulaPhasePathUnavailable("phase path crossed plan order")
        start = self._states.get(start_state_sha256)
        if start is None:
            start = self._initial_state(plan)
        if start.state_sha256 != start_state_sha256:
            raise LulaPhasePathUnavailable("phase path start state is unavailable")

        wire = phase.phase
        started = time.perf_counter_ns()
        ik_receipts: list[LulaQueryOnlyIKReceiptV1] = []
        effort_receipts: list[ConservativeEffortUpperBoundReceiptV1] = []
        samples: list[NonActuatingJointSampleV1] = []

        first_effort = self._effort(start.joints)
        effort_receipts.append(first_effort)
        samples.append(
            self._sample(
                index=0,
                joints=start.joints,
                effort=first_effort,
                position=start.hand_position,
                orientation=start.hand_orientation,
                gripper=start.gripper,
                ik_applicable=wire.command == "CARTESIAN_POSE",
            )
        )

        if wire.command == "CARTESIAN_POSE":
            assert wire.goal_position_world_m is not None
            assert wire.orientation_world_wxyz is not None
            warm_start = start.joints
            for index in range(1, wire.steps + 1):
                fraction = index / wire.steps
                target_position_world = tuple(
                    initial + fraction * (goal - initial)
                    for initial, goal in zip(
                        start.hand_position,
                        wire.goal_position_world_m,
                        strict=True,
                    )
                )
                target_orientation_world = _slerp(
                    start.hand_orientation,
                    wire.orientation_world_wxyz,
                    fraction,
                )
                target_position_base, target_orientation_base = self._world_target_in_base(
                    start,
                    target_position_world,  # type: ignore[arg-type]
                    target_orientation_world,
                )
                request = build_lula_query_only_ik_request_v1(
                    request_id=(
                        f"{plan.inputs.run_id}:{plan.inputs.decision_index}:"
                        f"{wire.phase_index}:{index}"
                    ),
                    warm_start_joint_positions_rad=warm_start,
                    target_position_robot_base_m=target_position_base,
                    target_orientation_robot_base_wxyz=target_orientation_base,
                    configuration=self._lula_configuration,
                    source_closure_sha256=(
                        self.ik_coordinator.source_closure.source_closure_sha256
                    ),
                )
                receipt = self.ik_coordinator.solve(request)
                if not receipt.accepted or (
                    self.mode == "REAL_ISAAC" and not receipt.formal_query_evidence_eligible
                ):
                    raise LulaPhasePathUnavailable("Lula rejected one frozen path sample")
                ik_receipts.append(receipt)
                warm_start = receipt.solution_joint_positions_rad
                achieved_position, achieved_orientation = self._base_result_in_world(start, receipt)
                effort = self._effort(warm_start)
                effort_receipts.append(effort)
                samples.append(
                    self._sample(
                        index=index,
                        joints=warm_start,
                        effort=effort,
                        position=achieved_position,
                        orientation=achieved_orientation,
                        gripper=start.gripper,
                        ik_applicable=True,
                        position_residual=receipt.position_residual_m,
                        orientation_residual=receipt.orientation_residual_rad,
                        iterations=receipt.certified_iteration_upper_bound,
                    )
                )
        elif wire.command == "GRIPPER_POSITION":
            assert wire.gripper_position_m is not None
            for index in range(1, wire.steps + 1):
                fraction = index / wire.steps
                gripper = start.gripper + fraction * (wire.gripper_position_m - start.gripper)
                effort = self._effort(start.joints)
                effort_receipts.append(effort)
                samples.append(
                    self._sample(
                        index=index,
                        joints=start.joints,
                        effort=effort,
                        position=start.hand_position,
                        orientation=start.hand_orientation,
                        gripper=gripper,
                        ik_applicable=False,
                    )
                )

        duration = time.perf_counter_ns() - started
        terminal = samples[-1]
        payload: dict[str, Any] = {
            "schema_version": "NonActuatingPhasePathV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_index": wire.phase_index,
            "phase_sha256": phase.phase_sha256,
            "start_state_sha256": start_state_sha256,
            "terminal_state_sha256": terminal.state_sha256,
            "joint_names": LULA_JOINT_NAMES,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "samples": [sample.model_dump(mode="json") for sample in samples],
            "ik_algorithm_sha256": self.ik_algorithm_sha256,
            "ik_configuration_sha256": configuration.ik.configuration_sha256,
            "joint_limit_configuration_sha256": (configuration.joint_limits.configuration_sha256),
            "gripper_limit_configuration_sha256": (
                configuration.gripper_limits.configuration_sha256
            ),
            "effort_estimator_sha256": self.effort_provider.implementation_sha256,
            "query_duration_ns": duration,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        path = NonActuatingPhasePathV1(
            **payload,
            path_sha256=canonical_sha256(payload),
        )
        terminal_state = _PredictedState(
            joints=terminal.joint_positions,
            gripper=terminal.gripper_position_m,
            hand_position=terminal.end_effector_world_m,
            hand_orientation=terminal.end_effector_world_wxyz,
            base_position=start.base_position,
            base_orientation=start.base_orientation,
            state_sha256=terminal.state_sha256,
            initial_state_receipt_sha256=start.initial_state_receipt_sha256,
        )
        self._states[terminal.state_sha256] = terminal_state
        evidence_payload: dict[str, Any] = {
            "schema_version": "LulaQueryOnlyPhasePathEvidenceV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "phase_index": wire.phase_index,
            "phase_sha256": phase.phase_sha256,
            "path_sha256": path.path_sha256,
            "initial_state_receipt_sha256": start.initial_state_receipt_sha256,
            "ik_query_receipts": [receipt.model_dump(mode="json") for receipt in ik_receipts],
            "effort_receipts": [receipt.model_dump(mode="json") for receipt in effort_receipts],
            "path_provider_implementation_sha256": self.implementation_sha256,
            "formal_query_evidence_eligible": self.mode == "REAL_ISAAC",
            "all_queries_before_any_command": True,
            "physical_execution_claimed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        evidence = LulaQueryOnlyPhasePathEvidenceV1(
            **evidence_payload,
            evidence_sha256=canonical_sha256(evidence_payload),
        )
        self._evidence[path.path_sha256] = evidence
        return path

    def evidence_for_path(self, path_sha256: str) -> LulaQueryOnlyPhasePathEvidenceV1:
        try:
            return self._evidence[path_sha256]
        except KeyError as exc:
            raise LulaPhasePathUnavailable("phase-path evidence is absent") from exc
