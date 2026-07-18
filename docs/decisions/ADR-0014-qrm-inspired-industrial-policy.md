# ADR-0014: Qwen-RobotManip-inspired industrial policy (QRM-Lite Alpha)

- Status: Accepted
- Date: 2026-07-18
- Owners: XH-202607 model track
- Branch: `codex/qrm-lite-alpha`
- Training host (user override): `gl@node2` only
- Paper reference: arXiv `2606.17846v2` (local PDF), official repo audit only

## Context

M1B remains the delivery mainline for industrial perception and non-oracle closed loop.
In parallel we need a lightweight vision-language-action (VLA) policy research line inspired by
Qwen-RobotManip, without claiming official reproduction and without blocking B0/M1B.

Official facts locked for this ADR:

| Source | Finding |
| --- | --- |
| arXiv 2606.17846v2 | Qwen-RobotManip uses Qwen3.5-4B VLM backbone, camera-frame delta EEF actions, in-context observation-state-action history, and a Flow-Matching DiT action expert |
| https://github.com/QwenLM/Qwen-RobotManip | Docs/assets only; **no weights and no training code release plan** stated in README |
| https://huggingface.co/Qwen/Qwen3.5-4B | Public `image-text-to-text` checkpoint, license **Apache-2.0**, revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` (audited 2026-07-18 via hf-mirror) |

Therefore the correct product claim is always:

```text
Qwen-RobotManip-inspired independent implementation
受 Qwen-RobotManip 的相机坐标动作对齐、行为上下文和 Flow-Matching 动作专家启发的独立轻量实现
```

## Decision

1. **Independent implementation only.** Do not claim reproduction of Qwen-RobotManip.
2. **Backbone:** `Qwen/Qwen3.5-4B` (post-trained multimodal), frozen first, then PEFT/LoRA.
3. **Action frame:** camera optical frame end-effector deltas (translation meters + 6D rotation residual + gripper), not absolute base-frame poses as the primary learning target.
4. **Residual policy:** MoveIt / B0 geometric nominal action is the safety anchor; the learned head predicts a bounded residual chunk; final candidate = nominal + residual, then MoveIt safety filter.
5. **FailureContext:** project-owned structured recovery context (expected/observed predicates, failure type, retries). Not present in the official paper as a first-class tensor; treated as our addition.
6. **Bring-up order:** coarse skill head → MLP residual baseline → Flow-Matching refiner prototype. Flow is kept only if it is at least competitive with MLP under the same split/budget.
7. **World models retired on this line:** Gazebo remains the physics/data/eval source. Cosmos/BWM/Qwen-RobotWorld are out of scope for QRM-Lite Alpha.
8. **Topology (user override vs original goal bundle):** original goal text mentioned train@chxy and sim@node2. User directive for this run: **remote only `gl@node2`**. Legacy artifacts may exist on `fx@chxy` but are not written by this track. Local git worktree `/Users/gl/tzb-qrm-lite` coordinates; M1B worktree `/Users/gl/tzb` is not rewritten.
9. **Downloads:** on node2 use domestic mirrors only (`HF_ENDPOINT=https://hf-mirror.com`, pip Tsinghua / PyTorch official cu wheel index). No local Clash proxy on node2.
10. **Failure isolation:** any QRM train failure leaves B0/M1B delivery intact.

## Alternatives considered

| Option | Why rejected |
| --- | --- |
| Wait for official Qwen-RobotManip weights | No release plan; blocks 48h gate |
| Full absolute trajectory generation without MoveIt | Violates project safety and IK/collision stack |
| Flow-only without MLP baseline | Unfair and academically dishonest |
| Train on `fx@chxy` | User restricted remote writes to `gl@node2` |
| Continue Student video world-model mainline | Already retired; conflicts with Gazebo-as-truth decision |

## Consequences

- New package: `src/xh_agent/policy/qrm_lite/`
- New schemas under `schemas/qrm-*.schema.json` and `schemas/failure-context-v1.schema.json`
- Independent env `.venv-qrm-lite` and remote root `~/xh-202607-qrm-lite`
- Reports under `reports/qrm-lite-*.md|json`
- Large HF weights stay outside git (`hf-cache/`, `models/`, `checkpoints/`)
- If Flow does not beat MLP, gate verdict prefers `GO_COARSE_AND_MLP_ONLY` or `STOP_MODEL_LINE_USE_LINGBOT_BASELINE` rather than marketing diffusion as the core innovation

## Honesty rule (must appear in training reports)

> 如果 Flow head 没有稳定优于 MLP residual baseline，就不把扩散式动作生成包装成项目核心创新；最终系统保留表现更好、更稳定、更容易复现的实现。

## Non-goals for Alpha

- Full official corpus scale (~38k hours)
- Closed-loop Gazebo success as a hard PASS requirement
- Full-parameter Qwen finetune as default
- Teacher soft-label world-model training
