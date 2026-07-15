# M1A offline FK workspace sampling

- Status: `EVIDENCE_ONLY — ADR-0006 NOT APPROVED`; no URDF, scene, controller, or end-effector change was made.
- Samples: `100000` uniform seven-arm-joint configurations, seed `20260716`; each yields two collision-centre fingertip points.
- Target: `[0.22, 0.12, 0.475]` m; finger joints held at `0.02` m.
- Current arm-and-wrist serial translation: `1.980000` m. The candidate scales only arm/wrist origins by `0.371212121`, retains the `0.115000` m hand/finger extension, and gives a `0.850` m nominal total reach.

| Model | Random minimum (m) | 3 cm pad-point density | 5 cm pad-point density | Refined position-only distance (m) |
| --- | ---: | ---: | ---: | ---: |
| Current controlled URDF | 0.026638 | 1/200000 (0.000500%) | 6/200000 (0.003000%) | 0.000000 |
| Uniform 0.85 m candidate | 0.142255 | 0/200000 (0.000000%) | 0/200000 (0.000000%) | 0.126863 |
| Official Panda-origin candidate | 0.019599 | 7/200000 (0.003500%) | 25/200000 (0.012500%) | 0.000000 |

The densities count collision-centre fingertip points; the adjacent JSON also records the number of source arm samples with either pad in each sphere and both point-cloud bounds. The raw 200,000-point clouds are deterministically regenerable from this script and are deliberately not committed as experiment artifacts.

The final column is a bounded damped-least-squares position-only refinement seeded by the nearest random point. It does not solve orientation, check collision or establish a collision-free approach, simulator contact, or grasp success; it cannot authorize the proposed model change.

## Audit handoff

- Changed files: `pyproject.toml`, `scripts/sample_panda_fk_workspace.py`, this JSON/Markdown report, ADR-0006, and `tests/unit/test_m1a_gates.py`.
- Verification commands: run this script with `--samples 100000 --seed 20260716 --workers 4`, then `.venv/bin/python -m pytest -q` and `.venv/bin/python scripts/validate_project.py`.
- Failure/rejection: the uniform 0.85 m candidate retains a 0.126863353 m position-only residual and is rejected.
- Blocker: `HUMAN_ADR_0006_APPROVAL_REQUIRED_BEFORE_URDF_OR_SCENE_CHANGE`.
- Next command after approval: implement the exact approved model candidate, then rerun S0 before S1 and S2.
