"""Host-owned active-session mutation counter for formal Isaac A.3 queries.

The counter is activated only after the authoritative scene owner finishes
stage construction and natural-settling setup.  Every later mutation surface
must record its intent before invoking Isaac.  Query-only providers snapshot
the same object before and after their getters; any intervening target write,
simulation step, scene mutation, controller command, or attachment mutation
therefore poisons the preflight comparison.

This is local coordination evidence, not remote attestation.  It performs no
Isaac call itself and cannot make an unbound physical executor eligible.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import A3FileBindingV1
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCountersV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_mutation_counter_v1.py"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacMutationCounterUnavailable(RuntimeError):
    """The active-session counter deployment or mutation record is invalid."""


class FormalIsaacMutationCounterActivationReceiptV1(_FrozenModel):
    schema_version: Literal["FormalIsaacMutationCounterActivationReceiptV1"] = (
        "FormalIsaacMutationCounterActivationReceiptV1"
    )
    implementation: A3FileBindingV1
    scene_owner_implementation: A3FileBindingV1
    stage_sha256: str = Field(pattern=SHA256_PATTERN)
    sdf_sha256: str = Field(pattern=SHA256_PATTERN)
    supervision_sha256: str = Field(pattern=SHA256_PATTERN)
    activated_at_ns: int = Field(gt=0)
    activation_boundary: Literal["AFTER_SCENE_STABILITY_BEFORE_FORMAL_SESSION"] = (
        "AFTER_SCENE_STABILITY_BEFORE_FORMAL_SESSION"
    )
    initial_counters: ActiveSessionMutationCountersV1
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def canonical_activation(self) -> "FormalIsaacMutationCounterActivationReceiptV1":
        if self.initial_counters != ActiveSessionMutationCountersV1(
            articulation_target_writes=0,
            simulation_steps=0,
            scene_mutations=0,
            controller_commands=0,
            attachment_mutations=0,
        ):
            raise ValueError("formal Isaac mutation counter does not start at zero")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal Isaac mutation counter activation digest differs")
        return self


def build_formal_isaac_mutation_counter_activation_v1(
    *,
    project_root: Path,
    scene_owner_path: Path,
    stage_sha256: str,
    sdf_sha256: str,
    supervision_sha256: str,
    activated_at_ns: int,
) -> FormalIsaacMutationCounterActivationReceiptV1:
    implementation = project_root.resolve() / IMPLEMENTATION_REPO_PATH
    implementation_sha256 = hashlib.sha256(read_regular_file_once(implementation)).hexdigest()
    scene_owner_sha256 = hashlib.sha256(read_regular_file_once(scene_owner_path)).hexdigest()
    zero = ActiveSessionMutationCountersV1(
        articulation_target_writes=0,
        simulation_steps=0,
        scene_mutations=0,
        controller_commands=0,
        attachment_mutations=0,
    )
    payload = {
        "schema_version": "FormalIsaacMutationCounterActivationReceiptV1",
        "implementation": {
            "path": IMPLEMENTATION_REPO_PATH,
            "sha256": implementation_sha256,
        },
        "scene_owner_implementation": {
            "path": str(scene_owner_path),
            "sha256": scene_owner_sha256,
        },
        "stage_sha256": stage_sha256,
        "sdf_sha256": sdf_sha256,
        "supervision_sha256": supervision_sha256,
        "activated_at_ns": activated_at_ns,
        "activation_boundary": "AFTER_SCENE_STABILITY_BEFORE_FORMAL_SESSION",
        "initial_counters": zero.model_dump(mode="json"),
        "real_isaac": True,
        "mocked_physics": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return FormalIsaacMutationCounterActivationReceiptV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


class FormalIsaacActiveSessionMutationCounterV1:
    """Thread-safe monotonic counter shared by one formal scene owner."""

    real_active_session_source: Literal[True] = True
    mocked_counter_source: Literal[False] = False

    def __init__(
        self,
        *,
        activation: FormalIsaacMutationCounterActivationReceiptV1,
    ) -> None:
        self.activation = activation
        self.implementation_sha256 = activation.implementation.sha256
        self._values = [0, 0, 0, 0, 0]
        self._lock = threading.Lock()

    @staticmethod
    def _count(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FormalIsaacMutationCounterUnavailable(
                "formal Isaac mutation increment must be a positive integer"
            )
        return value

    def _increment(self, index: int, count: int) -> None:
        count = self._count(count)
        with self._lock:
            self._values[index] += count

    def record_articulation_target_writes(self, count: int = 1) -> None:
        self._increment(0, count)

    def record_simulation_steps(self, count: int = 1) -> None:
        self._increment(1, count)

    def record_scene_mutations(self, count: int = 1) -> None:
        self._increment(2, count)

    def record_controller_commands(self, count: int = 1) -> None:
        self._increment(3, count)

    def record_attachment_mutations(self, count: int = 1) -> None:
        self._increment(4, count)

    def snapshot_mutation_counters(self) -> ActiveSessionMutationCountersV1:
        with self._lock:
            values = tuple(self._values)
        return ActiveSessionMutationCountersV1(
            articulation_target_writes=values[0],
            simulation_steps=values[1],
            scene_mutations=values[2],
            controller_commands=values[3],
            attachment_mutations=values[4],
        )
