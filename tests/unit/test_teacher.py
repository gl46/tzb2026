from __future__ import annotations

from pathlib import Path

import pytest

from xh_agent.teacher.cosmos3_nano import Cosmos3NanoClient
from xh_agent.teacher.cosmos3_super import Cosmos3SuperClient
from xh_agent.teacher.mock_teacher import MockTeacher
from xh_agent.teacher.registry import TeacherRegistry
from xh_agent.teacher.base import ModelParkedError
from test_contracts import request


ROOT = Path(__file__).parents[2]


def test_mock_teacher_returns_response() -> None:
    teacher = MockTeacher()
    handle = teacher.submit_forward_dynamics(request())
    assert teacher.get_result(handle).status == "MOCK"


def test_real_service_client_validates_mapping() -> None:
    candidate = Cosmos3NanoClient()
    bad = request().model_copy(update={"action_mapping_revision": "UNKNOWN"})
    with pytest.raises(ValueError):
        candidate.validate_request(bad)


def test_super_is_parked() -> None:
    with pytest.raises(ModelParkedError):
        Cosmos3SuperClient().submit_forward_dynamics(request())


def test_registry_cannot_silently_activate_or_promote_bwm() -> None:
    registry = TeacherRegistry.from_yaml(ROOT / "configs/teacher-candidates.yaml")
    with pytest.raises(PermissionError):
        registry.activate("cosmos3_nano")
    with pytest.raises(PermissionError):
        registry.activate("bwm", human_adr_id="ADR-HUMAN-1")
    assert registry.get("bwm").status == "CANDIDATE_LICENSE_PENDING"
