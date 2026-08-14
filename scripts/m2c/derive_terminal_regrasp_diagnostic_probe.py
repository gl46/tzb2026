#!/usr/bin/env python3
"""Derive the ADR-0026 terminal-regrasp diagnostic from frozen V4 helpers."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from m2c.derive_model_owned_chain_probe import (
    UPSTREAM_V4_PROBE_SHA256,
    derive_probe_bytes_v4,
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _replace_once(source: str, marker: str, replacement: str) -> str:
    if source.count(marker) != 1:
        raise ValueError(f"diagnostic derivation marker count is not one: {marker[:80]!r}")
    return source.replace(marker, replacement, 1)


def derive_terminal_regrasp_diagnostic_probe_bytes(upstream: bytes) -> bytes:
    """Reuse every frozen terminal primitive while adding diagnostic routing."""

    if sha256_bytes(upstream) != UPSTREAM_V4_PROBE_SHA256:
        raise ValueError("terminal diagnostic upstream V4 probe hash mismatch")
    source = derive_probe_bytes_v4(upstream).decode("utf-8")
    source = _replace_once(
        source,
        '        "--m2c-chain-role", choices=("TRAIN",), required=True\n',
        '        "--m2c-chain-role", choices=("DIAGNOSTIC",), required=True\n',
    )
    source = _replace_once(
        source,
        '    parser.add_argument("--m2c-declared-target-attribute", required=True)\n',
        """    parser.add_argument("--m2c-declared-target-attribute", required=True)
    parser.add_argument(
        "--m2c-diagnostic-condition",
        choices=("C1_NO_BLOCKER", "C2_RETAINED_BLOCKER", "C3_FULL_V4"),
        required=True,
    )
    parser.add_argument("--m2c-diagnostic-run-id", required=True)
""",
    )
    source = _replace_once(
        source,
        """from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    bind_consumed_claim_to_raw_session,
)
""",
        """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    bind_diagnostic_claim_to_raw_session,
)
""",
    )
    authorization_start = source.index(
        "M2C_V4_COLLECTION_AUTHORIZATION = bind_consumed_claim_to_raw_session("
    )
    authorization_end = source.index(
        ').model_dump(mode="json")\n\n',
        authorization_start,
    ) + len(').model_dump(mode="json")\n\n')
    authorization = """M2C_V4_COLLECTION_AUTHORIZATION = bind_diagnostic_claim_to_raw_session(
    claim_path=ARGS.m2c_collection_claim,
    source_snapshot_root=ARGS.m2c_source_snapshot_root,
    run_id=ARGS.m2c_diagnostic_run_id,
    scene_seed=SCENE.scene_seed,
    failure_seed=ARGS.m2c_failure_seed,
    condition=ARGS.m2c_diagnostic_condition,
    source_sdf_sha256=sha256_file(ARGS.sdf),
    source_supervision_sha256=sha256_file(ARGS.supervision),
    source_urdf_sha256=sha256_file(ARGS.urdf),
    upstream_v4_probe_sha256="6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87",
    derived_probe_sha256=sha256_file(__file__),
    container_image_id=ARGS.m2c_container_image_id,
).model_dump(mode="json")

"""
    source = source[:authorization_start] + authorization + source[authorization_end:]

    helper_marker = "\n\ndef main() -> int:\n"
    diagnostic_helpers = r"""

def _m2c_terminal_collision_or_safety_violations(result: dict[str, Any]) -> int:
    motions: list[dict[str, Any]] = []
    for candidate in result.get("ik_reachability_scan", {}).get("trials", []):
        motion = candidate.get("pregrasp_motion")
        if isinstance(motion, dict):
            motions.append(motion)
    for attempt in result.get("attempts", []):
        motion = attempt.get("contact_motion")
        if isinstance(motion, dict):
            motions.append(motion)
    lift = result.get("lift_motion")
    if isinstance(lift, dict):
        motions.append(lift)
    count = 0
    for motion in motions:
        gate = motion.get("collision_gate")
        if not isinstance(gate, dict):
            count += 1
            continue
        count += int(gate.get("unexpected_robot_contact_events", 0))
        if gate.get("status") != "PASS" and int(
            gate.get("unexpected_robot_contact_events", 0)
        ) == 0:
            count += 1
    return count


def _m2c_write_terminal_diagnostic(
    *,
    output: Path,
    result: dict[str, Any] | None,
    public_predicates: list[str],
    public_captures: list[dict[str, Any]],
) -> dict[str, Any]:
    terminal_status = (
        "NO_TERMINAL_ATTEMPT" if result is None else str(result.get("status"))
    )
    if terminal_status not in {
        "LIFTED",
        "PREGRASP_IK_GATE_REJECTED",
        "CONTACT_GATE_REJECTED",
        "NO_TERMINAL_ATTEMPT",
    }:
        raise RuntimeError("terminal diagnostic produced an unknown status")
    violations = (
        0
        if result is None
        else _m2c_terminal_collision_or_safety_violations(result)
    )
    selected_yaw = None
    if result is not None:
        selected_yaw = result.get("ik_reachability_scan", {}).get(
            "selected_yaw_rad"
        )
    terminal_success = bool(
        terminal_status == "LIFTED"
        and {"grasped=true", "lifted=true"}.issubset(public_predicates)
        and violations == 0
    )
    evidence = {
        "schema_version": "M2CTerminalRegraspDiagnosticRawV1",
        "authorization": M2C_V4_COLLECTION_AUTHORIZATION,
        "run_id": ARGS.m2c_diagnostic_run_id,
        "matched_key": ARGS.m2c_matched_key,
        "scene_seed": SCENE.scene_seed,
        "failure_seed": ARGS.m2c_failure_seed,
        "condition": ARGS.m2c_diagnostic_condition,
        "terminal_measurement_valid": result is not None,
        "terminal_execution_status": terminal_status,
        "pregrasp_ik_passed": terminal_status
        not in {"PREGRASP_IK_GATE_REJECTED", "NO_TERMINAL_ATTEMPT"},
        "contact_gate_passed": terminal_status == "LIFTED",
        "selected_free_gap_yaw_rad": selected_yaw,
        "terminal_target_blocker_surface_gap_m": M2C_V4_COLLECTION_AUTHORIZATION[
            "terminal_target_blocker_surface_gap_m"
        ],
        "public_predicates": sorted(public_predicates),
        "terminal_success": terminal_success,
        "physical_action_executed": result is not None,
        "collision_or_safety_violations": violations,
        "public_capture_evidence": public_captures,
        "terminal_regrasp_execution": result,
        "actuation_probe_source_sha256": ACTUATION_PROBE_SOURCE_SHA256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    path = output / "terminal-regrasp-diagnostic.json"
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "M2C_TERMINAL_REGRASP_DIAGNOSTIC "
        + json.dumps(
            {
                "run_id": ARGS.m2c_diagnostic_run_id,
                "condition": ARGS.m2c_diagnostic_condition,
                "status": terminal_status,
                "terminal_success": terminal_success,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return evidence
"""
    source = _replace_once(source, helper_marker, diagnostic_helpers + helper_marker)

    close_marker = """    close_target_m = (
        calibration_perceived_diameter_m
        - M1B_CLOSE_SQUEEZE_M
    ) / 2.0 + NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M

    if free_gap_yaw is None:
"""
    direct_branch = r"""    close_target_m = (
        calibration_perceived_diameter_m
        - M1B_CLOSE_SQUEEZE_M
    ) / 2.0 + NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M

    if ARGS.m2c_diagnostic_condition in {
        "C1_NO_BLOCKER",
        "C2_RETAINED_BLOCKER",
    }:
        if (
            m2b_public_rgbd is None
            or m2b_public_before is None
            or m2b_task_target_track_id is None
        ):
            raise RuntimeError("direct terminal diagnostic lacks public RGB-D target")
        direct_target = next(
            track
            for track in m2b_public_before
            if track.track_id == m2b_task_target_track_id
        )
        camera_to_world = np.asarray(
            m2b_public_rgbd["camera_to_world_optical"],
            dtype=np.float64,
        ).reshape(4, 4)
        regrasp_offset_world = camera_to_world[:3, :3] @ np.asarray(
            M2B_PUBLIC_REGRASP_OFFSET_CAMERA_XYZ_M,
            dtype=np.float64,
        )
        direct_result = _execute_m2b_public_regrasp(
            robot=robot,
            hand_prim=hand_prim,
            left_finger_prim=left_finger_prim,
            right_finger_prim=right_finger_prim,
            sensors=sensors,
            contact_collector=contact_collector,
            public_target_world_m=direct_target.position_world_m,
            public_tracks=m2b_public_before,
            controlled_offset_camera_m=M2B_PUBLIC_REGRASP_OFFSET_CAMERA_XYZ_M,
            controlled_offset_world_m=tuple(
                float(value) for value in regrasp_offset_world
            ),
            preclose_target_m=preclose_target_m,
            close_target_m=close_target_m,
        )
        direct_predicates: list[str] = []
        if direct_result["status"] == "LIFTED":
            direct_after = _capture_m2b_public_rgbd(
                m2b_public_rgbd,
                label="terminal_diagnostic_after_regrasp",
            )
            direct_public_result = infer_occlusion_aware_lift_success_predicates(
                m2b_public_before,
                direct_after,
                task_target_track_id=direct_target.track_id,
                hand_before_world_m=direct_result["hand_before_lift_world_m"],
                hand_after_world_m=direct_result["hand_after_lift_world_m"],
                gripper_closed=True,
            )
            direct_predicates = sorted(direct_public_result.predicates)
            _remove_attachment()
            _step_gripper(robot, 0.04, steps=60)
        _m2c_write_terminal_diagnostic(
            output=output,
            result=direct_result,
            public_predicates=direct_predicates,
            public_captures=list(m2b_public_rgbd["captures"]),
        )
        for annotator in m2b_public_rgbd["annotators"].values():
            annotator.detach()
        return 0

    if free_gap_yaw is None:
"""
    source = _replace_once(source, close_marker, direct_branch)

    final_print_marker = """    print(
        "M1B_ISAAC_ACTUATION_PROBE "
"""
    c3_projection = r"""    if ARGS.m2c_diagnostic_condition == "C3_FULL_V4":
        c3_predicates = (
            []
            if m2b_wrong_public_lift_success is None
            else sorted(m2b_wrong_public_lift_success.predicates)
        )
        _m2c_write_terminal_diagnostic(
            output=output,
            result=m2b_wrong_regrasp,
            public_predicates=c3_predicates,
            public_captures=(
                [] if m2b_public_rgbd is None else list(m2b_public_rgbd["captures"])
            ),
        )
    print(
        "M1B_ISAAC_ACTUATION_PROBE "
"""
    source = _replace_once(source, final_print_marker, c3_projection)
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = derive_terminal_regrasp_diagnostic_probe_bytes(args.upstream.read_bytes())
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite diagnostic probe: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"M2C_TERMINAL_DIAGNOSTIC_PROBE_SHA256={sha256_bytes(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
