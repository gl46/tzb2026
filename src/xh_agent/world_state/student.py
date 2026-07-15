"""Teacher-independent Student world-model boundary and decision utilities.

The classes here deliberately consume only policy-visible observations and
candidate actions. SimulatorSupervisionV0 belongs in offline training/eval data,
not in ``predict`` or residual attribution at execution time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from xh_agent.contracts.models import ActionTrajectoryV0, CandidateSkillV0, ObjectTrackV0, ObservationV0, TaskSpecV0


class StudentPredictionV0(BaseModel):
    """Planned Student output; none of its fields is simulator privileged truth."""

    model_config = ConfigDict(extra="forbid")
    future_object_tracks: list[ObjectTrackV0] = Field(default_factory=list)
    contact_probability: float = Field(ge=0, le=1)
    grasp_probability: float = Field(ge=0, le=1)
    collision_probability: float = Field(ge=0, le=1)
    slip_probability: float = Field(ge=0, le=1)
    task_progress: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    provenance: str


class StudentWorldModel(Protocol):
    """Trainable boundary; concrete models may be learned without a Teacher."""

    def predict(
        self,
        observation: ObservationV0,
        task: TaskSpecV0,
        candidate: CandidateSkillV0,
        action: ActionTrajectoryV0,
    ) -> StudentPredictionV0: ...


class CandidateDecisionV0(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    accepted: bool
    score: float
    reason: str
    prediction: StudentPredictionV0


class ResidualAttributionV0(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mean_track_position_error: float | None = Field(default=None, ge=0)
    predicted_progress: float = Field(ge=0, le=1)
    observed_progress: float = Field(ge=0, le=1)
    uncertainty: float = Field(ge=0, le=1)
    recovery_required: bool
    reason: str


def rank_candidates(
    predictions: list[tuple[CandidateSkillV0, StudentPredictionV0]], *, max_uncertainty: float = 0.5
) -> list[CandidateDecisionV0]:
    """Rank candidates by predicted progress/risk without consulting simulator truth."""
    decisions: list[CandidateDecisionV0] = []
    for candidate, prediction in predictions:
        risk = prediction.collision_probability + prediction.slip_probability + prediction.uncertainty
        score = prediction.task_progress + prediction.grasp_probability - risk
        accepted = prediction.uncertainty <= max_uncertainty and prediction.collision_probability <= 0.5
        reason = "accepted" if accepted else "uncertainty_or_collision_gate"
        decisions.append(CandidateDecisionV0(
            candidate_id=candidate.candidate_id, accepted=accepted, score=score, reason=reason, prediction=prediction
        ))
    return sorted(decisions, key=lambda decision: decision.score, reverse=True)


def attribute_residual(
    prediction: StudentPredictionV0,
    observation_after: ObservationV0,
    *, observed_progress: float,
    residual_threshold_m: float = 0.05,
) -> ResidualAttributionV0:
    """Compare predicted and perceived tracks only; no ground truth is accepted."""
    observed = {track.object_id: track for track in observation_after.object_tracks}
    errors: list[float] = []
    for expected in prediction.future_object_tracks:
        actual = observed.get(expected.object_id)
        if actual is not None:
            errors.append(sum((a - b) ** 2 for a, b in zip(expected.pose[:3], actual.pose[:3])) ** 0.5)
    mean_error = sum(errors) / len(errors) if errors else None
    recovery = prediction.uncertainty > 0.5 or (mean_error is not None and mean_error > residual_threshold_m)
    reason = "uncertainty_gate" if prediction.uncertainty > 0.5 else ("state_residual" if recovery else "prediction_consistent")
    return ResidualAttributionV0(
        mean_track_position_error=mean_error, predicted_progress=prediction.task_progress,
        observed_progress=observed_progress, uncertainty=prediction.uncertainty,
        recovery_required=recovery, reason=reason,
    )


@dataclass(frozen=True)
class MockStudentWorldModel:
    """Deterministic test double, not a claim of learned dynamics."""

    prediction: StudentPredictionV0

    def predict(
        self, observation: ObservationV0, task: TaskSpecV0, candidate: CandidateSkillV0, action: ActionTrajectoryV0
    ) -> StudentPredictionV0:
        del observation, task, candidate, action
        return self.prediction
