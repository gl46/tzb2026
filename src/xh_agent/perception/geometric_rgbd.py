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
    def __init__(self, *, table_depth_m: float = 1.0, min_component_pixels: int = 12, max_component_pixels: int = 2000) -> None:
        self.table_depth_m = table_depth_m
        self.min_component_pixels = min_component_pixels
        self.max_component_pixels = max_component_pixels

    def infer(self, observation: PerceptionInputV1, depth_m: np.ndarray, rgb: np.ndarray | None = None) -> list[PerceptionResultV1]:
        if depth_m.ndim != 2 or not np.isfinite(depth_m).any():
            raise ValueError("depth must be an HxW metric array with at least one finite sample")
        # Sensor dropouts are a normal online condition, not privileged input.
        # Estimate the visible table from the depth image itself; no simulator
        # surface pose, entity name, or scene seed participates in this step.
        valid = np.isfinite(depth_m)
        table = self._table_plane(depth_m, valid)
        depth_m = np.where(valid, depth_m, table)
        foreground = valid & (depth_m < table - 0.012)
        if rgb is not None:
            if rgb.shape != (*depth_m.shape, 3):
                raise ValueError("RGB must align with the depth image as HxWx3")
            rgb_int = rgb.astype(np.int16)
            maximum, minimum = rgb_int.max(axis=2), rgb_int.min(axis=2)
            blue_dominant = (rgb_int[:, :, 2] > rgb_int[:, :, 0] + 25) & (rgb_int[:, :, 2] > rgb_int[:, :, 1] + 25)
            foreground = valid & (maximum - minimum >= 70) & (maximum >= 90) & ~blue_dominant
        components = self._components(foreground)
        fx, fy, cx, cy = observation.camera_intrinsics[0], observation.camera_intrinsics[4], observation.camera_intrinsics[2], observation.camera_intrinsics[5]
        if fx <= 0 or fy <= 0:
            raise ValueError("camera focal lengths must be positive")
        results: list[PerceptionResultV1] = []
        for pixels in components:
            if not self.min_component_pixels <= len(pixels) <= self.max_component_pixels:
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
    def _table_plane(depth_m: np.ndarray, valid: np.ndarray) -> np.ndarray:
        """Fit a dominant planar surface in inverse-depth image coordinates."""
        rows, cols = np.where(valid)
        values = depth_m[rows, cols]
        if len(values) < 3:
            return np.full(depth_m.shape, float(np.nanmedian(values)))
        matrix = np.column_stack((cols, rows, np.ones(len(values))))
        inverse_depth = 1.0 / values
        # Deterministic RANSAC keeps this baseline reproducible and lightweight.
        rng = np.random.default_rng(20260717)
        sample_size = min(len(values), 3000)
        sampled = rng.choice(len(values), size=sample_size, replace=False)
        best_coefficients: np.ndarray | None = None
        best_inliers = -1
        for _ in range(96):
            chosen = rng.choice(sampled, size=3, replace=False)
            coefficients, _, _, _ = np.linalg.lstsq(matrix[chosen], inverse_depth[chosen], rcond=None)
            if not np.isfinite(coefficients).all() or np.max(np.abs(coefficients)) > 1e6:
                continue
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                denominator = matrix[sampled] @ coefficients
                predicted = np.divide(1.0, denominator, out=np.full_like(denominator, np.inf), where=np.abs(denominator) > 1e-9)
            inliers = np.isfinite(predicted) & (np.abs(values[sampled] - predicted) <= 0.012)
            if int(inliers.sum()) > best_inliers:
                best_coefficients = coefficients
                best_inliers = int(inliers.sum())
        assert best_coefficients is not None
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            denominator = matrix @ best_coefficients
            predicted = np.divide(1.0, denominator, out=np.full_like(denominator, np.inf), where=np.abs(denominator) > 1e-9)
        inliers = np.isfinite(predicted) & (np.abs(values - predicted) <= 0.012)
        if int(inliers.sum()) < 3:
            inliers = np.ones(len(values), dtype=bool)
        coefficients, _, _, _ = np.linalg.lstsq(matrix[inliers], inverse_depth[inliers], rcond=None)
        grid_rows, grid_cols = np.indices(depth_m.shape)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            denominator = coefficients[0] * grid_cols + coefficients[1] * grid_rows + coefficients[2]
            return np.divide(1.0, denominator, out=np.full(depth_m.shape, np.inf), where=np.abs(denominator) > 1e-9)

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
