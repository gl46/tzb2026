from __future__ import annotations

from m2b.build_residual_pair_pilot import build_pairs
from m2b.build_residual_pairs import build_pair


def test_residual_pilot_is_nonzero_reconstructible_and_bounded() -> None:
    payload = {
        "m2b_recovery": {
            "wrong_object": {
                "training_eligible": True,
                "regrasp_execution": {
                    "status": "LIFTED",
                    "public_action_input": {
                        "simulator_truth_used": False,
                        "target_world_m": [0.1, 0.2, 0.5],
                    },
                    "object_lift_m": 0.1,
                    "follow_error_m": 0.001,
                },
            }
        }
    }
    pairs = build_pairs(payload)
    assert len(pairs) == 24
    assert all(any(pair["residual_target"][:3]) for pair in pairs)
    assert all(
        target == corrected - nominal
        for pair in pairs
        for target, corrected, nominal in zip(
            pair["residual_target"],
            pair["corrected_action"],
            pair["perturbed_nominal"],
        )
    )


def _physical_execution(offset: list[float], *, lifted: bool) -> dict:
    execution = {
        "status": "LIFTED" if lifted else "CONTACT_GATE_REJECTED",
        "public_action_input": {
            "simulator_truth_used": False,
            "target_world_m": [0.1, 0.2, 0.5],
            "controlled_offset_camera_xyz_m": offset,
            "controlled_offset_coordinate_frame": (
                "m2b_policy_rgbd_optical"
            ),
        },
        "attempts": [{"motion_gate_passed": True}],
    }
    if lifted:
        execution.update({"object_lift_m": 0.1, "follow_error_m": 0.001})
    return {
        "scene_seed": 4025,
        "source_hashes": {"scene.sdf": "a" * 64},
        "m2b_recovery": {
            "wrong_object": {"regrasp_execution": execution}
        },
    }


def test_scaled_residual_pair_requires_independent_physical_correction() -> None:
    pair = build_pair(
        _physical_execution([0.006, -0.002, 0.003], lifted=False),
        _physical_execution([0.0, 0.0, 0.0], lifted=True),
        perturbed_path="/remote/perturbed.json",
        corrected_path="/remote/corrected.json",
        perturbed_sha256="b" * 64,
        corrected_sha256="c" * 64,
    )
    assert pair["perturbation_xyz_m"] == [0.006, -0.002, 0.003]
    assert pair["residual_target"][:3] == [-0.006, 0.002, -0.003]
    assert pair["correction_physically_successful"] is True
    assert pair["physical_correction_evidence"][
        "independent_executions"
    ] is True
    assert pair["teacher_used"] is False


def test_scaled_residual_pair_ids_follow_independent_perturbed_execution() -> None:
    corrected = _physical_execution([0.0, 0.0, 0.0], lifted=True)
    first = build_pair(
        _physical_execution([0.006, -0.002, 0.003], lifted=False),
        corrected,
        perturbed_path="/remote/perturbed-1.json",
        corrected_path="/remote/corrected.json",
        perturbed_sha256="b" * 64,
        corrected_sha256="c" * 64,
    )
    second = build_pair(
        _physical_execution([-0.015, 0.015, -0.005], lifted=False),
        corrected,
        perturbed_path="/remote/perturbed-2.json",
        corrected_path="/remote/corrected.json",
        perturbed_sha256="d" * 64,
        corrected_sha256="c" * 64,
    )
    assert first["pair_id"] != second["pair_id"]
    assert (
        first["physical_correction_evidence"]["corrected_evidence_sha256"]
        == second["physical_correction_evidence"]["corrected_evidence_sha256"]
        == "c" * 64
    )
