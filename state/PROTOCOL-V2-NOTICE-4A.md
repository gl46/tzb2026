【STATE-PROTOCOL-v2 切换通知 · 4A】发起 tzb-5e,依 tzb-fe 2026-08-30 裁定
裁定全文 state/PROTOCOL-V2-RULING.md(指针优先,只读这一个)。身份 state/PROTOCOL-V2-MANIFEST.json。

从现在起:
  读 → state/v2/M2C_STATE.md(12543B) / state/v2/QWEN_STATE.md(15372B)
       直接 cat/Read 即可,读取不受任何限制。禁的只有 glob 整个 state/journal/ 目录。
  写 → python3 tools/statectl.py fact|task|done|event <M2C|QWEN> --session <角色串> ...
       `--session` 取**角色串**(tzb-fe / m2c-exec / qwen-brain-owner),不是会话名(名字重启即变)。
  旧 → M2C_STATE.md / QWEN_BRAIN_STATE.md 转只读,**暂不设物理阻挡**(hook 属 4B,尚未激活)。
       切换后仍写旧路径不算违规,但内容不进当前真相;check 会检出,按裁定 B1 处置。

三条硬语义:
  1. 只有 §1-§4 具规范效力。§5 是 journal 缓存 —— 仅存在于 journal 的内容不是约束、不是待办。
  2. fact/task 按 stable key upsert,值未变即 no-op 不写 journal。摘要 ≤160 字符、整条 ≤1024B,
     超限拒写(正文进 ADR/证据文件,只留结论 + --ref)。导入的历史记录 grandfathered,不受此限。
  3. `--session` 是自声明未验证的字符串,属写入纪律层,**不是安全属性**,禁止引作访问控制主张。

迁移已完成并经协调侧独立核验:字节守恒成立,无历史记录丢失。
  M2C_STATE.md 116127B → 12543B    QWEN_BRAIN_STATE.md 105283B → 15372B
回退:rm -rf state/ 即完全复原,旧文件全程未被修改。
