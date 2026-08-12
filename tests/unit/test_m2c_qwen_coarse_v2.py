from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from m2c.evaluate_qwen_coarse_v2 import (
    _build_backbone as build_evaluator_backbone,
    _validate_args as validate_evaluator_args,
    coarse_intent_from_prediction,
    parse_args as parse_evaluator_args,
)
from m2c.qwen_coarse_v2 import (
    BUNDLE_MANIFEST_NAME,
    CHAIN_SKILLS,
    DESTINATION_LABELS,
    HEAD_CHECKPOINT_NAME,
    POINTER_LABELS,
    SKILL_LABELS,
    DatasetLoadReport,
    KeyManifestAudit,
    build_head_metadata,
    initialize_numpy_heads,
    index_executed_histories,
    load_bundle,
    load_head_checkpoint,
    load_training_dataset,
    qwen_coarse_v2_prompt,
    run_offline_smoke,
    runtime_observation_for_sample,
    save_head_checkpoint,
    validate_key_manifests,
    validate_training_sample,
)
from m2c.train_qwen_coarse_v2 import (
    WALL_BUDGET_ERROR,
    _attach_trainable_adapter,
    _build_backbone,
    _hard_wall_alarm,
    _model_cache_report,
    _publish_staged_output,
    _real_train,
    _require_wall_budget,
    _resolve_local_revision_snapshot,
    _run_with_wall_budget,
    _validate_args,
    main as train_main,
    parse_args,
)
from m2c.serve_qwen_coarse_v2 import (
    _binding_from_verified_bundle,
    _resolve_materialized_model_snapshot,
)
from xh_agent.policy.qrm_lite.backbone import DEFAULT_MODEL_ID, DEFAULT_REVISION
from xh_agent.policy.qrm_lite.runtime_adapter_v2 import (
    build_runtime_skill_request_v2,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import (
    load_registry_v2,
    validate_runtime_mapping_v2,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
    M2CPathBlockedSupervisedStepV2,
    PathBlockedSupervisedDatasetV2,
    build_path_blocked_supervised_dataset,
    canonical_manifest_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
TRAINING_KEYS = ROOT / "configs/m2c_s4_training_keys.json"
EVALUATION_KEYS = ROOT / "configs/m2c_s6_evaluation_keys.json"
REGISTRY = ROOT / "configs/qrm_runtime_mapping_v2.yaml"
REGISTRY_SHA = "a" * 64
BLOCKER = "track-public-blocker"
TARGET = "track-public-task-target"
OTHER = "track-public-other"
DIGEST = "a" * 64


def _frozen_records() -> tuple[dict, dict]:
    payload = json.loads(TRAINING_KEYS.read_text())
    return payload["training_keys"][0], payload["physical_prerequisite_smoke_keys"][0]


def _collection_key(record: dict, role: str) -> dict[str, object]:
    return {
        "collection_key": f"{record['matched_key']}-collection",
        "collection_role": role,
        "matched_key": record["matched_key"],
        "scene_seed": record["scene_seed"],
        "failure_seed": record["failure_seed"],
        "split": record["split"],
        "split_group": f"scene-{record['scene_seed']}",
    }


def _collection_manifest(keys: list[dict]) -> FrozenPathBlockedCollectionManifestV2:
    return FrozenPathBlockedCollectionManifestV2(
        manifest_key="m2c-qwen-test-collection",
        runtime_registry_sha256=REGISTRY_SHA,
        skill_labels=list(SKILL_LABELS),
        pointer_class_labels=list(POINTER_LABELS),
        destination_class_labels=list(DESTINATION_LABELS),
        keys=keys,
    )


def _s6_manifest() -> FrozenS6ExclusionManifestV2:
    record = json.loads(EVALUATION_KEYS.read_text())["evaluation_keys"][0]
    return FrozenS6ExclusionManifestV2(
        manifest_key="m2c-qwen-test-s6",
        keys=[
            {
                "matched_key": record["matched_key"],
                "scene_seed": record["scene_seed"],
                "failure_seed": record["failure_seed"],
            }
        ],
    )


def _track(track_id: str, color: str) -> dict[str, object]:
    return {
        "track_id": track_id,
        "category": f"industrial_cylinder:{color}",
        "confidence": 0.99,
        "pose_xyzquat": [0.1, 0.2, 0.5, 1.0, 0.0, 0.0, 0.0],
    }


def _raw_evidence(
    key: dict[str, object],
    collection: FrozenPathBlockedCollectionManifestV2,
    s6: FrozenS6ExclusionManifestV2,
) -> dict[str, object]:
    steps: list[dict[str, object]] = []
    previous_completed = 100
    for index, skill in enumerate(CHAIN_SKILLS):
        blocker = f"{BLOCKER}-{index}"
        target = f"{TARGET}-{index}"
        tracks = [_track(target, "yellow"), _track(OTHER, "green"), _track(blocker, "red")]
        slots = [blocker, OTHER, target, None, None, None, None, None]
        captured = previous_completed + 10
        started = captured + 10
        completed = started + 10
        steps.append(
            {
                "decision_index": index,
                "observation": {
                    "observation_id": f"{key['scene_seed']}-observation-{index}",
                    "captured_at_ns": captured,
                    "fresh": True,
                    "rgb_uri": f"dataset://episode-{key['scene_seed']}/rgb/{index}.png",
                    "depth_uri": f"dataset://episode-{key['scene_seed']}/depth/{index}.npy",
                    "rgb_sha256": f"{100 + index:064x}",
                    "depth_sha256": f"{200 + index:064x}",
                    "capture_receipt_sha256": f"{int(key['scene_seed']) * 100 + index:064x}",
                    "perception_tracks": tracks,
                    "canonical_slots": slots,
                },
                "public_blocker_track_id": blocker,
                "public_task_target_track_id": target,
                "destination_cell_label": "BIN_CELL_3" if index in {2, 3} else None,
                "physical_receipts": [
                    {
                        "receipt_id": f"{key['scene_seed']}-receipt-{index}",
                        "receipt_uri": f"evidence://receipt/{key['scene_seed']}/{index}.json",
                        "receipt_sha256": f"{int(key['scene_seed']) * 1000 + index:064x}",
                        "executed_skill": skill,
                        "physically_executed": True,
                        "started_at_ns": started,
                        "completed_at_ns": completed,
                        "execution_measurements": {
                            "fixture_physical_success": True,
                            "decision_index": index,
                        },
                        "action_protocol": {
                            "coordinate_frame": "policy_rgbd_optical"
                            if skill == "REOBSERVE"
                            else "world",
                            "units": "none"
                            if skill in {"REOBSERVE", "REASSOCIATE_TARGET"}
                            else "m_rad",
                            "dimensions": 0 if skill in {"REOBSERVE", "REASSOCIATE_TARGET"} else 3,
                            "frequency_hz": 60.0,
                            "normalization": "none",
                        },
                        "schema_gate": "PASS",
                        "stale_track_gate": "PASS",
                        "frame_unit_gate": "PASS",
                        "ik_gate": "PASS",
                        "collision_gate": "PASS",
                        "controller_gate": "PASS",
                        "safety_gate": "PASS",
                    }
                ],
            }
        )
        previous_completed = completed
    return {
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "episode_id": f"episode-{key['scene_seed']}",
        "scene_seed": key["scene_seed"],
        "failure_seed": key["failure_seed"],
        "split": key["split"],
        "split_group": key["split_group"],
        "matched_key": key["matched_key"],
        "collection_role": key["collection_role"],
        "collection_key": key["collection_key"],
        "collection_manifest_ref": {
            "manifest_key": collection.manifest_key,
            "manifest_sha256": canonical_manifest_sha256(collection),
        },
        "s6_exclusion_manifest_ref": {
            "manifest_key": s6.manifest_key,
            "manifest_sha256": canonical_manifest_sha256(s6),
        },
        "runtime_registry_sha256": REGISTRY_SHA,
        "sdf_sha256": "b" * 64,
        "supervision_sha256": "c" * 64,
        "source_evidence_uri": f"evidence://episode/{key['scene_seed']}.json",
        "source_evidence_sha256": f"{int(key['scene_seed']):064x}",
        "failure_observed_at_ns": 100,
        "final_task_success": True,
        "steps": steps,
    }


def _dataset(tmp_path: Path) -> tuple[Path, Path, list[M2CPathBlockedSupervisedStepV2]]:
    train_record, val_record = _frozen_records()
    train_key = _collection_key(train_record, "TRAIN")
    val_key = _collection_key(val_record, "SMOKE")
    collection = _collection_manifest([train_key, val_key])
    s6 = _s6_manifest()
    manifest = build_path_blocked_supervised_dataset(
        [
            _raw_evidence(train_key, collection, s6),
            _raw_evidence(val_key, collection, s6),
        ],
        collection_manifest=collection,
        s6_manifest=s6,
    )
    assert manifest.status == "PASS"
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text("".join(sample.model_dump_json() + "\n" for sample in manifest.samples))
    manifest_path = tmp_path / "dataset-manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n")
    return dataset_path, manifest_path, manifest.samples


def _dataset_report() -> DatasetLoadReport:
    return DatasetLoadReport(
        dataset_sha256=DIGEST,
        rows_total=8,
        rows_eligible=8,
        rows_excluded=0,
        eligible_episodes=1,
        split_counts={"train": 8, "val": 0},
        exclusion_reason_histogram={},
        dataset_manifest_path="fixture.json",
        dataset_manifest_sha256="f" * 64,
        dataset_manifest_status="PASS",
        key_manifest_audit=KeyManifestAudit(
            training_manifest_sha256="d" * 64,
            evaluation_manifest_sha256="e" * 64,
            training_keys=["train-key"],
            smoke_keys=["smoke-key"],
            evaluation_keys=["evaluation-key"],
            v4_excluded_keys=["v4-key"],
        ),
    )


def _checkpoint_payload(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as payload:
        return {key: np.asarray(payload[key]).copy() for key in payload.files}


def test_builder_sample_recomputes_all_three_labels(tmp_path: Path) -> None:
    _, _, samples = _dataset(tmp_path)
    sample = samples[2]
    validate_training_sample(sample)
    assert sample.model_label.skill_type == "MOVE"
    assert sample.pointer_class_index == 0
    assert sample.destination_class_index == 3
    histories = index_executed_histories(samples[:8])
    prompt = qwen_coarse_v2_prompt(
        sample,
        executed_intent_history=histories[sample.sample_id],
        use_failure_context=True,
    )
    assert "literal K=8" in prompt
    assert "continuous" in prompt.lower().split("context:", 1)[0]
    assert '"decision_index":2' not in prompt
    assert "expected_next" not in prompt

    payload = sample.model_dump(mode="json")
    payload["pointer_class_index"] = 8
    forged = M2CPathBlockedSupervisedStepV2.model_validate(payload)
    with pytest.raises(ValueError, match="pointer_class_index"):
        validate_training_sample(forged)


def test_training_history_is_exact_public_prefix_and_changes_prompt(
    tmp_path: Path,
) -> None:
    _, _, samples = _dataset(tmp_path)
    episode = samples[:8]
    histories = index_executed_histories(episode)
    for sample in episode:
        history = histories[sample.sample_id]
        assert len(history) == sample.decision_index
        assert [item.decision_index for item in history] == list(range(sample.decision_index))
        assert all(
            item.execution_attribution == "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION" for item in history
        )
    first = episode[0]
    normal = qwen_coarse_v2_prompt(
        first,
        executed_intent_history=[],
        use_failure_context=True,
    )
    same_observation_later = first.model_copy(update={"decision_index": 1})
    later = qwen_coarse_v2_prompt(
        same_observation_later,
        executed_intent_history=[histories[episode[1].sample_id][0]],
        use_failure_context=True,
    )
    assert normal != later
    normal_payload = json.loads(normal.split("Context:\n", 1)[1])
    later_payload = json.loads(later.split("Context:\n", 1)[1])
    assert "decision_index" not in normal_payload
    assert normal_payload["public_executed_intent_history"] == []
    assert len(later_payload["public_executed_intent_history"]) == 1
    assert (
        later_payload["public_executed_intent_history"][0]["execution_attribution"]
        == "EXECUTED_PHYSICAL_SKILL"
    )


def test_frozen_key_manifests_validate_and_detect_tampering(tmp_path: Path) -> None:
    audit = validate_key_manifests(TRAINING_KEYS, EVALUATION_KEYS)
    assert (len(audit.training_keys), len(audit.smoke_keys), len(audit.evaluation_keys)) == (
        36,
        3,
        30,
    )
    tampered = json.loads(TRAINING_KEYS.read_text())
    tampered["exclusions"]["all_s6_keys"] = False
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="manifest digest mismatch"):
        validate_key_manifests(path, EVALUATION_KEYS)


def test_dataset_loader_checks_builder_manifest_complete_chains_and_s6(tmp_path: Path) -> None:
    dataset, manifest, samples = _dataset(tmp_path)
    loaded, report = load_training_dataset(
        dataset,
        dataset_manifest_path=manifest,
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    assert len(loaded) == 8
    assert report.rows_total == 16
    assert report.rows_excluded == 8
    assert report.split_counts == {"train": 8, "val": 0}
    assert len({sample.model_label.target_track_id for sample in loaded[:5]}) == 5

    dataset.write_text("".join(sample.model_dump_json() + "\n" for sample in samples[:-1]))
    with pytest.raises(ValueError, match="digest differs"):
        load_training_dataset(
            dataset,
            dataset_manifest_path=manifest,
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )

    forged = [
        sample.model_copy(
            update={
                "matched_key": json.loads(EVALUATION_KEYS.read_text())["evaluation_keys"][0][
                    "matched_key"
                ]
            }
        )
        for sample in samples[:8]
    ]
    forged_manifest = PathBlockedSupervisedDatasetV2(
        status="PASS",
        samples=forged,
        episode_validations=[],
        dataset_sha256="0" * 64,
        episodes_received=1,
        episodes_physical_valid=1,
        episodes_training_eligible=1,
        samples_training_eligible=8,
    )
    forged_digest = (
        __import__("hashlib")
        .sha256(
            "".join(
                sample.model_dump_json(by_alias=False, exclude_none=False) + "\n"
                for sample in forged
            ).encode()
        )
        .hexdigest()
    )
    forged_manifest = forged_manifest.model_copy(update={"dataset_sha256": forged_digest})
    dataset.write_text("".join(sample.model_dump_json() + "\n" for sample in forged))
    manifest.write_text(forged_manifest.model_dump_json())
    with pytest.raises(ValueError, match="overlaps frozen evaluation"):
        load_training_dataset(
            dataset,
            dataset_manifest_path=manifest,
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )


def test_five_sample_smoke_updates_all_heads_and_reloads(tmp_path: Path) -> None:
    _, _, samples = _dataset(tmp_path)
    output = tmp_path / "smoke"
    report = run_offline_smoke(
        samples,
        output_root=output,
        dataset_report=_dataset_report(),
        seed=19,
        failure_context="on",
    )
    assert report["samples"] == 5
    assert report["heads_exercised"] == ["skill", "pointer", "destination"]
    assert report["head_update_l2"] > 0.0
    assert report["qwen_model_loaded"] is False
    heads, metadata, bundle = load_bundle(
        output,
        require_adapter=False,
        expected_model_id="SMOKE_ONLY_NO_QWEN_MODEL",
        expected_model_revision="NOT_LOADED",
    )
    assert heads.hidden_size == 16
    assert metadata.architecture_revision == "M2C_Q012_V2"
    assert bundle.adapter_path is None
    with pytest.raises(ValueError, match="has no Qwen LoRA adapter"):
        load_bundle(output, require_adapter=True)


def test_head_checkpoint_loader_preserves_legacy_m2b_init_metadata(tmp_path: Path) -> None:
    heads = initialize_numpy_heads(8, seed=1)
    metadata = build_head_metadata(
        model_id="Qwen/Qwen3.5-4B",
        model_revision="revision",
        hidden_size=8,
        failure_context="on",
        dataset_sha256="a" * 64,
        dataset_manifest_sha256="f" * 64,
        training_manifest_sha256="b" * 64,
        evaluation_manifest_sha256="c" * 64,
        seed=1,
        initialization_source="M2B_ADAPTER_INITIALIZATION_ONLY",
        initialization_adapter_sha256="d" * 64,
        adapter_source_architecture_revision="M2B_Q012_V1",
    )
    checkpoint = tmp_path / HEAD_CHECKPOINT_NAME
    save_head_checkpoint(checkpoint, heads, metadata)
    restored, restored_metadata = load_head_checkpoint(checkpoint)
    assert np.array_equal(restored.pointer_w, heads.pointer_w)
    assert restored_metadata.initialization_adapter_sha256 == "d" * 64

    payload = _checkpoint_payload(checkpoint)
    payload["pointer_w"] = np.zeros((8, 8))
    np.savez(checkpoint, **payload)
    with pytest.raises(ValueError, match="pointer_w shape mismatch"):
        load_head_checkpoint(checkpoint)


def test_formal_service_rejects_legacy_m2b_initialized_bundle(tmp_path: Path) -> None:
    heads = initialize_numpy_heads(8, seed=1)
    metadata = build_head_metadata(
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_REVISION,
        hidden_size=8,
        failure_context="on",
        dataset_sha256="a" * 64,
        dataset_manifest_sha256="f" * 64,
        training_manifest_sha256="b" * 64,
        evaluation_manifest_sha256="c" * 64,
        seed=1,
        initialization_source="M2B_ADAPTER_INITIALIZATION_ONLY",
        initialization_adapter_sha256="d" * 64,
        adapter_source_architecture_revision="M2B_Q012_V1",
    )
    manifest = type(
        "Manifest",
        (),
        {
            "status": "TRAINED_QWEN_LORA_THREE_HEADS",
            "head_checkpoint_sha256": "e" * 64,
            "adapter_tree_sha256": "f" * 64,
        },
    )()
    args = type(
        "Args",
        (),
        {
            "model_id": DEFAULT_MODEL_ID,
            "revision": DEFAULT_REVISION,
            "bundle_root": tmp_path,
            "cache_tree_sha256": "0" * 64,
        },
    )()

    with pytest.raises(ValueError, match="NONE initialization provenance"):
        _binding_from_verified_bundle(
            args,
            heads=heads,
            metadata=metadata,
            manifest=manifest,
            model_snapshot=tmp_path,
        )


def test_train_dry_run_never_enters_real_trainer_or_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, manifest, _ = _dataset(tmp_path)
    output = tmp_path / "dry-run"
    invoked: list[bool] = []

    def forbidden_real_train(*_args, **_kwargs):
        invoked.append(True)
        raise AssertionError("real trainer entered")

    monkeypatch.setattr("m2c.train_qwen_coarse_v2._real_train", forbidden_real_train)
    args = [
        "--dataset",
        str(dataset),
        "--dataset-manifest",
        str(manifest),
        "--dataset-root",
        str(tmp_path),
        "--training-keys",
        str(TRAINING_KEYS),
        "--evaluation-keys",
        str(EVALUATION_KEYS),
        "--output-root",
        str(output),
        "--failure-context",
        "on",
        "--dry-run",
    ]
    assert train_main(args) == 0
    assert invoked == []
    assert (output / BUNDLE_MANIFEST_NAME).is_file()
    smoke_report = json.loads((output / "train_report.json").read_text())
    assert smoke_report["qwen_model_loaded"] is False
    assert smoke_report["model_cache"] == {
        "mode": "NOT_ACCESSED_DRY_RUN",
        "cache_dir_explicit": False,
        "local_files_only": False,
        "fixed_revision_resolved": False,
        "cache_path_recorded_as_model_identity": False,
    }
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        train_main(args)


def test_train_args_enforce_six_hours_and_reject_m2b_init(tmp_path: Path) -> None:
    base = [
        "--dataset",
        str(tmp_path / "dataset.jsonl"),
        "--dataset-manifest",
        str(tmp_path / "dataset-manifest.json"),
        "--dataset-root",
        str(tmp_path / "assets"),
        "--training-keys",
        str(TRAINING_KEYS),
        "--evaluation-keys",
        str(EVALUATION_KEYS),
        "--output-root",
        str(tmp_path / "m2c-output"),
        "--failure-context",
        "on",
    ]
    with pytest.raises(ValueError, match="six hours"):
        _validate_args(parse_args([*base, "--max-wall-seconds", "21601"]))
    with pytest.raises(ValueError, match="complete 8-step episodes"):
        _validate_args(parse_args([*base, "--max-train", "7"]))

    with pytest.raises(ValueError, match="forbids --m2b-init-adapter"):
        _validate_args(parse_args([*base, "--m2b-init-adapter", str(tmp_path / "arbitrary-peft")]))


def test_train_cli_help_declares_m2b_init_fail_closed(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        parse_args(["--help"])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert "--m2b-init-adapter" in help_text
    assert "any value fails closed" in " ".join(help_text.split())


def test_m2b_init_rejected_before_dataset_or_model_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[str] = []

    def forbidden_dataset_load(*_args, **_kwargs):
        entered.append("dataset")
        raise AssertionError("dataset loader entered")

    def forbidden_real_train(*_args, **_kwargs):
        entered.append("trainer")
        raise AssertionError("real trainer entered")

    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.load_training_dataset",
        forbidden_dataset_load,
    )
    monkeypatch.setattr("m2c.train_qwen_coarse_v2._real_train", forbidden_real_train)
    with pytest.raises(ValueError, match="initialization_source must be NONE"):
        train_main(
            [
                "--dataset",
                str(tmp_path / "absent-dataset.jsonl"),
                "--dataset-manifest",
                str(tmp_path / "absent-manifest.json"),
                "--dataset-root",
                str(tmp_path / "absent-assets"),
                "--training-keys",
                str(TRAINING_KEYS),
                "--evaluation-keys",
                str(EVALUATION_KEYS),
                "--output-root",
                str(tmp_path / "m2c-output"),
                "--failure-context",
                "on",
                "--m2b-init-adapter",
                str(tmp_path / "arbitrary-peft"),
            ]
        )
    assert entered == []


def test_adapter_attachment_rejects_m2b_path_without_loading_backbone(tmp_path: Path) -> None:
    class BackboneTrap:
        def load(self) -> None:
            raise AssertionError("backbone loaded")

        def attach_lora(self, **_kwargs) -> None:
            raise AssertionError("LoRA attached")

    with pytest.raises(ValueError, match="initialization_source must be NONE"):
        _attach_trainable_adapter(BackboneTrap(), tmp_path / "arbitrary-peft")


def test_real_trainer_rejects_m2b_init_before_cuda_or_samples(tmp_path: Path) -> None:
    args = parse_args(
        [
            "--dataset",
            str(tmp_path / "absent-dataset.jsonl"),
            "--dataset-manifest",
            str(tmp_path / "absent-manifest.json"),
            "--dataset-root",
            str(tmp_path / "absent-assets"),
            "--training-keys",
            str(TRAINING_KEYS),
            "--evaluation-keys",
            str(EVALUATION_KEYS),
            "--output-root",
            str(tmp_path / "m2c-output"),
            "--failure-context",
            "on",
            "--m2b-init-adapter",
            str(tmp_path / "arbitrary-peft"),
        ]
    )
    with pytest.raises(ValueError, match="initialization_source must be NONE"):
        _real_train(args, [], None)


def test_adapter_attachment_initializes_new_lora_only() -> None:
    calls: list[dict[str, object]] = []

    class BackboneStub:
        def attach_lora(self, **kwargs) -> None:
            calls.append(kwargs)

    assert _attach_trainable_adapter(BackboneStub(), None) == ("NONE", None)
    assert calls == [{"r": 8, "alpha": 16, "dropout": 0.05}]


@pytest.mark.parametrize(
    ("override", "message"),
    (
        (["--model-id", "/unhashed/manual/Qwen3.5-4B"], "canonical Qwen model ID"),
        (["--revision", "main"], "canonical Qwen revision"),
    ),
)
def test_real_train_rejects_noncanonical_model_identity(
    tmp_path: Path,
    override: list[str],
    message: str,
) -> None:
    args = parse_args(
        [
            "--dataset",
            str(tmp_path / "dataset.jsonl"),
            "--dataset-manifest",
            str(tmp_path / "dataset-manifest.json"),
            "--dataset-root",
            str(tmp_path / "assets"),
            "--training-keys",
            str(TRAINING_KEYS),
            "--evaluation-keys",
            str(EVALUATION_KEYS),
            "--output-root",
            str(tmp_path / "m2c-output"),
            "--failure-context",
            "on",
            *override,
        ]
    )
    with pytest.raises(ValueError, match=message):
        _validate_args(args)


def _offline_cache_snapshot(cache_dir: Path) -> Path:
    snapshot = cache_dir / "models--Qwen--Qwen3.5-4B" / "snapshots" / DEFAULT_REVISION
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    (snapshot / "model-00001-of-00001.safetensors").write_bytes(b"weights")
    (snapshot / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"model.layer.weight": "model-00001-of-00001.safetensors"}})
    )
    return snapshot


def test_local_only_cache_resolves_pin_and_passes_loader_parameters_without_identity_drift(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "hf-cache"
    snapshot = _offline_cache_snapshot(cache_dir)
    args = parse_args(
        [
            "--dataset",
            str(tmp_path / "dataset.jsonl"),
            "--dataset-manifest",
            str(tmp_path / "dataset-manifest.json"),
            "--dataset-root",
            str(tmp_path / "assets"),
            "--training-keys",
            str(TRAINING_KEYS),
            "--evaluation-keys",
            str(EVALUATION_KEYS),
            "--output-root",
            str(tmp_path / "m2c-output"),
            "--failure-context",
            "on",
            "--cache-dir",
            str(cache_dir),
            "--local-files-only",
        ]
    )
    _validate_args(args)
    assert _resolve_local_revision_snapshot(cache_dir) == snapshot
    backbone = _build_backbone(args)
    assert backbone.model_id == DEFAULT_MODEL_ID
    assert backbone.revision == DEFAULT_REVISION
    assert backbone.cache_dir == str(cache_dir.resolve())
    assert backbone.local_files_only is True
    report = _model_cache_report(
        args,
        fixed_revision_resolved=True,
        dry_run=False,
    )
    assert report == {
        "mode": "LOCAL_FILES_ONLY",
        "cache_dir_explicit": True,
        "local_files_only": True,
        "fixed_revision_resolved": True,
        "cache_path_recorded_as_model_identity": False,
    }
    assert str(cache_dir) not in json.dumps(report)


def test_local_only_cache_rejects_incomplete_or_lfs_pointer_snapshot(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "hf-cache"
    snapshot = _offline_cache_snapshot(cache_dir)
    (snapshot / "model-00001-of-00001.safetensors").unlink()
    with pytest.raises(ValueError, match="absent or empty"):
        _resolve_local_revision_snapshot(cache_dir)
    (snapshot / "model-00001-of-00001.safetensors").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
    )
    with pytest.raises(ValueError, match="LFS pointer"):
        _resolve_local_revision_snapshot(cache_dir)


def test_local_only_cache_rejects_symlinked_root_snapshot_or_weights(
    tmp_path: Path,
) -> None:
    real_cache = tmp_path / "real-cache"
    snapshot = _offline_cache_snapshot(real_cache)
    symlinked_root = tmp_path / "cache-link"
    symlinked_root.symlink_to(real_cache, target_is_directory=True)
    with pytest.raises(ValueError, match="root may not be a symlink"):
        _resolve_materialized_model_snapshot(symlinked_root)

    weight = snapshot / "model-00001-of-00001.safetensors"
    external = tmp_path / "external-weights.safetensors"
    external.write_bytes(weight.read_bytes())
    weight.unlink()
    weight.symlink_to(external)
    with pytest.raises(ValueError, match="fully materialized"):
        _resolve_materialized_model_snapshot(real_cache)


def test_dry_run_cache_report_never_claims_model_resolution(tmp_path: Path) -> None:
    args = parse_args(
        [
            "--dataset",
            str(tmp_path / "dataset.jsonl"),
            "--dataset-manifest",
            str(tmp_path / "dataset-manifest.json"),
            "--dataset-root",
            str(tmp_path / "assets"),
            "--training-keys",
            str(TRAINING_KEYS),
            "--evaluation-keys",
            str(EVALUATION_KEYS),
            "--output-root",
            str(tmp_path / "smoke-output"),
            "--failure-context",
            "off",
            "--dry-run",
        ]
    )
    assert _model_cache_report(
        args,
        fixed_revision_resolved=False,
        dry_run=True,
    ) == {
        "mode": "NOT_ACCESSED_DRY_RUN",
        "cache_dir_explicit": False,
        "local_files_only": False,
        "fixed_revision_resolved": False,
        "cache_path_recorded_as_model_identity": False,
    }


def _evaluator_args(
    tmp_path: Path,
    cache_dir: Path,
    *extra: str,
):
    return parse_evaluator_args(
        [
            "--dataset",
            str(tmp_path / "dataset.jsonl"),
            "--dataset-manifest",
            str(tmp_path / "dataset-manifest.json"),
            "--dataset-root",
            str(tmp_path / "assets"),
            "--training-keys",
            str(TRAINING_KEYS),
            "--evaluation-keys",
            str(EVALUATION_KEYS),
            "--bundle-root",
            str(tmp_path / "bundle"),
            "--registry",
            str(REGISTRY),
            "--output",
            str(tmp_path / "decisions.jsonl"),
            "--report",
            str(tmp_path / "eval-report.json"),
            "--cache-dir",
            str(cache_dir),
            "--local-files-only",
            *extra,
        ]
    )


def test_evaluator_requires_canonical_offline_model_and_revision(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "hf-cache"
    cache_dir.mkdir()
    validate_evaluator_args(_evaluator_args(tmp_path, cache_dir))
    with pytest.raises(ValueError, match="canonical Qwen model ID"):
        validate_evaluator_args(
            _evaluator_args(
                tmp_path,
                cache_dir,
                "--model-id",
                str(tmp_path / "manual-Qwen"),
            )
        )
    with pytest.raises(ValueError, match="canonical Qwen revision"):
        validate_evaluator_args(
            _evaluator_args(
                tmp_path,
                cache_dir,
                "--revision",
                "main",
            )
        )


def test_evaluator_requires_existing_explicit_local_only_cache(
    tmp_path: Path,
) -> None:
    missing_cache = tmp_path / "missing-cache"
    with pytest.raises(ValueError, match="cache directory does not exist"):
        validate_evaluator_args(_evaluator_args(tmp_path, missing_cache))
    missing_cache.mkdir()
    args = _evaluator_args(tmp_path, missing_cache)
    args.local_files_only = False
    with pytest.raises(ValueError, match="must be local-files-only"):
        validate_evaluator_args(args)


def test_evaluator_passes_explicit_cache_without_identity_drift(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "hf-cache"
    _offline_cache_snapshot(cache_dir)
    args = _evaluator_args(tmp_path, cache_dir)
    validate_evaluator_args(args)
    assert _resolve_local_revision_snapshot(cache_dir).is_dir()
    backbone = build_evaluator_backbone(args)
    assert backbone.model_id == DEFAULT_MODEL_ID
    assert backbone.revision == DEFAULT_REVISION
    assert backbone.cache_dir == str(cache_dir.resolve())
    assert backbone.local_files_only is True
    cache_report = _model_cache_report(
        args,
        fixed_revision_resolved=True,
        dry_run=False,
    )
    assert cache_report["mode"] == "LOCAL_FILES_ONLY"
    assert str(cache_dir) not in json.dumps(cache_report)


def test_grasp_predictions_explicitly_decode_top_down_and_map_validly(
    tmp_path: Path,
) -> None:
    _, _, samples = _dataset(tmp_path)
    registry = load_registry_v2(REGISTRY)
    for skill in ("GRASP", "REGRASP"):
        sample = next(item for item in samples if item.model_label.skill_type == skill)
        intent = coarse_intent_from_prediction(
            skill_index=SKILL_LABELS.index(skill),
            target_track_id=sample.model_label.target_track_id,
            destination_cell=None,
        )
        assert intent.grasp_family == "top_down"
        request = build_runtime_skill_request_v2(
            runtime_observation_for_sample(sample),
            intent,
            registry,
        )
        mapping = validate_runtime_mapping_v2(request, registry)
        assert mapping.status == "VALID"
        assert mapping.parameters["grasp_family"] == "top_down"


def test_whole_run_wall_deadline_fails_closed_at_equal_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.time.monotonic",
        lambda: 21610.0,
    )
    with pytest.raises(TimeoutError, match=WALL_BUDGET_ERROR):
        _require_wall_budget(21610.0)


def test_hard_alarm_uses_only_remaining_whole_run_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[tuple[int, object]] = []
    timers: list[tuple[int, float]] = []
    previous_handler = object()
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.time.monotonic",
        lambda: 100.0,
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.signal.getitimer",
        lambda _timer: (0.0, 0.0),
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.signal.getsignal",
        lambda _signal: previous_handler,
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.signal.signal",
        lambda signal_number, handler: handlers.append((signal_number, handler)),
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.signal.setitimer",
        lambda timer, seconds: timers.append((timer, seconds)),
    )
    with pytest.raises(TimeoutError, match=WALL_BUDGET_ERROR):
        with _hard_wall_alarm(110.0):
            handler = handlers[0][1]
            assert callable(handler)
            handler(None, None)
    assert timers == [(0, 10.0), (0, 0.0)]
    assert handlers[-1] == (14, previous_handler)


@pytest.mark.parametrize(
    "stage",
    ("training", "in_sample_fit", "adapter_save", "head_and_bundle_save"),
)
def test_each_blocking_real_training_stage_rejects_completion_at_deadline(
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((1.0, 10.0))
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.time.monotonic",
        lambda: next(moments),
    )
    completed: list[str] = []
    with pytest.raises(TimeoutError, match=WALL_BUDGET_ERROR):
        _run_with_wall_budget(10.0, completed.append, stage)
    assert completed == [stage]


def test_real_main_timeout_keeps_formal_output_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "real-output"
    captured: dict[str, float | Path] = {}

    def fake_load(*_args, **_kwargs):
        return [], _dataset_report()

    def fake_real_train(
        fake_args,
        _samples,
        _dataset_report_value,
        *,
        whole_run_started_monotonic: float,
        deadline_monotonic: float,
    ):
        captured["started"] = whole_run_started_monotonic
        captured["deadline"] = deadline_monotonic
        captured["staging"] = fake_args.output_root
        fake_args.output_root.mkdir()
        return {"status": "WOULD_PASS_INSIDE_BUDGET"}

    moments = iter((100.0, 100.1, 101.0, 102.0, 105.0, 109.0, 110.0))
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.time.monotonic",
        lambda: next(moments),
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.load_training_dataset",
        fake_load,
    )
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2._real_train",
        fake_real_train,
    )
    with pytest.raises(TimeoutError, match=WALL_BUDGET_ERROR):
        train_main(
            [
                "--dataset",
                str(tmp_path / "dataset.jsonl"),
                "--dataset-manifest",
                str(tmp_path / "dataset-manifest.json"),
                "--dataset-root",
                str(tmp_path / "assets"),
                "--training-keys",
                str(TRAINING_KEYS),
                "--evaluation-keys",
                str(EVALUATION_KEYS),
                "--output-root",
                str(output),
                "--failure-context",
                "on",
                "--max-wall-seconds",
                "10",
            ]
        )
    assert captured["started"] == 100.0
    assert captured["deadline"] == 110.0
    staging = captured["staging"]
    assert isinstance(staging, Path)
    assert staging.name.startswith(".real-output.incomplete-")
    assert (staging / "train_report.json").is_file()
    assert not output.exists()


def test_atomic_publish_rolls_back_if_deadline_crosses_during_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / ".bundle.incomplete-test"
    staging.mkdir()
    (staging / "payload").write_text("complete")
    output = tmp_path / "bundle"
    moments = iter((9.0, 10.0))
    monkeypatch.setattr(
        "m2c.train_qwen_coarse_v2.time.monotonic",
        lambda: next(moments),
    )
    with pytest.raises(TimeoutError, match=WALL_BUDGET_ERROR):
        _publish_staged_output(staging, output, 10.0)
    assert not output.exists()
    assert (staging / "payload").read_text() == "complete"


def test_bundle_manifest_detects_checkpoint_tampering(tmp_path: Path) -> None:
    _, _, samples = _dataset(tmp_path)
    output = tmp_path / "bundle"
    run_offline_smoke(
        samples,
        output_root=output,
        dataset_report=_dataset_report(),
        seed=2,
        failure_context="off",
    )
    checkpoint = output / HEAD_CHECKPOINT_NAME
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash differs"):
        load_bundle(output, require_adapter=False)
