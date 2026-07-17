from __future__ import annotations

import pytest
from pydantic import ValidationError

from xh_agent.agent.closed_loop import record_step
from xh_agent.agent.skill_planner import plan
from xh_agent.recovery.manager import recovery_for
from xh_agent.task_compiler.deterministic import DeterministicTaskCompiler


@pytest.mark.parametrize("instruction,selector,destination", [
    ("把最左边的红色零件放进蓝色料箱。", "minimum_world_x_in_camera_calibrated_table_frame", "blue_bin"),
    ("把倒放的圆柱以正常姿态放入第二排第三格。", "orientation_inverted", "blue_bin_row_2_col_3"),
    ("优先把零件最多区域的零件装箱。", "argmax_region_track_count_then_leftmost", "blue_bin"),
])
def test_deterministic_compiler_supports_required_instructions(instruction: str, selector: str, destination: str) -> None:
    task = DeterministicTaskCompiler().compile(instruction)
    assert task.target_selector == selector
    assert task.destination == destination
    assert task.need_clarification is False
    assert "actual_sim_entity_id" not in task.model_dump_json()


def test_unknown_instruction_requests_clarification() -> None:
    task = DeterministicTaskCompiler().compile("随便放一个进去")
    assert task.need_clarification is True
    assert plan(task) == ["Observe", "AskClarification"]


def test_step_requires_a_fresh_observation_and_compares_expected_actual() -> None:
    step = record_step(step_id=1, skill="Approach", before_id="obs-1", before_timestamp_ns=1, after_id="obs-2", after_timestamp_ns=2, actual={"target_visible": True, "collision_free": True}, command_ref="trajectory://approach")
    assert step.comparison == "SUCCESS"
    with pytest.raises(ValidationError):
        step.model_copy(update={"observation_after_id": "obs-1"}).model_validate(step.model_copy(update={"observation_after_id": "obs-1"}).model_dump())


@pytest.mark.parametrize("failure_type", ["EMPTY_GRASP", "UNSTABLE_OR_WRONG_PLACEMENT", "RELEASE_FAILURE"])
def test_recovery_changes_parameters_and_has_bounded_retry(failure_type: str) -> None:
    recovery = recovery_for(failure_type)
    assert recovery.changed_parameters
    assert recovery.retry_budget == 2
    assert "cleanup" not in " ".join(recovery.recovery_subgoals).lower()
