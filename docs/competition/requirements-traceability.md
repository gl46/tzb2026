# Competition requirements traceability

| Official requirement | Engineering gate | Evidence / current status |
| --- | --- | --- |
| Q1 virtual data and generative augmentation | seed-disjoint manifest and augmentation boundary | `scripts/generate_perception_dataset.py`; fixture generated, Gazebo dataset pending |
| Q2 open-domain perception and fine-tune generalization | geometric fallback plus pluggable open-vocabulary adapter | `ADR-0012`; no model checkpoint/finetune yet |
| Q3 re-observe and expectation comparison | M1B-beta gate | blocked until Alpha status permits Beta |
| Q4 force control not mandatory | contact-gated primitive retained | `m1a-contact-gated-grasp` evidence; no M1B claim |
| Q5/Q6 simulator presentation | industrial world can start headless | `robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf`; runtime evidence pending |
| Q7 robot only as executor | broker and perception boundary | `ADR-0011`, `docs/architecture/m1b-alpha-perception.md` |
| Q8 cylinders, pose, bin cells, transport reserve | IndustrialCylinderBenchmarkV1 | `configs/scenes/industrial_cylinder_v1.yaml` |
| Q9 independent modules/submission | scripts and package APIs | Alpha interfaces supplied; Beta CLIs pending |
# M2A evidence extension (2026-07-31)

| Competition requirement | M2A evidence |
| --- | --- |
| Q1/Q2 virtual industrial data and perception generalization | `isaac-industrial-v1-pilot` dataset card, scene-level held-out split, RGB-D/mask hashes |
| Q3 re-perceive, reflect, re-decide | public RGB-D transitions, predicate residual, `FailureContextV1`, live checkpoint decision log |
| Q4 failure correction | `REOBSERVE` supervision, held-out FailureContext ablation, B0 fallback evidence |
| Q9 code/model/data/simulator/video/report | `docs/m2a-runbook.md`, M2A artifact index and reproducibility report; S8 currently has one explicitly labelled QRM representative-failure clip, not a success claim |

P1 adds a 30-episode LeRobot v3 format sample and a public-state Shadow Isaac
prototype. Both are offline evaluation/preparation artifacts. Teacher use is
disabled, SimulatorSupervision is not exported to LeRobot, and neither artifact
may replace the Student world-model prediction/selection role.
