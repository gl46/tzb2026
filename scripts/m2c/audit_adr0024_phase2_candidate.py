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
import subprocess
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
from xh_agent.policy.qrm_lite.formal_exact_plan_synthesis_v1 import (  # noqa: E402
    FormalExactPlanSynthesisConfigurationV1,
)


SCHEMA_VERSION = "M2CADR0024Phase2CandidateAuditV1"
CANDIDATE_CONFIG_SCHEMA = "M2CADR0024Phase2BindingCandidateV2"
CANDIDATE_CONFIG_PATH = Path("configs/m2c_adr0024_phase2_binding_candidate.json")
CANDIDATE_ADDENDUM_PATH = Path("docs/decisions/ADR-0024-PHASE2-BINDING-ADDENDUM-CANDIDATE.md")
ENTRY_GATE_PATH = Path("src/xh_agent/policy/qrm_lite/s4_entry_gate.py")
FORMAL_V2_RUNNER_PATH = Path("src/xh_agent/policy/qrm_lite/formal_split_runner_v2.py")
FORMAL_V4_HOST_PATH = Path("src/xh_agent/policy/qrm_lite/formal_split_host_v4.py")
FORMAL_V4_CLI_PATH = Path("scripts/m2c/run_formal_model_owned_chain_v4.py")
FORMAL_V4_SERVICE_PATH = Path("scripts/m2c/serve_formal_isaac_endpoint_v4.py")
FORMAL_ISAAC_SCENE_OWNER_PATH = Path("scripts/m2c/formal_isaac_v4_backend.py")
FORMAL_ISAAC_MUTATION_COUNTER_PATH = Path(
    "src/xh_agent/policy/qrm_lite/formal_isaac_mutation_counter_v1.py"
)
FORMAL_EPISODE_IO_PATH = Path("src/xh_agent/policy/qrm_lite/formal_isaac_episode_io_v4.py")
ATTACHED_OBJECT_PHASE_GEOMETRY_PATH = Path(
    "src/xh_agent/policy/qrm_lite/a3_attached_object_phase_geometry_v1.py"
)
FORMAL_V4_HMAC_VERIFIER_PATH = Path("src/xh_agent/policy/qrm_lite/offline_wire_auth_v4.py")
FORMAL_V4_HMAC_CLI_PATH = Path("scripts/m2c/verify_formal_wire_auth_v4.py")
PHASE2_READINESS_V2_PATH = Path("src/xh_agent/policy/qrm_lite/phase2_binding_readiness_v2.py")
PHASE2_READINESS_CLI_PATH = Path("scripts/m2c/check_adr0022_binding_addendum_readiness.py")
EXACT_PLAN_SYNTHESIS_CONFIG_PATH = Path("configs/m2c_exact_plan_synthesis_candidate_v1.json")
EXACT_PLAN_SYNTHESIS_DEPENDENCIES_PATH = Path(
    "configs/m2c_exact_plan_synthesis_dependencies_v1.json"
)
EXACT_PLAN_SYNTHESIS_BACKEND_PATH = Path(
    "src/xh_agent/policy/qrm_lite/formal_exact_plan_synthesis_v1.py"
)
EXACT_PLAN_SYNTHESIS_QUERY_PATH = Path(
    "src/xh_agent/policy/qrm_lite/formal_isaac_plan_synthesis_query_v1.py"
)
ACTIVE_SESSION_QUERY_PATH = Path("src/xh_agent/policy/qrm_lite/isaac_active_session_query_v1.py")
PER_DECISION_BUNDLE_FACTORY_PATH = Path(
    "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_bundle_factory_v1.py"
)
PER_DECISION_COMPONENT_SOURCE_PATH = Path(
    "src/xh_agent/policy/qrm_lite/formal_isaac_exact_plan_components_v1.py"
)
FORMAL_RUNTIME_FACTORY_PATH = Path(
    "src/xh_agent/policy/qrm_lite/formal_isaac_runtime_factory_v4.py"
)
EXACT_PLAN_SYNTHESIS_CONFIG_SHA256 = (
    "3b5947f5f81b06f8d9debae562979a714b4c6a2dc1a2e289001c23ce8e6c79d2"
)
EXACT_PLAN_SYNTHESIS_CONFIGURATION_SHA256 = (
    "7a155984c8dd859788f22f912bbd401f3f6867f3760463f84c7f04c6e67b41c9"
)
EXACT_PLAN_SYNTHESIS_DEPENDENCIES_SHA256 = (
    "ececd27d30aaa1ca5b95f2192a91f0aba2405bad0ea4677ed450a1faac89eb97"
)
EXACT_PLAN_SYNTHESIS_BACKEND_SHA256 = (
    "20dc25e744b3c698a068219de5a4d84362d30eb6cf224ca6dd66fb99dbd6fac5"
)
EXACT_PLAN_SYNTHESIS_QUERY_SHA256 = (
    "c71a2dae34b8924f33c35f8db8f7d2546f77ed089d4d72ee81f54be3ea37045b"
)
ACTIVE_SESSION_QUERY_SHA256 = "9a0f13f9f091cbf9bece4bc1725233c2e4110d06399b9614a02c53050b76afa8"
PER_DECISION_BUNDLE_FACTORY_SHA256 = (
    "12ec4d57deadd2f173a4b88d12837307a916538404645ed03c30f520fa37aa29"
)
PER_DECISION_COMPONENT_SOURCE_SHA256 = (
    "0299042a2d5b3a575dacb8d5c6293d835aaf9479f4ac7c02b1418d5311e2570a"
)
FORMAL_RUNTIME_FACTORY_SHA256 = "6422a0f4879b11c85678054712cca33ab8ab64c0751def8313df585158824784"
EXACT_PLAN_SYNTHESIS_IMPLEMENTATION_COMMIT = "1b97b6edb7e3678dd134a113f678e9d8feda9175"
FORMAL_EPISODE_IO_SHA256 = "bf149f00014d8c487fa65cedec74a3eb4e3c8f70d3df7aae88b5bf3403439aa5"
FORMAL_EPISODE_IO_IMPLEMENTATION_COMMIT = "961f370420b8c2073b4431751574a48502ce6c70"
ADR_0024_PATH = Path("docs/decisions/ADR-0024-m2c-s4-unblock-directive.md")
BINDING_NAMES = (
    "FORMAL_PHYSICAL_RUNNER_BINDING",
    "FORMAL_DEPLOYMENT_CLOSURE_BINDING",
    "FROZEN_B0_RUNTIME_WRAPPER_BINDING",
    "OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING",
)
EXPECTED_BLOCKERS = (
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "REAL_PUBLIC_TRACK_TO_COLLISION_PATH_A3_SAFETY_BINDING_NOT_BOUND",
    "REVIEWED_EXACT_PLAN_SYNTHESIS_DEPLOYMENT_NOT_BOUND",
    "REVIEWED_REAL_ISAAC_EPISODE_IO_DEPLOYMENT_NOT_BOUND",
    "REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "COMPLETE_SCENE_ENVIRONMENT_SWEPT_COLLISION_PROVIDER_NOT_BOUND",
    "REAL_ATTACHED_OBJECT_PHASE_GEOMETRY_RESOLVER_NOT_BOUND",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING",
    "REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
    "TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET",
)
NATIVE_BUILD_RECORDED_BLOCKERS = (
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
    "REAL_QUERY_ONLY_FK_PROVIDER_BINDING_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
)
NATIVE_BUILD_REPORT_PATH = Path("reports/m2c-phase2-a3-native-build.json")
NATIVE_BUILD_REPORT_SHA256 = "3c3d238e4dea260508bdb5b8bc70882c819005c1d1ff631c8510d78202e29047"
NATIVE_BUILD_IMAGE_ID = "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
NATIVE_SHARED_OBJECT_SHA256 = "2231cee659b15875fc0bed011f339ac9962168981d228f3f08c6189929ce9c23"
FK_REPORT_PATH = Path("reports/m2c-phase2-a3-controlled-panda-fk.json")
FK_REPORT_SHA256 = "fffc79564a60921398034913b13261e11d462b7dafdfe075f6b5558ff73379bb"
FK_PROVIDER_PATH = Path("src/xh_agent/policy/qrm_lite/controlled_panda_fk_v1.py")
FK_PROVIDER_SHA256 = "33d735905ecc132edae9c3a5f4d780518a328cd30518c0f897b1b0dda579b541"
FK_CONFIGURATION_SHA256 = "0567b222f22d2676b8b118e5583df186e2c71e06c2f57f3f1af72d736dd460df"
ACM_SOURCE_AUDIT_REPORT_PATH = Path("reports/m2c-phase2-a3-acm-adr0025.json")
ACM_SOURCE_AUDIT_REPORT_SHA256 = "4f9dd14d6fad0508b06919086321887e53aa9ff4c8c9593b12e19ed39f66a7ae"
ACM_CONFIGURATION_PATH = Path("configs/m2c_a3_acm_adr0025_v1.json")
ACM_CONFIGURATION_FILE_SHA256 = "9dd2a01d264b779782b0c1e7917b987b99a01e1f16a989b99870a24cecf88bcf"
ACM_CONFIGURATION_SHA256 = "5bb066245f6e717c1997322faa613ef1446064932fc4375af1276e3a8d9fcb89"
QUERY_COMPARISON_REPORT_PATH = Path("reports/m2c-phase2-a3-acm-smoke.json")
QUERY_COMPARISON_REPORT_SHA256 = "80320998f4b652b48d73aa45b0ae65a5353a424699d6d2aad7d7ef618db137df"
FINAL_QUERY_SMOKE_RECEIPT_SHA256 = (
    "146e2b25a02ecfd87fc04bcb88cf56d43a965dd3b6f39ab18b7786ec666b4be1"
)


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


def _historical_git_blob_with_sha256(
    project_root: Path,
    path: Path,
    expected_sha256: str,
) -> bytes:
    commits = subprocess.run(
        ["git", "-C", str(project_root), "log", "--all", "--format=%H", "--", path.as_posix()],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for commit in commits:
        result = subprocess.run(
            ["git", "-C", str(project_root), "show", f"{commit}:{path.as_posix()}"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0 and _sha256(result.stdout) == expected_sha256:
            return result.stdout
    raise CandidateAuditFailure(f"candidate historical Git blob is absent: {path}")


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
        "a3_acm_evidence",
        "query_only_deployment_smoke",
        "exact_plan_synthesis_candidate",
        "episode_io_candidate",
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
    acm = candidate["a3_acm_evidence"]
    if acm != {
        "report_path": ACM_SOURCE_AUDIT_REPORT_PATH.as_posix(),
        "report_sha256": ACM_SOURCE_AUDIT_REPORT_SHA256,
        "status": "PASS_EXACT_TWO_ACM_PAIRS_HAVE_OFFICIAL_UPSTREAM_SRDF_EVIDENCE",
        "configuration_path": ACM_CONFIGURATION_PATH.as_posix(),
        "configuration_file_sha256": ACM_CONFIGURATION_FILE_SHA256,
        "configuration_sha256": ACM_CONFIGURATION_SHA256,
        "authorized_pair_count": 2,
        "criterion": "A_OFFICIAL_UPSTREAM_SRDF",
        "formal_execution_eligible": False,
    }:
        raise CandidateAuditFailure("candidate ADR-0025 ACM evidence binding differs")
    query_smoke = candidate["query_only_deployment_smoke"]
    if query_smoke != {
        "report_path": QUERY_COMPARISON_REPORT_PATH.as_posix(),
        "report_sha256": QUERY_COMPARISON_REPORT_SHA256,
        "status": "PASS_QUERY_ONLY_A3_ACM_SMOKE_CLEAR",
        "final_smoke_receipt_sha256": FINAL_QUERY_SMOKE_RECEIPT_SHA256,
        "request_segment_count": 74,
        "clear_result_count": 74,
        "collision_rejection_count": 0,
        "query_failure_count": 0,
        "static_state_preflight_clear": True,
        "formal_execution_eligible": False,
    }:
        raise CandidateAuditFailure("candidate query-only deployment smoke binding differs")
    synthesis = candidate["exact_plan_synthesis_candidate"]
    expected_synthesis = {
        "configuration_path": EXACT_PLAN_SYNTHESIS_CONFIG_PATH.as_posix(),
        "configuration_file_sha256": EXACT_PLAN_SYNTHESIS_CONFIG_SHA256,
        "configuration_sha256": EXACT_PLAN_SYNTHESIS_CONFIGURATION_SHA256,
        "dependency_manifest_path": EXACT_PLAN_SYNTHESIS_DEPENDENCIES_PATH.as_posix(),
        "dependency_manifest_sha256": EXACT_PLAN_SYNTHESIS_DEPENDENCIES_SHA256,
        "backend_implementation_path": EXACT_PLAN_SYNTHESIS_BACKEND_PATH.as_posix(),
        "backend_implementation_sha256": EXACT_PLAN_SYNTHESIS_BACKEND_SHA256,
        "query_source_implementation_path": EXACT_PLAN_SYNTHESIS_QUERY_PATH.as_posix(),
        "query_source_implementation_sha256": EXACT_PLAN_SYNTHESIS_QUERY_SHA256,
        "active_session_query_implementation_path": ACTIVE_SESSION_QUERY_PATH.as_posix(),
        "active_session_query_implementation_sha256": ACTIVE_SESSION_QUERY_SHA256,
        "per_decision_bundle_factory_implementation_path": (
            PER_DECISION_BUNDLE_FACTORY_PATH.as_posix()
        ),
        "per_decision_bundle_factory_implementation_sha256": (PER_DECISION_BUNDLE_FACTORY_SHA256),
        "per_decision_component_source_implementation_path": (
            PER_DECISION_COMPONENT_SOURCE_PATH.as_posix()
        ),
        "per_decision_component_source_implementation_sha256": (
            PER_DECISION_COMPONENT_SOURCE_SHA256
        ),
        "formal_runtime_factory_implementation_path": FORMAL_RUNTIME_FACTORY_PATH.as_posix(),
        "formal_runtime_factory_implementation_sha256": FORMAL_RUNTIME_FACTORY_SHA256,
        "implementation_commit": EXACT_PLAN_SYNTHESIS_IMPLEMENTATION_COMMIT,
        "registered_skill_count": 8,
        "runtime_parameter_adaptation_allowed": False,
        "physical_execution_claimed": False,
        "query_source_contract_active": True,
        "per_decision_component_graph_contract_active": True,
        "public_track_collision_safety_binding_contract_active": True,
        "real_scene_safety_binding_source_bound": False,
        "real_query_source_bound": False,
        "real_per_decision_component_graph_bound": False,
        "reviewed_production_deployment_bound": False,
        "formal_execution_eligible": False,
    }
    if synthesis != expected_synthesis:
        raise CandidateAuditFailure("candidate exact-plan synthesis binding differs")
    episode_io = candidate["episode_io_candidate"]
    expected_episode_io = {
        "implementation_path": FORMAL_EPISODE_IO_PATH.as_posix(),
        "implementation_sha256": FORMAL_EPISODE_IO_SHA256,
        "implementation_commit": FORMAL_EPISODE_IO_IMPLEMENTATION_COMMIT,
        "shared_persistent_scene_owner_required": True,
        "public_failure_boundary_evidence_bound": True,
        "eight_capture_prefix_replay_bound": True,
        "public_final_evaluation_bound": True,
        "source_and_git_snapshot_verified_before_owner_contact": True,
        "real_scene_owner_deployment_bound": False,
        "http_backend_factory_bound": False,
        "formal_execution_eligible": False,
    }
    if episode_io != expected_episode_io:
        raise CandidateAuditFailure("candidate formal V4 episode I/O binding differs")
    synthesis_config_raw = read_regular_file_once(project_root / EXACT_PLAN_SYNTHESIS_CONFIG_PATH)
    if _sha256(synthesis_config_raw) != EXACT_PLAN_SYNTHESIS_CONFIG_SHA256:
        raise CandidateAuditFailure("candidate exact-plan synthesis config SHA-256 differs")
    try:
        synthesis_config = FormalExactPlanSynthesisConfigurationV1.model_validate_json(
            synthesis_config_raw
        )
    except ValueError as exc:
        raise CandidateAuditFailure("candidate exact-plan synthesis config is invalid") from exc
    if (
        synthesis_config.configuration_sha256 != EXACT_PLAN_SYNTHESIS_CONFIGURATION_SHA256
        or synthesis_config.immutable_commit != EXACT_PLAN_SYNTHESIS_IMPLEMENTATION_COMMIT
    ):
        raise CandidateAuditFailure("candidate exact-plan synthesis config identity differs")
    dependencies_raw = read_regular_file_once(project_root / EXACT_PLAN_SYNTHESIS_DEPENDENCIES_PATH)
    if _sha256(dependencies_raw) != EXACT_PLAN_SYNTHESIS_DEPENDENCIES_SHA256:
        raise CandidateAuditFailure("candidate exact-plan dependency manifest SHA-256 differs")
    try:
        dependencies = json.loads(dependencies_raw)
    except json.JSONDecodeError as exc:
        raise CandidateAuditFailure("candidate exact-plan dependency manifest is invalid") from exc
    if (
        set(dependencies)
        != {
            "schema_version",
            "implementation_commit",
            "dependencies",
            "teacher_used",
            "privileged_truth_policy_input",
        }
        or dependencies["schema_version"] != "M2CExactPlanSynthesisDependenciesV1"
        or dependencies["implementation_commit"] != EXACT_PLAN_SYNTHESIS_IMPLEMENTATION_COMMIT
        or dependencies["teacher_used"] is not False
        or dependencies["privileged_truth_policy_input"] is not False
    ):
        raise CandidateAuditFailure("candidate exact-plan dependency manifest fields differ")
    for path, expected in dependencies["dependencies"].items():
        if _sha256(read_regular_file_once(project_root / path)) != expected:
            raise CandidateAuditFailure(f"exact-plan synthesis dependency differs: {path}")
    if (
        _sha256(read_regular_file_once(project_root / EXACT_PLAN_SYNTHESIS_BACKEND_PATH))
        != EXACT_PLAN_SYNTHESIS_BACKEND_SHA256
    ):
        raise CandidateAuditFailure("candidate exact-plan synthesis backend SHA-256 differs")
    for path, expected in (
        (EXACT_PLAN_SYNTHESIS_QUERY_PATH, EXACT_PLAN_SYNTHESIS_QUERY_SHA256),
        (ACTIVE_SESSION_QUERY_PATH, ACTIVE_SESSION_QUERY_SHA256),
        (PER_DECISION_BUNDLE_FACTORY_PATH, PER_DECISION_BUNDLE_FACTORY_SHA256),
        (PER_DECISION_COMPONENT_SOURCE_PATH, PER_DECISION_COMPONENT_SOURCE_SHA256),
        (FORMAL_RUNTIME_FACTORY_PATH, FORMAL_RUNTIME_FACTORY_SHA256),
        (FORMAL_EPISODE_IO_PATH, FORMAL_EPISODE_IO_SHA256),
    ):
        if _sha256(read_regular_file_once(project_root / path)) != expected:
            raise CandidateAuditFailure(f"candidate query-only synthesis source differs: {path}")
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
    acm_report_raw = read_regular_file_once(project_root / ACM_SOURCE_AUDIT_REPORT_PATH)
    if _sha256(acm_report_raw) != acm["report_sha256"]:
        raise CandidateAuditFailure("candidate ACM source-audit report SHA-256 differs")
    try:
        acm_report = json.loads(acm_report_raw)
    except json.JSONDecodeError as exc:
        raise CandidateAuditFailure("candidate ACM source-audit report is unreadable") from exc
    if (
        acm_report.get("status") != acm["status"]
        or acm_report.get("configuration", {}).get("file_sha256")
        != acm["configuration_file_sha256"]
        or acm_report.get("configuration", {}).get("configuration_sha256")
        != acm["configuration_sha256"]
        or len(acm_report.get("pair_evidence", [])) != acm["authorized_pair_count"]
        or any(
            item.get("criterion") != acm["criterion"]
            for item in acm_report.get("pair_evidence", [])
        )
        or acm_report.get("controlled_srdf", {}).get("removed_pair_count") != 0
        or acm_report.get("evidence_claims", {}).get("physical_execution_performed") is not False
    ):
        raise CandidateAuditFailure("candidate ACM source-audit claims differ")
    query_report_raw = read_regular_file_once(project_root / QUERY_COMPARISON_REPORT_PATH)
    if _sha256(query_report_raw) != query_smoke["report_sha256"]:
        raise CandidateAuditFailure("candidate query-only comparison report SHA-256 differs")
    try:
        query_report = json.loads(query_report_raw)
    except json.JSONDecodeError as exc:
        raise CandidateAuditFailure("candidate query-only comparison report is unreadable") from exc
    if (
        query_report.get("status") != query_smoke["status"]
        or query_report.get("smoke_evidence", {}).get("sha256")
        != query_smoke["final_smoke_receipt_sha256"]
        or query_report.get("query_result", {}).get("request_segment_count")
        != query_smoke["request_segment_count"]
        or query_report.get("query_result", {}).get("clear_result_count")
        != query_smoke["clear_result_count"]
        or query_report.get("query_result", {}).get("collision_rejection_count")
        != query_smoke["collision_rejection_count"]
        or query_report.get("query_result", {}).get("query_failure_count")
        != query_smoke["query_failure_count"]
        or query_report.get("evidence_claims", {}).get("static_state_preflight_clear") is not True
        or query_report.get("evidence_claims", {}).get("formal_execution_eligible") is not False
    ):
        raise CandidateAuditFailure("candidate query-only deployment smoke claims differ")
    for path, expected in candidate["source_bindings"].items():
        current = read_regular_file_once(project_root / path)
        if _sha256(current) != expected:
            if Path(path) != ENTRY_GATE_PATH:
                raise CandidateAuditFailure(f"candidate source SHA-256 differs: {path}")
            _historical_git_blob_with_sha256(project_root, ENTRY_GATE_PATH, expected)
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
    entry_source = _historical_git_blob_with_sha256(
        root,
        ENTRY_GATE_PATH,
        candidate["source_bindings"][ENTRY_GATE_PATH.as_posix()],
    )
    bindings = parse_literal_none_bindings(entry_source)
    smokes = replay_exact_plan_contract_smoke()
    if len(smokes) != 3 or any(item["status"] != "PASS_CONTRACT_ONLY" for item in smokes):
        raise CandidateAuditFailure("exact-plan contract smoke failed")
    formal_source = read_regular_file_once(root / FORMAL_V2_RUNNER_PATH).decode("utf-8")
    required_terminal_tokens = (
        'receipt.execution_source != "NO_PHYSICAL_EXECUTION"',
        'receipt.executed_skill != "NO_PHYSICAL_EXECUTION"',
        "ADR-0024",
    )
    if any(token not in formal_source for token in required_terminal_tokens):
        raise CandidateAuditFailure("terminal NO_PHYSICAL_EXECUTION source contract is absent")
    formal_v4_host = read_regular_file_once(root / FORMAL_V4_HOST_PATH).decode("utf-8")
    for token in (
        "M2CFormalSplitRunnerEvidenceV4",
        "TERMINAL_NO_PHYSICAL_EXECUTION",
        "b0_runtime_fallback_present",
        "run_formal_v4_episode",
    ):
        if token not in formal_v4_host:
            raise CandidateAuditFailure(f"formal V4 host contract omitted marker: {token}")
    for forbidden in ("EXPECTED_CHAIN", "expected_skill", "B0_FALLBACK"):
        if forbidden in formal_v4_host:
            raise CandidateAuditFailure(f"formal V4 host contains fixed selection: {forbidden}")
    formal_v4_cli = read_regular_file_once(root / FORMAL_V4_CLI_PATH).decode("utf-8")
    for token in (
        "consume_wire_challenge_create_only",
        "require_pre_freeze",
        "_require_unused_outputs",
        "ABORTED_PARTIAL_RUN_NOT_ENTRY_EVIDENCE",
    ):
        if token not in formal_v4_cli:
            raise CandidateAuditFailure(f"formal V4 CLI contract omitted marker: {token}")
    formal_v4_service = read_regular_file_once(root / FORMAL_V4_SERVICE_PATH).decode("utf-8")
    for token in (
        "FormalIsaacEndpointStateMachineV4",
        "FORMAL_V4_HTTP_SERVICE_SHELL_ONLY_BACKEND_FACTORY_UNBOUND",
        "TERMINAL_FAILURE",
        "require_pre_freeze",
    ):
        if token not in formal_v4_service:
            raise CandidateAuditFailure(f"formal V4 service shell omitted marker: {token}")
    service_tree = ast.parse(formal_v4_service)
    factory_bindings = [
        node.value
        for node in service_tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "FORMAL_V4_BACKEND_FACTORY_BINDING"
    ]
    if len(factory_bindings) != 1 or not (
        isinstance(factory_bindings[0], ast.Constant) and factory_bindings[0].value is None
    ):
        raise CandidateAuditFailure("formal V4 service backend factory is not literal None")
    scene_owner = read_regular_file_once(root / FORMAL_ISAAC_SCENE_OWNER_PATH).decode("utf-8")
    for token in (
        "build_a3_scene_collision_geometry_v1",
        "FormalIsaacActiveSessionMutationCounterV1",
        "IsaacSceneRigidPrimReadOnlySourceV1",
        "self._initialize_scene_once()",
        "self._initialize_a3_query_sources()",
        "record_simulation_steps()",
    ):
        if token not in scene_owner:
            raise CandidateAuditFailure(f"formal Isaac scene source omitted marker: {token}")
    mutation_counter = read_regular_file_once(root / FORMAL_ISAAC_MUTATION_COUNTER_PATH).decode(
        "utf-8"
    )
    for token in (
        "FormalIsaacMutationCounterActivationReceiptV1",
        "AFTER_SCENE_STABILITY_BEFORE_FORMAL_SESSION",
        "snapshot_mutation_counters",
        "real_active_session_source",
    ):
        if token not in mutation_counter:
            raise CandidateAuditFailure(f"formal Isaac mutation counter omitted marker: {token}")
    episode_io_source = read_regular_file_once(root / FORMAL_EPISODE_IO_PATH).decode("utf-8")
    for token in (
        "FormalIsaacEpisodeIODeploymentBindingV1",
        "FormalIsaacPersistentSceneOwnerV4",
        "FormalIsaacEpisodeLifecycleAdapterV4",
        "FormalIsaacPublicCaptureSourceAdapterV4",
        "_require_immutable_commit",
        "public_failure_boundary_evidence_sha256",
    ):
        if token not in episode_io_source:
            raise CandidateAuditFailure(f"formal Isaac episode I/O omitted marker: {token}")
    component_source = read_regular_file_once(root / PER_DECISION_COMPONENT_SOURCE_PATH).decode(
        "utf-8"
    )
    for token in (
        "FormalIsaacExactPlanComponentSourceV1",
        "LulaQueryOnlyPhasePathProviderV1",
        "A3CompleteSceneSweptCollisionProviderV2",
        "A3ExactPlanNonActuatingCallbacksV1",
        "FrozenProbeExactPlanExecutorV1",
        "snapshot_mutation_counters",
    ):
        if token not in component_source:
            raise CandidateAuditFailure(
                f"per-decision exact-plan component source omitted marker: {token}"
            )
    bundle_factory = read_regular_file_once(root / PER_DECISION_BUNDLE_FACTORY_PATH).decode("utf-8")
    for token in (
        "FormalIsaacPerDecisionExactPlanBundleFactoryV1",
        "_validate_bundle_graph",
        "claim_active_session_query_provider",
        "build_bundle_components",
        "formal exact-plan bundle construction mutated the active scene",
    ):
        if token not in bundle_factory:
            raise CandidateAuditFailure(
                f"per-decision exact-plan bundle factory omitted marker: {token}"
            )
    runtime_factory = read_regular_file_once(root / FORMAL_RUNTIME_FACTORY_PATH).decode("utf-8")
    for token in (
        "FormalIsaacV4RuntimeFactoryV1",
        "FormalIsaacPerDecisionExactPlanBundleFactoryV1",
        "_verify_immutable_source_inventory",
        "per_decision_bundle_factory_binding_sha256",
    ):
        if token not in runtime_factory:
            raise CandidateAuditFailure(f"formal V4 runtime factory omitted marker: {token}")
    attached_geometry = read_regular_file_once(root / ATTACHED_OBJECT_PHASE_GEOMETRY_PATH).decode(
        "utf-8"
    )
    for token in (
        "A3PlannedAttachedObjectBindingV1",
        "A3AttachedObjectPhaseGeometryEvidenceV1",
        "produce_a3_scene_state_receipt_v1",
        "privileged_truth_policy_input",
    ):
        if token not in attached_geometry:
            raise CandidateAuditFailure(f"attached-object phase geometry omitted marker: {token}")
    hmac_source = read_regular_file_once(root / FORMAL_V4_HMAC_VERIFIER_PATH).decode("utf-8")
    hmac_tree = ast.parse(hmac_source)
    hmac_receipt_fields = {
        item.target.id
        for node in hmac_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "HostWireHMACVerificationCoreV4"
        for item in node.body
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
    }
    if not {
        "challenge_consumption_receipt_sha256",
        "formal_evidence_sha256",
        "service_audit_sha256",
        "envelope_set_sha256",
        "completion_kind",
        "decision_count",
        "all_hmac_valid",
    }.issubset(hmac_receipt_fields) or hmac_receipt_fields.intersection(
        {"signature_armored", "public_trust_root_sha256", "signer_principal"}
    ):
        raise CandidateAuditFailure("formal V4 host-local HMAC receipt schema differs")
    hmac_functions = {
        item.name
        for item in hmac_tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if not {
        "verify_node2_qwen_transcript_v4",
        "verify_labserver_isaac_transcript_v4",
        "build_hmac_verification_receipt_v4",
    }.issubset(hmac_functions):
        raise CandidateAuditFailure("formal V4 host-local HMAC replay is incomplete")
    hmac_cli = read_regular_file_once(root / FORMAL_V4_HMAC_CLI_PATH).decode("utf-8")
    for token in (
        "read_hmac_secret",
        "build_hmac_verification_receipt_v4",
        "_publish_create_only",
        "PASS_HOST_LOCAL_V4_HMAC_VERIFICATION_NOT_FORMAL_AUTHORIZATION",
    ):
        if token not in hmac_cli:
            raise CandidateAuditFailure(f"formal V4 HMAC CLI omitted marker: {token}")
    readiness = read_regular_file_once(root / PHASE2_READINESS_V2_PATH).decode("utf-8")
    for token in (
        "M2CADR0024Phase2EvidenceIndexV2",
        "HostWireHMACVerificationReceiptV4",
        "COMPLETE_REAL_ISAAC_EIGHT_SKILL_VALIDATION",
        '"FROZEN_B0_RUNTIME_WRAPPER_BINDING": None',
        '"OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING": None',
    ):
        if token not in readiness:
            raise CandidateAuditFailure(f"Phase-2 V2 readiness omitted marker: {token}")
    if "PHASE2_READINESS_VERIFIER_ADR0024_V2_MIGRATION_INCOMPLETE" in readiness:
        raise CandidateAuditFailure("Phase-2 V2 readiness retains the migration blocker")
    entry_v4 = read_regular_file_once(root / ENTRY_GATE_PATH).decode("utf-8")
    for token in (
        "M2CS4PhysicalIntegrationReceiptV3",
        "M2CFormalSplitRunnerEvidenceV4",
        "HostWireHMACVerificationReceiptV4",
        "verify_phase2_evidence",
    ):
        if token not in entry_v4:
            raise CandidateAuditFailure(f"S4 entry V4 replay omitted marker: {token}")
    readiness_cli = read_regular_file_once(root / PHASE2_READINESS_CLI_PATH).decode("utf-8")
    if "phase2_binding_readiness_v2" not in readiness_cli:
        raise CandidateAuditFailure("Phase-2 readiness CLI does not dispatch to V2")
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
        "a3_acm_evidence": candidate["a3_acm_evidence"],
        "a3_query_only_deployment_smoke": candidate["query_only_deployment_smoke"],
        "exact_plan_synthesis_candidate": candidate["exact_plan_synthesis_candidate"],
        "per_decision_exact_plan_component_graph": {
            "status": "PASS_CONTRACT_ONLY_NOT_PRODUCTION_BOUND",
            "bundle_factory_implementation_sha256": PER_DECISION_BUNDLE_FACTORY_SHA256,
            "component_source_implementation_sha256": PER_DECISION_COMPONENT_SOURCE_SHA256,
            "runtime_factory_implementation_sha256": FORMAL_RUNTIME_FACTORY_SHA256,
            "same_scene_mutation_counter_bound": True,
            "complete_query_preflight_executor_graph_constructed": True,
            "real_eight_skill_receipts_present": False,
            "formal_authorization": False,
        },
        "formal_isaac_episode_io_candidate": candidate["episode_io_candidate"],
        "formal_v4_host_local_hmac_verifier": {
            "status": "PASS_CONTRACT_ONLY_NO_REAL_HOST_RECEIPTS",
            "receipt_schema": "M2CHostWireHMACVerificationReceiptV4",
            "node2_and_labserver_replay_implemented": True,
            "variable_terminal_envelope_counts_supported": True,
            "trusted_host_signature_required": False,
            "real_host_receipts_present": False,
            "formal_authorization": False,
        },
        "phase2_readiness_verifier": {
            "status": "PASS_ADR0024_V2_CONTRACT_NO_REAL_EVIDENCE_INDEX",
            "evidence_index_schema": "M2CADR0024Phase2EvidenceIndexV2",
            "signed_host_receipts_required": False,
            "active_session_b0_wrapper_required": False,
            "real_evidence_index_present": False,
            "binding_application_authorized": False,
        },
        "formal_isaac_a3_scene_source": {
            "status": "PASS_CONTRACT_ONLY_NO_REAL_SCENE_RECEIPT",
            "complete_scene_collision_link_count": 8,
            "post_stability_mutation_counter_active": True,
            "attached_object_phase_geometry_replay_active": True,
            "real_scene_state_receipt_present": False,
            "real_attached_object_phase_geometry_receipt_present": False,
            "formal_authorization": False,
        },
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
