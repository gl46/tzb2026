#!/usr/bin/env python3
"""Build or replay the create-only Phase-2 source-binding closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.phase2_source_binding_closure_v1 import (
    build_phase2_source_binding_closure_v1,
    load_source_closure_request_v1,
    replay_phase2_source_binding_closure_v1,
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
    request = load_source_closure_request_v1(
        args.request,
        expected_file_sha256=args.expected_request_sha256,
    )
    operation = (
        replay_phase2_source_binding_closure_v1
        if args.verify_only
        else build_phase2_source_binding_closure_v1
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
