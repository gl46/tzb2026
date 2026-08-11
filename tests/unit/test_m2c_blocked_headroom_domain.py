from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from m2c.build_blocked_headroom_domain import (
    BLOCKER_DISTANCE_M,
    PROJECT,
    SCRIPTED_BLOCKER_ENTITY,
    TARGET_ENTITY,
    generate_domain,
)


TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"
UPSTREAM = PROJECT / "scripts/isaac_m1b_actuation_probe.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_selection_is_deterministic_layout_only_and_outcome_blind(
    tmp_path: Path,
) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        upstream_probe=UPSTREAM,
        output_root=tmp_path / "domain-v3",
        key_count=3,
        seed_start=8000,
        seed_stop=8200,
    )
    assert [item["scene_seed"] for item in manifest["keys"]] == [8018, 8038, 8039]
    assert manifest["status"] == "PREREGISTERED_NOT_EVALUATED"
    assert manifest["outcomes_observed"] is False
    assert manifest["q_a_decision"] is None
    assert manifest["selection_protocol"]["failure_type"] == "PATH_BLOCKED"
    assert (
        manifest["selection_protocol"][
            "object_geometry_mass_material_and_dynamics"
        ]
        == "unchanged M2B"
    )
    assert manifest["baseline_protocol"]["probe_sha256"].startswith("1e32fa89")
    assert manifest["derived_existence_probe"]["counted_as_b0"] is False
    assert manifest["existence_proof_protocol"]["policy_input_simulator_truth"] is False
    for record in manifest["keys"]:
        assert record["target_clearance_before_ok"] is False
        assert record["scripted_blocker_clearance_ok"] is True
        assert record["target_clearance_after_relocation_ok"] is True
        assert record["minimum_surface_gap_m"] >= 0.005


def test_v3_preserves_all_cylinder_geometry_and_hashes_sources(
    tmp_path: Path,
) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        upstream_probe=UPSTREAM,
        output_root=tmp_path / "domain-v3",
        key_count=1,
        seed_start=8018,
        seed_stop=8019,
    )
    record = manifest["keys"][0]
    sdf = Path(record["sdf"])
    supervision = Path(record["supervision"])
    assert sha256(sdf) == record["sdf_sha256"]
    assert sha256(supervision) == record["supervision_sha256"]
    assert record["blocker_distance_m"] == pytest.approx(BLOCKER_DISTANCE_M)
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
    assert {
        float(model.findtext("./link/inertial/mass", "nan"))
        for model in cylinders
    } == {0.045}
    labels = json.loads(supervision.read_text())["simulator_supervision"][
        "objects"
    ]
    roles = {item["actual_sim_entity_id"]: item["m2c_layout_role"] for item in labels}
    assert roles[TARGET_ENTITY] == "TASK_TARGET"
    assert roles[SCRIPTED_BLOCKER_ENTITY] == "SCRIPTED_RELOCATION_BLOCKER"

    derived = Path(manifest["derived_existence_probe"]["path"])
    assert sha256(derived) == manifest["derived_existence_probe"]["sha256"]
    assert derived.stat().st_mode & 0o111


def test_v3_preregistration_cannot_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "domain-v3"
    output.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_domain(
            template_path=TEMPLATE,
            upstream_probe=UPSTREAM,
            output_root=output,
            key_count=1,
            seed_start=8018,
            seed_stop=8019,
        )
