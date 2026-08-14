#!/usr/bin/env python3
"""Verify the ADR-0025 A3 ACM query-only smoke without starting Isaac."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "M2CPhase2A3ADR0025QueryOnlySmokeAuditV1"
STATUS = "PASS_QUERY_ONLY_A3_ACM_SMOKE_CLEAR"
SMOKE_SCHEMA_VERSION = "M2CA3QueryOnlyDeploymentSmokeV1"
SMOKE_STATUS = "PASS_QUERY_ONLY_DEPLOYMENT_SMOKE_CLEAR"
SMOKE_RECEIPT_SHA256 = "146e2b25a02ecfd87fc04bcb88cf56d43a965dd3b6f39ab18b7786ec666b4be1"
IMMUTABLE_COMMIT = "f4c0ec89142a041a4651133027ade66bf878c40e"
RUNTIME_IMAGE_ID = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
BUILDER_IMAGE_ID = "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
ACM_AUDIT_PATH = Path("reports/m2c-phase2-a3-acm-adr0025.json")
ACM_AUDIT_SHA256 = "4f9dd14d6fad0508b06919086321887e53aa9ff4c8c9593b12e19ed39f66a7ae"
ACM_CONFIG_PATH = Path("configs/m2c_a3_acm_adr0025_v1.json")
ACM_CONFIG_FILE_SHA256 = "9dd2a01d264b779782b0c1e7917b987b99a01e1f16a989b99870a24cecf88bcf"
ACM_CONFIGURATION_SHA256 = "5bb066245f6e717c1997322faa613ef1446064932fc4375af1276e3a8d9fcb89"
ADR_PATH = Path("docs/decisions/ADR-0025-m2c-raw-capacity-acm-and-yield.md")
ADR_SHA256 = "6f27171d319e3f966c652ca9f8c0fe7c641f4bf420de58642869f9c9c805c3aa"
NATIVE_BUILD_REPORT_PATH = Path("reports/m2c-phase2-a3-native-build.json")
NATIVE_BUILD_REPORT_SHA256 = "3c3d238e4dea260508bdb5b8bc70882c819005c1d1ff631c8510d78202e29047"
FK_REPORT_PATH = Path("reports/m2c-phase2-a3-controlled-panda-fk.json")
FK_REPORT_SHA256 = "fffc79564a60921398034913b13261e11d462b7dafdfe075f6b5558ff73379bb"
EXPECTED_SOURCE_BINDINGS = {
    "robot_ws/src/xh_sim/config/m1a_panda.srdf": (
        "9e139275cb11f0403abf10894f1424b80a5024e94f7d4e6fadb8bb637017edda"
    ),
    "robot_ws/src/xh_sim/urdf/panda_controlled.urdf": (
        "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
    ),
    "scripts/m2c/run_a3_query_only_deployment_smoke.py": (
        "fdef2e7dd76b6d3a141143eb30f794170126b59b3d605f651427749b07782058"
    ),
    "src/xh_agent/policy/qrm_lite/a3_bullet_native_adapter_v1.cpp": (
        "5de2750b6704e30eef1955d3e7f60692cc424777f23024aa064410585331c900"
    ),
    "src/xh_agent/policy/qrm_lite/a3_bullet_self_ccd_v1.cpp": (
        "48a1caa8d2f1c8fcb76a504377f399223018a26925c03f1d549db9bab833506f"
    ),
    "src/xh_agent/policy/qrm_lite/controlled_panda_fk_v1.py": (
        "33d735905ecc132edae9c3a5f4d780518a328cd30518c0f897b1b0dda579b541"
    ),
}
EXPECTED_NATIVE_CLOSURE = {
    "build_manifest_core_sha256": (
        "b55e6f15c4a7c933115bd25df03a3b6db2e0d51b4f33ff43eca16118da8fc2b0"
    ),
    "build_manifest_file_sha256": (
        "6285988b8aea7f5e3bdff0f3b215e483ff59a350cff5ff7aaf4a638bb12c65e3"
    ),
    "builder_image_id": BUILDER_IMAGE_ID,
    "bullet_collision_library_sha256": (
        "baa16598bc6a54aa51c825af6680807b548decb33ff11f469ac24c09f54826c2"
    ),
    "bullet_linear_math_library_sha256": (
        "5d3fe859ad08f78fac1e51ed85dddd9e39da501a0d566e86e00da5565d9e5343"
    ),
    "native_shared_object_sha256": (
        "2231cee659b15875fc0bed011f339ac9962168981d228f3f08c6189929ce9c23"
    ),
}
EXPECTED_QUERY = {
    "bound_plan_sha256": "e3d710112959a7db94d19779cca3467bf48e28c4aecc581ed151d644aac9c801",
    "clear_result_count": 74,
    "collision_rejection_count": 0,
    "fk_provider_configuration_sha256": (
        "0567b222f22d2676b8b118e5583df186e2c71e06c2f57f3f1af72d736dd460df"
    ),
    "fk_receipt_sha256": "2f2d40b8931cf55f99636857b0399b534007c636fc53dc73f0d82f74cc190835",
    "geometry_receipt_sha256": ("1885fe4200641c59939ad4a8e356235673889cbc76d2242d217cefd198de1c84"),
    "joint_names": [
        "panda_joint1",
        "panda_joint2",
        "panda_joint3",
        "panda_joint4",
        "panda_joint5",
        "panda_joint6",
        "panda_joint7",
        "panda_finger_joint1",
        "panda_finger_joint2",
    ],
    "joint_state_sequence_sha256": (
        "a9987a164b4ed7598f2b581c15cf9125f50b442489cd2002b429deb248927e23"
    ),
    "numeric_configuration_sha256": (
        "8c6ba840339bca5a84ccd805b0c068439d59812eb0c3ecc9bdd809f1341d4bb5"
    ),
    "query_failure_count": 0,
    "receipt_sha256": "31a9ec649807430a280e9d4762b200af6f4a13f81131f608a181c5092275615b",
    "receipt_status": "PASS",
    "rejected_pairs": [],
    "request_segment_count": 74,
    "request_sha256": "58eebd7e503eb121e9ef888d16837594409d1d3cd88e5e679ebfae0c0a48fd57",
    "world_sha256": "594a8f82c7c1f8d6721ead45895ee77ba38438fed544b40ea18c1d2b1680ebbd",
}
EXPECTED_CLAIMS = {
    "articulation_target_writes": 0,
    "deployment_query_completed": True,
    "formal_execution_eligible": False,
    "isaac_started": False,
    "physical_execution_performed": False,
    "privileged_truth_policy_input": False,
    "q_b_evaluation_performed": False,
    "scene_mutations": 0,
    "simulation_steps": 0,
    "static_state_preflight_clear": True,
    "teacher_used": False,
    "training_performed": False,
}
EXPECTED_BLOCKERS = (
    "EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING",
    "IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING",
    "REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING",
    "REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING",
)


class A3ACMSmokeAuditError(ValueError):
    """The immutable query-only smoke or its governed closure drifted."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def read_regular_file_once(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise A3ACMSmokeAuditError(f"audit input is not single-link regular: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity = lambda item: (  # noqa: E731
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
        )
        if identity(before) != identity(after):
            raise A3ACMSmokeAuditError(f"audit input changed while read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_object(raw: bytes, *, label: str, canonical: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise A3ACMSmokeAuditError(f"{label} is not JSON") from error
    if not isinstance(value, dict):
        raise A3ACMSmokeAuditError(f"{label} is not an object")
    if canonical and raw != canonical_json_bytes(value) + b"\n":
        raise A3ACMSmokeAuditError(f"{label} is not canonical JSON")
    return value


def _git_file_sha256(project_root: Path, commit: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise A3ACMSmokeAuditError(f"immutable source is unavailable: {commit}:{path}")
    return _sha256(result.stdout)


def _require_bound_report(
    project_root: Path,
    *,
    path: Path,
    expected_sha256: str,
    expected_schema: str,
    expected_status: str,
) -> dict[str, Any]:
    raw = read_regular_file_once(project_root / path)
    if _sha256(raw) != expected_sha256:
        raise A3ACMSmokeAuditError(f"bound report SHA-256 differs: {path}")
    value = _json_object(raw, label=path.as_posix())
    if value.get("schema_version") != expected_schema or value.get("status") != expected_status:
        raise A3ACMSmokeAuditError(f"bound report identity differs: {path}")
    return value


def build_report(*, project_root: Path, smoke_receipt_path: Path) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    smoke_path = smoke_receipt_path.resolve(strict=True)
    smoke_raw = read_regular_file_once(smoke_path)
    if _sha256(smoke_raw) != SMOKE_RECEIPT_SHA256:
        raise A3ACMSmokeAuditError("smoke receipt SHA-256 differs")
    smoke = _json_object(smoke_raw, label="smoke receipt", canonical=True)
    if set(smoke) != {
        "schema_version",
        "status",
        "immutable_commit",
        "native_closure",
        "query",
        "remaining_blockers",
        "runtime",
        "source_bindings",
        "evidence_claims",
    }:
        raise A3ACMSmokeAuditError("smoke receipt fields differ")
    if (
        smoke["schema_version"] != SMOKE_SCHEMA_VERSION
        or smoke["status"] != SMOKE_STATUS
        or smoke["immutable_commit"] != IMMUTABLE_COMMIT
        or smoke["native_closure"] != EXPECTED_NATIVE_CLOSURE
        or smoke["query"] != EXPECTED_QUERY
        or smoke["source_bindings"] != EXPECTED_SOURCE_BINDINGS
        or smoke["evidence_claims"] != EXPECTED_CLAIMS
        or tuple(smoke["remaining_blockers"]) != EXPECTED_BLOCKERS
        or smoke["runtime"].get("container_image_id") != RUNTIME_IMAGE_ID
        or smoke["runtime"].get("platform_system") != "Linux"
        or smoke["runtime"].get("platform_machine") != "x86_64"
        or smoke["runtime"].get("isaac_or_kit_module_loaded") is not False
    ):
        raise A3ACMSmokeAuditError("smoke receipt contract or result differs")
    for path, expected in EXPECTED_SOURCE_BINDINGS.items():
        if _git_file_sha256(project_root, IMMUTABLE_COMMIT, path) != expected:
            raise A3ACMSmokeAuditError(f"immutable source binding differs: {path}")

    acm = _require_bound_report(
        project_root,
        path=ACM_AUDIT_PATH,
        expected_sha256=ACM_AUDIT_SHA256,
        expected_schema="M2CA3ADR0025ACMSourceAuditV1",
        expected_status="PASS_EXACT_TWO_ACM_PAIRS_HAVE_OFFICIAL_UPSTREAM_SRDF_EVIDENCE",
    )
    if (
        len(acm.get("pair_evidence", [])) != 2
        or any(item.get("criterion") != "A_OFFICIAL_UPSTREAM_SRDF" for item in acm["pair_evidence"])
        or acm.get("controlled_srdf", {}).get("removed_pair_count") != 0
    ):
        raise A3ACMSmokeAuditError("ACM audit pair evidence differs")
    acm_config_raw = read_regular_file_once(project_root / ACM_CONFIG_PATH)
    adr_raw = read_regular_file_once(project_root / ADR_PATH)
    if _sha256(acm_config_raw) != ACM_CONFIG_FILE_SHA256 or _sha256(adr_raw) != ADR_SHA256:
        raise A3ACMSmokeAuditError("ADR-0025 or ACM configuration bytes differ")
    config = _json_object(acm_config_raw, label="ACM configuration")
    if config.get("configuration_sha256") != ACM_CONFIGURATION_SHA256:
        raise A3ACMSmokeAuditError("ACM embedded configuration SHA-256 differs")

    native = _require_bound_report(
        project_root,
        path=NATIVE_BUILD_REPORT_PATH,
        expected_sha256=NATIVE_BUILD_REPORT_SHA256,
        expected_schema="M2CPhase2A3NativeBuildAuditV1",
        expected_status="PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY",
    )
    fk = _require_bound_report(
        project_root,
        path=FK_REPORT_PATH,
        expected_sha256=FK_REPORT_SHA256,
        expected_schema="M2CControlledPandaFKKDLComparisonAuditV1",
        expected_status="PASS_QUERY_ONLY_FK_MATCHES_INDEPENDENT_NODE2_KDL",
    )
    if (
        native.get("native_build", {}).get("native_shared_object_sha256")
        != EXPECTED_NATIVE_CLOSURE["native_shared_object_sha256"]
        or native.get("native_build", {}).get("builder_image_id") != BUILDER_IMAGE_ID
        or fk.get("provider", {}).get("configuration_sha256")
        != EXPECTED_QUERY["fk_provider_configuration_sha256"]
    ):
        raise A3ACMSmokeAuditError("native-build or FK evidence does not bind the smoke")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "accepted_adr": {
            "path": ADR_PATH.as_posix(),
            "sha256": ADR_SHA256,
            "section": "2",
        },
        "acm_source_audit": {
            "path": ACM_AUDIT_PATH.as_posix(),
            "sha256": ACM_AUDIT_SHA256,
            "configuration_path": ACM_CONFIG_PATH.as_posix(),
            "configuration_file_sha256": ACM_CONFIG_FILE_SHA256,
            "configuration_sha256": ACM_CONFIGURATION_SHA256,
            "authorized_pair_count": 2,
            "criterion": "A_OFFICIAL_UPSTREAM_SRDF",
        },
        "smoke_evidence": {
            "path": smoke_path.as_posix(),
            "sha256": SMOKE_RECEIPT_SHA256,
            "immutable_commit": IMMUTABLE_COMMIT,
            "runtime_image_id": RUNTIME_IMAGE_ID,
            "builder_image_id": BUILDER_IMAGE_ID,
        },
        "native_build_evidence": {
            "path": NATIVE_BUILD_REPORT_PATH.as_posix(),
            "sha256": NATIVE_BUILD_REPORT_SHA256,
            "native_shared_object_sha256": EXPECTED_NATIVE_CLOSURE["native_shared_object_sha256"],
        },
        "read_only_fk_evidence": {
            "path": FK_REPORT_PATH.as_posix(),
            "sha256": FK_REPORT_SHA256,
            "configuration_sha256": EXPECTED_QUERY["fk_provider_configuration_sha256"],
        },
        "source_bindings": EXPECTED_SOURCE_BINDINGS,
        "query_result": EXPECTED_QUERY,
        "evidence_claims": EXPECTED_CLAIMS,
        "remaining_blockers": list(EXPECTED_BLOCKERS),
    }


def report_bytes(report: Mapping[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--smoke-receipt", type=Path, required=True)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    encoded = report_bytes(
        build_report(project_root=args.project_root, smoke_receipt_path=args.smoke_receipt)
    )
    if args.expected_json is not None and read_regular_file_once(args.expected_json) != encoded:
        raise SystemExit("A3 ACM smoke audit differs from expected JSON")
    print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
