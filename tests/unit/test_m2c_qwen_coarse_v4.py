from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from m2c.qwen_coarse_v4 import (
    DESTINATION_LABELS,
    POINTER_LABELS,
    SKILL_LABELS,
    checkpoint_binding_for_numpy_heads_v4,
    index_executed_histories_v4,
    initialize_numpy_heads_v4,
    load_training_packages_v4,
    qwen_coarse_v4_prompt,
    run_offline_contract_smoke_v4,
    validate_head_checkpoint_binding_v4,
    validate_key_manifests_v4,
)
from test_m2c_v4_collection_plumbing import _manifest, _raw_bundle
from xh_agent.policy.qrm_lite.path_blocked_collection_v4 import (
    build_path_blocked_supervised_dataset_v4,
    host_replay_probe_chain_v4,
    package_probe_chain_v4,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (
    FrozenS6ExclusionManifestV2,
)


ROOT = Path(__file__).resolve().parents[2]
TRAINING_KEYS = ROOT / "configs/m2c_s4_v4_training_keys.json"
EVALUATION_KEYS = ROOT / "configs/m2c_s6_evaluation_keys.json"


def _s6_manifest() -> FrozenS6ExclusionManifestV2:
    records = json.loads(EVALUATION_KEYS.read_text())["evaluation_keys"]
    return FrozenS6ExclusionManifestV2.model_validate(
        {
            "schema_version": "FrozenS6ExclusionManifestV2",
            "manifest_key": "M2C_S6_FROZEN_EVALUATION_KEYS",
            "frozen_before_q_b_training": True,
            "keys": [
                {
                    "schema_version": "FrozenS6EvaluationKeyV2",
                    "matched_key": item["matched_key"],
                    "scene_seed": item["scene_seed"],
                    "failure_seed": item["failure_seed"],
                }
                for item in records
            ],
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
    )


def _package(tmp_path: Path) -> Path:
    manifest = _manifest()
    key = manifest.training_keys[0]
    chain, captures = _raw_bundle()
    chain.update(
        scene_seed=key.scene_seed,
        failure_seed=key.failure_seed,
        matched_key=key.matched_key,
        collection_key=f"{key.matched_key}-collection",
        sdf_sha256=key.sdf_sha256,
        supervision_sha256=key.supervision_sha256,
    )
    for step in chain["steps"]:  # type: ignore[union-attr]
        receipt = step["physical_receipts"][0]
        receipt["action_protocol"]["frequency_hz"] = 60.0
        receipt_core = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        receipt["receipt_sha256"] = hashlib.sha256(
            json.dumps(receipt_core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    root = tmp_path / "package"
    root.mkdir(parents=True)
    for index, capture in enumerate(captures):
        for kind, suffix in (("rgb", ".png"), ("depth", ".npy")):
            payload = f"{kind}-{index}".encode()
            path = root / kind / f"{index}{suffix}"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            capture[f"{kind}_sha256"] = digest
            chain["steps"][index]["observation"][f"{kind}_sha256"] = digest  # type: ignore[index]
        capture_digest = hashlib.sha256(
            json.dumps(capture, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        chain["steps"][index]["observation"]["capture_receipt_sha256"] = (  # type: ignore[index]
            capture_digest
        )
    replayed = host_replay_probe_chain_v4(
        chain,
        captures,
        training_key=key,
        training_manifest=manifest,
        capture_source_implementation_sha256="d" * 64,
    )
    raw_source = json.dumps(
        {
            "status": "PASS",
            "not_policy_rollout": True,
            "m2c_v4_raw_association_captures": captures,
            "m2c_path_blocked_physical_chain": chain,
        },
        separators=(",", ":"),
    ).encode()
    s6 = _s6_manifest()
    evidence = package_probe_chain_v4(
        replayed.model_dump(mode="json"),
        training_manifest=manifest,
        s6_manifest=s6,
        runtime_registry_sha256="e" * 64,
        source_evidence_uri="dataset://actuation-probe.json",
        source_evidence_sha256=hashlib.sha256(raw_source).hexdigest(),
    )
    dataset = build_path_blocked_supervised_dataset_v4(
        evidence,
        training_manifest=manifest,
        s6_manifest=s6,
    )
    assert dataset.status == "PASS"
    (root / "packaged-physical-chain-v4.json").write_text(
        evidence.model_dump_json(),
        encoding="utf-8",
    )
    (root / "supervised-steps-v4.json").write_text(
        dataset.model_dump_json(),
        encoding="utf-8",
    )
    (root / "actuation-probe.json").write_bytes(raw_source)
    for step in evidence.steps:
        receipt = step.physical_receipts[0]
        relative = Path(receipt.receipt_uri.removeprefix("dataset://"))
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(receipt.model_dump_json(), encoding="utf-8")
    return root


def test_v4_frozen_train_and_s6_manifests_are_disjoint() -> None:
    audit, training, s6 = validate_key_manifests_v4(TRAINING_KEYS, EVALUATION_KEYS)
    assert len(audit.training_keys) == 36
    assert len(audit.evaluation_keys) == 30
    assert not audit.overlap_keys
    assert not audit.overlap_scene_seeds
    assert training.checkpoint_architecture_revision == "M2C_Q012_V4"
    assert len(s6.keys) == 30


def test_v4_loader_blocks_zero_packages_before_any_training() -> None:
    with pytest.raises(ValueError, match="BLOCKED_ZERO_ELIGIBLE_V4_PACKAGES"):
        load_training_packages_v4(
            [],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )


def test_v4_loader_replays_chain_labels_assets_and_receipts(tmp_path: Path) -> None:
    package = _package(tmp_path)
    samples, report = load_training_packages_v4(
        [package],
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    assert report.status == "PASS_REPLAYED_V4_TRAIN_DATA"
    assert report.rows_total == 8
    assert report.eligible_episodes == 1
    assert [item.decision_index for item in samples] == list(range(8))
    assert [SKILL_LABELS[item.skill_label_index] for item in samples] == [
        item.model_label.skill_type for item in samples
    ]


def test_v4_loader_rejects_dataset_label_asset_and_receipt_tamper(tmp_path: Path) -> None:
    package = _package(tmp_path)
    dataset_path = package / "supervised-steps-v4.json"
    original_dataset = dataset_path.read_bytes()
    dataset = json.loads(original_dataset)
    dataset["samples"][0]["pointer_class_index"] = 8
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(ValueError, match="independently rebuilt labels"):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )

    dataset_path.write_bytes(original_dataset)
    (package / "rgb/3.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="public asset SHA-256 mismatch"):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )

    package = _package(tmp_path / "receipt-case")
    receipt = package / "physical/2.json"
    payload = json.loads(receipt.read_text())
    payload["receipt_id"] = "substituted"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="copied physical receipt differs"):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )

    package = _package(tmp_path / "self-consistent-receipt-case")
    chain_path = package / "packaged-physical-chain-v4.json"
    dataset_path = package / "supervised-steps-v4.json"
    chain = json.loads(chain_path.read_text())
    dataset = json.loads(dataset_path.read_text())
    receipt_path = package / "physical/2.json"
    changed_receipt = json.loads(receipt_path.read_text())
    changed_receipt["execution_measurements"]["test"] = False
    core = {key: value for key, value in changed_receipt.items() if key != "receipt_sha256"}
    changed_receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt_path.write_text(json.dumps(changed_receipt), encoding="utf-8")
    chain["steps"][2]["physical_receipts"][0] = changed_receipt
    chain_path.write_text(json.dumps(chain), encoding="utf-8")
    dataset["samples"][2]["physical_receipt_sha256"] = changed_receipt["receipt_sha256"]
    dataset["dataset_sha256"] = hashlib.sha256(
        "".join(
            json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
            for item in dataset["samples"]
        ).encode()
    ).hexdigest()
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(ValueError, match="independently rebuilt labels"):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )


def test_v4_prompt_binds_exact_candidates_and_executed_prefix(tmp_path: Path) -> None:
    samples, _ = load_training_packages_v4(
        [_package(tmp_path)],
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    histories = index_executed_histories_v4(samples)
    prompt = qwen_coarse_v4_prompt(
        samples[7],
        executed_intent_history=histories[samples[7].sample_id],
        use_failure_context=True,
    )
    assert '"candidate_contract_revision":"PublicTrackCandidateV4"' in prompt
    assert '"checkpoint_architecture_revision":"M2C_Q012_V4"' in prompt
    assert '"failure_type":"PATH_BLOCKED"' in prompt
    assert '"decision_index":6' in prompt
    assert "TaskSpec target identity" in prompt


def test_v4_three_head_contract_smoke_writes_nothing(tmp_path: Path) -> None:
    samples, _ = load_training_packages_v4(
        [_package(tmp_path)],
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    smoke = run_offline_contract_smoke_v4(samples, hidden_size=8, seed=7)
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert before == after
    assert smoke.status == "CONTRACT_SMOKE_PASS_NO_TRAINING"
    assert smoke.optimizer_steps == 0
    assert smoke.checkpoint_written is False
    assert smoke.skill_logits_shape == [len(SKILL_LABELS)]
    assert smoke.pointer_logits_shape == [len(POINTER_LABELS)]
    assert smoke.destination_logits_shape == [len(DESTINATION_LABELS)]


def test_v4_checkpoint_binding_is_exact_and_cross_revision_safe() -> None:
    heads = initialize_numpy_heads_v4(hidden_size=8, seed=7)
    binding = checkpoint_binding_for_numpy_heads_v4(heads)
    validate_head_checkpoint_binding_v4(binding, hidden_size=8)
    assert binding.architecture_revision == "M2C_Q012_V4"
    assert [item.name for item in binding.tensors] == sorted(heads.tensors())

    changed = copy.deepcopy(binding.model_dump(mode="json"))
    changed["tensors"] = changed["tensors"][:-1]
    changed["metadata_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in changed.items() if key != "metadata_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="tensor inventory is not exact"):
        validate_head_checkpoint_binding_v4(
            type(binding).model_validate(changed),
            hidden_size=8,
        )

    logits = heads.logits(np.zeros(8), [True, False, False, False, False, False, False, False])
    assert np.isneginf(logits[1][1:8]).all()
    assert np.isfinite(logits[1][8])
