"""Persist one validated EpisodeTransition from a verified constrained transfer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from xh_agent.contracts.models import (
    ActionTrajectoryV0,
    CandidateSkillV0,
    EpisodeTransitionV0,
    ObservationV0,
    SimulatorSupervisionV0,
    SkillType,
    TaskSpecV0,
)

ARM_DIMENSIONS = [f"panda_joint{index}" for index in range(1, 8)]
APPROACH = [-0.307, 1.06, 0.76, -2.148, -1.435, 2.274, 1.422]
LIFT = [0.0] * 7
PLACE = [-1.9262, -1.6941, 2.8863, -1.9115, -0.9962, 3.0409, 2.2138]
# This calibration is from the world SDF's fixed RGB-D fixture, not simulator
# object truth. No object track is placed in ObservationV0 without perception.
CAMERA_INTRINSICS = [277.13, 0.0, 160.0, 0.0, 277.13, 120.0, 0.0, 0.0, 1.0]
CAMERA_EXTRINSICS = [-1.0, 0.0, 0.0, 0.35, 0.0, -0.8525, 0.5227, 0.0, 0.0, 0.5227, 0.8525, 1.07, 0.0, 0.0, 0.0, 1.0]


def _observation(status: dict[str, object], *, before: bool, episode_id: str) -> ObservationV0:
    joints = status["initial_joint_positions" if before else "final_joint_positions"]
    ee = status["initial_end_effector_pose" if before else "final_end_effector_pose"]
    if not isinstance(joints, list) or not isinstance(ee, list) or len(ee) != 7:
        raise ValueError("runtime report lacks observed joint positions or end-effector TF")
    return ObservationV0(
        episode_id=episode_id,
        step_id=0 if before else 1,
        timestamp_ns=int(datetime.now(tz=timezone.utc).timestamp() * 1_000_000_000),
        rgb_uri="ros-topic:///xh/camera/rgbd/image",
        depth_uri="ros-topic:///xh/camera/rgbd/depth_image",
        camera_intrinsics=CAMERA_INTRINSICS,
        camera_extrinsics=CAMERA_EXTRINSICS,
        joint_position=joints,
        joint_velocity=[],
        end_effector_pose=ee,
        gripper_state="open" if before else "released",
        object_tracks=[],
        relation_graph=[],
        current_task_id="p0-red-cube-to-bin-a",
        current_subgoal="approach" if before else "verify_placement",
        coordinate_frame="world",
        uncertainty=1.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", default="reports/p0-constrained-pick-place-status.json")
    parser.add_argument("--output", default="data/episodes/p0-constrained-transfer.json")
    args = parser.parse_args()
    status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    if status.get("status") != "VERIFIED_CONSTRAINED_PICK_PLACE":
        raise SystemExit("refusing to record: constrained pick-place was not verified")
    final = status.get("final_cube_pose_xyz")
    initial = status.get("initial_cube_pose_xyz")
    carried = status.get("carried_cube_pose_xyz")
    if not all(isinstance(item, list) and len(item) == 3 for item in (initial, carried, final)):
        raise SystemExit("refusing to record: missing measured cube poses")
    episode_id = "p0-constrained-transfer"
    transition = EpisodeTransitionV0(
        observation_before=_observation(status, before=True, episode_id=episode_id),
        task_spec=TaskSpecV0(
            task_id="p0-red-cube-to-bin-a", operation="pick_place", target_object_id="object_red_cube",
            reference_frame="world", destination="bin_a", goal_predicates=["in:bin_a"],
            ambiguity_score=0.0, need_clarification=False, source_instruction="Place the red cube in bin A.",
        ),
        candidate_skill=CandidateSkillV0(
            skill_type=SkillType.PLACE, target_object_id="object_red_cube", coordinate_frame="world",
            generated_by="B1_RULE_GEOMETRY", candidate_id="b1-p0-constrained-place",
            preconditions=["Gazebo detachable constraint attached", "lift clearance achieved"],
            expected_effects=["object_red_cube inside bin_a"],
        ),
        action_trajectory=ActionTrajectoryV0(
            embodiment="xh_panda_controlled", representation="joint_position", coordinate_frame="panda_joint_order",
            units="rad", fps=0.1, values=[APPROACH, LIFT, PLACE], dimension_names=ARM_DIMENSIONS,
            normalization_method="identity", normalization_revision="p0-v1", source_skill="PLACE", source_policy="B1_RULE_GEOMETRY",
        ),
        observation_after=_observation(status, before=False, episode_id=episode_id),
        simulator_supervision=SimulatorSupervisionV0(
            perfect_object_poses={"object_red_cube_initial": initial + [0.0, 0.0, 0.0, 1.0], "object_red_cube_carried": carried + [0.0, 0.0, 0.0, 1.0], "object_red_cube_final": final + [0.0, 0.0, 0.0, 1.0]},
            contacts=[{"sensor": "red_cube_contact", "observed": True}] if status.get("object_contact_supervision_observed") else [],
            collisions=[{"sensor": "red_cube_contact", "observed": True}] if status.get("object_contact_supervision_observed") else [],
            grasp_states={"object_red_cube_detachable_constraint": False},
            task_success=True, physical_parameters={"bin_inner_half_extent_m": 0.17},
            failure_injection={}, simulator="Gazebo Harmonic", simulator_version="gz-sim8",
        ),
        task_progress=1.0, failure_type=None,
        semantic_labels={"grasp_mode": "GAZEBO_DETACHABLE_JOINT_CONSTRAINT", "finger_contact_grasp_verified": False},
        provenance={"runtime_status": str(args.status), "host": str(status.get("host")), "truth_boundary": "object poses retained only in SimulatorSupervisionV0"},
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(transition.model_dump_json(indent=2) + "\n", encoding="utf-8")
    status["episode_recorded"] = True
    status["episode_path"] = str(output)
    Path(args.status).write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "RECORDED", "output": str(output), "task_success": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
