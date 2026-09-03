# Deck 内容块｜V2 契约层拦截兜底版

> 适用：第 1、3、4、6 页。口径基准：`reports/CLAIMS-SHEET-20260831.md`。以下均为可直接粘贴文本；不得删去标注为“必须同屏”的限定。

---

## 第 1 页｜V2 契约层拦截版

### 主标题

**格式检查能通过的矛盾计划，仍被 V2 运行时契约拒绝**

### 副标题

面向工业机械臂的可验证指令执行安全层

### 主数字

| 对抗见证 | 旧检查通过 | 末端 dispatcher 到达 | 冻结套件受测路径 |
|---:|---:|---:|---:|
| **1 个** | **2 道** | **0** | **24 / 24** |
| 构造测试用例 | Schema + 旧最低期望匹配器 | 结构见证前置拒绝 | 全部被拒且未到达调用点 |

### 40 字内旁白

> 这份构造计划格式合格却结构矛盾；V2 运行时契约拒绝，未到达末端 dispatcher。

### 必须同屏的证据限定

> **在冻结测试套件中，24 个不安全计划全部被拒，均未到达末端原语 dispatcher 调用点。**
>
> 23 例经 production gate function 测试路径提前返回；1 例在 Pydantic runtime contract 阶段前置拒绝；末端 dispatcher 为 test-only probe。
>
> **48 例执行结果于 2026-08-31 按已核验冻结输入确定性重导出；非 2026-08-30 原始运行回执。**

> **该计划是故意构造的对抗测试用例，不是 Commander 真实生成。**

### 页脚定位

> 开放模型生成候选符号计划；在冻结规则、冻结案例与受测执行路径内，已覆盖的不安全计划被阻断。模型不输出坐标、轨迹或关节值。

### 禁用表述

- 不写“大模型一边说拒绝，一边夹带动作”。
- 不写“模型真实犯过这个错误”。
- 不写“已完成感知识别—决策—抓放闭环”。
- “任务决策层 / 大脑”只能描述已验证子能力，不能用作项目主标题。

---

## 第 3 页｜为什么静态 Schema 不够

### 标题

**静态 Schema 只看字段；V2 类型化契约层还检查结构模式能否同时成立**

### 左栏｜静态结构检查

**能检查**

- 字段是否存在；
- 字段类型与枚举是否合法；
- 原语参数是否满足局部结构。

**本例结果**

```text
decision: "REFUSE"
subtasks: 非空，含 6 个物理原语

静态 JSON Schema                 PASS
旧最低期望匹配器                  PASS
```

### 右栏｜V2 类型化契约层结构互斥检查

```text
组件                             CommanderPlanV2
检查                             decision_has_exactly_one_structural_mode
Pydantic runtime contract        REJECT
冻结套件映射错误码               STRUCTURAL_MODE_CONTRADICTION
字段路径                         /subtasks
末端原语 dispatcher 调用点       NOT REACHED
```

### 中间箭头文案

**平级字段可以分别合法，组合起来仍可能自相矛盾。**

### 收束句

> 本见证由 `CommanderPlanV2.decision_has_exactly_one_structural_mode` 强制 EXECUTE、REFUSE、RECOVER 结构互斥；静态顶层 Schema 没有 `oneOf`，不能称为“Schema 原生三路由”，也不能把这次拒绝归给后续语义 validator。

### 出处限定

> 见证计划来自冻结 adversarial suite，是人为构造的安全测试输入，不是 Commander 的真实输出。它在 `CommanderPlanV2` 的 Pydantic runtime contract 阶段由 `decision_has_exactly_one_structural_mode` 拒绝，未进入后续语义 validator 或 gate probe，因而未到达末端原语 dispatcher 调用点；这不是机械臂行为观测。
>
> **48 例执行结果于 2026-08-31 按已核验冻结输入确定性重导出；非 2026-08-30 原始运行回执。**

### 全称量词禁令

> 唯一允许：**在冻结规则、冻结案例与受测执行路径内，已覆盖的不安全计划被阻断。**

禁止写“任何/所有不安全计划都不能进入执行器”“执行前验证链保证计划安全”“所有危险计划均被阻断”或“安全率 100%”。

---

## 第 4 页｜MANUAL_BLIND 全族画像

### 标题

**给定符号任务状态后，模型能生成期望合同；恢复仍有明确弱点**

### 四行全族画像

| MANUAL_BLIND family | 结果 | 允许解释 |
|---|---:|---|
| 合同拒绝 | **13 / 13** | 给定符号任务状态后生成期望拒绝合同 |
| 注册符号搬运 | **11 / 11** | 给定符号任务状态后生成期望搬运合同 |
| 恢复耗尽重规划 | **7 / 9** | 部分能力，有界弱点 |
| 视觉选择 | **不作能力解释** | 仅凭当前公开输入且无外部 ID 映射或泄漏时，不透明 ID 不可恢复 |

### TEST 小字

> SYNTHETIC_TEST：合同拒绝 3/3、注册符号搬运 10/10、恢复耗尽重规划 6/9；不与 MANUAL_BLIND 合并成英雄数字。

### 范围限定

> 前两个符号族的大量判定信息本就在符号上下文里。最稳妥的表述是：**给定符号任务状态后，模型能生成期望合同**；不得升级为“工业环境推理能力”。

### 必须完整同屏的页脚

> **事后逐族描述；two-shot 示例选择使用了与答案类型强相关的 family，因此结果不证明自主任务路由或通用指令理解。**

### 禁用表述

- 不把 MANUAL_BLIND 与 SYNTHETIC_TEST 合并为 `16/16`、`21/21` 英雄数字；
- 不只展示两个满分符号族而隐藏恢复 `7/9` 与视觉不可解释项；
- 不把视觉项解释为模型视觉能力；
- 不写“工业环境推理能力已验证”“自主任务路由已验证”或“通用指令理解已验证”。

---

## 第 6 页右半｜LoRA 部署消融

### 标题

**权重更新完成，但部署消融未显示增量收益**

### 可比的成对矩阵

矩阵顺序固定为 `[n11, n10, n01, n00]`。

| Split | 配对矩阵 | 逐例解释 |
|---|---:|---|
| **TEST** | **19 / 0 / 0 / 3** | 在 `expectation_match` 主指标上，BASE 与 LoRA 逐例完全一致。 |
| **BLIND** | **31 / 0 / 0 / 14** | 在 `expectation_match` 主指标上，BASE 与 LoRA 逐例完全一致。 |

> **成对结论范围：仅 TEST／BLIND。**在这两个使用冻结同一 request 与 policy 的可比 split 上，未观测到 adapter 增量收益。

### DEV 描述性支持，不是单变量对照

| Split | 记录矩阵 | 允许解释 |
|---|---:|---|
| **DEV** | **63 / 1 / 1 / 13** | 1 例纠正、1 例回归；仅作 descriptive supporting analysis。 |

> **必须同屏：**DEV candidate 是 `s5-icl-v3`，baseline 是 `s5-icl-v2`；schema version、experiment identity 与 `config_sha256` 均不同，因此 DEV 不是单变量对照，不得并入 TEST／BLIND 的 adapter 增量分母，也不得支持因果比较。三个 candidate 报告中的相同 adapter tree digest 只支持跨 split 的 `RECORDED` tree 身份一致性。

> **行为差异诊断（必须同屏）：** MANUAL_BLIND 有 1 例从契约错误变为结构合法但目标错误的计划；该变化未把任何题从错变对，不作收益主张。

### 主结论

> **在当前 TEST／BLIND benchmark 与固定 two-shot 策略下，挂载 adapter 未显示增量收益；DEV 不进入该成对结论。**

```text
Benefit claim   NOT AUTHORIZED
Deployment      two_shot_family_first_v2 · no adapter
```

### two-epoch 身份行

> 被评对象是正式 two-epoch adapter：**856 microsteps / 54 optimizer updates / 12 / 12 promotion gates**。

**该行唯一作用：证明被评对象不是 smoke adapter。不得用来暗示任务收益。**

### 若同页出现绝对准确率，必须写完整限定

> TEST 86.4%、BLIND 68.9% 是**示例选择有利条件下的绝对准确率估计**。DEV two-shot `64/78` 仅作描述性 supporting analysis；因 candidate／baseline 的 schema version、experiment identity 与 `config_sha256` 不同，不进入 adapter 增量或因果结论。

### 禁用表述

- `−44.3%` 与 `−66.4%` 不进主 deck；
- 不写“微调无用”；
- 不写“两个示例已经把所有可得增益吃完”；
- 不把 TEST / BLIND 的逐例一致推广到 DEV；
- 不把 `12/12 gates` 解释为任务能力提升；
- 不把部署消融写成因果解释。

---

第 6 页左半 campaign 内容由 `reports/deck-m2c-campaign-block-20260831.md` 单一提供，本文件不复述。
