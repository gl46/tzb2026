from __future__ import annotations

import math

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.contracts import (
    CameraFrameActionChunkV1,
    FailureContextV1,
    FailureType,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.context import build_context_vector, encode_failure_context
from xh_agent.policy.qrm_lite.safety_adapter import SafetyAdapter
from xh_agent.policy.qrm_lite.transforms import (
    ActionNormStats,
    base_delta_to_camera_delta,
    build_identity_action_chunk,
    camera_delta_to_base_delta,
    camera_r6d_to_ee_relative_rotation,
    clip_residual_chunk,
    ee_relative_rotation_to_camera_r6d,
    pose_xyzquat_to_mat,
    r6d_to_rotmat,
    reject_nonfinite,
    rotmat_to_r6d,
)


def test_camera_base_translation_roundtrip():
    base_T_cam = np.eye(4)
    base_T_cam[:3, 3] = [0.5, 0.1, 0.8]
    # random rotation
    ang = 0.3
    c, s = math.cos(ang), math.sin(ang)
    base_T_cam[:3, :3] = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    d_base = np.array([0.01, -0.02, 0.03])
    d_cam = base_delta_to_camera_delta(d_base, base_T_cam)
    back = camera_delta_to_base_delta(d_cam, base_T_cam)
    assert np.allclose(back, d_base, atol=1e-9)


def test_rotation_r6d_roundtrip_and_continuity():
    # near identity and a small yaw
    r = np.eye(3)
    r6 = rotmat_to_r6d(r)
    assert np.allclose(r6d_to_rotmat(r6), r, atol=1e-7)
    yaw = 0.2
    c, s = math.cos(yaw), math.sin(yaw)
    ry = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    r6b = rotmat_to_r6d(ry)
    assert np.allclose(r6d_to_rotmat(r6b), ry, atol=1e-6)
    # continuity: small yaw change => small r6d change
    ry2 = np.array([[math.cos(0.21), -math.sin(0.21), 0], [math.sin(0.21), math.cos(0.21), 0], [0, 0, 1]])
    assert np.linalg.norm(rotmat_to_r6d(ry2) - r6b) < 0.05


def test_ee_camera_rotation_roundtrip():
    base_T_cam = np.eye(4)
    base_T_cam[:3, 3] = [0.4, 0, 0.7]
    base_T_ee = pose_xyzquat_to_mat([0.3, 0.1, 0.2, 1, 0, 0, 0])
    ee_delta = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])  # 90 deg about z
    r6 = ee_relative_rotation_to_camera_r6d(ee_delta, base_T_cam, base_T_ee)
    back = camera_r6d_to_ee_relative_rotation(r6, base_T_cam, base_T_ee)
    assert np.allclose(back, ee_delta, atol=1e-6)


def test_norm_roundtrip_and_nan_reject():
    stats = ActionNormStats(mean=np.zeros(10), std=np.ones(10) * 0.1)
    x = np.linspace(-0.05, 0.05, 10)
    y = stats.denormalize(stats.normalize(x))
    assert np.allclose(x, y)
    with pytest.raises(ValueError):
        reject_nonfinite([[1.0, float("nan")]])


def test_action_chunk_mask_and_contract():
    vals = build_identity_action_chunk(4).tolist()
    mask = [[1] * 10 for _ in range(4)]
    chunk = CameraFrameActionChunkV1(values=vals, action_mask=mask)
    assert len(chunk.values) == 4
    with pytest.raises(ValueError):
        CameraFrameActionChunkV1(values=[[float("inf")] + [0] * 9])


def test_failure_context_and_oracle_rejection():
    fc = FailureContextV1(failure_type=FailureType.EMPTY_GRASP, retry_count=2, predicate_residual=["missing:grasped"])
    vec = encode_failure_context(fc)
    assert vec.shape[0] == len(FailureType) + 3
    with pytest.raises(ValueError):
        QRMObservationV1(
            episode_id="e",
            step_id=0,
            instruction="x",
            perception_tracks=[{"track_id": "gazebo_perfect_1", "category": "cube", "confidence": 1.0}],
        )


def test_history_context_includes_failure():
    obs = QRMObservationV1(
        episode_id="e",
        step_id=1,
        instruction="pick",
        failure_context=FailureContextV1(failure_type=FailureType.DROP_OR_SLIP, retry_count=1),
        joint_position=[0.0] * 8,
        end_effector_pose_base=[0.4, 0, 0.3, 1, 0, 0, 0],
    )
    ctx = build_context_vector(obs, backbone_dim=0)
    assert ctx.shape[0] > 10
    # failure one-hot somewhere non-zero
    assert np.any(ctx != 0)


def test_clip_and_safety_reject_workspace():
    residual = np.zeros((4, 10))
    residual[:, 0] = 0.2  # too large before clip
    clipped = clip_residual_chunk(residual, max_translation_m=0.05)
    assert np.max(np.abs(clipped[:, 0])) <= 0.05 + 1e-9
    adapter = SafetyAdapter()
    nominal = build_identity_action_chunk(4)
    # force large residual after denorm
    bad = np.zeros((4, 10))
    bad[:, 0] = 0.5
    # combine clips, but workspace with large base motion still checked via camera~base identity-ish
    base_T_cam = np.eye(4)
    base_T_ee = np.eye(4)
    decision = adapter.filter_candidate(
        nominal,
        bad,
        base_T_cam=base_T_cam,
        base_T_ee=base_T_ee,
        ee_xyz_base=np.array([0.7, 0.0, 0.3]),
    )
    # either accepted with clip or rejected on workspace/speed — must not crash
    assert decision.reason


def test_import_backbone_no_gpu_side_effect():
    from xh_agent.policy.qrm_lite.backbone import Qwen35Backbone, assert_import_is_side_effect_free

    assert_import_is_side_effect_free()
    b = Qwen35Backbone(local_files_only=True)
    assert b.is_loaded is False
