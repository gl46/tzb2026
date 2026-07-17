"""Deterministic Chinese instruction compiler for the limited M1B-beta scope."""

from __future__ import annotations

from .base import TaskSpecV1


class DeterministicTaskCompiler:
    backend = "deterministic"

    def compile(self, instruction: str, *, task_id: str = "m1b-beta-task") -> TaskSpecV1:
        common = {
            "task_id": task_id,
            "raw_instruction": instruction,
            "operation": "pick_place",
            "target_track_id_optional": None,
            "subgoals": ["Observe", "Approach", "Grasp", "Lift", "Transport", "Place", "Release", "Retreat"],
            "constraints": ["perceive_after_each_major_skill", "no_simulator_identity"],
            "compiler_backend": self.backend,
        }
        if "最左边" in instruction and "红色" in instruction and "蓝色料箱" in instruction:
            return TaskSpecV1(**common, target_query="red industrial cylinder", target_attributes={"color": "red", "category": "industrial_cylinder"}, target_selector="minimum_world_x_in_camera_calibrated_table_frame", destination="blue_bin", orientation_requirement="any", priority_rule="leftmost", ambiguity=0.0, need_clarification=False, compiler_evidence=["matched:leftmost", "matched:red", "matched:blue_bin"])
        if "倒放" in instruction and "第二排第三格" in instruction:
            return TaskSpecV1(**common, target_query="inverted industrial cylinder", target_attributes={"orientation": "inverted", "category": "industrial_cylinder"}, target_selector="orientation_inverted", destination="blue_bin_row_2_col_3", orientation_requirement="normal", priority_rule="first_confident_match", ambiguity=0.15, need_clarification=False, compiler_evidence=["matched:inverted", "matched:row_2_col_3", "orientation_requires_reobserve"])
        if "零件最多区域" in instruction and "装箱" in instruction:
            return TaskSpecV1(**common, target_query="industrial cylinder in densest incoming region", target_attributes={"category": "industrial_cylinder"}, target_selector="argmax_region_track_count_then_leftmost", destination="blue_bin", orientation_requirement="any", priority_rule="region_count_descending", ambiguity=0.1, need_clarification=False, compiler_evidence=["matched:region_count", "reference:incoming_a_vs_incoming_b"])
        clarification_common = {key: value for key, value in common.items() if key != "subgoals"}
        return TaskSpecV1(**clarification_common, target_query="unresolved", target_attributes={}, target_selector="none", destination="unresolved", orientation_requirement="unknown", priority_rule="ask_clarification", subgoals=["Observe", "AskClarification"], ambiguity=1.0, need_clarification=True, compiler_evidence=["no_supported_instruction_pattern"])
