from pathlib import Path


def test_root_imports_no_gpu_runtime() -> None:
    root = Path(__file__).parents[2]
    source = (root / "src/xh_agent/__init__.py").read_text(encoding="utf-8")
    assert "torch" not in source and "vllm" not in source and "cuda" not in source
