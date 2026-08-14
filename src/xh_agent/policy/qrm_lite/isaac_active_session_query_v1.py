"""Query-only active-session state and controller-effort evidence.

This module is the bridge between a persistent formal Isaac scene and the
Lula 60 Hz phase-path provider.  It deliberately owns no simulator objects and
executes no controller command.  A byte-bound scene owner supplies one atomic
readout; this module cross-checks that readout against a shared mutation
counter, caches it exactly once for bound-plan synthesis, and later binds the
same immutable state to the resulting plan.

The controller maximum-effort vector is used as a conservative upper bound,
not as a predicted torque.  The vector must be read from the same active
runtime, equal the reviewed joint-limit configuration, and remain protected by
the same mutation counter throughout all-plan preflight.  Contract fixtures
cannot claim REAL_ISAAC evidence.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    canonical_non_actuating_state_sha256,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    LULA_JOINT_NAMES,
    ActiveSessionMutationCounterSourceV1,
    ActiveSessionMutationCountersV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_phase_path_v1 import (
    ActiveSessionRobotStateV1,
    ConservativeEffortUpperBoundReceiptV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/isaac_active_session_query_v1.py"
CONTROLLED_PANDA_ARM_MAX_EFFORT = (87.0, 87.0, 87.0, 87.0, 12.0, 12.0, 12.0)
ISAAC_6_0_1_CONTAINER_IMAGE_DIGEST = (
    "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
)
ISAAC_6_0_1_FRANKA_RUNTIME_TYPE = (
    "isaacsim.robot.experimental.manipulators.examples.franka.franka.Franka"
)
ISAAC_6_0_1_RIGID_PRIM_RUNTIME_TYPE = "isaacsim.core.experimental.prims.impl.rigid_prim.RigidPrim"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IsaacActiveSessionQueryUnavailable(RuntimeError):
    """The active session cannot produce complete query-only evidence."""


def _model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _implementation_sha256(project_root: Path) -> str:
    return hashlib.sha256(
        read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
    ).hexdigest()


def _finite_tuple(values: tuple[float, ...], *, width: int, label: str) -> None:
    if len(values) != width or not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} is malformed")


def _canonical_quaternion(
    value: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    _finite_tuple(value, width=4, label="active-session quaternion")
    norm = math.sqrt(sum(item * item for item in value))
    if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("active-session quaternion is not normalized")
    normalized = tuple(item / norm for item in value)
    for item in normalized:
        if abs(item) > 1e-15:
            return tuple(-part for part in normalized) if item < 0.0 else normalized
    raise ValueError("active-session quaternion is degenerate")


class IsaacActiveSessionQueryConfigurationV1(_FrozenModel):
    """Immutable deployment/configuration identity for one real scene owner."""

    schema_version: Literal["IsaacActiveSessionQueryConfigurationV1"] = (
        "IsaacActiveSessionQueryConfigurationV1"
    )
    scope: Literal["CONTRACT_TEST", "REAL_ISAAC_6_0_1"]
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    runtime_owner_implementation_path: str = Field(min_length=1)
    runtime_owner_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    query_adapter_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    mutation_counter_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    robot_runtime_type: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]+$")
    rigid_prim_runtime_type: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]+$")
    controller_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_limit_source_sha256: str = Field(pattern=SHA256_PATTERN)
    robot_root_path: Literal["/World/Robot"] = "/World/Robot"
    hand_path: Literal["/World/Robot/panda_hand"] = "/World/Robot/panda_hand"
    joint_names: tuple[str, ...] = LULA_JOINT_NAMES
    arm_dof_indices: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    gripper_dof_index: Literal[7] = 7
    gripper_coordinate_semantics: Literal["PER_FINGER_OPENING_M"] = "PER_FINGER_OPENING_M"
    expected_arm_max_abs_effort: tuple[float, ...] = CONTROLLED_PANDA_ARM_MAX_EFFORT
    maximum_effort_abs_tolerance: Literal[1e-6] = 1e-6
    observation_clock: Literal["HOST_TIME_NS_AFTER_PUBLIC_CAPTURE"] = (
        "HOST_TIME_NS_AFTER_PUBLIC_CAPTURE"
    )
    query_only_required: Literal[True] = True
    teacher_allowed: Literal[False] = False
    privileged_truth_policy_input_allowed: Literal[False] = False
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "IsaacActiveSessionQueryConfigurationV1":
        if (
            self.joint_names != LULA_JOINT_NAMES
            or self.arm_dof_indices != tuple(range(7))
            or self.expected_arm_max_abs_effort != CONTROLLED_PANDA_ARM_MAX_EFFORT
        ):
            raise ValueError("active-session controlled-Panda identity differs")
        owner_path = Path(self.runtime_owner_implementation_path)
        if (
            owner_path.is_absolute()
            or not owner_path.parts
            or ".." in owner_path.parts
            or owner_path.suffix != ".py"
        ):
            raise ValueError("active-session runtime owner path is not repo-relative")
        if self.scope == "REAL_ISAAC_6_0_1" and (
            self.container_image_digest != ISAAC_6_0_1_CONTAINER_IMAGE_DIGEST
            or self.robot_runtime_type != ISAAC_6_0_1_FRANKA_RUNTIME_TYPE
            or self.rigid_prim_runtime_type != ISAAC_6_0_1_RIGID_PRIM_RUNTIME_TYPE
        ):
            raise ValueError("REAL_ISAAC runtime deployment identity differs")
        if self.configuration_sha256 != _model_sha256(self, "configuration_sha256"):
            raise ValueError("active-session query configuration digest differs")
        return self


class IsaacActiveSessionRuntimeReadoutV1(_FrozenModel):
    """Atomic scene-owner readout before any command for the bound plan."""

    schema_version: Literal["IsaacActiveSessionRuntimeReadoutV1"] = (
        "IsaacActiveSessionRuntimeReadoutV1"
    )
    context_sha256: str = Field(pattern=SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_owner_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    joint_names: tuple[str, ...] = LULA_JOINT_NAMES
    joint_positions_rad: tuple[float, ...] = Field(min_length=7, max_length=7)
    gripper_position_m: float = Field(ge=0.0, le=0.04)
    end_effector_world_m: tuple[float, float, float]
    end_effector_world_wxyz: tuple[float, float, float, float]
    robot_base_world_m: tuple[float, float, float]
    robot_base_world_wxyz: tuple[float, float, float, float]
    arm_max_abs_effort: tuple[float, ...] = Field(min_length=7, max_length=7)
    observed_at_ns: int = Field(gt=0)
    real_isaac: bool
    mocked_runtime: bool
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    controller_commands: Literal[0] = 0
    attachment_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    state_sha256: str = Field(pattern=SHA256_PATTERN)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "IsaacActiveSessionRuntimeReadoutV1":
        if self.real_isaac == self.mocked_runtime:
            raise ValueError("active-session runtime must be exactly real or mocked")
        if self.joint_names != LULA_JOINT_NAMES:
            raise ValueError("active-session runtime joint order differs")
        _finite_tuple(self.joint_positions_rad, width=7, label="active-session joints")
        _finite_tuple(self.arm_max_abs_effort, width=7, label="active-session effort clamp")
        _finite_tuple(self.end_effector_world_m, width=3, label="active-session hand")
        _finite_tuple(self.robot_base_world_m, width=3, label="active-session base")
        if any(value <= 0.0 for value in self.arm_max_abs_effort):
            raise ValueError("active-session effort clamp is non-positive")
        if (
            _canonical_quaternion(self.end_effector_world_wxyz) != self.end_effector_world_wxyz
            or _canonical_quaternion(self.robot_base_world_wxyz) != self.robot_base_world_wxyz
        ):
            raise ValueError("active-session runtime quaternion is not canonical")
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("active-session runtime readout mutated the scene")
        expected_state = canonical_non_actuating_state_sha256(
            {
                "joint_positions": self.joint_positions_rad,
                "end_effector_world_m": self.end_effector_world_m,
                "end_effector_world_wxyz": self.end_effector_world_wxyz,
                "gripper_position_m": self.gripper_position_m,
            }
        )
        if self.state_sha256 != expected_state:
            raise ValueError("active-session runtime state digest differs")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("active-session runtime receipt digest differs")
        return self


class FormalIsaacActiveSessionQueryRuntimeV1(Protocol):
    """Implemented by the single persistent, byte-bound Isaac scene owner."""

    implementation_sha256: str
    real_isaac: bool
    mocked_runtime: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1

    def read_active_session_query_state(
        self,
        *,
        context_sha256: str,
        configuration: IsaacActiveSessionQueryConfigurationV1,
        after_ns: int,
    ) -> IsaacActiveSessionRuntimeReadoutV1: ...


def _runtime_type(value: object) -> str:
    kind = type(value)
    return f"{kind.__module__}.{kind.__qualname__}"


def _sequence(value: Any, *, label: str) -> list[Any]:
    if hasattr(value, "numpy"):
        value = value.numpy()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        raise IsaacActiveSessionQueryUnavailable(f"{label} is not an array")
    return list(value)


def _first_row(value: Any, *, width: int, label: str) -> tuple[float, ...]:
    outer = _sequence(value, label=label)
    if len(outer) == 1 and isinstance(outer[0], (list, tuple)):
        outer = list(outer[0])
    try:
        result = tuple(float(item) for item in outer)
    except (TypeError, ValueError) as exc:
        raise IsaacActiveSessionQueryUnavailable(f"{label} contains non-numeric data") from exc
    if len(result) != width or not all(math.isfinite(item) for item in result):
        raise IsaacActiveSessionQueryUnavailable(f"{label} width/value differs")
    return result


class IsaacObjectActiveSessionRuntimeV1:
    """Concrete getter-only adapter for one active Isaac articulation.

    The enclosing scene owner increments the shared counter at every target
    write, physics step, controller command, scene edit, and attachment edit.
    This adapter calls only articulation/rigid-prim getters.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        robot: Any,
        hand_prim: Any,
        robot_root_prim: Any,
        mutation_counter_source: ActiveSessionMutationCounterSourceV1,
        now_ns: Callable[[], int],
        configuration: IsaacActiveSessionQueryConfigurationV1,
    ) -> None:
        owner_path = project_root.resolve() / configuration.runtime_owner_implementation_path
        if (
            hashlib.sha256(read_regular_file_once(owner_path)).hexdigest()
            != configuration.runtime_owner_implementation_sha256
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session runtime owner source digest differs"
            )
        if (
            _runtime_type(robot) != configuration.robot_runtime_type
            or _runtime_type(hand_prim) != configuration.rigid_prim_runtime_type
            or _runtime_type(robot_root_prim) != configuration.rigid_prim_runtime_type
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session Isaac object type identity differs"
            )
        if mode == "CONTRACT_TEST":
            if (
                configuration.scope != "CONTRACT_TEST"
                or mutation_counter_source.real_active_session_source
                or not mutation_counter_source.mocked_counter_source
            ):
                raise IsaacActiveSessionQueryUnavailable(
                    "contract Isaac object runtime received production claims"
                )
        elif (
            configuration.scope != "REAL_ISAAC_6_0_1"
            or not mutation_counter_source.real_active_session_source
            or mutation_counter_source.mocked_counter_source
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "REAL_ISAAC object runtime dependency identity differs"
            )
        self.implementation_sha256 = configuration.runtime_owner_implementation_sha256
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_runtime = mode == "CONTRACT_TEST"
        self.mutation_counter_source = mutation_counter_source
        self.robot = robot
        self.hand_prim = hand_prim
        self.robot_root_prim = robot_root_prim
        self.now_ns = now_ns

    @staticmethod
    def _world_pose(
        prim: Any,
        *,
        label: str,
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        getter = getattr(prim, "get_world_poses", None)
        if not callable(getter):
            raise IsaacActiveSessionQueryUnavailable(f"{label} lacks get_world_poses")
        positions, orientations = getter()
        return (
            _first_row(positions, width=3, label=f"{label} world position"),
            _canonical_quaternion(
                _first_row(
                    orientations,
                    width=4,
                    label=f"{label} world orientation",
                )
            ),
        )

    def read_active_session_query_state(
        self,
        *,
        context_sha256: str,
        configuration: IsaacActiveSessionQueryConfigurationV1,
        after_ns: int,
    ) -> IsaacActiveSessionRuntimeReadoutV1:
        if configuration.runtime_owner_implementation_sha256 != self.implementation_sha256:
            raise IsaacActiveSessionQueryUnavailable(
                "active-session runtime received a different configuration"
            )
        before = self.mutation_counter_source.snapshot_mutation_counters()
        joint_getter = getattr(self.robot, "get_joint_positions", None)
        effort_getter = getattr(self.robot, "get_dof_max_efforts", None)
        if not callable(joint_getter) or not callable(effort_getter):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session articulation query API is incomplete"
            )
        joints = _first_row(
            joint_getter(),
            width=8,
            label="active-session articulation positions",
        )
        efforts = _first_row(
            effort_getter(),
            width=8,
            label="active-session articulation maximum efforts",
        )
        hand_position, hand_orientation = self._world_pose(
            self.hand_prim,
            label="active-session hand prim",
        )
        base_position, base_orientation = self._world_pose(
            self.robot_root_prim,
            label="active-session robot-root prim",
        )
        observed_at_ns = int(self.now_ns())
        if observed_at_ns <= after_ns:
            raise IsaacActiveSessionQueryUnavailable(
                "active-session observation clock did not advance past capture"
            )
        after = self.mutation_counter_source.snapshot_mutation_counters()
        state_payload = {
            "joint_positions": joints[:7],
            "end_effector_world_m": hand_position,
            "end_effector_world_wxyz": hand_orientation,
            "gripper_position_m": joints[7],
        }
        payload: dict[str, Any] = {
            "schema_version": "IsaacActiveSessionRuntimeReadoutV1",
            "context_sha256": context_sha256,
            "configuration_sha256": configuration.configuration_sha256,
            "runtime_owner_implementation_sha256": self.implementation_sha256,
            "joint_names": LULA_JOINT_NAMES,
            "joint_positions_rad": joints[:7],
            "gripper_position_m": joints[7],
            "end_effector_world_m": hand_position,
            "end_effector_world_wxyz": hand_orientation,
            "robot_base_world_m": base_position,
            "robot_base_world_wxyz": base_orientation,
            "arm_max_abs_effort": efforts[:7],
            "observed_at_ns": observed_at_ns,
            "real_isaac": self.real_isaac,
            "mocked_runtime": self.mocked_runtime,
            "mutation_counters_before": before,
            "mutation_counters_after": after,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "controller_commands": 0,
            "attachment_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "state_sha256": canonical_non_actuating_state_sha256(state_payload),
        }
        return IsaacActiveSessionRuntimeReadoutV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )


class IsaacActiveSessionQueryProviderV1:
    """Single-use state source and conservative effort-clamp provider."""

    joint_names = LULA_JOINT_NAMES

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        runtime: FormalIsaacActiveSessionQueryRuntimeV1,
        configuration: IsaacActiveSessionQueryConfigurationV1,
    ) -> None:
        self.mode = mode
        self.runtime = runtime
        self.configuration = configuration
        self.configuration_sha256 = configuration.configuration_sha256
        self.joint_limit_source_sha256 = configuration.joint_limit_source_sha256
        self.controller_configuration_sha256 = configuration.controller_configuration_sha256
        self.maximum_abs_effort = configuration.expected_arm_max_abs_effort
        self.implementation_sha256 = _implementation_sha256(project_root)
        self.mutation_counter_source = runtime.mutation_counter_source
        self.real_active_session_source = mode == "REAL_ISAAC"
        self.mocked_source = mode == "CONTRACT_TEST"
        self.real_runtime_provider = mode == "REAL_ISAAC"
        self.mocked_provider = mode == "CONTRACT_TEST"
        self._cached: IsaacActiveSessionRuntimeReadoutV1 | None = None
        self._state_bound_to_plan = False

        expected_scope = "REAL_ISAAC_6_0_1" if mode == "REAL_ISAAC" else "CONTRACT_TEST"
        if (
            configuration.scope != expected_scope
            or configuration.query_adapter_implementation_sha256 != self.implementation_sha256
            or runtime.implementation_sha256 != configuration.runtime_owner_implementation_sha256
            or runtime.mutation_counter_source.implementation_sha256
            != configuration.mutation_counter_implementation_sha256
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session runtime/configuration identity differs"
            )
        if mode == "CONTRACT_TEST":
            if runtime.real_isaac or not runtime.mocked_runtime:
                raise IsaacActiveSessionQueryUnavailable(
                    "contract active-session provider received production claims"
                )
        elif (
            not runtime.real_isaac
            or runtime.mocked_runtime
            or not runtime.mutation_counter_source.real_active_session_source
            or runtime.mutation_counter_source.mocked_counter_source
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "REAL_ISAAC active-session dependencies differ"
            )

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    def capture_preplan_state(
        self,
        *,
        context_sha256: str,
        after_ns: int,
    ) -> IsaacActiveSessionRuntimeReadoutV1:
        """Consume one query context before plan construction or any command."""

        if self._cached is not None:
            raise IsaacActiveSessionQueryUnavailable(
                "active-session pre-plan state was already captured"
            )
        before = self.mutation_counter_source.snapshot_mutation_counters()
        raw = self.runtime.read_active_session_query_state(
            context_sha256=context_sha256,
            configuration=self.configuration,
            after_ns=after_ns,
        )
        readout = IsaacActiveSessionRuntimeReadoutV1.model_validate(
            raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        )
        after = self.mutation_counter_source.snapshot_mutation_counters()
        if (
            after != before
            or readout.mutation_counters_before != before
            or readout.mutation_counters_after != after
            or readout.context_sha256 != context_sha256
            or readout.configuration_sha256 != self.configuration_sha256
            or readout.runtime_owner_implementation_sha256 != self.runtime.implementation_sha256
            or readout.observed_at_ns <= after_ns
            or readout.real_isaac != self.runtime.real_isaac
            or readout.mocked_runtime != self.runtime.mocked_runtime
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session readout crossed context/runtime or mutated the scene"
            )
        tolerance = self.configuration.maximum_effort_abs_tolerance
        if any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)
            for actual, expected in zip(
                readout.arm_max_abs_effort,
                self.configuration.expected_arm_max_abs_effort,
                strict=True,
            )
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session controller effort clamp differs from reviewed limits"
            )
        self._cached = readout
        return readout

    def cached_preplan_state(
        self,
        *,
        context_sha256: str,
    ) -> IsaacActiveSessionRuntimeReadoutV1:
        state = self._cached
        if state is None or state.context_sha256 != context_sha256:
            raise IsaacActiveSessionQueryUnavailable(
                "active-session cached pre-plan state is absent"
            )
        return state

    def read_active_state(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> ActiveSessionRobotStateV1:
        state = self._cached
        if state is None or self._state_bound_to_plan:
            raise IsaacActiveSessionQueryUnavailable(
                "active-session state was absent or already bound"
            )
        if (
            state.state_sha256 != plan.inputs.preplan_state_sha256
            or state.observed_at_ns != plan.inputs.preplan_state_timestamp_ns
            or plan.inputs.preplan_state_dimensions != 8
            or plan.inputs.preplan_state_units != "rad_7_plus_per_finger_m"
        ):
            raise IsaacActiveSessionQueryUnavailable(
                "active-session state differs from bound-plan inputs"
            )
        payload: dict[str, Any] = {
            "schema_version": "ActiveSessionRobotStateV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "joint_names": LULA_JOINT_NAMES,
            "joint_positions_rad": state.joint_positions_rad,
            "gripper_position_m": state.gripper_position_m,
            "end_effector_world_m": state.end_effector_world_m,
            "end_effector_world_wxyz": state.end_effector_world_wxyz,
            "robot_base_world_m": state.robot_base_world_m,
            "robot_base_world_wxyz": state.robot_base_world_wxyz,
            "observed_at_ns": state.observed_at_ns,
            "source_implementation_sha256": self.implementation_sha256,
            "real_active_session_source": self.real_active_session_source,
            "mocked_source": self.mocked_source,
            "mutation_counters_before": state.mutation_counters_before,
            "mutation_counters_after": state.mutation_counters_after,
            "query_only": True,
            "state_sha256": state.state_sha256,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        self._state_bound_to_plan = True
        return ActiveSessionRobotStateV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )

    def estimate_abs_effort_upper_bound(
        self,
        joint_positions_rad: tuple[float, ...],
    ) -> ConservativeEffortUpperBoundReceiptV1:
        state = self._cached
        if state is None:
            raise IsaacActiveSessionQueryUnavailable(
                "effort-clamp query has no cached active session"
            )
        _finite_tuple(joint_positions_rad, width=7, label="effort-query joints")
        before = self.mutation_counter_source.snapshot_mutation_counters()
        after = self.mutation_counter_source.snapshot_mutation_counters()
        if before != after or before != state.mutation_counters_after:
            raise IsaacActiveSessionQueryUnavailable(
                "active session changed before all-plan effort preflight"
            )
        payload: dict[str, Any] = {
            "schema_version": "ConservativeEffortUpperBoundReceiptV1",
            "joint_names": LULA_JOINT_NAMES,
            "joint_positions_sha256": canonical_sha256(
                {
                    "joint_names": LULA_JOINT_NAMES,
                    "joint_positions": joint_positions_rad,
                }
            ),
            "estimated_abs_efforts": state.arm_max_abs_effort,
            "provider_implementation_sha256": self.implementation_sha256,
            "provider_configuration_sha256": self.configuration_sha256,
            "real_runtime_provider": self.real_runtime_provider,
            "mocked_provider": self.mocked_provider,
            "mutation_counters_before": before,
            "mutation_counters_after": after,
            "conservative_upper_bound": True,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
        }
        return ConservativeEffortUpperBoundReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
