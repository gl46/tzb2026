from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADDENDUM = ROOT / "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"


def _text() -> str:
    return " ".join(ADDENDUM.read_text(encoding="utf-8").split())


def test_phase2_source_unlock_addendum_freezes_only_the_two_active_bindings() -> None:
    text = _text()

    assert "Status: **Accepted Phase-2 binding addendum**" in text
    assert "2026-08-15 (Asia/Shanghai)" in text
    assert "Physical Q-B evidence produced by this addendum: **no**" in text
    assert "Teacher used: **no**" in text
    assert "Privileged simulator truth used as policy input: **no**" in text
    assert "`FORMAL_PHYSICAL_RUNNER_BINDING`" in text
    assert "`FORMAL_DEPLOYMENT_CLOSURE_BINDING`" in text
    assert "`FROZEN_B0_RUNTIME_WRAPPER_BINDING = None`" in text
    assert "`OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None`" in text
    assert "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9" in text


def test_phase2_source_unlock_addendum_freezes_exact_a3_and_execution_boundaries() -> None:
    text = _text()

    for required in (
        "`float64`, `BT_USE_DOUBLE_PRECISION`, no fast-math",
        "`1e-7 m`",
        "`0.002 m`",
        "allowed penetration: `0.0 m`",
        "contact rejection threshold: `0.001 m`",
        "native maximum CCD iterations: `64`",
        "subdivision cap: `4096`",
        "query timeout: `5,000,000,000 ns`",
        "74/74 governed child-pair requests were clear",
        "zero target writes, simulation steps or scene mutations",
    ):
        assert required in text

    assert "invalid pointer/mapping/cell" in text
    assert "terminal `NO_PHYSICAL_EXECUTION`" in text
    assert "does **not** by itself authorize a formal Q-B success claim" in text
    assert "`BLOCKED_UNMEASURED`, never measured zero" in text
    assert "The 2026-08-20 bundle-smoke checkpoint remains unchanged." in text


def test_phase2_source_unlock_addendum_requires_complete_two_phase_git_closure() -> None:
    text = _text()

    assert "reviewed two-phase closure protocol" in text
    assert "create-only `M2CPhase2SourceBindingClosureReceiptV1`" in text
    assert "`FormalTransitiveImportClosureManifestV1`" in text
    assert "every regular tracked file" in text
    assert "exact Git mode and SHA-256 replay" in text
    assert "ADR-0026 decision-level loader/trainer gate" in text
    assert "trained Qwen adapter" in text
    assert "cannot be included before they exist" in text
