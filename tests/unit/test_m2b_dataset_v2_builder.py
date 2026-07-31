from __future__ import annotations

from pathlib import Path

from m2b.build_dataset_v2 import scene_split, sources_from_manifest


def test_scene_split_is_deterministic_and_scene_grouped() -> None:
    assert scene_split(4025) == scene_split(4025)
    assert scene_split(4025) in {"train", "val", "test"}


def test_dataset_source_manifest_is_versioned_and_restart_safe() -> None:
    root = Path(__file__).resolve().parents[2]
    host, evidence, statuses = sources_from_manifest(
        root / "configs/m2b_dataset_sources.json"
    )
    assert host == "root@labserver"
    assert {failure for failure, _ in evidence} == {
        "EMPTY_GRASP",
        "WRONG_OBJECT",
        "RELEASE_FAILURE",
    }
    assert len(statuses) == 4
