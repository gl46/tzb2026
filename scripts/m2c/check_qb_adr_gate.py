#!/usr/bin/env python3
"""Evaluate and report the fail-closed human ADR gate before M2C Q-B."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xh_agent.policy.qrm_lite.qb_adr_gate import evaluate_qb_adr_gate


PROJECT = Path(__file__).resolve().parents[2]


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_markdown(path: Path, payload: dict[str, object]) -> None:
    blockers = [str(item) for item in payload.get("blockers", [])]
    frozen = payload.get("frozen_bindings", {})
    assert isinstance(frozen, dict)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# M2C Q-B human ADR gate",
                "",
                f"- Status: **{payload['status']}**",
                f"- Q-B authorized: `{payload['q_b_authorized']}`",
                f"- Checked Git HEAD: `{payload['checked_head_commit']}`",
                f"- Governance commit: `{payload['governance_commit']}`",
                f"- Decision option: `{payload['decision_option']}`",
                f"- Intent schema: `{payload['intent_schema_version']}`",
                (
                    "- Frozen Q-B pre-registration match: "
                    f"`{frozen.get('preregistration_match')}`"
                ),
                f"- Frozen B0 manifest match: `{frozen.get('b0_freeze_match')}`",
                f"- Frozen B0 files verified: `{frozen.get('b0_files_verified')}`",
                "- Q-B training executed: `false`",
                "- Q-B evaluation executed: `false`",
                "- Teacher used: `false`",
                "- Privileged simulator truth used as policy input: `false`",
                "",
                "## Blockers",
                "",
                *([f"- {item}" for item in blockers] or ["- None."]),
                "",
                "## Task report",
                "",
                "- Changed files: this generated JSON/Markdown report only.",
                "- Tests: use `pytest -q tests/unit/test_m2c_qb_adr_gate.py`.",
                "- Failures: none beyond the blockers listed above.",
                (
                    "- Blocker: none."
                    if payload["q_b_authorized"]
                    else "- Blocker: the exact human-approved expressivity ADR is not valid at Git HEAD."
                ),
                f"- Next command: `{payload['next_command']}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "reports/m2c-qb-adr-gate.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=PROJECT / "reports/m2c-qb-adr-gate.md",
    )
    args = parser.parse_args()
    result = evaluate_qb_adr_gate(args.project_root)
    write_json(args.output, result)
    write_markdown(args.output_md, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["q_b_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
