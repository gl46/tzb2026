#!/usr/bin/env python3
"""Audit the ADR-0024 Phase-2 candidate without unlocking or running Isaac."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from m2c.audit_adr0022_phase2_unlock import replay_exact_plan_contract_smoke  # noqa: E402
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (  # noqa: E402
    inspect_a3_production_closure_v1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (  # noqa: E402
    canonical_a3_bullet_numeric_configuration_v1,
)


SCHEMA_VERSION = "M2CADR0024Phase2CandidateAuditV1"
CANDIDATE_CONFIG_SCHEMA = "M2CADR0024Phase2BindingCandidateV1"
CANDIDATE_CONFIG_PATH = Path("configs/m2c_adr0024_phase2_binding_candidate.json")
CANDIDATE_ADDENDUM_PATH = Path("docs/decisions/ADR-0024-PHASE2-BINDING-ADDENDUM-CANDIDATE.md")
ENTRY_GATE_PATH = Path("src/xh_agent/policy/qrm_lite/s4_entry_gate.py")
FORMAL_RUNNER_PATH = Path("src/xh_agent/policy/qrm_lite/formal_split_runner_v2.py")
ADR_0024_PATH = Path("docs/decisions/ADR-0024-m2c-s4-unblock-directive.md")
BINDING_NAMES = (
    "FORMAL_PHYSICAL_RUNNER_BINDING",
    "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
    "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
    "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
)
EXPECTED_BLOCKERS = (
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
    "REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
)
NATIVE_BUILD_RECORDED_BLOCKERS = (
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
    "REAL_QUERY_ONLY_FK_PROVIDER_BINDING_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
)
NATIVE_BUILD_REPORT_PATH = Path("reports/m2c-phase2-a3-native-build.json")
NATIVE_BUILD_REPORT_SHA256 = "725c33bc8380ea5941542046b335b3a3512118b35b7427a119c809fa181af36b"
NATIVE_BUILD_IMAGE_ID = "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
NATIVE_SHARED_OBJECT_SHA256 = "2231cee659b15875fc0bed011f339ac9962168981d228f3f08c6189929ce9c23"
FK_REPORT_PATH = Path("reports/m2c-phase2-a3-controlled-panda-fk.json")
FK_REPORT_SHA256 = "fffc79564a60921398034913b13261e11d462b7dafdfe075f6b5558ff73379bb"
FK_PROVIDER_PATH = Path("src/xh_agent/policy/qrm_lite/controlled_panda_fk_v1.py")
FK_PROVIDER_SHA256 = "33d735905ecc132edae9c3a5f4d780518a328cd30518c0f897b1b0dda579b541"
FK_CONFIGURATION_SHA256 = "0567b222f22d2676b8b118e5583df186e2c71e06c2f57f3f1af72d736dd460df"


class CandidateAuditFailure(RuntimeError):
    """Candidate bytes drifted or made an unsupported readiness claim."""


def read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CandidateAuditFailure(
                f"candidate input is not a single-link regular file: {path}"
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda value: (  # noqa: E731
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise CandidateAuditFailure(f"candidate input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_literal_none_bindings(source: bytes) -> dict[str, None]:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise CandidateAuditFailure("entry gate is not parseable UTF-8 Python") from exc
    assignments: dict[str, list[ast.expr]] = {name: [] for name in BINDING_NAMES}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in assignments and node.value is not None:
                assignments[node.target.id].append(node.value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in assignments:
                    assignments[target.id].append(node.value)
    for name, values in assignments.items():
        if len(values) != 1 or not (
            isinstance(values[0], ast.Constant) and values[0].value is None
        ):
            raise CandidateAuditFailure(f"candidate binding is not one literal None: {name}")
    return {name: None for name in BINDING_NAMES}


def load_candidate_config(project_root: Path) -> dict[str, Any]:
    try:
        candidate = json.loads(read_regular_file_once(project_root / CANDIDATE_CONFIG_PATH))
    except (json.JSONDecodeError, OSError) as exc:
        raise CandidateAuditFailure("candidate config is unreadable") from exc
    exact_keys = {
        "schema_version",
        "status",
        "checkpoint_date_asia_shanghai",
        "accepted_adr",
        "source_bindings",
        "native_build_evidence",
        "read_only_fk_evidence",
        "a3_numeric_configuration_sha256",
        "production_bindings",
        "b0_policy",
        "evidence_claims",
        "blockers",
        "one_next_command",
    }
    if set(candidate) != exact_keys:
        raise CandidateAuditFailure("candidate config fields differ")
    if (
        candidate["schema_version"] != CANDIDATE_CONFIG_SCHEMA
        or candidate["status"] != "CONTRACT_SMOKE_ONLY_BLOCKED_UNMEASURED"
        or candidate["checkpoint_date_asia_shanghai"] != "2026-08-20"
        or candidate["production_bindings"] != {name: None for name in BINDING_NAMES}
        or tuple(candidate["blockers"]) != EXPECTED_BLOCKERS
    ):
        raise CandidateAuditFailure("candidate config status/bindings/blockers differ")
    claims = candidate["evidence_claims"]
    expected_claims = {
        "contract_smoke_passed": True,
        "contract_smoke_is_physical_evidence": False,
        "formal_execution_eligible": False,
        "isaac_started": False,
        "physical_execution_performed": False,
        "training_performed": False,
        "q_b_evaluation_performed": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    if claims != expected_claims:
        raise CandidateAuditFailure("candidate evidence claims differ")
    expected_b0 = {
        "runtime_wrapper_required": False,
        "runtime_fallback_allowed": False,
        "invalid_or_rejected_action_policy": "TERMINAL_NO_PHYSICAL_EXECUTION",
        "no_action_relabelled_b0_fallback": False,
        "independent_b0_comparison_arm_unchanged": True,
    }
    if candidate["b0_policy"] != expected_b0:
        raise CandidateAuditFailure("candidate B0/terminal policy differs")
    native = candidate["native_build_evidence"]
    if native != {
        "report_path": NATIVE_BUILD_REPORT_PATH.as_posix(),
        "report_sha256": NATIVE_BUILD_REPORT_SHA256,
        "status": "PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY",
        "builder_image_id": NATIVE_BUILD_IMAGE_ID,
        "native_shared_object_sha256": NATIVE_SHARED_OBJECT_SHA256,
        "formal_execution_eligible": False,
    }:
        raise CandidateAuditFailure("candidate native-build evidence binding differs")
    fk = candidate["read_only_fk_evidence"]
    if fk != {
        "report_path": FK_REPORT_PATH.as_posix(),
        "report_sha256": FK_REPORT_SHA256,
        "status": "PASS_QUERY_ONLY_FK_MATCHES_INDEPENDENT_NODE2_KDL",
        "provider_implementation_sha256": FK_PROVIDER_SHA256,
        "provider_configuration_sha256": FK_CONFIGURATION_SHA256,
        "comparison_state_count": 12,
        "comparison_row_count": 144,
        "formal_execution_eligible": False,
    }:
        raise CandidateAuditFailure("candidate read-only FK evidence binding differs")
    native_report_raw = read_regular_file_once(project_root / NATIVE_BUILD_REPORT_PATH)
    if _sha256(native_report_raw) != native["report_sha256"]:
        raise CandidateAuditFailure("candidate native-build report SHA-256 differs")
    try:
        native_report = json.loads(native_report_raw)
    except json.JSONDecodeError as exc:
        raise CandidateAuditFailure("candidate native-build report is unreadable") from exc
    if (
        native_report.get("status") != native["status"]
        or native_report.get("native_build", {}).get("builder_image_id")
        != native["builder_image_id"]
        or native_report.get("native_build", {}).get("native_shared_object_sha256")
        != native["native_shared_object_sha256"]
        or native_report.get("evidence_claims", {}).get("formal_execution_eligible") is not False
        or native_report.get("remaining_blockers") != list(NATIVE_BUILD_RECORDED_BLOCKERS)
    ):
        raise CandidateAuditFailure("candidate native-build report claims differ")
    fk_report_raw = read_regular_file_once(project_root / FK_REPORT_PATH)
    if _sha256(fk_report_raw) != fk["report_sha256"]:
        raise CandidateAuditFailure("candidate FK report SHA-256 differs")
    try:
        fk_report = json.loads(fk_report_raw)
    except json.JSONDecodeError as exc:
        raise CandidateAuditFailure("candidate FK report is unreadable") from exc
    if (
        fk_report.get("status") != fk["status"]
        or fk_report.get("provider", {}).get("sha256") != fk["provider_implementation_sha256"]
        or fk_report.get("provider", {}).get("configuration_sha256")
        != fk["provider_configuration_sha256"]
        or fk_report.get("comparison", {}).get("state_count") != fk["comparison_state_count"]
        or fk_report.get("comparison", {}).get("row_count") != fk["comparison_row_count"]
        or fk_report.get("evidence_claims", {}).get("formal_execution_eligible") is not False
    ):
        raise CandidateAuditFailure("candidate FK report claims differ")
    for path, expected in candidate["source_bindings"].items():
        if _sha256(read_regular_file_once(project_root / path)) != expected:
            raise CandidateAuditFailure(f"candidate source SHA-256 differs: {path}")
    adr = candidate["accepted_adr"]
    if (
        adr
        != {
            "path": ADR_0024_PATH.as_posix(),
            "sha256": candidate["source_bindings"][ADR_0024_PATH.as_posix()],
            "status": "ACCEPTED_HUMAN_DECISION",
        }
        or candidate["a3_numeric_configuration_sha256"]
        != canonical_a3_bullet_numeric_configuration_v1().configuration_sha256
    ):
        raise CandidateAuditFailure("candidate ADR/numeric binding differs")
    return candidate


def build_audit(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    candidate = load_candidate_config(root)
    entry_source = read_regular_file_once(root / ENTRY_GATE_PATH)
    bindings = parse_literal_none_bindings(entry_source)
    smokes = replay_exact_plan_contract_smoke()
    if len(smokes) != 3 or any(item["status"] != "PASS_CONTRACT_ONLY" for item in smokes):
        raise CandidateAuditFailure("exact-plan contract smoke failed")
    formal_source = read_regular_file_once(root / FORMAL_RUNNER_PATH).decode("utf-8")
    required_terminal_tokens = (
        'receipt.execution_source != "NO_PHYSICAL_EXECUTION"',
        'receipt.executed_skill != "NO_PHYSICAL_EXECUTION"',
        "ADR-0024",
    )
    if any(token not in formal_source for token in required_terminal_tokens):
        raise CandidateAuditFailure("terminal NO_PHYSICAL_EXECUTION source contract is absent")
    closure = inspect_a3_production_closure_v1(project_root=root)
    if closure.status != "NOT_AVAILABLE" or closure.formal_execution_eligible:
        raise CandidateAuditFailure("local A.3 closure unexpectedly claimed production readiness")
    addendum = read_regular_file_once(root / CANDIDATE_ADDENDUM_PATH).decode("utf-8")
    for token in (
        "CONTRACT_SMOKE_ONLY",
        "BLOCKED_UNMEASURED",
        "2026-08-20",
        "not an accepted binding addendum",
        "NO_PHYSICAL_EXECUTION",
        "Teacher used: **false**",
    ):
        if token not in addendum:
            raise CandidateAuditFailure(f"candidate addendum omitted marker: {token}")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CONTRACT_SMOKE_ONLY_BLOCKED_UNMEASURED",
        "production_binding_authorized": False,
        "candidate_config_sha256": _sha256(read_regular_file_once(root / CANDIDATE_CONFIG_PATH)),
        "candidate_addendum_sha256": _sha256(
            read_regular_file_once(root / CANDIDATE_ADDENDUM_PATH)
        ),
        "entry_bindings": bindings,
        "contract_smokes": smokes,
        "a3_local_closure": closure.model_dump(mode="json"),
        "a3_native_build_evidence": candidate["native_build_evidence"],
        "a3_read_only_fk_evidence": candidate["read_only_fk_evidence"],
        "blockers": list(EXPECTED_BLOCKERS),
        "governance": candidate["evidence_claims"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build_audit(args.project_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
