# QRM-Lite 48h gate

- verdict: **GO_COARSE_AND_MLP_ONLY**
- questions: `{
  "qwen_multimodal_forward": true,
  "hidden_states": true,
  "lora_step": true,
  "coarse_overfit": true,
  "camera_action_roundtrip": true,
  "mlp_overfit": true,
  "flow_forward_backward": true,
  "flow_loss_decreased": true,
  "flow_outperforms_mlp_preliminary": false,
  "data_alignment_auditable": true,
  "a100_capacity_ok": true
}`

- Qwen3.5-4B BF16 multimodal forward + hidden states + LoRA step verified on gl@node2 A100 (~17.8GB peak).
- Coarse and MLP residual overfit gates passed on 100-sample alpha set.
- Flow forward/backward and loss decrease verified, but offline metrics do not beat MLP.
- Therefore continue with coarse+MLP as the practical industrial residual path; Flow stays optional research head.

> 如果 Flow head 没有稳定优于 MLP residual baseline，就不把扩散式动作生成包装成项目核心创新。
