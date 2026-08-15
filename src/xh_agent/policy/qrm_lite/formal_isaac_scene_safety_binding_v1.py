"""Query-only public-track to active-scene collision-path binding.

The world model selects a public track before this module runs.  This module
never changes that selection and never exposes simulator paths to the model.
It binds the selected public world position to one live dynamic collision
path for A.3 only, using a two-sided uniqueness check over the same immutable
scene and mutation counter as the rest of the preflight query.

No name, TaskSpec identity, supervision target, Teacher value, outcome, or
simulator entity label participates in matching.  Distances use ADR-0024's
already approved 1e-6 m quantization and 0.02 m public ambiguity envelope.
Anything outside that envelope, or any competing path/public track within the
strict ambiguity margin, rejects before a plan can be constructed.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable, Literal, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PUBLIC_TRACK_AMBIGUITY_MARGIN_M,
    PUBLIC_TRACK_COST_QUANTUM_M,
    PublicAssociationDeploymentBindingV2,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3RigidTransformV1
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    A3ScenePoseProviderV1,
)
from xh_agent.policy.qrm_lite.formal_isaac_plan_synthesis_query_v1 import (
    FormalPlanSynthesisSceneSafetyBindingV1,
)
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import IsaacExecuteRequestV4
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCounterSourceV1,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import read_regular_file_once


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_scene_safety_binding_v1.py"
PUBLIC_SCENE_BINDING_DISTANCE_QUANTUM_M = PUBLIC_TRACK_COST_QUANTUM_M
PUBLIC_SCENE_BINDING_RESIDUAL_GATE_M = PUBLIC_TRACK_AMBIGUITY_MARGIN_M
PUBLIC_SCENE_BINDING_AMBIGUITY_MARGIN_M = PUBLIC_TRACK_AMBIGUITY_MARGIN_M
_QUANTA_PER_METRE = int(round(1.0 / PUBLIC_SCENE_BINDING_DISTANCE_QUANTUM_M))
_RESIDUAL_GATE_QUANTA = int(round(PUBLIC_SCENE_BINDING_RESIDUAL_GATE_M * _QUANTA_PER_METRE))
_AMBIGUITY_MARGIN_QUANTA = int(round(PUBLIC_SCENE_BINDING_AMBIGUITY_MARGIN_M * _QUANTA_PER_METRE))


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalIsaacSceneSafetyBindingUnavailable(RuntimeError):
    """The public target cannot be safely bound to the active scene."""


class PersistentSceneSafetyJournalV1(Protocol):
    def append(self, event_type: str, payload: Mapping[str, Any]) -> None: ...


class FormalScenePathDistanceV1(_FrozenModel):
    external_contact_path: str = Field(pattern=r"^/World/M1B/[^\s]+$")
    scene_position_world_m: tuple[float, float, float]
    residual_quanta: int = Field(ge=0)

    @model_validator(mode="after")
    def finite_position(self) -> "FormalScenePathDistanceV1":
        if not all(math.isfinite(value) for value in self.scene_position_world_m):
            raise ValueError("scene-path position is non-finite")
        return self


class FormalPublicTrackDistanceV1(_FrozenModel):
    public_track_id: str = Field(pattern=r"^track-[0-9a-f]{8}$")
    public_position_world_m: tuple[float, float, float]
    residual_to_selected_path_quanta: int = Field(ge=0)

    @model_validator(mode="after")
    def finite_position(self) -> "FormalPublicTrackDistanceV1":
        if not all(math.isfinite(value) for value in self.public_position_world_m):
            raise ValueError("public-track position is non-finite")
        return self


class FormalPublicTrackScenePathBindingReceiptV1(_FrozenModel):
    """Replayable two-sided uniqueness proof for one selected public track."""

    schema_version: Literal["FormalPublicTrackScenePathBindingReceiptV1"] = (
        "FormalPublicTrackScenePathBindingReceiptV1"
    )
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_observation_sha256: str = Field(pattern=SHA256_PATTERN)
    association_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_geometry_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    selected_public_track_id: str = Field(pattern=r"^track-[0-9a-f]{8}$")
    selected_public_position_world_m: tuple[float, float, float]
    selected_external_contact_path: str = Field(pattern=r"^/World/M1B/[^\s]+$")
    selected_residual_quanta: int = Field(ge=0)
    scene_path_distances: tuple[FormalScenePathDistanceV1, ...] = Field(min_length=1)
    public_track_distances_to_selected_path: tuple[FormalPublicTrackDistanceV1, ...] = Field(
        min_length=1
    )
    distance_quantum_m: Literal[0.000001] = PUBLIC_SCENE_BINDING_DISTANCE_QUANTUM_M
    residual_gate_m: Literal[0.02] = PUBLIC_SCENE_BINDING_RESIDUAL_GATE_M
    ambiguity_margin_m: Literal[0.02] = PUBLIC_SCENE_BINDING_AMBIGUITY_MARGIN_M
    assignment_policy: Literal[
        "SELECTED_TRACK_MINIMUM_QUANTIZED_RESIDUAL_WITH_TWO_SIDED_UNIQUENESS_V1"
    ] = "SELECTED_TRACK_MINIMUM_QUANTIZED_RESIDUAL_WITH_TWO_SIDED_UNIQUENESS_V1"
    observed_at_ns: int = Field(gt=0)
    query_only: Literal[True] = True
    simulator_paths_exposed_to_model: Literal[False] = False
    simulator_paths_used_only_for_a3_gates: Literal[True] = True
    teacher_used: Literal[False] = False
    task_spec_identity_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def unique_and_canonical(self) -> "FormalPublicTrackScenePathBindingReceiptV1":
        paths = tuple(item.external_contact_path for item in self.scene_path_distances)
        tracks = tuple(
            item.public_track_id for item in self.public_track_distances_to_selected_path
        )
        if paths != tuple(sorted(set(paths))) or tracks != tuple(sorted(set(tracks))):
            raise ValueError("public-scene distance inventories are not canonical")
        by_path = {
            item.external_contact_path: item.residual_quanta for item in self.scene_path_distances
        }
        by_track = {
            item.public_track_id: item.residual_to_selected_path_quanta
            for item in self.public_track_distances_to_selected_path
        }
        ranked_paths = sorted((distance, path) for path, distance in by_path.items())
        if (
            self.selected_external_contact_path not in by_path
            or self.selected_public_track_id not in by_track
            or ranked_paths[0]
            != (self.selected_residual_quanta, self.selected_external_contact_path)
            or by_track[self.selected_public_track_id] != self.selected_residual_quanta
            or self.selected_residual_quanta > _RESIDUAL_GATE_QUANTA
        ):
            raise ValueError("selected public-scene residual is not the unique gated minimum")
        if len(ranked_paths) > 1 and (
            ranked_paths[1][0] - self.selected_residual_quanta < _AMBIGUITY_MARGIN_QUANTA
        ):
            raise ValueError("selected public track has an ambiguous scene path")
        competing_tracks = sorted(
            distance
            for track, distance in by_track.items()
            if track != self.selected_public_track_id
        )
        if competing_tracks and (
            competing_tracks[0] - self.selected_residual_quanta < _AMBIGUITY_MARGIN_QUANTA
        ):
            raise ValueError("selected scene path has an ambiguous public identity")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("public-scene binding receipt digest differs")
        return self


class FormalIsaacActiveAttachmentBindingV1(_FrozenModel):
    schema_version: Literal["FormalIsaacActiveAttachmentBindingV1"] = (
        "FormalIsaacActiveAttachmentBindingV1"
    )
    public_track_id: str = Field(pattern=r"^track-[0-9a-f]{8}$")
    external_contact_path: str = Field(pattern=r"^/World/M1B/[^\s]+$")
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    attached_at_ns: int = Field(gt=0)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "FormalIsaacActiveAttachmentBindingV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("active attachment binding digest differs")
        return self


class FormalIsaacAttachmentRemovalReceiptV1(_FrozenModel):
    schema_version: Literal["FormalIsaacAttachmentRemovalReceiptV1"] = (
        "FormalIsaacAttachmentRemovalReceiptV1"
    )
    removed_attachment_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    removed_at_ns: int = Field(gt=0)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def digest_is_exact(self) -> "FormalIsaacAttachmentRemovalReceiptV1":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("attachment removal receipt digest differs")
        return self


class FormalIsaacActiveAttachmentSourceV1(Protocol):
    real_isaac: bool
    mocked_physics: bool

    def snapshot_active_attachment(self) -> FormalIsaacActiveAttachmentBindingV1 | None: ...


class FormalIsaacActiveAttachmentRegistryV1:
    """Single-session attachment state committed only after frozen helpers return."""

    def __init__(
        self,
        *,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        journal: PersistentSceneSafetyJournalV1,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_physics = mode == "CONTRACT_TEST"
        self.journal = journal
        self.now_ns = now_ns
        self._active: FormalIsaacActiveAttachmentBindingV1 | None = None
        self._lock = threading.Lock()

    def snapshot_active_attachment(self) -> FormalIsaacActiveAttachmentBindingV1 | None:
        with self._lock:
            return self._active

    def commit_attachment(
        self,
        *,
        public_track_id: str,
        external_contact_path: str,
        bound_plan_sha256: str,
        phase_sha256: str,
    ) -> FormalIsaacActiveAttachmentBindingV1:
        with self._lock:
            if self._active is not None:
                raise FormalIsaacSceneSafetyBindingUnavailable(
                    "active-session attachment already exists"
                )
            payload = {
                "schema_version": "FormalIsaacActiveAttachmentBindingV1",
                "public_track_id": public_track_id,
                "external_contact_path": external_contact_path,
                "bound_plan_sha256": bound_plan_sha256,
                "phase_sha256": phase_sha256,
                "attached_at_ns": int(self.now_ns()),
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            receipt = FormalIsaacActiveAttachmentBindingV1(
                **payload,
                receipt_sha256=canonical_sha256(payload),
            )
            self.journal.append(
                "FORMAL_ACTIVE_ATTACHMENT_COMMITTED",
                {"attachment": receipt.model_dump(mode="json")},
            )
            self._active = receipt
            return receipt

    def commit_removal(
        self,
        *,
        bound_plan_sha256: str,
        phase_sha256: str,
    ) -> FormalIsaacAttachmentRemovalReceiptV1:
        with self._lock:
            active = self._active
            if active is None:
                raise FormalIsaacSceneSafetyBindingUnavailable(
                    "active-session attachment is absent"
                )
            payload = {
                "schema_version": "FormalIsaacAttachmentRemovalReceiptV1",
                "removed_attachment_receipt_sha256": active.receipt_sha256,
                "bound_plan_sha256": bound_plan_sha256,
                "phase_sha256": phase_sha256,
                "removed_at_ns": int(self.now_ns()),
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            }
            receipt = FormalIsaacAttachmentRemovalReceiptV1(
                **payload,
                receipt_sha256=canonical_sha256(payload),
            )
            self.journal.append(
                "FORMAL_ACTIVE_ATTACHMENT_REMOVED",
                {"removal": receipt.model_dump(mode="json")},
            )
            self._active = None
            return receipt


def _position(track: Any) -> tuple[float, float, float]:
    pose = track.pose_xyzquat
    if pose is None or len(pose) != 7:
        raise FormalIsaacSceneSafetyBindingUnavailable("selected public track lacks a world pose")
    values = tuple(float(value) for value in pose[:3])
    if not all(math.isfinite(value) for value in values):
        raise FormalIsaacSceneSafetyBindingUnavailable("selected public track pose is non-finite")
    return values


def _quanta(left: tuple[float, float, float], right: tuple[float, float, float]) -> int:
    return int(round(math.dist(left, right) * _QUANTA_PER_METRE))


class FormalIsaacPublicTrackSceneSafetySourceV1:
    """Bind one model-selected public track to one A.3-only scene path."""

    def __init__(
        self,
        *,
        project_root: Path,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        association_deployment: PublicAssociationDeploymentBindingV2,
        scene_geometry: A3SceneCollisionGeometryReceiptV1,
        scene_pose_source: A3ScenePoseProviderV1,
        mutation_counter_source: ActiveSessionMutationCounterSourceV1,
        active_attachment_source: FormalIsaacActiveAttachmentSourceV1,
        journal: PersistentSceneSafetyJournalV1,
    ) -> None:
        implementation = project_root.resolve() / IMPLEMENTATION_REPO_PATH
        self.implementation_sha256 = hashlib.sha256(
            read_regular_file_once(implementation)
        ).hexdigest()
        self.real_isaac = mode == "REAL_ISAAC"
        self.mocked_physics = mode == "CONTRACT_TEST"
        self.association_deployment = PublicAssociationDeploymentBindingV2.model_validate(
            association_deployment.model_dump(mode="json")
        )
        self.scene_geometry = A3SceneCollisionGeometryReceiptV1.model_validate(
            scene_geometry.model_dump(mode="json")
        )
        self.scene_pose_source = scene_pose_source
        self.mutation_counter_source = mutation_counter_source
        self.active_attachment_source = active_attachment_source
        self.journal = journal
        if scene_pose_source.mutation_counter_source is not mutation_counter_source:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "scene pose and safety binding do not share one mutation counter"
            )
        if mode == "REAL_ISAAC":
            if (
                not scene_pose_source.real_runtime_provider
                or scene_pose_source.contract_test_only
                or not active_attachment_source.real_isaac
                or active_attachment_source.mocked_physics
            ):
                raise FormalIsaacSceneSafetyBindingUnavailable(
                    "real scene-safety source dependencies differ"
                )
        elif (
            scene_pose_source.real_runtime_provider
            or not scene_pose_source.contract_test_only
            or active_attachment_source.real_isaac
            or not active_attachment_source.mocked_physics
        ):
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "contract scene-safety source dependencies claim real Isaac"
            )

    def _bind_target(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
        scene_poses: Mapping[str, A3RigidTransformV1],
        observed_at_ns: int,
    ) -> FormalPublicTrackScenePathBindingReceiptV1 | None:
        selected = request.runtime_request.model_target_track_id
        if selected is None:
            return None
        tracks = observation.observation.perception_tracks
        selected_tracks = [track for track in tracks if track.track_id == selected]
        if len(selected_tracks) != 1:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "model-selected public track is absent or duplicated"
            )
        selected_position = _position(selected_tracks[0])
        dynamic_paths = self.scene_geometry.dynamic_collision_link_paths
        path_distances = tuple(
            FormalScenePathDistanceV1(
                external_contact_path=path,
                scene_position_world_m=scene_poses[path].translation_world_m,
                residual_quanta=_quanta(
                    selected_position,
                    scene_poses[path].translation_world_m,
                ),
            )
            for path in dynamic_paths
        )
        ranked = sorted(
            (item.residual_quanta, item.external_contact_path) for item in path_distances
        )
        if not ranked or ranked[0][0] > _RESIDUAL_GATE_QUANTA:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "selected public track is outside the scene binding residual gate"
            )
        selected_residual, selected_path = ranked[0]
        if len(ranked) > 1 and ranked[1][0] - selected_residual < _AMBIGUITY_MARGIN_QUANTA:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "selected public track has two plausible scene paths"
            )
        selected_scene_position = scene_poses[selected_path].translation_world_m
        track_distances = tuple(
            FormalPublicTrackDistanceV1(
                public_track_id=track.track_id,
                public_position_world_m=_position(track),
                residual_to_selected_path_quanta=_quanta(
                    _position(track),
                    selected_scene_position,
                ),
            )
            for track in sorted(tracks, key=lambda item: item.track_id)
        )
        competing = sorted(
            item.residual_to_selected_path_quanta
            for item in track_distances
            if item.public_track_id != selected
        )
        if competing and competing[0] - selected_residual < _AMBIGUITY_MARGIN_QUANTA:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "selected scene path has two plausible public identities"
            )
        payload = {
            "schema_version": "FormalPublicTrackScenePathBindingReceiptV1",
            "request_sha256": canonical_sha256(request),
            "formal_observation_sha256": observation.wire_sha256,
            "association_deployment_sha256": (
                self.association_deployment.deployment_binding_sha256
            ),
            "scene_geometry_receipt_sha256": self.scene_geometry.receipt_sha256,
            "selected_public_track_id": selected,
            "selected_public_position_world_m": selected_position,
            "selected_external_contact_path": selected_path,
            "selected_residual_quanta": selected_residual,
            "scene_path_distances": [item.model_dump(mode="json") for item in path_distances],
            "public_track_distances_to_selected_path": [
                item.model_dump(mode="json") for item in track_distances
            ],
            "distance_quantum_m": PUBLIC_SCENE_BINDING_DISTANCE_QUANTUM_M,
            "residual_gate_m": PUBLIC_SCENE_BINDING_RESIDUAL_GATE_M,
            "ambiguity_margin_m": PUBLIC_SCENE_BINDING_AMBIGUITY_MARGIN_M,
            "assignment_policy": (
                "SELECTED_TRACK_MINIMUM_QUANTIZED_RESIDUAL_WITH_TWO_SIDED_UNIQUENESS_V1"
            ),
            "observed_at_ns": observed_at_ns,
            "query_only": True,
            "simulator_paths_exposed_to_model": False,
            "simulator_paths_used_only_for_a3_gates": True,
            "teacher_used": False,
            "task_spec_identity_used": False,
            "privileged_truth_policy_input": False,
        }
        return FormalPublicTrackScenePathBindingReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )

    def query_scene_safety_binding(
        self,
        *,
        request: IsaacExecuteRequestV4,
        observation: FormalPublicObservationV4,
        after_ns: int,
    ) -> FormalPlanSynthesisSceneSafetyBindingV1:
        if (
            observation.association_deployment_sha256
            != self.association_deployment.deployment_binding_sha256
            or request.formal_observation_sha256 != observation.wire_sha256
        ):
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "scene-safety query crosses public association deployment"
            )
        before = self.mutation_counter_source.snapshot_mutation_counters()
        all_paths = tuple(item.link_path for item in self.scene_geometry.source_links)
        raw_poses, observed_at_ns = self.scene_pose_source.query_scene_link_world_poses(
            link_paths=all_paths,
            after_ns=after_ns,
        )
        scene_poses = {
            path: A3RigidTransformV1.model_validate(
                value.model_dump(mode="json") if isinstance(value, BaseModel) else value
            )
            for path, value in raw_poses.items()
        }
        if set(scene_poses) != set(all_paths) or observed_at_ns <= after_ns:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "scene-safety pose inventory or time differs"
            )
        target = self._bind_target(
            request=request,
            observation=observation,
            scene_poses=scene_poses,
            observed_at_ns=observed_at_ns,
        )
        attachment = self.active_attachment_source.snapshot_active_attachment()
        after = self.mutation_counter_source.snapshot_mutation_counters()
        if before != after:
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "scene-safety query mutated the active session"
            )
        if (
            attachment is not None
            and target is not None
            and (
                attachment.public_track_id == target.selected_public_track_id
                and attachment.external_contact_path != target.selected_external_contact_path
            )
        ):
            raise FormalIsaacSceneSafetyBindingUnavailable(
                "active attachment differs from fresh public-scene binding"
            )
        environment = tuple(item.link_path for item in self.scene_geometry.source_links)
        payload: dict[str, Any] = {
            "schema_version": "FormalPlanSynthesisSceneSafetyBindingV1",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "decision_index": request.decision_index,
            "observation_id": observation.observation_id,
            "capture_receipt_sha256": observation.capture_receipt_sha256,
            "formal_observation_sha256": observation.wire_sha256,
            "executed_intent_history_sha256": request.executed_intent_history_sha256,
            "selected_skill": request.runtime_request.skill,
            "target_public_track_id": (
                target.selected_public_track_id if target is not None else None
            ),
            "target_external_contact_path": (
                target.selected_external_contact_path if target is not None else None
            ),
            "target_binding_receipt_sha256": (
                target.receipt_sha256 if target is not None else None
            ),
            "attached_public_track_id": (
                attachment.public_track_id if attachment is not None else None
            ),
            "attached_external_contact_path": (
                attachment.external_contact_path if attachment is not None else None
            ),
            "active_attachment_receipt_sha256": (
                attachment.receipt_sha256 if attachment is not None else None
            ),
            "environment_collision_paths": environment,
            "scene_geometry_receipt_sha256": self.scene_geometry.receipt_sha256,
            "source_implementation_sha256": self.implementation_sha256,
            "observed_at_ns": observed_at_ns,
            "mutation_counters_before": before,
            "mutation_counters_after": after,
            "real_isaac": self.real_isaac,
            "mocked_physics": self.mocked_physics,
            "simulator_paths_used_for_skill_or_pointer_selection": False,
            "simulator_paths_exposed_to_model": False,
            "simulator_paths_used_only_for_a3_gates": True,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "controller_commands": 0,
            "attachment_mutations": 0,
            "teacher_used": False,
            "evaluator_identity_used": False,
            "task_spec_fallback_used": False,
            "privileged_truth_policy_input": False,
        }
        binding = FormalPlanSynthesisSceneSafetyBindingV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )
        self.journal.append(
            "PUBLIC_TRACK_SCENE_SAFETY_BINDING_COMMITTED",
            {
                "target_binding": (target.model_dump(mode="json") if target is not None else None),
                "scene_safety_binding": binding.model_dump(mode="json"),
            },
        )
        return binding
