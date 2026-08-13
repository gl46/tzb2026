from __future__ import annotations

import json
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.frozen_b0_fallback_wrapper_v1 import (
    FROZEN_B0_MANIFEST_PATH,
    FROZEN_B0_PROBE_SHA256,
    FrozenB0FallbackRequestV1,
    FrozenB0FallbackWrapperV1,
    FrozenB0Unavailable,
    sanitized_subprocess_environment,
    validate_no_extra_argv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _request() -> FrozenB0FallbackRequestV1:
    return FrozenB0FallbackRequestV1(
        run_id="run-1",
        session_id="session-1",
        decision_index=0,
        trigger="INVALID_POINTER",
        active_scene_state_sha256="a" * 64,
        rejected_model_mapping_sha256="b" * 64,
        previous_capture_receipt_sha256="c" * 64,
    )


def _argv(wrapper: FrozenB0FallbackWrapperV1, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    stage = tmp_path / "stage.usdc"
    sdf = source / "scene.sdf"
    supervision = source / "scene.supervision.json"
    output = tmp_path / "output"
    for path in (stage, sdf, supervision):
        path.write_bytes(b"contract fixture")
    return wrapper.build_legacy_argv(
        _request(),
        source_root=source,
        stage=stage,
        sdf=sdf,
        supervision=supervision,
        output_root=output,
        gpu=0,
    )


def test_wrapper_verifies_every_frozen_b0_source_without_copying_it() -> None:
    wrapper = FrozenB0FallbackWrapperV1(project_root=PROJECT_ROOT)
    receipt = wrapper.verify_frozen_sources()

    assert len(receipt.source_bindings) == 12
    assert receipt.probe_sha256 == FROZEN_B0_PROBE_SHA256
    assert receipt.b0_modified is False
    assert receipt.all_sources_verified_before_launch is True
    source_paths = {item.path for item in receipt.source_bindings}
    assert "scripts/isaac_m1b_actuation_probe.py" in source_paths
    assert not any("wrapper" in item.role.lower() for item in receipt.source_bindings)


def test_legacy_argv_is_exact_and_environment_or_extra_argument_fails_closed(
    tmp_path: Path,
) -> None:
    wrapper = FrozenB0FallbackWrapperV1(project_root=PROJECT_ROOT)
    argv = _argv(wrapper, tmp_path)

    assert argv.argv_sha256 == canonical_sha256(argv.argv)
    assert argv.environment == (
        ("LANG", "C"),
        ("LC_ALL", "C"),
        ("PATH", "/usr/bin:/bin"),
    )
    assert argv.starts_new_isaac_process is True
    assert argv.compatible_with_active_formal_session is False
    validate_no_extra_argv(argv.argv, argv)
    with pytest.raises(FrozenB0Unavailable, match="extra argument"):
        validate_no_extra_argv((*argv.argv, "--not-frozen"), argv)
    with pytest.raises(FrozenB0Unavailable, match="caller-supplied environment"):
        sanitized_subprocess_environment({"PYTHONPATH": "/tmp/injected"})


def test_active_formal_session_fallback_is_no_physical_execution(
    tmp_path: Path,
) -> None:
    wrapper = FrozenB0FallbackWrapperV1(project_root=PROJECT_ROOT)
    argv = _argv(wrapper, tmp_path)

    receipt = wrapper.invoke(_request(), legacy_argv=argv, active_session_binding=None)

    assert receipt.status == "NO_PHYSICAL_EXECUTION"
    assert receipt.execution_source == "NO_PHYSICAL_EXECUTION"
    assert receipt.physically_executed is False
    assert receipt.pure_model_success_eligible is False
    assert "ACTIVE_FORMAL_SESSION" in receipt.fallback_reason
    payload = receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    assert receipt.receipt_sha256 == canonical_sha256(payload)


def test_frozen_manifest_or_source_tamper_is_rejected(tmp_path: Path) -> None:
    manifest = json.loads((PROJECT_ROOT / FROZEN_B0_MANIFEST_PATH).read_text())
    copied = tmp_path / "project"
    for item in manifest["b0_files"]:
        source = PROJECT_ROOT / item["path"]
        target = copied / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    manifest_target = copied / FROZEN_B0_MANIFEST_PATH
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.write_bytes((PROJECT_ROOT / FROZEN_B0_MANIFEST_PATH).read_bytes())

    (copied / "scripts/isaac_m1b_actuation_probe.py").write_bytes(b"tampered")
    wrapper = FrozenB0FallbackWrapperV1(project_root=copied)
    with pytest.raises(FrozenB0Unavailable, match="source SHA-256 differs"):
        wrapper.verify_frozen_sources()


def test_trigger_set_is_closed() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        FrozenB0FallbackRequestV1(
            run_id="run-1",
            session_id="session-1",
            decision_index=0,
            trigger="UNKNOWN",  # type: ignore[arg-type]
            active_scene_state_sha256="a" * 64,
            rejected_model_mapping_sha256="b" * 64,
            previous_capture_receipt_sha256="c" * 64,
        )
