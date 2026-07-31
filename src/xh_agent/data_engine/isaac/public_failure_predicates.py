"""Public RGB-D-only predicate extraction for M2B failure episodes.

The helpers in this module deliberately accept only public perception tracks.
Simulator entity identifiers and perfect poses belong in the separate
supervision projection and cannot be passed here.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PublicTrackSnapshotV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["PublicTrackSnapshotV2"] = "PublicTrackSnapshotV2"
    track_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    visual_color: str | None = None
    position_world_m: list[float] = Field(min_length=3, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def finite_position(self) -> "PublicTrackSnapshotV2":
        if not all(math.isfinite(value) for value in self.position_world_m):
            raise ValueError("public track position must be finite")
        return self


class PublicFailurePredicateResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["PublicFailurePredicateResultV2"] = (
        "PublicFailurePredicateResultV2"
    )
    predicates: list[str]
    task_target_track_id: str | None = None
    carried_public_track_id: str | None = None
    measurements_m: dict[str, float]
    source: Literal[
        "PUBLIC_RGBD_TEMPORAL_TRACKS_ONLY",
        "PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION",
    ] = "PUBLIC_RGBD_TEMPORAL_TRACKS_ONLY"
    simulator_truth_used: Literal[False] = False


def select_task_target_track(
    tracks: list[PublicTrackSnapshotV2],
    *,
    visual_color: str,
    world_axis: Literal["x", "y", "z"] = "x",
    extremum: Literal["min", "max"] = "max",
) -> PublicTrackSnapshotV2:
    """Resolve an explicit public TaskSpec such as ``red/max-world-x``."""

    candidates = [track for track in tracks if track.visual_color == visual_color]
    if not candidates:
        raise ValueError(f"no public {visual_color!r} target candidate")
    axis = {"x": 0, "y": 1, "z": 2}[world_axis]
    ordered = sorted(
        candidates,
        key=lambda track: (track.position_world_m[axis], track.track_id),
    )
    return ordered[-1] if extremum == "max" else ordered[0]


def reassociate_task_target_track(
    before: list[PublicTrackSnapshotV2],
    after: list[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
    maximum_reassociation_distance_m: float = 0.08,
) -> PublicTrackSnapshotV2:
    """Reacquire TaskSpec from public identity or color/geometry continuity."""

    target = _by_track_id(before, task_target_track_id)
    exact = [track for track in after if track.track_id == task_target_track_id]
    if len(exact) == 1 and exact[0].confidence >= 0.5:
        return exact[0]
    candidates = [
        track
        for track in after
        if track.visual_color == target.visual_color and track.confidence >= 0.5
    ]
    if not candidates:
        raise ValueError("public TaskSpec target could not be reassociated")
    reassociated = min(
        candidates,
        key=lambda track: math.dist(
            track.position_world_m, target.position_world_m
        ),
    )
    if (
        math.dist(reassociated.position_world_m, target.position_world_m)
        > maximum_reassociation_distance_m
    ):
        raise ValueError("public TaskSpec reassociation exceeded distance gate")
    return reassociated


def infer_empty_grasp_predicates(
    before: list[PublicTrackSnapshotV2],
    after: list[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
    maximum_stationary_motion_m: float = 0.03,
) -> PublicFailurePredicateResultV2:
    start = _by_track_id(before, task_target_track_id)
    end = _by_track_id(after, task_target_track_id)
    motion = math.dist(start.position_world_m, end.position_world_m)
    predicates = []
    if motion <= maximum_stationary_motion_m:
        predicates.extend(("grasped=false", "lifted=false"))
    return PublicFailurePredicateResultV2(
        predicates=predicates,
        task_target_track_id=task_target_track_id,
        measurements_m={"task_target_motion_m": motion},
    )


def infer_wrong_object_predicates(
    before: list[PublicTrackSnapshotV2],
    after: list[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
    minimum_carried_motion_m: float = 0.01,
) -> PublicFailurePredicateResultV2:
    """Identify the most displaced public track and compare it to TaskSpec."""

    motions = _stable_track_motions(before, after)
    if not motions:
        raise ValueError("no stable public tracks are available for mismatch")
    carried_motion_m, carried_track_id = max(
        (motion, track_id) for track_id, motion in motions.items()
    )
    predicates = []
    if (
        carried_motion_m >= minimum_carried_motion_m
        and carried_track_id != task_target_track_id
    ):
        predicates.append("carried_target_match=false")
    return PublicFailurePredicateResultV2(
        predicates=predicates,
        task_target_track_id=task_target_track_id,
        carried_public_track_id=carried_track_id,
        measurements_m={"carried_track_motion_m": carried_motion_m},
    )


def infer_release_failure_predicates(
    before_release: list[PublicTrackSnapshotV2],
    after_motion: list[PublicTrackSnapshotV2],
    *,
    carried_public_track_id: str,
    minimum_follow_motion_m: float = 0.01,
) -> PublicFailurePredicateResultV2:
    start = _by_track_id(before_release, carried_public_track_id)
    end = _by_track_id(after_motion, carried_public_track_id)
    motion = math.dist(start.position_world_m, end.position_world_m)
    predicates = ["released=false"] if motion >= minimum_follow_motion_m else []
    return PublicFailurePredicateResultV2(
        predicates=predicates,
        carried_public_track_id=carried_public_track_id,
        measurements_m={"carried_track_follow_motion_m": motion},
    )


def infer_occlusion_aware_release_failure_predicates(
    before_grasp: list[PublicTrackSnapshotV2],
    after_release_motion: list[PublicTrackSnapshotV2],
    *,
    carried_public_track_id: str,
    hand_at_grasp_world_m: list[float],
    hand_before_release_world_m: list[float],
    hand_after_release_motion_world_m: list[float],
    minimum_hand_motion_m: float = 0.01,
    maximum_release_site_error_m: float = 0.05,
) -> PublicFailurePredicateResultV2:
    """Infer failed release when the carried track stays gripper-occluded."""

    target = _by_track_id(before_grasp, carried_public_track_id)
    hand_motion = math.dist(
        hand_before_release_world_m, hand_after_release_motion_world_m
    )
    release_site = [
        target_value + release_value - grasp_value
        for target_value, release_value, grasp_value in zip(
            target.position_world_m,
            hand_before_release_world_m,
            hand_at_grasp_world_m,
        )
    ]
    site_errors = [
        math.dist(track.position_world_m, release_site)
        for track in after_release_motion
        if track.visual_color == target.visual_color
        and track.confidence >= 0.5
    ]
    nearest_error = min(site_errors, default=float("inf"))
    failed = bool(
        hand_motion >= minimum_hand_motion_m
        and nearest_error > maximum_release_site_error_m
    )
    return PublicFailurePredicateResultV2(
        predicates=["released=false"] if failed else [],
        carried_public_track_id=carried_public_track_id if failed else None,
        measurements_m={
            "hand_follow_motion_m": hand_motion,
            "nearest_release_site_track_error_m": nearest_error,
        },
        source="PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION",
    )


def infer_lift_success_predicates(
    before: list[PublicTrackSnapshotV2],
    after_lift: list[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
    minimum_vertical_lift_m: float = 0.01,
) -> PublicFailurePredicateResultV2:
    start = _by_track_id(before, task_target_track_id)
    end = _by_track_id(after_lift, task_target_track_id)
    vertical_lift_m = end.position_world_m[2] - start.position_world_m[2]
    predicates = []
    if vertical_lift_m >= minimum_vertical_lift_m:
        predicates.extend(("grasped=true", "lifted=true"))
    return PublicFailurePredicateResultV2(
        predicates=predicates,
        task_target_track_id=task_target_track_id,
        carried_public_track_id=task_target_track_id,
        measurements_m={"task_target_vertical_lift_m": vertical_lift_m},
    )


def infer_occlusion_aware_lift_success_predicates(
    before: list[PublicTrackSnapshotV2],
    after_lift: list[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
    hand_before_world_m: list[float],
    hand_after_world_m: list[float],
    gripper_closed: bool,
    minimum_vertical_lift_m: float = 0.03,
    maximum_target_hand_xy_error_m: float = 0.04,
    maximum_original_site_motion_m: float = 0.03,
    minimum_visible_track_confidence: float = 0.5,
) -> PublicFailurePredicateResultV2:
    """Infer a carried target through documented public-view occlusion.

    The target must be observed before the action, absent from its original
    public RGB-D site afterwards, aligned with the gripper in XY, and followed
    by a closed-gripper vertical lift.  Robot hand positions are proprioceptive
    state; no object pose or simulator entity identifier is accepted.
    """

    if len(hand_before_world_m) != 3 or len(hand_after_world_m) != 3:
        raise ValueError("hand poses must be XYZ triples")
    if not all(
        math.isfinite(value)
        for value in [*hand_before_world_m, *hand_after_world_m]
    ):
        raise ValueError("hand poses must be finite")
    target = _by_track_id(before, task_target_track_id)
    current = [
        track
        for track in after_lift
        if track.track_id == task_target_track_id
        and track.confidence >= minimum_visible_track_confidence
    ]
    if current:
        direct = infer_lift_success_predicates(
            before,
            after_lift,
            task_target_track_id=task_target_track_id,
            minimum_vertical_lift_m=minimum_vertical_lift_m,
        )
        if {"grasped=true", "lifted=true"}.issubset(direct.predicates):
            return direct
        # A partly occluded RGB-D mask can retain the track id while its
        # projected centroid falls onto the table/background.  Do not treat
        # that noisy Z estimate as an unconditional rejection: the same
        # public original-site and hand-proprioception gates used below still
        # distinguish a carried target from one left on the table.
    same_color_at_original_site = any(
        track.visual_color == target.visual_color
        and track.confidence >= minimum_visible_track_confidence
        and math.dist(track.position_world_m, target.position_world_m)
        <= maximum_original_site_motion_m
        for track in after_lift
    )
    hand_vertical_lift_m = hand_after_world_m[2] - hand_before_world_m[2]
    target_hand_xy_error_m = math.dist(
        target.position_world_m[:2], hand_before_world_m[:2]
    )
    passed = bool(
        gripper_closed
        and not same_color_at_original_site
        and hand_vertical_lift_m >= minimum_vertical_lift_m
        and target_hand_xy_error_m <= maximum_target_hand_xy_error_m
    )
    return PublicFailurePredicateResultV2(
        predicates=["grasped=true", "lifted=true"] if passed else [],
        task_target_track_id=task_target_track_id,
        carried_public_track_id=task_target_track_id if passed else None,
        measurements_m={
            "hand_vertical_lift_m": hand_vertical_lift_m,
            "target_hand_xy_error_m": target_hand_xy_error_m,
        },
        source="PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION",
    )


def infer_occlusion_aware_wrong_object_predicates(
    before: list[PublicTrackSnapshotV2],
    after_lift: list[PublicTrackSnapshotV2],
    *,
    task_target_track_id: str,
    commanded_grasp_track_id: str,
    hand_before_world_m: list[float],
    hand_after_world_m: list[float],
    gripper_closed: bool,
) -> PublicFailurePredicateResultV2:
    carried = infer_occlusion_aware_lift_success_predicates(
        before,
        after_lift,
        task_target_track_id=commanded_grasp_track_id,
        hand_before_world_m=hand_before_world_m,
        hand_after_world_m=hand_after_world_m,
        gripper_closed=gripper_closed,
    )
    mismatch = bool(
        {"grasped=true", "lifted=true"}.issubset(carried.predicates)
        and commanded_grasp_track_id != task_target_track_id
    )
    return PublicFailurePredicateResultV2(
        predicates=["carried_target_match=false"] if mismatch else [],
        task_target_track_id=task_target_track_id,
        carried_public_track_id=(commanded_grasp_track_id if mismatch else None),
        measurements_m=carried.measurements_m,
        source="PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION",
    )


def infer_release_success_predicates(
    before_retreat: list[PublicTrackSnapshotV2],
    after_retreat: list[PublicTrackSnapshotV2],
    *,
    carried_public_track_id: str,
    hand_motion_world_m: list[float],
    minimum_relative_motion_m: float = 0.02,
) -> PublicFailurePredicateResultV2:
    if len(hand_motion_world_m) != 3 or not all(
        math.isfinite(value) for value in hand_motion_world_m
    ):
        raise ValueError("hand motion must be a finite public-proprioceptive XYZ")
    start = _by_track_id(before_retreat, carried_public_track_id)
    end = _by_track_id(after_retreat, carried_public_track_id)
    object_motion = [
        end_value - start_value
        for start_value, end_value in zip(
            start.position_world_m, end.position_world_m
        )
    ]
    relative_motion = math.dist(object_motion, hand_motion_world_m)
    predicates = (
        ["released=true"]
        if relative_motion >= minimum_relative_motion_m
        else []
    )
    return PublicFailurePredicateResultV2(
        predicates=predicates,
        carried_public_track_id=carried_public_track_id,
        measurements_m={
            "released_object_motion_m": math.dist(
                start.position_world_m, end.position_world_m
            ),
            "hand_object_relative_motion_m": relative_motion,
        },
    )


def infer_occlusion_aware_release_success_predicates(
    before_grasp: list[PublicTrackSnapshotV2],
    after_retreat: list[PublicTrackSnapshotV2],
    *,
    carried_public_track_id: str,
    hand_at_grasp_world_m: list[float],
    hand_before_detach_world_m: list[float],
    hand_after_retreat_world_m: list[float],
    maximum_release_site_xy_error_m: float = 0.08,
    minimum_hand_object_relative_motion_m: float = 0.02,
) -> PublicFailurePredicateResultV2:
    """Reassociate a released track by public color and detach-site geometry."""

    target = _by_track_id(before_grasp, carried_public_track_id)
    predicted_detach_site = [
        target_value + detach_value - grasp_value
        for target_value, detach_value, grasp_value in zip(
            target.position_world_m,
            hand_before_detach_world_m,
            hand_at_grasp_world_m,
        )
    ]
    candidates = [
        track
        for track in after_retreat
        if track.visual_color == target.visual_color and track.confidence >= 0.5
    ]
    if not candidates:
        return PublicFailurePredicateResultV2(
            predicates=[],
            carried_public_track_id=carried_public_track_id,
            measurements_m={"nearest_release_site_xy_error_m": float("inf")},
            source="PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION",
        )
    released_track = min(
        candidates,
        key=lambda track: math.dist(
            track.position_world_m[:2], predicted_detach_site[:2]
        ),
    )
    xy_error = math.dist(
        released_track.position_world_m[:2], predicted_detach_site[:2]
    )
    object_motion = [
        observed - predicted
        for observed, predicted in zip(
            released_track.position_world_m, predicted_detach_site
        )
    ]
    hand_motion = [
        after - before
        for before, after in zip(
            hand_before_detach_world_m, hand_after_retreat_world_m
        )
    ]
    relative_motion = math.dist(object_motion, hand_motion)
    passed = bool(
        xy_error <= maximum_release_site_xy_error_m
        and relative_motion >= minimum_hand_object_relative_motion_m
    )
    return PublicFailurePredicateResultV2(
        predicates=["released=true"] if passed else [],
        carried_public_track_id=released_track.track_id if passed else None,
        measurements_m={
            "nearest_release_site_xy_error_m": xy_error,
            "hand_object_relative_motion_m": relative_motion,
        },
        source="PUBLIC_RGBD_AND_ROBOT_PROPRIOCEPTION",
    )


def snapshots_from_perception_results(
    results: list[Any],
    camera_to_world_optical: list[float],
) -> list[PublicTrackSnapshotV2]:
    """Project public optical positions to world using public calibration."""

    if len(camera_to_world_optical) != 16:
        raise ValueError("camera-to-world transform must be a 4x4 row-major matrix")
    snapshots: list[PublicTrackSnapshotV2] = []
    for result in results:
        x, y, z = (float(value) for value in result.position_3d)
        matrix = camera_to_world_optical
        world = [
            matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
            matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
            matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
        ]
        snapshots.append(
            PublicTrackSnapshotV2(
                track_id=result.track_id,
                category=result.category,
                visual_color=result.attributes.get("visual_color"),
                position_world_m=world,
                confidence=result.confidence,
            )
        )
    return snapshots


def _stable_track_motions(
    before: list[PublicTrackSnapshotV2],
    after: list[PublicTrackSnapshotV2],
) -> dict[str, float]:
    after_by_id = {track.track_id: track for track in after}
    return {
        track.track_id: math.dist(
            track.position_world_m,
            after_by_id[track.track_id].position_world_m,
        )
        for track in before
        if track.track_id in after_by_id
    }


def _by_track_id(
    tracks: list[PublicTrackSnapshotV2], track_id: str
) -> PublicTrackSnapshotV2:
    matches = [track for track in tracks if track.track_id == track_id]
    if len(matches) != 1:
        raise ValueError(
            f"expected one public track {track_id!r}, found {len(matches)}"
        )
    return matches[0]
