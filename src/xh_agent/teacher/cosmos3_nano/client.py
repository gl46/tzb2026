from xh_agent.teacher.service_client import FutureServiceClient


class Cosmos3NanoClient(FutureServiceClient):
    def __init__(self) -> None:
        super().__init__("nvidia/Cosmos3-Nano", "CANDIDATE")
