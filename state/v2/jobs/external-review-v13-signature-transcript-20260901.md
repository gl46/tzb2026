# v13 外审签字 —— 对话记录摘录(非外审原始回信文件)

**独立锚点**:本转贴内嵌的 archive SHA-256(`8ff65445bd8e4a326d3977847dfd7db35333eb38e95284fb1f10cb7c45f98447`)与盘上 `reports/m2c-external-review-delivery-20260831-v13.tar.gz` 重算值、`.sha256` sidecar 三者逐字符相同——审核子代理 2026-09-02 独立核验。转贴文本因此带有一个可独立验证的锚点,可信度高于纯转述。

**来源与限定**:本文是用户于 2026-09-01 09:36:41 贴入协调会话 tzb-fe 的第九轮外审复审结论,从会话原始记录 `5ae1238c-…jsonl` 提取。**外审回信的原始文件不在本仓库盘上**;本摘录的可信度等于用户转贴的可信度,不等于原件。deck 引用时不得加引号称"原话",应写"经第九轮外审签字:限定范围通过,在已写明的边界内无剩余签字阻断项(archive 8ff65445…)"。

---

# v13 短复审结论

> **在收到的这一集合上，可以签字：限定范围通过。**

我已实际解包并检查 v13，不只是读取 brief。第八轮要求复核的七项已经全部闭合。

## 独立核验结果

* Archive SHA-256 实算为
  `8ff65445bd8e4a326d3977847dfd7db35333eb38e95284fb1f10cb7c45f98447`
* 与 sidecar **完全一致**
* `verify_manifest.py`：**PASS**

  * 非 MANIFEST 成员：83
  * 实际检查：83
  * `bad = []`
* Campaign 冻结结论 exact-match：**PASS**
* v12 → v13 的当前材料变更面符合声明：

  * 仅修改 3 个当前材料文件
  * 共 4 处裁定句替换
  * 其余当前材料没有意外变化

## 上轮两个阻断均已闭合

### 1. mtime 过强表述已修正

当前统一写成：

> 在 `find` 的扫描范围内未发现 mtime 晚于 2026-08-31 17:00 的 source/test/config 路径；这是局部 mtime 观测，不证明 mtime 未变化，更不证明字节相同。

我没有再找到现行材料中残留的：

* “无 mtime 变动”
* “没有任何文件发生变化”
* “一个字节都没变”

历史 brief-7 中的旧说法不构成阻断，因为该文件已在首屏及 MANIFEST 中明确标为：

```text
HISTORICAL_PROCESS_RECORD
SEMANTICALLY_SUPERSEDED
DO_NOT_USE_FOR_CURRENT_CLAIMS
```

### 2. 整条验证链命名已修正

`VNEXT-BRAIN-ROADMAP` 已从：

```text
重新规划 → 再过语义门
```

改为：

```text
重新规划 → 再过执行前验证链
```

这与当前统一定义一致：

```text
执行前验证链
= Pydantic typed/runtime contract
+ semantic validator
```

“语义门／语义验证器”不再覆盖那个在契约层提前拒绝的结构案例。

## 七项最终裁决

| 项目                                             | 结果 |
| ---------------------------------------------- | -- |
| 1. “逐例完全一致”限定到 `expectation_match`             | 闭合 |
| 2. BLIND 单例 secondary behavior difference 同屏披露 | 闭合 |
| 3. TEST／BLIND／DEV recorded tree identity       | 闭合 |
| 4. `LOADED` 改为 `RECORDED`                      | 闭合 |
| 5. safetensors／tree 的包内可验证范围降级                 | 闭合 |
| 6. FETCH receipt 包内路径                          | 闭合 |
| 7. 统一“执行前验证链”                                  | 闭合 |

## DEV baseline 裁决不变

`report-two-base-v2.json` 的文件名与另外两个 split 不同，不影响身份成立。对照臂由以下内容确定：

* DEV paired report 中的 `baseline_report_sha256`
* baseline 文件实算 SHA
* `adapter_tree_sha256 = null`
* split、case、source identity 和 paired binding

所以以下窄主张成立：

> TEST、BLIND、DEV 三个 candidate 报告记录同一个 tree digest；三个 baseline 报告均记录 null。

同时，v13 正确保留了限制：

> DEV 两臂的 schema version、experiment identity 和 config 不同，因此 DEV 只是 descriptive supporting analysis，不进入单变量 LoRA 因果主张。

## 签字边界

本次签字不扩大为以下主张：

* 不把 `RECORDED` tree digest 写成 runtime-loaded identity；
* 不把日期化测试观测写成一般可复现性结论；
* 不把 synthetic/free-contact harness 写成物理机械臂行为证明；
* 不把局部 mtime 扫描写成字节未变化证明；
* 不把 DEV 写成严格单变量因果对照。

在这些已经写明的边界内，**v13 没有剩余签字阻断项**。

---

**以下不是外审内容**(用户同一消息里附带的沙盒链接与用户自己的话,原样保留仅作记录):

[下载 v13 短复审签字结论](sandbox:/mnt/data/m2c-v13-short-review.md)

[下载 v13 交付包](sandbox:/mnt/data/m2c-external-review-delivery-20260831-v13.tar.gz)

[下载 v13 SHA-256 sidecar](sandbox:/mnt/data/m2c-external-review-delivery-20260831-v13.tar.gz.sha256)


之后别这么严谨了
