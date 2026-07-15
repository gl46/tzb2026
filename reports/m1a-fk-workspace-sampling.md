# M1A offline FK workspace sampling

- Status: `APPROVED_MODEL_OFFLINE_FK_EVIDENCE`; model/scene files are changed but the MoveIt home-state, S0, S1 and S2 runtime gates have not yet run.
- Source URDF SHA-256 before approval: `e017d82f218578603078fd5da73cdba88ed47fef2f5ed57cf9f01f5c666fb096`; approved current URDF SHA-256: `8c68b8dbfbc878d6af7924e2eab0d288c56d5ae126a6f93e4922d5b1638533cd`.
- Approved cube pose: `[0.22, 0.12, 0.475]` m. Approved bin centre: `[0.217366447885, -0.249990627453, 0.45]` m, 0.62 m from base and 0.37 m from cube; bin pre-place target: `[0.217366447885, -0.249990627453, 0.6]` m.

## Cube contact target

- Target: `[0.22, 0.12, 0.475]` m; `100000` uniform seven-arm-joint samples, seed `20260716`, finger joints `0.02` m.

| Model | Random minimum (m) | 3 cm pad-point density | 5 cm pad-point density | Refined position-only distance (m) |
| --- | ---: | ---: | ---: | ---: |
| Current controlled URDF | 0.019599 | 7/200000 (0.003500%) | 25/200000 (0.012500%) | 0.000000 |
| Uniform 0.85 m candidate | 0.061803 | 0/200000 (0.000000%) | 0/200000 (0.000000%) | 0.042994 |
| Official Panda-origin candidate | 0.019599 | 7/200000 (0.003500%) | 25/200000 (0.012500%) | 0.000000 |

## Bin pre-place target

- Target: `[0.217366447885, -0.249990627453, 0.6]` m; `100000` uniform seven-arm-joint samples, seed `20260716`, finger joints `0.02` m.

| Model | Random minimum (m) | 3 cm pad-point density | 5 cm pad-point density | Refined position-only distance (m) |
| --- | ---: | ---: | ---: | ---: |
| Current controlled URDF | 0.010181 | 5/200000 (0.002500%) | 19/200000 (0.009500%) | 0.000000 |
| Uniform 0.85 m candidate | 0.067485 | 0/200000 (0.000000%) | 0/200000 (0.000000%) | 0.059802 |
| Official Panda-origin candidate | 0.010181 | 5/200000 (0.002500%) | 19/200000 (0.009500%) | 0.000000 |

The densities count collision-centre fingertip points; the adjacent JSON records source-arm samples, bounds and both target profiles. Raw point clouds are deterministically regenerable and are not committed as experiment artifacts.

The final column is a bounded damped-least-squares position-only refinement. It does not solve orientation, check collision or establish a collision-free approach, simulator contact, or grasp success.

## Audit handoff

- Changed files: approved URDF/SRDF/collision policy/world, this sampling script and report, ADR-0006, home-state gate scripts, and their unit tests.
- Verification commands: run this script with `--samples 100000 --seed 20260716 --workers 4`, then `.venv/bin/python -m pytest -q` and `.venv/bin/python scripts/validate_project.py`.
- Failure/rejection: the historic uniform 0.85 m candidate remains rejected; no runtime success is claimed here.
- Blocker: `HOME_SELF_COLLISION_GATE_REQUIRED_BEFORE_S0`.
- Next command: run the MoveIt home-state self-collision gate, then S0 before S1 and S2.
