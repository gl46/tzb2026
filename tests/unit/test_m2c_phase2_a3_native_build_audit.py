from __future__ import annotations

import hashlib
from pathlib import Path
import shutil

import pytest

from m2c.audit_phase2_a3_native_build import (
    A3BuildAuditError,
    EXPECTED_BLOCKERS,
    build_report,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = Path("/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-native-build-v5")


@pytest.mark.skipif(not EVIDENCE_ROOT.is_dir(), reason="external A.3 evidence is absent")
def test_real_native_build_and_geometry_evidence_replays_without_execution() -> None:
    report = build_report(PROJECT_ROOT, EVIDENCE_ROOT)

    assert report["status"] == "PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY"
    assert report["evidence_inventory"]["regular_file_count"] == 10
    assert report["native_build"]["builder_image_id"] == (
        "sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e"
    )
    assert report["native_build"]["native_shared_object_sha256"] == (
        "2231cee659b15875fc0bed011f339ac9962168981d228f3f08c6189929ce9c23"
    )
    assert report["controlled_panda_geometry_replay"]["collision_child_count"] == 14
    assert report["controlled_panda_geometry_replay"]["shape_counts"] == {
        "BOX": 11,
        "CYLINDER": 1,
        "CONVEX_HULL": 2,
    }
    assert report["remaining_blockers"] == list(EXPECTED_BLOCKERS)
    assert not report["evidence_claims"]["isaac_started"]
    assert not report["evidence_claims"]["physical_execution_performed"]
    assert not report["evidence_claims"]["formal_execution_eligible"]
    assert not report["evidence_claims"]["teacher_used"]


@pytest.mark.skipif(not EVIDENCE_ROOT.is_dir(), reason="external A.3 evidence is absent")
def test_native_or_mesh_tamper_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, copied)
    for path in copied.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
        else:
            path.chmod(0o444)
    native = copied / "native/libm2c_a3_bullet_float64.so"
    native.chmod(0o644)
    native.write_bytes(native.read_bytes() + b"tamper")
    native.chmod(0o444)
    for path in sorted(copied.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o555)
    with pytest.raises(A3BuildAuditError, match="cross-binding"):
        build_report(PROJECT_ROOT, copied)


def test_audit_source_and_builder_are_bound_by_unit_test() -> None:
    audit = PROJECT_ROOT / "scripts/m2c/audit_phase2_a3_native_build.py"
    builder = PROJECT_ROOT / "scripts/m2c/build_a3_bullet_native_closure.py"
    dockerfile = PROJECT_ROOT / "docker/m2c-a3-bullet-builder/Dockerfile"
    assert all(path.is_file() for path in (audit, builder, dockerfile))
    assert all(
        len(hashlib.sha256(path.read_bytes()).hexdigest()) == 64 for path in (audit, builder)
    )
    assert "apt-get" not in dockerfile.read_text(encoding="utf-8")
