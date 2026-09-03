# 第八轮｜按 v6 终审七项条件逐条闭合,请求短复审

**本轮不请求你重读全部材料。**你上轮把签字条件收敛成七项,且明确说"无需新实验,也无需改变路线"。本文逐条对账,只请你复核这七项。

**上轮你的判决**:字节完整性通过,**主张语义完整性未通过**。我们接受这个区分,它比"通过/不通过"准确——问题确实全部落在 claim 与 evidence 的**语义范围**上,而不在字节。

**先说最重要的一句**:你上轮拒绝在 v4 摘要上签字,直接导致我们取回主件;取回当天就查出 BLIND secondary metric 的单例差异。本轮 P0-2 又是同一机制——**你数了 `bound_in` 里的条目,发现量词覆盖三个 split 而证据只有两个**。这两次都不是措辞洁癖,是真的抓出了错。

---

## 七项条件逐条对账

### 1｜所有"逐例完全一致"补 `expectation_match` 限定 —— 已闭合

权威清单主事实区原已限定;本轮补了你点名的四处下游:

| 位置 | 处置 |
|---|---|
| `deck-p1-p3-p4-p6-content-blocks.md:152–153` | 加指标限定 + 同页脚注(S5 执行) |
| `appendix-qwen-lane-defense-qa.md:86` | 加 `expectation_match` 限定(S5 执行) |
| `appendix-qwen-lane-defense-qa.md:146` | 改为"在 `expectation_match` 上逐族一致;MANUAL_BLIND secondary structural metrics 有 1 例差异"(S5 执行) |
| `CLAIMS-SHEET:5b` 小节标题 | **标题内直接加限定**,并加一行"标题即限定,不得省;不能指望读者往前翻" |

### 2｜同屏披露 BLIND 一例 secondary metric 差异 —— 已闭合

允许表述按你给的定性写死:

> MANUAL_BLIND 有一例输出行为发生变化:BASE 产生契约错误,LoRA 产生结构合法但目标错误的计划;**任务正确性没有改善**。

禁用清单已写入权威清单:结构合规性收益 / 鲁棒性提升 / 安全性提升 / **一例纠正** / `+1/45` 能力增益。定性统一为**行为差异诊断,不是收益**。

### 3｜DEV/TEST/BLIND 三 split 身份绑定 —— **走选择 A(补件),不是降级**

你给了两条路。我们查证后走 A,因为证据确实存在,只是上一轮没取:

- `icl-dev-trained-report-v3.json`(DEV candidate 臂)**确实带** `adapter_tree_sha256 = 8a09f56a…`;
- 它由包内 `icl-dev-paired-supporting-report-v3.json` 的 `candidate_report_sha256` **逐字节钉住**;
- 同时取回 DEV baseline 臂(由 `baseline_report_sha256` 钉住),**adapter 字段为 `null`**。

**但这只支持一件事:跨 split 的 RECORDED tree 身份一致性。** DEV 两臂的 schema version、experiment identity(`s5-icl-v2` vs `v3`)与 `config_sha256` **均不同**,**所以 DEV 不是单变量对照,不支持任何因果比较**,它在我们的口径里一直只是 supporting analysis。

现在三个 split 全部成立:

```
TEST  candidate  adapter = 8a09f56a      TEST  baseline  adapter = null
BLIND candidate  adapter = 8a09f56a      BLIND baseline  adapter = null
DEV   candidate  adapter = 8a09f56a      DEV   baseline  adapter = null
```

**这是第二次只读取件**,同一主机、同一目录、同一用户授权,**在收据里显式声明为对原枚举清单的两文件扩展**,不静默并入。取件保真现为 **15/15**(原 13/13)。

### 4｜`S5_ADAPTER_LOADED_TREE_IDENTITY` 重命名 —— 已闭合

改为 **`S5_RECORDED_ADAPTER_TREE_IDENTITY`**,旧 id 记为 supersedes。

你这条抓得最准,我们内部把它归到同一病型:**谓词贴错了主语**。一个 claim 不能同时叫 `LOADED`、描述成 `exact loaded identity`、又在 unsupported scope 里承认没有 runtime 证明。**这三者中必须有一个是假的,而假的那个是名字。**

允许:发布回执与三份 candidate 报告**记录了**同一 tree digest。
禁止:运行时加载已证明 / bit-exact / exact loaded identity 已建立。

### 5｜safetensors 与 tree 可验证措辞降级 —— 已闭合

作废表述:"树身份仍可凭发布回执复核" / "tree identity remains verifiable without shipping the payload"。

改为你给的二分:

**包内可核**:发布回执与三份 candidate 报告**记录了同一 tree digest**,这一记录的一致性可核对。
**包内不可核**(payload 不在包内):独立重算 safetensors 摘要、独立重建完整 adapter tree、证明回执所记 payload digest 对应真实 payload、证明运行时加载了该权重。

收据里保留了一条 `superseded_overclaim` 字段,写明旧句为什么太强——**不删,留作记录**。

### 6｜权威清单里的包内路径错误 —— 已闭合

`reports/evidence-s5-node2-20260831/FETCH-RECEIPT.json` 是**工作树路径**,发行包内实际是 `evidence/s5/node2-original/FETCH-RECEIPT.json`。已改为引用包内路径并注明两者关系。

这条是我们自己的低级错误:**权威清单给出的证据入口在发行包里解析不了**。

### 7｜统一"执行前验证链" + 重建 —— 已闭合

整条链统一称**执行前验证链**(类型化运行时契约层 + 语义验证器)。"语义执行门/语义门"**只能**用于确实到达 semantic validator 的 23 例,不得覆盖全部 24 例。

已改:权威清单 §6 标题与命名裁定、第 7/8 页、视频脚本(开场角标、能力矩阵、结尾旁白三处)。S5 负责 `deck-p2-p5`、`deck-p1-p3-p4-p6`、两份附录。MANIFEST / 索引重建与 archive SHA、exact-match 重跑随新包一并执行。

---

---

## 第八项:你没提,我们自己查出来的

七项之外我们自查出一处,**在你发现之前主动交出来**,因为它是我们主动写进 deck 的数字,而且**评委可以按恢复出的 selector 自己跑一次**——**那会是一次新的观测,不保证复现我们的历史结果**(日期、环境、依赖都不在我们控制内)。

**`135` 是七文件 scoped 子集,不是仓库全量测试。**

证据件 `/commands/pytest` 的原文是 "Exact historical **seven-file** terminal P1 compatibility pytest command",135 passed in 3.59s。而我们在第 8 页写的是:

> 当前冻结实现下 `135` 项回归测试通过

**"当前冻结实现下"是时间范围,不是文件范围。** 读者会读成"回归套件通过"。

同日我们用项目 `.venv`(Python 3.13.12)跑了**全仓扣除一个被 ignore 的 collection-error 文件**的选择器。**下面这个数字的状态是 `TRANSCRIPT_ATTESTED`(2026-09-01 从产生它的会话 transcript 取证恢复:tool_use 第 15075 行 / tool_result 第 15076 行,带 uuid 与时间戳;命令经 `tail -25`,故非完整 stdout,且 transcript 在包外)。我们未重现它:**

```
14 failed, 1933 passed, 5 skipped in 225.51s   ← TRANSCRIPT_ATTESTED,非完整 stdout(tail -25)
另有 tests/unit/test_m2c_s3_dataset.py collection error(缺 artifacts/m2b/dataset-v2.jsonl)
裸 pytest -q 会直接中止
```

**⚠ 2026-09-01 补充更正:上面那个数字不是现行值,而这件事的性质值得你单独评价。**

我们按你 v8 复核的要求去补全仓运行的原始证据(记录的 shell 命令 / stdout / nodeid / 退出码;**进程 argv 三次运行均未捕获**),**重跑(扣除一个被 ignore 的 collection-error 文件)得到的是 `61 failed, 1886 passed, 5 skipped`**。

**在 `find` 的扫描范围内,没有 source/test/config 文件的 mtime 晚于 8/31 17:00** —— 扫描返回三条路径:VLA spec 文档与两个 pytest cache。

**这句话我们第一版写成了"一个字节都没变",那是过强的**:`-newermt` 比的是修改时间不是内容,范围还排除了 `.git`/`.venv`/`artifacts`,而且**扫描结果本身非空**——我们自己的证据文件里就列着一条变动。要证明字节相同需要前后两次摘要,而 8/31 那个状态我们没有摘要。

**候选解释(不是已确立的根因)是我们自己预注册的硬冻结门在 9/1 零点生效:**
```
src/xh_agent/policy/qrm_lite/m2c_hard_freeze.py
M2C_HARD_FREEZE_LOCAL_ISO = "2026-09-01T00:00:00+08:00"
M2CHardFreezeError: M2C_HARD_FREEZE_ACTIVE:...:new experiment execution forbidden on/after ...
```
**transcript 记录的 8/31 结果与包内 9/1 观测不同。** 说"同一份代码库/同一份字节"都过强:**我们没有 8/31 的字节摘要**,run D 的局部 mtime 扫描**不建立同字节**。

**但这里我们必须把话说准,因为我们自己第一版写过头了**:已确立的是**数量差 47 出现在冻结边界**、**在 find 的扫描范围内未发现 mtime 晚于 2026-08-31 17:00 的 source/test/config 路径(这是局部 mtime 观测,不证明 mtime 未变化,更不证明字节相同)**、以及门机制在**一个抽样失败文件**上的演示(`test_m2c_formal_split_host_v4.py`,报 `M2CHardFreezeError`)。**未确立**的是那 47 个是否全部由该门导致——19 个失败文件里只抽查了 1 个。**一个样本不能为 47 个结果确立成因。**

**这一条对你我都有意义,因为它推翻的不是数字,是数字的类型**:我们把**一次带日期戳的测量**当作**可复核的定值**发布了出去。**transcript 记录 8/31 为 14,包内 9/1 观测为 61**——仍不说"8/31 为真、9/1 为假":两者都是**各自那次执行的记录**,不是可判真假的命题。而**在 find 的扫描范围内未发现 mtime 晚于 2026-08-31 17:00 的 source/test/config 路径——这是局部 mtime 观测,不证明 mtime 未变化,更不证明字节相同**(我们没有前后摘要,所以说不到"没人改过代码"这么强)。前一轮我们学到的是"数字对、范围标签缺";这一次是"**我们**按对待真值的方式发布了一个当时未捕获、也未标明时间与证据状态的数字****"。

**同时必须说的另一半**:2026-09-01 这次运行中,`qwen_brain` lane **观测到 359 passed / 4 skipped / 零失败**,且 61 个失败**全部**在 `test_m2c_*`,**没有一个在该 lane**。

**我们只说到这里。** "该 lane 不受冻结门影响"是**没测过的因果主张**——我们有的是那一天的一次零失败观测。

**并且**:我们**没有**逐个诊断那 61 个失败,**机制只在 1 个抽样文件上确立**(19 个失败文件里抽了 1 个)。所以既不说"它们无害",也不说"那 47 个都是门造成的"。

原始证据已入包:`evidence/fullrepo-test-20260901/`,含 **2026-09-01 四次捕获的命令**(裸跑 / 全仓扣除一个 ignore 文件 / qwen_brain lane / **文件系统变更扫描——是 `find`,不是测试运行**)的记录的 shell 命令、原始 stdout/stderr 摘要、1952 个 collected nodeid、61 个 failed nodeid、退出码与环境。**8/31 那次的证据形态不同**:命令文本、结果行与 14 个 nodeid 由同目录的 `TRANSCRIPT-RECOVERY-20260831-RUN.json` 与 `recovered-20260831-failed-nodeids.txt` 承载,锚点是两条 JSONL 行的 event-byte digest;**完整 stdout 未捕获、退出码不可推断、transcript 在包外**。

**transcript 记录的 8/31 那 14 个失败**,其 nodeid 已从恢复文本完整取出(14/14),**经程序化核验全部是 `test_m2c_*`**,分布为 qb_adr_gate 2、qwen_adr0026 2、s3_collection_plan 3、s3_public_category 1、s4_entry_gate 3、status 3。**该分布现为 `TRANSCRIPT_ATTESTED`,nodeid 清单已存为 `recovered-20260831-failed-nodeids.txt`;但完整 stdout 仍未捕获(命令经 `tail -25`)**——**我们未重现它**,也未做日期操纵或移除门的测试,因此不对可复现性作任何方向的结论。

**这一段此前自相矛盾,值得你看**:同一句话的前半写着"已从 transcript 恢复",后半却还留着"我们没有去 transcript 里找过"——那是升级前的旧句,升级后没删。**我们先断定不可恢复(错了两次),然后把'没去找'写进材料,再在同一段里报告已经找到了。** 三步都记在案。

**已改**:权威清单 §6 加 v5 范围更正,第 8 页改为"在冻结语义契约路径的七文件回归子集上,135 项全部通过",并禁止裸写。

**补充(2026-09-01):你上轮阻断 3 的另一半——七文件 selector——已闭合。** 该 selector 已从产生它的 transcript 中**取证恢复**(session 72ad7a26 第 28990 行 tool-use、第 28996 行 tool-result,均带 event-byte SHA),零猜测、零试组合、零重跑;我们用恢复出的 `exact_argv` 独立实跑,得 `135 passed`,exit 0。**tzb-fe 于 2026-09-01 按恢复的 `exact_argv` 独立实跑,观察到 `135 passed`、exit 0**(只报这一次观测,不作"可复现"的一般性主张)。
**边界**:恢复的是 **selector**,不是 P1 时点的文件身份——七个文件的当前摘要标为 `NOT_ASSERTED_AS_ORIGINAL_P1_IDENTITY`。**知道当时跑了哪些文件,不等于那些文件当时是这些字节。**
我们此前判定该 selector 不可恢复,那个判断**过早**了:记录一直在 transcript 里。拒绝继续猜是对的,断定不可恢复是错的。

**这一项最值得你评的地方,是它的来源**:证据件自身的 `proof_boundary` 只写了 "not evidence of the original P1 run",**完全没有声明文件范围,也没提全仓有失败**。所以这不是 deck 抄错了证据——**是证据件对自己的范围说少了,而下游忠实地继承了这个欠声明。**

这正是你上轮那个模式的一个新变种:前面几条是"人给证据贴错了谓词",这一条是"**证据自己没说清自己的边界**"。请判:`supported_scope` / `unsupported_scope` 这套字段,能不能靠 lint 强制要求"测试类证据必须声明选择器范围与全量对照"?还是这仍然落在你说的第三层人工门里?

---

## 我们采纳的其余判断(不需要你再答)

**LoRA 天花板**:接受你的定性。"未检出退化"**已作废**——它听起来像统计检验结论。现行对外短句:

> **主指标未观察到变化;不证明非退化。**

完整版按你给的写法保留 cluster=2/3、`UNSTABLE_LOW_CLUSTER_COUNT`、无 non-inferiority design、无裸基座回归四项限定。

**第 3 页分工**:接受。结构见证归 typed/runtime contract;semantic validator 的见证从已有 23 例里另选一个真正的 target/world/automaton 语义错误,不新增实验。

**"准确标注 ≠ 自我否定"**:接受降为**内部编辑原则**,不作对外口号,并改写为你给的可执行形式——先完整报正面事实,再紧邻标测试介质、拒绝组件与 unsupported scope。

**元层三层防线**:句法类型门与关系完整性门我们认为可以做成一次性 presubmit lint,**但排在 9/3 代码冻结之后**;冻结前只采纳其行为部分。第三层的两个固定提问("这份工件最强能支持什么""存在什么替代世界使同样工件出现而结论不成立")已写入内部复核清单。

---

## 本轮请你回答

1. 七项是否**逐项**闭合;哪一项你认为仍未闭合。
2. 选择 A 的补件是否真的满足 `ACROSS_SPLITS` 的量词——特别是:**DEV baseline 臂用 `report-two-base-v2.json`** 是否构成正确的对照臂(它由 DEV paired 报告的 `baseline_report_sha256` 钉住,但文件名与另外两个 split 的命名不同构)。
3. 是否可以签"在这一集合上,限定范围通过"。若仍不能,请只列**阻断项**,不要再给非阻断建议——距代码冻结 9/3 只剩三天,我们需要把改动面收敛。

**一个我们自己没解决的问题,顺便请你判**:本轮七项里有五项是"名字大于证据"。我们已经在权威清单里加了证据类型→允许推导表和三条可机器化 lint,但 P0-3 那种错误(`LOADED` vs `RECORDED`)**能被 lint 抓到吗**?我们的判断是能——只要 `evidence_type = REPORT_RECORDED_TREE_DIGEST` 禁止 claim 名含 `LOADED`。但这依赖有人先正确填 `evidence_type`,而填错 `evidence_type` 本身又是同一类错误。**这个递归有底吗?**
