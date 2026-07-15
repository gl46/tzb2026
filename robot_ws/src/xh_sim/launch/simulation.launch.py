"""Launch the bounded P0 Harmonic scene and its controller-backed arm."""

from pathlib import Path
import re

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory("xh_sim"))
    ros_gz_share = Path(get_package_share_directory("ros_gz_sim"))
    world = share / "worlds" / "p0_pick_place.sdf"
    urdf = share / "urdf" / "panda_controlled.urdf"

    # The same description is intentionally sent to robot_state_publisher and
    # Gazebo's create node.  This keeps TF and the gz_ros2_control model bound
    # to one concrete, auditable robot description.
    # ``ros_gz_sim create`` receives XML directly, not an xacro expansion pass.
    # Resolve the controller YAML package substitution before publication so the
    # Gazebo plugin receives an actual readable path rather than ``$(find ...)``.
    robot_xml = urdf.read_text(encoding="utf-8").replace("$(find xh_sim)", str(share))
    # This controller-validation approximation has no reliable link geometry
    # clearance model.  Keep its visual/inertial chain but exclude robot
    # collisions, so Gazebo does not silently truncate a requested joint goal
    # while the action server reports success. Object and bin collisions remain
    # enabled in the world and are collected as simulator supervision.
    robot_xml = re.sub(r"<collision>.*?</collision>", "", robot_xml)
    robot_description = {"robot_description": robot_xml, "use_sim_time": True}
    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description],
    )
    spawn_robot = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=[
            "-world", "xh_p0_pick_place", "-topic", "robot_description",
            "-name", "panda_controller", "-allow_renaming", "true",
            "-x", "0", "-y", "0", "-z", "0",
        ],
    )
    joint_state_broadcaster = Node(
        package="controller_manager",
        executable="spawner",
        output="screen",
        arguments=["joint_state_broadcaster", "--controller-manager-timeout", "20"],
    )
    arm_controller = Node(
        package="controller_manager",
        executable="spawner",
        output="screen",
        arguments=["panda_arm_controller", "--controller-manager-timeout", "20"],
    )
    hand_controller = Node(
        package="controller_manager",
        executable="spawner",
        output="screen",
        arguments=["panda_hand_controller", "--controller-manager-timeout", "20"],
    )
    # Camera bridges are intentionally explicit.  A missing transport topic is
    # reported by the smoke test rather than treated as a substitute for RGB-D.
    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        output="screen",
        arguments=[
            "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
            "/xh/camera/rgbd/image@sensor_msgs/msg/Image[gz.msgs.Image",
            "/xh/camera/rgbd/depth_image@sensor_msgs/msg/Image[gz.msgs.Image",
            "/xh/camera/rgbd/camera_info@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo",
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument("headless", default_value="true", description="Server-only P0 launch."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(ros_gz_share / "launch" / "gz_sim.launch.py")),
            launch_arguments={"gz_args": f"-r -s --headless-rendering {world}"}.items(),
        ),
        bridge,
        robot_state_publisher,
        spawn_robot,
        RegisterEventHandler(OnProcessExit(
            target_action=spawn_robot,
            on_exit=[joint_state_broadcaster],
        )),
        RegisterEventHandler(OnProcessExit(
            target_action=joint_state_broadcaster,
            on_exit=[arm_controller, hand_controller],
        )),
    ])
