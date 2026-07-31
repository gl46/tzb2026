from __future__ import annotations

from m2b.build_residual_pair_pilot import build_pairs


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
