# QRM-Lite MLP vs Flow (offline)

- n_eval: 12
- MLP: `{"translation_mae": 0.032765739611851634, "rotation_r6d_mae": 0.04009893795646421, "gripper_mae": 0.15190108794783122, "chunk_endpoint_trans_mae": 0.03982987020912543, "mse": 0.00511426890036524}`
- Flow: `{"translation_mae": 0.049686331260252875, "rotation_r6d_mae": 0.3849504459628432, "gripper_mae": 0.40005369726457823, "chunk_endpoint_trans_mae": 0.049247776008144235, "mse": 0.13058233565766594}`
- flow_outperforms_mlp_preliminary: **False**

> 如果 Flow head 没有稳定优于 MLP residual baseline，就不把扩散式动作生成包装成项目核心创新。
