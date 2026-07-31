from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from m2b.run_failure_evidence_worker import (
    accepted_target_reached,
    failure_command,
    load_existing_records,
    public_selector_entity,
    stage_is_valid,
)
from m2b.run_residual_evidence_worker import (
    accepted_correction,
    perturbation_for_seed,
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


def test_worker_resume_records_and_per_class_target_are_strict(tmp_path) -> None:
    status = {
        "schema_version": "M2BFailureEvidenceWorkerStatusV1",
        "teacher_used": False,
        "records": [
            {"scene_seed": 1, "failure_type": failure, "accepted": True}
            for failure in (
                "EMPTY_GRASP",
                "WRONG_OBJECT",
                "RELEASE_FAILURE",
            )
        ],
    }
    (tmp_path / "worker-status.json").write_text(json.dumps(status))
    records = load_existing_records(tmp_path)
    failures = ["EMPTY_GRASP", "WRONG_OBJECT", "RELEASE_FAILURE"]
    assert accepted_target_reached(records, failures, 1) is True
    assert accepted_target_reached(records, failures, 2) is False
    assert accepted_target_reached(records, failures, 0) is False


def test_scale_launcher_partitions_seeds_without_overlapping_workers(
    tmp_path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_log = tmp_path / "ssh.log"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *pgrep*) exit 1 ;;\n"
        "  *) printf '%s\\n' \"$*\" >>\"$FAKE_SSH_LOG\"; echo 12345 ;;\n"
        "esac\n"
    )
    fake_ssh.chmod(0o755)
    project = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_SSH_LOG": str(ssh_log),
        "M2B_SCENE_START": "4000",
        "M2B_SCENE_END": "4003",
        "M2B_EXCLUDE_SEEDS": "4001",
    }
    completed = subprocess.run(
        ["bash", str(project / "scripts/m2b/launch_failure_evidence_scale.sh")],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    launches = ssh_log.read_text().splitlines()
    assert len(launches) == 2
    assert "--scene-seed 4000" in launches[0]
    assert "--scene-seed 4002" in launches[0]
    assert "--scene-seed 4003" in launches[1]
    assert "--scene-seed 4001" not in ssh_log.read_text()
    assert "--accepted-target-per-failure 30" in ssh_log.read_text()


def test_residual_worker_uses_bounded_nonzero_camera_perturbations() -> None:
    for seed in range(4000, 4024):
        x, y, z = perturbation_for_seed(seed)
        assert 0.002 <= abs(x) <= 0.015
        assert 0.002 <= abs(y) <= 0.015
        assert 0.001 <= abs(z) <= 0.005


def test_residual_worker_requires_hash_bound_accepted_correction(
    tmp_path,
) -> None:
    summary = tmp_path / "physical-failure-smoke.json"
    summary.write_text(
        json.dumps(
            {
                "attempts": [
                    {
                        "accepted": True,
                        "evidence": "/remote/corrected.json",
                        "evidence_sha256": "a" * 64,
                    }
                ]
            }
        )
    )
    result = accepted_correction(summary)
    assert result is not None
    assert result["evidence_sha256"] == "a" * 64
