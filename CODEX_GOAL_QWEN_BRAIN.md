# GOAL QWEN-BRAIN:双系统指挥体(Qwen3.8-27B VL)+ 层级多智能体演示线

你是 XH-202607 项目的演示与材料研发代理。请直接执行工程任务,不要只输出建议或规划。

本 Goal 与 M2C 存在性探针主线**并行且严格隔离**,在 9/1 代码冻结前建成比赛材料需要的"聪明大脑"演示线:

```text
Qwen3.8-27B 多模态指挥体(看图 + 听指令,node2 A100 推理)
→ 任务分解 JSON(绑定 exact-plan 技能原语)
→ 多智能体分配(装箱体 A / 装箱体 B / 搬运体 C,动态重分配)
→ 执行体失败报告 → 指挥体重分解(升级链)
→ 演示视频素材 + 技术报告章节草稿
```

架构叙事(报告用词,必须准确):**与 Gemini Robotics 1.5 同构的双系统/层级架构**——大模型指挥体(≤低频推理)+ 可验证执行层;执行层用符号契约(exact-plan)+ 经典规划替代黑箱 VLA,失败恢复为显式双层(执行层 FC 局部恢复 → 指挥体重分解)。**永远不要自称端到端 VLA,不要声称复现 Gemini Robotics。**

如果某一步受阻:

1. 先联网检索官方文档、官方仓库、上游 issue;
2. 可以安装缺失的 pip/apt 依赖(vLLM、transformers 等);
3. 可以换更兼容的推理框架,但必须记录理由和版本;
4. 单个问题约 60–90 分钟无实质进展时,切换实现路径并保留证据;
5. 不得伪造模型输出、GPU 运行或演示结果;
6. 只有凭据、不可逆系统操作或明确人类决策才停下报告。

---

## 0. 硬边界(违反任何一条立即停止并报告)

1. **绝不写入 `/Users/gl/tzb-qrm-lite` 本体**(worktree、index、任何分支 ref)。该仓库的 `m2c-recovery-h3` 分支与脏工作树是受治理的证据面。工作只在专用克隆 `~/projects/xh-202607-qwen-brain` 中进行(启动脚本已创建),新分支 `codex/qwen-brain`,**禁止 git push 回源仓库**;交付用 `git bundle`。
2. **绝不触碰 labserver `/var/tmp/xh-data/isaac-industrial/m2c/` 下任何路径**(evidence/ledger/sources/stage/snapshots/existence-* checkouts/bundle)。那是 M2C formal 链的权威根。
3. **0 ordinal**:绝不运行任何 existence-probe runner、消费型容器或 M2C 评测命令。
4. **8/28–8/29 期间不在 labserver 启动任何新 Isaac 容器**——M2C formal 链正在使用 Isaac(preflight+12发窗口)。Tier-1 演示(见 S4)不需要 Isaac。live 演示只能在 12发完成后(预计 8/30 起)或用户明确确认后进行,且只用独立 demo 根 `/var/tmp/xh-data/isaac-industrial/qwen-brain-demo/`。
5. node2 A100:用户已授权本线使用;服务端口用 **18767**,不占 18766。chxy↔node2 为 100G 内网,将 chxy 的完整 Qwen3.8-27B 权重复制到 node2 后提供推理服务;chxy 保留给可选 LoRA。
6. 诚实标注:多执行机构若物理双臂不可行,用"N 个逻辑执行体分时共用一臂"并在材料中如实说明;replay 合成的演示片段必须标注 replay。

## 1. 资产(已确认在位,不要重复下载)

- 用户裁定的唯一主力模型为 **Qwen3.8-27B**;旧 Qwen3.6-27B 规格已作废,不得用于比赛证据;
- chxy(fx@chxy) `/home/fx/qwen38-27b-mtp/Qwen3.8-27B`:完整 BF16 多模态权重,66G on disk,18/18 safetensors(55,563,006,776 B),index 绑定 18 shards/1,199 tensors/55,562,855,904 B tensor payload;`vision_config` 已确认;这是复制到 node2 的源资产;
- chxy HF cache `models--Qwen--Qwen3.8-27B` 的确是空壳,但不代表上述独立目录缺失;两者不得混淆;
- node2 初始无 Qwen3.8-27B 完整权重;用户确认 chxy↔node2 为 100G 内网并允许传输,故复制完整资产到 node2 后 **S1 在 node2 使用**;chxy 保留给可选 LoRA;两台机的 Qwen3.8-9B GGUF 均不得误作 27B;
- node2 推理框架使用独立 venv安装,不得污染其他项目环境;
- 场景图像:克隆内 M2A 数据集(dataset-v3 / isaac-industrial-v1-pilot)的 RGB-D 帧与既有失败 episode 记录;
- 指令层代码:基分支 `codex/m2c-deliverables-instruction` 已含 instruction-understanding 层;
- exact-plan 技能原语与谓词 schema:克隆内 `src/xh_agent/` 既有实现,只读复用。

## 2. 分段目标

### S1 模型服务(8/28)
vLLM(优先)或 transformers 在 node2 起 Qwen3.8-27B 多模态服务,端口 18767;冒烟:输入一张 M2A 场景图 + 中文指令"哪个区域零件最多?",输出合理。记录显存占用与吞吐。

### S2 指挥体协议(8/28–29)
输入 = 场景图 + 自然语言指令;输出 = **严格 JSON**:`{subtasks: [{agent: A|B|C, skill_plan: [exact-plan 原语名+参数], preconditions, expected_postconditions}], rationale}`。schema 校验、失败重试、拒绝路径(图像不清/指令超域时显式拒绝而非编造)。覆盖题面三类指令:"把零件最多的区域装箱"、"放入料箱第二排第三个格子"、"搬运料箱"。用 ≥20 条指令×既有场景图做协议测试,产出通过率报告(如实,不挑选)。

### S3 升级链(8/29)
用既有失败 episode 记录回放:执行体报告失败(故障类型+上下文)→ 指挥体输出修正分解(如"重新抓取-调整姿态-再次放置")。与执行层 FC-QRM 的关系写清:FC 管技能级局部恢复,指挥体管任务级重分解,升级条件显式。产出 ≥5 组失败→重分解案例记录。

### S4 多智能体演示(8/29–30)
Tier-1(保底,不需 Isaac):指挥体对"帮我把所有零件装箱"输出 A/B/C 分工与动态重分配(A 先完成→C 搬 A 的箱→A 转战 D 区),配合既有执行录像 replay 合成分镜脚本。Tier-2(仅当 12发已完成且时间允许):独立 demo 根下 live 场景。

### S5 (可选,可整段砍)LoRA 场景 QA 微调
用 M2A 图像微调正常/倒放/倾倒判别与最多区域定位,报告微调前后对比。27B LoRA 不可行就降级 gguf 小模型或直接砍,记录理由。

### S6 材料交接(8/31 前代码冻结;素材可到 9/2)
交付:(a) demo 分镜脚本+全部指挥体 I/O 记录(reports/qwen-brain-*);(b) 技术报告"双系统指挥体"章节草稿(架构图、与 Gemini Robotics 1.5/GR00T N1 双系统谱系的对照、可验证契约差异化、诚实边界);(c) `git bundle` 交付件与复现说明。

## 3. 证据纪律

所有指挥体 I/O 原样落盘 `reports/qwen-brain-io/`,含失败与拒绝案例;协议通过率如实报告;每个演示片段可溯源到具体 I/O 记录。材料只允许引用落盘证据。
