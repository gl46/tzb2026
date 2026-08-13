#!/usr/bin/env python3
"""Create one unsigned host-local formal HMAC verification receipt."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import read_hmac_secret
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    build_hmac_verification_receipt_v2,
    read_regular_file_once,
    sha256_bytes,
)


IMPLEMENTATION_PATH = "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C host-local formal wire authentication")
    parser.add_argument("--host-role", choices=("NODE2_QWEN", "LABSERVER_ISAAC"), required=True)
    parser.add_argument("--formal-evidence", type=Path, required=True)
    parser.add_argument("--service-audit", type=Path, required=True)
    parser.add_argument("--session-audit", type=Path)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _read(path: Path) -> bytes:
    return read_regular_file_once(path)


def _publish(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    with tempfile.NamedTemporaryFile(
        mode="x",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.incomplete-",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
        temporary.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    formal = _read(args.formal_evidence)
    service = _read(args.service_audit)
    session = _read(args.session_audit) if args.session_audit is not None else None
    if (args.host_role == "LABSERVER_ISAAC") != (session is not None):
        raise ValueError("only the labserver role requires exactly one session audit")
    secret = read_hmac_secret(args.hmac_key_file)
    implementation = args.project_root / IMPLEMENTATION_PATH
    implementation_bytes = _read(implementation)
    receipt = build_hmac_verification_receipt_v2(
        host_role=args.host_role,
        formal_evidence_bytes=formal,
        service_audit_bytes=service,
        session_audit_bytes=session,
        verifier_implementation_bytes=implementation_bytes,
        secret=secret,
    )
    run_id = receipt.core.run_id
    challenge = receipt.core.challenge_nonce
    payload = receipt.model_dump(mode="json")
    published_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _publish(args.output, payload)
    print(
        json.dumps(
            {
                "status": "PASS_HOST_LOCAL_HMAC_VERIFICATION_NOT_FORMAL_AUTHORIZATION",
                "host_role": args.host_role,
                "run_id": run_id,
                "challenge_nonce": challenge,
                "receipt_sha256": sha256_bytes(published_bytes),
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
