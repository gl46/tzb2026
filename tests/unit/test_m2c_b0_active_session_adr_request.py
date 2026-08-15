from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).parents[2]
REQUEST = ROOT / "docs/decisions/M2C-S4-B0-ACTIVE-SESSION-FALLBACK-ADR-REQUEST.md"
B0_PROBE = ROOT / "scripts/isaac_m1b_actuation_probe.py"
ENTRY_GATE = ROOT / "src/xh_agent/policy/qrm_lite/s4_entry_gate.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_request_is_unapproved_and_freezes_all_three_human_options() -> None:
    text = REQUEST.read_text()

    assert "REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR" in text
    assert "Select exactly one of A, B, or C" in text
    assert "A — authorize a versioned active-session B0 implementation" in text
    assert "B — amend invalid mapping to terminal no-action (recommended)" in text
    assert "C — retain Option A and keep S4 blocked" in text
    assert "No option is selected" in text
    assert "Does approval alone set any Phase-2 binding?: **NO**" in text
    assert "Does approval alone authorize training or Q-B evaluation?: **NO**" in text


def test_request_binds_current_frozen_b0_bytes_and_absent_active_session_surface() -> None:
    text = REQUEST.read_text()
    expected = "1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"

    assert _sha256(B0_PROBE) == expected
    assert expected in text
    tree = ast.parse(B0_PROBE.read_bytes(), filename=str(B0_PROBE))
    functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "run_unchanged_b0_active_session_v1" not in functions


def test_later_source_unlock_keeps_request_withdrawn_bindings_none() -> None:
    source = ENTRY_GATE.read_text()
    tree = ast.parse(source, filename=str(ENTRY_GATE))
    expected = {
        "FORMAL_PHYSICAL_RUNNER_BINDING",
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
    }
    observed: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id in expected:
            observed[node.target.id] = ast.literal_eval(node.value)

    assert observed["FORMAL_PHYSICAL_RUNNER_BINDING"] == (
        "scripts/m2c/run_formal_model_owned_chain_v4.py",
        "799caecdb12f73b5e6ea226eb2b983e4fbe4c08482f7ed037ae33c2168068eef",
    )
    assert observed["FORMAL_DEPLOYMENT_CLOSURE_BINDING"] == (
        "3b86d4c997a6e2a7229c6e8149200b166fa32d77",
        "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9",
        "684c81dcb00d0abf33095bc704e7550d9bb64400b367d2b5da9324aeb85c8993",
    )
    assert observed["FROZEN_B0_RUNTIME_WRAPPER_BINDING"] is None
    assert observed["OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING"] is None
