#!/usr/bin/env python3
"""statectl — tzb 状态协议 v2 的唯一写入口。

模型:
  - 活跃快照 state/v2/<STREAM>_STATE.md = §1-§4(当前真相) + §5 recent tail(journal 缓存)
  - 所有记录先落按日 journal state/journal/<STREAM>/<YYYY-MM-DD>.md,再重建快照(journal-first / WAL)
  - 只有 §1-§4 具备规范效力;只存在于 journal 的内容不是约束、不是待办
  - fact/task 按 stable key upsert;值未变即 no-op,不写 journal

限额:
  摘要 <= 160 Unicode 字符;整条记录 <= 1024 UTF-8 字节 —— 超限拒写(正文进证据文件,只留摘要+ref)
  tail <= 20 条且 <= 8 KiB —— 触顶自动裁剪,永不拒写
  活跃文件 16 KiB 是 SLO 不是硬限 —— 核心区超限保留事实并告警,永不丢弃
"""
import argparse, datetime, fcntl, hashlib, json, os, re, sys
from contextlib import contextmanager

ROOT = os.environ.get("STATECTL_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMS = ("M2C", "QWEN")
SECTIONS = [
    ("facts",      "1. 当前事实"),
    ("lane",       "2. 归属与 lane"),
    ("constraint", "3. 硬约束与停止线"),
    ("task",       "4. 待办"),
    ("tail",       "5. Recent tail(journal 缓存,非权威)"),
]
SLUGS = [s for s, _ in SECTIONS]
FACT_SLUGS = ("facts", "lane", "constraint")
MAX_SUMMARY_CHARS = 160
MAX_RECORD_BYTES = 1024
TAIL_MAX_RECORDS = 20
TAIL_MAX_BYTES = 8192
ACTIVE_SLO_BYTES = 16384
BANNER = "<!-- GENERATED — 禁止直接 Edit/Write。唯一写入口: tools/statectl.py -->"

def state_path(s):   return os.path.join(ROOT, "state", "v2", f"{s}_STATE.md")
def journal_dir(s):  return os.path.join(ROOT, "state", "journal", s)
def journal_path(s, day): return os.path.join(journal_dir(s), f"{day}.md")
def lock_path(s):    return os.path.join(ROOT, "state", "v2", f".{s}.lock")
def meta_path(s):    return os.path.join(ROOT, "state", "v2", f".{s}.meta.json")

def now():
    return datetime.datetime.now().astimezone()

def today():
    return now().strftime("%Y-%m-%d")

@contextmanager
def stream_lock(s):
    os.makedirs(os.path.dirname(lock_path(s)), exist_ok=True)
    fd = os.open(lock_path(s), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

def atomic_write(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dfd = os.open(d, os.O_RDONLY)
    try: os.fsync(dfd)
    finally: os.close(dfd)

# ---------- 快照解析 ----------

def empty_state(stream):
    body = [BANNER,
            f"<!-- statectl protocol=2 stream={stream} -->",
            "",
            f"# {stream} 权威状态(活跃快照)",
            ""]
    for _, title in SECTIONS:
        body += [f"## {title}", ""]
    return "\n".join(body)

def load(stream):
    p = state_path(stream)
    if not os.path.exists(p):
        text = empty_state(stream)
    else:
        text = open(p, encoding="utf-8").read()
    head, cur, secs = [], None, {s: [] for s in SLUGS}
    order = []
    for line in text.splitlines():
        m = re.match(r"^## (\d+)\.", line)
        if m:
            idx = int(m.group(1)) - 1
            cur = SLUGS[idx] if 0 <= idx < len(SLUGS) else None
            if cur: order.append(cur)
            continue
        (secs[cur] if cur else head).append(line)
    return head, secs

def dump(stream, head, secs, generation):
    head = [l for l in head if not l.startswith("<!-- statectl protocol")]
    if not head or head[0] != BANNER:
        head = [BANNER] + [l for l in head if l != BANNER]
    head = head[:1] + [f"<!-- statectl protocol=2 stream={stream} generation={generation} "
                       f"updated={now().strftime('%Y-%m-%dT%H:%M%z')} -->"] + head[1:]
    out = list(head)
    while out and out[-1] == "": out.pop()
    for slug, title in SECTIONS:
        out += ["", f"## {title}"]
        body = [l for l in secs.get(slug, [])]
        while body and body[0] == "": body.pop(0)
        while body and body[-1] == "": body.pop()
        out += body
    return "\n".join(out).lstrip("\n") + "\n"

def read_meta(stream):
    try: return json.load(open(meta_path(stream), encoding="utf-8"))
    except Exception: return {"generation": 0}

def write_meta(stream, meta):
    atomic_write(meta_path(stream), json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

# ---------- journal ----------

def journal_line(kind, slug, session, key, summary, ref):
    ts = now().strftime("%Y-%m-%dT%H:%M%z")
    parts = [f"- {ts} [{kind}", ]
    tag = f"[{kind}/{slug}]" if slug else f"[{kind}]"
    line = f"- {ts} {tag} <{session}>"
    if key: line += f" `{key}`"
    line += f" — {summary}"
    if ref: line += f" · ref: {ref}"
    return line

def validate(summary, line):
    if len(summary) > MAX_SUMMARY_CHARS:
        die(f"摘要 {len(summary)} 字符 > 上限 {MAX_SUMMARY_CHARS}。"
            f"把正文写进 ADR/证据文件,这里只留结论与 --ref 指针。")
    n = len(line.encode("utf-8"))
    if n > MAX_RECORD_BYTES:
        die(f"整条记录 {n} 字节 > 上限 {MAX_RECORD_BYTES}。缩短摘要或改用更短的 ref 路径。")

def append_journal(stream, line):
    p = journal_path(stream, today())
    os.makedirs(os.path.dirname(p), exist_ok=True)
    exists = os.path.exists(p)
    with open(p, "a", encoding="utf-8") as f:
        if not exists:
            f.write(f"# {stream} journal {today()}\n\n")
        f.write(line + "\n")
        f.flush(); os.fsync(f.fileno())
    return p

def journal_files(stream):
    d = journal_dir(stream)
    if not os.path.isdir(d): return []
    return sorted(f for f in os.listdir(d) if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", f))

def recent_records(stream, limit=TAIL_MAX_RECORDS, max_bytes=TAIL_MAX_BYTES):
    out = []
    total = 0
    anchor = re.compile(r"^- \d{4}-\d{2}-\d{2}")
    for fn in reversed(journal_files(stream)):
        # 只取记录锚行(带日期);多行记录的续行留在 journal 中,不进 tail 缓存
        lines = [l for l in open(os.path.join(journal_dir(stream), fn), encoding="utf-8").read().splitlines()
                 if anchor.match(l)]
        for l in reversed(lines):
            b = len(l.encode("utf-8")) + 1
            if len(out) >= limit or total + b > max_bytes:
                return list(reversed(out))
            out.append(l); total += b
    return list(reversed(out))

def today_records(stream):
    p = journal_path(stream, today())
    if not os.path.exists(p): return []
    return [l for l in open(p, encoding="utf-8").read().splitlines()
            if re.match(r"^- \d{4}-\d{2}-\d{2}", l)]

# ---------- 写入 ----------

def writers_registry():
    """state/v2/WRITERS.json:tzb-fe 单写的 role→sessionId 注册表(裁定 A2)。"""
    try: return json.load(open(os.path.join(ROOT, "state", "v2", "WRITERS.json"), encoding="utf-8"))
    except Exception: return {}

def check_writer(stream, session):
    """保留既有硬边界:M2C 唯二写者 = tzb-fe + M2C 执行会话;QWEN 仅其 owner。
    (M2C_STATE.md 头部写入权收口 2026-08-28;QWEN 永久硬边界 #1)

    信任边界(裁定 A3):`--session` 取值是**角色串**(重启不变),且是**自声明、未验证**的
    字符串。本检查与 hook 同属写入纪律层,不是访问控制,禁止日后被引用为安全属性。
    """
    reg = writers_registry().get("roles", {})
    allowed = [r for r, v in reg.items() if stream in v.get("streams", [])] or read_meta(stream).get("writers")
    if allowed and session not in allowed:
        die(f"角色 `{session}` 不在 {stream} 的写者名单 {allowed} 内。"
            f"这是既有硬边界,不是本协议新增;要改名单请走 tzb-fe 裁定。")

def die(msg, code=2):
    print(f"statectl: 拒绝: {msg}", file=sys.stderr)
    sys.exit(code)

def fact_line(key, summary, ref):
    l = f"- `{key}` — {summary}"
    if ref: l += f" · ref: {ref}"
    return l

def upsert(secs, slug, key, line):
    body = secs.setdefault(slug, [])
    pat = re.compile(r"^- `" + re.escape(key) + r"`\s")
    for i, l in enumerate(body):
        if pat.match(l):
            if l.strip() == line.strip():
                return "unchanged"
            body[i] = line
            return "updated"
    body.append(line)
    return "added"

def commit(stream, secs, head, kind, slug, session, key, summary, ref, action):
    jline = journal_line(kind, slug, session, key, summary, ref)
    validate(summary, jline)
    append_journal(stream, jline)                      # 1) journal 先落盘 + fsync (WAL)
    secs["tail"] = recent_records(stream)              # 2) tail 从 journal 重建
    meta = read_meta(stream); meta["generation"] = meta.get("generation", 0) + 1
    if key and key in meta.get("grandfathered", []):
        meta["grandfathered"] = [k for k in meta["grandfathered"] if k != key]
    text = dump(stream, head, secs, meta["generation"])
    atomic_write(state_path(stream), text)             # 3) 原子替换快照
    write_meta(stream, meta)
    n = len(text.encode("utf-8"))
    print(f"statectl: {action}  generation={meta['generation']}  active={n}B  tail={len(secs['tail'])}条")
    if n > ACTIVE_SLO_BYTES:
        print(f"statectl: 告警 OVERSIZE_CORE: 活跃文件 {n}B > SLO {ACTIVE_SLO_BYTES}B。"
              f"事实已保留,请安排一次语义压缩。", file=sys.stderr)

def cmd_fact(a):
    check_writer(a.stream, a.session)
    if a.section not in FACT_SLUGS: die(f"--section 必须是 {'/'.join(FACT_SLUGS)}")
    with stream_lock(a.stream):
        head, secs = load(a.stream)
        r = upsert(secs, a.section, a.key, fact_line(a.key, a.summary, a.ref))
        if r == "unchanged":
            print(f"statectl: unchanged  `{a.key}` 值未变,不写 journal(no-op)"); return
        commit(a.stream, secs, head, "FACT", a.section, a.session, a.key, a.summary, a.ref, r)

def cmd_task(a):
    check_writer(a.stream, a.session)
    with stream_lock(a.stream):
        head, secs = load(a.stream)
        r = upsert(secs, "task", a.key, fact_line(a.key, a.summary, a.ref))
        if r == "unchanged":
            print(f"statectl: unchanged  `{a.key}` 值未变,不写 journal(no-op)"); return
        commit(a.stream, secs, head, "TASK", "task", a.session, a.key, a.summary, a.ref, r)

def cmd_done(a):
    check_writer(a.stream, a.session)
    with stream_lock(a.stream):
        head, secs = load(a.stream)
        pat = re.compile(r"^- `" + re.escape(a.key) + r"`\s")
        before = len(secs.get("task", []))
        secs["task"] = [l for l in secs.get("task", []) if not pat.match(l)]
        if len(secs["task"]) == before:
            die(f"§4 待办里没有 key `{a.key}`")
        commit(a.stream, secs, head, "DONE", "task", a.session, a.key,
               a.summary or f"完成 {a.key}", a.ref, "removed")

def cmd_event(a):
    check_writer(a.stream, a.session)
    with stream_lock(a.stream):
        head, secs = load(a.stream)
        probe = f"<{a.session}> — {a.summary}" + (f" · ref: {a.ref}" if a.ref else "")
        for l in today_records(a.stream):
            if l.endswith(probe.split("> — ", 1)[1]) and f"<{a.session}>" in l and "[EVENT" in l:
                print("statectl: duplicate  当日同会话同内容已记录,不重复写入(no-op)"); return
        commit(a.stream, secs, head, "EVENT", None, a.session, None, a.summary, a.ref, "logged")

def cmd_render(a):
    with stream_lock(a.stream):
        head, secs = load(a.stream)
        secs["tail"] = recent_records(a.stream)
        meta = read_meta(a.stream); meta["generation"] = meta.get("generation", 0) + 1
        atomic_write(state_path(a.stream), dump(a.stream, head, secs, meta["generation"]))
        write_meta(a.stream, meta)
        print(f"statectl: tail 已从 journal 重建,{len(secs['tail'])} 条")

def cmd_check(a):
    bad = 0
    for stream in ([a.stream] if a.stream else STREAMS):
        p = state_path(stream)
        print(f"— {stream} —")
        if not os.path.exists(p):
            print("  ! 活跃快照不存在"); bad += 1; continue
        text = open(p, encoding="utf-8").read()
        n = len(text.encode("utf-8"))
        for slug, title in SECTIONS:
            c = len(re.findall(r"^## " + re.escape(title), text, re.M))
            if c != 1:
                print(f"  ! 章节 '{title}' 出现 {c} 次(应为 1)"); bad += 1
        print(f"  活跃文件 {n}B  ({'OK' if n <= ACTIVE_SLO_BYTES else 'OVERSIZE_CORE 告警'})")
        head, secs = load(stream)
        jr = recent_records(stream)
        if secs.get("tail", []) != jr:
            print("  ! tail 与 journal 漂移(可能崩溃在 journal 落盘之后、快照替换之前)。修复: statectl render")
            bad += 1
        else:
            print(f"  tail 与 journal 一致,{len(jr)} 条")
        gf = set(read_meta(stream).get("grandfathered", []))
        ngf = 0
        for slug in FACT_SLUGS + ("task",):
            for l in secs.get(slug, []):
                if not l.strip() or len(l.encode("utf-8")) <= MAX_RECORD_BYTES: continue
                k = re.match(r"^- `([^`]+)`", l)
                if k and k.group(1) in gf: ngf += 1; continue
                print(f"  ! 超长记录 {len(l.encode('utf-8'))}B in §{slug}: {l[:50]}…"); bad += 1
        if ngf: print(f"  超限但 grandfathered 的导入记录 {ngf} 条(裁定 §3 修订,不计违规)")
        meta = read_meta(stream)
        lg = meta.get("legacy")
        if lg and os.path.exists(lg["path"]):
            cur = hashlib.sha256(open(lg["path"], "rb").read()).hexdigest()
            if cur != lg["sha256"]:
                print(f"  ! legacy 路径 {lg['path']} 在导入后被改动 → 需 legacy-reconcile")
                bad += 1
            else:
                print("  legacy 路径无迟到写入")
    sys.exit(1 if bad else 0)

def main():
    ap = argparse.ArgumentParser(prog="statectl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def common(p, key=True):
        p.add_argument("stream", choices=STREAMS)
        p.add_argument("--session", default=os.environ.get("STATECTL_SESSION"), required=False)
        if key: p.add_argument("--key", required=True)
        p.add_argument("--summary", required=False)
        p.add_argument("--ref", default="")
    p = sub.add_parser("fact", help="更新 §1-§3 当前真相(keyed upsert)"); common(p)
    p.add_argument("--section", default="facts"); p.set_defaults(fn=cmd_fact)
    p = sub.add_parser("task", help="更新 §4 待办(keyed upsert)"); common(p); p.set_defaults(fn=cmd_task)
    p = sub.add_parser("done", help="从 §4 移除待办"); common(p); p.set_defaults(fn=cmd_done)
    p = sub.add_parser("event", help="只写 journal,不改变当前真相"); common(p, key=False); p.set_defaults(fn=cmd_event)
    p = sub.add_parser("render", help="从 journal 重建 tail"); p.add_argument("stream", choices=STREAMS); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("check", help="校验快照/journal 一致性"); p.add_argument("stream", nargs="?", choices=STREAMS); p.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    if a.cmd in ("fact", "task", "done", "event"):
        if not a.session: die("需要 --session(或设 STATECTL_SESSION)")
        if a.cmd != "done" and not a.summary: die("需要 --summary")
    a.fn(a)

if __name__ == "__main__":
    main()
