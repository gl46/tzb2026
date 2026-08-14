from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from test_m2c_a3_complete_scene_collision_v2 import _scene_state
from test_m2c_a3_phase_swept_collision_v1 import (
    _Backend,
    _FK,
    _geometry,
    _path,
    _phase_and_plan,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_swept_collision_evidence_v2 import (
    A3CompleteScenePhaseSweptCollisionEvidenceV2,
)
from xh_agent.policy.qrm_lite.a3_complete_scene_swept_collision_v2 import (
    CONTRACT_ALGORITHM_ID,
    A3CompleteSceneSweptCollisionProviderV2,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightV1,
    SweptCollisionConfigurationV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
PLAN_SHA = "a" * 64
PHASE_SHA = "e" * 64


def _provider(tmp_path: Path, *, clock=(10, 20)):
    scene_geometry, scene_state = _scene_state(tmp_path)
    backend = _Backend()
    provider = A3CompleteSceneSweptCollisionProviderV2(
        project_root=ROOT,
        mode="CONTRACT_TEST",
        robot_geometry=_geometry(),
        fk_provider=_FK(tmp_path / "fk.py"),
        scene_geometry=scene_geometry,
        scene_state=scene_state,
        real_attached_geometry_resolver=False,
        native_backend=backend,
        numeric_configuration=canonical_a3_bullet_numeric_configuration_v1(),
        monotonic_ns=iter(clock).__next__,
    )
    return provider, backend


def _configuration(provider: A3CompleteSceneSweptCollisionProviderV2):
    raw = {
        "schema_version": "SweptCollisionConfigurationV1",
        "algorithm_id": CONTRACT_ALGORITHM_ID,
        "algorithm_sha256": provider.algorithm_sha256,
        "collision_geometry_sha256": provider.collision_geometry_binding_sha256,
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


def test_complete_scene_phase_provider_replays_robot_self_and_environment(
    tmp_path: Path,
) -> None:
    provider, backend = _provider(tmp_path)
    phase, plan = _phase_and_plan(PLAN_SHA, PHASE_SHA)
    path = _path(PLAN_SHA, PHASE_SHA)
    configuration = _configuration(provider)

    receipt = provider.query_phase(
        plan,
        phase,
        path,
        configuration=configuration,
    )

    assert backend.calls == 1
    assert receipt.query_duration_ns == 10
    assert isinstance(
        receipt.a3_phase_evidence,
        A3CompleteScenePhaseSweptCollisionEvidenceV2,
    )
    evidence = receipt.a3_phase_evidence
    assert evidence.child_pair_request.expected_non_acm_child_pair_count == 203
    assert len(evidence.complete_scene_world.environment_environment_acm_pairs) == 28
    assert evidence.complete_scene_world.complete_robot_environment_coverage is True
    assert evidence.formal_query_evidence_eligible is False

    replay = object.__new__(ExactPlanPreflightV1)
    replay.configuration = configuration
    replay._validate_collision(plan, phase, path, receipt)


def test_complete_scene_contract_evidence_cannot_be_relabelled_formal(
    tmp_path: Path,
) -> None:
    provider, _ = _provider(tmp_path)
    phase, plan = _phase_and_plan(PLAN_SHA, PHASE_SHA)
    receipt = provider.query_phase(
        plan,
        phase,
        _path(PLAN_SHA, PHASE_SHA),
        configuration=_configuration(provider),
    )
    assert receipt.a3_phase_evidence is not None
    raw = receipt.a3_phase_evidence.model_dump(mode="json")
    raw["formal_query_evidence_eligible"] = True
    raw["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "evidence_sha256"}
    )
    with pytest.raises(ValueError, match="formal eligibility|world replay"):
        A3CompleteScenePhaseSweptCollisionEvidenceV2.model_validate(raw)


def test_complete_scene_preflight_rejects_v1_schema_under_v2_algorithm(
    tmp_path: Path,
) -> None:
    provider, _ = _provider(tmp_path)
    phase, plan = _phase_and_plan(PLAN_SHA, PHASE_SHA)
    path = _path(PLAN_SHA, PHASE_SHA)
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        configuration=_configuration(provider),
    )
    raw = receipt.model_dump(mode="json")
    evidence = raw["a3_phase_evidence"]
    evidence["schema_version"] = "A3PhaseSweptCollisionEvidenceV1"
    with pytest.raises(ValueError):
        type(receipt).model_validate(raw)


def test_complete_scene_provider_binds_scene_state_to_exact_plan(tmp_path: Path) -> None:
    provider, _ = _provider(tmp_path)
    phase, plan = _phase_and_plan("f" * 64, PHASE_SHA)
    with pytest.raises(Exception, match="crossed plan"):
        provider.query_phase(
            plan,
            phase,
            _path("f" * 64, PHASE_SHA),
            configuration=_configuration(provider),
        )


def test_complete_scene_provider_rejects_attached_geometry_without_derivation_evidence(
    tmp_path: Path,
) -> None:
    provider, backend = _provider(tmp_path)
    phase, plan = _phase_and_plan(PLAN_SHA, PHASE_SHA)
    with pytest.raises(Exception, match="crossed plan/phase/path/state"):
        provider.query_phase(
            plan,
            phase,
            _path(PLAN_SHA, PHASE_SHA),
            configuration=_configuration(provider),
            attached_objects=(SimpleNamespace(receipt_sha256="a" * 64),),
        )
    assert backend.calls == 0


def test_non_motion_phase_does_not_query_native_backend(tmp_path: Path) -> None:
    provider, backend = _provider(tmp_path)
    phase, plan = _phase_and_plan(
        PLAN_SHA,
        PHASE_SHA,
        command="PUBLIC_RGBD_CAPTURE",
        steps=0,
    )
    path = _path(PLAN_SHA, PHASE_SHA, joint_values=(0.0,))
    receipt = provider.query_phase(
        plan,
        phase,
        path,
        configuration=_configuration(provider),
    )
    assert backend.calls == 0
    assert receipt.a3_phase_evidence is None
    assert receipt.segments == ()
