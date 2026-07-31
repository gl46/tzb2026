from __future__ import annotations

import json
import hashlib

from m2b.run_failure_evidence_worker import (
    public_selector_entity,
    stage_is_valid,
)


def test_public_selector_resolves_explicit_color_and_max_world_x(tmp_path) -> None:
    sdf = tmp_path / "scene-1.sdf"
    sdf.write_text(
        """<sdf><world>
        <model name="cylinder_01"><pose>-0.5 0 0.5 0 0 0</pose><link><visual><material><diffuse>0.800 0.100 0.100 1</diffuse></material></visual></link></model>
        <model name="cylinder_07"><pose>-0.1 0 0.5 0 0 0</pose><link><visual><material><diffuse>0.800 0.100 0.100 1</diffuse></material></visual></link></model>
        <model name="cylinder_04"><pose>-0.2 0 0.5 0 0 0</pose><link><visual><material><diffuse>0.800 0.600 0.100 1</diffuse></material></visual></link></model>
        </world></sdf>"""
    )
    assert public_selector_entity(sdf, "red") == "cylinder_07"
    assert public_selector_entity(sdf, "yellow") == "cylinder_04"


def test_stage_reuse_requires_source_and_stage_hashes(tmp_path) -> None:
    sdf = tmp_path / "scene-1.sdf"
    supervision = tmp_path / "scene-1.supervision.json"
    output = tmp_path / "stage"
    output.mkdir()
    sdf.write_text("<sdf/>")
    supervision.write_text("{}")
    stage = output / "m1b_physics_scene.usdc"
    stage.write_bytes(b"stage")
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "metrics.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "source_hashes": {
                    sdf.name: digest(sdf),
                    supervision.name: digest(supervision),
                },
                "clean_physics_stage": {"sha256": digest(stage)},
            }
        )
    )
    assert stage_is_valid(output, sdf=sdf, supervision=supervision)
    sdf.write_text("<sdf><changed/></sdf>")
    assert not stage_is_valid(output, sdf=sdf, supervision=supervision)
