# M2A completion audit

- core gate status: **PASS**
- overall status: **PASS_WITH_LIMITATIONS**
- Teacher used: no
- Teacher kill-rule events: none

| Core gate | Result |
| --- | --- |
| `m1b_baseline_and_isaac_migration_verified` | PASS |
| `50_seed_contract_nonblocking` | PASS |
| `dual_rtx3080_30m_benchmark_pass` | PASS |
| `at_least_500_valid_episodes` | PASS |
| `manifest_and_hash_complete` | PASS |
| `data_synced_to_a100` | PASS |
| `real_data_coarse_and_mlp_trained` | PASS |
| `failure_context_ablation_complete` | PASS |
| `at_least_10_isaac_closed_loop_scenes` | PASS |
| `b0_fallback_observed` | PASS |
| `teacher_free` | PASS |
| `no_privileged_truth_policy_input` | PASS |
| `required_reports_present` | PASS |
| `tests_passed` | PASS |

## Governance

- Equivalent M2A ADRs are ADR-0017 and ADR-0018 because ADR-0015 and ADR-0016 were already allocated.
- AGENTS.md world-model governance was not retired; ADR-0018 authorizes only the bounded M2A experiment and requires a separate human ADR for mainline replacement.

## Honest limitations

- pilot adjacent-frame corpus does not physically exercise: EMPTY_GRASP, RELEASE_FAILURE, WRONG_OBJECT
- The adjacent-frame Pilot does not physically exercise EMPTY_GRASP, WRONG_OBJECT, or RELEASE_FAILURE.
- Fifteen failed Isaac/Hydra startup attempts were retained as infrastructure quarantine and are not counted as failed episodes.
- Each paired run uses one epoch, at most 120 train samples, and 50 held-out test samples.
- Two seeds on one 550-episode Pilot dataset cannot establish deployment benefit.
- Physical EMPTY_GRASP, RELEASE_FAILURE, and WRONG_OBJECT cases are absent.
- FailureContext did not improve held-out accuracy for every seed.
- The local Qwen snapshot did not retain Hub revision metadata; the configured base revision is recorded but not independently verified by the raw training reports.
- structured Q2 residual did not beat the zero-residual baseline
- all learned action mappings rejected; B0 fallback rate is 1.0
- This smoke proves live checkpoint inference, validation rejection, and B0 execution.
- It does not claim learned residual actuation or task-success improvement.
- The live checkpoint is structured Q2 coarse+MLP (backbone_dim=0), not the Qwen LoRA adapter.
- Candidate success is limited to a public visibility predicate; task success is unavailable.
- The current Isaac runner does not expose authoritative collision events, so collision is null.
- Main-environment task-success consistency is unavailable for the articulation Pilot.
- Candidates are explicit joint-space physics probes, not learned action mappings or grasp plans.
- Startup and rollout latency make this tool unsuitable for online control.
- This is a format-validation sample, not LingBot training.
- Each canonical record has one action; no terminal action was invented.
- LingBot-World v2 is non-commercial CC BY-NC-SA 4.0.
- The official v2 example uses eight GPUs; no single-A100 runtime claim is made.
- No LingBot weight was downloaded and no VRAM/throughput metric was fabricated.
- closed-loop Isaac infrastructure attempts quarantined: 4

## Task report

- changed files:
  - `configs/m2a-detected-topology.yaml`
  - `data/manifests/isaac-industrial-v1-pilot.json`
  - `docs/competition/requirements-traceability.md`
  - `docs/competition/submission-checklist.md`
  - `docs/m2a-runbook.md`
  - `reports/m2a-artifact-index.json`
  - `reports/m2a-completion-audit.json`
  - `reports/m2a-completion-audit.md`
  - `reports/m2a-reproducibility.md`
  - `reports/m2a-s0-topology-audit.json`
  - `reports/m2a-s0-topology-audit.md`
  - `reports/m2a-s2-worker-benchmark.json`
  - `reports/m2a-s2-worker-benchmark.md`
  - `reports/m2a-s4-qwen-ablation.json`
  - `reports/m2a-s4-qwen-ablation.md`
  - `reports/m2a-s5-qrm-beta-closed-loop.json`
  - `reports/m2a-s5-qrm-beta-closed-loop.md`
  - `reports/m2a-status.json`
  - `reports/m2a-status.md`
  - `scripts/aggregate_isolated_contact_calibration.py`
  - `scripts/isaac/benchmark_workers.sh`
  - `scripts/isaac/host_resources.py`
  - `scripts/isaac/launch_worker.py`
  - `scripts/isaac/summarize_worker_benchmark.py`
  - `scripts/m1a_bullet_controller_probe.py`
  - `scripts/m1a_contact_gated_trial_client.py`
  - `scripts/m2a_status.py`
  - `scripts/plan_m1b_tolerance_calibration.py`
  - `scripts/qrm_lite/eval_failure_context_ablation.py`
  - `scripts/qrm_lite/export_policy.py`
  - `scripts/qrm_lite/prepare_dataset.py`
  - `scripts/qrm_lite/summarize_isaac_closed_loop.py`
  - `scripts/qrm_lite/summarize_qwen_ablation.py`
  - `scripts/qrm_lite/train_coarse_policy.py`
  - `scripts/run_isaac_m1b_dual_benchmark.py`
  - `scripts/run_m1b_attached_roundtrip.py`
  - `src/xh_agent/policy/qrm_lite/backbone.py`
  - `src/xh_agent/policy/qrm_lite/flow_refiner.py`
  - `src/xh_agent/policy/qrm_lite/models_q012.py`
  - `src/xh_agent/policy/qrm_lite/recovery_loop.py`
  - `tests/unit/test_m2a_isaac_data_engine.py`
  - `tests/unit/test_m2a_qwen_ablation.py`
- tests: 217 passed, 0 failed
- failures:
  - 15 Pilot Isaac/Hydra startup attempts were quarantined and excluded from accepted data.
  - 4 closed-loop infrastructure attempts were quarantined and excluded from the accepted evaluation.
- blockers: `[]`
- next command: `make m2a-status`
