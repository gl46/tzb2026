"""Headless MoveIt Panda planning server used for bounded B1 planning evidence.

This intentionally uses the official Panda MoveIt resource with mock hardware. It
does not dispatch trajectories to the Gazebo controller; that boundary is explicit
until planning-scene, collision and execution adapters are connected.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    moveit_config = (
        MoveItConfigsBuilder("moveit_resources_panda")
        .robot_description(
            file_path="config/panda.urdf.xacro",
            mappings={"ros2_control_hardware_type": "mock_components"},
        )
        .robot_description_semantic(file_path="config/panda.srdf")
        .planning_scene_monitor(
            publish_robot_description=True,
            publish_robot_description_semantic=True,
        )
        .trajectory_execution(file_path="config/gripper_moveit_controllers.yaml")
        .planning_pipelines(
            pipelines=["ompl", "chomp", "pilz_industrial_motion_planner", "stomp"],
        )
        .to_moveit_configs()
    )
    controller_config = os.path.join(
        get_package_share_directory("moveit_resources_panda_moveit_config"),
        "config",
        "ros2_controllers.yaml",
    )
    return LaunchDescription([
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            output="screen",
            parameters=[moveit_config.to_dict()],
        ),
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            name="panda_world_tf",
            output="screen",
            arguments=["0", "0", "0", "0", "0", "0", "world", "panda_link0"],
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            output="screen",
            parameters=[moveit_config.robot_description],
        ),
        Node(
            package="controller_manager",
            executable="ros2_control_node",
            output="screen",
            parameters=[controller_config],
            remappings=[("/controller_manager/robot_description", "/robot_description")],
        ),
        Node(
            package="controller_manager",
            executable="spawner",
            output="screen",
            arguments=["joint_state_broadcaster", "-c", "/controller_manager"],
        ),
        Node(
            package="controller_manager",
            executable="spawner",
            output="screen",
            arguments=["panda_arm_controller", "-c", "/controller_manager"],
        ),
        Node(
            package="controller_manager",
            executable="spawner",
            output="screen",
            arguments=["panda_hand_controller", "-c", "/controller_manager"],
        ),
    ])
