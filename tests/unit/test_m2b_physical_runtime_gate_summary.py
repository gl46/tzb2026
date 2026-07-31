from __future__ import annotations

from m2b.summarize_physical_runtime_gates import summarize


def row(failure: str, passing: bool) -> dict[str, object]:
    return {
        "receipt": {
            "failure_type": failure,
            "complete_and_passing": passing,
        }
    }


def test_summary_never_promotes_post_execution_rate_to_runtime_mapping() -> None:
    report = summarize(
        [
            row("WRONG_OBJECT", True),
            row("RELEASE_FAILURE", True),
            row("RELEASE_FAILURE", False),
        ]
    )
    assert report["receipts_valid"] == 3
    assert report["receipts_complete_and_passing"] == 2
    assert report["post_execution_gate_rate"] == 2 / 3
    assert report["runtime_mapping_rate"] is None
    assert report["model_selected_decisions"] == 0
    assert report["teacher_used"] is False
