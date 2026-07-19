#!/usr/bin/env python3
"""Reliably replay the generated robot description during simulator startup."""

from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


class RobotDescriptionRelay(Node):
    """Bridge the Gazebo controller-manager startup ordering race.

    The relay publishes only the generated URDF, with transient-local QoS and
    periodic replay.  It has no scene-supervision input and is not a policy
    path.
    """

    def __init__(self) -> None:
        super().__init__("robot_description_relay")
        self.declare_parameter("urdf_path", "")
        urdf_path = Path(str(self.get_parameter("urdf_path").value))
        if not urdf_path.is_file():
            raise RuntimeError(f"urdf_path is not a readable file: {urdf_path}")
        self._message = String(data=urdf_path.read_text(encoding="utf-8"))
        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._publisher = self.create_publisher(String, "/robot_description", qos)
        self._publisher.publish(self._message)
        self._timer = self.create_timer(1.0, self._publish)

    def _publish(self) -> None:
        self._publisher.publish(self._message)


def main() -> None:
    rclpy.init()
    node = RobotDescriptionRelay()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
