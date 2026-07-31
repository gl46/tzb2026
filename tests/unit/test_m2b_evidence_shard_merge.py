from __future__ import annotations

from pathlib import Path

import pytest

from m2b.build_prospective_runtime_decisions import (
    IsolatedIsaacPreflightManifestV1,
)
from m2b.merge_isolated_preflight_shards import (
    merge_shards as merge_preflights,
)
from m2b.merge_matched_closed_loop_shards import (
    merge_shards as merge_closed_loop,
)
from m2b.run_matched_closed_loop_batch import baseline_episode
from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    PhysicalRuntimeGateReceiptV1,
)


DIGEST = "a" * 64


def receipt() -> PhysicalRuntimeGateReceiptV1:
    return PhysicalRuntimeGateReceiptV1(
        failure_type="EMPTY_GRASP",
        recovery_skill="REOBSERVE",
        runtime_action="HOLD_AND_CAPTURE_PUBLIC_RGBD",
        ik_gate="NOT_APPLICABLE",
        collision_gate="NOT_APPLICABLE",
        safety_gate="PASS",
        physical_recovery_success=True,
        details={"source": "TEST"},
    )


def preflight(sample_id: str) -> IsolatedIsaacPreflightManifestV1:
    return IsolatedIsaacPreflightManifestV1(
        sample_id=sample_id,
        failure_type="EMPTY_GRASP",
        source_hashes={"scene.sdf": DIGEST},
        preflight_evidence_path=f"/evidence/{sample_id}.json",
        preflight_evidence_sha256=DIGEST,
        receipt=receipt(),
    )


def write_preflight(path: Path, item: IsolatedIsaacPreflightManifestV1) -> None:
    path.write_text(item.model_dump_json() + "\n")


def test_preflight_shards_merge_in_stable_sample_order(tmp_path: Path) -> None:
    second = tmp_path / "gpu1.jsonl"
    first = tmp_path / "gpu0.jsonl"
    write_preflight(second, preflight("sample-2"))
    write_preflight(first, preflight("sample-1"))
    merged = merge_preflights([second, first])
    assert [item.sample_id for item in merged] == ["sample-1", "sample-2"]


def test_preflight_shards_reject_duplicate_samples(tmp_path: Path) -> None:
    first = tmp_path / "gpu0.jsonl"
    second = tmp_path / "gpu1.jsonl"
    write_preflight(first, preflight("sample-1"))
    write_preflight(second, preflight("sample-1"))
    with pytest.raises(ValueError, match="duplicate preflight sample IDs"):
        merge_preflights([first, second])


def closed_episode(key: str, scene_seed: int):
    return baseline_episode(
        key=key,
        scene_seed=scene_seed,
        failure_type="EMPTY_GRASP",
        recovery_sequence=["REOBSERVE"],
        previous_failed_skill="GRASP",
        receipt=receipt(),
        evidence_sha256=DIGEST,
        elapsed_s=2.0,
    )


def write_closed_shard(
    episode_path: Path, journal_path: Path, *, key: str, scene_seed: int
) -> None:
    episode = closed_episode(key, scene_seed)
    episode_path.write_text(episode.model_dump_json() + "\n")
    journal_path.write_text(
        "{"
        f'"schema_version":"M2BClosedLoopExecutionJournalV1",'
        f'"episode_id":"{episode.episode_id}",'
        '"method":"B0",'
        f'"matched_key":"{key}",'
        '"status":"EVALUATION_EXECUTION_RECORDED",'
        '"execution_evidence_path":"/evidence/eval.json",'
        f'"execution_evidence_sha256":"{DIGEST}",'
        '"privileged_truth_policy_input":false,'
        '"teacher_used":false}'
        "\n"
    )


def test_closed_loop_shards_merge_with_execution_journals(
    tmp_path: Path,
) -> None:
    ep0, journal0 = tmp_path / "ep0.jsonl", tmp_path / "journal0.jsonl"
    ep1, journal1 = tmp_path / "ep1.jsonl", tmp_path / "journal1.jsonl"
    write_closed_shard(ep0, journal0, key="m2b-match-0", scene_seed=4000)
    write_closed_shard(ep1, journal1, key="m2b-match-1", scene_seed=4001)
    episodes, journals = merge_closed_loop(
        [ep1, ep0], [journal1, journal0]
    )
    assert [item.matched_key for item in episodes] == [
        "m2b-match-0",
        "m2b-match-1",
    ]
    assert [item["episode_id"] for item in journals] == [
        item.episode_id for item in episodes
    ]


def test_closed_loop_shards_reject_cross_shard_duplicates(
    tmp_path: Path,
) -> None:
    ep0, journal0 = tmp_path / "ep0.jsonl", tmp_path / "journal0.jsonl"
    ep1, journal1 = tmp_path / "ep1.jsonl", tmp_path / "journal1.jsonl"
    write_closed_shard(ep0, journal0, key="m2b-match-0", scene_seed=4000)
    write_closed_shard(ep1, journal1, key="m2b-match-0", scene_seed=4000)
    with pytest.raises(ValueError, match="across shards"):
        merge_closed_loop([ep0, ep1], [journal0, journal1])
