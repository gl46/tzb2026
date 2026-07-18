"""Minimal empty-grasp recovery closed-loop protocol for Beta-1 (20 episodes).

Model only chooses recovery skill after injected empty-grasp. Continuous motion:
geometric nominal + MLP residual + MoveIt/contact gate (not bypassed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from xh_agent.policy.qrm_lite.contracts import FailureContextV1, FailureType, QRMObservationV1
from xh_agent.policy.qrm_lite.metrics_beta1 import RecoveryEvent
from xh_agent.policy.qrm_lite.models_q012 import RECOVERY_SKILLS, FormalModelId, FormalPolicy, ModelOutput


RecoverySkill = Literal[
    "REOBSERVE",
    "RETRY_TOP",
    "ALTERNATE_OBLIQUE",
    "ALTERNATE_SIDE",
    "ABORT_SAFE",
]


@dataclass
class RecoveryEpisodeResult:
    episode_id: str
    model_id: str
    injected_failure: str
    first_action: str
    recovery_skill: str
    repeated_same_failed_action: bool
    moveit_rejected: bool
    success: bool | None
    attempts: int
    latency_ms: float | None = None
    notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryLoopConfig:
    n_episodes: int = 20
    n_q1: int = 10
    n_q2: int = 10
    first_action: str = "RETRY_TOP"  # initial top grasp that will fail via injection
    inject_failure: str = "EMPTY_GRASP"


class EmptyGraspRecoveryProtocol:
    """Orchestrates: top grasp → inject empty-grasp → reobserve → QRM recovery skill → execute."""

    def __init__(
        self,
        q1: FormalPolicy,
        q2: FormalPolicy,
        *,
        execute_fn: Callable[[str, QRMObservationV1, ModelOutput], dict[str, Any]] | None = None,
        clock_ms: Callable[[], float] | None = None,
    ) -> None:
        assert q1.model_id == FormalModelId.Q1
        assert q2.model_id == FormalModelId.Q2
        self.q1 = q1
        self.q2 = q2
        self.execute_fn = execute_fn or self._dry_execute
        self.clock_ms = clock_ms or (lambda: 0.0)

    @staticmethod
    def _dry_execute(skill: str, obs: QRMObservationV1, out: ModelOutput) -> dict[str, Any]:
        # Offline/dry path for unit tests without Gazebo.
        success = skill in {"ALTERNATE_SIDE", "ALTERNATE_OBLIQUE", "REOBSERVE"}
        return {
            "success": success,
            "moveit_rejected": False,
            "executed_skill": skill,
            "dry_run": True,
        }

    def _obs_after_empty_grasp(self, episode_id: str, seed: int) -> QRMObservationV1:
        return QRMObservationV1(
            episode_id=episode_id,
            step_id=1,
            instruction="recover after empty grasp on random cube/cylinder",
            rgb_uri=f"sim://{episode_id}/post_fail_rgb.png",
            current_skill_stage="REOBSERVE",
            joint_position=[0.0] * 8,
            end_effector_pose_base=[0.4, 0.0, 0.35, 1, 0, 0, 0],
            gripper_state=0.2,
            failure_context=FailureContextV1(
                last_skill="GRASP",
                expected_predicates=["grasped"],
                observed_predicates=[],
                predicate_residual=["missing:grasped"],
                failure_type=FailureType.EMPTY_GRASP,
                retry_count=1,
                attempted_recoveries=["RETRY_TOP"],
                last_action_summary="GRASP:top_down",
                last_target_track_id="track-object-0",
            ),
        )

    def run_episode(self, policy: FormalPolicy, episode_id: str, seed: int = 0) -> RecoveryEpisodeResult:
        obs = self._obs_after_empty_grasp(episode_id, seed)
        t0 = self.clock_ms()
        # nominal identity residual path for dry/unit; real loop supplies MoveIt nominal
        import numpy as np
        from xh_agent.policy.qrm_lite.transforms import build_identity_action_chunk

        nominal = build_identity_action_chunk(4)
        out = policy.predict(obs, nominal=nominal)
        latency = self.clock_ms() - t0
        skill = out.recovery_skill or (out.coarse.skill_type if out.coarse else "ABORT_SAFE")
        if skill not in RECOVERY_SKILLS:
            # map coarse recovery_mode / skill into allowed set
            if out.coarse and out.coarse.reobserve_flag:
                skill = "REOBSERVE"
            elif skill in {"GRASP", "REGRASP"}:
                skill = "RETRY_TOP"
            else:
                skill = "REOBSERVE"
        exec_res = self.execute_fn(skill, obs, out)
        first = "RETRY_TOP"
        return RecoveryEpisodeResult(
            episode_id=episode_id,
            model_id=policy.model_id.value,
            injected_failure="EMPTY_GRASP",
            first_action=first,
            recovery_skill=skill,
            repeated_same_failed_action=(skill == first),
            moveit_rejected=bool(exec_res.get("moveit_rejected")),
            success=exec_res.get("success"),
            attempts=1 + int(obs.failure_context.retry_count),
            latency_ms=latency,
            notes=["dry_run"] if exec_res.get("dry_run") else [],
            raw={"model_meta": out.meta, "exec": exec_res, "used_failure_context": out.used_failure_context},
        )

    def run_suite(self, cfg: RecoveryLoopConfig | None = None) -> dict[str, Any]:
        cfg = cfg or RecoveryLoopConfig()
        results: list[RecoveryEpisodeResult] = []
        for i in range(cfg.n_q1):
            results.append(self.run_episode(self.q1, f"beta1-q1-empty-{i+1:02d}", seed=i))
        for i in range(cfg.n_q2):
            results.append(self.run_episode(self.q2, f"beta1-q2-empty-{i+1:02d}", seed=100 + i))
        q1_events = [
            RecoveryEvent(
                episode_id=r.episode_id,
                failure_type=r.injected_failure,
                previous_action=r.first_action,
                chosen_action=r.recovery_skill,
                model_id=r.model_id,
                success=r.success,
            )
            for r in results
            if r.model_id == FormalModelId.Q1.value
        ]
        q2_events = [
            RecoveryEvent(
                episode_id=r.episode_id,
                failure_type=r.injected_failure,
                previous_action=r.first_action,
                chosen_action=r.recovery_skill,
                model_id=r.model_id,
                success=r.success,
            )
            for r in results
            if r.model_id == FormalModelId.Q2.value
        ]
        from xh_agent.policy.qrm_lite.metrics_beta1 import compare_q1_q2

        return {
            "config": {
                "n_q1": cfg.n_q1,
                "n_q2": cfg.n_q2,
                "inject_failure": cfg.inject_failure,
            },
            "results": [r.__dict__ for r in results],
            "q1_vs_q2": compare_q1_q2(q1_events, q2_events),
            "moveit_reject_rate": sum(1 for r in results if r.moveit_rejected) / max(len(results), 1),
            "mean_attempts": sum(r.attempts for r in results) / max(len(results), 1),
        }
