from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from m2c.build_headroom_domain import PROJECT
from m2c.build_tall_headroom_domain import (
    BASELINE_CONTACT_CENTERLINE_M,
    SCRIPTED_EXISTENCE_CONTACT_CENTERLINE_M,
    TALL_TARGET_LENGTH_M,
    generate_domain,
)


TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v2_selection_is_deterministic_stable_and_outcome_blind(
    tmp_path: Path,
) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        output_root=tmp_path / "domain-v2",
        key_count=3,
        seed_start=7000,
        seed_stop=7050,
    )
    assert [item["scene_seed"] for item in manifest["keys"]] == [7018, 7037, 7038]
    assert manifest["status"] == "PREREGISTERED_NOT_EVALUATED"
    assert manifest["outcomes_observed"] is False
    assert manifest["q_a_decision"] is None
    assert manifest["selection_protocol"]["all_orientations"] == "normal upright"
    assert (
        manifest["selection_protocol"][
            "mass_material_friction_and_velocity_decay_changed"
        ]
        is False
    )
    assert manifest["baseline_protocol"]["contact_centerline_m"] == 0.12
    assert (
        manifest["baseline_protocol"][
            "implementation_parameters_retries_and_gates_changed"
        ]
        is False
    )
    assert manifest["existence_proof_protocol"]["contact_centerline_m"] == 0.10
    assert manifest["teacher_used"] is False


def test_v2_changes_only_selected_target_length_and_supported_height(
    tmp_path: Path,
) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        output_root=tmp_path / "domain-v2",
        key_count=1,
        seed_start=7018,
        seed_stop=7019,
    )
    record = manifest["keys"][0]
    sdf = Path(record["sdf"])
    supervision = Path(record["supervision"])
    assert sha256(sdf) == record["sdf_sha256"]
    assert sha256(supervision) == record["supervision_sha256"]
    assert record["part_count"] <= 9
    assert record["baseline_contact_centerline_m"] == pytest.approx(
        BASELINE_CONTACT_CENTERLINE_M
    )
    assert record["scripted_existence_contact_centerline_m"] == pytest.approx(
        SCRIPTED_EXISTENCE_CONTACT_CENTERLINE_M
    )

    root = ET.parse(sdf).getroot()
    target = root.find(
        f".//world/model[@name='{record['target_entity_evaluator_only']}']"
    )
    assert target is not None
    pose = [float(value) for value in target.findtext("pose", "").split()]
    assert pose[2] == pytest.approx(0.45 + TALL_TARGET_LENGTH_M / 2.0 + 0.0001)
    assert pose[3:5] == pytest.approx([0.0, 0.0])
    target_lengths = [
        float(node.text or "nan")
        for node in target.findall(".//geometry/cylinder/length")
    ]
    assert target_lengths == [TALL_TARGET_LENGTH_M] * 2
    other_lengths = {
        float(node.text or "nan")
        for model in root.findall(".//world/model")
        if (model.get("name") or "").startswith("cylinder_") and model is not target
        for node in model.findall(".//geometry/cylinder/length")
    }
    assert other_lengths == {0.08}

    labels = json.loads(supervision.read_text())["simulator_supervision"][
        "objects"
    ]
    target_label = next(
        item
        for item in labels
        if item["actual_sim_entity_id"] == record["target_entity_evaluator_only"]
    )
    assert target_label["orientation_state"] == "normal"
    assert target_label["m2c_scene_geometry"]["upright_free_standing"] is True


def test_v2_preregistration_cannot_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "domain-v2"
    output.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_domain(
            template_path=TEMPLATE,
            output_root=output,
            key_count=1,
            seed_start=7018,
            seed_stop=7019,
        )
