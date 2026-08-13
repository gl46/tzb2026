from __future__ import annotations

import copy
import hashlib
import io

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from test_m2c_path_blocked_supervision_v4 import observation_bundle
from xh_agent.policy.qrm_lite.formal_public_observation_v4 import (
    FormalPublicObservationV4,
    formal_public_capture_receipt_v4,
    load_formal_public_observation_v4,
    public_asset_inline_v4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PathBlockedPublicObservationV4,
)


def _rgb() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 255, 0)).save(stream, format="PNG")
    return stream.getvalue()


def _depth() -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.ones((2, 2), dtype=np.float32), allow_pickle=False)
    return stream.getvalue()


def _formal() -> FormalPublicObservationV4:
    payload, deployment, journal, session, attribute = observation_bundle()
    rgb = _rgb()
    depth = _depth()
    payload["rgb_sha256"] = hashlib.sha256(rgb).hexdigest()
    payload["depth_sha256"] = hashlib.sha256(depth).hexdigest()
    observation = PathBlockedPublicObservationV4.model_validate(payload)
    candidate_ids = [item.track_id for item in observation.candidate_payload.candidates]
    formal = FormalPublicObservationV4(
        observation=observation,
        previous_physical_completed_at_ns=50,
        rgb=public_asset_inline_v4(
            uri=observation.rgb_uri,
            sha256=observation.rgb_sha256,
            media_type="image/png",
            data=rgb,
        ),
        depth=public_asset_inline_v4(
            uri=observation.depth_uri,
            sha256=observation.depth_sha256,
            media_type="application/x-npy",
            data=depth,
        ),
        canonical_slots=[*candidate_ids, *([None] * (8 - len(candidate_ids)))],
        association_deployment=deployment,
        association_deployment_sha256=deployment.deployment_binding_sha256,
        proprioception_journal=journal,
        proprioception_journal_sha256=journal.journal_sha256,
        association_session_receipt=session,
        association_session_receipt_sha256=session.session_receipt_sha256,
        declared_attribute_binding=attribute,
        declared_attribute_binding_sha256=attribute.binding_sha256,
        formal_capture_receipt=formal_public_capture_receipt_v4(
            observation=observation,
            association_deployment_sha256=deployment.deployment_binding_sha256,
            proprioception_journal_sha256=journal.journal_sha256,
            association_session_receipt_sha256=session.session_receipt_sha256,
            declared_attribute_binding_sha256=attribute.binding_sha256,
        ),
    )
    return load_formal_public_observation_v4(
        formal.model_dump(mode="json"),
        expected_association_deployment_sha256=deployment.deployment_binding_sha256,
    )


def test_formal_v4_replays_all_public_inputs_and_exposes_exact_a1_digest() -> None:
    formal = _formal()

    assert formal.observation_id == "fresh-v4-observation"
    assert formal.captured_at_ns == 200
    assert formal.association_capture_receipt_sha256 == formal.observation.capture_receipt_sha256
    assert formal.capture_receipt_sha256 == formal.formal_capture_receipt.receipt_sha256
    assert formal.canonical_public_tracks_sha256 == formal.observation.candidate_payload_sha256
    assert formal.canonical_slots[:2] == [
        item.track_id for item in formal.observation.candidate_payload.candidates
    ]
    assert len(formal.wire_sha256) == 64
    assert formal.teacher_used is False
    assert formal.privileged_truth_policy_input is False


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("previous_physical_completed_at_ns", 200, "not newer"),
        ("association_deployment_sha256", "f" * 64, "deployment digest"),
        ("proprioception_journal_sha256", "f" * 64, "journal digest"),
        ("association_session_receipt_sha256", "f" * 64, "session receipt digest"),
        ("declared_attribute_binding_sha256", "f" * 64, "attribute binding digest"),
    ],
)
def test_formal_v4_rejects_external_binding_or_freshness_tamper(
    field: str,
    value: object,
    error: str,
) -> None:
    payload = _formal().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match=error):
        FormalPublicObservationV4.model_validate(payload)


def test_formal_v4_rejects_asset_or_candidate_slot_splice() -> None:
    formal = _formal()

    payload = formal.model_dump(mode="json")
    payload["rgb"]["uri"] = "dataset://policy/rgb/other.png"
    with pytest.raises(ValidationError, match="RGB transport differs"):
        FormalPublicObservationV4.model_validate(payload)

    payload = formal.model_dump(mode="json")
    payload["canonical_slots"][0], payload["canonical_slots"][1] = (
        payload["canonical_slots"][1],
        payload["canonical_slots"][0],
    )
    with pytest.raises(ValidationError, match="K=8 slots differ"):
        FormalPublicObservationV4.model_validate(payload)

    payload = formal.model_dump(mode="json")
    payload["formal_capture_receipt"]["rgb_sha256"] = "f" * 64
    payload["formal_capture_receipt"]["receipt_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in payload["formal_capture_receipt"].items()
            if key != "receipt_sha256"
        }
    )
    with pytest.raises(ValidationError, match="whole-capture receipt crosses"):
        FormalPublicObservationV4.model_validate(payload)


def test_formal_v4_rejects_rehashed_association_history_tamper() -> None:
    formal = _formal()
    payload = formal.model_dump(mode="json")
    tampered = copy.deepcopy(payload)
    tampered["observation"]["association_history"][0]["associated_tracks"][0]["confidence"] = 0.1
    tracks = tampered["observation"]["association_history"][0]["associated_tracks"]
    tampered["observation"]["association_history"][0]["associated_tracks_sha256"] = (
        canonical_sha256(tracks)
    )
    with pytest.raises(ValidationError, match="association replay differs"):
        FormalPublicObservationV4.model_validate(tampered)


def test_formal_v4_asset_builder_rejects_unbound_bytes() -> None:
    with pytest.raises(ValueError, match="asset bytes differ"):
        public_asset_inline_v4(
            uri="dataset://policy/rgb/0001.png",
            sha256="0" * 64,
            media_type="image/png",
            data=_rgb(),
        )


def test_formal_v4_loader_requires_external_endpoint_deployment_digest() -> None:
    formal = _formal()
    with pytest.raises(ValueError, match="expected endpoint deployment"):
        load_formal_public_observation_v4(
            formal.model_dump(mode="json"),
            expected_association_deployment_sha256="f" * 64,
        )
