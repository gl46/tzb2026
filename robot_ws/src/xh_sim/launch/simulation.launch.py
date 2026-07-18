"""Launch the bounded P0 Harmonic scene and its controller-backed arm."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def _generate_spawn_representation(share: Path, calibration_mode: bool, scene_supervision: str) -> tuple[Path, Path, Path]:
    """Create ADR-0009's verified SDF before Gazebo can spawn the robot."""

    urdf = share / "urdf" / "panda_controlled.urdf"
    mode = "beta" if scene_supervision else "calibration" if calibration_mode else "production"
    artifact_root = os.environ.get("XH_SIM_GENERATED_SDF_DIR")
    artifact_dir = (
        Path(artifact_root).resolve()
        if artifact_root else Path(tempfile.mkdtemp(prefix=f"xh-sim-{mode}-"))
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_sdf = artifact_dir / "panda_controller.sdf"
    output_urdf = artifact_dir / "panda_controller.urdf"
    manifest = artifact_dir / "panda_controller.manifest.json"
    generator = (
        Path(get_package_prefix("xh_sim")) / "lib" / "xh_sim" / "generate_panda_spawn_sdf.py"
    )
    completed = subprocess.run(
        [
            sys.executable, str(generator), "--urdf", str(urdf),
            "--package-share", str(share), "--mode", mode,
            "--output-sdf", str(output_sdf), "--output-urdf", str(output_urdf),
            "--manifest", str(manifest),
            *(["--scene-supervision", scene_supervision] if scene_supervision else []),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if completed.returncode != 0 or not all(path.is_file() for path in (output_sdf, output_urdf, manifest)):
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"ADR-0009 generated SDF is unavailable: {detail}")
    hashes = json.loads(manifest.read_text(encoding="utf-8"))["hashes"]
    print(
        "M1A_SDF_SPAWN_MANIFEST "
        f"mode={mode} urdf={hashes['source_urdf_sha256']} "
        f"sdf={hashes['generated_sdf_sha256']} generator={hashes['generator_sha256']} "
        f"path={manifest}",
        flush=True,
    )
    return output_urdf, output_sdf, manifest


def _robot_actions(context, share: Path):
    """Build the controller-backed robot after resolving calibration mode."""

    calibration_mode = LaunchConfiguration("calibration_mode").perform(context).lower() == "true"
    scene_supervision = LaunchConfiguration("m1b_scene_supervision").perform(context)
    world_name = LaunchConfiguration("world_name")
    world_name_value = world_name.perform(context)
    generated_urdf, generated_sdf, _manifest = _generate_spawn_representation(share, calibration_mode, scene_supervision)
    robot_xml = generated_urdf.read_text(encoding="utf-8")
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
            "-world", world_name, "-file", str(generated_sdf),
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
        arguments=["panda_hand_physical_controller", "--controller-manager-timeout", "20"],
    )
    hand_adapter = Node(
        package="xh_sim",
        executable="panda_hand_mimic_adapter.py",
        output="screen",
    )
    actions = [
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
        RegisterEventHandler(OnProcessExit(
            target_action=hand_controller,
            on_exit=[hand_adapter],
        )),
    ]
    if scene_supervision:
        configured_calibration = os.environ.get("XH_M1B_CAMERA_CALIBRATION")
        calibration_path = Path(configured_calibration) if configured_calibration else next(
            (
                parent / "configs" / "m1b_camera_calibration.json"
                for parent in Path(__file__).resolve().parents
                if (parent / "configs" / "m1b_camera_calibration.json").is_file()
            ),
            None,
        )
        if calibration_path is None:
            raise RuntimeError("M1B camera calibration file is unavailable")
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        if calibration.get("schema_version") != "M1BStaticCameraCalibrationV1":
            raise RuntimeError("M1B camera calibration schema is unavailable")
        if calibration.get("link_to_optical_axes") != "gazebo_camera_link_to_ros_optical_v1":
            raise RuntimeError("M1B camera calibration axis convention is unavailable")
        # The launch process owns the static TF publication.  It never queries
        # Gazebo for a pose, so privileged simulator state cannot enter policy.
        x, y, z = calibration["translation_m"]
        roll, pitch, yaw = calibration["rpy_rad"]
        actions.extend((Node(
            package="tf2_ros", executable="static_transform_publisher", output="screen",
            arguments=["--x", str(x), "--y", str(y), "--z", str(z), "--roll", str(roll), "--pitch", str(pitch), "--yaw", str(yaw), "--frame-id", calibration["parent_frame"], "--child-frame-id", calibration["camera_link_frame"]],
        ), Node(
            package="tf2_ros", executable="static_transform_publisher", output="screen",
            arguments=["--roll", str(-1.5707963267948966), "--pitch", "0", "--yaw", str(-1.5707963267948966), "--frame-id", calibration["camera_link_frame"], "--child-frame-id", calibration["camera_optical_frame"]],
        )))
        # Raw finger contacts remain actuation-internal.  The broker alone
        # parses their simulator collision names; task/perception interfaces
        # never subscribe to these topics.
        left_contact = (
            f"/world/{world_name_value}/model/panda_controller/link/panda_leftfinger/"
            "sensor/left_finger_contact/contact"
        )
        right_contact = (
            f"/world/{world_name_value}/model/panda_controller/link/panda_rightfinger/"
            "sensor/right_finger_contact/contact"
        )
        # Each cylinder also publishes its own physical contact stream.  Keep
        # these bridges actuation-internal: the broker can use a cylinder's
        # contact pair to recover an independently observed finger event when
        # one finger-mounted sensor drops an event.  The static 12-topic upper
        # bound matches the industrial generator; absent models simply have no
        # publisher and never create synthetic contact data.
        cylinder_contacts = [
            f"/xh/actuation_internal/cylinders/cylinder_{index:02d}/contacts"
            for index in range(1, 13)
        ]
        actions.append(Node(
            package="ros_gz_bridge", executable="parameter_bridge", output="screen",
            arguments=[
                f"{left_contact}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
                f"{right_contact}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
                *(f"{topic}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts" for topic in cylinder_contacts),
            ],
            remappings=[
                (left_contact, "/xh/actuation_internal/m1b/panda_leftfinger_contacts"),
                (right_contact, "/xh/actuation_internal/m1b/panda_rightfinger_contacts"),
                *( (topic, f"/xh/actuation_internal/m1b/cylinder_{index:02d}_contacts")
                   for index, topic in enumerate(cylinder_contacts, start=1) ),
            ],
        ))
    return actions


def generate_launch_description():
    share = Path(get_package_share_directory("xh_sim"))
    ros_gz_share = Path(get_package_share_directory("ros_gz_sim"))
    default_world = share / "worlds" / "p0_pick_place.sdf"
    world_file = LaunchConfiguration("world_file")
    start_paused = LaunchConfiguration("start_paused")
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
    cube_bilateral_contact_gz = (
        "/world/xh_p0_pick_place/model/object_red_cube_bilateral/link/link/"
        "sensor/red_cube_bilateral_contact/contact"
    )
    dynamic_pose_gz = "/world/xh_p0_pick_place/dynamic_pose/info"
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
            f"{cube_bilateral_contact_gz}@ros_gz_interfaces/msg/Contacts[gz.msgs.Contacts",
            f"{dynamic_pose_gz}@geometry_msgs/msg/PoseArray[gz.msgs.Pose_V",
        ],
        remappings=[
            (left_contact_gz, "/xh/supervision/panda_leftfinger_contacts"),
            (right_contact_gz, "/xh/supervision/panda_rightfinger_contacts"),
            (cube_contact_gz, "/xh/supervision/red_cube_contacts"),
            (cube_environment_contact_gz, "/xh/supervision/red_cube_environment_contacts"),
            (cube_bilateral_contact_gz, "/xh/supervision/red_cube_bilateral_contacts"),
            (dynamic_pose_gz, "/xh/supervision/dynamic_pose"),
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
        DeclareLaunchArgument(
            "world_name",
            default_value="xh_p0_pick_place",
            description="Gazebo world name used by the controller-backed Panda spawn.",
        ),
        DeclareLaunchArgument(
            "m1b_scene_supervision",
            default_value="",
            description="ADR-0013 beta only: supervision manifest used at spawn to create per-object internal grasp joints.",
        ),
        DeclareLaunchArgument(
            "start_paused",
            default_value="false",
            description="Start Gazebo paused; ADR-0014 requires this for M1B detach-first reset.",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(ros_gz_share / "launch" / "gz_sim.launch.py")),
            launch_arguments={
                "gz_args": [
                    PythonExpression([
                        "'-s --headless-rendering ' if '", start_paused,
                        "'.lower() == 'true' else '-r -s --headless-rendering '",
                    ]),
                    world_file,
                ],
            }.items(),
        ),
        bridge,
        OpaqueFunction(function=lambda context: _robot_actions(context, share)),
    ])
