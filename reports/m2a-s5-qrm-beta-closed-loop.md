# M2A S5 QRM Beta Isaac closed-loop

- status: **PASS_WITH_B0_FALLBACK**
- scene episodes: 10
- applied live decisions: 50
- action mapping: `REJECTED_NO_OFFICIAL_EVIDENCE`
- B0 fallback: 50/50
- safety violations: 0
- infrastructure attempts quarantined: 4

The checkpoint ran inside each Isaac process on public RGB-D. Every learned residual was rejected before execution because no official camera-residual-to-joint mapping exists; the validated B0 excitation executed instead.

Limitation: the live checkpoint is structured Q2 coarse+MLP (`backbone_dim=0`), not the Qwen LoRA adapter.
