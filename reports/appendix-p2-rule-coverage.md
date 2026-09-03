# 技术附录｜P2 语义规则覆盖边界

## 一句话版本

> 冻结的 48-case 套件实际触发声明集 `SEMANTIC_RULE_CODES_V2` 中的 26 类规则；该声明集按源码精确枚举为 38 类，因此有 12 类未触发。这里的分母是**声明集**，不是“验证器只有 38 条可用规则”的一般性主张。

## 分母说明

- Validator 声明集 `SEMANTIC_RULE_CODES_V2`：**38 类**；
- 冻结 P2 套件实际触发的声明码：**26 类**；
- 冻结 P2 套件未触发的声明码：**12 类**；
- `STRUCTURAL_MODE_CONTRADICTION` 是 `CommanderPlanV2.decision_has_exactly_one_structural_mode` 在 Pydantic 运行时结构合同层产生的外部见证映射码，不属于后续 semantic validator 的 38-code 声明集分母。

`38` 的原始推导机制已经从精确源码恢复：suite runner 导入 `SEMANTIC_RULE_CODES_V2`，以 `len(SEMANTIC_RULE_CODES_V2)` 生成 `rule_code_count`，并以该集合和 observed codes 的交集计算覆盖数。按预注册后冻结的声明集口径，完整有序 inventory 的实际 N 为 38，确认源报告分母。另行静态观察到 38/38 声明码均有 production emitter 标记；这**不证明** public-entry 可达性、不排除额外 dynamic emission，也不表示 38 类都被套件触发——冻结套件触发的是 26 类。

`26/38` 不是现实危险空间覆盖率，也不是“安全得分”。主 deck 最多写“冻结套件实际触发声明集中的 26 类语义规则”；完整分母与分类只在本附录出现。

### 可独立复核的库存

权威库存是 create-only JSON；对外一律引用包内路径，工作树路径仅作来源溯源：

```text
evidence/s5/rule-inventory/semantic-validator-rule-inventory-20260901-v1.json
```

工作树来源：

```text
/private/tmp/m2c-v9-semantic-validator-rule-inventory-20260901-v1.json
```

每一项均包含 `code`、`component`、精确 validator source SHA-256、源码位置和直接绑定的 focused test node IDs（无直接绑定时为空）。方法链还包括读值前冻结的 V1/V2 preregistration，以及明确撤回 V2 中“不改变 V1 extraction unit”错误措辞的 post-enumeration ruling addendum。V2 被选中，是因为它对齐源分母的实际声明集来源；V1/V2 等价性未证明、也不是本结论的前提。

---

## A｜六项设计取舍或当前边界

| 未触发规则 | 规则语义 | 为什么未进入冻结 P2 套件 | 其他证据位置 |
|---|---|---|---|
| `INVALID_SNAPSHOT_TIME` | snapshot 时间戳不可解析或缺少 UTC offset | 严格 `PublicWorldSnapshotV2` 通常在进入语义 validator 前已拒绝该输入 | 结构合同边界 |
| `INVALID_SNAPSHOT_INTERVAL` | snapshot expiry 不晚于 capture | snapshot model 已前置强制 `captured < expires` | 结构合同边界 |
| `SNAPSHOT_NOT_YET_VALID` | 校验时刻早于 snapshot capture | 属于时钟边界，未占用固定 P2 多样性分母 | P1 focused test 已直接绑定 |
| `STALE_WORLD_SNAPSHOT` | 校验或派发时 snapshot 已过期 | 属于运行时 freshness 边界，未占用固定 P2 多样性分母 | P1 validator / dispatch-gate focused tests 已直接绑定 |
| `DECISION_MISMATCH` | plan decision 与可信 task-spec decision 不一致 | 结构上通常已被互斥模式先行阻断；P2 使用更强、更直观的 `REFUSE + physical subtasks` 见证 | P1 focused test 已直接绑定 |
| `PHYSICAL_AUTOMATON` | EXECUTE 物理原语序列不符合规定六步自动机 | P2 的 invalid witness 刻意保留物理 inventory，使旧最低期望匹配器仍能通过 | P1 focused test 已直接绑定 |

### 对外答法

> 这六项不是声称“不重要”，而是说明为什么它们没有进入固定的 48-case P2 分母：两项主要由严格结构模型前置排除，两项属于时间与运行时边界，另两项已有 focused tests，且 P2 把有限用例预算用于 old-pass / new-reject 的语义差异见证。

---

## B｜六项冻结 P2 套件的真实遗漏

| 未触发规则 | 规则语义 | 冻结套件缺少什么案例 |
|---|---|---|
| `UNKNOWN_TASK_TARGET` | task target 不在 world snapshot 的目标集合中 | 缺少 trusted task 与 world target-membership 冲突 |
| `UNREGISTERED_TASK_DESTINATION` | task destination 未在 snapshot 中注册 | 缺少目的地注册表失配 |
| `UNKNOWN_TASK_POSE` | approach / destination pose 不在 snapshot pose 集合中 | 现有 pose 错误发生在 plan 参数层，未覆盖 task-spec / world 层 |
| `EXECUTION_RESOURCE_CONFLICT` | 同一物理序列跨多个 agent，共享一个执行资源 | 缺少将物理六步序列拆到多个 agent 的资源冲突案例 |
| `RECOVERY_AUTOMATON` | RECOVER 的 reassociation / capture 数量不满足约束 | 已覆盖缺失 capture、顺序与参数，未覆盖 cardinality |
| `UNEXPECTED_CAPTURE` | task 未请求 fresh observation，却在 RECOVER 中加入 capture | 缺少“无需新 observation，但计划仍执行采集”的案例 |

### 对外答法

> 这六项是真实遗漏，不包装成“有意不测”。因此 48-case 结果证明的是固定套件内的行为，不代表现实世界危险计划已经穷尽。补齐这些边界属于后续 suite 扩展，不回填当前冻结分母。

---

## 冻结套件本身证明什么

| 指标 | 冻结结果 |
|---|---:|
| 合法案例 | 24 |
| 不安全案例 | 24 |
| 不安全误放 | 0 / 24 |
| 合法误拒 | 0 / 24 |
| 错误字段定位 | 44 / 44 |
| 不安全案例被拒且未到达末端原语 dispatcher 调用点 | 24 / 24 |

允许的结论：

> **在冻结测试套件中，24 个不安全计划全部被拒，均未到达末端原语 dispatcher 调用点。**23 个可解析 case 经 production gate function 测试路径提前返回；第 24 个结构矛盾见证在 `CommanderPlanV2` 的 Pydantic runtime contract 阶段前置拒绝，未进入 semantic validator 或 gate probe；末端 dispatcher 为 test-only probe。

禁止外推：

- 不代表现实危险空间的发生率；
- 不代表声明集 38 类规则都在该套件中触发；
- 不得写“任何/所有不安全计划都不能进入执行器”“执行前验证链保证计划安全”“所有危险计划均被阻断”或“安全率 100%”；
- 不代表真实机械臂保持不动，也不代表端到端执行器“执行了且仅执行了”某组原语；
- 不把运行时结构见证 `STRUCTURAL_MODE_CONTRADICTION` 计入 38-code 声明集分母。
