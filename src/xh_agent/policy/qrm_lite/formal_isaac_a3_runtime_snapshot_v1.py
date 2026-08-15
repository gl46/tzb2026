"""Bind one exact plan to a mutation-free A.3 runtime readiness snapshot.

Plan synthesis already captures the physical articulation state from the
persistent Isaac scene.  The A.3 preflight callback graph additionally needs
controller, collision-world, contact, attachment, and emergency-stop readiness
from that *same* scene.  This module joins those two query-only views without
consuming the articulation state needed by the Lula phase-path provider.

The readiness source is an independently byte-bound implementation.  It may
report a failed readiness condition, but it cannot choose a plan, change a
gate, execute a command, or make the snapshot retryable.  The resulting
``PreflightRuntimeSnapshotV1`` is consumed later by the unchanged exact-plan
preflight validator.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.a3_active_session_attachment_evidence_v2 import (
    A3ExecutedAttachmentBindingV2,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    EXPECTED_COMMAND_DIMENSIONS,
    ControllerCommandShapeV1,
    ExactPlanPreflightConfigurationV1,
    PreflightRuntimeSnapshotV1,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.isaac_active_session_query_v1 import (
    IsaacActiveSessionQueryProviderV1,
)
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
    ActiveSessionMutationCountersV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_a3_runtime_snapshot_v1.py"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacA3RuntimeSnapshotUnavailable(RuntimeError):
    """The active scene cannot produce one complete non-actuating snapshot."""


def _model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _safe_source_path(project_root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise FormalIsaacA3RuntimeSnapshotUnavailable(
            "A.3 readiness source path escapes the repository"
        )
    cursor = project_root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "A.3 readiness source path contains a symlink"
            )
    try:
        resolved = cursor.resolve(strict=True)
    except OSError as exc:
        raise FormalIsaacA3RuntimeSnapshotUnavailable(
            "A.3 readiness source path is unavailable"
        ) from exc
    if not resolved.is_relative_to(project_root):
        raise FormalIsaacA3RuntimeSnapshotUnavailable(
            "A.3 readiness source resolves outside the repository"
        )
    return resolved


class FormalIsaacA3RuntimeReadinessReceiptV1(_FrozenModel):
    """Exact query-only readiness readout from one persistent scene."""

    schema_version: Literal["FormalIsaacA3RuntimeReadinessReceiptV1"] = (
        "FormalIsaacA3RuntimeReadinessReceiptV1"
    )
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_sha256: str = Field(pattern=SHA256_PATTERN)
    preplan_state_timestamp_ns: int = Field(gt=0)
    preflight_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    source_implementation_path: str = Field(min_length=1)
    source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    query_started_at_ns: int = Field(gt=0)
    checked_at_ns: int = Field(gt=0)
    controller_id: str = Field(min_length=1)
    controller_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    controller_ready: bool
    controller_readiness_query_duration_ns: int = Field(ge=0)
    controller_rate_hz: float = Field(gt=0.0)
    collision_world_ready: bool
    contact_monitor_ready: bool
    attachment_monitor_ready: bool
    terminal_bilateral_contact_broker_ready: bool
    emergency_stop_active: bool
    active_attachment_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    real_isaac: bool
    mocked_runtime: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    controller_commands: Literal[0] = 0
    attachment_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def complete_and_canonical(self) -> "FormalIsaacA3RuntimeReadinessReceiptV1":
        if self.real_isaac == self.mocked_runtime:
            raise ValueError("A.3 readiness must be exactly real or mocked")
        if self.checked_at_ns < self.query_started_at_ns:
            raise ValueError("A.3 readiness completed before it started")
        if (
            self.controller_readiness_query_duration_ns
            != self.checked_at_ns - self.query_started_at_ns
        ):
            raise ValueError("A.3 controller-readiness duration differs from timestamps")
        if not math.isfinite(self.controller_rate_hz):
            raise ValueError("A.3 controller rate is NaN/Inf")
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("A.3 readiness query mutated the active session")
        if self.receipt_sha256 != _model_sha256(self, "receipt_sha256"):
            raise ValueError("A.3 readiness receipt digest differs")
        return self


class FormalIsaacA3ActiveAttachmentSourceV1(Protocol):
    real_isaac: bool
    mocked_physics: bool

    def snapshot_active_attachment(self) -> A3ExecutedAttachmentBindingV2 | None: ...


class FormalIsaacA3RuntimeReadinessSourceV1(Protocol):
    """Reviewed source of controller/safety readiness for one live scene."""

    implementation_path: str
    implementation_sha256: str
    real_isaac: bool
    mocked_runtime: bool
    mutation_counter_source: ActiveSessionMutationCounterSourceV1
    active_attachment_source: FormalIsaacA3ActiveAttachmentSourceV1

    def query_runtime_readiness(
        self,
        *,
        plan: M2CExactPlanPrimitivePlanV1,
        configuration: ExactPlanPreflightConfigurationV1,
        after_ns: int,
    ) -> FormalIsaacA3RuntimeReadinessReceiptV1: ...


class FormalIsaacA3RuntimeSnapshotProviderV1:
    """Create one single-use A.3 snapshot from the captured physical state."""

    implementation_path = IMPLEMENTATION_REPO_PATH
    query_only: Literal[True] = True

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        active_session_provider: IsaacActiveSessionQueryProviderV1,
        readiness_source: FormalIsaacA3RuntimeReadinessSourceV1,
        configuration: ExactPlanPreflightConfigurationV1,
    ) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.mode = mode
        self.active_session_provider = active_session_provider
        self.readiness_source = readiness_source
        self.active_attachment_source = readiness_source.active_attachment_source
        self.configuration = ExactPlanPreflightConfigurationV1.model_validate(
            configuration.model_dump(mode="json")
        )
        self.mutation_counter_source = active_session_provider.mutation_counter_source
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(self.project_root / IMPLEMENTATION_REPO_PATH)
        ).hexdigest()
        source_path = _safe_source_path(
            self.project_root,
            readiness_source.implementation_path,
        )
        self.readiness_source_implementation_sha256 = hashlib.sha256(
            read_regular_file_once(source_path)
        ).hexdigest()
        self._consumed = False
        self._readiness_receipt: FormalIsaacA3RuntimeReadinessReceiptV1 | None = None

        if (
            readiness_source.implementation_sha256 != self.readiness_source_implementation_sha256
            or readiness_source.mutation_counter_source is not self.mutation_counter_source
            or active_session_provider.mode != mode
            or self.configuration.controller.controller_configuration_sha256
            != active_session_provider.controller_configuration_sha256
            or self.configuration.joint_limits.source_sha256
            != active_session_provider.joint_limit_source_sha256
            or self.configuration.joint_limits.maximum_abs_effort
            != active_session_provider.maximum_abs_effort
        ):
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "A.3 runtime snapshot dependencies cross source/configuration"
            )
        attachment_source = self.active_attachment_source
        if mode == "REAL_ISAAC":
            if (
                not active_session_provider.real_active_session_source
                or active_session_provider.mocked_source
                or not readiness_source.real_isaac
                or readiness_source.mocked_runtime
                or not attachment_source.real_isaac
                or attachment_source.mocked_physics
            ):
                raise FormalIsaacA3RuntimeSnapshotUnavailable(
                    "REAL_ISAAC snapshot dependencies claim another execution mode"
                )
        elif (
            active_session_provider.real_active_session_source
            or not active_session_provider.mocked_source
            or readiness_source.real_isaac
            or not readiness_source.mocked_runtime
            or attachment_source.real_isaac
            or not attachment_source.mocked_physics
        ):
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "contract snapshot dependencies claim real Isaac"
            )

    @property
    def formal_query_evidence_eligible(self) -> bool:
        return self.mode == "REAL_ISAAC"

    @property
    def readiness_receipt(self) -> FormalIsaacA3RuntimeReadinessReceiptV1:
        receipt = self._readiness_receipt
        if receipt is None:
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "A.3 runtime readiness receipt is not available"
            )
        return receipt

    @staticmethod
    def _attachment_sha256(
        attachment: A3ExecutedAttachmentBindingV2 | None,
    ) -> str | None:
        return attachment.receipt_sha256 if attachment is not None else None

    def build_snapshot(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
    ) -> PreflightRuntimeSnapshotV1:
        """Consume one readiness query and bind it to the exact plan/state."""

        if self._consumed:
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "A.3 runtime snapshot provider is single-use"
            )
        # Consume before any external getter.  A failed or crossed query may
        # not be retried under a different readiness observation.
        self._consumed = True
        state = self.active_session_provider.peek_bound_preplan_state(plan)
        before = self.mutation_counter_source.snapshot_mutation_counters()
        attachment_before = self.active_attachment_source.snapshot_active_attachment()
        raw = self.readiness_source.query_runtime_readiness(
            plan=plan,
            configuration=self.configuration,
            after_ns=plan.inputs.plan_constructed_at_ns,
        )
        receipt = FormalIsaacA3RuntimeReadinessReceiptV1.model_validate(
            raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
        )
        attachment_after = self.active_attachment_source.snapshot_active_attachment()
        after = self.mutation_counter_source.snapshot_mutation_counters()
        attachment_sha256 = self._attachment_sha256(attachment_before)
        expected = {
            "bound_plan_sha256": plan.bound_plan_sha256,
            "preplan_state_sha256": state.state_sha256,
            "preplan_state_timestamp_ns": state.observed_at_ns,
            "preflight_configuration_sha256": self.configuration.configuration_sha256,
            "source_implementation_path": self.readiness_source.implementation_path,
            "source_implementation_sha256": self.readiness_source_implementation_sha256,
            "controller_id": self.configuration.controller.controller_id,
            "controller_configuration_sha256": (
                self.configuration.controller.controller_configuration_sha256
            ),
            "controller_rate_hz": self.configuration.controller.required_rate_hz,
            "active_attachment_receipt_sha256": attachment_sha256,
            "mutation_counters_before": before,
            "mutation_counters_after": after,
            "real_isaac": self.mode == "REAL_ISAAC",
            "mocked_runtime": self.mode == "CONTRACT_TEST",
        }
        if (
            any(getattr(receipt, name) != value for name, value in expected.items())
            or before != after
            or before != state.mutation_counters_after
            or attachment_before != attachment_after
            or receipt.query_started_at_ns <= plan.inputs.plan_constructed_at_ns
            or receipt.checked_at_ns < receipt.query_started_at_ns
            or receipt.controller_readiness_query_duration_ns
            > self.configuration.controller.readiness_timeout_ns
        ):
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "A.3 runtime readiness crossed plan/state/session or mutated it"
            )
        if attachment_before is not None and (
            attachment_before.real_isaac != (self.mode == "REAL_ISAAC")
            or attachment_before.contract_test_only != (self.mode == "CONTRACT_TEST")
            or (
                self.mode == "REAL_ISAAC"
                and not attachment_before.formal_execution_evidence_eligible
            )
        ):
            raise FormalIsaacA3RuntimeSnapshotUnavailable(
                "A.3 active attachment mode/evidence differs from runtime"
            )

        payload: dict[str, Any] = {
            "schema_version": "PreflightRuntimeSnapshotV1",
            "bound_plan_sha256": plan.bound_plan_sha256,
            "preplan_state_sha256": state.state_sha256,
            "observed_at_ns": state.observed_at_ns,
            "checked_at_ns": receipt.checked_at_ns,
            "controller_id": receipt.controller_id,
            "controller_configuration_sha256": receipt.controller_configuration_sha256,
            "controller_ready": receipt.controller_ready,
            "controller_readiness_query_duration_ns": (
                receipt.controller_readiness_query_duration_ns
            ),
            "controller_rate_hz": receipt.controller_rate_hz,
            "command_shapes": [
                ControllerCommandShapeV1(command=command, dimensions=dimensions).model_dump(
                    mode="json"
                )
                for command, dimensions in EXPECTED_COMMAND_DIMENSIONS.items()
            ],
            "collision_world_ready": receipt.collision_world_ready,
            "contact_monitor_ready": receipt.contact_monitor_ready,
            "attachment_monitor_ready": receipt.attachment_monitor_ready,
            "terminal_bilateral_contact_broker_ready": (
                receipt.terminal_bilateral_contact_broker_ready
            ),
            "active_attachment_present": attachment_sha256 is not None,
            "active_attachment_sha256": attachment_sha256,
            "emergency_stop_active": receipt.emergency_stop_active,
            "state_stale": (
                receipt.checked_at_ns - state.observed_at_ns
                > self.configuration.safety.maximum_state_age_ns
            ),
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        snapshot = PreflightRuntimeSnapshotV1(
            **payload,
            snapshot_sha256=canonical_sha256(payload),
        )
        self._readiness_receipt = receipt
        return snapshot


def implementation_sha256_v1(project_root: Path) -> str:
    return hashlib.sha256(
        read_regular_file_once(project_root.resolve() / IMPLEMENTATION_REPO_PATH)
    ).hexdigest()
