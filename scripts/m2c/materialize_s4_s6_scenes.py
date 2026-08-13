#!/usr/bin/env python3
"""Materialize hash-bound M2C S4/S6 scene sources from frozen key manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from m2c.s4_scene_family import materialize_scene


PROJECT = Path(__file__).resolve().parents[2]
TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
CONTROLLED_URDF = PROJECT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
CONTROLLED_URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def records_for_role(
    training: dict[str, object],
    evaluation: dict[str, object],
    role: str,
) -> list[dict[str, object]]:
    return {
        "TRAIN": training["training_keys"],
        "SMOKE": training["physical_prerequisite_smoke_keys"],
        "EVALUATION": evaluation["evaluation_keys"],
    }[role]  # type: ignore[return-value]


def records_for_v3_train(
    training: dict[str, object],
    *,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Select the create-only ADR-0021 TRAIN sources; SMOKE is unauthorized."""

    if (
        training.get("schema_version") != "M2CS4V3TrainingKeyManifestV1"
        or training.get("status") != "FROZEN_TRAIN_ONLY_BEFORE_ANY_V3_COLLECTION"
        or training.get("train_only") is not True
        or training.get("smoke_collection_authorized") is not False
        or training.get("evaluation_collection_authorized") is not False
        or training.get("teacher_used") is not False
        or training.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("V3 source materialization requires the frozen TRAIN-only manifest")
    records = training.get("training_keys")
    if not isinstance(records, list) or len(records) != 36:
        raise ValueError("V3 source manifest must contain exactly 36 TRAIN keys")
    if any(
        not isinstance(record, dict)
        or record.get("role") != "TRAIN"
        or record.get("split") != "train"
        or record.get("candidate_contract_revision") != "PublicTrackCandidateV3"
        or record.get("teacher_used") is not False
        or record.get("privileged_truth_policy_input") is not False
        for record in records
    ):
        raise ValueError("V3 source manifest contains a non-TRAIN or forbidden key")
    if limit is not None and not 1 <= limit <= len(records):
        raise ValueError("V3 materialization limit must be in [1, 36]")
    return records[:limit] if limit is not None else records  # type: ignore[return-value]


def materialize(
    records: list[dict[str, object]],
    *,
    output_root: Path,
) -> dict[str, object]:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite scene source root: {output_root}")
    template = TEMPLATE.read_text(encoding="utf-8")
    urdf_bytes = CONTROLLED_URDF.read_bytes()
    if sha256_bytes(urdf_bytes) != CONTROLLED_URDF_SHA256:
        raise ValueError("controlled Panda URDF SHA-256 mismatch")
    staged: list[tuple[int, bytes, bytes, dict[str, object]]] = []
    for record in records:
        seed = int(record["scene_seed"])
        anchor = tuple(float(value) for value in record["anchor_xy_m"])
        candidate = materialize_scene(template, seed, anchor)
        if candidate is None:
            raise ValueError(f"frozen seed {seed} is no longer a six-object scene")
        sdf_bytes, supervision_bytes, receipt = candidate
        if receipt["sdf_sha256"] != record["sdf_sha256"]:
            raise ValueError(f"seed {seed}: frozen SDF SHA-256 mismatch")
        if receipt["supervision_sha256"] != record["supervision_sha256"]:
            raise ValueError(f"seed {seed}: frozen supervision SHA-256 mismatch")
        staged.append((seed, sdf_bytes, supervision_bytes, record))
    output_root.mkdir(parents=True, exist_ok=False)
    urdf = output_root / CONTROLLED_URDF.name
    urdf.write_bytes(urdf_bytes)
    written = []
    for seed, sdf_bytes, supervision_bytes, record in staged:
        sdf = output_root / f"scene-{seed}.sdf"
        supervision = output_root / f"scene-{seed}.supervision.json"
        sdf.write_bytes(sdf_bytes)
        supervision.write_bytes(supervision_bytes)
        written.append(
            {
                "scene_seed": seed,
                "matched_key": record["matched_key"],
                "sdf": str(sdf),
                "sdf_sha256": record["sdf_sha256"],
                "supervision": str(supervision),
                "supervision_sha256": record["supervision_sha256"],
            }
        )
    receipt = {
        "schema_version": "M2CS4S6SceneMaterializationReceiptV1",
        "status": "MATERIALIZED_OFFLINE_NO_ISAAC_EXECUTION",
        "records": written,
        "controlled_urdf": str(urdf),
        "controlled_urdf_sha256": CONTROLLED_URDF_SHA256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    (output_root / "materialization-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--training-manifest",
        type=Path,
        default=PROJECT / "configs/m2c_s4_training_keys.json",
    )
    parser.add_argument(
        "--evaluation-manifest",
        type=Path,
        default=PROJECT / "configs/m2c_s6_evaluation_keys.json",
    )
    parser.add_argument("--role", choices=("TRAIN", "SMOKE", "EVALUATION"), required=True)
    parser.add_argument(
        "--v3-train-only",
        action="store_true",
        help="consume M2CS4V3TrainingKeyManifestV1; role must be TRAIN",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    training = json.loads(args.training_manifest.read_text())
    evaluation = json.loads(args.evaluation_manifest.read_text())
    if args.v3_train_only and args.role != "TRAIN":
        parser.error("--v3-train-only authorizes role TRAIN only")
    receipt = materialize(
        (
            records_for_v3_train(training, limit=args.limit)
            if args.v3_train_only
            else records_for_role(training, evaluation, args.role)
        ),
        output_root=args.output_root,
    )
    print(json.dumps({"status": receipt["status"], "scenes": len(receipt["records"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
