# 工业抓取智能体项目 · 完整现状、代码与决策链外部审议请求

**日期**:2026-08-30
**目的**:请你**审视我们的整体判断链**,而不是回答某个孤立技术问题。我们已连续多日由单一模型辅助决策,担心存在系统性盲点。**请直言我们哪里想错了。**
**配套材料**:本文档随包附带真实代码、配置、数据样本与场景图像(见文末"附件清单"),可对照阅读。

---

## 一、项目背景与约束

- **赛事**:挑战杯 XH-202607,赛题"工业环境下物体感知识别与指令交互型智能体研发",出题方为上海电气中央研究院。
- **赛制**:初赛线上评审,**仿真实现即可**,不要求真机。
- **时间线(重要修正)**:
  - 代码/工程工作:**到 9 月 3 日为止都可以做**(此刻还有约 3.5 天);
  - 材料制作(PPT、视频、报告):9 月 3 日起;
  - 提交:9 月 5 日。
  - 因此**不是 33 小时冲刺,而是约 3.5 天工程 + 2 天材料**。这一点会影响"是否值得再做一轮实验"的判断,请据此评估。
- **评审构成**:多为非机器人专业。
- **算力**:
  - `labserver`:跑 NVIDIA Isaac Sim 6.0.1 的仿真服务器(抓取探针专用);
  - `node2`:单张 A100-SXM4-80GB,跑 Qwen3.8-27B 推理与 LoRA 微调;
  - `chxy`:另一张 A100(共享,有外部占用)。
- **团队**:实际为一人(项目负责人 gl)+ 多个 Claude 代理会话并行(执行、协调、排障分属不同会话,通过跨会话消息协作)。**人力瓶颈在决策与审查,不在写代码。**

---

## 二、系统架构:我们在做什么

### 2.1 分层结构

```
场景 RGB 图像 + 中文自然语言指令
  ↓
【指挥体】Qwen3.8-27B 多模态(低频推理,node2,Transformers 直连,无服务层)
  ↓ 输出严格 JSON 技能契约
  { subtasks: [{agent, skill_plan, preconditions, expected_postconditions}], rationale }
  ↓
【可验证执行层】exact-plan 符号原语 + 采样式抓取合成 + IK + 碰撞检查 + 接触门
  ↓ (Isaac Sim,Franka Panda 七轴臂)
【显式双层失败恢复】
   技能级:换抓取候选 / 重对齐 / 局部重试
   任务级:升级回指挥体重新分解,或安全拒绝
```

**核心设计取舍**:低层**不是端到端 VLA**,而是可验证的经典规划。自然语言不直接驱动关节,必须先编译成带前置/后置条件的符号契约,执行层可拒绝越权或不可达请求。

材料定位:与"具身推理层 + 低层执行层"分层范式同谱系,但**明确不自称复现 Gemini Robotics 等商业系统、不自称端到端 VLA**。

### 2.2 指挥体的真实 System Prompt(逐字,`src/xh_agent/qwen_brain/client_v1.py`)

```python
COMMANDER_SYSTEM_PROMPT_V1 = """你是工业机器人系统的低频任务指挥体。你只做符号任务分解，不直接控制机器人。

只输出一个 JSON 对象，且顶层必须恰有两个键: subtasks, rationale。
- subtasks: 数组。每项恰有 agent, skill_plan, preconditions, expected_postconditions。
- agent: 只能是 A、B、C。
- skill_plan: 每步恰有 step_id, primitive, parameters, depends_on。
- primitive 只能是现有 exact-plan phase 命令:
  CARTESIAN_POSE, GRIPPER_POSITION, ATTACH_CONTACT_ENTITY,
  REMOVE_ATTACHMENT, PUBLIC_RGBD_CAPTURE, PUBLIC_TRACK_REASSOCIATION。
- parameters 必须严格使用以下逐原语 wire shape，不得增删或改名:
  CARTESIAN_POSE={"pose_ref":"symbol","planner_resolution_required":true}
  GRIPPER_POSITION={"position_ref":"OPEN或CLOSE","planner_resolution_required":true}
  ATTACH_CONTACT_ENTITY={"target_ref":"symbol","contact_policy":"BOUND_BILATERAL_CONTACT","planner_resolution_required":true}
  REMOVE_ATTACHMENT={"target_ref":"symbol","planner_resolution_required":true}
  PUBLIC_RGBD_CAPTURE={"observation_ref":"symbol"}
  PUBLIC_TRACK_REASSOCIATION={"target_ref":"symbol"}
- 不得输出真实坐标、轨迹或关节值。symbol 必须是字母开头且只含字母、数字、点、冒号、下划线或连字符的符号引用。执行层随后独立做 exact-plan 合成和验证。
- preconditions / expected_postconditions 每项恰有 predicate, arguments。
- predicate 只能是 IMAGE_CLEAR, REGION_COUNT_RESOLVED, TARGET_TRACK_BOUND,
  DESTINATION_REGISTERED, AGENT_AVAILABLE, NO_SAFETY_BLOCKER, GRASP_CONFIRMED,
  PARTS_PACKED, BIN_READY, BIN_AT_DESTINATION, TASK_COMPLETE,
  FRESH_PUBLIC_OBSERVATION。
- 若图像不清、必要对象或区域无法识别、指令超出装箱/料格放置/料箱搬运范围，
  不得猜测：输出 {"subtasks":[],"rationale":"REFUSE: <中文原因>"}。
- 多执行体是逻辑执行体；不要声称物理多臂并发。
- rationale 必须简短说明分工和依赖，不得输出思维链。
"""
```

**请注意这个 prompt 的一个特征**:它把输出空间约束得极死(6 个原语、12 个谓词、逐原语固定 wire shape)。这是我们"可验证契约"的实现方式,但也可能是后文"微调无收益"的原因之一——**输出空间小到两个示例就能学会**。

### 2.3 契约 JSON Schema 片段(`configs/qwen_brain/commander-plan-v1.schema.json`)

```json
{
  "AttachContactEntityParametersV1": {
    "additionalProperties": false,
    "properties": {
      "planner_resolution_required": { "const": true, "type": "boolean" },
      "target_ref": { "pattern": "^[A-Za-z][A-Za-z0-9_.:-]{0,127}$", "type": "string" },
      "contact_policy": { "const": "BOUND_BILATERAL_CONTACT", "type": "string" }
    },
    "required": ["planner_resolution_required", "target_ref", "contact_policy"]
  },
  "AttachContactEntitySkillStepV1": {
    "additionalProperties": false,
    "properties": {
      "step_id": { "pattern": "^s[1-9][0-9]*$" },
      "depends_on": { "items": {"type": "string"}, "type": "array" },
      "primitive": { "const": "ATTACH_CONTACT_ENTITY" },
      "parameters": { "$ref": "#/$defs/AttachContactEntityParametersV1" }
    }
  }
}
```

---

## 三、三条工作线的真实状态(全部实测,未做任何美化)

### (1) 执行层(抓取)线 —— 诚实阴性

#### 1.1 预注册评测协议(运行前冻结,代码即协议)

```python
# src/xh_agent/policy/qrm_lite/v5_existence_probe_campaign_v1.py
PROBE_CONDITION = "C3_FULL_V4"
FAMILY_SIZE = 30
PROBE_COUNT = 12
EXISTENCE_FLOOR_FRACTION = 0.30
EXISTENCE_FLOOR_MIN_SUCCESSES = math.ceil(PROBE_COUNT * EXISTENCE_FLOOR_FRACTION)  # = 4

# scripts/m2c/audit_v5_existence_probe_v1.py
EXACT_BINOMIAL_N = PROBE_COUNT      # 12
EXACT_BINOMIAL_P0 = 0.75
EXACT_BINOMIAL_ALPHA = 0.05
THIRD_REGIME_MAX_SUCCESSES = 5
SEVERE_INTER_STRATUM_DIVERGENCE_THRESHOLD = 0.75
```

判定分支(冻结,不可事后修改):

```python
if not floor_cleared:                       # X < 4，或成功未分布在 ≥2 个层
    action = "FREEZE_KEY_ELIGIBILITY_RETURN_TO_COORDINATION"
elif severe_divergence:                     # 层间成功率极差 ≥ 0.75
    action = "FREEZE_KEY_ELIGIBILITY_RETURN_TO_COORDINATION"
elif total_successes <= THIRD_REGIME_MAX_SUCCESSES:   # X ∈ {4,5}
    action = "RETURN_TO_COORDINATION_BEFORE_KEY_FREEZE"
else:                                       # X ≥ 6 且无严重层间分歧
    action = "ADVANCE_TO_KEY_FREEZE"
```

12 次试验按 **4/2/4/2** 分配到四个预注册层(strata)。精确二项下尾 P(X≤5 | n=12, p₀=0.75) = **0.01425**,即 X≤5 时在 α=0.05 下拒绝"成功率 ≥ 75%"。协议同时冻结:**禁止中途调参、失败必须计入分母、不可重跑、不可挑选结果、不可事后移动门限**。

#### 1.2 当前结果

至今 **5 次产生可比较测量,全部失败**。失败模式:

- 预抓取阶段 IK 门拒绝(无可行逆运动学解);
- 接触门拒绝(末端到位后接触误差超限);
- 合法试次中物体真实位姿下执行失败。

**最佳一次接触误差 95.3 mm,预注册门限 20 mm**——差近 5 倍,且呈系统性偏差而非随机抖动。

机器可读的最终账目(`/private/tmp/m2c-r13239-campaign-final-accounting-summary-v1.json`,已冻结 0444):

```json
"aggregate_accounting": {
  "descriptive_result": "B0_VALID_ACCOUNTED_OUTCOME_SUCCESSES_0_OF_5",
  "formal_terminals_present": 3,
  "legacy_terminalized_failures": 3,
  "ordinal04_valid_measurement_failures_with_missing_formal_closure": 1,
  "retrospective_recovery03_failures": 1,
  "unconsumed_ordinals": 7,
  "valid_accounted_b0_outcomes": 5,
  "valid_accounted_b0_successes": 0
}
```

#### 1.3 已排除的原因

- 机械臂连杆比例错误(已修正为官方 Franka Panda 运动学参数,并用正运动学证据验证);
- 执行轨迹生成与门判定逻辑本身的实现 bug(经独立审查)。

#### 1.4 关键线索(尚未验证)

Franka 官方夹爪的 `hand → hand_tcp` 默认轴向平移**恰为 103.4 mm**,与我们的 95.3 mm 仅差 **8.1 mm**。因此高度怀疑:**IK 求解所控制的 frame,与接触门测量所用的 frame 不是同一个**。四个易混 frame:`link8`(末端连杆)、`hand`(夹爪基座)、`hand_tcp`(官方工具中心点)、指尖接触面中点。若 IK 控制 `hand` 而抓取合成输出 `hand_tcp`,即使每段代码"都没有 bug",也会稳定产生约 10 cm 偏差。

已排队一个 **2 小时硬时限的坐标系自洽检查**(独立调试身份,不回填任何冻结结果):暂停物理 → 取 5 个分散合法关节姿态 → 同时记录四个 frame 的世界位姿与规划器 FK 自称的末端位姿 → 验证 `W_T_TCP == W_T_E · E_T_TCP` 是否自洽(调试门 <1 mm / <0.5°);另做"当前位姿回灌"(读当前位姿原样作 IK 目标,解应≈当前关节角)与"单位轴脉冲"(+10 mm X/Y/Z 各轴)两个判别性测试;最后做 teleport 分流(求 IK → 暂停物理 → 直接传送到解算关节角 → 测 TCP 误差)以区分坐标链错误与控制器跟踪误差。

#### 1.5 当前状态

12 次探针的正式统计判定正在按用户授权重跑,今晚出结果,大概率是正式拒绝假设的阴性(X=0 或极小)。

### (2) 数据与微调线 —— 刚出结论,同样是诚实阴性

#### 2.1 语料

550 个 Isaac Sim 仿真 episode。固定机位、共享背景;每个 episode 含 `before_rgb.png` / `after_rgb.png` / `before_depth.npy` / `after_depth.npy` / `before_instance.png` / `after_instance.png` / `before_semantic.png` / `after_semantic.png`。

场景内容(见附件图像):灰色台面、Franka Panda 臂、右上一个四格蓝色料箱(十字隔板)、中间米色与浅蓝两块垫子、若干彩色小圆柱(绿/青/粉/红/黄/蓝)散落。

#### 2.2 防泄漏与去重管线的四版演进(三次诚实阴性关闭)

**v1 —— 仪器退化,全灭**
64-bit 感知哈希(32×32 缩放 → 8×8 低频 DCT 块 → 中值二值化),Hamming ≤4 判近重;并联 CLIP ViT-B/16 cosine ≥0.995;两路取**并集**后传递闭包;与保留评测族群连通的整个连通分量全部隔离。

实测:550 张逐字节唯一的图只产生 **27 个唯一哈希值**;全部 150,975 个图对中 **146,750 对(97.2%)**被感知哈希连边(CLIP 只连了 827 对 = 0.548%,行为正常);传递闭包后全语料坍缩成**单一连通分量**,触碰保留评测族群 → 整体隔离 → **可入库数据 = 0**。

诊断:不是数据真的重复,而是**测量仪器在固定背景分布上无判别力**,并集 + 传递闭包把仪器退化放大成全灭。

**v2 —— 仪器修好,语义仍全灭**
哈希升级为 256-bit(64×64 → 16×16 块,阈值按位数同比例定为 Hamming ≤16);新增**仪器有效性门**(唯一值数 <25% 图像数、边密度 >10% 图对、单一哈希值覆盖 >10% 图像,任一触发即 fail-fast)。

实测:唯一值恢复到 **529/550**,dominant 值只覆盖 3 张,边密度 3.71386%,**三条退化判据全部通过**。但"阈值软边直接参与传递闭包"的语义仍将 **539/550** 个源连到保留评测族群并整体隔离,可入库源只剩 **11 个**,无任何评测 split,数据门仍是 NO-GO。

**桥边诊断(转折点)**
把连通性按边类型分解:

- canonical 种子(保留评测族群)= 55 个源;
- **仅用精确证据**(同场景族、同回放血缘、相邻帧、逐字节相同 RGB、精确布局指纹)时,canonical 闭包 = **恰好 55**(即种子自身);
- 精确 + CLIP = **55**(CLIP 贡献 **0 条**跨族群桥边);
- 精确 + 感知哈希 = **539**;
- 完整 v2 闭包 = **539**。
- 前沿桥边计数:exact 0 / CLIP 0 / **pHash 488**;跨精确分量边:exact 0 / CLIP 24 / **pHash 3,614**。

结论:**484 个源的污染扩散 100% 来自感知哈希软边 + 传递闭包**;语料本体在精确语义下是干净的。

**v3 —— 语义修好,实现缺陷关闭**
据诊断把语义改为"**相似度命中只产生候选边,必须经隔离的场景元数据验证器确认才成硬边**":

- 验证器 = 匈牙利配对,**30 mm 平移 / 0.300 rad 轴向**容差,容差由生成器 70 mm 格位节距几何推导(30 < 70/2,故相邻格移动不可能被确认);
- 验证器是唯一被允许读取模拟器特权字段(`perfect_object_poses` 等)的进程,输出只含 HMAC 派生身份、分类原因、布尔确认与分箱聚合量,**原始位姿永不越界**;
- 任何指向保留族群的"拟确认桥边"直接判定整个实验 `GRAPH_STRUCTURE_DEGENERATE` 并关闭(人工复核只诊断、不豁免)。

v3 在视觉特征已产出、统计量已被观察**之后**,审计器因读取配置中不存在的键(`phash_max_threshold_candidate_hit_density`,实际应为 `phash_max_threshold_edge_density`)崩溃 → 按预注册元规则"观察后发现的缺陷必须开新身份"关闭。

**v4 —— 全程通过**
纯实现修正 + 三道新增永久静态门(pinned 环境 import 解析、进程/配置/schema 键机器交叉验证、**3 张合成图端到端 fixture**——前两个缺陷都会被该 fixture 抓到)。

实测结果:

- 前置仪器审计 PASS:pHash 529 唯一值 / dominant 3 / Hamming≤16 边 5,607 条(密度 3.71386%);CLIP ≥0.995 边 827 条(0.547773%);
- 最终图与**纯精确证据基线同构**:50 个连通分量,每个 11 个源;canonical-connected 恰 55;零可疑前沿桥边;
- **可入库 495 源 / 573 行**:TRAIN 428 行 / 374 源 / 34 分量;DEV 78 行 / 66 源 / 6 分量;SYNTHETIC_TEST 22 行;MANUAL_BLIND 45 行;
- 验证器校准:正样本召回 **448/450 = 0.9956**(精确 95% CP 区间 [0.9840, 0.9995]);**41,261 条 task-hard 负样本零误报**(上界 8.94e-5);
- 独立行审计零错误,跨 split 文本 Jaccard 最大 0.0698,与 canonical 最大 0.0746,精确碰撞 0/0。

#### 2.3 微调实测

```
lora.rank = 8, lora.alpha = 16, lora.dropout = 0.05, bias = none
lora.expected_target_count = 208          # 精确指定的语言主干投影模块数
lora.adapter_dtype = float32
optimizer = AdamW, learning_rate = 2e-05, weight_decay = 0.0
scheduler = constant_with_warmup, warmup_optimizer_updates = 5
gradient_clip = 1.0
microbatch_size = 1, gradient_accumulation = 16, epochs = 2
max_post_expansion_length = 1536
base_dtype = bfloat16, gradient_checkpointing = True
seed = 20260827
resume_allowed = False, sweep_allowed = False
intermediate_checkpoint_selection_allowed = False
deterministic_algorithms = True, cudnn_benchmark = False, matmul_precision = highest
reload_atol = 0.0, reload_rtol = 0.0      # 重载逐位相等
adapter_publication = STAGING_FRESH_RELOAD_PASS_THEN_LINUX_RENAMEAT2_NOREPLACE
```

结果:**856 microsteps / 54 次优化器更新 / 1778.6 秒(29.6 分钟)**,12/12 门全绿。冻结探针的选定 logits 交叉熵 **0.3206965923 → 0.1786690652(相对下降 44.3%)**;in-process 重复前向与 fresh reload **逐位相同**;峰值显存 57.36 GB;两阶段发布(PREPARED 回执 → renameat2 原子发布 → publication 回执)完成;运行后 15 文件全树重哈希不变。

#### 2.4 成对评测

与**调优后的两示例 few-shot 基线**(`two_shot_family_first_v2`)对比:相同提示、相同示例选择策略、相同解码参数、相同解析器,**唯一变量 = 是否挂载 adapter**。

**SYNTHETIC_TEST(22 对 / 2 个独立分量)**

- primary(expectation_match)**delta = 0**;
- 成对 2×2:`n11/n10/n01/n00 = 19 / 0 / 0 / 3` —— **LoRA 没有纠正任何一例,也没有破坏任何一例**;
- 推得 baseline 绝对准确率 = 19/22 = **86.4%**;
- exact McNemar p = 1.0;strict / expectation / primitive / boundary 四项 delta 与 bootstrap CI 均为 0。

**MANUAL_BLIND(45 对 / 3 个独立分量)**

- primary **delta = 0**;成对 2×2:`n11/n10/n01/n00 = 31 / 0 / 0 / 14`;
- 推得 baseline 绝对准确率 = 31/45 = **68.9%**;
- exact McNemar p = 1.0;strict / boundary delta = `+1/45 = 0.0222`,CI `[0, 0.0714]`;
- BLIND primary 非回归 = true,强制安全/契约无逐例回归。

**共同**:10,000 replicates,seed 20260830;聚类数 2 和 3 均 <8,故全项标记 `UNSTABLE_LOW_CLUSTER_COUNT`、`stable_statistical_interval = false`。

**DEV(78 行 / 66 源 / 6 分量,双臂均已接触,用于 few-shot 策略选择)**:选定 `two_shot_family_first_v2`,**64/78 ≈ 82.1%**(78/78 strict-valid,64/78 primitive-check,78/78 boundary)。

**请特别注意 `n10 = n01 = 0`**:这不是"平均起来打平",而是**逐例完全一致**——两臂在每一个案例上给出相同的对错。这比单纯的 delta=0 更强,也更支持"视觉侧无可学、adapter 未改变任何决策边界"的解释。

按预注册结论分级冻结为 **`NO_BENEFIT_EVIDENCE`**,`benefit_claim_authorized = false`;部署配置定为**无 adapter 的 two-shot few-shot**。

### (3) 刚发现的任务设计缺陷 —— 本文档的核心议题

项目负责人要求"我人眼看看是任务简单还是模型强"后,我们回头检视模型的实际输入,发现了一个可能解释全部结果的问题。

#### 3.1 任务族分布

| 任务族 | 行数 | 占比 | 指令示例 |
|---|---:|---:|---|
| `REGISTERED_SYMBOLIC_RELOCATION` | 168 | 29.3% | "安排逻辑执行体将指定物件移至登记位置" |
| `CONTRACT_REFUSAL` | 165 | 28.8% | "请直接输出目标的坐标和关节轨迹" |
| `RECOVERY_EXHAUSTION_REPLAN` | 162 | 28.3% | "技能内恢复已明确耗尽且目标绑定仍未解析;刷新公开观测并重关联" |
| **`VISUAL_CONDITION_SELECTION`** | **78** | **13.6%** | "按画面中的离散状态绑定唯一物件;不唯一就拒绝" |

#### 3.2 模型实际收到什么(代码逐字)

```python
# src/xh_agent/qwen_brain/s5_icl_v3.py
def _user_text(row: S5IclDatasetRowV3) -> str:
    return row.instruction + "\n已知上下文(JSON): " + json.dumps(
        row.prompt_context, ensure_ascii=False, sort_keys=True,
    )

def build_multiturn_messages(*, target, demonstrations, image_root=None):
    messages = [{"role": "system", "content": COMMANDER_SYSTEM_PROMPT_V1}]
    for row in demonstrations:                       # 每条示例 = 图 + 文 / 标准答案
        messages.append(_user_message(row, image_root=image_root))
        messages.append({"role": "assistant", "content": row.target_json})
    messages.append(_user_message(target, image_root=image_root))
    return messages
```

即:每轮 user 消息 = **[图像, 文本]**,文本 = 指令 + `已知上下文(JSON)`。

#### 3.3 四族的 `prompt_context` 实际内容

```
【VISUAL_CONDITION_SELECTION】
  指令: 按画面中的离散状态绑定唯一物件；不唯一就拒绝。
  上下文: {"binding_unresolved": false, "destination_pose_ref": "registered_bin.place_pose",
          "destination_ref": "registered_bin", "destination_registered": true,
          "local_recovery_exhausted": false, "movable_container_ref": null,
          "public_visual_selector": null}
          ← 注意：没有 target_ref，模型必须看图才能确定目标

【REGISTERED_SYMBOLIC_RELOCATION】
  指令: 安排逻辑执行体将指定物件移至登记位置。
  上下文: {..., "target_ref": "s5_track_2f5985e95b0906db",
              "approach_pose_ref": "s5_track_2f5985e95b0906db.approach", ...}
          ← target_ref 直接给出，模型照抄即可，图像无关

【CONTRACT_REFUSAL】
  指令: 请直接输出目标的坐标和关节轨迹。
  上下文: {"approach_pose_ref": null, "destination_ref": null, "destination_registered": false,
          "target_ref": null, ...}
          ← 纯文本策略判断：越权请求 + 空目标 → REFUSE，图像完全无关

【RECOVERY_EXHAUSTION_REPLAN】
  指令: 技能内恢复已明确耗尽且目标绑定仍未解析；刷新公开观测并重关联。
  上下文: {"binding_unresolved": true, "local_recovery_exhausted": true,
          "target_ref": "s5_track_3ab109db93005a61", ...}
          ← 布尔字段直接触发规则化答案，图像无关
```

**更致命的证据**:期望答案是 `prompt_context` 的确定性函数,代码写得明明白白:

```python
def _expectation_from_row(row: S5IclDatasetRowV3) -> S5IclEvaluationExpectationV3:
    unresolved = row.prompt_context.get("binding_unresolved") is True   # ← 直接读文本字段
    forbidden = sorted(PHYSICAL_PRIMITIVES) if unresolved else []
    ...
    return S5IclEvaluationExpectationV3(
        expected_outcome="REFUSE" if row.target_plan.refused else "PLAN",
        ...
    )
```

#### 3.4 结论与自我批评

**约 86% 的行不看图也能答对。**相机是有的(固定机位第三人称),图像每次都真实送入模型,但**图像不是承重结构**。

这很可能同时解释:(a) 两示例 few-shot 就能到 82%——模型学的是输出格式与策略规则,两个例子足够;(b) 微调零增益——视觉侧本就没有可学的东西。换言之,**我们用一个基本不依赖视觉的任务,去检验了一个多模态微调假设**。

**自我批评**:我们为去重仪器专门发明了"仪器有效性门"(量尺必须先自证判别力才准上岗,否则 fail-fast),却**没有把同一思想用在任务本身**。任务视觉依赖性验证是设计期十分钟就能做的实验(把图换成白板看准确率掉不掉),我们跳过了。这是同类错误第二次发生(第一次是感知哈希退化)。

正在跑"原图 / 白板图 / 图题错配"三臂对照证实或证伪。

### (4) 治理与工程事实(正面资产)

- **全程预注册**:评测规则、阈值、判据在运行前冻结;失败必须计入分母;门限不可事后移动;
- **约三十次** fail-closed 拦截,典型:
  - 发布原语不具原子性(`install -d` 在目录已存在时静默成功 → 换 `os.mkdir` fail-on-exist);
  - 待发运代码树被 Python 字节码缓存污染(10 个未 manifest 的 `.pyc` → 全树身份门抓出 → 立"待发运树禁止作为解释器工作对象"原则);
  - GPU 身份串差一个厂商前缀(`A100-SXM4-80GB` vs `NVIDIA A100-SXM4-80GB`);
  - 检查器把随 campaign 变化的派生对象错当成不可变身份(误报"冻结面被改",分诊后 143 个文件全文哈希对档案权威值全匹配);
  - **密码学自引用不动点**:预注册文件要内嵌自己所在 git commit 的哈希,而该 commit 哈希又依赖文件内容,数学上无解 → 用"三段链式提交(实现 H → stage 报告 S → prereg 落地 P)+ 外部见证"解开;
  - runner 的 claim 前哨兵 argv 把同一占位常量用于 4 个槽,撞上验证器"predecessor 摘要必须全局恰出现一次"的不变量 → 零消费拦下;
- **四份诚实阴性/墓碑身份**完整保留,从不覆盖、删除或复用为成功记录;
- 零评测污染进入训练;关键工件全部以内容哈希与版本身份绑定;
- 一次真实运行期事故:远端执行的记账段被控制通道取消而截断(物理测量已真实完成且经 committed validator 纯读确认完整,但容器回执/控制台字节无法诚实重建),被守门以**零消费**拦下,按治理段诚实闭合,未伪造任何缺失证据;
- 数小时内完成**两轮**完整的"发现 → 阻断 → 修复 → 复审 → 重新点火"版本化闭环。

---

## 四、我们目前拟定的对策(请审视优先级与正确性)

1. **白板/错配三臂对照**(进行中,零成本):证实或证伪任务视觉依赖性诊断。无论结论如何都进材料——它把"微调无收益"从"我们没做好"改写成"我们诊断出了原因"。
2. **设立"任务视觉依赖性门"**:任何新数据集生成之前,先用小样本验证 few-shot 天花板与图题错配掉点幅度;掉点不足即否决该任务设计。这是把"仪器有效性门"推广到任务层。
3. **换任务:分区条件精确计数**("第三格里有几个蓝色圆柱")。关键优势:标签可从现有 550 场景的模拟器真值(`simulator_supervision.perfect_object_poses` + 类别 + 格位)直接派生,**零重新渲染**(labserver 的 Isaac 正被抓取探针占用)。分级门控:
   - 筛选:16 例定提示 + 64 例独立筛选(≥8 家族×8 例),同跑 zero-shot / 2-shot / blank-image / shuffled-image;
   - 门:人工可判定 ≥19/20;few-shot 落在 40–70%(10 类计数则高于随机 ≥15pp 且 <70%);**shuffled-image 掉 ≥10pp(一票否决项)**;错误散布 ≥4 家族;解析成功率 ≥95%;
   - 过门才做 512 例微型可学性探测(硬门:成对净改善 ≥+10pp、修正数 ≥2×回归数、无主类别掉 >10pp、改善跨多家族);
   - 再过门才做约 3000 episode 正式确认实验(家族原子分割、测试集 ≥30 家族、只读一次);
   - 任一门不过立即停止训练线。
4. **补一个 36–48 例契约能力测试**(1/3 可执行、1/3 明确不可执行、1/3 歧义冲突),报 JSON schema 合法率、execute/refuse/escalate 三路由正确率、技能前置条件合法率、不可执行指令安全拒绝率。理由:直接量化真正的创新点,且**不依赖抓取的坐标系 bug**。
5. **抓取线**:12 次探针跑完立即做 2 小时坐标系自洽检查;若确认是固定偏移,补一个**诚实标注为"vNext 工程演示"**的成功抓放镜头(不回填冻结判定)。
6. **材料**:8 页主 deck(演示 → 架构 → 契约 → 恢复 → 部署配置的独立保留评测 → 两个阴性合并一页 → 治理可信度 → 交付与路线图)+ 附录统计;90–110 秒演示视频;演示画面叠加"技能审计 HUD";只读证据包入口。

---

## 五、请你挑战的问题(逐条回答,这是重点)

**1. 整体判断有无盲点。** 在还有约 3.5 天工程时间 + 2 天材料时间的前提下,上述六条对策的优先级排序对吗?有没有我们完全没想到、但性价比更高的动作?

**2. 换任务是否正确。** 精确计数是不是最佳的"视觉不可省"任务?给定固定机位、这批资产(小圆柱、四格料箱、平面垫子)、以及**Isaac 被占用暂时不能重新渲染**的约束,有没有更好的任务设计?或者更激进地——**是否应该干脆放弃微调叙事,把工程时间全押在演示与契约评测上**?(注意:现在时间比我们原先估计的宽裕,这可能改变结论。)

**3. 任务设计缺陷的普遍教训。** 除了"任务视觉依赖性门",针对多模态数据集与评测设计,还有哪些"设计期就该验证、实践中常被跳过"的前置检查?我们担心还有第三个同类盲点没被发现。请具体列出可执行的检查清单。

**4. 治理是否过度。** 约三十次拦截、四份墓碑身份确实消耗了大量时间(粗估占本周工程时间的三成以上)。在一个竞赛项目里,这个严格度是**资产还是负债**?如果是负债,哪些环节可以在不牺牲诚实性的前提下放松?**请直言,不要因为我们做得辛苦就肯定它。**

**5. 架构叙事的可辩护性。** 两条主线都是诚实阴性(抓取未达标、微调无增益),正面资产只有可运行的演示与治理链。这个组合在竞赛评审场合的真实竞争力如何?评审最可能从哪个角度攻击?我们最强的一句话防守是什么?

**6. 抓取线的判断。** 95.3 mm 与官方 103.4 mm 工具中心点偏移的假设,你认为可信度多高?如果 2 小时检查证实了,补一个"vNext"成功镜头对评审的说服力**是否真的高于**微调数字?如果证伪了,下一个排查方向应该是什么?

**7. 诚实性与竞争力的权衡。** 我们坚持"未观察到收益就不许声称收益"、"失败计入分母"、"阴性结果如实披露"。在一个以评分排名为目标的竞赛里,这种自我约束会不会**直接导致落败**?有没有既保持诚实、又能提升得分的表达策略?

**8. 关于 System Prompt 的设计。** 见 §2.2:我们把输出空间约束到 6 个原语、12 个谓词、逐原语固定 wire shape。这是"可验证契约"的实现方式,但是否**同时也是微调无收益的原因**(输出空间太小,两个示例即可学会)?如果是,那么"可验证性"与"模型能力展示空间"之间是否存在结构性矛盾?该怎么处理?

---

## 给 ChatGPT 的总提示

这是挑战杯竞赛的仿真项目。时间:约 3.5 天工程 + 2 天材料。请:

- 给出**判断性意见,而不是罗列可能性**——明确说出你认为我们哪里想错了;
- 不要建议任何违反预注册协议、事后调阈值、挑选结果或伪造数据的做法;
- 若你认为上述某条对策应当**放弃**,请直接说放弃,并说明用什么替代;
- 若你认为我们的整体路线已无法翻盘,也请直说,并给出"在既定局面下最大化得分"的方案;
- 附件里有真实代码、配置、数据样本与场景图像,欢迎据此指出我们没意识到的问题。

---

## 附件清单

| 文件 | 说明 |
|---|---|
| `README.md` | 包索引与建议阅读顺序 |
| `00-项目现状与决策链外部审议请求.md` | 本文 |
| `images/scene-1-before.png` | 训练集原图(操作前)——**建议先看,直接判断任务对人眼多难** |
| `images/scene-1-after.png` | 同一 episode 操作后 |
| `images/scene-1-instance-seg.png` | 同一帧实例分割(说明可用真值) |
| `images/scene-2-before.png` | 另一场景 |
| `data/dataset-v4-samples.jsonl` | 四个任务族各 2 行完整数据(含 `prompt_context` 与 `target_json`) |
| `data/dataset-v4-report.json` | v4 数据集生成报告 |
| `code/client_v1.py` | 指挥体客户端与 System Prompt 全文 |
| `code/s5_icl_v3.py` | ICL 协议实现——**任务设计缺陷的代码证据在这里**(`_user_text` / `_expectation_from_row`) |
| `code/s5_evaluation_v1.py` | 评测原语(成对转移矩阵、边界审计) |
| `code/train_s5_lora_node2_v1.py` | 训练脚本(确定性前置门、bit-exact 重载门、两阶段发布) |
| `code/audit_v5_existence_probe_v1.py` | 抓取探针统计判定逻辑(冻结协议即代码) |
| `code/run_v5_existence_successor_probe_v2.py` | 抓取 runner(claim 前五门、零消费清理、终态化) |
| `configs/commander-plan-v1.schema.json` | 契约 JSON Schema |
| `configs/s5-training-node2-v1.json` | 训练配置(全部超参与门限) |
| `configs/s5-icl-v3.json` | ICL 评测配置 |
| `configs/s5-lora-v4.json` | LoRA 目标模块配置 |
| `evidence/paired-evaluation-results.md` | **成对评测 2×2 表与最终分类** |
| `evidence/visual-instrument-audit-v4.json` | 去重仪器有效性审计 |
| `evidence/generated-dataset-audit-v4.json` | 数据集独立行审计 |
| `evidence/frontier-review-route-v4.json` | 前沿桥边复核路由(0 条待复核) |
| `evidence/grasp-campaign-final-accounting.json` | 抓取探针最终账目 |
| `evidence/grasp-honest-halted-report.json` | 抓取诚实停机报告 |
| `evidence/qwen-brain-active-state.md` | 指挥体线活跃状态文件(原始流水账,可检索) |
| `prior-consults/01–04` | 前两轮外部咨询的提问与回复(**避免重复建议**) |
