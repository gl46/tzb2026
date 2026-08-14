from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from test_m2c_formal_public_observation_v4 import _depth, _rgb
from test_m2c_path_blocked_supervision_v4 import (
    attribute_binding,
    capture,
    deployment,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    FormalPublicCapturePacketV4,
    ReplayableFormalPublicObservationProviderV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import public_asset_inline_v4


class _Source:
    real_isaac = False
    mocked_physics = True

    def __init__(self, packets: list[FormalPublicCapturePacketV4]) -> None:
        self.implementation_sha256 = deployment().capture_source_implementation_sha256
        self.packets = packets
        self.calls: list[dict[str, Any]] = []

    def capture_public_v4(self, **kwargs: Any) -> FormalPublicCapturePacketV4:
        self.calls.append(dict(kwargs))
        return self.packets.pop(0)


class _FailingSource(_Source):
    def capture_public_v4(self, **kwargs: Any) -> FormalPublicCapturePacketV4:
        self.calls.append(dict(kwargs))
        raise OSError("capture transport failed")


def _packet(
    index: int,
    association_capture: Any,
    *,
    previous_completed_at_ns: int,
    source_sha256: str | None = None,
) -> FormalPublicCapturePacketV4:
    rgb = _rgb()
    depth = _depth()
    return FormalPublicCapturePacketV4(
        run_id="formal-provider-run",
        session_id="formal-provider-session",
        decision_index=index,
        observation_id=f"formal-provider-observation-{index}",
        previous_execution_completed_at_ns=previous_completed_at_ns,
        capture_source_implementation_sha256=(
            source_sha256 or deployment().capture_source_implementation_sha256
        ),
        capture=association_capture,
        rgb=public_asset_inline_v4(
            uri=f"dataset://formal-provider/rgb/{index}.png",
            sha256=hashlib.sha256(rgb).hexdigest(),
            media_type="image/png",
            data=rgb,
        ),
        depth=public_asset_inline_v4(
            uri=f"dataset://formal-provider/depth/{index}.npy",
            sha256=hashlib.sha256(depth).hexdigest(),
            media_type="application/x-npy",
            data=depth,
        ),
        real_isaac=False,
        mocked_physics=True,
        contract_test_only=True,
    )


def _captures() -> tuple[Any, Any]:
    first = capture(
        1_000,
        [
            (0.01, "yellow", 0.90),
            (0.31, "blue", 0.95),
        ],
        previous=None,
    )
    second = capture(
        2_000,
        [
            (0.011, "yellow", 0.90),
            (0.311, "blue", 0.95),
        ],
        previous=first,
    )
    return first, second


def _provider(source: _Source) -> ReplayableFormalPublicObservationProviderV4:
    provider = ReplayableFormalPublicObservationProviderV4(
        mode="CONTRACT_TEST",
        source=source,
        association_deployment=deployment(),
        declared_attribute_binding=attribute_binding(),
    )
    provider.begin_session(
        run_id="formal-provider-run",
        session_id="formal-provider-session",
    )
    return provider


def test_provider_replays_complete_prefix_into_formal_v4_observations() -> None:
    first, second = _captures()
    source = _Source(
        [
            _packet(0, first, previous_completed_at_ns=50),
            _packet(1, second, previous_completed_at_ns=1_500),
        ]
    )
    provider = _provider(source)

    observation0 = provider.capture(
        run_id="formal-provider-run",
        session_id="formal-provider-session",
        decision_index=0,
        previous_execution_completed_at_ns=50,
    )
    observation1 = provider.capture(
        run_id="formal-provider-run",
        session_id="formal-provider-session",
        decision_index=1,
        previous_execution_completed_at_ns=1_500,
    )

    assert len(observation0.observation.association_history) == 1
    assert len(observation1.observation.association_history) == 2
    assert (
        observation1.observation.association_history[0]
        == observation0.observation.association_history[0]
    )
    assert len(observation1.proprioception_journal.captures) == 2
    assert observation1.association_session_receipt.capture_count == 2
    assert observation1.previous_physical_completed_at_ns == 1_500
    assert observation1.canonical_slots[:2] == observation0.canonical_slots[:2]
    assert observation1.canonical_public_tracks_sha256 == (
        observation1.observation.candidate_payload_sha256
    )
    assert [call["decision_index"] for call in source.calls] == [0, 1]


def test_provider_rejects_crossed_packet_and_consumes_capture_attempt() -> None:
    first, _ = _captures()
    bad = _packet(
        0,
        first,
        previous_completed_at_ns=50,
        source_sha256="f" * 64,
    )
    good = _packet(0, first, previous_completed_at_ns=50)
    source = _Source([bad, good])
    provider = _provider(source)

    with pytest.raises(ValueError, match="crosses request/deployment"):
        provider.capture(
            run_id="formal-provider-run",
            session_id="formal-provider-session",
            decision_index=0,
            previous_execution_completed_at_ns=50,
        )
    with pytest.raises(RuntimeError, match="poisoned after capture failure"):
        provider.capture(
            run_id="formal-provider-run",
            session_id="formal-provider-session",
            decision_index=0,
            previous_execution_completed_at_ns=50,
        )
    assert len(source.packets) == 1


def test_provider_source_failure_consumes_capture_attempt() -> None:
    first, _ = _captures()
    source = _FailingSource([_packet(0, first, previous_completed_at_ns=50)])
    provider = _provider(source)

    with pytest.raises(OSError, match="capture transport failed"):
        provider.capture(
            run_id="formal-provider-run",
            session_id="formal-provider-session",
            decision_index=0,
            previous_execution_completed_at_ns=50,
        )
    with pytest.raises(RuntimeError, match="poisoned after capture failure"):
        provider.capture(
            run_id="formal-provider-run",
            session_id="formal-provider-session",
            decision_index=0,
            previous_execution_completed_at_ns=50,
        )
    assert len(source.calls) == 1


def test_provider_rejects_mock_source_in_real_mode() -> None:
    first, _ = _captures()
    with pytest.raises(ValueError, match="requires a real source"):
        ReplayableFormalPublicObservationProviderV4(
            mode="REAL_ISAAC",
            source=_Source([_packet(0, first, previous_completed_at_ns=50)]),
            association_deployment=deployment(),
            declared_attribute_binding=attribute_binding(),
        )


def test_provider_rejects_reused_observation_identity() -> None:
    first, second = _captures()
    repeated = _packet(1, second, previous_completed_at_ns=1_500).model_copy(
        update={"observation_id": "formal-provider-observation-0"}
    )
    provider = _provider(
        _Source(
            [
                _packet(0, first, previous_completed_at_ns=50),
                repeated,
            ]
        )
    )
    provider.capture(
        run_id="formal-provider-run",
        session_id="formal-provider-session",
        decision_index=0,
        previous_execution_completed_at_ns=50,
    )
    with pytest.raises(ValueError, match="repeats an observation identity"):
        provider.capture(
            run_id="formal-provider-run",
            session_id="formal-provider-session",
            decision_index=1,
            previous_execution_completed_at_ns=1_500,
        )


def test_capture_packet_schema_forbids_task_identity() -> None:
    first, _ = _captures()
    raw = _packet(0, first, previous_completed_at_ns=50).model_dump(mode="json")
    raw["task_target_track_id"] = "track-deadbeef"
    with pytest.raises(ValidationError):
        FormalPublicCapturePacketV4.model_validate(raw)


def test_provider_file_is_present_for_deployment_binding() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src/xh_agent/policy/qrm_lite/formal_public_observation_provider_v4.py"
    )
    assert path.is_file()
