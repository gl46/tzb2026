from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

import xh_agent.perception.public_track_associator_v2 as association
from xh_agent.perception.public_track_associator_v2 import (
    LastPhysicallyExecutedPublicSkillV2,
    PublicAssociationCaptureV2,
    PublicAssociationProtocolV2,
    PublicBBoxOrMaskV2,
    PublicDetectionAttributesV2,
    PublicProprioceptionCaptureBindingV2,
    PublicProprioceptionIntervalV2,
    PublicProprioceptionJournalBindingV2,
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
    PublicTrackAssociatorV2,
)


IDENTITY_TRANSFORM = [
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
]


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def protocol() -> PublicAssociationProtocolV2:
    return PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=IDENTITY_TRANSFORM,
        calibration_sha256=hashlib.sha256(
            json.dumps(IDENTITY_TRANSFORM, separators=(",", ":")).encode("ascii")
        ).hexdigest(),
    )


def proprio(timestamp_ns: int, x: float, *, closed: bool) -> PublicRobotProprioceptionV2:
    return PublicRobotProprioceptionV2(
        timestamp_ns=timestamp_ns,
        world_frame="world",
        end_effector_position_world_m=[x, 0.0, 0.8],
        end_effector_orientation_world_xyzw=[0.0, 0.0, 0.0, 1.0],
        gripper_width_m=0.0 if closed else 0.04,
        gripper_closed=closed,
    )


def detection(timestamp_ns: int, x: float) -> PublicRGBDDetectionV2:
    return PublicRGBDDetectionV2(
        timestamp_ns=timestamp_ns,
        frame_id="policy_rgbd_optical",
        category="industrial_cylinder",
        attributes=PublicDetectionAttributesV2(visual_color="yellow"),
        position_3d=[x, 0.0, 0.5],
        confidence=0.9,
        bbox_or_mask=PublicBBoxOrMaskV2(x=1, y=2, width=3, height=4),
        visibility=1.0,
        covariance_or_quality={"component_pixels": 100.0},
    )


def make_capture(
    timestamp_ns: int,
    xs: list[float],
    *,
    previous: PublicAssociationCaptureV2 | None = None,
    previous_ee_x: float = 0.0,
    current_ee_x: float = 0.0,
    closed: bool = False,
    skill: str | None = None,
    expected_timestamps: list[int] | None = None,
) -> PublicAssociationCaptureV2:
    timestamps = expected_timestamps or (
        [timestamp_ns] if previous is None else [previous.timestamp_ns, timestamp_ns]
    )
    samples = [
        proprio(
            value,
            current_ee_x if value == timestamp_ns else previous_ee_x,
            closed=closed,
        )
        for value in timestamps
    ]
    interval = PublicProprioceptionIntervalV2(
        start_capture_timestamp_ns=timestamps[0],
        end_capture_timestamp_ns=timestamp_ns,
        expected_sample_timestamps_ns=timestamps,
        samples=samples,
        samples_sha256=canonical([item.model_dump(mode="json") for item in samples]),
    )
    payload: dict[str, object] = {
        "schema_version": "PublicAssociationCaptureV2",
        "timestamp_ns": timestamp_ns,
        "protocol": protocol().model_dump(mode="json"),
        "previous_capture_receipt_sha256": (
            previous.capture_receipt_sha256 if previous is not None else None
        ),
        "detections": [detection(timestamp_ns, x).model_dump(mode="json") for x in xs],
        "proprioception_interval": interval.model_dump(mode="json"),
        "last_physically_executed_public_skill": (
            LastPhysicallyExecutedPublicSkillV2(
                skill_name=skill,
                started_at_ns=(previous.timestamp_ns if previous else 0) + 1,
                completed_at_ns=timestamp_ns,
            ).model_dump(mode="json")
            if skill
            else None
        ),
    }
    payload["capture_receipt_sha256"] = canonical(payload)
    return PublicAssociationCaptureV2.model_validate(payload)


def journal(
    captures: list[PublicAssociationCaptureV2],
) -> PublicProprioceptionJournalBindingV2:
    payload: dict[str, object] = {
        "schema_version": "PublicProprioceptionJournalBindingV2",
        "protocol_sha256": canonical(protocol().model_dump(mode="json")),
        "source_implementation_sha256": "1" * 64,
        "captures": [
            PublicProprioceptionCaptureBindingV2(
                capture_timestamp_ns=item.timestamp_ns,
                previous_capture_receipt_sha256=item.previous_capture_receipt_sha256,
                capture_receipt_sha256=item.capture_receipt_sha256,
                expected_sample_timestamps_ns=(
                    item.proprioception_interval.expected_sample_timestamps_ns
                ),
                samples_sha256=item.proprioception_interval.samples_sha256,
            ).model_dump(mode="json")
            for item in captures
        ],
    }
    payload["journal_sha256"] = canonical(payload)
    return PublicProprioceptionJournalBindingV2.model_validate(payload)


def associator(captures: list[PublicAssociationCaptureV2]) -> PublicTrackAssociatorV2:
    return PublicTrackAssociatorV2(
        expected_protocol=protocol(),
        expected_journal=journal(captures),
    )


def test_external_protocol_and_complete_journal_are_mandatory() -> None:
    with pytest.raises(TypeError):
        PublicTrackAssociatorV2()  # type: ignore[call-arg]
    first = make_capture(10, [0.0])
    second = make_capture(20, [0.01], previous=first)
    tracker = associator([first, second])
    tracker.associate(first)
    tracker.associate(second)
    assert tracker.journal_complete
    with pytest.raises(ValueError, match="exceeds frozen journal"):
        tracker.associate(second)


def test_external_journal_rejects_self_consistent_but_unbound_schedule() -> None:
    first = make_capture(10, [0.0])
    second = make_capture(20, [0.17], previous=first, closed=True, skill="LIFT")
    tracker = associator([first, second])
    tracker.associate(first)
    substituted = make_capture(
        20,
        [0.17],
        previous=first,
        closed=True,
        skill="LIFT",
        expected_timestamps=[10, 15, 20],
    )
    with pytest.raises(ValueError, match="external proprioception journal"):
        tracker.associate(substituted)


def test_static_and_hand_carry_hypotheses_and_quantization() -> None:
    first = make_capture(10, [0.0])
    static = make_capture(20, [0.0111114], previous=first)
    tracker = associator([first, static])
    initial = tracker.associate(first)[0]
    moved = tracker.associate(static)[0]
    assert moved.track_id == initial.track_id
    assert moved.association_hypothesis == "STATIC"
    assert moved.association_cost_quantized_m == 0.011111

    first = make_capture(10, [0.0])
    carried = make_capture(
        20,
        [0.17],
        previous=first,
        current_ee_x=0.17,
        closed=True,
        skill="LIFT",
    )
    tracker = associator([first, carried])
    initial = tracker.associate(first)[0]
    moved = tracker.associate(carried)[0]
    assert moved.track_id == initial.track_id
    assert moved.association_hypothesis == "HAND_CARRY"


@pytest.mark.parametrize(("closed", "skill"), [(False, "LIFT"), (True, "PLACE"), (True, None)])
def test_hand_carry_requires_closed_whole_interval_and_frozen_skill(
    closed: bool,
    skill: str | None,
) -> None:
    first = make_capture(10, [0.0])
    second = make_capture(
        20,
        [0.17],
        previous=first,
        current_ee_x=0.17,
        closed=closed,
        skill=skill,
    )
    tracker = associator([first, second])
    initial = tracker.associate(first)[0]
    assert tracker.associate(second)[0].track_id != initial.track_id


def test_global_assignment_maximum_cardinality_then_minimum_cost() -> None:
    first = make_capture(10, [0.0, 0.13])
    second = make_capture(20, [0.12, 0.0], previous=first)
    tracker = associator([first, second])
    initial = tracker.associate(first)
    current = tracker.associate(second)
    assert [item.track_id for item in current] == [initial[1].track_id, initial[0].track_id]


def test_forced_alternative_uses_global_total_cost_not_edge_cost() -> None:
    first = make_capture(10, [0.0, 0.08])
    second = make_capture(20, [0.03, 0.09], previous=first)
    tracker = associator([first, second])
    initial = tracker.associate(first)
    current = tracker.associate(second)
    # Selected total is 0.04 m; the forced swapped global total is 0.14 m.
    # Although one alternative edge differs by only 0.02 m, total-cost
    # ambiguity does not fire.
    assert [item.track_id for item in current] == [initial[0].track_id, initial[1].track_id]

    # Directly lock the P1 counterexample: edge difference is >= 0.02 m while
    # the forced global total differs by < 0.02 m.
    detections = (
        association._Detection(0, detection(20, 0.0), (0.0, 0.0, 0.5)),
        association._Detection(1, detection(20, 0.1), (0.1, 0.0, 0.5)),
    )
    edges = {
        ("track-a", 0): association._Edge("track-a", 0, 10_000, "STATIC"),
        ("track-a", 1): association._Edge("track-a", 1, 40_000, "STATIC"),
        ("track-b", 0): association._Edge("track-b", 0, 49_000, "STATIC"),
        ("track-b", 1): association._Edge("track-b", 1, 70_000, "STATIC"),
    }
    chosen = association._solve_assignment(
        priors=("track-a", "track-b"),
        detections=detections,
        edges=edges,
    )
    assert chosen.total_cost_quanta == 80_000
    assert association._ambiguous_detections(
        assignment=chosen,
        priors=("track-a", "track-b"),
        detections=detections,
        edges=edges,
    ) == {0, 1}


def test_two_unmatched_captures_expire_and_never_emit_prior() -> None:
    first = make_capture(10, [0.0])
    second = make_capture(20, [], previous=first)
    third = make_capture(30, [], previous=second)
    fourth = make_capture(40, [0.0], previous=third)
    tracker = associator([first, second, third, fourth])
    initial = tracker.associate(first)[0]
    assert tracker.associate(second) == []
    assert tracker.active_track_ids == (initial.track_id,)
    assert tracker.associate(third) == []
    assert tracker.active_track_ids == ()
    assert tracker.associate(fourth)[0].track_id != initial.track_id


def test_detection_bound_and_forbidden_fields_fail_closed() -> None:
    with pytest.raises(ValidationError, match="at most 8"):
        make_capture(10, [float(index) for index in range(9)])
    payload = make_capture(10, [0.0]).model_dump(mode="python")
    payload["task_target_track_id"] = "track-secret"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicAssociationCaptureV2.model_validate(payload)


def test_protocol_mismatch_rejected_before_first_capture() -> None:
    first = make_capture(10, [0.0])
    transform = [*IDENTITY_TRANSFORM]
    transform[3] = 0.01
    changed = PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=transform,
        calibration_sha256=hashlib.sha256(
            json.dumps(transform, separators=(",", ":")).encode("ascii")
        ).hexdigest(),
    )
    tracker = associator([first])
    poisoned = first.model_copy(update={"protocol": changed})
    with pytest.raises(ValueError, match="binding changed"):
        tracker.associate(poisoned)
