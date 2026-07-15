#!/usr/bin/env python3
"""Record real Gazebo RGB frames to PPM for a bounded M1A evidence clip.

This tool only records the bridged simulator camera; it never synthesizes or
alters imagery.  Encode the resulting frames with ffmpeg after recording.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image


class RGBDRecorder(Node):
    def __init__(self, output: Path, duration_s: float, fps: float) -> None:
        super().__init__("m1a_rgbd_video_recorder")
        self.output = output
        self.deadline = time.monotonic() + duration_s
        self.minimum_interval_s = 1.0 / fps
        self.last_frame_at = -float("inf")
        self.frames = 0
        self.encoding = ""
        self.create_subscription(Image, "/xh/camera/rgbd/image", self.on_image, 10)

    def on_image(self, image: Image) -> None:
        now = time.monotonic()
        if now >= self.deadline or now - self.last_frame_at < self.minimum_interval_s:
            return
        if image.encoding not in {"rgb8", "bgr8"}:
            self.get_logger().warning(f"Skipping unsupported image encoding: {image.encoding}")
            return
        expected_row = image.width * 3
        rows = [
            bytes(image.data[row * image.step:row * image.step + expected_row])
            for row in range(image.height)
        ]
        pixels = b"".join(rows)
        if image.encoding == "bgr8":
            converted = bytearray(len(pixels))
            for index in range(0, len(pixels), 3):
                converted[index:index + 3] = pixels[index + 2], pixels[index + 1], pixels[index]
            pixels = bytes(converted)
        path = self.output / f"frame_{self.frames:05d}.ppm"
        path.write_bytes(f"P6\n{image.width} {image.height}\n255\n".encode() + pixels)
        self.last_frame_at = now
        self.frames += 1
        self.encoding = image.encoding


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--fps", type=float, default=15.0)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    recorder = RGBDRecorder(args.output_dir, args.duration_s, args.fps)
    try:
        while time.monotonic() < recorder.deadline:
            rclpy.spin_once(recorder, timeout_sec=0.2)
    finally:
        recorder.destroy_node()
        rclpy.shutdown()
    (args.output_dir / "recording.json").write_text(json.dumps({
        "source": "/xh/camera/rgbd/image",
        "frames": recorder.frames,
        "encoding": recorder.encoding,
        "duration_s": args.duration_s,
        "max_fps": args.fps,
    }, indent=2) + "\n")
    return 0 if recorder.frames else 2


if __name__ == "__main__":
    raise SystemExit(main())
