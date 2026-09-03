# 答辩附录｜Qwen / 执行前验证链 / LoRA 标准问答

> 使用方式：每条先给结论，再给边界。不得把限定删掉后单独引用数字。

---

## 1｜你们到底完成了什么？

**标准答法**

> 我们部分完成了题目，站得住的定位是“面向工业机械臂的可验证指令执行安全层”。27B Commander 用于生成候选符号合同；候选合同必须经类型化运行时契约与确定性语义验证后才能进入受测执行路径。我们没有可辩护的视觉识别正证据，也没有冻结条件下的成功抓放闭环，所以不把系统说成完整感知—决策—抓放闭环。

**不要回答**

- “虽然没有完成题目，但治理更重要”；
- “我们完成了机器人认知大脑”；
- “这是端到端 VLA”。

---

## 2｜为什么只讲“安全层”，不叫“机器人决策大脑”？

**标准答法**

> 事后逐族描述中，MANUAL_BLIND 的合同拒绝为 13/13、注册符号搬运为 11/11、恢复耗尽重规划为 7/9；视觉选择不作能力解释。Two-shot 示例选择使用了与答案类型强相关的 family，因此这些结果不证明自主任务路由或通用指令理解。最稳妥的能力表述是“给定符号任务状态后，模型能生成期望合同”；整体主标题仍必须小于证据，叫“可验证指令执行安全层”。

---

## 3｜48 个案例够吗？

**标准答法**

> 够支撑固定套件内的明确结论，不够代表现实危险空间。套件有 24 个合法和 24 个不安全案例，其中 12 个是复合对抗。结果是误放 0/24、误拒 0/24、错误字段定位 44/44；24 个 rejected case 均未到达末端原语 dispatcher 调用点。23 例经 production gate function 测试路径提前返回，1 例在 Pydantic runtime contract 阶段前置拒绝，末端 dispatcher 为 test-only probe。源码声明集 `SEMANTIC_RULE_CODES_V2` 已按预注册口径完整枚举为 38 类，套件实际触发声明集中的 26 类；未触发的 12 类中，6 类属于当前边界或已有 focused tests，另 6 类是真实遗漏，完整有序 inventory、源码位置与直接 focused-test 绑定放在技术附录。**分母是声明集，不能说成“验证器只有 38 条规则可用”；另行观察到 38/38 声明码有静态 production emitter 标记，也不等于 38 类都被套件触发。** **48 例执行结果于 2026-08-31 按已核验冻结输入确定性重导出；非 2026-08-30 原始运行回执。**

**关键边界**

> `26/38` 不是安全得分，不在主 deck 与 FAR / FRR 并列展示。

---

## 4｜这个 REFUSE + 动作的错误是模型真实生成的吗？

**标准答法**

> 不是。这是我们故意构造的对抗测试用例，用来检查类型化契约层如何处理这类输入。它在静态 Schema 和旧最低期望匹配器中通过，但被 `CommanderPlanV2.decision_has_exactly_one_structural_mode` 的 Pydantic model validator 拒绝；原始异常是 `value_error`，消息为 `Value error, REFUSE requires empty subtasks and no recovery_request`。冻结 suite 把它规范映射为 `STRUCTURAL_MODE_CONTRADICTION`，路径 `/subtasks`。它未进入后续语义 validator 或 gate probe，因而未到达末端原语 dispatcher 调用点。我们不把它冒充 Commander 的真实事故。

**不要回答**

- “大模型一边拒绝一边夹带动作”；
- “模型真实犯过这个错”。

---

## 5｜为什么静态 JSON Schema 会放过矛盾计划？

**标准答法**

> 当前静态顶层 Schema 中 `decision` 与 `subtasks` 是平级字段，没有用顶层 `oneOf` 表达三种模式的互斥关系。因此字段分别合法时，组合仍可能自相矛盾。EXECUTE、REFUSE、RECOVER 的互斥由 `CommanderPlanV2.decision_has_exactly_one_structural_mode` 这个 Pydantic model validator 强制实施，不能称为“Schema 原生三路由”，也不能把本见证的拒绝归给后续 semantic validator。

**标识符说明**

> `REFUSE_WITH_NONEMPTY_SUBTASKS` 在当前代码、测试与冻结 inventory 中均不存在，是描述性叫法，不得当作真实错误码。真实原始异常标识是 Pydantic `value_error`；冻结 suite 的规范映射码是 `STRUCTURAL_MODE_CONTRADICTION`，路径 `/subtasks`。

---

## 6｜“未到达末端 dispatcher 调用点”证明了什么？

**标准答法**

> 这来自 synthetic/free-contact 测试 harness，不是真实机械臂观测。两类拒绝必须分开：23 个可解析的不安全 case 先由 semantic validator 产生 REJECT，再进入 production gate function `dispatch_after_semantic_gate_v2` 并提前返回；第 24 个结构矛盾见证由 `CommanderPlanV2.decision_has_exactly_one_structural_mode` 在 Pydantic runtime contract 阶段前置拒绝，未进入 semantic validator 或 gate probe。末端 dispatcher 为 test-only probe，两类均未到达其调用点；冻结结果同时记录 `primitive_dispatch_count = 0`。统一结论是：**在冻结测试套件中，24 个不安全计划全部被拒，均未到达末端原语 dispatcher 调用点。**不能说 production gate function 未被调用、机械臂保持不动或端到端执行安全。

---

## 7｜七文件子集 135 PASS 与 48 个语义案例是什么关系？

**标准答法**

> 两者必须分栏。**在冻结语义契约路径的七文件回归子集上，135 项全部通过**，并另行通过 lint / compile / schema / diff 四门；这四门不在 135 之内。七文件的有序 selector 与精确 argv 已从产生该结果的 transcript 取证恢复；tzb-fe 于 2026-09-01 按恢复的 argv 独立实跑，观测到 `135 passed`、exit 0。**只报告这次复现观测，不把一次复现写成一般性保证。**`135` 是当前冻结身份的 2026-08-31 重导出结果，不是 P1 原始 134 运行，也不是仓库全量。七文件子集涉及的 13 个 terminal 文件中，11 个身份一致，2 个（validator 与其测试）已是后续 P2 身份。48 是独立冻结的语义案例，其中 24 合法、24 不安全；其执行结果于 2026-08-31 按已核验冻结输入确定性重导出，不是 2026-08-30 原始运行回执。不能把 135 说成 135 个安全案例，也不能把两者合成一个分母。
>
> | 全仓相关口径 | 必须完整保留的限定 |
> |---|---|
> | 现行可核值 | `61 failed / 1886 passed / 5 skipped`，2026-09-01 实测；有记录的 shell 命令、原始 stdout、nodeid 与退出码回执；**进程 argv 未确立**。 |
> | 旧值 | `14 failed / 1933 passed / 5 skipped`，2026-08-31 **一次执行**；状态为 `TRANSCRIPT_ATTESTED`：记录的 shell 命令、结果行与 14 个 failed nodeid 均从产生它的会话 transcript 取证恢复，但 transcript **在包外**；命令经 `tail -25`，故完整 stdout 未捕获；无 `pipefail` / `PIPESTATUS`，故 pytest 退出码不可推断；进程 argv 未确立；我们未重现它。 |
> | selector | 两次均为**全仓扣除一个被 ignore 的 collection-error 文件**，不是真正的“全仓”；8/31 恢复的是 shell 命令文本，不是 process argv。 |
> | 失败归属 | 61/61 全在 `test_m2c_*`；**19 个失败文件中只抽查了 1 个**，不得说 47 个新增失败全由冻结门导致，也不得说“无害”。 |
> | 变更扫描 | `find -newermt` 是 **mtime 证据，不是字节证据**；范围排除 `.git`、`.venv`、`artifacts`，且扫描结果非空。 |
> | qwen_brain | 2026-09-01 **观测到** `359 passed / 4 skipped / 0 failed`；不得写“不受冻结门影响”。 |

---

## 8｜为什么训练 loss 降了，任务结果却没提升？

**标准答法**

> 优化目标变化和任务级决策变化不是同一个量。Two-epoch 训练健康完成；可用于同配置成对比较的 TEST 是 `19/0/0/3`、BLIND 是 `31/0/0/14`，两者在 `expectation_match` 上逐例完全一致。因此在当前 TEST／BLIND benchmark 与固定 two-shot 策略下，没有观察到 adapter 增量收益。**DEV 的 candidate 是 `s5-icl-v3`、baseline 是 `s5-icl-v2`，schema version、experiment identity 与 `config_sha256` 均不同，不是单变量对照；`63/1/1/13` 只能作描述性 supporting analysis，不得并入 adapter 增量或成对因果结论。**这个结论是有界部署消融，不是“微调普遍无用”的结论。

**如追问 loss 百分比**

> `−44.3%` 是固定探针交叉熵变化，不是训练损失；训练损失是 `0.5663 → 0.1900`，约 `−66.4%`。两者都只说明优化目标改变，不能替代任务级成对证据。它们不进入主 deck。

---

## 9｜两个示例是不是已经吃完所有收益？

**标准答法**

> 不能这样说。`18/78 → 64/78` 包含按 `row.family` 选择示例的有利条件，而 family 与答案类型强相关，所以不是“增加两个普通示例”的纯因果效应。唯一允许的增量结论是：在当前 TEST／BLIND benchmark 与固定 two-shot 策略下，没有观察到 adapter 增量收益。**DEV 因 candidate／baseline 的 schema version、experiment identity 与 `config_sha256` 不同，只能作描述性 supporting analysis，不进入该结论。**

---

## 10｜为什么最后部署 two-shot，而不是 LoRA？

**标准答法**

> TEST 与 BLIND 的 candidate／baseline 使用各自冻结的同一 request 与 policy，且没有 discordant pair；这两个可比 split 支持预注册 no-benefit 判定。三个 candidate 报告记录相同 adapter tree digest，**只支持跨 split 的 `RECORDED` tree 身份一致性**。
>
> **DEV 不进入成对增量证据链：**DEV candidate 是 `s5-icl-v3`、baseline 是 `s5-icl-v2`，schema version、experiment identity 与 `config_sha256` 均不同；`63/1/1/13` 仅作描述性 supporting analysis，不支持 adapter 增量或成对因果比较。部署选择为无 adapter 的 `two_shot_family_first_v2`，不得表述为三个 split 共同构成单变量消融。

---

## 11｜12/12 promotion gates 是否证明 LoRA 有效？

**标准答法**

> 不证明任务收益。`856 microsteps / 54 optimizer updates / 12/12 promotion gates` 的唯一作用，是证明被评对象是完整 two-epoch adapter 而不是 smoke，并证明训练管道按预定完整运行。任务收益只看冻结的成对评测。

---

## 12｜绝对准确率能怎么报？

**标准答法**

> 可以报 TEST 86.4%、BLIND 68.9%，但必须紧跟“示例选择有利条件下的绝对准确率估计”。历史 two-shot 分支优先使用显式 `row.family`，它与答案类型强相关。
>
> **DEV two-shot `64/78` 只能作为 descriptive supporting analysis 单列：**DEV candidate 与 baseline 的 schema version、experiment identity、`config_sha256` 不同，不是单变量对照，不进入 adapter 增量或因果结论。

---

## 13｜有没有正面的模型能力证据？

**标准答法**

> 有界的描述性证据位于符号合同生成层。MANUAL_BLIND 中，合同拒绝为 13/13、注册符号搬运为 11/11、恢复耗尽重规划为 7/9；视觉选择不作能力解释。前两个符号族的大量判定信息本就在符号上下文里，且 two-shot 示例选择使用了与答案类型强相关的 family，所以最稳妥的表述是“给定符号任务状态后，模型能生成期望合同”；自主任务路由、通用指令理解与工业环境推理能力均未验证。

---

## 14｜视觉族 0/12 是否说明模型视觉能力很差？

**标准答法**

> 不能得出这个结论。该视觉任务要求逐字输出当前公开输入中不存在的不透明内部 ID；对任何仅访问当前公开输入、且无外部 ID 映射或泄漏的方法，该 ID 不可恢复。因此 0/12 与任务可识别性缺陷一致，不是模型视觉能力的干净测量。我们本版本没有可辩护的视觉绑定证据，修正设计留到 vNext。

---

## 15｜BLIND 的错误是不是全部来自视觉？

**标准答法**

> 不是。MANUAL_BLIND 的 14 个错误中，12 个属于视觉族，另 2 个属于恢复族。全族画像是：合同拒绝 13/13、注册符号搬运 11/11、恢复耗尽重规划 7/9；视觉选择不作能力解释，因为对任何仅访问当前公开输入、且无外部 ID 映射或泄漏的方法，该不透明 ID 不可恢复。BASE 与 LoRA 在 `expectation_match` 上逐族一致；MANUAL_BLIND 的 secondary structural metrics 有 1 例差异。

---

## 16｜安全层是否依赖 Qwen3.8-27B？

**标准答法**

> 当前实现使用冻结的 Qwen3.8-27B 多模态 VL 作为 Commander，用于生成候选符号合同。架构通过符号合同接口分层；尚未做跨基座替换测试，因此不声称可替换性已经验证。通用指令理解与自主任务路由同样未被干净验证。

---

## 17｜权重冻结是否意味着系统能力不会下降？

**标准答法**

> 不意味着。过长 prompt、错误 few-shot、强制 JSON、错误路由、上下文截断或 validator 误拒，都可能使系统中的模型表现低于裸基座，而我们没有测裸基座基线。可以声称的是：基座权重保持冻结；在冻结规则、冻结案例与受测执行路径内，已覆盖的不安全计划被阻断，rejected case 均未到达 test-only 末端原语 dispatcher 调用点。

---

## 18｜抓取 campaign 能否说 0/12？

**标准答法**

> 不能。冻结账目是 5 个有效结果、0 成功、7 个 ordinal 未消费；ordinal05 有一次真实物理派发尝试，但 harness `rc=1`，没有形成 canonical outcome，06–11 从未执行。因此不作成功率或假设检验结论，也不写 `0/12`。

---

## 19｜为什么在剩余运行前停止？是否丢失信息？

**标准答法**

> 在 ordinal05 点火前，我们用冻结判据枚举剩余 128 种后缀，确认进入关键冻结的可能性已经为 0，因此停止。这个决定没有丢失进入关键冻结的可能性，但仍丢失了剩余运行本可提供的描述性、失败模式和后续版本诊断信息。原协议没有预先检查终态可达性，这是设计缺陷；该内容只放技术附录。

---

## 20｜你们最强的技术证据是什么？

**标准答法**

> 最强证据是可验证契约与受测执行路径：在固定 48-case 语义套件中，合法误拒 0/24、不安全误放 0/24、错误字段定位 44/44，且 24 个 rejected case 均未到达 test-only 末端原语 dispatcher 调用点。23 例经 production gate function 测试路径提前返回，1 例在 Pydantic runtime contract 阶段前置拒绝。该结论只适用于冻结规则、冻结案例与受测执行路径，不是全称安全保证。其次是分层架构与明确的信任边界；治理用于保证这些数字没有被事后改写，但不排在技术贡献之前。
