"""Public temporal track association with no simulator-entity input."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math


@dataclass
class _TrackState:
    track_id: str
    category: str
    visual_color: str | None
    position_3d: tuple[float, float, float]
    timestamp_ns: int


class PublicTrackAssociator:
    """Associate sequential public RGB-D detections by bounded continuity.

    IDs are allocated in an instance-local deterministic order.  Once a track
    exists, matching considers only public category, optional visual colour,
    and Euclidean distance in the camera frame.  In particular, this class
    cannot receive, derive, or retain a Gazebo model/entity identifier.
    """

    def __init__(self, *, maximum_association_distance_m: float = 0.050) -> None:
        if maximum_association_distance_m <= 0:
            raise ValueError("maximum_association_distance_m must be positive")
        self.maximum_association_distance_m = maximum_association_distance_m
        self._tracks: dict[str, _TrackState] = {}
        self._next_index = 0

    def associate(
        self, detections: list[tuple[list[float], str, str | None]], *, timestamp_ns: int,
    ) -> list[str]:
        """Return one stable public ID for each current-frame detection."""
        candidates: list[tuple[float, int, str]] = []
        for detection_index, (position, category, visual_color) in enumerate(detections):
            if len(position) != 3 or not all(math.isfinite(value) for value in position):
                raise ValueError("track association requires a finite 3D public position")
            for track_id, track in self._tracks.items():
                if category != track.category or (visual_color and track.visual_color and visual_color != track.visual_color):
                    continue
                distance = math.dist(position, track.position_3d)
                if distance <= self.maximum_association_distance_m:
                    candidates.append((distance, detection_index, track_id))
        assigned_detection: dict[int, str] = {}
        used_tracks: set[str] = set()
        for _, detection_index, track_id in sorted(candidates):
            if detection_index not in assigned_detection and track_id not in used_tracks:
                assigned_detection[detection_index] = track_id
                used_tracks.add(track_id)
        assigned: list[str] = []
        for index, (position, category, visual_color) in enumerate(detections):
            track_id = assigned_detection.get(index)
            if track_id is None:
                track_id = self._new_track_id(category, visual_color)
            self._tracks[track_id] = _TrackState(
                track_id=track_id, category=category, visual_color=visual_color,
                position_3d=tuple(float(value) for value in position), timestamp_ns=timestamp_ns,
            )
            assigned.append(track_id)
        return assigned

    def _new_track_id(self, category: str, visual_color: str | None) -> str:
        self._next_index += 1
        key = f"public-temporal-v1:{self._next_index}:{category}:{visual_color or ''}"
        return "track-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def track_id_from_geometry(position_3d: list[float], category: str) -> str:
    """Legacy stateless ID helper for one-frame tools only.

    Runtime inference uses :class:`PublicTrackAssociator`, because geometry
    hashes change under normal RGB-D noise and cannot support a carried-track
    identity decision.
    """
    key = f"{category}:{','.join(f'{coordinate:.2f}' for coordinate in position_3d)}"
    return "track-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
