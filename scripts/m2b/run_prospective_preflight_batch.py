#!/usr/bin/env python3
"""Run model-triggered isolated Isaac preflights before evaluation execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from m2b.build_prospective_runtime_decisions import (
    IsolatedIsaacPreflightManifestV1,
    validate_model_record,
)
from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    PhysicalRuntimeGateReceiptV1,
    extract_physical_runtime_gate_receipt,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    RuntimeSkillRegistryV1,
    load_registry,
)


EXPECTED_FIRST_RECOVERY_SKILL = {
    "EMPTY_GRASP": "REOBSERVE",
    "WRONG_OBJECT": "SAFE_PLACE_NON_TARGET",
    "RELEASE_FAILURE": "RETRY_RELEASE",
}


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


def remote_json(host: str, path: str) -> dict[str, Any]:
    return json.loads(remote_bytes(host, path))


def scene_root_from_evidence(path: str, scene_seed: int) -> PurePosixPath:
    evidence = PurePosixPath(path)
    marker = f"scene-{scene_seed}"
    try:
        index = evidence.parts.index(marker)
    except ValueError as error:
        raise ValueError(
            f"evidence path does not contain {marker}: {path}"
        ) from error
    return PurePosixPath(*evidence.parts[: index + 1])


def remote_stage(host: str, scene_root: PurePosixPath) -> str:
    completed = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            host,
            "find",
            str(scene_root),
            "-path",
            "*/stage-attempt-*/m1b_physics_scene.usdc",
            "-type",
            "f",
            "-print",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    stages = sorted(line for line in completed.stdout.splitlines() if line)
    if completed.returncode != 0 or not stages:
        raise RuntimeError(f"no physical stage under {scene_root}")
    return stages[0]


def target_entities(
    payload: dict[str, Any], failure_type: str
) -> tuple[str, str]:
    attached = str(payload["attached_entity"])
    wrong = payload.get("m2b_wrong_object_injection") or {}
    task_target = str(wrong.get("task_target_entity_id") or attached)
    if failure_type == "WRONG_OBJECT":
        attached = str(wrong["attached_entity_id"])
    return attached, task_target


def validated_source_hashes(payload: dict[str, Any]) -> dict[str, str]:
    source_hashes = payload.get("source_hashes") or {}
    if not source_hashes or any(
        re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
        for digest in source_hashes.values()
    ):
        raise ValueError("physical evidence lacks hash-bound scene sources")
    return dict(source_hashes)


def verify_bytes_sha256(raw: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"{label} sha256 mismatch")


def preflight_command(
    *,
    project_root: str,
    source_root: str,
    stage: str,
    scene_seed: int,
    failure_type: str,
    gpu: int,
    output_root: str,
    injection_entity: str,
    task_target_entity: str,
    container_prefix: str,
) -> list[str]:
    return [
        "python3",
        f"{project_root}/scripts/m2b/run_physical_failure_smoke.py",
        "--project-root",
        project_root,
        "--source-root",
        source_root,
        "--stage",
        stage,
        "--sdf",
        f"{source_root}/scene-{scene_seed}.sdf",
        "--supervision",
        f"{source_root}/scene-{scene_seed}.supervision.json",
        "--output-root",
        output_root,
        "--gpu",
        str(gpu),
        "--target-object",
        injection_entity,
        "--public-target-object",
        injection_entity,
        "--wrong-object-task-target",
        task_target_entity,
        "--max-attempts",
        "1",
        "--settle-s",
        "10",
        "--capture-public-rgbd",
        "--release-follow-delta-z-m",
        "0.08",
        "--public-regrasp-offset-camera-xyz-m",
        "0,0,0",
        "--container-prefix",
        container_prefix,
        "--failures",
        failure_type,
    ]


def expected_first_runtime_action(
    registry: RuntimeSkillRegistryV1, failure_type: str
) -> str:
    skill = EXPECTED_FIRST_RECOVERY_SKILL[failure_type]
    return registry.skills[skill].runtime_action


def selected_action_is_physically_supported(
    registry: RuntimeSkillRegistryV1,
    failure_type: str,
    runtime_action: str,
) -> bool:
    return expected_first_runtime_action(registry, failure_type) == runtime_action


def validate_batch_inputs(
    model_records: list[dict[str, Any]],
    episodes: dict[str, dict[str, Any]],
    *,
    registry: RuntimeSkillRegistryV1,
    registry_sha256: str,
) -> None:
    """Fail closed on all local provenance before starting remote Isaac."""
    sample_ids = [str(item.get("sample_id")) for item in model_records]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("duplicate model sample_id")
    for model_record in model_records:
        sample_id = str(model_record["sample_id"])
        _, structural = validate_model_record(
            model_record,
            registry=registry,
            registry_sha256=registry_sha256,
        )
        episode_id = str(model_record["episode_id"])
        if episode_id not in episodes:
            raise ValueError(f"{sample_id}: dataset episode missing")
        episode = episodes[episode_id]
        failure_type = str(model_record["failure_type"])
        if failure_type not in EXPECTED_FIRST_RECOVERY_SKILL:
            raise ValueError(f"{sample_id}: unsupported failure type")
        if episode["failure_context"]["failure_type"] != failure_type:
            raise ValueError(f"{sample_id}: dataset failure type mismatch")
        observation = model_record["model_input"]["observation"]
        if str(observation["episode_id"]) != episode_id:
            raise ValueError(f"{sample_id}: model input episode mismatch")
        observed_failure = observation["failure_context"]["failure_type"]
        if observed_failure != failure_type:
            raise ValueError(f"{sample_id}: model input failure type mismatch")
        expected_sample_id = f"{episode_id}:coarse-recovery-0"
        if sample_id != expected_sample_id:
            raise ValueError(f"{sample_id}: unexpected held-out sample ID")
        if structural.model_dump(mode="json") != model_record["mapping"]:
            raise AssertionError("validated structural mapping changed")


def prepare_preflights(
    model_records: list[dict[str, Any]],
    episodes: dict[str, dict[str, Any]],
    *,
    host: str,
    source_root: str,
    gpu_filter: int | None,
    registry: RuntimeSkillRegistryV1,
) -> dict[str, dict[str, Any]]:
    """Read and hash-check every selected scene before executing any run."""
    prepared = {}
    for model_record in model_records:
        if model_record["mapping"]["status"] != "VALID":
            continue
        episode = episodes[str(model_record["episode_id"])]
        scene_seed = int(episode["scene_seed"])
        gpu = scene_seed % 2
        if gpu_filter is not None and gpu != gpu_filter:
            continue
        sample_id = str(model_record["sample_id"])
        evidence_path = str(episode["provenance"]["evidence_path"])
        evidence_bytes = remote_bytes(host, evidence_path)
        verify_bytes_sha256(
            evidence_bytes,
            str(episode["provenance"]["evidence_sha256"]),
            f"{sample_id}: source evidence",
        )
        payload = json.loads(evidence_bytes)
        source_hashes = validated_source_hashes(payload)
        failure_type = str(model_record["failure_type"])
        item = {
            "episode": episode,
            "scene_seed": scene_seed,
            "gpu": gpu,
            "payload": payload,
            "source_hashes": source_hashes,
            "stage": None,
        }
        runtime_action = str(model_record["mapping"]["runtime_action"])
        if selected_action_is_physically_supported(
            registry, failure_type, runtime_action
        ):
            scene_root = scene_root_from_evidence(
                evidence_path, scene_seed
            )
            stage = remote_stage(host, scene_root)
            required_sources = {
                "m1b_physics_scene.usdc": stage,
                f"scene-{scene_seed}.sdf": (
                    f"{source_root}/scene-{scene_seed}.sdf"
                ),
                f"scene-{scene_seed}.supervision.json": (
                    f"{source_root}/scene-{scene_seed}.supervision.json"
                ),
            }
            for name, path in required_sources.items():
                if name not in source_hashes:
                    raise ValueError(f"{sample_id}: {name} hash missing")
                verify_bytes_sha256(
                    remote_bytes(host, path),
                    source_hashes[name],
                    f"{sample_id}: {name}",
                )
            item["stage"] = stage
        prepared[sample_id] = item
    return prepared


def dispatch_rejection_manifest(
    *,
    model_record: dict[str, Any],
    source_hashes: dict[str, str],
    evidence_root: Path,
    supported_runtime_action: str,
) -> IsolatedIsaacPreflightManifestV1:
    sample_id = str(model_record["sample_id"])
    failure_type = str(model_record["failure_type"])
    runtime_action = str(model_record["mapping"]["runtime_action"])
    expected = supported_runtime_action
    evidence = {
        "schema_version": "M2BFailureStateActionDispatchRejectionV1",
        "sample_id": sample_id,
        "failure_type": failure_type,
        "selected_runtime_action": runtime_action,
        "supported_first_runtime_action": expected,
        "status": "SAFETY_REJECTED_BEFORE_EXECUTION",
        "source_hashes": source_hashes,
        "model_output_sha256": model_record["model_output_sha256"],
        "evaluation_execution_started": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    evidence_root.mkdir(parents=True, exist_ok=True)
    path = evidence_root / f"{hashlib.sha256(sample_id.encode()).hexdigest()}.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    receipt = PhysicalRuntimeGateReceiptV1(
        failure_type=failure_type,
        recovery_skill=str(model_record["request"]["skill"]),
        runtime_action=runtime_action,
        ik_gate="NOT_APPLICABLE",
        collision_gate="NOT_APPLICABLE",
        safety_gate="REJECTED",
        physical_recovery_success=False,
        details={
            "source": "DECLARED_FAILURE_STATE_ACTION_COMPATIBILITY_GATE",
            "supported_first_runtime_action": expected,
            "evaluation_execution_started": False,
        },
    )
    return IsolatedIsaacPreflightManifestV1(
        sample_id=sample_id,
        failure_type=failure_type,
        source_hashes=source_hashes,
        preflight_evidence_path=str(path.resolve()),
        preflight_evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        receipt=receipt,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-records", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--registry",
        default=Path("configs/qrm_runtime_mapping.yaml"),
        type=Path,
    )
    parser.add_argument("--host", default="root@labserver")
    parser.add_argument(
        "--project-root",
        default="/var/tmp/m2a-isaac-project-20260731",
    )
    parser.add_argument(
        "--source-root",
        default="/var/tmp/m2b-heldout-source-copy-20260731",
    )
    parser.add_argument(
        "--remote-output-root",
        default=(
            "/var/tmp/xh-data/isaac-industrial/m2b/"
            "prospective-runtime-preflight-v1"
        ),
    )
    parser.add_argument("--gpu", type=int, choices=(0, 1), default=None)
    parser.add_argument("--local-evidence-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    model_records = [
        json.loads(line)
        for line in args.model_records.read_text().splitlines()
        if line.strip()
    ]
    episode_rows = [
        json.loads(line)
        for line in args.dataset.read_text().splitlines()
        if line.strip()
    ]
    episodes = {episode["episode_id"]: episode for episode in episode_rows}
    if len(episodes) != len(episode_rows):
        raise ValueError("duplicate dataset episode_id")
    registry = load_registry(args.registry)
    registry_sha256 = hashlib.sha256(args.registry.read_bytes()).hexdigest()
    validate_batch_inputs(
        model_records,
        episodes,
        registry=registry,
        registry_sha256=registry_sha256,
    )
    prepared = prepare_preflights(
        model_records,
        episodes,
        host=args.host,
        source_root=args.source_root,
        gpu_filter=args.gpu,
        registry=registry,
    )
    manifests = []
    run_records = []
    for model_record in model_records:
        if model_record["mapping"]["status"] != "VALID":
            continue
        prepared_item = prepared.get(str(model_record["sample_id"]))
        if prepared_item is None:
            continue
        scene_seed = prepared_item["scene_seed"]
        gpu = prepared_item["gpu"]
        if args.gpu is not None and gpu != args.gpu:
            continue
        failure_type = str(model_record["failure_type"])
        original_payload = prepared_item["payload"]
        source_hashes = prepared_item["source_hashes"]
        runtime_action = str(model_record["mapping"]["runtime_action"])
        supported_runtime_action = expected_first_runtime_action(
            registry, failure_type
        )
        if not selected_action_is_physically_supported(
            registry, failure_type, runtime_action
        ):
            manifests.append(
                dispatch_rejection_manifest(
                    model_record=model_record,
                    source_hashes=source_hashes,
                    evidence_root=args.local_evidence_root,
                    supported_runtime_action=supported_runtime_action,
                )
            )
            run_records.append(
                {
                    "sample_id": model_record["sample_id"],
                    "status": "SAFETY_REJECTED_BEFORE_EXECUTION",
                    "runtime_action": runtime_action,
                }
            )
            continue
        stage = prepared_item["stage"]
        if not stage:
            raise AssertionError("supported action lacks a prepared stage")
        injection_entity, task_target_entity = target_entities(
            original_payload, failure_type
        )
        safe_sample = hashlib.sha256(
            str(model_record["sample_id"]).encode()
        ).hexdigest()[:16]
        remote_output = (
            f"{args.remote_output_root}/gpu{gpu}/{safe_sample}"
        )
        command = preflight_command(
            project_root=args.project_root,
            source_root=args.source_root,
            stage=stage,
            scene_seed=scene_seed,
            failure_type=failure_type,
            gpu=gpu,
            output_root=remote_output,
            injection_entity=injection_entity,
            task_target_entity=task_target_entity,
            container_prefix=f"m2b-preflight-g{gpu}-{safe_sample}",
        )
        completed = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                args.host,
                shlex.join(command),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        summary_path = f"{remote_output}/physical-failure-smoke.json"
        summary = remote_json(args.host, summary_path)
        evidence_paths = [
            str(item["evidence"])
            for item in summary.get("attempts", [])
            if item.get("evidence")
        ]
        if not evidence_paths:
            raise RuntimeError(
                f"{model_record['sample_id']}: preflight evidence missing"
            )
        evidence_path = evidence_paths[-1]
        evidence_bytes = remote_bytes(args.host, evidence_path)
        preflight_payload = json.loads(evidence_bytes)
        preflight_source_hashes = preflight_payload.get("source_hashes") or {}
        if preflight_source_hashes != source_hashes:
            raise ValueError(
                f"{model_record['sample_id']}: preflight scene sources changed"
            )
        receipt = extract_physical_runtime_gate_receipt(
            preflight_payload,
            failure_type=failure_type,
        )
        if receipt.runtime_action != runtime_action:
            raise ValueError(
                f"{model_record['sample_id']}: wrong action preflighted"
            )
        manifests.append(
            IsolatedIsaacPreflightManifestV1(
                sample_id=model_record["sample_id"],
                failure_type=failure_type,
                source_hashes=preflight_source_hashes,
                preflight_evidence_path=evidence_path,
                preflight_evidence_sha256=hashlib.sha256(
                    evidence_bytes
                ).hexdigest(),
                receipt=receipt,
            )
        )
        run_records.append(
            {
                "sample_id": model_record["sample_id"],
                "status": "ISOLATED_PREFLIGHT_COMPLETE",
                "runtime_action": runtime_action,
                "runner_returncode": completed.returncode,
                "summary_path": summary_path,
                "evidence_path": evidence_path,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(item.model_dump_json() + "\n" for item in manifests)
    )
    report = {
        "schema_version": "M2BProspectivePreflightBatchReportV1",
        "records": len(manifests),
        "gpu_filter": args.gpu,
        "runs": run_records,
        "output": str(args.output),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "evaluation_execution_started": False,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
