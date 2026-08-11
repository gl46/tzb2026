from __future__ import annotations

from pathlib import Path

import pytest

from m2c.derive_blocker_probe import (
    UPSTREAM_B0_PROBE_SHA256,
    derive_probe_bytes,
    sha256_bytes,
)


ROOT = Path(__file__).parents[2]
UPSTREAM = ROOT / "scripts/isaac_m1b_actuation_probe.py"


def test_derived_probe_is_hash_bound_compilable_and_not_b0() -> None:
    upstream = UPSTREAM.read_bytes()
    assert sha256_bytes(upstream) == UPSTREAM_B0_PROBE_SHA256
    derived = derive_probe_bytes(upstream)
    assert derived != upstream
    text = derived.decode()
    compile(text, "isaac_m2c_blocker_probe.py", "exec")
    assert text.count("--m2c-scripted-safe-place-bin-cell") == 1
    assert text.count('"counted_as_b0": False') == 1
    assert text.count('"existence_proof_only": True') == 1
    assert "M2C_SCRIPTED_SAFE_PLACE_TRANSPORT" in text
    assert "generate_industrial_scenes.bin_cell_targets" in text
    assert 'm2c_scripted_safe_place["passed"]' in text


def test_derived_probe_rejects_any_other_upstream_revision() -> None:
    with pytest.raises(ValueError, match="frozen B0 probe hash mismatch"):
        derive_probe_bytes(UPSTREAM.read_bytes() + b"\n")
