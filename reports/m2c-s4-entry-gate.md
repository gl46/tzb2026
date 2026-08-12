# M2C S4 Q-B entry gate

- Status: **BLOCKED_FORMAL_Q_B_EVALUATION**
- Checked Git HEAD: `1a46ebf2c14077d03fb715b71eaf33bb56c9300d`
- Required physical policy: trained Qwen V2 world-model bundle (LoRA adapter + skill/pointer/destination heads).
- Structured Q0/Q1/Q2 checkpoint accepted as world model: `false`
- Governance gate passed: `True`
- Local contract tests passed: `True`
- Real physical integration receipt passed: `False`
- Formal Q-B evaluation authorized: `False`
- ADR-authorized training scope available: `True`
- Training executed by this command: `false`
- Evaluation executed by this command: `false`
- Teacher used: `false`
- Privileged simulator truth used as policy input: `false`
- Synthetic unit journal accepted as physical evidence: `false`

## Evidence layers

- Local layer: `PASS`; origin `LOCAL_CONTRACT_TESTS`.
- Physical layer: `NOT_RUN`; origin `None`; receipts `None`; Qwen bundle verified `False`.

Local pytest evidence proves contracts only. ADR §7(3) passes only with one real Isaac receipt from a frozen SMOKE key containing eight fresh public observations, eight unique physical receipts, and trained Qwen V2 world-model provenance. Entry independently replays the complete formal runner wire evidence and its hash-bound labserver service/session audits; it also requires a frozen implementation commit/container/import closure, an unchanged B0 runtime wrapper, and a separately verifiable authentication receipt that never persists endpoint HMAC secrets. Arbitrary hash files and a structured Q012 NPZ cannot satisfy this layer.

## Blockers

- real Isaac Qwen-world-model physical integration receipt not provided
- formal Q-B evaluation is blocked until every ADR section 7 layer passes

## Task report

- Changed files: entry-gate implementation, CLI, Make target, and unit tests.
- Tests: `pytest -q tests/unit/test_m2c_s4_entry_gate.py`.
- Failures: none beyond the blockers above.
- Blocker: formal Q-B evaluation remains fail-closed.
- Next command: `obtain human ADR direction for the frozen K=8 public-input admissibility blocker before collecting training data; after a compliant trained bundle and real-Isaac contract startup exist, collect one frozen-SMOKE-key receipt and rerun make m2c-s4-entry-gate`
