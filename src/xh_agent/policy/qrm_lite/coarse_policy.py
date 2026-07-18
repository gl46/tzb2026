"""Coarse skill / intent head on top of context features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from xh_agent.policy.qrm_lite.contracts import CoarseIntentV1, FailureType


DEFAULT_SKILLS = [
    "OBSERVE",
    "APPROACH",
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REGRASP",
    "REOBSERVE",
    "STOP",
]

DEFAULT_GRASP_FAMILIES = ["unknown", "top_down", "side", "corner", "industrial_detachable"]
DEFAULT_RECOVERY = ["none", "retry_same", "reobserve", "regrasp", "backoff"]


@dataclass
class CoarseLabelSpace:
    skills: list[str]
    grasp_families: list[str]
    recovery_modes: list[str]
    n_trans_bins: int = 5
    n_rot_bins: int = 5

    @property
    def out_dim(self) -> int:
        # skill + grasp + recovery + reobserve + 3 trans bins + 3 rot bins + failure aux
        return (
            len(self.skills)
            + len(self.grasp_families)
            + len(self.recovery_modes)
            + 1
            + 3 * self.n_trans_bins
            + 3 * self.n_rot_bins
            + len(FailureType)
        )


def default_label_space(n_trans_bins: int = 5, n_rot_bins: int = 5) -> CoarseLabelSpace:
    return CoarseLabelSpace(
        skills=list(DEFAULT_SKILLS),
        grasp_families=list(DEFAULT_GRASP_FAMILIES),
        recovery_modes=list(DEFAULT_RECOVERY),
        n_trans_bins=n_trans_bins,
        n_rot_bins=n_rot_bins,
    )


def _onehot(index: int, n: int) -> np.ndarray:
    v = np.zeros((n,), dtype=np.float64)
    if 0 <= index < n:
        v[index] = 1.0
    return v


def _bin_index(value: float, n_bins: int, low: float, high: float) -> int:
    if n_bins <= 1:
        return 0
    x = min(max(value, low), high - 1e-9)
    width = (high - low) / n_bins
    return int((x - low) / width)


def encode_coarse_intent(intent: CoarseIntentV1, space: CoarseLabelSpace | None = None) -> np.ndarray:
    space = space or default_label_space()
    skill_i = space.skills.index(intent.skill_type) if intent.skill_type in space.skills else 0
    grasp_i = (
        space.grasp_families.index(intent.grasp_family)
        if intent.grasp_family in space.grasp_families
        else 0
    )
    rec_i = (
        space.recovery_modes.index(intent.recovery_mode)
        if intent.recovery_mode in space.recovery_modes
        else 0
    )
    parts = [
        _onehot(skill_i, len(space.skills)),
        _onehot(grasp_i, len(space.grasp_families)),
        _onehot(rec_i, len(space.recovery_modes)),
        np.asarray([1.0 if intent.reobserve_flag else 0.0], dtype=np.float64),
    ]
    # translation / rotation bins: use provided lists or zeros
    for axis in range(3):
        if axis < len(intent.coarse_translation_bins):
            parts.append(_onehot(int(intent.coarse_translation_bins[axis]), space.n_trans_bins))
        else:
            parts.append(_onehot(space.n_trans_bins // 2, space.n_trans_bins))
    for axis in range(3):
        if axis < len(intent.coarse_rotation_bins):
            parts.append(_onehot(int(intent.coarse_rotation_bins[axis]), space.n_rot_bins))
        else:
            parts.append(_onehot(space.n_rot_bins // 2, space.n_rot_bins))
    fail = intent.failure_type_aux or FailureType.NONE
    fail_types = list(FailureType)
    fail_i = fail_types.index(fail) if fail in fail_types else fail_types.index(FailureType.UNKNOWN)
    parts.append(_onehot(fail_i, len(fail_types)))
    return np.concatenate(parts, axis=0)


def decode_coarse_intent(vec: np.ndarray, space: CoarseLabelSpace | None = None) -> CoarseIntentV1:
    space = space or default_label_space()
    x = np.asarray(vec, dtype=np.float64).reshape(-1)
    o = 0

    def take(n: int) -> np.ndarray:
        nonlocal o
        sl = x[o : o + n]
        o += n
        return sl

    skill_i = int(np.argmax(take(len(space.skills))))
    grasp_i = int(np.argmax(take(len(space.grasp_families))))
    rec_i = int(np.argmax(take(len(space.recovery_modes))))
    reobs = float(take(1)[0]) >= 0.5
    t_bins = [int(np.argmax(take(space.n_trans_bins))) for _ in range(3)]
    r_bins = [int(np.argmax(take(space.n_rot_bins))) for _ in range(3)]
    fail_i = int(np.argmax(take(len(FailureType))))
    return CoarseIntentV1(
        skill_type=space.skills[skill_i],
        grasp_family=space.grasp_families[grasp_i],
        recovery_mode=space.recovery_modes[rec_i],
        reobserve_flag=reobs,
        coarse_translation_bins=t_bins,
        coarse_rotation_bins=r_bins,
        failure_type_aux=list(FailureType)[fail_i],
    )


class CoarsePolicyHead:
    """Pure-numpy MLP coarse head (torch optional via train script)."""

    def __init__(self, in_dim: int, space: CoarseLabelSpace | None = None, hidden: int = 256) -> None:
        self.space = space or default_label_space()
        self.in_dim = in_dim
        self.hidden = hidden
        self.out_dim = self.space.out_dim
        rng = np.random.default_rng(0)
        s1 = np.sqrt(2.0 / (in_dim + hidden))
        s2 = np.sqrt(2.0 / (hidden + self.out_dim))
        self.w1 = rng.normal(0, s1, size=(in_dim, hidden))
        self.b1 = np.zeros((hidden,))
        self.w2 = rng.normal(0, s2, size=(hidden, self.out_dim))
        self.b2 = np.zeros((self.out_dim,))

    def forward(self, x: np.ndarray) -> np.ndarray:
        x = np.nan_to_num(np.asarray(x, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        h = np.tanh(np.clip(x @ self.w1 + self.b1, -20.0, 20.0))
        return h @ self.w2 + self.b2

    def predict_intent(self, x: np.ndarray) -> CoarseIntentV1:
        logits = self.forward(x.reshape(1, -1))[0]
        return decode_coarse_intent(logits, self.space)

    def state_dict(self) -> dict[str, Any]:
        return {
            "w1": self.w1,
            "b1": self.b1,
            "w2": self.w2,
            "b2": self.b2,
            "in_dim": self.in_dim,
            "hidden": self.hidden,
            "space": {
                "skills": self.space.skills,
                "grasp_families": self.space.grasp_families,
                "recovery_modes": self.space.recovery_modes,
                "n_trans_bins": self.space.n_trans_bins,
                "n_rot_bins": self.space.n_rot_bins,
            },
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.w1 = np.asarray(state["w1"])
        self.b1 = np.asarray(state["b1"])
        self.w2 = np.asarray(state["w2"])
        self.b2 = np.asarray(state["b2"])
        self.in_dim = int(state["in_dim"])
        self.hidden = int(state["hidden"])
        sp = state["space"]
        self.space = CoarseLabelSpace(
            skills=list(sp["skills"]),
            grasp_families=list(sp["grasp_families"]),
            recovery_modes=list(sp["recovery_modes"]),
            n_trans_bins=int(sp["n_trans_bins"]),
            n_rot_bins=int(sp["n_rot_bins"]),
        )
        self.out_dim = self.space.out_dim


def translation_bins_from_delta(dx: float, dy: float, dz: float, n_bins: int = 5) -> list[int]:
    return [
        _bin_index(dx, n_bins, -0.1, 0.1),
        _bin_index(dy, n_bins, -0.1, 0.1),
        _bin_index(dz, n_bins, -0.1, 0.1),
    ]
