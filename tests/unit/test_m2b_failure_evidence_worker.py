from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from m2b.run_failure_evidence_worker import (
    failure_command,
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


def test_failure_container_prefix_is_unique_per_gpu_and_scene(tmp_path) -> None:
    args = SimpleNamespace(
        project_root=tmp_path / "project",
        source_root=tmp_path / "source",
        gpu=1,
        max_failure_attempts=2,
        settle_s=10,
        release_follow_delta_z_m=0.08,
        container_prefix="m2b-evidence",
    )
    command = failure_command(
        args,
        failure="EMPTY_GRASP",
        sdf=args.source_root / "scene-4091.sdf",
        supervision=args.source_root / "scene-4091.supervision.json",
        stage=tmp_path / "stage.usdc",
        output=tmp_path / "output",
        yellow_entity="cylinder_04",
        red_entity="cylinder_07",
    )
    prefix_index = command.index("--container-prefix") + 1
    assert command[prefix_index] == "m2b-evidence-g1-s4091"
