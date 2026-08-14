from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from test_m2c_formal_public_observation_v4 import _formal
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanSourceBindingV1,
    ExactPlanUnavailable,
)
from xh_agent.policy.qrm_lite.formal_bound_plan_provider_v1 import (
    FormalBoundExactPlanProviderV1,
    FormalPreplanStateReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_synthesis_v1 import (
    ConfiguredFormalExactPlanSynthesisBackendV1,
    FormalExactPlanSynthesisConfigurationV1,
    FormalPlanSynthesisSnapshotV1,
    FormalPlanSynthesisStateV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacExecuteRequestV4,
    RuntimeSkillRequestV4,
    validate_runtime_mapping_v4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    ParameterProvenanceV2,
    RuntimeSkillMappingResultV2,
    load_registry_v2,
)


_ROLES = (
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
)
_ACTIONS = {
    "GRASP": "B0_PUBLIC_GEOMETRY_GRASP",
    "LIFT": "B0_CARTESIAN_LIFT",
    "MOVE": "B0_PUBLIC_GEOMETRY_MOVE",
    "PLACE": "B0_PUBLIC_GEOMETRY_PLACE",
    "RELEASE": "B0_RELEASE",
    "REOBSERVE": "HOLD_AND_CAPTURE_PUBLIC_RGBD",
    "REASSOCIATE_TARGET": "PUBLIC_TRACK_REASSOCIATION",
    "REGRASP": "B0_PUBLIC_GEOMETRY_REGRASP",
}
_EXPECTED_COMMANDS = {
    "GRASP": (
        "CARTESIAN_POSE",
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "GRIPPER_POSITION",
        "GRIPPER_POSITION",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "CARTESIAN_POSE",
        "CARTESIAN_POSE",
    ),
    "REGRASP": (
        "CARTESIAN_POSE",
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "GRIPPER_POSITION",
        "GRIPPER_POSITION",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "CARTESIAN_POSE",
        "CARTESIAN_POSE",
    ),
    "LIFT": ("CARTESIAN_POSE",),
    "MOVE": ("CARTESIAN_POSE",),
    "PLACE": (
        "CARTESIAN_POSE",
        "CARTESIAN_POSE",
        "REMOVE_ATTACHMENT",
        "GRIPPER_POSITION",
        "CARTESIAN_POSE",
    ),
    "RELEASE": (
        "REMOVE_ATTACHMENT",
        "GRIPPER_POSITION",
        "CARTESIAN_POSE",
    ),
    "REOBSERVE": ("PUBLIC_RGBD_CAPTURE",),
    "REASSOCIATE_TARGET": ("PUBLIC_TRACK_REASSOCIATION",),
}


def _bindings(root: Path) -> tuple[ExactPlanSourceBindingV1, ...]:
    result = []
    for index, role in enumerate(_ROLES):
        path = root / f"bound-source-{index}.txt"
        raw = f"{role}\n".encode()
        path.write_bytes(raw)
        result.append(
            ExactPlanSourceBindingV1(
                role=role,  # type: ignore[arg-type]
                path=path.name,
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    return tuple(result)


def _configuration(root: Path) -> FormalExactPlanSynthesisConfigurationV1:
    payload: dict[str, Any] = {
        "schema_version": "FormalExactPlanSynthesisConfigurationV1",
        "revision": "M2C_ADR0024_EXACT_PLAN_SYNTHESIS_V1",
        "immutable_commit": "1" * 40,
        "container_image_digest": "sha256:" + "2" * 64,
        "source_bindings": [item.model_dump(mode="json") for item in _bindings(root)],
        "controller_frequency_hz": 60.0,
        "convergence_tolerance_m": 0.02,
        "phase_timeout_ns": 5_000_000_000,
        "preplan_freshness_limit_ns": 1_000_000,
        "expected_grasp_category_prefix": "industrial_cylinder",
        "pregrasp_height_m": 0.27,
        "grasp_lift_height_m": 0.17,
        "contact_centerline_m": 0.12,
        "preclose_finger_position_m": 0.0205,
        "close_finger_position_m": 0.014,
        "open_finger_position_m": 0.04,
        "default_lift_height_m": 0.05,
        "place_approach_height_m": 0.10,
        "retreat_height_m": 0.05,
        "approach_steps": 150,
        "contact_steps": 120,
        "preclose_steps": 48,
        "preclose_settle_steps": 24,
        "close_steps": 72,
        "contact_observation_steps": 60,
        "lift_steps": 150,
        "transport_steps": 120,
        "place_steps": 90,
        "release_steps": 60,
        "retreat_steps": 90,
        "controlled_robot_links": ["/World/Robot/panda_link0", "/World/Robot/panda_hand"],
        "permitted_robot_contact_paths": [
            "/World/Robot/panda_leftfinger",
            "/World/Robot/panda_rightfinger",
        ],
        "teacher_used": False,
        "evaluator_identity_used": False,
        "task_spec_fallback_used": False,
        "privileged_truth_policy_input": False,
    }
    payload["configuration_sha256"] = canonical_sha256(payload)
    return FormalExactPlanSynthesisConfigurationV1.model_validate(payload)


def _parameters(skill: str, target: str) -> tuple[dict[str, Any], dict[str, ParameterProvenanceV2]]:
    parameters: dict[str, Any] = {}
    provenance: dict[str, ParameterProvenanceV2] = {}
    if skill != "REOBSERVE":
        parameters["target_track_id"] = target
        provenance["target_track_id"] = ParameterProvenanceV2.MODEL
    if skill in {"GRASP", "REGRASP"}:
        parameters["grasp_family"] = "top_down"
        provenance["grasp_family"] = ParameterProvenanceV2.MODEL
    elif skill == "LIFT":
        parameters["lift_height_m"] = 0.05
        provenance["lift_height_m"] = ParameterProvenanceV2.MODEL
    elif skill in {"MOVE", "PLACE"}:
        parameters["destination"] = "BIN_CELL_0"
        provenance["destination"] = ParameterProvenanceV2.MODEL
    elif skill == "RELEASE":
        parameters["open_width_m"] = 0.04
        provenance["open_width_m"] = ParameterProvenanceV2.MODEL
    return parameters, provenance


def _request_and_mapping(skill: str) -> tuple[IsaacExecuteRequestV4, RuntimeSkillMappingResultV2]:
    observation = _formal()
    target = observation.canonical_slots[0]
    assert target is not None
    parameters, provenance = _parameters(skill, target)
    registry = load_registry_v2(Path("configs/qrm_runtime_mapping_v2.yaml"))
    spec = registry.skills[skill]
    target_value = None if skill == "REOBSERVE" else target
    target_slot = None if target_value is None else 0
    runtime = RuntimeSkillRequestV4(
        canonical_public_tracks_sha256=observation.canonical_public_tracks_sha256,
        model_class_id=f"coarse.skill.{skill}",
        skill=skill,
        model_target_track_id=target_value,
        model_target_slot=target_slot,
        target_track_provenance=(
            ParameterProvenanceV2.NONE if target_value is None else ParameterProvenanceV2.MODEL
        ),
        canonical_track_ids=observation.canonical_slots,
        parameters=parameters,
        parameter_provenance=provenance,
        coordinate_frame=spec.coordinate_frame,
        units=spec.units,
        current_phase="RECOVERY",
    )
    request = IsaacExecuteRequestV4(
        run_id="formal-synthesis-run",
        session_id="formal-synthesis-session",
        decision_index=0,
        observation_id=observation.observation_id,
        capture_receipt_sha256=observation.capture_receipt_sha256,
        formal_observation_sha256=observation.wire_sha256,
        canonical_public_tracks_sha256=observation.canonical_public_tracks_sha256,
        inference_response_sha256="a" * 64,
        executed_intent_history=[],
        executed_intent_history_sha256=canonical_sha256([]),
        observation=observation,
        runtime_request=runtime,
    )
    mapping = validate_runtime_mapping_v4(runtime, observation, registry)
    assert mapping.status == "VALID"
    assert mapping.runtime_action == _ACTIONS[skill]
    return request, mapping


class _QuerySource:
    implementation_sha256 = "9" * 64
    real_isaac = False
    mocked_physics = True

    def __init__(
        self, *, attached_public_track_id: str | None, updates: dict[str, Any] | None = None
    ):
        self.attached_public_track_id = attached_public_track_id
        self.updates = updates or {}
        self.receipt_updates: dict[str, Any] = {}
        self.calls = 0

    def query_plan_synthesis_state(self, *, request, observation):  # type: ignore[no-untyped-def]
        self.calls += 1
        payload: dict[str, Any] = {
            "schema_version": "FormalPlanSynthesisStateV1",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "active_session_runtime_receipt_sha256": "6" * 64,
            "scene_safety_binding_receipt_sha256": "7" * 64,
            "scene_geometry_receipt_sha256": "8" * 64,
            "active_attachment_receipt_sha256": (
                "5" * 64 if self.attached_public_track_id is not None else None
            ),
            "end_effector_position_world_m": [0.10, 0.20, 0.65],
            "end_effector_orientation_world_wxyz": [0.0, 1.0, 0.0, 0.0],
            "gripper_position_m": 0.014,
            "attached_public_track_id": self.attached_public_track_id,
            "dynamic_contact_allowlist_paths": [
                "/World/M1B/cylinder_01/link",
            ],
            "environment_collision_paths": [
                "/World/M1B/partition_bin/link",
                "/World/M1B/work_table/link",
            ],
            "state_timestamp_ns": observation.captured_at_ns + 1,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "evaluator_identity_used": False,
            "task_spec_fallback_used": False,
            "privileged_identity_or_pose_used": False,
            "privileged_contact_or_success_truth_used": False,
            "privileged_truth_policy_input": False,
        }
        payload.update(self.updates)
        payload["state_sha256"] = canonical_sha256(payload)
        state = FormalPlanSynthesisStateV1.model_validate(payload)
        receipt_payload: dict[str, Any] = {
            "schema_version": "FormalPreplanStateReceiptV1",
            "run_id": state.run_id,
            "session_id": state.session_id,
            "decision_index": state.decision_index,
            "observation_id": state.observation_id,
            "capture_receipt_sha256": state.capture_receipt_sha256,
            "formal_observation_sha256": state.formal_observation_sha256,
            "state_sha256": state.state_sha256,
            "state_frame": "world",
            "state_dimensions": 8,
            "state_units": "world_m,normalized_wxyz,gripper_m",
            "state_timestamp_ns": state.state_timestamp_ns,
            "freshness_limit_ns": 1_000_000,
            "query_source_implementation_sha256": self.implementation_sha256,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "evaluator_identity_used": False,
            "task_spec_fallback_used": False,
            "privileged_identity_or_pose_used": False,
            "privileged_contact_or_success_truth_used": False,
            "privileged_truth_policy_input": False,
        }
        receipt_payload.update(self.receipt_updates)
        receipt_payload["receipt_sha256"] = canonical_sha256(receipt_payload)
        return FormalPlanSynthesisSnapshotV1(
            state=state,
            receipt=FormalPreplanStateReceiptV1.model_validate(receipt_payload),
        )


def _backend(
    tmp_path: Path,
    *,
    skill: str,
    query_updates: dict[str, Any] | None = None,
) -> tuple[ConfiguredFormalExactPlanSynthesisBackendV1, _QuerySource]:
    request, mapping = _request_and_mapping(skill)
    del mapping
    attached = (
        request.runtime_request.model_target_track_id
        if skill in {"LIFT", "MOVE", "PLACE", "RELEASE"}
        else None
    )
    query = _QuerySource(attached_public_track_id=attached, updates=query_updates)
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 2,
    )
    return backend, query


@pytest.mark.parametrize("skill", tuple(_EXPECTED_COMMANDS))
def test_all_eight_skills_freeze_complete_phase_schema_before_execution(
    tmp_path: Path,
    skill: str,
) -> None:
    request, mapping = _request_and_mapping(skill)
    backend, query = _backend(tmp_path, skill=skill)
    provider = FormalBoundExactPlanProviderV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        backend=backend,
        deployment=None,
    )

    plan = provider.build_bound_plan(
        request=request,
        observation=request.observation,
        mapping=mapping,
    )

    assert (
        tuple(phase.command for phase in plan.exact_execution_plan.phases)
        == (_EXPECTED_COMMANDS[skill])
    )
    assert tuple(phase.phase_index for phase in plan.exact_execution_plan.phases) == tuple(
        range(len(_EXPECTED_COMMANDS[skill]))
    )
    assert all(item.permitted_retry_count == 0 for item in plan.phases)
    assert plan.inputs.teacher_used is False
    assert plan.inputs.privileged_truth_policy_input is False
    assert provider.formal_execution_eligible is False
    assert query.calls == 1


def test_grasp_binds_one_public_yaw_centerline_and_full_contact_window(tmp_path: Path) -> None:
    request, mapping = _request_and_mapping("GRASP")
    backend, _ = _backend(tmp_path, skill="GRASP")

    result = backend.synthesize_bound_plan(
        request=request,
        observation=request.observation,
        mapping=mapping,
    )

    plan = result.bound_plan
    geometry = plan.grasp_geometry
    assert geometry is not None
    assert geometry.selected_yaw_rad == pytest.approx(0.0)
    assert geometry.contact_centerline_m == 0.12
    assert geometry.finger_target_m == 0.014
    assert [phase.phase.steps for phase in plan.phases[2:6]] == [48, 24, 72, 60]
    assert plan.phases[6].attachment_or_removal_selector == (
        "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"
    )


@pytest.mark.parametrize(
    ("skill", "attached"),
    [("LIFT", None), ("GRASP", "track-32bd0e00")],
)
def test_attachment_state_mismatch_fails_before_any_plan(
    tmp_path: Path,
    skill: str,
    attached: str | None,
) -> None:
    request, mapping = _request_and_mapping(skill)
    query = _QuerySource(attached_public_track_id=attached)
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 2,
    )

    with pytest.raises(ExactPlanUnavailable, match="attachment"):
        backend.synthesize_bound_plan(
            request=request,
            observation=request.observation,
            mapping=mapping,
        )
    assert query.calls == 1


def test_non_top_down_regrasp_and_stale_query_fail_closed(tmp_path: Path) -> None:
    request, mapping = _request_and_mapping("REGRASP")
    mapping = mapping.model_copy(
        update={
            "parameters": {**mapping.parameters, "grasp_family": "side"},
            "execution_parameters": {**mapping.execution_parameters, "grasp_family": "side"},
        }
    )
    backend, _ = _backend(tmp_path, skill="REGRASP")
    with pytest.raises(ExactPlanUnavailable, match="non-top-down"):
        backend.synthesize_bound_plan(
            request=request,
            observation=request.observation,
            mapping=mapping,
        )

    stale_backend, _ = _backend(
        tmp_path,
        skill="REGRASP",
        query_updates={"state_timestamp_ns": request.observation.captured_at_ns + 1_000_001},
    )
    _, valid_mapping = _request_and_mapping("REGRASP")
    with pytest.raises(ExactPlanUnavailable, match="stale"):
        stale_backend.synthesize_bound_plan(
            request=request,
            observation=request.observation,
            mapping=valid_mapping,
        )


def test_contract_backend_rejects_real_query_source(tmp_path: Path) -> None:
    query = _QuerySource(attached_public_track_id=None)
    query.real_isaac = True
    with pytest.raises(ExactPlanUnavailable, match="production dependencies"):
        ConfiguredFormalExactPlanSynthesisBackendV1(
            project_root=tmp_path,
            mode="CONTRACT_TEST",
            configuration=_configuration(tmp_path),
            query_source=query,
            deployment=None,
        )


def test_real_backend_requires_reviewed_deployment(tmp_path: Path) -> None:
    query = _QuerySource(attached_public_track_id=None)
    query.real_isaac = True
    query.mocked_physics = False
    with pytest.raises(ExactPlanUnavailable, match="deployment differs"):
        ConfiguredFormalExactPlanSynthesisBackendV1(
            project_root=tmp_path,
            mode="REAL_ISAAC",
            configuration=_configuration(tmp_path),
            query_source=query,
            deployment=None,
        )


def test_query_receipt_must_name_the_called_implementation(tmp_path: Path) -> None:
    request, mapping = _request_and_mapping("GRASP")
    backend, query = _backend(tmp_path, skill="GRASP")
    query.receipt_updates = {"query_source_implementation_sha256": "f" * 64}

    with pytest.raises(ExactPlanUnavailable, match="another implementation"):
        backend.synthesize_bound_plan(
            request=request,
            observation=request.observation,
            mapping=mapping,
        )


def test_configuration_and_state_digests_are_not_self_asserted(tmp_path: Path) -> None:
    config = _configuration(tmp_path).model_dump(mode="json")
    config["contact_centerline_m"] = 0.11
    with pytest.raises(ValueError, match="configuration digest"):
        FormalExactPlanSynthesisConfigurationV1.model_validate(config)

    request, _ = _request_and_mapping("GRASP")
    query = _QuerySource(
        attached_public_track_id=None,
        updates={"formal_observation_sha256": "f" * 64},
    )
    backend = ConfiguredFormalExactPlanSynthesisBackendV1(
        project_root=tmp_path,
        mode="CONTRACT_TEST",
        configuration=_configuration(tmp_path),
        query_source=query,
        deployment=None,
        clock_ns=lambda: request.observation.captured_at_ns + 2,
    )
    _, mapping = _request_and_mapping("GRASP")
    with pytest.raises(ExactPlanUnavailable, match="crosses request/observation"):
        backend.synthesize_bound_plan(
            request=request,
            observation=request.observation,
            mapping=mapping,
        )
