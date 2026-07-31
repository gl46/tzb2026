from __future__ import annotations

from m2b.evaluate_qwen_coarse_adapter import (
    canonical_sha256,
    sha256_tree,
)


def test_canonical_model_record_hash_ignores_mapping_key_order() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256(
        {"a": 1, "b": 2}
    )


def test_adapter_tree_hash_binds_relative_names_and_file_contents(
    tmp_path,
) -> None:
    adapter = tmp_path / "adapter"
    nested = adapter / "nested"
    nested.mkdir(parents=True)
    (adapter / "adapter_config.json").write_text("{}")
    weights = nested / "adapter_model.safetensors"
    weights.write_bytes(b"weights-v1")
    first = sha256_tree(adapter)
    assert first == sha256_tree(adapter)
    weights.write_bytes(b"weights-v2")
    assert sha256_tree(adapter) != first
