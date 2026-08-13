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
    load_bundle_v4,
    load_training_packages_v4,
    qwen_coarse_v4_prompt,
    run_offline_contract_smoke_v4,
    validate_head_checkpoint_binding_v4,
    validate_key_manifests_v4,
    write_bundle_manifest_v4,
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
from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    ACCEPTED_ADR_INTRODUCED_COMMIT,
    ACCEPTED_ADR_PATH,
    ACCEPTED_ADR_SHA256,
    CANONICAL_COLLECTION_LEDGER_ROOT,
    FROZEN_UPSTREAM_V4_PROBE_SHA256,
    RUNTIME_REGISTRY_FILE_SHA256,
    S6_MANIFEST_FILE_SHA256,
    V4_MANIFEST_FILE_SHA256,
)


ROOT = Path(__file__).resolve().parents[2]
TRAINING_KEYS = ROOT / "configs/m2c_s4_v4_training_keys.json"
EVALUATION_KEYS = ROOT / "configs/m2c_s6_evaluation_keys.json"


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
    source_snapshot = {
        "commit": "a" * 40,
        "tree": "b" * 40,
        "file_count": 1,
        "total_bytes": 1,
        "inventory_sha256": "c" * 64,
    }
    prereg_path = "docs/decisions/test-v4-prereg.json"
    selected_key = {
        "scene_seed": key.scene_seed,
        "failure_seed": key.failure_seed,
        "matched_key": key.matched_key,
        "sdf_sha256": key.sdf_sha256,
        "supervision_sha256": key.supervision_sha256,
    }
    prereg_core = {
        "schema_version": "M2CS4V4SelectedKeyCollectionPreregV1",
        "status": "FROZEN_BEFORE_ANY_SELECTED_KEY_EXECUTION_OR_RESULT",
        "repository_relative_path": prereg_path,
        "introduction_commit_paths": [prereg_path],
        "batch_id": "m2c-s4-v4-train-batch-99",
        "registered_before_selected_key_execution": True,
        "selected_key_outcome_observed_before_registration": False,
        "governing_adr": {
            "path": ACCEPTED_ADR_PATH,
            "sha256": ACCEPTED_ADR_SHA256,
            "status": "ACCEPTED_HUMAN_ADR",
            "introduced_commit": ACCEPTED_ADR_INTRODUCED_COMMIT,
            "selected_option": "A",
        },
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "candidate_count_bound": 8,
        "recapture_policy": "NONE",
        "training_manifest": {
            "path": "configs/m2c_s4_v4_training_keys.json",
            "sha256": V4_MANIFEST_FILE_SHA256,
        },
        "training_manifest_content_sha256": manifest.manifest_sha256,
        "s6_exclusion_manifest": {
            "path": "configs/m2c_s6_evaluation_keys.json",
            "sha256": S6_MANIFEST_FILE_SHA256,
        },
        "runtime_registry": {
            "path": "configs/qrm_runtime_mapping_v2.yaml",
            "sha256": RUNTIME_REGISTRY_FILE_SHA256,
        },
        "semantic_source_bindings": [],
        "committed_source_snapshot": source_snapshot,
        "prior_attempt_identity_sources": [{"path": "reports/test-prior.json", "sha256": "8" * 64}],
        "container_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
        "container_image_id": (
            "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
        ),
        "upstream_v4_probe_sha256": FROZEN_UPSTREAM_V4_PROBE_SHA256,
        "selection_rule": "manifest_order_first_unattempted_per_sdf_v1",
        "selection_inputs": ["manifest_order", "prior_attempted_identity", "sdf_sha256"],
        "selection_uses_outcomes": False,
        "selected_keys": [selected_key],
        "stop_after_selected_keys": 1,
        "attempt_each_selected_key_at_most_once": True,
        "retry_authorized": False,
        "replacement_authorized": False,
        "ledger_namespace": "M2C_S4_V4_COLLECTION_TEST",
        "ledger_root": CANONICAL_COLLECTION_LEDGER_ROOT,
        "scope": {
            "role": "TRAIN",
            "split": "train",
            "scripted_public_physical_supervision_collection": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "model_rollout": False,
            "training_execution": False,
            "q_b_evaluation": False,
        },
    }
    prereg = {**prereg_core, "prereg_sha256": canonical(prereg_core)}
    prereg_bytes = json.dumps(prereg, sort_keys=True).encode()
    claim_core = {
        "schema_version": "M2CS4V4CollectionConsumptionReceiptV1",
        "event": "CONSUMED_BEFORE_STAGE",
        "ledger_namespace": prereg["ledger_namespace"],
        "ledger_sequence": 0,
        "batch_id": prereg["batch_id"],
        "ordinal": 0,
        "consumption_id": "5" * 64,
        "challenge_nonce": "6" * 64,
        "prereg_repository_path": prereg_path,
        "prereg_file_sha256": hashlib.sha256(prereg_bytes).hexdigest(),
        "prereg_sha256": prereg["prereg_sha256"],
        "prereg_introduced_commit": "3" * 40,
        "selected_key": selected_key,
        "selected_key_sha256": canonical(selected_key),
        "source_sdf_sha256": key.sdf_sha256,
        "source_supervision_sha256": key.supervision_sha256,
        "source_urdf_sha256": "7" * 64,
        "upstream_v4_probe_sha256": FROZEN_UPSTREAM_V4_PROBE_SHA256,
        "committed_source_snapshot": source_snapshot,
        "derived_probe_sha256": "d" * 64,
        "container_image": prereg["container_image"],
        "container_image_id": prereg["container_image_id"],
        "role": "TRAIN",
        "split": "train",
        "declared_target_attribute": "yellow",
        "destination_cell": key.destination_cell,
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "previous_receipt_sha256": None,
        "consumed_at_ns": 1,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "model_rollout": False,
        "training_executed": False,
        "formal_q_b_evaluation": False,
    }
    claim = {**claim_core, "receipt_sha256": canonical(claim_core)}
    claim_bytes = json.dumps(claim, sort_keys=True).encode()
    raw_authorization = {
        "schema_version": "M2CS4V4RawClaimBindingV1",
        "prereg_repository_path": prereg_path,
        "prereg_file_sha256": hashlib.sha256(prereg_bytes).hexdigest(),
        "prereg_sha256": prereg["prereg_sha256"],
        "prereg_introduced_commit": "3" * 40,
        "consumption_receipt_sha256": claim["receipt_sha256"],
        "consumption_id": claim["consumption_id"],
        "challenge_nonce": claim["challenge_nonce"],
        "matched_key": key.matched_key,
        "failure_seed": key.failure_seed,
        "source_sdf_sha256": key.sdf_sha256,
        "source_supervision_sha256": key.supervision_sha256,
        "source_urdf_sha256": "7" * 64,
        "upstream_v4_probe_sha256": FROZEN_UPSTREAM_V4_PROBE_SHA256,
        "committed_source_snapshot": source_snapshot,
        "derived_probe_sha256": "d" * 64,
        "container_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
        "container_image_id": (
            "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
        ),
        "role": "TRAIN",
        "split": "train",
        "declared_target_attribute": "yellow",
        "destination_cell": key.destination_cell,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
    }
    raw_authorization_sha256 = canonical(raw_authorization)
    chain["collection_authorization_sha256"] = raw_authorization_sha256
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
            "actuation_probe_source_sha256": "d" * 64,
            "m2c_v4_collection_authorization": raw_authorization,
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
    console = b"test\n"
    (root / "console.log").write_bytes(console)
    (root / "collection-prereg-v4.json").write_bytes(prereg_bytes)
    (root / "collection-claim-v4.json").write_bytes(claim_bytes)
    for step in evidence.steps:
        receipt = step.physical_receipts[0]
        relative = Path(receipt.receipt_uri.removeprefix("dataset://"))
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(receipt.model_dump_json(), encoding="utf-8")
    (root / "collection-manifest-v4.json").write_bytes(TRAINING_KEYS.read_bytes())
    (root / "s6-exclusion-manifest-v2.json").write_bytes(EVALUATION_KEYS.read_bytes())
    authorization_core = {
        "schema_version": "M2CS4V4PackagedClaimBindingV1",
        "raw_claim_binding_sha256": raw_authorization_sha256,
        "raw_probe_sha256": hashlib.sha256(raw_source).hexdigest(),
        "console_sha256": hashlib.sha256(console).hexdigest(),
        "consumption_receipt_sha256": raw_authorization["consumption_receipt_sha256"],
        "consumption_id": raw_authorization["consumption_id"],
        "matched_key": key.matched_key,
        "committed_source_snapshot": source_snapshot,
        "container_image_id": raw_authorization["container_image_id"],
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
    }
    packaged_authorization = {
        **authorization_core,
        "receipt_sha256": canonical(authorization_core),
    }
    copied_assets = {
        f"{step.decision_index}:{kind}": digest
        for step in evidence.steps
        for kind, digest in (
            ("rgb", step.observation.rgb_sha256),
            ("depth", step.observation.depth_sha256),
        )
    }
    copied_receipts = {}
    for step in evidence.steps:
        receipt = step.physical_receipts[0]
        relative = Path(receipt.receipt_uri.removeprefix("dataset://"))
        copied_receipts[str(step.decision_index)] = {
            "path": str(relative),
            "file_sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest(),
            "canonical_receipt_sha256": receipt.receipt_sha256,
        }
    chain_bytes = (root / "packaged-physical-chain-v4.json").read_bytes()
    dataset_bytes = (root / "supervised-steps-v4.json").read_bytes()
    collection_receipt = {
        "schema_version": "M2CPathBlockedCollectionReceiptV4",
        "status": "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
        "matched_key": key.matched_key,
        "scene_seed": key.scene_seed,
        "failure_seed": key.failure_seed,
        "split": "train",
        "collection_role": "TRAIN",
        "decision_source": "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
        "model_owned": False,
        "model_rollout": False,
        "formal_q_b_evaluation": False,
        "pure_model_success_evidence": False,
        "physical_chain_steps": 8,
        "physical_receipts": 8,
        "fresh_public_rgbd_observations": 8,
        "copied_public_assets": copied_assets,
        "physical_receipt_files": copied_receipts,
        "raw_probe_sha256": hashlib.sha256(raw_source).hexdigest(),
        "console_file_sha256": hashlib.sha256(console).hexdigest(),
        "packaged_physical_chain_sha256": hashlib.sha256(chain_bytes).hexdigest(),
        "supervised_dataset_file_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_sha256": dataset.dataset_sha256,
        "collection_manifest_sha256": manifest.manifest_sha256,
        "collection_manifest_file_sha256": hashlib.sha256(TRAINING_KEYS.read_bytes()).hexdigest(),
        "candidate_contract_revision": "PublicTrackCandidateV4",
        "checkpoint_architecture_revision": "M2C_Q012_V4",
        "s6_exclusion_manifest_sha256": canonical(s6.model_dump(mode="json")),
        "frozen_training_key_manifest_file_sha256": hashlib.sha256(
            TRAINING_KEYS.read_bytes()
        ).hexdigest(),
        "frozen_s6_key_manifest_file_sha256": hashlib.sha256(
            EVALUATION_KEYS.read_bytes()
        ).hexdigest(),
        "runtime_registry_sha256": "e" * 64,
        "executing_probe_source_sha256": "d" * 64,
        "derived_probe_file_sha256": raw_authorization["derived_probe_sha256"],
        "frozen_upstream_v4_probe_sha256": FROZEN_UPSTREAM_V4_PROBE_SHA256,
        "sdf_sha256": key.sdf_sha256,
        "supervision_sha256": key.supervision_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "checkpoint_path": None,
        "checkpoint_sha256": None,
        "training_executed": False,
        "evaluation_executed": False,
        "collection_authorization": packaged_authorization,
    }
    (root / "collection-receipt-v4.json").write_text(json.dumps(collection_receipt))
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


@pytest.mark.parametrize(
    ("relative_path", "mutate", "message"),
    [
        (
            "collection-receipt-v4.json",
            lambda payload: payload["collection_authorization"].__setitem__(
                "console_sha256", "0" * 64
            ),
            "canonical digest mismatch",
        ),
        (
            "collection-receipt-v4.json",
            lambda payload: payload.__setitem__("runtime_registry_sha256", "0" * 64),
            "collection receipt differs",
        ),
        (
            "actuation-probe.json",
            lambda payload: payload.__setitem__("actuation_probe_source_sha256", "0" * 64),
            "source evidence SHA-256 differs",
        ),
    ],
)
def test_v4_loader_rejects_collection_receipt_and_source_closure_tamper(
    tmp_path: Path,
    relative_path: str,
    mutate: object,
    message: str,
) -> None:
    package = _package(tmp_path)
    path = package / relative_path
    payload = json.loads(path.read_text())
    mutate(payload)  # type: ignore[operator]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=message):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )


def test_v4_loader_rejects_console_and_claim_projection_tamper(tmp_path: Path) -> None:
    package = _package(tmp_path / "console")
    (package / "console.log").write_text("substituted\n")
    with pytest.raises(ValueError, match="collection authorization differs"):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )

    package = _package(tmp_path / "claim-file")
    claim_path = package / "collection-claim-v4.json"
    claim = json.loads(claim_path.read_text())
    claim["challenge_nonce"] = "0" * 64
    claim_core = {key: value for key, value in claim.items() if key != "receipt_sha256"}
    claim["receipt_sha256"] = canonical(claim_core)
    claim_path.write_text(json.dumps(claim))
    with pytest.raises(ValueError, match="collection authorization differs"):
        load_training_packages_v4(
            [package],
            training_manifest_path=TRAINING_KEYS,
            evaluation_manifest_path=EVALUATION_KEYS,
        )

    package = _package(tmp_path / "claim")
    source_path = package / "actuation-probe.json"
    source = json.loads(source_path.read_text())
    source["m2c_v4_collection_authorization"]["challenge_nonce"] = "0" * 64
    source_path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="source evidence SHA-256 differs"):
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


def test_v4_bundle_round_trip_binds_adapter_heads_data_and_s6(tmp_path: Path) -> None:
    samples, report = load_training_packages_v4(
        [_package(tmp_path / "evidence")],
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    output = tmp_path / "trained"
    adapter = output / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter_model.safetensors").write_bytes(b"fixture-adapter")
    heads = initialize_numpy_heads_v4(hidden_size=8, seed=7)
    manifest = write_bundle_manifest_v4(
        output,
        heads=heads,
        model_id="Qwen/Qwen3.5-2B",
        model_revision="frozen-revision",
        base_model_snapshot_tree_sha256="a" * 64,
        failure_context="on",
        dataset_report=report,
        seed=7,
        optimizer_steps=len(samples),
    )
    loaded = load_bundle_v4(output, expected_bundle_sha256=manifest.bundle_sha256)
    assert loaded.manifest.training_dataset_sha256 == report.combined_dataset_sha256
    assert loaded.manifest.base_model_snapshot_tree_sha256 == "a" * 64
    assert loaded.manifest.training_dataset_report_sha256 == canonical(
        report.model_dump(mode="json")
    )
    assert loaded.manifest.train_samples == 8
    assert np.array_equal(loaded.heads.skill_w, heads.skill_w)

    (adapter / "adapter_model.safetensors").write_bytes(b"substituted")
    with pytest.raises(ValueError, match="adapter tree SHA-256 mismatch"):
        load_bundle_v4(output, expected_bundle_sha256=manifest.bundle_sha256)


def test_v4_bundle_rejects_training_dataset_report_substitution(tmp_path: Path) -> None:
    _, report = load_training_packages_v4(
        [_package(tmp_path / "evidence")],
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    output = tmp_path / "trained"
    adapter = output / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter.json").write_text("{}")
    manifest = write_bundle_manifest_v4(
        output,
        heads=initialize_numpy_heads_v4(hidden_size=8, seed=7),
        model_id="Qwen/Qwen3.5-2B",
        model_revision="frozen-revision",
        base_model_snapshot_tree_sha256="a" * 64,
        failure_context="on",
        dataset_report=report,
        seed=7,
        optimizer_steps=8,
    )
    report_path = output / manifest.training_dataset_report_relative_path
    payload = json.loads(report_path.read_text())
    payload["packages"][0]["collection_receipt_file_sha256"] = "0" * 64
    report_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="dataset report file SHA-256 mismatch"):
        load_bundle_v4(output, expected_bundle_sha256=manifest.bundle_sha256)


def test_v4_bundle_refuses_zero_step_and_external_digest_substitution(tmp_path: Path) -> None:
    _, report = load_training_packages_v4(
        [_package(tmp_path / "evidence")],
        training_manifest_path=TRAINING_KEYS,
        evaluation_manifest_path=EVALUATION_KEYS,
    )
    output = tmp_path / "trained"
    adapter = output / "adapter"
    adapter.mkdir(parents=True)
    (adapter / "adapter.json").write_text("{}")
    heads = initialize_numpy_heads_v4(hidden_size=8, seed=7)
    with pytest.raises(ValueError, match="at least one optimizer step"):
        write_bundle_manifest_v4(
            output,
            heads=heads,
            model_id="Qwen/Qwen3.5-2B",
            model_revision="frozen-revision",
            base_model_snapshot_tree_sha256="a" * 64,
            failure_context="off",
            dataset_report=report,
            seed=7,
            optimizer_steps=0,
        )
    with pytest.raises(ValueError, match="snapshot tree SHA-256 is malformed"):
        write_bundle_manifest_v4(
            output,
            heads=heads,
            model_id="Qwen/Qwen3.5-2B",
            model_revision="frozen-revision",
            base_model_snapshot_tree_sha256="not-a-digest",
            failure_context="off",
            dataset_report=report,
            seed=7,
            optimizer_steps=8,
        )
    manifest = write_bundle_manifest_v4(
        output,
        heads=heads,
        model_id="Qwen/Qwen3.5-2B",
        model_revision="frozen-revision",
        base_model_snapshot_tree_sha256="a" * 64,
        failure_context="off",
        dataset_report=report,
        seed=7,
        optimizer_steps=8,
    )
    with pytest.raises(ValueError, match="external expected digest"):
        load_bundle_v4(output, expected_bundle_sha256="0" * 64)
    assert manifest.physical_evaluation_executed is False
    assert manifest.teacher_used is False
