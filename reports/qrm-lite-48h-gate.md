# QRM-Lite 48h gate

- verdict: **CONTINUE_WITH_FIXES**
- questions: `{
  "qwen_multimodal_forward": false,
  "hidden_states": false,
  "lora_step": false,
  "coarse_overfit": true,
  "camera_action_roundtrip": true,
  "mlp_overfit": true,
  "flow_forward_backward": true,
  "flow_loss_decreased": true,
  "flow_outperforms_mlp_preliminary": false,
  "data_alignment_auditable": true,
  "a100_capacity_ok": true
}`

- Coarse/MLP/Flow numpy paths and contracts are implemented and unit-tested.
- Flow does not beat MLP on the alpha offline split; do not market Flow as core innovation.
- Qwen3.5-4B download on node2 in progress via hf-mirror; multimodal smoke pending completion.
- User topology override: gl@node2 only.

Honesty rule: if Flow is not better than MLP, keep the simpler residual head.
