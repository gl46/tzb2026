"""Fail-closed governance gate for the human-approved M2C Q-B ADR."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any


ADR_PATH = "docs/decisions/ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md"
ADR_SHA256 = "5a0aecc1c31a1aca7a48150ec0792df13aa041c5e0802382b9c1432a012598c3"
PREREGISTRATION_PATH = "docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md"
PREREGISTRATION_SHA256 = (
    "1b3453a975352d78f78759446ae774f5317a93d60fbb097708a07f0934b99e70"
)
B0_FREEZE_PATH = "configs/m2c_b0_freeze.json"
B0_FREEZE_SHA256 = (
    "4bec9104be849dfd8d71b32b537eb2b5d70ea4d8560b4bdd65b1d1019d3e8d04"
)
V4_MANIFEST_PATH = "configs/m2c_headroom_domain_v4.json"
V4_MANIFEST_SHA256 = (
    "4e78c044b68b11c1d871ecb90e65c7e2dfc616c8971abb89cb9969d2d48f738b"
)
V4_DOMAIN_SHA256 = (
    "a08d0deec846168511ecdb8dac1ee54284493a973eb1d9a0e5fa843718196359"
)
DATASET_PATH = "artifacts/m2c/dataset-v3.jsonl"
DATASET_SHA256 = "48924a208c0ab417384f09bbef45073a10f58c9aac16cc64089409288401f35b"
PATH_BLOCKED_PATH = "artifacts/m2c/path-blocked-raw-v1.jsonl"
PATH_BLOCKED_SHA256 = (
    "704cc5790ca6c5f0694664195130585b7420660b6c99b29afc342b83ef5908d5"
)
GENERATOR_PATH = "scripts/generate_industrial_scenes.py"
GENERATOR_SHA256 = (
    "e9f9e20106a05dbec24453ce39422d57aa212709567fb7eba7f8d9beb03cd6c5"
)
B0_PROBE_PATH = "scripts/isaac_m1b_actuation_probe.py"
B0_PROBE_SHA256 = (
    "1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"
)
PURE_METRIC_COMMIT = "80a1910"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative_path(raw: str) -> str | None:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        return None
    return path.as_posix()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )


def _head_and_worktree_file(
    root: Path,
    relative: str,
    *,
    blockers: list[str],
    label: str,
) -> bytes | None:
    safe = _safe_relative_path(relative)
    if safe is None:
        blockers.append(f"{label} path is unsafe: {relative}")
        return None
    committed = _git(root, "show", f"HEAD:{safe}")
    if committed.returncode != 0:
        blockers.append(f"{label} is not committed at Git HEAD: {safe}")
        return None
    worktree_path = root / safe
    if not worktree_path.is_file():
        blockers.append(f"{label} is absent from the worktree: {safe}")
        return None
    worktree = worktree_path.read_bytes()
    if worktree != committed.stdout:
        blockers.append(f"{label} differs between worktree and Git HEAD: {safe}")
        return None
    return committed.stdout


def _worktree_file(
    root: Path,
    relative: str,
    *,
    blockers: list[str],
    label: str,
) -> bytes | None:
    safe = _safe_relative_path(relative)
    if safe is None:
        blockers.append(f"{label} path is unsafe: {relative}")
        return None
    path = root / safe
    if not path.is_file():
        blockers.append(f"{label} is absent: {safe}")
        return None
    return path.read_bytes()


def _require_sha(
    data: bytes | None,
    expected: str,
    *,
    blockers: list[str],
    label: str,
) -> bool:
    if data is None:
        return False
    actual = _sha256(data)
    if actual != expected:
        blockers.append(f"{label} SHA-256 mismatch: {actual} != {expected}")
        return False
    return True


def _verify_frozen_b0_files(
    root: Path,
    freeze_bytes: bytes | None,
    blockers: list[str],
) -> int:
    if freeze_bytes is None:
        return 0
    try:
        payload = json.loads(freeze_bytes)
    except json.JSONDecodeError as error:
        blockers.append(f"B0 freeze manifest is invalid JSON: {error}")
        return 0
    if payload.get("schema_version") != "M2CB0FreezeManifestV1":
        blockers.append("B0 freeze manifest schema_version changed")
    if payload.get("baseline_commit") != (
        "141e45dabddcaf59bb49ab958d9d5273d1f54d88"
    ):
        blockers.append("B0 freeze manifest baseline commit changed")
    entries = payload.get("b0_files")
    if not isinstance(entries, list) or not entries:
        blockers.append("B0 freeze manifest has no frozen B0 files")
        return 0
    verified = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            blockers.append(f"B0 freeze entry {index} is not an object")
            continue
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            blockers.append(f"B0 freeze entry {index} lacks path/SHA-256")
            continue
        data = _head_and_worktree_file(
            root,
            relative,
            blockers=blockers,
            label=f"frozen B0 file {relative}",
        )
        if _require_sha(
            data,
            expected,
            blockers=blockers,
            label=f"frozen B0 file {relative}",
        ):
            verified += 1
    return verified


def _governance_commit(
    root: Path,
    adr_bytes: bytes | None,
    blockers: list[str],
) -> str | None:
    introduced = _git(
        root,
        "log",
        "--diff-filter=A",
        "-1",
        "--format=%H",
        "--",
        ADR_PATH,
    )
    if introduced.returncode != 0 or not introduced.stdout.strip():
        blockers.append("cannot resolve the commit that introduced the human ADR")
        return None
    commit = introduced.stdout.decode().strip()
    ancestor = _git(root, "merge-base", "--is-ancestor", commit, "HEAD")
    if ancestor.returncode != 0:
        blockers.append("the human ADR commit is not an ancestor of Git HEAD")
    committed_adr = _git(root, "show", f"{commit}:{ADR_PATH}")
    if (
        committed_adr.returncode != 0
        or adr_bytes is None
        or committed_adr.stdout != adr_bytes
    ):
        blockers.append("the ADR introduction commit does not contain the frozen ADR bytes")
    changed = _git(
        root,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit,
    )
    changed_paths = set(changed.stdout.decode().splitlines())
    if changed.returncode != 0 or changed_paths != {ADR_PATH}:
        blockers.append(
            "the human ADR was not introduced by an ADR-only governance commit"
        )
    return commit


def evaluate_qb_adr_gate(root: Path) -> dict[str, Any]:
    """Verify that the exact human ADR predates any Q-B implementation/run."""

    root = root.resolve()
    blockers: list[str] = []
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        blockers.append(f"Q-B governance root is not a Git repository: {root}")
    elif Path(top.stdout.decode().strip()).resolve() != root:
        blockers.append(f"Q-B governance root is not the Git toplevel: {root}")
    head = _git(root, "rev-parse", "HEAD")
    head_commit = head.stdout.decode().strip() if head.returncode == 0 else None

    adr = _head_and_worktree_file(
        root,
        ADR_PATH,
        blockers=blockers,
        label="human-approved Q-B ADR",
    )
    adr_match = _require_sha(
        adr,
        ADR_SHA256,
        blockers=blockers,
        label="human-approved Q-B ADR",
    )
    governance_commit = _governance_commit(root, adr, blockers)
    if adr is not None:
        text = adr.decode("utf-8", errors="replace")
        required = (
            "# ADR-0020: CoarseIntentV2 model-owned recovery chain",
            "Status: Accepted for the bounded M2C Q-B experiment (human decision)",
            "Decision — option (a): versioned intent, no new skill labels",
            "M2C_Q012_V2",
            "Required tests before any Q-B evaluation execution",
            V4_DOMAIN_SHA256,
            V4_MANIFEST_SHA256,
            DATASET_SHA256,
            PATH_BLOCKED_SHA256,
            GENERATOR_SHA256,
            B0_PROBE_SHA256,
        )
        missing = [token for token in required if token not in text]
        if missing:
            blockers.append("human ADR lacks frozen content: " + ", ".join(missing))
        if re.search(r"[0-9a-fA-F]{8,63}…", text):
            blockers.append("human ADR still contains an abbreviated SHA-256")

    prereg = _head_and_worktree_file(
        root,
        PREREGISTRATION_PATH,
        blockers=blockers,
        label="Q-B pre-registration",
    )
    prereg_match = _require_sha(
        prereg,
        PREREGISTRATION_SHA256,
        blockers=blockers,
        label="Q-B pre-registration",
    )
    freeze = _head_and_worktree_file(
        root,
        B0_FREEZE_PATH,
        blockers=blockers,
        label="B0 freeze manifest",
    )
    freeze_match = _require_sha(
        freeze,
        B0_FREEZE_SHA256,
        blockers=blockers,
        label="B0 freeze manifest",
    )
    b0_files_verified = _verify_frozen_b0_files(root, freeze, blockers)

    v4_manifest = _head_and_worktree_file(
        root,
        V4_MANIFEST_PATH,
        blockers=blockers,
        label="V4 domain manifest",
    )
    v4_manifest_match = _require_sha(
        v4_manifest,
        V4_MANIFEST_SHA256,
        blockers=blockers,
        label="V4 domain manifest",
    )
    if v4_manifest is not None:
        try:
            domain_sha = json.loads(v4_manifest).get("domain_sha256")
        except json.JSONDecodeError as error:
            blockers.append(f"V4 domain manifest is invalid JSON: {error}")
        else:
            if domain_sha != V4_DOMAIN_SHA256:
                blockers.append("V4 domain SHA-256 no longer matches the human ADR")

    artifact_checks: dict[str, bool] = {}
    for relative, expected, label in (
        (DATASET_PATH, DATASET_SHA256, "S3 Dataset V3"),
        (PATH_BLOCKED_PATH, PATH_BLOCKED_SHA256, "PATH_BLOCKED raw evidence"),
    ):
        data = _worktree_file(root, relative, blockers=blockers, label=label)
        artifact_checks[relative] = _require_sha(
            data,
            expected,
            blockers=blockers,
            label=label,
        )

    generator = _head_and_worktree_file(
        root,
        GENERATOR_PATH,
        blockers=blockers,
        label="frozen scene generator",
    )
    generator_match = _require_sha(
        generator,
        GENERATOR_SHA256,
        blockers=blockers,
        label="frozen scene generator",
    )
    probe = _head_and_worktree_file(
        root,
        B0_PROBE_PATH,
        blockers=blockers,
        label="frozen B0 probe",
    )
    probe_match = _require_sha(
        probe,
        B0_PROBE_SHA256,
        blockers=blockers,
        label="frozen B0 probe",
    )
    metric_commit = _git(root, "rev-parse", f"{PURE_METRIC_COMMIT}^{{commit}}")
    metric_commit_full = (
        metric_commit.stdout.decode().strip() if metric_commit.returncode == 0 else None
    )
    if metric_commit_full is None:
        blockers.append(f"strict metric commit cannot be resolved: {PURE_METRIC_COMMIT}")

    unique_blockers = list(dict.fromkeys(blockers))
    authorized = not unique_blockers
    return {
        "schema_version": "M2CQBExpressivityADRGateReportV1",
        "status": (
            "PASS_Q_B_HUMAN_ADR_GATE"
            if authorized
            else "BLOCKED_HUMAN_ADR_REQUIRED"
        ),
        "q_b_authorized": authorized,
        "checked_head_commit": head_commit,
        "governance_commit": governance_commit,
        "adr": {
            "path": ADR_PATH,
            "sha256": ADR_SHA256,
            "matches": adr_match,
            "introduced_in_adr_only_commit": governance_commit is not None,
        },
        "frozen_bindings": {
            "preregistration_path": PREREGISTRATION_PATH,
            "preregistration_sha256": PREREGISTRATION_SHA256,
            "preregistration_match": prereg_match,
            "b0_freeze_path": B0_FREEZE_PATH,
            "b0_freeze_sha256": B0_FREEZE_SHA256,
            "b0_freeze_match": freeze_match,
            "b0_files_verified": b0_files_verified,
            "v4_manifest_match": v4_manifest_match,
            "generator_match": generator_match,
            "b0_probe_match": probe_match,
            "strict_metric_commit": metric_commit_full,
            "artifact_matches": artifact_checks,
        },
        "decision_option": "VERSIONED_INTENT_NO_NEW_SKILL_LABELS",
        "intent_schema_version": "CoarseIntentV2",
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "world_model_mainline_replaced": False,
        "q_b_training_executed": False,
        "q_b_evaluation_executed": False,
        "blockers": unique_blockers,
        "next_command": (
            "implement and pass all ADR section 7 tests before Q-B training/evaluation"
            if authorized
            else f"restore and commit the exact approved ADR at {ADR_PATH}"
        ),
    }
