from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

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
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.isaac_lula_non_actuating_callbacks_v1 import (
    ISAAC_6_0_1_IMAGE_DIGEST,
    IsaacClosureFileV1,
    IsaacLulaNonActuatingCallbacksV1,
    IsaacLulaQueryClosureManifestV1,
    IsaacQueryCapabilityUnavailable,
    IsaacQueryCapabilityV1,
    IsaacQueryMutationDetected,
    NonActuatingMutationCountersV1,
    audit_isaac_lula_query_closure_v1,
    canonical_isaac_6_0_1_blocked_manifest,
    run_non_actuating_backend_query_v1,
)


def _with_digest(cls: Any, **payload: Any):
    provisional = cls.model_construct(**payload, configuration_sha256="0" * 64)
    dumped = provisional.model_dump(mode="json")
    dumped["configuration_sha256"] = canonical_sha256(
        provisional.model_dump(mode="json", exclude={"configuration_sha256"})
    )
    return cls.model_validate(dumped)


def _adapter_sha256() -> str:
    source = (
        Path(__file__).parents[2]
        / "src/xh_agent/policy/qrm_lite/isaac_lula_non_actuating_callbacks_v1.py"
    )
    return hashlib.sha256(source.read_bytes()).hexdigest()


def _configuration(robot_description_sha256: str) -> ExactPlanPreflightConfigurationV1:
    ik = _with_digest(
        IKPreflightConfigurationV1,
        algorithm_id="ISAAC_LULA_QUERY_IK_V1",
        algorithm_sha256="1" * 64,
        robot_description_sha256=robot_description_sha256,
        base_frame="world",
        end_effector_frame="panda_hand",
        maximum_position_residual_m=0.002,
        maximum_orientation_residual_rad=0.01,
        maximum_iterations_per_sample=64,
        timeout_ns_per_phase=1_000_000,
    )
    joints = _with_digest(
        JointLimitConfigurationV1,
        source_sha256="2" * 64,
        joint_names=("joint_a", "joint_b"),
        lower_position=(-2.0, -2.0),
        upper_position=(2.0, 2.0),
        maximum_velocity_per_s=(2.0, 2.0),
        maximum_abs_effort=(10.0, 10.0),
        effort_estimator_sha256="3" * 64,
    )
    gripper = _with_digest(
        GripperLimitConfigurationV1,
        source_sha256="4" * 64,
        minimum_position_m=0.0,
        maximum_position_m=0.08,
        maximum_velocity_m_per_s=1.0,
        target_tolerance_m=0.001,
        timeout_ns_per_phase=1_000_000,
    )
    collision = _with_digest(
        SweptCollisionConfigurationV1,
        algorithm_id="ISAAC_SWEPT_QUERY_V1",
        algorithm_sha256="5" * 64,
        collision_geometry_sha256="6" * 64,
        robot_root_path="/World/Robot",
        subsamples_per_segment=4,
        timeout_ns_per_phase=1_000_000,
    )
    controller = _with_digest(
        ControllerPreflightConfigurationV1,
        controller_id="official_franka_dls",
        controller_configuration_sha256="7" * 64,
        readiness_timeout_ns=1_000_000,
    )
    safety = _with_digest(
        SafetyPreflightConfigurationV1,
        safety_configuration_sha256="8" * 64,
        workspace_min_world_m=(-1.0, -1.0, 0.0),
        workspace_max_world_m=(1.0, 1.0, 1.0),
        maximum_state_age_ns=100,
        contact_monitor_configuration_sha256="9" * 64,
        attachment_monitor_configuration_sha256="a" * 64,
    )
    attachment = _with_digest(
        AttachmentPreflightConfigurationV1,
        algorithm_id="ISAAC_ATTACHMENT_QUERY_V1",
        algorithm_sha256="b" * 64,
        contact_monitor_configuration_sha256=(safety.contact_monitor_configuration_sha256),
        attachment_monitor_configuration_sha256=(safety.attachment_monitor_configuration_sha256),
        timeout_ns_per_phase=1_000_000,
    )
    return _with_digest(
        ExactPlanPreflightConfigurationV1,
        ik=ik,
        joint_limits=joints,
        gripper_limits=gripper,
        swept_collision=collision,
        controller=controller,
        safety=safety,
        attachment=attachment,
        callback_implementation_sha256=_adapter_sha256(),
        total_timeout_ns=10_000_000,
    )


def _capabilities() -> tuple[IsaacQueryCapabilityV1, ...]:
    return tuple(
        IsaacQueryCapabilityV1(capability=name, status="NOT_AVAILABLE", reason="not proven")
        for name in (
            "IK_FK_PATH_SAMPLING",
            "SWEPT_COLLISION",
            "ATTACHMENT_CONTACT_TRANSITION",
            "ACTIVE_SESSION_RUNTIME_SNAPSHOT",
        )
    )


def _manifest(
    *,
    config: ExactPlanPreflightConfigurationV1,
    closure_file: IsaacClosureFileV1,
) -> IsaacLulaQueryClosureManifestV1:
    payload = {
        "schema_version": "IsaacLulaQueryClosureManifestV1",
        "scope": "CONTRACT_FIXTURE",
        "container_image_digest": ISAAC_6_0_1_IMAGE_DIGEST,
        "isaac_runtime_version": "6.0.1",
        "expected_preflight_configuration_sha256": config.configuration_sha256,
        "files": [closure_file.model_dump(mode="json")],
        "capabilities": [item.model_dump(mode="json") for item in _capabilities()],
        "reviewed_binding_addendum_sha256": None,
        "teacher_allowed": False,
        "privileged_truth_policy_input_allowed": False,
    }
    return IsaacLulaQueryClosureManifestV1(
        **payload,
        manifest_sha256=canonical_sha256(payload),
    )


def _fixture_closure(tmp_path: Path):
    image_root = tmp_path / "isaac-sim"
    asset = image_root / "assets/franka.urdf"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"fixture robot description\n")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    config = _configuration(digest)
    closure_file = IsaacClosureFileV1(
        role="LULA_ROBOT_DESCRIPTION",
        relative_path="assets/franka.urdf",
        sha256=digest,
        size_bytes=asset.stat().st_size,
    )
    return image_root, asset, config, _manifest(config=config, closure_file=closure_file)


def test_canonical_isaac_image_audit_is_explicitly_not_available() -> None:
    config = _configuration("e9024642e7952cbcaec0ae14425bf1cd19d674d3c98eeef3793913f63a8101b6")
    manifest = canonical_isaac_6_0_1_blocked_manifest(configuration=config)

    assert manifest.container_image_digest == ISAAC_6_0_1_IMAGE_DIGEST
    assert {item.status for item in manifest.capabilities} == {"NOT_AVAILABLE"}
    assert "No public API" in next(
        item.reason for item in manifest.capabilities if item.capability == "SWEPT_COLLISION"
    )
    assert manifest.reviewed_binding_addendum_sha256 is None


def test_read_only_closure_audit_binds_bytes_but_does_not_unlock(tmp_path: Path) -> None:
    image_root, _asset, config, manifest = _fixture_closure(tmp_path)

    receipt = audit_isaac_lula_query_closure_v1(
        image_root=image_root,
        manifest=manifest,
        configuration=config,
    )

    assert receipt.production_callback_available is False
    assert len(receipt.blockers) == 4
    assert receipt.scene_started is False
    assert receipt.simulation_steps == 0
    assert receipt.articulation_target_writes == 0
    with pytest.raises(IsaacQueryCapabilityUnavailable, match="NOT_AVAILABLE"):
        IsaacLulaNonActuatingCallbacksV1(audit_receipt=receipt, backend=_Backend())


def test_closure_hash_drift_fails_closed(tmp_path: Path) -> None:
    image_root, asset, config, manifest = _fixture_closure(tmp_path)
    asset.write_bytes(b"tampered\n")

    with pytest.raises(IsaacQueryCapabilityUnavailable, match="hash/size mismatch"):
        audit_isaac_lula_query_closure_v1(
            image_root=image_root,
            manifest=manifest,
            configuration=config,
        )


def test_closure_symlink_fails_closed(tmp_path: Path) -> None:
    image_root, asset, config, manifest = _fixture_closure(tmp_path)
    original = tmp_path / "original"
    asset.replace(original)
    asset.symlink_to(original)

    with pytest.raises(OSError):
        audit_isaac_lula_query_closure_v1(
            image_root=image_root,
            manifest=manifest,
            configuration=config,
        )


def test_robot_description_cross_binding_fails_before_closure_use(tmp_path: Path) -> None:
    image_root, _asset, _config, manifest = _fixture_closure(tmp_path)
    wrong_config = _configuration("f" * 64)
    dumped = manifest.model_dump(mode="json")
    dumped["expected_preflight_configuration_sha256"] = wrong_config.configuration_sha256
    dumped["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in dumped.items() if key != "manifest_sha256"}
    )
    crossed = IsaacLulaQueryClosureManifestV1.model_validate(dumped)

    with pytest.raises(IsaacQueryCapabilityUnavailable, match="robot description differs"):
        audit_isaac_lula_query_closure_v1(
            image_root=image_root,
            manifest=crossed,
            configuration=wrong_config,
        )


class _Backend:
    implementation_sha256 = "c" * 64

    def __init__(self) -> None:
        self.counters = NonActuatingMutationCountersV1(
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            attachment_mutations=0,
            capture_operations=0,
        )

    def read_mutation_counters(self) -> NonActuatingMutationCountersV1:
        return self.counters


def test_contract_query_guard_accepts_only_unchanged_counters() -> None:
    backend = _Backend()

    assert run_non_actuating_backend_query_v1(backend, lambda: "query result") == ("query result")


def test_contract_query_guard_rejects_any_mutation() -> None:
    backend = _Backend()

    def mutate() -> str:
        backend.counters = backend.counters.model_copy(update={"simulation_steps": 1})
        return "invalid result"

    with pytest.raises(IsaacQueryMutationDetected, match="changed mutation counters"):
        run_non_actuating_backend_query_v1(backend, mutate)


def test_contract_query_guard_checks_counters_even_when_query_raises() -> None:
    backend = _Backend()

    def mutate_then_fail() -> None:
        backend.counters = backend.counters.model_copy(update={"scene_mutations": 1})
        raise RuntimeError("query failed")

    with pytest.raises(IsaacQueryMutationDetected, match="failed query changed"):
        run_non_actuating_backend_query_v1(backend, mutate_then_fail)
