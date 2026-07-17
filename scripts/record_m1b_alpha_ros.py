#!/usr/bin/env python3
"""Record one synchronized non-oracle RGB-D/robot observation from live ROS 2.

This script consumes only public topics.  Simulator supervision must be written
by a separate offline producer; it is not subscribed to or embedded here.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image, JointState
from tf2_msgs.msg import TFMessage


def _stamp(header: Any) -> int:
    return int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec)


class SnapshotRecorder(Node):
    def __init__(self, output: Path, duration_s: float, max_skew_ns: int, sensor_only: bool) -> None:
        super().__init__("m1b_alpha_snapshot_recorder")
        self.output = output
        self.deadline = time.monotonic() + duration_s
        self.max_skew_ns = max_skew_ns
        self.sensor_only = sensor_only
        self.rgb: Image | None = None
        self.depth: Image | None = None
        self.camera_info: CameraInfo | None = None
        self.joints: JointState | None = None
        self.transforms: list[TransformStamped] | None = None
        self.create_subscription(Image, "/xh/camera/rgbd/image", self._rgb, 10)
        self.create_subscription(Image, "/xh/camera/rgbd/depth_image", self._depth, 10)
        self.create_subscription(CameraInfo, "/xh/camera/rgbd/camera_info", self._camera, 10)
        self.create_subscription(JointState, "/joint_states", self._joints, 10)
        self.create_subscription(TFMessage, "/tf", self._tf, 10)

    def _rgb(self, message: Image) -> None:
        self.rgb = message

    def _depth(self, message: Image) -> None:
        self.depth = message

    def _camera(self, message: CameraInfo) -> None:
        self.camera_info = message

    def _joints(self, message: JointState) -> None:
        self.joints = message

    def _tf(self, message: TFMessage) -> None:
        if message.transforms:
            self.transforms = list(message.transforms)

    def complete(self) -> bool:
        required = (self.rgb, self.depth, self.camera_info) if self.sensor_only else (self.rgb, self.depth, self.camera_info, self.joints, self.transforms)
        if not all(value is not None for value in required):
            return False
        assert self.rgb is not None and self.depth is not None and self.camera_info is not None
        timestamps = [_stamp(self.rgb.header), _stamp(self.depth.header), _stamp(self.camera_info.header)]
        if not self.sensor_only:
            assert self.joints is not None and self.transforms is not None
            timestamps.extend((_stamp(self.joints.header), min(_stamp(transform.header) for transform in self.transforms)))
        return max(timestamps) - min(timestamps) <= self.max_skew_ns

    def write(self) -> dict[str, object]:
        if not self.complete():
            values = {"rgb": self.rgb, "depth": self.depth, "camera_info": self.camera_info}
            if not self.sensor_only:
                values.update({"joint_states": self.joints, "tf": self.transforms})
            missing = [name for name, value in values.items() if value is None]
            raise RuntimeError(f"missing required live streams: {','.join(missing)}")
        assert self.rgb is not None and self.depth is not None and self.camera_info is not None
        self.output.mkdir(parents=True, exist_ok=True)
        if self.rgb.encoding not in {"rgb8", "bgr8"}:
            raise RuntimeError(f"unsupported RGB encoding: {self.rgb.encoding}")
        rows = [bytes(self.rgb.data[index * self.rgb.step:index * self.rgb.step + self.rgb.width * 3]) for index in range(self.rgb.height)]
        pixels = b"".join(rows)
        if self.rgb.encoding == "bgr8":
            pixels = b"".join(pixels[index:index + 3][::-1] for index in range(0, len(pixels), 3))
        (self.output / "rgb.ppm").write_bytes(f"P6\n{self.rgb.width} {self.rgb.height}\n255\n".encode() + pixels)
        (self.output / "depth.bin").write_bytes(bytes(self.depth.data))
        (self.output / "camera_info.json").write_text(json.dumps({"k": list(self.camera_info.k), "d": list(self.camera_info.d), "p": list(self.camera_info.p), "frame_id": self.camera_info.header.frame_id, "timestamp_ns": _stamp(self.camera_info.header)}, indent=2) + "\n")
        manifest = {
            "schema_version": "M1BAlphaRecordingV1", "channels": "ONLINE_OBSERVATION_ONLY",
            "rgb": {"uri": "rgb.ppm", "encoding": "rgb8", "timestamp_ns": _stamp(self.rgb.header)},
            "depth": {"uri": "depth.bin", "encoding": self.depth.encoding, "width": self.depth.width, "height": self.depth.height, "step": self.depth.step, "is_bigendian": self.depth.is_bigendian, "timestamp_ns": _stamp(self.depth.header)},
            "camera_info": {"uri": "camera_info.json", "timestamp_ns": _stamp(self.camera_info.header)},
            "simulator_supervision": "separate_required_not_recorded",
        }
        if not self.sensor_only:
            assert self.joints is not None and self.transforms is not None
            (self.output / "joint_states.json").write_text(json.dumps({"name": list(self.joints.name), "position": list(self.joints.position), "velocity": list(self.joints.velocity), "timestamp_ns": _stamp(self.joints.header)}, indent=2) + "\n")
            (self.output / "tf.json").write_text(json.dumps({"transforms": [{"parent": transform.header.frame_id, "child": transform.child_frame_id, "timestamp_ns": _stamp(transform.header)} for transform in self.transforms]}, indent=2) + "\n")
            manifest["joint_states"] = {"uri": "joint_states.json", "timestamp_ns": _stamp(self.joints.header)}
            manifest["tf"] = {"uri": "tf.json", "timestamp_ns": min(_stamp(transform.header) for transform in self.transforms)}
        timestamps = [entry["timestamp_ns"] for entry in manifest.values() if isinstance(entry, dict) and "timestamp_ns" in entry]
        manifest["max_stream_skew_ns"] = max(timestamps) - min(timestamps)
        (self.output / "recording.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--duration-s", type=float, default=20.0)
    parser.add_argument("--max-skew-ms", type=float, default=200.0)
    parser.add_argument("--sensor-only", action="store_true", help="record RGB-D/camera only for simulator dataset generation")
    args = parser.parse_args()
    rclpy.init()
    node = SnapshotRecorder(args.output_dir, args.duration_s, int(args.max_skew_ms * 1_000_000), args.sensor_only)
    try:
        while time.monotonic() < node.deadline and not node.complete():
            rclpy.spin_once(node, timeout_sec=0.2)
        manifest = node.write()
        print(json.dumps({"status": "RECORDED", "output": str(args.output_dir), "max_stream_skew_ns": manifest["max_stream_skew_ns"]}))
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
