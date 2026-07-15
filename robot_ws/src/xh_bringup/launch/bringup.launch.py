"""Unified P0 bringup delegates scene startup to xh_sim."""
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    sim_share = Path(get_package_share_directory("xh_sim"))
    return LaunchDescription([
        DeclareLaunchArgument("headless", default_value="true"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(sim_share / "launch" / "simulation.launch.py")),
        ),
    ])
