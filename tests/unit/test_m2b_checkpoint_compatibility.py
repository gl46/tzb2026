from __future__ import annotations

import numpy as np

from xh_agent.policy.qrm_lite.contracts import QRMObservationV1
from xh_agent.policy.qrm_lite.models_q012 import load_formal_checkpoint


def test_frozen_m2a_q2_checkpoint_loads_with_named_legacy_revision(
    tmp_path,
) -> None:
    checkpoint = tmp_path / "Q2-legacy.npz"
    np.savez(
        checkpoint,
        model_id="Q2_COARSE_MLP_FAILURE_CONTEXT",
        coarse_w1=np.zeros((110, 256)),
        coarse_b1=np.zeros(256),
        coarse_w2=np.zeros((256, 70)),
        coarse_b2=np.zeros(70),
        mlp_w1=np.zeros((150, 512)),
        mlp_b1=np.zeros(512),
        mlp_w2=np.zeros((512, 40)),
        mlp_b2=np.zeros(40),
    )
    model = load_formal_checkpoint(str(checkpoint))
    observation = QRMObservationV1(
        episode_id="legacy-test",
        step_id=0,
        instruction="observe",
        camera_frame="camera_optical",
        camera_intrinsics=[1.0] * 9,
    )
    output = model.predict(
        observation,
        nominal=np.zeros((4, 10)),
        moveit_accept_fn=lambda _chunk: (False, "test-only"),
    )
    assert model.meta_checkpoint_revision == "M2A_BETA1_LEGACY_V1"
    assert model.context_dim == 110
    assert model.coarse.out_dim == 70
    assert output.coarse is not None
