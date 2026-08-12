#!/usr/bin/env python3
"""Create one host-local, independently signed formal wire attestation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import read_hmac_secret
from xh_agent.policy.qrm_lite.offline_wire_auth_v1 import (
    build_signed_receipt,
    read_regular_file_once,
    sha256_bytes,
    verify_labserver_isaac_transcript,
    verify_node2_qwen_transcript,
    verify_receipt_signature,
)


IMPLEMENTATION_PATH = "src/xh_agent/policy/qrm_lite/offline_wire_auth_v1.py"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2C host-local formal wire authentication")
    parser.add_argument("--host-role", choices=("NODE2_QWEN", "LABSERVER_ISAAC"), required=True)
    parser.add_argument("--formal-evidence", type=Path, required=True)
    parser.add_argument("--service-audit", type=Path, required=True)
    parser.add_argument("--session-audit", type=Path)
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
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
    if args.host_role == "NODE2_QWEN":
        run_id, challenge, transcript = verify_node2_qwen_transcript(formal, service, secret=secret)
    else:
        assert session is not None
        run_id, challenge, transcript = verify_labserver_isaac_transcript(
            formal, service, session, secret=secret
        )
    implementation = args.project_root / IMPLEMENTATION_PATH
    implementation_bytes = _read(implementation)
    allowed_signers = _read(args.allowed_signers)
    receipt = build_signed_receipt(
        host_role=args.host_role,
        run_id=run_id,
        challenge_nonce=challenge,
        formal_evidence_bytes=formal,
        service_audit_bytes=service,
        session_audit_bytes=session,
        envelope_set_sha256=transcript,
        verifier_implementation_path=IMPLEMENTATION_PATH,
        verifier_implementation_bytes=implementation_bytes,
        allowed_signers_bytes=allowed_signers,
        private_key_path=args.signing_key,
    )
    verify_receipt_signature(receipt, allowed_signers_bytes=allowed_signers)
    payload = receipt.model_dump(mode="json")
    published_bytes = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _publish(args.output, payload)
    print(
        json.dumps(
            {
                "status": "PASS_HOST_LOCAL_WIRE_ATTESTATION_NOT_FORMAL_AUTHORIZATION",
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
