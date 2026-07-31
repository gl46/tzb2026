#!/usr/bin/env python3
"""Merge matched closed-loop episode and execution-journal shards."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from m2b.run_matched_closed_loop_batch import validate_journal_episode
from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopEpisodeV1,
)


def merge_shards(
    episode_shards: list[Path],
    journal_shards: list[Path],
) -> tuple[list[M2BClosedLoopEpisodeV1], list[dict[str, Any]]]:
    if len(episode_shards) != len(journal_shards):
        raise ValueError("episode and journal shard counts differ")
    episodes = []
    journals = []
    for episode_path, journal_path in zip(
        episode_shards, journal_shards, strict=True
    ):
        shard_episodes = [
            M2BClosedLoopEpisodeV1.model_validate_json(line)
            for line in episode_path.read_text().splitlines()
            if line.strip()
        ]
        shard_journals = [
            json.loads(line)
            for line in journal_path.read_text().splitlines()
            if line.strip()
        ]
        episode_by_id = {item.episode_id: item for item in shard_episodes}
        journal_by_id = {
            str(item["episode_id"]): item for item in shard_journals
        }
        if len(episode_by_id) != len(shard_episodes):
            raise ValueError(f"{episode_path}: duplicate episode IDs")
        if len(journal_by_id) != len(shard_journals):
            raise ValueError(f"{journal_path}: duplicate episode IDs")
        if set(episode_by_id) != set(journal_by_id):
            raise ValueError("episode and journal shard IDs differ")
        for episode_id, episode in episode_by_id.items():
            validate_journal_episode(journal_by_id[episode_id], episode)
        episodes.extend(shard_episodes)
        journals.extend(shard_journals)
    episode_ids = [episode.episode_id for episode in episodes]
    duplicates = sorted(
        episode_id
        for episode_id in set(episode_ids)
        if episode_ids.count(episode_id) > 1
    )
    if duplicates:
        raise ValueError(f"duplicate episode IDs across shards: {duplicates}")
    decision_ids = [
        decision.decision_id
        for episode in episodes
        for decision in episode.decisions
    ]
    duplicate_decisions = sorted(
        decision_id
        for decision_id in set(decision_ids)
        if decision_ids.count(decision_id) > 1
    )
    if duplicate_decisions:
        raise ValueError(
            f"duplicate decision IDs across shards: {duplicate_decisions}"
        )
    journal_by_id = {str(item["episode_id"]): item for item in journals}
    ordered_episodes = sorted(
        episodes, key=lambda item: (item.matched_key, item.method)
    )
    ordered_journals = [
        journal_by_id[episode.episode_id] for episode in ordered_episodes
    ]
    return ordered_episodes, ordered_journals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--episode-shard", action="append", required=True, type=Path
    )
    parser.add_argument(
        "--journal-shard", action="append", required=True, type=Path
    )
    parser.add_argument("--episodes-output", required=True, type=Path)
    parser.add_argument("--journal-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    episodes, journals = merge_shards(
        args.episode_shard, args.journal_shard
    )
    args.episodes_output.parent.mkdir(parents=True, exist_ok=True)
    args.episodes_output.write_text(
        "".join(episode.model_dump_json() + "\n" for episode in episodes)
    )
    args.journal_output.parent.mkdir(parents=True, exist_ok=True)
    args.journal_output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in journals)
    )
    report = {
        "schema_version": "M2BMatchedClosedLoopShardMergeV1",
        "status": "PASS",
        "episode_shards": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in args.episode_shard
        ],
        "journal_shards": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in args.journal_shard
        ],
        "episodes": len(episodes),
        "matched_keys": len({episode.matched_key for episode in episodes}),
        "methods": dict(sorted(Counter(episode.method for episode in episodes).items())),
        "unique_decision_ids": len(
            {
                decision.decision_id
                for episode in episodes
                for decision in episode.decisions
            }
        ),
        "episodes_output": str(args.episodes_output),
        "episodes_output_sha256": hashlib.sha256(
            args.episodes_output.read_bytes()
        ).hexdigest(),
        "journal_output": str(args.journal_output),
        "journal_output_sha256": hashlib.sha256(
            args.journal_output.read_bytes()
        ).hexdigest(),
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
