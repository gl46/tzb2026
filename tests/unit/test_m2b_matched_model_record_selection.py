from __future__ import annotations

import pytest

from m2b.select_matched_model_records import FAILURES, select_matched


def records(per_failure: int, *, fc: bool) -> list[dict[str, object]]:
    rows = []
    for failure in FAILURES:
        for index in reversed(range(per_failure)):
            rows.append(
                {
                    "sample_id": f"{failure.lower()}-{index:02d}",
                    "episode_id": f"episode-{failure.lower()}-{index:02d}",
                    "failure_type": failure,
                    "split": "val",
                    "registry_sha256": "a" * 64,
                    "confidence": 1.0 if fc else 0.0,
                }
            )
    return rows


def test_selection_is_matched_and_lexicographic_not_metric_based() -> None:
    quotas = {"EMPTY_GRASP": 5, "WRONG_OBJECT": 5, "RELEASE_FAILURE": 10}
    no_fc, fc = select_matched(
        records(10, fc=False),
        records(10, fc=True),
        quotas=quotas,
    )
    assert [row["sample_id"] for row in no_fc] == [row["sample_id"] for row in fc]
    assert len(fc) == 20
    assert [row["sample_id"] for row in fc if row["failure_type"] == "EMPTY_GRASP"] == [
        f"empty_grasp-{index:02d}" for index in range(5)
    ]


def test_selection_rejects_too_few_or_unmatched_records() -> None:
    with pytest.raises(ValueError, match="at least 20"):
        select_matched(
            records(10, fc=False),
            records(10, fc=True),
            quotas={failure: 1 for failure in FAILURES},
        )
    fc = records(10, fc=True)
    fc.pop()
    with pytest.raises(ValueError, match="sample sets differ"):
        select_matched(
            records(10, fc=False),
            fc,
            quotas={"EMPTY_GRASP": 5, "WRONG_OBJECT": 5, "RELEASE_FAILURE": 10},
        )
