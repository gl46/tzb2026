from xh_agent.teacher.service_client import FutureServiceClient


class BWMClient(FutureServiceClient):
    def __init__(self) -> None:
        super().__init__("BLM-Lab/Boundless-World-Model", "CANDIDATE_LICENSE_PENDING")
