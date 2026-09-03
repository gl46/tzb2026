# 挑战杯 XH-202607 工业抓取智能体 · 外部审议材料包

**日期**:2026-08-30
**用途**:请外部模型审视我们的整体判断链,指出盲点。**主文档在 `00-项目现状与决策链外部审议请求.md`,请先读它**;本包其余文件是它引用的真实证据,可按需查阅。

## 阅读顺序建议

1. `00-项目现状与决策链外部审议请求.md` —— 主文档(现状 + 代码 + 七个挑战问题)
2. `images/` —— 4 张真实场景图。**建议先看这个**:直接判断任务对人眼有多难
3. `evidence/paired-evaluation-results.md` —— 成对评测的 2×2 表(最关键的实验结论)
4. `data/dataset-v4-samples.jsonl` —— 四个任务族各 2 行完整数据
5. 其余按主文档引用查阅

## 目录

| 路径 | 内容 |
|---|---|
| `00-*.md` | **主文档** |
| `images/scene-1-before.png` | 训练集原图(操作前) |
| `images/scene-1-after.png` | 同一 episode 操作后 |
| `images/scene-1-instance-seg.png` | 同一帧的实例分割(说明我们有哪些可用真值) |
| `images/scene-2-before.png` | 另一场景 |
| `data/dataset-v4-samples.jsonl` | 四族各 2 行完整数据(含 `prompt_context` 与 `target_json`) |
| `data/dataset-v4-report.json` | 数据集生成报告 |
| `code/client_v1.py` | 指挥体客户端 + System Prompt 全文 |
| `code/s5_icl_v3.py` | ICL 协议(多轮多图消息构造、期望推导、成对评测)——**任务设计缺陷的证据在这里** |
| `code/s5_evaluation_v1.py` | 评测原语(成对转移矩阵、边界审计) |
| `code/train_s5_lora_node2_v1.py` | 训练脚本(确定性前置门、bit-exact 重载门、两阶段发布) |
| `code/audit_v5_existence_probe_v1.py` | 抓取探针统计判定(**冻结协议即代码**) |
| `code/run_v5_existence_successor_probe_v2.py` | 抓取 runner(claim 前五门、零消费清理、终态化) |
| `configs/commander-plan-v1.schema.json` | 契约 JSON Schema |
| `configs/s5-training-node2-v1.json` | 训练配置(全部超参与门限) |
| `configs/s5-icl-v3.json` | ICL 评测配置 |
| `configs/s5-lora-v4.json` | LoRA 目标模块配置 |
| `evidence/paired-evaluation-results.md` | **成对评测 2×2 表与最终分类** |
| `evidence/visual-instrument-audit-v4.json` | 去重仪器有效性审计(v4 通过版) |
| `evidence/generated-dataset-audit-v4.json` | 数据集独立行审计 |
| `evidence/frontier-review-route-v4.json` | 前沿桥边复核路由(0 条待复核) |
| `evidence/grasp-campaign-final-accounting.json` | 抓取探针最终账目 |
| `evidence/grasp-honest-halted-report.json` | 抓取诚实停机报告 |
| `evidence/qwen-brain-active-state.md` | 指挥体线活跃状态文件(原始流水账,很长,可检索) |
| `prior-consults/` | 前两轮外部咨询的提问与回复(**避免重复建议**) |

## 已知的时间线

- 工程时间:到 9 月 3 日(约 3.5 天)
- 材料时间:9 月 3 日 – 9 月 5 日
- 提交:9 月 5 日
