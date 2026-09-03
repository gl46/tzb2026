# ADR-0035 — LocateAnything 正式 run:训练精确完成后的打包失败,如何分类

- 日期:2026-09-02 03:4x
- 裁定人:tzb-fe(tzb-c2),夜间代批 gen606
- 执行线:two-shot-canonical-gate
- 前序:job `locateanything-visual-prompt-lora-v1`,go/no-go prereg `0de1a863…`,posttraining-chain-freeze-v3 `73e9f096`

## 事实(执行线报告,裁定以其可验证部分为准)

1. 正式 run 达到精确 2000/2000:`trainer_state.global_step == max_steps == 2000`,末步 LR=0。
2. checkpoint `global_step2000` 已 commit READY,含 optimizer / model / dataloader state;milestone-2000 已存;trainer 打印 Training completed 与最终 metrics。
3. `trainer.save_model` 成功。
4. **此后**,官方脚本把推理 helper 文件复制进 output root 时,`shutil.copy2` 对已存在的 mode-0400 文件 `outputs/formal-training-2000step-v3/image_processing_locateanything.py` 抛 `PermissionError`。该文件由执行线预先放置,**字节与 SHA 与冻结 base helper 完全一致**。
5. 进程 exit 1。日志 2 个 Traceback 标记(该失败 + launcher 包装),无 OOM。
6. 冻结的 completion checker v2 因 Traceback 标记 fail-closed:无 receipt、无 adapter、无 adapted 输出。

## 裁定:准予分类为 `COMPLETE_WITH_POSTCOMPLETION_PACKAGING_FAILURE`,附七项条件

**为什么不是事后合理化:** 本裁定在**任何 adapted 输出、A/B、主评测、swapped 诊断、配对判定产生之前**做出。它决定的是"训练工件是否有效",不是"结果是否可接受";不存在结果依赖。失败点在已 commit 的最终 checkpoint 之下游,对学习到的权重零影响。重训只会得到相同(同 seed)或略异(异 seed)的权重,二者都不比现有的更好,却多花两小时 GPU 并重新暴露启动风险。

**条件(全部满足才准;后继 completion checker 须逐条断言):**

1. **顺序断言**:从日志按行序证明 `2000/2000` → checkpoint commit → `save_model` 成功 → 之后才出现第一个 Traceback。若 Traceback 出现在 `save_model` 之前,**拒绝**,回到 fail-closed。
2. **错误签名断言**:第一个 Traceback 必须是 `shutil.copy2` + `PermissionError` + 目标路径为 helper 文件。**只接受这一个签名**;任何其他 Traceback 仍 fail-closed。
3. **字节断言**:PermissionError 目标文件的 SHA-256 必须等于冻结 base helper 的 SHA-256。不等 → 拒绝。
4. **权重来源**:adapter / delta 提取一律从 **`checkpoint global_step2000`** 读取(已 commit、含 optimizer state 的那份),receipt 记录其路径与 digest。不从 output root 的 save_model 产物读,以免二者不一致时无法归因。
5. **原文保留**:两个 Traceback 全文进 completion receipt,不摘要。
6. **披露**:最终 go/no-go 工件同屏写明:训练精确完成;训后打包失败;根因是执行线预先放置 0400 helper 与官方脚本复制步骤冲突;对权重零影响;本 ADR 编号。**不得**写成"训练无异常完成"。
7. **不动训练树**:不重训、不 resume、不修改 `formal-training-2000step-v3/` 下任何文件、不改官方脚本。checker v2 标 `SUPERSEDED_BY_ADR0035`,不删不改。

## 流程缺陷(执行线,记录不追责)

在官方脚本的 output root 预放 0400 文件,与脚本自己的写入步骤冲突。这是"在活的东西上动手"的另一个变体——脚本的 output root 在训练期间归脚本。后续 run 不得预放任何文件到官方脚本的 output root;需要固定 helper 时,冻结在别处并在评测侧引用。

## 冻结声明

本文件自此不可变,chmod 444。后继更正写 ADR-0036 起。
