from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from test_m2c_formal_exact_plan_synthesis_v1 import (
    _configuration as _synthesis_configuration,
    _request_and_mapping,
)
from test_m2c_formal_isaac_plan_synthesis_query_v1 import _query
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    ControllerPreflightConfigurationV1,
    ExactPlanPreflightConfigurationV1,
    GripperLimitConfigurationV1,
    IKPreflightConfigurationV1,
    JointLimitConfigurationV1,
    SafetyPreflightConfigurationV1,
    SweptCollisionConfigurationV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_synthesis_v1 import (
    ConfiguredFormalExactPlanSynthesisBackendV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_a3_runtime_snapshot_v1 import (
    FormalIsaacA3RuntimeReadinessReceiptV1,
    FormalIsaacA3RuntimeSnapshotProviderV1,
    FormalIsaacA3RuntimeSnapshotUnavailable,
)
from xh_agent.policy.qrm_lite.formal_isaac_scene_safety_binding_v1 import (
    FormalIsaacActiveAttachmentRegistryV2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.isaac_active_session_query_v1 import (
    CONTROLLED_PANDA_ARM_MAX_EFFORT,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import LULA_JOINT_NAMES


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = "tests/unit/test_m2c_formal_isaac_a3_runtime_snapshot_v1.py"


def _with_digest(model_type: type[Any], **payload: Any) -> Any:
    provisional = model_type.model_construct(**payload, configuration_sha256="0" * 64)
    dumped = provisional.model_dump(mode="json", exclude={"configuration_sha256"})
    return model_type.model_validate({**dumped, "configuration_sha256": canonical_sha256(dumped)})


def _preflight_configuration(active_session) -> ExactPlanPreflightConfigurationV1:
    ik = _with_digest(
        IKPreflightConfigurationV1,
        algorithm_id="LULA_QUERY_ONLY_PHASE_PATH_V1",
        algorithm_sha256="1" * 64,
        robot_description_sha256="2" * 64,
        base_frame="panda_link0",
        end_effector_frame="panda_hand",
        maximum_position_residual_m=0.002,
        maximum_orientation_residual_rad=0.01,
        maximum_iterations_per_sample=64,
        timeout_ns_per_phase=1_000_000,
    )
    limits = _with_digest(
        JointLimitConfigurationV1,
        source_sha256=active_session.joint_limit_source_sha256,
        joint_names=LULA_JOINT_NAMES,
        lower_position=(-3.0,) * 7,
        upper_position=(3.0,) * 7,
        maximum_velocity_per_s=(3.0,) * 7,
        maximum_abs_effort=CONTROLLED_PANDA_ARM_MAX_EFFORT,
        effort_estimator_sha256=active_session.implementation_sha256,
    )
    gripper = _with_digest(
        GripperLimitConfigurationV1,
        source_sha256="3" * 64,
        minimum_position_m=0.0,
        maximum_position_m=0.08,
        maximum_velocity_m_per_s=1.0,
        target_tolerance_m=0.001,
        timeout_ns_per_phase=1_000_000,
    )
    collision = _with_digest(
        SweptCollisionConfigurationV1,
        algorithm_id="A3_BULLET_CHILD_PAIR_CCD_V1",
        algorithm_sha256="4" * 64,
        collision_geometry_sha256="5" * 64,
        robot_root_path="/World/Robot",
        subsamples_per_segment=1,
        timeout_ns_per_phase=1_000_000,
    )
    controller = _with_digest(
        ControllerPreflightConfigurationV1,
        controller_id="official_franka_dls",
        controller_configuration_sha256=(active_session.controller_configuration_sha256),
        readiness_timeout_ns=100,
    )
    safety = _with_digest(
        SafetyPreflightConfigurationV1,
        safety_configuration_sha256="6" * 64,
        workspace_min_world_m=(-2.0, -2.0, 0.0),
        workspace_max_world_m=(2.0, 2.0, 2.0),
        maximum_state_age_ns=1_000_000,
        contact_monitor_configuration_sha256="7" * 64,
        attachment_monitor_configuration_sha256="8" * 64,
    )
    attachment = _with_digest(
        AttachmentPreflightConfigurationV1,
        algorithm_id="A3_PLANNED_ATTACHMENT_TRANSITION_V1",
        algorithm_sha256="9" * 64,
        contact_monitor_configuration_sha256=(safety.contact_monitor_configuration_sha256),
        attachment_monitor_configuration_sha256=(safety.attachment_monitor_configuration_sha256),
        timeout_ns_per_phase=1_000_000,
    )
    return _with_digest(
        ExactPlanPreflightConfigurationV1,
        ik=ik,
        joint_limits=limits,
        gripper_limits=gripper,
        swept_collision=collision,
        controller=controller,
        safety=safety,
        attachment=attachment,
        callback_implementation_sha256="a" * 64,
        total_timeout_ns=10_000_000,
    )


class _Journal:
    def append(self, event_type: str, payload: dict[str, object]) -> None:
        del event_type, payload


class _ReadinessSource:
    implementation_path = SOURCE_PATH
    real_isaac = False
    mocked_runtime = True

    def __init__(
        self,
        counters,
        attachment_source,
        *,
        mutate: bool = False,
        updates: dict[str, Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.implementation_sha256 = hashlib.sha256(
            (ROOT / self.implementation_path).read_bytes()
        ).hexdigest()
        self.mutation_counter_source = counters
        self.active_attachment_source = attachment_source
        self.mutate = mutate
        self.updates = updates or {}
        self.fail = fail
        self.calls = 0

    def query_runtime_readiness(self, *, plan, configuration, after_ns):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("readiness unavailable")
        before = self.mutation_counter_source.snapshot_mutation_counters()
        started_at_ns = after_ns + 1
        checked_at_ns = started_at_ns + 10
        if self.mutate:
            self.mutation_counter_source.writes += 1
        after = self.mutation_counter_source.snapshot_mutation_counters()
        active = self.active_attachment_source.snapshot_active_attachment()
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacA3RuntimeReadinessReceiptV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "preplan_state_sha256": plan.inputs.preplan_state_sha256,
            "preplan_state_timestamp_ns": plan.inputs.preplan_state_timestamp_ns,
            "preflight_configuration_sha256": configuration.configuration_sha256,
            "source_implementation_path": self.implementation_path,
            "source_implementation_sha256": self.implementation_sha256,
            "query_started_at_ns": started_at_ns,
            "checked_at_ns": checked_at_ns,
            "controller_id": configuration.controller.controller_id,
            "controller_configuration_sha256": (
                configuration.controller.controller_configuration_sha256
            ),
            "controller_ready": True,
            "controller_readiness_query_duration_ns": 10,
            "controller_rate_hz": configuration.controller.required_rate_hz,
            "collision_world_ready": True,
            "contact_monitor_ready": True,
            "attachment_monitor_ready": True,
            "terminal_bilateral_contact_broker_ready": True,
            "emergency_stop_active": False,
            "active_attachment_receipt_sha256": (
                active.receipt_sha256 if active is not None else None
            ),
            "mutation_counters_before": before,
            "mutation_counters_after": after,
            "real_isaac": False,
            "mocked_runtime": True,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "controller_commands": 0,
            "attachment_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        payload.update(self.updates)
        return FormalIsaacA3RuntimeReadinessReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )


def _plan_and_active_session(tmp_path: Path):  # type: ignore[no-untyped-def]
    request, mapping = _request_and_mapping("GRASP")
    query, _ = _query()
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_synthesis_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 4,
    )
    result = backend.synthesize_bound_plan(
        request=request,
        observation=request.observation,
        mapping=mapping,
    )
    active_session = query.claim_active_session_query_provider(result.bound_plan)
    return result.bound_plan, active_session


def _snapshot_provider(
    tmp_path: Path,
    *,
    mutate: bool = False,
    updates: dict[str, Any] | None = None,
    fail: bool = False,
):  # type: ignore[no-untyped-def]
    plan, active_session = _plan_and_active_session(tmp_path)
    attachment = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=_Journal(),
    )
    source = _ReadinessSource(
        active_session.mutation_counter_source,
        attachment,
        mutate=mutate,
        updates=updates,
        fail=fail,
    )
    configuration = _preflight_configuration(active_session)
    provider = FormalIsaacA3RuntimeSnapshotProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        active_session_provider=active_session,
        readiness_source=source,
        configuration=configuration,
    )
    return plan, active_session, source, configuration, provider


def test_snapshot_binds_exact_physical_state_without_consuming_phase_state(
    tmp_path: Path,
) -> None:
    plan, active_session, source, configuration, provider = _snapshot_provider(tmp_path)

    snapshot = provider.build_snapshot(plan)
    phase_state = active_session.read_active_state(plan)

    assert source.calls == 1
    assert snapshot.bound_plan_sha256 == plan.bound_plan_sha256
    assert snapshot.preplan_state_sha256 == plan.inputs.preplan_state_sha256
    assert snapshot.observed_at_ns == plan.inputs.preplan_state_timestamp_ns
    assert snapshot.controller_id == configuration.controller.controller_id
    assert snapshot.controller_ready is True
    assert snapshot.state_stale is False
    assert phase_state.state_sha256 == snapshot.preplan_state_sha256
    assert provider.readiness_receipt.source_implementation_sha256 == (source.implementation_sha256)
    assert provider.formal_query_evidence_eligible is False
    with pytest.raises(FormalIsaacA3RuntimeSnapshotUnavailable, match="single-use"):
        provider.build_snapshot(plan)


def test_snapshot_failure_is_consumed_but_does_not_consume_phase_state(
    tmp_path: Path,
) -> None:
    plan, active_session, source, _, provider = _snapshot_provider(tmp_path, fail=True)

    with pytest.raises(RuntimeError, match="readiness unavailable"):
        provider.build_snapshot(plan)
    with pytest.raises(FormalIsaacA3RuntimeSnapshotUnavailable, match="single-use"):
        provider.build_snapshot(plan)
    assert source.calls == 1
    assert active_session.read_active_state(plan).state_sha256 == (plan.inputs.preplan_state_sha256)


def test_snapshot_rejects_mutation_during_readiness_query(tmp_path: Path) -> None:
    plan, _, _, _, provider = _snapshot_provider(tmp_path, mutate=True)

    with pytest.raises(ValueError, match="mutated"):
        provider.build_snapshot(plan)


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        ({"bound_plan_sha256": "f" * 64}, "crossed"),
        ({"source_implementation_sha256": "f" * 64}, "crossed"),
        ({"controller_configuration_sha256": "f" * 64}, "crossed"),
        ({"active_attachment_receipt_sha256": "f" * 64}, "crossed"),
        ({"query_started_at_ns": 1, "checked_at_ns": 11}, "crossed"),
    ),
)
def test_snapshot_rejects_crossed_readiness_fields(
    tmp_path: Path,
    updates: dict[str, Any],
    message: str,
) -> None:
    plan, _, _, _, provider = _snapshot_provider(tmp_path, updates=updates)

    with pytest.raises(FormalIsaacA3RuntimeSnapshotUnavailable, match=message):
        provider.build_snapshot(plan)


def test_state_staleness_is_derived_not_source_asserted(tmp_path: Path) -> None:
    plan, _, _, configuration, provider = _snapshot_provider(
        tmp_path,
        updates={
            "query_started_at_ns": 2_000_000,
            "checked_at_ns": 2_000_010,
        },
    )

    snapshot = provider.build_snapshot(plan)

    assert configuration.safety.maximum_state_age_ns == 1_000_000
    assert snapshot.state_stale is True


def test_constructor_rejects_crossed_readiness_source_bytes(tmp_path: Path) -> None:
    plan, active_session = _plan_and_active_session(tmp_path)
    del plan
    attachment = FormalIsaacActiveAttachmentRegistryV2(
        mode="CONTRACT_TEST",
        journal=_Journal(),
    )
    source = _ReadinessSource(active_session.mutation_counter_source, attachment)
    source.implementation_sha256 = "f" * 64

    with pytest.raises(FormalIsaacA3RuntimeSnapshotUnavailable, match="cross"):
        FormalIsaacA3RuntimeSnapshotProviderV1(
            project_root=ROOT,
            mode="CONTRACT_TEST",
            active_session_provider=active_session,
            readiness_source=source,
            configuration=_preflight_configuration(active_session),
        )
