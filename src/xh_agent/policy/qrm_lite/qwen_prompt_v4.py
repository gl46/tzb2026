"""One shared public-only prompt renderer for M2C_Q012_V4."""

from __future__ import annotations

import json
from typing import Sequence

from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
    prompt_executed_intent_history_v2,
)
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    M2C_Q012_V4_SKILL_LABELS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
    POINTER_CLASS_LABELS,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v4 import (
    PublicTrackCandidatePayloadV4,
)


def render_qwen_public_prompt_v4(
    *,
    candidate_payload: PublicTrackCandidatePayloadV4,
    decision_index: int,
    executed_intent_history: Sequence[PublicExecutedIntentHistoryItemV2],
    use_failure_context: bool,
) -> str:
    """Render the exact train/runtime prompt from replayed public inputs."""

    candidate_payload = PublicTrackCandidatePayloadV4.model_validate(
        candidate_payload.model_dump(mode="json")
        if isinstance(candidate_payload, PublicTrackCandidatePayloadV4)
        else candidate_payload
    )
    if not 0 <= decision_index <= 7:
        raise ValueError("V4 prompt decision index is outside 0..7")
    payload = {
        "task": "recover from a public PATH_BLOCKED manipulation failure",
        "public_observation_revision": "PathBlockedPublicObservationV4",
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "canonical_public_track_candidates_k8": candidate_payload.model_dump(mode="json"),
        "failure_context": {"failure_type": "PATH_BLOCKED" if use_failure_context else "MASKED"},
        "public_executed_intent_history": prompt_executed_intent_history_v2(
            executed_intent_history,
            expected_length=decision_index,
        ),
        "allowed_skills": list(M2C_Q012_V4_SKILL_LABELS),
        "allowed_pointer_classes": list(POINTER_CLASS_LABELS),
        "allowed_destinations": list(DESTINATION_CLASS_LABELS),
    }
    return (
        "Select one CoarseIntentV2 skill, one literal V4 K=8 public-track pointer "
        "(or NONE), and one registered destination cell (or NONE). Continuous "
        "coordinates, TaskSpec target identity, Teacher output, and simulator truth "
        "are unavailable. Context:\n" + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
