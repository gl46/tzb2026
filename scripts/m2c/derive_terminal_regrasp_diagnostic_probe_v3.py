#!/usr/bin/env python3
"""Derive the V3 terminal diagnostic public-measurement setup."""

from __future__ import annotations

import argparse
from pathlib import Path

from m2c.derive_terminal_regrasp_diagnostic_probe_v2 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v2,
)
from m2c.derive_terminal_regrasp_diagnostic_probe import sha256_bytes


def _replace_once(source: str, marker: str, replacement: str) -> str:
    if source.count(marker) != 1:
        raise ValueError(f"V3 diagnostic marker count is not one: {marker[:96]!r}")
    return source.replace(marker, replacement, 1)


def derive_terminal_regrasp_diagnostic_probe_bytes_v3(upstream: bytes) -> bytes:
    source = derive_terminal_regrasp_diagnostic_probe_bytes_v2(upstream).decode("utf-8")
    source = _replace_once(
        source,
        """    parser.add_argument("--m2c-diagnostic-run-id", required=True)
""",
        """    parser.add_argument("--m2c-diagnostic-run-id", required=True)
    parser.add_argument(
        "--m2c-direct-terminal-public-rgbd",
        action="store_true",
        help=(
            "ADR-0026 diagnostic-only public measurement setup for C1/C2; "
            "it does not declare or synthesize a failure injection"
        ),
    )
""",
    )
    source = _replace_once(
        source,
        """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    bind_diagnostic_claim_to_raw_session_v2 as bind_diagnostic_claim_to_raw_session,
)
""",
        """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v3 import (
    bind_diagnostic_claim_to_raw_session_v3 as bind_diagnostic_claim_to_raw_session,
)
""",
    )
    source = _replace_once(
        source,
        """    container_image_id=ARGS.m2c_container_image_id,
).model_dump(mode="json")
""",
        """    container_image_id=ARGS.m2c_container_image_id,
    direct_public_rgbd_enabled=ARGS.m2c_direct_terminal_public_rgbd,
).model_dump(mode="json")
""",
    )
    source = _replace_once(
        source,
        """ARGS, _UNKNOWN = parse_args()
SCENE = load_m1b_isaac_generated_scene(ARGS.sdf, ARGS.supervision)
""",
        """ARGS, _UNKNOWN = parse_args()
_M2C_DIRECT_TERMINAL_EXPECTED = ARGS.m2c_diagnostic_condition in {
    "C1_NO_BLOCKER",
    "C2_RETAINED_BLOCKER",
}
if ARGS.m2c_direct_terminal_public_rgbd is not _M2C_DIRECT_TERMINAL_EXPECTED:
    raise ValueError(
        "ADR-0026 direct public RGB-D flag differs from the frozen condition"
    )
SCENE = load_m1b_isaac_generated_scene(ARGS.sdf, ARGS.supervision)
""",
    )
    source = _replace_once(
        source,
        """    if not (
        ARGS.m2b_inject_empty_grasp
        or ARGS.m2b_inject_release_failure
        or ARGS.m2b_task_target_object is not None
    ):
        raise ValueError("M2B public RGB-D capture requires a failure injection")
""",
        """    diagnostic_direct_measurement = bool(
        ARGS.m2c_chain_role == "DIAGNOSTIC"
        and ARGS.m2c_diagnostic_condition in {
            "C1_NO_BLOCKER",
            "C2_RETAINED_BLOCKER",
        }
        and ARGS.m2c_direct_terminal_public_rgbd
    )
    if not (
        ARGS.m2b_inject_empty_grasp
        or ARGS.m2b_inject_release_failure
        or ARGS.m2b_task_target_object is not None
        or diagnostic_direct_measurement
    ):
        raise ValueError("M2B public RGB-D capture requires a failure injection")
""",
    )
    source = _replace_once(
        source,
        '        "schema_version": "M2CTerminalRegraspDiagnosticRawV2",\n',
        '        "schema_version": "M2CTerminalRegraspDiagnosticRawV3",\n',
    )
    source = _replace_once(
        source,
        """        "condition": ARGS.m2c_diagnostic_condition,
        "terminal_measurement_valid": result is not None,
""",
        """        "condition": ARGS.m2c_diagnostic_condition,
        "public_rgbd_setup_contract": M2C_V4_COLLECTION_AUTHORIZATION[
            "public_rgbd_setup_contract"
        ],
        "terminal_measurement_valid": result is not None,
""",
    )
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = derive_terminal_regrasp_diagnostic_probe_bytes_v3(args.upstream.read_bytes())
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite V3 diagnostic probe: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"M2C_TERMINAL_DIAGNOSTIC_V3_PROBE_SHA256={sha256_bytes(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
