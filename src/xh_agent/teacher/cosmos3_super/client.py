from xh_agent.contracts.models import TeacherRequestV0, TeacherResponseV0
from xh_agent.teacher.base import BaseTeacher, ModelParkedError


class Cosmos3SuperClient(BaseTeacher):
    model_id = "nvidia/Cosmos3-Super"

    def health_check(self) -> dict[str, str]:
        return {"status": "PARKED", "reason": "REQUIRES_EXPLICIT_HUMAN_REACTIVATION"}

    def get_capabilities(self) -> dict[str, object]:
        return {"forward_dynamics": False, "parked": True, "loads_local_model": False}

    def validate_request(self, request: TeacherRequestV0) -> None:
        del request
        raise ModelParkedError("Cosmos3-Super is PARKED and cannot receive requests")

    def submit_forward_dynamics(self, request: TeacherRequestV0) -> str:
        self.validate_request(request)
        raise AssertionError("unreachable")

    def get_result(self, handle: str) -> TeacherResponseV0:
        del handle
        raise ModelParkedError("Cosmos3-Super is PARKED")

    def cancel(self, handle: str) -> None:
        del handle
        raise ModelParkedError("Cosmos3-Super is PARKED")
