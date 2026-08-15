#!/usr/bin/env python3
"""Derive the V2 diagnostic probe without changing frozen terminal helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from m2c.derive_terminal_regrasp_diagnostic_probe import (
    derive_terminal_regrasp_diagnostic_probe_bytes,
    sha256_bytes,
)


def derive_terminal_regrasp_diagnostic_probe_bytes_v2(upstream: bytes) -> bytes:
    source = derive_terminal_regrasp_diagnostic_probe_bytes(upstream).decode("utf-8")
    old_import = """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    bind_diagnostic_claim_to_raw_session,
)
"""
    new_import = """from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    bind_diagnostic_claim_to_raw_session_v2 as bind_diagnostic_claim_to_raw_session,
)
"""
    if source.count(old_import) != 1:
        raise ValueError("V2 diagnostic authorization import marker changed")
    source = source.replace(old_import, new_import, 1)
    if source.count('"schema_version": "M2CTerminalRegraspDiagnosticRawV1"') != 1:
        raise ValueError("V2 diagnostic raw schema marker changed")
    source = source.replace(
        '"schema_version": "M2CTerminalRegraspDiagnosticRawV1"',
        '"schema_version": "M2CTerminalRegraspDiagnosticRawV2"',
        1,
    )
    return source.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = derive_terminal_regrasp_diagnostic_probe_bytes_v2(args.upstream.read_bytes())
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite V2 diagnostic probe: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(f"M2C_TERMINAL_DIAGNOSTIC_V2_PROBE_SHA256={sha256_bytes(payload)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
