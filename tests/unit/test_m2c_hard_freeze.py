from __future__ import annotations

from pathlib import Path
import importlib.util

import pytest

from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2C_HARD_FREEZE_LOCAL_ISO,
    M2C_HARD_FREEZE_UNIX_NS,
    M2CExperimentAction,
    M2CHardFreezeError,
    require_pre_freeze,
)


ROOT = Path(__file__).resolve().parents[2]


def test_create_before_freeze_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import m2c_hard_freeze

    monkeypatch.setattr(
        m2c_hard_freeze.time,
        "time_ns",
        lambda: M2C_HARD_FREEZE_UNIX_NS - 1,
    )
    result = require_pre_freeze(M2CExperimentAction.TRAINING)
    assert result.isoformat() == "2026-08-31T23:59:59.999999+08:00"


@pytest.mark.parametrize("action", list(M2CExperimentAction))
@pytest.mark.parametrize(
    "observed_ns",
    [
        M2C_HARD_FREEZE_UNIX_NS,
        M2C_HARD_FREEZE_UNIX_NS + 1,
        M2C_HARD_FREEZE_UNIX_NS + 86_400_000_000_000,
    ],
)
def test_rejects_every_experiment_action_on_or_after_freeze(
    action: M2CExperimentAction,
    observed_ns: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import m2c_hard_freeze

    monkeypatch.setattr(m2c_hard_freeze.time, "time_ns", lambda: observed_ns)
    with pytest.raises(M2CHardFreezeError, match="M2C_HARD_FREEZE_ACTIVE"):
        require_pre_freeze(action)


def test_cutoff_identity_is_frozen_and_environment_is_not_an_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import m2c_hard_freeze

    monkeypatch.setenv("M2C_HARD_FREEZE", "2099-01-01T00:00:00Z")
    monkeypatch.setattr(
        m2c_hard_freeze.time,
        "time_ns",
        lambda: M2C_HARD_FREEZE_UNIX_NS,
    )
    assert M2C_HARD_FREEZE_LOCAL_ISO == "2026-09-01T00:00:00+08:00"
    with pytest.raises(M2CHardFreezeError, match="M2C_HARD_FREEZE_ACTIVE"):
        require_pre_freeze(M2CExperimentAction.SMOKE)


@pytest.mark.parametrize("invalid_clock", ["not-an-integer", 0, -1])
def test_invalid_system_clock_fails_closed(
    invalid_clock: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import m2c_hard_freeze

    monkeypatch.setattr(m2c_hard_freeze.time, "time_ns", lambda: invalid_clock)
    with pytest.raises(M2CHardFreezeError, match="M2C_HARD_FREEZE_CLOCK_INVALID"):
        require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)


def test_fixed_timezone_construction_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import m2c_hard_freeze

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("fixed timezone unavailable")

    monkeypatch.setattr(m2c_hard_freeze, "timezone", unavailable)
    with pytest.raises(M2CHardFreezeError, match="M2C_HARD_FREEZE_CLOCK_INVALID"):
        require_pre_freeze(M2CExperimentAction.S6_EXECUTION)


def test_guard_does_not_require_external_iana_tzdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xh_agent.policy.qrm_lite import m2c_hard_freeze

    monkeypatch.setenv("PYTHONTZPATH", "/definitely/missing")
    monkeypatch.setenv("TZ", "Invalid/Timezone")
    monkeypatch.setattr(
        m2c_hard_freeze.time,
        "time_ns",
        lambda: M2C_HARD_FREEZE_UNIX_NS - 1,
    )
    result = require_pre_freeze(M2CExperimentAction.ISAAC_COLLECTION)
    assert result.isoformat() == "2026-08-31T23:59:59.999999+08:00"


def test_all_current_real_m2c_entrypoints_call_the_shared_guard() -> None:
    expected = {
        "scripts/m2c/train_qwen_coarse_v2.py": "M2CExperimentAction.TRAINING",
        "scripts/m2c/evaluate_qwen_coarse_v2.py": "M2CExperimentAction.Q_B_EVALUATION",
        "scripts/m2c/run_path_blocked_collection_worker.py": "require_pre_freeze",
        "scripts/m2c/run_formal_model_owned_chain.py": "M2CExperimentAction.Q_B_EVALUATION",
        "scripts/m2c/serve_qwen_coarse_v2.py": "M2CExperimentAction.FORMAL_MODEL_SERVICE",
        "scripts/m2c/serve_qwen_coarse_v4.py": "M2CExperimentAction.FORMAL_MODEL_SERVICE",
        "scripts/m2c/serve_formal_isaac_endpoint.py": "M2CExperimentAction.FORMAL_ISAAC_SERVICE",
    }
    for relative, marker in expected.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "m2c_hard_freeze import" in source
        assert marker in source


def test_read_only_audit_and_status_entrypoints_remain_unblocked() -> None:
    for relative in (
        "scripts/m2c/status.py",
        "scripts/m2c/check_s4_entry_gate.py",
        "scripts/m2c/audit_path_blocked_train_collection.py",
        "scripts/m2c/summarize_s6_matched.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "m2c_hard_freeze" not in source


def _load_script(relative: str, module_name: str) -> object:
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_training_dry_run_is_rejected_after_freeze_before_dataset_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script(
        "scripts/m2c/train_qwen_coarse_v2.py",
        "m2c_hard_freeze_train_entrypoint",
    )
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda _argv: type("Args", (), {"dry_run": True})(),
    )
    monkeypatch.setattr(
        module,
        "require_pre_freeze",
        lambda _action: (_ for _ in ()).throw(M2CHardFreezeError("frozen")),
    )
    monkeypatch.setattr(
        module,
        "load_training_dataset",
        lambda *_args, **_kwargs: pytest.fail("dataset loaded after hard freeze"),
    )
    with pytest.raises(M2CHardFreezeError, match="frozen"):
        module.main([])


def test_formal_backend_constructor_guards_before_loading_probe() -> None:
    source = (ROOT / "scripts/m2c/formal_isaac_v4_backend.py").read_text(encoding="utf-8")
    constructor = source[source.index("class FormalIsaacV4BackendV2") :]
    guard = constructor.index("require_pre_freeze(M2CExperimentAction.FORMAL_ISAAC_SERVICE)")
    probe_load = constructor.index("self.probe = _load_frozen_v4_probe")
    assert guard < probe_load
