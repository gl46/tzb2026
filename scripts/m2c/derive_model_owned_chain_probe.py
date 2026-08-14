#!/usr/bin/env python3
"""Derive the M2C split-step physical chain probe from frozen V4 code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    DESTINATION_CLASS_LABELS,
    M2C_Q012_V2_SKILL_LABELS,
    POINTER_CLASS_LABELS,
)


UPSTREAM_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _replace_once(source: str, marker: str, replacement: str) -> str:
    count = source.count(marker)
    if count != 1:
        raise ValueError(f"derived model-chain marker count changed: {marker[:80]!r}={count}")
    return source.replace(marker, replacement, 1)


def _replace_exact(source: str, marker: str, replacement: str, *, count: int) -> str:
    observed = source.count(marker)
    if observed != count:
        raise ValueError(f"derived model-chain marker count changed: {marker[:80]!r}={observed}")
    return source.replace(marker, replacement)


def derive_probe_bytes(upstream: bytes) -> bytes:
    """Create a public-input eight-step probe without changing frozen helpers."""

    if sha256_bytes(upstream) != UPSTREAM_V4_PROBE_SHA256:
        raise ValueError("frozen V4 existence probe hash mismatch before derivation")
    source = upstream.decode("utf-8")
    source = _replace_once(
        source,
        "    return parser.parse_known_args()\n",
        """    parser.add_argument(
        "--m2c-chain-role", choices=("TRAIN", "SMOKE"), required=True
    )
    parser.add_argument(
        "--m2c-split", choices=("train", "val", "test"), required=True
    )
    parser.add_argument("--m2c-matched-key", required=True)
    parser.add_argument("--m2c-failure-seed", type=int, required=True)
    parser.add_argument(
        "--m2c-decision-source",
        choices=("SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",),
        required=True,
    )
    return parser.parse_known_args()
""",
    )
    source = _replace_once(
        source,
        "from xh_agent.perception.interfaces import PerceptionInputV1\n",
        """from xh_agent.perception.interfaces import PerceptionInputV1
from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.public_tracks_v2 import canonical_track_slots
""",
    )
    source = _replace_once(
        source,
        "from isaacsim import SimulationApp\n",
        """from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)

# This guard lives inside the derived probe, before Kit/SimulationApp starts,
# so a probe generated before 9/1 cannot be invoked directly after the hard
# freeze to bypass the collection worker.
require_pre_freeze(
    M2CExperimentAction.SMOKE
    if ARGS.m2c_chain_role == "SMOKE"
    else M2CExperimentAction.ISAAC_COLLECTION
)

from isaacsim import SimulationApp
""",
    )
    source = _replace_once(
        source,
        "def _execute_m2b_public_regrasp(\n",
        r"""def _m2c_now_ns() -> int:
    return int(
        SimulationManager.get_num_physics_steps()
        * SimulationManager.get_physics_dt()
        * 1_000_000_000
    )


def _m2c_capture(
    runtime: dict[str, Any],
    *,
    step_index: int,
    skill: str,
) -> tuple[list[Any], dict[str, object]]:
    tracks = _capture_m2b_public_rgbd(
        runtime, label=f"m2c_step_{step_index:02d}_{skill.lower()}"
    )
    capture = runtime["captures"][-1]
    public_tracks = [
        PerceptionTrackV1(
            track_id=track.track_id,
            category=(
                f"industrial_cylinder:{track.visual_color}"
                if track.visual_color
                else "industrial_cylinder:unknown"
            ),
            confidence=track.confidence,
            pose_xyzquat=[*track.position_world_m, 1.0, 0.0, 0.0, 0.0],
        )
        for track in tracks
    ]
    slots = canonical_track_slots(public_tracks)
    observation = {
        "schema_version": "PathBlockedPublicObservationV2",
        "observation_id": f"{ARGS.m2c_matched_key}-observation-{step_index}",
        "captured_at_ns": int(capture["timestamp_ns"]),
        "rgb_sha256": capture["rgb_sha256"],
        "depth_sha256": capture["depth_sha256"],
        "rgb_uri": capture["rgb_uri"],
        "depth_uri": capture["depth_uri"],
        "source": "PUBLIC_RGBD",
        "fresh": True,
        "perception_tracks": [track.model_dump(mode="json") for track in public_tracks],
        "canonical_slots": [
            track.track_id if track is not None else None
            for track in slots.tracks
        ],
        "capture_receipt_sha256": __import__("hashlib").sha256(
            json.dumps(capture, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return tracks, observation


def _m2c_select_public_track(
    tracks: list[Any],
    *,
    visual_color: str,
) -> Any:
    # This is the frozen public selector from the S4 key manifest.  It is
    # deliberately rerun on every fresh capture because a moved object may
    # receive a new public temporal track ID.
    return select_task_target_track(
        tracks,
        visual_color=visual_color,
        world_axis="x",
        extremum="max",
        maximum_height_below_tallest_m=0.02,
    )


def _m2c_receipt(
    *,
    step_index: int,
    skill: str,
    started_at_ns: int,
    motions: list[dict[str, object]],
    physical_passed: bool,
    measurements: dict[str, object] | None = None,
) -> dict[str, object]:
    if not measurements:
        raise RuntimeError("every physical skill receipt requires execution measurements")
    completed_at_ns = _m2c_now_ns()
    ik_passed = all(
        float(motion.get("final_error_m", float("inf")))
        <= PRODUCTION_EE_POSITION_ERROR_GATE_M
        for motion in motions
    )
    collision_passed = all(
        (motion.get("collision_gate") or {}).get("status") == "PASS"
        for motion in motions
    )
    core = {
        "schema_version": "PathBlockedPhysicalSkillReceiptV2",
        "receipt_id": f"{ARGS.m2c_matched_key}-physical-{step_index}",
        "receipt_uri": f"dataset://m2c_path_blocked/physical/{ARGS.m2c_matched_key}/{step_index}.json",
        "executed_skill": skill,
        "execution_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
        "physically_executed": True,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
        "schema_gate": "PASS",
        "stale_track_gate": "PASS",
        "frame_unit_gate": "PASS",
        "ik_gate": "PASS" if ik_passed else "REJECTED",
        "collision_gate": "PASS" if collision_passed else "REJECTED",
        "controller_gate": "PASS" if physical_passed else "REJECTED",
        "safety_gate": "PASS" if collision_passed else "REJECTED",
        "collision_or_safety_violation": not collision_passed,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "action_protocol": {
            "schema_version": "PhysicalActionProtocolV2",
            "coordinate_frame": (
                "policy_rgbd_optical" if skill == "REOBSERVE" else "world"
            ),
            "units": (
                "m_rad"
                if skill in {"GRASP", "MOVE", "PLACE", "REGRASP"}
                else "m"
                if skill in {"LIFT", "RELEASE"}
                else "none"
            ),
            "dimensions": (
                3
                if skill in {"GRASP", "LIFT", "MOVE", "PLACE", "RELEASE", "REGRASP"}
                else 0
            ),
            "frequency_hz": 60,
            "normalization": "none",
        },
        "execution_measurements": measurements,
    }
    digest = __import__("hashlib").sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**core, "receipt_sha256": digest}


def _m2c_step(
    *,
    step_index: int,
    skill: str,
    observation: dict[str, object],
    target_track_id: str | None,
    destination_cell: str | None,
    receipt: dict[str, object],
) -> dict[str, object]:
    slots = [track for track in observation["canonical_slots"] if track is not None]
    if target_track_id is not None and target_track_id not in slots:
        raise RuntimeError("public target is outside the fresh canonical K=8 slots")
    return {
        "schema_version": "PathBlockedPhysicalStepEvidenceV2",
        "decision_index": step_index,
        "observation": observation,
        "public_blocker_track_id": (
            target_track_id if step_index <= 4 else None
        ),
        "public_task_target_track_id": (
            target_track_id if step_index >= 6 else None
        ),
        "destination_cell_label": destination_cell,
        "physical_receipts": [receipt],
        "label_source": "PUBLIC_RGBD_PHYSICAL_SUPERVISION",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def _execute_m2b_public_regrasp(
""",
    )
    source = _replace_once(
        source,
        "    m2b_public_before: list[Any] | None = None\n",
        """    m2c_chain_steps: list[dict[str, object]] = []
    m2c_failure_observed_at_ns = _m2c_now_ns()
    m2b_public_before: list[Any] | None = None
""",
    )
    source = _replace_once(
        source,
        """        m2b_public_before = _capture_m2b_public_rgbd(
            m2b_public_rgbd,
            label="before_failure",
        )
""",
        """        m2b_public_before = _capture_m2b_public_rgbd(
            m2b_public_rgbd,
            label="before_failure_identity_binding",
        )
""",
    )
    source = _replace_once(
        source,
        "    target_spec_center = np.asarray(TARGET_MODEL.pose.xyz, dtype=np.float32)\n",
        """    if m2b_public_rgbd is None or m2b_injected_grasp_track_id is None or m2b_task_target_track_id is None:
        raise RuntimeError("M2C chain requires public blocker and task-target tracks")
    m2c_grasp_tracks, m2c_grasp_observation = _m2c_capture(
        m2b_public_rgbd, step_index=0, skill="GRASP",
    )
    m2c_grasp_public = _m2c_select_public_track(
        m2c_grasp_tracks,
        visual_color=ARGS.m2b_injected_public_grasp_color,
    )
    target_spec_center = np.asarray(TARGET_MODEL.pose.xyz, dtype=np.float32)
""",
    )
    source = _replace_once(
        source,
        """        target_reobserved_after_orientation_scan = np.asarray(
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
""",
        """        target_reobserved_after_orientation_scan = np.asarray(
            _live_pose(target_object_prim)[0],
            dtype=np.float32,
        )
        # The scripted supervision action remains bound to the fresh public
        # track; the inherited live/SDF pose is calibration evidence only.
        commanded_target_center = np.asarray(
            m2c_grasp_public.position_world_m, dtype=np.float32
        ) + calibration_offset
        pregrasp = commanded_target_center + np.asarray(
            [0.0, 0.0, 0.27],
            dtype=np.float32,
        )
        phases["pregrasp"] = _step_pose(
            robot,
            pregrasp,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
            contact_collector=contact_collector,
            collision_phase="M2C_MODEL_CHAIN_GRASP_PREGRASP",
        )
""",
    )
    source = _replace_exact(
        source,
        """            contact_phase = _step_pose(
                robot,
                contact_goal,
                steps=120,
                orientation_wxyz=top_down_orientation_wxyz,
            )
""",
        """            contact_phase = _step_pose(
                robot,
                contact_goal,
                steps=120,
                orientation_wxyz=top_down_orientation_wxyz,
                contact_collector=contact_collector,
                collision_phase="M2C_MODEL_CHAIN_GRASP_CONTACT_DESCENT",
                allowed_robot_contact_paths=(LEFT_FINGER_PATH, RIGHT_FINGER_PATH),
                allowed_external_contact_paths=(target_object_path,),
            )
""",
        count=2,
    )
    source = _replace_once(
        source,
        "    commanded_target_center = target_live_center + calibration_offset\n",
        """    commanded_target_center = np.asarray(
        m2c_grasp_public.position_world_m, dtype=np.float32
    ) + calibration_offset
""",
    )
    source = _replace_once(
        source,
        '    hand_before, _ = _live_pose(hand_prim)\n    object_path = f"/World/M1B/{entity}/link"\n',
        """    m2c_grasp_started_at_ns = int(m2c_grasp_observation["captured_at_ns"]) + 1
    m2c_grasp_receipt = _m2c_receipt(
        step_index=0,
        skill="GRASP",
        started_at_ns=m2c_grasp_started_at_ns,
        motions=[phases["pregrasp"], contact_attempts[-1]["motion"]],
        physical_passed=bool(
            feedback.grasp_success
            and contact_attempts[-1]["motion_gate"]["passed"]
        ),
        measurements={
            "bilateral_contact": bool(feedback.grasp_success),
            "motion_gate_passed": bool(contact_attempts[-1]["motion_gate"]["passed"]),
            "contact_centerline_m": float(contact_attempts[-1]["contact_centerline_m"]),
        },
    )
    m2c_chain_steps.append(_m2c_step(
        step_index=0, skill="GRASP", observation=m2c_grasp_observation,
        target_track_id=m2c_grasp_public.track_id, destination_cell=None,
        receipt=m2c_grasp_receipt,
    ))
    m2c_lift_tracks, m2c_lift_observation = _m2c_capture(
        m2b_public_rgbd, step_index=1, skill="LIFT",
    )
    m2c_lift_public = _m2c_select_public_track(
        m2c_lift_tracks,
        visual_color=ARGS.m2b_injected_public_grasp_color,
    )
    m2c_lift_started_at_ns = int(m2c_lift_observation["captured_at_ns"]) + 1
    hand_before, _ = _live_pose(hand_prim)
    object_path = f"/World/M1B/{entity}/link"
""",
    )
    source = _replace_once(
        source,
        "    m2b_public_after_lift: list[Any] | None = None\n",
        """    m2c_lift_receipt = _m2c_receipt(
        step_index=1,
        skill="LIFT",
        started_at_ns=m2c_lift_started_at_ns,
        motions=[phases["lift"]],
        physical_passed=attached_follow_pass,
        measurements={"object_lift_m": float(object_motion[2]), "follow_error_m": follow_error_m},
    )
    m2c_chain_steps.append(_m2c_step(
        step_index=1, skill="LIFT", observation=m2c_lift_observation,
        target_track_id=m2c_lift_public.track_id, destination_cell=None,
        receipt=m2c_lift_receipt,
    ))
    m2b_public_after_lift: list[Any] | None = None
""",
    )
    source = _replace_once(
        source,
        """        transport_hand_start, _ = _live_pose(hand_prim)
        transport_object_start, _ = _live_pose(object_prim)
""",
        """        m2c_move_tracks, m2c_move_observation = _m2c_capture(
            m2b_public_rgbd, step_index=2, skill="MOVE",
        )
        m2c_move_public = _m2c_select_public_track(
            m2c_move_tracks,
            visual_color=ARGS.m2b_injected_public_grasp_color,
        )
        m2c_move_started_at_ns = int(m2c_move_observation["captured_at_ns"]) + 1
        transport_hand_start, _ = _live_pose(hand_prim)
        transport_object_start, _ = _live_pose(object_prim)
""",
    )
    source = _replace_once(
        source,
        """        transport_hand_goal = desired_object_world_m + hand_object_offset_m
        transport_motion = _step_pose(
            robot,
            transport_hand_goal,
            steps=180,
            orientation_wxyz=top_down_orientation_wxyz,
            contact_collector=contact_collector,
            collision_phase="M2C_SCRIPTED_SAFE_PLACE_TRANSPORT",
            allowed_robot_contact_paths=(LEFT_FINGER_PATH, RIGHT_FINGER_PATH),
            allowed_external_contact_paths=(object_path,),
        )
""",
        """        transport_hand_goal = desired_object_world_m + hand_object_offset_m
        move_hand_goal = transport_hand_goal + np.asarray([0.0, 0.0, 0.10], dtype=np.float32)
        move_motion = _step_pose(
            robot,
            move_hand_goal,
            steps=150,
            orientation_wxyz=top_down_orientation_wxyz,
            contact_collector=contact_collector,
            collision_phase="M2C_MODEL_CHAIN_MOVE",
            allowed_robot_contact_paths=(LEFT_FINGER_PATH, RIGHT_FINGER_PATH),
            allowed_external_contact_paths=(object_path,),
        )
        m2c_move_receipt = _m2c_receipt(
            step_index=2, skill="MOVE", started_at_ns=m2c_move_started_at_ns,
            motions=[move_motion],
            physical_passed=move_motion["collision_gate"]["status"] == "PASS",
            measurements={
                "final_error_m": float(move_motion["final_error_m"]),
                "commanded_goal_world_m": [float(value) for value in move_hand_goal],
            },
        )
        m2c_chain_steps.append(_m2c_step(
            step_index=2, skill="MOVE", observation=m2c_move_observation,
            target_track_id=m2c_move_public.track_id,
            destination_cell=f"BIN_CELL_{ARGS.m2c_scripted_safe_place_bin_cell}",
            receipt=m2c_move_receipt,
        ))
        m2c_place_tracks, m2c_place_observation = _m2c_capture(
            m2b_public_rgbd, step_index=3, skill="PLACE",
        )
        m2c_place_public = _m2c_select_public_track(
            m2c_place_tracks,
            visual_color=ARGS.m2b_injected_public_grasp_color,
        )
        m2c_place_started_at_ns = int(m2c_place_observation["captured_at_ns"]) + 1
        transport_motion = _step_pose(
            robot,
            transport_hand_goal,
            steps=90,
            orientation_wxyz=top_down_orientation_wxyz,
            contact_collector=contact_collector,
            collision_phase="M2C_MODEL_CHAIN_PLACE",
            allowed_robot_contact_paths=(LEFT_FINGER_PATH, RIGHT_FINGER_PATH),
            allowed_external_contact_paths=(object_path,),
        )
""",
    )
    source = _replace_once(
        source,
        "        hand_after = transport_hand_end\n\n    _remove_attachment()\n",
        """        m2c_place_receipt = _m2c_receipt(
            step_index=3, skill="PLACE", started_at_ns=m2c_place_started_at_ns,
            motions=[transport_motion], physical_passed=transport_passed,
            measurements={"destination_error_m": destination_error_m, "follow_error_m": transport_follow_error_m},
        )
        m2c_chain_steps.append(_m2c_step(
            step_index=3, skill="PLACE", observation=m2c_place_observation,
            target_track_id=m2c_place_public.track_id,
            destination_cell=f"BIN_CELL_{ARGS.m2c_scripted_safe_place_bin_cell}",
            receipt=m2c_place_receipt,
        ))
        hand_after = transport_hand_end

    m2c_release_tracks, m2c_release_observation = _m2c_capture(
        m2b_public_rgbd, step_index=4, skill="RELEASE",
    )
    m2c_release_public = _m2c_select_public_track(
        m2c_release_tracks,
        visual_color=ARGS.m2b_injected_public_grasp_color,
    )
    m2c_release_started_at_ns = int(m2c_release_observation["captured_at_ns"]) + 1
    _remove_attachment()
""",
    )
    source = _replace_once(
        source,
        "    m2b_public_after_recovery: list[Any] | None = None\n",
        """    m2c_release_receipt = _m2c_receipt(
        step_index=4, skill="RELEASE", started_at_ns=m2c_release_started_at_ns,
        motions=[phases["detach_retreat"]],
        physical_passed=detached_noncoupling_pass,
        measurements={
            "attachment_absent_after_detach": bool(attachment_absent_after_detach),
            "hand_motion_m": detached_hand_motion_m,
            "relative_change_m": detached_relative_change_m,
        },
    )
    m2c_chain_steps.append(_m2c_step(
        step_index=4, skill="RELEASE", observation=m2c_release_observation,
        target_track_id=m2c_release_public.track_id, destination_cell=None,
        receipt=m2c_release_receipt,
    ))
    m2b_public_after_recovery: list[Any] | None = None
""",
    )
    source = _replace_once(
        source,
        """        m2b_public_after_recovery = _capture_m2b_public_rgbd(
            m2b_public_rgbd,
            label="after_recovery_retreat",
        )
""",
        """        m2c_reobserve_tracks, m2c_reobserve_observation = _m2c_capture(
            m2b_public_rgbd, step_index=5, skill="REOBSERVE",
        )
        m2b_public_after_recovery = m2c_reobserve_tracks
        m2c_reobserve_started_at_ns = int(m2c_reobserve_observation["captured_at_ns"]) + 1
        simulation_app.update()
        m2c_reobserve_receipt = _m2c_receipt(
            step_index=5, skill="REOBSERVE",
            started_at_ns=m2c_reobserve_started_at_ns, motions=[],
            physical_passed=True,
            measurements={
                "capture_receipt_sha256": m2c_reobserve_observation["capture_receipt_sha256"],
                "fresh_public_track_count": len(m2c_reobserve_tracks),
            },
        )
        m2c_chain_steps.append(_m2c_step(
            step_index=5, skill="REOBSERVE", observation=m2c_reobserve_observation,
            target_track_id=None, destination_cell=None,
            receipt=m2c_reobserve_receipt,
        ))
""",
    )
    source = _replace_once(
        source,
        "            try:\n                m2b_reassociated_target = reassociate_task_target_track(\n",
        """            m2c_reassociate_tracks, m2c_reassociate_observation = _m2c_capture(
                m2b_public_rgbd, step_index=6, skill="REASSOCIATE_TARGET",
            )
            m2c_reassociate_started_at_ns = int(m2c_reassociate_observation["captured_at_ns"]) + 1
            try:
                m2b_reassociated_target = reassociate_task_target_track(
""",
    )
    source = _replace_once(
        source,
        "                    m2b_public_after_recovery,\n                    task_target_track_id=m2b_task_target_track_id,\n                )\n            except ValueError as error:\n",
        """                    m2c_reassociate_tracks,
                    task_target_track_id=m2b_task_target_track_id,
                )
            except ValueError as error:
""",
    )
    source = _replace_once(
        source,
        "                m2b_reassociation_error = str(error)\n",
        """                m2b_reassociation_error = str(error)
            if m2b_reassociated_target is None:
                raise RuntimeError("fresh public task target could not be reassociated")
            reassociated_id = m2b_reassociated_target.track_id
            simulation_app.update()
            m2c_reassociate_receipt = _m2c_receipt(
                step_index=6, skill="REASSOCIATE_TARGET",
                started_at_ns=m2c_reassociate_started_at_ns, motions=[],
                physical_passed=m2b_reassociated_target is not None,
                measurements={
                    "capture_receipt_sha256": m2c_reassociate_observation["capture_receipt_sha256"],
                    "reassociated_public_track_id": reassociated_id,
                },
            )
            m2c_chain_steps.append(_m2c_step(
                step_index=6, skill="REASSOCIATE_TARGET",
                observation=m2c_reassociate_observation,
                target_track_id=reassociated_id, destination_cell=None,
                receipt=m2c_reassociate_receipt,
            ))
""",
    )
    source = _replace_once(
        source,
        "            m2b_wrong_regrasp = _execute_m2b_public_regrasp(\n",
        """            m2c_regrasp_tracks, m2c_regrasp_observation = _m2c_capture(
                m2b_public_rgbd, step_index=7, skill="REGRASP",
            )
            m2c_regrasp_target = reassociate_task_target_track(
                m2c_reassociate_tracks,
                m2c_regrasp_tracks,
                task_target_track_id=m2b_reassociated_target.track_id,
            )
            m2c_regrasp_started_at_ns = int(m2c_regrasp_observation["captured_at_ns"]) + 1
            m2b_wrong_regrasp = _execute_m2b_public_regrasp(
""",
    )
    source = _replace_once(
        source,
        """                public_target_world_m=(
                    m2b_reassociated_target.position_world_m
                ),
                public_tracks=m2b_public_after_recovery,
""",
        """                public_target_world_m=m2c_regrasp_target.position_world_m,
                public_tracks=m2c_regrasp_tracks,
""",
    )
    source = _replace_once(
        source,
        "    same_process_reset = (\n",
        """            m2c_regrasp_motions = [
                motion for motion in (
                    m2b_wrong_regrasp.get("pregrasp_motion"),
                    next(
                        (
                            attempt.get("contact_motion")
                            for attempt in reversed(m2b_wrong_regrasp.get("attempts", []))
                            if attempt.get("motion_gate_passed")
                        ),
                        None,
                    ),
                    m2b_wrong_regrasp.get("lift_motion"),
                ) if isinstance(motion, dict)
            ]
            m2c_regrasp_receipt = _m2c_receipt(
                step_index=7, skill="REGRASP",
                started_at_ns=m2c_regrasp_started_at_ns,
                motions=m2c_regrasp_motions,
                physical_passed=m2b_wrong_regrasp.get("status") == "LIFTED",
                measurements={
                    "status": m2b_wrong_regrasp.get("status"),
                    "object_lift_m": float(m2b_wrong_regrasp.get("object_lift_m", 0.0)),
                    "follow_error_m": (
                        float(m2b_wrong_regrasp["follow_error_m"])
                        if m2b_wrong_regrasp.get("follow_error_m") is not None
                        and np.isfinite(float(m2b_wrong_regrasp["follow_error_m"]))
                        else None
                    ),
                },
            )
            m2c_chain_steps.append(_m2c_step(
                step_index=7, skill="REGRASP", observation=m2c_regrasp_observation,
                target_track_id=m2c_regrasp_target.track_id,
                destination_cell=None, receipt=m2c_regrasp_receipt,
            ))
    same_process_reset = (
""",
    )
    source = _replace_once(
        source,
        '            "m2b_recovery": {\n',
        """            "m2c_path_blocked_physical_chain": {
                "schema_version": "M2CPathBlockedProbeChainV2",
                "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
                "episode_id": f"{ARGS.m2c_matched_key}-failure-{ARGS.m2c_failure_seed}",
                "scene_seed": SCENE.scene_seed,
                "failure_seed": ARGS.m2c_failure_seed,
                "split": ARGS.m2c_split,
                "split_group": f"scene-{SCENE.scene_seed}",
                "matched_key": ARGS.m2c_matched_key,
                "collection_role": ARGS.m2c_chain_role,
                "collection_key": f"{ARGS.m2c_matched_key}-collection",
                "sdf_sha256": SCENE.source_sdf_sha256,
                "supervision_sha256": SCENE.source_supervision_sha256,
                "failure_type": "PATH_BLOCKED",
                "failure_observed_at_ns": m2c_failure_observed_at_ns,
                "steps": m2c_chain_steps,
                "final_task_success": bool(
                    len(m2c_chain_steps) == 8
                    and m2b_wrong_regrasp is not None
                    and m2b_wrong_regrasp.get("status") == "LIFTED"
                    and m2b_wrong_public_lift_success is not None
                    and {"grasped=true", "lifted=true"}.issubset(
                        m2b_wrong_public_lift_success.predicates
                    )
                ),
                "model_rollout": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
            "m2b_recovery": {
""",
    )
    return source.encode("utf-8")


def derive_probe_bytes_v3(upstream: bytes) -> bytes:
    """Derive the ADR-0021 TRAIN-only probe without reinterpreting V2 bytes."""

    source = derive_probe_bytes(upstream).decode("utf-8")
    source = _replace_once(
        source,
        "from xh_agent.policy.qrm_lite.public_tracks_v2 import canonical_track_slots\n",
        """from xh_agent.policy.qrm_lite.public_tracks_v3 import (
    build_public_track_candidates_v3,
    canonical_candidate_payload_v3,
    canonical_candidate_sha256_v3,
)
""",
    )
    source = _replace_once(
        source,
        '    parser.add_argument("--m2c-failure-seed", type=int, required=True)\n',
        """    parser.add_argument("--m2c-failure-seed", type=int, required=True)
    parser.add_argument("--m2c-declared-target-attribute", required=True)
    parser.add_argument("--m2c-collection-claim", type=Path, required=True)
    parser.add_argument("--m2c-probe-start-capability", type=Path, required=True)
    parser.add_argument("--m2c-probe-entry-broker-socket", type=Path, required=True)
    parser.add_argument("--m2c-probe-entry-token-file", type=Path, required=True)
    parser.add_argument("--m2c-source-snapshot-root", type=Path, required=True)
    parser.add_argument("--m2c-container-image-id", required=True)
    parser.add_argument("--m2c-docker-command-sha256", required=True)
    parser.add_argument("--m2c-stage-metrics-sha256", required=True)
    parser.add_argument("--m2c-stage-command-sha256", required=True)
    parser.add_argument("--m2c-job-root-sha256", required=True)
    parser.add_argument("--m2c-probe-output-root-sha256", required=True)
""",
    )
    authorization = """M2C_V3_COLLECTION_AUTHORIZATION = authorize_probe_start(
    claim_path=ARGS.m2c_collection_claim,
    start_capability_path=ARGS.m2c_probe_start_capability,
    probe_entry_broker_socket=ARGS.m2c_probe_entry_broker_socket,
    probe_entry_token_file=ARGS.m2c_probe_entry_token_file,
    source_snapshot_root=ARGS.m2c_source_snapshot_root,
    matched_key=ARGS.m2c_matched_key,
    failure_seed=ARGS.m2c_failure_seed,
    source_sdf_sha256=sha256_file(ARGS.sdf),
    source_supervision_sha256=sha256_file(ARGS.supervision),
    source_urdf_sha256=sha256_file(ARGS.urdf),
    upstream_v4_probe_sha256="6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87",
    stage_usdc_sha256=sha256_file(ARGS.stage),
    stage_metrics_sha256=ARGS.m2c_stage_metrics_sha256,
    stage_command_sha256=ARGS.m2c_stage_command_sha256,
    derived_probe_sha256=sha256_file(__file__),
    container_image_id=ARGS.m2c_container_image_id,
    probe_argv=__import__("sys").argv,
    job_root_sha256=ARGS.m2c_job_root_sha256,
    probe_output_root_sha256=ARGS.m2c_probe_output_root_sha256,
    role=ARGS.m2c_chain_role,
    split=ARGS.m2c_split,
    declared_target_attribute=ARGS.m2c_declared_target_attribute,
    destination_cell=f"BIN_CELL_{ARGS.m2c_scripted_safe_place_bin_cell}",
).model_dump(mode="json")

"""
    source = _replace_once(
        source,
        "# This guard lives inside the derived probe, before Kit/SimulationApp starts,\n",
        """from xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1 import (
    authorize_probe_start,
)

# This guard lives inside the derived probe, before Kit/SimulationApp starts,
"""
        + authorization,
    )
    source = _replace_once(
        source,
        '    slots = canonical_track_slots(public_tracks)\n    observation = {\n        "schema_version": "PathBlockedPublicObservationV2",\n',
        """    candidates = build_public_track_candidates_v3(
        public_tracks,
        declared_target_attribute=ARGS.m2c_declared_target_attribute,
    )
    candidate_payload = canonical_candidate_payload_v3(candidates)
    observation = {
        "schema_version": "PathBlockedPublicObservationV3",
""",
    )
    source = _replace_once(
        source,
        """        "canonical_slots": [
            track.track_id if track is not None else None
            for track in slots.tracks
        ],
""",
        """        "declared_target_attribute": ARGS.m2c_declared_target_attribute,
        "candidate_payload": candidate_payload,
        "candidate_payload_sha256": canonical_candidate_sha256_v3(candidates),
        "task_target_track_id_used_for_candidates": False,
""",
    )
    source = _replace_once(
        source,
        '    slots = [track for track in observation["canonical_slots"] if track is not None]\n',
        """    slots = [
        candidate["track_id"]
        for candidate in observation["candidate_payload"]["candidates"]
    ]
""",
    )
    source = _replace_once(
        source,
        '        "schema_version": "PathBlockedPhysicalStepEvidenceV2",\n',
        '        "schema_version": "PathBlockedPhysicalStepEvidenceV3",\n',
    )
    source = _replace_once(
        source,
        '                "schema_version": "M2CPathBlockedProbeChainV2",\n',
        """                "schema_version": "M2CPathBlockedProbeChainV3",
                "declared_target_attribute": ARGS.m2c_declared_target_attribute,
                "candidate_contract_revision": "PublicTrackCandidateV3",
                "checkpoint_architecture_revision": "M2C_Q012_V3",
                "collection_authorization_sha256": __import__("hashlib").sha256(
                    json.dumps(
                        M2C_V3_COLLECTION_AUTHORIZATION,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
""",
    )
    source = _replace_once(
        source,
        '            "m2c_path_blocked_physical_chain": {\n',
        '            "m2c_v3_collection_authorization": M2C_V3_COLLECTION_AUTHORIZATION,\n'
        '            "m2c_path_blocked_physical_chain": {\n',
    )
    # V3 is TRAIN-only, so the inherited role-aware hard-freeze call is
    # exactly the required collection guard. Move authorization immediately
    # after it instead of adding a duplicate gate or consuming before it.
    guard = """require_pre_freeze(
    M2CExperimentAction.SMOKE
    if ARGS.m2c_chain_role == "SMOKE"
    else M2CExperimentAction.ISAAC_COLLECTION
)

"""
    source = _replace_once(source, authorization, "")
    source = _replace_once(source, guard, guard + authorization)
    # ADR-0021 permits only new TRAIN collection.  The V3 worker separately
    # enforces TRAIN, but the derived executable also fails closed itself.
    source = source.replace(
        'parser.add_argument(\n        "--m2c-chain-role", choices=("TRAIN", "SMOKE"), required=True\n    )',
        'parser.add_argument(\n        "--m2c-chain-role", choices=("TRAIN",), required=True\n    )',
        1,
    )
    return source.encode("utf-8")


def derive_probe_bytes_v4(upstream: bytes) -> bytes:
    """Derive ADR-0024 V4 raw capture-history collection plumbing.

    The Isaac process records only unassociated public RGB-D detections,
    ordered public robot-proprioception samples, the last physically executed
    public skill, and exact public frame/calibration fields.  It intentionally
    does not assign V2 identities: the host packager independently constructs
    the journal, replays ``PublicTrackAssociatorV2``, and builds V4 K=8 slots.
    """

    source = derive_probe_bytes_v3(upstream).decode("utf-8")
    source = _replace_once(
        source,
        "from xh_agent.policy.qrm_lite.public_tracks_v3 import (\n"
        "    build_public_track_candidates_v3,\n"
        "    canonical_candidate_payload_v3,\n"
        "    canonical_candidate_sha256_v3,\n"
        ")\n",
        """from xh_agent.perception.public_track_associator_v2 import (
    PublicAssociationProtocolV2,
    PublicBBoxOrMaskV2,
    PublicDetectionAttributesV2,
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
)
""",
    )
    source = _replace_once(
        source,
        "from xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1 import (\n"
        "    authorize_probe_start,\n"
        ")\n",
        """from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    bind_consumed_claim_to_raw_session,
)
""",
    )
    source = source.replace(
        '    parser.add_argument("--m2c-probe-start-capability", type=Path, required=True)\n'
        '    parser.add_argument("--m2c-probe-entry-broker-socket", type=Path, required=True)\n'
        '    parser.add_argument("--m2c-probe-entry-token-file", type=Path, required=True)\n',
        "",
        1,
    )
    authorization_start = source.index("M2C_V3_COLLECTION_AUTHORIZATION = authorize_probe_start(")
    authorization_end = source.index(
        ').model_dump(mode="json")\n\n',
        authorization_start,
    ) + len(').model_dump(mode="json")\n\n')
    source = (
        source[:authorization_start]
        + """M2C_V3_COLLECTION_AUTHORIZATION = bind_consumed_claim_to_raw_session(
    claim_path=ARGS.m2c_collection_claim,
    source_snapshot_root=ARGS.m2c_source_snapshot_root,
    matched_key=ARGS.m2c_matched_key,
    failure_seed=ARGS.m2c_failure_seed,
    source_sdf_sha256=sha256_file(ARGS.sdf),
    source_supervision_sha256=sha256_file(ARGS.supervision),
    source_urdf_sha256=sha256_file(ARGS.urdf),
    upstream_v4_probe_sha256="6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87",
    derived_probe_sha256=sha256_file(__file__),
    container_image_id=ARGS.m2c_container_image_id,
    role=ARGS.m2c_chain_role,
    split=ARGS.m2c_split,
    declared_target_attribute=ARGS.m2c_declared_target_attribute,
    destination_cell=f"BIN_CELL_{ARGS.m2c_scripted_safe_place_bin_cell}",
).model_dump(mode="json")

"""
        + source[authorization_end:]
    )
    source = source.replace("M2C_V3_COLLECTION_AUTHORIZATION", "M2C_V4_COLLECTION_AUTHORIZATION")
    source = _replace_once(
        source,
        "def _m2c_now_ns() -> int:\n",
        """M2C_V4_PROPRIOCEPTION_JOURNAL: list[dict[str, object]] = []
M2C_V4_LAST_EXECUTED_PUBLIC_SKILL: dict[str, object] | None = None


def _m2c_now_ns() -> int:
""",
    )
    source = _replace_once(
        source,
        "def _m2c_capture(\n",
        """def _m2c_v4_public_proprioception(
    *,
    timestamp_ns: int,
) -> dict[str, object]:
    position, orientation_wxyz = _live_pose(M2C_V4_PUBLIC_HAND_PRIM)
    finger_positions = _array_or_list(M2C_V4_PUBLIC_ROBOT.get_dof_positions())[0][-2:]
    width_m = float(sum(float(value) for value in finger_positions))
    return PublicRobotProprioceptionV2(
        timestamp_ns=timestamp_ns,
        world_frame="world",
        end_effector_position_world_m=[float(value) for value in position],
        end_effector_orientation_world_xyzw=[
            float(orientation_wxyz[1]),
            float(orientation_wxyz[2]),
            float(orientation_wxyz[3]),
            float(orientation_wxyz[0]),
        ],
        gripper_width_m=width_m,
        gripper_closed=bool(width_m <= 0.002),
    ).model_dump(mode="json")


def _m2c_v4_record_proprioception_sample() -> None:
    if "M2C_V4_PUBLIC_ROBOT" not in globals():
        return
    # The upstream probe intentionally performs one Kit update before
    # timeline play so contact-report USD edits are visible to PhysX.  Isaac's
    # articulation exists at that point, but its tensor entity is not valid
    # until play + initialize_physics.  This update is not a public control
    # sample and must not query DOF state.
    if not M2C_V4_PUBLIC_ROBOT.is_physics_tensor_entity_valid():
        return
    timestamp_ns = _m2c_now_ns()
    if M2C_V4_PROPRIOCEPTION_JOURNAL and int(
        M2C_V4_PROPRIOCEPTION_JOURNAL[-1]["timestamp_ns"]
    ) == timestamp_ns:
        return
    M2C_V4_PROPRIOCEPTION_JOURNAL.append(
        _m2c_v4_public_proprioception(timestamp_ns=timestamp_ns)
    )


def _m2c_capture(
""",
    )
    capture_start = source.index("def _m2c_capture(\n")
    selector_start = source.index("\n\ndef _m2c_select_public_track(\n", capture_start)
    replacement = r"""def _m2c_capture(
    runtime: dict[str, Any],
    *,
    step_index: int,
    skill: str,
) -> tuple[list[Any], dict[str, object]]:
    tracks = _capture_m2b_public_rgbd(
        runtime, label=f"m2c_step_{step_index:02d}_{skill.lower()}"
    )
    capture = runtime["captures"][-1]
    timestamp_ns = int(capture["timestamp_ns"])
    _m2c_v4_record_proprioception_sample()
    interval_start_ns = (
        timestamp_ns
        if not M2C_V4_RAW_ASSOCIATION_CAPTURES
        else int(M2C_V4_RAW_ASSOCIATION_CAPTURES[-1]["timestamp_ns"])
    )
    interval_samples = [
        sample
        for sample in M2C_V4_PROPRIOCEPTION_JOURNAL
        if interval_start_ns <= int(sample["timestamp_ns"]) <= timestamp_ns
    ]
    if not interval_samples or int(interval_samples[-1]["timestamp_ns"]) != timestamp_ns:
        raise RuntimeError("V4 public proprioception journal lacks the capture endpoint")
    if not M2C_V4_RAW_ASSOCIATION_CAPTURES:
        interval_samples = [interval_samples[-1]]
    detections = []
    for result in runtime["last_unassociated_public_results"]:
        detections.append(
            PublicRGBDDetectionV2(
                timestamp_ns=timestamp_ns,
                frame_id="m2b_policy_rgbd_optical",
                category=result.category,
                attributes=PublicDetectionAttributesV2(
                    visual_color=result.attributes.get("visual_color")
                ),
                position_3d=[float(value) for value in result.position_3d],
                confidence=float(result.confidence),
                bbox_or_mask=PublicBBoxOrMaskV2(
                    x=int(result.bbox_or_mask.x),
                    y=int(result.bbox_or_mask.y),
                    width=int(result.bbox_or_mask.width),
                    height=int(result.bbox_or_mask.height),
                ),
                visibility=float(result.visibility),
                covariance_or_quality={
                    str(key): float(value)
                    for key, value in result.covariance_or_quality.items()
                },
            ).model_dump(mode="json")
        )
    raw_capture = {
        "schema_version": "M2CV4RawPublicAssociationCaptureV2",
        "raw_detection_capacity_revision": "M2C_V4_RAW_PUBLIC_DETECTIONS_32_V1",
        "max_raw_public_detections": 32,
        "timestamp_ns": timestamp_ns,
        "camera_frame": "m2b_policy_rgbd_optical",
        "world_frame": "world",
        "position_units": "m",
        "camera_to_world_row_major": [
            float(value) for value in runtime["camera_to_world_optical"]
        ],
        "detections": detections,
        "proprioception_interval": interval_samples,
        "last_physically_executed_public_skill": M2C_V4_LAST_EXECUTED_PUBLIC_SKILL,
        "rgb_uri": capture["rgb_uri"],
        "depth_uri": capture["depth_uri"],
        "rgb_sha256": capture["rgb_sha256"],
        "depth_sha256": capture["depth_sha256"],
    }
    raw_capture_receipt_sha256 = __import__("hashlib").sha256(
        json.dumps(raw_capture, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    M2C_V4_RAW_ASSOCIATION_CAPTURES.append(raw_capture)
    observation = {
        "schema_version": "PathBlockedRawPublicObservationV4",
        "observation_id": f"{ARGS.m2c_matched_key}-observation-{step_index}",
        "captured_at_ns": timestamp_ns,
        "source": "PUBLIC_RGBD",
        "fresh": True,
        "rgb_uri": capture["rgb_uri"],
        "depth_uri": capture["depth_uri"],
        "rgb_sha256": capture["rgb_sha256"],
        "depth_sha256": capture["depth_sha256"],
        "capture_receipt_sha256": raw_capture_receipt_sha256,
        "association_capture_index": len(M2C_V4_RAW_ASSOCIATION_CAPTURES) - 1,
        "declared_target_attribute": ARGS.m2c_declared_target_attribute,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "task_target_track_id_used_for_candidates": False,
    }
    return tracks, observation"""
    source = source[:capture_start] + replacement + source[selector_start:]
    # Capture the geometric detector outputs before the legacy V1 tracker can
    # influence V4 evidence. The legacy snapshots are retained only for the
    # inherited scripted physical selector, never as V4 model input.
    source = _replace_once(
        source,
        "    snapshots = snapshots_from_perception_results(\n"
        "        public_results,\n"
        '        runtime["camera_to_world_optical"],\n'
        "    )\n",
        """    runtime["last_unassociated_public_results"] = public_results
    snapshots = snapshots_from_perception_results(
        public_results,
        runtime["camera_to_world_optical"],
    )
""",
    )
    source = _replace_once(
        source,
        "def main() -> int:\n",
        """def main() -> int:
    global M2C_V4_PUBLIC_ROBOT
    global M2C_V4_PUBLIC_HAND_PRIM
    global M2C_V4_RAW_ASSOCIATION_CAPTURES
    global M2C_V4_PROPRIOCEPTION_JOURNAL
    global M2C_V4_LAST_EXECUTED_PUBLIC_SKILL
    M2C_V4_RAW_ASSOCIATION_CAPTURES = []
    M2C_V4_PROPRIOCEPTION_JOURNAL = []
    M2C_V4_LAST_EXECUTED_PUBLIC_SKILL = None
""",
    )
    source = _replace_once(
        source,
        "    target_object_prim = RigidPrim(target_object_path)\n",
        """    target_object_prim = RigidPrim(target_object_path)
    M2C_V4_PUBLIC_ROBOT = robot
    M2C_V4_PUBLIC_HAND_PRIM = hand_prim
""",
    )
    # Record every public 60 Hz control update, including gripper motion, so
    # whole-interval HAND_CARRY eligibility is replayable without a claimed
    # completeness boolean.
    instrumented_lines: list[str] = []
    for line in source.splitlines(keepends=True):
        instrumented_lines.append(line)
        if line.lstrip() == "simulation_app.update()\n":
            indentation = line[: len(line) - len(line.lstrip())]
            instrumented_lines.append(indentation + "_m2c_v4_record_proprioception_sample()\n")
    source = "".join(instrumented_lines)
    source = _replace_once(
        source,
        "def _m2c_receipt(\n",
        """def _m2c_v4_mark_last_skill(*, skill: str, started_at_ns: int, completed_at_ns: int) -> None:
    global M2C_V4_LAST_EXECUTED_PUBLIC_SKILL
    M2C_V4_LAST_EXECUTED_PUBLIC_SKILL = {
        "schema_version": "LastPhysicallyExecutedPublicSkillV2",
        "skill_name": skill,
        "started_at_ns": started_at_ns,
        "completed_at_ns": completed_at_ns,
    }


def _m2c_receipt(
""",
    )
    source = _replace_once(
        source,
        '    digest = __import__("hashlib").sha256(\n',
        """    _m2c_v4_mark_last_skill(
        skill=skill,
        started_at_ns=started_at_ns,
        completed_at_ns=completed_at_ns,
    )
    digest = __import__("hashlib").sha256(
""",
    )
    # Raw V4 steps deliberately contain no tracker-generated pointer. The host
    # replay injects V4 observations/pointers before schema validation.
    step_start = source.index("def _m2c_step(\n")
    next_function = source.index("\n\ndef _execute_m2b_public_regrasp(\n", step_start)
    step_replacement = r"""def _m2c_step(
    *,
    step_index: int,
    skill: str,
    observation: dict[str, object],
    target_track_id: str | None,
    destination_cell: str | None,
    receipt: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "PathBlockedRawPhysicalStepEvidenceV4",
        "decision_index": step_index,
        "observation": observation,
        "scripted_public_selector_color": (
            ARGS.m2b_injected_public_grasp_color
            if step_index <= 4
            else ARGS.m2b_task_target_public_color
            if step_index >= 6
            else None
        ),
        "destination_cell_label": destination_cell,
        "physical_receipts": [receipt],
        "label_source": "PUBLIC_RGBD_PHYSICAL_SUPERVISION",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }"""
    source = source[:step_start] + step_replacement + source[next_function:]
    source = source.replace(
        '"schema_version": "M2CPathBlockedProbeChainV3",',
        '"schema_version": "M2CPathBlockedRawProbeChainV4",',
        1,
    )
    source = source.replace('"PublicTrackCandidateV3"', '"PublicTrackCandidateV4"')
    source = source.replace('"M2C_Q012_V3"', '"M2C_Q012_V4"')
    source = source.replace(
        '            "m2c_v3_collection_authorization": M2C_V4_COLLECTION_AUTHORIZATION,\n',
        '            "m2c_v4_collection_authorization": M2C_V4_COLLECTION_AUTHORIZATION,\n'
        '            "m2c_v4_raw_association_captures": M2C_V4_RAW_ASSOCIATION_CAPTURES,\n',
        1,
    )
    source = source.replace(
        '"collection_authorization_sha256": __import__("hashlib").sha256(',
        '"collection_authorization_sha256": __import__("hashlib").sha256(',
        1,
    )
    return source.encode("utf-8")


def derive_probe_file(upstream: Path, output: Path, *, revision: str = "V2") -> str:
    derived = {
        "V2": derive_probe_bytes,
        "V3": derive_probe_bytes_v3,
        "V4": derive_probe_bytes_v4,
    }[revision](upstream.read_bytes())
    output.write_bytes(derived)
    output.chmod(0o555)
    return sha256_bytes(derived)


def _canonical_sha256(payload: object) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def build_collection_manifests(
    training_keys: dict[str, object],
    evaluation_keys: dict[str, object],
    *,
    runtime_registry_sha256: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Project the committed key identities into strict raw-evidence manifests."""

    collection_records: list[dict[str, object]] = []
    for role, field in (
        ("TRAIN", "training_keys"),
        ("SMOKE", "physical_prerequisite_smoke_keys"),
    ):
        for record in training_keys[field]:  # type: ignore[index]
            matched_key = str(record["matched_key"])
            scene_seed = int(record["scene_seed"])
            collection_records.append(
                {
                    "schema_version": "PathBlockedCollectionKeyV2",
                    "collection_key": f"{matched_key}-collection",
                    "collection_role": role,
                    "matched_key": matched_key,
                    "scene_seed": scene_seed,
                    "failure_seed": int(record["failure_seed"]),
                    "split": str(record["split"]),
                    "split_group": f"scene-{scene_seed}",
                }
            )
    collection = {
        "schema_version": "FrozenPathBlockedCollectionManifestV2",
        "manifest_key": "M2C_S4_FROZEN_TRAIN_SMOKE_KEYS",
        "frozen_before_collection": True,
        "runtime_registry_sha256": runtime_registry_sha256,
        "skill_labels": list(M2C_Q012_V2_SKILL_LABELS),
        "pointer_class_labels": list(POINTER_CLASS_LABELS),
        "destination_class_labels": list(DESTINATION_CLASS_LABELS),
        "keys": collection_records,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    s6 = {
        "schema_version": "FrozenS6ExclusionManifestV2",
        "manifest_key": "M2C_S6_FROZEN_EVALUATION_KEYS",
        "frozen_before_q_b_training": True,
        "keys": [
            {
                "schema_version": "FrozenS6EvaluationKeyV2",
                "matched_key": record["matched_key"],
                "scene_seed": record["scene_seed"],
                "failure_seed": record["failure_seed"],
            }
            for record in evaluation_keys["evaluation_keys"]  # type: ignore[index]
        ],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return collection, s6


def write_collection_manifests(
    *,
    training_keys_path: Path,
    evaluation_keys_path: Path,
    runtime_registry_path: Path,
    collection_output: Path,
    s6_output: Path,
) -> tuple[str, str]:
    collection, s6 = build_collection_manifests(
        json.loads(training_keys_path.read_text()),
        json.loads(evaluation_keys_path.read_text()),
        runtime_registry_sha256=sha256_bytes(runtime_registry_path.read_bytes()),
    )
    for output, payload in ((collection_output, collection), (s6_output, s6)):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite frozen manifest: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return _canonical_sha256(collection), _canonical_sha256(s6)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--training-keys", type=Path)
    parser.add_argument("--evaluation-keys", type=Path)
    parser.add_argument("--runtime-registry", type=Path)
    parser.add_argument("--collection-manifest-output", type=Path)
    parser.add_argument("--s6-exclusion-output", type=Path)
    parser.add_argument("--revision", choices=("V2", "V3", "V4"), default="V2")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite derived probe: {args.output}")
    probe_sha256 = derive_probe_file(args.upstream, args.output, revision=args.revision)
    manifest_paths = (
        args.training_keys,
        args.evaluation_keys,
        args.runtime_registry,
        args.collection_manifest_output,
        args.s6_exclusion_output,
    )
    if any(path is not None for path in manifest_paths):
        if not all(path is not None for path in manifest_paths):
            parser.error("all five manifest arguments are required together")
        collection_sha, s6_sha = write_collection_manifests(
            training_keys_path=args.training_keys,
            evaluation_keys_path=args.evaluation_keys,
            runtime_registry_path=args.runtime_registry,
            collection_output=args.collection_manifest_output,
            s6_output=args.s6_exclusion_output,
        )
        print(
            json.dumps(
                {
                    "probe_sha256": probe_sha256,
                    "collection_manifest_sha256": collection_sha,
                    "s6_exclusion_manifest_sha256": s6_sha,
                },
                sort_keys=True,
            )
        )
    else:
        print(probe_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
