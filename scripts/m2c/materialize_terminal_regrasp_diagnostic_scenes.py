#!/usr/bin/env python3
"""Materialize the exact ADR-0026 C1/C2/C3 diagnostic scene sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from m2c.s4_scene_family import materialize_scene
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    CONTROLLED_URDF_SHA256,
    TerminalDiagnosticError,
    load_committed_diagnostic_prereg,
    materialize_diagnostic_scene,
    sha256_bytes,
)


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
CONTROLLED_URDF = ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"


def materialize_sources(
    *,
    project_root: Path,
    prereg_path: Path,
    output_root: Path,
) -> dict[str, object]:
    resolved = load_committed_diagnostic_prereg(
        project_root=project_root,
        prereg_path=prereg_path,
    )
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite diagnostic source root: {output_root}")
    template = (project_root / TEMPLATE.relative_to(ROOT)).read_text(encoding="utf-8")
    urdf_bytes = (project_root / CONTROLLED_URDF.relative_to(ROOT)).read_bytes()
    if sha256_bytes(urdf_bytes) != CONTROLLED_URDF_SHA256:
        raise TerminalDiagnosticError("diagnostic controlled URDF digest mismatch")
    cache: dict[int, tuple[bytes, bytes]] = {}
    staged: list[tuple[object, bytes, bytes]] = []
    for run in resolved.prereg.runs:
        if run.source_base_seed not in cache:
            full = materialize_scene(
                template,
                run.source_base_seed,
                tuple(run.anchor_xy_m),
            )
            if full is None:
                raise TerminalDiagnosticError("diagnostic source seed is not a six-object scene")
            cache[run.source_base_seed] = (full[0], full[1])
        full_sdf, full_supervision = cache[run.source_base_seed]
        sdf, supervision = materialize_diagnostic_scene(
            full_v4_sdf_bytes=full_sdf,
            full_v4_supervision_bytes=full_supervision,
            scene_seed=run.scene_seed,
            source_base_seed=run.source_base_seed,
            condition=run.condition,
        )
        if (
            sha256_bytes(sdf) != run.sdf_sha256
            or sha256_bytes(supervision) != run.supervision_sha256
        ):
            raise TerminalDiagnosticError(
                "diagnostic materialized source differs from preregistration"
            )
        staged.append((run, sdf, supervision))
    output_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    urdf_path = output_root / CONTROLLED_URDF.name
    urdf_path.write_bytes(urdf_bytes)
    records: list[dict[str, object]] = []
    for run, sdf, supervision in staged:
        sdf_path = output_root / f"scene-{run.scene_seed}.sdf"
        supervision_path = output_root / f"scene-{run.scene_seed}.supervision.json"
        sdf_path.write_bytes(sdf)
        supervision_path.write_bytes(supervision)
        records.append(
            {
                "ordinal": run.ordinal,
                "run_id": run.run_id,
                "condition": run.condition,
                "scene_seed": run.scene_seed,
                "sdf": str(sdf_path),
                "sdf_sha256": run.sdf_sha256,
                "supervision": str(supervision_path),
                "supervision_sha256": run.supervision_sha256,
            }
        )
    receipt = {
        "schema_version": "M2CTerminalDiagnosticMaterializationReceiptV1",
        "status": "MATERIALIZED_OFFLINE_DIAGNOSTIC_ONLY_NO_ISAAC_EXECUTION",
        "campaign_id": resolved.prereg.campaign_id,
        "prereg_file_sha256": resolved.file_sha256,
        "prereg_sha256": resolved.prereg.prereg_sha256,
        "records": records,
        "controlled_urdf": str(urdf_path),
        "controlled_urdf_sha256": CONTROLLED_URDF_SHA256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    (output_root / "materialization-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    for member in output_root.iterdir():
        member.chmod(0o444)
    output_root.chmod(0o555)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--prereg", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    receipt = materialize_sources(
        project_root=args.project_root.resolve(strict=True),
        prereg_path=args.prereg,
        output_root=args.output_root,
    )
    print(json.dumps({"status": receipt["status"], "runs": len(receipt["records"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
