from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from m2c.train_qwen_coarse_v4 import _require_phase2_training_bindings
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    canonical_json_bytes,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.phase2_source_binding_closure_v1 import (
    Phase2SourceBindingClosureReceiptV1,
    Phase2SourceBindingClosureRequestV1,
)
from xh_agent.policy.qrm_lite.s4_entry_gate import (
    FORMAL_DEPLOYMENT_CLOSURE_BINDING,
    FORMAL_PHYSICAL_RUNNER_BINDING,
    FROZEN_B0_RUNTIME_WRAPPER_BINDING,
    OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING,
    FormalTransitiveImportClosureManifestV1,
    _formal_source_unlock_blockers,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/m2c_s4_unlock_bindings.json"
REPORT_PATH = ROOT / "reports/m2c-phase2-source-binding-application.json"
IMPLEMENTATION_COMMIT = "3b86d4c997a6e2a7229c6e8149200b166fa32d77"
IMPLEMENTATION_TREE = "14d7659ac76b9a0b1f4e0fec0bc9d6175894a8bf"
IMAGE = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
MANIFEST_SHA256 = "684c81dcb00d0abf33095bc704e7550d9bb64400b367d2b5da9324aeb85c8993"
RUNNER_PATH = "scripts/m2c/run_formal_model_owned_chain_v4.py"
RUNNER_SHA256 = "799caecdb12f73b5e6ea226eb2b983e4fbe4c08482f7ed037ae33c2168068eef"
ADDENDUM_PATH = "docs/decisions/ADR-0022-BINDING-ADDENDUM.md"
ADDENDUM_SHA256 = "712fe64e60bf31b67d1eb5552bc2e9a9cfa96c43b07c4e7f2ebbc3a57207078b"


def _git(*args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        input=input_bytes,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _frozen_tree() -> tuple[dict[str, str], dict[str, str]]:
    records: list[tuple[str, str, str]] = []
    for raw in _git("ls-tree", "-r", "-z", IMPLEMENTATION_COMMIT).split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split(" ")
        assert kind == "blob"
        assert mode in {"100644", "100755"}
        records.append((mode, object_id, raw_path.decode("utf-8")))

    object_ids = list(dict.fromkeys(object_id for _, object_id, _ in records))
    batch = _git("cat-file", "--batch", input_bytes=("\n".join(object_ids) + "\n").encode())
    blobs: dict[str, bytes] = {}
    offset = 0
    for expected_id in object_ids:
        header_end = batch.index(b"\n", offset)
        object_id, kind, raw_size = batch[offset:header_end].decode("ascii").split(" ")
        assert object_id == expected_id and kind == "blob"
        size = int(raw_size)
        start = header_end + 1
        end = start + size
        blobs[object_id] = batch[start:end]
        assert batch[end : end + 1] == b"\n"
        offset = end + 1
    assert offset == len(batch)

    files = {path: hashlib.sha256(blobs[object_id]).hexdigest() for _, object_id, path in records}
    modes = {path: mode for mode, _, path in records}
    return files, modes


def test_complete_git_tree_reconstructs_the_applied_manifest() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    files, modes = _frozen_tree()
    manifest = FormalTransitiveImportClosureManifestV1(
        implementation_commit=IMPLEMENTATION_COMMIT,
        container_image_digest=IMAGE,
        files=files,
        complete_transitive_import_closure=True,
        generated_inside_bound_container=True,
        teacher_used=False,
    )
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"

    assert _git("rev-parse", f"{IMPLEMENTATION_COMMIT}^{{tree}}").decode().strip() == (
        IMPLEMENTATION_TREE
    )
    assert hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256
    assert len(files) == report["source_closure"]["tracked_file_count"] == 1258
    assert sum(mode == "100755" for mode in modes.values()) == 59
    assert canonical_sha256(modes) == report["source_closure"]["git_mode_map_sha256"]
    assert files[RUNNER_PATH] == RUNNER_SHA256
    assert files[ADDENDUM_PATH] == ADDENDUM_SHA256


def test_source_closure_request_and_receipt_are_canonical() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    request_payload = {
        "schema_version": "M2CPhase2SourceBindingClosureRequestV1",
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "repository_tree_sha1": IMPLEMENTATION_TREE,
        "container_image_digest": IMAGE,
        "builder_implementation_path": (
            "src/xh_agent/policy/qrm_lite/phase2_source_binding_closure_v1.py"
        ),
        "builder_implementation_sha256": (
            "553a5d5f8690e0852074e43e8c6737b8eeb66f580f14dfb77c2d946c46f46812"
        ),
        "complete_git_tree_required": True,
        "generated_inside_bound_container": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    request = Phase2SourceBindingClosureRequestV1(
        **request_payload,
        request_sha256=canonical_sha256(request_payload),
    )
    request_bytes = canonical_json_bytes(request.model_dump(mode="json")) + b"\n"
    closure = report["source_closure"]
    assert request.request_sha256 == closure["request_sha256"]
    assert hashlib.sha256(request_bytes).hexdigest() == closure["request_file_sha256"]

    receipt_payload = {
        "schema_version": "M2CPhase2SourceBindingClosureReceiptV1",
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "repository_tree_sha1": IMPLEMENTATION_TREE,
        "container_image_digest": IMAGE,
        "request_sha256": request.request_sha256,
        "tracked_file_count": 1258,
        "executable_file_count": 59,
        "git_mode_map_sha256": closure["git_mode_map_sha256"],
        "transitive_import_manifest_path": "transitive-import-manifest.json",
        "transitive_import_manifest_sha256": MANIFEST_SHA256,
        "complete_git_tree_replayed": True,
        "complete_transitive_import_closure": True,
        "create_only_publication": True,
        "sealed_read_only": True,
        "generated_inside_bound_container": True,
        "physical_execution_performed": False,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    receipt = Phase2SourceBindingClosureReceiptV1(
        **receipt_payload,
        receipt_sha256=canonical_sha256(receipt_payload),
    )
    receipt_bytes = canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n"
    assert receipt.receipt_sha256 == closure["receipt_sha256"]
    assert hashlib.sha256(receipt_bytes).hexdigest() == closure["receipt_file_sha256"]


def test_only_two_source_bindings_are_applied_and_training_gate_opens() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    expected_runner = (RUNNER_PATH, RUNNER_SHA256)
    expected_closure = (IMPLEMENTATION_COMMIT, IMAGE, MANIFEST_SHA256)

    assert FORMAL_PHYSICAL_RUNNER_BINDING == expected_runner
    assert FORMAL_DEPLOYMENT_CLOSURE_BINDING == expected_closure
    assert FROZEN_B0_RUNTIME_WRAPPER_BINDING is None
    assert OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING is None
    assert config == {
        "schema_version": "M2CS4UnlockBindingV2",
        "status": "APPLIED_TO_REVIEWED_SOURCE",
        "adr_path": "docs/decisions/ADR-0024-m2c-s4-unblock-directive.md",
        "binding_addendum_path": ADDENDUM_PATH,
        "binding_addendum_sha256": ADDENDUM_SHA256,
        "FORMAL_PHYSICAL_RUNNER_BINDING": list(expected_runner),
        "FORMAL_DEPLOYMENT_CLOSURE_BINDING": list(expected_closure),
        "FROZEN_B0_RUNTIME_WRAPPER_BINDING": None,
        "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING": None,
        "applied_to_source": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    assert not _formal_source_unlock_blockers()
    _require_phase2_training_bindings()


def test_binding_report_does_not_claim_physical_or_q_b_evidence() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    claims = report["evidence_claims"]
    assert report["status"] == "PASS_SOURCE_BINDINGS_APPLIED"
    assert claims == {
        "formal_q_b_evaluation_authorized_by_this_report": False,
        "physical_execution_performed": False,
        "privileged_truth_policy_input": False,
        "q_b_evaluation_performed": False,
        "s4_no_teacher_training_authorized": True,
        "teacher_used": False,
        "training_performed": False,
    }
    assert len(report["remaining_formal_q_b_evidence"]) == 6
    for item in report["contract_evidence"].values():
        assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
