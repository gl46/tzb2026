#!/usr/bin/env python3
# ruff: noqa: E402
"""Calibration-only Isaac probe for the accepted M1B grasp/attach contracts.

This is not a policy rollout.  The target centre is read from the hash-recorded
scene specification solely to validate the simulator adapter: official Franka
IK, bilateral finger contacts, same-entity brokerage, dynamic fixed-joint
attachment, lift following, detach, and physical non-coupling.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xh_agent.data.isaac_m1b import (
    M1B_URDF_SHA256,
    load_m1b_isaac_generated_scene,
    load_robot_base_pose,
    sha256_file,
)
from xh_agent.grasp.m1b_contact_window import (
    M1BContactSampleV1,
    broker_from_window,
)


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Probe the native Isaac M1B contact/attachment adapter."
    )
    parser.add_argument("--stage", required=True)
    parser.add_argument("--sdf", required=True)
    parser.add_argument("--supervision", required=True)
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-object", default="cylinder_07")
    parser.add_argument("--physics-device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument(
        "--contact-centerlines-m",
        default="0.12,0.11,0.10,0.09,0.08",
        help="Calibration-only hand-origin offsets above the live object centre.",
    )
    parser.add_argument(
        "--gripper-close-steps",
        type=int,
        default=240,
        help="60 Hz settling window for the official Franka gripper drive.",
    )
    return parser.parse_known_args()


ARGS, _UNKNOWN = parse_args()
SCENE = load_m1b_isaac_generated_scene(ARGS.sdf, ARGS.supervision)
ROBOT_BASE_POSE = load_robot_base_pose(ARGS.urdf)
if sha256_file(ARGS.urdf) != M1B_URDF_SHA256:
    raise ValueError("M1B actuation probe URDF hash mismatch")
TARGET_MODEL = next(
    (model for model in SCENE.dynamic_models if model.name == ARGS.target_object),
    None,
)
if TARGET_MODEL is None:
    raise ValueError(f"target object is absent from scene: {ARGS.target_object}")
CONTACT_CENTERLINES_M = tuple(
    float(value) for value in ARGS.contact_centerlines_m.split(",")
)
if (
    not CONTACT_CENTERLINES_M
    or any(not 0.06 <= value <= 0.15 for value in CONTACT_CENTERLINES_M)
    or any(
        later >= earlier
        for earlier, later in zip(CONTACT_CENTERLINES_M, CONTACT_CENTERLINES_M[1:])
    )
):
    raise ValueError("contact centreline scan must be strictly descending in [0.06, 0.15] m")
if not 90 <= ARGS.gripper_close_steps <= 360:
    raise ValueError("gripper close settling window must be in [90, 360] steps")
CONTACT_FILTERS = tuple(
    (
        model.name,
        f"/World/M1B/{model.name}/{link.name}/Collision_{collision.name}",
    )
    for model in SCENE.dynamic_models
    for link in model.links
    for collision in link.collisions
)
if not CONTACT_FILTERS:
    raise ValueError("M1B actuation probe requires dynamic collision filters")

from isaacsim import SimulationApp


simulation_app = SimulationApp(
    {
        "headless": True,
        "renderer": "RaytracedLighting",
        "active_gpu": 0,
        "physics_gpu": 0,
        "multi_gpu": False,
    }
)

import numpy as np
import carb.settings
import omni.kit.app
import omni.physx
import omni.timeline
import omni.usd
from isaacsim.core.simulation_manager import SimulationManager
from isaacsim.core.experimental.prims import RigidPrim
from pxr import (
    Gf,
    PhysicsSchemaTools,
    PhysxSchema,
    Sdf,
    Usd,
    UsdGeom,
    UsdPhysics,
)

PHYSICS_SETTINGS = carb.settings.get_settings()
DISABLE_CONTACT_PROCESSING_SETTING = "/physics/disableContactProcessing"
DISABLE_CONTACT_PROCESSING_BEFORE = PHYSICS_SETTINGS.get(
    DISABLE_CONTACT_PROCESSING_SETTING
)
PHYSICS_SETTINGS.set_bool(DISABLE_CONTACT_PROCESSING_SETTING, False)


extension_manager = omni.kit.app.get_app().get_extension_manager()
extension_manager.set_extension_enabled_immediate(
    "isaacsim.robot.experimental.manipulators.examples",
    True,
)
extension_manager.set_extension_enabled_immediate(
    "isaacsim.sensors.experimental.physics",
    True,
)

from isaacsim.robot.experimental.manipulators.examples.franka.franka import Franka
from isaacsim.sensors.experimental.physics import Contact, ContactSensor


ACTION_PROTOCOL = {
    "frame": "PANDA_JOINT_ORDER_BY_NAME",
    "units": "radian_arm_metre_finger",
    "dimensions": 9,
    "frequency_hz": 60,
    "normalization": "none",
    "source": "CALIBRATION_ONLY_INITIALIZATION_NOT_POLICY_ACTION",
}
HAND_PATH = "/World/Robot/panda_hand"
LEFT_FINGER_PATH = "/World/Robot/panda_leftfinger"
RIGHT_FINGER_PATH = "/World/Robot/panda_rightfinger"
ATTACH_JOINT_PATH = "/World/M1B/ActuationInternal/grasp_fixed_joint"
DOWNWARD_WXYZ = np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
OFFICIAL_FRANKA_CLOSED_POSITION_M = 0.0


class _PhysxContactCollector:
    """Own the official PhysX raw-contact subscription for one probe run."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._interface = omni.physx.get_physx_simulation_interface()
        self._subscription = self._interface.subscribe_contact_report_events(
            self._on_contact_report
        )

    def _events_from_headers(self, headers: Any) -> list[dict[str, object]]:
        timestamp_s = (
            SimulationManager.get_num_physics_steps()
            * SimulationManager.get_physics_dt()
        )
        events: list[dict[str, object]] = []
        for header in headers:
            if int(header.num_contact_data) <= 0:
                continue
            events.append(
                {
                    "time_s": float(timestamp_s),
                    "physics_step": SimulationManager.get_num_physics_steps(),
                    "event_type": int(header.type),
                    "actor0": str(
                        PhysicsSchemaTools.intToSdfPath(int(header.actor0))
                    ),
                    "actor1": str(
                        PhysicsSchemaTools.intToSdfPath(int(header.actor1))
                    ),
                    "collider0": str(
                        PhysicsSchemaTools.intToSdfPath(int(header.collider0))
                    ),
                    "collider1": str(
                        PhysicsSchemaTools.intToSdfPath(int(header.collider1))
                    ),
                    "contact_point_count": int(header.num_contact_data),
                }
            )
        return events

    def _on_contact_report(self, headers: Any, _contact_data: Any) -> None:
        self.events.extend(self._events_from_headers(headers))

    def cursor(self) -> int:
        return len(self.events)

    def events_after(self, cursor: int) -> tuple[int, list[dict[str, object]]]:
        return len(self.events), self.events[cursor:]

    def poll_current_report(self) -> list[dict[str, object]]:
        headers, _contact_data, _friction_anchors = (
            self._interface.get_full_contact_report()
        )
        return self._events_from_headers(headers)


def _live_pose(prim: RigidPrim) -> tuple[list[float], list[float]]:
    """Read a simulated rigid-body pose from the PhysX tensor backend.

    Reading an authored USD transform after the timeline starts can return the
    initial transform rather than the live PhysX pose.  The experimental rigid
    prim API is the official Isaac runtime interface and returns wxyz
    quaternions directly.
    """

    positions, orientations = prim.get_world_poses()
    return (
        _array_or_list(positions)[0],
        _array_or_list(orientations)[0],
    )


def _live_matrix(prim: RigidPrim) -> Gf.Matrix4d:
    position, orientation = _live_pose(prim)
    quaternion = Gf.Quatd(
        float(orientation[0]),
        Gf.Vec3d(*(float(value) for value in orientation[1:])),
    )
    matrix = Gf.Matrix4d(1.0)
    matrix.SetRotate(quaternion)
    matrix.SetTranslateOnly(Gf.Vec3d(*(float(value) for value in position)))
    return matrix


def _step_pose(
    robot: Franka,
    goal_position: np.ndarray,
    *,
    steps: int,
) -> dict[str, object]:
    errors: list[float] = []
    for _ in range(steps):
        robot.set_end_effector_pose(
            position=goal_position,
            orientation=DOWNWARD_WXYZ,
            ik_method="damped-least-squares",
        )
        simulation_app.update()
        _, position, _ = robot.get_current_state()
        errors.append(float(np.linalg.norm(position[0] - goal_position)))
    return {
        "goal_world_m": goal_position.tolist(),
        "steps": steps,
        "final_error_m": errors[-1],
        "minimum_error_m": min(errors),
    }


def _step_gripper(
    robot: Franka,
    position_m: float,
    *,
    steps: int,
    sensors: dict[str, ContactSensor] | None = None,
    contact_views: dict[str, RigidPrim] | None = None,
    contact_collector: _PhysxContactCollector | None = None,
) -> tuple[
    list[M1BContactSampleV1],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    samples: list[M1BContactSampleV1] = []
    sensor_frames: list[dict[str, object]] = []
    tensor_contact_frames: list[dict[str, object]] = []
    physx_contact_frames: list[dict[str, object]] = []
    contact_cursor = (
        contact_collector.cursor() if contact_collector is not None else 0
    )
    target = np.asarray([position_m, position_m], dtype=np.float32)
    for _ in range(steps):
        robot.set_gripper_position(target)
        simulation_app.update()
        if contact_collector is not None:
            contact_cursor, new_events = contact_collector.events_after(
                contact_cursor
            )
            new_events.extend(contact_collector.poll_current_report())
            new_events = [
                dict(event)
                for event in {
                    tuple(sorted(event.items())): event
                    for event in new_events
                }.values()
            ]
            timestamp_s = (
                SimulationManager.get_num_physics_steps()
                * SimulationManager.get_physics_dt()
            )
            for finger, finger_path in (
                ("left", LEFT_FINGER_PATH),
                ("right", RIGHT_FINGER_PATH),
            ):
                finger_events = [
                    event
                    for event in new_events
                    if any(
                        str(event[field]).startswith(finger_path)
                        for field in ("actor0", "actor1", "collider0", "collider1")
                    )
                ]
                collision_pairs = tuple(
                    sorted(
                        {
                            (
                                str(event["collider0"]),
                                str(event["collider1"]),
                            )
                            for event in finger_events
                        }
                    )
                )
                samples.append(
                    M1BContactSampleV1(
                        timestamp_s=float(timestamp_s),
                        finger=finger,
                        collision_pairs=collision_pairs,
                    )
                )
                physx_contact_frames.append(
                    {
                        "finger": finger,
                        "time_s": float(timestamp_s),
                        "physics_step": SimulationManager.get_num_physics_steps(),
                        "collision_pairs": [
                            list(pair) for pair in collision_pairs
                        ],
                        "events": finger_events,
                    }
                )
        if contact_views is not None:
            timestamp_s = (
                SimulationManager.get_num_physics_steps()
                * SimulationManager.get_physics_dt()
            )
            for finger, contact_view in contact_views.items():
                contact_force_matrix = _array_or_list(
                    contact_view.get_contact_force_matrix(
                        dt=SimulationManager.get_physics_dt()
                    )
                )
                pair_counts = _array_or_list(
                    contact_view.get_contact_force_data(
                        dt=SimulationManager.get_physics_dt()
                    )[4]
                )
                active_filter_indices = [
                    index
                    for index, count in enumerate(pair_counts[0])
                    if int(count) > 0
                ]
                collision_pairs = tuple(
                    (
                        LEFT_FINGER_PATH if finger == "left" else RIGHT_FINGER_PATH,
                        CONTACT_FILTERS[index][1],
                    )
                    for index in active_filter_indices
                )
                if contact_collector is None:
                    samples.append(
                        M1BContactSampleV1(
                            timestamp_s=float(timestamp_s),
                            finger=finger,
                            collision_pairs=collision_pairs,
                        )
                    )
                tensor_contact_frames.append(
                    {
                        "finger": finger,
                        "time_s": float(timestamp_s),
                        "physics_step": SimulationManager.get_num_physics_steps(),
                        "active_entities": [
                            CONTACT_FILTERS[index][0]
                            for index in active_filter_indices
                        ],
                        "active_collision_paths": [
                            CONTACT_FILTERS[index][1]
                            for index in active_filter_indices
                        ],
                        "pair_contact_counts": {
                            CONTACT_FILTERS[index][0]: int(count)
                            for index, count in enumerate(pair_counts[0])
                            if int(count) > 0
                        },
                        "contact_force_norms_n": {
                            CONTACT_FILTERS[index][0]: float(
                                np.linalg.norm(
                                    np.asarray(
                                        contact_force_matrix[0][index],
                                        dtype=float,
                                    )
                                )
                            )
                            for index in active_filter_indices
                        },
                    }
                )
        if sensors is None:
            continue
        for finger, sensor in sensors.items():
            frame = sensor.get_data()
            reading = sensor.get_sensor_reading()
            contacts = frame.get("contacts", [])
            collision_pairs = tuple(
                (str(contact["body0"]), str(contact["body1"]))
                for contact in contacts
            )
            sensor_frames.append(
                {
                    "finger": finger,
                    "time_s": float(frame.get("time", 0.0)),
                    "reading_valid": bool(reading.is_valid),
                    "physics_step": int(frame.get("physics_step", 0)),
                    "in_contact": bool(frame.get("in_contact", False)),
                    "force": float(frame.get("force", 0.0)),
                    "number_of_contacts": int(frame.get("number_of_contacts", 0)),
                    "collision_pairs": [list(pair) for pair in collision_pairs],
                }
            )
    return samples, sensor_frames, tensor_contact_frames, physx_contact_frames


def _decompose_frame(matrix: Gf.Matrix4d) -> tuple[Gf.Vec3f, Gf.Quatf]:
    position = Gf.Vec3f(matrix.ExtractTranslation())
    rotation = matrix.ExtractRotation().GetQuat()
    quaternion = Gf.Quatf(
        float(rotation.GetReal()),
        Gf.Vec3f(rotation.GetImaginary()),
    )
    return position, quaternion


def _attach_preserving_pose(
    entity: str,
    hand_prim: RigidPrim,
    object_prim: RigidPrim,
) -> dict[str, object]:
    stage = omni.usd.get_context().get_stage()
    body1_path = Sdf.Path(f"/World/M1B/{entity}/link")
    body0_path = Sdf.Path(HAND_PATH)
    body0 = stage.GetPrimAtPath(body0_path)
    body1 = stage.GetPrimAtPath(body1_path)
    if not body0.IsValid() or not body1.IsValid():
        raise RuntimeError(f"invalid attachment bodies: {body0_path}, {body1_path}")
    body0_world = _live_matrix(hand_prim)
    body1_world = _live_matrix(object_prim)
    body1_frame = body0_world * body1_world.GetInverse()
    local_pos1, local_rot1 = _decompose_frame(body1_frame)

    joint = UsdPhysics.FixedJoint.Define(stage, ATTACH_JOINT_PATH)
    joint.CreateBody0Rel().SetTargets([body0_path])
    joint.CreateBody1Rel().SetTargets([body1_path])
    joint.CreateLocalPos0Attr().Set(Gf.Vec3f(0.0))
    joint.CreateLocalRot0Attr().Set(Gf.Quatf(1.0))
    joint.CreateLocalPos1Attr().Set(local_pos1)
    joint.CreateLocalRot1Attr().Set(local_rot1)
    simulation_app.update()
    return {
        "joint_path": ATTACH_JOINT_PATH,
        "body0": str(body0_path),
        "body1": str(body1_path),
        "local_pos1_m": [float(value) for value in local_pos1],
        "local_rot1_wxyz": [
            float(local_rot1.GetReal()),
            *(float(value) for value in local_rot1.GetImaginary()),
        ],
    }


def _remove_attachment() -> None:
    stage = omni.usd.get_context().get_stage()
    if not stage.RemovePrim(ATTACH_JOINT_PATH):
        raise RuntimeError(f"failed to remove {ATTACH_JOINT_PATH}")
    simulation_app.update()


def _delta(first: list[float], second: list[float]) -> np.ndarray:
    return np.asarray(second, dtype=float) - np.asarray(first, dtype=float)


def _robot_snapshot(
    robot: Franka,
    *,
    hand_prim: RigidPrim,
    left_finger_prim: RigidPrim,
    right_finger_prim: RigidPrim,
    object_prim: RigidPrim,
) -> dict[str, object]:
    positions = robot.get_dof_positions()
    lower_limits, upper_limits = robot.get_dof_limits()
    return {
        "dof_positions": _array_or_list(positions),
        "dof_position_targets": _array_or_list(robot.get_dof_position_targets()),
        "dof_efforts": _array_or_list(robot.get_dof_efforts()),
        "dof_lower_limits": _array_or_list(lower_limits),
        "dof_upper_limits": _array_or_list(upper_limits),
        "dof_max_efforts": _array_or_list(robot.get_dof_max_efforts()),
        "hand_pose_world_wxyz": _live_pose(hand_prim),
        "left_finger_pose_world_wxyz": _live_pose(left_finger_prim),
        "right_finger_pose_world_wxyz": _live_pose(right_finger_prim),
        "object_pose_world_wxyz": _live_pose(object_prim),
    }


def _array_or_list(value: Any) -> list[object]:
    array = value.numpy() if hasattr(value, "numpy") else np.asarray(value)
    return array.tolist()


def _physics_prim_diagnostics(stage: Usd.Stage, path: str) -> dict[str, object]:
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return {"valid": False}
    return {
        "valid": True,
        "instanceable": prim.IsInstanceable(),
        "instance_proxy": prim.IsInstanceProxy(),
        "rigid_body_api": prim.HasAPI(UsdPhysics.RigidBodyAPI),
        "contact_report_api": prim.HasAPI(PhysxSchema.PhysxContactReportAPI),
        "collision_prim_paths": [
            str(descendant.GetPath())
            for descendant in Usd.PrimRange(prim, Usd.TraverseInstanceProxies())
            if descendant.HasAPI(UsdPhysics.CollisionAPI)
        ],
    }


def main() -> int:
    output = Path(ARGS.output)
    output.mkdir(parents=True, exist_ok=True)
    context = omni.usd.get_context()
    if not context.open_stage(ARGS.stage):
        raise RuntimeError(f"failed to open Isaac stage: {ARGS.stage}")
    for _ in range(5):
        simulation_app.update()
    stage = context.get_stage()
    # The dataset stage records render products and SyntheticData graphs for
    # provenance.  The actuation-only probe does not consume them; retaining
    # the graphs while stepping physics causes stale-frame errors and obscures
    # the contact evidence.
    if stage.GetPrimAtPath("/Render").IsValid():
        stage.RemovePrim("/Render")
        simulation_app.update()
    if UsdGeom.GetStageMetersPerUnit(stage) != 1.0:
        raise RuntimeError("Isaac M1B stage must use metres")
    for path in ("/World/Robot", HAND_PATH, LEFT_FINGER_PATH, RIGHT_FINGER_PATH):
        if not stage.GetPrimAtPath(path).IsValid():
            raise RuntimeError(f"official Franka stage is missing {path}")

    # The sensor step manager registers against SimulationManager.  Configure
    # the manager before constructing runtime sensors; doing this in the
    # opposite order leaves their callbacks attached to the superseded
    # simulation context and produces permanently invalid/empty readings.
    SimulationManager.setup_simulation(dt=1.0 / 60.0, device=ARGS.physics_device)
    target_object_path = f"/World/M1B/{ARGS.target_object}/link"
    robot = Franka(robot_path="/World/Robot", create_robot=False)
    contact_filter_paths = [path for _, path in CONTACT_FILTERS]
    hand_prim = RigidPrim(HAND_PATH)
    left_finger_prim = RigidPrim(
        LEFT_FINGER_PATH,
        contact_filter_paths=contact_filter_paths,
        max_contact_count=max(64, len(contact_filter_paths) * 16),
    )
    right_finger_prim = RigidPrim(
        RIGHT_FINGER_PATH,
        contact_filter_paths=contact_filter_paths,
        max_contact_count=max(64, len(contact_filter_paths) * 16),
    )
    target_object_prim = RigidPrim(target_object_path)
    left_sensor = ContactSensor(
        Contact.create(
            f"{LEFT_FINGER_PATH}/m1b_contact_sensor",
            min_threshold=0.0,
            max_threshold=1_000_000.0,
            radius=-1.0,
        )
    )
    right_sensor = ContactSensor(
        Contact.create(
            f"{RIGHT_FINGER_PATH}/m1b_contact_sensor",
            min_threshold=0.0,
            max_threshold=1_000_000.0,
            radius=-1.0,
        )
    )
    object_sensor = ContactSensor(
        Contact.create(
            f"{target_object_path}/m1b_diagnostic_contact_sensor",
            min_threshold=0.0,
            max_threshold=1_000_000.0,
            radius=-1.0,
        )
    )
    sensors = {
        "left": left_sensor,
        "right": right_sensor,
        "target_object_diagnostic_only": object_sensor,
    }
    for sensor in sensors.values():
        sensor.add_raw_contact_data_to_frame()
    # PhysX documents articulation-level ContactReportAPI as the reliable way
    # to receive contacts from any link in an articulation.  Link-local APIs
    # remain present for the per-finger sensors, while this root report drives
    # the raw collider-pair subscription used by the broker.
    articulation_contact_report = PhysxSchema.PhysxContactReportAPI.Apply(
        stage.GetPrimAtPath("/World/Robot")
    )
    articulation_contact_report.CreateThresholdAttr().Set(0.0)
    contact_collector = _PhysxContactCollector()

    # NVIDIA's contact-sensor fixture yields one Kit update after authoring
    # ContactReportAPI/sensor prims and before timeline play.  This flushes the
    # USD changes so PhysX sees reporting enabled while it builds the scene.
    simulation_app.update()
    omni.timeline.get_timeline_interface().play()
    # Match NVIDIA's Isaac Sim 6 contact-sensor tests exactly: author sensors
    # first, start the timeline, then explicitly initialize physics before the
    # first step.  Relying on an implicit first-update initialization yielded
    # valid timestamps but no PhysX contact reports on the referenced Franka.
    SimulationManager.initialize_physics()
    simulation_app.update()
    robot.reset_to_default_pose()
    _step_gripper(robot, 0.04, steps=60)

    target_spec_center = np.asarray(TARGET_MODEL.pose.xyz, dtype=np.float32)
    target_live_center = np.asarray(_live_pose(target_object_prim)[0], dtype=np.float32)
    pregrasp = target_live_center + np.asarray([0.0, 0.0, 0.27], dtype=np.float32)
    phases = {
        "pregrasp": _step_pose(robot, pregrasp, steps=150),
    }
    contact_attempts: list[dict[str, object]] = []
    feedback = None
    broker_internal = None
    selected_contact_goal: np.ndarray | None = None
    for contact_centerline_m in CONTACT_CENTERLINES_M:
        contact_goal = target_live_center + np.asarray(
            [0.0, 0.0, contact_centerline_m],
            dtype=np.float32,
        )
        contact_phase = _step_pose(robot, contact_goal, steps=120)
        pre_close_snapshot = _robot_snapshot(
            robot,
            hand_prim=hand_prim,
            left_finger_prim=left_finger_prim,
            right_finger_prim=right_finger_prim,
            object_prim=target_object_prim,
        )
        (
            samples,
            raw_contact_frames,
            tensor_contact_frames,
            physx_contact_frames,
        ) = _step_gripper(
            robot,
            OFFICIAL_FRANKA_CLOSED_POSITION_M,
            steps=ARGS.gripper_close_steps,
            sensors=sensors,
            contact_views={
                "left": left_finger_prim,
                "right": right_finger_prim,
            },
            contact_collector=contact_collector,
        )
        attempt_feedback, attempt_internal = broker_from_window(samples)
        nonempty_frames = [
            frame
            for frame in raw_contact_frames
            if frame["finger"] in {"left", "right"}
            and (frame["in_contact"] or frame["collision_pairs"])
        ]
        sensor_diagnostics = {
            finger: {
                "frame_count": len(finger_frames),
                "valid_frame_count": sum(
                    1 for frame in finger_frames if frame["reading_valid"]
                ),
                "first_time_s": (
                    None if not finger_frames else finger_frames[0]["time_s"]
                ),
                "last_time_s": (
                    None if not finger_frames else finger_frames[-1]["time_s"]
                ),
                "first_physics_step": (
                    None if not finger_frames else finger_frames[0]["physics_step"]
                ),
                "last_physics_step": (
                    None if not finger_frames else finger_frames[-1]["physics_step"]
                ),
                "maximum_force_n": max(
                    (float(frame["force"]) for frame in finger_frames),
                    default=0.0,
                ),
                "collision_pair_frame_counts": {
                    "|".join(pair): sum(
                        1
                        for frame in finger_frames
                        if pair in frame["collision_pairs"]
                    )
                    for pair in sorted(
                        {
                            pair
                            for frame in finger_frames
                            for pair in frame["collision_pairs"]
                        }
                    )
                },
            }
            for finger in sensors
            for finger_frames in (
                [
                    frame
                    for frame in raw_contact_frames
                    if frame["finger"] == finger
                ],
            )
        }
        post_close_snapshot = _robot_snapshot(
            robot,
            hand_prim=hand_prim,
            left_finger_prim=left_finger_prim,
            right_finger_prim=right_finger_prim,
            object_prim=target_object_prim,
        )
        object_motion_during_close_m = _delta(
            pre_close_snapshot["object_pose_world_wxyz"][0],
            post_close_snapshot["object_pose_world_wxyz"][0],
        )
        tensor_contact_diagnostics = {
            finger: {
                "frame_count": len(finger_frames),
                "contact_frame_count": sum(
                    1 for frame in finger_frames if frame["active_entities"]
                ),
                "entity_contact_frame_counts": {
                    entity: sum(
                        1
                        for frame in finger_frames
                        if entity in frame["active_entities"]
                    )
                    for entity in sorted(
                        {
                            entity
                            for frame in finger_frames
                            for entity in frame["active_entities"]
                        }
                    )
                },
                "maximum_force_n_by_entity": {
                    entity: max(
                        float(frame["contact_force_norms_n"].get(entity, 0.0))
                        for frame in finger_frames
                    )
                    for entity in sorted(
                        {
                            entity
                            for frame in finger_frames
                            for entity in frame["active_entities"]
                        }
                    )
                },
            }
            for finger in ("left", "right")
            for finger_frames in (
                [
                    frame
                    for frame in tensor_contact_frames
                    if frame["finger"] == finger
                ],
            )
        }
        physx_contact_diagnostics = {
            finger: {
                "frame_count": len(finger_frames),
                "contact_frame_count": sum(
                    1 for frame in finger_frames if frame["collision_pairs"]
                ),
                "collision_pair_frame_counts": {
                    "|".join(pair): sum(
                        1
                        for frame in finger_frames
                        if list(pair) in frame["collision_pairs"]
                    )
                    for pair in sorted(
                        {
                            tuple(pair)
                            for frame in finger_frames
                            for pair in frame["collision_pairs"]
                        }
                    )
                },
            }
            for finger in ("left", "right")
            for finger_frames in (
                [
                    frame
                    for frame in physx_contact_frames
                    if frame["finger"] == finger
                ],
            )
        }
        contact_attempts.append(
            {
                "contact_centerline_m": contact_centerline_m,
                "motion": contact_phase,
                "contact_feedback": attempt_feedback.__dict__,
                "broker_internal": attempt_internal,
                "sample_count": len(samples),
                "contact_source": (
                    "NVIDIA_PHYSX_SUBSCRIBE_CONTACT_REPORT_EVENTS"
                ),
                "physx_contact_diagnostics": physx_contact_diagnostics,
                "tensor_contact_diagnostics": tensor_contact_diagnostics,
                "sensor_diagnostics": sensor_diagnostics,
                "nonempty_contact_frame_count": len(nonempty_frames),
                "nonempty_contact_frames": nonempty_frames,
                "pre_close_snapshot": pre_close_snapshot,
                "post_close_snapshot": post_close_snapshot,
                "object_motion_during_close_m": (
                    object_motion_during_close_m.tolist()
                ),
            }
        )
        if attempt_feedback.grasp_success:
            feedback = attempt_feedback
            broker_internal = attempt_internal
            selected_contact_goal = contact_goal
            break
        _step_gripper(robot, 0.04, steps=45)
        _step_pose(robot, pregrasp, steps=90)
    if feedback is None or broker_internal is None:
        feedback = attempt_feedback
        broker_internal = attempt_internal
    evidence: dict[str, object] = {
        "schema_version": "IsaacM1BActuationProbeV1",
        "status": "CONTACT_GATE_REJECTED",
        "scope": "CALIBRATION_ONLY_INITIALIZATION",
        "not_policy_rollout": True,
        "official_robot": {
            "asset": "Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd",
            "variants": {"Gripper": "AlternateFinger", "Mesh": "Performance"},
            "available_variants": {
                set_name: list(
                    stage.GetPrimAtPath("/World/Robot")
                    .GetVariantSets()
                    .GetVariantSet(set_name)
                    .GetVariantNames()
                )
                for set_name in ("Gripper", "Mesh")
            },
            "local_simplified_robot_used": False,
            "base_pose": ROBOT_BASE_POSE.__dict__,
        },
        "scene_seed": SCENE.scene_seed,
        "source_hashes": {
            Path(ARGS.stage).name: sha256_file(ARGS.stage),
            Path(ARGS.sdf).name: SCENE.source_sdf_sha256,
            Path(ARGS.supervision).name: SCENE.source_supervision_sha256,
            Path(ARGS.urdf).name: sha256_file(ARGS.urdf),
        },
        "target_object": ARGS.target_object,
        "target_center_source": "CALIBRATION_ONLY_SDF_SPEC",
        "target_center_world_m": target_spec_center.tolist(),
        "target_live_center_world_m": target_live_center.tolist(),
        "action_protocol": ACTION_PROTOCOL,
        "gripper_close_settling": {
            "steps": ARGS.gripper_close_steps,
            "duration_s": ARGS.gripper_close_steps / ACTION_PROTOCOL["frequency_hz"],
            "position_target_m": OFFICIAL_FRANKA_CLOSED_POSITION_M,
            "source": (
                "NVIDIA_ISAAC_SIM_6_FRANKA_CLASS_"
                "gripper_closed_position_AND_close_gripper"
            ),
        },
        "physx_contact_processing": {
            "setting": DISABLE_CONTACT_PROCESSING_SETTING,
            "value_before_adapter_override": DISABLE_CONTACT_PROCESSING_BEFORE,
            "value_during_probe": PHYSICS_SETTINGS.get(
                DISABLE_CONTACT_PROCESSING_SETTING
            ),
            "required_for_raw_contact_evidence": True,
        },
        "physics_prim_diagnostics": {
            "robot_articulation": _physics_prim_diagnostics(
                stage, "/World/Robot"
            ),
            "left_finger": {
                **_physics_prim_diagnostics(stage, LEFT_FINGER_PATH),
                "physics_shape_count": left_finger_prim.num_shapes,
                "contact_filter_count": left_finger_prim.num_contact_filters,
            },
            "right_finger": {
                **_physics_prim_diagnostics(stage, RIGHT_FINGER_PATH),
                "physics_shape_count": right_finger_prim.num_shapes,
                "contact_filter_count": right_finger_prim.num_contact_filters,
            },
            "target_object": _physics_prim_diagnostics(stage, target_object_path),
        },
        "phases": phases,
        "contact_attempts": contact_attempts,
        "selected_contact_centerline_m": (
            None
            if selected_contact_goal is None
            else float(selected_contact_goal[2] - target_live_center[2])
        ),
        "contact_feedback": feedback.__dict__,
        "broker_internal": broker_internal,
    }
    if not feedback.grasp_success:
        (output / "actuation-probe.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            "M1B_ISAAC_ACTUATION_PROBE_NO_GO "
            + json.dumps(
                {
                    "status": evidence["status"],
                    "target_object": ARGS.target_object,
                    "contact_attempts": [
                        {
                            "contact_centerline_m": attempt["contact_centerline_m"],
                            "final_error_m": attempt["motion"]["final_error_m"],
                            "contact_feedback": attempt["contact_feedback"],
                            "nonempty_contact_frame_count": attempt[
                                "nonempty_contact_frame_count"
                            ],
                        }
                        for attempt in contact_attempts
                    ],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 1

    entity = str(broker_internal["actual_sim_entity_id"])
    hand_before, _ = _live_pose(hand_prim)
    object_path = f"/World/M1B/{entity}/link"
    object_prim = RigidPrim(object_path)
    object_before, _ = _live_pose(object_prim)
    attachment = _attach_preserving_pose(entity, hand_prim, object_prim)
    phases["lift"] = _step_pose(robot, pregrasp, steps=150)
    hand_after, _ = _live_pose(hand_prim)
    object_after, _ = _live_pose(object_prim)
    hand_motion = _delta(hand_before, hand_after)
    object_motion = _delta(object_before, object_after)
    follow_error_m = float(np.linalg.norm(hand_motion - object_motion))
    attached_follow_pass = bool(
        object_motion[2] >= 0.05
        and follow_error_m <= 0.02
    )

    _remove_attachment()
    _step_gripper(robot, 0.04, steps=60)
    object_detached_start, _ = _live_pose(object_prim)
    retreat = np.asarray(hand_after, dtype=np.float32) + np.asarray(
        [0.0, 0.0, 0.05],
        dtype=np.float32,
    )
    phases["detach_retreat"] = _step_pose(robot, retreat, steps=90)
    object_detached_end, _ = _live_pose(object_prim)
    detached_object_motion_m = float(
        np.linalg.norm(_delta(object_detached_start, object_detached_end))
    )
    detached_noncoupling_pass = detached_object_motion_m <= 0.01

    evidence.update(
        {
            "status": (
                "PASS"
                if attached_follow_pass and detached_noncoupling_pass
                else "PHYSICS_GATE_REJECTED"
            ),
            "attached_entity": entity,
            "attachment": attachment,
            "attached_follow": {
                "hand_motion_m": hand_motion.tolist(),
                "object_motion_m": object_motion.tolist(),
                "follow_error_m": follow_error_m,
                "object_lift_m": float(object_motion[2]),
                "passed": attached_follow_pass,
            },
            "detached_noncoupling": {
                "object_motion_m": detached_object_motion_m,
                "maximum_m": 0.01,
                "passed": detached_noncoupling_pass,
            },
        }
    )
    (output / "actuation-probe.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "M1B_ISAAC_ACTUATION_PROBE "
        + json.dumps(
            {
                "status": evidence["status"],
                "target_object": ARGS.target_object,
                "attached_entity": entity,
                "selected_contact_centerline_m": evidence[
                    "selected_contact_centerline_m"
                ],
                "attached_follow": evidence["attached_follow"],
                "detached_noncoupling": evidence["detached_noncoupling"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException as error:
        # Isaac's asynchronous renderer shutdown can abort while unwinding an
        # earlier exception and hide the actual root cause.  Preserve the
        # diagnostic first and let process teardown handle the failed run.
        print(
            "M1B_ISAAC_ACTUATION_PROBE_FATAL "
            + json.dumps(
                {
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise
    else:
        simulation_app.close()
    raise SystemExit(exit_code)
