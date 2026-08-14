#!/usr/bin/env python3
"""Create one unsigned host-local formal V4 HMAC verification receipt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import read_hmac_secret
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    read_regular_file_once,
    sha256_bytes,
)
from xh_agent.policy.qrm_lite.offline_wire_auth_v4 import (
    HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH,
    build_hmac_verification_receipt_v4,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C host-local formal V4 wire HMAC verification")
    parser.add_argument(
        "--host-role",
        choices=("NODE2_QWEN", "LABSERVER_ISAAC"),
        required=True,
    )
    parser.add_argument("--formal-evidence", type=Path, required=True)
    parser.add_argument("--challenge-consumption-receipt", type=Path, required=True)
    parser.add_argument("--service-audit", type=Path, required=True)
    parser.add_argument("--session-audit", type=Path)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("formal V4 HMAC receipt write made no progress")
        view = view[written:]


def _publish_create_only(path: Path, payload: bytes) -> None:
    if path.parent.is_symlink():
        raise ValueError("formal V4 HMAC receipt directory may not be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.parent.stat(follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise PermissionError("formal V4 HMAC receipt directory permissions are unsafe")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
    finally:
        os.close(descriptor)
    directory = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    formal = read_regular_file_once(args.formal_evidence)
    consumption = read_regular_file_once(args.challenge_consumption_receipt)
    service = read_regular_file_once(args.service_audit)
    session = read_regular_file_once(args.session_audit) if args.session_audit is not None else None
    if (args.host_role == "LABSERVER_ISAAC") != (session is not None):
        raise ValueError("only the V4 labserver role requires exactly one session audit")
    secret = read_hmac_secret(args.hmac_key_file)
    implementation = args.project_root / HOST_HMAC_VERIFIER_V4_IMPLEMENTATION_PATH
    implementation_bytes = read_regular_file_once(implementation)
    receipt = build_hmac_verification_receipt_v4(
        host_role=args.host_role,
        formal_evidence_bytes=formal,
        challenge_consumption_bytes=consumption,
        service_audit_bytes=service,
        session_audit_bytes=session,
        secret=secret,
        verifier_implementation_bytes=implementation_bytes,
    )
    published = (
        json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _publish_create_only(args.output, published)
    print(
        json.dumps(
            {
                "status": "PASS_HOST_LOCAL_V4_HMAC_VERIFICATION_NOT_FORMAL_AUTHORIZATION",
                "host_role": args.host_role,
                "run_id": receipt.core.run_id,
                "challenge_nonce": receipt.core.challenge_nonce,
                "completion_kind": receipt.core.completion_kind,
                "decision_count": receipt.core.decision_count,
                "receipt_sha256": sha256_bytes(published),
                "hmac_secret_exported": False,
                "teacher_used": False,
                "privileged_truth_policy_input": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
