# ADR-0015: QRM-Lite Beta-1 — real data, three models, FailureContext ablation

- Status: Accepted
- Date: 2026-07-18
- Parent freeze: tag `qrm-lite-alpha` @ `0287d23`
- Branch: `codex/qrm-lite-beta1`
- Alpha verdict: `GO_COARSE_AND_MLP_ONLY`

## Context

Alpha proved bring-up: Qwen3.5-4B multimodal BF16 + LoRA step on A100, camera-frame residual contracts, coarse/MLP overfit, Flow prototype. Flow did **not** beat MLP offline.

Alpha dataset was weak for product claims (100 geometric synthetic + 20 empty-grasp logs). Beta-1 must answer a different question:

> Does explicit FailureContext reduce same-failed-action repetition and improve recovery skill selection on real M1A episodes and a minimal Gazebo recovery loop?

## Freeze

| Item | Value |
| --- | --- |
| Tag | `qrm-lite-alpha` |
| Commit | `0287d23` |
| Verdict | `GO_COARSE_AND_MLP_ONLY` |
| Flow status | `IMPLEMENTED_NOT_SELECTED` |
| Policy | Do **not** keep piling experiments on the alpha branch tip |

Flow code and tests remain in-tree as appendix only. No further Flow optimization in Beta-1.

## Topology

| Role | Host | Notes |
| --- | --- | --- |
| Training / Qwen resident service / offline ablations | `fx@chxy` | A100; domestic mirrors; long jobs |
| Limited 20-episode recovery closed loop only | `gl@node2` | Only when M1B idle; no long train; no new foundation downloads |
| Code review / reports | local worktree `/Users/gl/tzb-qrm-lite` | No merge to main until Beta-1 gate |

M1B remains delivery mainline. QRM must not rewrite M1B worktree or occupy node2 during M1B sessions.

## Three formal models only

| ID | Name | Inputs | Output |
| --- | --- | --- | --- |
| **Q0** | Coarse-only | Qwen hidden / structured context | skill, grasp family, target track, reobserve, recovery mode |
| **Q1** | Coarse + MLP residual | Q0 + geometric nominal + local geometry | bounded residual Δxyz / wrist rot / gripper / speed bin |
| **Q2** | Q1 + FailureContext | Q1 + failure_type, predicate residual, retry, prior grasp, attempted recoveries | same as Q1 with recovery-aware coarse |

Flow is **not** in the formal table.

Primary ablation is **Q1 vs Q2**, not MLP vs Flow.

## Data: QRM-Real-V1

Sources (labels may use oracle geometry; **online policy inputs must not**):

- M1A S0 contact calibration
- M1A S1 MoveIt multi-segment execution
- M1A S2 frictional grasp failures
- M1A S3 contact-gated pick/place
- M1A S4 B1 oracle pick/place (oracle for labels/nominal only)
- M0 empty-grasp + release-delay

Gate targets (first gate, not final scale):

- ≥50 real episodes
- ≥300 real transitions/chunks
- ≥30% failure/recovery samples
- synthetic ≤50% of train
- episode-level splits
- M1B non-oracle auto-append reserved as **QRM-Real-V2** (do not block Beta-1)

## Residual safety (hard)

Default clip bounds before MoveIt:

- translation ±3 cm / axis
- rotation ±15°
- gripper width ±1 cm
- speed from discrete bins only

Pipeline: `nominal + residual → clip → IK → collision → workspace → execute or fallback nominal/B0`.  
QRM never bypasses MoveIt.

## Minimal closed loop (20 episodes)

Task: random cube/cylinder → top grasp → inject empty-grasp → reobserve → QRM chooses recovery skill → MoveIt + contact gate execute.

Recovery skill set only:

`REOBSERVE | RETRY_TOP | ALTERNATE_OBLIQUE | ALTERNATE_SIDE | ABORT_SAFE`

10 episodes Q1 (no FailureContext) vs 10 episodes Q2 (with FailureContext).

## Latency

Separate cold start vs warm p50/p90. Prefer resident `QwenPolicyService`. Target warm p50 ≤ 5 s; 8–10 s acceptable only for post-failure low-frequency decisions.

## Beta-1 stop/go

- `GO_QRM_BETA_2` — real pipeline repeatable; coarse > majority; MLP > zero residual; FailureContext improves a core metric; ≥1 real Gazebo recovery; no oracle leak
- `GO_QRM_COARSE_ONLY` — FailureContext/coarse useful; residual no real gain
- `STOP_QRM_ACTION_REFINER` — coarse fails to generalize or cannot beat B0 recovery usefulness

## Consequences

- New package surface for Real-V1 importer, Q0/Q1/Q2 registry, residual safety, recovery loop protocol, latency service stub
- Alpha tag immutable reference
- Reports under `reports/qrm-lite-beta1-*`
