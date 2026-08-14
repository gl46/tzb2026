"""Deployment-bound exact-plan synthesis for the eight formal M2C skills.

The legacy Isaac probe chooses yaw and contact height while actuating.  That
behaviour is intentionally not reused here.  This module consumes one
query-only active-session snapshot and the replayed public observation, then
freezes one complete plan before the A.3 whole-plan preflight can run.

The module is not an execution authority.  ``REAL_ISAAC`` construction needs
an accepted deployment binding and exact source bytes; the resulting plan is
still non-executable until the independent primitive bundle accepts its full
preflight receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.grasp.free_gap import (
    isaac_top_down_orientation_wxyz,
    select_free_gap_yaw_from_xy,
)
from xh_agent.policy.qrm_lite.exact_plan_primitive_bundle_v1 import (
    ExactGraspGeometryV1,
    ExactPlanA1InputsV1,
    ExactPlanPhaseContractV1,
    ExactPlanSourceBindingV1,
    ExactPlanUnavailable,
    M2CExactPlanPrimitivePlanV1,
)
from xh_agent.policy.qrm_lite.formal_bound_plan_provider_v1 import (
    BoundExactPlanSynthesisResultV1,
    FormalPreplanStateReceiptV1,
)
from xh_agent.policy.qrm_lite.formal_exact_plan_runtime_v1 import (
    canonical_runtime_mapping_sha256_v1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    ExactExecutionPhaseGatesV2,
    ExactExecutionPhaseV2,
    ExactExecutionPlanV2,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacExecuteRequestV4
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once
from xh_agent.policy.qrm_lite.skill_registry_v2 import RuntimeSkillMappingResultV2


_SKILL_TO_ACTION = {
    "GRASP": "B0_PUBLIC_GEOMETRY_GRASP",
    "LIFT": "B0_CARTESIAN_LIFT",
    "MOVE": "B0_PUBLIC_GEOMETRY_MOVE",
    "PLACE": "B0_PUBLIC_GEOMETRY_PLACE",
    "RELEASE": "B0_RELEASE",
    "REOBSERVE": "HOLD_AND_CAPTURE_PUBLIC_RGBD",
    "REASSOCIATE_TARGET": "PUBLIC_TRACK_REASSOCIATION",
    "REGRASP": "B0_PUBLIC_GEOMETRY_REGRASP",
}
_PHYSICAL_SKILLS = frozenset({"GRASP", "LIFT", "MOVE", "PLACE", "RELEASE", "REGRASP"})
_ATTACHED_SKILLS = frozenset({"LIFT", "MOVE", "PLACE", "RELEASE"})
_SOURCE_ROLES = frozenset(
    {
        "PRIMITIVE_ENTRYPOINT",
        "PREFLIGHT_IMPLEMENTATION",
        "EXECUTOR_IMPLEMENTATION",
        "TRANSITIVE_DEPENDENCY_MANIFEST",
        "ISAAC_RUNTIME",
        "IK_ALGORITHM",
        "JOINT_LIMIT_CONFIGURATION",
        "SWEPT_COLLISION_ALGORITHM",
        "ROBOT_ASSET",
        "CONTROLLER_CONFIGURATION",
        "SAFETY_CONFIGURATION",
        "SCENE_ASSET",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(read_regular_file_once(path)).hexdigest()


def _finite_tuple(values: tuple[float, ...], *, name: str) -> tuple[float, ...]:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{name} contains NaN/Inf")
    return values


class FormalExactPlanSynthesisConfigurationV1(_FrozenModel):
    """All numeric choices made by synthesis rather than the executor."""

    schema_version: Literal["FormalExactPlanSynthesisConfigurationV1"] = (
        "FormalExactPlanSynthesisConfigurationV1"
    )
    revision: Literal["M2C_ADR0024_EXACT_PLAN_SYNTHESIS_V1"] = "M2C_ADR0024_EXACT_PLAN_SYNTHESIS_V1"
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_bindings: tuple[ExactPlanSourceBindingV1, ...] = Field(min_length=12, max_length=12)
    controller_frequency_hz: Literal[60.0] = 60.0
    convergence_tolerance_m: Literal[0.02] = 0.02
    phase_timeout_ns: int = Field(gt=0)
    preplan_freshness_limit_ns: int = Field(gt=0)
    expected_grasp_category_prefix: Literal["industrial_cylinder"] = "industrial_cylinder"
    pregrasp_height_m: Literal[0.27] = 0.27
    grasp_lift_height_m: float = Field(gt=0.0)
    contact_centerline_m: float = Field(ge=0.06, le=0.15)
    preclose_finger_position_m: float = Field(ge=0.0, le=0.08)
    close_finger_position_m: float = Field(ge=0.0, le=0.08)
    open_finger_position_m: float = Field(ge=0.0, le=0.08)
    default_lift_height_m: float = Field(gt=0.0, le=0.20)
    place_approach_height_m: float = Field(gt=0.0)
    retreat_height_m: float = Field(gt=0.0)
    approach_steps: Literal[150] = 150
    contact_steps: Literal[120] = 120
    preclose_steps: Literal[48] = 48
    preclose_settle_steps: Literal[24] = 24
    close_steps: Literal[72] = 72
    contact_observation_steps: Literal[60] = 60
    lift_steps: Literal[150] = 150
    transport_steps: int = Field(gt=0)
    place_steps: int = Field(gt=0)
    release_steps: Literal[60] = 60
    retreat_steps: Literal[90] = 90
    controlled_robot_links: tuple[str, ...] = Field(min_length=1)
    permitted_robot_contact_paths: tuple[str, ...] = Field(min_length=2)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    task_spec_fallback_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def configuration_is_canonical(self) -> "FormalExactPlanSynthesisConfigurationV1":
        roles = [binding.role for binding in self.source_bindings]
        if len(roles) != len(set(roles)) or frozenset(roles) != _SOURCE_ROLES:
            raise ValueError("exact-plan synthesis source roles differ")
        if len(self.controlled_robot_links) != len(set(self.controlled_robot_links)):
            raise ValueError("controlled robot links repeat")
        if len(self.permitted_robot_contact_paths) != len(set(self.permitted_robot_contact_paths)):
            raise ValueError("permitted robot contact paths repeat")
        if self.close_finger_position_m >= self.preclose_finger_position_m:
            raise ValueError("grasp close target is not inside the preclose target")
        if self.open_finger_position_m <= self.preclose_finger_position_m:
            raise ValueError("open hand target is not outside the preclose target")
        numeric = (
            self.grasp_lift_height_m,
            self.contact_centerline_m,
            self.preclose_finger_position_m,
            self.close_finger_position_m,
            self.open_finger_position_m,
            self.default_lift_height_m,
            self.place_approach_height_m,
            self.retreat_height_m,
        )
        _finite_tuple(numeric, name="exact-plan synthesis configuration")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"configuration_sha256"}))
        if self.configuration_sha256 != expected:
            raise ValueError("exact-plan synthesis configuration digest differs")
        return self


class FormalPlanSynthesisStateV1(_FrozenModel):
    """Query-only active-session state; no commanded target is exposed."""

    schema_version: Literal["FormalPlanSynthesisStateV1"] = "FormalPlanSynthesisStateV1"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    active_session_runtime_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_safety_binding_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_geometry_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    active_attachment_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    end_effector_position_world_m: tuple[float, float, float]
    end_effector_orientation_world_wxyz: tuple[float, float, float, float]
    gripper_position_m: float = Field(ge=0.0, le=0.08)
    attached_public_track_id: str | None = Field(default=None, pattern=r"^track-[0-9a-f]{8}$")
    dynamic_contact_allowlist_paths: tuple[str, ...] = ()
    environment_collision_paths: tuple[str, ...] = Field(min_length=1)
    state_timestamp_ns: int = Field(gt=0)
    state_sha256: str = Field(pattern=SHA256_PATTERN)
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    evaluator_identity_used: Literal[False] = False
    task_spec_fallback_used: Literal[False] = False
    privileged_identity_or_pose_used: Literal[False] = False
    privileged_contact_or_success_truth_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def state_is_canonical(self) -> "FormalPlanSynthesisStateV1":
        _finite_tuple(self.end_effector_position_world_m, name="end-effector position")
        _finite_tuple(self.end_effector_orientation_world_wxyz, name="end-effector orientation")
        norm = math.sqrt(sum(value * value for value in self.end_effector_orientation_world_wxyz))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("query-only end-effector orientation is not normalized")
        if (
            self.dynamic_contact_allowlist_paths
            != tuple(sorted(set(self.dynamic_contact_allowlist_paths)))
            or self.environment_collision_paths
            != tuple(sorted(set(self.environment_collision_paths)))
            or any(
                not path.startswith("/World/")
                for path in (
                    *self.dynamic_contact_allowlist_paths,
                    *self.environment_collision_paths,
                )
            )
        ):
            raise ValueError("query-only scene path inventory is not canonical")
        if (self.attached_public_track_id is None) != (
            self.active_attachment_receipt_sha256 is None
        ):
            raise ValueError("query-only attachment identity lacks its execution receipt")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"state_sha256"}))
        if self.state_sha256 != expected:
            raise ValueError("query-only plan-synthesis state digest differs")
        return self


class FormalPlanSynthesisSnapshotV1(_FrozenModel):
    schema_version: Literal["FormalPlanSynthesisSnapshotV1"] = "FormalPlanSynthesisSnapshotV1"
    state: FormalPlanSynthesisStateV1
    receipt: FormalPreplanStateReceiptV1

    @model_validator(mode="after")
    def receipt_binds_state(self) -> "FormalPlanSynthesisSnapshotV1":
        expected = {
            "run_id": self.state.run_id,
            "session_id": self.state.session_id,
            "decision_index": self.state.decision_index,
            "observation_id": self.state.observation_id,
            "capture_receipt_sha256": self.state.capture_receipt_sha256,
            "formal_observation_sha256": self.state.formal_observation_sha256,
            "state_sha256": self.state.state_sha256,
            "state_frame": "world",
            "state_dimensions": 8,
            "state_units": "world_m,normalized_wxyz,gripper_m",
            "state_timestamp_ns": self.state.state_timestamp_ns,
        }
        if any(getattr(self.receipt, name) != value for name, value in expected.items()):
            raise ValueError("query-only state receipt crosses its canonical state")
        return self


class FormalPlanSynthesisStateQueryV1(Protocol):
    implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool

    def query_plan_synthesis_state(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
    ) -> FormalPlanSynthesisSnapshotV1: ...


class FormalExactPlanSynthesisDeploymentV1(_FrozenModel):
    schema_version: Literal["FormalExactPlanSynthesisDeploymentV1"] = (
        "FormalExactPlanSynthesisDeploymentV1"
    )
    accepted_adr_0022_path: Literal[
        "docs/decisions/ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md"
    ]
    accepted_adr_0022_sha256: str = Field(pattern=SHA256_PATTERN)
    accepted_adr_0024_path: Literal["docs/decisions/ADR-0024-m2c-s4-unblock-directive.md"]
    accepted_adr_0024_sha256: str = Field(pattern=SHA256_PATTERN)
    binding_addendum_path: Literal["docs/decisions/ADR-0022-BINDING-ADDENDUM.md"]
    binding_addendum_sha256: str = Field(pattern=SHA256_PATTERN)
    unlock_config_path: Literal["configs/m2c_s4_unlock_bindings.json"]
    unlock_config_sha256: str = Field(pattern=SHA256_PATTERN)
    synthesis_configuration_path: str = Field(min_length=1)
    synthesis_configuration_file_sha256: str = Field(pattern=SHA256_PATTERN)
    backend_implementation_path: Literal[
        "src/xh_agent/policy/qrm_lite/formal_exact_plan_synthesis_v1.py"
    ]
    backend_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    query_source_implementation_path: str = Field(min_length=1)
    query_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reviewed_addendum_accepted: Literal[True] = True
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


def _phase_gates(*, logical: bool) -> ExactExecutionPhaseGatesV2:
    detail = (
        "NOT_APPLICABLE_LOGICAL_FRESHNESS_OPERATION"
        if logical
        else "FULL_PLAN_A3_QUERY_ONLY_PREFLIGHT_REQUIRED_BEFORE_EXECUTION"
    )
    return ExactExecutionPhaseGatesV2(
        ik_detail=detail,
        joint_limits_detail=detail,
        swept_collision_detail=detail,
        controller_detail=detail,
        safety_detail=detail,
    )


class ConfiguredFormalExactPlanSynthesisBackendV1:
    """Deterministic plan builder; never calls a controller or simulator step."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        configuration: FormalExactPlanSynthesisConfigurationV1,
        query_source: FormalPlanSynthesisStateQueryV1,
        deployment: FormalExactPlanSynthesisDeploymentV1 | None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.project_root = project_root.resolve()
        self.mode = mode
        self.configuration = configuration
        self.query_source = query_source
        self.deployment = deployment
        self.clock_ns = clock_ns
        self.implementation_sha256 = _sha256_file(Path(__file__))
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_physics = mode == "CONTRACT_TEST"
        if mode == "CONTRACT_TEST":
            if deployment is not None or query_source.real_isaac or not query_source.mocked_physics:
                raise ExactPlanUnavailable("contract synthesis received production dependencies")
        else:
            self._validate_real_deployment()

    def _repo_file(self, raw: str) -> Path:
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise ExactPlanUnavailable("exact-plan deployment path escapes the repository")
        unresolved = self.project_root / relative
        cursor = self.project_root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ExactPlanUnavailable("exact-plan deployment path contains a symlink")
        path = unresolved.resolve()
        if not path.is_relative_to(self.project_root):
            raise ExactPlanUnavailable("exact-plan deployment path resolves outside repository")
        return path

    def _validate_real_deployment(self) -> None:
        deployment = self.deployment
        if (
            deployment is None
            or not self.query_source.real_isaac
            or self.query_source.mocked_physics
            or deployment.backend_implementation_sha256 != self.implementation_sha256
            or deployment.query_source_implementation_sha256
            != self.query_source.implementation_sha256
            or deployment.immutable_commit != self.configuration.immutable_commit
            or deployment.container_image_digest != self.configuration.container_image_digest
        ):
            raise ExactPlanUnavailable("REAL_ISAAC exact-plan synthesis deployment differs")
        files = {
            deployment.accepted_adr_0022_path: deployment.accepted_adr_0022_sha256,
            deployment.accepted_adr_0024_path: deployment.accepted_adr_0024_sha256,
            deployment.binding_addendum_path: deployment.binding_addendum_sha256,
            deployment.unlock_config_path: deployment.unlock_config_sha256,
            deployment.synthesis_configuration_path: (
                deployment.synthesis_configuration_file_sha256
            ),
            deployment.backend_implementation_path: deployment.backend_implementation_sha256,
            deployment.query_source_implementation_path: (
                deployment.query_source_implementation_sha256
            ),
        }
        for raw, expected in files.items():
            if _sha256_file(self._repo_file(raw)) != expected:
                raise ExactPlanUnavailable(f"exact-plan synthesis deployment file differs: {raw}")
        try:
            frozen_configuration = FormalExactPlanSynthesisConfigurationV1.model_validate(
                json.loads(
                    read_regular_file_once(self._repo_file(deployment.synthesis_configuration_path))
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ExactPlanUnavailable(
                "exact-plan synthesis deployment configuration is not canonical"
            ) from exc
        if frozen_configuration != self.configuration:
            raise ExactPlanUnavailable(
                "exact-plan synthesis in-memory configuration differs from deployment bytes"
            )
        for binding in self.configuration.source_bindings:
            if _sha256_file(self._repo_file(binding.path)) != binding.sha256:
                raise ExactPlanUnavailable(
                    f"exact-plan synthesis source binding differs: {binding.role}"
                )

    @staticmethod
    def _target_position(
        observation: FormalPublicObservationV4,
        target_track_id: str,
    ) -> tuple[float, float, float]:
        matches = [
            track
            for track in observation.observation.perception_tracks
            if track.track_id == target_track_id
        ]
        if len(matches) != 1 or matches[0].pose_xyzquat is None:
            raise ExactPlanUnavailable("selected public target has no unique metric pose")
        pose = tuple(float(value) for value in matches[0].pose_xyzquat[:3])
        _finite_tuple(pose, name="selected public target pose")
        return pose  # type: ignore[return-value]

    @staticmethod
    def _target_category(
        observation: FormalPublicObservationV4,
        target_track_id: str,
    ) -> str:
        matches = [
            track.category
            for track in observation.observation.perception_tracks
            if track.track_id == target_track_id
        ]
        if len(matches) != 1 or matches[0] is None:
            raise ExactPlanUnavailable("selected public target has no unique category")
        return matches[0]

    @staticmethod
    def _mapping_is_exact(mapping: RuntimeSkillMappingResultV2) -> tuple[str, str]:
        skill = mapping.canonical_skill
        action = mapping.runtime_action
        if (
            mapping.status != "VALID"
            or skill not in _SKILL_TO_ACTION
            or action != _SKILL_TO_ACTION.get(str(skill))
            or mapping.fallback_required
            or mapping.execution_attribution != "MODEL_SELECTED_REGISTERED_SKILL"
        ):
            raise ExactPlanUnavailable("runtime mapping is not an exact formal skill")
        return str(skill), str(action)

    def _phase(
        self,
        *,
        index: int,
        name: str,
        command: Literal[
            "CARTESIAN_POSE",
            "GRIPPER_POSITION",
            "ATTACH_CONTACT_ENTITY",
            "REMOVE_ATTACHMENT",
            "PUBLIC_RGBD_CAPTURE",
            "PUBLIC_TRACK_REASSOCIATION",
        ],
        state: FormalPlanSynthesisStateV1,
        position: tuple[float, float, float] | None = None,
        orientation: tuple[float, float, float, float] | None = None,
        gripper: float | None = None,
        steps: int = 0,
        allow_robot_contact: bool = False,
        allow_external_contact: bool = False,
        target_track_id: str | None = None,
        capture_label: str | None = None,
    ) -> ExactExecutionPhaseV2:
        external = state.dynamic_contact_allowlist_paths if allow_external_contact else ()
        return ExactExecutionPhaseV2(
            phase_index=index,
            phase_name=name,
            command=command,
            goal_position_world_m=position,
            orientation_world_wxyz=orientation,
            gripper_position_m=gripper,
            steps=steps,
            collision_phase=name,
            allowed_robot_contact_paths=(
                self.configuration.permitted_robot_contact_paths if allow_robot_contact else ()
            ),
            allowed_external_contact_paths=external,
            public_target_track_id=target_track_id,
            public_capture_label=capture_label,
            contact_entity_selection=(
                "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"
                if command == "ATTACH_CONTACT_ENTITY"
                else "NONE"
            ),
            gates=_phase_gates(
                logical=command in {"PUBLIC_RGBD_CAPTURE", "PUBLIC_TRACK_REASSOCIATION"}
            ),
        )

    def _grasp_phases(
        self,
        *,
        skill: str,
        target_track_id: str,
        target: tuple[float, float, float],
        orientation: tuple[float, float, float, float],
        state: FormalPlanSynthesisStateV1,
    ) -> tuple[tuple[ExactExecutionPhaseV2, ...], ExactGraspGeometryV1]:
        prefix = skill
        cfg = self.configuration
        pregrasp = (target[0], target[1], target[2] + cfg.pregrasp_height_m)
        contact = (target[0], target[1], target[2] + cfg.contact_centerline_m)
        lift = (target[0], target[1], target[2] + cfg.grasp_lift_height_m)
        phases = (
            self._phase(
                index=0,
                name=f"{prefix}_APPROACH",
                command="CARTESIAN_POSE",
                state=state,
                position=pregrasp,
                orientation=orientation,
                steps=cfg.approach_steps,
            ),
            self._phase(
                index=1,
                name=f"{prefix}_CONTACT_DESCENT",
                command="CARTESIAN_POSE",
                state=state,
                position=contact,
                orientation=orientation,
                steps=cfg.contact_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=2,
                name=f"{prefix}_PRECLOSE",
                command="GRIPPER_POSITION",
                state=state,
                gripper=cfg.preclose_finger_position_m,
                steps=cfg.preclose_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=3,
                name=f"{prefix}_PRECLOSE_SETTLE",
                command="GRIPPER_POSITION",
                state=state,
                gripper=cfg.preclose_finger_position_m,
                steps=cfg.preclose_settle_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=4,
                name=f"{prefix}_TERMINAL_CLOSE",
                command="GRIPPER_POSITION",
                state=state,
                gripper=cfg.close_finger_position_m,
                steps=cfg.close_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=5,
                name=f"{prefix}_CONTACT_OBSERVE",
                command="GRIPPER_POSITION",
                state=state,
                gripper=cfg.close_finger_position_m,
                steps=cfg.contact_observation_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=6,
                name=f"{prefix}_ATTACH",
                command="ATTACH_CONTACT_ENTITY",
                state=state,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=7,
                name=f"{prefix}_LIFT",
                command="CARTESIAN_POSE",
                state=state,
                position=lift,
                orientation=orientation,
                steps=cfg.lift_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
            self._phase(
                index=8,
                name=f"{prefix}_RETREAT",
                command="CARTESIAN_POSE",
                state=state,
                position=pregrasp,
                orientation=orientation,
                steps=cfg.retreat_steps,
                allow_robot_contact=True,
                allow_external_contact=True,
            ),
        )
        return phases, ExactGraspGeometryV1(
            selected_yaw_rad=2.0 * math.atan2(orientation[2], orientation[1]),
            contact_centerline_m=cfg.contact_centerline_m,
            finger_target_m=cfg.close_finger_position_m,
            approach_phase_index=0,
            contact_phase_indices=(1,),
            close_phase_index=4,
            attach_phase_index=6,
            lift_phase_index=7,
            retreat_phase_index=8,
            contact_allowlist_sha256=canonical_sha256(state.dynamic_contact_allowlist_paths),
        )

    def _build_phases(
        self,
        *,
        skill: str,
        mapping: RuntimeSkillMappingResultV2,
        observation: FormalPublicObservationV4,
        state: FormalPlanSynthesisStateV1,
    ) -> tuple[tuple[ExactExecutionPhaseV2, ...], ExactGraspGeometryV1 | None]:
        cfg = self.configuration
        target_id = mapping.target_track_id
        if skill in _PHYSICAL_SKILLS and target_id is None:
            raise ExactPlanUnavailable("physical exact plan has no public target pointer")
        if skill in _ATTACHED_SKILLS:
            if state.attached_public_track_id != target_id:
                raise ExactPlanUnavailable("transport/release target is not the bound attachment")
        elif skill in {"GRASP", "REGRASP"} and state.attached_public_track_id is not None:
            raise ExactPlanUnavailable("grasp exact plan begins with an existing attachment")
        if skill in _PHYSICAL_SKILLS and len(state.dynamic_contact_allowlist_paths) != 1:
            raise ExactPlanUnavailable(
                "physical exact plan lacks one uniquely bound external contact path"
            )

        if skill in {"GRASP", "REGRASP"}:
            assert target_id is not None
            if mapping.execution_parameters.get("grasp_family") != "top_down":
                raise ExactPlanUnavailable(
                    "exact-plan synthesis has no frozen non-top-down grasp geometry"
                )
            category = self._target_category(observation, target_id)
            if not category.startswith(cfg.expected_grasp_category_prefix):
                raise ExactPlanUnavailable("grasp target category lacks a frozen geometry family")
            target = self._target_position(observation, target_id)
            neighbors = [
                track.pose_xyzquat[:2]
                for track in observation.observation.perception_tracks
                if track.track_id != target_id and track.pose_xyzquat is not None
            ]
            yaw = select_free_gap_yaw_from_xy(
                target[:2],
                neighbors,
                source="FORMAL_V4_REPLAYED_PUBLIC_TRACKS",
                open_finger_m=cfg.open_finger_position_m,
            )
            if yaw["clearance_ok"] is not True:
                raise ExactPlanUnavailable("public free-gap yaw has no clearance-safe candidate")
            selected = float(yaw["selected_yaw_rad"])
            orientation = isaac_top_down_orientation_wxyz(selected)
            return self._grasp_phases(
                skill=skill,
                target_track_id=target_id,
                target=target,
                orientation=orientation,
                state=state,
            )

        if skill == "LIFT":
            height = float(
                mapping.execution_parameters.get("lift_height_m", cfg.default_lift_height_m)
            )
            if not math.isfinite(height) or not 0.02 <= height <= 0.20:
                raise ExactPlanUnavailable("LIFT height differs from the registered range")
            position = (
                state.end_effector_position_world_m[0],
                state.end_effector_position_world_m[1],
                state.end_effector_position_world_m[2] + height,
            )
            return (
                (
                    self._phase(
                        index=0,
                        name="LIFT_TRANSPORT",
                        command="CARTESIAN_POSE",
                        state=state,
                        position=position,
                        orientation=state.end_effector_orientation_world_wxyz,
                        steps=cfg.transport_steps,
                        allow_robot_contact=True,
                        allow_external_contact=True,
                    ),
                ),
                None,
            )

        if skill in {"MOVE", "PLACE"}:
            raw_destination = mapping.execution_parameters.get("destination_world_xyz_m")
            if (
                not isinstance(raw_destination, list)
                or len(raw_destination) != 3
                or not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    for value in raw_destination
                )
            ):
                raise ExactPlanUnavailable(f"{skill} lacks a registry-derived world destination")
            destination = tuple(float(value) for value in raw_destination)
            _finite_tuple(destination, name=f"{skill} destination")
            approach = (
                destination[0],
                destination[1],
                destination[2] + cfg.place_approach_height_m,
            )
            if skill == "MOVE":
                return (
                    (
                        self._phase(
                            index=0,
                            name="MOVE_PREPLACE",
                            command="CARTESIAN_POSE",
                            state=state,
                            position=approach,
                            orientation=state.end_effector_orientation_world_wxyz,
                            steps=cfg.transport_steps,
                            allow_robot_contact=True,
                            allow_external_contact=True,
                        ),
                    ),
                    None,
                )
            retreat = (destination[0], destination[1], destination[2] + cfg.retreat_height_m)
            return (
                (
                    self._phase(
                        index=0,
                        name="PLACE_APPROACH",
                        command="CARTESIAN_POSE",
                        state=state,
                        position=approach,
                        orientation=state.end_effector_orientation_world_wxyz,
                        steps=cfg.place_steps,
                        allow_robot_contact=True,
                        allow_external_contact=True,
                    ),
                    self._phase(
                        index=1,
                        name="PLACE_LOWER",
                        command="CARTESIAN_POSE",
                        state=state,
                        position=destination,
                        orientation=state.end_effector_orientation_world_wxyz,
                        steps=cfg.place_steps,
                        allow_robot_contact=True,
                        allow_external_contact=True,
                    ),
                    self._phase(
                        index=2,
                        name="PLACE_REMOVE_ATTACHMENT",
                        command="REMOVE_ATTACHMENT",
                        state=state,
                    ),
                    self._phase(
                        index=3,
                        name="PLACE_OPEN",
                        command="GRIPPER_POSITION",
                        state=state,
                        gripper=cfg.open_finger_position_m,
                        steps=cfg.release_steps,
                    ),
                    self._phase(
                        index=4,
                        name="PLACE_RETREAT",
                        command="CARTESIAN_POSE",
                        state=state,
                        position=retreat,
                        orientation=state.end_effector_orientation_world_wxyz,
                        steps=cfg.retreat_steps,
                    ),
                ),
                None,
            )

        if skill == "RELEASE":
            open_width = float(
                mapping.execution_parameters.get(
                    "open_width_m",
                    cfg.open_finger_position_m,
                )
            )
            if not math.isfinite(open_width) or not 0.0 <= open_width <= 0.08:
                raise ExactPlanUnavailable("RELEASE width differs from the registered range")
            retreat = (
                state.end_effector_position_world_m[0],
                state.end_effector_position_world_m[1],
                state.end_effector_position_world_m[2] + cfg.retreat_height_m,
            )
            return (
                (
                    self._phase(
                        index=0,
                        name="RELEASE_REMOVE_ATTACHMENT",
                        command="REMOVE_ATTACHMENT",
                        state=state,
                    ),
                    self._phase(
                        index=1,
                        name="RELEASE_OPEN",
                        command="GRIPPER_POSITION",
                        state=state,
                        gripper=open_width,
                        steps=cfg.release_steps,
                    ),
                    self._phase(
                        index=2,
                        name="RELEASE_RETREAT",
                        command="CARTESIAN_POSE",
                        state=state,
                        position=retreat,
                        orientation=state.end_effector_orientation_world_wxyz,
                        steps=cfg.retreat_steps,
                    ),
                ),
                None,
            )

        if skill == "REOBSERVE":
            return (
                (
                    self._phase(
                        index=0,
                        name="REOBSERVE_CAPTURE",
                        command="PUBLIC_RGBD_CAPTURE",
                        state=state,
                        capture_label=f"formal_reobserve_{mapping.target_track_slot or 0}",
                    ),
                ),
                None,
            )
        if skill == "REASSOCIATE_TARGET":
            if target_id is None:
                raise ExactPlanUnavailable("REASSOCIATE_TARGET lacks a public pointer")
            return (
                (
                    self._phase(
                        index=0,
                        name="REASSOCIATE_TARGET_PUBLIC",
                        command="PUBLIC_TRACK_REASSOCIATION",
                        state=state,
                        target_track_id=target_id,
                    ),
                ),
                None,
            )
        raise ExactPlanUnavailable(f"unsupported formal exact-plan skill: {skill}")

    def _phase_contracts(
        self,
        phases: tuple[ExactExecutionPhaseV2, ...],
        *,
        state: FormalPlanSynthesisStateV1,
    ) -> tuple[ExactPlanPhaseContractV1, ...]:
        cfg = self.configuration
        robot_hash = canonical_sha256(cfg.controlled_robot_links)
        environment_hash = canonical_sha256(state.environment_collision_paths)
        result = []
        for phase in phases:
            dimensions = {
                "CARTESIAN_POSE": 7,
                "GRIPPER_POSITION": 1,
                "ATTACH_CONTACT_ENTITY": 0,
                "REMOVE_ATTACHMENT": 0,
                "PUBLIC_RGBD_CAPTURE": 0,
                "PUBLIC_TRACK_REASSOCIATION": 0,
            }[phase.command]
            result.append(
                ExactPlanPhaseContractV1(
                    phase=phase,
                    phase_sha256=canonical_sha256(phase),
                    command_rate_hz=cfg.controller_frequency_hz,
                    command_dimensions=dimensions,
                    interpolation_rule=(
                        "LINEAR_FIXED_STEPS"
                        if phase.command
                        in {
                            "CARTESIAN_POSE",
                            "GRIPPER_POSITION",
                            "ATTACH_CONTACT_ENTITY",
                            "REMOVE_ATTACHMENT",
                        }
                        else "NONE"
                    ),
                    convergence_tolerance_m=cfg.convergence_tolerance_m,
                    timeout_ns=cfg.phase_timeout_ns,
                    allowed_robot_links_sha256=robot_hash,
                    allowed_environment_paths_sha256=environment_hash,
                    allowed_external_contact_paths_sha256=canonical_sha256(
                        phase.allowed_external_contact_paths
                    ),
                    attachment_or_removal_selector=(
                        "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"
                        if phase.command == "ATTACH_CONTACT_ENTITY"
                        else "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT"
                        if phase.command == "REMOVE_ATTACHMENT"
                        else "NONE"
                    ),
                    freshness_transition=(
                        "CAPTURE_RECEIPT_ADVANCES"
                        if phase.command == "PUBLIC_RGBD_CAPTURE"
                        else "PUBLIC_ASSOCIATION_RECEIPT_ADVANCES"
                        if phase.command == "PUBLIC_TRACK_REASSOCIATION"
                        else "NONE"
                    ),
                )
            )
        return tuple(result)

    def synthesize_bound_plan(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
        mapping: RuntimeSkillMappingResultV2,
    ) -> BoundExactPlanSynthesisResultV1:
        skill, action = self._mapping_is_exact(mapping)
        snapshot = self.query_source.query_plan_synthesis_state(
            request=request,
            observation=observation,
        )
        snapshot = FormalPlanSynthesisSnapshotV1.model_validate(
            snapshot.model_dump(mode="json") if isinstance(snapshot, BaseModel) else snapshot
        )
        if (
            snapshot.receipt.query_source_implementation_sha256
            != self.query_source.implementation_sha256
        ):
            raise ExactPlanUnavailable("query-only state receipt names another implementation")
        state = snapshot.state
        expected_state = {
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
        }
        if any(getattr(state, name) != value for name, value in expected_state.items()):
            raise ExactPlanUnavailable("query-only synthesis state crosses request/observation")
        cfg = self.configuration
        if (
            state.state_timestamp_ns <= observation.captured_at_ns
            or state.state_timestamp_ns - observation.captured_at_ns
            > cfg.preplan_freshness_limit_ns
            or snapshot.receipt.freshness_limit_ns != cfg.preplan_freshness_limit_ns
        ):
            raise ExactPlanUnavailable("query-only synthesis state is stale")
        constructed_at_ns = int(self.clock_ns())
        if constructed_at_ns <= state.state_timestamp_ns:
            raise ExactPlanUnavailable("exact plan clock does not follow the query-only state")

        phases, grasp_geometry = self._build_phases(
            skill=skill,
            mapping=mapping,
            observation=observation,
            state=state,
        )
        wire_plan = ExactExecutionPlanV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=observation.observation_id,
            capture_receipt_sha256=observation.capture_receipt_sha256,
            canonical_skill=skill,
            runtime_action=action,
            execution_parameters_sha256=canonical_sha256(mapping.execution_parameters),
            target_track_id=mapping.target_track_id,
            phases=phases,
        )
        contracts = self._phase_contracts(phases, state=state)
        projection = tuple(
            {
                "phase_index": item.phase.phase_index,
                "phase_name": item.phase.phase_name,
                "command": item.phase.command,
                "phase_sha256": item.phase_sha256,
                "command_rate_hz": item.command_rate_hz,
                "command_dimensions": item.command_dimensions,
                "interpolation_rule": item.interpolation_rule,
                "timeout_ns": item.timeout_ns,
                "permitted_retry_count": item.permitted_retry_count,
                "attachment_or_removal_selector": item.attachment_or_removal_selector,
                "freshness_transition": item.freshness_transition,
            }
            for item in contracts
        )
        inputs = ExactPlanA1InputsV1(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=observation.observation_id,
            capture_receipt_sha256=observation.capture_receipt_sha256,
            rgb_sha256=observation.rgb.sha256,
            depth_sha256=observation.depth.sha256,
            canonical_public_tracks_sha256=observation.canonical_public_tracks_sha256,
            signed_model_inference_response_sha256=request.inference_response_sha256,
            runtime_mapping_sha256=canonical_runtime_mapping_sha256_v1(mapping),
            canonical_skill=skill,
            runtime_action=action,
            target_track_id=mapping.target_track_id,
            destination_cell=(
                str(mapping.execution_parameters["destination"])
                if "destination" in mapping.execution_parameters
                else None
            ),
            resolved_execution_parameters_sha256=canonical_sha256(mapping.execution_parameters),
            preplan_state_sha256=state.state_sha256,
            preplan_state_dimensions=8,
            preplan_state_units="world_m,normalized_wxyz,gripper_m",
            preplan_state_timestamp_ns=state.state_timestamp_ns,
            preplan_state_freshness_limit_ns=cfg.preplan_freshness_limit_ns,
            plan_constructed_at_ns=constructed_at_ns,
            controller_frequency_hz=cfg.controller_frequency_hz,
            command_dimensions=7,
            convergence_tolerance_m=cfg.convergence_tolerance_m,
            immutable_commit=cfg.immutable_commit,
            container_image_digest=cfg.container_image_digest,
        )
        payload = {
            "schema_version": "M2CExactPlanPrimitivePlanV1",
            "bundle_name": "M2CExactPlanPrimitiveBundleV1",
            "exact_execution_plan": wire_plan.model_dump(mode="json"),
            "exact_execution_plan_sha256": canonical_sha256(wire_plan),
            "inputs": inputs.model_dump(mode="json"),
            "source_bindings": [item.model_dump(mode="json") for item in cfg.source_bindings],
            "phases": [item.model_dump(mode="json") for item in contracts],
            "grasp_geometry": (
                grasp_geometry.model_dump(mode="json") if grasp_geometry is not None else None
            ),
            "phase_schema_sha256": canonical_sha256(projection),
            "constructed_before_physical_execution": True,
            "executor_parameter_adaptation_allowed": False,
            "hidden_replan_allowed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        payload["bound_plan_sha256"] = canonical_sha256(payload)
        plan = M2CExactPlanPrimitivePlanV1.model_validate(payload)
        result_payload = {
            "schema_version": "BoundExactPlanSynthesisResultV1",
            "request_sha256": canonical_sha256(request),
            "formal_observation_sha256": observation.wire_sha256,
            "runtime_mapping_sha256": canonical_runtime_mapping_sha256_v1(mapping),
            "synthesis_backend_implementation_sha256": self.implementation_sha256,
            "preplan_state_receipt": snapshot.receipt.model_dump(mode="json"),
            "bound_plan": plan.model_dump(mode="json"),
            "plan_constructed_before_any_command": True,
            "physical_execution_claimed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        result_payload["result_sha256"] = canonical_sha256(result_payload)
        return BoundExactPlanSynthesisResultV1.model_validate(result_payload)
