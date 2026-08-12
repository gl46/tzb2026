from __future__ import annotations

import json
from pathlib import Path

import pytest

from m2c.aggregate_path_blocked_collections import aggregate_collections, canonical_sha256
from m2c.package_path_blocked_collection import package_collection
from m2c.qwen_coarse_v2 import load_training_dataset

# Reuse the established strict physical-chain fixture rather than making a
# weaker aggregate-only schema fixture.
from test_m2c_path_blocked_collection_tools import (  # type: ignore[import-not-found]
    ROOT,
    UPSTREAM,
    _write_physical_probe_fixture,
)


def _retarget_fixture(
    tmp_path: Path,
    *,
    role: str,
    record: dict,
) -> tuple[Path, Path, Path]:
    evidence_root, probe, derived, _old, _source_sha = _write_physical_probe_fixture(
        tmp_path, role=role
    )
    payload = json.loads(probe.read_text())
    chain = payload["m2c_path_blocked_physical_chain"]
    chain.update(
        {
            "episode_id": f"aggregate-fixture-{record['matched_key']}",
            "scene_seed": record["scene_seed"],
            "failure_seed": record["failure_seed"],
            "split": record["split"],
            "split_group": f"scene-{record['scene_seed']}",
            "matched_key": record["matched_key"],
            "collection_role": role,
            "collection_key": f"{record['matched_key']}-collection",
            "sdf_sha256": record["sdf_sha256"],
            "supervision_sha256": record["supervision_sha256"],
        }
    )
    for index, step in enumerate(chain["steps"]):
        observation = step["observation"]
        observation["observation_id"] = f"{record['matched_key']}-observation-{index}"
        receipt = step["physical_receipts"][0]
        receipt["receipt_id"] = f"{record['matched_key']}-receipt-{index}"
        core = dict(receipt)
        core.pop("receipt_sha256")
        receipt["receipt_sha256"] = canonical_sha256(core)
    probe.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return evidence_root, probe, derived


def _bundles(tmp_path: Path) -> Path:
    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    bundles = tmp_path / "bundles"
    for role, field in (
        ("TRAIN", "training_keys"),
        ("SMOKE", "physical_prerequisite_smoke_keys"),
    ):
        for index, record in enumerate(training[field]):
            evidence, probe, derived = _retarget_fixture(
                tmp_path / role.lower() / str(index), role=role, record=record
            )
            package_collection(
                raw_probe_path=probe,
                evidence_root=evidence,
                output_root=bundles,
                role=role,
                matched_key=record["matched_key"],
                training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
                s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
                runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
                derived_probe_path=derived,
                upstream_v4_probe_path=UPSTREAM,
            )
    return bundles


def _aggregate(tmp_path: Path) -> tuple[Path, dict]:
    bundles = _bundles(tmp_path)
    output = tmp_path / "aggregate"
    result = aggregate_collections(
        bundles_root=bundles,
        output_root=output,
        include_smoke=True,
        training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
        s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
        runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
    )
    return output, result


def test_aggregate_exactly_covers_36_train_and_3_smoke_with_resolvable_uris(
    tmp_path: Path,
) -> None:
    output, result = _aggregate(tmp_path)
    rows = [json.loads(line) for line in (output / "dataset.jsonl").read_text().splitlines()]
    manifest = json.loads((output / "dataset-manifest.json").read_text())
    projection = json.loads((output / "asset-projection-manifest-v1.json").read_text())

    assert result["train_bundle_count"] == 36
    assert result["smoke_bundle_count"] == 3
    assert result["eligible_train_steps"] == 288
    assert result["ineligible_smoke_steps"] == 24
    assert len(rows) == 312
    assert manifest["samples_training_eligible"] == 288
    assert sum(row["model_training_eligible"] for row in rows) == 288
    assert sum(not row["model_training_eligible"] for row in rows) == 24
    assert all(
        row["exclusion_reasons"] == ["COLLECTION_ROLE_SMOKE_NOT_TRAINING"]
        for row in rows
        if not row["model_training_eligible"]
    )
    uris = [
        uri
        for row in rows
        for uri in (row["observation"]["rgb_uri"], row["observation"]["depth_uri"])
    ]
    assert len(uris) == len(set(uris))
    assert all(uri.startswith("dataset://episodes/") for uri in uris)
    assert all((output / uri.removeprefix("dataset://")).is_file() for uri in uris)
    first_projection = projection["assets"][0]
    source_asset = (
        tmp_path
        / "bundles"
        / first_projection["source_bundle"]
        / first_projection["source_uri"].removeprefix("dataset://")
    )
    projected_asset = output / first_projection["projected_uri"].removeprefix("dataset://")
    assert source_asset.stat().st_ino != projected_asset.stat().st_ino
    assert projection["source_physical_chain_modified"] is False
    assert len(projection["assets"]) == 624
    assert all(
        item["source_asset_sha256"] == item["projected_asset_sha256"]
        and len(item["source_physical_evidence_sha256"]) == 64
        and len(item["source_collection_receipt_sha256"]) == 64
        for item in projection["assets"]
    )
    loaded, report = load_training_dataset(
        output / "dataset.jsonl",
        dataset_manifest_path=output / "dataset-manifest.json",
        training_manifest_path=ROOT / "configs/m2c_s4_training_keys.json",
        evaluation_manifest_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
    )
    assert len(loaded) == 288
    assert report.rows_eligible == 288
    assert report.rows_excluded == 24


def test_aggregate_rejects_missing_duplicate_tampered_and_existing_output(tmp_path: Path) -> None:
    bundles = _bundles(tmp_path)
    training = json.loads((ROOT / "configs/m2c_s4_training_keys.json").read_text())
    missing_key = training["training_keys"][0]["matched_key"]
    (bundles / "train" / missing_key).rename(bundles / "train" / "missing")
    with pytest.raises(ValueError, match="coverage must be exact"):
        aggregate_collections(
            bundles_root=bundles,
            output_root=tmp_path / "missing",
            include_smoke=True,
            training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        )
    (bundles / "train" / "missing").rename(bundles / "train" / missing_key)

    duplicate = bundles / "train" / "duplicate"
    duplicate.mkdir()
    with pytest.raises(ValueError, match="coverage must be exact"):
        aggregate_collections(
            bundles_root=bundles,
            output_root=tmp_path / "duplicate",
            include_smoke=True,
            training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        )
    duplicate.rmdir()

    bundle = bundles / "train" / missing_key
    asset = next((bundle / "m2b_public_rgbd").rglob("*.png"))
    asset.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        aggregate_collections(
            bundles_root=bundles,
            output_root=tmp_path / "tampered",
            include_smoke=True,
            training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        )

    output, _result = _aggregate(tmp_path / "fresh")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        aggregate_collections(
            bundles_root=tmp_path / "fresh" / "bundles",
            output_root=output,
            include_smoke=True,
            training_keys_path=ROOT / "configs/m2c_s4_training_keys.json",
            s6_keys_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
            runtime_registry_path=ROOT / "configs/qrm_runtime_mapping_v2.yaml",
        )
