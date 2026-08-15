# M2C S4 ADR-0026 two-arm Qwen runtime startup smoke

- Status: `PASS_TWO_ARM_REAL_QWEN_RUNTIME_STARTUP_NOT_Q_B`
- Implementation commit: `01883be7f976810b2850c43fb956d764e8df496f`
- Date: 2026-08-15 (Asia/Shanghai)

Both ADR-0026 decision-level bundles were loaded on node2 through the real formal
Qwen V4 service entrypoint.  Each run loaded the pinned Qwen3.5-4B snapshot, its
LoRA adapter, and the three trained heads, then published a strict
`QwenBundleRuntimeBindingV4` and a two-event startup audit.  FC was bound with
`failure_context=on`; NoFC was bound with `failure_context=off`.

This was deliberately `--startup-check-only`.  No HTTP service was opened, no
wire request was received, no Isaac process or physical action ran, and no model
rollout or formal Q-B evaluation occurred.  The association, capture-source, and
declared-attribute digests were contract-smoke inputs only; they are not a claim
of reviewed production deployment evidence.

The complete byte bindings and local evidence paths are recorded in
`reports/m2c-s4-qwen-adr0026-runtime-smoke.json`.  Remaining blockers are the
reviewed production association/attribute deployment, formal Isaac scene and
host-session evidence, and actual formal Q-B episodes.  Consequently
`pure_model_success_episodes` remains `null` and D2 remains false.

Next command:

```bash
PYTHONPATH=src:scripts .venv/bin/python -m pytest -q tests/unit/test_m2c_s4_qwen_adr0026_runtime_smoke.py
```
