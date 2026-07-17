"""Write a replayable manifest; supervision is deliberately a separate file."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class RecordingEvent:
    timestamp_ns: int
    stream: str
    uri: str


@dataclass
class EpisodeRecorder:
    episode_id: str
    scene_seed: int
    events: list[RecordingEvent] = field(default_factory=list)

    def add(self, timestamp_ns: int, stream: str, uri: str) -> None:
        if self.events and timestamp_ns < self.events[-1].timestamp_ns:
            raise ValueError("recording timestamps must be monotonic")
        if stream == "simulator_supervision":
            raise ValueError("write simulator supervision through write_supervision")
        self.events.append(RecordingEvent(timestamp_ns, stream, uri))

    def write(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"episode_id": self.episode_id, "scene_seed": self.scene_seed, "events": [asdict(event) for event in self.events]}, indent=2) + "\n", encoding="utf-8")

    def write_supervision(self, output: Path, payload: dict[str, object]) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
