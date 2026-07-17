"""Dependency-light geometric RGB-D baseline.

It segments non-table connected components in a metric depth image, backprojects
their centroids, and assigns public track IDs.  It reads only arrays provided by
the caller; it has no Gazebo or supervision dependency.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .interfaces import BBoxV1, PerceptionInputV1, PerceptionResultV1
from .pose_state import orientation_state
from .tracker import track_id_from_geometry


class GeometricRGBDBaseline:
    def __init__(self, *, table_depth_m: float = 1.0, min_component_pixels: int = 12) -> None:
        self.table_depth_m = table_depth_m
        self.min_component_pixels = min_component_pixels

    def infer(self, observation: PerceptionInputV1, depth_m: np.ndarray) -> list[PerceptionResultV1]:
        if depth_m.ndim != 2 or not np.isfinite(depth_m).all():
            raise ValueError("depth must be a finite HxW metric array")
        foreground = depth_m < self.table_depth_m - 0.01
        components = self._components(foreground)
        fx, fy, cx, cy = observation.camera_intrinsics[0], observation.camera_intrinsics[4], observation.camera_intrinsics[2], observation.camera_intrinsics[5]
        if fx <= 0 or fy <= 0:
            raise ValueError("camera focal lengths must be positive")
        results: list[PerceptionResultV1] = []
        for pixels in components:
            if len(pixels) < self.min_component_pixels:
                continue
            rows = np.fromiter((pixel[0] for pixel in pixels), dtype=int)
            cols = np.fromiter((pixel[1] for pixel in pixels), dtype=int)
            z = float(np.median(depth_m[rows, cols]))
            u, v = float(np.mean(cols)), float(np.mean(rows))
            position = [(u - cx) * z / fx, (v - cy) * z / fy, z]
            bbox = BBoxV1(x=int(cols.min()), y=int(rows.min()), width=int(cols.max() - cols.min() + 1), height=int(rows.max() - rows.min() + 1))
            lateral = max(bbox.width / fx * z, bbox.height / fy * z)
            height = max(0.005, self.table_depth_m - z)
            state = orientation_state(height, lateral)
            confidence = min(0.99, len(pixels) / float(self.min_component_pixels * 4))
            results.append(PerceptionResultV1(
                frame_id=observation.frame_id, timestamp_ns=observation.timestamp_ns,
                track_id=track_id_from_geometry(position, "industrial_cylinder"), category="industrial_cylinder",
                attributes={"orientation": state}, bbox_or_mask=bbox, position_3d=position,
                orientation_state=state, confidence=confidence,
                covariance_or_quality={"component_pixels": float(len(pixels)), "depth_median_m": z},
                visibility=min(1.0, len(pixels) / 100.0), relations=[],
                source_components=["geometric_rgbd_v1"],
            ))
        return sorted(results, key=lambda item: item.position_3d[0])

    @staticmethod
    def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
        seen = np.zeros(mask.shape, dtype=bool)
        height, width = mask.shape
        output: list[list[tuple[int, int]]] = []
        for row, col in zip(*np.where(mask)):
            if seen[row, col]:
                continue
            seen[row, col] = True
            queue = deque([(int(row), int(col))])
            component: list[tuple[int, int]] = []
            while queue:
                current_row, current_col = queue.popleft()
                component.append((current_row, current_col))
                for next_row, next_col in ((current_row - 1, current_col), (current_row + 1, current_col), (current_row, current_col - 1), (current_row, current_col + 1)):
                    if 0 <= next_row < height and 0 <= next_col < width and mask[next_row, next_col] and not seen[next_row, next_col]:
                        seen[next_row, next_col] = True
                        queue.append((next_row, next_col))
            output.append(component)
        return output
