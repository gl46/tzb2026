from __future__ import annotations

import json
from math import nan

import pytest
from pydantic import ValidationError

from xh_agent.contracts.models import (
    CONTRACT_MODELS,
    ActionTrajectoryV0,
    CandidateSkillV0,
    EpisodeTransitionV0,
    ObjectTrackV0,
    ObservationV0,
    SimulatorSupervisionV0,
    TaskSpecV0,
    TeacherRequestV0,
)
from xh_agent.world_state import MockStudentWorldModel, StudentPredictionV0, attribute_residual, rank_candidates
from xh_agent.baselines.b1 import ExecutionEvent, run_b1


def observation(step: int = 0) -> ObservationV0:
    return ObservationV0(
        episode_id="e1", step_id=step, timestamp_ns=1 + step, rgb_uri="data://rgb.png",
        depth_uri="data://depth.png", camera_intrinsics=[1.0] * 9, camera_extrinsics=[1.0] * 16,
        joint_position=[0.0] * 7, joint_velocity=[0.0] * 7, end_effector_pose=[0.0] * 7,
        gripper_state="open", object_tracks=[ObjectTrackV0(object_id="cube", category="cube", pose=[0.0] * 7, confidence=0.7)],
        current_task_id="task", coordinate_frame="world", uncertainty=0.2,
    )


def task() -> TaskSpecV0:
    return TaskSpecV0(task_id="task", operation="pick_place", target_object_id="cube", reference_frame="world",
                      destination="bin", goal_predicates=["in:bin"], ambiguity_score=0.0,
                      need_clarification=False, source_instruction="put cube in bin")


def trajectory(**overrides: object) -> ActionTrajectoryV0:
    data: dict[str, object] = dict(embodiment="panda", representation="ee_delta", coordinate_frame="world",
        units="m_rad", fps=20.0, values=[[0.0, 0.0], [0.1, 0.0]], dimension_names=["x", "yaw"],
        normalization_method="identity", normalization_revision="v1", source_skill="MOVE", source_policy="B1")
    data.update(overrides)
    return ActionTrajectoryV0(**data)


def supervision() -> SimulatorSupervisionV0:
    return SimulatorSupervisionV0(perfect_object_poses={"cube": [0.0] * 7}, task_success=False,
                                  simulator="Gazebo", simulator_version="Harmonic")


def request() -> TeacherRequestV0:
    return TeacherRequestV0(candidate_model="test", checkpoint_revision="r1", conditioning_observation=observation(),
                            action_trajectory=trajectory(), prompt="predict", seed=1, action_domain="ee_delta",
                            action_mapping_revision="franka-v1")


def test_every_contract_has_json_schema() -> None:
    assert len(CONTRACT_MODELS) == 9
    for model in CONTRACT_MODELS.values():
        assert json.loads(json.dumps(model.model_json_schema()))["type"] == "object"


def test_json_round_trip_and_optional_teacher_response() -> None:
    transition = EpisodeTransitionV0(
        observation_before=observation(), task_spec=task(),
        candidate_skill=CandidateSkillV0(skill_type="MOVE", target_object_id="cube", coordinate_frame="world", generated_by="B1", candidate_id="c1"),
        action_trajectory=trajectory(), observation_after=observation(1), simulator_supervision=supervision(),
        task_progress=0.2, provenance={"source": "sim"},
    )
    assert EpisodeTransitionV0.model_validate_json(transition.model_dump_json()).teacher_response is None


def test_observation_rejects_privileged_truth() -> None:
    data = observation().model_dump()
    data["task_success"] = True
    with pytest.raises(ValidationError):
        ObservationV0.model_validate(data)


def test_simulator_supervision_requires_training_only_marker() -> None:
    data = supervision().model_dump()
    data["training_and_evaluation_only"] = False
    with pytest.raises(ValidationError):
        SimulatorSupervisionV0.model_validate(data)


def test_action_rejects_non_rectangular_and_nonfinite() -> None:
    with pytest.raises(ValidationError):
        trajectory(values=[[0.0]], dimension_names=["x", "y"])
    with pytest.raises(ValidationError):
        trajectory(values=[[nan, 0.0]])


def test_real_teacher_rejects_unknown_mapping() -> None:
    invalid = request().model_copy(update={"action_mapping_revision": "UNKNOWN"})
    with pytest.raises(ValueError):
        invalid.validate_for_real_teacher()
    invalid_action = trajectory(coordinate_frame="UNKNOWN")
    with pytest.raises(ValueError):
        invalid_action.validate_real_teacher_mapping()


def test_student_boundary_ranks_without_supervision_and_attributes_residual() -> None:
    candidate = CandidateSkillV0(skill_type="PLACE", target_object_id="cube", coordinate_frame="world", generated_by="B1", candidate_id="place")
    prediction = StudentPredictionV0(
        future_object_tracks=[ObjectTrackV0(object_id="cube", category="cube", pose=[0.1, 0.0, 0.0, 0, 0, 0, 1], confidence=.5)],
        contact_probability=.8, grasp_probability=.7, collision_probability=.1, slip_probability=.1,
        task_progress=.8, uncertainty=.2, provenance="mock",
    )
    model = MockStudentWorldModel(prediction)
    result = model.predict(observation(), task(), candidate, trajectory())
    ranked = rank_candidates([(candidate, result)])
    assert ranked[0].accepted and ranked[0].candidate_id == "place"
    after = observation(1).model_copy(update={"object_tracks": [ObjectTrackV0(object_id="cube", category="cube", pose=[0.2, 0.0, 0.0, 0, 0, 0, 1], confidence=.5)]})
    residual = attribute_residual(result, after, observed_progress=.1, residual_threshold_m=.05)
    assert residual.recovery_required and residual.reason == "state_residual"


def test_b1_selects_one_explicit_recovery_for_an_execution_event() -> None:
    result = run_b1(task(), execution_event=ExecutionEvent.EMPTY_GRASP)
    assert result.status == "RECOVERY_REQUIRED"
    assert result.recovery_skill is not None
    assert result.recovery_skill.skill_type.value == "REGRASP"
