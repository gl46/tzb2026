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
import math
from pathlib import Path
from typing import Any

from xh_agent.data.isaac_m1b import (
    M1B_URDF_SHA256,
    load_m1b_gripper_effort_limit,
    load_m1b_isaac_generated_scene,
    load_robot_base_pose,
    sha256_file,
)
from xh_agent.grasp.m1b_contact_window import (
    M1BContactSampleV1,
    broker_from_window,
)
from xh_agent.grasp.free_gap import (
    FREE_GAP_MIN_CLEARANCE_M,
    isaac_top_down_orientation_wxyz,
    select_free_gap_yaw_from_xy,
)


PRODUCTION_GRIPPER_EVIDENCE_STEPS = 132


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
    parser.add_argument(
        "--m2b-task-target-object",
        default=None,
        help=(
            "Supervision-only TaskSpec target for a physical WRONG_OBJECT "
            "injection probe; the broker still attaches actual finger contact."
        ),
    )
    parser.add_argument(
        "--calibration-offset-xyz-m",
        default="0,0,0",
        help=(
            "Calibration-only commanded target-centre bias in world XYZ. "
            "Never available to the policy path."
        ),
    )
    parser.add_argument("--physics-device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument(
        "--contact-centerlines-m",
        default="0.12,0.11,0.10,0.09,0.08",
        help="Calibration-only hand-origin offsets above the live object centre.",
    )
    parser.add_argument(
        "--gripper-close-steps",
        type=int,
        default=PRODUCTION_GRIPPER_EVIDENCE_STEPS,
        help=(
            "Production terminal-close plus post-close evidence steps at "
            "60 Hz; fixed to 72+60 outside the free-close diagnostic."
        ),
    )
    parser.add_argument(
        "--free-close-diagnostic",
        action="store_true",
        help=(
            "Require one 0.18-0.30 m centreline offset so the official "
            "fingertips close entirely above the target; never an attach trial."
        ),
    )
    parser.add_argument(
        "--same-process-reset-gate",
        action="store_true",
        help=(
            "After release, reset all dynamic bodies inside the same Kit process "
            "and prove physical non-coupling with a small production-IK jog."
        ),
    )
    parser.add_argument(
        "--calibration-free-gap-yaw",
        action="store_true",
        help=(
            "Select ADR-0016's top-grasp yaw from calibration-only live object "
            "centres using the accepted 15-degree maximum-clearance grid."
        ),
    )
    parser.add_argument(
        "--calibration-free-gap-yaw-override-rad",
        type=float,
        default=None,
        help=(
            "Diagnostic-only selection of one safe ADR-0016 grid candidate; "
            "requires --calibration-free-gap-yaw and never enters policy input."
        ),
    )
    parser.add_argument(
        "--preclose-before-contact-descent",
        action="store_true",
        help=(
            "Diagnostic staging candidate: apply the unchanged public-diameter "
            "preclose at near-distance pregrasp before the final vertical "
            "contact descent. All production pose/contact/attach gates remain "
            "unchanged."
        ),
    )
    parser.add_argument(
        "--natural-scene-stability-audit",
        action="store_true",
        help=(
            "Diagnostic-only audit of the unmodified SDF-derived scene under "
            "gravity. It is not part of the production grasp primitive."
        ),
    )
    parser.add_argument(
        "--m2b-inject-empty-grasp",
        action="store_true",
        help=(
            "Before the accepted grasp, close and lift in free space, prove "
            "that no object follows, reopen, and then run the accepted grasp."
        ),
    )
    parser.add_argument(
        "--m2b-inject-release-failure",
        action="store_true",
        help=(
            "After the accepted lift, issue open while the attachment remains, "
            "prove the object still follows, then retry detach/release."
        ),
    )
    return parser.parse_known_args()


ARGS, _UNKNOWN = parse_args()
SCENE = load_m1b_isaac_generated_scene(ARGS.sdf, ARGS.supervision)
ROBOT_BASE_POSE = load_robot_base_pose(ARGS.urdf)
SOURCE_GRIPPER_MAX_EFFORT_N = load_m1b_gripper_effort_limit(ARGS.urdf)
if sha256_file(ARGS.urdf) != M1B_URDF_SHA256:
    raise ValueError("M1B actuation probe URDF hash mismatch")
TARGET_MODEL = next(
    (model for model in SCENE.dynamic_models if model.name == ARGS.target_object),
    None,
)
if TARGET_MODEL is None:
    raise ValueError(f"target object is absent from scene: {ARGS.target_object}")
M2B_TASK_TARGET_MODEL = next(
    (
        model
        for model in SCENE.dynamic_models
        if model.name == ARGS.m2b_task_target_object
    ),
    None,
)
if ARGS.m2b_task_target_object is not None and M2B_TASK_TARGET_MODEL is None:
    raise ValueError(
        f"M2B task target is absent from scene: {ARGS.m2b_task_target_object}"
    )
CONTACT_CENTERLINES_M = tuple(
    float(value) for value in ARGS.contact_centerlines_m.split(",")
)
CALIBRATION_OFFSET_XYZ_M = tuple(
    float(value) for value in ARGS.calibration_offset_xyz_m.split(",")
)
if (
    len(CALIBRATION_OFFSET_XYZ_M) != 3
    or not all(math.isfinite(value) for value in CALIBRATION_OFFSET_XYZ_M)
    or any(abs(value) > 0.02 for value in CALIBRATION_OFFSET_XYZ_M)
):
    raise ValueError(
        "calibration offset must be a finite XYZ triple within +/-0.02 m"
    )
if ARGS.free_close_diagnostic:
    if (
        len(CONTACT_CENTERLINES_M) != 1
        or not 0.18 <= CONTACT_CENTERLINES_M[0] <= 0.30
    ):
        raise ValueError(
            "free-close diagnostic requires one centreline in [0.18, 0.30] m"
        )
elif (
    not CONTACT_CENTERLINES_M
    or any(not 0.06 <= value <= 0.15 for value in CONTACT_CENTERLINES_M)
    or any(
        later >= earlier
        for earlier, later in zip(CONTACT_CENTERLINES_M, CONTACT_CENTERLINES_M[1:])
    )
):
    raise ValueError(
        "contact centreline scan must be strictly descending in [0.06, 0.15] m"
    )
if not 90 <= ARGS.gripper_close_steps <= 360:
    raise ValueError("gripper close settling window must be in [90, 360] steps")
if (
    not ARGS.free_close_diagnostic
    and ARGS.gripper_close_steps != PRODUCTION_GRIPPER_EVIDENCE_STEPS
):
    raise ValueError(
        "production close evidence must preserve the accepted 72+60 steps"
    )
if ARGS.calibration_free_gap_yaw_override_rad is not None and (
    not ARGS.calibration_free_gap_yaw
    or not math.isfinite(ARGS.calibration_free_gap_yaw_override_rad)
):
    raise ValueError(
        "calibration yaw override requires finite calibration free-gap yaw"
    )
CONTACT_FILTERS = tuple(
    (
        model.name,
        f"/World/M1B/{model.name}/{link.name}",
    )
    for model in SCENE.dynamic_models
    for link in model.links
    if link.collisions
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
    Vt,
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
OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX = 7
PRODUCTION_EE_POSITION_ERROR_GATE_M = 0.020
M1B_PRECLOSE_PUBLIC_DIAMETER_MARGIN_M = 0.011
M1B_SOURCE_FALLBACK_FINGER_BOARD_THICKNESS_M = 0.006
NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M = 0.0
NVIDIA_DEFAULT_COLLISION_INNER_FACE_BOUND_ABS_MAX_M = 0.000084
M1B_CLOSE_SQUEEZE_M = 0.002
M1B_PRECLOSE_STEPS = 48
M1B_PRECLOSE_SETTLE_STEPS = 24
M1B_TERMINAL_CLOSE_STEPS = 72
M1B_POST_CLOSE_OBSERVATION_STEPS = 60
ISAACLAB_6_FRANKA_CONFIG_COMMIT = (
    "10e969aec0c1da133c13d2b7ff7ff88641c86da6"
)
ISAACLAB_FRANKA_HAND_STIFFNESS_N_PER_M = 2_000.0
ISAACLAB_FRANKA_HAND_DAMPING_N_S_PER_M = 100.0


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
    orientation_wxyz: np.ndarray | None = None,
) -> dict[str, object]:
    orientation = (
        DOWNWARD_WXYZ if orientation_wxyz is None else orientation_wxyz
    )
    errors: list[float] = []
    for _ in range(steps):
        robot.set_end_effector_pose(
            position=goal_position,
            orientation=orientation,
            ik_method="damped-least-squares",
        )
        simulation_app.update()
        _, position, _ = robot.get_current_state()
        errors.append(float(np.linalg.norm(position[0] - goal_position)))
    return {
        "goal_world_m": goal_position.tolist(),
        "orientation_world_wxyz": orientation.tolist(),
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
        # The official USD drives panda_finger_joint1 and authors
        # panda_finger_joint2 as a zero-effort PhysxMimicJoint.  Sending a
        # target to both tensor DOFs makes the mimic solver rebound around
        # 15.5 mm in free space.  Command only the driven joint and let the
        # official mimic constraint produce the symmetric second motion.
        robot.set_dof_position_targets(
            target[:1].reshape(1, 1),
            dof_indices=[OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX],
        )
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
            gripper_positions = _array_or_list(robot.get_dof_positions())[0][-2:]
            gripper_velocities = _array_or_list(robot.get_dof_velocities())[0][
                -2:
            ]
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
                physx_contact_frames.append(
                    {
                        "finger": finger,
                        "time_s": float(timestamp_s),
                        "physics_step": SimulationManager.get_num_physics_steps(),
                        "gripper_positions_m": gripper_positions,
                        "gripper_velocities_mps": gripper_velocities,
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
                force_norms = [
                    float(
                        np.linalg.norm(
                            np.asarray(
                                contact_force_matrix[0][index],
                                dtype=float,
                            )
                        )
                    )
                    for index in range(len(CONTACT_FILTERS))
                ]
                active_filter_indices = [
                    index
                    for index, count in enumerate(pair_counts[0])
                    if int(count) > 0 and force_norms[index] > 0.0
                ]
                collision_pairs = tuple(
                    (
                        LEFT_FINGER_PATH if finger == "left" else RIGHT_FINGER_PATH,
                        CONTACT_FILTERS[index][1],
                    )
                    for index in active_filter_indices
                )
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
                            CONTACT_FILTERS[index][0]: force_norms[index]
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


def _wait_for_natural_scene_stability(
    scene_dynamic_prims: dict[str, RigidPrim],
    *,
    minimum_settling_steps: int = 120,
    stability_window_steps: int = 30,
    maximum_stability_windows: int = 60,
    stability_displacement_limit_m: float = 0.00025,
) -> dict[str, object]:
    """Wait for the unmodified SDF-derived physics scene to become quiet."""

    start_poses = {
        entity: _live_pose(prim)
        for entity, prim in scene_dynamic_prims.items()
    }
    initial_sleep_thresholds = {
        entity: float(_array_or_list(prim.get_sleep_thresholds())[0][0])
        for entity, prim in scene_dynamic_prims.items()
    }
    initial_gravity_enabled = {
        entity: bool(_array_or_list(prim.get_enabled_gravities())[0][0])
        for entity, prim in scene_dynamic_prims.items()
    }
    for _ in range(minimum_settling_steps):
        simulation_app.update()
    previous_poses = {
        entity: _live_pose(prim)
        for entity, prim in scene_dynamic_prims.items()
    }
    windows: list[dict[str, object]] = []
    passed = False
    final_displacement_m: dict[str, float] = {}
    for window_index in range(maximum_stability_windows):
        for _ in range(stability_window_steps):
            simulation_app.update()
        current_poses = {
            entity: _live_pose(prim)
            for entity, prim in scene_dynamic_prims.items()
        }
        final_displacement_m = {
            entity: float(
                np.linalg.norm(
                    _delta(
                        previous_poses[entity][0],
                        current_poses[entity][0],
                    )
                )
            )
            for entity in scene_dynamic_prims
        }
        maximum_displacement_m = max(
            final_displacement_m.values(),
            default=math.inf,
        )
        windows.append(
            {
                "index": window_index,
                "duration_s": (
                    stability_window_steps / ACTION_PROTOCOL["frequency_hz"]
                ),
                "maximum_displacement_m": maximum_displacement_m,
                "maximum_displacement_entity": (
                    max(final_displacement_m, key=final_displacement_m.get)
                    if final_displacement_m
                    else None
                ),
            }
        )
        if maximum_displacement_m <= stability_displacement_limit_m:
            passed = True
            previous_poses = current_poses
            break
        previous_poses = current_poses

    final_poses = previous_poses
    total_displacement_m = {
        entity: float(
            np.linalg.norm(
                _delta(start_poses[entity][0], final_poses[entity][0])
            )
        )
        for entity in scene_dynamic_prims
    }
    return {
        "source": (
            "SDF_DERIVED_PHYSICS_NATURAL_GRAVITY_SETTLING_"
            "NO_STATE_FREEZE"
        ),
        "minimum_settling_window_s": (
            minimum_settling_steps / ACTION_PROTOCOL["frequency_hz"]
        ),
        "stability_window_s": (
            stability_window_steps / ACTION_PROTOCOL["frequency_hz"]
        ),
        "maximum_stability_window_count": maximum_stability_windows,
        "observed_stability_window_count": len(windows),
        "elapsed_simulation_s": (
            minimum_settling_steps
            + len(windows) * stability_window_steps
        )
        / ACTION_PROTOCOL["frequency_hz"],
        "stability_displacement_limit_m": stability_displacement_limit_m,
        "final_stability_displacement_m": final_displacement_m,
        "maximum_final_stability_displacement_m": max(
            final_displacement_m.values(),
            default=math.inf,
        ),
        "total_displacement_m": total_displacement_m,
        "maximum_total_displacement_m": max(
            total_displacement_m.values(),
            default=math.inf,
        ),
        "windows": windows,
        "initial_sleep_thresholds": initial_sleep_thresholds,
        "initial_gravity_enabled": initial_gravity_enabled,
        "gravity_disabled": False,
        "velocities_zeroed": False,
        "sleep_threshold_modified": False,
        "passed": passed,
    }


def _restore_calibration_scene_after_orientation_scan(
    scene_dynamic_prims: dict[str, RigidPrim],
    initial_poses: dict[str, tuple[list[float], list[float]]],
) -> dict[str, object]:
    """Undo physical scene mutation caused by the calibration IK scan.

    ADR-0016's orientation-feasibility scan is a precondition check, not part
    of the grasp trajectory.  The Isaac probe currently realizes that check
    with the production IK executor, so an open official finger can touch a
    freely resting cylinder while a candidate is evaluated.  Restore the
    calibration-only live scene snapshot before executing the selected
    production primitive; simulator truth remains outside the policy path.
    """

    minimum_settling_steps = 120
    stability_window_steps = 30
    stability_displacement_limit_m = 0.00025
    before_restore = {
        entity: _live_pose(prim)
        for entity, prim in scene_dynamic_prims.items()
    }
    for entity, prim in scene_dynamic_prims.items():
        position, orientation = initial_poses[entity]
        prim.set_world_poses(
            positions=np.asarray([position], dtype=np.float32),
            orientations=np.asarray([orientation], dtype=np.float32),
        )
        prim.set_velocities(
            linear_velocities=np.zeros((1, 3), dtype=np.float32),
            angular_velocities=np.zeros((1, 3), dtype=np.float32),
        )
    for _ in range(minimum_settling_steps):
        simulation_app.update()
    pre_isolation_poses = {
        entity: _live_pose(prim)
        for entity, prim in scene_dynamic_prims.items()
    }
    original_gravity_enabled = {
        entity: bool(_array_or_list(prim.get_enabled_gravities())[0][0])
        for entity, prim in scene_dynamic_prims.items()
    }
    original_sleep_thresholds = {
        entity: float(_array_or_list(prim.get_sleep_thresholds())[0][0])
        for entity, prim in scene_dynamic_prims.items()
    }
    isolation_sleep_threshold = 1_000_000.0
    for prim in scene_dynamic_prims.values():
        prim.set_enabled_gravities(False)
        prim.set_sleep_thresholds(isolation_sleep_threshold)
        prim.set_velocities(
            linear_velocities=np.zeros((1, 3), dtype=np.float32),
            angular_velocities=np.zeros((1, 3), dtype=np.float32),
        )
    for _ in range(stability_window_steps):
        simulation_app.update()
    after_restore = {
        entity: _live_pose(prim)
        for entity, prim in scene_dynamic_prims.items()
    }
    for entity, prim in scene_dynamic_prims.items():
        prim.set_enabled_gravities(original_gravity_enabled[entity])
        prim.set_sleep_thresholds(original_sleep_thresholds[entity])
    scan_displacement_m = {
        entity: float(
            np.linalg.norm(
                _delta(
                    initial_poses[entity][0],
                    before_restore[entity][0],
                )
            )
        )
        for entity in scene_dynamic_prims
    }
    restore_error_m = {
        entity: float(
            np.linalg.norm(
                _delta(
                    initial_poses[entity][0],
                    after_restore[entity][0],
                )
            )
        )
        for entity in scene_dynamic_prims
    }
    stability_displacement_m = {
        entity: float(
            np.linalg.norm(
                _delta(
                    pre_isolation_poses[entity][0],
                    after_restore[entity][0],
                )
            )
        )
        for entity in scene_dynamic_prims
    }
    maximum_stability_displacement_m = max(
        stability_displacement_m.values(),
        default=math.inf,
    )
    passed = (
        maximum_stability_displacement_m
        <= stability_displacement_limit_m
    )
    return {
        "source": (
            "CALIBRATION_ONLY_ORIENTATION_SCAN_SCENE_RESTORATION_"
            "NOT_POLICY_INPUT"
        ),
        "performed": True,
        "minimum_settling_window_s": (
            minimum_settling_steps / ACTION_PROTOCOL["frequency_hz"]
        ),
        "stability_window_s": (
            stability_window_steps / ACTION_PROTOCOL["frequency_hz"]
        ),
        "scan_displacement_m": scan_displacement_m,
        "maximum_scan_displacement_m": max(
            scan_displacement_m.values(),
            default=math.inf,
        ),
        "restore_error_m": restore_error_m,
        "maximum_restore_error_m": max(
            restore_error_m.values(),
            default=math.inf,
        ),
        "restore_error_is_acceptance_gate": False,
        "stability_displacement_m": stability_displacement_m,
        "maximum_stability_displacement_m": (
            maximum_stability_displacement_m
        ),
        "stability_displacement_limit_m": stability_displacement_limit_m,
        "passive_motion_isolation": {
            "gravity_disabled_during_quiet_window": True,
            "gravity_restored_after_quiet_window": True,
            "velocities_zeroed_before_quiet_window": True,
            "sleep_threshold_during_quiet_window": (
                isolation_sleep_threshold
            ),
            "sleep_thresholds_restored_after_quiet_window": True,
            "original_gravity_enabled": original_gravity_enabled,
            "original_sleep_thresholds": original_sleep_thresholds,
        },
        "passed": passed,
    }


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
    stiffnesses, dampings = robot.get_dof_gains()
    (
        static_frictions,
        dynamic_frictions,
        viscous_frictions,
    ) = robot.get_dof_friction_properties()
    (
        speed_effort_gradients,
        maximum_actuator_velocities,
        velocity_dependent_resistances,
    ) = robot.get_dof_drive_model_properties()
    return {
        "dof_positions": _array_or_list(positions),
        "dof_velocities": _array_or_list(robot.get_dof_velocities()),
        "dof_position_targets": _array_or_list(robot.get_dof_position_targets()),
        "dof_efforts": _array_or_list(robot.get_dof_efforts()),
        "dof_projected_joint_forces": _array_or_list(
            robot.get_dof_projected_joint_forces()
        ),
        "dof_lower_limits": _array_or_list(lower_limits),
        "dof_upper_limits": _array_or_list(upper_limits),
        "dof_max_efforts": _array_or_list(robot.get_dof_max_efforts()),
        "dof_max_velocities": _array_or_list(robot.get_dof_max_velocities()),
        "dof_stiffnesses": _array_or_list(stiffnesses),
        "dof_dampings": _array_or_list(dampings),
        "dof_static_friction_efforts": _array_or_list(static_frictions),
        "dof_dynamic_friction_efforts": _array_or_list(dynamic_frictions),
        "dof_viscous_friction_coefficients": _array_or_list(
            viscous_frictions
        ),
        "dof_speed_effort_gradients": _array_or_list(speed_effort_gradients),
        "dof_maximum_actuator_velocities": _array_or_list(
            maximum_actuator_velocities
        ),
        "dof_velocity_dependent_resistances": _array_or_list(
            velocity_dependent_resistances
        ),
        "hand_pose_world_wxyz": _live_pose(hand_prim),
        "left_finger_pose_world_wxyz": _live_pose(left_finger_prim),
        "right_finger_pose_world_wxyz": _live_pose(right_finger_prim),
        "object_pose_world_wxyz": _live_pose(object_prim),
    }


def _same_process_reset_gate(
    robot: Franka,
    *,
    reset_prims: dict[str, RigidPrim],
    initial_poses: dict[str, tuple[list[float], list[float]]],
    hand_prim: RigidPrim,
) -> dict[str, object]:
    """Reset through Isaac runtime APIs, then prove objects are not hand-coupled."""

    minimum_settling_steps = 120
    stability_window_steps = 30
    stability_displacement_limit_m = 0.00025
    minimum_hand_jog_motion_m = 0.020
    maximum_allowed_object_jog_motion_m = 0.001
    stage = omni.usd.get_context().get_stage()
    attachment_absent_before = not stage.GetPrimAtPath(ATTACH_JOINT_PATH).IsValid()
    robot.reset_to_default_pose()
    _step_gripper(robot, 0.04, steps=60)
    for entity, prim in reset_prims.items():
        position, orientation = initial_poses[entity]
        prim.set_world_poses(
            positions=np.asarray([position], dtype=np.float32),
            orientations=np.asarray([orientation], dtype=np.float32),
        )
        prim.set_velocities(
            linear_velocities=np.zeros((1, 3), dtype=np.float32),
            angular_velocities=np.zeros((1, 3), dtype=np.float32),
        )
    # The reset transaction owns privileged state initialization.  Give every
    # cylinder the approved two-second minimum settling interval, then require
    # a bounded quiet window before the jog.  Tilted cylinders can legitimately
    # fall to a support-stable pose after reset; measuring the jog while that
    # motion is still in progress would be a false coupling positive.
    for _ in range(minimum_settling_steps):
        simulation_app.update()

    pre_isolation_poses = {
        entity: _live_pose(prim) for entity, prim in reset_prims.items()
    }
    original_gravity_enabled = {
        entity: bool(_array_or_list(prim.get_enabled_gravities())[0][0])
        for entity, prim in reset_prims.items()
    }
    original_sleep_thresholds = {
        entity: float(_array_or_list(prim.get_sleep_thresholds())[0][0])
        for entity, prim in reset_prims.items()
    }
    reset_jog_sleep_threshold = 1_000_000.0
    for prim in reset_prims.values():
        # A tilted free cylinder can still be rolling after the mandatory
        # two-second window.  Zero velocity and gravity isolation remove only
        # passive reset motion during the bounded jog; any surviving physical
        # attachment still constrains the body and therefore moves it.
        prim.set_enabled_gravities(False)
        prim.set_sleep_thresholds(reset_jog_sleep_threshold)
        prim.set_velocities(
            linear_velocities=np.zeros((1, 3), dtype=np.float32),
            angular_velocities=np.zeros((1, 3), dtype=np.float32),
        )
    for _ in range(stability_window_steps):
        simulation_app.update()
    settled_poses = {
        entity: _live_pose(prim) for entity, prim in reset_prims.items()
    }
    isolated_displacement_m = {
        entity: float(
            np.linalg.norm(
                _delta(
                    pre_isolation_poses[entity][0],
                    settled_poses[entity][0],
                )
            )
        )
        for entity in reset_prims
    }
    maximum_isolated_displacement_m = max(
        isolated_displacement_m.values(),
        default=math.inf,
    )
    settling_stable = (
        maximum_isolated_displacement_m <= stability_displacement_limit_m
    )
    settling_windows = [
        {
            "index": 0,
            "duration_s": stability_window_steps
            / ACTION_PROTOCOL["frequency_hz"],
            "object_displacement_m": isolated_displacement_m,
            "maximum_object_displacement_m": (
                maximum_isolated_displacement_m
            ),
            "gravity_isolated": True,
            "velocities_zeroed_before_window": True,
        }
    ]
    reset_errors_m = {
        entity: float(np.linalg.norm(_delta(initial_poses[entity][0], pose[0])))
        for entity, pose in settled_poses.items()
    }
    hand_before, _ = _live_pose(hand_prim)
    _, current_ee_position, _ = robot.get_current_state()
    jog_goal = np.asarray(current_ee_position[0], dtype=np.float32) + np.asarray(
        [0.025, 0.0, 0.015],
        dtype=np.float32,
    )
    jog = _step_pose(robot, jog_goal, steps=120)
    hand_after, _ = _live_pose(hand_prim)
    after_jog_poses = {
        entity: _live_pose(prim) for entity, prim in reset_prims.items()
    }
    object_jog_motion_m = {
        entity: float(np.linalg.norm(_delta(settled_poses[entity][0], pose[0])))
        for entity, pose in after_jog_poses.items()
    }
    for entity, prim in reset_prims.items():
        prim.set_enabled_gravities(original_gravity_enabled[entity])
        prim.set_sleep_thresholds(original_sleep_thresholds[entity])
    hand_jog_motion_m = float(np.linalg.norm(_delta(hand_before, hand_after)))
    attachment_absent_after = not stage.GetPrimAtPath(ATTACH_JOINT_PATH).IsValid()
    maximum_reset_error_m = max(reset_errors_m.values(), default=math.inf)
    maximum_object_jog_motion_m = max(
        object_jog_motion_m.values(),
        default=math.inf,
    )
    passed = bool(
        attachment_absent_before
        and attachment_absent_after
        and settling_stable
        and hand_jog_motion_m >= minimum_hand_jog_motion_m
        and maximum_object_jog_motion_m <= maximum_allowed_object_jog_motion_m
    )
    return {
        "status": "PASS" if passed else "RESET_GATE_REJECTED",
        "passed": passed,
        "scope": "RESET_INFRASTRUCTURE_SUPERVISION_NOT_POLICY_INPUT",
        "reset_method": (
            "OFFICIAL_ISAAC_RIGIDPRIM_RUNTIME_POSE_AND_ZERO_VELOCITY_"
            "PLUS_OFFICIAL_FRANKA_DEFAULT_POSE"
        ),
        "minimum_settling_window_s": (
            minimum_settling_steps / ACTION_PROTOCOL["frequency_hz"]
        ),
        "settling_stability_windows": settling_windows,
        "settling_stable": settling_stable,
        "settling_stability_displacement_limit_m": (
            stability_displacement_limit_m
        ),
        "passive_motion_isolation": {
            "source": (
                "RESET_INFRASTRUCTURE_GRAVITY_ISOLATED_JOG_AFTER_"
                "MANDATORY_2S_SETTLE"
            ),
            "gravity_disabled_during_jog": True,
            "velocities_zeroed_before_quiet_window": True,
            "gravity_restored_after_jog": True,
            "original_gravity_enabled": original_gravity_enabled,
            "sleep_threshold_during_jog": reset_jog_sleep_threshold,
            "sleep_thresholds_restored_after_jog": True,
            "original_sleep_thresholds": original_sleep_thresholds,
        },
        "jog_path": "PRODUCTION_OFFICIAL_FRANKA_DAMPED_LEAST_SQUARES_IK",
        "jog": jog,
        "hand_jog_motion_m": hand_jog_motion_m,
        "minimum_hand_jog_motion_m": minimum_hand_jog_motion_m,
        "reset_errors_m": reset_errors_m,
        "maximum_reset_error_m": maximum_reset_error_m,
        "reset_error_is_acceptance_gate": False,
        "object_jog_motion_m": object_jog_motion_m,
        "maximum_object_jog_motion_m": maximum_object_jog_motion_m,
        "maximum_allowed_object_jog_motion_m": (
            maximum_allowed_object_jog_motion_m
        ),
        "attachment_absent_before_jog": attachment_absent_before,
        "attachment_absent_after_jog": attachment_absent_after,
    }


def _array_or_list(value: Any) -> list[object]:
    array = value.numpy() if hasattr(value, "numpy") else np.asarray(value)
    return array.tolist()


def _json_native_usd_metadata(value: Any) -> Any:
    """Convert USD customData containers without changing their values."""
    if isinstance(value, dict):
        return {
            str(key): _json_native_usd_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, Vt.StringArray)):
        return [_json_native_usd_metadata(item) for item in value]
    return value


def _physics_prim_diagnostics(stage: Usd.Stage, path: str) -> dict[str, object]:
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return {"valid": False}
    self_collisions = prim.GetAttribute(
        "physxArticulation:enabledSelfCollisions"
    )
    return {
        "valid": True,
        "instanceable": prim.IsInstanceable(),
        "instance_proxy": prim.IsInstanceProxy(),
        "rigid_body_api": prim.HasAPI(UsdPhysics.RigidBodyAPI),
        "contact_report_api": prim.HasAPI(PhysxSchema.PhysxContactReportAPI),
        "enabled_self_collisions": (
            self_collisions.Get() if self_collisions.IsValid() else None
        ),
        "collision_prim_paths": [
            str(descendant.GetPath())
            for descendant in Usd.PrimRange(prim, Usd.TraverseInstanceProxies())
            if descendant.HasAPI(UsdPhysics.CollisionAPI)
        ],
    }


def _joint_prim_diagnostics(stage: Usd.Stage, path: str) -> dict[str, object]:
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return {"valid": False}
    selected_attributes: dict[str, object] = {}
    for attribute in prim.GetAttributes():
        name = attribute.GetName()
        if any(
            token in name.lower()
            for token in (
                "mimic",
                "drive",
                "friction",
                "limit",
                "gear",
                "target",
            )
        ):
            value = attribute.Get()
            selected_attributes[name] = (
                value
                if value is None
                or isinstance(value, (bool, float, int, str))
                else str(value)
            )
    return {
        "valid": True,
        "applied_schemas": list(prim.GetAppliedSchemas()),
        "attributes": selected_attributes,
    }


def _enable_contact_reporting_on_colliders(
    stage: Usd.Stage,
    root_paths: tuple[str, ...],
) -> dict[str, object]:
    applied_paths: list[str] = []
    skipped_instance_proxy_paths: list[str] = []
    for root_path in root_paths:
        root = stage.GetPrimAtPath(root_path)
        if not root.IsValid():
            continue
        for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
            if not prim.HasAPI(UsdPhysics.CollisionAPI):
                continue
            if prim.IsInstanceProxy():
                skipped_instance_proxy_paths.append(str(prim.GetPath()))
                continue
            report = PhysxSchema.PhysxContactReportAPI.Apply(prim)
            report.CreateThresholdAttr().Set(0.0)
            applied_paths.append(str(prim.GetPath()))
    return {
        "applied_paths": applied_paths,
        "skipped_instance_proxy_paths": skipped_instance_proxy_paths,
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
    official_asset_contract = _json_native_usd_metadata(
        stage.GetPrimAtPath("/World/Robot").GetCustomDataByKey(
            "xhM1BOfficialAssetContract"
        )
    )
    if (
        not isinstance(official_asset_contract, dict)
        or official_asset_contract.get("provenance")
        != "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"
        or official_asset_contract.get("local_simplified_robot_used") is not False
        or official_asset_contract.get("variants")
        != {"Gripper": "Default", "Mesh": "Performance"}
    ):
        raise RuntimeError(
            "Isaac stage lacks the self-described official Default Franka contract"
        )

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
    sensors = {
        "left": left_sensor,
        "right": right_sensor,
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
    collider_contact_reporting = _enable_contact_reporting_on_colliders(
        stage,
        (LEFT_FINGER_PATH, RIGHT_FINGER_PATH),
    )
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
    (
        official_default_stiffnesses_raw,
        official_default_dampings_raw,
    ) = robot.get_dof_gains()
    official_default_stiffnesses = np.asarray(
        _array_or_list(official_default_stiffnesses_raw),
        dtype=np.float32,
    )
    official_default_dampings = np.asarray(
        _array_or_list(official_default_dampings_raw),
        dtype=np.float32,
    )
    isaaclab_aligned_stiffnesses = official_default_stiffnesses.copy()
    isaaclab_aligned_dampings = official_default_dampings.copy()
    isaaclab_aligned_stiffnesses[
        :, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
    ] = ISAACLAB_FRANKA_HAND_STIFFNESS_N_PER_M
    isaaclab_aligned_dampings[
        :, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
    ] = ISAACLAB_FRANKA_HAND_DAMPING_N_S_PER_M
    robot.set_dof_gains(
        stiffnesses=isaaclab_aligned_stiffnesses,
        dampings=isaaclab_aligned_dampings,
    )
    official_default_max_efforts = np.asarray(
        _array_or_list(robot.get_dof_max_efforts()),
        dtype=np.float32,
    )
    source_aligned_max_efforts = official_default_max_efforts.copy()
    source_aligned_max_efforts[
        :, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
    ] = SOURCE_GRIPPER_MAX_EFFORT_N
    robot.set_dof_max_efforts(source_aligned_max_efforts)
    simulation_app.update()
    observed_stiffnesses_raw, observed_dampings_raw = robot.get_dof_gains()
    observed_stiffnesses = np.asarray(
        _array_or_list(observed_stiffnesses_raw),
        dtype=np.float32,
    )
    observed_dampings = np.asarray(
        _array_or_list(observed_dampings_raw),
        dtype=np.float32,
    )
    observed_source_aligned_max_efforts = np.asarray(
        _array_or_list(robot.get_dof_max_efforts()),
        dtype=np.float32,
    )
    observed_gripper_max_effort_n = float(
        observed_source_aligned_max_efforts[
            0, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
        ]
    )
    if not math.isclose(
        observed_gripper_max_effort_n,
        SOURCE_GRIPPER_MAX_EFFORT_N,
        abs_tol=1e-6,
    ):
        raise RuntimeError(
            "official Franka driven-finger effort did not accept the "
            "source production limit"
        )
    observed_gripper_stiffness = float(
        observed_stiffnesses[0, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX]
    )
    observed_gripper_damping = float(
        observed_dampings[0, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX]
    )
    if not (
        math.isclose(
            observed_gripper_stiffness,
            ISAACLAB_FRANKA_HAND_STIFFNESS_N_PER_M,
            abs_tol=1e-6,
        )
        and math.isclose(
            observed_gripper_damping,
            ISAACLAB_FRANKA_HAND_DAMPING_N_S_PER_M,
            abs_tol=1e-6,
        )
    ):
        raise RuntimeError(
            "official Franka driven-finger gains did not accept the "
            "pinned Isaac Lab configuration"
        )
    robot.reset_to_default_pose()
    _step_gripper(robot, 0.04, steps=60)
    scene_dynamic_prims = {
        model.name: (
            target_object_prim
            if model.name == ARGS.target_object
            else RigidPrim(f"/World/M1B/{model.name}/{model.links[0].name}")
        )
        for model in SCENE.dynamic_models
    }
    initial_scene_natural_stability = {
        "source": (
            "SDF_DERIVED_PHYSICS_NATURAL_GRAVITY_SETTLING_"
            "NO_STATE_FREEZE"
        ),
        "performed": False,
        "reason": "DIAGNOSTIC_NOT_REQUESTED",
        "passed": None,
    }
    if ARGS.natural_scene_stability_audit:
        initial_scene_natural_stability = (
            _wait_for_natural_scene_stability(scene_dynamic_prims)
        )
        initial_scene_natural_stability["performed"] = True
        if not initial_scene_natural_stability["passed"]:
            diagnostic_path = (
                Path(ARGS.output) / "scene-stability-diagnostic.json"
            )
            diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostic_path.write_text(
                json.dumps(
                    initial_scene_natural_stability,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            raise RuntimeError(
                "source-derived Isaac scene did not reach the 0.25 mm natural "
                "gravity-settling gate; diagnostic="
                f"{diagnostic_path}"
            )
    live_scene_poses = {
        entity: _live_pose(prim) for entity, prim in scene_dynamic_prims.items()
    }
    free_gap_yaw = None
    top_down_orientation_wxyz = DOWNWARD_WXYZ
    if ARGS.calibration_free_gap_yaw:
        target_xy = live_scene_poses[ARGS.target_object][0][:2]
        neighbors = [
            pose[0][:2]
            for entity, pose in live_scene_poses.items()
            if entity != ARGS.target_object
        ]
        free_gap_yaw = select_free_gap_yaw_from_xy(
            target_xy,
            neighbors,
            source="CALIBRATION_LIVE_SUPERVISION_FREE_GAP_GEOMETRY",
        )
        if ARGS.calibration_free_gap_yaw_override_rad is not None:
            selected_override = next(
                (
                    candidate
                    for candidate in free_gap_yaw["candidates"]
                    if math.isclose(
                        float(candidate["yaw_rad"]),
                        ARGS.calibration_free_gap_yaw_override_rad,
                        abs_tol=1e-9,
                    )
                ),
                None,
            )
            if (
                selected_override is None
                or float(selected_override["min_clearance_m"])
                < FREE_GAP_MIN_CLEARANCE_M
            ):
                raise RuntimeError(
                    "calibration yaw override is not a safe ADR-0016 grid "
                    "candidate"
                )
            free_gap_yaw["maximum_clearance_selected_yaw_rad"] = free_gap_yaw[
                "selected_yaw_rad"
            ]
            free_gap_yaw["selected_yaw_rad"] = float(
                selected_override["yaw_rad"]
            )
            free_gap_yaw["min_clearance_m"] = float(
                selected_override["min_clearance_m"]
            )
            free_gap_yaw["selection"] = (
                "CALIBRATION_ONLY_SAFE_GRID_OVERRIDE_NOT_POLICY_INPUT"
            )
        if not free_gap_yaw["clearance_ok"]:
            raise RuntimeError(
                "calibration free-gap yaw has no candidate with at least "
                f"{FREE_GAP_MIN_CLEARANCE_M:.3f} m clearance"
            )
        top_down_orientation_wxyz = np.asarray(
            isaac_top_down_orientation_wxyz(
                float(free_gap_yaw["selected_yaw_rad"])
            ),
            dtype=np.float32,
        )
    reset_prims = scene_dynamic_prims if ARGS.same_process_reset_gate else {}
    reset_initial_poses = {
        entity: _live_pose(prim) for entity, prim in reset_prims.items()
    }

    target_spec_center = np.asarray(TARGET_MODEL.pose.xyz, dtype=np.float32)
    target_live_center = np.asarray(_live_pose(target_object_prim)[0], dtype=np.float32)
    calibration_offset = np.asarray(CALIBRATION_OFFSET_XYZ_M, dtype=np.float32)
    commanded_target_center = target_live_center + calibration_offset
    pregrasp = commanded_target_center + np.asarray(
        [0.0, 0.0, 0.27],
        dtype=np.float32,
    )
    target_collision = TARGET_MODEL.links[0].collisions[0]
    if target_collision.radius is None:
        raise RuntimeError("M1B target collision has no cylinder radius")
    calibration_perceived_diameter_m = 2.0 * target_collision.radius
    preclose_target_m = (
        calibration_perceived_diameter_m
        + M1B_PRECLOSE_PUBLIC_DIAMETER_MARGIN_M
    ) / 2.0 + NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M
    close_target_m = (
        calibration_perceived_diameter_m
        - M1B_CLOSE_SQUEEZE_M
    ) / 2.0 + NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M

    if free_gap_yaw is None:
        orientation_candidates = [
            {
                "yaw_rad": 0.0,
                "min_clearance_m": math.inf,
            }
        ]
    elif ARGS.calibration_free_gap_yaw_override_rad is not None:
        orientation_candidates = [
            candidate
            for candidate in free_gap_yaw["candidates"]
            if math.isclose(
                float(candidate["yaw_rad"]),
                ARGS.calibration_free_gap_yaw_override_rad,
                abs_tol=1e-9,
            )
        ]
    else:
        orientation_candidates = sorted(
            (
                candidate
                for candidate in free_gap_yaw["candidates"]
                if float(candidate["min_clearance_m"])
                >= FREE_GAP_MIN_CLEARANCE_M
            ),
            key=lambda candidate: float(candidate["min_clearance_m"]),
            reverse=True,
        )
    if not orientation_candidates:
        raise RuntimeError("no safe top-down orientation candidate")

    orientation_feasibility_scan: list[dict[str, object]] = []
    selected_orientation_feasible = False
    phases: dict[str, dict[str, object]] = {}
    contact_goal_for_scan = commanded_target_center + np.asarray(
        [0.0, 0.0, CONTACT_CENTERLINES_M[0]],
        dtype=np.float32,
    )
    contact_phase_for_scan: dict[str, object] = {}
    for candidate in orientation_candidates:
        candidate_yaw_rad = float(candidate["yaw_rad"])
        candidate_orientation_wxyz = np.asarray(
            isaac_top_down_orientation_wxyz(candidate_yaw_rad),
            dtype=np.float32,
        )
        candidate_pregrasp = _step_pose(
            robot,
            pregrasp,
            steps=150,
            orientation_wxyz=candidate_orientation_wxyz,
        )
        candidate_contact = _step_pose(
            robot,
            contact_goal_for_scan,
            steps=120,
            orientation_wxyz=candidate_orientation_wxyz,
        )
        candidate_passed = bool(
            candidate_pregrasp["final_error_m"]
            <= PRODUCTION_EE_POSITION_ERROR_GATE_M
            and candidate_contact["final_error_m"]
            <= PRODUCTION_EE_POSITION_ERROR_GATE_M
        )
        orientation_feasibility_scan.append(
            {
                "yaw_rad": candidate_yaw_rad,
                "min_clearance_m": float(candidate["min_clearance_m"]),
                "pregrasp": candidate_pregrasp,
                "contact": candidate_contact,
                "passed": candidate_passed,
                "closed_gripper_during_scan": False,
            }
        )
        phases = {"pregrasp": candidate_pregrasp}
        contact_phase_for_scan = candidate_contact
        top_down_orientation_wxyz = candidate_orientation_wxyz
        if candidate_passed:
            selected_orientation_feasible = True
            if free_gap_yaw is not None:
                free_gap_yaw["selected_yaw_rad"] = candidate_yaw_rad
                free_gap_yaw["min_clearance_m"] = float(
                    candidate["min_clearance_m"]
                )
                if ARGS.calibration_free_gap_yaw_override_rad is None:
                    free_gap_yaw["selection"] = (
                        "SAFE_GRID_FIRST_POSE_FEASIBLE_BY_"
                        "DESCENDING_CLEARANCE"
                    )
            _step_pose(
                robot,
                pregrasp,
                steps=90,
                orientation_wxyz=top_down_orientation_wxyz,
            )
            break

    orientation_scan_scene_restoration = {
        "source": (
            "CALIBRATION_ONLY_ORIENTATION_SCAN_SCENE_RESTORATION_"
            "NOT_POLICY_INPUT"
        ),
        "performed": False,
        "reason": "NO_SELECTED_ORIENTATION_TO_EXECUTE",
        "passed": True,
    }
    target_reobserved_after_orientation_scan = None
    if selected_orientation_feasible:
        orientation_scan_scene_restoration = (
            _restore_calibration_scene_after_orientation_scan(
                scene_dynamic_prims,
                live_scene_poses,
            )
        )
        if not orientation_scan_scene_restoration["passed"]:
            raise RuntimeError(
                "calibration orientation scan scene restoration did not "
                "reach the 0.25 mm quiet-window gate"
            )
        target_reobserved_after_orientation_scan = np.asarray(
            _live_pose(target_object_prim)[0],
            dtype=np.float32,
        )
        commanded_target_center = (
            target_reobserved_after_orientation_scan + calibration_offset
        )
        pregrasp = commanded_target_center + np.asarray(
            [0.0, 0.0, 0.27],
            dtype=np.float32,
        )
        phases["pregrasp"] = _step_pose(
            robot,
            pregrasp,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
        )

    empty_grasp_injection: dict[str, object] | None = None
    if ARGS.m2b_inject_empty_grasp and selected_orientation_feasible:
        empty_hand_before, _ = _live_pose(hand_prim)
        empty_object_before, _ = _live_pose(target_object_prim)
        (
            empty_samples,
            empty_sensor_frames,
            empty_tensor_frames,
            empty_physx_frames,
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
        empty_feedback, empty_broker = broker_from_window(empty_samples)
        empty_lift_goal = np.asarray(
            empty_hand_before, dtype=np.float32
        ) + np.asarray([0.0, 0.0, 0.05], dtype=np.float32)
        empty_lift_motion = _step_pose(
            robot,
            empty_lift_goal,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
        )
        empty_hand_after, _ = _live_pose(hand_prim)
        empty_object_after, _ = _live_pose(target_object_prim)
        empty_hand_delta = _delta(empty_hand_before, empty_hand_after)
        empty_object_delta = _delta(empty_object_before, empty_object_after)
        empty_attachment_absent = not stage.GetPrimAtPath(
            ATTACH_JOINT_PATH
        ).IsValid()
        empty_physics_pass = bool(
            not empty_feedback.grasp_success
            and empty_attachment_absent
            and float(np.linalg.norm(empty_hand_delta)) >= 0.02
            and float(np.linalg.norm(empty_object_delta)) <= 0.005
        )
        _step_gripper(robot, 0.04, steps=60)
        phases["empty_grasp_return_to_pregrasp"] = _step_pose(
            robot,
            pregrasp,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
        )
        empty_grasp_injection = {
            "schema_version": "M2BPhysicalInjectionProbeV1",
            "failure_type": "EMPTY_GRASP",
            "injection_commanded": True,
            "close_command_issued": True,
            "bilateral_grasp_observed": bool(empty_feedback.grasp_success),
            "attachment_created": not empty_attachment_absent,
            "hand_lift_delta_m": empty_hand_delta.tolist(),
            "target_lift_delta_m": float(np.linalg.norm(empty_object_delta)),
            "lift_motion": empty_lift_motion,
            "physical_state_passed": empty_physics_pass,
            "broker_internal": empty_broker,
            "contact_sample_count": len(empty_samples),
            "sensor_frame_count": len(empty_sensor_frames),
            "tensor_frame_count": len(empty_tensor_frames),
            "physx_frame_count": len(empty_physx_frames),
            "public_observation_status": "NOT_CAPTURED_BY_ACTUATION_PROBE",
            "training_eligible": False,
            "recovery_steps_executed": [
                "OPEN_GRIPPER",
                "RETURN_TO_PREGRASP",
            ],
        }

    contact_attempts: list[dict[str, object]] = []
    feedback = None
    broker_internal = None
    selected_contact_goal: np.ndarray | None = None
    if not selected_orientation_feasible:
        attempt_feedback, attempt_internal = broker_from_window([])
        motion_gate = {
            "source": "S1_VERIFIED_MOVEIT_EXECUTION_EE_POSITION_ERROR_GATE",
            "maximum_ee_position_error_m": PRODUCTION_EE_POSITION_ERROR_GATE_M,
            "pregrasp_final_error_m": phases["pregrasp"]["final_error_m"],
            "contact_final_error_m": contact_phase_for_scan["final_error_m"],
            "contact_terminal_convergence_required": True,
            "passed": False,
        }
        contact_attempts.append(
            {
                "contact_centerline_m": CONTACT_CENTERLINES_M[0],
                "motion": contact_phase_for_scan,
                "motion_gate": motion_gate,
                "preclose": {
                    "source": "ADR0016B_TWO_STAGE_PUBLIC_DIAMETER_PRECLOSE",
                    "stage": (
                        "PREGRASP_BEFORE_CONTACT_DESCENT"
                        if ARGS.preclose_before_contact_descent
                        else "AT_CONTACT_BEFORE_TERMINAL_CLOSE"
                    ),
                    "per_finger_target_m": preclose_target_m,
                    "steps": M1B_PRECLOSE_STEPS,
                    "settle_steps": M1B_PRECLOSE_SETTLE_STEPS,
                    "action_mapping_source": (
                        "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q; "
                        "SOURCE_FALLBACK_INWARD_PAD_OFFSET_REMOVED"
                    ),
                    "executed": False,
                },
                "terminal_close": {
                    "source": "ADR0016B_WINDOW_EDGE_SQUEEZE",
                    "per_finger_target_m": close_target_m,
                    "close_steps": M1B_TERMINAL_CLOSE_STEPS,
                    "post_close_observation_steps": (
                        M1B_POST_CLOSE_OBSERVATION_STEPS
                    ),
                    "action_mapping_source": (
                        "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q; "
                        "SOURCE_FALLBACK_INWARD_PAD_OFFSET_REMOVED"
                    ),
                    "executed": False,
                },
                "contact_feedback": attempt_feedback.__dict__,
                "broker_internal": attempt_internal,
                "sample_count": 0,
                "contact_source": (
                    "NOT_EXECUTED_ORIENTATION_FEASIBILITY_GATE_REJECTED"
                ),
                "nonempty_contact_frame_count": 0,
                "nonempty_contact_frames": [],
                "object_motion_during_close_m": [0.0, 0.0, 0.0],
            }
        )
    for contact_centerline_m in (
        CONTACT_CENTERLINES_M if selected_orientation_feasible else ()
    ):
        contact_goal = commanded_target_center + np.asarray(
            [0.0, 0.0, contact_centerline_m],
            dtype=np.float32,
        )
        before_preclose_snapshot = _robot_snapshot(
            robot,
            hand_prim=hand_prim,
            left_finger_prim=left_finger_prim,
            right_finger_prim=right_finger_prim,
            object_prim=target_object_prim,
        )
        if ARGS.preclose_before_contact_descent:
            _step_gripper(
                robot,
                preclose_target_m,
                steps=M1B_PRECLOSE_STEPS,
            )
            _step_gripper(
                robot,
                preclose_target_m,
                steps=M1B_PRECLOSE_SETTLE_STEPS,
            )
            after_preclose_snapshot = _robot_snapshot(
                robot,
                hand_prim=hand_prim,
                left_finger_prim=left_finger_prim,
                right_finger_prim=right_finger_prim,
                object_prim=target_object_prim,
            )
            contact_phase = _step_pose(
                robot,
                contact_goal,
                steps=120,
                orientation_wxyz=top_down_orientation_wxyz,
            )
            pre_close_snapshot = _robot_snapshot(
                robot,
                hand_prim=hand_prim,
                left_finger_prim=left_finger_prim,
                right_finger_prim=right_finger_prim,
                object_prim=target_object_prim,
            )
        else:
            contact_phase = _step_pose(
                robot,
                contact_goal,
                steps=120,
                orientation_wxyz=top_down_orientation_wxyz,
            )
            before_preclose_snapshot = _robot_snapshot(
                robot,
                hand_prim=hand_prim,
                left_finger_prim=left_finger_prim,
                right_finger_prim=right_finger_prim,
                object_prim=target_object_prim,
            )
            _step_gripper(
                robot,
                preclose_target_m,
                steps=M1B_PRECLOSE_STEPS,
            )
            _step_gripper(
                robot,
                preclose_target_m,
                steps=M1B_PRECLOSE_SETTLE_STEPS,
            )
            after_preclose_snapshot = _robot_snapshot(
                robot,
                hand_prim=hand_prim,
                left_finger_prim=left_finger_prim,
                right_finger_prim=right_finger_prim,
                object_prim=target_object_prim,
            )
            pre_close_snapshot = after_preclose_snapshot
        preclose_object_motion_m = _delta(
            before_preclose_snapshot["object_pose_world_wxyz"][0],
            after_preclose_snapshot["object_pose_world_wxyz"][0],
        )
        samples: list[M1BContactSampleV1] = []
        raw_contact_frames: list[dict[str, object]] = []
        tensor_contact_frames: list[dict[str, object]] = []
        physx_contact_frames: list[dict[str, object]] = []
        close_segments = (
            ((OFFICIAL_FRANKA_CLOSED_POSITION_M, ARGS.gripper_close_steps),)
            if ARGS.free_close_diagnostic
            else (
                (close_target_m, M1B_TERMINAL_CLOSE_STEPS),
                (close_target_m, M1B_POST_CLOSE_OBSERVATION_STEPS),
            )
        )
        for segment_target_m, segment_steps in close_segments:
            (
                segment_samples,
                segment_raw_frames,
                segment_tensor_frames,
                segment_physx_frames,
            ) = _step_gripper(
                robot,
                segment_target_m,
                steps=segment_steps,
                sensors=sensors,
                contact_views={
                    "left": left_finger_prim,
                    "right": right_finger_prim,
                },
                contact_collector=contact_collector,
            )
            samples.extend(segment_samples)
            raw_contact_frames.extend(segment_raw_frames)
            tensor_contact_frames.extend(segment_tensor_frames)
            physx_contact_frames.extend(segment_physx_frames)
        attempt_feedback, attempt_internal = broker_from_window(samples)
        motion_gate = {
            "source": "S1_VERIFIED_MOVEIT_EXECUTION_EE_POSITION_ERROR_GATE",
            "maximum_ee_position_error_m": PRODUCTION_EE_POSITION_ERROR_GATE_M,
            "pregrasp_final_error_m": phases["pregrasp"]["final_error_m"],
            "contact_final_error_m": contact_phase["final_error_m"],
            "contact_terminal_convergence_required": True,
            "passed": bool(
                phases["pregrasp"]["final_error_m"]
                <= PRODUCTION_EE_POSITION_ERROR_GATE_M
                and contact_phase["final_error_m"]
                <= PRODUCTION_EE_POSITION_ERROR_GATE_M
            ),
        }
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
                "motion_gate": motion_gate,
                "preclose": {
                    "source": (
                        "ADR0016B_TWO_STAGE_PUBLIC_DIAMETER_PRECLOSE"
                    ),
                    "stage": (
                        "PREGRASP_BEFORE_CONTACT_DESCENT"
                        if ARGS.preclose_before_contact_descent
                        else "AT_CONTACT_BEFORE_TERMINAL_CLOSE"
                    ),
                    "diameter_source": (
                        "CALIBRATION_ONLY_SDF_CLASS_GEOMETRY_NOT_POLICY_INPUT"
                    ),
                    "calibration_perceived_diameter_m": (
                        calibration_perceived_diameter_m
                    ),
                    "public_diameter_margin_m": (
                        M1B_PRECLOSE_PUBLIC_DIAMETER_MARGIN_M
                    ),
                    "source_fallback_finger_board_thickness_m": (
                        M1B_SOURCE_FALLBACK_FINGER_BOARD_THICKNESS_M
                    ),
                    "official_inner_face_to_joint_axis_m": (
                        NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M
                    ),
                    "official_collision_inner_face_bound_abs_max_m": (
                        NVIDIA_DEFAULT_COLLISION_INNER_FACE_BOUND_ABS_MAX_M
                    ),
                    "action_mapping_source": (
                        "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q; "
                        "SOURCE_FALLBACK_INWARD_PAD_OFFSET_REMOVED"
                    ),
                    "per_finger_target_m": preclose_target_m,
                    "steps": M1B_PRECLOSE_STEPS,
                    "settle_steps": M1B_PRECLOSE_SETTLE_STEPS,
                    "before_snapshot": before_preclose_snapshot,
                    "after_snapshot": after_preclose_snapshot,
                    "object_motion_m": preclose_object_motion_m.tolist(),
                },
                "terminal_close": {
                    "source": "ADR0016B_WINDOW_EDGE_SQUEEZE",
                    "close_squeeze_m": M1B_CLOSE_SQUEEZE_M,
                    "source_fallback_finger_board_thickness_m": (
                        M1B_SOURCE_FALLBACK_FINGER_BOARD_THICKNESS_M
                    ),
                    "official_inner_face_to_joint_axis_m": (
                        NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M
                    ),
                    "official_collision_inner_face_bound_abs_max_m": (
                        NVIDIA_DEFAULT_COLLISION_INNER_FACE_BOUND_ABS_MAX_M
                    ),
                    "action_mapping_source": (
                        "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q; "
                        "SOURCE_FALLBACK_INWARD_PAD_OFFSET_REMOVED"
                    ),
                    "per_finger_target_m": close_target_m,
                    "close_steps": M1B_TERMINAL_CLOSE_STEPS,
                    "post_close_observation_steps": (
                        M1B_POST_CLOSE_OBSERVATION_STEPS
                    ),
                },
                "contact_feedback": attempt_feedback.__dict__,
                "broker_internal": attempt_internal,
                "sample_count": len(samples),
                "contact_source": (
                    "NVIDIA_ISAAC_SIM_6_RIGIDPRIM_TENSOR_CONTACT_VIEW"
                ),
                "physx_contact_diagnostics": physx_contact_diagnostics,
                "gripper_state_trace": [
                    {
                        "time_s": frame["time_s"],
                        "physics_step": frame["physics_step"],
                        "positions_m": frame["gripper_positions_m"],
                        "velocities_mps": frame["gripper_velocities_mps"],
                    }
                    for frame_index, frame in enumerate(physx_contact_frames)
                    if frame["finger"] == "left" and frame_index % 20 == 0
                ],
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
        if attempt_feedback.grasp_success and motion_gate["passed"]:
            feedback = attempt_feedback
            broker_internal = attempt_internal
            selected_contact_goal = contact_goal
            break
        _step_gripper(robot, 0.04, steps=45)
        _step_pose(
            robot,
            pregrasp,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
        )
    if feedback is None or broker_internal is None:
        feedback = attempt_feedback
        broker_internal = attempt_internal
    evidence: dict[str, object] = {
        "schema_version": "IsaacM1BActuationProbeV1",
        "actuation_probe_source_sha256": sha256_file(__file__),
        "status": "CONTACT_GATE_REJECTED",
        "scope": "CALIBRATION_ONLY_INITIALIZATION",
        "free_close_diagnostic": ARGS.free_close_diagnostic,
        "not_policy_rollout": True,
        "official_robot": {
            **official_asset_contract,
            "base_pose": ROBOT_BASE_POSE.__dict__,
        },
        "scene_seed": SCENE.scene_seed,
        "initial_scene_natural_stability": (
            initial_scene_natural_stability
        ),
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
        "target_reobserved_after_orientation_scan_world_m": (
            None
            if target_reobserved_after_orientation_scan is None
            else target_reobserved_after_orientation_scan.tolist()
        ),
        "calibration_offset_xyz_m": list(CALIBRATION_OFFSET_XYZ_M),
        "commanded_target_center_world_m": commanded_target_center.tolist(),
        "calibration_offset_provenance": (
            "CALIBRATION_ONLY_INITIALIZATION_NOT_POLICY_INPUT"
        ),
        "calibration_free_gap_yaw": free_gap_yaw,
        "orientation_feasibility_scan": {
            "source": (
                "ADR0016_SAFE_FREE_GAP_GRID_PLUS_S1_20MM_"
                "PREGRASP_AND_CONTACT_POSE_GATE"
            ),
            "selection_rule": (
                "FIRST_POSE_FEASIBLE_CANDIDATE_BY_DESCENDING_CLEARANCE"
            ),
            "minimum_clearance_m": FREE_GAP_MIN_CLEARANCE_M,
            "maximum_ee_position_error_m": (
                PRODUCTION_EE_POSITION_ERROR_GATE_M
            ),
            "selected": selected_orientation_feasible,
            "candidates": orientation_feasibility_scan,
        },
        "orientation_scan_scene_restoration": (
            orientation_scan_scene_restoration
        ),
        "production_grasp_primitive": (
            "open_official_hand + top_down_pregrasp + "
            "ADR0016_safe_grid_pose_feasibility_selection + "
            + (
                "ADR0016B_two_stage_public_diameter_preclose_at_pregrasp + "
                "fixed_height_contact_descend + "
                if ARGS.preclose_before_contact_descent
                else "fixed_height_contact_descend + "
                "ADR0016B_two_stage_public_diameter_preclose_at_contact + "
            )
            + "NVIDIA_Default_inner_gap_2q_mapping + "
            "0p4s_preclose_settle + "
            "ADR0016B_2mm_window_edge_squeeze + "
            "1p0s_post_close_bilateral_broker"
        ),
        "action_protocol": ACTION_PROTOCOL,
        "gripper_close_settling": {
            "steps": ARGS.gripper_close_steps,
            "duration_s": ARGS.gripper_close_steps / ACTION_PROTOCOL["frequency_hz"],
            "position_target_m": (
                OFFICIAL_FRANKA_CLOSED_POSITION_M
                if ARGS.free_close_diagnostic
                else close_target_m
            ),
            "production_timing_steps": {
                "preclose": M1B_PRECLOSE_STEPS,
                "preclose_settle": M1B_PRECLOSE_SETTLE_STEPS,
                "terminal_close": M1B_TERMINAL_CLOSE_STEPS,
                "post_close_observation": M1B_POST_CLOSE_OBSERVATION_STEPS,
            },
            "source": (
                "NVIDIA_OFFICIAL_USD_DRIVEN_PANDA_FINGER_JOINT1_"
                "PLUS_PHYSX_MIMIC_JOINT2"
            ),
            "actuated_dof_index": OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX,
        },
        "gripper_actuation_parity": {
            "source": (
                "PINNED_NVIDIA_ISAACLAB_FRANKA_HAND_GAINS_WITH_"
                "HASH_LOCKED_PRODUCTION_URDF_EFFORT_CAP"
            ),
            "source_urdf_joint": "panda_finger_joint2",
            "source_effort_limit_n": SOURCE_GRIPPER_MAX_EFFORT_N,
            "isaaclab_config": {
                "repository": "https://github.com/isaac-sim/IsaacLab",
                "commit": ISAACLAB_6_FRANKA_CONFIG_COMMIT,
                "path": (
                    "source/isaaclab_assets/isaaclab_assets/robots/franka.py"
                ),
                "configuration": "FRANKA_PANDA_CFG.panda_hand",
                "declared_effort_limit_n": 200.0,
                "stiffness_n_per_m": ISAACLAB_FRANKA_HAND_STIFFNESS_N_PER_M,
                "damping_n_s_per_m": ISAACLAB_FRANKA_HAND_DAMPING_N_S_PER_M,
            },
            "isaac_official_driven_joint": "panda_finger_joint1",
            "isaac_official_mimic_joint": "panda_finger_joint2",
            "isaac_default_driven_joint_stiffness_n_per_m": float(
                official_default_stiffnesses[
                    0, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
                ]
            ),
            "isaac_default_driven_joint_damping_n_s_per_m": float(
                official_default_dampings[
                    0, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
                ]
            ),
            "isaac_default_driven_joint_effort_limit_n": float(
                official_default_max_efforts[
                    0, OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX
                ]
            ),
            "isaac_applied_driven_joint_effort_limit_n": (
                observed_gripper_max_effort_n
            ),
            "isaac_applied_driven_joint_stiffness_n_per_m": (
                observed_gripper_stiffness
            ),
            "isaac_applied_driven_joint_damping_n_s_per_m": (
                observed_gripper_damping
            ),
            "geometry_or_joint_topology_modified": False,
            "action_mapping": (
                "NVIDIA_DEFAULT_INNER_GAP_EQUALS_2Q_METRES; "
                "source fallback 6mm inward pad offset removed; "
                "official Isaac joint1 drives joint2 mimic"
            ),
        },
        "physx_contact_processing": {
            "setting": DISABLE_CONTACT_PROCESSING_SETTING,
            "value_before_adapter_override": DISABLE_CONTACT_PROCESSING_BEFORE,
            "value_during_probe": PHYSICS_SETTINGS.get(
                DISABLE_CONTACT_PROCESSING_SETTING
            ),
            "required_for_raw_contact_evidence": True,
            "collider_contact_reporting": collider_contact_reporting,
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
        "finger_joint_diagnostics": {
            name: _joint_prim_diagnostics(
                stage,
                str(
                    robot.dof_paths[0][
                        int(_array_or_list(robot.get_dof_indices(name))[0])
                    ]
                ),
            )
            for name in ("panda_finger_joint1", "panda_finger_joint2")
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
        "motion_gate": {
            "source": "S1_VERIFIED_MOVEIT_EXECUTION_EE_POSITION_ERROR_GATE",
            "maximum_ee_position_error_m": PRODUCTION_EE_POSITION_ERROR_GATE_M,
            "passed": selected_contact_goal is not None,
        },
        "m2b_empty_grasp_injection": empty_grasp_injection,
    }
    if ARGS.free_close_diagnostic:
        final_finger_positions = contact_attempts[-1]["post_close_snapshot"][
            "dof_positions"
        ][0][-2:]
        free_close_pass = bool(
            max(abs(float(value)) for value in final_finger_positions) <= 0.002
            and not feedback.grasp_success
        )
        evidence.update(
            {
                "status": (
                    "FREE_CLOSE_DIAGNOSTIC_PASS"
                    if free_close_pass
                    else "FREE_CLOSE_DIAGNOSTIC_REJECTED"
                ),
                "free_close_result": {
                    "final_finger_positions_m": final_finger_positions,
                    "maximum_closed_position_m": 0.002,
                    "cylinder_contact_observed": feedback.grasp_success,
                    "passed": free_close_pass,
                },
            }
        )
        (output / "actuation-probe.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            "M1B_ISAAC_FREE_CLOSE_DIAGNOSTIC "
            + json.dumps(evidence["free_close_result"], sort_keys=True),
            flush=True,
        )
        return 0 if free_close_pass else 1
    if selected_contact_goal is None:
        pose_gate_rejected = any(
            not bool(attempt["motion_gate"]["passed"])
            and (
                bool(attempt["contact_feedback"]["grasp_success"])
                or attempt["terminal_close"].get("executed") is False
            )
            for attempt in contact_attempts
        )
        evidence["status"] = (
            "POSE_GATE_REJECTED"
            if pose_gate_rejected
            else "CONTACT_GATE_REJECTED"
        )
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
                            "motion_gate": attempt["motion_gate"],
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
    phases["lift"] = _step_pose(
        robot,
        pregrasp,
        steps=150,
        orientation_wxyz=top_down_orientation_wxyz,
    )
    hand_after, _ = _live_pose(hand_prim)
    object_after, _ = _live_pose(object_prim)
    hand_motion = _delta(hand_before, hand_after)
    object_motion = _delta(object_before, object_after)
    follow_error_m = float(np.linalg.norm(hand_motion - object_motion))
    attached_follow_pass = bool(
        object_motion[2] >= 0.05
        and follow_error_m <= 0.02
    )
    wrong_object_injection = (
        {
            "schema_version": "M2BPhysicalInjectionProbeV1",
            "failure_type": "WRONG_OBJECT",
            "injection_commanded": True,
            "close_command_issued": True,
            "contacted_entity_id": str(
                broker_internal["actual_sim_entity_id"]
            ),
            "attached_entity_id": entity,
            "task_target_entity_id": ARGS.m2b_task_target_object,
            "broker_attached_actual_contact": (
                str(broker_internal["actual_sim_entity_id"]) == entity
            ),
            "physical_state_passed": bool(
                attached_follow_pass
                and str(broker_internal["actual_sim_entity_id"]) == entity
                and entity != ARGS.m2b_task_target_object
            ),
            "public_observation_status": "NOT_CAPTURED_BY_ACTUATION_PROBE",
            "training_eligible": False,
        }
        if ARGS.m2b_task_target_object is not None
        else None
    )

    release_failure_injection: dict[str, object] | None = None
    if ARGS.m2b_inject_release_failure:
        release_hand_before, _ = _live_pose(hand_prim)
        release_object_before, _ = _live_pose(object_prim)
        _step_gripper(robot, 0.04, steps=60)
        attachment_remained = stage.GetPrimAtPath(ATTACH_JOINT_PATH).IsValid()
        release_follow_goal = np.asarray(
            release_hand_before, dtype=np.float32
        ) + np.asarray([0.0, 0.0, 0.03], dtype=np.float32)
        release_follow_motion = _step_pose(
            robot,
            release_follow_goal,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
        )
        release_hand_after, _ = _live_pose(hand_prim)
        release_object_after, _ = _live_pose(object_prim)
        release_hand_delta = _delta(release_hand_before, release_hand_after)
        release_object_delta = _delta(
            release_object_before, release_object_after
        )
        release_follow_error_m = float(
            np.linalg.norm(release_hand_delta - release_object_delta)
        )
        release_physics_pass = bool(
            attachment_remained
            and float(np.linalg.norm(release_object_delta)) >= 0.01
            and release_follow_error_m <= 0.02
        )
        release_failure_injection = {
            "schema_version": "M2BPhysicalInjectionProbeV1",
            "failure_type": "RELEASE_FAILURE",
            "injection_commanded": True,
            "release_command_issued": True,
            "attachment_remained_after_release": attachment_remained,
            "hand_follow_delta_m": release_hand_delta.tolist(),
            "carried_follow_delta_m": float(
                np.linalg.norm(release_object_delta)
            ),
            "follow_error_m": release_follow_error_m,
            "follow_motion": release_follow_motion,
            "physical_state_passed": release_physics_pass,
            "public_observation_status": "NOT_CAPTURED_BY_ACTUATION_PROBE",
            "training_eligible": False,
        }
        hand_after = release_hand_after

    _remove_attachment()
    _step_gripper(robot, 0.04, steps=60)
    attachment_absent_after_detach = not stage.GetPrimAtPath(
        ATTACH_JOINT_PATH
    ).IsValid()
    hand_detached_start, _ = _live_pose(hand_prim)
    object_detached_start, _ = _live_pose(object_prim)
    retreat = np.asarray(hand_after, dtype=np.float32) + np.asarray(
        [0.0, 0.0, 0.05],
        dtype=np.float32,
    )
    phases["detach_retreat"] = _step_pose(
        robot,
        retreat,
        steps=90,
        orientation_wxyz=top_down_orientation_wxyz,
    )
    hand_detached_end, _ = _live_pose(hand_prim)
    object_detached_end, _ = _live_pose(object_prim)
    detached_hand_motion = _delta(hand_detached_start, hand_detached_end)
    detached_object_motion = _delta(
        object_detached_start,
        object_detached_end,
    )
    detached_relative_change_m = float(
        np.linalg.norm(detached_object_motion - detached_hand_motion)
    )
    detached_hand_motion_m = float(np.linalg.norm(detached_hand_motion))
    minimum_decoupled_relative_change_m = 0.020
    minimum_detach_jog_m = 0.020
    detached_noncoupling_pass = bool(
        attachment_absent_after_detach
        and detached_hand_motion_m >= minimum_detach_jog_m
        and detached_relative_change_m >= minimum_decoupled_relative_change_m
    )
    same_process_reset = (
        _same_process_reset_gate(
            robot,
            reset_prims=reset_prims,
            initial_poses=reset_initial_poses,
            hand_prim=hand_prim,
        )
        if ARGS.same_process_reset_gate
        else None
    )
    same_process_reset_pass = bool(
        same_process_reset is None or same_process_reset["passed"]
    )
    m2b_injection_pass = bool(
        (
            empty_grasp_injection is None
            or empty_grasp_injection["physical_state_passed"]
        )
        and (
            release_failure_injection is None
            or release_failure_injection["physical_state_passed"]
        )
        and (
            wrong_object_injection is None
            or wrong_object_injection["physical_state_passed"]
        )
    )

    evidence.update(
        {
            "status": (
                "PASS"
                if (
                    attached_follow_pass
                    and detached_noncoupling_pass
                    and same_process_reset_pass
                    and m2b_injection_pass
                )
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
                "source": "ADR0013_ACCEPTANCE3_GATE4_RELATIVE_DECOUPLING",
                "attachment_absent_after_detach": (
                    attachment_absent_after_detach
                ),
                "hand_motion_vector_m": detached_hand_motion.tolist(),
                "hand_motion_m": detached_hand_motion_m,
                "minimum_hand_motion_m": minimum_detach_jog_m,
                "object_motion_vector_m": detached_object_motion.tolist(),
                "relative_change_m": detached_relative_change_m,
                "minimum_relative_change_m": (
                    minimum_decoupled_relative_change_m
                ),
                "passed": detached_noncoupling_pass,
            },
            "same_process_reset": same_process_reset,
            "m2b_release_failure_injection": release_failure_injection,
            "m2b_wrong_object_injection": wrong_object_injection,
            "m2b_injection_pass": m2b_injection_pass,
            "m2b_recovery": {
                "empty_grasp": (
                    {
                        "sequence": ["REOBSERVE", "REGRASP"],
                        "physical_regrasp_and_lift_passed": attached_follow_pass,
                        "public_reobserve_status": (
                            "NOT_CAPTURED_BY_ACTUATION_PROBE"
                        ),
                        "training_eligible": False,
                    }
                    if empty_grasp_injection is not None
                    else None
                ),
                "release_failure": (
                    {
                        "sequence": [
                            "RETRY_RELEASE",
                            "RETREAT",
                            "REOBSERVE",
                        ],
                        "retry_detach_and_retreat_passed": (
                            detached_noncoupling_pass
                        ),
                        "public_reobserve_status": (
                            "NOT_CAPTURED_BY_ACTUATION_PROBE"
                        ),
                        "training_eligible": False,
                    }
                    if release_failure_injection is not None
                    else None
                ),
                "wrong_object": (
                    {
                        "sequence": [
                            "SAFE_PLACE_NON_TARGET",
                            "REASSOCIATE_TARGET",
                            "REGRASP",
                        ],
                        "safe_place_non_target_passed": (
                            detached_noncoupling_pass
                        ),
                        "reassociate_target_executed": False,
                        "regrasp_target_executed": False,
                        "public_reobserve_status": (
                            "NOT_CAPTURED_BY_ACTUATION_PROBE"
                        ),
                        "training_eligible": False,
                    }
                    if wrong_object_injection is not None
                    else None
                ),
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
                "same_process_reset": evidence["same_process_reset"],
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
