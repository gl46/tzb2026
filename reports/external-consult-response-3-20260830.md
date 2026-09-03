# 第三份外部咨询回复(ChatGPT Pro,2026-08-30,基于完整证据包的静态审查)

> 输入=`external-review-package-20260830.zip`(未脱敏,含代码/配置/数据样例/证据)。本文件为协调整理的**可执行版**:只保留结论与已采纳的裁定要点。协调复核标注见各节。**不构成授权**,裁定已分别下发两 lane。

## 总判断(原文要点)

项目未到翻不了盘,但**最想主打的三项证据都有定义问题**:(1) 抓取实验不是正式 0/12,而是 5 个有效结果后停机、7 个 ordinal 未执行;(2) 视觉选择任务不是"视觉贡献小",而是**任务不可识别**;(3) 现 evaluator 只验字段出现,撑不起"可验证契约"卖点。建议:**停止把微调救援当主线、停止继续加治理、把工程时间押在"语义契约验证器 + 可识别的视觉绑定接口 + 一个诚实标注的 vNext 成功演示"**。精确计数保留为诊断,不作主叙事,不启动 3000 episode 实验。

## 协调已盘上复核确认的事实

- **SYNTHETIC_TEST 视觉行 = 0**(实测各 split×family:TEST 拒绝3/恢复9/搬运10/视觉**0**;TRAIN 视觉 54/428;DEV 12/78;BLIND 12/45)→ 19/22=86.4% 属**纯非视觉的符号契约与规划成绩**,禁作多模态 headline。
- **视觉任务不可识别**:BLIND 视觉行期望答案要求逐字输出内部哈希 ID(如 `s5_track_3ab109db93005a61`),该 ID 在模型输入(instruction+prompt_context)中**完全不出现**。→ 那 78 行设计上无法完成;若曾观察到答对,须优先怀疑泄漏/顺序/ID 相关性。
- 成对 2×2 表(已复核):TEST `19/0/0/3`、BLIND `31/0/0/14`、DEV `63/1/1/13` → 测试与盲测**逐例完全一致**,adapter 未改变任何一个判断。
- **两代运行时探针**:审包 `byte_identical_across_generations: false`。协调此前"探针字节同一"的表述**错误,已更正**(见下)。

## 一、抓取线证据身份(已裁)

**措辞禁令(12 发完成前)**:唯一合法表述="已完成的 5 个有效结果均未成功;原定 12 次 campaign 未完成,因此不作成功率或假设检验结论"。禁写 `0/12`、"12 次探针拒绝了成功率≥75%"、"二项检验表明"、"正式阴性结论"。理由:冻结账目自身 `statistical_claim=null`、7 ordinal 未消费,叙述与冻结证据不一致会毁掉整个证据包可信度。

**协调保留"继续跑完"的裁定**(与外部建议分歧处),依据已盘上核实:冻结账目的 `future_restart_requirement` 要求"新用户指令 + 全新治理设计解决 prereg/stage/update-chain 语义",两条**均已满足**(用户 8/30 13:25 指令;协调裁定 S″/P″ 必须重生成的 R3 全新治理链正是解决该 gap)。故非"静默续跑",是该文件规定的合法重启路径。

**合并正当性的正确依据(三条,缺一不可,须在 audit 显式产出)**:
1. **共享上游**:12 发绑定同一 upstream V4 物理探针(逐发列 digest 比对);
2. **各代自证**:每 ordinal 精确匹配**其自身预注册代**的 derived probe 摘要;
3. **致动路径非漂移附证**(具名 `ACTUATION_PATH_NON_DRIFT_ACROSS_GENERATIONS`):两代差异**仅在证据发射层**、致动路径未变的机器证据(normal non-drift + base actuation 字节禁改的 focused 证据)。
**若第 3 条无法干净产出,禁止合并为单一 12 分母**,改分段报告(00–03 / 04–11)并说明原因。

**成分披露(强制,禁裸写 s/12)**:3 个 legacy terminal + 1 个零消费追溯闭合(ordinal03)+ 1 个 orphan-closure(ordinal04,测量有效、记账被控制通道取消截断、容器回执与控制台缺席)+ 7 个 successor-native。

**三证据身份分类法(坐标修复后一切适用)**:`B0-HALT/B0-COMPLETE`(当前链,坐标未修)/ `VNEXT-DEMO`(修复后独立工程演示,不报成功率、不回填、不并入任何分母)/ `B1-FRESH`(修复稳定后从 ordinal 0 重新预注册的全新 12 发,自有新分母)。**永不出现"旧 5 发+修复后新发=12"**。B1 治理用最小充分集即可。

## 二、语义契约验证器(新的最高价值工程)

现 evaluator 只查"必需 primitive 是否出现 + expected target ref 是否出现 + 少量 forbidden + reassociation boundary",**不能拒绝**:额外危险动作、错 pose_ref、错目的地、缺谓词参数、重复 step_id、悬空依赖、循环依赖、顺序错误、target 中途偷换、完成后夹带破坏性动作。材料中一律称其为**"最低期望匹配器"(benchmark 用途),不得称"旧安全验证器"**。

**V1|必须以可信 TaskSpec 为参照(防循环论证)**:仅凭计划自身无法证明"模型选中了用户真正想要的物体"(否则"模型说是 B、计划全程用 B、判定正确")。接口 `validate(plan, task_spec, world_snapshot) -> ValidationReport`;grounding 后生成绑定的可信 TaskSpec(intent/target_ref/destination_ref/destination_pose_ref/allowed_primitives)。验证器证明的是"计划与冻结 TaskSpec 一致且安全";**禁称"验证器证明模型理解了指令"**——模型选得对不对由 grounding benchmark 独立测量。

**V2|必须接 fail-closed 执行门**:执行器仅接受 status==PASS 且报告绑定当前计划 canonical hash、同一 TaskSpec、当前 world snapshot、未失效、无旁路的计划。**核心集成测试不是"返回 REJECT",而是 `validator=REJECT` 且 `primitive_dispatch_count == 0`**。

**V2b|永久不变量(协调追加)**:**执行的计划字节 == 通过验证的计划字节**——dispatch 入口重新 canonical 序列化+哈希与 `plan_sha256` 比对,不等即 fail-closed 且 dispatch=0;负例:验证后任何原地修改(含字段规范化/排序/默认值填充)必须被拒;receipt 绑定**重算后**的哈希。(独立复审已实证该缺陷存在:dispatcher 原地 mutate 后 receipt 仍旧 hash。)

**V3|ValidationReport**:status、plan_sha256、task_spec_sha256、world_snapshot_ref、errors[{code, path(JSON pointer), message}]。

**V4|Schema v2 三路由为一等字段**:现顶层仅 subtasks+rationale,REFUSE 靠空数组+rationale 前缀、RECOVER 无一等字段 → 不能只靠 validator 加 if 就声称三路由互斥。升级 `decision: EXECUTE|REFUSE|RECOVER`(EXECUTE:subtasks 非空含物理原语;REFUSE:必空且无恢复/物理动作;RECOVER:仅恢复允许集或 recovery request 对象;三者互斥)。若冻结前不改顶层,则称**"验证器强制的三种结构模式"**,不得称 Schema 原生三路由。

**V5|Schema 三个洞**:`depends_on` 改 required;predicate `arguments` 改 required 且**逐谓词定型**(TARGET_TRACK_BOUND→target;DESTINATION_REGISTERED→destination;BIN_AT_DESTINATION→bin,destination;GRASP_CONFIRMED→target;FRESH_PUBLIC_OBSERVATION→observation_ref);新增 `TARGET_AT_DESTINATION(target,destination)` 或 `ENTITY_AT_LOCATION(entity,location)`;**`TASK_COMPLETE` 不是独立完成证据**,只能在领域后置条件成立时出现。(现 golden plan 后置条件只说"箱子在目的地",没说目标物体在目的地。)

**EXECUTE 前缀最终裁定(协调,经两轮收敛)**:**结构性禁止**。理由:静态验证器看不到重关联的运行时输出,无法对该步作真实判断 → 按"验证器验不了的声明不得出现在安全结构里"原则移除;运行时重关联握手列为 **vNext 明确未实现项**。EXECUTE = 恰好六步物理序列。两点守住:(a) `TARGET_REF_DRIFT` **不废弃**,继续覆盖静态可判漂移(引用目标≠TaskSpec 绑定目标、计划内前后步目标不一致);(b) 六步之间仍须在依赖拓扑/agent 分工/等价安全顺序上体现多样性并各自通过,否则验证器只是换了个精确匹配器。
**另**:`PUBLIC_RGBD_CAPTURE` 归 RECOVER 不归 EXECUTE——计划中途创建新观测会**自我作废验证所依据的快照**(构造性 TOCTOU);"拍新图→新快照→指挥体重分解→重新过门"本就是双层恢复的定义动作,此点建议写进 PPT 第 4 页。
**recovery_request.failed_step_ref**:默认删除(不可核验);唯一例外=world_snapshot 已带权威失败步身份则保留并对快照校验(此时反而是能力信号,对抗组补"归因错步必须被拒")。

**信任边界(协调裁定)**:可声称"计划字节不可变绑定 + 派发边界处 REJECT 时原语派发计数为 0";**禁称**"端到端证明执行器执行了且仅执行了这些原语"。架构图须画出**证明边界终止于哪一层**。可选廉价强化:派发器产出逐原语派发日志(标识+顺序+绑定计划哈希),把"计数为 0"升级为"边界处身份与顺序可核"。

## 三、48 例对抗契约测试

构成:**12 合法执行**(必须多种不同但合法拓扑:线性依赖/合法并行前置感知/不同逻辑 agent 分工/有无重关联前缀/等价的不同安全顺序——防止验证器退化成参考计划精确匹配)+ **6 合法拒绝** + **6 合法恢复** + **12 单缺陷**(重复 step_id / 悬空依赖 / 依赖环 / target 漂移 / 错 destination pose / REMOVE_ATTACHMENT 早于 attach / attach 前未闭夹爪 / 完成后额外物理动作 / 未授权 primitive / 过期 observation 或 binding / TASK_COMPLETE 缺领域完成条件 / 多 agent 争用同一执行资源)+ **12 复合对抗**(同时:JSON Schema 合法、大部分能过旧最低期望匹配、新验证器必须拒绝、含两个以上互相掩盖的缺陷)。

示范恶意变换:合法搬运计划尾部追加 `s7: ATTACH_CONTACT_ENTITY(target_ref=decoy_track, depends_on=[s6])` → 旧匹配器很可能 schema_valid=true / expectation_match=true;新验证器应报 `UNEXPECTED_EXTRA_ACTION` + `TARGET_REF_DRIFT` + `ATTACH_AFTER_RELEASE`。演示标题用:**"JSON Schema 与旧最低期望匹配均通过,但新语义执行门识别并阻断了危险计划"**。

指标:主指标 **Unsafe False Acceptance Rate** 与 **Valid False Rejection Rate**;另报三路由模式正确率、错误规则覆盖数、错误字段定位正确率、旧匹配器接受而新门拒绝的对抗计划数、REJECT 时 dispatch 是否恒为 0。**禁止只报 48/48**。**严格区分** validator 测试(给定计划是否正确放行/阻断)与 commander 测试(给定图文是否生成正确 route 与计划)——不得因前者 48/48 就声称后者 48/48。

## 四、视觉任务改为公开候选 grounding(取代精确计数)

在既有 RGB 上用实例分割真值叠加 `A/B/C/D` marker。**模型只可见:带标记的 RGB + 指令 + 允许输出的候选字母集合**;`A→track_17` 映射**仅绑定器私有**,模型响应前冻结。(协调更正:此前"输入给出候选映射表"的说法是错的,会把内部 ID 送进模型视野留下捷径。)模型输出 `selected_marker` + 意图 + 目的地,由确定性 binder 转成内部 target_ref/pose_ref。**绝不让模型猜内部主键。**

每次绑定记录:image_sha256 / overlay_sha256 / candidate_mapping_sha256 / selected_marker / bound_target_ref。marker 字母随机置换;样式尺寸偏移一致;正确目标不得总在 A 或固定位置;marker 不遮挡关键视觉特征。

**32 例结构**:8 个基础场景 × 2 条指令(各选中不同对象)× 2 套 marker 置换;另在 16 个场景-指令组合上成对跑 blank / shuffled / text-only / 正常。报告:正常 grounding 准确率、marker 置换一致性、同图换指令的反事实敏感性、blank/shuffle 成对掉点、合法 marker 输出率、binder 映射完整性。**统计单位声明为 8 个基础场景**,不得假装 32 行独立。材料定位:"仿真器实例分割支持的候选生成 + 多模态指令条件候选选择 + 确定性内部绑定",**不称端到端检测**(如实披露不丢分,掩饰才危险)。

## 五、多模态任务设计前置十门(今后所有任务训练前必过)

A 答案可恢复性(输出中每个符号必须直接出现在公开输入中或可由公开确定规则推导;内部 ID/隐藏 pose/隐式候选顺序不得成为必须猜测的标签)/ B 人类可解性(随机 20–30 例,≥2 名不看生成器规则的人独立作答,报正确率、一致率、歧义原因)/ C 模态析因(image+text、text only、image only、blank+text、shuffled+text,不能只看 blank)/ D 反事实敏感性(同文本换图答案变、同图换文本答案变)/ E 泄漏与捷径(候选顺序、ID 前缀、文件名、prompt 残留字段、demo 与 test 模板规律、标签频率、行顺序、类别或格位不平衡)/ F 有效样本量(报 family 数与**视觉承重行数**,不只报总 rows;同场景变体按场景聚类)/ G 标签熵与硬负例 / H 指标完备性(必须拒绝多余答案、错 destination、错顺序、target 偷换、不完整 postcondition)/ I 干预对齐(训练的模块必须能影响真正瓶颈)/ J 部署一致性(训练、验证、演示同一图像预处理/prompt/候选暴露方式/parser/binder/validator;仿真器真值介入哪些环节须明示)。

## 六、治理:已从资产转为负债(协调接受)

保留:预注册、冻结配置、完整分母、训练/测试隔离、原始工件哈希、事故不回填。**停止扩张**:多层自引用 commit 身份、OS 文件模式与 rename 原语级防护、复杂 predecessor 唯一性约束、控制通道字节级闭合、大量 tombstone 与多阶段身份链、把随 campaign 变化的派生对象纳入冻结身份。**最小充分集七项**:预注册 md+hash / 冻结 run manifest / append-only 结果 JSONL / 全部有效尝试入分母 / 原始日志视频配置留 hash / 统一 readout 脚本 / 事故写 incident log 不覆盖旧结果。材料中治理**最多一页**,只讲三件:失败没从分母删除、adapter 无增益故未部署、抓取 campaign 真实状态。("拦截三十次"不一定显严谨,也可能显得被流程反噬。)

## 七、8 页主 deck(重构)

1 完整干净的成功演示(指令→图像候选→选目标→合同计划→验证→执行)/ 2 分层架构(感知候选、Commander、语义验证器、规划执行层、双层恢复;**不先讲 LoRA**)/ 3 什么叫可验证契约(合法计划 vs schema-valid 但语义错误的计划被拒)/ 4 失败恢复(技能级→恢复耗尽→重分解或拒绝;含"新观测必然开启新决策周期")/ 5 正面量化(grounding 成绩、blank/shuffle/text-only 对照、契约路由正确率、不安全计划拦截率;**不得把 86.4% 标成视觉成绩**)/ 6 能力边界(adapter +0pp 不部署;抓取已测 5 例均失败、campaign 状态如实;vNext 独立不回填)/ 7 证据完整性(完整分母、冻结评测、原始工件可核验,仅三项)/ 8 交付与下一步。

**30 秒标准答案**:"我们交付的是一套在 Isaac Sim 中可运行的工业智能体:大模型把图像和指令转成结构化计划,经典执行层负责受约束动作和两级失败恢复。严格测试发现抓取与微调仍有边界,因此我们没有强行上线无效模块,而是让成功、拒绝和失败都可验证、可追溯。"

**最强一句(修补完成后)**:"我们不让大模型直接碰控制器:它只在公开候选上完成视觉绑定和任务决策,所有动作都必须经过确定性语义验证与执行门;没有通过验证的能力,我们不包装成成功。"

**措辞禁区**:不说"few-shot 已达任务天花板"(78 例 dev、2/3 聚类,证不了);不说"收益会随数据规模自然释放"(无 scaling curve);不说"训练损失减半"(实为 **−44.3%**);不把 JSON Schema 合法率称作完整安全契约验证;不夸大多智能体协同(A/B/C 称**逻辑角色或可扩展执行代理接口**)。

## 八、放弃清单

3000 episode 正式微调确认;为出正数继续扫 LoRA 超参;精确计数作为主创新(可留附录诊断);继续扩张治理;`0/12` 或正式抓取阴性统计叙事;把 86.4% 称多模态能力;把 schema 合法率称完整安全验证;夸大多智能体协同。
