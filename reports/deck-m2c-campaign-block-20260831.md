# 第 6 页左半｜抓取 campaign 实际处置

> 本内容块的数字与处置状态只取自已批准的 halted report v2（`b3586033`）；不从其他报告拼接或推导 campaign 数字。

## 画面主标题

**抓取 campaign：诚实停止，不补写缺失结果**

## 12 个 ordinal 状态图

按 ordinal 顺序横排 12 个等大圆点；只显示实际处置，不显示阈值带、X 分档或推测后缀。

```text
0 ●   1 ●   2 ●   3 ●   4 ●   │   5 ◐   │   6 ○   7 ○   8 ○   9 ○   10 ○   11 ○
  有效结果 · 全部未成功          物理派发尝试           从未执行
                                  无 canonical outcome
```

### 视觉编码

- `●` 深灰实心：ordinal 0–4，**5 个有效结果，全部未成功**。
- `◐` 琥珀半实心：ordinal05，**一次真实物理派发尝试**；worker 启动，runner `rc=1`，未形成 canonical outcome，按冻结 ledger 语义不计消费。
- `○` 浅灰空心：ordinal 6–11，**6 个从未执行**。
- 不使用红色“失败率”色阶，避免把未完成分母误读成统计结论。

## 必须同时出现的账目条

```text
5 有效  ·  0 成功  ·  7 未消费  ·  6 从未执行  ·  ordinal05 physical attempt = 1  ·  rc=1
```

## 冻结原话

```text
已完成的 5 个有效结果均未成功;原定 12 次 campaign 未完成,因此不作成功率或假设检验结论
```

## 构成披露

**5 个有效结果的构成：**3 legacy terminal 测量 + 1 ordinal03 零消费追溯闭合 + 1 ordinal04 orphan-closure。

## 版面脚注

- ordinal05：因 harness import failure 未形成 canonical outcome；不修补、不重派、不回填。
- 证据索引入口：`reports/appendix-m2c-evidence-index-20260831.md`
- 数字权威来源：approved halted report v2（`b3586033`）。

## 禁止进入画面的元素

- `0/12`、`s/12`、成功率、二项检验或“正式阴性结论”。
- 最低门、`p₀=0.75`、层间分歧门、X 分档或阈值带；这些只进技术附录/答辩备用页。
- “证明该架构不能抓取”“机器人抓取不存在”“大模型没有物理能力”。
- 任何成功或失败抓放镜头。
