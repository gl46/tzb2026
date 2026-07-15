# M1A offline FK workspace sampling

- Status: `EVIDENCE_ONLY — ADR-0006 NOT APPROVED`; no URDF, scene, controller, or end-effector change was made.
- Samples: `100000` uniform seven-arm-joint configurations, seed `20260716`; each yields two collision-centre fingertip points.
- Target: `[0.22, 0.12, 0.475]` m; finger joints held at `0.02` m.
- Current arm-and-wrist serial translation: `1.980000` m. The candidate scales only arm/wrist origins by `0.371212121`, retains the `0.115000` m hand/finger extension, and gives a `0.850` m nominal total reach.

| Model | Minimum pad-centre distance to target (m) | 3 cm pad-point density | 5 cm pad-point density |
| --- | ---: | ---: | ---: |
| Current controlled URDF | 0.016674 | 3/200000 (0.001500%) | 10/200000 (0.005000%) |
| Candidate Panda-scale kinematics | 0.142255 | 0/200000 (0.000000%) | 0/200000 (0.000000%) |

The densities count collision-centre fingertip points; the adjacent JSON also records the number of source arm samples with either pad in each sphere and both point-cloud bounds. The raw 200,000-point clouds are deterministically regenerable from this script and are deliberately not committed as experiment artifacts.

This is an offline kinematic comparison only. It does not establish collision-free approach, simulator contact, or grasp success, and it cannot authorize the proposed model change.
