from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from m2c.build_headroom_domain import (
    HORIZONTAL_TARGET_LENGTH_M,
    PROJECT,
    generate_domain,
)


TEMPLATE = PROJECT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_domain_selection_is_geometry_only_deterministic_and_b0_unchanged(
    tmp_path: Path,
) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        output_root=tmp_path / "domain",
        key_count=3,
        seed_start=6000,
        seed_stop=6050,
    )
    assert [item["scene_seed"] for item in manifest["keys"]] == [6017, 6019, 6038]
    assert manifest["status"] == "PREREGISTERED_NOT_EVALUATED"
    assert manifest["outcomes_observed"] is False
    assert manifest["q_a_decision"] is None
    assert manifest["baseline_protocol"]["calibration_free_gap_yaw_override"] is None
    assert (
        manifest["baseline_protocol"][
            "implementation_parameters_retries_and_gates_changed"
        ]
        is False
    )
    assert manifest["existence_proof_protocol"]["purpose"].endswith(
        "never counted as B0"
    )
    assert manifest["teacher_used"] is False
    assert manifest["privileged_truth_policy_input"] is False


def test_only_selected_target_gets_horizontal_long_geometry(tmp_path: Path) -> None:
    manifest = generate_domain(
        template_path=TEMPLATE,
        output_root=tmp_path / "domain",
        key_count=1,
        seed_start=6017,
        seed_stop=6018,
    )
    record = manifest["keys"][0]
    sdf = Path(record["sdf"])
    supervision = Path(record["supervision"])
    assert sha256(sdf) == record["sdf_sha256"]
    assert sha256(supervision) == record["supervision_sha256"]

    root = ET.parse(sdf).getroot()
    target = root.find(
        f".//world/model[@name='{record['target_entity_evaluator_only']}']"
    )
    assert target is not None
    pose = [float(value) for value in target.findtext("pose", "").split()]
    assert pose[3] == pytest.approx(math.pi / 2.0)
    assert pose[5] == pytest.approx(record["b0_selected_yaw_rad"])
    target_lengths = [
        float(node.text or "nan")
        for node in target.findall(".//geometry/cylinder/length")
    ]
    assert target_lengths == [HORIZONTAL_TARGET_LENGTH_M] * 2
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
    assert target_label["orientation_state"] == "tilted"
    assert target_label["m2c_scene_geometry"]["domain_only"] is True
    assert (
        (record["scripted_existence_yaw_rad"] - record["b0_selected_yaw_rad"])
        % math.pi
        == pytest.approx(math.pi / 2.0)
    )


def test_preregistration_cannot_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "domain"
    output.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_domain(
            template_path=TEMPLATE,
            output_root=output,
            key_count=1,
            seed_start=6017,
            seed_stop=6018,
        )
