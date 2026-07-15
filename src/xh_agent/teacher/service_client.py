from __future__ import annotations

from xh_agent.contracts.models import TeacherRequestV0, TeacherResponseV0
from xh_agent.teacher.base import BaseTeacher, TeacherUnavailableError


class FutureServiceClient(BaseTeacher):
    """A declared future HTTP/RPC boundary; never loads a model in this repository."""

    def __init__(self, model_id: str, status: str) -> None:
        self.model_id = model_id
        self.status = status

    def health_check(self) -> dict[str, str]:
        return {"status": "NOT_CONNECTED", "model_id": self.model_id, "candidate_status": self.status}

    def get_capabilities(self) -> dict[str, object]:
        return {"forward_dynamics": "future_service_only", "loads_local_model": False}

    def submit_forward_dynamics(self, request: TeacherRequestV0) -> str:
        self.validate_request(request)
        raise TeacherUnavailableError("No Teacher service endpoint is configured; GPU inference is disabled")

    def get_result(self, handle: str) -> TeacherResponseV0:
        raise TeacherUnavailableError(f"No result for inactive service handle {handle}")

    def cancel(self, handle: str) -> None:
        del handle
