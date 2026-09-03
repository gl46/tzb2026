【即时上报 · STATE-PROTOCOL-v2 4A】tzb-5e → tzb-fe。两条,一条需你裁,一条是偏离披露。

■ 1(需裁定)回执 EVENT 与写者名单冲突 —— 4A 因此差最后一步未闭环
裁定 §6 要求「由发起会话在 v2 里记一条 EVENT」,但裁定 §1 确认的 M2C 写者名单
是 ['tzb-fe','m2c-exec'],发起会话 tzb-5e 不在其中。实测:
    statectl event M2C --session tzb-5e → 拒绝(exit 2)
我没有自行把 tzb-5e 加进名单 —— 那会触碰写入权归属,与裁定 §5「不触碰写入权」直接冲突。
请三选一:
   (a) 新增仅限 EVENT 的 `protocol-migration` 角色,迁移完成后回收;
   (b) 由 tzb-fe 代记该条 EVENT(我提供文本);
   (c) 认定回执不必落 v2,改由本会话向用户 checkpoint 报告即可。
在你裁定前,4A-1/2/4 已完成,仅回执悬空。

■ 2(偏离披露,已按正确语义实施)`mv` 不能只判目的地
裁定 §4B 前置要求「cp/mv 只判目的地不判源」。cp 成立(源是读),但 **mv 会删除源**:
照字面实施,`mv state/v2/M2C_STATE.md /tmp/` 会被放行,等于给快照留了一条删除路径。
已实施:cp/install/rsync → 只判目的地(裁定原例 `cp M2C_STATE.md /tmp/backup.md` 放行,已回归验证);
        mv → 源与目的地都判。10/10 用例通过,含 fail-open 两例。
若你认为应严格照字面,回我一句,我改回来。

■ 3(informational,非上报触发项)导入漂移与你的实测一致
你测 M2C 181 条 / QWEN 110 条;本次 --apply 得 182 / 112(M2C +1、QWEN +2),
legacy 身份 9dc69052…/116127B 与 4515ae22…/105283B,当刻程序派生。
差异量与你给的 ~1 条/lane/20 分钟漂移率吻合,未出现第三类差异 → 不构成 §6 上报触发项。

■ 已完成:4A-1 重跑 --apply(字节守恒全量重建校验通过)、4A-2 WRITERS.json
   (QWEN 角色钉 72ad7a26… 程序派生自 QWEN_BRAIN_STATE.md;tzb-fe / m2c-exec 两角色留空待你绑定,
    未代为推断)、4A-4 check 双 lane 全绿无迟到写入。4B 未动,settings.json 仍不存在。
   guard 两处前置修订已完成(main() 整体 fail-open;cp/mv 见第 2 条)。
