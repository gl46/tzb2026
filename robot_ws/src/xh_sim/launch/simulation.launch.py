"""Launch the bounded P0 Harmonic scene and its controller-backed arm."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _robot_actions(context, share: Path):
    """Build the controller-backed robot after resolving calibration mode."""
    urdf = share / "urdf" / "panda_controlled.urdf"
    robot_xml = urdf.read_text(encoding="utf-8").replace("$(find xh_sim)", str(share))
    calibration_mode = LaunchConfiguration("calibration_mode").perform(context).lower() == "true"
    if calibration_mode:
        # The M0 detachable joint moves the red cube with the arm even before a
        # physical finger grasp is established.  S0 validates raw contact
        # telemetry, so its isolated world excludes only this simulator-only
        # constraint; every link, joint, limit, collision and controller is
        # otherwise byte-for-byte from panda_controlled.urdf.
        start = robot_xml.find('<plugin filename="gz-sim-detachable-joint-system"')
        end = robot_xml.find("</plugin>", start)
        if start < 0 or end < 0:
            raise RuntimeError("S0 calibration requested but detachable-joint plugin was not found")
        robot_xml = robot_xml[:start] + robot_xml[end + len("</plugin>"):]
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
    return [
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
    ]


def generate_launch_description():
    share = Path(get_package_share_directory("xh_sim"))
    ros_gz_share = Path(get_package_share_directory("ros_gz_sim"))
    default_world = share / "worlds" / "p0_pick_place.sdf"
    world_file = LaunchConfiguration("world_file")
    left_contact_gz = (
        "/world/xh_p0_pick_place/model/panda_controller/link/panda_leftfinger/"
        "sensor/left_finger_contact/contact"
    )
    right_contact_gz = (
        "/world/xh_p0_pick_place/model/panda_controller/link/panda_rightfinger/"
        "sensor/right_finger_contact/contact"
    )
    cube_contact_gz = (
        "/world/xh_p0_pick_place/model/object_red_cube/link/link/"
        "sensor/red_cube_contact/contact"
    )
    cube_environment_contact_gz = (
        "/world/xh_p0_pick_place/model/object_red_cube_environment/link/link/"
        "sensor/red_cube_environment_contact/contact"
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
            f"{left_contact_gz}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
            f"{right_contact_gz}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
            f"{cube_contact_gz}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
            f"{cube_environment_contact_gz}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
        ],
        remappings=[
            (left_contact_gz, "/xh/supervision/panda_leftfinger_contacts"),
            (right_contact_gz, "/xh/supervision/panda_rightfinger_contacts"),
            (cube_contact_gz, "/xh/supervision/red_cube_contacts"),
            (cube_environment_contact_gz, "/xh/supervision/red_cube_environment_contacts"),
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument("headless", default_value="true", description="Server-only P0 launch."),
        DeclareLaunchArgument(
            "calibration_mode",
            default_value="false",
            description="S0-only: omit the M0 detachable joint, retaining all robot mechanics.",
        ),
        DeclareLaunchArgument(
            "world_file",
            default_value=str(default_world),
            description="Absolute SDF world path; S0 may select its isolated calibration world.",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(ros_gz_share / "launch" / "gz_sim.launch.py")),
            launch_arguments={"gz_args": ["-r -s --headless-rendering ", world_file]}.items(),
        ),
        bridge,
        OpaqueFunction(function=lambda context: _robot_actions(context, share)),
    ])
