"""Beta-1 offline / closed-loop metrics, including same-failed-action repetition."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass
class RecoveryEvent:
    episode_id: str
    failure_type: str
    previous_action: str
    chosen_action: str
    model_id: str
    success: bool | None = None


def skill_accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    if not y_true:
        return 0.0
    return sum(a == b for a, b in zip(y_true, y_pred)) / len(y_true)


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    labels = sorted(set(y_true) | set(y_pred))
    if not labels:
        return 0.0
    f1s = []
    for lab in labels:
        tp = sum((t == lab and p == lab) for t, p in zip(y_true, y_pred))
        fp = sum((t != lab and p == lab) for t, p in zip(y_true, y_pred))
        fn = sum((t == lab and p != lab) for t, p in zip(y_true, y_pred))
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1s.append(0.0 if (prec + rec) == 0 else 2 * prec * rec / (prec + rec))
    return float(sum(f1s) / len(f1s))


def same_failed_action_repetition_rate(events: Iterable[RecoveryEvent]) -> float:
    """Fraction of recovery decisions that simply repeat the previous failed action.

    This is the most judge-legible Beta-1 metric for FailureContext value.
    """
    ev = list(events)
    if not ev:
        return 0.0
    rep = sum(1 for e in ev if e.chosen_action == e.previous_action)
    return rep / len(ev)


def recovery_top1_accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    return skill_accuracy(y_true, y_pred)


def residual_errors(pred, target) -> dict[str, float]:
    import numpy as np

    p = np.asarray(pred, dtype=np.float64)
    t = np.asarray(target, dtype=np.float64)
    err = p - t
    return {
        "l1": float(np.mean(np.abs(err))),
        "l2": float(np.mean(err**2) ** 0.5),
        "translation_l1": float(np.mean(np.abs(err[..., 0:3]))),
    }


def zero_residual_baseline(target) -> dict[str, float]:
    import numpy as np

    t = np.asarray(target, dtype=np.float64)
    z = np.zeros_like(t)
    return residual_errors(z, t)


def compare_q1_q2(
    q1_events: Sequence[RecoveryEvent],
    q2_events: Sequence[RecoveryEvent],
) -> dict:
    r1 = same_failed_action_repetition_rate(q1_events)
    r2 = same_failed_action_repetition_rate(q2_events)
    return {
        "q1_same_failed_action_repetition_rate": r1,
        "q2_same_failed_action_repetition_rate": r2,
        "relative_reduction": None if r1 == 0 else (r1 - r2) / r1,
        "absolute_reduction": r1 - r2,
        "q1_n": len(q1_events),
        "q2_n": len(q2_events),
        "q1_action_hist": dict(Counter(e.chosen_action for e in q1_events)),
        "q2_action_hist": dict(Counter(e.chosen_action for e in q2_events)),
    }
