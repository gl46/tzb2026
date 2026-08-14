"""Live prefix-replay provider for formal public V4 observations.

The provider contains no detector, simulator, planner, or controller.  A
separately frozen capture source supplies one already hash-bound public RGB-D
capture plus the complete public proprioception interval.  For every cycle we
freeze the current capture prefix, replay ``PublicTrackAssociatorV2`` from an
empty state, and construct the exact ``FormalPublicObservationV4`` consumed by
Qwen and the exact-plan A.1 gate.

Production mode is fail-closed: it accepts only real-Isaac packets from the
deployment-bound source and rechecks the hard freeze on every capture.  The
contract-test mode is explicit and can never claim real physics.
"""

from __future__ import annotations

import threading
from typing import Literal, Protocol

from pydantic import Field, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationCaptureV2,
    PublicAssociatedTrackV2,
    PublicAssociationDeploymentBindingV2,
    PublicAssociationSessionReceiptV2,
    PublicProprioceptionCaptureBindingV2,
    PublicProprioceptionJournalBindingV2,
    PublicTrackAssociatorV2,
)
from xh_agent.policy.qrm_lite.contracts import StrictModel
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
    formal_public_capture_receipt_v4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    PublicAssetInlineV2,
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
    PublicAssociationReplayFrameV4,
    PublicDeclaredTargetAttributeBindingV4,
    associated_tracks_to_perception_tracks_v4,
)
from xh_agent.policy.qrm_lite.public_tracks_v4 import (
    build_public_track_candidates_v4,
    canonical_candidate_payload_v4,
    canonical_candidate_sha256_v4,
)


class FormalPublicCapturePacketV4(StrictModel):
    """One source-produced capture before public association replay."""

    schema_version: Literal["FormalPublicCapturePacketV4"] = "FormalPublicCapturePacketV4"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    observation_id: str = Field(min_length=1)
    previous_execution_completed_at_ns: int = Field(ge=0)
    capture_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    capture: PublicAssociationCaptureV2
    rgb: PublicAssetInlineV2
    depth: PublicAssetInlineV2
    real_isaac: bool
    mocked_physics: bool
    contract_test_only: bool
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def source_mode_and_time_are_exact(self) -> "FormalPublicCapturePacketV4":
        if self.real_isaac == self.mocked_physics:
            raise ValueError("formal V4 capture packet must be exactly real or mocked")
        if self.contract_test_only != self.mocked_physics:
            raise ValueError("formal V4 capture packet mode is internally inconsistent")
        if self.capture.timestamp_ns <= self.previous_execution_completed_at_ns:
            raise ValueError("formal V4 capture packet is not fresh after prior execution")
        if self.rgb.media_type not in {"image/png", "image/jpeg"}:
            raise ValueError("formal V4 capture packet RGB media type differs")
        if self.depth.media_type != "application/x-npy":
            raise ValueError("formal V4 capture packet depth media type differs")
        return self


class FormalPublicCaptureSourceV4(Protocol):
    """Frozen source boundary; implementations may own a real Isaac scene."""

    implementation_sha256: str
    real_isaac: bool
    mocked_physics: bool

    def capture_public_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicCapturePacketV4: ...


def build_prefix_journal_v4(
    captures: tuple[PublicAssociationCaptureV2, ...],
    *,
    deployment: PublicAssociationDeploymentBindingV2,
) -> PublicProprioceptionJournalBindingV2:
    """Freeze the exact public capture prefix supplied to the associator."""

    payload = {
        "schema_version": "PublicProprioceptionJournalBindingV2",
        "protocol_sha256": deployment.protocol_sha256,
        "source_implementation_sha256": deployment.capture_source_implementation_sha256,
        "captures": [
            PublicProprioceptionCaptureBindingV2(
                capture_timestamp_ns=capture.timestamp_ns,
                previous_capture_receipt_sha256=capture.previous_capture_receipt_sha256,
                capture_receipt_sha256=capture.capture_receipt_sha256,
                expected_sample_timestamps_ns=(
                    capture.proprioception_interval.expected_sample_timestamps_ns
                ),
                samples_sha256=capture.proprioception_interval.samples_sha256,
            ).model_dump(mode="json")
            for capture in captures
        ],
    }
    return PublicProprioceptionJournalBindingV2(
        **payload,
        journal_sha256=canonical_sha256(payload),
    )


def build_prefix_session_receipt_v4(
    journal: PublicProprioceptionJournalBindingV2,
    *,
    deployment: PublicAssociationDeploymentBindingV2,
) -> PublicAssociationSessionReceiptV2:
    """Bind one prefix journal to the exact association deployment."""

    payload = {
        "schema_version": "PublicAssociationSessionReceiptV2",
        "deployment_binding_sha256": deployment.deployment_binding_sha256,
        "capture_source_implementation_sha256": (deployment.capture_source_implementation_sha256),
        "proprioception_journal_sha256": journal.journal_sha256,
        "capture_count": len(journal.captures),
        "first_capture_receipt_sha256": journal.captures[0].capture_receipt_sha256,
        "final_capture_receipt_sha256": journal.captures[-1].capture_receipt_sha256,
    }
    return PublicAssociationSessionReceiptV2(
        **payload,
        session_receipt_sha256=canonical_sha256(payload),
    )


class ReplayableFormalPublicObservationProviderV4:
    """One-session public capture coordinator with deterministic prefix replay."""

    def __init__(
        self,
        *,
        mode: Literal["CONTRACT_TEST", "REAL_ISAAC"],
        source: FormalPublicCaptureSourceV4,
        association_deployment: PublicAssociationDeploymentBindingV2,
        declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4,
    ) -> None:
        association_deployment = PublicAssociationDeploymentBindingV2.model_validate(
            association_deployment.model_dump(mode="json")
        )
        declared_attribute_binding = PublicDeclaredTargetAttributeBindingV4.model_validate(
            declared_attribute_binding.model_dump(mode="json")
        )
        if source.implementation_sha256 != (
            association_deployment.capture_source_implementation_sha256
        ):
            raise ValueError("formal V4 capture source differs from association deployment")
        if mode == "REAL_ISAAC":
            if not source.real_isaac or source.mocked_physics:
                raise ValueError("REAL_ISAAC observation provider requires a real source")
        elif source.real_isaac or not source.mocked_physics:
            raise ValueError("CONTRACT_TEST observation provider requires a mocked source")
        self.mode = mode
        self.source = source
        self.deployment = association_deployment
        self.attribute_binding = declared_attribute_binding
        self._run_id: str | None = None
        self._session_id: str | None = None
        self._captures: tuple[PublicAssociationCaptureV2, ...] = ()
        self._observation_ids: frozenset[str] = frozenset()
        self._lock = threading.Lock()
        self._poisoned = False

    def begin_session(self, *, run_id: str, session_id: str) -> None:
        with self._lock:
            if self._run_id is not None or self._captures:
                raise RuntimeError("formal V4 observation provider session is single-use")
            if not run_id or not session_id:
                raise ValueError("formal V4 observation provider session identity is empty")
            self._run_id = run_id
            self._session_id = session_id

    def capture(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicObservationV4:
        with self._lock:
            return self._capture_locked(
                run_id=run_id,
                session_id=session_id,
                decision_index=decision_index,
                previous_execution_completed_at_ns=previous_execution_completed_at_ns,
            )

    def _capture_locked(
        self,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> FormalPublicObservationV4:
        if self.mode == "REAL_ISAAC":
            require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
        if self._poisoned:
            raise RuntimeError("formal V4 observation provider is poisoned after capture failure")
        if (run_id, session_id) != (self._run_id, self._session_id):
            raise ValueError("formal V4 observation request crosses provider session")
        if decision_index != len(self._captures) or decision_index > 7:
            raise ValueError("formal V4 observation request is not the next capture")
        # A source capture advances the public sensor timeline.  Consume the
        # attempt before calling it so an invalid/lost packet cannot be retried
        # and cherry-picked under the same decision index.
        self._poisoned = True
        source_packet = self.source.capture_public_v4(
            run_id=run_id,
            session_id=session_id,
            decision_index=decision_index,
            previous_execution_completed_at_ns=previous_execution_completed_at_ns,
        )
        packet = FormalPublicCapturePacketV4.model_validate(
            source_packet.model_dump(mode="json")
            if isinstance(source_packet, FormalPublicCapturePacketV4)
            else source_packet
        )
        self._validate_packet(
            packet,
            run_id=run_id,
            session_id=session_id,
            decision_index=decision_index,
            previous_execution_completed_at_ns=previous_execution_completed_at_ns,
        )
        if packet.observation_id in self._observation_ids:
            raise ValueError("formal V4 capture packet repeats an observation identity")
        captures = (*self._captures, packet.capture)
        journal = build_prefix_journal_v4(captures, deployment=self.deployment)
        session_receipt = build_prefix_session_receipt_v4(
            journal,
            deployment=self.deployment,
        )
        associator = PublicTrackAssociatorV2(
            expected_deployment=self.deployment,
            expected_deployment_binding_sha256=self.deployment.deployment_binding_sha256,
            expected_journal=journal,
            expected_session_receipt=session_receipt,
            expected_session_receipt_sha256=session_receipt.session_receipt_sha256,
        )
        frames: list[PublicAssociationReplayFrameV4] = []
        for capture in captures:
            tracks = associator.associate(capture)
            frames.append(self._replay_frame(capture, tracks))
        current_tracks = associated_tracks_to_perception_tracks_v4(frames[-1].associated_tracks)
        candidates = build_public_track_candidates_v4(
            current_tracks,
            declared_target_attribute=self.attribute_binding.declared_target_attribute,
        )
        public = PathBlockedPublicObservationV4(
            schema_version="PathBlockedPublicObservationV4",
            observation_id=packet.observation_id,
            captured_at_ns=packet.capture.timestamp_ns,
            source="PUBLIC_RGBD",
            fresh=True,
            rgb_uri=packet.rgb.uri,
            depth_uri=packet.depth.uri,
            rgb_sha256=packet.rgb.sha256,
            depth_sha256=packet.depth.sha256,
            capture_receipt_sha256=packet.capture.capture_receipt_sha256,
            public_track_associator_revision="PublicTrackAssociatorV2",
            camera_frame=packet.capture.protocol.declared_camera_frame,
            position_units="m",
            calibration_sha256=packet.capture.protocol.calibration_sha256,
            association_history=frames,
            perception_tracks=current_tracks,
            declared_target_attribute=self.attribute_binding.declared_target_attribute,
            candidate_payload=canonical_candidate_payload_v4(candidates),
            candidate_payload_sha256=canonical_candidate_sha256_v4(candidates),
            teacher_used=False,
            privileged_truth_policy_input=False,
            task_target_track_id_used_for_candidates=False,
        )
        slots = [item.track_id for item in candidates]
        observation = FormalPublicObservationV4(
            observation=public,
            previous_physical_completed_at_ns=previous_execution_completed_at_ns,
            rgb=packet.rgb,
            depth=packet.depth,
            canonical_slots=[*slots, *([None] * (8 - len(slots)))],
            association_deployment=self.deployment,
            association_deployment_sha256=self.deployment.deployment_binding_sha256,
            proprioception_journal=journal,
            proprioception_journal_sha256=journal.journal_sha256,
            association_session_receipt=session_receipt,
            association_session_receipt_sha256=session_receipt.session_receipt_sha256,
            declared_attribute_binding=self.attribute_binding,
            declared_attribute_binding_sha256=self.attribute_binding.binding_sha256,
            formal_capture_receipt=formal_public_capture_receipt_v4(
                observation=public,
                association_deployment_sha256=self.deployment.deployment_binding_sha256,
                proprioception_journal_sha256=journal.journal_sha256,
                association_session_receipt_sha256=session_receipt.session_receipt_sha256,
                declared_attribute_binding_sha256=self.attribute_binding.binding_sha256,
            ),
        )
        self._captures = captures
        self._observation_ids = self._observation_ids | {packet.observation_id}
        self._poisoned = False
        return observation

    def _validate_packet(
        self,
        packet: FormalPublicCapturePacketV4,
        *,
        run_id: str,
        session_id: str,
        decision_index: int,
        previous_execution_completed_at_ns: int,
    ) -> None:
        if (
            packet.run_id != run_id
            or packet.session_id != session_id
            or packet.decision_index != decision_index
            or packet.previous_execution_completed_at_ns != previous_execution_completed_at_ns
            or packet.capture_source_implementation_sha256
            != self.deployment.capture_source_implementation_sha256
            or packet.capture.protocol != self.deployment.protocol
        ):
            raise ValueError("formal V4 capture packet crosses request/deployment")
        if self.mode == "REAL_ISAAC":
            if not packet.real_isaac or packet.mocked_physics or packet.contract_test_only:
                raise ValueError("formal V4 production capture packet is not real Isaac")
        elif packet.real_isaac or not packet.mocked_physics or not packet.contract_test_only:
            raise ValueError("formal V4 contract capture packet claims real Isaac")
        expected_previous = self._captures[-1].capture_receipt_sha256 if self._captures else None
        if packet.capture.previous_capture_receipt_sha256 != expected_previous:
            raise ValueError("formal V4 capture packet breaks association receipt history")

    @staticmethod
    def _replay_frame(
        capture: PublicAssociationCaptureV2,
        tracks: list[PublicAssociatedTrackV2],
    ) -> PublicAssociationReplayFrameV4:
        return PublicAssociationReplayFrameV4(
            capture=capture,
            associated_tracks=tracks,
            associated_tracks_sha256=canonical_sha256(
                [track.model_dump(mode="json") for track in tracks]
            ),
        )
