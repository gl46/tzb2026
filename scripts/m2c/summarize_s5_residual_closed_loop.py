#!/usr/bin/env python3
"""Summarize a real, paired M2C S5 residual closed-loop experiment.

The summary is deliberately downstream of raw terminal evidence.  It never
executes a policy and it cannot turn offline MLP metrics into S5 evidence.
Each key must contain one zero-residual FC episode and one FC+MLP episode,
both backed by unique physical receipt files.  ``status.py`` independently
replays the same evidence before accepting a terminal disposition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from m2c.summarize_s6_matched import paired_bootstrap_difference
from xh_agent.policy.qrm_lite.s5_evidence import (
    S5AcceptedGovernanceReceiptV1,
    S5PhysicalExecutionReceiptV1,
    S5ResidualEpisodeEvidenceV1,
    validate_s5_accepted_adr_text,
)


EXPECTED_METHODS = ("QRM_COARSE_FC", "QRM_COARSE_FC_MLP")
DEFAULT_RESAMPLES = 20_000
DEFAULT_SEED = 20_260_813
TEACHER_KILL_RULES = (
    "kill the run if Teacher soft labels enter Student training or evaluation",
    "kill the run if a Teacher response or adapter enters the control stack",
    "kill the run if a Teacher is silently replaced or upgraded",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoundFileV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResidualDispositionV1(StrictModel):
    status: Literal["TRAINED_WITH_PHYSICAL_EVIDENCE", "FROZEN_EXACT_ZERO"]
    reason: str = Field(min_length=1)
    limitation: str = Field(min_length=1)
    evidence: BoundFileV1 | None = None

    @model_validator(mode="after")
    def evidence_matches_status(self) -> "ResidualDispositionV1":
        if self.status == "TRAINED_WITH_PHYSICAL_EVIDENCE" and self.evidence is None:
            raise ValueError("trained residual dimension requires physical evidence")
        if self.status == "FROZEN_EXACT_ZERO" and self.evidence is not None:
            raise ValueError("frozen residual dimension may not cite active evidence")
        return self


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, raw: str) -> Path:
    candidate = Path(raw)
    candidate = candidate if candidate.is_absolute() else root / candidate
    if candidate.is_symlink():
        raise ValueError(f"S5 evidence path may not be a symlink: {raw}")
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise ValueError(f"S5 evidence file is absent: {raw}")
    return resolved


def _verify_bound_file(root: Path, binding: BoundFileV1, *, label: str) -> Path:
    path = _resolve(root, binding.path)
    if sha256_file(path) != binding.sha256:
        raise ValueError(f"{label} SHA-256 mismatch")
    return path


def _load_rows(path: Path) -> list[S5ResidualEpisodeEvidenceV1]:
    rows: list[S5ResidualEpisodeEvidenceV1] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(S5ResidualEpisodeEvidenceV1.model_validate_json(line))
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: invalid S5 episode evidence") from error
    if not rows:
        raise ValueError("S5 episode evidence is empty")
    return rows


def _verify_receipts(
    rows: list[S5ResidualEpisodeEvidenceV1],
    *,
    evidence_root: Path,
) -> dict[str, S5PhysicalExecutionReceiptV1]:
    receipts: dict[str, S5PhysicalExecutionReceiptV1] = {}
    for row in rows:
        digest = row.physical_execution_receipt_sha256
        if digest in receipts:
            raise ValueError("S5 physical execution receipt is reused")
        receipt = _resolve(evidence_root, f"physical-receipts/{digest}.json")
        if sha256_file(receipt) != digest:
            raise ValueError("S5 physical receipt filename/content SHA-256 differs")
        parsed = S5PhysicalExecutionReceiptV1.model_validate_json(
            receipt.read_text(encoding="utf-8")
        )
        parsed.validate_episode_binding(row)
        receipts[digest] = parsed
    return receipts


def _verify_governance(
    governance_path: Path,
    *,
    project_root: Path,
) -> S5AcceptedGovernanceReceiptV1:
    root = project_root.resolve()
    receipt_path = governance_path.resolve()
    if governance_path.is_symlink() or (receipt_path != root and root not in receipt_path.parents):
        raise ValueError("S5 governance receipt must be a project file, not a symlink")
    governance = S5AcceptedGovernanceReceiptV1.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    adr = _verify_bound_file(project_root, governance.adr, label="S5 accepted human ADR")
    adr_text = adr.read_text(encoding="utf-8")
    validate_s5_accepted_adr_text(adr_text, selected_option=governance.selected_option)
    for path, label in ((receipt_path, "governance receipt"), (adr, "accepted ADR")):
        relative = str(path.relative_to(root))
        tracked = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0 or tracked.stdout != path.read_bytes():
            raise ValueError(f"S5 {label} is not committed at current HEAD")
    adr_relative = str(adr.relative_to(root))
    introduced = subprocess.run(
        ["git", "log", "--diff-filter=A", "-1", "--format=%H", "--", adr_relative],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if introduced.returncode != 0 or introduced.stdout.strip() != governance.approval_commit:
        raise ValueError("S5 accepted ADR introduction commit differs from governance receipt")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", governance.approval_commit, "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise ValueError("S5 accepted ADR commit is not an ancestor of current HEAD")
    return governance


def _verify_terminal_manifest(
    manifest_path: Path,
    *,
    project_root: Path,
    episodes_path: Path,
    receipts: dict[str, S5PhysicalExecutionReceiptV1],
) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("S5 raw evidence manifest is not an object")
    if payload.get("schema_version") != "M2CTerminalRawEvidenceManifestV1":
        raise ValueError("S5 raw evidence manifest schema is not frozen V1")
    if payload.get("teacher_used") is not False:
        raise ValueError("S5 raw evidence manifest reports Teacher use")
    if payload.get("privileged_truth_policy_input") is not False:
        raise ValueError("S5 raw evidence manifest reports privileged policy input")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("S5 raw evidence manifest has no files")
    inventory: dict[str, Path] = {}
    for item in raw_files:
        binding = BoundFileV1.model_validate(item)
        path = _verify_bound_file(project_root, binding, label="S5 raw evidence file")
        if binding.sha256 in inventory or path in inventory.values():
            raise ValueError("S5 raw evidence manifest reuses a file or digest")
        inventory[binding.sha256] = path
    if inventory.get(sha256_file(episodes_path)) != episodes_path.resolve():
        raise ValueError("S5 episode JSONL is absent from the raw evidence manifest")
    required = set(receipts)
    for row in _load_rows(episodes_path):
        for decision in row.episode.decisions:
            required.update(
                digest
                for digest in (
                    decision.registry_sha256,
                    decision.model_checkpoint_sha256,
                    decision.model_input_sha256,
                    decision.model_output_sha256,
                    decision.mapping_result_sha256,
                    *decision.gate_evidence_sha256.values(),
                )
                if digest is not None
            )
    for receipt in receipts.values():
        required.update(receipt.required_raw_digests())
    missing = sorted(required - set(inventory))
    if missing:
        raise ValueError(f"S5 raw evidence manifest lacks {len(missing)} required files")


def summarize_s5(
    rows: list[S5ResidualEpisodeEvidenceV1],
    *,
    r6d_disposition: ResidualDispositionV1,
    gripper_disposition: ResidualDispositionV1,
    evidence_root: Path,
    governance: S5AcceptedGovernanceReceiptV1 | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    if governance is None:
        raise ValueError("S5 requires a separately accepted human ADR governance receipt")
    if (
        r6d_disposition.status != "FROZEN_EXACT_ZERO"
        or gripper_disposition.status != "FROZEN_EXACT_ZERO"
    ):
        raise ValueError(
            "implemented S5 option A requires r6d and gripper to remain FROZEN_EXACT_ZERO"
        )
    receipts = _verify_receipts(rows, evidence_root=evidence_root)
    by_key: dict[str, dict[str, S5ResidualEpisodeEvidenceV1]] = {}
    violations = 0
    for row in rows:
        episode = row.episode
        methods = by_key.setdefault(episode.matched_key, {})
        if episode.method in methods:
            raise ValueError("S5 repeats a matched key/method")
        methods[episode.method] = row
        violations += int(episode.collision_or_safety_violation)
        if any(decision.collision_or_safety_violation for decision in episode.decisions):
            violations += 1
    if not by_key or any(set(methods) != set(EXPECTED_METHODS) for methods in by_key.values()):
        raise ValueError("S5 requires paired zero-residual and MLP episodes for every key")
    for key, methods in by_key.items():
        zero = methods["QRM_COARSE_FC"].episode
        mlp = methods["QRM_COARSE_FC_MLP"].episode
        if zero.scene_seed != mlp.scene_seed or zero.failure_type != mlp.failure_type:
            raise ValueError(f"S5 paired identity differs for {key}")
    if violations:
        raise ValueError("S5 contains a collision or safety violation")
    pairs = [
        (
            methods["QRM_COARSE_FC_MLP"].episode.final_success,
            methods["QRM_COARSE_FC"].episode.final_success,
        )
        for _, methods in sorted(by_key.items())
    ]
    metric = paired_bootstrap_difference(pairs, resamples=resamples, seed=seed)
    metric["name"] = "fc_mlp_gain_over_fc"
    measurable = metric["estimate"] != 0.0
    return {
        "schema_version": "M2CS5ResidualClosedLoopReportV1",
        "status": (
            "PASS_MEASURABLE_RESIDUAL_DIFFERENCE" if measurable else "D3_GO_QRM_COARSE_ONLY"
        ),
        "residual_closed_loop_executed": True,
        "measurable_difference_observed": measurable,
        "d3_triggered": not measurable,
        "paired_keys": len(by_key),
        "episodes": len(rows),
        "physical_execution_receipts": len(receipts),
        "selected_adr_option": governance.selected_option,
        "collision_or_safety_violations": 0,
        "comparison_metric": metric,
        "r6d_disposition": r6d_disposition.model_dump(mode="json"),
        "gripper_disposition": gripper_disposition.model_dump(mode="json"),
        "teacher_used": False,
        "teacher_kill_rules": list(TEACHER_KILL_RULES),
        "teacher_kill_rule_events": [],
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--episodes", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--r6d-disposition", required=True, type=Path)
    parser.add_argument("--gripper-disposition", required=True, type=Path)
    parser.add_argument("--governance-receipt", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(f"refusing to overwrite S5 report: {args.report}")
    rows = _load_rows(args.episodes)
    r6d = ResidualDispositionV1.model_validate_json(
        args.r6d_disposition.read_text(encoding="utf-8")
    )
    gripper = ResidualDispositionV1.model_validate_json(
        args.gripper_disposition.read_text(encoding="utf-8")
    )
    governance = _verify_governance(
        args.governance_receipt,
        project_root=args.project_root.resolve(),
    )
    report = summarize_s5(
        rows,
        r6d_disposition=r6d,
        gripper_disposition=gripper,
        evidence_root=args.evidence_root,
        governance=governance,
    )
    _verify_terminal_manifest(
        args.evidence_root / "manifest.json",
        project_root=args.project_root.resolve(),
        episodes_path=args.episodes,
        receipts=_verify_receipts(rows, evidence_root=args.evidence_root),
    )
    report["terminal_evidence"] = {
        "schema_version": "M2CS5TerminalEvidenceBindingV1",
        "episodes": {"path": str(args.episodes), "sha256": sha256_file(args.episodes)},
        "evidence_manifest": {
            "path": str(args.evidence_root / "manifest.json"),
            "sha256": sha256_file(args.evidence_root / "manifest.json"),
        },
        "governance": {
            "path": str(args.governance_receipt),
            "sha256": sha256_file(args.governance_receipt),
        },
        "r6d_disposition": {
            "status": (
                "ACTIVE_WITH_PHYSICAL_EVIDENCE"
                if r6d.status == "TRAINED_WITH_PHYSICAL_EVIDENCE"
                else "FROZEN_ZERO"
            ),
            "rationale": r6d.reason,
            "impact_on_conclusion": r6d.limitation,
            "evidence": r6d.evidence.model_dump(mode="json") if r6d.evidence else None,
        },
        "gripper_disposition": {
            "status": (
                "ACTIVE_WITH_PHYSICAL_EVIDENCE"
                if gripper.status == "TRAINED_WITH_PHYSICAL_EVIDENCE"
                else "FROZEN_ZERO"
            ),
            "rationale": gripper.reason,
            "impact_on_conclusion": gripper.limitation,
            "evidence": gripper.evidence.model_dump(mode="json") if gripper.evidence else None,
        },
    }
    report.update(
        {
            "episodes_path": str(args.episodes),
            "episodes_sha256": sha256_file(args.episodes),
            "evidence_manifest_path": str(args.evidence_root / "manifest.json"),
            "evidence_manifest_sha256": sha256_file(args.evidence_root / "manifest.json"),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
