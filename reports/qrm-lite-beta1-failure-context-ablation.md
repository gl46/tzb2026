# Beta-1 FailureContext ablation (Q1 vs Q2)

Primary question: does FailureContext reduce same-failed-action repetition?

- offline repetition: `{"q1_same_failed_action_repetition_rate": 0.10204081632653061, "q2_same_failed_action_repetition_rate": 0.02040816326530612, "relative_reduction": 0.8, "absolute_reduction": 0.0816326530612245, "q1_n": 49, "q2_n": 49, "q1_action_hist": {"REOBSERVE": 21, "GRASP": 8, "OBSERVE": 5, "ALTERNATE_OBLIQUE": 5, "ALTERNATE_SIDE": 10}, "q2_action_hist": {"REOBSERVE": 25, "GRASP": 4, "OBSERVE": 9, "MOVE": 1, "ALTERNATE_SIDE": 10}}`
- dry loop q1 vs q2: `{"q1_same_failed_action_repetition_rate": 0.0, "q2_same_failed_action_repetition_rate": 0.0, "relative_reduction": null, "absolute_reduction": 0.0, "q1_n": 10, "q2_n": 10, "q1_action_hist": {"REOBSERVE": 10}, "q2_action_hist": {"REOBSERVE": 10}}`
- q1 offline: `{"recovery_top1": 0.3877551020408163, "skill_accuracy": 0.3877551020408163, "macro_f1": 0.18333333333333335, "n_fail_samples": 49}`
- q2 offline: `{"recovery_top1": 0.3877551020408163, "skill_accuracy": 0.3877551020408163, "macro_f1": 0.15384615384615385, "n_fail_samples": 49}`

Flow is not part of this comparison.
