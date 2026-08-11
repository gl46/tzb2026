from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from m2c.build_final_headroom_domain import (
    ANCHORS_XY_M,
    BLOCKER_DISTANCE_M,
    PROJECT,
    RETAINED_BLOCKER_DISTANCE_M,
    SCRIPTED_BLOCKER_ENTITY,
    TARGET_ENTITY,
    generate_domain,
)


TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
UPSTREAM = PROJECT / "scripts/isaac_m1b_actuation_probe.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_is_final_v3_informed_and_unobserved(tmp_path: Path) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        upstream_probe=UPSTREAM,
        output_root=tmp_path / "domain-v4",
        seed_start=9000,
        seed_stop=9200,
    )
    assert [item["scene_seed"] for item in manifest["keys"]] == [9038, 9057, 9077]
    assert manifest["candidate_number"] == 4
    assert manifest["final_domain_candidate"] is True
    assert manifest["further_domain_iterations_forbidden"] is True
    assert manifest["v4_outcomes_observed"] is False
    assert manifest["q_a_decision"] is None
    timing = manifest["preregistration_timing"]
    assert timing["written_after_v3_results"] is True
    assert timing["written_before_any_v4_isaac_execution"] is True
    assert manifest["outcome_informed_design"]["uses_v3_results"] is True
    assert manifest["outcome_informed_design"]["v4_results_used_for_design"] is False
    assert manifest["stop_loss"]["authorized_candidate_number"] == 4
    assert manifest["stop_loss"]["v5_and_later_forbidden"] is True
    assert manifest["stop_loss"]["v4_nonpass_disposition"] == "TRIGGER_D1"
    assert manifest["baseline_protocol"]["probe_sha256"].startswith("1e32fa89")
    assert manifest["baseline_protocol"]["retry_count"] == 2
    assert manifest["derived_existence_probe"]["changed_since_v3"] is False
    predicate = manifest["existence_proof_protocol"]
    assert predicate["top_level_probe_pass_alone_is_insufficient"] is True
    assert any(
        "regrasp_target_executed == true" in item
        for item in predicate["strict_success_predicate_all_required"]
    )
    assert manifest["teacher_used"] is False
    for index, record in enumerate(manifest["keys"]):
        assert record["anchor_xy_m"] == list(ANCHORS_XY_M[index])
        assert record["blocker_distance_m"] == pytest.approx(BLOCKER_DISTANCE_M)
        assert record["retained_blocker_distance_m"] == pytest.approx(RETAINED_BLOCKER_DISTANCE_M)
        assert record["target_clearance_before_ok"] is False
        assert record["scripted_blocker_clearance_ok"] is True
        assert record["target_clearance_after_relocation_ok"] is True
        assert record["target_clearance_before_m"] == pytest.approx(0.0027102155)
        assert record["target_clearance_after_relocation_m"] == pytest.approx(0.0461684803)
        assert record["minimum_surface_gap_m"] >= 0.005


def test_v4_preserves_standard_cylinder_geometry_and_source_hashes(
    tmp_path: Path,
) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        upstream_probe=UPSTREAM,
        output_root=tmp_path / "domain-v4",
        key_count=1,
        seed_start=9038,
        seed_stop=9039,
    )
    record = manifest["keys"][0]
    sdf = Path(record["sdf"])
    supervision = Path(record["supervision"])
    assert sha256(sdf) == record["sdf_sha256"]
    assert sha256(supervision) == record["supervision_sha256"]
    root = ET.parse(sdf).getroot()
    cylinders = [
        model
        for model in root.findall(".//world/model")
        if (model.get("name") or "").startswith("cylinder_")
    ]
    assert len(cylinders) == 6
    assert {
        float(node.text or "nan")
        for model in cylinders
        for node in model.findall(".//geometry/cylinder/length")
    } == {0.08}
    assert {
        float(node.text or "nan")
        for model in cylinders
        for node in model.findall(".//geometry/cylinder/radius")
    } == {0.015}
    assert {float(model.findtext("./link/inertial/mass", "nan")) for model in cylinders} == {0.045}
    labels = json.loads(supervision.read_text())["simulator_supervision"]["objects"]
    roles = {item["actual_sim_entity_id"]: item["m2c_layout_role"] for item in labels}
    assert roles[TARGET_ENTITY] == "TASK_TARGET"
    assert roles[SCRIPTED_BLOCKER_ENTITY] == "SCRIPTED_RELOCATION_BLOCKER"

    derived = Path(manifest["derived_existence_probe"]["path"])
    assert sha256(derived) == manifest["derived_existence_probe"]["sha256"]
    assert derived.stat().st_mode & 0o111


def test_v4_preregistration_cannot_overwrite_or_expand(tmp_path: Path) -> None:
    output = tmp_path / "domain-v4"
    output.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_domain(
            template_path=TEMPLATE,
            upstream_probe=UPSTREAM,
            output_root=output,
            key_count=1,
            seed_start=9038,
            seed_stop=9039,
        )
    with pytest.raises(ValueError, match=r"key_count must be in \[1, 3\]"):
        generate_domain(
            template_path=TEMPLATE,
            upstream_probe=UPSTREAM,
            output_root=tmp_path / "too-many",
            key_count=4,
            seed_start=9000,
            seed_stop=9200,
        )
