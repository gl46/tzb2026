from __future__ import annotations

from pathlib import Path

import pytest

from m2c.qwen_decision_level_v4 import (
    DecisionDatasetV4Error,
    M2CQwenADR0026DecisionDatasetLoadReportV1,
    decision_head_targets_v4,
    index_decision_histories_v4,
    load_adr0026_decision_bundle_v4,
    load_adr0026_decision_dataset_v4,
    qwen_decision_prompt_v4,
    run_offline_decision_contract_smoke_v4,
    validate_decision_training_sample_v4,
    write_adr0026_decision_bundle_v4,
)
from m2c.qwen_coarse_v4 import (
    M2CQwenCoarseV4KeyManifestAuditV1,
    initialize_numpy_heads_v4,
)
from test_m2c_qwen_coarse_v4 import _package
from xh_agent.policy.qrm_lite.decision_level_supervision_v1 import (
    BoundEvidenceFileV1,
    M2CS4DecisionLevelTrainingSampleV1,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.backbone import DEFAULT_MODEL_ID, DEFAULT_REVISION
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    PathBlockedSupervisedDatasetV4,
)


ROOT = Path(__file__).resolve().parents[2]


def _dataset_report() -> M2CQwenADR0026DecisionDatasetLoadReportV1:
    s6_keys = [f"s6-{index}" for index in range(30)]
    audits = [
        M2CQwenCoarseV4KeyManifestAuditV1(
            training_manifest_file_sha256=character * 64,
            training_manifest_sha256=canonical * 64,
            s6_manifest_file_sha256="e" * 64,
            s6_manifest_sha256="f" * 64,
            training_keys=[f"train-{group}-{index}" for index in range(36)],
            evaluation_keys=s6_keys,
            overlap_keys=[],
            overlap_scene_seeds=[],
        )
        for group, character, canonical in ((0, "a", "b"), (1, "c", "d"))
    ]
    source = BoundEvidenceFileV1(path="evidence://raw.json", sha256="1" * 64)
    return M2CQwenADR0026DecisionDatasetLoadReportV1(
        status="PASS_REPLAYED_ADR0026_V4_DECISION_DATA",
        packaging_report=BoundEvidenceFileV1(path="reports/package.json", sha256="2" * 64),
        dataset_manifest=BoundEvidenceFileV1(path="artifacts/manifest.json", sha256="3" * 64),
        dataset_manifest_sha256="4" * 64,
        v4_shard=BoundEvidenceFileV1(path="artifacts/v4.jsonl", sha256="5" * 64),
        v3_shard_excluded_from_v4=BoundEvidenceFileV1(path="artifacts/v3.jsonl", sha256="6" * 64),
        rows_total=7,
        eligible_episodes=1,
        decision_index_counts={str(index): 1 for index in range(7)},
        skill_head_supervised_rows=7,
        pointer_head_supervised_rows=6,
        pointer_head_masked_rows=1,
        destination_head_supervised_rows=7,
        source_training_manifest_audits=audits,
        source_evidence_files=[source],
        source_evidence_inventory_sha256=canonical_sha256([source.model_dump(mode="json")]),
        public_asset_files_verified=14,
        public_asset_inventory_sha256="7" * 64,
        combined_dataset_sha256="5" * 64,
    )


def _decision_sample(old: object) -> M2CS4DecisionLevelTrainingSampleV1:
    payload = old.model_dump(mode="json")  # type: ignore[attr-defined]
    for field in (
        "schema_version",
        "checkpoint_architecture_revision",
        "candidate_contract_revision",
        "model_training_eligible",
    ):
        payload.pop(field)
    payload.update(
        {
            "schema_version": "M2CS4DecisionLevelTrainingSampleV1",
            "evidence_revision": "V4",
            "label_source": "EXECUTED_PUBLIC_PHYSICAL_CHAIN_ADR0026",
            "skill_head_supervision_eligible": True,
            "pointer_head_supervision_eligible": True,
            "destination_head_supervision_eligible": True,
            "decision_level_training_eligible": True,
        }
    )
    payload["sample_sha256"] = canonical_sha256(payload)
    return M2CS4DecisionLevelTrainingSampleV1.model_validate(payload)


def _samples(tmp_path: Path) -> list[M2CS4DecisionLevelTrainingSampleV1]:
    package = _package(tmp_path)
    dataset = PathBlockedSupervisedDatasetV4.model_validate_json(
        (package / "supervised-steps-v4.json").read_bytes()
    )
    return [_decision_sample(item) for item in dataset.samples]


def test_decision_v4_validates_labels_and_builds_exact_prefix_history(tmp_path: Path) -> None:
    samples = _samples(tmp_path)[:7]
    for sample in samples:
        validate_decision_training_sample_v4(sample)
    histories = index_decision_histories_v4(samples)
    assert [len(histories[sample.sample_id]) for sample in samples] == list(range(7))
    prompt = qwen_decision_prompt_v4(
        samples[6],
        executed_intent_history=histories[samples[6].sample_id],
        use_failure_context=True,
    )
    assert "PATH_BLOCKED" in prompt
    assert decision_head_targets_v4(samples[0])["skill"] == samples[0].skill_label_index


def test_decision_v4_pointer_mask_cannot_hide_an_encodable_target(tmp_path: Path) -> None:
    sample = _samples(tmp_path)[0]
    payload = sample.model_dump(mode="json", exclude={"sample_sha256"})
    payload["pointer_class_index"] = None
    payload["pointer_head_supervision_eligible"] = False
    payload["sample_sha256"] = canonical_sha256(payload)
    masked = M2CS4DecisionLevelTrainingSampleV1.model_validate(payload)
    with pytest.raises(DecisionDatasetV4Error, match="outside K=8"):
        validate_decision_training_sample_v4(masked)


def test_decision_v4_rejects_incomplete_episode_prefix(tmp_path: Path) -> None:
    samples = _samples(tmp_path)[:6]
    with pytest.raises(DecisionDatasetV4Error, match="exact 0..6 prefix"):
        index_decision_histories_v4(samples)


def test_decision_v4_bundle_is_versioned_and_fail_closed(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    (output / "adapter").mkdir(parents=True)
    (output / "adapter" / "adapter.bin").write_bytes(b"adapter")
    manifest = write_adr0026_decision_bundle_v4(
        output,
        heads=initialize_numpy_heads_v4(16, 20260815),
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_REVISION,
        base_model_snapshot_tree_sha256="8" * 64,
        failure_context="on",
        dataset_report=_dataset_report(),
        seed=20260815,
        optimizer_steps=1,
    )
    loaded = load_adr0026_decision_bundle_v4(
        output,
        expected_bundle_sha256=manifest.bundle_sha256,
    )
    assert loaded.manifest.training_contract_revision == ("ADR0026_DECISION_LEVEL_PREFIX_0_6_V1")
    assert loaded.manifest.train_samples == 7
    report_path = output / loaded.manifest.training_dataset_report_relative_path
    report_path.write_bytes(report_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="report file SHA-256 mismatch"):
        load_adr0026_decision_bundle_v4(
            output,
            expected_bundle_sha256=manifest.bundle_sha256,
        )


def test_real_adr0026_v4_dataset_replays_when_external_evidence_is_present(
    tmp_path: Path,
) -> None:
    manifest = ROOT / "artifacts/m2c/s4-decision-level-supervision-adr0026-v1/dataset-manifest.json"
    evidence = Path("/Users/gl/tzb-m2c-evidence")
    if not manifest.is_file() or not evidence.is_dir():
        pytest.skip("external ADR-0026 replay evidence is not installed")
    loaded = load_adr0026_decision_dataset_v4(
        project_root=ROOT,
        evidence_base=evidence,
        dataset_manifest_path=manifest,
        packaging_report_path=(ROOT / "reports/m2c-s4-decision-level-supervision-adr0026.json"),
        training_manifest_paths=[
            ROOT / "configs/m2c_s4_v4_training_keys.json",
            ROOT / "configs/m2c_s4_v4_training_keys_extension1.json",
        ],
        evaluation_manifest_path=ROOT / "configs/m2c_s6_evaluation_keys.json",
    )
    assert loaded.report.rows_total == 273
    assert loaded.report.eligible_episodes == 39
    assert loaded.report.pointer_head_supervised_rows == 259
    assert loaded.report.pointer_head_masked_rows == 14
    smoke = run_offline_decision_contract_smoke_v4(loaded)
    assert smoke["status"] == "CONTRACT_SMOKE_PASS_NO_TRAINING"
    assert smoke["optimizer_steps"] == 0
    assert smoke["teacher_used"] is False
    bundle_root = tmp_path / "bundle"
    (bundle_root / "adapter").mkdir(parents=True)
    (bundle_root / "adapter" / "adapter.bin").write_bytes(b"trained-adapter-fixture")
    bundle = write_adr0026_decision_bundle_v4(
        bundle_root,
        heads=initialize_numpy_heads_v4(16, 20260815),
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_REVISION,
        base_model_snapshot_tree_sha256="a" * 64,
        failure_context="on",
        dataset_report=loaded.report,
        seed=20260815,
        optimizer_steps=1,
    )
    assert bundle.training_dataset_manifest_file_sha256 == loaded.report.dataset_manifest.sha256
    assert (
        load_adr0026_decision_bundle_v4(
            bundle_root,
            expected_bundle_sha256=bundle.bundle_sha256,
        ).manifest
        == bundle
    )
