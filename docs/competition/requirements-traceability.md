# Competition requirements traceability

| Official requirement | Engineering gate | Evidence / current status |
| --- | --- | --- |
| Q1 virtual data and generative augmentation | seed-disjoint manifest and augmentation boundary | M2A Pilot READY: 550 valid Isaac RGB-D adjacent-frame episodes; 418/66/66 scene-level split |
| Q2 open-domain perception and fine-tune generalization | geometric fallback plus pinned Qwen LoRA ablation | Qwen two-seed real-data ablation complete; no FailureContext gain and no open-domain generalization claim |
| Q3 re-observe and expectation comparison | public RGB-D → predicate residual → FailureContext → re-observe | ten live Isaac scene smokes loaded Q2; all learned mappings rejected and B0 executed |
| Q4 force control not mandatory | contact-gated primitive and fail-closed recovery retained | M1B physical acceptance retained; M2A has no new physical EMPTY_GRASP/WRONG_OBJECT/RELEASE_FAILURE training trajectories |
| Q5/Q6 simulator presentation | dual-worker Isaac industrial scene runs headless | Isaac Sim 6.0.1 dual-RTX evidence and retained worker benchmark |
| Q7 robot only as executor | broker and perception boundary | `ADR-0011`, `docs/architecture/m1b-alpha-perception.md` |
| Q8 cylinders, pose, bin cells, transport reserve | IndustrialCylinderBenchmarkV1 | `configs/scenes/industrial_cylinder_v1.yaml` |
| Q9 independent modules/submission | scripts and package APIs | M2A Make/CLI entries, dataset card, artifact index, reproducibility report and partial video evidence supplied |
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
