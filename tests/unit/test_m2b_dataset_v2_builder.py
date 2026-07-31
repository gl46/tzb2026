from __future__ import annotations

from m2b.build_dataset_v2 import scene_split


def test_scene_split_is_deterministic_and_scene_grouped() -> None:
    assert scene_split(4025) == scene_split(4025)
    assert scene_split(4025) in {"train", "val", "test"}
