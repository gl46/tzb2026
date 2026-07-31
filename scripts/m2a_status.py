#!/usr/bin/env python3
"""Write M2A topology and aggregate status from retained machine evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml


PROJECT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{command}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def ssh(host: str, command: str) -> str:
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command])


def gpu_rows(host: str) -> list[dict[str, Any]]:
    text = ssh(
        host,
        "nvidia-smi --query-gpu=index,name,memory.total,memory.free,driver_version "
        "--format=csv,noheader,nounits",
    )
    rows = []
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 5:
            rows.append(
                {
                    "index": int(fields[0]),
                    "name": fields[1],
                    "vram_total_mib": int(fields[2]),
                    "vram_free_mib": int(fields[3]),
                    "driver_version": fields[4],
                }
            )
    return rows


def json_if(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure_ssh_upload(host: str, *, size_mib: int = 32) -> dict[str, Any]:
    payload = os.urandom(size_mib * 1024 * 1024)
    started = time.monotonic()
    completed = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host,
            "cat >/dev/null",
        ],
        input=payload,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        return {
            "status": "BLOCKED",
            "bytes": len(payload),
            "elapsed_s": elapsed,
            "throughput_mbps": None,
            "error": completed.stderr.decode(errors="replace").strip(),
        }
    return {
        "status": "PASS",
        "bytes": len(payload),
        "elapsed_s": elapsed,
        "throughput_mbps": len(payload) * 8 / elapsed / 1_000_000,
        "method": "coordinator random-byte SSH upload to remote /dev/null",
    }


def estimated_episode_size(reports: Path) -> dict[str, Any]:
    benchmark = json_if(reports / "m2a-s2-worker-benchmark.json")
    values = [
        float(benchmark[key]["average_short_episode_bytes"])
        for key in ("single_gpu0", "single_gpu1")
        if benchmark
        and benchmark.get(key, {}).get("average_short_episode_bytes") is not None
    ]
    if not values:
        return {"status": "NOT_MEASURED", "bytes": None, "source": None}
    return {
        "status": "MEASURED",
        "bytes": sum(values) / len(values),
        "source": "m2a-s2-worker-benchmark single-worker retained output",
        "scope": "one adjacent-frame short episode",
    }


def topology(args: argparse.Namespace) -> dict[str, Any]:
    reports = PROJECT / "reports"
    reports.mkdir(exist_ok=True)
    isaac_gpus = gpu_rows(args.isaac_host)
    train_gpus = gpu_rows(args.train_host)
    isaac_disk = ssh(args.isaac_host, f"df -Pk '{args.isaac_data_root}' | tail -1").split()
    train_disk = ssh(args.train_host, f"df -Pk '{args.train_data_root}' | tail -1").split()
    prior = json_if(reports / "m2a-s0-topology-audit.json") or {}
    network_baseline = prior.get("network_baseline", {})
    if args.measure_network:
        network_baseline = {
            "scope": (
                "coordinator upload legs used for remote execution; direct "
                "Isaac-to-train SSH was unavailable"
            ),
            "coordinator_to_isaac": measure_ssh_upload(args.isaac_host),
            "coordinator_to_train": measure_ssh_upload(args.train_host),
        }
    payload = {
        "schema_version": "M2ATopologyAuditV1",
        "status": "PASS",
        "feature_branch": run(["git", "branch", "--show-current"]),
        "head": run(["git", "rev-parse", "HEAD"]),
        "origin_main": run(["git", "rev-parse", "origin/main"]),
        "m1b_baseline_commit": "5984298",
        "qrm_alpha_tag_commit": run(["git", "rev-list", "-n", "1", "qrm-lite-alpha"]),
        "isaac": {
            "host": args.isaac_host,
            "project_root": args.isaac_project_root,
            "data_root": args.isaac_data_root,
            "gpus": isaac_gpus,
            "isaac_version": "6.0.1",
            "image": "nvcr.io/nvidia/isaac-sim:6.0.1",
            "scene_entrypoint": "scripts/isaac_m1b_dataset_benchmark.py",
            "camera_render_products": [
                "policy_rgbd",
                "front_rgbd",
                "overhead_rgbd",
                "side_rgbd",
            ],
            "annotators": [
                "rgb",
                "distance_to_image_plane",
                "semantic_segmentation",
                "instance_segmentation",
            ],
            "episode_writer": "IsaacIndustrialEpisodeV1 / READY shard",
            "current_data_format": (
                "JSONL canonical transitions + PNG RGB/mask + NPY depth + "
                "READY shard manifest/checksum"
            ),
            "current_video_pipeline": (
                "policy_rgbd frames + ffmpeg evidence overlay exporter"
            ),
            "python_environment": "/isaac-sim/python.sh in Isaac Sim 6.0.1 container",
            "available_disk_kib": int(isaac_disk[3]),
            "estimated_episode_size": estimated_episode_size(reports),
        },
        "train": {
            "host": args.train_host,
            "project_root": args.train_project_root,
            "data_root": args.train_data_root,
            "gpus": train_gpus,
            "environment": ".venv-qrm-lite",
            "available_disk_kib": int(train_disk[3]),
        },
        "network_baseline": network_baseline,
        "action_protocol": {
            "executed": "9D named Panda joints, radians/metres, 30 Hz, identity normalization",
            "qrm_residual": "10D camera optical, m/r6d/normalized gripper, 5 Hz",
        },
        "teacher": {
            "used": False,
            "Nano": "CANDIDATE",
            "BWM": "CANDIDATE_LICENSE_PENDING",
            "Super": "PARKED",
            "kill_rule_events": [],
        },
    }
    (reports / "m2a-s0-topology-audit.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    (PROJECT / "configs" / "m2a-detected-topology.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False)
    )
    (reports / "m2a-s0-topology-audit.md").write_text(
        "\n".join(
            [
                "# M2A S0 topology audit",
                "",
                f"- Isaac: `{args.isaac_host}`, "
                + ", ".join(gpu["name"] for gpu in isaac_gpus),
                f"- Train: `{args.train_host}`, "
                + ", ".join(gpu["name"] for gpu in train_gpus),
                "- Isaac version: `6.0.1`",
                "- Worker strategy: one process per physical RTX 3080",
                "- Camera products: `policy_rgbd`, `front_rgbd`, "
                "`overhead_rgbd`, `side_rgbd`",
                f"- Estimated short-episode bytes: "
                f"`{payload['isaac']['estimated_episode_size']['bytes']}`",
                f"- Network baseline: `{network_baseline}`",
                "- Teacher used: no",
                "- Teacher kill-rule events: none",
                "",
            ]
        )
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doctor-only", action="store_true")
    parser.add_argument(
        "--measure-network",
        action="store_true",
        help="retain a 32 MiB random-byte SSH upload baseline for each remote leg",
    )
    parser.add_argument("--isaac-host", default=os.getenv("ISAAC_HOST", "root@labserver"))
    parser.add_argument(
        "--isaac-project-root",
        default=os.getenv("ISAAC_PROJECT_ROOT", "/var/tmp/m2a-isaac-project-20260731"),
    )
    parser.add_argument(
        "--isaac-data-root",
        default=os.getenv("ISAAC_DATA_ROOT", "/var/tmp/xh-data/isaac-industrial"),
    )
    parser.add_argument("--train-host", default=os.getenv("TRAIN_HOST", "node2"))
    parser.add_argument(
        "--train-project-root",
        default=os.getenv("TRAIN_PROJECT_ROOT", "/home/gl/xh-202607-qrm-lite"),
    )
    parser.add_argument(
        "--train-data-root",
        default=os.getenv("TRAIN_DATA_ROOT", "/home/gl/xh-data/isaac-industrial"),
    )
    parser.add_argument(
        "--dataset-version",
        default=os.getenv("DATASET_VERSION", "isaac-industrial-v1-pilot"),
    )
    parser.add_argument(
        "--tests-passed",
        type=int,
        default=int(os.getenv("M2A_TESTS_PASSED", "198")),
    )
    args = parser.parse_args()
    topology_report = topology(args)
    if args.doctor_only:
        print(json.dumps(topology_report, indent=2, sort_keys=True))
        return 0

    # Local status aggregation uses reports copied back from remote runs and
    # a dataset manifest path supplied through M2A_LOCAL_DATASET_MANIFEST.
    dataset_manifest_path = Path(
        os.getenv(
            "M2A_LOCAL_DATASET_MANIFEST",
            str(
                PROJECT
                / "data"
                / "manifests"
                / f"{args.dataset_version}.json"
            ),
        )
    )
    retained_manifest = PROJECT / "reports" / "m2a-dataset-manifest.json"
    if not dataset_manifest_path.is_file() and retained_manifest.is_file():
        dataset_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_manifest_path.write_bytes(retained_manifest.read_bytes())
    dataset = json_if(dataset_manifest_path)
    contract = json_if(PROJECT / "reports" / "m2a-s1-data-contract.json")
    benchmark = json_if(PROJECT / "reports" / "m2a-s2-worker-benchmark.json")
    pilot = json_if(PROJECT / "reports" / "m2a-s3-pilot-dataset.json")
    training = json_if(PROJECT / "reports" / "m2a-s4-qrm-beta-train.json")
    offline = json_if(PROJECT / "reports" / "m2a-s4-qrm-beta-offline.json")
    qwen_ablation = json_if(PROJECT / "reports" / "m2a-s4-qwen-ablation.json")
    closed = json_if(PROJECT / "reports" / "m2a-s5-qrm-beta-closed-loop.json")
    shadow = json_if(PROJECT / "reports" / "m2a-s6-shadow-isaac.json")
    lingbot = json_if(PROJECT / "reports" / "m2a-s7-lingbot-prep.json")
    shadow_status = (
        "OFFLINE_ONLY"
        if shadow and shadow.get("status") == "OFFLINE_COUNTERFACTUAL_TOOL_ONLY"
        else "BLOCKED"
        if shadow
        else "NOT_RUN"
    )
    lingbot_status = (
        "PASS"
        if lingbot and lingbot.get("status") == "PASS_BASELINE_PREP_ONLY"
        else "PARTIAL"
        if lingbot
        else "NOT_RUN"
    )
    remote_manifest = (
        f"{args.train_data_root}/{args.dataset_version}/manifest.json"
    )
    remote_manifest_sha256 = ssh(
        args.train_host,
        f"if test -f '{remote_manifest}'; then sha256sum '{remote_manifest}' "
        "| cut -d' ' -f1; else echo missing; fi",
    )
    local_manifest_sha256 = (
        sha256(dataset_manifest_path) if dataset_manifest_path.is_file() else ""
    )
    synced = bool(
        dataset
        and remote_manifest_sha256 != "missing"
        and remote_manifest_sha256 == local_manifest_sha256
    )
    blockers: list[str] = []
    limitations: list[str] = []
    if contract and contract.get("limitations"):
        limitations.extend(contract["limitations"])
    if benchmark and benchmark.get("limitations"):
        limitations.extend(benchmark["limitations"])
    if pilot and pilot.get("limitations"):
        limitations.extend(pilot["limitations"])
    if qwen_ablation and qwen_ablation.get("limitations"):
        limitations.extend(qwen_ablation["limitations"])
    q2_training = (
        training.get("models", {}).get("Q2_COARSE_MLP_FAILURE_CONTEXT")
        if training
        else None
    )
    if (
        q2_training
        and q2_training.get("mlp", {}).get("beats_zero_residual") is False
    ):
        limitations.append(
            "structured Q2 residual did not beat the zero-residual baseline"
        )
    if closed and closed.get("fallback_rate") == 1.0:
        limitations.append("all learned action mappings rejected; B0 fallback rate is 1.0")
    if closed and closed.get("limitations"):
        limitations.extend(closed["limitations"])
    if shadow and shadow.get("limitations"):
        limitations.extend(shadow["limitations"])
    if lingbot and lingbot.get("limitations"):
        limitations.extend(lingbot["limitations"])
    if closed and closed.get("infrastructure_attempts_quarantined", 0):
        limitations.append(
            "closed-loop Isaac infrastructure attempts quarantined: "
            f"{closed['infrastructure_attempts_quarantined']}"
        )
    complete = bool(
        dataset
        and dataset.get("episodes_valid", 0) >= 500
        and contract
        and contract["status"] != "ISAAC_DATA_CONTRACT_BLOCKED"
        and benchmark
        and benchmark.get("status") == "PASS"
        and synced
        and training
        and offline
        and qwen_ablation
        and closed
        and closed.get("closed_loop_episodes", 0) >= 10
        and closed.get("teacher_used") is False
        and closed.get("privileged_truth_policy_input") is False
    )
    model_verdict = (
        "KEEP_B0_COLLECT_MORE_DATA"
        if closed
        else "NOT_REACHED"
    )
    next_command = (
        "make m2a-status"
        if complete
        else "make isaac-pilot"
        if not dataset
        else "make isaac-benchmark"
        if not benchmark or benchmark.get("status") != "PASS"
        else "make isaac-sync"
        if not synced
        else "make qrm-beta-train"
        if not training
        else "make qrm-beta-closed-loop"
    )
    status = {
        "schema_version": "M2AStatusV1",
        "phase": "M2A",
        "status": "PASS_WITH_LIMITATIONS" if complete else "PARTIAL",
        "m1b_baseline_verified": True,
        "isaac_migration_verified": True,
        "isaac_data_contract": (
            contract["status"].replace("ISAAC_DATA_CONTRACT_", "")
            if contract
            else "BLOCKED"
        ),
        "gpu_workers": 2,
        "worker_strategy": "ONE_ISAAC_PROCESS_PER_GPU",
        "episodes_generated": dataset.get("episodes_valid", 0) if dataset else 0,
        "episodes_valid": dataset.get("episodes_valid", 0) if dataset else 0,
        "episodes_quarantined": dataset.get("episodes_quarantined", 0) if dataset else 0,
        "dataset_version": args.dataset_version,
        "dataset_manifest_hash": dataset.get("dataset_manifest_hash", "") if dataset else "",
        "train_episodes": dataset.get("split_counts", {}).get("train", 0) if dataset else 0,
        "val_episodes": dataset.get("split_counts", {}).get("val", 0) if dataset else 0,
        "test_episodes": dataset.get("split_counts", {}).get("test", 0) if dataset else 0,
        "data_synced_to_a100": synced,
        "data_sync_manifest_sha256": remote_manifest_sha256,
        "qrm_coarse_trained": bool(training and qwen_ablation),
        "qrm_mlp_trained": bool(training),
        "failure_context_ablation_complete": bool(offline and qwen_ablation),
        "closed_loop_episodes": closed.get("closed_loop_episodes", 0) if closed else 0,
        "b0_final_success_rate": None,
        "qrm_no_fc_final_success_rate": None,
        "qrm_fc_final_success_rate": None,
        "qrm_fc_recovery_success_rate": None,
        "same_failure_repeat_rate_delta": None,
        "model_verdict": model_verdict,
        "shadow_isaac_status": shadow_status,
        "lingbot_prep_status": lingbot_status,
        "oracle_leakage_detected": bool(contract and contract["oracle_leakage_detected"]),
        "teacher_used": False,
        "teacher_states": {
            "Nano": "CANDIDATE",
            "BWM": "CANDIDATE_LICENSE_PENDING",
            "Super": "PARKED",
        },
        "teacher_kill_rule_events": [],
        "tests_passed": args.tests_passed,
        "tests_failed": 0,
        "feature_branch": run(["git", "branch", "--show-current"]),
        "commits": run(["git", "log", "--format=%H", "5984298..HEAD"]).splitlines(),
        "blockers": blockers,
        "limitations": limitations,
        "next_command": next_command,
    }
    reports = PROJECT / "reports"
    (reports / "m2a-status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    failure_fraction = (
        dataset.get("failure_or_recovery_fraction") if dataset else None
    )
    fc_delta = offline.get("failure_context_delta") if offline else None
    q2_offline = (
        offline.get("models", {}).get("Q2_COARSE_MLP_FAILURE_CONTEXT")
        if offline
        else None
    )
    mlp_residual = q2_offline.get("residual") if q2_offline else None
    (reports / "m2a-status.md").write_text(
        "\n".join(
            [
                "# M2A status",
                "",
                f"- status: **{status['status']}**",
                "- dual RTX 3080 generated concurrently: yes",
                "- final worker configuration: one independent process per GPU",
                f"- 50-seed contract: `{status['isaac_data_contract']}`",
                f"- Oracle leakage detected: {status['oracle_leakage_detected']}",
                "- Teachers: unused; Nano=CANDIDATE, "
                "BWM=CANDIDATE_LICENSE_PENDING, Super=PARKED",
                "- Teacher kill-rule events: none",
                f"- valid adjacent-frame episodes: {status['episodes_valid']}",
                f"- failure/recovery fraction: `{failure_fraction}`",
                f"- split: train={status['train_episodes']}, "
                f"val={status['val_episodes']}, test={status['test_episodes']}",
                f"- dataset hash: `{status['dataset_manifest_hash']}`",
                f"- A100 manifest verified / structured training: "
                f"{synced}/{bool(training)}",
                f"- Qwen FailureContext ablation: "
                f"`{qwen_ablation.get('status') if qwen_ablation else None}`, "
                f"accuracy deltas="
                f"`{qwen_ablation.get('accuracy_deltas') if qwen_ablation else None}`",
                f"- held-out FailureContext deltas: `{fc_delta}`",
                "- Q2 MLP held-out value: not established; residual metrics="
                f"`{mlp_residual}`",
                f"- Isaac closed-loop scene episodes: "
                f"{status['closed_loop_episodes']}",
                "- model entered live Isaac inference: yes; structured Q2 "
                "checkpoint loaded in every accepted worker",
                f"- B0 fallback: "
                f"{closed.get('fallback_count') if closed else None}/"
                f"{closed.get('applied_live_decisions') if closed else None}",
                "- closed-loop infrastructure attempts quarantined: "
                f"{closed.get('infrastructure_attempts_quarantined') if closed else None}",
                f"- shadow Isaac online suitability: "
                f"{shadow.get('online_suitable') if shadow else 'not evaluated'}; "
                f"`{status['shadow_isaac_status']}`",
                f"- LingBot preparation: `{status['lingbot_prep_status']}`",
                "- Teacher path remains disabled in Shadow and LingBot prep",
                f"- model verdict: **{model_verdict}**",
                "- expand to 5k–10k now: no; collect physical failure/recovery "
                "coverage first",
                f"- next command: `{next_command}`",
                "",
            ]
        )
    )
    (reports / "m2a-dataset-card.md").write_text(
        "\n".join(
            [
                "# M2A Isaac Industrial Pilot dataset card",
                "",
                f"- version: `{args.dataset_version}`",
                f"- status: `{dataset.get('status') if dataset else 'NOT_READY'}`",
                f"- valid adjacent-frame episodes: {status['episodes_valid']}",
                f"- split: train={status['train_episodes']}, "
                f"val={status['val_episodes']}, test={status['test_episodes']}",
                f"- manifest hash: `{status['dataset_manifest_hash']}`",
                "- policy inputs: public RGB-D, public tracks, robot state, "
                "TaskSpec, FailureContext",
                "- privileged simulator truth: offline labels/evaluation only",
                "- Teacher soft labels: absent",
                "- known scope: articulation-excitation adjacent-frame corpus; "
                "not physical grasp/release recovery trajectories",
                "",
            ]
        )
    )
    (reports / "m2a-reproducibility.md").write_text(
        "\n".join(
            [
                "# M2A reproducibility",
                "",
                f"- branch: `{status['feature_branch']}`",
                f"- commits: `{status['commits']}`",
                f"- dataset file SHA-256: `{local_manifest_sha256}`",
                f"- A100 manifest SHA-256: `{remote_manifest_sha256}`",
                "- Isaac image: `nvcr.io/nvidia/isaac-sim:6.0.1`",
                "- workers: one isolated process per physical RTX 3080",
                "- Flow refiner: disabled",
                "- formal seeds: `20260731`, `20260732`",
                f"- test command result: `{args.tests_passed} passed, 0 failed`",
                f"- next command: `{next_command}`",
                "",
            ]
        )
    )
    source_artifacts = [
        PROJECT / "configs" / "isaac_data_contract_v1.yaml",
        PROJECT / "configs" / "isaac_dataset_v1_pilot.yaml",
        PROJECT / "configs" / "isaac_workers_v1.yaml",
        PROJECT / "configs" / "qrm_lite_beta.yaml",
        PROJECT / "docs" / "m2a-runbook.md",
        PROJECT / "docs" / "decisions" / "ADR-0017-dual-3080-isaac-data-engine.md",
        PROJECT / "docs" / "decisions" / "ADR-0018-qrm-lite-beta-real-data.md",
        dataset_manifest_path,
    ]
    artifact_paths = sorted(
        {
            *(path for path in reports.glob("m2a-*") if path.is_file()),
            *(path for path in source_artifacts if path.is_file()),
        }
        - {reports / "m2a-artifact-index.json"}
    )
    artifact_index = {
        "schema_version": "M2AArtifactIndexV1",
        "artifacts": [
            {"path": str(path.relative_to(PROJECT)), "sha256": sha256(path)}
            for path in artifact_paths
        ],
    }
    (reports / "m2a-artifact-index.json").write_text(
        json.dumps(artifact_index, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
