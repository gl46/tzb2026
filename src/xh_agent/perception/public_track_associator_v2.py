"""ADR-0024 public-only temporal track association.

``PublicTrackAssociatorV2`` is deliberately separate from the historical V1
tracker.  Its input models expose only the four public input groups approved
by ADR-0024 section 1.  In particular, this module has no TaskSpec, receipt,
outcome, simulator-identity, supervision, or Teacher input.

Positions supplied by RGB-D are expressed in the declared camera frame and
metres.  The approved row-major camera-to-world transform is applied before
the two frozen motion hypotheses are evaluated.  Association is stateful per
instance and an ``associate`` call is atomic under a process-local lock.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


PUBLIC_TRACK_ASSOCIATOR_REVISION = "PublicTrackAssociatorV2"
PUBLIC_TRACK_ASSOCIATION_GATE_M = 0.12
PUBLIC_TRACK_AMBIGUITY_MARGIN_M = 0.02
PUBLIC_TRACK_COST_QUANTUM_M = 0.000001
PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES = 2
PUBLIC_TRACK_MAX_CURRENT_DETECTIONS = 8
PUBLIC_TRACK_HAND_CARRY_SKILLS = frozenset({"GRASP", "LIFT", "MOVE", "REGRASP"})
PUBLIC_TRACK_ASSIGNMENT_OBJECTIVE = (
    "MAXIMUM_CARDINALITY_THEN_MINIMUM_TOTAL_QUANTIZED_COST_THEN_LEXICOGRAPHIC_V2"
)

_COST_QUANTA_PER_METRE = 1_000_000
_ASSOCIATION_GATE_QUANTA = 120_000
_AMBIGUITY_MARGIN_QUANTA = 20_000


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, frozen=True)


class PublicDetectionAttributesV2(_StrictModel):
    """The sole association-visible semantic attribute."""

    visual_color: str | None = None


class PublicBBoxOrMaskV2(_StrictModel):
    """Public image-space component bounds; never an association cost term."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PublicRGBDDetectionV2(_StrictModel):
    """One current, unassociated public RGB-D detection.

    ``bbox_or_mask`` is retained as an opaque public component-quality value;
    it is never inspected by matching.  Current detections intentionally have
    no caller-provided ``track_id`` field, so an external identity cannot
    override association.
    """

    schema_version: Literal["PublicRGBDDetectionV2"] = "PublicRGBDDetectionV2"
    timestamp_ns: int = Field(ge=0)
    frame_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    attributes: PublicDetectionAttributesV2
    position_3d: list[float] = Field(min_length=3, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_or_mask: PublicBBoxOrMaskV2
    visibility: float = Field(ge=0.0, le=1.0)
    covariance_or_quality: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def public_geometry_is_finite(self) -> "PublicRGBDDetectionV2":
        numeric = [*self.position_3d, *self.covariance_or_quality.values()]
        if not all(math.isfinite(float(value)) for value in numeric):
            raise ValueError("public detection geometry/quality must be finite")
        return self


class PublicAssociationProtocolV2(_StrictModel):
    """Explicit public frame, unit, and immutable calibration binding."""

    schema_version: Literal["PublicAssociationProtocolV2"] = "PublicAssociationProtocolV2"
    declared_camera_frame: str = Field(min_length=1)
    declared_world_frame: str = Field(min_length=1)
    metric_units: Literal["m"] = "m"
    camera_to_world_row_major: list[float] = Field(min_length=16, max_length=16)
    calibration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def transform_is_finite_affine(self) -> "PublicAssociationProtocolV2":
        if not all(math.isfinite(float(value)) for value in self.camera_to_world_row_major):
            raise ValueError("camera-to-world calibration must be finite")
        if self.camera_to_world_row_major[12:] != [0.0, 0.0, 0.0, 1.0]:
            raise ValueError("camera-to-world calibration must be a row-major affine transform")
        expected_hash = hashlib.sha256(
            json.dumps(
                self.camera_to_world_row_major,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        if self.calibration_sha256 != expected_hash:
            raise ValueError("calibration SHA-256 does not bind camera-to-world transform")
        return self


class PublicAssociationDeploymentBindingV2(_StrictModel):
    """Externally frozen implementation, protocol, and algorithm contract.

    ``deployment_binding_sha256`` is checked again against an independently
    supplied expected digest by ``PublicTrackAssociatorV2``.  The nested
    protocol therefore cannot be replaced together with a caller-authored
    journal, and the associator source on disk must match the deployment
    manifest before any capture is consumed.
    """

    schema_version: Literal["PublicAssociationDeploymentBindingV2"] = (
        "PublicAssociationDeploymentBindingV2"
    )
    associator_revision: Literal["PublicTrackAssociatorV2"] = PUBLIC_TRACK_ASSOCIATOR_REVISION
    associator_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_source_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol: PublicAssociationProtocolV2
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assignment_objective: Literal[
        "MAXIMUM_CARDINALITY_THEN_MINIMUM_TOTAL_QUANTIZED_COST_THEN_LEXICOGRAPHIC_V2"
    ] = PUBLIC_TRACK_ASSIGNMENT_OBJECTIVE
    association_gate_m: Literal[0.12] = PUBLIC_TRACK_ASSOCIATION_GATE_M
    ambiguity_margin_m: Literal[0.02] = PUBLIC_TRACK_AMBIGUITY_MARGIN_M
    cost_quantum_m: Literal[0.000001] = PUBLIC_TRACK_COST_QUANTUM_M
    max_consecutive_unmatched_captures: Literal[2] = PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES
    max_current_detections: Literal[8] = PUBLIC_TRACK_MAX_CURRENT_DETECTIONS
    deployment_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def deployment_is_self_consistent(self) -> "PublicAssociationDeploymentBindingV2":
        protocol_sha256 = _canonical_sha256(self.protocol.model_dump(mode="json"))
        if self.protocol_sha256 != protocol_sha256:
            raise ValueError("public association deployment protocol digest mismatch")
        expected = _canonical_sha256(
            self.model_dump(mode="json", exclude={"deployment_binding_sha256"})
        )
        if self.deployment_binding_sha256 != expected:
            raise ValueError("public association deployment binding digest mismatch")
        return self


class PublicRobotProprioceptionV2(_StrictModel):
    """One public, time-aligned robot proprioception sample."""

    schema_version: Literal["PublicRobotProprioceptionV2"] = "PublicRobotProprioceptionV2"
    timestamp_ns: int = Field(ge=0)
    world_frame: str = Field(min_length=1)
    end_effector_position_world_m: list[float] = Field(min_length=3, max_length=3)
    end_effector_orientation_world_xyzw: list[float] = Field(
        min_length=4,
        max_length=4,
    )
    gripper_width_m: float = Field(ge=0.0)
    gripper_closed: bool

    @model_validator(mode="after")
    def proprioception_is_finite(self) -> "PublicRobotProprioceptionV2":
        values = [
            *self.end_effector_position_world_m,
            *self.end_effector_orientation_world_xyzw,
            self.gripper_width_m,
        ]
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("public robot proprioception must be finite")
        if (
            math.sqrt(sum(float(value) ** 2 for value in self.end_effector_orientation_world_xyzw))
            == 0.0
        ):
            raise ValueError("end-effector orientation quaternion must be non-zero")
        return self


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _read_implementation_sha256(path: Path) -> str:
    """Hash one immutable regular-file snapshot without following symlinks."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("public association implementation must be a regular file")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("public association implementation changed while being read")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def public_track_associator_implementation_sha256_v2() -> str:
    """Return the running V2 source digest for an external manifest builder."""

    return _read_implementation_sha256(Path(__file__))


def canonical_deployment_binding_sha256_v2(
    binding: PublicAssociationDeploymentBindingV2,
) -> str:
    """Return the canonical digest that an external deployment must freeze."""

    return _canonical_sha256(binding.model_dump(mode="json", exclude={"deployment_binding_sha256"}))


def canonical_session_receipt_sha256_v2(
    receipt: PublicAssociationSessionReceiptV2,
) -> str:
    """Return the canonical digest that the independent host must freeze."""

    return _canonical_sha256(receipt.model_dump(mode="json", exclude={"session_receipt_sha256"}))


class PublicProprioceptionIntervalV2(_StrictModel):
    """Externally scheduled, byte-bound coverage of two public captures.

    The associator does not invent a sampling frequency.  Instead, the trusted
    host freezes the exact expected ordered timestamps for the adjacent
    capture interval and binds the full public sample list by canonical digest.
    This proves complete coverage without turning a capture-provided
    ``interval_complete`` boolean into authority.
    """

    schema_version: Literal["PublicProprioceptionIntervalV2"] = "PublicProprioceptionIntervalV2"
    start_capture_timestamp_ns: int = Field(ge=0)
    end_capture_timestamp_ns: int = Field(ge=0)
    expected_sample_timestamps_ns: list[int] = Field(min_length=1)
    samples: list[PublicRobotProprioceptionV2] = Field(min_length=1)
    samples_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def interval_is_complete_and_bound(self) -> "PublicProprioceptionIntervalV2":
        if self.end_capture_timestamp_ns < self.start_capture_timestamp_ns:
            raise ValueError("public proprioception capture interval is reversed")
        expected = self.expected_sample_timestamps_ns
        if (
            expected[0] != self.start_capture_timestamp_ns
            or expected[-1] != self.end_capture_timestamp_ns
            or any(after <= before for before, after in zip(expected, expected[1:]))
        ):
            raise ValueError("expected public proprioception schedule lacks exact endpoints")
        observed = [sample.timestamp_ns for sample in self.samples]
        if observed != expected:
            raise ValueError("public proprioception samples do not cover the frozen schedule")
        payload = [sample.model_dump(mode="json") for sample in self.samples]
        if self.samples_sha256 != _canonical_sha256(payload):
            raise ValueError("public proprioception sample digest mismatch")
        return self


class PublicProprioceptionCaptureBindingV2(_StrictModel):
    schema_version: Literal["PublicProprioceptionCaptureBindingV2"] = (
        "PublicProprioceptionCaptureBindingV2"
    )
    capture_timestamp_ns: int = Field(ge=0)
    previous_capture_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_sample_timestamps_ns: list[int] = Field(min_length=1)
    samples_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicProprioceptionJournalBindingV2(_StrictModel):
    """Externally frozen authority for the complete capture/proprio journal."""

    schema_version: Literal["PublicProprioceptionJournalBindingV2"] = (
        "PublicProprioceptionJournalBindingV2"
    )
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captures: list[PublicProprioceptionCaptureBindingV2] = Field(min_length=1)
    journal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def journal_is_ordered_chained_and_bound(self) -> "PublicProprioceptionJournalBindingV2":
        for index, item in enumerate(self.captures):
            if index == 0:
                if item.previous_capture_receipt_sha256 is not None:
                    raise ValueError("first public journal capture has a predecessor")
            elif (
                item.previous_capture_receipt_sha256
                != self.captures[index - 1].capture_receipt_sha256
            ):
                raise ValueError("public journal capture receipt chain differs")
            if index and item.capture_timestamp_ns <= self.captures[index - 1].capture_timestamp_ns:
                raise ValueError("public journal capture timestamps are not monotonic")
        if len({item.capture_receipt_sha256 for item in self.captures}) != len(self.captures):
            raise ValueError("public journal repeats a capture receipt")
        expected = _canonical_sha256(self.model_dump(mode="json", exclude={"journal_sha256"}))
        if self.journal_sha256 != expected:
            raise ValueError("public proprioception journal digest mismatch")
        return self


class PublicAssociationSessionReceiptV2(_StrictModel):
    """Independent host receipt binding one capture session to deployment.

    Receipt fields are validation-only.  They are never passed to edge
    construction, hypothesis eligibility, assignment, or ambiguity logic.
    """

    schema_version: Literal["PublicAssociationSessionReceiptV2"] = (
        "PublicAssociationSessionReceiptV2"
    )
    deployment_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_source_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proprioception_journal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capture_count: int = Field(ge=1)
    first_capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def session_receipt_is_bound(self) -> "PublicAssociationSessionReceiptV2":
        expected = _canonical_sha256(
            self.model_dump(mode="json", exclude={"session_receipt_sha256"})
        )
        if self.session_receipt_sha256 != expected:
            raise ValueError("public association session receipt digest mismatch")
        return self


class LastPhysicallyExecutedPublicSkillV2(_StrictModel):
    """Public skill name/times used only for HAND_CARRY eligibility."""

    schema_version: Literal["LastPhysicallyExecutedPublicSkillV2"] = (
        "LastPhysicallyExecutedPublicSkillV2"
    )
    skill_name: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]*$")
    started_at_ns: int = Field(ge=0)
    completed_at_ns: int = Field(ge=0)

    @model_validator(mode="after")
    def times_are_ordered(self) -> "LastPhysicallyExecutedPublicSkillV2":
        if self.completed_at_ns <= self.started_at_ns:
            raise ValueError("physically executed public skill timestamps are not ordered")
        return self


class PublicAssociationCaptureV2(_StrictModel):
    """One complete input to a V2 association step."""

    schema_version: Literal["PublicAssociationCaptureV2"] = "PublicAssociationCaptureV2"
    timestamp_ns: int = Field(ge=0)
    protocol: PublicAssociationProtocolV2
    previous_capture_receipt_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    detections: list[PublicRGBDDetectionV2] = Field(
        max_length=PUBLIC_TRACK_MAX_CURRENT_DETECTIONS,
    )
    proprioception_interval: PublicProprioceptionIntervalV2
    last_physically_executed_public_skill: LastPhysicallyExecutedPublicSkillV2 | None = None
    capture_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def capture_fields_are_aligned(self) -> "PublicAssociationCaptureV2":
        for detection in self.detections:
            if detection.timestamp_ns != self.timestamp_ns:
                raise ValueError("public detection timestamp differs from capture")
            if detection.frame_id != self.protocol.declared_camera_frame:
                raise ValueError("public detection frame differs from declared camera frame")
        interval = self.proprioception_interval
        if interval.end_capture_timestamp_ns != self.timestamp_ns:
            raise ValueError("public proprioception interval does not end at capture")
        if any(
            sample.world_frame != self.protocol.declared_world_frame for sample in interval.samples
        ):
            raise ValueError("public proprioception frame differs from declared world frame")
        skill = self.last_physically_executed_public_skill
        if skill is not None and skill.completed_at_ns > self.timestamp_ns:
            raise ValueError("last public skill completes after the capture")
        expected_receipt = _canonical_sha256(
            self.model_dump(mode="json", exclude={"capture_receipt_sha256"})
        )
        if self.capture_receipt_sha256 != expected_receipt:
            raise ValueError("public association capture receipt SHA-256 mismatch")
        return self


class PublicAssociatedTrackV2(_StrictModel):
    """One current detection with a V2 public identity."""

    schema_version: Literal["PublicAssociatedTrackV2"] = "PublicAssociatedTrackV2"
    associator_revision: Literal["PublicTrackAssociatorV2"] = PUBLIC_TRACK_ASSOCIATOR_REVISION
    track_id: str = Field(pattern=r"^track-[0-9a-f]{8}$")
    timestamp_ns: int = Field(ge=0)
    frame_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    attributes: PublicDetectionAttributesV2
    position_3d: list[float] = Field(min_length=3, max_length=3)
    position_world_m: list[float] = Field(min_length=3, max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_or_mask: PublicBBoxOrMaskV2
    visibility: float = Field(ge=0.0, le=1.0)
    covariance_or_quality: dict[str, float] = Field(default_factory=dict)
    association_hypothesis: Literal["STATIC", "HAND_CARRY", "NEW"]
    association_cost_quantized_m: float | None = Field(default=None, ge=0.0)


@dataclass(frozen=True)
class _TrackState:
    track_id: str
    category: str
    visual_color: str | None
    last_observed_position_world_m: tuple[float, float, float]
    hand_carry_prediction_world_m: tuple[float, float, float] | None
    missed_captures: int


@dataclass(frozen=True)
class _Detection:
    input_index: int
    raw: PublicRGBDDetectionV2
    position_world_m: tuple[float, float, float]

    @property
    def order_key(self) -> tuple[float, float, float, int]:
        return (*self.position_world_m, self.input_index)


@dataclass(frozen=True)
class _Edge:
    prior_track_id: str
    detection_index: int
    cost_quanta: int
    hypothesis: Literal["STATIC", "HAND_CARRY"]


@dataclass(frozen=True)
class _Assignment:
    edges: tuple[_Edge, ...]
    total_cost_quanta: int
    lexicographic_key: tuple[tuple[str, float, float, float], ...]

    @property
    def cardinality(self) -> int:
        return len(self.edges)


class PublicTrackAssociatorV2:
    """Deterministic ADR-0024 public association state machine."""

    def __init__(
        self,
        *,
        expected_deployment: PublicAssociationDeploymentBindingV2,
        expected_deployment_binding_sha256: str,
        expected_journal: PublicProprioceptionJournalBindingV2,
        expected_session_receipt: PublicAssociationSessionReceiptV2,
        expected_session_receipt_sha256: str,
    ) -> None:
        expected_deployment = PublicAssociationDeploymentBindingV2.model_validate(
            expected_deployment.model_dump(mode="json")
            if isinstance(expected_deployment, PublicAssociationDeploymentBindingV2)
            else expected_deployment
        )
        expected_journal = PublicProprioceptionJournalBindingV2.model_validate(
            expected_journal.model_dump(mode="json")
            if isinstance(expected_journal, PublicProprioceptionJournalBindingV2)
            else expected_journal
        )
        expected_session_receipt = PublicAssociationSessionReceiptV2.model_validate(
            expected_session_receipt.model_dump(mode="json")
            if isinstance(expected_session_receipt, PublicAssociationSessionReceiptV2)
            else expected_session_receipt
        )
        if expected_deployment.deployment_binding_sha256 != expected_deployment_binding_sha256:
            raise ValueError("public association deployment differs from external expected digest")
        actual_implementation_sha256 = public_track_associator_implementation_sha256_v2()
        if expected_deployment.associator_implementation_sha256 != actual_implementation_sha256:
            raise ValueError("public association implementation differs from deployment")
        if expected_journal.protocol_sha256 != expected_deployment.protocol_sha256:
            raise ValueError("public proprioception journal binds a different protocol")
        if (
            expected_journal.source_implementation_sha256
            != expected_deployment.capture_source_implementation_sha256
        ):
            raise ValueError("public capture source implementation differs from deployment")
        if expected_session_receipt.session_receipt_sha256 != expected_session_receipt_sha256:
            raise ValueError("public association session differs from external expected digest")
        first_capture = expected_journal.captures[0]
        final_capture = expected_journal.captures[-1]
        expected_session_fields = (
            expected_deployment.deployment_binding_sha256,
            expected_deployment.capture_source_implementation_sha256,
            expected_journal.journal_sha256,
            len(expected_journal.captures),
            first_capture.capture_receipt_sha256,
            final_capture.capture_receipt_sha256,
        )
        actual_session_fields = (
            expected_session_receipt.deployment_binding_sha256,
            expected_session_receipt.capture_source_implementation_sha256,
            expected_session_receipt.proprioception_journal_sha256,
            expected_session_receipt.capture_count,
            expected_session_receipt.first_capture_receipt_sha256,
            expected_session_receipt.final_capture_receipt_sha256,
        )
        if actual_session_fields != expected_session_fields:
            raise ValueError("public association session receipt does not bind frozen journal")
        self._tracks: dict[str, _TrackState] = {}
        self._protocol = expected_deployment.protocol
        self._expected_journal = expected_journal
        self._journal_position = 0
        self._last_capture_timestamp_ns: int | None = None
        self._last_capture_receipt_sha256: str | None = None
        self._last_end_effector_position_world_m: tuple[float, float, float] | None = None
        self._next_track_index = 0
        self._lock = threading.RLock()

    @property
    def active_track_ids(self) -> tuple[str, ...]:
        """Return retained IDs for local diagnostics, never as observations."""

        with self._lock:
            return tuple(sorted(self._tracks))

    @property
    def journal_complete(self) -> bool:
        with self._lock:
            return self._journal_position == len(self._expected_journal.captures)

    def associate(
        self,
        capture: PublicAssociationCaptureV2,
    ) -> list[PublicAssociatedTrackV2]:
        """Associate one capture and return current detections only.

        The assignment objective is maximum admissible cardinality followed by
        minimum quantized total cost.  Maximum cardinality is the conventional
        fail-closed completion of a one-to-one assignment with unmatched
        tracks/detections; without it, a zero-edge assignment would always
        minimize cost.  ADR-0024's complete lexicographic tie-break is then
        applied to equal-cardinality, equal-cost assignments.
        """

        if not isinstance(capture, PublicAssociationCaptureV2):
            capture = PublicAssociationCaptureV2.model_validate(capture)
        with self._lock:
            return self._associate_locked(capture)

    def _associate_locked(
        self,
        capture: PublicAssociationCaptureV2,
    ) -> list[PublicAssociatedTrackV2]:
        previous_timestamp = self._last_capture_timestamp_ns
        if self._journal_position >= len(self._expected_journal.captures):
            raise ValueError("public association capture exceeds frozen journal")
        expected_capture = self._expected_journal.captures[self._journal_position]
        interval = capture.proprioception_interval
        actual_binding = PublicProprioceptionCaptureBindingV2(
            capture_timestamp_ns=capture.timestamp_ns,
            previous_capture_receipt_sha256=capture.previous_capture_receipt_sha256,
            capture_receipt_sha256=capture.capture_receipt_sha256,
            expected_sample_timestamps_ns=interval.expected_sample_timestamps_ns,
            samples_sha256=interval.samples_sha256,
        )
        if actual_binding != expected_capture:
            raise ValueError("public capture differs from external proprioception journal")
        if previous_timestamp is not None and capture.timestamp_ns <= previous_timestamp:
            raise ValueError("public association capture timestamp must be strictly monotonic")
        if capture.protocol != self._protocol:
            raise ValueError("public association frame/unit/calibration binding changed")

        first_capture = previous_timestamp is None
        if first_capture:
            if (
                capture.previous_capture_receipt_sha256 is not None
                or capture.proprioception_interval.start_capture_timestamp_ns
                != capture.timestamp_ns
                or len(capture.proprioception_interval.samples) != 1
            ):
                raise ValueError("first association capture requires one aligned proprio sample")
        elif (
            capture.previous_capture_receipt_sha256 != self._last_capture_receipt_sha256
            or capture.proprioception_interval.start_capture_timestamp_ns != previous_timestamp
        ):
            raise ValueError("public capture/proprioception interval is not chained")

        skill = capture.last_physically_executed_public_skill
        if (
            skill is not None
            and previous_timestamp is not None
            and skill.started_at_ns < previous_timestamp
        ):
            raise ValueError("last public skill is outside the adjacent capture interval")

        current_ee = tuple(
            float(value)
            for value in capture.proprioception_interval.samples[-1].end_effector_position_world_m
        )
        displacement = (0.0, 0.0, 0.0)
        if self._last_end_effector_position_world_m is not None:
            displacement = tuple(
                after - before
                for before, after in zip(
                    self._last_end_effector_position_world_m,
                    current_ee,
                )
            )
        hand_carry_interval_eligible = bool(
            not first_capture
            and skill is not None
            and skill.skill_name in PUBLIC_TRACK_HAND_CARRY_SKILLS
            and all(sample.gripper_closed for sample in capture.proprioception_interval.samples)
        )

        detections = tuple(
            _Detection(
                input_index=index,
                raw=raw,
                position_world_m=_camera_to_world(
                    capture.protocol.camera_to_world_row_major,
                    raw.position_3d,
                ),
            )
            for index, raw in enumerate(capture.detections)
        )
        edges, carried_predictions = self._build_edges(
            detections,
            displacement=displacement,
            hand_carry_interval_eligible=hand_carry_interval_eligible,
        )
        assignment = _solve_assignment(
            priors=tuple(sorted(self._tracks)),
            detections=detections,
            edges=edges,
        )
        ambiguous_detection_indices = _ambiguous_detections(
            assignment=assignment,
            priors=tuple(sorted(self._tracks)),
            detections=detections,
            edges=edges,
        )
        selected_by_detection = {
            edge.detection_index: edge
            for edge in assignment.edges
            if edge.detection_index not in ambiguous_detection_indices
        }

        next_track_index = self._next_track_index
        occupied_ids = set(self._tracks)
        current_states: dict[str, _TrackState] = {}
        outputs_by_index: dict[int, PublicAssociatedTrackV2] = {}
        matched_prior_ids: set[str] = set()

        for detection in sorted(detections, key=lambda item: item.order_key):
            edge = selected_by_detection.get(detection.input_index)
            if edge is None:
                track_id, next_track_index = _new_track_id(
                    next_track_index=next_track_index,
                    occupied_ids=occupied_ids | set(current_states),
                    detection=detection,
                    timestamp_ns=capture.timestamp_ns,
                )
                hypothesis: Literal["STATIC", "HAND_CARRY", "NEW"] = "NEW"
                cost_m = None
            else:
                track_id = edge.prior_track_id
                matched_prior_ids.add(track_id)
                hypothesis = edge.hypothesis
                cost_m = edge.cost_quanta / _COST_QUANTA_PER_METRE
            current_states[track_id] = _TrackState(
                track_id=track_id,
                category=detection.raw.category,
                visual_color=detection.raw.attributes.visual_color,
                last_observed_position_world_m=detection.position_world_m,
                hand_carry_prediction_world_m=detection.position_world_m,
                missed_captures=0,
            )
            outputs_by_index[detection.input_index] = PublicAssociatedTrackV2(
                track_id=track_id,
                timestamp_ns=detection.raw.timestamp_ns,
                frame_id=detection.raw.frame_id,
                category=detection.raw.category,
                attributes=detection.raw.attributes,
                position_3d=detection.raw.position_3d,
                position_world_m=list(detection.position_world_m),
                confidence=detection.raw.confidence,
                bbox_or_mask=detection.raw.bbox_or_mask,
                visibility=detection.raw.visibility,
                covariance_or_quality=detection.raw.covariance_or_quality,
                association_hypothesis=hypothesis,
                association_cost_quantized_m=cost_m,
            )

        retained_states: dict[str, _TrackState] = {}
        for track_id, prior in self._tracks.items():
            if track_id in matched_prior_ids:
                continue
            missed = prior.missed_captures + 1
            if missed >= PUBLIC_TRACK_MAX_CONSECUTIVE_UNMATCHED_CAPTURES:
                continue
            retained_states[track_id] = _TrackState(
                track_id=track_id,
                category=prior.category,
                visual_color=prior.visual_color,
                last_observed_position_world_m=prior.last_observed_position_world_m,
                hand_carry_prediction_world_m=carried_predictions.get(track_id),
                missed_captures=missed,
            )

        overlap = set(retained_states) & set(current_states)
        if overlap:  # pragma: no cover - protected by matching/allocation invariants
            raise AssertionError(f"public track state collision: {sorted(overlap)}")
        self._tracks = {**retained_states, **current_states}
        self._last_capture_timestamp_ns = capture.timestamp_ns
        self._last_capture_receipt_sha256 = capture.capture_receipt_sha256
        self._last_end_effector_position_world_m = current_ee
        self._next_track_index = next_track_index
        self._journal_position += 1
        return [outputs_by_index[index] for index in range(len(detections))]

    def _build_edges(
        self,
        detections: Sequence[_Detection],
        *,
        displacement: tuple[float, float, float],
        hand_carry_interval_eligible: bool,
    ) -> tuple[dict[tuple[str, int], _Edge], dict[str, tuple[float, float, float] | None]]:
        edges: dict[tuple[str, int], _Edge] = {}
        carried_predictions: dict[str, tuple[float, float, float] | None] = {}
        for track_id, prior in self._tracks.items():
            carried: tuple[float, float, float] | None = None
            if hand_carry_interval_eligible and prior.hand_carry_prediction_world_m is not None:
                carried = tuple(
                    value + delta
                    for value, delta in zip(
                        prior.hand_carry_prediction_world_m,
                        displacement,
                    )
                )
            carried_predictions[track_id] = carried
            hypotheses: list[tuple[Literal["STATIC", "HAND_CARRY"], tuple[float, float, float]]] = [
                ("STATIC", prior.last_observed_position_world_m)
            ]
            if carried is not None:
                hypotheses.append(("HAND_CARRY", carried))
            for detection in detections:
                if (
                    detection.raw.category != prior.category
                    or detection.raw.attributes.visual_color != prior.visual_color
                ):
                    continue
                eligible = [
                    (_quantized_distance(predicted, detection.position_world_m), name)
                    for name, predicted in hypotheses
                    if math.dist(predicted, detection.position_world_m)
                    <= PUBLIC_TRACK_ASSOCIATION_GATE_M
                ]
                if not eligible:
                    continue
                cost, hypothesis = min(
                    eligible,
                    key=lambda value: (value[0], 0 if value[1] == "STATIC" else 1),
                )
                if cost > _ASSOCIATION_GATE_QUANTA:
                    continue
                edges[(track_id, detection.input_index)] = _Edge(
                    prior_track_id=track_id,
                    detection_index=detection.input_index,
                    cost_quanta=cost,
                    hypothesis=hypothesis,
                )
        return edges, carried_predictions


def _camera_to_world(
    transform: Sequence[float],
    position_3d: Sequence[float],
) -> tuple[float, float, float]:
    x, y, z = (float(value) for value in position_3d)
    output = (
        transform[0] * x + transform[1] * y + transform[2] * z + transform[3],
        transform[4] * x + transform[5] * y + transform[6] * z + transform[7],
        transform[8] * x + transform[9] * y + transform[10] * z + transform[11],
    )
    if not all(math.isfinite(value) for value in output):
        raise ValueError("camera-to-world public detection position is non-finite")
    return output


def _quantized_distance(
    left: Sequence[float],
    right: Sequence[float],
) -> int:
    # Python's round is deterministic round-half-to-even; the integer is the
    # canonical 1e-6 m representation used for all cost comparisons.
    return int(round(math.dist(left, right) * _COST_QUANTA_PER_METRE))


def _assignment_key(
    edges: Sequence[_Edge],
    detections_by_index: dict[int, _Detection],
) -> tuple[tuple[str, float, float, float], ...]:
    return tuple(
        (
            edge.prior_track_id,
            *detections_by_index[edge.detection_index].position_world_m,
        )
        for edge in sorted(edges, key=lambda item: item.prior_track_id)
    )


def _solve_assignment(
    *,
    priors: tuple[str, ...],
    detections: Sequence[_Detection],
    edges: dict[tuple[str, int], _Edge],
    forbidden_edge: tuple[str, int] | None = None,
) -> _Assignment:
    ordered_detections = tuple(sorted(detections, key=lambda item: item.order_key))
    detection_bit = {
        detection.input_index: 1 << position
        for position, detection in enumerate(ordered_detections)
    }
    by_index = {detection.input_index: detection for detection in detections}
    memo: dict[tuple[int, int], _Assignment] = {}

    def better(left: _Assignment, right: _Assignment) -> _Assignment:
        left_key = (-left.cardinality, left.total_cost_quanta, left.lexicographic_key)
        right_key = (-right.cardinality, right.total_cost_quanta, right.lexicographic_key)
        return left if left_key < right_key else right

    def visit(prior_position: int, used_mask: int) -> _Assignment:
        memo_key = (prior_position, used_mask)
        if memo_key in memo:
            return memo[memo_key]
        if prior_position == len(priors):
            result = _Assignment(edges=(), total_cost_quanta=0, lexicographic_key=())
            memo[memo_key] = result
            return result
        prior_id = priors[prior_position]
        best = visit(prior_position + 1, used_mask)
        options = sorted(
            (
                edge
                for (candidate_prior, _), edge in edges.items()
                if candidate_prior == prior_id
                and edge.detection_index in detection_bit
                and (candidate_prior, edge.detection_index) != forbidden_edge
            ),
            key=lambda edge: by_index[edge.detection_index].order_key,
        )
        for edge in options:
            bit = detection_bit[edge.detection_index]
            if used_mask & bit:
                continue
            suffix = visit(prior_position + 1, used_mask | bit)
            combined_edges = (edge, *suffix.edges)
            candidate = _Assignment(
                edges=combined_edges,
                total_cost_quanta=edge.cost_quanta + suffix.total_cost_quanta,
                lexicographic_key=_assignment_key(combined_edges, by_index),
            )
            best = better(best, candidate)
        memo[memo_key] = best
        return best

    return visit(0, 0)


def _ambiguous_detections(
    *,
    assignment: _Assignment,
    priors: tuple[str, ...],
    detections: Sequence[_Detection],
    edges: dict[tuple[str, int], _Edge],
) -> set[int]:
    """Reject any global identity alternative within the frozen margin.

    Each selected identity edge is forbidden in turn and the complete global
    assignment is solved again.  This enumerates both ways an identity can
    change: another prior can take the same detection, or the same prior can
    take another detection.  If the best same-cardinality alternative is
    within the strict 0.02 m margin, every detection whose assigned identity
    changes between the two global assignments is implicated and receives no
    prior ID.
    """

    ambiguous: set[int] = set()
    for selected in assignment.edges:
        alternative = _solve_assignment(
            priors=priors,
            detections=detections,
            edges=edges,
            forbidden_edge=(selected.prior_track_id, selected.detection_index),
        )
        if alternative.cardinality != assignment.cardinality:
            continue
        if alternative.total_cost_quanta - assignment.total_cost_quanta >= _AMBIGUITY_MARGIN_QUANTA:
            continue
        selected_identity_by_detection = {
            edge.detection_index: edge.prior_track_id for edge in assignment.edges
        }
        alternative_identity_by_detection = {
            edge.detection_index: edge.prior_track_id for edge in alternative.edges
        }
        ambiguous.update(
            detection_index
            for detection_index in (
                selected_identity_by_detection.keys() | alternative_identity_by_detection.keys()
            )
            if selected_identity_by_detection.get(detection_index)
            != alternative_identity_by_detection.get(detection_index)
        )
    return ambiguous


def _new_track_id(
    *,
    next_track_index: int,
    occupied_ids: set[str],
    detection: _Detection,
    timestamp_ns: int,
) -> tuple[str, int]:
    while True:
        next_track_index += 1
        identity_payload = {
            "associator_revision": PUBLIC_TRACK_ASSOCIATOR_REVISION,
            "allocation_index": next_track_index,
            "timestamp_ns": timestamp_ns,
            "category": detection.raw.category,
            "visual_color": detection.raw.attributes.visual_color,
            "position_world_quanta": [
                int(round(value * _COST_QUANTA_PER_METRE)) for value in detection.position_world_m
            ],
        }
        wire = json.dumps(
            identity_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        track_id = "track-" + hashlib.sha256(wire).hexdigest()[:8]
        if track_id not in occupied_ids:
            return track_id, next_track_index
