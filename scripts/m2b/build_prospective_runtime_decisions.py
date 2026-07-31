#!/usr/bin/env python3
"""Bind held-out model outputs to isolated Isaac preflight gate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from xh_agent.policy.qrm_lite.physical_runtime_gates import (
    PhysicalRuntimeGateReceiptV1,
)
from xh_agent.policy.qrm_lite.prospective_mapping import (
    M2BProspectiveRuntimeDecisionV1,
)
from xh_agent.policy.qrm_lite.skill_registry import (
    RuntimeSkillMappingResultV1,
    RuntimeSkillRequestV1,
    RuntimeSkillRegistryV1,
    load_registry,
    validate_runtime_mapping,
)


class IsolatedIsaacPreflightManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["IsolatedIsaacPreflightManifestV1"] = (
        "IsolatedIsaacPreflightManifestV1"
    )
    sample_id: str
    failure_type: Literal[
        "EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"
    ]
    source_hashes: dict[str, str]
    preflight_evidence_path: str
    preflight_evidence_sha256: str
    receipt: PhysicalRuntimeGateReceiptV1
    isolated_from_evaluation_rollout: Literal[True] = True
    evaluation_execution_started: Literal[False] = False
    model_selection_triggered_preflight: Literal[True] = True
    privileged_truth_policy_input: Literal[False] = False
    teacher_used: Literal[False] = False


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _verify_hash(
    model_record: dict[str, Any],
    *,
    payload_key: str,
    hash_key: str,
) -> None:
    actual = canonical_sha256(model_record[payload_key])
    if actual != model_record.get(hash_key):
        raise ValueError(
            f"{model_record.get('sample_id')}: {hash_key} mismatch"
        )


def validate_model_record(
    model_record: dict[str, Any],
    *,
    registry: RuntimeSkillRegistryV1,
    registry_sha256: str,
) -> tuple[RuntimeSkillRequestV1, RuntimeSkillMappingResultV1]:
    """Verify held-out inference provenance before any physical preflight."""
    sample_id = str(model_record.get("sample_id"))
    for payload_key, hash_key in (
        ("model_input", "model_input_sha256"),
        ("model_output", "model_output_sha256"),
        ("request", "request_sha256"),
        ("mapping", "mapping_result_sha256"),
    ):
        _verify_hash(
            model_record,
            payload_key=payload_key,
            hash_key=hash_key,
        )
    if model_record.get("registry_sha256") != registry_sha256:
        raise ValueError(f"{sample_id}: runtime registry hash mismatch")
    if re.fullmatch(
        r"[0-9a-f]{64}",
        str(model_record.get("model_checkpoint_sha256", "")),
    ) is None:
        raise ValueError(f"{sample_id}: model checkpoint hash missing")
    request = RuntimeSkillRequestV1.model_validate(model_record["request"])
    structural = validate_runtime_mapping(request, registry)
    if structural.model_dump(mode="json") != model_record["mapping"]:
        raise ValueError(
            f"{sample_id}: structural mapping is not reproducible"
        )
    return request, structural


def build_records(
    model_records: list[dict[str, Any]],
    preflights: list[IsolatedIsaacPreflightManifestV1],
    *,
    registry_path: Path,
) -> list[M2BProspectiveRuntimeDecisionV1]:
    registry = load_registry(registry_path)
    registry_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    preflight_by_sample = {item.sample_id: item for item in preflights}
    if len(preflight_by_sample) != len(preflights):
        raise ValueError("duplicate preflight sample_id")
    records = []
    for model_record in model_records:
        sample_id = str(model_record["sample_id"])
        request, structural = validate_model_record(
            model_record,
            registry=registry,
            registry_sha256=registry_sha256,
        )
        structural_payload = structural.model_dump(mode="json")
        structural_sha256 = canonical_sha256(structural_payload)
        if structural_payload != model_record["mapping"]:
            raise ValueError(
                f"{sample_id}: structural mapping is not reproducible"
            )
        common = {
            "decision_id": f"prospective-{sample_id}",
            "sample_id": sample_id,
            "failure_type": model_record["failure_type"],
            "request": request,
            "registry_sha256": registry_sha256,
            "model_checkpoint_sha256": model_record[
                "model_checkpoint_sha256"
            ],
            "model_input_sha256": model_record["model_input_sha256"],
            "model_output_sha256": model_record["model_output_sha256"],
            "request_sha256": model_record["request_sha256"],
            "structural_mapping_result_sha256": structural_sha256,
        }
        if structural.status == "REJECTED":
            records.append(
                M2BProspectiveRuntimeDecisionV1(
                    **common,
                    mapping=structural,
                    mapping_result_sha256=structural_sha256,
                    ik_gate="NOT_RUN",
                    collision_gate="NOT_RUN",
                    safety_gate="NOT_RUN",
                    prospective_planning_check=False,
                    isolated_from_evaluation_rollout=False,
                    evaluation_execution_started=False,
                )
            )
            continue
        preflight = preflight_by_sample.get(sample_id)
        if preflight is None:
            raise ValueError(f"{sample_id}: isolated Isaac preflight missing")
        if preflight.failure_type != model_record["failure_type"]:
            raise ValueError(f"{sample_id}: preflight failure type mismatch")
        if preflight.receipt.failure_type != preflight.failure_type:
            raise ValueError(f"{sample_id}: receipt failure type mismatch")
        if preflight.receipt.runtime_action != structural.runtime_action:
            raise ValueError(f"{sample_id}: preflight runtime action mismatch")
        gates = {
            "ik": preflight.receipt.ik_gate,
            "collision": preflight.receipt.collision_gate,
            "safety": preflight.receipt.safety_gate,
        }
        if "NOT_RUN" in gates.values():
            raise ValueError(f"{sample_id}: preflight contains an unrun gate")

        def check(name: str):
            def result(
                _action: str, _parameters: dict[str, Any]
            ) -> tuple[bool, str | None]:
                status = gates[name]
                return (
                    status in {"PASS", "NOT_APPLICABLE"},
                    None if status == "PASS" else status,
                )

            return result

        mapping = validate_runtime_mapping(
            request,
            registry,
            ik_check=check("ik"),
            collision_check=check("collision"),
            safety_check=check("safety"),
        )
        mapping_payload = mapping.model_dump(mode="json")
        records.append(
            M2BProspectiveRuntimeDecisionV1(
                **common,
                mapping=mapping,
                mapping_result_sha256=canonical_sha256(mapping_payload),
                ik_gate=gates["ik"],
                collision_gate=gates["collision"],
                safety_gate=gates["safety"],
                source_hashes=preflight.source_hashes,
                isolated_preflight_evidence_path=(
                    preflight.preflight_evidence_path
                ),
                isolated_preflight_evidence_sha256=(
                    preflight.preflight_evidence_sha256
                ),
                prospective_planning_check=True,
                isolated_from_evaluation_rollout=True,
                evaluation_execution_started=False,
            )
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-records", required=True, type=Path)
    parser.add_argument("--preflight-manifest", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    model_records = [
        json.loads(line)
        for line in args.model_records.read_text().splitlines()
        if line.strip()
    ]
    preflights = [
        IsolatedIsaacPreflightManifestV1.model_validate_json(line)
        for line in args.preflight_manifest.read_text().splitlines()
        if line.strip()
    ]
    records = build_records(
        model_records,
        preflights,
        registry_path=args.registry,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(record.model_dump_json() + "\n" for record in records)
    )
    print(
        json.dumps(
            {
                "records": len(records),
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
