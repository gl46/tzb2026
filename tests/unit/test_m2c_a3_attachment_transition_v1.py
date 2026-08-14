from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from xh_agent.policy.qrm_lite.a3_attachment_transition_evidence_v1 import (
    A3AttachmentTransitionEvidenceV1,
)
from xh_agent.policy.qrm_lite.a3_attachment_transition_v1 import (
    A3AttachmentTransitionProviderV1,
    A3AttachmentTransitionUnavailable,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    AttachmentPreflightConfigurationV1,
    ControllerCommandShapeV1,
    ExactPlanPreflightRejected,
    ExactPlanPreflightV1,
    NonActuatingAttachmentTransitionV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    "CARTESIAN_POSE": 7,
    "GRIPPER_POSITION": 1,
    "ATTACH_CONTACT_ENTITY": 0,
    "REMOVE_ATTACHMENT": 0,
    "PUBLIC_RGBD_CAPTURE": 0,
    "PUBLIC_TRACK_REASSOCIATION": 0,
}


def _snapshot(plan_sha256: str, *, attached_sha256: str | None = None):
    payload = {
        "schema_version": "PreflightRuntimeSnapshotV1",
        "bound_plan_sha256": plan_sha256,
        "preplan_state_sha256": "1" * 64,
        "observed_at_ns": 100,
        "checked_at_ns": 101,
        "controller_id": "official_franka_dls",
        "controller_configuration_sha256": "2" * 64,
        "controller_ready": True,
        "controller_readiness_query_duration_ns": 1,
        "controller_rate_hz": 60.0,
        "command_shapes": [
            ControllerCommandShapeV1(command=command, dimensions=dimensions).model_dump(mode="json")
            for command, dimensions in COMMANDS.items()
        ],
        "collision_world_ready": True,
        "contact_monitor_ready": True,
        "attachment_monitor_ready": True,
        "terminal_bilateral_contact_broker_ready": True,
        "active_attachment_present": attached_sha256 is not None,
        "active_attachment_sha256": attached_sha256,
        "emergency_stop_active": False,
        "state_stale": False,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return PreflightRuntimeSnapshotV1(
        **payload,
        snapshot_sha256=canonical_sha256(payload),
    )


def _provider(
    snapshot: PreflightRuntimeSnapshotV1,
    *,
    clock=None,
):
    clock = iter((10, 20)).__next__ if clock is None else clock
    return A3AttachmentTransitionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        runtime_snapshot=snapshot,
        runtime_snapshot_provider_implementation_sha256="3" * 64,
        real_runtime_snapshot=False,
        monotonic_ns=clock,
    )


def _configuration(provider: A3AttachmentTransitionProviderV1):
    payload = {
        "schema_version": "AttachmentPreflightConfigurationV1",
        "algorithm_id": "A3_PLANNED_ATTACHMENT_TRANSITION_CONTRACT_V1",
        "algorithm_sha256": provider.algorithm_sha256,
        "contact_monitor_configuration_sha256": "4" * 64,
        "attachment_monitor_configuration_sha256": "5" * 64,
        "timeout_ns_per_phase": 1_000_000,
        "require_unique_bilateral_contact_pair": True,
        "require_terminal_bilateral_contact_selector": True,
        "query_only_required": True,
    }
    attachment = AttachmentPreflightConfigurationV1(
        **payload,
        configuration_sha256=canonical_sha256(payload),
    )
    return SimpleNamespace(attachment=attachment)


def _phase(
    *,
    command: str,
    robot_paths: tuple[str, ...] = (
        "/World/Robot/panda_leftfinger",
        "/World/Robot/panda_rightfinger",
    ),
    external_paths: tuple[str, ...] = ("/World/M1B/blocker/link",),
):
    selector = {
        "ATTACH_CONTACT_ENTITY": ("TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"),
        "REMOVE_ATTACHMENT": "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT",
    }.get(command, "NONE")
    wire = SimpleNamespace(
        phase_index=0,
        command=command,
        allowed_robot_contact_paths=robot_paths,
        allowed_external_contact_paths=external_paths,
    )
    phase = SimpleNamespace(
        phase=wire,
        phase_sha256="7" * 64,
        attachment_or_removal_selector=selector,
        timeout_ns=1_000_000,
    )
    return phase


def _plan_path(plan_sha256: str, phase):
    plan = SimpleNamespace(bound_plan_sha256=plan_sha256, phases=(phase,))
    path = SimpleNamespace(
        bound_plan_sha256=plan_sha256,
        phase_index=0,
        phase_sha256=phase.phase_sha256,
        path_sha256="8" * 64,
    )
    return plan, path


def test_attach_selects_one_replayable_planned_bilateral_pair() -> None:
    plan_sha256 = "6" * 64
    snapshot = _snapshot(plan_sha256)
    provider = _provider(snapshot)
    configuration = _configuration(provider)
    phase = _phase(command="ATTACH_CONTACT_ENTITY")
    plan, path = _plan_path(plan_sha256, phase)

    receipt = provider.query_phase(
        plan,
        phase,
        path,
        expected_attachment_present=False,
        expected_attachment_sha256=None,
        configuration=configuration,
    )

    assert receipt.query_duration_ns == 10
    assert len(receipt.bilateral_contact_pairs) == 1
    assert receipt.attachment_present_after is True
    assert receipt.a3_attachment_evidence is not None
    assert receipt.a3_attachment_evidence.formal_query_evidence_eligible is False
    assert receipt.a3_attachment_evidence.planned_bilateral_pair is not None

    replay = object.__new__(ExactPlanPreflightV1)
    replay.configuration = configuration
    assert replay._validate_attachment_transition(
        plan,
        phase,
        path,
        receipt,
        expected_attachment_present=False,
        expected_attachment_sha256=None,
        runtime_snapshot_sha256=snapshot.snapshot_sha256,
    ) == (True, receipt.attachment_sha256_after)


def test_attachment_allowlist_must_name_one_left_and_one_right_finger() -> None:
    plan_sha256 = "6" * 64
    provider = _provider(_snapshot(plan_sha256))
    phase = _phase(
        command="ATTACH_CONTACT_ENTITY",
        robot_paths=(
            "/World/Robot/panda_leftfinger",
            "/World/Robot/other_leftfinger",
        ),
    )
    plan, path = _plan_path(plan_sha256, phase)
    with pytest.raises(A3AttachmentTransitionUnavailable, match="bilateral broker pair"):
        provider.query_phase(
            plan,
            phase,
            path,
            expected_attachment_present=False,
            expected_attachment_sha256=None,
            configuration=_configuration(provider),
        )


def test_remove_consumes_the_existing_planned_attachment_identity() -> None:
    plan_sha256, existing = "6" * 64, "9" * 64
    snapshot = _snapshot(plan_sha256, attached_sha256=existing)
    provider = _provider(snapshot)
    phase = _phase(command="REMOVE_ATTACHMENT", robot_paths=(), external_paths=())
    plan, path = _plan_path(plan_sha256, phase)
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        expected_attachment_present=True,
        expected_attachment_sha256=existing,
        configuration=_configuration(provider),
    )
    assert receipt.transition == "REMOVE"
    assert receipt.bilateral_contact_pairs == ()
    assert receipt.attachment_present_after is False
    assert receipt.attachment_sha256_after is None


def test_non_transition_phase_preserves_attachment_state() -> None:
    plan_sha256, existing = "6" * 64, "9" * 64
    snapshot = _snapshot(plan_sha256, attached_sha256=existing)
    provider = _provider(snapshot)
    phase = _phase(command="CARTESIAN_POSE", robot_paths=(), external_paths=())
    plan, path = _plan_path(plan_sha256, phase)
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        expected_attachment_present=True,
        expected_attachment_sha256=existing,
        configuration=_configuration(provider),
    )
    assert receipt.transition == "NONE"
    assert receipt.attachment_sha256_after == existing


def test_contract_attachment_evidence_cannot_be_relabelled_formal() -> None:
    plan_sha256 = "6" * 64
    provider = _provider(_snapshot(plan_sha256))
    phase = _phase(command="ATTACH_CONTACT_ENTITY")
    plan, path = _plan_path(plan_sha256, phase)
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        expected_attachment_present=False,
        expected_attachment_sha256=None,
        configuration=_configuration(provider),
    )
    assert receipt.a3_attachment_evidence is not None
    raw = receipt.a3_attachment_evidence.model_dump(mode="json")
    raw["formal_query_evidence_eligible"] = True
    raw["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "evidence_sha256"}
    )
    with pytest.raises(ValueError, match="formal eligibility"):
        A3AttachmentTransitionEvidenceV1.model_validate(raw)


def test_preflight_rejects_attachment_evidence_from_another_runtime_snapshot() -> None:
    plan_sha256 = "6" * 64
    snapshot = _snapshot(plan_sha256)
    provider = _provider(snapshot)
    configuration = _configuration(provider)
    phase = _phase(command="ATTACH_CONTACT_ENTITY")
    plan, path = _plan_path(plan_sha256, phase)
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        expected_attachment_present=False,
        expected_attachment_sha256=None,
        configuration=configuration,
    )
    replay = object.__new__(ExactPlanPreflightV1)
    replay.configuration = configuration
    with pytest.raises(ExactPlanPreflightRejected, match="bound replay evidence"):
        replay._validate_attachment_transition(
            plan,
            phase,
            path,
            receipt,
            expected_attachment_present=False,
            expected_attachment_sha256=None,
            runtime_snapshot_sha256="f" * 64,
        )


def test_high_level_bilateral_pair_cannot_be_spliced_around_replay_evidence() -> None:
    plan_sha256 = "6" * 64
    provider = _provider(_snapshot(plan_sha256))
    phase = _phase(command="ATTACH_CONTACT_ENTITY")
    plan, path = _plan_path(plan_sha256, phase)
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        expected_attachment_present=False,
        expected_attachment_sha256=None,
        configuration=_configuration(provider),
    )
    raw = receipt.model_dump(mode="json")
    raw["bilateral_contact_pairs"][0]["left_robot_path"] += "/tip"
    raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="crossed transition inputs"):
        NonActuatingAttachmentTransitionV1.model_validate(raw)
