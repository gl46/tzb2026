# M2C S4 ADR-0026 Qwen V4 two-arm training

Status: **PASS_TWO_ARM_A100_TRAINING_NOT_Q_B**

Both required Qwen V4 training arms completed on node2 at source commit `81dbb5efe4010fc34162f4113122d11feed04165`. The FC arm used `failure_context=on`; the NoFC arm used `failure_context=off`. Seed, one-epoch schedule, learning rate, 273-row/39-episode dataset, base-model revision, optimizer-step count, and PyTorch fallback were otherwise identical.

The committed machine report binds the training source, ADR, dataset manifests and shard, node2 preflight, both bundle manifests, LoRA adapter trees/files, head checkpoints, deployment files, and full train reports. Both local mirrors independently pass `load_adr0026_decision_bundle_v4` with their expected canonical bundle digests.

## Results

| Arm | Bundle SHA-256 | Wall time | Reported peak VRAM | Training-fit joint exact match |
| --- | --- | ---: | ---: | ---: |
| FC (`failure_context=on`) | `6e7cb272445a64413d6adbe687431172816148f2bd571ada28ec7075fc2dd2a2` | 929.457 s | 34203.829 MiB | 0.498168 |
| NoFC (`failure_context=off`) | `1b6757dc66bbabc939858f477537e18ef9797edce2c57c95f7ae6f4423c72138` | 936.567 s | 34195.737 MiB | 0.549451 |

These are training-set fit measurements only. They are neither held-out evidence nor physical Q-B results, and no comparison above is used as a model-capability conclusion.

## Evidence boundary

- Training performed: yes, two arms, 273 optimizer steps each.
- Teacher used: no.
- Privileged simulator truth used as policy input: no.
- Model rollout or physical execution: no.
- Formal Q-B evaluation: not run.
- `pure_model_success_episodes`: `null`; D2 is not triggered.

The remaining blocker is runtime integration of the ADR-0026 decision bundle into the frozen formal deployment closure, followed by a source-bound contract smoke and only then formal physical Q-B evidence collection.

## Changed files

- `reports/m2c-s4-qwen-adr0026-training.json`
- `reports/m2c-s4-qwen-adr0026-training.md`
- `tests/unit/test_m2c_s4_qwen_adr0026_training.py`

Failures: none in the two completed training runs.

Blockers: ADR-0026 runtime integration is not yet in the formal deployment closure; formal Q-B remains unmeasured.

Next command:

```bash
PYTHONPATH=src:scripts .venv/bin/python -m pytest -q tests/unit/test_m2c_s4_qwen_adr0026_training.py
```
