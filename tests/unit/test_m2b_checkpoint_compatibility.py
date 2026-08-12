from __future__ import annotations

import numpy as np
import pytest

from xh_agent.policy.qrm_lite.contracts import QRMObservationV1
from xh_agent.policy.qrm_lite.models_q012 import (
    FormalModelId,
    build_formal_model,
    load_formal_checkpoint,
)


TENSOR_NAMES = (
    "coarse_w1",
    "coarse_b1",
    "coarse_w2",
    "coarse_b2",
    "mlp_w1",
    "mlp_b1",
    "mlp_w2",
    "mlp_b2",
)


def _legacy_payload() -> dict[str, object]:
    return {
        "model_id": "Q2_COARSE_MLP_FAILURE_CONTEXT",
        "coarse_w1": np.zeros((110, 256)),
        "coarse_b1": np.zeros(256),
        "coarse_w2": np.zeros((256, 70)),
        "coarse_b2": np.zeros(70),
        "mlp_w1": np.zeros((150, 512)),
        "mlp_b1": np.zeros(512),
        "mlp_w2": np.zeros((512, 40)),
        "mlp_b2": np.zeros(40),
    }


def _m2b_payload() -> dict[str, object]:
    model = build_formal_model(FormalModelId.Q2)
    return {
        "checkpoint_schema_version": "QRMFormalCheckpointV1",
        "architecture_revision": "M2B_Q012_V1",
        "model_id": model.model_id.value,
        "coarse_w1": model.coarse.w1,
        "coarse_b1": model.coarse.b1,
        "coarse_w2": model.coarse.w2,
        "coarse_b2": model.coarse.b2,
        "mlp_w1": model.mlp.w1,
        "mlp_b1": model.mlp.b1,
        "mlp_w2": model.mlp.w2,
        "mlp_b2": model.mlp.b2,
    }


def test_frozen_m2a_q2_checkpoint_loads_with_named_legacy_revision(
    tmp_path,
) -> None:
    checkpoint = tmp_path / "Q2-legacy.npz"
    np.savez(checkpoint, **_legacy_payload())
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


def test_m2b_checkpoint_loads_only_with_matching_revision_metadata(
    tmp_path,
) -> None:
    checkpoint = tmp_path / "Q2-m2b.npz"
    np.savez(checkpoint, **_m2b_payload())
    model = load_formal_checkpoint(
        str(checkpoint),
        expected_model_id="Q2_COARSE_MLP_FAILURE_CONTEXT",
    )
    assert model.meta_checkpoint_revision == "M2B_Q012_V1"
    assert model.context_dim == 113
    assert model.coarse.out_dim == 73

    missing_metadata = _m2b_payload()
    missing_metadata.pop("architecture_revision")
    np.savez(checkpoint, **missing_metadata)
    with pytest.raises(ValueError, match="requires schema and architecture"):
        load_formal_checkpoint(str(checkpoint))

    wrong_revision = _m2b_payload()
    wrong_revision["architecture_revision"] = "M2A_BETA1_LEGACY_V1"
    np.savez(checkpoint, **wrong_revision)
    with pytest.raises(ValueError, match="revision/layout mismatch"):
        load_formal_checkpoint(str(checkpoint))


@pytest.mark.parametrize("tensor_name", TENSOR_NAMES)
def test_v1_checkpoint_rejects_every_tensor_shape_mismatch(
    tmp_path,
    tensor_name: str,
) -> None:
    payload = _m2b_payload()
    value = np.asarray(payload[tensor_name])
    payload[tensor_name] = np.zeros(value.shape + (1,))
    checkpoint = tmp_path / f"bad-{tensor_name}.npz"
    np.savez(checkpoint, **payload)
    with pytest.raises(ValueError, match="tensor layout"):
        load_formal_checkpoint(str(checkpoint))


def test_v1_checkpoint_rejects_nonfinite_or_unknown_contents(tmp_path) -> None:
    checkpoint = tmp_path / "bad-contents.npz"
    nonfinite = _m2b_payload()
    nonfinite["pointer"] = np.zeros(1)
    np.savez(checkpoint, **nonfinite)
    with pytest.raises(ValueError, match="unsupported fields"):
        load_formal_checkpoint(str(checkpoint))

    nonfinite = _m2b_payload()
    coarse_b1 = np.asarray(nonfinite["coarse_b1"]).copy()
    coarse_b1[0] = np.nan
    nonfinite["coarse_b1"] = coarse_b1
    np.savez(checkpoint, **nonfinite)
    with pytest.raises(ValueError, match="non-finite"):
        load_formal_checkpoint(str(checkpoint))


def test_v1_checkpoint_rejects_cross_revision_tensor_mix(tmp_path) -> None:
    payload = _m2b_payload()
    legacy = _legacy_payload()
    payload["coarse_w1"] = legacy["coarse_w1"]
    payload["coarse_w2"] = legacy["coarse_w2"]
    payload["coarse_b2"] = legacy["coarse_b2"]
    payload["mlp_w1"] = legacy["mlp_w1"]
    checkpoint = tmp_path / "mixed-layout.npz"
    np.savez(checkpoint, **payload)
    with pytest.raises(ValueError, match="revision/layout mismatch"):
        load_formal_checkpoint(str(checkpoint))
