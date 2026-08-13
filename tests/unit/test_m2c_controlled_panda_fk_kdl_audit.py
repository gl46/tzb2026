from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from m2c.audit_controlled_panda_fk_v1 import (
    FKComparisonAuditFailure,
    build_audit,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = Path("/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-controlled-panda-fk-kdl-v1")


@pytest.mark.skipif(not EVIDENCE_ROOT.is_dir(), reason="external FK/KDL evidence is absent")
def test_query_only_fk_matches_independent_node2_kdl_at_binary64_tolerance() -> None:
    report = build_audit(project_root=PROJECT_ROOT, evidence_root=EVIDENCE_ROOT)

    assert report["status"] == "PASS_QUERY_ONLY_FK_MATCHES_INDEPENDENT_NODE2_KDL"
    assert report["comparison"] == {
        "state_count": 12,
        "collision_link_count": 12,
        "row_count": 144,
        "maximum_translation_error_m": 2.5438405243138006e-16,
        "maximum_orientation_error_rad": 5.147892387644517e-16,
        "translation_tolerance_m": 1e-12,
        "orientation_tolerance_rad": 1e-12,
        "worst_translation": {
            "state_index": 6,
            "link_path": "/World/Robot/panda_rightfinger",
        },
        "worst_orientation": {
            "state_index": 9,
            "link_path": "/World/Robot/panda_hand",
        },
    }
    assert report["evidence_inventory"]["regular_file_count"] == 6
    assert not report["evidence_claims"]["formal_execution_eligible"]
    assert not report["evidence_claims"]["isaac_started"]
    assert not report["evidence_claims"]["physical_execution_performed"]
    assert not report["evidence_claims"]["teacher_used"]


@pytest.mark.skipif(not EVIDENCE_ROOT.is_dir(), reason="external FK/KDL evidence is absent")
@pytest.mark.parametrize(
    ("relative_path", "expected_message"),
    (
        ("kdl-transforms.csv", "KDL comparison CSV"),
        ("controlled_panda_fk_kdl_verifier_v1.cpp", "verifier source/binary"),
        ("panda_controlled.urdf", "controlled URDF bytes"),
    ),
)
def test_kdl_transform_source_and_urdf_tamper_fail_closed(
    tmp_path: Path,
    relative_path: str,
    expected_message: str,
) -> None:
    copied = tmp_path / "evidence"
    shutil.copytree(EVIDENCE_ROOT, copied)
    target = copied / relative_path
    target.chmod(0o644)
    target.write_bytes(target.read_bytes() + b"tamper")

    with pytest.raises(FKComparisonAuditFailure, match=expected_message):
        build_audit(project_root=PROJECT_ROOT, evidence_root=copied)


def test_fk_kdl_audit_sources_are_present_and_do_not_import_isaac() -> None:
    paths = (
        PROJECT_ROOT / "src/xh_agent/policy/qrm_lite/controlled_panda_fk_v1.py",
        PROJECT_ROOT / "scripts/m2c/build_controlled_panda_fk_kdl_evidence.py",
        PROJECT_ROOT / "scripts/m2c/controlled_panda_fk_kdl_verifier_v1.cpp",
        PROJECT_ROOT / "scripts/m2c/audit_controlled_panda_fk_v1.py",
    )
    assert all(path.is_file() for path in paths)
    joined = b"\n".join(path.read_bytes() for path in paths)
    assert b"isaacsim" not in joined
    assert b"SimulationApp" not in joined
    assert b"set_dof_position_targets" not in joined
