"""Offline evaluator.  Truth stays in this module's private label objects."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .interfaces import PerceptionResultV1


@dataclass(frozen=True)
class SimulatorLabel:
    actual_sim_entity_id: str
    position_3d: tuple[float, float, float]
    orientation_state: str


def evaluate(predictions: list[PerceptionResultV1], labels: list[SimulatorLabel]) -> dict[str, float]:
    """Compute aggregate metrics without ever adding truth to online results."""
    count = min(len(predictions), len(labels))
    if count == 0:
        return {"valid_output_rate": 0.0, "position_median_error_m": float("inf"), "orientation_accuracy": 0.0}
    errors = [sum((prediction.position_3d[index] - label.position_3d[index]) ** 2 for index in range(3)) ** 0.5 for prediction, label in zip(predictions, labels)]
    orientation = sum(prediction.orientation_state == label.orientation_state for prediction, label in zip(predictions, labels)) / count
    return {"valid_output_rate": count / len(labels), "position_median_error_m": median(errors), "orientation_accuracy": orientation}
