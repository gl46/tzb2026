# M1A Bullet mimic counterfactuals

- Status: `M1A_BULLET_SIGN_HYPOTHESIS_RESOLVED_CLEAN`.
- Both SDF-only counterfactuals used the same controlled URDF SHA-256: `2a8f3b1edf9cea769a7e5f952f74c29dd4bc18e257bd32d72b43a68b4f864478`.
- Historical `multiplier=-1` observation: the fingers remained at zero in both directions; passive initial-state error was 20 mm. It is invalid for multiplier-sign inference because the controller-level q1 mimic loop was also active.
- Historical q2 `+Y` axis-frame normalization observation: offline zero-pose, 12-collision, and two-sensor checks passed, but runtime again sagged to 13.3 mm, opened only to 15.9 mm, and closed normally. It is likewise invalid for multiplier-sign inference.
- The production generator is restored to direct SDF `multiplier=+1`; neither rejected representation remains active.
- Raw evidence: `logs/m1a-20260717-bullet-opposed-axis-compensation-gate2.log` and `logs/m1a-20260717-bullet-q2-axis-frame-r1-bullet-capability-audit.log`.
- Static audit conclusion: `M1A_CLEAN_SIGN_CONFIRMED_PASSIVE_HOLD_BLOCKED`. The direct q1 parameter removal alone was insufficient; the explicit q1 `mimic="false"` parser opt-out is now applied and is proven in the generated-SDF manifest.
- Root cause: `hardware_interface` 4.45.2 scans the structural URDF `<joint><mimic>` and populates `info_.mimic_joints` unless the corresponding `<ros2_control><joint>` has `mimic="false"`. `gz_ros2_control` 1.2.19 then writes q1's `JointVelocityCmd` each cycle, concurrently with the approved SDF/Bullet physical mimic.
- Clean `+1` result: no controller-side q1 mimic log; q2 opened to 0.04 m with 0.272 mm terminal error, closed to 0.01 m with 0.0011 mm terminal error, and q1 tracked q2. It failed only the no-command initial-state criterion: 0.0183258 m rather than 0.020 m ±1 mm (1.6742 mm error).
- Clean `-1` result: both fingers collapsed to zero and neither 0.04 m open nor 0.01 m close could move them. It rejects `-1` as a compensation encoding. The production generator is restored to direct `+1`.
- Next command: diagnose the 1.674 mm no-command q2 hold error without reintroducing a q1 controller command or relaxing the 1 mm threshold; then rerun clean `+1` GATE2 before GATE3–5.
