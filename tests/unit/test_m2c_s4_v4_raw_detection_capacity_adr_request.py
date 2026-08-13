from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUEST = ROOT / "docs/decisions/M2C-S4-V4-RAW-DETECTION-CAPACITY-ADR-REQUEST.md"
REPORT = ROOT / "reports/m2c-s4-v4-batch08-collection.json"
DETECTOR = ROOT / "src/xh_agent/perception/geometric_rgbd.py"


def _text() -> str:
    return REQUEST.read_text(encoding="utf-8")


def _evidence() -> dict[str, object]:
    blocks = re.findall(r"```json\n(.*?)\n```", _text(), re.DOTALL)
    assert len(blocks) == 1
    payload = json.loads(blocks[0])
    assert isinstance(payload, dict)
    return payload


def test_request_is_post_outcome_and_does_not_authorize_a_schema_change() -> None:
    text = _text()
    payload = _evidence()
    assert "POST-OUTCOME / NOT APPROVED" in text
    assert "REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR" in text
    assert "Decision recorded by this request: **NONE**" in text
    assert payload["timing"] == "POST_OUTCOME"
    assert payload["approved_adr"] is False
    assert payload["selected_option"] is None
    assert set(payload["authorization"].values()) == {False}


def test_batch08_evidence_and_detector_contract_are_byte_bound() -> None:
    payload = _evidence()
    report = json.loads(REPORT.read_text())
    detector_sha = hashlib.sha256(DETECTOR.read_bytes()).hexdigest()
    assert payload["batch08"]["audit_sha256"] == hashlib.sha256(REPORT.read_bytes()).hexdigest()
    assert payload["batch08"]["raw_probe_sha256"] == report["attempts"][2]["raw_probe_sha256"]
    assert payload["batch08"]["raw_capture_detection_counts"] == [
        7,
        13,
        11,
        7,
        8,
        9,
        10,
        10,
    ]
    assert payload["batch08"]["permission_failure"] is False
    assert payload["batch08"]["training_sample_packaged"] is False
    assert payload["detector"] == {
        "path": "src/xh_agent/perception/geometric_rgbd.py",
        "sha256": detector_sha,
        "public_color_prototype_count": 6,
        "minimum_component_pixels": 12,
        "maximum_component_pixels": 2500,
        "independent_maximum_component_count": None,
    }


def test_options_are_exactly_exclusive_and_keep_final_k8() -> None:
    headings = re.findall(r"^### ([A-C]) — (.+)$", _text(), re.MULTILINE)
    assert headings == [
        ("A", "separate raw association capacity from final K=8 (recommended)"),
        ("B", "retain raw capacity 8 and keep S4 blocked"),
        ("C", "another complete human-specified contract"),
    ]
    assert "exact `max_raw_public_detections`: `NONE`" in _text()
    assert "Does final candidate K remain exactly 8?: `YES`" in _text()
    assert "physical retry/replacement or outcome reinterpretation authorized?: `NO`" in _text()
