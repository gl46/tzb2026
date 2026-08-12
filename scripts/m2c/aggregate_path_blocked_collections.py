#!/usr/bin/env python3
"""Fail-closed aggregation of S4 PATH_BLOCKED collection bundles.

The per-key packager deliberately makes every bundle self contained.  This
tool is the only place where those chains are combined for Qwen ingestion.  It
does not modify a physical chain: it validates each source bundle first, then
projects only the training sample RGB/depth URI names into an aggregate-local
namespace so independently collected episodes cannot collide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping

from m2c.package_path_blocked_collection import (
    FROZEN_RUNTIME_REGISTRY_SHA256,
    FROZEN_S6_KEYS_FILE_SHA256,
    FROZEN_TRAINING_KEYS_FILE_SHA256,
    project_frozen_manifests,
    sha256_file,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    M2CPathBlockedPhysicalChainEvidenceV2,
    M2CPathBlockedSupervisedStepV2,
    PathBlockedEvidenceValidationV2,
    PathBlockedSupervisedDatasetV2,
    build_path_blocked_supervised_dataset,
    canonical_manifest_sha256,
)


EXPECTED_STEPS = 8
RECEIPT_NAME = "collection-receipt-v2.json"
PACKAGED_NAME = "packaged-physical-chain-v2.json"
DATASET_NAME = "supervised-steps-v2.json"
COLLECTION_MANIFEST_NAME = "collection-manifest-v2.json"
S6_MANIFEST_NAME = "s6-exclusion-manifest-v2.json"


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _require_file(path: Path, *, label: str) -> Path:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def _dataset_relative(uri: str, *, label: str) -> Path:
    if not isinstance(uri, str) or not uri.startswith("dataset://"):
        raise ValueError(f"{label} must use a dataset:// URI")
    text = uri.removeprefix("dataset://")
    relative = Path(text)
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(f"{label} URI escapes its bundle")
    return relative


def _write_json_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_jsonl_new(path: Path, samples: Iterable[M2CPathBlockedSupervisedStepV2]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for sample in samples:
            stream.write(sample.model_dump_json(by_alias=False, exclude_none=False))
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _false_only(value: object, *, label: str) -> None:
    if value is not False:
        raise ValueError(f"{label} permits Teacher or privileged truth")


def _key_hash(matched_key: str) -> str:
    return hashlib.sha256(matched_key.encode("utf-8")).hexdigest()


def _check_source_layout(bundles_root: Path, *, include_smoke: bool) -> None:
    if not bundles_root.is_dir() or bundles_root.is_symlink():
        raise ValueError(f"bundle root must be a regular directory: {bundles_root}")
    allowed = {"train"} | ({"smoke"} if include_smoke else set())
    names = {item.name for item in bundles_root.iterdir()}
    unexpected = sorted(names - allowed)
    if unexpected:
        raise ValueError(f"bundle root has unexpected entries: {unexpected}")
    missing = sorted(allowed - names)
    if missing:
        raise ValueError(f"bundle root is missing role directories: {missing}")
    if not include_smoke and (bundles_root / "smoke").exists():
        raise ValueError("SMOKE bundles require --include-smoke")


def _source_records(
    training: Mapping[str, Any], *, include_smoke: bool
) -> list[tuple[str, dict[str, Any]]]:
    groups = [("TRAIN", training.get("training_keys"))]
    if include_smoke:
        groups.append(("SMOKE", training.get("physical_prerequisite_smoke_keys")))
    result: list[tuple[str, dict[str, Any]]] = []
    for role, records in groups:
        if not isinstance(records, list):
            raise ValueError(f"frozen {role} records are not a list")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"frozen {role} record is not an object")
            result.append((role, record))
    expected_train = sum(role == "TRAIN" for role, _ in result)
    expected_smoke = sum(role == "SMOKE" for role, _ in result)
    if expected_train != 36 or (include_smoke and expected_smoke != 3):
        raise ValueError("frozen S4 coverage is not exactly 36 TRAIN and optional 3 SMOKE")
    keys = [str(record.get("matched_key")) for _, record in result]
    if len(keys) != len(set(keys)):
        raise ValueError("frozen S4 aggregation keys are duplicated")
    return result


def _assert_no_teacher_or_truth(payload: object, *, label: str) -> None:
    """Fail closed even if an unmodelled proof field is added to a bundle."""

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if ("teacher" in normalized_key or "truth" in normalized_key) and value is not False:
                raise ValueError(f"{label} contains forbidden {key}")
            _assert_no_teacher_or_truth(value, label=label)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_teacher_or_truth(value, label=label)


def _verify_bundle(
    bundle: Path,
    *,
    role: str,
    source: Mapping[str, Any],
    collection_manifest: object,
    s6_manifest: object,
    frozen_hashes: Mapping[str, str],
) -> tuple[
    M2CPathBlockedPhysicalChainEvidenceV2,
    list[M2CPathBlockedSupervisedStepV2],
    PathBlockedEvidenceValidationV2,
    dict[str, Any],
    list[dict[str, str]],
]:
    """Return independently revalidated chain, samples, receipt and assets."""

    if not bundle.is_dir() or bundle.is_symlink():
        raise ValueError(f"collection bundle must be a regular directory: {bundle}")
    required = {
        RECEIPT_NAME,
        PACKAGED_NAME,
        DATASET_NAME,
        COLLECTION_MANIFEST_NAME,
        S6_MANIFEST_NAME,
        "actuation-probe.json",
    }
    names = {item.name for item in bundle.iterdir()}
    if not required.issubset(names):
        raise ValueError(f"collection bundle misses required files: {bundle}")
    for name in required:
        _require_file(bundle / name, label=f"bundle {name}")

    receipt = _load_object(bundle / RECEIPT_NAME, label="collection receipt")
    _assert_no_teacher_or_truth(receipt, label="collection receipt")
    expected = {
        "status": "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
        "matched_key": source["matched_key"],
        "scene_seed": source["scene_seed"],
        "failure_seed": source["failure_seed"],
        "split": source["split"],
        "collection_role": role,
        "physical_chain_steps": EXPECTED_STEPS,
        "physical_receipts": EXPECTED_STEPS,
        "fresh_public_rgbd_observations": EXPECTED_STEPS,
        "decision_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
        "model_owned": False,
        "model_rollout": False,
        "training_executed": False,
        "evaluation_executed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "checkpoint_path": None,
        "checkpoint_sha256": None,
        "sdf_sha256": source["sdf_sha256"],
        "supervision_sha256": source["supervision_sha256"],
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValueError(f"collection receipt {field} mismatch for {source['matched_key']}")
    for field, digest in frozen_hashes.items():
        if receipt.get(field) != digest:
            raise ValueError(f"collection receipt frozen hash mismatch: {field}")
    for name, receipt_field in (
        ("actuation-probe.json", "raw_probe_sha256"),
        (PACKAGED_NAME, "packaged_physical_chain_sha256"),
        (DATASET_NAME, "supervised_dataset_file_sha256"),
    ):
        if receipt.get(receipt_field) != sha256_file(bundle / name):
            raise ValueError(f"collection receipt {receipt_field} mismatch")

    stored_collection = _load_object(
        bundle / COLLECTION_MANIFEST_NAME, label="bundle collection manifest"
    )
    stored_s6 = _load_object(bundle / S6_MANIFEST_NAME, label="bundle S6 manifest")
    if stored_collection != collection_manifest.model_dump(mode="json"):
        raise ValueError("bundle collection manifest differs from frozen S4 manifest")
    if stored_s6 != s6_manifest.model_dump(mode="json"):
        raise ValueError("bundle S6 manifest differs from frozen exclusion manifest")
    if receipt.get("collection_manifest_sha256") != canonical_manifest_sha256(collection_manifest):
        raise ValueError("collection receipt S4 manifest hash mismatch")
    if receipt.get("s6_exclusion_manifest_sha256") != canonical_manifest_sha256(s6_manifest):
        raise ValueError("collection receipt S6 manifest hash mismatch")

    chain_payload = _load_object(bundle / PACKAGED_NAME, label="packaged physical chain")
    _assert_no_teacher_or_truth(chain_payload, label="packaged physical chain")
    try:
        chain = M2CPathBlockedPhysicalChainEvidenceV2.model_validate(chain_payload)
    except Exception as error:
        raise ValueError("packaged physical chain is invalid") from error
    if chain.source_evidence_sha256 != sha256_file(bundle / "actuation-probe.json"):
        raise ValueError("packaged physical chain source evidence hash mismatch")
    if chain.source_evidence_uri != "dataset://actuation-probe.json":
        raise ValueError("packaged physical chain source evidence URI changed")
    rebuilt = build_path_blocked_supervised_dataset(
        [chain], collection_manifest=collection_manifest, s6_manifest=s6_manifest
    )
    if rebuilt.status != "PASS" or len(rebuilt.samples) != EXPECTED_STEPS:
        raise ValueError("packaged physical chain does not rebuild as a complete bundle")
    stored_dataset_payload = _load_object(bundle / DATASET_NAME, label="bundle supervised dataset")
    try:
        stored_dataset = PathBlockedSupervisedDatasetV2.model_validate(stored_dataset_payload)
    except Exception as error:
        raise ValueError("bundle supervised dataset is invalid") from error
    if stored_dataset.model_dump(mode="json") != rebuilt.model_dump(mode="json"):
        raise ValueError("bundle supervised dataset does not match packaged chain")
    if chain.collection_role != role or chain.matched_key != source["matched_key"]:
        raise ValueError("packaged physical chain role/key mismatch")
    if chain.scene_seed != source["scene_seed"] or chain.failure_seed != source["failure_seed"]:
        raise ValueError("packaged physical chain seed mismatch")
    if (
        chain.sdf_sha256 != source["sdf_sha256"]
        or chain.supervision_sha256 != source["supervision_sha256"]
    ):
        raise ValueError("packaged physical chain frozen scene hash mismatch")
    if role == "TRAIN" and not all(item.model_training_eligible for item in rebuilt.samples):
        raise ValueError("TRAIN bundle has ineligible samples")
    if role == "SMOKE" and any(item.model_training_eligible for item in rebuilt.samples):
        raise ValueError("SMOKE bundle must never be training eligible")

    copied_assets = receipt.get("copied_public_assets")
    receipt_files = receipt.get("physical_receipt_files")
    if not isinstance(copied_assets, dict) or not isinstance(receipt_files, dict):
        raise ValueError("collection receipt has no asset/physical-receipt inventory")
    assets: list[dict[str, str]] = []
    seen_asset_pairs: set[str] = set()
    for step in chain.steps:
        for kind, uri, expected_sha in (
            ("rgb", step.observation.rgb_uri, step.observation.rgb_sha256),
            ("depth", step.observation.depth_uri, step.observation.depth_sha256),
        ):
            key = f"{step.decision_index}:{kind}"
            if key in seen_asset_pairs or copied_assets.get(key) != expected_sha:
                raise ValueError("collection receipt public asset inventory mismatch")
            seen_asset_pairs.add(key)
            seen_asset_pairs.add(key)
            relative = _dataset_relative(uri, label=f"{kind} asset")
            asset = _require_file(bundle / relative, label=f"{kind} asset")
            if sha256_file(asset) != expected_sha:
                raise ValueError(f"{kind} asset SHA-256 mismatch")
            assets.append({"kind": kind, "source_uri": uri, "source_sha256": expected_sha})
        physical = step.physical_receipts[0]
        receipt_entry = receipt_files.get(str(step.decision_index))
        if not isinstance(receipt_entry, dict):
            raise ValueError("collection receipt physical-receipt inventory mismatch")
        relative = _dataset_relative(physical.receipt_uri, label="physical receipt")
        receipt_file = _require_file(bundle / relative, label="physical receipt")
        if receipt_entry.get("path") != str(relative) or receipt_entry.get(
            "file_sha256"
        ) != sha256_file(receipt_file):
            raise ValueError("physical receipt file hash mismatch")
        if receipt_entry.get("canonical_receipt_sha256") != physical.receipt_sha256:
            raise ValueError("physical receipt canonical hash mismatch")
        if _load_object(receipt_file, label="physical receipt") != physical.model_dump(mode="json"):
            raise ValueError("physical receipt content differs from packaged chain")
    if set(copied_assets) != {
        f"{step.decision_index}:{kind}" for step in chain.steps for kind in ("rgb", "depth")
    }:
        raise ValueError("collection receipt has missing or extra public assets")
    if set(receipt_files) != {str(step.decision_index) for step in chain.steps}:
        raise ValueError("collection receipt has missing or extra physical receipts")
    return chain, rebuilt.samples, rebuilt.episode_validations[0], receipt, assets


def _copy_asset_create_only(source: Path, destination: Path) -> str:
    if destination.exists():
        raise ValueError(f"asset projection collision: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep the aggregate immutable from later in-place writes to a source
    # collection bundle.  A hard link would make two independently hash-bound
    # evidence roots share the same inode.
    shutil.copyfile(source, destination)
    actual = sha256_file(destination)
    if actual != sha256_file(source):
        raise ValueError("projected public asset SHA-256 mismatch")
    return actual


def aggregate_collections(
    *,
    bundles_root: Path,
    output_root: Path,
    include_smoke: bool = False,
    training_keys_path: Path,
    s6_keys_path: Path,
    runtime_registry_path: Path,
) -> dict[str, Any]:
    """Validate exact S4 coverage and atomically create a Qwen-ready JSONL root."""

    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite aggregate collection: {output_root}")
    _check_source_layout(bundles_root, include_smoke=include_smoke)
    training, _s6, collection_manifest, s6_manifest = project_frozen_manifests(
        training_keys_path, s6_keys_path, runtime_registry_path
    )
    records = _source_records(training, include_smoke=include_smoke)
    frozen_hashes = {
        "frozen_training_key_manifest_file_sha256": FROZEN_TRAINING_KEYS_FILE_SHA256,
        "frozen_s6_key_manifest_file_sha256": FROZEN_S6_KEYS_FILE_SHA256,
        "runtime_registry_sha256": FROZEN_RUNTIME_REGISTRY_SHA256,
    }
    expected_paths = {
        ("train" if role == "TRAIN" else "smoke", str(record["matched_key"]))
        for role, record in records
    }
    actual_paths = {
        (role_dir.name, item.name)
        for role_dir in bundles_root.iterdir()
        for item in role_dir.iterdir()
    }
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        raise ValueError(f"bundle coverage must be exact; missing={missing}, extra={extra}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_root.name}.", dir=output_root.parent
    ) as temporary_text:
        staging = Path(temporary_text)
        aggregate_samples: list[M2CPathBlockedSupervisedStepV2] = []
        projection_entries: list[dict[str, str]] = []
        bundle_entries: list[dict[str, Any]] = []
        validations: list[PathBlockedEvidenceValidationV2] = []
        seen_projected_uris: set[str] = set()
        for role, source in records:
            matched_key = str(source["matched_key"])
            bundle = bundles_root / role.lower() / matched_key
            chain, samples, validation, receipt, assets = _verify_bundle(
                bundle,
                role=role,
                source=source,
                collection_manifest=collection_manifest,
                s6_manifest=s6_manifest,
                frozen_hashes=frozen_hashes,
            )
            key_hash = _key_hash(matched_key)
            projected_by_source: dict[str, str] = {}
            for asset in assets:
                source_uri = asset["source_uri"]
                projected_uri = projected_by_source.get(source_uri)
                if projected_uri is None:
                    projected_relative = (
                        Path("episodes")
                        / key_hash
                        / _dataset_relative(source_uri, label="source asset")
                    )
                    projected_uri = "dataset://" + projected_relative.as_posix()
                    if projected_uri in seen_projected_uris:
                        raise ValueError("aggregate projected asset URI collision")
                    source_path = bundle / _dataset_relative(source_uri, label="source asset")
                    projected_sha = _copy_asset_create_only(
                        source_path, staging / projected_relative
                    )
                    if projected_sha != asset["source_sha256"]:
                        raise ValueError("aggregate projection changed a public asset")
                    seen_projected_uris.add(projected_uri)
                    projected_by_source[source_uri] = projected_uri
                    projection_entries.append(
                        {
                            "matched_key": matched_key,
                            "matched_key_sha256": key_hash,
                            "collection_role": role,
                            "source_bundle": str(bundle.relative_to(bundles_root)),
                            "source_uri": source_uri,
                            "projected_uri": projected_uri,
                            "source_asset_sha256": asset["source_sha256"],
                            "projected_asset_sha256": projected_sha,
                            "source_physical_evidence_sha256": chain.source_evidence_sha256,
                            "source_collection_receipt_sha256": sha256_file(bundle / RECEIPT_NAME),
                        }
                    )
            for sample in samples:
                observation = sample.observation.model_copy(
                    update={
                        "rgb_uri": projected_by_source[sample.observation.rgb_uri],
                        "depth_uri": projected_by_source[sample.observation.depth_uri],
                    }
                )
                aggregate_samples.append(sample.model_copy(update={"observation": observation}))
            validations.append(validation)
            bundle_entries.append(
                {
                    "matched_key": matched_key,
                    "collection_role": role,
                    "source_bundle": str(bundle.relative_to(bundles_root)),
                    "source_collection_receipt_sha256": sha256_file(bundle / RECEIPT_NAME),
                    "source_physical_evidence_sha256": chain.source_evidence_sha256,
                    "source_packaged_chain_sha256": sha256_file(bundle / PACKAGED_NAME),
                    "source_supervised_dataset_sha256": sha256_file(bundle / DATASET_NAME),
                }
            )
        aggregate_samples.sort(key=lambda sample: (sample.episode_id, sample.decision_index))
        aggregate_uris = [
            uri
            for sample in aggregate_samples
            for uri in (sample.observation.rgb_uri, sample.observation.depth_uri)
        ]
        if len(aggregate_uris) != len(set(aggregate_uris)):
            raise ValueError("aggregate training sample RGB-D URIs are not unique")
        dataset = PathBlockedSupervisedDatasetV2(
            status="PASS",
            samples=aggregate_samples,
            episode_validations=validations,
            dataset_sha256=hashlib.sha256(
                "".join(
                    sample.model_dump_json(by_alias=False, exclude_none=False) + "\n"
                    for sample in aggregate_samples
                ).encode()
            ).hexdigest(),
            episodes_received=len(records),
            episodes_physical_valid=len(records),
            episodes_training_eligible=sum(role == "TRAIN" for role, _ in records),
            samples_training_eligible=sum(
                sample.model_training_eligible for sample in aggregate_samples
            ),
            exclusion_reasons=[],
        )
        _write_jsonl_new(staging / "dataset.jsonl", aggregate_samples)
        _write_json_new(staging / "dataset-manifest.json", dataset.model_dump(mode="json"))
        projection_manifest = {
            "schema_version": "M2CPathBlockedAssetProjectionManifestV1",
            "projection_scope": "TRAINING_SAMPLE_RGB_DEPTH_URIS_ONLY",
            "source_physical_chain_modified": False,
            "asset_count": len(projection_entries),
            "assets": projection_entries,
        }
        _write_json_new(staging / "asset-projection-manifest-v1.json", projection_manifest)
        projection_receipt = {
            "schema_version": "M2CPathBlockedAssetProjectionReceiptV1",
            "status": "PASS_URI_NAMESPACE_PROJECTION",
            "source_physical_chain_modified": False,
            "projection_manifest_sha256": sha256_file(
                staging / "asset-projection-manifest-v1.json"
            ),
            "projection_entries": len(projection_entries),
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        _write_json_new(staging / "asset-projection-receipt-v1.json", projection_receipt)
        receipt = {
            "schema_version": "M2CPathBlockedCollectionAggregationReceiptV1",
            "status": "PASS",
            "source_bundle_count": len(bundle_entries),
            "train_bundle_count": sum(role == "TRAIN" for role, _ in records),
            "smoke_bundle_count": sum(role == "SMOKE" for role, _ in records),
            "eligible_train_steps": sum(
                sample.model_training_eligible for sample in aggregate_samples
            ),
            "ineligible_smoke_steps": sum(
                not sample.model_training_eligible for sample in aggregate_samples
            ),
            "dataset_jsonl_sha256": sha256_file(staging / "dataset.jsonl"),
            "dataset_manifest_sha256": sha256_file(staging / "dataset-manifest.json"),
            "asset_projection_manifest_sha256": sha256_file(
                staging / "asset-projection-manifest-v1.json"
            ),
            "asset_projection_receipt_sha256": sha256_file(
                staging / "asset-projection-receipt-v1.json"
            ),
            "frozen_training_key_manifest_file_sha256": FROZEN_TRAINING_KEYS_FILE_SHA256,
            "frozen_s6_key_manifest_file_sha256": FROZEN_S6_KEYS_FILE_SHA256,
            "runtime_registry_sha256": FROZEN_RUNTIME_REGISTRY_SHA256,
            "source_physical_chains_modified": False,
            "bundles": bundle_entries,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        _write_json_new(staging / "aggregation-receipt-v1.json", receipt)
        if output_root.exists():
            raise FileExistsError(f"refusing to overwrite aggregate collection: {output_root}")
        staging.replace(output_root)
    return {**receipt, "output": str(output_root)}


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundles-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--include-smoke", action="store_true")
    parser.add_argument(
        "--training-keys", type=Path, default=project / "configs/m2c_s4_training_keys.json"
    )
    parser.add_argument(
        "--s6-keys", type=Path, default=project / "configs/m2c_s6_evaluation_keys.json"
    )
    parser.add_argument(
        "--runtime-registry", type=Path, default=project / "configs/qrm_runtime_mapping_v2.yaml"
    )
    args = parser.parse_args()
    print(json.dumps(aggregate_collections(**vars(args)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
