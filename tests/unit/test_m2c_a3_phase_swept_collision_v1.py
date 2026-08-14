from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3ControlledPandaGeometryReceiptV1,
    A3FileBindingV1,
    A3ReadOnlyFKProviderV1,
    A3RigidTransformV1,
    A3ShapePayloadV1,
    CONTROLLED_PANDA_URDF_PATH,
    CONTROLLED_PANDA_URDF_SHA256,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3ChildPairCCDReceiptV1,
    A3ChildPairCCDResultV1,
    A3ConvexChildV1,
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.a3_phase_swept_collision_evidence_v1 import (
    A3PhaseSweptCollisionEvidenceV1,
)
from xh_agent.policy.qrm_lite.a3_phase_swept_collision_v1 import (
    A3PhaseSweptCollisionProviderV1,
    A3PhaseSweptCollisionUnavailable,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightRejected,
    ExactPlanPreflightV1,
    NonActuatingJointSampleV1,
    NonActuatingPhasePathV1,
    NonActuatingSweptCollisionV1,
    SweptCollisionConfigurationV1,
    canonical_non_actuating_state_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
DIGEST = "a" * 64


def _payload(link: str) -> A3ShapePayloadV1:
    raw = {
        "schema_version": "A3ShapePayloadV1",
        "link_path": link,
        "child_index": 0,
        "shape_kind": "BOX",
        "shape_parameters": (0.01, 0.01, 0.01),
        "decoded_vertices_xyz_m": (),
        "hull_construction_tolerance_m": 1e-7,
        "outward_padding_m": 0.002,
        "collision_margin_m": 0.04,
        "every_decoded_stl_vertex_retained": False,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    return A3ShapePayloadV1(**raw, payload_sha256=canonical_sha256(raw))


def _geometry() -> A3ControlledPandaGeometryReceiptV1:
    identity = A3RigidTransformV1(
        translation_world_m=(0.0, 0.0, 0.0),
        rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    payloads = tuple(_payload(f"/World/Robot/link{index:02d}") for index in range(14))
    children = []
    for payload in payloads:
        child_raw = {
            "schema_version": "A3ConvexChildV1",
            "link_path": payload.link_path,
            "child_index": 0,
            "shape_kind": "BOX",
            "local_transform": identity.model_dump(mode="json"),
            "shape_parameters_sha256": payload.payload_sha256,
            "source_asset_path": "contract.urdf",
            "source_asset_sha256": DIGEST,
            "source_vertex_count": 0,
            "decoded_vertices_sha256": None,
            "smallest_conservative_radius_m": 0.01,
            "maximum_angular_motion_radius_m": 0.02,
            "collision_margin_m": 0.04,
            "outward_padding_m": 0.002,
            "conservative_outer_envelope": True,
            "geometry_equality_claimed": False,
        }
        children.append(
            A3ConvexChildV1(
                **child_raw,
                child_sha256=canonical_sha256(child_raw),
            )
        )
    raw = {
        "schema_version": "A3ControlledPandaGeometryReceiptV1",
        "robot_description": A3FileBindingV1(
            path=CONTROLLED_PANDA_URDF_PATH,
            sha256=CONTROLLED_PANDA_URDF_SHA256,
        ).model_dump(mode="json"),
        "semantic_collision_matrix": A3FileBindingV1(
            path="contract.srdf", sha256=DIGEST
        ).model_dump(mode="json"),
        "mesh_bindings": (),
        "children": [item.model_dump(mode="json") for item in children],
        "shape_payloads": [item.model_dump(mode="json") for item in payloads],
        "acm_link_pairs": (),
        "expected_collision_child_count": 14,
        "all_compounds_expanded": True,
        "unknown_or_concave_shape_rejects": True,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "contract_test_only": True,
        "formal_evidence": False,
    }
    return A3ControlledPandaGeometryReceiptV1(
        **raw,
        receipt_sha256=canonical_sha256(raw),
    )


class _FK(A3ReadOnlyFKProviderV1):
    def __init__(self, path: Path) -> None:
        path.write_text("# query-only FK fixture\n", encoding="utf-8")
        self.implementation_path = str(path)
        self.implementation_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.configuration_sha256 = "b" * 64
        self.real_runtime_provider = False
        self.query_only = True
        self.calls = 0

    def query_link_transforms(self, *, joint_names, joint_state_sequence, link_paths):
        del joint_names
        self.calls += 1
        identity = A3RigidTransformV1(
            translation_world_m=(0.0, 0.0, 0.0),
            rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        )
        return {path: (identity,) * len(joint_state_sequence) for path in link_paths}


class _Backend:
    implementation_sha256 = "c" * 64
    real_native_backend = False

    def __init__(self, *, receipt_backend_sha256: str | None = None) -> None:
        self.calls = 0
        self.receipt_backend_sha256 = receipt_backend_sha256 or self.implementation_sha256

    def query(self, request, *, children, shape_payloads, configuration):
        del children, shape_payloads
        self.calls += 1
        results = tuple(
            A3ChildPairCCDResultV1(
                pair_index=index,
                status="CLEAR",
                discrete_start_clear=True,
                discrete_end_clear=True,
                continuous_query_completed=True,
                iteration_count=min(1, configuration.maximum_ccd_iterations),
            )
            for index in range(len(request.segments))
        )
        raw = {
            "schema_version": "A3ChildPairCCDReceiptV1",
            "request_sha256": request.request_sha256,
            "backend_implementation_sha256": self.receipt_backend_sha256,
            "bullet_collision_library_sha256": "d" * 64,
            "bullet_linear_math_library_sha256": "e" * 64,
            "scalar_abi": "float64",
            "results": [item.model_dump(mode="json") for item in results],
            "status": "PASS",
            "real_native_backend": False,
            "contract_test_only": True,
            "formal_evidence": False,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return A3ChildPairCCDReceiptV1(
            **raw,
            receipt_sha256=canonical_sha256(raw),
        )


def _sample(index: int, first_joint: float) -> NonActuatingJointSampleV1:
    raw = {
        "schema_version": "NonActuatingJointSampleV1",
        "sample_index": index,
        "joint_positions": (first_joint, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        "estimated_abs_efforts": (1.0,) * 7,
        "end_effector_world_m": (0.4 + first_joint, 0.0, 0.4),
        "end_effector_world_wxyz": (1.0, 0.0, 0.0, 0.0),
        "gripper_position_m": 0.04,
        "ik_applicable": True,
        "ik_converged": True,
        "ik_position_residual_m": 0.0,
        "ik_orientation_residual_rad": 0.0,
        "iterations": 1,
    }
    return NonActuatingJointSampleV1(
        **raw,
        state_sha256=canonical_non_actuating_state_sha256(raw),
    )


def _path(
    plan_sha: str,
    phase_sha: str,
    *,
    joint_values: tuple[float, ...] = (0.0, 0.001),
) -> NonActuatingPhasePathV1:
    samples = tuple(_sample(index, value) for index, value in enumerate(joint_values))
    raw = {
        "schema_version": "NonActuatingPhasePathV1",
        "bound_plan_sha256": plan_sha,
        "phase_index": 0,
        "phase_sha256": phase_sha,
        "start_state_sha256": samples[0].state_sha256,
        "terminal_state_sha256": samples[-1].state_sha256,
        "joint_names": tuple(f"panda_joint{index}" for index in range(1, 8)),
        "sample_rate_hz": 60.0,
        "samples": [item.model_dump(mode="json") for item in samples],
        "ik_algorithm_sha256": "1" * 64,
        "ik_configuration_sha256": "2" * 64,
        "joint_limit_configuration_sha256": "3" * 64,
        "gripper_limit_configuration_sha256": "4" * 64,
        "effort_estimator_sha256": "5" * 64,
        "query_duration_ns": 1,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return NonActuatingPhasePathV1(**raw, path_sha256=canonical_sha256(raw))


def _phase_and_plan(
    plan_sha: str,
    phase_sha: str,
    *,
    command: str = "CARTESIAN_POSE",
    steps: int = 1,
):
    wire = SimpleNamespace(
        phase_index=0,
        command=command,
        steps=steps,
        allowed_robot_contact_paths=(),
        allowed_external_contact_paths=(),
    )
    phase = SimpleNamespace(phase=wire, phase_sha256=phase_sha)
    phase.timeout_ns = 10_000_000
    return phase, SimpleNamespace(bound_plan_sha256=plan_sha, phases=(phase,))


def _configuration(provider: A3PhaseSweptCollisionProviderV1):
    raw = {
        "schema_version": "SweptCollisionConfigurationV1",
        "algorithm_id": "A3_BULLET_CHILD_PAIR_CCD_CONTRACT_V1",
        "algorithm_sha256": provider.algorithm_sha256,
        "collision_geometry_sha256": provider.geometry.receipt_sha256,
        "robot_root_path": "/World/Robot",
        "continuous_between_samples": True,
        "subsamples_per_segment": 1,
        "timeout_ns_per_phase": 10_000_000,
        "fail_on_unknown_pair": True,
    }
    collision = SweptCollisionConfigurationV1(
        **raw,
        configuration_sha256=canonical_sha256(raw),
    )
    return SimpleNamespace(swept_collision=collision)


def test_phase_provider_replays_complete_child_pair_product(tmp_path: Path) -> None:
    fk, backend = _FK(tmp_path / "fk.py"), _Backend()
    clock = iter((10, 20))
    provider = A3PhaseSweptCollisionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        geometry=_geometry(),
        fk_provider=fk,
        native_backend=backend,
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
        monotonic_ns=lambda: next(clock),
    )
    plan_sha, phase_sha = "6" * 64, "7" * 64
    phase, plan = _phase_and_plan(plan_sha, phase_sha)
    path = _path(plan_sha, phase_sha)
    configuration = _configuration(provider)

    receipt = provider.query_phase(
        plan,
        phase,
        path,
        configuration=configuration,
    )

    assert fk.calls == backend.calls == 1
    assert receipt.query_duration_ns == 10
    assert len(receipt.segments) == 1
    assert receipt.a3_phase_evidence is not None
    evidence = receipt.a3_phase_evidence
    assert evidence.formal_query_evidence_eligible is False
    assert evidence.child_pair_request.expected_executor_segment_count == 1
    assert evidence.child_pair_request.expected_non_acm_child_pair_count == 91
    assert len(evidence.native_receipt.results) == len(evidence.child_pair_request.segments)

    replay = object.__new__(ExactPlanPreflightV1)
    replay.configuration = configuration
    replay._validate_collision(plan, phase, path, receipt)


def test_contract_evidence_cannot_be_relabelled_formal(tmp_path: Path) -> None:
    provider = A3PhaseSweptCollisionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        geometry=_geometry(),
        fk_provider=_FK(tmp_path / "fk.py"),
        native_backend=_Backend(),
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
        monotonic_ns=iter((1, 2)).__next__,
    )
    phase, plan = _phase_and_plan("6" * 64, "7" * 64)
    receipt = provider.query_phase(
        plan,
        phase,
        _path("6" * 64, "7" * 64),
        configuration=_configuration(provider),
    )
    assert receipt.a3_phase_evidence is not None
    raw = receipt.a3_phase_evidence.model_dump(mode="json")
    raw["formal_query_evidence_eligible"] = True
    raw["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "evidence_sha256"}
    )
    with pytest.raises(ValueError, match="production binding|eligibility"):
        A3PhaseSweptCollisionEvidenceV1.model_validate(raw)


def test_a3_algorithm_rejects_missing_detailed_evidence(tmp_path: Path) -> None:
    provider = A3PhaseSweptCollisionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        geometry=_geometry(),
        fk_provider=_FK(tmp_path / "fk.py"),
        native_backend=_Backend(),
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
    )
    plan_sha, phase_sha = "6" * 64, "7" * 64
    phase, plan = _phase_and_plan(plan_sha, phase_sha)
    path = _path(plan_sha, phase_sha)
    configuration = _configuration(provider)
    payload = {
        "schema_version": "NonActuatingSweptCollisionV1",
        "bound_plan_sha256": plan_sha,
        "phase_index": 0,
        "phase_sha256": phase_sha,
        "path_sha256": path.path_sha256,
        "algorithm_sha256": provider.algorithm_sha256,
        "configuration_sha256": configuration.swept_collision.configuration_sha256,
        "segments": [
            {
                "segment_index": 0,
                "subsamples_checked": 1,
                "complete": True,
                "collision_pairs": (),
            }
        ],
        "a3_phase_evidence": None,
        "query_duration_ns": 1,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    receipt = NonActuatingSweptCollisionV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )
    replay = object.__new__(ExactPlanPreflightV1)
    replay.configuration = configuration
    with pytest.raises(ExactPlanPreflightRejected, match="complete child-pair"):
        replay._validate_collision(plan, phase, path, receipt)


def test_tampered_joint_state_sequence_is_not_replayable(tmp_path: Path) -> None:
    provider = A3PhaseSweptCollisionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        geometry=_geometry(),
        fk_provider=_FK(tmp_path / "fk.py"),
        native_backend=_Backend(),
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
        monotonic_ns=iter((1, 2)).__next__,
    )
    phase, plan = _phase_and_plan("6" * 64, "7" * 64)
    receipt = provider.query_phase(
        plan,
        phase,
        _path("6" * 64, "7" * 64),
        configuration=_configuration(provider),
    )
    assert receipt.a3_phase_evidence is not None
    raw = receipt.a3_phase_evidence.model_dump(mode="json")
    raw["executor_joint_state_sequence"][1][0] = 0.2
    raw["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "evidence_sha256"}
    )
    with pytest.raises(ValueError, match="FK evidence crossed"):
        A3PhaseSweptCollisionEvidenceV1.model_validate(raw)


def test_non_motion_phase_is_empty_and_does_not_query_fk_or_native(tmp_path: Path) -> None:
    fk, backend = _FK(tmp_path / "fk.py"), _Backend()
    provider = A3PhaseSweptCollisionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        geometry=_geometry(),
        fk_provider=fk,
        native_backend=backend,
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
        monotonic_ns=iter((1, 2)).__next__,
    )
    phase, plan = _phase_and_plan(
        "6" * 64,
        "7" * 64,
        command="PUBLIC_RGBD_CAPTURE",
        steps=0,
    )
    receipt = provider.query_phase(
        plan,
        phase,
        _path("6" * 64, "7" * 64, joint_values=(0.0,)),
        configuration=_configuration(provider),
    )
    assert receipt.segments == ()
    assert receipt.a3_phase_evidence is None
    assert fk.calls == backend.calls == 0


def test_native_receipt_must_bind_the_configured_backend(tmp_path: Path) -> None:
    provider = A3PhaseSweptCollisionProviderV1(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        geometry=_geometry(),
        fk_provider=_FK(tmp_path / "fk.py"),
        native_backend=_Backend(receipt_backend_sha256="f" * 64),
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
    )
    phase, plan = _phase_and_plan("6" * 64, "7" * 64)
    with pytest.raises(A3PhaseSweptCollisionUnavailable, match="complete child-pair query"):
        provider.query_phase(
            plan,
            phase,
            _path("6" * 64, "7" * 64),
            configuration=_configuration(provider),
        )
