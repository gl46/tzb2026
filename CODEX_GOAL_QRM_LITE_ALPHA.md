# GOAL P1-QRM-α：Qwen-RobotManip-inspired 工业动作策略最小实现、数据对齐与 48 小时可行性门禁

你是 XH-202607 项目的并行模型研发代理。请直接执行工程任务，不要只输出建议或规划。

本 Goal 与 M1B 感知—闭环主线并行，研发一条 **受 Qwen-RobotManip 启发、但由本团队独立实现** 的工业视觉语言动作策略：

```text
Qwen3.5-4B 多模态骨干
+ 工业任务与失败上下文适配
+ 粗粒度技能/动作意图头
+ 相机坐标系动作表示
+ 几何名义动作锚定的残差细化
+ MLP 基线
+ Flow-Matching 动作细化器原型
```

本轮不是要在一夜之间训练一个通用机器人基础模型，而是完成：

```text
官方方法审计
→ 独立训练环境
→ 数据和动作坐标对齐
→ Qwen3.5 多模态特征接通
→ LoRA/粗技能头可训练
→ MLP 残差基线
→ Flow-Matching 头前向、反向和小样本过拟合
→ 公平离线对比
→ 可继续训练的代码、配置、报告和 checkpoint
```

如果某一步受阻：

1. 先联网检索官方文档、官方仓库、上游 issue 和兼容性说明；
2. 可以安装缺失的 pip、apt、conda、CUDA 扩展和容器依赖；
3. 可以选择更兼容的库、训练框架或实现方式，但必须记录理由和版本；
4. 不要因一个包缺失就提前终止；
5. 单个问题约 60–90 分钟无实质进展时，切换实现路径并保留证据；
6. 不得伪造训练、GPU、数据或 Gazebo 运行结果；
7. 不要询问可通过仓库、运行环境、联网检索或合理默认值解决的问题；
8. 只有凭据、不可逆系统操作或明确的人类架构决策才需要停下并报告。

---

## 0. 项目定位与硬边界

### 0.1 这条线的身份

本项目不声称复现官方 Qwen-RobotManip，因为官方当前未发布其模型权重和完整训练实现。

正确表述始终是：

```text
Qwen-RobotManip-inspired independent implementation
受 Qwen-RobotManip 的相机坐标动作对齐、行为上下文和 Flow-Matching 动作专家启发的独立轻量实现
```

必须清楚区分：

#### 公开论文/官方方法启发

- Qwen3.5-4B 视觉语言骨干；
- Flow-Matching DiT 动作专家思想；
- 相机坐标系末端增量；
- 最近 observation-state-action 历史上下文；
- 连续 action chunk；
- 表示、运动和行为对齐思想。

#### 本项目自己的实现与新增机制

- 面向本榜题的参数化技能空间；
- 失败类型、预期谓词、实际谓词和恢复历史组成的显式 FailureContext；
- 几何/MoveIt 名义动作作为动作锚点；
- 只预测安全范围内的残差 action chunk；
- 逐技能重新感知与谓词残差；
- 工业姿态辅助监督；
- 与规则基线、LingBot 基线、MLP 残差头的公平消融。

### 0.2 物理世界与世界模型决定

本项目已经退役学习式视频世界模型主线：

```text
Gazebo = 物理仿真环境、训练数据源、失败注入器和评测真值
Cosmos/BWM/Qwen-RobotWorld = 不进入本轮
```

本 Goal 不实现未来视频预测，不训练 Student 世界模型，不运行大型生成式世界模型 Teacher。

### 0.3 主线优先级

M1B 的工业感知、非 Oracle 闭环、规则恢复和录像是交付主线。

本 Goal 必须满足：

- 在独立分支和独立训练工作区进行；
- 不改写 M1B 正在使用的工作树；
- 不长期占用仿真节点；
- SIM_HOST 忙碌时优先使用已有离线数据、合成 fixture 或训练节点上的数据副本；
- 任何模型训练失败都不得影响 B0 规则系统交付。

---

## 1. 当前资源与运行拓扑

本地协调仓库：

```text
PROJECT_DIR=/Users/gl/projects/xh-202607-world-agent
```

训练节点：

```text
TRAIN_HOST=chxy
TRAIN_USER=gl
QRM_REMOTE_ROOT=xh-202607-qrm-lite
```

仿真节点：

```text
SIM_HOST=node2
SIM_USER=gl
SIM_PROJECT_REMOTE_ROOT=xh-202607-world-agent
```

可用硬件为用户报告值，开始时实际核验：

```text
训练节点：1×A100 80GB
仿真节点：Gazebo Harmonic + ROS 2 Jazzy
```

只访问显式给定的主机，不扫描局域网。

---

## 2. 权限策略：允许正常工程操作

本 Goal 不是“零安装、零联网”审计任务。默认允许：

```text
ALLOW_NETWORK_FETCH=1
ALLOW_PIP_INSTALL=1
ALLOW_APT_INSTALL=1
ALLOW_CONDA_INSTALL=1
ALLOW_MODEL_DOWNLOAD=1
ALLOW_CONTAINER_PULL=1
ALLOW_GPU_RUN=1
ALLOW_REMOTE_PROJECT_WRITE=1
ALLOW_SIM_DATA_GENERATION=1
ALLOW_GIT_BRANCH=1
ALLOW_GIT_COMMIT=1
ALLOW_GIT_PUSH=1
MAX_MODEL_DOWNLOAD_GIB=30
```

### 2.1 允许执行

- 搜索互联网、论文、官方文档、GitHub 仓库和 issue；
- 克隆官方或必要的开源仓库；
- 在独立 venv、uv、Conda 或容器环境中安装依赖；
- 在训练节点使用 `sudo -n apt-get update/install` 安装普通构建与运行依赖；
- 下载 `Qwen/Qwen3.5-4B`、processor、tokenizer 和必要的小型公开模型；
- 编译 FlashAttention、xFormers 或其他兼容 CUDA 扩展；
- 拉取合理体量的官方训练容器；
- 运行 A100 训练、评测和 profiling；
- 在专用分支 commit 并普通 push；
- 在不影响 M1B 的情况下，有界调用 node2 生成少量动作数据。

### 2.2 仍需避免的高风险操作

以下不是为了限制开发，而是避免破坏共享机器：

- 不升级或替换 NVIDIA 驱动、系统 CUDA、Linux kernel、引导项；
- 不做 `apt full-upgrade`、`dist-upgrade` 或整体 ROS/Gazebo 大版本迁移；
- 不修改防火墙、SSH daemon、用户权限和 GitHub 权限；
- 不强推、不自动合并 main、不移动已有 tag；
- 不删除 M0/M1A/M1B 证据和用户已有数据；
- 不在仓库或日志中写入 HF token、SSH 私钥、密码；
- 不执行来源不明的 `curl | sh`；
- 不下载 Cosmos3-Super、BWM 或其他与本 Goal 无关的大模型；
- 不在不知情的情况下终止其他用户 GPU 任务。

如果必须执行上述操作才能继续，记录准确证据和人工命令，不伪造完成。

---

## 3. Git 与并行工作区

### 3.1 本地只做协调检查

在 `PROJECT_DIR` 记录：

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git remote -v
```

不得切换或改写本地正在被 M1B 使用的工作树。

### 3.2 训练节点建立独立仓库

优先在训练节点创建或复用：

```text
$HOME/$QRM_REMOTE_ROOT
```

策略：

1. 若目录不存在，从当前项目 origin 克隆；
2. 若存在，确认是正确远端且工作树可安全使用；
3. fetch 最新 origin；
4. 从执行时的 `origin/main` 创建或复用：

```text
codex/qrm-lite-alpha
```

5. 记录基线 commit；
6. 不自动合并 main；
7. 若已有同名分支带用户改动，不覆盖，改用带时间戳的分支。

### 3.3 大文件纪律

以下不得提交到 Git：

- Hugging Face cache；
- Qwen 原始权重；
- optimizer state 大文件；
- 原始 rosbag、视频和批量图像；
- 第三方完整仓库；
- Conda 环境；
- secrets。

允许提交：

- LoRA adapter；
- 小型动作头 checkpoint，若单文件体量合理；
- 配置；
- 数据 manifest；
- 训练曲线和摘要；
- 小型测试 fixture；
- 代码、报告和许可证清单。

若 checkpoint 太大，写入 artifact manifest 和可恢复路径，不强行提交。

---

## 4. 阶段与柔性时间预算

本轮目标是“bring-up + 小样本可训练性证明”，建议总运行 8–14 小时，但不设置机械到点即失败。

```text
Q0  官方方法和仓库审计                    30–60 min
Q1  训练节点环境与 Qwen3.5 bring-up       60–150 min
Q2  数据/坐标/动作协议                    90–180 min
Q3  粗技能与失败上下文策略                90–180 min
Q4  MLP 几何残差基线                      60–150 min
Q5  Flow-Matching 细化器原型              90–240 min
Q6  评测、报告、测试、commit/push         45–120 min
```

原则：

- 先完成最小可训练闭环，再提高复杂度；
- 先 MLP，后 Flow；
- 先冻结骨干，再 LoRA；
- 先 100 条过拟合，再扩大数据；
- 不做无边界超参数搜索；
- Flow 没有稳定优于 MLP 时，不把扩散/Flow 写成最终核心创新。

---

## 5. Q0：官方方法审计与 ADR

### 5.1 只依赖权威来源理解 Qwen-RobotManip

优先读取并锁定：

```text
https://arxiv.org/abs/2606.17846
https://github.com/QwenLM/Qwen-RobotManip
https://huggingface.co/Qwen/Qwen3.5-4B
```

可阅读第三方实现和 issue 帮助排错，但方法事实、许可证和官方发布状态以以上来源为准。

记录：

- 论文版本与下载时间；
- 官方 GitHub commit；
- Qwen3.5 checkpoint revision；
- Qwen3.5 模型许可证；
- 官方仓库“暂无 Qwen-RobotManip 权重发布计划”的状态；
- 所有关键实现假设与论文未公开细节。

### 5.2 新增 ADR

创建：

```text
docs/decisions/ADR-0011-qrm-inspired-industrial-policy.md
```

至少说明：

- 为什么不能宣称复现官方模型；
- 为什么使用 Qwen3.5-4B；
- 为什么采用相机坐标动作；
- 为什么保留 MoveIt 作为安全和全局运动层；
- 为什么动作模型预测残差而不是从零生成整条全局轨迹；
- 为什么先做 MLP，再做 Flow；
- 失败上下文是本团队新增机制；
- 本线如何与 LingBot 官方基线保持独立；
- 本线失败时 B0 仍可完整交付。

### 5.3 同步旧世界模型条款

审计 `AGENTS.md` 和 roadmap：

- 如果仍把 Student world model、Teacher 或 Cosmos 写成必做主线，更新为退役/可选历史项；
- 不删除历史 ADR；
- 记录架构转向的证据链；
- 不干扰 M1B 现有接口。

---

## 6. Q1：训练环境与 Qwen3.5-4B bring-up

### 6.1 环境

在训练节点建立独立环境，例如：

```text
.venv-qrm-lite
或 conda env: xh-qrm-lite
```

可以根据兼容性自行选择：

- uv / pip / Conda；
- PyTorch 官方 wheel；
- Transformers 最新兼容版本；
- PEFT；
- Accelerate；
- DeepSpeed/FSDP（仅有实际收益时）；
- FlashAttention/xFormers（可选）；
- Diffusers 或自研 Flow-Matching 实现；
- Hydra/OmegaConf 或简洁 YAML 配置；
- TensorBoard/W&B（W&B 必须允许离线模式且不得暴露 token）。

记录完整环境：

```text
Python
PyTorch
CUDA runtime
Transformers
PEFT
Accelerate
GPU
驱动
关键扩展
```

### 6.2 模型下载与许可

默认模型：

```text
Qwen/Qwen3.5-4B
```

采用官方 post-trained checkpoint 作为首个 bring-up；如果后续实验说明 Base 更合适，可新增配置，不要覆盖首个结果。

要求：

- 缓存位于仓库外；
- 固定 revision；
- 保存文件 manifest 和许可证摘要；
- 不打印 token；
- 下载可断点续传；
- 检查可用磁盘后再开始。

### 6.3 必须实际完成的 smoke

至少实际运行：

1. 文本推理；
2. 单图多模态推理；
3. batch=1 的多模态 forward；
4. `output_hidden_states=True` 或等价特征抽取；
5. BF16 GPU 推理；
6. 记录峰值显存和耗时；
7. 对一层或 LoRA adapter 完成一次真实 backward 和 optimizer step；
8. 保存和重新加载一个最小 adapter。

不得只通过 `import` 就宣布模型接通。

### 6.4 Qwen wrapper

建立：

```text
src/xh_agent/policy/qrm_lite/backbone.py
```

接口至少支持：

```python
encode_multimodal(batch) -> BackboneFeatures
forward_policy_context(batch) -> PolicyContextFeatures
save_adapter(path)
load_adapter(path)
```

不得在 Python import 阶段自动下载模型或占用 GPU。

---

## 7. Q2：动作、失败上下文和训练样本协议

建立独立、可测试的协议，建议路径：

```text
src/xh_agent/policy/qrm_lite/contracts.py
schemas/qrm-observation-v1.schema.json
schemas/failure-context-v1.schema.json
schemas/camera-action-chunk-v1.schema.json
schemas/qrm-training-sample-v1.schema.json
```

### 7.1 QRMObservationV1

至少包含：

- RGB 或多视角 RGB URI/张量；
- 可选深度、目标 crop、mask、点云特征；
- TaskSpec；
- perception track 和置信度；
- 当前机器人状态；
- 当前末端位姿；
- 相机内外参；
- 当前技能阶段；
- 最近 N 步观察—状态—动作摘要；
- FailureContext，可为空。

在线策略禁止读取：

- Gazebo 完美物体 pose；
- 完美 entity ID；
- 完美成功标签；
- 完美失败类型。

SimulatorSupervision 仅用于训练标签和评测。

### 7.2 FailureContextV1

至少包含：

```text
last_skill
expected_predicates
observed_predicates
predicate_residual
failure_type
retry_count
attempted_recoveries
last_action_summary
last_target_track_id
```

失败类型使用可扩展枚举，首版至少支持：

```text
NONE
EMPTY_GRASP
WRONG_OBJECT
DROP_OR_SLIP
UNSTABLE_PLACEMENT
WRONG_CELL
RELEASE_FAILURE
PATH_BLOCKED
TRACKING_LOST
```

### 7.3 CoarseIntentV1

首版输出可以包含：

```text
skill_type
target_track_id
grasp_family
recovery_mode
reobserve_flag
orientation_goal
coarse_translation_bins
coarse_rotation_bins
```

分箱数量做成配置，不写死。默认可从 3 或 5 档开始，并保留 10 档实验入口。

### 7.4 CameraFrameActionChunkV1

默认表示建议为：

```text
T × D
translation: camera-frame Δx, Δy, Δz，单位 m
rotation: 6D rotation delta 或 axis-angle delta
 gripper: normalized open/close or width
```

要求：

- 明确 camera optical frame 与机器人 base frame 约定；
- 明确左乘/右乘、局部/全局旋转约定；
- 明确时间频率、chunk 长度、单位、归一化；
- 支持 action mask；
- 拒绝 NaN/Inf；
- 提供 base↔camera↔EEF 转换往返测试；
- 提供旋转连续性测试；
- 提供反归一化边界测试。

允许 Codex 根据现有 MoveIt/TF 接口选择 7D 或 10D 默认实现，但必须在 ADR 和配置中写清楚，不能静默混用。

### 7.5 几何名义动作与残差

定义：

```text
nominal_action_chunk = B0/MoveIt/几何规划产生的安全名义动作
residual_action_chunk = 学习模型预测的局部修正
final_action_candidate = nominal + residual
```

残差首版应有配置化安全边界，例如位置、旋转、夹爪和速度范围；具体数值根据数据统计和现有控制接口确定，不凭空硬编码。

MoveIt 继续负责：

- IK；
- 工作空间；
- 自碰撞；
- 环境碰撞；
- 全局路径；
- 最终动作拒绝。

---

## 8. Q2：数据适配与小样本数据集

### 8.1 审计现有数据

搜索并统计当前仓库或明确 artifact 路径中的：

- M1A EpisodeTransition；
- RGB-D 图像或 rosbag；
- B1-Oracle/非 Oracle 轨迹；
- empty-grasp、release-delay、摩擦滑落等失败；
- MoveIt 期望与实际轨迹；
- TaskSpec 或自然语言指令。

输出：

```text
reports/qrm-lite-data-inventory.md
reports/qrm-lite-data-inventory.json
```

### 8.2 转换器

建立：

```text
scripts/qrm_lite/prepare_dataset.py
```

将现有数据转换成 `QRMTrainingSampleV1`，至少支持：

- 图像/深度索引；
- 当前状态和历史窗口；
- 相机坐标 action chunk；
- nominal/residual 分解；
- coarse intent 标签；
- FailureContext；
- provenance；
- episode/seed split。

### 8.3 数据不足时的处理

如果真实可用样本不足以做 100 条 overfit：

1. 优先从现有 M1A/M1B 日志生成；
2. 可在 node2 使用当前稳定 B1/接触门控链路有界生成少量数据；
3. 默认总占用 node2 不超过约 90 分钟，SIM_HOST 忙碌时立即退出；
4. 可使用单独场景 seed 和独立输出路径；
5. 不修改 M1B 运行中的 world、branch 或数据；
6. 仍不足时，创建几何一致的 synthetic fixture 用于代码和过拟合测试，并明确标记，不冒充 Gazebo 数据。

### 8.4 最小数据集

本轮目标不是正式训练集，建议至少形成：

```text
100–500 个短 episode 或等价 action chunks
包含成功、抓空、滑落/掉落、放置异常或释放失败中的至少两类
```

划分必须按 episode/seed，不得随机拆相邻帧。

保存：

```text
data/qrm_lite/manifests/alpha-dataset.json
configs/qrm_lite/dataset-alpha.yaml
reports/qrm-lite-dataset.md
```

原始大数据放仓库外，manifest 记录路径和 SHA/统计。

---

## 9. Q3：粗技能策略与 FailureContext

建议结构：

```text
Qwen3.5 multimodal features
+ robot-state projection
+ history/context projection
+ structured FailureContext encoding
→ coarse policy head
```

建立：

```text
src/xh_agent/policy/qrm_lite/context.py
src/xh_agent/policy/qrm_lite/coarse_policy.py
src/xh_agent/policy/qrm_lite/model.py
```

### 9.1 训练策略

按以下顺序执行：

1. 冻结 Qwen 骨干，只训练 coarse head；
2. 在 100 条或更小子集上过拟合；
3. 接入 LoRA，验证梯度和收敛；
4. 比较 `failure_context=off/on`；
5. 保存最小 checkpoint 和训练日志。

### 9.2 任务头

至少支持：

- skill_type 分类；
- grasp_family 分类；
- reobserve/recovery 二分类或多分类；
- orientation_goal；
- coarse translation/rotation bins；
- 可选 failure_type 辅助头；
- 可选工业姿态辅助头。

### 9.3 过拟合门禁

推荐而非僵化指标：

- 小样本 coarse skill 训练准确率接近 100%；
- loss 明显下降且无 NaN；
- 保存/加载后输出一致；
- `failure_context=on` 的数据路径实际参与 forward，而非只写在 JSON；
- 至少展示 5 条输入、目标和模型预测。

未达到时必须定位：

```text
数据标签
特征抽取
mask
loss
优化器
类别不平衡
坐标转换
```

不要直接扩大模型掩盖问题。

---

## 10. Q4：MLP 几何残差基线

Flow 前必须先完成简单基线。

建立：

```text
src/xh_agent/policy/qrm_lite/mlp_refiner.py
scripts/qrm_lite/train_mlp_refiner.py
scripts/qrm_lite/evaluate_refiner.py
```

输入建议包括：

- Qwen/粗技能上下文；
- 目标局部 RGB-D 或几何特征；
- 机器人状态；
- nominal action chunk；
- FailureContext；
- action mask。

输出：

```text
residual action chunk
```

要求：

- 可配置 chunk 长度；
- 训练 loss、验证误差和动作边界完整记录；
- 100 条子集可明显过拟合；
- 反归一化后无 NaN/Inf；
- 残差裁剪和安全拒绝有测试；
- 同时报告 absolute action 和 residual action 两种目标中至少一种的实验理由。

建议指标：

```text
translation MAE
rotation error
 gripper accuracy/MAE
chunk endpoint error
valid-action rate
```

该模型是后续 Flow 的必须比较对象。

---

## 11. Q5：Flow-Matching 动作细化器原型

建立：

```text
src/xh_agent/policy/qrm_lite/flow_refiner.py
src/xh_agent/policy/qrm_lite/flow_matching.py
scripts/qrm_lite/train_flow_refiner.py
scripts/qrm_lite/sample_flow_refiner.py
```

### 11.1 设计原则

- 条件 Flow Matching；
- 预测几何名义动作周围的 residual chunk；
- 支持多峰候选采样；
- 不负责全局路径规划；
- 不绕过 MoveIt 安全过滤；
- 第一版规模以单张 A100 快速迭代为目标；
- 具体层数、hidden size、heads、参数量和 ODE 步数由 Codex根据显存、数据规模和实现成熟度选择并记录，不被固定数字束缚。

### 11.2 最小实现要求

至少完成：

1. 条件 DiT/Transformer 或等价 Flow 网络；
2. 时间步嵌入；
3. context conditioning；
4. action mask；
5. flow-matching loss；
6. Euler 或兼容 ODE 采样；
7. forward/backward；
8. checkpoint save/load；
9. deterministic seed 测试；
10. 100 条子集 loss 下降和过拟合趋势；
11. 采样输出反归一化后处于合理动作边界。

### 11.3 公平比较

MLP 与 Flow 必须使用：

- 同一训练/验证划分；
- 同一输入信息；
- 同一 nominal action；
- 同一动作归一化；
- 同一评测脚本；
- 相近训练预算或明确披露差异。

不得只展示 Flow 的最好样本。

### 11.4 学术诚实规则

必须把下面这句话写进报告和未来训练 Goal：

> 如果 Flow head 没有稳定优于 MLP residual baseline，就不把扩散式动作生成包装成项目核心创新；最终系统保留表现更好、更稳定、更容易复现的实现。

---

## 12. 安全执行适配器

建立：

```text
src/xh_agent/policy/qrm_lite/safety_adapter.py
```

职责：

- 反归一化；
- action residual 边界；
- 工作空间与速度预检查；
- 转换到 MoveIt/技能参数；
- 无效动作拒绝；
- 记录拒绝原因；
- 不直接控制 Gazebo 关节；
- 不绕过当前接触门控抓取原语。

本轮至少做离线测试和接口 smoke。

如果 M1B 环境稳定且 SIM_HOST 空闲，可选执行一个受限闭环 smoke：

```text
感知/固定目标
→ nominal skill
→ learned residual candidate
→ MoveIt safety check
→ 只执行通过检查的短动作
```

闭环 smoke 不是 `PASS_QRM_ALPHA` 的硬性前提；M1B 不应被阻塞。

---

## 13. 训练配置与 CLI

建立独立命令：

```text
python -m xh_agent.policy.qrm_lite.inspect_backbone
python scripts/qrm_lite/prepare_dataset.py ...
python scripts/qrm_lite/train_coarse_policy.py ...
python scripts/qrm_lite/train_mlp_refiner.py ...
python scripts/qrm_lite/train_flow_refiner.py ...
python scripts/qrm_lite/evaluate_offline.py ...
python scripts/qrm_lite/export_policy.py ...
```

配置建议：

```text
configs/qrm_lite/backbone-qwen35-4b.yaml
configs/qrm_lite/coarse-alpha.yaml
configs/qrm_lite/mlp-alpha.yaml
configs/qrm_lite/flow-alpha.yaml
configs/qrm_lite/eval-alpha.yaml
```

要求：

- CLI 有 `--help`；
- 随机种子可配置；
- 路径不硬编码用户名；
- 训练可断点续训；
- 日志记录 git commit、配置和数据 manifest；
- 支持 BF16；
- 根据需要使用梯度累积和 checkpointing；
- 默认不全参数微调 Qwen；
- 全参数微调只有在实测必要且显存允许时才可新增实验，不覆盖 LoRA 基线。

---

## 14. 测试

新增测试至少覆盖：

```text
camera/base frame transform round trip
rotation representation continuity
normalization round trip
NaN/Inf rejection
action mask
history window construction
FailureContext serialization
oracle field rejection
coarse labels
MLP output shape and bounds
Flow forward/backward
Flow deterministic seed
checkpoint save/load
safety adapter rejection
model import does not auto-download or allocate GPU
```

GPU 测试应使用 marker，可在 A100 节点运行；普通单元测试不得要求完整 4B 权重。

运行：

```text
pytest
ruff/check formatting
python compile/import check
git diff --check
shell syntax check
```

记录实际测试数量和退出码，不写死。

---

## 15. 48 小时技术门禁

本 Goal 建立并尽可能完成第一轮，输出：

```text
reports/qrm-lite-48h-gate.md
reports/qrm-lite-48h-gate.json
```

门禁问题：

1. Qwen3.5-4B 能否在单张 A100 上完成多模态 forward？
2. hidden features 是否可稳定抽取？
3. LoRA 是否能完成真实 optimizer step？
4. 粗技能头是否能过拟合 100 条样本？
5. camera-frame action 转换是否通过往返测试？
6. MLP residual 是否能过拟合小样本？
7. Flow head 是否能 forward/backward、loss 下降并生成有界动作？
8. Flow 相对 MLP 是否已有初步正向证据？
9. 数据、动作和历史对齐是否清晰可审计？
10. 单张 A100 显存和吞吐是否允许继续扩大？

结论只能是：

```text
GO_FULL_QRM_LITE
GO_COARSE_AND_MLP_ONLY
CONTINUE_WITH_FIXES
STOP_MODEL_LINE_USE_LINGBOT_BASELINE
```

说明：

- `STOP_MODEL_LINE_USE_LINGBOT_BASELINE` 不代表项目失败；
- B0 与 M1B 不受影响；
- 结论必须由证据产生，不能因为“想做”就写 GO。

---

## 16. 完成状态

### 16.1 PASS_QRM_ALPHA

至少满足：

- 独立分支/工作区建立；
- 官方来源、revision 和许可证锁定；
- ADR-0011 完成；
- Qwen3.5-4B 多模态 BF16 forward 实际运行；
- hidden feature 抽取完成；
- LoRA 或等价参数高效训练完成至少一次真实 step；
- 数据转换器和 action frame 转换可运行；
- FailureContext 和 coarse intent 实际进入模型；
- coarse head 在小样本上有明确过拟合证据；
- MLP residual baseline 有明确训练证据；
- Flow head 完成 forward/backward、checkpoint 和 loss 下降；
- 公平离线评测脚本可运行；
- 测试通过；
- 报告、配置和下一步计划完整。

### 16.2 PASS_QRM_ALPHA_WITH_LIMITATIONS

可接受情况：

- Qwen/LoRA/coarse/MLP 均通过，但 Flow 仅完成 smoke，尚无过拟合或无优于 MLP 证据；
- 数据量不足，只完成 synthetic fixture + 少量 Gazebo 数据；
- 闭环 smoke 未执行；
- 某个高性能 CUDA 扩展不可用但普通实现能训练。

此状态仍应给出是否继续 Flow 的诚实建议。

### 16.3 PARTIAL

例如：

- Qwen 能加载但动作数据对齐未完成；
- 数据转换完成但训练未跑；
- 只生成代码，没有真实 GPU forward/backward。

### 16.4 BLOCKED

仅用于：

- 训练节点不可访问；
- GPU 长期不可用；
- 模型下载/许可证权限阻塞；
- 磁盘或系统环境无法在合理操作范围内修复。

---

## 17. 报告与产物

至少生成：

```text
reports/qrm-lite-alpha-status.md
reports/qrm-lite-alpha-status.json
reports/qrm-lite-hardware-and-env.md
reports/qrm-lite-data-inventory.md
reports/qrm-lite-dataset.md
reports/qrm-lite-coarse-policy.md
reports/qrm-lite-mlp-vs-flow.md
reports/qrm-lite-48h-gate.md
reports/qrm-lite-license-and-attribution.md
```

状态 JSON 至少包含：

```json
{
  "phase": "P1-QRM-alpha",
  "status": "PASS_QRM_ALPHA|PASS_QRM_ALPHA_WITH_LIMITATIONS|PARTIAL|BLOCKED",
  "base_model": "Qwen/Qwen3.5-4B",
  "base_revision": "",
  "branch": "",
  "base_commit": "",
  "gpu": "",
  "qwen_multimodal_forward": false,
  "hidden_states_verified": false,
  "lora_train_step_verified": false,
  "dataset_samples": 0,
  "camera_action_roundtrip": false,
  "coarse_overfit_verified": false,
  "mlp_overfit_verified": false,
  "flow_forward_backward_verified": false,
  "flow_loss_decreased": false,
  "flow_outperforms_mlp_preliminary": null,
  "gate_verdict": "GO_FULL_QRM_LITE|GO_COARSE_AND_MLP_ONLY|CONTINUE_WITH_FIXES|STOP_MODEL_LINE_USE_LINGBOT_BASELINE",
  "tests_passed": 0,
  "tests_failed": 0,
  "commit": "",
  "pushed": false,
  "blockers": [],
  "next_command": ""
}
```

### 17.1 Commit 与 push

若测试和报告完成且 `ALLOW_GIT_COMMIT=1`：

```text
milestone: bring up qrm-inspired industrial policy alpha
```

若 `ALLOW_GIT_PUSH=1`，普通 push 当前 feature branch，并设置 upstream。

不得：

- 自动合并 main；
- 自动打 release tag；
- 强推。

---

## 18. 最终回复格式

最终回复应简洁但有证据，列出：

1. 总状态；
2. 48 小时门禁结论；
3. 训练节点、GPU、环境；
4. Qwen bring-up 是否真实通过；
5. 数据样本量和来源；
6. coarse/MLP/Flow 各自结果；
7. MLP 与 Flow 初步对比；
8. 修改的主要文件；
9. 测试结果；
10. commit 和 push 状态；
11. 限制或 blocker；
12. 唯一推荐的下一条命令。

现在开始执行。优先建立独立工作区、锁定官方来源、完成 Qwen3.5 多模态 forward 和数据/动作对齐，再推进 coarse、MLP 与 Flow。不要停在文档阶段。
