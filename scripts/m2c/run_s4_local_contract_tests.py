#!/usr/bin/env python3
"""Run only the frozen local ADR test suite and write a non-physical receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from xh_agent.policy.qrm_lite.s4_entry_gate import (
    LOCAL_TEST_NODE_IDS,
    RUNTIME_BINDINGS,
)


PROJECT = Path(__file__).resolve().parents[2]


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    command = ["python", "-m", "pytest", "-q", *LOCAL_TEST_NODE_IDS]
    executable_command = [str(Path(__file__).resolve().parents[2] / ".venv/bin/python")]
    if not Path(executable_command[0]).is_file():
        executable_command = ["python3"]
    completed = subprocess.run(
        [*executable_command, "-m", "pytest", "-q", *LOCAL_TEST_NODE_IDS],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    summary = completed.stdout + completed.stderr
    passed = 0
    failed = 0
    skipped = 0
    import re

    for count, label in re.findall(r"(\d+) (passed|failed|skipped)", summary):
        if label == "passed":
            passed = int(count)
        elif label == "failed":
            failed = int(count)
        else:
            skipped = int(count)
    receipt = {
        "schema_version": "M2CS4LocalContractTestReceiptV2",
        "evidence_origin": "LOCAL_CONTRACT_TESTS",
        "command": command,
        "node_ids": list(LOCAL_TEST_NODE_IDS),
        "exit_code": completed.returncode,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_skipped": skipped,
        "checked_implementation_commit": _git_head(root),
        "runtime_binding_sha256": RUNTIME_BINDINGS,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary, end="")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
