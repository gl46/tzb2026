# GOAL M2C：制造 B0 缺口、让模型接管恢复链，并在 9/1 前冻结可提交证据

你是 XH-202607 项目的模型研发代理。请直接执行工程任务，不要只输出建议或规划。

本 Goal 的起点是已完成的 M2B：分支 `codex/m2b-failure-rich-qrm-activation`，
commit `141e45d`，verdict `GO_QRM_COARSE_ONLY`，364 tests passed，blocker 0。

---

## 0. 本轮要解决的唯一核心问题

M2B 的冻结集上三个方法的最终成功率是：

```text
B0              final_task_success_rate = 1.0
QRM_COARSE_NO_FC                        = 0.5
QRM_COARSE_FC                           = 1.0
```

并且 `model_executed_successful_decisions = 0`，
`system_success_with_non_model_continuation = 20`。

结论：**规则基线 B0 已经饱和，这套评测域没有给模型留下任何可测量的收益空间。**
FC 只是追平 B0，而不是超过 B0；20 次成功的最后一公里全部由固定 B0 continuation 完成。

因此 M2C 不是"再训一点"，而是按顺序回答两个问题：

```text
Q-A  能不能造出一个 B0 会失败、但物理上可恢复的评测域？
     （没有 B0 缺口，任何模型收益都不可测，M2C 无论怎么训都无意义）

Q-B  在那个域里，模型能不能自己走完整条恢复链，产出
     pure model-success episodes > 0，并且 FC 成功率 > B0 成功率？
```

Q-A 未通过时**不得**进入 Q-B 的训练与评测阶段，直接执行 §7 的降级路径。

---

## 1. 硬边界（违反即终止本轮并上报）

继承 `AGENTS.md` 全部 19 条项目规则与 ADR-0019 的运行时边界，并追加：

1. **禁止削弱 B0 来制造缺口。** B0 的实现、参数、重试次数、安全门必须与 M2B
   完全一致，并在报告中给出 B0 相关源文件的 SHA-256，与 M2B 的取值逐一比对。
   缺口只能来自更难的场景，不能来自更弱的基线。
2. **禁止为提升模型指标放宽任何安全门、IK 门、碰撞门、schema 门或映射校验。**
   门槛的任何改动必须单独提交、单独说明理由，并同时给出改动前后的双份评测结果。
3. **禁止改写既有判据的定义来让指标好看。** 若认为某判据定义有误，写进
   `findings` 并保留原判据一并报告，不得静默替换。
4. Teacher 全程不参与：不得引入 Teacher soft label、不得让 Teacher 进入控制栈、
   不得静默替换或升级 Teacher。Nano/BWM/Super 状态保持不变。
5. 特权仿真真值（entity/prim identity、完美位姿、接触、注入失败真值、
   task-success 真值）只能作为训练/评测标签，不得进入 test-time policy input。
6. 不得伪造训练、GPU、吞吐、显存、数据或仿真运行结果。任何一次未真实执行的
   实验都不得进入正式证据。
7. world-model 主线不得被替换；本 Goal 只授权一次有界实验。

遇阻处理规则同既往：先查官方文档与上游 issue，可以安装依赖、可以更换实现路径并
记录理由与版本；单个问题约 60–90 分钟无实质进展就换路径并保留证据；只有凭据、
不可逆系统操作或明确的人类架构决策才停下上报。

---

## 2. 拓扑与起点

```bash
export ISAAC_HOST=root@labserver
export ISAAC_DATA_ROOT=/var/tmp/xh-data/isaac-industrial
export TRAIN_HOST=node2
export DATASET_VERSION=isaac-industrial-v3-headroom
```

工作树 `/Users/gl/tzb-qrm-lite`，从 `141e45d` 开出新分支：

```bash
git checkout -b codex/m2c-model-headroom 141e45d
```

M2B 的全部证据（`reports/m2b-*`、`artifacts/m2b/*`、Dataset V2）一律只读。
不得在 M2C 中修改、覆盖或重新生成任何 M2B 正式证据文件。

---

## 3. 关键指标定义（先定义，后测量）

以下定义在本轮开始前写入 `src/xh_agent/policy/qrm_lite/closed_loop_metrics.py`
并配单元测试，评测阶段不得再改：

- `pure_model_success_episode`：该 episode 任务成功，且从**首次失败**到**任务完成**
  之间的所有恢复决策全部由模型产出并被真实执行，期间没有任何固定 B0 continuation
  或人工兜底动作介入。
- `b0_headroom`：`1.0 − B0_final_task_success_rate`，在同一批 matched key 上测量。
- `fc_gain_over_b0`：`FC_final_task_success_rate − B0_final_task_success_rate`。
  这是 M2C 的**主判据**，M2B 的 NoFC-vs-FC 对比降为次要判据。
- `model_owned_decision_ratio`：模型产出并执行的恢复决策数 / 恢复决策总数。

---

## 4. 阶段与通过判据

每个阶段完成后立即提交，并写入 `reports/m2c-s{N}-*.json` 与同名 `.md`。

### S0 — 冻结与治理（截止 8/14）

- 冻结 M2B commit `141e45d` 与 Dataset V2 为只读证据，记录 hash。
- 写 `docs/decisions/ADR-0020-m2c-model-owned-recovery.md`。
  本 Goal 文档即人类指令（human direction），ADR 必须记录：M2C 扩大了 ADR-0019 的
  运行时边界——模型从"只选第一个恢复技能"扩展到"拥有整条恢复链"；安全门、
  schema 门、IK 门、碰撞门全部保留在执行之前；无效决策仍回落 B0 且不得计为模型成功。
- 通过判据：hash 冻结完成 + ADR 落盘 + `make test` 全绿。

### S1 — 参赛交付物保险（截止 8/15，**优先于一切技术工作**）

挑战杯 9/5 截止，这一阶段是不可延后的保险，必须先落地：

- 从 M2B 已有的成功 episode 中导出一个可哈希校验的 `task_success=true` RGB-D 样例
  （M2A 时期 Pilot 为零成功，M2B 的 B0/FC 均为 1.0，样例现在存在）。
- 录制 WRONG_OBJECT 恢复的同步视频（RGB-D + 决策日志时间对齐）。
- 录制一段 M2B 代表性闭环视频，标注清楚哪一步是模型决策、哪一步是 B0 continuation，
  不得把 B0 收尾的成功包装成模型成功。
- 更新 `docs/competition/submission-checklist.md`，把两个未打勾项打满。
- 通过判据：清单无未打勾必需项；视频与日志的时间戳可对齐核验。

### S2 — 制造 B0 缺口（截止 8/18，**Q-A 门**）

- 构造更难的失败域，候选手段（按成本从低到高，允许组合）：
  复合失败（一个 episode 内连续两类失败）、未见姿态/倾斜圆柱、
  更紧的 bin cell、第四类 `UNSTABLE_PLACEMENT` / `WRONG_CELL`。
- 在新域上跑纯 B0，测 `b0_headroom`。
- **通过判据：`B0_final_task_success_rate < 0.8`，且该域内失败在物理上可恢复
  （给出至少一条人工或脚本可达的成功恢复轨迹作为存在性证明）。**
- 未通过则不进入 S3–S6，直接执行 §7 降级路径 D1。

### S3 — 数据扩展（截止 8/22）

- 三类失败扩到推荐门 **100 failures / 50 recoveries 每类**，并采集第四类。
- 沿用 M2B 的 scene/failure-seed 分组切分，禁止跨 split 泄漏。
- 通过判据：过 full class-coverage gate（不是 M2B 的 reduced gate）；0 quarantine
  或每一条隔离样本都有记录的隔离理由。

### S4 — 模型接管恢复链（截止 8/26，**Q-B 主门**）

- 取消固定 B0 continuation，让模型产出整条恢复链；安全门全部保留在执行前。
- 无效决策仍回落 B0，且该 episode **不得**计入 `pure_model_success_episode`。
- 通过判据：`pure_model_success_episodes ≥ 1`（目标 ≥ 10）。
- 到期未达成则执行降级路径 D2。

### S5 — 残差进闭环（截止 8/29）

- MLP 残差进入闭环；r6d/gripper 要么解冻并给出证据，要么保持冻结并在报告中
  写明冻结理由与其对结论的限制。
- 通过判据：闭环上 MLP 对 zero-residual 有可测差异（正负都算通过，
  **证伪也是有效结论**）；verdict 相应升级或明确维持 `COARSE_ONLY`。

### S6 — 正式匹配评测（截止 9/1）

- matched 评测扩到 **≥30 冻结 key、≥50 次真实执行的模型决策**。
- 四个方法同集对比：B0 / NoFC / FC / FC+MLP。
- 通过判据：报告 `fc_gain_over_b0` 及其置信区间；碰撞/安全违规必须为 0。

### S7 — 完成审计（截止 9/2）

- 产出 `reports/m2c-completion-audit.md`、`m2c-status.md`、`m2c-artifact-index.json`、
  `m2c-reproducibility.md`、`m2c-dataset-card.md`，格式对齐 M2B。
- 必须包含一节 **Honest limitations**，与 M2B 同等诚实。
- 最后一条命令：`make m2c-status`。

---

## 5. 日期检查点

```text
8/14  S0 冻结 + ADR-0020
8/15  S1 交付物落地            ← 参赛保险，不可延后
8/18  S2 Q-A 门：B0 缺口是否存在  ← 决定 M2C 是否继续
8/22  S3 数据扩展
8/26  S4 Q-B 门：pure model-success > 0
8/29  S5 残差闭环
9/01  S6 正式评测 + 硬冻结      ← 此后不得开新实验
9/02  S7 审计与报告
```

**9/1 为硬冻结日。** 到该日无论进度如何，停止一切新实验，只做 S7 的审计与报告，
把 9/2–9/5 完整留给人类撰写提交材料。

---

## 6. 算力预算

- Isaac 数据生成（labserver 双 RTX3080）：S2 探索 ≤ 12h，S3 扩展 ≤ 36h。
- A100 训练：每次消融 ≤ 6h，S4/S5 合计 ≤ 24h。
- 超预算时优先砍 S3 的数据量（降回 reduced gate），不砍 S2 和 S4——
  没有 B0 缺口和模型自主恢复，数据再多也换不来结论。

---

## 7. 降级路径（deadline-aware，必须显式执行并上报）

- **D1（S2 到期未造出 B0 缺口）**：停止 S3–S5。把剩余时间全部转入 S6，
  在 M2B 的域上把样本量扩到 ≥30 keys / ≥50 次模型执行，提升统计效力，
  结论诚实维持 `GO_QRM_COARSE_ONLY`，并在报告中明确写出
  "B0 在当前工业场景已饱和，模型收益不可测"这一发现本身就是结论。
- **D2（S4 到期 pure model-success 仍为 0）**：冻结结论为 `GO_QRM_COARSE_ONLY`，
  不得通过放宽安全门或缩短恢复链定义来制造"纯模型成功"。转入 S6 扩样本量。
- **D3（S5 残差闭环不稳）**：维持 `COARSE_ONLY`，把不稳定证据完整保留。
- 任一降级触发后，S1 的交付物与 S7 的审计仍必须完成。

---

## 8. 顺带修复（低优先级，只在阶段间隙做）

- `scripts/evaluate_isaac_m1b_perception_gate.py` 的 `main()` 在 NO_GO 时
  仍无条件 `return 0`（第 452 行），修为非零返回码并补一条单元测试。
- 2026-07-29 审查列出的其余 Isaac 侧问题（探针 detach gate 阈值与报告文字不符、
  `_world_pose_xyzw` 用 XformCache 读 authored 变换可能返回冻结位姿、
  躺倒圆柱沿用直立半长 Z 偏移）逐条复核：已修的标注 commit，未修的写进 findings。
- 这些不得占用 S2 与 S4 的时间预算。

---

## 9. 报告要求

每个阶段的任务报告必须列出：changed files、tests、failures、blockers、
以及一条 next command。禁止在没有真实执行的情况下填写任何指标。
最终报告必须同时给出主判据 `fc_gain_over_b0` 与
`pure_model_success_episodes`，即使二者都不利于模型。
