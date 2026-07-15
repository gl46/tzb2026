"""M1A MoveIt execution server bound to the Gazebo-controlled URDF.

This launch deliberately shares the same source URDF with the Gazebo spawn in
``simulation.launch.py``.  It attaches MoveIt to the already-active Gazebo
controllers; it never starts a mock controller manager.
"""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    share = Path(get_package_share_directory("xh_sim"))
    moveit_config = (
        MoveItConfigsBuilder("xh_panda_controlled", package_name="xh_sim")
        .robot_description(file_path="urdf/panda_controlled.urdf")
        .robot_description_semantic(file_path="config/m1a_panda.srdf")
        .robot_description_kinematics(file_path="config/m1a_kinematics.yaml")
        .joint_limits(file_path="config/m1a_joint_limits.yaml")
        .trajectory_execution(file_path="config/m1a_moveit_controllers.yaml", moveit_manage_controllers=False)
        .planning_pipelines(default_planning_pipeline="ompl", pipelines=["ompl"], load_all=False)
        .to_moveit_configs()
    )
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(share / "launch" / "simulation.launch.py")),
            launch_arguments={"headless": "true"}.items(),
        ),
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            output="screen",
            parameters=[
                moveit_config.to_dict(),
                {"use_sim_time": True, "planning_scene_monitor.publish_planning_scene": True,
                 "planning_scene_monitor.publish_geometry_updates": True,
                 "planning_scene_monitor.publish_state_updates": True,
                 "planning_scene_monitor.publish_transforms_updates": True},
            ],
        ),
    ])
