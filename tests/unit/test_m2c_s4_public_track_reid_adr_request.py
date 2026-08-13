from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
REQUEST = ROOT / "docs/decisions/M2C-S4-PUBLIC-TRACK-REID-ADR-REQUEST.md"
PROBE_SHA256 = "f190bb44c1533ec4b4a37cbaf84955485fee073ee91e0f9d112a1b8009a057cb"
# Filled after the request bytes are finalized. This locks prose outside the
# machine-readable evidence block as well as the block itself.
REQUEST_SHA256 = "3ac9d5e30e9529df6e12d9914fa31b67243cd90ea490d5e3043d34f3260dfd59"


def _text() -> str:
    return REQUEST.read_text(encoding="utf-8")


def _payload() -> dict[str, object]:
    matches = re.findall(r"```json\n(.*?)\n```", _text(), re.DOTALL)
    assert len(matches) == 1
    payload = json.loads(matches[0])
    assert isinstance(payload, dict)
    return payload


def test_entire_request_bytes_are_frozen() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", REQUEST_SHA256)
    assert hashlib.sha256(REQUEST.read_bytes()).hexdigest() == REQUEST_SHA256


def test_probe_binding_and_post_outcome_arithmetic_are_exact() -> None:
    payload = _payload()
    assert payload["schema_version"] == "M2CS4PublicTrackReidADRRequestEvidenceV1"
    assert payload["timing"] == "POST_OUTCOME"
    assert payload["outcome_observed_before_request"] is True
    assert payload["scene_seed"] == 16073
    assert payload["probe"] == {
        "relative_evidence_path": (
            "batch03-01/train/"
            "m2c-s4-v3-train-a101b1d9d220dfd6f293d1eab337e412b29b48a61759b5baef1ef8b2ad6ba5d2/"
            "probe/actuation-probe.json"
        ),
        "sha256": PROBE_SHA256,
    }

    positions = payload["public_track_positions_world_m"]
    diagnostics = payload["association_diagnostics_m"]
    step_05 = positions["step_05_predicate_reference_track_e91f94dc"]
    step_07 = positions["step_07_pre_lift_track_e91f94dc"]
    original_site = positions["after_lift_original_site_detection_track_e91f94dc"]
    carried = positions["after_lift_carried_detection_track_e4beb00e"]
    assert math.dist(step_07, original_site) == diagnostics["step_07_to_original_site_detection"]
    assert math.dist(step_07, carried) == diagnostics["step_07_to_carried_detection"]

    tracker = payload["tracker_v1"]
    assert tracker == {
        "source_component": "public_temporal_tracker_v1",
        "maximum_association_distance_m": 0.12,
        "matching_fields": ["category", "visual_color", "position_3d"],
    }
    assert (
        diagnostics["step_07_to_original_site_detection"]
        < tracker["maximum_association_distance_m"]
    )
    assert diagnostics["step_07_to_carried_detection"] > tracker["maximum_association_distance_m"]

    predicate = payload["frozen_public_predicate"]
    assert math.dist(step_05, original_site) == predicate["step_05_to_original_site_detection_m"]
    assert (
        predicate["step_05_to_original_site_detection_m"]
        < predicate["maximum_original_site_motion_m"]
    )
    assert predicate["hand_vertical_lift_m"] == 0.16424095630645752
    assert predicate["target_hand_xy_error_m"] == 0.034575710801854835
    assert predicate["predicates"] == []
    assert predicate["final_task_success"] is False
    assert payload["physical_receipt"] == {
        "status": "LIFTED",
        "object_lift_m": 0.16423627734184265,
        "follow_error_m": 0.004680934429056637,
    }


def test_request_is_not_approval_and_authorizes_nothing() -> None:
    text = _text()
    payload = _payload()
    assert "HUMAN DECISION REQUIRED — NOT APPROVED" in text
    assert "Timing disclosure: **POST-OUTCOME**" in text
    assert "Decision recorded by this request: **NONE**" in text
    assert payload["authorization"] == {
        "approved_adr": False,
        "code_change": False,
        "collection": False,
        "training": False,
        "smoke": False,
        "model_rollout": False,
        "q_b_evaluation": False,
        "physical_execution": False,
        "reinterpret_existing_evidence": False,
    }
    assert "Authorization for new TRAIN collection: `NO`" in text
    assert "Authorization for training: `NO`" in text
    assert "Authorization for SMOKE/model rollout/Q-B evaluation: `NO`" in text
    assert "Accepted ADR path/commit: `NONE`" in text


def test_options_are_exactly_mutually_exclusive_a_b_c() -> None:
    text = _text()
    headings = re.findall(r"^### ([A-Z]) — (.+)$", text, re.MULTILINE)
    assert [letter for letter, _ in headings] == ["A", "B", "C"]
    assert headings[0][1] == (
        "PublicTrackAssociatorV2 with public-only motion association (recommended)"
    )
    assert headings[1][1] == "no tracker change; stop PATH_BLOCKED collection"
    assert headings[2][1] == "another explicit human choice"
    assert "The approver must select exactly one of A, B, or C." in text
    assert "Selected option: `NONE` (`A | B | C`, exactly one required)" in text


def test_option_a_is_public_only_fail_closed_and_revision_isolated() -> None:
    text = _text()
    normalized_text = " ".join(text.split())
    required_allowed_fields = (
        "timestamp_ns",
        "frame_id",
        "track_id",
        "category",
        "attributes.visual_color",
        "position_3d",
        "confidence",
        "bbox_or_mask",
        "visibility",
        "covariance_or_quality",
        "end-effector position and orientation",
        "gripper width/closed state",
    )
    for field in required_allowed_fields:
        assert field in text

    required_forbidden_fields = (
        "entity or prim IDs",
        "attached-entity IDs",
        "simulator object poses",
        "semantic or instance render truth",
        "contact-entity identity",
        "task_target_track_id",
        "Teacher output",
        "scene seed",
        "matched-key outcome",
    )
    for field in required_forbidden_fields:
        assert field in normalized_text

    for contract in (
        "strict timestamp monotonicity",
        "deterministic one-to-one global matching",
        "explicit ambiguity margin",
        "downstream stale-pointer handling remains fail-closed",
        "PublicTrackAssociatorV2",
        "PathBlockedPublicObservationV4",
        "PublicTrackCandidateV4",
        "M2C_Q012_V4",
        "outcome-blind preregistration of wholly new TRAIN keys",
    ):
        assert contract in text


def test_old_evidence_thresholds_and_teacher_boundary_cannot_be_reinterpreted() -> None:
    text = _text()
    assert "Do not change, tune, or reinterpret the V1 0.12 m association gate" in text
    assert "frozen 0.03 m original-site predicate gate" in text
    assert "Do not relabel e4beb00e as e91f94dc in the old capture" in text
    assert "backfill scene16073 as eligible or\n  successful" in text
    assert "No simulator/Isaac entity or prim identity" in text
    assert "Teacher kill rules: not triggered" in text
    assert "no Teacher was used or proposed" in text
