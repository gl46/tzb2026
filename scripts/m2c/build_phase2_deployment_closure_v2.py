#!/usr/bin/env python3
"""Build or replay a create-only ADR-0024 Phase-2 deployment closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.phase2_deployment_closure_v2 import (
    build_phase2_deployment_closure_v2,
    load_build_request_v2,
    replay_phase2_deployment_closure_v2,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-request-sha256")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    request = load_build_request_v2(
        args.request,
        expected_file_sha256=args.expected_request_sha256,
    )
    operation = (
        replay_phase2_deployment_closure_v2
        if args.verify_only
        else (build_phase2_deployment_closure_v2)
    )
    receipt = operation(
        project_root=args.project_root,
        request=request,
        output_root=args.output_root,
    )
    print(json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
