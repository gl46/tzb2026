[STATE-PROTOCOL-v2 裁定请求 · 最小版本]
发起:执行会话 tzb-5e(sessionId 前缀 b7634e30)  日期:2026-08-30
配套身份清单:state/PROTOCOL-V2-MANIFEST.json(全部 digest 程序派生;下文短前缀仅 informational)

== 0. 请求内容 ==
把 M2C_STATE.md 与 QWEN_BRAIN_STATE.md 从"当前状态 + 无界写回区"改为
"有界活跃快照(§1-§4)+ 按日 journal",唯一写入口 tools/statectl.py。
不改变任何实验事实、冻结链、既有裁定内容、写入权归属或停止线。只改状态存储与写回协议。

== 1. 事实依据(实测,来源 ~/.claude/projects/-Users-gl-tzb/*.jsonl)==
- M2C_STATE.md 累计 2458 次工具调用 / 42.7 MB 工具输出 = 全部工具输出 181 MB 的 24%;单会话最高占比 38.5%。
- 结构失衡:§1-§4 核心 3.3 KB(3%),§5 写回区 106.5 KB(96%),而写回区只含 8/29-8/30 两天 → 约 50 KB/天。
- QWEN_BRAIN_STATE.md 同型:§6 写回区 92.4 KB / 99 KB = 93%。
- 1665 次读已经是带 offset/limit 的(纪律无问题),但写回区平均 595 B/行、最长 1423 字符,行级窗口在该文件上无效。
- 8/29(M2C)、8/30(QWEN)已各做过一次手工归档,一到两天长回原量 → 不带速率控制的轮转会复发。
- 主力写入是 Edit 工具 541 次(93%),shell 追加仅 21 次(3.6%);826 次写入中跨会话冲突仅 3 次且被 harness 拦住。
  → 本变更的理由是"限额需要一个能拒绝的入口",不是防并发丢写。并发风险经实测基本未兑现。

== 2. 已完成(纯增量、可回退;未触碰旧文件、hook 未激活)==
- tools/statectl.py(14582B, sha a6750a0e…)
  命令 fact/task/done/event/render/check;flock + 锁内重读 + fsync + os.replace;
  journal 先落盘再重建快照(WAL),崩溃可由 check 检出漂移、render 修复。
- tools/statectl_guard.py(2908B, sha 126c8353…)PreToolUse 拦截器,8/8 用例正确。
- tools/statectl_import.py(6837B, sha 1721ca6d…)一次性迁移,默认 dry-run。
- 迁移结果:
    M2C_STATE.md 112743B  →  state/v2/M2C_STATE.md 12481B(sha c11e0226…)
    QWEN_BRAIN_STATE.md 102737B  →  state/v2/QWEN_STATE.md 15474B(sha cba2e3fb…)
- 字节守恒:preamble + 全部记录行逐字节重建原写回区(全量重建校验,非抽样)。
  QWEN 有 1 条记录含 90 行续行,已作为整条记录保留,未拆散。
- 核心区 §1-§4 摘要逐字照抄,未改写一字;只附加 stable key(M2C 15 个 / QWEN 30 个,表在 statectl_import.py 的 PLAN)。
- 既有硬边界已编码为 writers 名单:M2C=['tzb-fe','m2c-exec'],QWEN=['qwen-brain-owner']。
  依据:M2C_STATE.md 头部"写入权(2026-08-28 收口)"与 QWEN 永久硬边界 #1。发起会话 tzb-5e 试写 M2C 已被拒。

== 3. 请求裁定(R1/R2 不能只 ACK)==
R1【写者名单字面确认】上述 writers 名单是我从两文件头部现有条款推出的。请确认字面正确,
    特别是 M2C 的 'm2c-exec' 应绑定为哪个标识(会话名会随重启变化)。
R2【legacy 迟到写入的判定归属】切换后 check 会比对旧路径哈希;若某会话在切换后仍写入旧路径,
    该条内容"导入 v2"还是"判定为重复"由谁裁定,请指定 owner。
R3【协议本体】以下十条,可 ACK:
    1) 活跃快照只含 §1-§4(当前真相)+ §5 recent tail(journal 缓存,非权威)
    2) 所有记录先落按日 journal,再重建快照
    3) 只有 §1-§4 具规范效力;仅存在于 journal 的内容不是约束、不是待办
    4) 三种行为 fact / task / event;fact、task 按 stable key upsert,值未变即 no-op 不写 journal
    5) 摘要 <= 160 Unicode 字符、整条记录 <= 1024 UTF-8 字节,超限拒写(正文进 ADR/证据文件,只留结论+ref)
    6) tail <= 20 条且 <= 8 KiB,触顶自动裁剪,永不因此拒写
    7) 活跃文件 16 KiB 是 SLO 不是硬限;核心区超限保留事实并告警,永不丢弃
    8) 读取不受限:直接 cat/Read 活跃快照即可;禁止的只有 glob 整个 journal 目录
    9) 唯一写入口 statectl;PreToolUse hook 是写入纪律强制点,非安全边界
   10) 采用新路径 state/v2/,旧路径切换后为 legacy capture,由 check 监控迟到写入

== 4. 切换序列(裁定后执行,需与通知同步)==
 1) 重跑 statectl_import.py --apply(旧文件仍在增长:本会话期间 M2C 由 109,652B 长到 112743B)
 2) 启用 .claude/settings.json.staged → .claude/settings.json(sha 93a7faf6…)
 3) 通知四个活会话:读 state/v2/,写走 statectl
 4) 观察一日;check 无 legacy 迟到写入后,旧路径转只读

注:hook 可能不作用于已在运行的会话(settings 于会话启动读入)。这正是采用新路径的理由——
未加载 hook 的旧会话继续写它知道的旧路径,物理上污染不了 v2,并会被 check 检出。

== 5. 回退 ==
rm -rf state/ 且不启用 hook,即完全回到当前状态。旧文件全程未被修改。

== 6. 明确不在本次范围 ==
- 每日 git seal(会触发 commit 授权,已延后,不在关键路径)
- cursor / catchup / ack / seq 续读协议(降速后 tail 可覆盖一日,暂不需要)
- v5_existence_probe_campaign_v1.py 等代码读取优化(收益远低于状态文件,暂不做)
