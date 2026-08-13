"""Versioned ADR-0024 public observation transport for the formal path.

This module does not replace ``FormalPublicObservationV2`` and does not make
the real Isaac backend executable.  It defines the missing wire-level record
whose V4 association history and K=8 candidate digest can be independently
replayed before a model request or exact plan consumes them.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Literal, Mapping

from pydantic import Field, model_validator

from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationDeploymentBindingV2,
    PublicAssociationSessionReceiptV2,
    PublicProprioceptionJournalBindingV2,
)
from xh_agent.policy.qrm_lite.contracts import StrictModel
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    PublicAssetInlineV2,
    SHA256_PATTERN,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
    PublicDeclaredTargetAttributeBindingV4,
    validate_public_observation_replay_v4,
)


_TRACK_ID_PATTERN = r"^track-[0-9a-f]{8}$"


class FormalPublicCaptureReceiptV4(StrictModel):
    """Canonical whole-capture binding consumed by exact-plan A.1."""

    schema_version: Literal["FormalPublicCaptureReceiptV4"] = "FormalPublicCaptureReceiptV4"
    observation_id: str = Field(min_length=1)
    captured_at_ns: int = Field(gt=0)
    association_capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    rgb_sha256: str = Field(pattern=SHA256_PATTERN)
    depth_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_payload_sha256: str = Field(pattern=SHA256_PATTERN)
    association_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    proprioception_journal_sha256: str = Field(pattern=SHA256_PATTERN)
    association_session_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def receipt_is_canonical(self) -> "FormalPublicCaptureReceiptV4":
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("formal V4 whole-capture receipt digest differs")
        return self


class FormalPublicObservationV4(StrictModel):
    """Fresh, replayable V4 public input with no privileged policy fields."""

    schema_version: Literal["FormalPublicObservationV4"] = "FormalPublicObservationV4"
    observation: PathBlockedPublicObservationV4
    previous_physical_completed_at_ns: int = Field(ge=0)
    rgb: PublicAssetInlineV2
    depth: PublicAssetInlineV2
    canonical_slots: list[str | None] = Field(min_length=8, max_length=8)
    association_deployment: PublicAssociationDeploymentBindingV2
    association_deployment_sha256: str = Field(pattern=SHA256_PATTERN)
    proprioception_journal: PublicProprioceptionJournalBindingV2
    proprioception_journal_sha256: str = Field(pattern=SHA256_PATTERN)
    association_session_receipt: PublicAssociationSessionReceiptV2
    association_session_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    declared_attribute_binding: PublicDeclaredTargetAttributeBindingV4
    declared_attribute_binding_sha256: str = Field(pattern=SHA256_PATTERN)
    formal_capture_receipt: FormalPublicCaptureReceiptV4
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def bytes_slots_and_external_bindings_are_exact(self) -> "FormalPublicObservationV4":
        observation = self.observation
        if observation.captured_at_ns <= self.previous_physical_completed_at_ns:
            raise ValueError("formal V4 capture is not newer than the previous physical event")
        if (
            self.rgb.uri != observation.rgb_uri
            or self.rgb.sha256 != observation.rgb_sha256
            or self.rgb.media_type not in {"image/png", "image/jpeg"}
        ):
            raise ValueError("formal V4 RGB transport differs from replayed observation")
        if (
            self.depth.uri != observation.depth_uri
            or self.depth.sha256 != observation.depth_sha256
            or self.depth.media_type != "application/x-npy"
        ):
            raise ValueError("formal V4 depth transport differs from replayed observation")
        valid_ids = [item.track_id for item in observation.candidate_payload.candidates]
        expected_slots: list[str | None] = [*valid_ids, *([None] * (8 - len(valid_ids)))]
        if self.canonical_slots != expected_slots:
            raise ValueError("formal V4 K=8 slots differ from the replayed candidate payload")
        if any(
            track_id is not None and re.fullmatch(_TRACK_ID_PATTERN, track_id) is None
            for track_id in self.canonical_slots
        ):
            raise ValueError("formal V4 slots contain a non-public track identifier")

        if (
            self.association_deployment_sha256
            != self.association_deployment.deployment_binding_sha256
        ):
            raise ValueError("formal V4 association deployment digest differs")
        if self.proprioception_journal_sha256 != self.proprioception_journal.journal_sha256:
            raise ValueError("formal V4 proprioception journal digest differs")
        if (
            self.association_session_receipt_sha256
            != self.association_session_receipt.session_receipt_sha256
        ):
            raise ValueError("formal V4 association session receipt digest differs")
        if self.declared_attribute_binding_sha256 != self.declared_attribute_binding.binding_sha256:
            raise ValueError("formal V4 declared attribute binding digest differs")

        expected_capture = {
            "observation_id": observation.observation_id,
            "captured_at_ns": observation.captured_at_ns,
            "association_capture_receipt_sha256": observation.capture_receipt_sha256,
            "rgb_sha256": observation.rgb_sha256,
            "depth_sha256": observation.depth_sha256,
            "candidate_payload_sha256": observation.candidate_payload_sha256,
            "association_deployment_sha256": self.association_deployment_sha256,
            "proprioception_journal_sha256": self.proprioception_journal_sha256,
            "association_session_receipt_sha256": self.association_session_receipt_sha256,
            "declared_attribute_binding_sha256": self.declared_attribute_binding_sha256,
        }
        if any(
            getattr(self.formal_capture_receipt, name) != value
            for name, value in expected_capture.items()
        ):
            raise ValueError("formal V4 whole-capture receipt crosses observation/session inputs")

        validate_public_observation_replay_v4(
            observation,
            expected_deployment=self.association_deployment,
            expected_deployment_binding_sha256=self.association_deployment_sha256,
            expected_journal=self.proprioception_journal,
            expected_session_receipt=self.association_session_receipt,
            expected_session_receipt_sha256=self.association_session_receipt_sha256,
            expected_attribute_binding=self.declared_attribute_binding,
            expected_attribute_binding_sha256=self.declared_attribute_binding_sha256,
        )
        return self

    @property
    def observation_id(self) -> str:
        return self.observation.observation_id

    @property
    def captured_at_ns(self) -> int:
        return self.observation.captured_at_ns

    @property
    def capture_receipt_sha256(self) -> str:
        return self.formal_capture_receipt.receipt_sha256

    @property
    def association_capture_receipt_sha256(self) -> str:
        return self.observation.capture_receipt_sha256

    @property
    def canonical_public_tracks_sha256(self) -> str:
        """Exact ADR-0024 K=8 candidate digest used by exact-plan A.1."""

        return self.observation.candidate_payload_sha256

    @property
    def wire_sha256(self) -> str:
        return canonical_sha256(self)


def public_asset_inline_v4(
    *,
    uri: str,
    sha256: str,
    media_type: Literal["image/png", "image/jpeg", "application/x-npy"],
    data: bytes,
) -> PublicAssetInlineV2:
    """Build the existing byte-bound asset envelope without touching disk."""

    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("formal V4 asset bytes differ from the replayed SHA-256")
    return PublicAssetInlineV2(
        uri=uri,
        sha256=sha256,
        media_type=media_type,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def formal_public_capture_receipt_v4(
    *,
    observation: PathBlockedPublicObservationV4,
    association_deployment_sha256: str,
    proprioception_journal_sha256: str,
    association_session_receipt_sha256: str,
    declared_attribute_binding_sha256: str,
) -> FormalPublicCaptureReceiptV4:
    payload = {
        "schema_version": "FormalPublicCaptureReceiptV4",
        "observation_id": observation.observation_id,
        "captured_at_ns": observation.captured_at_ns,
        "association_capture_receipt_sha256": observation.capture_receipt_sha256,
        "rgb_sha256": observation.rgb_sha256,
        "depth_sha256": observation.depth_sha256,
        "candidate_payload_sha256": observation.candidate_payload_sha256,
        "association_deployment_sha256": association_deployment_sha256,
        "proprioception_journal_sha256": proprioception_journal_sha256,
        "association_session_receipt_sha256": association_session_receipt_sha256,
        "declared_attribute_binding_sha256": declared_attribute_binding_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return FormalPublicCaptureReceiptV4(
        **payload,
        receipt_sha256=canonical_sha256(payload),
    )


def load_formal_public_observation_v4(
    raw: str | bytes | Mapping[str, object],
    *,
    expected_association_deployment_sha256: str,
) -> FormalPublicObservationV4:
    """Validate a wire record against the endpoint's frozen deployment hash."""

    if isinstance(raw, (str, bytes)):
        observation = FormalPublicObservationV4.model_validate_json(raw)
    else:
        observation = FormalPublicObservationV4.model_validate(raw)
    if observation.association_deployment_sha256 != expected_association_deployment_sha256:
        raise ValueError("formal V4 observation differs from expected endpoint deployment")
    return observation
