"""Public-only state machine for one persistent formal V4 Isaac scene.

The Isaac-specific capture source is deliberately injected through a narrow
protocol.  This module owns the formal episode identity, converts each raw
public RGB-D/proprioception frame into the exact ``PublicAssociationCaptureV2``
wire, and replays the complete association history for the terminal public
outcome.  It never accepts a TaskSpec target id, simulator entity/prim id,
Teacher output, or privileged outcome truth.

Construction alone is not an execution authorization.  The enclosing
``FormalIsaacEpisodeIOV4`` still requires a reviewed deployment binding and
the HTTP service factory remains fail-closed until the Phase-2 addendum binds
this source and its real Isaac implementation.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.data_engine.isaac.public_failure_predicates import (
    PublicTrackSnapshotV2,
    infer_occlusion_aware_lift_success_predicates,
    select_task_target_track,
)
from xh_agent.grasp.free_gap import select_free_gap_yaw_from_xy
from xh_agent.perception.public_track_associator_v2 import (
    LastPhysicallyExecutedPublicSkillV2,
    PublicAssociationCaptureV2,
    PublicAssociationDeploymentBindingV2,
    PublicAssociationSessionReceiptV2,
    PublicProprioceptionIntervalV2,
    PublicProprioceptionJournalBindingV2,
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
    PublicTrackAssociatorV2,
)
from xh_agent.policy.qrm_lite.formal_isaac_episode_io_v4 import (
    FormalIsaacSceneFinalEvidenceV4,
    FormalIsaacSceneStartEvidenceV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    FormalPublicCapturePacketV4,
    build_prefix_journal_v4,
    build_prefix_session_receipt_v4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    PublicAssetInlineV2,
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacStartRequestV4,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PublicDeclaredTargetAttributeBindingV4,
)


IMPLEMENTATION_REPO_PATH = "src/xh_agent/policy/qrm_lite/formal_isaac_scene_owner_v4.py"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


class FormalIsaacRawPublicFrameV4(_FrozenModel):
    """One unassociated public frame emitted by the real scene source."""

    schema_version: Literal["FormalIsaacRawPublicFrameV4"] = "FormalIsaacRawPublicFrameV4"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    capture_index: int = Field(ge=-1, le=8)
    label: Literal["FAILURE_BOUNDARY", "POLICY_INPUT", "FINAL_EVALUATION"]
    previous_execution_completed_at_ns: int = Field(ge=0)
    captured_at_ns: int = Field(gt=0)
    capture_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    detections: tuple[PublicRGBDDetectionV2, ...]
    proprioception_samples: tuple[PublicRobotProprioceptionV2, ...] = Field(min_length=1)
    last_physically_executed_public_skill: LastPhysicallyExecutedPublicSkillV2 | None = None
    rgb: PublicAssetInlineV2
    depth: PublicAssetInlineV2
    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    frame_receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def public_frame_is_complete_and_canonical(self) -> "FormalIsaacRawPublicFrameV4":
        if self.captured_at_ns <= self.previous_execution_completed_at_ns:
            raise ValueError("formal V4 raw frame is not fresh after prior execution")
        if self.rgb.media_type not in {"image/png", "image/jpeg"}:
            raise ValueError("formal V4 raw frame RGB media type differs")
        if self.depth.media_type != "application/x-npy":
            raise ValueError("formal V4 raw frame depth media type differs")
        if any(item.timestamp_ns != self.captured_at_ns for item in self.detections):
            raise ValueError("formal V4 raw detections differ from capture time")
        sample_times = tuple(item.timestamp_ns for item in self.proprioception_samples)
        if sample_times[-1] != self.captured_at_ns or any(
            after <= before for before, after in zip(sample_times, sample_times[1:])
        ):
            raise ValueError("formal V4 raw proprioception is not ordered to capture")
        if self.frame_receipt_sha256 != _model_sha256(self, "frame_receipt_sha256"):
            raise ValueError("formal V4 raw frame digest differs")
        return self


class FormalIsaacRawPublicFrameSourceV4(Protocol):
    """Real scene surface; no association, planning, or outcome label."""

    implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool

    def capture_raw_public_frame_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        capture_index: int,
        label: Literal["FAILURE_BOUNDARY", "POLICY_INPUT", "FINAL_EVALUATION"],
        previous_execution_completed_at_ns: int,
    ) -> FormalIsaacRawPublicFrameV4: ...


def _world_position(
    detection: PublicRGBDDetectionV2,
    deployment: PublicAssociationDeploymentBindingV2,
) -> tuple[float, float, float]:
    matrix = deployment.protocol.camera_to_world_row_major
    x, y, z = (float(value) for value in detection.position_3d)
    values = (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("formal V4 public world projection is not finite")
    return values


def _boundary_snapshots(
    frame: FormalIsaacRawPublicFrameV4,
    deployment: PublicAssociationDeploymentBindingV2,
) -> list[PublicTrackSnapshotV2]:
    ordered = sorted(
        enumerate(frame.detections),
        key=lambda item: (*_world_position(item[1], deployment), item[0]),
    )
    return [
        PublicTrackSnapshotV2(
            track_id=f"boundary-{index:03d}",
            category=detection.category,
            visual_color=detection.attributes.visual_color,
            position_world_m=list(_world_position(detection, deployment)),
            confidence=detection.confidence,
        )
        for index, detection in ordered
    ]


def _associated_snapshots(tracks: tuple[Any, ...]) -> list[PublicTrackSnapshotV2]:
    return [
        PublicTrackSnapshotV2(
            track_id=item.track_id,
            category=item.category,
            visual_color=item.attributes.visual_color,
            position_world_m=list(item.position_world_m),
            confidence=item.confidence,
        )
        for item in tracks
    ]


class FormalIsaacPersistentSceneOwnerCoreV4:
    """One formal episode over a single injected real-Isaac frame source."""

    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False

    def __init__(
        self,
        *,
        implementation_sha256: str,
        source: FormalIsaacRawPublicFrameSourceV4,
        association_deployment: PublicAssociationDeploymentBindingV2,
        declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
    ) -> None:
        if (
            not source.real_isaac
            or source.mocked_physics
            or source.implementation_sha256
            != association_deployment.capture_source_implementation_sha256
        ):
            raise ValueError("formal V4 scene owner source differs from real deployment")
        if declared_attribute_binding.declared_target_attribute != "yellow":
            raise ValueError("formal V4 scene owner requires the accepted yellow attribute")
        self.implementation_sha256 = implementation_sha256
        self.capture_source_implementation_sha256 = source.implementation_sha256
        self.source = source
        self.association_deployment = PublicAssociationDeploymentBindingV2.model_validate(
            association_deployment.model_dump(mode="json")
        )
        self.declared_attribute_binding = PublicDeclaredTargetAttributeBindingV4.model_validate(
            declared_attribute_binding.model_dump(mode="json")
        )
        self._run_id: str | None = None
        self._session_id: str | None = None
        self._failure_observed_at_ns = 0
        self._captures: tuple[PublicAssociationCaptureV2, ...] = ()
        self._terminal = False

    def _validate_raw(
        self,
        raw: FormalIsaacRawPublicFrameV4,
        *,
        run_id: str,
        session_id: str,
        capture_index: int,
        label: str,
        previous_execution_completed_at_ns: int,
    ) -> FormalIsaacRawPublicFrameV4:
        frame = FormalIsaacRawPublicFrameV4.model_validate(raw.model_dump(mode="json"))
        expected = {
            "run_id": run_id,
            "session_id": session_id,
            "capture_index": capture_index,
            "label": label,
            "previous_execution_completed_at_ns": previous_execution_completed_at_ns,
            "capture_source_implementation_sha256": (self.capture_source_implementation_sha256),
        }
        if any(getattr(frame, name) != value for name, value in expected.items()):
            raise ValueError("formal V4 raw frame crosses scene owner request")
        protocol = self.association_deployment.protocol
        if any(item.frame_id != protocol.declared_camera_frame for item in frame.detections):
            raise ValueError("formal V4 raw detection frame differs from deployment")
        if any(
            item.world_frame != protocol.declared_world_frame
            for item in frame.proprioception_samples
        ):
            raise ValueError("formal V4 raw proprioception frame differs from deployment")
        return frame

    def establish_public_failure_boundary_v4(
        self,
        request: IsaacStartRequestV4,
    ) -> FormalIsaacSceneStartEvidenceV4:
        if self._run_id is not None or self._terminal:
            raise RuntimeError("formal V4 scene owner start is single-use")
        if (
            request.declared_target_attribute
            != self.declared_attribute_binding.declared_target_attribute
            or request.declared_attribute_binding_sha256
            != self.declared_attribute_binding.binding_sha256
        ):
            raise ValueError("formal V4 scene owner start crosses public attribute binding")
        session_id = f"{request.run_id}-{uuid.uuid4().hex}"
        raw = self.source.capture_raw_public_frame_v4(
            run_id=request.run_id,
            session_id=session_id,
            capture_index=-1,
            label="FAILURE_BOUNDARY",
            previous_execution_completed_at_ns=0,
        )
        frame = self._validate_raw(
            raw,
            run_id=request.run_id,
            session_id=session_id,
            capture_index=-1,
            label="FAILURE_BOUNDARY",
            previous_execution_completed_at_ns=0,
        )
        snapshots = _boundary_snapshots(frame, self.association_deployment)
        target = select_task_target_track(
            snapshots,
            visual_color=self.declared_attribute_binding.declared_target_attribute,
            world_axis="x",
            extremum="max",
        )
        neighbors = [
            item.position_world_m[:2] for item in snapshots if item.track_id != target.track_id
        ]
        gap = select_free_gap_yaw_from_xy(
            target.position_world_m[:2],
            neighbors,
            source="PUBLIC_RGBD_PATH_BLOCKED_FAILURE_BOUNDARY_V4",
        )
        if gap["clearance_ok"] is not False:
            raise ValueError("formal V4 scene lacks public PATH_BLOCKED geometry")
        boundary_payload = {
            "raw_frame_receipt_sha256": frame.frame_receipt_sha256,
            "public_snapshots": [item.model_dump(mode="json") for item in snapshots],
            "task_target_track_id": target.track_id,
            "free_gap": gap,
            "association_deployment_sha256": (
                self.association_deployment.deployment_binding_sha256
            ),
            "declared_attribute_binding_sha256": (self.declared_attribute_binding.binding_sha256),
        }
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacSceneStartEvidenceV4",
            "run_id": request.run_id,
            "session_id": session_id,
            "start_request_sha256": canonical_sha256(request),
            "endpoint_binding_sha256": request.endpoint_binding_sha256,
            "scene_owner_implementation_sha256": self.implementation_sha256,
            "matched_key": request.matched_key,
            "scene_seed": request.scene_seed,
            "failure_seed": request.failure_seed,
            "sdf_sha256": request.sdf_sha256,
            "supervision_sha256": request.supervision_sha256,
            "declared_attribute_binding_sha256": (request.declared_attribute_binding_sha256),
            "failure_observed_at_ns": frame.captured_at_ns,
            "public_failure_boundary_evidence_sha256": canonical_sha256(boundary_payload),
            "real_isaac": True,
            "mocked_physics": False,
            "failure_boundary_derived_from_public_observation": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        evidence = FormalIsaacSceneStartEvidenceV4(
            **payload,
            evidence_sha256=canonical_sha256(payload),
        )
        self._run_id = request.run_id
        self._session_id = session_id
        self._failure_observed_at_ns = frame.captured_at_ns
        return evidence

    def _capture_from_frame(
        self,
        frame: FormalIsaacRawPublicFrameV4,
        *,
        include_in_policy_history: bool,
    ) -> PublicAssociationCaptureV2:
        previous = self._captures[-1] if self._captures else None
        expected_start = frame.captured_at_ns if previous is None else previous.timestamp_ns
        samples = frame.proprioception_samples
        if samples[0].timestamp_ns != expected_start:
            raise ValueError("formal V4 raw proprioception lacks prior capture endpoint")
        sample_payload = [item.model_dump(mode="json") for item in samples]
        interval = PublicProprioceptionIntervalV2(
            start_capture_timestamp_ns=expected_start,
            end_capture_timestamp_ns=frame.captured_at_ns,
            expected_sample_timestamps_ns=[item.timestamp_ns for item in samples],
            samples=list(samples),
            samples_sha256=canonical_sha256(sample_payload),
        )
        payload: dict[str, Any] = {
            "schema_version": "PublicAssociationCaptureV2",
            "timestamp_ns": frame.captured_at_ns,
            "protocol": self.association_deployment.protocol.model_dump(mode="json"),
            "previous_capture_receipt_sha256": (
                previous.capture_receipt_sha256 if previous is not None else None
            ),
            "detections": [item.model_dump(mode="json") for item in frame.detections],
            "proprioception_interval": interval.model_dump(mode="json"),
            "last_physically_executed_public_skill": (
                frame.last_physically_executed_public_skill.model_dump(mode="json")
                if frame.last_physically_executed_public_skill is not None
                else None
            ),
        }
        capture = PublicAssociationCaptureV2(
            **payload,
            capture_receipt_sha256=canonical_sha256(payload),
        )
        if include_in_policy_history:
            self._captures = (*self._captures, capture)
        return capture

    def capture_public_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicCapturePacketV4:
        if (
            self._terminal
            or (run_id, session_id) != (self._run_id, self._session_id)
            or decision_index != len(self._captures)
        ):
            raise ValueError("formal V4 scene owner capture crosses active episode")
        raw = self.source.capture_raw_public_frame_v4(
            run_id=run_id,
            session_id=session_id,
            capture_index=decision_index,
            label="POLICY_INPUT",
            previous_execution_completed_at_ns=previous_execution_completed_at_ns,
        )
        frame = self._validate_raw(
            raw,
            run_id=run_id,
            session_id=session_id,
            capture_index=decision_index,
            label="POLICY_INPUT",
            previous_execution_completed_at_ns=previous_execution_completed_at_ns,
        )
        if (decision_index == 0) != (frame.last_physically_executed_public_skill is None):
            raise ValueError("formal V4 raw frame last-skill chain differs")
        capture = self._capture_from_frame(frame, include_in_policy_history=True)
        return FormalPublicCapturePacketV4(
            run_id=run_id,
            session_id=session_id,
            decision_index=decision_index,
            observation_id=f"{session_id}-observation-{decision_index}",
            previous_execution_completed_at_ns=previous_execution_completed_at_ns,
            capture_source_implementation_sha256=(self.capture_source_implementation_sha256),
            capture=capture,
            rgb=frame.rgb,
            depth=frame.depth,
            real_isaac=True,
            mocked_physics=False,
            contract_test_only=False,
            teacher_used=False,
            privileged_truth_policy_input=False,
        )

    def _replay_with_final_capture(
        self,
        final_capture: PublicAssociationCaptureV2,
    ) -> tuple[tuple[Any, ...], tuple[Any, ...], PublicProprioceptionJournalBindingV2]:
        captures = (*self._captures, final_capture)
        journal = build_prefix_journal_v4(
            captures,
            deployment=self.association_deployment,
        )
        session: PublicAssociationSessionReceiptV2 = build_prefix_session_receipt_v4(
            journal,
            deployment=self.association_deployment,
        )
        associator = PublicTrackAssociatorV2(
            expected_deployment=self.association_deployment,
            expected_deployment_binding_sha256=(
                self.association_deployment.deployment_binding_sha256
            ),
            expected_journal=journal,
            expected_session_receipt=session,
            expected_session_receipt_sha256=session.session_receipt_sha256,
        )
        before: tuple[Any, ...] = ()
        after: tuple[Any, ...] = ()
        for index, capture in enumerate(captures):
            associated = tuple(associator.associate(capture))
            if index == 7:
                before = associated
            if index == 8:
                after = associated
        if not associator.journal_complete or not before or not after:
            raise ValueError("formal V4 final association replay is incomplete")
        return before, after, journal

    def evaluate_public_outcome_v4(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacSceneFinalEvidenceV4:
        if (
            self._terminal
            or (request.run_id, request.session_id) != (self._run_id, self._session_id)
            or len(self._captures) != 8
            or len(execution_responses) != 8
        ):
            raise ValueError("formal V4 final public evaluation crosses active episode")
        self._terminal = True
        last = execution_responses[-1]
        last_receipt = last.execution_receipts[0]
        raw = self.source.capture_raw_public_frame_v4(
            run_id=request.run_id,
            session_id=request.session_id,
            capture_index=8,
            label="FINAL_EVALUATION",
            previous_execution_completed_at_ns=last_receipt.completed_at_ns,
        )
        frame = self._validate_raw(
            raw,
            run_id=request.run_id,
            session_id=request.session_id,
            capture_index=8,
            label="FINAL_EVALUATION",
            previous_execution_completed_at_ns=last_receipt.completed_at_ns,
        )
        final_capture = self._capture_from_frame(
            frame,
            include_in_policy_history=False,
        )
        before_tracks, after_tracks, journal = self._replay_with_final_capture(final_capture)
        target = last.mapping.target_track_id
        before_samples = self._captures[-1].proprioception_interval.samples
        final_samples = final_capture.proprioception_interval.samples
        predicate = None
        if target is not None:
            predicate = infer_occlusion_aware_lift_success_predicates(
                _associated_snapshots(before_tracks),
                _associated_snapshots(after_tracks),
                task_target_track_id=target,
                hand_before_world_m=list(before_samples[-1].end_effector_position_world_m),
                hand_after_world_m=list(final_samples[-1].end_effector_position_world_m),
                gripper_closed=final_samples[-1].gripper_closed,
            )
        final_success = bool(
            last.mapping.canonical_skill == "REGRASP"
            and last.bundle_execution_receipt is not None
            and last.bundle_execution_receipt.status == "PASS"
            and predicate is not None
            and {"grasped=true", "lifted=true"}.issubset(predicate.predicates)
        )
        response_hashes = tuple(canonical_sha256(item) for item in execution_responses)
        evaluation_payload = {
            "policy_capture_count": len(self._captures),
            "final_capture_receipt_sha256": final_capture.capture_receipt_sha256,
            "complete_journal_sha256": journal.journal_sha256,
            "before_tracks_sha256": canonical_sha256(
                [item.model_dump(mode="json") for item in before_tracks]
            ),
            "after_tracks_sha256": canonical_sha256(
                [item.model_dump(mode="json") for item in after_tracks]
            ),
            "predicate": predicate.model_dump(mode="json") if predicate is not None else None,
            "execution_response_sha256": response_hashes,
            "final_task_success": final_success,
        }
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacSceneFinalEvidenceV4",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "finalize_request_sha256": canonical_sha256(request),
            "scene_owner_implementation_sha256": self.implementation_sha256,
            "last_execution_receipt_sha256": request.last_execution_receipt_sha256,
            "last_bundle_execution_receipt_sha256": (request.last_bundle_execution_receipt_sha256),
            "execution_response_sha256": response_hashes,
            "public_evaluation_evidence_sha256": canonical_sha256(evaluation_payload),
            "evaluated_at_ns": frame.captured_at_ns,
            "final_task_success": final_success,
            "real_isaac": True,
            "mocked_physics": False,
            "outcome_used_as_policy_input": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return FormalIsaacSceneFinalEvidenceV4(
            **payload,
            evidence_sha256=canonical_sha256(payload),
        )


def implementation_sha256_v4() -> str:
    """Return the byte identity used by the reviewed deployment builder."""

    with open(__file__, "rb") as source:
        return hashlib.sha256(source.read()).hexdigest()
