"""Frozen public-only role selectors for the M2C formal episode journal.

The selected IDs are evaluator metadata.  They are returned beside a public
capture so the strict journal can later score whether a model-selected literal
was the blocker or task target.  They must never be copied into a model request
or used by the physical skill dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from xh_agent.data_engine.isaac.public_failure_predicates import (
    PublicTrackSnapshotV2,
    select_task_target_track,
)


BLOCKER_VISUAL_COLOR = "red"
TASK_TARGET_VISUAL_COLOR = "yellow"
SELECTOR_WORLD_AXIS = "x"
SELECTOR_EXTREMUM = "max"
SELECTOR_TOP_Z_BAND_M = 0.02


@dataclass(frozen=True)
class PublicJournalRoleIdsV2:
    blocker_track_id: str | None
    task_target_track_id: str | None


def _select_optional(
    tracks: list[PublicTrackSnapshotV2],
    *,
    visual_color: str,
) -> str | None:
    try:
        return select_task_target_track(
            tracks,
            visual_color=visual_color,
            world_axis=SELECTOR_WORLD_AXIS,
            extremum=SELECTOR_EXTREMUM,
            maximum_height_below_tallest_m=SELECTOR_TOP_Z_BAND_M,
        ).track_id
    except ValueError:
        # Occlusion is a real public outcome.  Missing roles stay missing in
        # the evaluator journal instead of being filled from simulator truth.
        return None


def select_public_journal_roles_v2(
    tracks: Sequence[PublicTrackSnapshotV2],
) -> PublicJournalRoleIdsV2:
    """Resolve both committed roles using only the current public tracks."""

    public = list(tracks)
    return PublicJournalRoleIdsV2(
        blocker_track_id=_select_optional(
            public,
            visual_color=BLOCKER_VISUAL_COLOR,
        ),
        task_target_track_id=_select_optional(
            public,
            visual_color=TASK_TARGET_VISUAL_COLOR,
        ),
    )
