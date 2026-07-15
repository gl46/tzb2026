from pydantic import BaseModel, ConfigDict, Field

from xh_agent.skills.failure_injection import FailureInjectionConfig


class SceneObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str
    color: str
    shape: str
    pose: list[float] = Field(min_length=7, max_length=7)


class SceneConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int
    table_frame: str = "table"
    camera_frame: str = "camera_rgbd"
    objects: list[SceneObject] = Field(min_length=3)
    destination_container: str
    failures: list[FailureInjectionConfig] = Field(default_factory=list)
