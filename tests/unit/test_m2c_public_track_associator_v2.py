from __future__ import annotations

import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from xh_agent.perception.public_track_associator_v2 import (
    PUBLIC_TRACK_AMBIGUITY_MARGIN_M,
    PUBLIC_TRACK_ASSOCIATION_GATE_M,
    PUBLIC_TRACK_COST_QUANTUM_M,
    PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES,
    LastPhysicallyExecutedPublicSkillV2,
    PublicAssociationCaptureV2,
    PublicAssociationProtocolV2,
    PublicDetectionAttributesV2,
    PublicBBoxOrMaskV2,
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
CALIBRATION_SHA256 = hashlib.sha256(
    json.dumps(IDENTITY_TRANSFORM, separators=(",", ":")).encode("ascii")
).hexdigest()


def protocol() -> PublicAssociationProtocolV2:
    return PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=IDENTITY_TRANSFORM,
        calibration_sha256=CALIBRATION_SHA256,
    )


def detection(
    timestamp_ns: int,
    x: float,
    *,
    color: str | None = "yellow",
    category: str = "industrial_cylinder",
    confidence: float = 0.9,
) -> PublicRGBDDetectionV2:
    return PublicRGBDDetectionV2(
        timestamp_ns=timestamp_ns,
        frame_id="policy_rgbd_optical",
        category=category,
        attributes=PublicDetectionAttributesV2(visual_color=color),
        position_3d=[x, 0.0, 0.5],
        confidence=confidence,
        bbox_or_mask=PublicBBoxOrMaskV2(x=1, y=2, width=3, height=4),
        visibility=1.0,
        covariance_or_quality={"component_pixels": 100.0},
    )


def proprio(
    timestamp_ns: int,
    x: float,
    *,
    closed: bool,
) -> PublicRobotProprioceptionV2:
    return PublicRobotProprioceptionV2(
        timestamp_ns=timestamp_ns,
        world_frame="world",
        end_effector_position_world_m=[x, 0.0, 0.8],
        end_effector_orientation_world_xyzw=[0.0, 0.0, 0.0, 1.0],
        gripper_width_m=0.0 if closed else 0.04,
        gripper_closed=closed,
    )


def capture(
    timestamp_ns: int,
    xs: list[float],
    *,
    previous_timestamp_ns: int | None = None,
    previous_ee_x: float = 0.0,
    current_ee_x: float = 0.0,
    closed: bool = False,
    skill: str | None = None,
    colors: list[str | None] | None = None,
    categories: list[str] | None = None,
    protocol_override: PublicAssociationProtocolV2 | None = None,
) -> PublicAssociationCaptureV2:
    samples = []
    if previous_timestamp_ns is not None:
        samples.append(proprio(previous_timestamp_ns, previous_ee_x, closed=closed))
    samples.append(proprio(timestamp_ns, current_ee_x, closed=closed))
    skill_input = None
    if skill is not None:
        skill_input = LastPhysicallyExecutedPublicSkillV2(
            skill_name=skill,
            started_at_ns=(previous_timestamp_ns or 0) + 1,
            completed_at_ns=timestamp_ns,
        )
    return PublicAssociationCaptureV2(
        timestamp_ns=timestamp_ns,
        protocol=protocol_override or protocol(),
        detections=[
            detection(
                timestamp_ns,
                x,
                color=(colors[index] if colors is not None else "yellow"),
                category=(categories[index] if categories is not None else "industrial_cylinder"),
            )
            for index, x in enumerate(xs)
        ],
        proprioception=samples,
        last_physically_executed_public_skill=skill_input,
    )


def test_frozen_numeric_contract_and_static_association() -> None:
    assert PUBLIC_TRACK_ASSOCIATION_GATE_M == 0.12
    assert PUBLIC_TRACK_AMBIGUITY_MARGIN_M == 0.02
    assert PUBLIC_TRACK_COST_QUANTUM_M == 0.000001
    assert PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES == 2
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0]))
    moved = associator.associate(capture(20, [0.0111114], previous_timestamp_ns=10))
    assert moved[0].track_id == initial[0].track_id
    assert moved[0].association_hypothesis == "STATIC"
    assert moved[0].association_cost_quantized_m == 0.011111


def test_hand_carry_beats_static_and_static_decoy() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0]))[0]
    # The old site is still visible, but STATIC and HAND_CARRY give two equal-
    # cost identity assignments for the same prior.  The lexicographic global
    # optimum selects the lower centroid (STATIC); HAND_CARRY is not a distinct
    # prior identity, so it does not trigger the identity-ambiguity margin.
    outputs = associator.associate(
        capture(
            20,
            [0.0, 0.17],
            previous_timestamp_ns=10,
            previous_ee_x=0.0,
            current_ee_x=0.17,
            closed=True,
            skill="LIFT",
        )
    )
    assert outputs[0].track_id == initial.track_id
    assert outputs[0].association_hypothesis == "STATIC"
    assert outputs[1].track_id != initial.track_id
    assert outputs[1].association_hypothesis == "NEW"


def test_hand_carry_recovers_identity_when_static_is_outside_gate() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0]))[0]
    carried = associator.associate(
        capture(
            20,
            [0.17],
            previous_timestamp_ns=10,
            previous_ee_x=0.0,
            current_ee_x=0.17,
            closed=True,
            skill="LIFT",
        )
    )[0]
    assert carried.track_id == initial.track_id
    assert carried.association_hypothesis == "HAND_CARRY"


@pytest.mark.parametrize(
    ("closed", "skill"),
    [(False, "LIFT"), (True, "PLACE"), (True, None)],
)
def test_hand_carry_ineligible_without_both_frozen_conditions(
    closed: bool,
    skill: str | None,
) -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0]))[0]
    output = associator.associate(
        capture(
            20,
            [0.17],
            previous_timestamp_ns=10,
            current_ee_x=0.17,
            closed=closed,
            skill=skill,
        )
    )[0]
    assert output.track_id != initial.track_id
    assert output.association_hypothesis == "NEW"


def test_category_and_visual_color_are_strict_equality_prefilters() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0]))[0]
    color_changed = associator.associate(
        capture(20, [0.0], previous_timestamp_ns=10, colors=["blue"])
    )[0]
    assert color_changed.track_id != initial.track_id
    category_changed = associator.associate(
        capture(
            30,
            [0.0],
            previous_timestamp_ns=20,
            colors=["blue"],
            categories=["box"],
        )
    )[0]
    assert category_changed.track_id != color_changed.track_id


def test_global_assignment_maximizes_cardinality_then_minimizes_total_cost() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0, 0.13]))
    # Greedy nearest would assign prior 0.00 -> 0.12 and strand prior 0.13;
    # the maximum-cardinality global solution is 0.00 -> 0.00 and 0.13 -> 0.12.
    current = associator.associate(capture(20, [0.12, 0.0], previous_timestamp_ns=10))
    assert [item.track_id for item in current] == [initial[1].track_id, initial[0].track_id]


def test_equal_cost_global_optimum_uses_frozen_lexicographic_assignment() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [-0.03, 0.03]))
    current = associator.associate(capture(20, [0.0, 0.0], previous_timestamp_ns=10))
    # Both complete assignments have identical cost and centroid tuples.  Both
    # detections are implicated by an alternative prior identity and therefore
    # fail closed to deterministic new IDs instead of exposing either optimum.
    assert all(item.track_id not in {track.track_id for track in initial} for item in current)


def test_per_detection_local_alternative_within_margin_gets_new_id() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0, 0.03]))
    current = associator.associate(capture(20, [0.014], previous_timestamp_ns=10))[0]
    assert current.track_id not in {item.track_id for item in initial}
    assert current.association_hypothesis == "NEW"
    assert set(associator.active_track_ids).issuperset({item.track_id for item in initial})


def test_global_assignment_alternative_identity_is_compared_per_detection() -> None:
    associator = PublicTrackAssociatorV2()
    initial = associator.associate(capture(10, [0.0, 0.08]))
    # Every alternative identity edge differs by at least exactly 0.02 m, so
    # the strict '< 0.02' rule does not fire even though a forced global swap
    # exists.  This locks the ADR's per-detection identity-cost definition.
    current = associator.associate(capture(20, [0.03, 0.09], previous_timestamp_ns=10))
    assert [item.track_id for item in current] == [
        initial[0].track_id,
        initial[1].track_id,
    ]


def test_unmatched_tracks_never_emit_and_expire_after_two_captures() -> None:
    associator = PublicTrackAssociatorV2()
    initial_id = associator.associate(capture(10, [0.0]))[0].track_id
    assert associator.associate(capture(20, [], previous_timestamp_ns=10)) == []
    assert associator.active_track_ids == (initial_id,)
    assert associator.associate(capture(30, [], previous_timestamp_ns=20)) == []
    assert associator.active_track_ids == ()
    replacement = associator.associate(capture(40, [0.0], previous_timestamp_ns=30))[0]
    assert replacement.track_id != initial_id


def test_timestamp_frame_unit_calibration_and_interval_fail_closed() -> None:
    associator = PublicTrackAssociatorV2()
    associator.associate(capture(10, [0.0]))
    with pytest.raises(ValueError, match="strictly monotonic"):
        associator.associate(capture(10, [0.0], previous_timestamp_ns=10))
    changed_transform = [*IDENTITY_TRANSFORM]
    changed_transform[3] = 0.01
    changed = PublicAssociationProtocolV2(
        declared_camera_frame="policy_rgbd_optical",
        declared_world_frame="world",
        camera_to_world_row_major=changed_transform,
        calibration_sha256=hashlib.sha256(
            json.dumps(changed_transform, separators=(",", ":")).encode("ascii")
        ).hexdigest(),
    )
    with pytest.raises(ValueError, match="binding changed"):
        associator.associate(
            capture(
                20,
                [0.0],
                previous_timestamp_ns=10,
                protocol_override=changed,
            )
        )
    with pytest.raises(ValueError, match="prior capture"):
        associator.associate(capture(20, [0.0], previous_timestamp_ns=9))


def test_calibration_hash_and_adjacent_skill_interval_are_verified() -> None:
    protocol_payload = protocol().model_dump(mode="python")
    protocol_payload["calibration_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="does not bind"):
        PublicAssociationProtocolV2.model_validate(protocol_payload)

    associator = PublicTrackAssociatorV2()
    associator.associate(capture(10, [0.0]))
    stale_skill_capture = capture(
        20,
        [0.17],
        previous_timestamp_ns=10,
        current_ee_x=0.17,
        closed=True,
        skill="LIFT",
    )
    stale_skill_capture = stale_skill_capture.model_copy(
        update={
            "last_physically_executed_public_skill": (
                LastPhysicallyExecutedPublicSkillV2(
                    skill_name="LIFT",
                    started_at_ns=1,
                    completed_at_ns=20,
                )
            )
        }
    )
    with pytest.raises(ValueError, match="adjacent capture interval"):
        associator.associate(stale_skill_capture)


@pytest.mark.parametrize(
    "forbidden",
    [
        "task_target_track_id",
        "receipt_sha256",
        "task_success",
        "entity_id",
        "teacher_output",
        "scene_seed",
    ],
)
def test_forbidden_identity_truth_teacher_and_outcome_fields_rejected(
    forbidden: str,
) -> None:
    payload = capture(10, [0.0]).model_dump(mode="python")
    payload[forbidden] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicAssociationCaptureV2.model_validate(payload)
    detection_payload = detection(10, 0.0).model_dump(mode="python")
    detection_payload[forbidden] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PublicRGBDDetectionV2.model_validate(detection_payload)


def test_input_order_does_not_change_deterministic_new_identity_mapping() -> None:
    first = PublicTrackAssociatorV2().associate(capture(10, [0.2, -0.1]))
    second = PublicTrackAssociatorV2().associate(capture(10, [-0.1, 0.2]))
    assert {item.position_3d[0]: item.track_id for item in first} == {
        item.position_3d[0]: item.track_id for item in second
    }


def test_capture_input_is_copied_and_cannot_be_mutated_by_association() -> None:
    raw = capture(10, [0.0]).model_dump(mode="python")
    before = copy.deepcopy(raw)
    PublicTrackAssociatorV2().associate(PublicAssociationCaptureV2.model_validate(raw))
    assert raw == before
