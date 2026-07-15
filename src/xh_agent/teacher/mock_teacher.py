from __future__ import annotations

from xh_agent.contracts.models import TeacherRequestV0, TeacherResponseV0
from xh_agent.teacher.base import BaseTeacher


class MockTeacher(BaseTeacher):
    model_id = "mock/teacher"

    def __init__(self) -> None:
        self._responses: dict[str, TeacherResponseV0] = {}

    def health_check(self) -> dict[str, str]:
        return {"status": "READY", "model_id": self.model_id}

    def get_capabilities(self) -> dict[str, object]:
        return {"forward_dynamics": True, "mock": True, "gpu_required": False}

    def validate_request(self, request: TeacherRequestV0) -> None:
        if not request.candidate_model:
            raise ValueError("candidate_model is required")

    def submit_forward_dynamics(self, request: TeacherRequestV0) -> str:
        self.validate_request(request)
        handle = f"mock-{len(self._responses) + 1}"
        self._responses[handle] = TeacherResponseV0(
            status="MOCK", output_uris=[f"mock://{handle}/future.mp4"], latency_ms=0.0,
            peak_vram_mb=0.0, provenance={"teacher": self.model_id, "simulator_truth": "false"},
        )
        return handle

    def get_result(self, handle: str) -> TeacherResponseV0:
        return self._responses[handle]

    def cancel(self, handle: str) -> None:
        self._responses[handle] = TeacherResponseV0(
            status="CANCELLED", provenance={"teacher": self.model_id}
        )
