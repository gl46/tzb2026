#!/usr/bin/env python3
"""Derive V4 with the direct terminal branch before inherited V4-chain gates."""

from __future__ import annotations

import argparse
from pathlib import Path

from m2c.derive_terminal_regrasp_diagnostic_probe import sha256_bytes
from m2c.derive_terminal_regrasp_diagnostic_probe_v3 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v3,
)


def _replace_once(source: str, marker: str, replacement: str) -> str:
    if source.count(marker) != 1:
        raise ValueError(f"V4 diagnostic marker count is not one: {marker[:96]!r}")
    return source.replace(marker, replacement, 1)


EARLY_DIRECT_BRANCH = r"""    if ARGS.m2c_diagnostic_condition in {
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
        direct_target_collision = TARGET_MODEL.links[0].collisions[0]
        if direct_target_collision.radius is None:
            raise RuntimeError("M1B target collision has no cylinder radius")
        direct_perceived_diameter_m = 2.0 * direct_target_collision.radius
        direct_preclose_target_m = (
            direct_perceived_diameter_m
            + M1B_PRECLOSE_PUBLIC_DIAMETER_MARGIN_M
        ) / 2.0 + NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M
        direct_close_target_m = (
            direct_perceived_diameter_m - M1B_CLOSE_SQUEEZE_M
        ) / 2.0 + NVIDIA_DEFAULT_INNER_FACE_TO_JOINT_AXIS_M
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
            preclose_target_m=direct_preclose_target_m,
            close_target_m=direct_close_target_m,
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

"""


def derive_terminal_regrasp_diagnostic_probe_bytes_v4(upstream: bytes) -> bytes:
    source = derive_terminal_regrasp_diagnostic_probe_bytes_v3(upstream).decode("utf-8")
    source = _replace_once(
        source,
        """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    bind_diagnostic_claim_to_raw_session_v3 as bind_diagnostic_claim_to_raw_session,
)
""",
        """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v4 import (
    bind_diagnostic_claim_to_raw_session_v4 as bind_diagnostic_claim_to_raw_session,
)
""",
    )
    old_start = source.index(
        """    if ARGS.m2c_diagnostic_condition in {
        "C1_NO_BLOCKER",
        "C2_RETAINED_BLOCKER",
    }:
"""
    )
    old_end = source.index("    if free_gap_yaw is None:\n", old_start)
    source = source[:old_start] + source[old_end:]
    inherited_guard = """    if m2b_public_rgbd is None or m2b_injected_grasp_track_id is None or m2b_task_target_track_id is None:
        raise RuntimeError("M2C chain requires public blocker and task-target tracks")
"""
    source = _replace_once(
        source,
        inherited_guard,
        EARLY_DIRECT_BRANCH + inherited_guard,
    )
    source = _replace_once(
        source,
        '        "schema_version": "M2CTerminalRegraspDiagnosticRawV3",\n',
        '        "schema_version": "M2CTerminalRegraspDiagnosticRawV4",\n',
    )
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = derive_terminal_regrasp_diagnostic_probe_bytes_v4(args.upstream.read_bytes())
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite V4 diagnostic probe: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"M2C_TERMINAL_DIAGNOSTIC_V4_PROBE_SHA256={sha256_bytes(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
