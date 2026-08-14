#!/usr/bin/env python3
"""Check ADR-0022 Phase-2 evidence; generate proposals only when READY."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from xh_agent.policy.qrm_lite.phase2_binding_readiness_v2 import (
    ADDENDUM_PATH,
    ReadinessFailure,
    UNLOCK_CONFIG_PATH,
    build_readiness_report,
    render_binding_addendum,
    render_binding_proposal,
    sha256_bytes,
)


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o444,
    )
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("create-only Phase-2 output write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--evidence-index", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--addendum-output", type=Path)
    parser.add_argument("--binding-proposal-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.generate != (
        args.addendum_output is not None and args.binding_proposal_output is not None
    ):
        raise ReadinessFailure(
            "--generate requires both --addendum-output and --binding-proposal-output"
        )
    report, verified = build_readiness_report(args.project_root, args.evidence_index)
    report_bytes = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    if args.report_output is not None:
        _write_create_only(args.report_output, report_bytes)
    else:
        print(report_bytes.decode(), end="")
    if not args.generate:
        return 0 if report["ready"] else 2
    if not report["ready"] or verified is None:
        raise ReadinessFailure("Phase-2 is BLOCKED; no addendum/config may be generated")
    if args.addendum_output.as_posix() != ADDENDUM_PATH:
        raise ReadinessFailure(f"binding addendum output must be exactly {ADDENDUM_PATH}")
    if args.binding_proposal_output.as_posix() != UNLOCK_CONFIG_PATH:
        raise ReadinessFailure(f"binding proposal output must be exactly {UNLOCK_CONFIG_PATH}")
    addendum = render_binding_addendum(verified)
    proposal = render_binding_proposal(verified, addendum_sha256=sha256_bytes(addendum))
    _write_create_only(args.addendum_output, addendum)
    try:
        _write_create_only(args.binding_proposal_output, proposal)
    except Exception:
        # A partially published addendum is safer than overwriting anything;
        # its text explicitly says no binding is applied and the absent paired
        # proposal keeps Phase-2 blocked.
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
