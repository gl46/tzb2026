"""CPU-only service contract for optional world-model Teachers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from xh_agent.contracts.models import TeacherRequestV0, TeacherResponseV0


class TeacherUnavailableError(RuntimeError):
    pass


class ModelParkedError(TeacherUnavailableError):
    pass


class BaseTeacher(ABC):
    model_id: str

    @abstractmethod
    def health_check(self) -> dict[str, str]: ...

    @abstractmethod
    def get_capabilities(self) -> dict[str, object]: ...

    def validate_request(self, request: TeacherRequestV0) -> None:
        request.validate_for_real_teacher()

    @abstractmethod
    def submit_forward_dynamics(self, request: TeacherRequestV0) -> str: ...

    @abstractmethod
    def get_result(self, handle: str) -> TeacherResponseV0: ...

    @abstractmethod
    def cancel(self, handle: str) -> None: ...
