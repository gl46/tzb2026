from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from test_m2c_formal_isaac_endpoint_v4 import _execute_request, _observations
from m2c.formal_isaac_raw_source_v4 import (
    PUBLIC_GRIPPER_CLOSED_MAX_WIDTH_M,
    FormalIsaacRawPublicFrameSourceV4Real,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    ModelDecisionExecutionReceiptV4,
)


SOURCE_SHA256 = "a" * 64


class _Robot:
    def is_physics_tensor_entity_valid(self) -> bool:
        return True

    def get_dof_positions(self) -> list[list[float]]:
        return [[0.0] * 7 + [0.001, 0.001]]


class _App:
    def __init__(self) -> None:
        self.calls = 0

    def update(self) -> None:
        self.calls += 1


class _Probe:
    def __init__(self) -> None:
        self.simulation_app = _App()

    @staticmethod
    def _live_pose(_hand: object) -> tuple[list[float], list[float]]:
        return [0.1, 0.2, 0.3], [1.0, 0.0, 0.0, 0.0]

    @staticmethod
    def _array_or_list(value: Any) -> Any:
        return value


class _Scene:
    def __init__(self) -> None:
        self.probe = _Probe()
        self.robot = _Robot()
        self.hand_prim = object()
        self.source: FormalIsaacRawPublicFrameSourceV4Real | None = None
        self.closed = False
        self.run_id: str | None = None
        self.session_id: str | None = None
        self.previous_completed_at_ns = 0

    def _capture_public(self, *, decision_index: int, label: str) -> dict[str, Any]:
        del decision_index, label
        assert self.source is not None
        self.source._record_proprioception_sample()
        rgb = b"rgb"
        depth = b"depth"
        result = SimpleNamespace(
            category="industrial_cylinder",
            attributes={"visual_color": "yellow"},
            position_3d=[0.1, 0.2, 0.5],
            confidence=0.95,
            bbox_or_mask=SimpleNamespace(x=1, y=2, width=3, height=4),
            visibility=1.0,
            covariance_or_quality={"depth_support": 1.0},
        )
        return {
            "unassociated_public_results": (result,),
            "rgb_uri": "dataset://formal/rgb.png",
            "depth_uri": "dataset://formal/depth.npy",
            "rgb_sha256": hashlib.sha256(rgb).hexdigest(),
            "depth_sha256": hashlib.sha256(depth).hexdigest(),
            "rgb_bytes": rgb,
            "depth_bytes": depth,
        }

    def close(self) -> None:
        self.closed = True


def _source(timestamps: list[int]) -> FormalIsaacRawPublicFrameSourceV4Real:
    source = object.__new__(FormalIsaacRawPublicFrameSourceV4Real)
    source.implementation_sha256 = SOURCE_SHA256
    source._scene = _Scene()
    source._scene.source = source
    source._proprioception = []
    source._last_timestamp_ns = 0
    source._last_policy_capture_at_ns = None
    source._active_identity = None
    source._next_capture_index = -1
    source._next_execution_index = 0
    source._pending_public_skill = None
    source._last_execution_completed_at_ns = 0
    source._closed = False
    iterator = iter(timestamps)
    source._ordered_now_ns = lambda: next(iterator)  # type: ignore[method-assign]
    return source


def _receipt(
    *,
    skill: str,
    started_at_ns: int,
    completed_at_ns: int,
    robot_actuation: bool,
) -> ModelDecisionExecutionReceiptV4:
    payload: dict[str, Any] = {
        "schema_version": "ModelDecisionExecutionReceiptV4",
        "receipt_id": "session-execution-0",
        "selected_skill": skill,
        "execution_source": "MODEL_SELECTED_REGISTERED_SKILL",
        "operation_kind": "ROBOT_ACTUATION" if robot_actuation else "PUBLIC_RGBD_CAPTURE",
        "outcome": "PASS",
        "executed_in_real_isaac": True,
        "robot_actuation_executed": robot_actuation,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "schema_gate": "PASS",
        "stale_track_gate": "PASS",
        "frame_unit_gate": "PASS",
        "ik_gate": "PASS" if robot_actuation else "NOT_RUN",
        "collision_gate": "PASS" if robot_actuation else "NOT_RUN",
        "controller_gate": "PASS" if robot_actuation else "NOT_RUN",
        "safety_gate": "PASS" if robot_actuation else "NOT_RUN",
        "collision_or_safety_violation": False,
        "failure_reason": None,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return ModelDecisionExecutionReceiptV4(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


def _request() -> Any:
    return _execute_request(_observations()[0], index=0).model_copy(
        update={"run_id": "run", "session_id": "session"}
    )


def test_raw_source_binds_real_skill_and_complete_public_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "m2c.formal_isaac_raw_source_v4.require_pre_freeze",
        lambda _action: None,
    )
    source = _source([100, 2_000, 4_000])
    boundary = source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=-1,
        label="FAILURE_BOUNDARY",
        previous_execution_completed_at_ns=0,
    )
    assert boundary.captured_at_ns == 100
    first = source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=0,
        label="POLICY_INPUT",
        previous_execution_completed_at_ns=100,
    )
    assert [item.timestamp_ns for item in first.proprioception_samples] == [2_000]
    receipt = _receipt(
        skill="LIFT",
        started_at_ns=3_000,
        completed_at_ns=3_500,
        robot_actuation=True,
    )
    source.commit_public_execution_v4(request=_request(), receipt=receipt)
    second = source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=1,
        label="POLICY_INPUT",
        previous_execution_completed_at_ns=3_500,
    )
    assert [item.timestamp_ns for item in second.proprioception_samples] == [2_000, 4_000]
    assert second.last_physically_executed_public_skill is not None
    assert second.last_physically_executed_public_skill.skill_name == "LIFT"
    assert second.detections[0].attributes.visual_color == "yellow"
    assert second.teacher_used is False
    assert second.privileged_truth_policy_input is False
    assert source._scene.run_id == "run"
    assert source._scene.session_id == "session"
    assert source._scene.previous_completed_at_ns == 3_500


def test_non_actuating_public_operation_does_not_enable_hand_carry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "m2c.formal_isaac_raw_source_v4.require_pre_freeze",
        lambda _action: None,
    )
    source = _source([100, 2_000, 4_000])
    source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=-1,
        label="FAILURE_BOUNDARY",
        previous_execution_completed_at_ns=0,
    )
    source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=0,
        label="POLICY_INPUT",
        previous_execution_completed_at_ns=100,
    )
    source.commit_public_execution_v4(
        request=_request(),
        receipt=_receipt(
            skill="REOBSERVE",
            started_at_ns=3_000,
            completed_at_ns=3_500,
            robot_actuation=False,
        ),
    )
    frame = source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=1,
        label="POLICY_INPUT",
        previous_execution_completed_at_ns=3_500,
    )
    assert frame.last_physically_executed_public_skill is None


def test_update_recorder_and_execution_commit_are_single_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "m2c.formal_isaac_raw_source_v4.require_pre_freeze",
        lambda _action: None,
    )
    source = _source([100, 2_000, 3_000, 4_000])
    source._install_update_recorder()
    source._scene.probe.simulation_app.update()
    assert len(source._proprioception) == 1
    source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=-1,
        label="FAILURE_BOUNDARY",
        previous_execution_completed_at_ns=0,
    )
    source.capture_raw_public_frame_v4(
        run_id="run",
        session_id="session",
        capture_index=0,
        label="POLICY_INPUT",
        previous_execution_completed_at_ns=2_000,
    )
    receipt = _receipt(
        skill="LIFT",
        started_at_ns=3_500,
        completed_at_ns=3_800,
        robot_actuation=True,
    )
    source.commit_public_execution_v4(request=_request(), receipt=receipt)
    with pytest.raises(ValueError, match="crosses active history"):
        source.commit_public_execution_v4(request=_request(), receipt=receipt)


def test_source_file_is_an_explicit_bound_runtime_surface() -> None:
    source = Path("scripts/m2c/formal_isaac_raw_source_v4.py").read_text()
    assert "FormalIsaacRawPublicFrameSourceV4Real" in source
    assert "unassociated_public_results" in source
    assert "TaskSpec" in source
    assert 'teacher_used": False' in source
    assert 'privileged_truth_policy_input": False' in source
    assert PUBLIC_GRIPPER_CLOSED_MAX_WIDTH_M == 0.002
    assert "M1B" in source and "accepted V4 collection" in source
