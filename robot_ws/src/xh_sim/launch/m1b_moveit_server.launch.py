"""MoveIt execution server for an already-running ADR-0013 M1B simulation.

It deliberately does not include ``simulation.launch.py``: the industrial
world, generated SDF, controller manager, and static camera TF must already be
running under the reset contract before this planning server starts.
"""

from launch import LaunchDescription
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    moveit_config = (
        MoveItConfigsBuilder("xh_panda_controlled", package_name="xh_sim")
        .robot_description(file_path="urdf/panda_controlled.urdf")
        .robot_description_semantic(file_path="config/m1a_panda.srdf")
        .robot_description_kinematics(file_path="config/m1a_kinematics.yaml")
        .joint_limits(file_path="config/m1a_joint_limits.yaml")
        .trajectory_execution(
            file_path="config/m1a_moveit_controllers.yaml", moveit_manage_controllers=False
        )
        .planning_pipelines(default_planning_pipeline="ompl", pipelines=["ompl"], load_all=False)
        .to_moveit_configs()
    )
    return LaunchDescription([
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            output="screen",
            parameters=[
                moveit_config.to_dict(),
                {
                    "use_sim_time": True,
                    "planning_scene_monitor.publish_planning_scene": True,
                    "planning_scene_monitor.publish_geometry_updates": True,
                    "planning_scene_monitor.publish_state_updates": True,
                    "planning_scene_monitor.publish_transforms_updates": True,
                },
            ],
        ),
    ])
