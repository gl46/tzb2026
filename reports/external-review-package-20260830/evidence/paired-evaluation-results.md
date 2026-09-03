# 成对评测最终结果(逐字摘自冻结报告)

对照定义:相同 system prompt、相同 two-shot 示例策略(`two_shot_family_first_v2`)、
相同解码参数、相同解析器;**唯一变量 = 是否挂载 LoRA adapter**。
全分母、零隐藏重试、零测试引导的选择。

## SYNTHETIC_TEST(冻结报告 SHA bcf376d9…)

- 22 cases / **2 个独立分量(聚类)**
- primary = expectation_match,**delta = 0**
- 成对 2×2:`n11/n10/n01/n00 = 19 / 0 / 0 / 3`
  - n11 = 两臂都对 19;n10 = 仅 baseline 对 0;n01 = 仅 LoRA 对 0;n00 = 两臂都错 3
  - **即:LoRA 没有纠正任何一例,也没有破坏任何一例**
  - 推得 baseline 绝对准确率 = 19/22 = **86.4%**
- exact McNemar p = 1.0
- strict / expectation / primitive / boundary 四项 delta 及 bootstrap CI **均为 0**
- 10,000 replicates,seed 20260830;2 < 8 故全项标记 `UNSTABLE_LOW_CLUSTER_COUNT`,
  `stable_statistical_interval = false`

## MANUAL_BLIND(冻结报告 SHA c261454b…)

- 45 cases / **3 个独立分量**
- primary = expectation_match,**delta = 0**
- 成对 2×2:`n11/n10/n01/n00 = 31 / 0 / 0 / 14`
  - 推得 baseline 绝对准确率 = 31/45 = **68.9%**
- exact McNemar p = 1.0
- strict / boundary delta = `+1/45 = 0.0222`,CI = `[0, 0.0714]`
- expectation / primitive 的 delta 与 CI 均 0
- 3 < 8 故全项 unstable flag;`point gate = false`
- **BLIND primary 非回归 = true**,强制安全/契约无逐例回归

## 最终 A2 分类(冻结 SHA 09f4078a…)

```
point_delta_gate_pass       = false      (未达 +0.05 方向性门)
CI_lower_nonnegative        = true
BLIND_nonregression         = true
complete_evidence           = true
no_contract_safety_regression = true
unstable_flag               = true
-------------------------------------------
结论 = NO_BENEFIT_EVIDENCE / 无收益证据
benefit_claim_authorized    = false
```

**注意**:这不是"训练退化"的声明。primary expectation 在 TEST 与 BLIND 上 delta 均为 0,
即 LoRA 与调优后 few-shot **完全打平**(逐例层面也打平:n10 = n01 = 0)。

## DEV 集(用于 few-shot 策略选择,双臂均已接触)

- 选定策略 `two_shot_family_first_v2`:64/78 expectation ≈ **82.1%**
- 78/78 strict-valid;64/78 primitive-check;78/78 boundary
- DEV = 78 行 / 66 源 / **6 个分量**
