from __future__ import annotations

import numpy as np

from xh_agent.policy.qrm_lite.contracts import FailureContextV1, FailureType, QRMObservationV1
from xh_agent.policy.qrm_lite.flow_status import FLOW_SELECTED_FOR_BETA1, FLOW_STATUS
from xh_agent.policy.qrm_lite.metrics_beta1 import RecoveryEvent, same_failed_action_repetition_rate
from xh_agent.policy.qrm_lite.models_q012 import FORMAL_MODEL_TABLE, FormalModelId, build_formal_model
from xh_agent.policy.qrm_lite.recovery_loop import EmptyGraspRecoveryProtocol, RecoveryLoopConfig
from xh_agent.policy.qrm_lite.residual_safety import ResidualSafetyFilter
from xh_agent.policy.qrm_lite.transforms import build_identity_action_chunk


def test_flow_frozen_not_selected():
    assert FLOW_STATUS == "IMPLEMENTED_NOT_SELECTED"
    assert FLOW_SELECTED_FOR_BETA1 is False
    assert "Q0" in str(list(FORMAL_MODEL_TABLE)) or FormalModelId.Q0.value in FORMAL_MODEL_TABLE


def test_q1_strips_failure_context_q2_keeps():
    obs = QRMObservationV1(
        episode_id="e",
        step_id=0,
        instruction="x",
        failure_context=FailureContextV1(failure_type=FailureType.EMPTY_GRASP, retry_count=2),
        joint_position=[0.0] * 8,
        end_effector_pose_base=[0.4, 0, 0.3, 1, 0, 0, 0],
    )
    q1 = build_formal_model(FormalModelId.Q1)
    q2 = build_formal_model(FormalModelId.Q2)
    c1 = q1._encode(obs)
    c2 = q2._encode(obs)
    # With non-NONE failure, encodings must differ because Q1 zeros FailureContext.
    assert c1.shape == c2.shape
    assert not np.allclose(c1, c2)


def test_residual_safety_clips_3cm():
    filt = ResidualSafetyFilter()
    nom = build_identity_action_chunk(4)
    bad = np.zeros_like(nom)
    bad[:, 0] = 0.10  # 10 cm
    res = filt.combine_and_filter(nom, bad)
    assert res.outcome == "residual_clipped"
    assert np.max(np.abs(res.residual_clipped[:, 0])) <= 0.03 + 1e-9


def test_residual_fallback_on_moveit_reject():
    filt = ResidualSafetyFilter()
    nom = build_identity_action_chunk(2)
    residual = np.zeros_like(nom)
    residual[:, 2] = 0.01

    def reject(_final):
        return False, "collision"

    res = filt.combine_and_filter(nom, residual, moveit_accept_fn=reject)
    assert res.outcome == "fallback_to_nominal"
    assert np.allclose(res.final_candidate, nom)


def test_same_failed_action_metric():
    ev = [
        RecoveryEvent("e1", "EMPTY_GRASP", "RETRY_TOP", "RETRY_TOP", "Q1"),
        RecoveryEvent("e2", "EMPTY_GRASP", "RETRY_TOP", "ALTERNATE_SIDE", "Q1"),
    ]
    assert abs(same_failed_action_repetition_rate(ev) - 0.5) < 1e-9


def test_recovery_loop_dry_suite():
    q1 = build_formal_model(FormalModelId.Q1)
    q2 = build_formal_model(FormalModelId.Q2)
    suite = EmptyGraspRecoveryProtocol(q1, q2).run_suite(RecoveryLoopConfig(n_q1=2, n_q2=2))
    assert len(suite["results"]) == 4
    assert "q1_vs_q2" in suite
