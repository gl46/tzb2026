#!/usr/bin/env python3
"""Replay and freeze the eleven observed S4 PATH_BLOCKED TRAIN attempts.

This is an offline evidence auditor, not a packager, trainer, model rollout, or
Q-B evaluator.  Each attempt is checked against the frozen TRAIN manifest and
must match one of three observed, fail-closed classifications.  A previously
written JSON report can be supplied to make any evidence-byte change fatal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "M2CS4PathBlockedTrainCollectionAuditV1"
TRAINING_MANIFEST_SCHEMA = "M2CS4TrainingAndSmokeKeyManifestV1"
S6_MANIFEST_SCHEMA = "M2CS6FrozenEvaluationKeyManifestV1"
JOB_SCHEMA = "M2CPathBlockedCollectionJobV2"
RAW_SCHEMA = "IsaacM1BActuationProbeV1"
CHAIN_SCHEMA = "M2CPathBlockedProbeChainV2"
K8_REJECTION = "PUBLIC_TARGET_OUTSIDE_CANONICAL_K8"
CONTACT_REJECTION = "RAW_PASS_FINAL_FALSE_REGRASP_CONTACT_GATE_REJECTED"
INFRASTRUCTURE_EXIT_139 = "INFRASTRUCTURE_STAGE_EXIT_139"
K8_CONSOLE_SUFFIX = "RuntimeError: public target is outside the fresh canonical K=8 slots"
STAGE_EXIT_139_SUFFIX = "terminating this process with exit code 139."
DECISION_SOURCE = "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
EXPECTED_SKILLS = (
    "GRASP",
    "LIFT",
    "MOVE",
    "PLACE",
    "RELEASE",
    "REOBSERVE",
    "REASSOCIATE_TARGET",
    "REGRASP",
)
EXPECTED_PROTOCOLS = (
    ("world", "m_rad", 3),
    ("world", "m", 3),
    ("world", "m_rad", 3),
    ("world", "m_rad", 3),
    ("world", "m", 3),
    ("policy_rgbd_optical", "none", 0),
    ("world", "none", 0),
    ("world", "m_rad", 3),
)
IDENTITY_FIELDS = (
    "matched_key",
    "scene_seed",
    "failure_seed",
    "sdf_sha256",
    "supervision_sha256",
)
EXPECTED_ATTEMPTS = 11
EXPECTED_K8_REJECTIONS = 8
EXPECTED_CONTACT_REJECTIONS = 2
EXPECTED_INFRASTRUCTURE_FAILURES = 1
EXPECTED_TRAIN_KEYS = 36
INITIAL_ATTEMPTED_SCENE_SEEDS = (12000, 12005, 12008, 12029, 12050, 12071, 12086, 12091)
BATCH02_SELECTED_SCENE_SEEDS = (12143, 12169, 12109)
BATCH02_PREREG_SHA256 = "177820dae82127c7bef30e9ebf7fd479596c5c60f68ccb312c4cf3ddce3a6e89"
BATCH02_PREREG_COMMIT = "b66870e65743f87f8d8ad111c64dd7b81de40161"
BATCH02_RUNTIME_COMMIT = "b6def060326ae78235826cf8600dbe10f29c1a58"
BATCH02_PREREG_REPO_PATH = "docs/decisions/M2C-S4-TRAIN-COLLECTION-BATCH-02-PREREG.md"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _require_false(value: object, *, label: str) -> None:
    if value is not False:
        raise ValueError(f"{label} must be false")


def _validate_content_digest(payload: Mapping[str, Any], *, label: str) -> str:
    embedded = payload.get("manifest_sha256")
    if not isinstance(embedded, str) or _SHA256.fullmatch(embedded) is None:
        raise ValueError(f"{label} has no valid content digest")
    without_digest = dict(payload)
    without_digest.pop("manifest_sha256", None)
    if canonical_sha256(without_digest) != embedded:
        raise ValueError(f"{label} content digest mismatch")
    return embedded


def _records_by_key(
    values: object, *, expected_count: int, role: str, split: str, label: str
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(values, list) or len(values) != expected_count:
        raise ValueError(f"{label} must contain exactly {expected_count} records")
    records: dict[str, Mapping[str, Any]] = {}
    for record in values:
        if not isinstance(record, Mapping):
            raise ValueError(f"{label} contains a non-object record")
        key = record.get("matched_key")
        if not isinstance(key, str) or not key or key in records:
            raise ValueError(f"{label} keys are missing or duplicated")
        if record.get("role") != role or record.get("split") != split:
            raise ValueError(f"{label} record {key} has the wrong role or split")
        for field in ("sdf_sha256", "supervision_sha256"):
            value = record.get(field)
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{label} record {key} has invalid {field}")
        records[key] = record
    return records


def load_frozen_manifests(training_path: Path, s6_path: Path) -> dict[str, Any]:
    training = _load_object(training_path, label="frozen S4 training manifest")
    s6 = _load_object(s6_path, label="frozen S6 evaluation manifest")
    if training.get("schema_version") != TRAINING_MANIFEST_SCHEMA:
        raise ValueError("unsupported frozen S4 training manifest schema")
    if s6.get("schema_version") != S6_MANIFEST_SCHEMA:
        raise ValueError("unsupported frozen S6 evaluation manifest schema")
    for name, manifest in (("training", training), ("S6", s6)):
        if manifest.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION":
            raise ValueError(f"{name} manifest is not frozen before execution")
        _require_false(manifest.get("teacher_used"), label=f"{name} manifest teacher_used")
        _require_false(
            manifest.get("privileged_truth_policy_input"),
            label=f"{name} manifest privileged_truth_policy_input",
        )
    training_content_sha = _validate_content_digest(training, label="training manifest")
    s6_content_sha = _validate_content_digest(s6, label="S6 manifest")
    train_records = _records_by_key(
        training.get("training_keys"),
        expected_count=EXPECTED_TRAIN_KEYS,
        role="TRAIN",
        split="train",
        label="frozen TRAIN keys",
    )
    smoke_records = _records_by_key(
        training.get("physical_prerequisite_smoke_keys"),
        expected_count=3,
        role="SMOKE",
        split="val",
        label="frozen SMOKE keys",
    )
    evaluation_records = _records_by_key(
        s6.get("evaluation_keys"),
        expected_count=30,
        role="EVALUATION",
        split="test",
        label="frozen S6 keys",
    )
    if training.get("s6_evaluation_key_digest") != canonical_sha256(list(s6["evaluation_keys"])):
        raise ValueError("training manifest does not bind the frozen S6 records")
    all_keys = set(train_records) | set(smoke_records) | set(evaluation_records)
    if len(all_keys) != EXPECTED_TRAIN_KEYS + 3 + 30:
        raise ValueError("TRAIN, SMOKE, and S6 frozen key sets overlap")
    v4_keys = set(training.get("v4_excluded_matched_keys", []))
    v4_scenes = set(training.get("v4_excluded_scene_seeds", []))
    if len(v4_keys) != 3 or len(v4_scenes) != 3:
        raise ValueError("training manifest does not contain the three frozen V4 exclusions")
    return {
        "training": training,
        "s6": s6,
        "train_records": train_records,
        "smoke_records": smoke_records,
        "evaluation_records": evaluation_records,
        "v4_keys": v4_keys,
        "v4_scenes": v4_scenes,
        "bindings": {
            "training_manifest": {
                "path": str(training_path.resolve()),
                "file_sha256": sha256_file(training_path),
                "content_sha256": training_content_sha,
            },
            "s6_manifest": {
                "path": str(s6_path.resolve()),
                "file_sha256": sha256_file(s6_path),
                "content_sha256": s6_content_sha,
            },
        },
    }


def validate_batch02_prereg(
    path: Path, *, train_records: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    if sha256_file(path) != BATCH02_PREREG_SHA256:
        raise ValueError("batch-02 preregistration file SHA-256 mismatch")
    text = path.read_text(encoding="utf-8")
    required_fragments = (
        "Status: pre-registered before observing any batch-02 execution result",
        "Runtime implementation commit:\n  `b6def060326ae78235826cf8600dbe10f29c1a58`",
        "The batch stops after the three selected records regardless of outcomes.",
        "Teacher use, model rollout, training, Q-B evaluation, and privileged truth",
    )
    if any(fragment not in text for fragment in required_fragments):
        raise ValueError("batch-02 preregistration contract text is incomplete")
    project = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", f"{BATCH02_PREREG_COMMIT}^{{commit}}"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        committed = subprocess.run(
            ["git", "show", f"{commit}:{BATCH02_PREREG_REPO_PATH}"],
            cwd=project,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError("batch-02 preregistration commit is unavailable") from error
    if commit != BATCH02_PREREG_COMMIT:
        raise ValueError("batch-02 preregistration commit did not resolve exactly")
    if hashlib.sha256(committed).hexdigest() != BATCH02_PREREG_SHA256:
        raise ValueError("batch-02 preregistration differs from its committed bytes")
    remaining_by_sdf: dict[str, list[Mapping[str, Any]]] = {}
    for record in train_records.values():
        if record["scene_seed"] in INITIAL_ATTEMPTED_SCENE_SEEDS:
            continue
        remaining_by_sdf.setdefault(str(record["sdf_sha256"]), []).append(record)
    selected = sorted(
        (
            min(records, key=lambda item: int(item["scene_seed"]))
            for records in remaining_by_sdf.values()
        ),
        key=lambda item: BATCH02_SELECTED_SCENE_SEEDS.index(int(item["scene_seed"])),
    )
    if tuple(int(item["scene_seed"]) for item in selected) != BATCH02_SELECTED_SCENE_SEEDS:
        raise ValueError("batch-02 preregistration selection rule does not reproduce three keys")
    for record in selected:
        fragments = (
            str(record["scene_seed"]),
            str(record["failure_seed"]),
            str(record["matched_key"]),
            str(record["sdf_sha256"]),
        )
        if any(fragment not in text for fragment in fragments):
            raise ValueError("batch-02 preregistration does not bind a selected TRAIN identity")
    return {
        "path": str(path.resolve()),
        "file_sha256": BATCH02_PREREG_SHA256,
        "commit": BATCH02_PREREG_COMMIT,
        "runtime_implementation_commit": BATCH02_RUNTIME_COMMIT,
        "selection_rule_recomputed": True,
        "selected_scene_seeds": list(BATCH02_SELECTED_SCENE_SEEDS),
        "selected_matched_keys": [str(item["matched_key"]) for item in selected],
    }


def _regular_files(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"attempt root must be a regular directory: {root}")
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"attempt evidence may not contain symlinks: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256_file(path)
        elif not path.is_dir():
            raise ValueError(f"attempt evidence contains a non-regular entry: {path}")
    if not result:
        raise ValueError(f"attempt root contains no files: {root}")
    return result


def _find_one(root: Path, candidates: Sequence[str], *, label: str) -> Path:
    found = [root / name for name in candidates if (root / name).is_file()]
    if len(found) != 1 or found[0].is_symlink():
        raise ValueError(f"attempt root must contain exactly one {label}")
    return found[0]


def _find_optional_one(root: Path, candidates: Sequence[str], *, label: str) -> Path | None:
    found = [root / name for name in candidates if (root / name).is_file()]
    if len(found) > 1 or any(path.is_symlink() for path in found):
        raise ValueError(f"attempt root contains ambiguous {label}")
    return found[0] if found else None


def _verify_files_manifest(root: Path, manifest_path: Path, tree: Mapping[str, str]) -> None:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            expected, raw_path = line.split("  ", 1)
        except ValueError as error:
            raise ValueError(f"files.sha256 line {line_number} is malformed") from error
        if _SHA256.fullmatch(expected) is None:
            raise ValueError(f"files.sha256 line {line_number} has an invalid digest")
        absolute = Path(raw_path)
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("files.sha256 entry escapes its attempt root") from error
        if relative in entries:
            raise ValueError("files.sha256 contains a duplicate path")
        entries[relative] = expected
    manifest_relative = manifest_path.relative_to(root).as_posix()
    if set(entries) != set(tree):
        raise ValueError("files.sha256 coverage differs from the evidence tree")
    # A hash manifest cannot cryptographically bind its own final bytes.  The
    # report binds the actual manifest SHA and verifies every non-self entry.
    for relative, actual in tree.items():
        if relative != manifest_relative and entries[relative] != actual:
            raise ValueError(f"files.sha256 mismatch for {relative}")


def _validate_stage_metrics(
    path: Path, identity: Mapping[str, Any], job: Mapping[str, Any]
) -> None:
    metrics = _load_object(path, label="stage metrics")
    if metrics.get("status") != "PASS":
        raise ValueError("stage metrics status must be PASS")
    source_hashes = metrics.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ValueError("stage metrics lacks source hashes")
    scene = identity["scene_seed"]
    expected = {
        f"scene-{scene}.sdf": identity["sdf_sha256"],
        f"scene-{scene}.supervision.json": identity["supervision_sha256"],
        "panda_controlled.urdf": job.get("urdf_sha256"),
    }
    if dict(source_hashes) != expected:
        raise ValueError("stage metrics source hashes differ from frozen identity")


def _validate_job(
    job: Mapping[str, Any], frozen: Mapping[str, Any], *, training_path: Path, s6_path: Path
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    if job.get("schema_version") != JOB_SCHEMA:
        raise ValueError("unsupported collection job schema")
    key = job.get("matched_key")
    scene = job.get("scene_seed")
    if key in frozen["smoke_records"]:
        raise ValueError("SMOKE key is forbidden in the TRAIN audit")
    if key in frozen["evaluation_records"]:
        raise ValueError("S6 evaluation key is forbidden in the TRAIN audit")
    if key in frozen["v4_keys"] or scene in frozen["v4_scenes"]:
        raise ValueError("V4 key or scene is forbidden in the TRAIN audit")
    record = frozen["train_records"].get(key)
    if record is None:
        raise ValueError("collection job key is not a frozen TRAIN key")
    if job.get("collection_role") != "TRAIN" or job.get("split") != "train":
        raise ValueError("collection job must have TRAIN/train role and split")
    for field in IDENTITY_FIELDS:
        if job.get(field) != record.get(field):
            raise ValueError(f"collection job {field} differs from frozen TRAIN identity")
    expected = {
        "decision_source": DECISION_SOURCE,
        "status": "PREPARED_NOT_EXECUTED",
        "model_owned": False,
        "model_rollout": False,
        "training_executed": False,
        "evaluation_executed": False,
        "formal_q_b_evaluation": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "training_key_manifest_sha256": sha256_file(training_path),
        "s6_key_manifest_sha256": sha256_file(s6_path),
    }
    for field, value in expected.items():
        if job.get(field) != value:
            raise ValueError(f"collection job has invalid {field}")
    for field in ("derived_probe_sha256", "upstream_v4_probe_sha256", "urdf_sha256"):
        value = job.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ValueError(f"collection job has invalid {field}")
    identity = {field: record[field] for field in IDENTITY_FIELDS}
    return record, identity


def _validate_partial_receipt(
    path: Path | None,
    *,
    identity: Mapping[str, Any],
    console_path: Path,
    job_path: Path,
) -> None:
    if path is None:
        return
    payload = _load_object(path, label="partial public RGB-D receipt")
    if payload.get("schema_version") != "M2CPartialPublicRGBDAuditInputV1":
        raise ValueError("partial public RGB-D receipt schema is unsupported")
    for field in IDENTITY_FIELDS:
        if payload.get(field) != identity[field]:
            raise ValueError(f"partial public RGB-D receipt has wrong {field}")
    if payload.get("probe_console_sha256") != sha256_file(console_path):
        raise ValueError("partial public RGB-D receipt console SHA mismatch")
    if payload.get("collection_job_sha256") != sha256_file(job_path):
        raise ValueError("partial public RGB-D receipt collection job SHA mismatch")
    _require_false(payload.get("teacher_used"), label="partial receipt teacher_used")
    _require_false(
        payload.get("privileged_truth_policy_input"),
        label="partial receipt privileged_truth_policy_input",
    )


def _validate_k8_rejection(
    root: Path, *, console_path: Path, raw_path: Path | None, identity: Mapping[str, Any]
) -> dict[str, Any]:
    del identity
    if raw_path is not None:
        raise ValueError("K8 rejection classification forbids a raw probe envelope")
    console = console_path.read_text(encoding="utf-8", errors="strict")
    if not console.rstrip().endswith(K8_CONSOLE_SUFFIX):
        raise ValueError("console does not end in the exact canonical K8 rejection")
    if "actuation-probe.json" in {path.name for path in root.rglob("*") if path.is_file()}:
        raise ValueError("K8 rejection attempt contains an unexpected raw probe")
    return {
        "raw_probe_present": False,
        "console_terminal_exception": K8_CONSOLE_SUFFIX,
        "final_task_success": None,
        "regrasp_controller_gate": None,
        "regrasp_status": None,
    }


def _validate_infrastructure_exit_139(
    root: Path, *, console_path: Path, raw_path: Path | None
) -> dict[str, Any]:
    if raw_path is not None:
        raise ValueError("infrastructure stage-exit classification forbids a raw probe")
    probe_dir = root / "probe"
    if probe_dir.exists() and (not probe_dir.is_dir() or any(probe_dir.iterdir())):
        raise ValueError(
            "infrastructure stage-exit classification permits only an empty probe directory"
        )
    if (root / "metrics.json").exists() or (root / "stage/metrics.json").exists():
        raise ValueError("infrastructure stage-exit classification forbids stage metrics")
    console = console_path.read_text(encoding="utf-8", errors="strict")
    if not console.rstrip().endswith(STAGE_EXIT_139_SUFFIX):
        raise ValueError("stage console does not end in the exact exit-139 receipt")
    if "[Fatal] [carb.crashreporter-breakpad.plugin]" not in console:
        raise ValueError("stage exit 139 lacks a fatal crash-reporter receipt")
    return {
        "stage_console_terminal_receipt": STAGE_EXIT_139_SUFFIX,
        "stage_metrics_present": False,
        "probe_directory_present_but_empty": probe_dir.is_dir(),
        "raw_probe_present": False,
        "final_task_success": None,
        "infrastructure_failure": True,
    }


def _check_chain_false_fields(value: Mapping[str, Any], *, label: str) -> None:
    _require_false(value.get("teacher_used"), label=f"{label}.teacher_used")
    _require_false(
        value.get("privileged_truth_policy_input"),
        label=f"{label}.privileged_truth_policy_input",
    )


def _validate_raw_contact_rejection(
    raw_path: Path | None, *, identity: Mapping[str, Any]
) -> dict[str, Any]:
    if raw_path is None:
        raise ValueError("raw-contact rejection classification requires a raw probe")
    raw = _load_object(raw_path, label="raw actuation probe")
    if raw.get("schema_version") != RAW_SCHEMA or raw.get("status") != "PASS":
        raise ValueError("raw probe must be a complete IsaacM1BActuationProbeV1 PASS")
    if raw.get("not_policy_rollout") is not True:
        raise ValueError("raw probe must state not_policy_rollout=true")
    chain = raw.get("m2c_path_blocked_physical_chain")
    if not isinstance(chain, Mapping) or chain.get("schema_version") != CHAIN_SCHEMA:
        raise ValueError("raw probe lacks the frozen physical chain")
    for field in IDENTITY_FIELDS:
        if chain.get(field) != identity[field]:
            raise ValueError(f"raw physical chain has wrong {field}")
    expected_chain = {
        "collection_role": "TRAIN",
        "split": "train",
        "failure_type": "PATH_BLOCKED",
        "evidence_origin": "ISAAC_PHYSICAL_INTEGRATION",
        "model_rollout": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "final_task_success": False,
    }
    for field, value in expected_chain.items():
        if chain.get(field) != value:
            raise ValueError(f"raw physical chain has invalid {field}")
    steps = chain.get("steps")
    if not isinstance(steps, list) or len(steps) != len(EXPECTED_SKILLS):
        raise ValueError("raw physical chain must contain exactly eight steps")
    for index, (step, skill) in enumerate(zip(steps, EXPECTED_SKILLS, strict=True)):
        if not isinstance(step, Mapping) or step.get("decision_index") != index:
            raise ValueError("raw physical chain decision indices are not contiguous")
        _check_chain_false_fields(step, label=f"step[{index}]")
        observation = step.get("observation")
        receipts = step.get("physical_receipts")
        if (
            not isinstance(observation, Mapping)
            or not isinstance(receipts, list)
            or len(receipts) != 1
        ):
            raise ValueError(f"raw step {index} lacks one observation and one receipt")
        _check_chain_false_fields(observation, label=f"step[{index}].observation")
        receipt = receipts[0]
        if not isinstance(receipt, Mapping):
            raise ValueError(f"raw step {index} receipt is not an object")
        _check_chain_false_fields(receipt, label=f"step[{index}].receipt")
        receipt_core = dict(receipt)
        receipt_sha = receipt_core.pop("receipt_sha256", None)
        if receipt_sha != canonical_sha256(receipt_core):
            raise ValueError(f"raw step {index} physical receipt digest mismatch")
        if receipt.get("executed_skill") != skill or receipt.get("physically_executed") is not True:
            raise ValueError(f"raw step {index} has the wrong executed skill")
        if receipt.get("execution_source") != DECISION_SOURCE:
            raise ValueError(f"raw step {index} is not scripted public supervision")
        protocol = receipt.get("action_protocol")
        frame, units, dimensions = EXPECTED_PROTOCOLS[index]
        expected_protocol = {
            "schema_version": "PhysicalActionProtocolV2",
            "coordinate_frame": frame,
            "units": units,
            "dimensions": dimensions,
            "frequency_hz": 60,
            "normalization": "none",
        }
        if protocol != expected_protocol:
            raise ValueError(f"raw step {index} action protocol differs from the frozen wire")
        controller = receipt.get("controller_gate")
        measurements = receipt.get("execution_measurements")
        if index < len(EXPECTED_SKILLS) - 1 and controller != "PASS":
            raise ValueError(f"raw step {index} controller gate did not pass")
        if index == len(EXPECTED_SKILLS) - 1:
            if controller != "REJECTED" or not isinstance(measurements, Mapping):
                raise ValueError("raw regrasp does not contain a rejected controller receipt")
            if measurements.get("status") != "CONTACT_GATE_REJECTED":
                raise ValueError("raw regrasp is not CONTACT_GATE_REJECTED")
            if measurements.get("object_lift_m") != 0.0:
                raise ValueError("raw rejected regrasp unexpectedly lifted the task object")
    return {
        "raw_probe_present": True,
        "raw_probe_status": "PASS",
        "physical_chain_steps": len(steps),
        "final_task_success": False,
        "regrasp_controller_gate": "REJECTED",
        "regrasp_status": "CONTACT_GATE_REJECTED",
        "execution_source": DECISION_SOURCE,
    }


def audit_attempt(
    root: Path,
    classification: str,
    *,
    frozen: Mapping[str, Any],
    training_path: Path,
    s6_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    tree = _regular_files(root)
    job_path = _find_one(root, ("collection-job-v2.json",), label="collection job")
    console_candidates = (
        ("stage/console.log",)
        if classification == INFRASTRUCTURE_EXIT_139
        else ("probe-console.log", "probe/console.log")
    )
    console_path = _find_one(root, console_candidates, label="classification console")
    metrics_path = _find_optional_one(
        root, ("metrics.json", "stage/metrics.json"), label="stage metrics"
    )
    raw_path = _find_optional_one(
        root,
        ("actuation-probe.json", "probe/actuation-probe.json"),
        label="raw actuation probe",
    )
    partial_path = _find_optional_one(
        root, ("partial-public-rgbd.json",), label="partial public RGB-D receipt"
    )
    files_manifest = _find_optional_one(root, ("files.sha256",), label="files manifest")
    job = _load_object(job_path, label="collection job")
    _record, identity = _validate_job(job, frozen, training_path=training_path, s6_path=s6_path)
    if classification == INFRASTRUCTURE_EXIT_139:
        if metrics_path is not None:
            raise ValueError("infrastructure stage-exit classification forbids stage metrics")
    elif metrics_path is None:
        raise ValueError("non-infrastructure attempt requires stage metrics")
    else:
        _validate_stage_metrics(metrics_path, identity, job)
    _validate_partial_receipt(
        partial_path,
        identity=identity,
        console_path=console_path,
        job_path=job_path,
    )
    if files_manifest is not None:
        _verify_files_manifest(root, files_manifest, tree)
    if classification == K8_REJECTION:
        details = _validate_k8_rejection(
            root, console_path=console_path, raw_path=raw_path, identity=identity
        )
    elif classification == CONTACT_REJECTION:
        details = _validate_raw_contact_rejection(raw_path, identity=identity)
    elif classification == INFRASTRUCTURE_EXIT_139:
        details = _validate_infrastructure_exit_139(
            root, console_path=console_path, raw_path=raw_path
        )
    else:
        raise ValueError(f"unsupported expected classification: {classification}")
    forbidden_packages = {
        "collection-receipt-v2.json",
        "packaged-physical-chain-v2.json",
        "supervised-steps-v2.json",
    }
    if forbidden_packages & {Path(relative).name for relative in tree}:
        raise ValueError("attempt contains a packaged training artifact")
    core_relative = {
        job_path.relative_to(root).as_posix(),
        console_path.relative_to(root).as_posix(),
    }
    if metrics_path is not None:
        core_relative.add(metrics_path.relative_to(root).as_posix())
    for optional in (raw_path, partial_path, files_manifest):
        if optional is not None:
            core_relative.add(optional.relative_to(root).as_posix())
    for name in (
        "derived-path-blocked-probe.py",
        "offline-audit.json",
        "m2b-record-template.txt",
        "stage/m1b_physics_scene.usdc",
        "stage/m1b_scene.usda",
        "stage/runtime_frames.jsonl",
        "stage/supervision_frames.jsonl",
    ):
        if name in tree:
            core_relative.add(name)
    return {
        "attempt_root": str(root),
        "classification": classification,
        "identity": identity,
        "frozen_role": "TRAIN",
        "frozen_split": "train",
        "core_evidence_sha256": {name: tree[name] for name in sorted(core_relative)},
        "evidence_file_sha256": {
            name: digest for name, digest in sorted(tree.items()) if name != "files.sha256"
        },
        "auxiliary_files_manifest_sha256": tree.get("files.sha256"),
        "evidence_tree": {
            "regular_file_count": len(tree),
            "canonical_path_sha256_map_digest": canonical_sha256(tree),
            "files_manifest_present": files_manifest is not None,
            "files_manifest_trusted_as_root": False,
            "files_manifest_non_self_entries_verified_as_auxiliary": files_manifest is not None,
            "files_manifest_self_entry_cryptographically_verified": False,
        },
        "classification_evidence": details,
        "training_sample_packaged": False,
        "training_sample_eligible": False,
        "model_owned": False,
        "model_rollout": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "formal_q_b_evaluation": False,
        "counted_as_pure_model_success": False,
        "declared_probe_bindings": {
            "derived_probe_sha256": job["derived_probe_sha256"],
            "upstream_v4_probe_sha256": job["upstream_v4_probe_sha256"],
            "runtime_registry_sha256": job.get("runtime_registry_sha256"),
            "urdf_sha256": job["urdf_sha256"],
        },
    }


def build_report(
    attempt_specs: Sequence[tuple[Path, str]],
    *,
    training_path: Path,
    s6_path: Path,
    batch02_prereg_path: Path,
) -> dict[str, Any]:
    if len(attempt_specs) != EXPECTED_ATTEMPTS:
        raise ValueError(f"audit requires exactly {EXPECTED_ATTEMPTS} attempt roots")
    counts = {
        K8_REJECTION: sum(kind == K8_REJECTION for _, kind in attempt_specs),
        CONTACT_REJECTION: sum(kind == CONTACT_REJECTION for _, kind in attempt_specs),
        INFRASTRUCTURE_EXIT_139: sum(kind == INFRASTRUCTURE_EXIT_139 for _, kind in attempt_specs),
    }
    if (
        counts[K8_REJECTION] != EXPECTED_K8_REJECTIONS
        or counts[CONTACT_REJECTION] != EXPECTED_CONTACT_REJECTIONS
        or counts[INFRASTRUCTURE_EXIT_139] != EXPECTED_INFRASTRUCTURE_FAILURES
    ):
        raise ValueError(
            "audit requires exactly eight K8, two raw-contact, and one exit-139 classification"
        )
    frozen = load_frozen_manifests(training_path, s6_path)
    batch02_binding = validate_batch02_prereg(
        batch02_prereg_path, train_records=frozen["train_records"]
    )
    attempts = [
        audit_attempt(
            root,
            classification,
            frozen=frozen,
            training_path=training_path,
            s6_path=s6_path,
        )
        for root, classification in attempt_specs
    ]
    keys = [str(item["identity"]["matched_key"]) for item in attempts]
    if len(keys) != len(set(keys)):
        raise ValueError("audited TRAIN keys are duplicated")
    scenes = [int(item["identity"]["scene_seed"]) for item in attempts]
    if len(scenes) != len(set(scenes)):
        raise ValueError("audited TRAIN scene seeds are duplicated")
    batch02_attempts = [
        item
        for item in attempts
        if int(item["identity"]["scene_seed"]) in BATCH02_SELECTED_SCENE_SEEDS
    ]
    if {int(item["identity"]["scene_seed"]) for item in batch02_attempts} != set(
        BATCH02_SELECTED_SCENE_SEEDS
    ):
        raise ValueError("audit does not contain exactly the preregistered batch-02 keys")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_ZERO_ELIGIBLE_TRAIN_SAMPLES",
        "evidence_use": "TRAIN_COLLECTION_AUDIT_ONLY_NOT_Q_B_EVALUATION",
        "finding": (
            "eleven unique frozen TRAIN keys were attempted: eight exited before a raw "
            "probe because the public target was outside canonical K=8; two produced "
            "complete scripted raw PASS envelopes but failed final regrasp at "
            "CONTACT_GATE_REJECTED; one stage crashed with infrastructure exit 139"
        ),
        "frozen_manifest_bindings": frozen["bindings"],
        "batch02_preregistration_binding": batch02_binding,
        "scope": {
            "frozen_training_keys": EXPECTED_TRAIN_KEYS,
            "unique_training_keys_audited": len(keys),
            "unobserved_training_keys": EXPECTED_TRAIN_KEYS - len(keys),
            "inference_about_unobserved_training_keys": None,
            "smoke_keys_used": 0,
            "s6_evaluation_keys_used": 0,
            "v4_keys_used": 0,
        },
        "observed_counts": {
            "public_target_outside_canonical_k8": counts[K8_REJECTION],
            "raw_pass_final_false_regrasp_contact_gate_rejected": counts[CONTACT_REJECTION],
            "infrastructure_stage_exit_139": counts[INFRASTRUCTURE_EXIT_139],
            "training_samples_packaged": 0,
            "training_samples_eligible": 0,
        },
        "execution_boundaries": {
            "training_executed": False,
            "model_rollout_executed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "formal_q_b_evaluation_executed": False,
            "scripted_collection_counted_as_pure_model_success": False,
            "pure_model_success_episodes": None,
        },
        "attempts": attempts,
        "task_report": {
            "changed_files": [
                "scripts/m2c/audit_path_blocked_train_collection.py",
                "tests/unit/test_m2c_path_blocked_train_collection_audit.py",
                "reports/m2c-s4-path-blocked-train-collection.json",
                "reports/m2c-s4-path-blocked-train-collection.md",
            ],
            "tests": [
                ".venv/bin/pytest -q tests/unit/test_m2c_path_blocked_train_collection_audit.py",
                ".venv/bin/ruff check scripts/m2c/audit_path_blocked_train_collection.py tests/unit/test_m2c_path_blocked_train_collection_audit.py",
                'for audit_file in scripts/m2c/audit_path_blocked_train_collection.py tests/unit/test_m2c_path_blocked_train_collection_audit.py reports/m2c-s4-path-blocked-train-collection.json reports/m2c-s4-path-blocked-train-collection.md; do git diff --no-index --check /dev/null "$audit_file" || test $? -eq 1; done',
            ],
            "failures": [
                "initial bare pytest command was unavailable; project .venv command was used",
                "initial evidence replay exposed per-skill action-protocol differences; frozen observed protocols were then encoded and retested",
            ],
            "blockers": [
                "zero packaged or eligible TRAIN samples",
                "25 frozen TRAIN keys remain unobserved; this audit makes no inference about them",
                "systemic public K8/regrasp admissibility failures require human ADR direction",
            ],
            "next_command": "STOP_BATCH_COLLECTION_AND_REQUEST_HUMAN_ADR_DIRECTION",
            "batch03_preregistered": False,
        },
    }


def verify_expected_report(actual: Mapping[str, Any], expected_path: Path) -> None:
    expected = _load_object(expected_path, label="expected collection audit report")
    if actual != expected:
        raise ValueError("replayed collection audit differs from the frozen expected report")


def _attempt_spec(value: str) -> tuple[Path, str]:
    try:
        classification, raw_path = value.split("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("attempt must be CLASSIFICATION=PATH") from error
    if (
        classification not in {K8_REJECTION, CONTACT_REJECTION, INFRASTRUCTURE_EXIT_139}
        or not raw_path
    ):
        raise argparse.ArgumentTypeError("attempt classification or path is invalid")
    return Path(raw_path), classification


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", action="append", type=_attempt_spec, required=True)
    parser.add_argument(
        "--training-keys", type=Path, default=project / "configs/m2c_s4_training_keys.json"
    )
    parser.add_argument(
        "--s6-keys", type=Path, default=project / "configs/m2c_s6_evaluation_keys.json"
    )
    parser.add_argument(
        "--batch02-prereg",
        type=Path,
        default=project / BATCH02_PREREG_REPO_PATH,
    )
    parser.add_argument("--expected-report", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(
        args.attempt,
        training_path=args.training_keys,
        s6_path=args.s6_keys,
        batch02_prereg_path=args.batch02_prereg,
    )
    if args.expected_report is not None:
        verify_expected_report(report, args.expected_report)
    if args.output is not None:
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite report: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    elif args.expected_report is None:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
