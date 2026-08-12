#!/usr/bin/env python3
"""Build or run one frozen M2C PATH_BLOCKED TRAIN/SMOKE collection job.

The worker is deliberately single-key and create-only.  ``--dry-run`` emits
the exact stage/probe commands without launching Docker.  A live run first
builds a clean Isaac stage, then executes the derived public scripted chain;
it never loads a model checkpoint and never counts as model-owned Q-B eval.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from m2c.derive_model_owned_chain_probe import derive_probe_bytes
from m2c.s4_scene_family import SCRIPTED_BLOCKER_ENTITY, TARGET_ENTITY
from m2c.package_path_blocked_collection import (
    DECISION_SOURCE,
    frozen_source_record,
    load_json_object,
    package_collection,
    project_frozen_manifests,
    sha256_file,
)
from xh_agent.data.isaac_m1b import M1B_URDF_SHA256


ISAAC_IMAGE = "nvcr.io/nvidia/isaac-sim:6.0.1"
TASK_TARGET_PUBLIC_COLOR = "yellow"
BLOCKER_PUBLIC_COLOR = "red"


def _validate_direct_source(path: Path, root: Path, *, label: str) -> None:
    if not path.is_file() or path.parent.resolve() != root.resolve():
        raise ValueError(f"{label} must be a direct file under source root: {path}")


def validate_frozen_scene_semantics(
    supervision: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Cross-check evaluator-only roles against the frozen public selectors."""

    headroom = supervision.get("m2c_headroom_domain")
    if not isinstance(headroom, dict):
        raise ValueError("scene lacks the frozen M2C headroom domain contract")
    if (
        headroom.get("target_entity_evaluator_only") != TARGET_ENTITY
        or headroom.get("scripted_blocker_entity_evaluator_only") != SCRIPTED_BLOCKER_ENTITY
        or headroom.get("target_selector") != record["target_selector_policy_input"]
        or headroom.get("scripted_blocker_selector") != record["blocker_selector_policy_input"]
        or headroom.get("scripted_bin_cell_index")
        != int(str(record["destination_cell"]).removeprefix("BIN_CELL_"))
    ):
        raise ValueError("scene roles, public selectors, or destination differ from frozen key")


def stage_command(
    args: argparse.Namespace,
    *,
    output: Path,
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{args.container_prefix}-stage",
        "--gpus",
        f"device={args.gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{args.project_root}:/workspace/project:ro",
        "-v",
        f"{args.source_root}:/workspace/source:ro",
        "-v",
        f"{output}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        args.image,
        "scripts/isaac_m1b_dataset_benchmark.py",
        "--sdf",
        f"/workspace/source/{args.sdf.name}",
        "--supervision",
        f"/workspace/source/{args.supervision.name}",
        "--urdf",
        f"/workspace/source/{args.urdf.name}",
        "--output",
        "/workspace/output",
        "--worker-id",
        "0",
        "--physical-gpu-index",
        # Docker remaps the selected host device to cuda:0 inside the
        # single-GPU container.  Passing the host ordinal here makes a
        # host-GPU-1 worker request a nonexistent in-container cuda:1.
        "0",
        "--frames",
        "1",
        "--warmup-frames",
        "1",
    ]


def probe_command(
    args: argparse.Namespace,
    *,
    derived_probe: Path,
    stage: Path,
    output: Path,
    source_record: dict[str, Any],
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{args.container_prefix}-probe",
        "--gpus",
        f"device={args.gpu}",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "PYTHONPATH=/workspace/project/src",
        "-v",
        f"{args.project_root}:/workspace/project:ro",
        "-v",
        f"{args.source_root}:/workspace/source:ro",
        "-v",
        f"{derived_probe.parent}:/workspace/derived:ro",
        "-v",
        f"{stage.parent}:/workspace/stage:ro",
        "-v",
        f"{output}:/workspace/output",
        "-w",
        "/workspace/project",
        "--entrypoint",
        "/isaac-sim/python.sh",
        args.image,
        f"/workspace/derived/{derived_probe.name}",
        "--stage",
        f"/workspace/stage/{stage.name}",
        "--sdf",
        f"/workspace/source/{args.sdf.name}",
        "--supervision",
        f"/workspace/source/{args.supervision.name}",
        "--urdf",
        f"/workspace/source/{args.urdf.name}",
        "--output",
        "/workspace/output",
        "--target-object",
        SCRIPTED_BLOCKER_ENTITY,
        "--m2b-task-target-object",
        TARGET_ENTITY,
        "--physics-device",
        "cuda",
        "--contact-centerlines-m",
        "0.12,0.11,0.10,0.09,0.08",
        "--gripper-close-steps",
        "132",
        "--calibration-free-gap-yaw",
        "--m2b-capture-public-rgbd",
        "--m2b-task-target-public-color",
        TASK_TARGET_PUBLIC_COLOR,
        "--m2b-injected-public-grasp-color",
        BLOCKER_PUBLIC_COLOR,
        "--m2c-scripted-safe-place-bin-cell",
        str(source_record["destination_cell"]).removeprefix("BIN_CELL_"),
        "--m2c-chain-role",
        args.role,
        "--m2c-matched-key",
        args.matched_key,
        "--m2c-failure-seed",
        str(source_record["failure_seed"]),
        "--m2c-decision-source",
        DECISION_SOURCE,
    ]


def stage_is_valid(
    stage_root: Path,
    *,
    sdf: Path,
    supervision: Path,
    urdf: Path,
) -> bool:
    metrics_path = stage_root / "metrics.json"
    stage_path = stage_root / "m1b_physics_scene.usdc"
    if not metrics_path.is_file() or not stage_path.is_file():
        return False
    metrics = load_json_object(metrics_path, label="Isaac stage metrics")
    hashes = metrics.get("source_hashes")
    clean = metrics.get("clean_physics_stage")
    return bool(
        metrics.get("status") == "PASS"
        and isinstance(hashes, dict)
        and hashes.get(sdf.name) == sha256_file(sdf)
        and hashes.get(supervision.name) == sha256_file(supervision)
        and hashes.get(urdf.name) == sha256_file(urdf)
        and isinstance(clean, dict)
        and clean.get("sha256") == sha256_file(stage_path)
    )


def _write_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def prepare_job(args: argparse.Namespace) -> tuple[dict[str, Any], list[str], list[str]]:
    """Fail closed on sources/key, derive the probe, and return exact commands."""

    for root, label in (
        (args.project_root, "project root"),
        (args.source_root, "source root"),
    ):
        if not root.is_dir():
            raise ValueError(f"{label} is not a directory: {root}")
    for source, label in (
        (args.sdf, "SDF"),
        (args.supervision, "supervision"),
        (args.urdf, "URDF"),
    ):
        _validate_direct_source(source, args.source_root, label=label)
    for source, label in (
        (args.upstream_v4_probe, "frozen V4 probe"),
        (args.training_keys, "training key manifest"),
        (args.s6_keys, "S6 key manifest"),
        (args.runtime_registry, "runtime registry"),
    ):
        if not source.is_file():
            raise ValueError(f"{label} is missing: {source}")

    training, _s6, collection, s6 = project_frozen_manifests(
        args.training_keys,
        args.s6_keys,
        args.runtime_registry,
    )
    record = frozen_source_record(training, role=args.role, matched_key=args.matched_key)
    if int(record["scene_seed"]) in {9038, 9057, 9077} or any(
        key.matched_key == args.matched_key or key.scene_seed == int(record["scene_seed"])
        for key in s6.keys
    ):
        raise ValueError("worker request overlaps V4 or frozen S6")
    collection_matches = [key for key in collection.keys if key.matched_key == args.matched_key]
    if len(collection_matches) != 1 or collection_matches[0].collection_role != args.role:
        raise ValueError("worker key is not exactly once in projected collection manifest")
    if sha256_file(args.sdf) != record["sdf_sha256"]:
        raise ValueError("SDF SHA-256 differs from frozen key")
    if sha256_file(args.supervision) != record["supervision_sha256"]:
        raise ValueError("supervision SHA-256 differs from frozen key")
    if args.urdf.name != "panda_controlled.urdf" or sha256_file(args.urdf) != M1B_URDF_SHA256:
        raise ValueError("URDF name or SHA-256 differs from the production Isaac contract")
    validate_frozen_scene_semantics(
        load_json_object(args.supervision, label="scene supervision"),
        record,
    )

    job_root = args.output_root / args.role.lower() / args.matched_key
    if job_root.exists():
        raise FileExistsError(f"refusing to overwrite collection job: {job_root}")
    job_root.mkdir(parents=True, exist_ok=False)
    derived = job_root / "derived-path-blocked-probe.py"
    derived.write_bytes(derive_probe_bytes(args.upstream_v4_probe.read_bytes()))
    derived.chmod(0o555)
    stage_root = job_root / "stage"
    probe_root = job_root / "probe"
    stage_root.mkdir()
    probe_root.mkdir()
    stage_root.chmod(0o777)
    probe_root.chmod(0o777)
    stage_cmd = stage_command(args, output=stage_root)
    probe_cmd = probe_command(
        args,
        derived_probe=derived,
        stage=stage_root / "m1b_physics_scene.usdc",
        output=probe_root,
        source_record=record,
    )
    job_receipt: dict[str, Any] = {
        "schema_version": "M2CPathBlockedCollectionJobV2",
        "status": "DRY_RUN_NOT_EXECUTED" if args.dry_run else "PREPARED_NOT_EXECUTED",
        "matched_key": args.matched_key,
        "scene_seed": record["scene_seed"],
        "failure_seed": record["failure_seed"],
        "split": record["split"],
        "collection_role": args.role,
        "decision_source": DECISION_SOURCE,
        "model_owned": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
        "derived_probe": str(derived),
        "derived_probe_sha256": sha256_file(derived),
        "upstream_v4_probe_sha256": sha256_file(args.upstream_v4_probe),
        "sdf_sha256": sha256_file(args.sdf),
        "supervision_sha256": sha256_file(args.supervision),
        "urdf_sha256": sha256_file(args.urdf),
        "training_key_manifest_sha256": sha256_file(args.training_keys),
        "s6_key_manifest_sha256": sha256_file(args.s6_keys),
        "runtime_registry_sha256": sha256_file(args.runtime_registry),
        "stage_command": stage_cmd,
        "probe_command": probe_cmd,
        "stage_command_shell": shlex.join(stage_cmd),
        "probe_command_shell": shlex.join(probe_cmd),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_executed": False,
        "evaluation_executed": False,
    }
    _write_new(job_root / "collection-job-v2.json", job_receipt)
    return job_receipt, stage_cmd, probe_cmd


def run(args: argparse.Namespace) -> dict[str, Any]:
    receipt, stage_cmd, probe_cmd = prepare_job(args)
    job_root = args.output_root / args.role.lower() / args.matched_key
    if args.dry_run:
        return {**receipt, "job_root": str(job_root)}

    stage_completed = subprocess.run(
        stage_cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=args.stage_timeout_s,
    )
    (job_root / "stage" / "console.log").write_text(
        stage_completed.stdout + stage_completed.stderr,
        encoding="utf-8",
    )
    if stage_completed.returncode != 0 or not stage_is_valid(
        job_root / "stage",
        sdf=args.sdf,
        supervision=args.supervision,
        urdf=args.urdf,
    ):
        raise RuntimeError("Isaac stage builder failed its hash-bound acceptance gate")
    probe_completed = subprocess.run(
        probe_cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=args.probe_timeout_s,
    )
    (job_root / "probe" / "console.log").write_text(
        probe_completed.stdout + probe_completed.stderr,
        encoding="utf-8",
    )
    raw_probe = job_root / "probe" / "actuation-probe.json"
    if probe_completed.returncode != 0 or not raw_probe.is_file():
        raise RuntimeError("Isaac PATH_BLOCKED probe failed or emitted no raw evidence")
    packaged = package_collection(
        raw_probe_path=raw_probe,
        evidence_root=job_root / "probe",
        output_root=args.packaged_output_root,
        role=args.role,
        matched_key=args.matched_key,
        training_keys_path=args.training_keys,
        s6_keys_path=args.s6_keys,
        runtime_registry_path=args.runtime_registry,
        derived_probe_path=job_root / "derived-path-blocked-probe.py",
        upstream_v4_probe_path=args.upstream_v4_probe,
    )
    return {
        **receipt,
        "status": "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION_PACKAGED",
        "job_root": str(job_root),
        "package": packaged,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--sdf", required=True, type=Path)
    parser.add_argument("--supervision", required=True, type=Path)
    parser.add_argument("--urdf", required=True, type=Path)
    parser.add_argument("--upstream-v4-probe", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--packaged-output-root", required=True, type=Path)
    parser.add_argument("--role", choices=("TRAIN", "SMOKE"), required=True)
    parser.add_argument("--matched-key", required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--image", default=ISAAC_IMAGE)
    parser.add_argument("--container-prefix", default="m2c-path-blocked")
    parser.add_argument("--stage-timeout-s", type=float, default=1200.0)
    parser.add_argument("--probe-timeout-s", type=float, default=5400.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--training-keys",
        type=Path,
        default=project / "configs/m2c_s4_training_keys.json",
    )
    parser.add_argument(
        "--s6-keys",
        type=Path,
        default=project / "configs/m2c_s6_evaluation_keys.json",
    )
    parser.add_argument(
        "--runtime-registry",
        type=Path,
        default=project / "configs/qrm_runtime_mapping_v2.yaml",
    )
    args = parser.parse_args(argv)
    if args.gpu < 0 or args.stage_timeout_s <= 0 or args.probe_timeout_s <= 0:
        parser.error("GPU and timeout values are invalid")
    return args


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
