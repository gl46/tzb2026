from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.contracts import CoarseIntentV1, CoarseIntentV2


ROOT = Path(__file__).parents[2]


def test_coarse_intent_v2_round_trip_preserves_v1_fields_and_destination() -> None:
    intent = CoarseIntentV2(
        skill_type="MOVE",
        target_track_id="public-blocker-track",
        grasp_family="top_down",
        recovery_mode="path_blocked",
        destination_cell="BIN_CELL_3",
    )
    restored = CoarseIntentV2.model_validate_json(intent.model_dump_json())
    assert restored == intent
    assert restored.schema_version == "CoarseIntentV2"
    assert restored.destination_cell == "BIN_CELL_3"


def test_v2_rejects_free_form_destination_and_v1_remains_exact() -> None:
    with pytest.raises(ValidationError):
        CoarseIntentV2(skill_type="MOVE", destination_cell="0.2,0.1,0.3")
    with pytest.raises(ValidationError):
        CoarseIntentV1.model_validate(
            {"skill_type": "MOVE", "destination_cell": "BIN_CELL_3"}
        )


def test_coarse_intent_v2_json_schema_round_trip() -> None:
    schema = CoarseIntentV2.model_json_schema()
    assert schema == json.loads(
        (ROOT / "schemas/coarse-intent-v2.schema.json").read_text()
    )
    assert schema["properties"]["schema_version"]["const"] == "CoarseIntentV2"
    destination_schema = json.dumps(schema["properties"]["destination_cell"])
    for index in range(6):
        assert f"BIN_CELL_{index}" in destination_schema
    assert "BIN_CELL_6" not in destination_schema
