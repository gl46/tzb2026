from __future__ import annotations

from pathlib import Path

from xh_agent.policy.qrm_lite.contracts import (
    CoarseIntentV1,
    FailureContextV1,
    FailureType,
    PerceptionTrackV1,
    QRMObservationV1,
)
from xh_agent.policy.qrm_lite.models_q012 import (
    FormalModelId,
    ModelOutput,
)
from xh_agent.policy.qrm_lite.runtime_adapter import (
    build_runtime_skill_request,
    normalize_runtime_phase,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    load_registry,
    validate_runtime_mapping,
)


ROOT = Path(__file__).parents[2]


def observation(failure: FailureType = FailureType.NONE) -> QRMObservationV1:
    return QRMObservationV1(
        episode_id="episode",
        step_id=1,
        instruction="pick the public target",
        task_target_track_id="track-target",
        camera_frame="policy_rgbd_optical",
        camera_intrinsics=[1.0] * 9,
        current_skill_stage=("RECOVERY" if failure != FailureType.NONE else "APPROACH"),
        perception_tracks=[
            PerceptionTrackV1(
                track_id="track-target",
                confidence=0.9,
                pose_xyzquat=[0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0],
            )
        ],
        failure_context=FailureContextV1(failure_type=failure),
    )


def test_adapter_materializes_registered_protocol_and_public_track() -> None:
    registry = load_registry(ROOT / "configs/qrm_runtime_mapping.yaml")
    output = ModelOutput(
        model_id=FormalModelId.Q0,
        coarse=CoarseIntentV1(
            skill_type="GRASP",
            grasp_family="top_down",
        ),
    )
    request = build_runtime_skill_request(observation(), output, registry)
    assert request.model_class_id == "coarse.skill.GRASP"
    assert request.coordinate_frame == "world"
    assert request.units == "m_rad"
    assert request.parameters == {"grasp_family": "top_down"}
    assert validate_runtime_mapping(request, registry).status == "VALID"


def test_adapter_selects_declared_recovery_head_only_when_failure_active() -> None:
    registry = load_registry(ROOT / "configs/qrm_runtime_mapping.yaml")
    output = ModelOutput(
        model_id=FormalModelId.Q2,
        coarse=CoarseIntentV1(
            skill_type="GRASP",
            grasp_family="side",
        ),
        recovery_skill="ALTERNATE_SIDE",
        used_failure_context=True,
    )
    request = build_runtime_skill_request(
        observation(FailureType.EMPTY_GRASP), output, registry
    )
    assert request.skill == "ALTERNATE_SIDE"
    assert request.model_class_id == "coarse.recovery.ALTERNATE_SIDE"
    result = validate_runtime_mapping(request, registry)
    assert result.status == "VALID"
    assert result.canonical_skill == "REGRASP"
    assert result.parameters["grasp_family"] == "side"


def test_only_declared_recovery_stages_normalize_to_recovery_phase() -> None:
    assert normalize_runtime_phase("RECOVERY_DECISION") == "RECOVERY"
    assert normalize_runtime_phase("REOBSERVE") == "RECOVERY"
    assert normalize_runtime_phase("ALTERNATE_OBLIQUE") == "RECOVERY"
    assert normalize_runtime_phase("APPROACH") == "APPROACH"
    assert normalize_runtime_phase("unexpected") == "UNEXPECTED"
