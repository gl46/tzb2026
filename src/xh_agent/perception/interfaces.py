"""Public online perception contracts.

The input deliberately has no simulator identifiers, perfect poses, contacts, or
success labels.  Those remain in an evaluator-only manifest.
"""
from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PerceptionInputV1(StrictModel):
    schema_version: Literal["PerceptionInputV1"] = "PerceptionInputV1"
    frame_id: str
    timestamp_ns: int = Field(ge=0)
    rgb_uri: str
    depth_uri: str
    camera_intrinsics: list[float] = Field(min_length=9, max_length=9)
    camera_frame: str

    @model_validator(mode="after")
    def finite_intrinsics(self) -> "PerceptionInputV1":
        if not all(isfinite(value) for value in self.camera_intrinsics):
            raise ValueError("camera intrinsics may not contain NaN or Inf")
        return self


class BBoxV1(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PerceptionResultV1(StrictModel):
    """A track-level result safe to provide to planning and execution."""

    schema_version: Literal["PerceptionResultV1"] = "PerceptionResultV1"
    frame_id: str
    timestamp_ns: int = Field(ge=0)
    track_id: str = Field(pattern=r"^track-[0-9a-f]{8}$")
    category: str
    attributes: dict[str, str] = Field(default_factory=dict)
    bbox_or_mask: BBoxV1
    position_3d: list[float] = Field(min_length=3, max_length=3)
    orientation_state: Literal["normal", "inverted", "tilted", "unknown"]
    pose_estimate_optional: list[float] | None = Field(default=None, min_length=7, max_length=7)
    confidence: float = Field(ge=0, le=1)
    covariance_or_quality: dict[str, float] = Field(default_factory=dict)
    visibility: float = Field(ge=0, le=1)
    relations: list[dict[str, str]] = Field(default_factory=list)
    source_components: list[str] = Field(min_length=1)
    failure_reason_optional: str | None = None

    @model_validator(mode="after")
    def finite_geometry(self) -> "PerceptionResultV1":
        values = [*self.position_3d, *(self.pose_estimate_optional or [])]
        if not all(isfinite(value) for value in values):
            raise ValueError("perception geometry may not contain NaN or Inf")
        return self
