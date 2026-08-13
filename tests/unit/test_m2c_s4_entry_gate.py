from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from m2c.qwen_coarse_v2 import (
    BUNDLE_MANIFEST_NAME,
    HEAD_CHECKPOINT_NAME,
    KeyManifestAudit,
    DatasetLoadReport,
    build_head_metadata,
    initialize_numpy_heads,
    save_head_checkpoint,
    write_bundle_manifest,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import EXPECTED_PATH_BLOCKED_CHAIN
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import ModelOwnedChainEpisodeV2
from xh_agent.policy.qrm_lite.models_q012 import FormalModelId
from xh_agent.policy.qrm_lite.models_q012_v2 import (
    build_formal_model_v2,
    save_formal_checkpoint_v2,
)
from xh_agent.policy.qrm_lite.s4_entry_gate import (
    ADR_IMPLEMENTATION_COMMIT,
    B0_FREEZE_SHA256,
    FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256,
    FROZEN_EVALUATION_MANIFEST_FILE_SHA256,
    FROZEN_EVALUATION_MANIFEST_PATH,
    FROZEN_KEY_MANIFEST_COMMIT,
    FROZEN_KEY_MANIFEST_CONTENT_SHA256,
    FROZEN_KEY_MANIFEST_FILE_SHA256,
    FROZEN_KEY_MANIFEST_PATH,
    FROZEN_WIRE_CHALLENGE_MANIFEST_PATH,
    LOCAL_TEST_NODE_IDS,
    QWEN_HIDDEN_SIZE,
    QWEN_MODEL_ID,
    QWEN_MODEL_REVISION,
    RUNTIME_BINDINGS,
    _commit_binding_blockers,
    canonical_qwen_head_tensor_hashes,
    evaluate_s4_entry_gate,
)


ROOT = Path(__file__).resolve().parents[2]
BLOCKER = "track-public-blocker"
TARGET = "track-public-task-target"


@pytest.fixture(autouse=True)
def _future_reviewed_implementation_commit(monkeypatch):
    """Exercise downstream gates as if the current shared files were committed.

    Production code still inspects the real commit.  The separate test below
    proves that the historical key-freeze commit cannot satisfy that check.
    """

    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_entry_gate._commit_binding_blockers",
        lambda _root, _commit: [],
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _head() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _local_receipt(path: Path, *, commit: str = FROZEN_KEY_MANIFEST_COMMIT) -> None:
    _write(
        path,
        {
            "schema_version": "M2CS4LocalContractTestReceiptV2",
            "evidence_origin": "LOCAL_CONTRACT_TESTS",
            "command": ["python", "-m", "pytest", "-q", *LOCAL_TEST_NODE_IDS],
            "node_ids": list(LOCAL_TEST_NODE_IDS),
            "exit_code": 0,
            "tests_passed": 83,
            "tests_failed": 0,
            "tests_skipped": 0,
            "checked_implementation_commit": commit,
            "runtime_binding_sha256": RUNTIME_BINDINGS,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        },
    )


def _episode() -> dict[str, object]:
    decisions: list[dict[str, object]] = []
    previous_completed = 100
    for index, skill in enumerate(EXPECTED_PATH_BLOCKED_CHAIN):
        observation_time = previous_completed + 10
        started = observation_time + 10
        completed = started + 10
        tracks = [BLOCKER, TARGET, "track-public-other"]
        slots = sorted(tracks)
        if index <= 4:
            target = BLOCKER
            pointer = slots.index(BLOCKER)
            target_provenance = "MODEL"
        elif index >= 6:
            target = TARGET
            pointer = slots.index(TARGET)
            target_provenance = "MODEL"
        else:
            target = None
            pointer = 8
            target_provenance = "NONE"
        destination_required = index in {2, 3}
        decisions.append(
            {
                "decision_id": f"physical-decision-{index}",
                "step_index": index,
                "observation": {
                    "observation_id": f"physical-observation-{index}",
                    "captured_at_ns": observation_time,
                    "rgb_sha256": f"{index + 101:064x}",
                    "depth_sha256": f"{index + 201:064x}",
                    "source": "PUBLIC_RGBD",
                    "fresh": True,
                    "perception_track_ids": tracks,
                    "pointer_slots": slots,
                    "blocker_track_id": BLOCKER,
                    "task_target_track_id": TARGET,
                    "teacher_used": False,
                    "privileged_truth_policy_input": False,
                },
                "model_output_sha256": f"{index + 301:064x}",
                "selected_skill": skill,
                "skill_provenance": "MODEL",
                "target_track_id": target,
                "target_pointer_class": pointer,
                "target_provenance": target_provenance,
                "destination_cell": "BIN_CELL_3" if destination_required else None,
                "destination_class": 3 if destination_required else 6,
                "destination_provenance": "MODEL" if destination_required else "NONE",
                "mapping_status": "VALID",
                "physical_skill_receipts": [
                    {
                        "receipt_id": f"physical-receipt-{index}",
                        "receipt_sha256": f"{index + 401:064x}",
                        "executed_skill": skill,
                        "execution_source": "MODEL_SELECTED_REGISTERED_SKILL",
                        "physically_executed": True,
                        "started_at_ns": started,
                        "completed_at_ns": completed,
                        "schema_gate": "PASS",
                        "stale_track_gate": "PASS",
                        "frame_unit_gate": "PASS",
                        "ik_gate": "PASS",
                        "collision_gate": "PASS",
                        "controller_gate": "PASS",
                        "safety_gate": "PASS",
                        "teacher_used": False,
                        "privileged_truth_policy_input": False,
                    }
                ],
            }
        )
        previous_completed = completed
    return {
        "schema_version": "ModelOwnedChainEpisodeV2",
        "episode_id": "physical-frozen-smoke-chain",
        "failure_type": "PATH_BLOCKED",
        "failure_observed_at_ns": 100,
        "final_task_success": True,
        "decisions": decisions,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }


def _trained_world_model_bundle(tmp_path: Path) -> dict[str, object]:
    dataset = tmp_path / "supervised-steps-v2.jsonl"
    dataset.write_text('{"public_training_row":true}\n')
    dataset_manifest = tmp_path / "supervised-dataset-v2.json"
    _write(dataset_manifest, {"status": "PASS", "teacher_used": False})
    dataset_sha = _sha256(dataset)
    dataset_manifest_sha = _sha256(dataset_manifest)
    heads = initialize_numpy_heads(QWEN_HIDDEN_SIZE, seed=20260812)
    metadata = build_head_metadata(
        model_id=QWEN_MODEL_ID,
        model_revision=QWEN_MODEL_REVISION,
        hidden_size=QWEN_HIDDEN_SIZE,
        failure_context="on",
        dataset_sha256=dataset_sha,
        dataset_manifest_sha256=dataset_manifest_sha,
        training_manifest_sha256=FROZEN_KEY_MANIFEST_FILE_SHA256,
        evaluation_manifest_sha256=FROZEN_EVALUATION_MANIFEST_FILE_SHA256,
        seed=20260812,
        initialization_source="NONE",
    )
    bundle_root = tmp_path / "qwen-bundle"
    bundle_root.mkdir()
    save_head_checkpoint(bundle_root / HEAD_CHECKPOINT_NAME, heads, metadata)
    adapter = bundle_root / "adapter"
    adapter.mkdir()
    _write(adapter / "adapter_config.json", {"peft_type": "LORA", "r": 8})
    (adapter / "adapter_model.safetensors").write_bytes(b"fixture-adapter-weights")
    bundle = write_bundle_manifest(
        bundle_root,
        status="TRAINED_QWEN_LORA_THREE_HEADS",
    )
    audit = KeyManifestAudit(
        training_manifest_sha256=FROZEN_KEY_MANIFEST_FILE_SHA256,
        evaluation_manifest_sha256=FROZEN_EVALUATION_MANIFEST_FILE_SHA256,
        training_keys=["fixture-train-key"],
        smoke_keys=["fixture-smoke-key"],
        evaluation_keys=["fixture-evaluation-key"],
        v4_excluded_keys=["fixture-v4-key"],
    )
    dataset_report = DatasetLoadReport(
        dataset_sha256=dataset_sha,
        rows_total=8,
        rows_eligible=8,
        rows_excluded=0,
        eligible_episodes=1,
        split_counts={"train": 8, "val": 0},
        exclusion_reason_histogram={},
        dataset_manifest_path=str(dataset_manifest),
        dataset_manifest_sha256=dataset_manifest_sha,
        dataset_manifest_status="PASS",
        key_manifest_audit=audit,
    )
    report = {
        "schema_version": "M2CQwenCoarseV2TrainReportV1",
        "status": "PASS_TRAINED_QWEN_LORA_THREE_HEADS_NOT_PHYSICAL_EVALUATION",
        "model_id": QWEN_MODEL_ID,
        "model_revision": QWEN_MODEL_REVISION,
        "failure_context": "on",
        "seed": 20260812,
        "n_train": 8,
        "optimizer_steps": 8,
        "initialization_source": "NONE",
        "initialization_adapter_sha256": None,
        "adapter_source_architecture_revision": None,
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "dataset_report": dataset_report.model_dump(mode="json"),
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "flow_status": "DISABLED",
        "physical_evaluation_executed": False,
    }
    _write(bundle_root / "train_report.json", report)
    return {
        "schema_version": "M2CS4QwenWorldModelBundleReceiptV1",
        "bundle_root": str(bundle_root),
        "bundle_manifest_sha256": _sha256(bundle_root / BUNDLE_MANIFEST_NAME),
        "train_report_sha256": _sha256(bundle_root / "train_report.json"),
        "head_checkpoint_sha256": bundle.head_checkpoint_sha256,
        "adapter_tree_sha256": bundle.adapter_tree_sha256,
        "head_tensor_sha256": canonical_qwen_head_tensor_hashes(heads),
        "metadata_sha256": _canonical_sha256(metadata.model_dump(mode="json")),
        "architecture_revision": "M2C_Q012_V2",
        "model_id": QWEN_MODEL_ID,
        "model_revision": QWEN_MODEL_REVISION,
        "failure_context": "on",
        "hidden_size": QWEN_HIDDEN_SIZE,
        "seed": 20260812,
        "initialization_source": "NONE",
        "initialization_adapter_sha256": None,
        "adapter_source_architecture_revision": None,
        "dataset_path": str(dataset),
        "dataset_sha256": dataset_sha,
        "dataset_manifest_path": str(dataset_manifest),
        "dataset_manifest_sha256": dataset_manifest_sha,
        "training_key_manifest_path": FROZEN_KEY_MANIFEST_PATH,
        "training_key_manifest_file_sha256": FROZEN_KEY_MANIFEST_FILE_SHA256,
        "training_key_manifest_content_sha256": FROZEN_KEY_MANIFEST_CONTENT_SHA256,
        "evaluation_key_manifest_path": FROZEN_EVALUATION_MANIFEST_PATH,
        "evaluation_key_manifest_file_sha256": (FROZEN_EVALUATION_MANIFEST_FILE_SHA256),
        "evaluation_key_manifest_content_sha256": (FROZEN_EVALUATION_MANIFEST_CONTENT_SHA256),
        "world_model_mainline": True,
        "structured_q012_control_policy": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "flow_status": "DISABLED",
        "physical_evaluation_executed_by_training": False,
    }


def _physical_receipt(tmp_path: Path) -> Path:
    manifest = json.loads((ROOT / FROZEN_KEY_MANIFEST_PATH).read_text())
    b0_freeze = json.loads((ROOT / "configs/m2c_b0_freeze.json").read_text())
    key = manifest["physical_prerequisite_smoke_keys"][0]
    challenge_manifest = json.loads((ROOT / FROZEN_WIRE_CHALLENGE_MANIFEST_PATH).read_text())
    challenge = next(
        item
        for item in challenge_manifest["challenge_records"]
        if item["matched_key"] == key["matched_key"]
    )
    episode = ModelOwnedChainEpisodeV2.model_validate(_episode()).model_dump(mode="json")
    runner = tmp_path / "formal-qwen-isaac-runner.py"
    runner.write_text("# reviewed fixture runner bytes\n")
    arbitrary_evidence = tmp_path / "arbitrary-formal-evidence.json"
    _write(arbitrary_evidence, {"claimed_complete": True, "episode": episode})
    arbitrary_node2_auth = tmp_path / "arbitrary-node2-authentication.json"
    _write(arbitrary_node2_auth, {"claimed_hmac_valid": True})
    arbitrary_labserver_auth = tmp_path / "arbitrary-labserver-authentication.json"
    _write(arbitrary_labserver_auth, {"claimed_hmac_valid": True})
    arbitrary_qwen_audit = tmp_path / "arbitrary-qwen-audit.jsonl"
    arbitrary_qwen_audit.write_text('{"claimed_qwen":true}\n')
    arbitrary_session_audit = tmp_path / "arbitrary-session-audit.jsonl"
    arbitrary_session_audit.write_text('{"claimed_append_only":true}\n')
    arbitrary_service_audit = tmp_path / "arbitrary-service-audit.jsonl"
    arbitrary_service_audit.write_text('{"claimed_service":true}\n')
    import_manifest = tmp_path / "arbitrary-import-closure.json"
    _write(import_manifest, {"claimed_complete": True})
    payload = {
        "schema_version": "M2CS4PhysicalIntegrationReceiptV2",
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "execution_mode": "REAL_PHYSICS_NO_MOCKS",
        "test_model_provenance": "M2C_QWEN_V2_WORLD_MODEL_BUNDLE",
        "host": "labserver",
        "run_id": challenge["run_id"],
        "challenge_nonce": challenge["challenge_nonce"],
        "collected_at_ns": 10_000,
        "matched_key": key["matched_key"],
        "scene_seed": key["scene_seed"],
        "failure_seed": key["failure_seed"],
        "sdf_sha256": key["sdf_sha256"],
        "supervision_sha256": key["supervision_sha256"],
        "key_manifest_commit": FROZEN_KEY_MANIFEST_COMMIT,
        "key_manifest_file_sha256": FROZEN_KEY_MANIFEST_FILE_SHA256,
        "key_manifest_content_sha256": FROZEN_KEY_MANIFEST_CONTENT_SHA256,
        "adr_implementation_commit": ADR_IMPLEMENTATION_COMMIT,
        "checked_implementation_commit": FROZEN_KEY_MANIFEST_COMMIT,
        "runtime_binding_sha256": RUNTIME_BINDINGS,
        "b0_freeze_sha256": B0_FREEZE_SHA256,
        "runner_implementation_path": str(runner),
        "runner_implementation_sha256": _sha256(runner),
        "deployment_closure": {
            "schema_version": "M2CFormalDeploymentClosureReceiptV1",
            "implementation_commit": _head(),
            "container_image_digest": "sha256:" + "d" * 64,
            "transitive_import_manifest_path": str(import_manifest),
            "transitive_import_manifest_sha256": _sha256(import_manifest),
            "invalid_or_rejected_action_policy": "TERMINAL_NO_PHYSICAL_EXECUTION",
            "b0_runtime_wrapper_present": False,
            "b0_runtime_fallback_invocation_allowed": False,
            "b0_comparison_freeze_manifest_sha256": B0_FREEZE_SHA256,
            "b0_comparison_freeze_file_bindings": {
                item["path"]: item["sha256"] for item in b0_freeze["b0_files"]
            },
            "backend_reimplements_b0_fallback": False,
            "teacher_used": False,
        },
        "world_model_bundle": _trained_world_model_bundle(tmp_path),
        "formal_runner_evidence_path": str(arbitrary_evidence),
        "formal_runner_evidence_sha256": _sha256(arbitrary_evidence),
        "node2_wire_authentication_receipt_path": str(arbitrary_node2_auth),
        "node2_wire_authentication_receipt_sha256": _sha256(arbitrary_node2_auth),
        "labserver_wire_authentication_receipt_path": str(arbitrary_labserver_auth),
        "labserver_wire_authentication_receipt_sha256": _sha256(arbitrary_labserver_auth),
        "qwen_service_audit_path": str(arbitrary_qwen_audit),
        "qwen_service_audit_sha256": _sha256(arbitrary_qwen_audit),
        "isaac_session_audit_path": str(arbitrary_session_audit),
        "isaac_session_audit_sha256": _sha256(arbitrary_session_audit),
        "isaac_service_audit_path": str(arbitrary_service_audit),
        "isaac_service_audit_sha256": _sha256(arbitrary_service_audit),
        "episode": episode,
        "synthetic": False,
        "mocked_physics": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    path = tmp_path / "physical-receipt.json"
    _write(path, payload)
    return path


def test_no_physical_receipt_blocks_evaluation_but_not_adr_training(tmp_path: Path) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    result = evaluate_s4_entry_gate(ROOT, local_receipt_path=local)
    assert result["local_contract_tests_passed"] is True
    assert result["physical_integration_receipt_passed"] is False
    assert result["formal_q_b_evaluation_authorized"] is False
    assert result["training_authorized_by_adr"] is True
    assert result["training_requires_physical_integration_receipt"] is False
    assert result["q_b_training_executed_by_this_gate"] is False
    assert result["q_b_evaluation_executed_by_this_gate"] is False
    assert result["world_model_mainline_required"] is True
    assert result["structured_q012_checkpoint_accepted_as_world_model"] is False


def test_bare_unit_journal_or_structured_q012_cannot_masquerade(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    bare = tmp_path / "bare-unit-journal.json"
    _write(bare, _episode())
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=bare,
    )
    assert result["physical_integration"]["status"] == "INVALID"
    assert result["formal_q_b_evaluation_authorized"] is False

    structured = tmp_path / "structured-q0.npz"
    save_formal_checkpoint_v2(structured, build_formal_model_v2(FormalModelId.Q0))
    disguised = {
        "schema_version": "M2CS4PhysicalIntegrationReceiptV2",
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "test_model_provenance": "M2C_Q012_V2_CHECKPOINT",
        "checkpoint": {"checkpoint_path": str(structured)},
        "episode": _episode(),
    }
    _write(bare, disguised)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=bare,
    )
    assert result["physical_integration"]["status"] == "INVALID"
    assert result["structured_q012_checkpoint_accepted_as_world_model"] is False
    assert any("physical integration receipt invalid" in item for item in result["blockers"])


def test_arbitrary_hash_files_cannot_pass_even_if_runner_binding_is_patched(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    physical = _physical_receipt(tmp_path)
    runner = json.loads(physical.read_text())
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_entry_gate.FORMAL_PHYSICAL_RUNNER_BINDING",
        (
            runner["runner_implementation_path"],
            runner["runner_implementation_sha256"],
        ),
    )
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["status"] == "BLOCKED_FORMAL_Q_B_EVALUATION"
    assert result["local_contract_tests_passed"] is True
    assert result["physical_integration_receipt_passed"] is False
    assert result["formal_q_b_evaluation_authorized"] is False
    assert any(
        "formal physical evidence replay failed closed" in item for item in result["blockers"]
    )


def test_missing_formal_runner_freeze_blocks_even_complete_bundle(tmp_path: Path) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    physical = _physical_receipt(tmp_path)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["formal_q_b_evaluation_authorized"] is False
    assert result["physical_integration"]["world_model_bundle_verified"] is True
    assert any(
        "formal Qwen-to-Isaac runner is not independently reviewed, "
        "real-Isaac contract-verified, and frozen" in item
        for item in result["blockers"]
    )
    assert any("transitive-import closure" in item for item in result["blockers"])
    assert any("consumption ledger" in item for item in result["blockers"])


def test_adr0024_withdrawn_b0_and_signing_sentinels_are_not_source_blockers() -> None:
    blockers = __import__(
        "xh_agent.policy.qrm_lite.s4_entry_gate",
        fromlist=["_formal_source_unlock_blockers"],
    )._formal_source_unlock_blockers()

    assert not any("B0 wrapper" in item or "B0 fallback" in item for item in blockers)
    assert not any(
        "signing-key custody" in item or "public trust root" in item for item in blockers
    )


def test_implementation_commit_may_be_ancestor_but_must_exist(tmp_path: Path) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local, commit=FROZEN_KEY_MANIFEST_COMMIT)
    result = evaluate_s4_entry_gate(ROOT, local_receipt_path=local)
    assert result["local_contract_tests_passed"] is True
    descendant = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert (
        subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "merge-base",
                "--is-ancestor",
                result["local_contract_tests"]["checked_implementation_commit"],
                descendant,
            ],
            check=False,
        ).returncode
        == 0
    )

    _local_receipt(local, commit="0" * 40)
    result = evaluate_s4_entry_gate(ROOT, local_receipt_path=local)
    assert result["local_contract_tests_passed"] is False
    assert any("cannot be resolved" in item for item in result["blockers"])


def test_historical_key_commit_lacks_qwen_runtime_bindings(monkeypatch) -> None:
    monkeypatch.undo()
    blockers = _commit_binding_blockers(ROOT, FROZEN_KEY_MANIFEST_COMMIT)
    assert any("scripts/m2c/qwen_coarse_v2.py" in item for item in blockers)
    assert any("scripts/m2c/train_qwen_coarse_v2.py" in item for item in blockers)


def test_non_smoke_key_and_teacher_or_privileged_flags_fail_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    physical = _physical_receipt(tmp_path)
    runner = json.loads(physical.read_text())
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_entry_gate.FORMAL_PHYSICAL_RUNNER_BINDING",
        (
            runner["runner_implementation_path"],
            runner["runner_implementation_sha256"],
        ),
    )
    original = json.loads(physical.read_text())
    non_smoke = deepcopy(original)
    non_smoke["matched_key"] = "m2c-s4-s6-not-frozen"
    _write(physical, non_smoke)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["formal_q_b_evaluation_authorized"] is False
    assert any("not exactly one frozen SMOKE key" in item for item in result["blockers"])

    for field in ("teacher_used", "privileged_truth_policy_input"):
        poisoned = deepcopy(original)
        poisoned[field] = True
        poison_path = tmp_path / f"poison-{field}.json"
        _write(poison_path, poisoned)
        result = evaluate_s4_entry_gate(
            ROOT,
            local_receipt_path=local,
            physical_receipt_path=poison_path,
        )
        assert result["formal_q_b_evaluation_authorized"] is False
        assert result["physical_integration"]["status"] == "INVALID"


def test_wire_challenge_must_match_preregistered_run_and_key(tmp_path: Path) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    physical = _physical_receipt(tmp_path)
    payload = json.loads(physical.read_text())
    payload["challenge_nonce"] = "0" * 64
    _write(physical, payload)

    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )

    assert result["formal_q_b_evaluation_authorized"] is False
    assert any("preregistered wire challenge" in item for item in result["blockers"])


def test_runtime_binding_or_bundle_hash_drift_blocks(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    payload = json.loads(local.read_text())
    payload["runtime_binding_sha256"] = {**RUNTIME_BINDINGS, "extra": "f" * 64}
    _write(local, payload)
    result = evaluate_s4_entry_gate(ROOT, local_receipt_path=local)
    assert result["local_contract_tests"]["status"] == "INVALID"

    _local_receipt(local)
    bundle_root = tmp_path / "bundle-drift"
    bundle_root.mkdir()
    physical = _physical_receipt(bundle_root)
    runner = json.loads(physical.read_text())
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_entry_gate.FORMAL_PHYSICAL_RUNNER_BINDING",
        (
            runner["runner_implementation_path"],
            runner["runner_implementation_sha256"],
        ),
    )
    payload = json.loads(physical.read_text())
    payload["world_model_bundle"]["adapter_tree_sha256"] = "0" * 64
    _write(physical, payload)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["formal_q_b_evaluation_authorized"] is False
    assert any("adapter tree SHA-256" in item for item in result["blockers"])


def test_entry_receipt_rejects_m2b_initialized_world_model(tmp_path: Path) -> None:
    physical = _physical_receipt(tmp_path)
    payload = json.loads(physical.read_text())
    payload["world_model_bundle"].update(
        initialization_source="M2B_ADAPTER_INITIALIZATION_ONLY",
        initialization_adapter_sha256="a" * 64,
        adapter_source_architecture_revision="M2B_Q012_V1",
    )
    _write(physical, payload)

    result = evaluate_s4_entry_gate(ROOT, physical_receipt_path=physical)

    assert result["physical_integration"]["status"] == "INVALID"
    assert result["formal_q_b_evaluation_authorized"] is False


def test_duplicate_receipt_or_head_tensor_hash_blocks_physical_layer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    physical = _physical_receipt(tmp_path)
    runner = json.loads(physical.read_text())
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_entry_gate.FORMAL_PHYSICAL_RUNNER_BINDING",
        (
            runner["runner_implementation_path"],
            runner["runner_implementation_sha256"],
        ),
    )
    original = json.loads(physical.read_text())
    duplicate = deepcopy(original)
    first = duplicate["episode"]["decisions"][0]["physical_skill_receipts"][0]
    second = duplicate["episode"]["decisions"][1]["physical_skill_receipts"][0]
    second["receipt_sha256"] = first["receipt_sha256"]
    _write(physical, duplicate)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["formal_q_b_evaluation_authorized"] is False
    assert any("PHYSICAL_RECEIPT_REUSED" in item for item in result["blockers"])

    bad_head = deepcopy(original)
    bad_head["world_model_bundle"]["head_tensor_sha256"]["pointer_w"] = "0" * 64
    _write(physical, bad_head)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["formal_q_b_evaluation_authorized"] is False
    assert any("tensor hashes differ" in item for item in result["blockers"])


def test_offline_smoke_bundle_cannot_replace_trained_qwen_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local = tmp_path / "local.json"
    _local_receipt(local)
    physical = _physical_receipt(tmp_path)
    runner = json.loads(physical.read_text())
    monkeypatch.setattr(
        "xh_agent.policy.qrm_lite.s4_entry_gate.FORMAL_PHYSICAL_RUNNER_BINDING",
        (
            runner["runner_implementation_path"],
            runner["runner_implementation_sha256"],
        ),
    )
    payload = json.loads(physical.read_text())
    bundle_root = Path(payload["world_model_bundle"]["bundle_root"])
    manifest_path = bundle_root / BUNDLE_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "OFFLINE_SMOKE_ONLY_NOT_QB_EVALUATION"
    manifest["adapter_path"] = None
    manifest["adapter_tree_sha256"] = None
    _write(manifest_path, manifest)
    payload["world_model_bundle"]["bundle_manifest_sha256"] = _sha256(manifest_path)
    _write(physical, payload)
    result = evaluate_s4_entry_gate(
        ROOT,
        local_receipt_path=local,
        physical_receipt_path=physical,
    )
    assert result["formal_q_b_evaluation_authorized"] is False
    assert any("offline smoke bundle" in item for item in result["blockers"])
