# ADR-0034 — v4 因持续争用超时中止;v5 放宽超时并论证其输出中立

- 日期:2026-09-02 03:1x
- 裁定人:tzb-fe(tzb-c2)
- 执行线:fresh-v4-repair-loop
- 前序:ADR-0032(`dba870d09b5027cc`)、ADR-0033(`9430837d5ed2940c`),均 444 不可变
- 授权:用户夜间代批 gen606;"不管他,我们继续跑" gen591

## 事实

v4 于 03:05:10 起跑,03:06:10 中止:`single-01` attempt-00 `TimeoutError: model request exceeded 60.000s`,`INFRASTRUCTURE_FAILURE_ABORT`,result 工件已落(`ABORTED_WITHOUT_HEADLINE_METRICS`)。**ADR-0032/0033 冻结后 abort 工件正常落盘,冻结机制有效。**

诱因不是瞬时抖动。vLLM 日志:单请求解码 **12.6 tok/s**,GPU util 43%,与第三方任务(PID 134346,3270 MiB)平分。v2 时单次 attempt `elapsed_s` 24–35s;同样长度的输出在当前吞吐下需 60s 以上。第三方任务是无人值守重试循环(gen590),争用**持续存在**。

探测通过(6.269s)却真跑即超时:ADR-0033 §5 的"代表性请求"未按真实 CommanderPlanV2 输出长度(数百 token)构造,探测不具代表性。**该规格缺陷由 tzb-fe 负责。**

## 裁定:v5,fresh 路径,超时 60s → 240s,其余一字不改

**5.1 唯一新增变动:`request_timeout_s` 60 → 240。** 六采样参、24 case、k=3、TaskSpec、world snapshot、schema、validator、端点同进程不重启、`enable_thinking=False`、max_tokens、历史不累积——全部与 ADR-0032 §5.2 相同。

**5.2 为什么超时是输出中立的,可以放宽而不破坏单变量:**

- 超时只决定"是否等到输出",不参与生成。生成的 token 由模型、prompt、采样参数与采样 RNG 决定,与墙钟时间无关。
- v2 全程 93 次输出无一超时(最大 elapsed 约 35s),故 v2 的结果在任何 ≥ 35s 的超时下**逐字节相同**。
- v5 在 240s 下得到的输出,与"v4 在无限超时下"得到的输出**逐字节相同**。
- 因此 **v5 与 v2 在科学上仍只差采样这一个变量**;超时是纯基础设施让步,对比较无影响。

**5.3 240s 的依据:** 当前 12.6 tok/s,max_tokens=2048 的最坏情形约 163s;取 240s 留余量。若争用进一步加剧仍超时,再次按预登记 ABORT,不再放宽——届时写 state 等早上。

**5.4 披露义务:** v5 预登记与最终分析件须同屏写明:超时从 60s 改为 240s、原因(第三方争用致吞吐减半)、5.2 的输出中立论证、以及 v4 一次中止的完整记录。**不得把 v5 描述为"与 v2 仅差采样"而不提超时**——即便科学上等价,字段确实变了。

**5.5 探测规格更正:** 代表性请求须使用一个**真实 case 同等长度**的合成 payload(非 24 case 之一,不进证据),max_tokens 与实验相同。探测仍为 advisory(gen591),记 latency receipt。

## 不做的

- 不改 max_tokens、不改采样、不加 seed 字段、不重启服务。
- 不碰 PID 134346。
- 不回改 ADR-0032/0033。

## 冻结声明

本文件自此不可变,chmod 444。后续更正写 ADR-0035 起。
