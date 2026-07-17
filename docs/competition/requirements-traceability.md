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
