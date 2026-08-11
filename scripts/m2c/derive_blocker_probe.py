#!/usr/bin/env python3
"""Derive a hash-bound scripted blocker-relocation probe from frozen B0 code."""

from __future__ import annotations

import hashlib
from pathlib import Path


UPSTREAM_B0_PROBE_SHA256 = (
    "1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _replace_once(source: str, marker: str, replacement: str) -> str:
    if source.count(marker) != 1:
        raise ValueError(
            f"derived probe marker count changed: {marker[:60]!r}="
            f"{source.count(marker)}"
        )
    return source.replace(marker, replacement, 1)


def derive_probe_bytes(upstream: bytes) -> bytes:
    if sha256_bytes(upstream) != UPSTREAM_B0_PROBE_SHA256:
        raise ValueError("frozen B0 probe hash mismatch before derivation")
    source = upstream.decode("utf-8")
    source = _replace_once(
        source,
        "    return parser.parse_known_args()\n",
        '''    parser.add_argument(
        "--m2c-scripted-safe-place-bin-cell",
        type=int,
        default=None,
        help=(
            "Existence-proof only: physically transport the attached non-target "
            "to one official generated bin cell before detach. Never a B0 run."
        ),
    )
    return parser.parse_known_args()
''',
    )
    source = _replace_once(
        source,
        "CONTACT_FILTERS = tuple(\n",
        '''M2C_BIN_CELL_TARGETS_WORLD_M = (
    (0.275, 0.010, 0.560),
    (0.125, 0.010, 0.560),
    (0.275, 0.150, 0.560),
    (0.125, 0.150, 0.560),
    (0.275, 0.290, 0.560),
    (0.125, 0.290, 0.560),
)
if ARGS.m2c_scripted_safe_place_bin_cell is not None and (
    ARGS.m2b_task_target_object is None
    or not ARGS.m2b_capture_public_rgbd
    or not 0 <= ARGS.m2c_scripted_safe_place_bin_cell
    < len(M2C_BIN_CELL_TARGETS_WORLD_M)
):
    raise ValueError(
        "M2C scripted safe-place requires public WRONG_OBJECT and bin cell 0..5"
    )

CONTACT_FILTERS = tuple(
''',
    )
    source = _replace_once(
        source,
        "    _remove_attachment()\n    _step_gripper(robot, 0.04, steps=60)\n",
        '''    m2c_scripted_safe_place = None
    if ARGS.m2c_scripted_safe_place_bin_cell is not None:
        desired_object_world_m = np.asarray(
            M2C_BIN_CELL_TARGETS_WORLD_M[
                ARGS.m2c_scripted_safe_place_bin_cell
            ],
            dtype=np.float32,
        )
        transport_hand_start, _ = _live_pose(hand_prim)
        transport_object_start, _ = _live_pose(object_prim)
        hand_object_offset_m = (
            np.asarray(transport_hand_start, dtype=np.float32)
            - np.asarray(transport_object_start, dtype=np.float32)
        )
        transport_hand_goal = desired_object_world_m + hand_object_offset_m
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
        transport_hand_end, _ = _live_pose(hand_prim)
        transport_object_end, _ = _live_pose(object_prim)
        transport_hand_delta = _delta(
            transport_hand_start, transport_hand_end
        )
        transport_object_delta = _delta(
            transport_object_start, transport_object_end
        )
        transport_follow_error_m = float(
            np.linalg.norm(transport_hand_delta - transport_object_delta)
        )
        destination_error_m = float(
            np.linalg.norm(
                np.asarray(transport_object_end, dtype=np.float32)
                - desired_object_world_m
            )
        )
        transport_passed = bool(
            transport_motion["final_error_m"]
            <= PRODUCTION_EE_POSITION_ERROR_GATE_M
            and transport_motion["collision_gate"]["status"] == "PASS"
            and transport_follow_error_m <= 0.02
            and destination_error_m <= 0.03
        )
        m2c_scripted_safe_place = {
            "schema_version": "M2CScriptedSafePlaceEvidenceV1",
            "existence_proof_only": True,
            "counted_as_b0": False,
            "bin_cell_index": ARGS.m2c_scripted_safe_place_bin_cell,
            "desired_object_world_m": desired_object_world_m.tolist(),
            "transport_hand_goal_world_m": transport_hand_goal.tolist(),
            "object_start_world_m": list(transport_object_start),
            "object_end_world_m": list(transport_object_end),
            "destination_error_m": destination_error_m,
            "follow_error_m": transport_follow_error_m,
            "motion": transport_motion,
            "action_protocol": {
                "frame": "world",
                "units": "m",
                "dimensions": 3,
                "frequency_hz": 60,
                "normalization": "none",
                "destination_source": "generate_industrial_scenes.bin_cell_targets",
            },
            "policy_input_simulator_truth": False,
            "passed": transport_passed,
        }
        hand_after = transport_hand_end

    _remove_attachment()
    _step_gripper(robot, 0.04, steps=60)
''',
    )
    source = _replace_once(
        source,
        '                    and m2b_injection_pass\n',
        '''                    and m2b_injection_pass
                    and (
                        m2c_scripted_safe_place is None
                        or m2c_scripted_safe_place["passed"]
                    )
''',
    )
    source = _replace_once(
        source,
        '            "m2b_release_failure_injection": release_failure_injection,\n',
        '''            "m2c_scripted_safe_place": m2c_scripted_safe_place,
            "m2b_release_failure_injection": release_failure_injection,
''',
    )
    source = _replace_once(
        source,
        '''                        "safe_place_non_target_passed": (
                            detached_noncoupling_pass
                        ),
''',
        '''                        "safe_place_non_target_passed": bool(
                            detached_noncoupling_pass
                            and (
                                m2c_scripted_safe_place is None
                                or m2c_scripted_safe_place["passed"]
                            )
                        ),
''',
    )
    return source.encode("utf-8")


def derive_probe_file(upstream: Path, output: Path) -> str:
    derived = derive_probe_bytes(upstream.read_bytes())
    output.write_bytes(derived)
    output.chmod(0o555)
    return sha256_bytes(derived)
