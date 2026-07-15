from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class TeacherCandidate:
    model_id: str
    status: str
    priority: str
    license_status: str
    access_status: str
    action_domains: tuple[str, ...]
    action_mapping_status: str
    recommended_hardware: str
    revision: str
    last_checked_at: str
    blockers: tuple[str, ...]


class TeacherRegistry:
    def __init__(self, candidates: dict[str, TeacherCandidate]) -> None:
        self._candidates = candidates
        self._active_model: str | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TeacherRegistry":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        candidates = {key: TeacherCandidate(
            model_id=value["model_id"], status=value["status"], priority=value["priority"],
            license_status=value["license_status"], access_status=value["access_status"],
            action_domains=tuple(value["action_domains"]),
            action_mapping_status=value["action_mapping_status"],
            recommended_hardware=value["recommended_hardware"], revision=value["revision"],
            last_checked_at=value["last_checked_at"], blockers=tuple(value["blockers"]),
        ) for key, value in raw.items()}
        return cls(candidates)

    def get(self, key: str) -> TeacherCandidate:
        return self._candidates[key]

    def all(self) -> dict[str, TeacherCandidate]:
        return dict(self._candidates)

    @property
    def active_model(self) -> str | None:
        return self._active_model

    def activate(self, key: str, human_adr_id: str | None = None) -> None:
        candidate = self.get(key)
        if not human_adr_id:
            raise PermissionError("Teacher activation requires an explicit human ADR")
        if candidate.status in {"PARKED", "CANDIDATE_LICENSE_PENDING"}:
            raise PermissionError(f"{candidate.model_id} cannot be activated in status {candidate.status}")
        self._active_model = key
