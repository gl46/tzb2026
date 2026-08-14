#!/usr/bin/env python3
"""Audit the two exact ADR-0025 A.3 ACM entries against upstream SRDF bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Mapping
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path("configs/m2c_a3_acm_adr0025_v1.json")
EXPECTED_SCHEMA = "M2CA3ADR0025ACMConfigurationV1"
EXPECTED_STATUS = "FROZEN_EXACT_TWO_UPSTREAM_PROVEN_PAIRS"


class A3ACMAuditError(ValueError):
    """The controlled or upstream collision matrix differs from ADR-0025."""


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def read_regular_file_once(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise A3ACMAuditError(f"ACM input is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise A3ACMAuditError(f"ACM input changed while being read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _git_bytes(*, project_root: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=project_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise A3ACMAuditError(f"ACM Git binding is unavailable: {commit}:{path}")
    return result.stdout


def _head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _pairs(raw: bytes, *, label: str) -> dict[tuple[str, str], str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise A3ACMAuditError(f"{label} SRDF is malformed") from error
    result: dict[tuple[str, str], str] = {}
    for item in root.findall("disable_collisions"):
        left = item.get("link1")
        right = item.get("link2")
        reason = item.get("reason")
        if not left or not right or not reason or left == right:
            raise A3ACMAuditError(f"{label} SRDF contains a malformed ACM entry")
        key = tuple(sorted((left, right)))
        if key in result:
            raise A3ACMAuditError(f"{label} SRDF repeats an ACM pair")
        result[key] = reason
    return result


def _load_configuration(project_root: Path) -> tuple[dict[str, Any], bytes]:
    raw = read_regular_file_once(project_root / CONFIG_PATH)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise A3ACMAuditError("ACM configuration is not an object")
    embedded = payload.get("configuration_sha256")
    core = dict(payload)
    core.pop("configuration_sha256", None)
    if (
        payload.get("schema_version") != EXPECTED_SCHEMA
        or payload.get("status") != EXPECTED_STATUS
        or embedded != canonical_sha256(core)
        or payload.get("pair_count") != 2
        or payload.get("wildcard_or_category_disable_allowed") is not False
    ):
        raise A3ACMAuditError("ACM configuration identity or boundary differs")
    for field in (
        "collision_margin_changed",
        "outward_padding_changed",
        "hull_geometry_changed",
        "collision_threshold_changed",
        "teacher_used",
        "privileged_truth_policy_input",
    ):
        if payload.get(field) is not False:
            raise A3ACMAuditError(f"ACM forbidden boundary changed: {field}")
    return payload, raw


def _read_upstream(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    return read_regular_file_once(Path(path))


def build_report(
    *,
    upstream_srdf: bytes,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    config, config_raw = _load_configuration(project_root)
    controlled_binding = config["controlled_srdf"]
    upstream_binding = config["official_upstream_srdf"]
    controlled_path = project_root / controlled_binding["path"]
    current_raw = read_regular_file_once(controlled_path)
    baseline_raw = _git_bytes(
        project_root=project_root,
        commit=controlled_binding["baseline_commit"],
        path=controlled_binding["path"],
    )
    if hashlib.sha256(baseline_raw).hexdigest() != controlled_binding["baseline_sha256"]:
        raise A3ACMAuditError("baseline controlled SRDF binding differs")
    if hashlib.sha256(current_raw).hexdigest() != controlled_binding["revised_sha256"]:
        raise A3ACMAuditError("revised controlled SRDF binding differs")
    if hashlib.sha256(upstream_srdf).hexdigest() != upstream_binding["sha256"]:
        raise A3ACMAuditError("official upstream SRDF binding differs")

    baseline_pairs = _pairs(baseline_raw, label="baseline controlled")
    current_pairs = _pairs(current_raw, label="revised controlled")
    upstream_pairs = _pairs(upstream_srdf, label="official upstream")
    additions = set(current_pairs) - set(baseline_pairs)
    removals = set(baseline_pairs) - set(current_pairs)
    expected_pairs: dict[tuple[str, str], Mapping[str, Any]] = {}
    pair_evidence: list[dict[str, Any]] = []
    for item in config["authorized_pairs"]:
        pair = tuple(sorted((item["link1"], item["link2"])))
        if pair in expected_pairs:
            raise A3ACMAuditError("ACM configuration repeats an authorized pair")
        expected_pairs[pair] = item
        upstream_pair = tuple(sorted((item["upstream_link1"], item["upstream_link2"])))
        if (
            pair != upstream_pair
            or item["adr0025_criterion"] != "A_OFFICIAL_UPSTREAM_SRDF"
            or item["original_mesh_check_used"] is not False
            or item["kinematic_permanence_claim_required"] is not False
            or current_pairs.get(pair) != item["controlled_reason"]
            or upstream_pairs.get(pair) != item["upstream_reason"]
        ):
            raise A3ACMAuditError("ACM pair lacks exact ADR-0025 criterion-(a) evidence")
        pair_evidence.append(
            {
                "link_pair": list(pair),
                "controlled_reason": current_pairs[pair],
                "criterion": item["adr0025_criterion"],
                "official_upstream_reason": upstream_pairs[pair],
                "original_mesh_check_used": False,
                "kinematic_permanence_claim_required": False,
            }
        )
    if additions != set(expected_pairs) or removals:
        raise A3ACMAuditError("controlled SRDF change is not exactly the two authorized pairs")

    source_paths = [
        CONFIG_PATH.as_posix(),
        controlled_binding["path"],
        "scripts/m1a_moveit_execution_client.py",
        "scripts/run_moveit_execution_gate.sh",
        "src/xh_agent/policy/qrm_lite/a3_bullet_production_adapter_v1.py",
    ]
    source_bindings = {
        path: hashlib.sha256(read_regular_file_once(project_root / path)).hexdigest()
        for path in source_paths
    }
    return {
        "schema_version": "M2CA3ADR0025ACMSourceAuditV1",
        "status": "PASS_EXACT_TWO_ACM_PAIRS_HAVE_OFFICIAL_UPSTREAM_SRDF_EVIDENCE",
        "implementation_commit": _head(project_root),
        "configuration": {
            "path": CONFIG_PATH.as_posix(),
            "file_sha256": hashlib.sha256(config_raw).hexdigest(),
            "configuration_sha256": config["configuration_sha256"],
        },
        "accepted_adr": config["accepted_adr"],
        "controlled_srdf": {
            **controlled_binding,
            "baseline_pair_count": len(baseline_pairs),
            "revised_pair_count": len(current_pairs),
            "added_pair_count": len(additions),
            "removed_pair_count": len(removals),
        },
        "official_upstream_srdf": upstream_binding,
        "pair_evidence": sorted(pair_evidence, key=lambda item: item["link_pair"]),
        "source_bindings": source_bindings,
        "evidence_claims": {
            "query_only_source_audit": True,
            "physical_execution_performed": False,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "collision_margin_changed": False,
            "outward_padding_changed": False,
            "hull_geometry_changed": False,
            "collision_threshold_changed": False,
            "wildcard_or_category_disable_used": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        },
    }


def report_bytes(report: Mapping[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _publish_create_only(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o444,
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise A3ACMAuditError("short write publishing ACM audit")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-srdf", required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-json", type=Path)
    args = parser.parse_args()
    report = build_report(
        upstream_srdf=_read_upstream(args.upstream_srdf),
        project_root=args.project_root.resolve(),
    )
    encoded = report_bytes(report)
    if args.expected_json is not None and read_regular_file_once(args.expected_json) != encoded:
        raise SystemExit("A.3 ACM audit differs from expected JSON")
    if args.output is not None:
        _publish_create_only(args.output, encoded)
    else:
        print(encoded.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
