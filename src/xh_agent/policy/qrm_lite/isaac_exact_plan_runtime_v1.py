"""ADR-0022 active-session adapters for a frozen Isaac exact plan.

This module deliberately separates three surfaces which must not be confused:

* :class:`FrozenProbeExactPlanExecutorV1` executes an already constructed and
  fully preflighted phase sequence.  It has no planner, retry, yaw selection,
  centreline selection, or TaskSpec fallback callback.
* :class:`FrozenProbePreflightUnavailableV1` documents and enforces the current
  hard blocker: the frozen V4/M1B helpers validate IK and collision only after
  commanding motion, so they cannot satisfy ADR-0022's all-phase,
  non-actuating preflight contract.
* :func:`audit_frozen_b0_active_session_surface_v1` verifies the unchanged B0
  bytes without importing them.  Those frozen bytes expose no active-session
  callable, so composing their low-level helpers is forbidden and B0 fallback
  remains ``NO_PHYSICAL_EXECUTION``.

The executor is a real adapter, not a second implementation of robot motion:
it calls only allowlisted functions from the hash-frozen B0 probe and passes
the immutable phase's position, orientation, gripper target, step count, and
contact allowlists verbatim.  Production construction additionally requires
the accepted Phase-2 addendum/config and a ``REAL_ISAAC`` deployment binding.
No such files/binding are shipped by this module.
"""

from __future__ import annotations

import ast
import hashlib
import math
import os
from pathlib import Path
import stat
import time
from types import ModuleType
from typing import Any, Callable, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactPlanPhaseContractV1,
    ExactPlanPhaseExecutionV1,
    ExactPlanPhasePreflightV1,
    ExactPlanPreflightReceiptV1,
    ExactPlanPrimitiveDeploymentBindingV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.frozen_b0_fallback_wrapper_v1 import (
    FROZEN_B0_PROBE_PATH,
    FROZEN_B0_PROBE_SHA256,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)


ADR_0022_PATH = "docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"
ADR_0022_BINDING_ADDENDUM_PATH = "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"
ADR_0022_UNLOCK_CONFIG_PATH = "configs/m2c_s4_unlock_bindings.json"
REQUIRED_ACTIVE_SESSION_B0_ENTRYPOINT = "run_unchanged_b0_active_session_v1"
FROZEN_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
FROZEN_HELPER_SOURCE_SHA256: Mapping[str, str] = {
    "_step_pose": "81ce2b3850a3b7902fd926f36e4f49fe82120dd961b280417e227d0538c6fc87",
    "_step_gripper": "d7c4bdf8062c62a18dbae14828aa2474200192cd2ea29495abd44146ae27f5d7",
    "_attach_preserving_pose": ("7935b093d37248facd42ef6b27cbe151d2aa1a9718d5a17afdc808b28fbfdbb2"),
    "_remove_attachment": ("cba7f1833aa15c655386a82044fbd55c3790cfbefee6acf7650379f0f2676beb"),
}
SUPPORTED_SKILLS = frozenset(
    {
        "GRASP",
        "LIFT",
        "MOVE",
        "PLACE",
        "RELEASE",
        "REOBSERVE",
        "REASSOCIATE_TARGET",
        "REGRASP",
    }
)
EXPECTED_COMMANDS_BY_SKILL: Mapping[str, frozenset[str]] = {
    "GRASP": frozenset({"CARTESIAN_POSE", "GRIPPER_POSITION", "ATTACH_CONTACT_ENTITY"}),
    "REGRASP": frozenset({"CARTESIAN_POSE", "GRIPPER_POSITION", "ATTACH_CONTACT_ENTITY"}),
    "LIFT": frozenset({"CARTESIAN_POSE"}),
    "MOVE": frozenset({"CARTESIAN_POSE"}),
    "PLACE": frozenset({"CARTESIAN_POSE", "GRIPPER_POSITION"}),
    "RELEASE": frozenset({"CARTESIAN_POSE", "GRIPPER_POSITION", "REMOVE_ATTACHMENT"}),
    "REOBSERVE": frozenset({"PUBLIC_RGBD_CAPTURE"}),
    "REASSOCIATE_TARGET": frozenset({"PUBLIC_TRACK_REASSOCIATION"}),
}
_ALLOWED_FROZEN_EXECUTION_HELPERS = frozenset(
    {
        "_step_pose",
        "_step_gripper",
        "_attach_preserving_pose",
        "_remove_attachment",
        "broker_from_window",
        "evaluate_robot_collision_events",
        "RigidPrim",
        "np",
    }
)
_FORBIDDEN_RUNTIME_SELECTORS = frozenset(
    {
        "_execute_m2b_public_regrasp",
        "select_free_gap_yaw_from_xy",
        "rank_clearance_safe_yaw_candidates",
    }
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactPlanRuntimeUnavailable(ExactPlanUnavailable):
    """Raised before a command when the active-session runtime is not frozen."""


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ExactPlanRuntimeUnavailable(
                f"runtime source is not a single-link regular file: {path}"
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise ExactPlanRuntimeUnavailable(f"runtime source changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(_read_regular_file_once(path)).hexdigest()


def _top_level_function_sha256(path: Path, names: frozenset[str]) -> dict[str, str]:
    raw = _read_regular_file_once(path)
    try:
        text = raw.decode("utf-8")
        tree = ast.parse(text, filename=str(path))
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        raise ExactPlanRuntimeUnavailable("frozen probe source cannot be audited") from exc
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in names:
            continue
        segment = ast.get_source_segment(text, node)
        if segment is None:
            raise ExactPlanRuntimeUnavailable(f"cannot bind frozen helper source: {node.name}")
        found[node.name] = hashlib.sha256(segment.encode("utf-8")).hexdigest()
    if set(found) != names:
        raise ExactPlanRuntimeUnavailable("frozen probe helper source set is incomplete")
    return found


class PublicCapturePhaseReceiptV1(FrozenModel):
    """Public-only output accepted from a real REOBSERVE callback."""

    schema_version: Literal["PublicCapturePhaseReceiptV1"] = "PublicCapturePhaseReceiptV1"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    capture_label: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    captured_at_ns: int = Field(gt=0)
    rgb_sha256: str = Field(pattern=SHA256_PATTERN)
    depth_sha256: str = Field(pattern=SHA256_PATTERN)
    canonical_public_tracks_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    real_isaac: bool
    mocked_physics: bool
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def mode_is_honest(self) -> "PublicCapturePhaseReceiptV1":
        if self.real_isaac == self.mocked_physics:
            raise ValueError("capture must be exactly real Isaac or mocked/contract")
        return self


class PublicReassociationPhaseReceiptV1(FrozenModel):
    """Public-track-only output accepted from REASSOCIATE_TARGET."""

    schema_version: Literal["PublicReassociationPhaseReceiptV1"] = (
        "PublicReassociationPhaseReceiptV1"
    )
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    input_capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    input_public_tracks_sha256: str = Field(pattern=SHA256_PATTERN)
    requested_public_track_id: str = Field(min_length=1)
    resulting_public_track_id: str = Field(min_length=1)
    association_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    computed_at_ns: int = Field(gt=0)
    real_isaac: bool
    mocked_physics: bool
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def mode_is_honest(self) -> "PublicReassociationPhaseReceiptV1":
        if self.real_isaac == self.mocked_physics:
            raise ValueError("association must be exactly real Isaac or mocked/contract")
        return self


class ExactPlanIsaacPhaseAuditV1(FrozenModel):
    """Sanitized persistent record; no simulator entity identity is retained."""

    schema_version: Literal["ExactPlanIsaacPhaseAuditV1"] = "ExactPlanIsaacPhaseAuditV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    command: str = Field(min_length=1)
    status: Literal["PASS", "FAILED"]
    sanitized_result_sha256: str = Field(pattern=SHA256_PATTERN)
    physical_command_dispatched: bool
    hidden_replan_used: Literal[False] = False
    runtime_selector_used: Literal[False] = False
    retry_used: Literal[False] = False
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class FrozenB0ActiveSessionSurfaceAuditV1(FrozenModel):
    schema_version: Literal["FrozenB0ActiveSessionSurfaceAuditV1"] = (
        "FrozenB0ActiveSessionSurfaceAuditV1"
    )
    probe_path: Literal["scripts/isaac_m1b_actuation_probe.py"] = FROZEN_B0_PROBE_PATH
    probe_sha256: Literal["1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"] = (
        FROZEN_B0_PROBE_SHA256
    )
    required_entrypoint: Literal["run_unchanged_b0_active_session_v1"] = (
        REQUIRED_ACTIVE_SESSION_B0_ENTRYPOINT
    )
    required_entrypoint_present: Literal[False] = False
    frozen_main_rejected_for_active_session: Literal[True] = True
    low_level_helper_composition_rejected_as_unchanged_b0: Literal[True] = True
    active_session_unchanged_b0_available: Literal[False] = False
    physical_execution_performed: Literal[False] = False
    reason: Literal[
        "FROZEN_B0_BYTES_HAVE_NO_ACTIVE_SESSION_CALLABLE_AND_MAY_NOT_BE_REIMPLEMENTED"
    ] = "FROZEN_B0_BYTES_HAVE_NO_ACTIVE_SESSION_CALLABLE_AND_MAY_NOT_BE_REIMPLEMENTED"
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "FrozenB0ActiveSessionSurfaceAuditV1":
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(payload):
            raise ValueError("active-session B0 surface audit digest differs")
        return self


class PersistentIsaacJournalV1(Protocol):
    def append(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


class ActiveSessionMutationRecorderV1(Protocol):
    """Mutation intent recorder shared with the formal A.3 query sources."""

    def record_scene_mutations(self, count: int = 1) -> None: ...

    def record_attachment_mutations(self, count: int = 1) -> None: ...


class ActiveSessionAttachmentRegistryV1(Protocol):
    def commit_attachment(
        self,
        *,
        public_track_id: str,
        external_contact_path: str,
        bound_plan_sha256: str,
        phase_sha256: str,
    ) -> Any: ...

    def commit_removal(
        self,
        *,
        bound_plan_sha256: str,
        phase_sha256: str,
    ) -> Any: ...


class FrozenProbePreflightUnavailableV1:
    """Fail-closed preflight adapter for the currently frozen helper surface."""

    def __init__(self) -> None:
        self.implementation_sha256 = _file_sha256(Path(__file__))

    def verify_phase(
        self,
        _plan: M2CExactPlanPrimitivePlanV1,
        _phase: ExactPlanPhaseContractV1,
    ) -> ExactPlanPhasePreflightV1:
        raise ExactPlanRuntimeUnavailable(
            "FROZEN_PROBE_HAS_NO_NON_ACTUATING_ALL_PHASE_IK_LIMITS_SWEPT_"
            "COLLISION_CONTROLLER_SAFETY_PREFLIGHT"
        )


def validate_eight_skill_phase_surface_v1(
    plans: Mapping[str, M2CExactPlanPrimitivePlanV1],
) -> str:
    """Validate a complete eight-skill plan set without executing it.

    This is intentionally structural.  It cannot replace A.3 real-Isaac
    preflight or A.4 real phase receipts and is never formal evidence.
    """

    if set(plans) != SUPPORTED_SKILLS:
        raise ExactPlanRuntimeUnavailable("eight-skill exact-plan set is incomplete or extra")
    projection: list[dict[str, object]] = []
    for skill in sorted(SUPPORTED_SKILLS):
        plan = plans[skill]
        if plan.exact_execution_plan.canonical_skill != skill:
            raise ExactPlanRuntimeUnavailable("eight-skill plan key differs from canonical skill")
        commands = tuple(phase.phase.command for phase in plan.phases)
        if not EXPECTED_COMMANDS_BY_SKILL[skill].issubset(commands):
            raise ExactPlanRuntimeUnavailable(f"{skill} exact-plan command surface is incomplete")
        if skill == "REOBSERVE" and commands != ("PUBLIC_RGBD_CAPTURE",):
            raise ExactPlanRuntimeUnavailable("REOBSERVE is not exactly one public capture")
        if skill == "REASSOCIATE_TARGET" and commands != ("PUBLIC_TRACK_REASSOCIATION",):
            raise ExactPlanRuntimeUnavailable(
                "REASSOCIATE_TARGET is not exactly one public association"
            )
        projection.append(
            {
                "skill": skill,
                "bound_plan_sha256": plan.bound_plan_sha256,
                "phase_schema_sha256": plan.phase_schema_sha256,
                "commands": commands,
            }
        )
    return canonical_sha256(projection)


def audit_frozen_b0_active_session_surface_v1(
    project_root: Path,
) -> FrozenB0ActiveSessionSurfaceAuditV1:
    """Inspect unchanged B0 bytes without importing or executing the probe."""

    probe_path = project_root.resolve() / FROZEN_B0_PROBE_PATH
    raw = _read_regular_file_once(probe_path)
    if hashlib.sha256(raw).hexdigest() != FROZEN_B0_PROBE_SHA256:
        raise ExactPlanRuntimeUnavailable("frozen B0 probe digest differs")
    try:
        tree = ast.parse(raw, filename=str(probe_path))
    except (SyntaxError, ValueError) as exc:
        raise ExactPlanRuntimeUnavailable("frozen B0 probe cannot be audited") from exc
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if REQUIRED_ACTIVE_SESSION_B0_ENTRYPOINT in top_level_functions:
        # The pinned bytes are known not to contain this symbol.  Reaching this
        # branch means the parser and the pinned digest disagree, so never call it.
        raise ExactPlanRuntimeUnavailable("unexpected active-session B0 symbol in frozen bytes")
    payload: dict[str, object] = {
        "schema_version": "FrozenB0ActiveSessionSurfaceAuditV1",
        "probe_path": FROZEN_B0_PROBE_PATH,
        "probe_sha256": FROZEN_B0_PROBE_SHA256,
        "required_entrypoint": REQUIRED_ACTIVE_SESSION_B0_ENTRYPOINT,
        "required_entrypoint_present": False,
        "frozen_main_rejected_for_active_session": True,
        "low_level_helper_composition_rejected_as_unchanged_b0": True,
        "active_session_unchanged_b0_available": False,
        "physical_execution_performed": False,
        "reason": ("FROZEN_B0_BYTES_HAVE_NO_ACTIVE_SESSION_CALLABLE_AND_MAY_NOT_BE_REIMPLEMENTED"),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return FrozenB0ActiveSessionSurfaceAuditV1(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


class FrozenProbeExactPlanExecutorV1:
    """Execute immutable phases by calling only hash-frozen probe primitives.

    ``CONTRACT_TEST`` may use fakes and always reports ``operation_executed``
    false.  ``REAL_ISAAC`` construction validates the Phase-2 deployment
    binding and all relevant source bytes before exposing any execution method.
    The enclosing :class:`M2CExactPlanPrimitiveBundleV1` remains responsible
    for validating every preflight result before it calls this executor.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        probe: ModuleType | Any,
        robot: Any,
        hand_prim: Any,
        contact_collector: Any,
        sensors: Mapping[str, Any],
        contact_views: Mapping[str, Any],
        journal: PersistentIsaacJournalV1,
        state_digest: Callable[[], str],
        capture_public: Callable[
            [M2CExactPlanPrimitivePlanV1, ExactPlanPhaseContractV1],
            PublicCapturePhaseReceiptV1,
        ],
        reassociate_public: Callable[
            [M2CExactPlanPrimitivePlanV1, ExactPlanPhaseContractV1],
            PublicReassociationPhaseReceiptV1,
        ],
        mutation_counter_source: ActiveSessionMutationRecorderV1 | None = None,
        attachment_state_registry: ActiveSessionAttachmentRegistryV1 | None = None,
        deployment_binding: ExactPlanPrimitiveDeploymentBindingV1 | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.mode = mode
        self.real_isaac = mode == "REAL_ISAAC"
        self.probe = probe
        self.robot = robot
        self.hand_prim = hand_prim
        self.contact_collector = contact_collector
        self.sensors = dict(sensors)
        self.contact_views = dict(contact_views)
        self.journal = journal
        self.state_digest = state_digest
        self.capture_public = capture_public
        self.reassociate_public = reassociate_public
        self.mutation_counter_source = mutation_counter_source
        self.attachment_state_registry = attachment_state_registry
        self.deployment_binding = deployment_binding
        self.implementation_sha256 = _file_sha256(Path(__file__))
        self._authorized_plan: str | None = None
        self._authorized_preflight: str | None = None
        self._next_phase_index = 0
        self._poisoned = False
        self._attachment_candidate: str | None = None
        self._attachment_candidate_phase_index: int | None = None
        self._phase_operation_started = False
        if self.real_isaac:
            # Guard construction before any source/module inspection can lead
            # to a new Isaac experiment service or physical command.
            require_pre_freeze(M2CExperimentAction.FORMAL_ISAAC_SERVICE)
        self._verify_runtime_surface()

    def _verify_runtime_surface(self) -> None:
        missing = sorted(
            name for name in _ALLOWED_FROZEN_EXECUTION_HELPERS if not hasattr(self.probe, name)
        )
        if missing:
            raise ExactPlanRuntimeUnavailable(
                "frozen probe execution surface is incomplete: " + ",".join(missing)
            )
        if self.mode == "CONTRACT_TEST":
            if self.deployment_binding is not None:
                raise ExactPlanRuntimeUnavailable(
                    "contract-test executor may not accept a production deployment binding"
                )
            return
        if self.mutation_counter_source is None:
            raise ExactPlanRuntimeUnavailable(
                "REAL_ISAAC executor requires the shared active-session mutation counter"
            )
        if self.attachment_state_registry is None:
            raise ExactPlanRuntimeUnavailable(
                "REAL_ISAAC executor requires the shared active-session attachment registry"
            )
        binding = self.deployment_binding
        if binding is None or binding.execution_mode != "REAL_ISAAC":
            raise ExactPlanRuntimeUnavailable(
                "REAL_ISAAC executor requires the reviewed Phase-2 deployment binding"
            )
        addendum = self.project_root / ADR_0022_BINDING_ADDENDUM_PATH
        unlock = self.project_root / ADR_0022_UNLOCK_CONFIG_PATH
        if (
            _file_sha256(addendum) != binding.binding_addendum_sha256
            or _file_sha256(unlock) != binding.unlock_config_sha256
        ):
            raise ExactPlanRuntimeUnavailable("Phase-2 addendum/config digest differs")
        role_hashes = {item.role: item.sha256 for item in binding.source_bindings}
        if role_hashes.get("EXECUTOR_IMPLEMENTATION") != self.implementation_sha256:
            raise ExactPlanRuntimeUnavailable("executor source differs from deployment binding")
        probe_path = Path(str(getattr(self.probe, "__file__", ""))).resolve()
        if _file_sha256(probe_path) != FROZEN_V4_PROBE_SHA256:
            raise ExactPlanRuntimeUnavailable("loaded frozen V4 probe source digest differs")
        if getattr(self.probe, "ACTUATION_PROBE_SOURCE_SHA256", None) != FROZEN_V4_PROBE_SHA256:
            raise ExactPlanRuntimeUnavailable("loaded frozen probe self-digest differs")
        if _top_level_function_sha256(
            probe_path,
            frozenset(FROZEN_HELPER_SOURCE_SHA256),
        ) != dict(FROZEN_HELPER_SOURCE_SHA256):
            raise ExactPlanRuntimeUnavailable("frozen execution helper source digest differs")
        # Never inspect or call the selectors; their mere availability is
        # expected in the frozen module, but this adapter's allowlist excludes them.
        if not _FORBIDDEN_RUNTIME_SELECTORS.isdisjoint(_ALLOWED_FROZEN_EXECUTION_HELPERS):
            raise ExactPlanRuntimeUnavailable("runtime selector entered executor allowlist")

    def verify_bound_plan_before_execution(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        preflight: ExactPlanPreflightReceiptV1,
    ) -> str:
        self._verify_runtime_surface()
        if self._authorized_plan is not None or self._poisoned:
            raise ExactPlanRuntimeUnavailable("executor is single-use or poisoned")
        if plan.exact_execution_plan.canonical_skill not in SUPPORTED_SKILLS:
            raise ExactPlanRuntimeUnavailable("plan skill is outside ADR-0022")
        if preflight.bound_plan_sha256 != plan.bound_plan_sha256:
            raise ExactPlanRuntimeUnavailable("preflight crossed bound plan")
        if len(preflight.phase_results) != len(plan.phases):
            raise ExactPlanRuntimeUnavailable("preflight does not cover every phase")
        for phase, result in zip(plan.phases, preflight.phase_results):
            if (
                result.phase_index != phase.phase.phase_index
                or result.phase_sha256 != phase.phase_sha256
                or result.preplan_state_sha256 != plan.inputs.preplan_state_sha256
            ):
                raise ExactPlanRuntimeUnavailable("preflight phase/state binding differs")
        if self.state_digest() != plan.inputs.preplan_state_sha256:
            raise ExactPlanRuntimeUnavailable("active session state changed after preflight")
        self._authorized_plan = plan.bound_plan_sha256
        self._authorized_preflight = preflight.receipt_sha256
        self.journal.append(
            "EXACT_PLAN_BOUND_BEFORE_EXECUTION",
            {
                "bound_plan_sha256": plan.bound_plan_sha256,
                "preflight_receipt_sha256": preflight.receipt_sha256,
                "phase_count": len(plan.phases),
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
        )
        return plan.bound_plan_sha256

    @staticmethod
    def _path_is_allowed(path: str, prefixes: tuple[str, ...]) -> bool:
        return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)

    def _execute_pose(self, phase: ExactPlanPhaseContractV1) -> dict[str, object]:
        wire = phase.phase
        # Preserve the wire's Python/JSON float values.  Forcing the frozen
        # probe's historical float32 convenience dtype here would itself be a
        # runtime parameter adaptation prohibited by ADR-0022 A.2/A.4.
        goal = self.probe.np.asarray(wire.goal_position_world_m)
        orientation = self.probe.np.asarray(wire.orientation_world_wxyz)
        self._phase_operation_started = True
        result = self.probe._step_pose(
            self.robot,
            goal,
            steps=wire.steps,
            orientation_wxyz=orientation,
            contact_collector=self.contact_collector,
            collision_phase=wire.collision_phase,
            allowed_robot_contact_paths=wire.allowed_robot_contact_paths,
            allowed_external_contact_paths=wire.allowed_external_contact_paths,
        )
        expected_goal = goal.tolist()
        expected_orientation = orientation.tolist()
        if (
            list(result.get("goal_world_m", ())) != expected_goal
            or list(result.get("orientation_world_wxyz", ())) != expected_orientation
            or result.get("steps") != wire.steps
        ):
            raise ExactPlanRuntimeUnavailable("frozen pose helper altered exact phase parameters")
        final_error = float(result.get("final_error_m", math.inf))
        collision = result.get("collision_gate")
        if (
            not math.isfinite(final_error)
            or final_error > phase.convergence_tolerance_m
            or not isinstance(collision, Mapping)
            or collision.get("status") != "PASS"
        ):
            raise ExactPlanRuntimeUnavailable("pose execution controller/collision gate failed")
        return {
            "command": wire.command,
            "final_error_m": final_error,
            "collision_status": "PASS",
            "phase_sha256": phase.phase_sha256,
        }

    def _execute_gripper(self, phase: ExactPlanPhaseContractV1) -> dict[str, object]:
        wire = phase.phase
        self._phase_operation_started = True
        samples, _sensor_frames, _tensor_frames, physx_frames = self.probe._step_gripper(
            self.robot,
            wire.gripper_position_m,
            steps=wire.steps,
            sensors=self.sensors,
            contact_views=self.contact_views,
            contact_collector=self.contact_collector,
        )
        events = [dict(event) for frame in physx_frames for event in frame.get("events", ())]
        collision = self.probe.evaluate_robot_collision_events(
            events,
            phase=wire.collision_phase,
            allowed_robot_collider_prefixes=wire.allowed_robot_contact_paths,
            allowed_external_collider_prefixes=wire.allowed_external_contact_paths,
        )
        if collision.get("status") != "PASS":
            raise ExactPlanRuntimeUnavailable("gripper execution collision gate failed")
        feedback, broker = self.probe.broker_from_window(samples)
        self._attachment_candidate = None
        self._attachment_candidate_phase_index = None
        if bool(getattr(feedback, "grasp_success", False)):
            entity = broker.get("actual_sim_entity_id")
            if not isinstance(entity, str) or not entity:
                raise ExactPlanRuntimeUnavailable("bilateral broker omitted its internal entity")
            self._attachment_candidate = entity
            self._attachment_candidate_phase_index = wire.phase_index
        return {
            "command": wire.command,
            "collision_status": "PASS",
            "bilateral_contact_selected": self._attachment_candidate is not None,
            "phase_sha256": phase.phase_sha256,
        }

    def _execute_attach(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> dict[str, object]:
        wire = phase.phase
        entity = self._attachment_candidate
        if entity is None or self._attachment_candidate_phase_index != wire.phase_index - 1:
            raise ExactPlanRuntimeUnavailable(
                "attachment lacks an immediately preceding terminal bilateral broker result"
            )
        object_path = f"/World/M1B/{entity}/link"
        if not self._path_is_allowed(object_path, wire.allowed_external_contact_paths):
            raise ExactPlanRuntimeUnavailable(
                "broker entity is outside the bound contact allowlist"
            )
        object_prim = self.probe.RigidPrim(object_path)
        self._phase_operation_started = True
        if self.mutation_counter_source is None:
            raise ExactPlanRuntimeUnavailable("attachment mutation counter is unavailable")
        self.mutation_counter_source.record_scene_mutations()
        self.mutation_counter_source.record_attachment_mutations()
        self.probe._attach_preserving_pose(entity, self.hand_prim, object_prim)
        attachment_receipt_sha256 = None
        if self.attachment_state_registry is not None:
            attachment = self.attachment_state_registry.commit_attachment(
                public_track_id=plan.inputs.target_track_id,
                external_contact_path=object_path,
                bound_plan_sha256=plan.bound_plan_sha256,
                phase_sha256=phase.phase_sha256,
            )
            attachment_receipt_sha256 = str(attachment.receipt_sha256)
        elif self.real_isaac:
            raise ExactPlanRuntimeUnavailable("active attachment registry is unavailable")
        # Entity identity is actuation-internal and intentionally absent from
        # the public/persistent model-path audit projection.
        return {
            "command": wire.command,
            "attachment_status": "PASS",
            "selector": wire.contact_entity_selection,
            "active_attachment_receipt_sha256": attachment_receipt_sha256,
            "phase_sha256": phase.phase_sha256,
        }

    def _execute_remove(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> dict[str, object]:
        self._phase_operation_started = True
        if self.mutation_counter_source is None:
            raise ExactPlanRuntimeUnavailable("attachment mutation counter is unavailable")
        self.mutation_counter_source.record_scene_mutations()
        self.mutation_counter_source.record_attachment_mutations()
        self.probe._remove_attachment()
        removal_receipt_sha256 = None
        if self.attachment_state_registry is not None:
            removal = self.attachment_state_registry.commit_removal(
                bound_plan_sha256=plan.bound_plan_sha256,
                phase_sha256=phase.phase_sha256,
            )
            removal_receipt_sha256 = str(removal.receipt_sha256)
        elif self.real_isaac:
            raise ExactPlanRuntimeUnavailable("active attachment registry is unavailable")
        self._attachment_candidate = None
        self._attachment_candidate_phase_index = None
        return {
            "command": phase.phase.command,
            "attachment_removal_status": "PASS",
            "attachment_removal_receipt_sha256": removal_receipt_sha256,
            "phase_sha256": phase.phase_sha256,
        }

    def _execute_capture(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> dict[str, object]:
        self._phase_operation_started = True
        result = self.capture_public(plan, phase)
        wire = phase.phase
        if (
            result.run_id != plan.inputs.run_id
            or result.session_id != plan.inputs.session_id
            or result.decision_index != plan.inputs.decision_index
            or result.capture_label != wire.public_capture_label
            or result.real_isaac != self.real_isaac
            or result.mocked_physics == self.real_isaac
        ):
            raise ExactPlanRuntimeUnavailable("public capture receipt crossed plan/mode")
        return result.model_dump(mode="json")

    def _execute_reassociation(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> dict[str, object]:
        self._phase_operation_started = True
        result = self.reassociate_public(plan, phase)
        wire = phase.phase
        if (
            result.run_id != plan.inputs.run_id
            or result.session_id != plan.inputs.session_id
            or result.decision_index != plan.inputs.decision_index
            or result.requested_public_track_id != wire.public_target_track_id
            or result.real_isaac != self.real_isaac
            or result.mocked_physics == self.real_isaac
        ):
            raise ExactPlanRuntimeUnavailable("public reassociation receipt crossed plan/mode")
        return result.model_dump(mode="json")

    def _dispatch_exact_command(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
    ) -> dict[str, object]:
        command = phase.phase.command
        if command == "CARTESIAN_POSE":
            return self._execute_pose(phase)
        if command == "GRIPPER_POSITION":
            return self._execute_gripper(phase)
        if command == "ATTACH_CONTACT_ENTITY":
            return self._execute_attach(plan, phase)
        if command == "REMOVE_ATTACHMENT":
            return self._execute_remove(plan, phase)
        if command == "PUBLIC_RGBD_CAPTURE":
            return self._execute_capture(plan, phase)
        if command == "PUBLIC_TRACK_REASSOCIATION":
            return self._execute_reassociation(plan, phase)
        raise ExactPlanRuntimeUnavailable(f"unsupported exact command: {command}")

    def execute_precomputed_phase(
        self,
        plan: M2CExactPlanPrimitivePlanV1,
        phase: ExactPlanPhaseContractV1,
        preflight: ExactPlanPhasePreflightV1,
    ) -> ExactPlanPhaseExecutionV1:
        if self.real_isaac:
            # A pre-freeze service must not execute a phase after midnight.
            require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
        if self._poisoned:
            raise ExactPlanRuntimeUnavailable("executor is poisoned after phase failure")
        if (
            self._authorized_plan != plan.bound_plan_sha256
            or self._authorized_preflight is None
            or phase.phase.phase_index != self._next_phase_index
            or preflight.phase_index != phase.phase.phase_index
            or preflight.phase_sha256 != phase.phase_sha256
            or preflight.bound_plan_sha256 != plan.bound_plan_sha256
        ):
            raise ExactPlanRuntimeUnavailable("phase is not the next preflighted exact command")
        started_at_ns = time.time_ns()
        self.journal.append(
            "EXACT_PLAN_PHASE_EXECUTION_STARTED",
            {
                "bound_plan_sha256": plan.bound_plan_sha256,
                "phase_index": phase.phase.phase_index,
                "phase_sha256": phase.phase_sha256,
                "command": phase.phase.command,
                "physical_command_dispatched": False,
            },
        )
        status: Literal["PASS", "FAILED"] = "PASS"
        outcome = f"{phase.phase.command}_PASS"
        dispatched = False
        sanitized: dict[str, object]
        self._phase_operation_started = False
        try:
            sanitized = self._dispatch_exact_command(plan, phase)
            dispatched = self._phase_operation_started
        except Exception as exc:
            dispatched = self._phase_operation_started
            status = "FAILED"
            outcome = f"{phase.phase.command}_FAILED:{type(exc).__name__}"
            sanitized = {
                "command": phase.phase.command,
                "status": "FAILED",
                "error_type": type(exc).__name__,
                "phase_sha256": phase.phase_sha256,
            }
            self._poisoned = True
        completed_at_ns = max(time.time_ns(), started_at_ns + 1)
        audit = ExactPlanIsaacPhaseAuditV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            command=phase.phase.command,
            status=status,
            sanitized_result_sha256=canonical_sha256(sanitized),
            physical_command_dispatched=dispatched and self.real_isaac,
        )
        self.journal.append("EXACT_PLAN_PHASE_EXECUTION_COMMITTED", audit.model_dump(mode="json"))
        self._next_phase_index += 1
        return ExactPlanPhaseExecutionV1(
            bound_plan_sha256=plan.bound_plan_sha256,
            phase_index=phase.phase.phase_index,
            phase_sha256=phase.phase_sha256,
            started_at_ns=started_at_ns,
            completed_at_ns=completed_at_ns,
            status=status,
            operation_executed=dispatched and self.real_isaac,
            controller_outcome=outcome,
            real_isaac=self.real_isaac,
            contract_test_only=not self.real_isaac,
        )
