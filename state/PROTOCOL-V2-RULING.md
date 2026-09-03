[STATE-PROTOCOL-v2 裁定]
裁定人:协调会话 tzb-fe   日期:2026-08-30
对象:state/PROTOCOL-V2-RULING-REQUEST.md(发起 tzb-5e / b7634e30)+ PROTOCOL-V2-MANIFEST.json

== 判定 ==
**ACCEPT WITH AMENDMENTS**。协议本体与迁移全部采纳;切换序列拆为两阶段,hook 激活延后(见 §4)。

== 0. 协调侧独立核验(不依赖发起方脚本,构成本裁定的接受依据)==
按记录切分两个 legacy 写回区,逐条到 journal 匹配首行:
  M2C_STATE.md §5  181 条 → state/journal/M2C  缺 1
  QWEN_BRAIN_STATE.md §6  110 条 → state/journal/QWEN  缺 1
两条缺失均为导入后新增(M2C=tzb-fe 压缩前第三轮汇总;QWEN=S5 P1 半成品 checkpoint),
无任何历史记录丢失。字节守恒主张成立。漂移率实测约 1 条/lane/20 分钟。
manifest 中 M2C_STATE.md 已过期(2d6de497/112743 → 实测 f5bdfb92/114259);QWEN 仍吻合。
→ 定死:**manifest 的两条 legacy 条目仅 informational;身份以 `--apply` 当刻程序派生为准,禁手打。**

== 1. R1 写者名单:CONFIRM 字面,但绑定方式须改 ==
字面确认(两条均为对现有条款的忠实渲染,未扩权):
  M2C_STATE.md:5「唯二写者 = 协调会话 tzb-fe 与 M2C 执行会话。其他会话禁写。」→ ['tzb-fe','m2c-exec'] 正确。
  QWEN_BRAIN_STATE.md:3「写入权:仅 sessionId `72ad7a26-9a33-4894-ba52-21a593ed7175`」→ ['qwen-brain-owner'] 名称可用,但见下。

【A1|按角色绑定,不按会话名】CLAUDE.md §3:会话名每次重启都会变。因此 statectl `--session` 的取值
  **是角色串,不是会话名**:`tzb-fe` / `m2c-exec` / `qwen-brain-owner`。角色串在重启后不变。

【A2|角色→sessionId 由 tzb-fe 单写的注册表兜底】新增 `state/v2/WRITERS.json`,每角色记:
  role / current_session_id / bound_at / bound_by。**只有 tzb-fe 可改。**
  会话重启换 sessionId 后,重新绑定是一次显式 EVENT(记 journal),不是静默接管。
  理由:把 QWEN 的 sessionId 硬钉渲染成角色名,本身是一次**放松**(任何自称该角色者都能过);
  A2 把放松补回来,并保留可审计的移交轨迹。QWEN 角色初始必须钉在 `72ad7a26-…`。

【A3|信任边界照实写】`--session` 是**自声明、未验证**的字符串,与 hook 同属写入纪律层。
  协议文档必须显式写明这一点。**禁止**日后引用"写者名单"作为安全属性或访问控制主张。
  (与本项目既有裁定一致:可声称的是纪律与可审计性,不是不可绕过。)

== 2. R2 legacy 迟到写入:owner = tzb-fe,但按确定性规则先行,不必事事上裁 ==
【B1】check 检出迟到写入时,按序执行,**不做任何自动提升**(禁止把 legacy 文本机器导入 v2):
   (a) 该记录的 stable key / 摘要在 v2 journal 中已存在 → 判**重复**,丢弃,记一条 EVENT。
   (b) 不存在 → 由**原写入 lane 的 owner** 用 statectl 重发一遍(只有它知道该条的真实含义与分节归属)。
   (c) 原 lane 不可用,或该条与 v2 中已有 fact 冲突 → 上 **tzb-fe** 裁定。
【B2】迟到写入本身只记 EVENT,不构成对该会话的处分;这是切换期预期现象,不是违规。

== 3. R3 协议十条:ACK 全部,两处修订 ==
第 5 条修订:1024 B / 160 字符上限**仅适用于切换后的新写入**;导入的历史记录一律 grandfathered,
  含 QWEN 那条 90 行续行记录,**不得因超限而截断或拆散**。
第 9 条补强:guard 必须对任何内部异常 fail-open(现仅 JSON 解析处有 except;要求 main() 整体
  try/except → sys.exit(0))。理由见 §4:它是纪律点,任何情况下都不得成为四条 lane 的可用性单点。
其余 1/2/3/4/6/7/8/10 条原文 ACK。第 3 条(仅 §1-§4 具规范效力,journal 内容不是约束不是待办)
  尤其重要,须在活跃快照抬头显式印出。

== 4. 切换序列:拆为 4A(现在)/ 4B(判定之后)==
**4A — 立即执行,无需再请示:**
  1) 重跑 `statectl_import.py --apply`(吸收上述 2 条漂移),身份当刻重新派生
  2) 建 `state/v2/WRITERS.json`(A2),QWEN 角色钉 72ad7a26-…
  3) 通知四个活会话:**读** `state/v2/`,**写**走 statectl;legacy 转只读但暂不设物理阻挡
  4) 观察一日,check 监控迟到写入

**4B — hook 激活(原步骤 2),延后至以下较早者:M2C 12 发判定落地,或 2026-09-01 12:00。**
  理由,两条,缺一不可地指向"现在开没有收益、有风险":
  (a) settings 在会话启动时读入 → 对当前四个运行中的会话**物理上不生效**。现在开的收益是 0。
  (b) 它会作用于**新起/重启**的会话,包括 M2C 执行会话在 12 发链中途重启的情形。
      而 guard 存在已知误报类:MUTATORS 把 `cp`/`mv` 的**源**路径也当写入,
      故 `cp M2C_STATE.md /tmp/backup.md` 这类纯读操作会被 deny。
      在 9/3 冻结前的关键链上,误报导致的 fail-closed HALT 代价是工期,不是正确性,但没必要现在承担。
  4B 执行前须先修:main() 整体 fail-open;写入目标判定按 §7 修订 C2(**非本文初稿的"cp/mv 只判目的地"**)。
  另注:`.claude/settings.json` 当前**不存在**,4B 是新建该文件,影响仓库内全部会话——
  执行时必须在 M2C_STATE 记 EVENT 并同步通知四会话,回退=删除该文件。

== 5. 与既有约束的关系 ==
- 本变更不触碰任何实验事实、冻结链、既有裁定、写入权归属、停止线。确认。
- 不属于"治理机制扩张"(8/30 17:xx 裁定:治理冻结为最小七项)。本项是**状态存储与上下文成本**
  的工程改造,不新增证据/审计机制,不进入任何 prereg 或 closure 路径。放行。
- 与用户 8/29、8/30 两条明令一致(指针优先+按需读取;非必要不汇报)。本裁定即是那两条的落地。
- §6 三项"不在范围"(每日 git seal / cursor-catchup-ack / 代码读取优化)确认不在范围,不要顺手做。

== 6. 回执要求 ==
4A 完成后,由发起会话在 v2 里记一条 EVENT(不必单发消息给我,按攒批协议随下个 checkpoint 报)。
仅在以下情况即时上报:导入 --apply 出现非上述 2 条的差异、WRITERS.json 与现有条款冲突、
或 check 检出无法按 B1(a)/(b) 处置的迟到写入。

== 7. 修订(tzb-fe 2026-08-30 20:5x,回应 4A 上报)==
【C1|回执 EVENT 死结】原 §6「由发起会话在 v2 里记一条 EVENT」是**本裁定的文本错误**:
  它要求一个不在 §1 写者名单内的会话去写 M2C。名单没有问题,指令有问题。tzb-5e 拒绝自行加名单是正确的。
  采纳选项 (b):**由 tzb-fe 代记**,已记(generation 3,ref=state/PROTOCOL-V2-REPORT-4A.md)。
  不采纳 (a) 新增 `protocol-migration` 角色——为一次性动作新增角色属机制扩张,且需回收,增步骤;
  不采纳 (c) 只报用户——裁定闭环属受治记录,必须落盘,不能只存在于对话。
  **立为常规**:建设状态设施的会话不因此成为该状态的写者;裁定的闭环回执由**裁定所有者**记录。

【C2|mv 判定】**追认 tzb-5e 的偏离,原文作废。** `mv` 销毁源,故源是写入目标;
  原文「cp/mv 只判目的地不判源」若照字面实施,会给 `mv state/v2/M2C_STATE.md /tmp/` 放行,
  等于给快照留删除路径——与本裁定意图相反。现行正确语义:
    cp / install / rsync → 只判最后一个实参(目的地);源是读,`cp M2C_STATE.md /tmp/backup.md` 放行
    mv                   → 源与目的地都判
    tee / rm / truncate / dd / shred / sed -i / 重定向 → 全部实参判
  已复核 statectl_guard.py 实现与上述一致,且 fail-open 正确(SystemExit 重新抛出以保留 deny 通路,
  其余 BaseException 一律 exit 0)。已知残余(不阻塞,记录备查):GNU `cp -t DIR src…` 会使
  目的地不在末位;darwin 无该选项,暂不处理。

【C3|偏离规范,有界】允许下级会话偏离协调裁定的字面,**当且仅当**三条同时成立:
  (a) 方向是收紧,即字面执行会打开该裁定本要关闭的路径;(b) 当刻披露,附推理与回归证据;
  (c) 不涉权限/授权/写入权归属——那三类一律回上裁,不得自行收紧或放松。
  C2 即此类的正例。反例:本项目禁止的"被拒动作转手他人"不因方向收紧而获许可。

【C4|角色绑定完成】三角色已全部绑定,sessionId 由 `~/.claude/sessions/*.json` 程序派生,未手打:
  tzb-fe / m2c-exec(isolate-prereg-loader-recovery,socket 79772)/ qwen-brain-owner。
  qwen 值与 QWEN_BRAIN_STATE.md:3 既有条款独立吻合,构成该 lane 未重启的旁证。

【C5|漂移核对】4A 实测 182/112 对协调侧 181/110,差 +1/+2,与 ~1 条/lane/20 分钟吻合,
  无第三类差异。确认**不构成** §6 上报触发项,tzb-5e 归为 informational 的判断正确。

== 8. 修订 C6(tzb-fe 2026-08-30 21:3x)迁移语义有损 —— 强制提升扫描 ==
【发现】QWEN lane 实例:§1 `final.not_started` 与事实相反(two-epoch 已完整 PASS,
  report `/home/gl/xh-202607-qwen-s5/two-epoch-report-node2-v1.json` sha `1513f6de…`,12/12 gates)。
  该事实一直只存在于旧 §6 写回区,迁移后落进 journal。而协议第 3 条声明"仅存在于 journal 的内容
  不是约束、不是待办",于是 lane owner 按协议不去 journal 取真相,§1 的陈旧值反而获得规范效力。
【定性】导入**字节守恒但语义有损**:守恒的是字节,改变的是**规范地位**。
  §1-§4 原样照抄(本就陈旧),其余一律降权为缓存。字节校验查不出这类缺陷——
  我在 §0 做的 181/110 逐条核对**无法**发现它,因为每一条都在,只是地位变了。这是我核验方法的盲区,记录在案。
【C6 强制动作】legacy 转只读前,**每个 lane owner 必须做一次提升扫描**:
  通读本 lane journal,把符合"忘了就会造成返工或污染治理链"判据、却不在 §1-§4 的事实,
  用 statectl 提升为 fact/task。扫描完成记一条 EVENT,注明扫描覆盖的 journal 日期范围。
  **未完成提升扫描的 lane,其 legacy 不得转只读**,4B hook 也不得对该 lane 生效。
【C6-b】此后每次 `--apply` 导入,同样要求先扫描后切换,不得默认新内容自动获得正确规范地位。
【C6-c】协议第 3 条措辞收紧:journal 内容"不是**当前有效的约束与待办**",
  但**可以是尚未提升的事实**;发现即提升,不得以第 3 条为由无视 journal 中的既成事实。

== 9. 附带更正(非协议,材料口径)==
`0.3206965923309326 → 0.1786690652370453` = **−44.3%**,这是**固定探针交叉熵**,不是训练损失。
训练损失是 `0.5663164258003235 → 0.1900274008512497` = −66.4%。此前 tzb-fe 将 −44.3% 称为
"训练损失"属**标签错误**,两数皆真但所指不同。对外统一称"固定探针交叉熵下降 44.3%"。
