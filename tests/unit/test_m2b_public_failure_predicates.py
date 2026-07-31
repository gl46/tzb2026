from __future__ import annotations

from dataclasses import dataclass

import pytest

from xh_agent.data_engine.isaac.public_failure_predicates import (
    PublicTrackSnapshotV2,
    infer_empty_grasp_predicates,
    infer_lift_success_predicates,
    infer_occlusion_aware_lift_success_predicates,
    infer_occlusion_aware_release_failure_predicates,
    infer_occlusion_aware_release_success_predicates,
    infer_occlusion_aware_wrong_object_predicates,
    infer_release_failure_predicates,
    infer_release_success_predicates,
    infer_wrong_object_predicates,
    reassociate_task_target_track,
    select_task_target_track,
    snapshots_from_perception_results,
)


def _track(
    track_id: str,
    color: str,
    xyz: tuple[float, float, float],
    confidence: float = 0.9,
) -> PublicTrackSnapshotV2:
    return PublicTrackSnapshotV2(
        track_id=track_id,
        category="industrial_cylinder",
        visual_color=color,
        position_world_m=list(xyz),
        confidence=confidence,
    )


def test_public_predicates_cover_three_mandatory_failures() -> None:
    before = [
        _track("red-left", "red", (-0.53, -0.34, 0.49)),
        _track("target", "red", (-0.11, -0.13, 0.49)),
        _track("wrong", "yellow", (-0.25, 0.34, 0.49)),
    ]
    target = select_task_target_track(before, visual_color="red")
    assert target.track_id == "target"

    empty_after = [*before[:2], _track("wrong", "yellow", (-0.25, 0.34, 0.49))]
    empty = infer_empty_grasp_predicates(
        before, empty_after, task_target_track_id=target.track_id
    )
    assert empty.predicates == ["grasped=false", "lifted=false"]

    lifted = [
        before[0],
        before[1],
        _track("wrong", "yellow", (-0.25, 0.34, 0.55)),
    ]
    wrong = infer_wrong_object_predicates(
        before, lifted, task_target_track_id=target.track_id
    )
    assert wrong.predicates == ["carried_target_match=false"]
    assert wrong.carried_public_track_id == "wrong"

    released = [
        before[0],
        before[1],
        _track("wrong", "yellow", (-0.25, 0.34, 0.58)),
    ]
    release = infer_release_failure_predicates(
        lifted, released, carried_public_track_id="wrong"
    )
    assert release.predicates == ["released=false"]
    assert release.simulator_truth_used is False

    lifted_success = infer_lift_success_predicates(
        before,
        [before[0], _track("target", "red", (-0.11, -0.13, 0.55)), before[2]],
        task_target_track_id="target",
    )
    assert lifted_success.predicates == ["grasped=true", "lifted=true"]

    release_success = infer_release_success_predicates(
        released,
        [before[0], before[1], _track("wrong", "yellow", (-0.25, 0.34, 0.5801))],
        carried_public_track_id="wrong",
        hand_motion_world_m=[0.0, 0.0, 0.05],
    )
    assert release_success.predicates == ["released=true"]


def test_wrong_object_rejects_missing_public_temporal_identity() -> None:
    with pytest.raises(ValueError, match="no stable public tracks"):
        infer_wrong_object_predicates(
            [_track("before", "yellow", (0.0, 0.0, 0.0))],
            [_track("after", "yellow", (0.0, 0.0, 0.1))],
            task_target_track_id="target",
        )


def test_occlusion_aware_lift_uses_public_site_and_hand_proprioception() -> None:
    before = [_track("target", "red", (-0.11, -0.13, 0.49))]
    result = infer_occlusion_aware_lift_success_predicates(
        before,
        [],
        task_target_track_id="target",
        hand_before_world_m=[-0.11, -0.13, 0.55],
        hand_after_world_m=[-0.11, -0.13, 0.61],
        gripper_closed=True,
    )
    assert result.predicates == ["grasped=true", "lifted=true"]
    assert result.source == "PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION"

    low_confidence_fragment = [
        _track("target", "red", (-0.06, -0.13, 0.46), confidence=0.25)
    ]
    fragment_result = infer_occlusion_aware_lift_success_predicates(
        before,
        low_confidence_fragment,
        task_target_track_id="target",
        hand_before_world_m=[-0.11, -0.13, 0.55],
        hand_after_world_m=[-0.11, -0.13, 0.61],
        gripper_closed=True,
    )
    assert fragment_result.predicates == ["grasped=true", "lifted=true"]

    displaced_noisy_centroid = [
        _track("target", "red", (-0.16, -0.20, 0.46), confidence=0.5)
    ]
    displaced_result = infer_occlusion_aware_lift_success_predicates(
        before,
        displaced_noisy_centroid,
        task_target_track_id="target",
        hand_before_world_m=[-0.11, -0.13, 0.55],
        hand_after_world_m=[-0.11, -0.13, 0.70],
        gripper_closed=True,
    )
    assert displaced_result.predicates == ["grasped=true", "lifted=true"]
    assert displaced_result.source == "PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION"

    visible_at_original_site = [_track("new-red", "red", (-0.11, -0.13, 0.49))]
    rejected = infer_occlusion_aware_lift_success_predicates(
        before,
        visible_at_original_site,
        task_target_track_id="target",
        hand_before_world_m=[-0.11, -0.13, 0.55],
        hand_after_world_m=[-0.11, -0.13, 0.61],
        gripper_closed=True,
    )
    assert rejected.predicates == []


def test_occlusion_aware_wrong_object_compares_public_action_to_task() -> None:
    before = [
        _track("task", "red", (-0.11, -0.13, 0.49)),
        _track("commanded", "yellow", (-0.25, 0.34, 0.49)),
    ]
    result = infer_occlusion_aware_wrong_object_predicates(
        before,
        [before[0]],
        task_target_track_id="task",
        commanded_grasp_track_id="commanded",
        hand_before_world_m=[-0.25, 0.34, 0.55],
        hand_after_world_m=[-0.25, 0.34, 0.61],
        gripper_closed=True,
    )
    assert result.predicates == ["carried_target_match=false"]
    assert result.carried_public_track_id == "commanded"


def test_occlusion_aware_release_uses_public_site_and_hand_motion() -> None:
    before = [_track("carried", "yellow", (-0.25, 0.34, 0.49))]
    failed = infer_occlusion_aware_release_failure_predicates(
        before,
        [],
        carried_public_track_id="carried",
        hand_at_grasp_world_m=[-0.25, 0.34, 0.55],
        hand_before_release_world_m=[-0.25, 0.34, 0.70],
        hand_after_release_motion_world_m=[-0.25, 0.34, 0.73],
    )
    assert failed.predicates == ["released=false"]

    recovered = infer_occlusion_aware_release_success_predicates(
        before,
        [_track("reassociated", "yellow", (-0.248, 0.338, 0.49))],
        carried_public_track_id="carried",
        hand_at_grasp_world_m=[-0.25, 0.34, 0.55],
        hand_before_detach_world_m=[-0.25, 0.34, 0.73],
        hand_after_retreat_world_m=[-0.25, 0.34, 0.78],
    )
    assert recovered.predicates == ["released=true"]
    assert recovered.carried_public_track_id == "reassociated"


def test_task_target_reassociates_without_entity_truth() -> None:
    before = [_track("task", "red", (-0.11, -0.13, 0.49))]
    after = [_track("new-track", "red", (-0.115, -0.132, 0.492))]
    result = reassociate_task_target_track(
        before, after, task_target_track_id="task"
    )
    assert result.track_id == "new-track"


@dataclass
class _Result:
    track_id: str
    category: str
    attributes: dict[str, str]
    position_3d: list[float]
    confidence: float


def test_snapshot_projection_uses_public_camera_calibration() -> None:
    result = _Result(
        track_id="track-1",
        category="industrial_cylinder",
        attributes={"visual_color": "red"},
        position_3d=[1.0, 2.0, 3.0],
        confidence=0.8,
    )
    transform = [
        1.0,
        0.0,
        0.0,
        4.0,
        0.0,
        1.0,
        0.0,
        5.0,
        0.0,
        0.0,
        1.0,
        6.0,
        0.0,
        0.0,
        0.0,
        1.0,
    ]
    snapshots = snapshots_from_perception_results([result], transform)
    assert snapshots[0].position_world_m == [5.0, 7.0, 9.0]
