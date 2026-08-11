# M2C S0 M2B/B0 freeze

- status: **PASS**
- M2B baseline commit: `141e45dabddcaf59bb49ab958d9d5273d1f54d88`
- M2B artifact index: 116/116 verified
- M2B reports unchanged: True (51 files)
- B0 implementation/parameters/gates match M2B: True
- local M2B artifacts match frozen hashes: True
- Teacher used: no; kill-rule events: none
- privileged truth used as policy input: no
- world-model mainline replaced: no

## Frozen B0 files

| Path | Role | M2B SHA-256 | Match |
| --- | --- | --- | --- |
| `scripts/isaac_m1b_actuation_probe.py` | physical B0 actuation, recovery, and task-state evidence | `1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094` | PASS |
| `scripts/m2b/run_physical_failure_smoke.py` | M2B B0 retry count and physical failure runner parameters | `7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865` | PASS |
| `scripts/m2b/run_matched_closed_loop_batch.py` | M2B matched B0 sequences and fixed continuation | `5dcb5e17d7a7850939c121ee1fbee4442b40a3a3804b1f1e165a6685d2a21795` | PASS |
| `scripts/m2b/run_prospective_preflight_batch.py` | prospective physical preflight and execution command | `2aa2fc71ac56d6ad01a101c228c7538e8d159bc05c88e6a5419a72d35621f191` | PASS |
| `src/xh_agent/policy/qrm_lite/physical_runtime_gates.py` | physical runtime gate contract | `396dbd1f8ce7c28e89c33e55e22fc297a27b73ebafef2d2435d4aa73f6cb0afc` | PASS |
| `src/xh_agent/policy/qrm_lite/collision_evidence.py` | collision evidence validation | `8e720054c7caf7884b04238a94cef341e8a27ce574c6bdbb51c3c51a1610d93c` | PASS |
| `src/xh_agent/policy/qrm_lite/runtime_adapter.py` | model-to-runtime adapter | `69189ad5fd39980f4d762aeb899b8d953cc5680b534ac853446328af8fc09194` | PASS |
| `src/xh_agent/policy/qrm_lite/safety_adapter.py` | fail-closed safety adapter | `b8082408e6321affa929876ef563b72e39ed1d3329e98406ce6aa13d0e5b5030` | PASS |
| `src/xh_agent/policy/qrm_lite/skill_registry.py` | canonical skill mapping and validation | `d62b2d11440a74152d89e9b58fa86dd14f8e33f12bc6975c6080d72bf6b91a0d` | PASS |
| `src/xh_agent/policy/qrm_lite/transforms.py` | explicit frame and unit transforms | `40257bef2907faddf5f28c136023dbd7c4f8eb172c31a147682859d11f3b3829` | PASS |
| `configs/qrm_runtime_mapping.yaml` | runtime skill registry, parameter bounds, frames, and units | `0019b10e54c79cbca16f842dbfd86708ac1f5259e0d7d062be85855062207559` | PASS |
| `scripts/run_constrained_pick_place.sh` | delivery B0 constrained-pick-place entrypoint | `1b4e52b03eb9a069362fb8b898d3ceeb2719e6eb60f378b74234eae472980cd8` | PASS |

## Task report

- changed files:
  - `akefile`
  - `configs/m2c_b0_freeze.json`
  - `docs/decisions/ADR-0020-m2c-model-owned-recovery.md`
  - `reports/m2c-s0-freeze.json`
  - `reports/m2c-s0-freeze.md`
  - `reports/m2c-s0-verification.json`
  - `scripts/m2c/`
  - `src/xh_agent/policy/qrm_lite/closed_loop_metrics.py`
  - `tests/unit/test_m2c_freeze.py`
  - `tests/unit/test_m2c_metrics.py`
- tests: 372 passed, 0 failed
- failures:
  - none
- blockers:
  - none
- next command: `make m2c-s1`
