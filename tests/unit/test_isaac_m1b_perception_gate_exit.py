from __future__ import annotations

from evaluate_isaac_m1b_perception_gate import gate_exit_code


def test_no_go_is_a_nonzero_process_exit() -> None:
    assert gate_exit_code({"status": "NO_GO"}) == 1


def test_go_and_audit_only_remain_successful_process_exits() -> None:
    assert gate_exit_code({"status": "GO"}) == 0
    assert gate_exit_code({"status": "ACTUAL_ISAAC_RGBD_AUDIT_COMPLETE_GATE_PENDING"}) == 0
