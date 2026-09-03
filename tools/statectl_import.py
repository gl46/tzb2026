#!/usr/bin/env python3
"""一次性 legacy → v2 迁移。默认 dry-run;--apply 才落盘。

原则:写回区逐字节守恒进 journal;核心区 §1-§4 只"附加 stable key",不改写一个字。
超过限额的既有核心行保留并由 check 告警(OVERSIZE_CORE),不截断、不丢弃。
"""
import hashlib, json, os, re, shutil, sys

ROOT = os.environ.get("STATECTL_ROOT", "/Users/gl/tzb")
APPLY = "--apply" in sys.argv

PLAN = {
 "M2C": {
  "legacy": "M2C_STATE.md", "writeback_at": "## 5.",
  "writers": ["tzb-fe", "m2c-exec"],
  "map": [("## 1.", "facts", ["chain.head","campaign.12shot","host.formal_canonical",
                              "ruling.r132_39_option_a","design.terminalization_fix"]),
          ("## 2.", "lane",  ["lane.m2c_exec","lane.tzb_fe","lane.qwen_brain"]),
          ("## 3.", "constraint", ["stopline.impl_phase","stopline.human_gates",
                                   "discipline.hash_and_citation","stopline.compaction_ladder"]),
          ("## 4.", "task",  ["todo.m2c_exec","todo.tzb_fe","todo.user"])]},
 "QWEN": {
  "legacy": "QWEN_BRAIN_STATE.md", "writeback_at": "## 6.",
  "writers": ["qwen-brain-owner"],
  "map": [("## 1.", "facts", ["archive.path","archive.identity","archive.prefix_equal","archive.read_rule"]),
          ("## 2.", "facts", ["lane.clone","auth.user_training","config.node2_strict","env.node2",
                              "pkg.immutable","snapshot.model","data.train_reconstructed","freeze.scientific"]),
          ("## 3.", "facts", ["smoke32.pass","probe.promoted","adapter.smoke","gpu.evidence","final.not_started"]),
          ("## 4.", "constraint", ["bound.no_write_governed","bound.no_isaac","bound.baseline_endpoint",
                                   "bound.shared_gpu","bound.no_service","bound.no_sweep","bound.no_push",
                                   "bound.immutable_pkg_runtime","bound.adapter_publish"]),
          ("## 5.", "task", ["todo.two_epoch","todo.freeze_verify","todo.post_rehash","todo.icl_lane_isolation"])]},
}

def bullets(block):
    """返回 (原文行, 内容) 列表;支持 '- x' 与 '1. x' 两种。"""
    out = []
    for l in block.splitlines():
        m = re.match(r"^(?:-|\d+\.)\s+(.*)$", l)
        if m and m.group(1).strip():
            out.append((l, m.group(1).strip()))
    return out

def section_block(text, marker, nxt):
    i = text.index(marker)
    j = text.index(nxt, i) if nxt else len(text)
    return text[i:j]

rc = 0
for stream, cfg in PLAN.items():
    lp = os.path.join(ROOT, cfg["legacy"])
    raw = open(lp, encoding="utf-8").read()
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    print(f"\n{'='*64}\n== {stream}  {cfg['legacy']}  {len(raw.encode())}B  sha={sha[:12]}…")

    # ---- 写回区 → journal,逐字节守恒 ----
    wb = raw[raw.index(cfg["writeback_at"]):]
    wb_lines = wb.splitlines()
    # 记录 = 一条日期锚行 + 其后所有续行(直到下一条锚行)。多行记录整体保留。
    preamble, recs = [], []          # recs: [(day, [lines...])]
    for l in wb_lines:
        m = re.match(r"^- (\d{4}-\d{2}-\d{2})", l)
        if m: recs.append((m.group(1), [l]))
        elif recs: recs[-1][1].append(l)
        else: preamble.append(l)
    byday = {}
    for day, ls in recs: byday.setdefault(day, []).extend(ls)
    multi = sum(1 for _, ls in recs if len(ls) > 1)
    cont  = sum(len(ls) - 1 for _, ls in recs)
    print(f"   写回区 {len(wb.encode())}B / {len(wb_lines)} 行 → 记录 {len(recs)} 条"
          f"(其中 {multi} 条多行,续行 {cont} 行)→ {len(byday)} 个日文件 {sorted(byday)}")
    # 守恒:preamble + 全部记录行 必须逐字节重建整个写回区
    rebuilt = "\n".join(preamble + [l for _, ls in recs for l in ls])
    if rebuilt != wb.rstrip("\n"):
        print("   ! 字节守恒失败:重建结果与原写回区不一致"); rc = 1
    else:
        print(f"   ✓ 字节守恒:preamble({len(preamble)} 行)+ 全部记录行 逐字节重建写回区")
    if preamble and any(l.strip() and not l.startswith("## ") for l in preamble):
        print(f"   · 首条记录之前的 preamble 将原样写入当日 journal 顶部")

    # ---- 核心区 → 附 key ----
    core_lines, oversize = {}, []
    for k, (marker, slug, keys) in enumerate(cfg["map"]):
        nxt = cfg["map"][k+1][0] if k+1 < len(cfg["map"]) else cfg["writeback_at"]
        bs = bullets(section_block(raw, marker, nxt))
        if len(bs) != len(keys):
            print(f"   ! {marker} 条目 {len(bs)} 条,但 key 表给了 {len(keys)} 个 —— 需修表"); rc = 1
        for (orig, content), key in zip(bs, keys):
            line = f"- `{key}` — {content}"
            core_lines.setdefault(slug, []).append(line)
            if len(line.encode()) > 1024: oversize.append((key, len(line.encode())))
    for slug in ("facts","lane","constraint","task"):
        n = len(core_lines.get(slug, []))
        if n: print(f"   §{slug}: {n} 条")
    if oversize:
        print(f"   ! 超 1024B 的既有核心行(保留,由 check 告警,待后续语义压缩):")
        for k, n in oversize: print(f"       {n}B  {k}")

    if not APPLY: continue
    # ---- 落盘 ----
    cap = os.path.join(ROOT, "state", "legacy-capture"); os.makedirs(cap, exist_ok=True)
    shutil.copy2(lp, os.path.join(cap, f"{cfg['legacy'][:-3]}.{sha[:12]}.md"))
    jd = os.path.join(ROOT, "state", "journal", stream); os.makedirs(jd, exist_ok=True)
    for day, ls in byday.items():
        with open(os.path.join(jd, f"{day}.md"), "w", encoding="utf-8") as f:
            f.write(f"# {stream} journal {day}(自 {cfg['legacy']} §写回区 逐字节导入)\n\n")
            if day == min(byday) and preamble:
                f.write("\n".join(preamble).strip() + "\n")
            f.write("\n".join(ls) + "\n")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import statectl as S
    head, secs = S.load(stream)
    head = [S.BANNER, f"<!-- 自 {cfg['legacy']} 迁移 sha={sha} -->", "",
            f"# {stream} 权威状态(活跃快照,协议 v2)", "",
            f"> **只有 §1-§4 具规范效力。**§5 是 journal 缓存;仅存在于 journal 的内容"
            f"**不是约束、不是待办、不是当前真相**。完整历史见 state/journal/{stream}/。",
            f"> 唯一写入口 tools/statectl.py。写者角色 {cfg['writers']}(角色串,重启不变;"
            f"绑定见 state/v2/WRITERS.json)。`--session` 自声明未验证,属写入纪律层,**非安全属性**。",
            f"> 导入的历史记录 grandfathered,不受 1024B/160 字符上限约束(tzb-fe 裁定 2026-08-30 §3)。"]
    for slug, ls in core_lines.items(): secs[slug] = ls
    secs["tail"] = S.recent_records(stream)
    S.atomic_write(S.state_path(stream), S.dump(stream, head, secs, 1))
    gf = [m.group(1) for ls in core_lines.values() for l in ls
          for m in [re.match(r"^- `([^`]+)`", l)] if m]
    S.write_meta(stream, {"generation": 1, "writers": cfg["writers"],
                          "grandfathered": gf,
                          "legacy": {"path": lp, "sha256": sha}})
    print(f"   ✓ 已写入 {S.state_path(stream)}  "
          f"{len(open(S.state_path(stream),encoding='utf-8').read().encode())}B")
print(f"\n{'dry-run 完成(未落盘)。加 --apply 执行。' if not APPLY else '迁移已落盘。'}")
sys.exit(rc)
