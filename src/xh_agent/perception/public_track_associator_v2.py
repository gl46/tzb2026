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


@dataclass(frozen=True)
class _ForcedIdentityAssignment:
    """Best assignment under one required detection/prior identity."""

    assignment: _Assignment
    forced_edge: _Edge


class PublicTrackAssociatorV2:
    """Deterministic ADR-0024 public association state machine."""

    def __init__(
        self,
        *,
        expected_protocol: PublicAssociationProtocolV2,
        expected_journal: PublicProprioceptionJournalBindingV2,
    ) -> None:
        if not isinstance(expected_protocol, PublicAssociationProtocolV2):
            expected_protocol = PublicAssociationProtocolV2.model_validate(expected_protocol)
        if not isinstance(expected_journal, PublicProprioceptionJournalBindingV2):
            expected_journal = PublicProprioceptionJournalBindingV2.model_validate(expected_journal)
        protocol_sha256 = _canonical_sha256(expected_protocol.model_dump(mode="json"))
        if expected_journal.protocol_sha256 != protocol_sha256:
            raise ValueError("public proprioception journal binds a different protocol")
        self._tracks: dict[str, _TrackState] = {}
        self._protocol = expected_protocol
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


def _solve_assignment_forced_identity(
    *,
    priors: tuple[str, ...],
    detections: Sequence[_Detection],
    edges: dict[tuple[str, int], _Edge],
    prior_track_id: str,
    detection_index: int,
) -> _ForcedIdentityAssignment | None:
    forced_edge = edges.get((prior_track_id, detection_index))
    if forced_edge is None:
        return None
    remaining_priors = tuple(item for item in priors if item != prior_track_id)
    remaining_detections = tuple(item for item in detections if item.input_index != detection_index)
    suffix = _solve_assignment(
        priors=remaining_priors,
        detections=remaining_detections,
        edges=edges,
    )
    combined_edges = (forced_edge, *suffix.edges)
    by_index = {item.input_index: item for item in detections}
    return _ForcedIdentityAssignment(
        forced_edge=forced_edge,
        assignment=_Assignment(
            edges=combined_edges,
            total_cost_quanta=forced_edge.cost_quanta + suffix.total_cost_quanta,
            lexicographic_key=_assignment_key(combined_edges, by_index),
        ),
    )


def _ambiguous_detections(
    *,
    assignment: _Assignment,
    priors: tuple[str, ...],
    detections: Sequence[_Detection],
    edges: dict[tuple[str, int], _Edge],
) -> set[int]:
    """Reject any global identity alternative within the frozen margin.

    For each selected detection, every other admissible prior identity is
    forced in turn and the best remaining one-to-one assignment is solved.  A
    same-cardinality alternative whose global total cost differs by less than
    0.02 m makes that detection ambiguous.  The comparison is per detection as
    ADR-0024 specifies, but both the selected and forced-alternative values are
    complete global assignment costs.
    """

    ambiguous: set[int] = set()
    for selected in assignment.edges:
        for alternative_prior in priors:
            if alternative_prior == selected.prior_track_id:
                continue
            forced = _solve_assignment_forced_identity(
                priors=priors,
                detections=detections,
                edges=edges,
                prior_track_id=alternative_prior,
                detection_index=selected.detection_index,
            )
            if forced is None or forced.assignment.cardinality != assignment.cardinality:
                continue
            if (
                abs(forced.assignment.total_cost_quanta - assignment.total_cost_quanta)
                < _AMBIGUITY_MARGIN_QUANTA
            ):
                ambiguous.add(selected.detection_index)
                break
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
