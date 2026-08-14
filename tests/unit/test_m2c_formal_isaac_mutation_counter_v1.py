from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from xh_agent.policy.qrm_lite.formal_isaac_mutation_counter_v1 import (
    FormalIsaacActiveSessionMutationCounterV1,
    FormalIsaacMutationCounterActivationReceiptV1,
    FormalIsaacMutationCounterUnavailable,
    build_formal_isaac_mutation_counter_activation_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]


def _activation() -> FormalIsaacMutationCounterActivationReceiptV1:
    return build_formal_isaac_mutation_counter_activation_v1(
        project_root=ROOT,
        scene_owner_path=Path(__file__),
        stage_sha256="1" * 64,
        sdf_sha256="2" * 64,
        supervision_sha256="3" * 64,
        activated_at_ns=100,
    )


def test_counter_activation_and_all_mutation_surfaces_are_replayable() -> None:
    activation = _activation()
    counter = FormalIsaacActiveSessionMutationCounterV1(activation=activation)

    assert counter.snapshot_mutation_counters() == activation.initial_counters
    counter.record_articulation_target_writes(2)
    counter.record_simulation_steps(3)
    counter.record_scene_mutations()
    counter.record_controller_commands(4)
    counter.record_attachment_mutations(5)

    observed = counter.snapshot_mutation_counters()
    assert observed.articulation_target_writes == 2
    assert observed.simulation_steps == 3
    assert observed.scene_mutations == 1
    assert observed.controller_commands == 4
    assert observed.attachment_mutations == 5
    assert counter.real_active_session_source is True
    assert counter.mocked_counter_source is False
    assert activation.teacher_used is False
    assert activation.privileged_truth_policy_input is False


def test_counter_increments_are_thread_safe_and_monotonic() -> None:
    counter = FormalIsaacActiveSessionMutationCounterV1(activation=_activation())
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: counter.record_simulation_steps(), range(1000)))
    assert counter.snapshot_mutation_counters().simulation_steps == 1000


@pytest.mark.parametrize("value", (0, -1, True, 1.5))
def test_counter_rejects_non_positive_or_non_integer_increments(value: object) -> None:
    counter = FormalIsaacActiveSessionMutationCounterV1(activation=_activation())
    with pytest.raises(FormalIsaacMutationCounterUnavailable, match="positive integer"):
        counter.record_simulation_steps(value)  # type: ignore[arg-type]
    assert counter.snapshot_mutation_counters().simulation_steps == 0


def test_activation_tamper_fails_canonical_replay() -> None:
    raw = _activation().model_dump(mode="json")
    raw["stage_sha256"] = "f" * 64
    raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "receipt_sha256"}
    )
    # A self-consistent different deployment is a different valid activation,
    # while relabelling only the initial counter state is forbidden.
    changed = FormalIsaacMutationCounterActivationReceiptV1.model_validate(raw)
    assert changed.stage_sha256 == "f" * 64

    raw["initial_counters"]["simulation_steps"] = 1
    raw["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="start at zero"):
        FormalIsaacMutationCounterActivationReceiptV1.model_validate(raw)
