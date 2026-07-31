#!/usr/bin/env python3
"""Wrap isolated Isaac action runs as prospective preflight manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from m2b.build_prospective_runtime_decisions import (
    IsolatedIsaacPreflightManifestV1,
)
from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    extract_physical_runtime_gate_receipt,
)


class M2BIsolatedPreflightPlanV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["M2BIsolatedPreflightPlanV1"] = (
        "M2BIsolatedPreflightPlanV1"
    )
    sample_id: str
    failure_type: Literal[
        "EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"
    ]
    runtime_action: str
    preflight_evidence_path: str
    model_selection_triggered_preflight: Literal[True] = True
    evaluation_execution_started: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False


def remote_bytes(host: str, path: str) -> bytes:
    completed = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "cat", path],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.decode(errors="replace").strip()
            or f"cannot read {host}:{path}"
        )
    return completed.stdout


def manifest_from_payload(
    plan: M2BIsolatedPreflightPlanV1,
    payload: dict[str, Any],
    *,
    evidence_sha256: str,
) -> IsolatedIsaacPreflightManifestV1:
    receipt = extract_physical_runtime_gate_receipt(
        payload,
        failure_type=plan.failure_type,
    )
    if receipt.runtime_action != plan.runtime_action:
        raise ValueError(
            f"{plan.sample_id}: selected runtime action was not preflighted"
        )
    source_hashes = payload.get("source_hashes") or {}
    if not source_hashes:
        raise ValueError(f"{plan.sample_id}: preflight source hashes missing")
    return IsolatedIsaacPreflightManifestV1(
        sample_id=plan.sample_id,
        failure_type=plan.failure_type,
        source_hashes=source_hashes,
        preflight_evidence_path=plan.preflight_evidence_path,
        preflight_evidence_sha256=evidence_sha256,
        receipt=receipt,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plans = [
        M2BIsolatedPreflightPlanV1.model_validate_json(line)
        for line in args.plan.read_text().splitlines()
        if line.strip()
    ]
    manifests = []
    for plan in plans:
        evidence = remote_bytes(args.host, plan.preflight_evidence_path)
        manifests.append(
            manifest_from_payload(
                plan,
                json.loads(evidence),
                evidence_sha256=hashlib.sha256(evidence).hexdigest(),
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(item.model_dump_json() + "\n" for item in manifests)
    )
    print(
        json.dumps(
            {
                "preflights": len(manifests),
                "output": str(args.output),
                "output_sha256": hashlib.sha256(
                    args.output.read_bytes()
                ).hexdigest(),
                "teacher_used": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
