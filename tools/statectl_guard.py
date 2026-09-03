#!/usr/bin/env python3
"""PreToolUse 反射拦截器:把对状态文件的直写导回 statectl。

定位:这是写入纪律的强制点,不是安全边界(同一 OS 用户下可经 python/mv/cp 间接绕过)。
威胁模型是"压缩后凭反射直接 Edit",不是对手。因此 Bash 只做窄黑名单,读一律放行。
"""
import json, os, re, sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or "/Users/gl/tzb"
PROTECTED_DIRS = [os.path.join(ROOT, "state", "v2"), os.path.join(ROOT, "state", "journal")]
LEGACY = [os.path.join(ROOT, "M2C_STATE.md"), os.path.join(ROOT, "QWEN_BRAIN_STATE.md")]
REDIRECT = re.compile(r">>?\s*([^\s|;&]+)")
# cp/install/rsync 的源是读,只有目的地(最后一个实参)是写 —— tzb-fe 裁定 §4B 前置修订。
# mv 例外:它会删除源,故源与目的地都判。(对裁定字面的偏离,已上报)
COPYONLY = re.compile(r"\b(?:cp|install|rsync)\b([^|;&]*)")
MOVE     = re.compile(r"\bmv\b([^|;&]*)")
DESTRUCT = re.compile(r"\b(?:tee|rm|truncate|dd|shred)\b([^|;&]*)|\bsed\s+-i\b([^|;&]*)")

def write_targets(cmd):
    """返回该命令中真正会被写入的路径 token。"""
    out = []
    out += REDIRECT.findall(cmd)
    for seg in COPYONLY.findall(cmd):
        args = [t for t in re.findall(r"[^\s]+", seg) if not t.startswith("-")]
        if args: out.append(args[-1])          # 只判最后一个实参 = 目的地
    for seg in MOVE.findall(cmd):
        out += [t for t in re.findall(r"[^\s]+", seg) if not t.startswith("-")]  # mv 源亦被销毁
    for m in DESTRUCT.finditer(cmd):
        seg = m.group(1) or m.group(2) or ""
        out += [t for t in re.findall(r"[^\s]+", seg) if not t.startswith("-")]
    return out

def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)

def norm(p, cwd):
    if not p: return ""
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd or ROOT, p))

def classify(path):
    if not path: return None
    for d in PROTECTED_DIRS:
        if path == d or path.startswith(d + os.sep): return "v2"
    if path in [os.path.realpath(p) for p in LEGACY]: return "legacy"
    return None

USE = ("唯一写入口是 tools/statectl.py。用:\n"
       "  python3 tools/statectl.py fact  <M2C|QWEN> --section facts|lane|constraint --key K --summary S [--ref R]\n"
       "  python3 tools/statectl.py task  <M2C|QWEN> --key K --summary S [--ref R]\n"
       "  python3 tools/statectl.py done  <M2C|QWEN> --key K\n"
       "  python3 tools/statectl.py event <M2C|QWEN> --summary S [--ref R]\n"
       "(会话名用 --session 或 STATECTL_SESSION。读取不受限制,直接 cat/Read 即可。)")

def main():
    try: payload = json.load(sys.stdin)
    except Exception: sys.exit(0)
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or ROOT

    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        kind = classify(norm(ti.get("file_path") or ti.get("notebook_path"), cwd))
        if kind == "v2":
            deny("状态快照与 journal 是 statectl 生成文件,禁止直接 " + tool + "。\n" + USE)
        if kind == "legacy":
            deny("该路径已是 legacy capture(协议 v2 已切换),写入不会进入当前真相。\n" + USE)
        sys.exit(0)

    if tool == "Bash":
        cmd = ti.get("command", "") or ""
        for tok in write_targets(cmd):
            if classify(norm(tok.strip("\"'").lstrip("~"), cwd)):
                deny(f"检测到对状态文件的 shell 写入(目标 `{tok[:60]}`)。\n" + USE)
    sys.exit(0)

if __name__ == "__main__":
    # fail-open:tzb-fe 裁定 §3 第 9 条补强。deny 走 sys.exit(0) + stdout,
    # 因此 SystemExit 必须放行;其余任何异常一律放行,绝不 fail-closed。
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        sys.exit(0)
