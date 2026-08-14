from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    canonical_non_actuating_state_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.isaac_active_session_query_v1 import (
    CONTROLLED_PANDA_ARM_MAX_EFFORT,
    IsaacActiveSessionQueryConfigurationV1,
    IsaacActiveSessionQueryProviderV1,
    IsaacActiveSessionQueryUnavailable,
    IsaacActiveSessionRuntimeReadoutV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    LULA_JOINT_NAMES,
    ActiveSessionMutationCountersV1,
)


ROOT = Path(__file__).resolve().parents[2]


def _with_digest(model_type: type[Any], **payload: Any) -> Any:
    provisional = model_type.model_construct(**payload, configuration_sha256="0" * 64)
    raw = provisional.model_dump(mode="json", exclude={"configuration_sha256"})
    return model_type.model_validate({**raw, "configuration_sha256": canonical_sha256(raw)})


class _Counters:
    implementation_sha256 = "1" * 64
    real_active_session_source = False
    mocked_counter_source = True

    def __init__(self) -> None:
        self.writes = 0

    def snapshot_mutation_counters(self) -> ActiveSessionMutationCountersV1:
        return ActiveSessionMutationCountersV1(
            articulation_target_writes=self.writes,
            simulation_steps=0,
            scene_mutations=0,
            controller_commands=0,
            attachment_mutations=0,
        )


class _Runtime:
    implementation_sha256 = "2" * 64
    real_isaac = False
    mocked_runtime = True

    def __init__(
        self,
        counters: _Counters,
        *,
        max_effort: tuple[float, ...] = CONTROLLED_PANDA_ARM_MAX_EFFORT,
        mutate: bool = False,
    ) -> None:
        self.mutation_counter_source = counters
        self.max_effort = max_effort
        self.mutate = mutate
        self.calls = 0

    def read_active_session_query_state(
        self,
        *,
        context_sha256: str,
        configuration: IsaacActiveSessionQueryConfigurationV1,
        after_ns: int,
    ) -> IsaacActiveSessionRuntimeReadoutV1:
        self.calls += 1
        before = self.mutation_counter_source.snapshot_mutation_counters()
        if self.mutate:
            self.mutation_counter_source.writes += 1
        after = self.mutation_counter_source.snapshot_mutation_counters()
        state_payload = {
            "joint_positions": (0.0,) * 7,
            "end_effector_world_m": (0.0, 0.0, 0.5),
            "end_effector_world_wxyz": (1.0, 0.0, 0.0, 0.0),
            "gripper_position_m": 0.04,
        }
        payload: dict[str, Any] = {
            "schema_version": "IsaacActiveSessionRuntimeReadoutV1",
            "context_sha256": context_sha256,
            "configuration_sha256": configuration.configuration_sha256,
            "runtime_owner_implementation_sha256": self.implementation_sha256,
            "joint_names": LULA_JOINT_NAMES,
            "joint_positions_rad": (0.0,) * 7,
            "gripper_position_m": 0.04,
            "end_effector_world_m": (0.0, 0.0, 0.5),
            "end_effector_world_wxyz": (1.0, 0.0, 0.0, 0.0),
            "robot_base_world_m": (-0.35, 0.0, 0.45),
            "robot_base_world_wxyz": (1.0, 0.0, 0.0, 0.0),
            "arm_max_abs_effort": self.max_effort,
            "observed_at_ns": after_ns + 1,
            "real_isaac": False,
            "mocked_runtime": True,
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


def _configuration(runtime: _Runtime) -> IsaacActiveSessionQueryConfigurationV1:
    return _with_digest(
        IsaacActiveSessionQueryConfigurationV1,
        scope="CONTRACT_TEST",
        container_image_digest="sha256:" + "3" * 64,
        runtime_owner_implementation_path="scripts/m2c/formal_isaac_backend_v4.py",
        runtime_owner_implementation_sha256=runtime.implementation_sha256,
        mutation_counter_implementation_sha256=(
            runtime.mutation_counter_source.implementation_sha256
        ),
        controller_configuration_sha256="4" * 64,
        joint_limit_source_sha256="5" * 64,
        robot_root_path="/World/Robot",
        hand_path="/World/Robot/panda_hand",
        joint_names=LULA_JOINT_NAMES,
        arm_dof_indices=tuple(range(7)),
        gripper_dof_index=7,
        gripper_coordinate_semantics="PER_FINGER_OPENING_M",
        expected_arm_max_abs_effort=CONTROLLED_PANDA_ARM_MAX_EFFORT,
        maximum_effort_abs_tolerance=1e-6,
        observation_clock="HOST_TIME_NS_AFTER_PUBLIC_CAPTURE",
        query_only_required=True,
        teacher_allowed=False,
        privileged_truth_policy_input_allowed=False,
    )


def _provider(
    *,
    max_effort: tuple[float, ...] = CONTROLLED_PANDA_ARM_MAX_EFFORT,
    mutate: bool = False,
) -> tuple[IsaacActiveSessionQueryProviderV1, _Runtime]:
    counters = _Counters()
    runtime = _Runtime(counters, max_effort=max_effort, mutate=mutate)
    provider = IsaacActiveSessionQueryProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime=runtime,
        configuration=_configuration(runtime),
    )
    return provider, runtime


def test_state_is_captured_once_then_bound_to_the_same_plan() -> None:
    provider, runtime = _provider()
    context = "6" * 64
    captured = provider.capture_preplan_state(context_sha256=context, after_ns=100)
    plan = SimpleNamespace(
        bound_plan_sha256="7" * 64,
        inputs=SimpleNamespace(
            preplan_state_sha256=captured.state_sha256,
            preplan_state_timestamp_ns=captured.observed_at_ns,
            preplan_state_dimensions=8,
            preplan_state_units="rad_7_plus_per_finger_m",
        ),
    )

    state = provider.read_active_state(plan)
    effort = provider.estimate_abs_effort_upper_bound((0.01,) * 7)

    assert runtime.calls == 1
    assert state.state_sha256 == captured.state_sha256
    assert state.bound_plan_sha256 == plan.bound_plan_sha256
    assert effort.estimated_abs_efforts == CONTROLLED_PANDA_ARM_MAX_EFFORT
    assert effort.provider_configuration_sha256 == provider.configuration_sha256
    assert effort.mutation_counters_before == effort.mutation_counters_after
    assert provider.formal_query_evidence_eligible is False
    with pytest.raises(IsaacActiveSessionQueryUnavailable, match="already captured"):
        provider.capture_preplan_state(context_sha256=context, after_ns=101)
    with pytest.raises(IsaacActiveSessionQueryUnavailable, match="already bound"):
        provider.read_active_state(plan)


def test_context_and_plan_identity_cannot_be_substituted() -> None:
    provider, _ = _provider()
    captured = provider.capture_preplan_state(context_sha256="8" * 64, after_ns=100)
    with pytest.raises(IsaacActiveSessionQueryUnavailable, match="cached"):
        provider.cached_preplan_state(context_sha256="9" * 64)
    wrong_plan = SimpleNamespace(
        bound_plan_sha256="a" * 64,
        inputs=SimpleNamespace(
            preplan_state_sha256="b" * 64,
            preplan_state_timestamp_ns=captured.observed_at_ns,
            preplan_state_dimensions=8,
            preplan_state_units="rad_7_plus_per_finger_m",
        ),
    )
    with pytest.raises(IsaacActiveSessionQueryUnavailable, match="bound-plan"):
        provider.read_active_state(wrong_plan)


def test_mutating_readout_is_rejected() -> None:
    provider, _ = _provider(mutate=True)
    with pytest.raises(ValueError, match="mutated"):
        provider.capture_preplan_state(context_sha256="c" * 64, after_ns=100)


def test_controller_effort_clamp_must_match_reviewed_limits() -> None:
    provider, _ = _provider(max_effort=(86.0, 87.0, 87.0, 87.0, 12.0, 12.0, 12.0))
    with pytest.raises(IsaacActiveSessionQueryUnavailable, match="effort clamp"):
        provider.capture_preplan_state(context_sha256="d" * 64, after_ns=100)


def test_real_mode_rejects_contract_runtime() -> None:
    counters = _Counters()
    runtime = _Runtime(counters)
    config = _configuration(runtime)
    raw = config.model_dump(mode="json")
    raw["scope"] = "REAL_ISAAC_6_0_1"
    raw["configuration_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "configuration_sha256"}
    )
    with pytest.raises(IsaacActiveSessionQueryUnavailable, match="REAL_ISAAC"):
        IsaacActiveSessionQueryProviderV1(
            project_root=ROOT,
            mode="REAL_ISAAC",
            runtime=runtime,
            configuration=IsaacActiveSessionQueryConfigurationV1.model_validate(raw),
        )


def test_readout_digest_and_quaternion_are_fail_closed() -> None:
    provider, runtime = _provider()
    readout = runtime.read_active_session_query_state(
        context_sha256="e" * 64,
        configuration=provider.configuration,
        after_ns=100,
    )
    raw = readout.model_dump(mode="json")
    raw["end_effector_world_wxyz"] = [-1.0, 0.0, 0.0, 0.0]
    raw["state_sha256"] = canonical_non_actuating_state_sha256(
        {
            "joint_positions": raw["joint_positions_rad"],
            "end_effector_world_m": raw["end_effector_world_m"],
            "end_effector_world_wxyz": raw["end_effector_world_wxyz"],
            "gripper_position_m": raw["gripper_position_m"],
        }
    )
    raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="canonical"):
        IsaacActiveSessionRuntimeReadoutV1.model_validate(raw)


def test_no_teacher_or_privileged_truth_enters_query_contract() -> None:
    source = (ROOT / "src/xh_agent/policy/qrm_lite/isaac_active_session_query_v1.py").read_text()
    assert "TeacherResponse" not in source
    assert "task_target_track_id" not in source
    assert '"teacher_used": False' in source
    assert '"privileged_truth_policy_input": False' in source
    assert '"articulation_target_writes": 0' in source
    assert '"simulation_steps": 0' in source
    assert '"scene_mutations": 0' in source
