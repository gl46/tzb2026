#!/usr/bin/env python3
"""Package one M2C PATH_BLOCKED Isaac TRAIN/SMOKE chain, fail closed.

This host-side tool never executes Isaac, trains a model, or evaluates a
model-owned rollout.  It binds one already-written physical probe to frozen
key/manifests, validates eight fresh public RGB-D observations and eight
physical receipts, and atomically publishes a supervised training bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping


def _bootstrap_option(argv: list[str], name: str) -> str | None:
    prefix = f"{name}="
    matches: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value.startswith(prefix):
            candidate = value[len(prefix) :]
            if not candidate:
                raise RuntimeError(f"pre-import option {name} has an empty value")
            matches.append(candidate)
        elif value == name:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise RuntimeError(f"pre-import option {name} lacks a value")
            matches.append(argv[index + 1])
            index += 1
        index += 1
    if len(matches) > 1:
        raise RuntimeError(f"pre-import option {name} is repeated")
    return matches[0] if matches else None


def _bootstrap_git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pre-import git {' '.join(args)} failed")
    return completed.stdout


def _bootstrap_read_regular(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("pre-import preregistration is not a single regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _preimport_v3_checkout_guard(*, project_root: Path, prereg_path: Path) -> None:
    root = project_root.resolve(strict=True)
    prereg = prereg_path.resolve(strict=True)
    try:
        relative = prereg.relative_to(root).as_posix()
    except ValueError as error:
        raise RuntimeError("pre-import preregistration escapes the project root") from error
    raw = _bootstrap_read_regular(prereg)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("pre-import preregistration is not strict JSON") from error
    if not isinstance(payload, dict) or payload.get("repository_relative_path") != relative:
        raise RuntimeError("pre-import preregistration path binding is invalid")
    head = _bootstrap_git(root, "rev-parse", "HEAD").decode().strip()
    introductions = (
        _bootstrap_git(root, "log", "--diff-filter=A", "--format=%H", "--", relative)
        .decode()
        .splitlines()
    )
    if not introductions or head != introductions[0]:
        raise RuntimeError("pre-import preregistration must be the current HEAD")
    if _bootstrap_git(root, "show", f"HEAD:{relative}") != raw:
        raise RuntimeError("pre-import preregistration differs from HEAD bytes")
    changed = set(
        _bootstrap_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head)
        .decode()
        .splitlines()
    )
    if changed != {relative}:
        raise RuntimeError("pre-import preregistration commit is not prereg-only")
    if _bootstrap_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ):
        raise RuntimeError("pre-import host checkout is not clean")
    if _bootstrap_git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        "src/xh_agent",
        "scripts/m2c",
    ):
        raise RuntimeError("pre-import runtime roots contain ignored shadow bytes")
    sys.dont_write_bytecode = True


def _run_cli_preimport_guard() -> None:
    argv = sys.argv[1:]
    if (_bootstrap_option(argv, "--revision") or "V3") == "V2":
        return
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.dont_write_bytecode
        and sys.flags.safe_path
    ):
        raise RuntimeError("V3 CLI must use the project venv Python with -I -S -B")
    prereg = _bootstrap_option(argv, "--collection-prereg")
    if not prereg:
        raise RuntimeError("V3 CLI requires a committed preregistration")
    root = Path(__file__).resolve().parents[2]
    _preimport_v3_checkout_guard(
        project_root=root,
        prereg_path=Path(prereg),
    )
    venv_root = Path(sys.executable).absolute().parent.parent
    site_packages = (
        venv_root
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    if not site_packages.is_dir():
        raise RuntimeError("V3 isolated host dependency directory is unavailable")
    sys.path[:0] = [str(root / "scripts"), str(root / "src"), str(site_packages)]


if __name__ == "__main__":
    try:
        _run_cli_preimport_guard()
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"M2C V3 pre-import gate blocked: {error}") from error


from m2c.derive_model_owned_chain_probe import (  # noqa: E402
    build_collection_manifests,
    derive_probe_bytes,
    derive_probe_bytes_v3,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v2 import (  # noqa: E402
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
    build_path_blocked_supervised_dataset,
    canonical_manifest_sha256,
    package_probe_payload,
)
from xh_agent.policy.qrm_lite.path_blocked_supervision_v3 import (  # noqa: E402
    M2CPathBlockedProbeChainV3,
    V3_MANIFEST_FILE_SHA256,
    build_path_blocked_supervised_dataset_v3,
    load_v3_training_manifest,
    package_probe_chain_v3,
    recompute_candidate_payload_v3,
)
from xh_agent.policy.qrm_lite.s4_v3_collection_authorization_v1 import (  # noqa: E402
    read_regular_file_once,
    require_v3_host_runtime_launcher,
    verify_packaging_authorization,
)


DECISION_SOURCE = "SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION"
EXPECTED_STEP_COUNT = 8
FROZEN_TRAINING_KEYS_FILE_SHA256 = (
    "ca2162a898853ee04600aaf9246c121ac0604754638e497d1824b159c161fd94"
)
FROZEN_TRAINING_KEYS_MANIFEST_SHA256 = (
    "f5dc3566d028821f5df48afd07f133ea94af21fae21ec8bd5be63644893145e2"
)
FROZEN_S6_KEYS_FILE_SHA256 = "ce1440966d31dda6b3f0e06c41a19dc654ebc734a6597d6346ec9df3c5f0d2ba"
FROZEN_S6_KEYS_MANIFEST_SHA256 = "0ce322d948dac851d7a26053af0207e563a69bb0127c462312cdad9badafe419"
FROZEN_RUNTIME_REGISTRY_SHA256 = "3572f80f1597b7f3bdffb1f8aad90d5baeb086b25c371b88511bc58444813359"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return payload


def _embedded_manifest_sha_is_valid(payload: Mapping[str, Any], *, label: str) -> None:
    embedded = payload.get("manifest_sha256")
    if not isinstance(embedded, str):
        raise ValueError(f"{label} is missing manifest_sha256")
    without_digest = dict(payload)
    without_digest.pop("manifest_sha256", None)
    if canonical_sha256(without_digest) != embedded:
        raise ValueError(f"{label} embedded manifest_sha256 mismatch")


def project_frozen_manifests(
    training_keys_path: Path,
    s6_keys_path: Path,
    runtime_registry_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    FrozenPathBlockedCollectionManifestV2,
    FrozenS6ExclusionManifestV2,
]:
    for path, label in (
        (training_keys_path, "training key manifest"),
        (s6_keys_path, "S6 key manifest"),
        (runtime_registry_path, "runtime registry"),
    ):
        if not path.is_file():
            raise ValueError(f"{label} does not exist")
    if sha256_file(runtime_registry_path) != FROZEN_RUNTIME_REGISTRY_SHA256:
        raise ValueError("runtime registry differs from the frozen checked-in file")
    training_keys = load_json_object(training_keys_path, label="training key manifest")
    s6_keys = load_json_object(s6_keys_path, label="S6 key manifest")
    _embedded_manifest_sha_is_valid(training_keys, label="training key manifest")
    _embedded_manifest_sha_is_valid(s6_keys, label="S6 key manifest")
    if training_keys.get("manifest_sha256") != FROZEN_TRAINING_KEYS_MANIFEST_SHA256:
        raise ValueError("training key manifest identity is not the frozen S4 identity")
    if s6_keys.get("manifest_sha256") != FROZEN_S6_KEYS_MANIFEST_SHA256:
        raise ValueError("S6 key manifest identity is not the frozen S6 identity")
    if sha256_file(training_keys_path) != FROZEN_TRAINING_KEYS_FILE_SHA256:
        raise ValueError("training key manifest differs from the frozen checked-in file")
    if sha256_file(s6_keys_path) != FROZEN_S6_KEYS_FILE_SHA256:
        raise ValueError("S6 key manifest differs from the frozen checked-in file")
    if (
        training_keys.get("schema_version") != "M2CS4TrainingAndSmokeKeyManifestV1"
        or training_keys.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION"
        or training_keys.get("selection_uses_rollout_outcomes") is not False
        or training_keys.get("teacher_used") is not False
        or training_keys.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("training key manifest is not a frozen public-only S4 manifest")
    if (
        s6_keys.get("schema_version") != "M2CS6FrozenEvaluationKeyManifestV1"
        or s6_keys.get("status") != "FROZEN_BEFORE_COLLECTION_TRAINING_OR_EVALUATION"
        or s6_keys.get("excluded_from_all_training") is not True
        or s6_keys.get("selection_uses_rollout_outcomes") is not False
        or s6_keys.get("teacher_used") is not False
        or s6_keys.get("privileged_truth_policy_input") is not False
    ):
        raise ValueError("S6 key manifest is not a frozen public-only exclusion manifest")
    training_records = training_keys.get("training_keys")
    smoke_records = training_keys.get("physical_prerequisite_smoke_keys")
    evaluation_records = s6_keys.get("evaluation_keys")
    if not all(
        isinstance(records, list)
        for records in (training_records, smoke_records, evaluation_records)
    ):
        raise ValueError("frozen key manifests do not contain all key lists")
    if training_keys.get("s6_evaluation_key_digest") != canonical_sha256(evaluation_records):
        raise ValueError("training manifest S6 cross-binding digest mismatch")
    if s6_keys.get("training_and_smoke_key_digest") != canonical_sha256(
        [*training_records, *smoke_records]
    ):
        raise ValueError("S6 manifest TRAIN/SMOKE cross-binding digest mismatch")
    collection_raw, s6_raw = build_collection_manifests(
        training_keys,
        s6_keys,
        runtime_registry_sha256=sha256_file(runtime_registry_path),
    )
    collection_scene_seeds = {int(item["scene_seed"]) for item in collection_raw["keys"]}
    collection_matched_keys = {str(item["matched_key"]) for item in collection_raw["keys"]}
    s6_scene_seeds = {int(item["scene_seed"]) for item in s6_raw["keys"]}
    s6_matched_keys = {str(item["matched_key"]) for item in s6_raw["keys"]}
    if collection_scene_seeds & s6_scene_seeds or collection_matched_keys & s6_matched_keys:
        raise ValueError("projected TRAIN/SMOKE collection overlaps frozen S6")
    if collection_scene_seeds & {9038, 9057, 9077}:
        raise ValueError("projected TRAIN/SMOKE collection overlaps frozen V4")
    return (
        training_keys,
        s6_keys,
        FrozenPathBlockedCollectionManifestV2.model_validate(collection_raw),
        FrozenS6ExclusionManifestV2.model_validate(s6_raw),
    )


def frozen_source_record(
    training_keys: Mapping[str, Any],
    *,
    role: str,
    matched_key: str,
) -> dict[str, Any]:
    field = {
        "TRAIN": "training_keys",
        "SMOKE": "physical_prerequisite_smoke_keys",
    }.get(role)
    if field is None:
        raise ValueError("collection role must be TRAIN or SMOKE")
    records = training_keys.get(field)
    if not isinstance(records, list):
        raise ValueError(f"frozen training key field is not a list: {field}")
    matches = [
        dict(record)
        for record in records
        if isinstance(record, Mapping) and record.get("matched_key") == matched_key
    ]
    if len(matches) != 1:
        raise ValueError("matched key is not exactly once in the frozen role manifest")
    record = matches[0]
    if (
        record.get("role") != role
        or record.get("failure_type") != "PATH_BLOCKED"
        or record.get("outcome_observed_during_selection") is not False
    ):
        raise ValueError("frozen source key role/failure/outcome contract changed")
    return record


def _write_json_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _dataset_relative_path(uri: str, *, label: str) -> Path:
    if not uri.startswith("dataset://"):
        raise ValueError(f"{label} must use a dataset:// URI")
    relative_text = uri.removeprefix("dataset://")
    relative = Path(relative_text)
    if (
        not relative_text
        or relative_text.startswith("/")
        or "\\" in relative_text
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError(f"{label} URI escapes the collection bundle")
    return relative


def _atomic_publish_directory(staging: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite packaged collection: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(destination)


def package_collection(
    *,
    raw_probe_path: Path,
    evidence_root: Path,
    output_root: Path,
    role: str,
    matched_key: str,
    training_keys_path: Path,
    s6_keys_path: Path,
    runtime_registry_path: Path,
    derived_probe_path: Path,
    upstream_v4_probe_path: Path,
    revision: str = "V2",
    collection_prereg_path: Path | None = None,
    collection_claim_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and atomically publish one frozen TRAIN/SMOKE collection."""

    if revision not in {"V2", "V3"}:
        raise ValueError("collection revision must be V2 or V3")
    # Authorization is a capability boundary, not another property of the
    # evidence payload. Reject an unclaimed V3 request before probing input
    # paths or the destination.
    if revision == "V3" and (collection_prereg_path is None or collection_claim_path is None):
        raise ValueError(
            "V3 packaging requires the committed preregistration and consumed key claim"
        )
    if revision == "V3":
        # Packaging is a second production entry point.  Do not let direct
        # library calls bypass the immutable-host-runtime prerequisite that
        # the worker CLI enforces before importing project modules.
        require_v3_host_runtime_launcher()
    destination = output_root / role.lower() / matched_key
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite packaged collection: {destination}")
    for path, label in (
        (raw_probe_path, "raw probe"),
        (training_keys_path, "training key manifest"),
        (s6_keys_path, "S6 key manifest"),
        (runtime_registry_path, "runtime registry"),
        (derived_probe_path, "derived probe source"),
        (upstream_v4_probe_path, "frozen upstream V4 probe"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    expected_derived_bytes = (
        derive_probe_bytes_v3(upstream_v4_probe_path.read_bytes())
        if revision == "V3"
        else derive_probe_bytes(upstream_v4_probe_path.read_bytes())
    )
    if derived_probe_path.read_bytes() != expected_derived_bytes:
        raise ValueError("derived probe source does not exactly derive from frozen V4")
    expected_probe_source_sha256 = hashlib.sha256(expected_derived_bytes).hexdigest()
    raw_probe_resolved = raw_probe_path.resolve(strict=True)
    evidence_root_resolved = evidence_root.resolve(strict=True)
    if not raw_probe_resolved.is_relative_to(evidence_root_resolved):
        raise ValueError("raw probe must remain under the evidence root")
    try:
        output_resolved = output_root.resolve()
    except OSError as error:
        raise ValueError("packaged output root cannot be resolved") from error
    if output_resolved.is_relative_to(
        evidence_root_resolved
    ) or evidence_root_resolved.is_relative_to(output_resolved):
        raise ValueError("packaged output root must be separate from raw evidence root")

    if revision == "V3":
        if role != "TRAIN":
            raise ValueError("ADR-0021 V3 packaging accepts TRAIN only")
        training_manifest_v3 = load_v3_training_manifest(training_keys_path)
        source_matches = [
            item for item in training_manifest_v3.training_keys if item.matched_key == matched_key
        ]
        if len(source_matches) != 1:
            raise ValueError("V3 package key is not exactly once in frozen TRAIN manifest")
        source_record = source_matches[0].model_dump(mode="json")
        # Reuse the strict frozen S6 projection only; old collection keys are
        # never accepted as V3 training keys.
        _old_training, _s6_keys, _old_collection, s6_manifest = project_frozen_manifests(
            Path(__file__).resolve().parents[2] / "configs/m2c_s4_training_keys.json",
            s6_keys_path,
            runtime_registry_path,
        )
    else:
        (
            training_keys,
            _s6_keys,
            collection_manifest,
            s6_manifest,
        ) = project_frozen_manifests(
            training_keys_path,
            s6_keys_path,
            runtime_registry_path,
        )
        source_record = frozen_source_record(
            training_keys,
            role=role,
            matched_key=matched_key,
        )
        collection_key = f"{matched_key}-collection"
        collection_matches = [
            key for key in collection_manifest.keys if key.collection_key == collection_key
        ]
        if len(collection_matches) != 1 or collection_matches[0].collection_role != role:
            raise ValueError("projected collection manifest does not contain the exact role key")
    if any(
        key.matched_key == matched_key or key.scene_seed == int(source_record["scene_seed"])
        for key in s6_manifest.keys
    ):
        raise ValueError("requested collection overlaps frozen S6")

    raw_probe_bytes = read_regular_file_once(raw_probe_resolved)
    packaged_authorization: dict[str, Any] | None = None
    try:
        raw_payload = json.loads(raw_probe_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("raw probe is not readable JSON") from error
    if not isinstance(raw_payload, dict):
        raise ValueError("raw probe must be a JSON object")
    if revision == "V3":
        raw_authorization = raw_payload.get("m2c_v3_collection_authorization")
        if not isinstance(raw_authorization, dict):
            raise ValueError("V3 raw probe lacks the collection authorization binding")
        console_path = raw_probe_resolved.parent / "console.log"
        console_bytes = read_regular_file_once(console_path)
        _resolved_prereg, _claim, packaged_binding = verify_packaging_authorization(
            project_root=Path(__file__).resolve().parents[2],
            prereg_path=collection_prereg_path,
            claim_path=collection_claim_path,
            matched_key=matched_key,
            raw_binding=raw_authorization,
            raw_probe_sha256=hashlib.sha256(raw_probe_bytes).hexdigest(),
            console_sha256=hashlib.sha256(console_bytes).hexdigest(),
            job_root=raw_probe_resolved.parent.parent,
            probe_output_root=raw_probe_resolved.parent,
        )
        packaged_authorization = packaged_binding.model_dump(mode="json")
    chain = raw_payload.get("m2c_path_blocked_physical_chain")
    if not isinstance(chain, Mapping):
        raise ValueError("raw probe lacks m2c_path_blocked_physical_chain")
    if chain.get("matched_key") != matched_key or chain.get("collection_role") != role:
        raise ValueError("raw probe matched key/role differs from request")
    if raw_payload.get("status") != "PASS" or raw_payload.get("not_policy_rollout") is not True:
        raise ValueError("raw probe must be a passing non-policy physical probe")
    if chain.get("model_rollout") is not False:
        raise ValueError("scripted physical supervision may not claim a model rollout")
    if raw_payload.get("actuation_probe_source_sha256") != expected_probe_source_sha256:
        raise ValueError("raw probe executing source SHA-256 differs from derived probe")

    if revision == "V3":
        if chain.get("schema_version") != "M2CPathBlockedProbeChainV3":
            raise ValueError("V3 package refuses V2 or unversioned probe evidence")
        if chain.get("collection_authorization_sha256") != canonical_sha256(raw_authorization):
            raise ValueError("V3 physical chain is not bound to the raw collection authorization")
        if chain.get("declared_target_attribute") != source_record["declared_target_attribute"]:
            raise ValueError("probe declared attribute differs from frozen TaskSpec selector")
        parsed_probe = M2CPathBlockedProbeChainV3.model_validate(chain)
        public_rgbd = raw_payload.get("m2b_public_rgbd")
        raw_captures = public_rgbd.get("captures") if isinstance(public_rgbd, Mapping) else None
        if not isinstance(raw_captures, list):
            raise ValueError("V3 package requires the top-level public RGB-D capture journal")
        for step in parsed_probe.steps:
            expected_payload, expected_hash = recompute_candidate_payload_v3(step.observation)
            if step.observation.candidate_payload.model_dump(mode="json") != expected_payload:
                raise ValueError("host recomputation rejects probe V3 candidate slots")
            if step.observation.candidate_payload_sha256 != expected_hash:
                raise ValueError("host recomputation rejects probe V3 candidate hash")
            for kind, uri, expected_asset_hash in (
                ("RGB", step.observation.rgb_uri, step.observation.rgb_sha256),
                ("depth", step.observation.depth_uri, step.observation.depth_sha256),
            ):
                actual_asset_hash = sha256_file(
                    (evidence_root_resolved / _dataset_relative_path(uri, label=kind)).resolve(
                        strict=True
                    )
                )
                if actual_asset_hash != expected_asset_hash:
                    raise ValueError(f"V3 {kind} asset SHA-256 mismatch")
            captures = [
                item
                for item in raw_captures
                if isinstance(item, Mapping)
                and item.get("timestamp_ns") == step.observation.captured_at_ns
                and item.get("rgb_uri") == step.observation.rgb_uri
                and item.get("depth_uri") == step.observation.depth_uri
                and item.get("rgb_sha256") == step.observation.rgb_sha256
                and item.get("depth_sha256") == step.observation.depth_sha256
            ]
            if len(captures) != 1:
                raise ValueError("V3 observation does not bind exactly one public capture")
            if canonical_sha256(captures[0]) != step.observation.capture_receipt_sha256:
                raise ValueError("V3 capture receipt SHA-256 mismatch")
        packaged = package_probe_chain_v3(
            chain,
            training_manifest=training_manifest_v3,
            s6_manifest=s6_manifest,
            runtime_registry_sha256=sha256_file(runtime_registry_path),
            source_evidence_uri="dataset://actuation-probe.json",
            source_evidence_sha256=hashlib.sha256(raw_probe_bytes).hexdigest(),
        )
        dataset = build_path_blocked_supervised_dataset_v3(
            packaged,
            training_manifest=training_manifest_v3,
            s6_manifest=s6_manifest,
        )
    else:
        packaged = package_probe_payload(
            raw_payload,
            probe_evidence_path=raw_probe_path,
            evidence_root=evidence_root,
            source_evidence_uri="dataset://actuation-probe.json",
            collection_manifest=collection_manifest,
            collection_manifest_path=None,
            s6_manifest=s6_manifest,
            s6_manifest_path=None,
            runtime_registry_path=runtime_registry_path,
            expected_sdf_sha256=str(source_record["sdf_sha256"]),
            expected_supervision_sha256=str(source_record["supervision_sha256"]),
        )
        dataset = build_path_blocked_supervised_dataset(
            [packaged],
            collection_manifest=collection_manifest,
            s6_manifest=s6_manifest,
        )
    if dataset.status != "PASS":
        raise ValueError(f"supervised dataset did not pass: {dataset.status}")
    validation = dataset.validation if revision == "V3" else dataset.episode_validations[0]
    if (
        not validation.physical_evidence_valid
        or validation.steps_validated != EXPECTED_STEP_COUNT
        or len(dataset.samples) != EXPECTED_STEP_COUNT
        or (role == "TRAIN" and not validation.model_training_eligible)
        or (role == "SMOKE" and validation.model_training_eligible)
    ):
        raise ValueError("packaged collection failed the strict eight-step role gate")

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{matched_key}.",
        dir=output_root,
    ) as temporary_text:
        temporary = Path(temporary_text)
        raw_copy = temporary / "actuation-probe.json"
        raw_copy.write_bytes(raw_probe_bytes)
        copied_assets: dict[str, str] = {}
        copied_receipts: dict[str, dict[str, str]] = {}
        for step in packaged.steps:
            for kind, uri in (
                ("rgb", step.observation.rgb_uri),
                ("depth", step.observation.depth_uri),
            ):
                relative = _dataset_relative_path(uri, label=f"step {step.decision_index} {kind}")
                source = (evidence_root_resolved / relative).resolve(strict=True)
                if not source.is_relative_to(evidence_root_resolved):
                    raise ValueError("public RGB-D asset escaped the raw evidence root")
                # Preserve the dataset:// URI namespace in the standalone bundle.
                # A downstream resolver may therefore use the bundle root directly.
                destination_asset = temporary / relative
                destination_asset.parent.mkdir(parents=True, exist_ok=True)
                if not destination_asset.exists():
                    destination_asset.write_bytes(source.read_bytes())
                copied_hash = sha256_file(destination_asset)
                expected_hash = getattr(step.observation, f"{kind}_sha256")
                if copied_hash != expected_hash:
                    raise ValueError(f"copied step {step.decision_index} {kind} SHA-256 mismatch")
                copied_assets[f"{step.decision_index}:{kind}"] = copied_hash
            receipt_payload = step.physical_receipts[0].model_dump(mode="json")
            receipt_relative = _dataset_relative_path(
                step.physical_receipts[0].receipt_uri,
                label=f"step {step.decision_index} physical receipt",
            )
            receipt_output = temporary / receipt_relative
            receipt_output.parent.mkdir(parents=True, exist_ok=True)
            if receipt_output.exists():
                raise ValueError("physical receipt URI is reused across chain steps")
            _write_json_new(receipt_output, receipt_payload)
            copied_receipts[str(step.decision_index)] = {
                "path": str(receipt_relative),
                "file_sha256": sha256_file(receipt_output),
                "canonical_receipt_sha256": step.physical_receipts[0].receipt_sha256,
            }
        packaged_path = temporary / f"packaged-physical-chain-{revision.lower()}.json"
        samples_path = temporary / f"supervised-steps-{revision.lower()}.json"
        collection_manifest_path = temporary / f"collection-manifest-{revision.lower()}.json"
        s6_manifest_path = temporary / "s6-exclusion-manifest-v2.json"
        _write_json_new(packaged_path, packaged.model_dump(mode="json"))
        _write_json_new(samples_path, dataset.model_dump(mode="json"))
        _write_json_new(
            collection_manifest_path,
            (
                training_manifest_v3.model_dump(mode="json")
                if revision == "V3"
                else collection_manifest.model_dump(mode="json")
            ),
        )
        _write_json_new(s6_manifest_path, s6_manifest.model_dump(mode="json"))
        receipt: dict[str, Any] = {
            "schema_version": f"M2CPathBlockedCollectionReceipt{revision}",
            "status": "PASS_SCRIPTED_PUBLIC_PHYSICAL_SUPERVISION",
            "matched_key": matched_key,
            "scene_seed": source_record["scene_seed"],
            "failure_seed": source_record["failure_seed"],
            "split": source_record["split"],
            "collection_role": role,
            "decision_source": DECISION_SOURCE,
            "model_owned": False,
            "model_rollout": False,
            "formal_q_b_evaluation": False,
            "pure_model_success_evidence": False,
            "physical_chain_steps": EXPECTED_STEP_COUNT,
            "physical_receipts": EXPECTED_STEP_COUNT,
            "fresh_public_rgbd_observations": EXPECTED_STEP_COUNT,
            "copied_public_assets": copied_assets,
            "physical_receipt_files": copied_receipts,
            "raw_probe_sha256": sha256_file(raw_copy),
            "packaged_physical_chain_sha256": sha256_file(packaged_path),
            "supervised_dataset_file_sha256": sha256_file(samples_path),
            "dataset_sha256": dataset.dataset_sha256,
            "collection_manifest_sha256": (
                training_manifest_v3.manifest_sha256
                if revision == "V3"
                else canonical_manifest_sha256(collection_manifest)
            ),
            "collection_manifest_file_sha256": (
                V3_MANIFEST_FILE_SHA256 if revision == "V3" else sha256_file(training_keys_path)
            ),
            "candidate_contract_revision": ("PublicTrackCandidateV3" if revision == "V3" else None),
            "checkpoint_architecture_revision": (
                "M2C_Q012_V3" if revision == "V3" else "M2C_Q012_V2"
            ),
            "s6_exclusion_manifest_sha256": canonical_manifest_sha256(s6_manifest),
            "frozen_training_key_manifest_file_sha256": sha256_file(training_keys_path),
            "frozen_s6_key_manifest_file_sha256": sha256_file(s6_keys_path),
            "runtime_registry_sha256": sha256_file(runtime_registry_path),
            "executing_probe_source_sha256": raw_payload.get("actuation_probe_source_sha256"),
            "derived_probe_file_sha256": sha256_file(derived_probe_path),
            "frozen_upstream_v4_probe_sha256": sha256_file(upstream_v4_probe_path),
            "sdf_sha256": source_record["sdf_sha256"],
            "supervision_sha256": source_record["supervision_sha256"],
            "teacher_used": False,
            "privileged_truth_policy_input": False,
            "checkpoint_path": None,
            "checkpoint_sha256": None,
            "training_executed": False,
            "evaluation_executed": False,
        }
        if revision == "V3":
            receipt["collection_authorization"] = packaged_authorization
        receipt_path = temporary / f"collection-receipt-{revision.lower()}.json"
        _write_json_new(receipt_path, receipt)
        _atomic_publish_directory(temporary, destination)
    return {
        **receipt,
        "output": str(destination),
        "collection_receipt_sha256": sha256_file(
            destination / f"collection-receipt-{revision.lower()}.json"
        ),
    }


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-probe", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--role", choices=("TRAIN", "SMOKE"), required=True)
    parser.add_argument("--revision", choices=("V2", "V3"), default="V3")
    parser.add_argument("--matched-key", required=True)
    parser.add_argument("--derived-probe", required=True, type=Path)
    parser.add_argument("--upstream-v4-probe", required=True, type=Path)
    parser.add_argument("--collection-prereg", type=Path)
    parser.add_argument("--collection-claim", type=Path)
    parser.add_argument(
        "--training-keys",
        type=Path,
        default=project / "configs/m2c_s4_v3_training_keys.json",
    )
    parser.add_argument(
        "--s6-keys",
        type=Path,
        default=project / "configs/m2c_s6_evaluation_keys.json",
    )
    parser.add_argument(
        "--runtime-registry",
        type=Path,
        default=project / "configs/qrm_runtime_mapping_v2.yaml",
    )
    args = parser.parse_args()
    result = package_collection(
        raw_probe_path=args.raw_probe,
        evidence_root=args.evidence_root,
        output_root=args.output_root,
        role=args.role,
        matched_key=args.matched_key,
        training_keys_path=args.training_keys,
        s6_keys_path=args.s6_keys,
        runtime_registry_path=args.runtime_registry,
        derived_probe_path=args.derived_probe,
        upstream_v4_probe_path=args.upstream_v4_probe,
        revision=args.revision,
        collection_prereg_path=args.collection_prereg,
        collection_claim_path=args.collection_claim,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
