from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from test_m2c_formal_isaac_endpoint_v4 import _binding, _observations
from test_m2c_formal_isaac_episode_io_v4 import _execution_responses
from test_m2c_formal_public_observation_v4 import _depth, _rgb
from test_m2c_path_blocked_supervision_v4 import (
    attribute_binding,
    capture,
    deployment,
    detection,
    proprio,
)
from xh_agent.perception.public_track_associator_v2 import (
    LastPhysicallyExecutedPublicSkillV2,
    PublicAssociationCaptureV2,
    PublicProprioceptionIntervalV2,
)
from xh_agent.policy.qrm_lite.formal_isaac_scene_owner_v4 import (
    FormalIsaacPersistentSceneOwnerCoreV4,
    FormalIsaacRawPublicFrameV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    public_asset_inline_v4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacFinalizeRequestV4,
    IsaacStartRequestV4,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA256 = "1" * 64
OWNER_SHA256 = "9" * 64


def _association_deployment():  # noqa: ANN202
    value = deployment().model_dump(mode="json")
    value["capture_source_implementation_sha256"] = SOURCE_SHA256
    value["deployment_binding_sha256"] = canonical_sha256(
        {key: item for key, item in value.items() if key != "deployment_binding_sha256"}
    )
    return type(deployment()).model_validate(value)


def _asset(index: int, *, depth: bool = False):  # noqa: ANN202
    raw = _depth() if depth else _rgb()
    return public_asset_inline_v4(
        uri=(
            f"dataset://formal-owner/depth/{index}.npy"
            if depth
            else f"dataset://formal-owner/rgb/{index}.png"
        ),
        sha256=hashlib.sha256(raw).hexdigest(),
        media_type="application/x-npy" if depth else "image/png",
        data=raw,
    )


def _frame(
    *,
    run_id: str,
    session_id: str,
    capture_index: int,
    label: str,
    previous_completed_at_ns: int,
    association_capture: PublicAssociationCaptureV2,
    last_skill: LastPhysicallyExecutedPublicSkillV2 | None,
) -> FormalIsaacRawPublicFrameV4:
    payload: dict[str, Any] = {
        "schema_version": "FormalIsaacRawPublicFrameV4",
        "run_id": run_id,
        "session_id": session_id,
        "capture_index": capture_index,
        "label": label,
        "previous_execution_completed_at_ns": previous_completed_at_ns,
        "captured_at_ns": association_capture.timestamp_ns,
        "capture_source_implementation_sha256": SOURCE_SHA256,
        "detections": [item.model_dump(mode="json") for item in association_capture.detections],
        "proprioception_samples": [
            item.model_dump(mode="json")
            for item in association_capture.proprioception_interval.samples
        ],
        "last_physically_executed_public_skill": (
            last_skill.model_dump(mode="json") if last_skill is not None else None
        ),
        "rgb": _asset(capture_index).model_dump(mode="json"),
        "depth": _asset(capture_index, depth=True).model_dump(mode="json"),
        "real_isaac": True,
        "mocked_physics": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return FormalIsaacRawPublicFrameV4(
        **payload,
        frame_receipt_sha256=canonical_sha256(payload),
    )


def _blocked_boundary_capture() -> PublicAssociationCaptureV2:
    selected = capture(
        50,
        [
            (0.0, "yellow", 0.95),
            (0.0439, "red", 0.95),
            (-0.0439, "red", 0.95),
            (0.0, "red", 0.95),
            (0.0, "red", 0.95),
        ],
    )
    payload = selected.model_dump(mode="json")
    positions = (
        (0.0, 0.0),
        (0.0439, 0.0),
        (-0.0439, 0.0),
        (0.0, 0.0439),
        (0.0, -0.0439),
    )
    for raw_detection, (x, y) in zip(payload["detections"], positions, strict=True):
        raw_detection["position_3d"] = [x, y, 0.5]
    payload["capture_receipt_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "capture_receipt_sha256"}
    )
    return PublicAssociationCaptureV2.model_validate(payload)


class _Source:
    implementation_sha256 = SOURCE_SHA256
    real_isaac = True
    mocked_physics = False

    def __init__(self, policy_captures: list[PublicAssociationCaptureV2]) -> None:
        self.policy_captures = policy_captures
        self.calls: list[dict[str, Any]] = []

    def capture_raw_public_frame_v4(self, **kwargs: Any) -> FormalIsaacRawPublicFrameV4:
        self.calls.append(dict(kwargs))
        index = int(kwargs["capture_index"])
        if index == -1:
            selected = _blocked_boundary_capture()
            last_skill = None
        elif index == 8:
            previous = self.policy_captures[-1]
            samples = [
                proprio(previous.timestamp_ns),
                proprio(9_000),
            ]
            interval = PublicProprioceptionIntervalV2(
                start_capture_timestamp_ns=previous.timestamp_ns,
                end_capture_timestamp_ns=9_000,
                expected_sample_timestamps_ns=[item.timestamp_ns for item in samples],
                samples=samples,
                samples_sha256=canonical_sha256([item.model_dump(mode="json") for item in samples]),
            )
            raw: dict[str, Any] = {
                "schema_version": "PublicAssociationCaptureV2",
                "timestamp_ns": 9_000,
                "protocol": previous.protocol.model_dump(mode="json"),
                "previous_capture_receipt_sha256": previous.capture_receipt_sha256,
                "detections": [
                    item.model_copy(update={"timestamp_ns": 9_000}).model_dump(mode="json")
                    for item in previous.detections
                ],
                "proprioception_interval": interval.model_dump(mode="json"),
                "last_physically_executed_public_skill": None,
            }
            selected = PublicAssociationCaptureV2(
                **raw,
                capture_receipt_sha256=canonical_sha256(raw),
            )
            last_skill = LastPhysicallyExecutedPublicSkillV2(
                skill_name="LIFT",
                started_at_ns=8_001,
                completed_at_ns=8_020,
            )
        else:
            selected = self.policy_captures[index]
            last_skill = (
                None
                if index == 0
                else LastPhysicallyExecutedPublicSkillV2(
                    skill_name="LIFT",
                    started_at_ns=(index - 1) * 1_000 + 1_001,
                    completed_at_ns=(index - 1) * 1_000 + 1_020,
                )
            )
        return _frame(
            run_id=str(kwargs["run_id"]),
            session_id=str(kwargs["session_id"]),
            capture_index=index,
            label=str(kwargs["label"]),
            previous_completed_at_ns=int(kwargs["previous_execution_completed_at_ns"]),
            association_capture=selected,
            last_skill=last_skill,
        )


def _start_request() -> IsaacStartRequestV4:
    endpoint = _binding(_observations()[0])
    request = IsaacStartRequestV4.model_validate(
        {
            **__import__(
                "test_m2c_formal_isaac_backend_v4",
                fromlist=["_start_request"],
            )
            ._start_request(endpoint)
            .model_dump(mode="json"),
            "declared_attribute_binding_sha256": attribute_binding().binding_sha256,
        }
    )
    return request


def _owner(source: _Source) -> FormalIsaacPersistentSceneOwnerCoreV4:
    return FormalIsaacPersistentSceneOwnerCoreV4(
        implementation_sha256=OWNER_SHA256,
        source=source,
        association_deployment=_association_deployment(),
        declared_attribute_binding=attribute_binding(),
    )


def test_scene_owner_builds_eight_capture_chain_and_public_final_evidence(
    tmp_path: Path,
) -> None:
    endpoint = _binding(_observations()[0])
    responses, observations = _execution_responses(tmp_path, endpoint)
    captures = [item.observation.association_history[-1].capture for item in observations]
    source = _Source(captures)
    owner = _owner(source)
    start = owner.establish_public_failure_boundary_v4(_start_request())
    assert start.failure_observed_at_ns == 50
    assert start.public_failure_boundary_evidence_sha256 != "0" * 64

    packets = []
    for index, response in enumerate(responses):
        previous_completed = (
            50 if index == 0 else responses[index - 1].execution_receipts[0].completed_at_ns
        )
        packets.append(
            owner.capture_public_v4(
                run_id=start.run_id,
                session_id=start.session_id,
                decision_index=index,
                previous_execution_completed_at_ns=previous_completed,
            )
        )
        assert packets[-1].capture.previous_capture_receipt_sha256 == (
            None if index == 0 else packets[index - 1].capture.capture_receipt_sha256
        )

    last = responses[-1]
    finalize = IsaacFinalizeRequestV4(
        run_id=start.run_id,
        session_id=start.session_id,
        last_execution_receipt_sha256=last.execution_receipts[0].receipt_sha256,
        last_bundle_execution_receipt_sha256=last.bundle_execution_receipt_sha256,
    )
    final = owner.evaluate_public_outcome_v4(
        finalize,
        execution_responses=responses,
    )
    assert final.final_task_success is False
    assert final.outcome_used_as_policy_input is False
    assert final.privileged_truth_policy_input is False
    assert [item["capture_index"] for item in source.calls] == [-1, *range(9)]


def test_scene_owner_rejects_more_than_frozen_detection_capacity() -> None:
    first = capture(
        1_000,
        [(0.01 * index, "yellow" if index == 0 else "blue", 0.9) for index in range(8)],
    )
    source = _Source([first])
    owner = _owner(source)
    start = owner.establish_public_failure_boundary_v4(_start_request())
    raw = source.capture_raw_public_frame_v4

    def over_capacity(**kwargs: Any) -> FormalIsaacRawPublicFrameV4:
        base = raw(**kwargs)
        value = base.model_dump(mode="json")
        while len(value["detections"]) <= 32:
            value["detections"].append(
                detection(
                    base.captured_at_ns,
                    0.2 + len(value["detections"]) * 0.01,
                    "blue",
                    confidence=0.9,
                ).model_dump(mode="json")
            )
        value["frame_receipt_sha256"] = canonical_sha256(
            {key: item for key, item in value.items() if key != "frame_receipt_sha256"}
        )
        return FormalIsaacRawPublicFrameV4.model_validate(value)

    source.capture_raw_public_frame_v4 = over_capacity  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="at most 32 items"):
        owner.capture_public_v4(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=0,
            previous_execution_completed_at_ns=start.failure_observed_at_ns,
        )


def test_scene_owner_rejects_task_or_privileged_fields_in_raw_frame() -> None:
    first = capture(1_000, [(0.0, "yellow", 0.9)])
    source = _Source([first])
    raw = source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=0,
        label="POLICY_INPUT",
        previous_execution_completed_at_ns=50,
    ).model_dump(mode="json")
    raw["task_target_track_id"] = "track-forbidden"
    with pytest.raises(ValueError):
        FormalIsaacRawPublicFrameV4.model_validate(raw)
