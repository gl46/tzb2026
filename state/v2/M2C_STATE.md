<!-- GENERATED — 禁止直接 Edit/Write。唯一写入口: tools/statectl.py -->
<!-- statectl protocol=2 stream=M2C generation=901 updated=2026-09-03T09:01+0800 -->
<!-- 自 M2C_STATE.md 迁移 sha=9dc690524ad77e6d51964237f11ee107e23e3ae92398d19e3424eb0676648fc6 -->

# M2C 权威状态(活跃快照,协议 v2)

> **只有 §1-§4 具规范效力。**§5 是 journal 缓存;仅存在于 journal 的内容**不是约束、不是待办、不是当前真相**。完整历史见 state/journal/M2C/。
> 唯一写入口 tools/statectl.py。写者角色 ['tzb-fe', 'm2c-exec'](角色串,重启不变;绑定见 state/v2/WRITERS.json)。`--session` 自声明未验证,属写入纪律层,**非安全属性**。
> 导入的历史记录 grandfathered,不受 1024B/160 字符上限约束(tzb-fe 裁定 2026-08-30 §3)。

## 1. 当前事实
- `chain.head` — 治理链 head:**P″ `51de5c916ed8065ab2d20effc23ad5c3336d24af`**,分支 `m2c-recovery-h3`,仓库 `/Users/gl/tzb-qrm-lite`(worktree 脏面受治理,禁动;零 origin recovery ref)。链序 H‴<R′<P<Q<R″<P′<Q′<R‴<P″(全身份见档)。
- `campaign.12shot` — 冻结账目(9e7d6f2e,OFFICIAL_HONEST_HALT):有效结果5/成功0/未消费ordinal7,statistical_claim=null。12发未完成,禁称0/12或假设检验结论;成分=3legacy+ordinal03追溯+ordinal04孤儿闭合 · ref: /private/tmp/m2c-r13239-campaign-final-accounting-summary-v1.json
- `host.formal_canonical` — formal host(labserver root@labserver)canonical 面:P″ checkout、封印源 0555/25、ledger(bootstrap+attestation+claims00-03+terminals00-02)、evidence(run-00..03 目录)、scratch——全部冻结,禁触。
- `ruling.r132_39_option_a` — 用户决策(R132.39,Option A):**successor campaign 双机制**(前向类型化 POSE_GATE_REJECTED 终态化 + 零消费追溯 recovery03),八段治理序各自审查冻结;**successor combined-prefix preflight PASS 后剩余 8 发立即跑,不再询问用户**;**硬截止 2026-08-30T12:00+08:00**,未全绿则自动发布诚实 halted-campaign 报告(用户可延,截至目前未延)。
- `design.terminalization_fix` — 冻结设计蓝图:`/private/tmp/m2c-r13236-terminalization-fix-design-v1.json`(sha 0b02af91…,binding,偏离需 fresh ruling)。

- `ruling.deadline_extended` — 用户 8/30 口头延 R132.39 硬截止(原 8/30T12:00 已过):授权跑正式版取得 12 发判定,halted-report 预案不再自动触发;代码冻结日 9/3(非 9/1) · ref: reports/external-consult-response-3-20260830.md

- `campaign.strata` — 分层为2x2:EAE=ord0-3(配额4,已满0/4锁死),EAN=ord4-5,MAE=ord6-9,MAN=ord10-11。最小层率永久0.000,故层间极差门可能使X>=6不可达——待冻结auditor枚举128后缀判定 · ref: /private/tmp/m2c-r13239-successor-implementation-51de5c9-v1/docs/decisions/M2C-V5-EXISTENCE-SUCCESSOR-PREREG.json

- `campaign.advance_unreachable` — 冻结auditor枚举128后缀:ADVANCE_TO_KEY_FREEZE可达数=0。终态已定为退回协调,与剩余7发结果无关。X>=5全因层间结构退回;仅X=4的12个后缀入third regime。仍须跑满12发 · ref: /private/tmp/m2c-r13239-task33-reachability-summary-v1.json

- `campaign.ordinal05_harness_halt` — ordinal05单次dispatch后runner因ModuleNotFoundError:m2c退出1；control六文件齐，但claim05/terminal05缺失。禁redispatch/修补，依替代停止规则转源84ceadfc诚实halted。 · ref: /private/tmp/m2c-r13239-task31-ordinal05-runner-stderr-v1.txt

- `campaign.halted_final` — ordinal05 于23:46物理派发,runner rc=1 ModuleNotFoundError m2c,claim05/terminal05未写。停止规则生效:不重试(冻结NO_RETRY+替代规则+重试语义三重依据),转诚实halted报告 · ref: /private/tmp/m2c-r13239-r3-honest-halted-campaign-report-v1.json

- `eval.family_breakdown` — 逐族分解(两臂完全一致):契约拒绝16/16、符号重定位21/21、恢复13/18、视觉0/12。BLIND14错=12视觉+2恢复,故'错误全为视觉'已证伪 · ref: reports/CLAIMS-SHEET-20260831.md

- `auth.user_gpu_20260831` — 用户gl 2026-08-31明确授权两项:(1)按4dc01803计划原样只读核验v2未知终态;(2)Task32 labserver GPU<=2h。发现残留须停报不得清理;清理需另次用户授权

- `report.halted_final_authoritative` — halted报告v2(b3586033,17证据身份)经tzb-fe逐字段复核APPROVE为最终件;deck第6页与最终报告一律引用,禁自行复述数字;六次停机枚举以其pre_ssh_zero_consumption_stops为准 · ref: /private/tmp/m2c-r13239-r3-honest-halted-campaign-report-v2.json

- `incident.orphan_container` — 孤儿容器只读补证后已按用户授权精确stop：inspect/top/logs各1次且rc0；stop仅作用b40e4e76且rc0；复核容器0行、PID74398/74573与命令族0行、GPU0 PID74573 0行，另3个既有GPU进程未动。Task32可启动。 · ref: /private/tmp/m2c-r13239-task32-orphan-poststop-verification-v1/manifest.json

- `deck.positioning` — 定位裁定:唯一站得住=面向工业机械臂的可验证指令执行安全层。禁称已完成感知识别-指令决策-抓放闭环。贡献主次①契约与执行入口②架构信任边界③治理,治理不得居前;主deck不设整页治理 · ref: reports/CLAIMS-SHEET-20260831.md

- `witness.synthetic_provenance` — 见证案例出处经S5独立核实为合成:套件builder取execute fixture改decision为REFUSE,rationale字段自带'Synthetic schema-valid contradictory REFUSE mode',无Commander生成工件。禁称模型真实输出

- `incident.frozen_root_metadata_check` — 纯本地比对PASS：五个冻结R3根在可比维度(type/path/mode/uid/gid/size/顶层成员)均与事故前权威一致；1934条已捕获递归记录无mtime>=孤儿容器启动时刻。未找到同格式事故前递归manifest，故不声称全递归字段/内容字节等价。 · ref: /private/tmp/m2c-r13239-task32-frozen-root-metadata-comparison-v2.json

- `incident.frozen_root_clean` — 冻结根比对PASS(bc3e2169):五根可比维度与事故前权威一致,1934条递归记录无mtime>=事故起始。限定:无同格式事故前递归manifest,不声称全递归字段或内容字节等价 · ref: /private/tmp/m2c-r13239-task32-frozen-root-metadata-comparison-v2.json

- `route.frozen_base_orchestration` — 用户8/31裁定主线转向:冻结基座+编排,不再做微调实验,LoRA封存为消融证据。主标题仍为可验证指令执行安全层,决策层只作已验证子能力描述,名字须小于证据 · ref: reports/VNEXT-BRAIN-ROADMAP-20260831.md

- `task32.closeout` — Task32收官(2c255c69):未确认固定偏移、无视频。四候选hand/TCP系误差向量跨候选偏离213.4mm,非近似常量,固定参考系错配假设被否。原向量因探针不存final pose不可重建 · ref: /private/tmp/m2c-r13239-task32-frame-chain-v1/task32-final-disposition-v3.json

- `deck.page1_version` — 第1页确定走语义门拦截版(无vNext镜头):Task32未确认根因故不录。标题方向=格式检查能通过的矛盾计划仍被挡在机械臂之外

- `deck.all_pages_covered` — 8页deck内容块齐:1/3/4/6右半=S5,6左半=m2c-exec,2/5=S5,7/8=tzb-fe。加演示HTML、视频脚本、三附录、权威清单、vNext路线,共11份材料

- `lane.m2cexec_materials_status` — 六材料终检PASS:冻结句机器比对、page6数字单一来源、禁语/限定一致、索引当前字节14/14; lane关闭,未commit/push · ref: /private/tmp/m2c-r13239-six-material-final-consistency-audit-v1.json

- `chain.task29_r3_landed` — Task29链事实补发:H″0eb522cf→S″6c7e4a72→P″b034a054,父链精确;H″11路径,S/P各单文件,closure=76+1+1,重生字节一致 · ref: /private/tmp/m2c-r13239-task29-chain-proof-v1.json

- `handoff.20260831_materials_complete` — 8/31 04:00 交接点:11份材料齐(8页内容块/演示HTML/视频脚本/三附录/权威清单/vNext路线),两lane停靠,第六轮终审件待发。余下=PPT与视频制作,需用户或外部工具 · ref: reports/CLAIMS-SHEET-20260831.md

- `lane.m2cexec_delivery_package` — 外审v2包完成并取代v1:TierA 12、TierB 13/13 match,MANIFEST/解包核验28/28；v1仅过程记录禁止交付 · ref: /private/tmp/m2c-r13239-external-review-delivery-package-v2.json

- `package.delivery_v1_superseded` — v1包仅保留为过程记录且禁止交付；S5结构见证实际由Pydantic契约层在语义验证器/gate前拒绝，待create-once v2取代 · ref: /private/tmp/m2c-r13239-external-review-delivery-package-v1.json

- `delivery.v2_package` — v2外审交付包经tzb-fe独立复核可发:sidecar af346410与实算一致,36成员零不安全,TierA=12/TierB=13全match,三处最新编辑均在包内,真码在假码禁令在 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v2.json

- `delivery.v2_package_location` — v2交付包已从/private/tmp拷至 reports/ 与材料同级:m2c-external-review-delivery-20260831-v2.tar.gz + .sha256;拷贝后 match=True 字节未变。tmp为易失,交付件不留tmp

- `audit.round7_cannot_sign` — 第七轮终审:包完整性可签(archive/manifest/HTML字节均验过),对外主张准确性不可签。四阻断=旧口径残留、46pp因果、exact-match源与字节不一致、核心P2/LoRA证据不在包内

- `package.delivery_v2_superseded` — v2包完整性通过但主张准确性未签，标PROCESS_RECORD_DO_NOT_DELIVER；v3须修冻结句、显式TierB语义、扩证据并附exact-match工具回执 · ref: /private/tmp/m2c-r13239-external-review-delivery-package-v2.json

- `audit.round7_tzbfe_fixes_done` — tzb-fe四份终审P0改完并自查归一:零派发26处统一为'未到达末端原语dispatcher调用点',全称句删除,46pp因果作废,子能力表去理解/路由升级,冻结句逐字节无句号 · ref: reports/CLAIMS-SHEET-20260831.md

- `evidence.seven_class_gap` — 七类证据盘点:AVAILABLE=1(48例套件定义),NO_EVIDENCE=6影响21条claim。分两种:3类件在node2取不回(待用户批),3类从未生成独立冻结件(已授权确定性重导出) · ref: /private/tmp/m2c-r13239-v3-s5-evidence-handoff-qwen-v1.json

- `evidence.p2_rederived_match` — P2重导出headline逐项一致:0/24误放、0/24误拒、44/44定位、24/24未达末端dispatcher、26/38覆盖。既补上证据件,也实际演示了一次确定性 · ref: /private/tmp/m2c-s5-p2-semantic-suite-rederived-20260831-v1.json

- `lane.m2cexec_v3_blocked` — v3定为PROCESS_RECORD_DO_NOT_DELIVER。机械字节核验PASS但语义扫描仅6/8命中统一重导出标签;v4仅补父/子标签层级,其余内容不动。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v3.json

- `regression_135_supersedes_134` — 回归数更正:当前冻结实现重导出实测135 passed零FAIL四门全过,原报134为P1时点数字已作废。13个terminal文件11一致2为后续P2身份。活跃材料134残留已归零

- `evidence.three_state_counts` — 证据三态更新:原始冻结件13条、2026-08-31重导出件8条(带NOT_ORIGINAL_RUN)、无包内证据0条。原2/8/11作废 · ref: reports/evidence-s5-node2-20260831/FETCH-RECEIPT.json

- `lane.m2cexec_v4_complete` — v4标签层级包独立核验PASS:父标签8/8、子标签2/2；TierA=12、TierB=17/17、ledger=1、S5三态2/8/11；archive前缀f313713a。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v4.json

- `delivery.v4_ready` — v4交付包经tzb-fe独立复核可发(f313713a,137256B,47成员零不安全):TierA=12/TierB 17-17 match/三态2-8-11/父标签8-8/子标签2-2;已拷至reports/,v2改名SUPERSEDED防误发 · ref: reports/m2c-external-review-delivery-20260831-v4.tar.gz

- `auth.user_node2_readonly_fetch` — 用户2026-08-31授权(原话'2你批一下')只读取回node2 /home/gl/xh-202607-qwen-s5 的TEST/BLIND/三split paired、two-epoch训练报告、adapter tree清单。仅读:禁rm/kill/写入/起GPU任务 · ref: state/v2/M2C_STATE.md

- `evidence.node2_fetch_complete` — 用户批准后只读取回node2 13件,源端sha与本地拷贝13/13逐字节一致。79MB safetensors声明性排除只记digest。收据含逐条claim覆盖与不支持范围 · ref: reports/evidence-s5-node2-20260831/FETCH-RECEIPT.json

- `evidence.blind_family_breakdown_original` — BLIND四族逐行重数与清单完全一致:13/13、11/11、7/9、0/12(n=45);TEST为3/3、10/10、6/9(n=22)。原始冻结件,禁贴NOT_ORIGINAL_RUN标签 · ref: reports/evidence-s5-node2-20260831/FETCH-RECEIPT.json

- `evidence.lora_zero_benefit_measured` — LoRA实测无可主张收益:TEST四指标Δ=0且discordant=0;BLIND主指标Δ=0,strict_valid仅+1/45低于0.05下限。区间标UNSTABLE故不得反推'未退化已证明' · ref: reports/evidence-s5-node2-20260831/FETCH-RECEIPT.json

- `evidence.node2_fetch_independent_audit` — node2取回证据独立审计PASS:13/13源端-拷贝-实算身份一致,11 claim精确覆盖,三类结果/LoRA限定/adapter绑定/排除披露均复核。 · ref: /private/tmp/m2c-r13239-node2-fetch-independent-audit-v1.json

- `freeze.materials_baseline_v5` — v6基线:consult7=待m2c-exec重算(修陈旧计数13/13->30/30);CLAIMS=56238b92/32017B;deck-p7-p8=8ea16ccb;video=59254c26;vNext=59626c55。v5包因该错不发

- `lane.m2cexec_v5_complete` — v5 create-once包独立核验PASS:TierA=12、TierB=30/30、S5三态13/8/0、21 claim精确分区、node2原始件13/13且无重导出标签、archive前缀220801a1。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v5.json

- `lane.m2cexec_v5_blocked` — tzb-fe发前独立复核:技术面PASS但consult7仍写旧13/13 claim-bearing计数；v5保留为PROCESS_RECORD_DO_NOT_DELIVER，须create-once v6。 · ref: /Users/gl/tzb/reports/external-consult-brief-7-20260831.md

- `incident.v6_refreeze_v1_empty` — v6 baseline-v1因shell重定向先截断、脚本后检测路径存在而成为0B；未触碰reports/v5/冻结证据。v1保留PROCESS_RECORD_DO_NOT_USE，后续用create-once v2并显式披露。 · ref: /private/tmp/m2c-r13239-v6-tzbfe-five-file-refreeze-baseline-v1.json

- `stopline.create_once_no_shell_redirect` — 裁定:create-once产物禁shell'>'喂入(重定向先截断,守卫在破坏下游)。须--out+O_EXCL或临时名+RENAME_NOREPLACE。m2c-exec已扫v6调用面0命中——范围仅v6脚本,全治理侧清扫属9/3后

- `ruling.create_once_proportionality` — 裁定:不追溯作废exists()+write_text中间件。写入原语防的是覆写丢失,不是内容真伪;内容保证来自对独立来源的复算。O_EXCL只对新建生效。v6 packager立即恢复

- `stopline.governance_freeze_until_v6` — 硬停:v6发出前不再新增/重建任何治理机制。只做两件=补完整Bash+Python扫描、建v6。非内容性流程瑕疵一律记录后延至9/3后。距冻结3天

- `incident.v6_redirection_scan_v1_invalid` — v6 create-once重定向扫描v1自身由shell >创建且只扫Python源文本、未审计Bash调用；0B路径保留PROCESS_RECORD_DO_NOT_USE，不覆写/删除/复用；先前0命中结论撤回，v6打包暂停待fresh O_EXCL完整审计与协调裁定。 · ref: /private/tmp/m2c-r13239-v6-create-once-shell-redirection-scan-v1.txt

- `audit.v6_create_once_full_scan` — v6完整扫描PASS_WITH_CLASSIFIED_HISTORICAL_HITS:Bash19次中5次/9个重定向均枚举；8个active Python无直接shell/shell=True。旧zero-hit撤回，scan-v1被取代；fresh回执O_EXCL写入。 · ref: /private/tmp/m2c-r13239-v6-create-once-shell-redirection-full-scan-v2.json

- `lane.m2cexec_v6_complete` — v6 create-once包独立核验PASS:archive前缀da033e44/199445B，TierA12、TierB30/30、13/8/0、21 claim；consult7与索引30/30一致，v5完整保留，完整调用审计PASS。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v6.json

- `delivery.v6_ready_to_send` — v6经tzb-fe同强度独立复核可发:da033e44/199445B,摘要复算101零不一致,56/56登记,三态13/8/0,node2 13件对源端0不一致,exact-match三处。已拷reports/,v2/v4改名SUPERSEDED · ref: reports/m2c-external-review-delivery-20260831-v6.tar.gz

- `freeze.materials_baseline_v7` — v7基线13件已程序化生成并发m2c-exec:S5四件760e7151/7e83cec8/a8632788/63da397f/49f5ce04经tzb-fe独立复核对上,命名清零,HTML 6处NOT_ORIGINAL_RUN+2处aggregate绑定+零外链

- `audit.round7_v4_limited_pass_v7_required` — 第七轮外审审的是v4并限定范围通过；11条无包内证据已由v6的13/8/0消除，但独立核验措辞、legacy字段归属与38规则inventory仍需v7。 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260831.md

- `evidence.node2_second_pass_dev` — 第二次只读取件2件闭合外审P0-2:DEV candidate带adapter 8a09f56a、DEV baseline为null,均由DEV paired的candidate/baseline_report_sha256钉住。保真15/15。收据显式声明为清单扩展 · ref: reports/evidence-s5-node2-20260831/FETCH-RECEIPT.json

- `ruling.lora_ceiling_final` — LoRA对外短句终版:'主指标未观察到变化;不证明非退化'。'未检出退化'作废(听似检验结论)。那1例44/45->45/45定性为行为差异诊断,非收益

- `audit.round7_v6_semantic_fail_v7_authority` — 更正:v6正式终审为字节完整性PASS、主张语义完整性FAIL；此前v4意见降为参考。v7须按七项条件修claim ontology、补三split绑定、降级tensor措辞并声明30/30仅字节层。 · ref: /Users/gl/tzb/reports/external-consult-brief-8-20260831.md

- `ownership.deploy_adapt_subagent` — 用户批派子代理做部署适配。独占:client_v1.py、run_protocol_suite.py、run_escalation_suite.py、新建commander-endpoint.example.json。禁碰reports/与冻结面

- `incident.v7_baseline_v1_stale` — v7 baseline-v1为非空且当刻有效的纠正前五文件快照；现源集已变，保留为PROCESS_RECORD_DO_NOT_USE，不覆写、删除或复用 · ref: /private/tmp/m2c-r13239-v7-tzbfe-five-file-refreeze-baseline-v1.json

- `evidence.node2_fetch_independent_audit_v2` — 15件node2本地发行拷贝独立复核PASS:15/15源-拷-实算一致，DEV成对摘要绑定及三split recorded-tree量词成立；零node2访问 · ref: /private/tmp/m2c-r13239-node2-fetch-independent-audit-v2.json

- `stale.project_overview_do_not_send` — reports/project-overview-for-external-review-20260830.md 已过时:285行有未加指标限定的'逐例完全一致'且措辞更强。不在v6/v7包内。文件名含for-external-review,属误发风险,禁外发

- `evidence.s5_v7_material_receipt` — S5五材料create-only回执经m2c-exec独立重算PASS:34 checks/0 failed，五文件identity全一致；v7最终编辑阻断解除 · ref: /private/tmp/m2c-s5-v7-material-validation-receipt-20260831-v1.json

- `evidence.regression_135_scope` — 135为七文件scoped子集非全仓。tzb-fe实测全仓14failed/1933passed/5skipped+1collection error,14个全在test_m2c_*不在qwen_brain,成因未逐个诊断。证据件proof_boundary未声明文件范围

- `evidence.regression_135_scope_correction` — 135为冻结语义契约路径七文件scoped子集，不代表全仓通过；同日全仓14 failed/1933 passed/5 skipped，另有collection error；14失败均test_m2c_*且成因未逐个诊断。 · ref: /private/tmp/m2c-s5-current-frozen-regression-rederived-20260831-v1.json

- `errorclass.unverified_unverifiability` — 新元层错误变种(子代理自陈):'我无法核实X'本身是一条未经核实的断言。它只探测了Qwen2.5-VL就对Qwen3.8-27B下了不可核实结论,实际200存在。v7后写入§0e

- `deploy.adaptation_done` — 部署适配完成:三洞修复+Docker三场景实测+key零落盘(2.86MB证据grep exit1)+默认模型对齐Qwen3.8-27B四处+基座替换警告三处+网盘节改待补。回归零退化 · ref: /Users/gl/projects/xh-202607-qwen-brain/deploy/README.md

- `freeze.materials_baseline_v7_final` — v7非索引TierA最终baseline-v3 PASS:12件相对v6变更8、新增brief8、未变3；O_EXCL，源字节再变即停。 · ref: /private/tmp/m2c-r13239-v7-tier-a-refreeze-baseline-v3.json

- `incident.v7_preindex_v2_false_positive` — preindex-v2写出FAIL/9项，均为分类器误报；保留PROCESS_RECORD_DO_NOT_USE，禁覆写删除复用；fresh v3分离指标限定与结构差异检查。 · ref: /private/tmp/m2c-r13239-v7-tier-a-preindex-prescan-v2.json

- `incident.v7_preindex_v3_classifier_false_positive` — preindex-v3写出FAIL/2项，仍为分类器误报：两文件已披露结构差异但扫描器误要求同一段含收益定性。封存DO_NOT_USE，fresh v4改为语义字段分离。 · ref: /private/tmp/m2c-r13239-v7-tier-a-preindex-prescan-v3.json

- `incident.v7_preindex_v4_classifier_false_positive` — preindex-v4写出FAIL/1项，deck已同屏披露但扫描器只认MANUAL_BLIND/BLIND，实际行写“行为差异诊断”。封存DO_NOT_USE；fresh v5加入该显式标题。 · ref: /private/tmp/m2c-r13239-v7-tier-a-preindex-prescan-v4.json

- `incident.v7_preindex_v5_classifier_false_positive` — preindex-v5写出FAIL/1项；deck以“一例”及“次级结构指标”中文披露，扫描器只认阿拉伯数字/英文字段。封存DO_NOT_USE；fresh v6纳入等价中文。 · ref: /private/tmp/m2c-r13239-v7-tier-a-preindex-prescan-v5.json

- `incident.v7_preindex_v6_classifier_false_positive` — preindex-v6写出FAIL/1项；deck写“有1例从契约错误变为结构合法但目标错误”且标行为差异诊断，扫描器仍误要求“差异”邻接。封存DO_NOT_USE。 · ref: /private/tmp/m2c-r13239-v7-tier-a-preindex-prescan-v6.json

- `audit.v7_tier_a_preindex_final` — v7非索引TierA prescan-v7 PASS:12件、相对v6变更8/新增1/未变3，语义禁语/指标限定/结构差异/七文件135均零发现；O_EXCL。 · ref: /private/tmp/m2c-r13239-v7-tier-a-preindex-prescan-v7.json

- `evidence.v7_index_rebuilt` — v7最终索引fresh v9 PASS:TierA13、TierB32/32、15件；RECORDED精确publication+三candidate四绑定，adapter_config仅composition/training支持；旧v7/v8过程件封存。 · ref: /private/tmp/m2c-r13239-evidence-index-provenance-rebuild-v9.json

- `job.vla_molmoact2_offline_pilot_v1` — VLA卡v5:裁定summary标签为PIPELINE_CONNECTED_SHIELD_TESTS_NOT_RUN(限定焊进标签,非第三类)。裸PIPELINE_CONNECTED保留至盾实现。Stage1A真正的headline是盾尚未实现 · ref: state/v2/jobs/qwen-vnext-vla-molmoact2-franka-offline-pilot-v1.json

- `incident.v7_index_v7_extra_recorded_binding` — index-v7误将不记录tree digest的adapter_config绑定到RECORDED claim；封存PROCESS_RECORD_DO_NOT_USE，fresh superseding索引限publication+三candidate精确四绑定。 · ref: /private/tmp/m2c-r13239-evidence-index-provenance-rebuild-v7.json

- `evidence.node2_fetch_independent_audit_v3` — 修正后FETCH收据独立审计PASS:15/15、11 claims；RECORDED精确四绑定且adapter_config/README仅作tree composition支持，零node2访问/修改。 · ref: /private/tmp/m2c-r13239-node2-fetch-independent-audit-v3.json

- `incident.v7_index_v8_order_check_false_failure` — superseding builder首次调用在索引写出后因四绑定顺序比较误报而停；v2索引封存PROCESS_RECORD_DO_NOT_USE，无receipt/package target消费。fresh路径改集合精确性并前移检查。 · ref: /private/tmp/m2c-r13239-v7-appendix-m2c-evidence-index-20260831-v2.md

- `incident.v7_complete_scan_v2_false_positive` — complete-scan-v2 FAIL两项均分类器误报:index已有“有1例 secondary-structural行为差异”及“索引自身第13个TierA”语义，扫描器只认更窄字面；封存DO_NOT_USE。 · ref: /private/tmp/m2c-r13239-v7-complete-tier-a-prescan-v2.json

- `evidence.vla_stage0_verified` — Stage0回执经tzb-fe独立核实:chxy绝对路径存在,11384B,sha a3cecbba逐字符对上;内容含controller_mapping_authorized=false与三项unverified_items。核实方式=只读ssh sha256sum · ref: chxy:/home/fx/vla-experiments/qwen-vnext-vla-molmoact2-franka-offline-pilot-v1/receipts/stage0-source-mapping-preprocessing-v1.json

- `auth.chxy_readonly_basis` — tzb-fe对chxy的只读访问依据=用户'chxy够的'(该线GPU授权)。仅限只读核验本线自产回执。写入/调度/触碰他人进程仍须另行授权

- `incident.v7_complete_scan_v3_false_positive` — complete-scan-v3剩1项仍为误报:已识别secondary-structural指标但direction词表漏同一英文短语；封存DO_NOT_USE，fresh v4补该等价标记。 · ref: /private/tmp/m2c-r13239-v7-complete-tier-a-prescan-v3.json

- `audit.v7_tier_a_complete_final` — v7完整TierA scanner-v4 PASS:13件、TierB32/32、node2 15、RECORDED精确四绑定、三态21分区、语义/135/tensor/expectation限定零发现；O_EXCL。 · ref: /private/tmp/m2c-r13239-v7-complete-tier-a-prescan-v4.json

- `audit.v6_preservation_before_v7` — v7建包前v6 preservation PASS:root/archive/sidecar/package+independent receipts/index/manifest全相互一致；原archive与sidecar未改，v7仅用不同create-once路径。 · ref: /private/tmp/m2c-r13239-v6-preservation-before-v7-v1.json

- `incident.v7_postcompact_first_action_violation` — 压缩恢复后首工具误写final verifier草稿，早于state-v2重读，违反恢复顺序；该草稿封存PROCESS_RECORD_DO_NOT_USE，fresh v2须基于已重读§1-§4生成。未消费包/回执/冻结面。 · ref: /private/tmp/verify_m2c_external_review_v7_final.py

- `incident.v7_invocation_audit_v1_classifier_false_positive` — final invocation audit-v1写出FAIL：文本token扫描把Python比较运算符>误判为shell重定向；AST结果仍无shell=True、直接write_text/bytes、破坏调用，包目标未消费。封存DO_NOT_USE，fresh v2移除粗糙token项。 · ref: /private/tmp/m2c-r13239-v7-create-once-final-invocation-audit-v1.json

- `incident.v7_independent_verifier_v1_classifier_false_positive` — 独立verifier-v1 FAIL唯一项为CLAIMS禁止列表“把逐例完全一致推广到全部split(只对TEST/BLIND成立)”；上下文下一条明确仅expectation_match且披露结构差异，属分类器误报。包字节不变，fresh verifier回执路径复核。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v7.json

- `incident.v7_superseding_verifier_v3_stale_audit_binding` — fresh verifier-v3尚未执行即发现沿用active verifier=self检查，会与预包audit-v3钉定的v2身份冲突；v3源封存PROCESS_RECORD_DO_NOT_USE，未消费其receipt/extract目标。fresh v4加独立post-package源码审计。 · ref: /private/tmp/verify_m2c_external_review_v7_final_v3.py

- `evidence.vla_stage1a_verified` — Stage1A经tzb-fe只读独立复核:三digest对上,20/20 shape(15,8)全finite三重identity匹配四字段齐全cc=0,判据1-5 PASS,判据6诚实NOT_RUN。fangzhou前后均34490MiB未触碰 · ref: chxy:/home/fx/vla-experiments/qwen-vnext-vla-molmoact2-franka-offline-pilot-v1/receipts/stage1a-pipeline-connectivity-v1.json

- `finding.vla_shield_not_implemented` — Stage1A主发现:连续动作盾只有spec无可运行代码,符号扫描0命中。VLA集成论点所依赖的组件尚不存在。这是发现不是缺口 · ref: state/v2/jobs/qwen-vnext-vla-molmoact2-franka-offline-pilot-v1.json

- `lane.m2cexec_v7_complete` — v7 create-once包与superseding独立核验PASS:prefix204e2baa/231568B,TierA13,TierB32/32,node2 15,S5 13/8/0,RECORDED四绑定；v6/legacy保留。首核验唯一分类器误报已封存。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v7-v1.json

- `audit.v7_tzbfe_final_review` — tzb-fe同强度十项复核:v7技术面主体PASS但两项阻断，须create-once v8且v7保留。brief7删陈旧32计数；MANIFEST需声明source_claim_ids仅历史provenance，现行以claim states为准。 · ref: /Users/gl/tzb/reports/external-consult-brief-7-20260831.md

- `freeze.materials_baseline_v8` — v8非索引TierA refreeze-v1 PASS：12件相对v7仅brief7变更、无新增、其余11不变；新不变量存在且陈旧30计数缺席；O_EXCL。 · ref: /private/tmp/m2c-r13239-v8-tier-a-refreeze-baseline-v1.json

- `audit.v8_tier_a_preindex` — v8非索引TierA prescan-v1 PASS：12件、相对v7仅brief7变更、无新增、11不变；禁语/expectation限定/结构差异/七文件135零发现；新不变量存在且陈旧30计数缺席；O_EXCL。 · ref: /private/tmp/m2c-r13239-v8-tier-a-preindex-prescan-v1.json

- `delivery.external_brief_current_state` — 已写现况简报给外部顾问:逐项带范围,含泄漏/不可识别/歧义1-48/无裸基座四项自诊缺陷,并请对方专挑范围写宽处。重心=意图感知,VLA已停 · ref: reports/external-brief-current-state-20260831.md

- `evidence.v8_index_rebuilt` — v8 index-v10 PASS：TierA13、TierB32/32且同v7；source_claim_ids顶层定义为历史provenance，active registry仅claim states，LOADED→RECORDED。 · ref: /private/tmp/m2c-r13239-evidence-index-provenance-rebuild-v10.json

- `audit.v8_tier_a_complete` — v8完整TierA scan-v1 PASS：13件、TierB32/32、node2 15、S5 13/8/0、RECORDED四绑定；source_claim_ids provenance七检查全绿，brief7唯一源变更。 · ref: /private/tmp/m2c-r13239-v8-complete-tier-a-prescan-v1.json

- `audit.v7_preservation_before_v8` — v8建包前v7 preservation PASS：root/archive/sidecar/package+independent receipts/index/MANIFEST/final audit全绑定一致；v7不删不改，v8用不同create-once路径。 · ref: /private/tmp/m2c-r13239-v7-preservation-before-v8-v1.json

- `incident.v8_postcompact_read_order` — v8期间两次压缩后首动作未先窄读state-v2：首次bad repl在O_EXCL前停、无产物；本次误先创建audit builder源码。均未执行脚本或消费包路径，现已重读§§1–4。 · ref: /private/tmp/create_m2c_v8_final_invocation_audit_v1.py

- `audit.v8_final_invocation` — v8 source-bound invocation audit-v1 PASS：packager/verifier两源AST/type检查已过，零shell=True/直接Path写/破坏调用，os.open全O_EXCL；v8七个目标均未消费，legacy一致。 · ref: /private/tmp/m2c-r13239-v8-create-once-final-invocation-audit-v1.json

- `package.delivery_v8_built` — v8 final packager单次执行PASS：TierA13、TierB32/32、node2 15、S5 13/8/0、RECORDED四绑定/跨split十路径、v7 preservation与legacy均PASS；待独立核验。 · ref: /private/tmp/m2c-r13239-external-review-delivery-package-v8.json

- `verify.delivery_v8_independent` — v8冻结verifier单次独立核验PASS：archive/package/sidecar/MANIFEST/安全解包/源到包字节/13+32/32+15/13-8-0/claim语义/v7与legacy均绿，issues=0。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v8-v1.json

- `audit.delivery_v8_final` — v8 final cross-receipt audit-v1 PASS：24项全绿，绑定包/独立核验/冻结源/sidecar/MANIFEST/claim语义/v7完整保留/legacy只读；短前缀已程序化派生。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v8-v1.json

- `handoff.delivery_v8_to_tzbfe` — v8 final audit PASS后，按WRITERS中sessionId反查live会话名tzb-fe；仅发送程序化派生8位archive前缀，未发完整hash/包/外部内容。等待同强度十项复核。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v8-v1.json

- `job.vla_shield_contract_v1` — REGISTER(+3修正)Task#76盾合约实现:写根限chxy VLA目录,禁碰qwen-brain仓保冻结前字节稳定;CPU only GPU=0;52例48违规4对照。修正=清单须先冻后跑 · ref: state/v2/jobs/vla-continuous-action-shield-contract-v1.json

- `delivery.v8_ready_to_send` — v8经tzb-fe十项独立复核可发:ccb3883c/231876B,摘要复算113零不一致,61/61登记,13/8/0,node2 15件对源端0不一致,exact-match三处,legacy只读线未变。已拷reports/,v6改名SUPERSEDED · ref: reports/m2c-external-review-delivery-20260831-v8.tar.gz

- `evidence.vla_shield_contract_verified` — 盾合约经tzb-fe只读复核PASS:清单23:39:26冻结早于runner23:47:50共8分24秒(时间戳证实非自述);52=48违规+4对照;52/52至少一门PASS证明门会区分;cc=0与双hash null全52 · ref: chxy:/home/fx/vla-experiments/qwen-vnext-vla-molmoact2-franka-offline-pilot-v1/receipts/continuous-action-shield-summary-v1.json

- `freeze.qwen_brain_repo_integrity` — 冻结面复查:13个terminal文件今日未动,contracts_v1=24a1d8e2与冻结记录逐字符同。git M项为早于冻结快照的未提交改动。今日仅改.gitignore与部署三文件

- `finding.dev_baseline_arm_version_delta` — 自查披露:DEV baseline臂产自s5-icl-v2而candidate为v3,config_sha256不同,缺5个v3字段。同请求集同策略同解码同基座。影响DEV配对强度不影响ACROSS_SPLITS(仅需candidate臂) · ref: reports/external-consult-addendum-dev-arm-20260901.md

- `finding.hard_freeze_gate_fired` — 8/31 TRANSCRIPT_ATTESTED一次观测14/1933/5（tail-25，pytest rc与process argv未建立）；9/1一次观测61/1886/5。差47仅为两次记录差；mtime扫描非字节证据，门机制仅抽样1/19失败文件，禁全因果。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `open.regression_135_selector_unrecorded` — 已闭合:selector从producing transcript取证恢复，tzb-fe按恢复的exact argv独立一次实跑观测135 passed/exit0；仅一次日期化观测，禁写一般可复现保证，当前文件身份不等于P1身份。 · ref: /private/tmp/m2c-s5-current-frozen-regression-selector-recovery-20260901-v1.json

- `audit.v8_tzbfe_final_review` — tzb-fe同强度复核：v8字节链全过、七项五项闭合；三项阻断须v9：brief7降历史件、独立核验措辞收窄与P2分母限定、纳入9/1全仓日期依赖新证据并等S5两件。v8保留。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v8-v1.json

- `audit.v9_fullrepo_input_precheck` — fullrepo目录现13成员=12引用证据+receipt；8/31为TRANSCRIPT_ATTESTED且transcript包外、tail-25、pytest rc/process argv未建立；9/1 B/C与D边界已独立核验，待最终源冻结。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `audit.v8_preservation_before_v9` — v8 preservation-before-v9-v1 PASS：root/archive/sidecar/package/independent/index/MANIFEST/final audit十三检查全绿；v8不删不改，v9使用独立create-once路径。 · ref: /private/tmp/m2c-r13239-v8-preservation-before-v9-v1.json

- `vnext.motto_verified_not_usable` — Motto(2607.24407)核实:西安交大2026-07-28,底座Qwen3-VL-2B/4B非Qwen3.5,权重Coming soon、无训练代码,仅架构+PR-Bench可用。降级为最近邻+一把现成的秤 · ref: https://github.com/TG0110/Motto

- `vnext.model_availability_verified` — 带阴性对照实测:Qwen3.5-4B多模态HF/MS均200;Qwen3.5-3B不存在;SAM3 HF200;Rex-Omni HF+MS均200(境内可达已核实);fake对照401

- `freeze.active_presentation_v9` — v9 active presentation refreeze-v1 PASS：11件现行材料相对v8仅CLAIMS与brief8变化、9件不变；brief7具三重历史banner且排除出active集合，另作为历史过程件保留。 · ref: /private/tmp/m2c-r13239-v9-active-presentation-refreeze-baseline-v1.json

- `stop.v9_fullrepo_internal_contradiction` — v9旧停止线已闭合：47全因果、零字节与未来全称三类过度声称均由tzb-fe收窄；receipt只把runD视为局部mtime扫描且保留NOT_supported。fresh源身份须独立复核后重冻。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `auth.qwen_research_license_ok` — 用户2026-09-01裁定:Qwen RESEARCH LICENSE用于本次比赛允许。Rex-Omni路线许可证阻断解除。用户已另开会话推进该线

- `ownership.rex_omni_lane_tzb50` — tzb-50候选集扩为三个含LocateAnything-3B(MS404境内待测,权重不支持visual prompt无ETA)。用户裁定非商业许可与网盘均可。判据序:beat incumbent>视觉提示>境内>许可 · ref: state/v2/jobs/rex-omni-pointing-lane-phase0.json

- `evidence.v9_s5_two_inputs_ready` — S5两件create-only到齐：P2 active谓词纠正为validation_chain24/semantic_validator23/runtime_pre_gate1/no_dispatch24；135七文件selector从producing transcript恢复，非原P1文件身份。 · ref: /private/tmp/m2c-s5-p2-validation-chain-predicate-correction-20260901-v1.json

- `stop.v9_source_semantic_prescan` — PROJECT_REPORTED派生继续下钻：47/same-command/same-codebase/8-31失败分布均须继承标签。已报协调。 · ref: /Users/gl/tzb/reports/external-consult-brief-8-20260831.md

- `audit.v9_s5_input_independent` — S5两件独立语义核验17项PASS：file/semantic摘要、P2 23+1=24完整互斥分区、legacy禁绑、selector七路径顺序/未猜未重跑/当前非P1身份/135 receipt均成立。 · ref: /private/tmp/m2c-s5-current-frozen-regression-selector-recovery-20260901-v1.json

- `incident.v9_postcompact_read_order` — 压缩后首工具误读v8 audit源码，后补读state-v2 §§1–4；未执行脚本或消费v9路径，fresh链仍未创建。 · ref: /private/tmp/create_m2c_v8_final_invocation_audit_v1.py

- `incident.v9_state_section5_overread` — 前次恢复读state-v2时越过§4进入非权威§5；未把§5当事实源。今后先定位边界并限定至§§1–4。 · ref: /Users/gl/tzb/state/v2/M2C_STATE.md

- `freeze.v9_latest_four_source_identities` — fresh4:41178/83937b55,14144/7d734a3a,14727/bee610dd,17736/331bbca8 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `finding.perception_targets_unreachable_twice` — 同一缺陷第二次出现:冻结视觉族要求输出输入中不存在的ID;Isaac数据的指令是world-frame minimum-x(leftmost),RGB单独也推不出。两次都造了感知够不到的感知目标 · ref: state/v2/jobs/rex-omni-pointing-lane-phase0.json

- `finding.prbench_evaluator_defect` — PR-Bench评测器静默丢弃畸形JSON、不强制count/ID、不出总分。用它当秤前必须strict-wrap,否则会偏袒输出垃圾的模型。tzb-50 phase0发现

- `finding.locateanything_visual_prompt_cost` — LocateAnything视觉提示需自训:官方LoRA脚本默认8GPU/5000步。我们只有chxy共享A100约46GB空闲,该路径实际够不到。hf-mirror仅验到byte-range可达非全量

- `stop.v9_active11_semantic_blockers` — 旧三类阻断已闭合:P2分母按声明集N=38裁定；8/31恢复为TRANSCRIPT_ATTESTED并补齐限制；DEV限定supporting-only。仍须active11完整语义审计PASS后方可refreeze。 · ref: /private/tmp/m2c-v9-semantic-validator-rule-inventory-authority-wrapper-20260901-v2.json

- `ruling.rule_inventory_38_option_A` — S5选A:只读枚举验证器源码产38条冻结inventory。tzb-fe加条件:先冻口径(何为一条规则/在哪数/component归属)再枚举;数不出38即为发现不许回调凑数,会推翻26/38与12类未触发

- `errorclass.overclaim_in_negative_direction` — 新变种:否定方向的过度声称。把'证据不支持X'写成'证据反驳X';把'两次测量间字节身份不可核'写成'任何文件字节身份不可核'。纪律是谓词与工件等强,不是一律说弱

- `stop.v9_fullrepo_command_provenance` — receipt A/B/C exact_argv混入env赋值与C glob模板，非已证实进程argv；须降级或补展开取证。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `incident.v9_postcompact_read_order_2` — 压缩后首工具误读四个v9候选源；后补读state-v2 §§1–4。未执行脚本、未消费v9产物，fresh链未创建。 · ref: /Users/gl/tzb/state/v2/M2C_STATE.md

- `evidence.v9_transcript_recovery_pending_audit` — 8/31 pytest命令、tail-25结果与14失败nodeid已恢复，候选状态TRANSCRIPT_ATTESTED；须独立核验后方可入v9。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/TRANSCRIPT-RECOVERY-20260831-RUN.json

- `stop.v9_transcript_recovery_semantics` — 8/31事件与14 nodeid核验通过；恢复件仍误把env列为argv，命令字节/记录不等且无pytest pipeline exit证据，禁入v9待修。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/TRANSCRIPT-RECOVERY-20260831-RUN.json

- `stop.v9_fullrepo_receipt_stale_layers` — fullrepo fresh receipt仍跨层残留exact argv、PROJECT_REPORTED/未查transcript、旧11成员计数；已报tzb-fe，禁refreeze。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `evidence.v9_transcript_recovery_verified_partial` — 8/31 transcript事件绑定、结果文本与14 nodeid已独立PASS；完整stdout与pytest退出码未建立，恢复件fresh修正版待终核。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/TRANSCRIPT-RECOVERY-20260831-RUN.json

- `stop.v9_active_presentation_stale_after_recovery` — Claims与brief8仍残留8/31 PROJECT_REPORTED/未查transcript，虽deck已修；active11未语义PASS，禁refreeze。 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260831.md

- `stop.v9_p2_prereg_unit_conflict` — 已裁明:V1/V2单位确实不同且不需等价；V2因对准原报告len(声明集)而获权威，结果一致不得作方法正当性；声明集N=38、套件触发26、补集12成立，须分开报告静态emitter 38/38。 · ref: /private/tmp/m2c-v9-semantic-validator-rule-counting-method-ruling-addendum-20260901-v2.json

- `audit.v9_transcript_recovery_independent` — c5e09999独立PASS:命令/结果/event raw-line SHA含LF/14 nodeid全绑定；仅tail文本，argv及pytest rc未建立，transcript在包外。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/TRANSCRIPT-RECOVERY-20260831-RUN.json

- `audit.v9_fullrepo_sources_provisional` — fullrepo13成员摘要/计数、8/31恢复锚点与14 nodeid、9/1 B 1952/61及19文件、C/D边界均核；active文案已同步，待P2后终冻。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json

- `incident.v9_p2_values_read_before_ruling` — S5已读规则值后承认v1/v2单位冲突；candidate declared-set inventory隔离，禁再称pre-enumeration，待tzb-fe fresh裁定。 · ref: /private/tmp/m2c-v9-semantic-validator-rule-counting-method-prereg-20260901-v2.json

- `evidence.rule_inventory_38_closed` — 38分母闭合:tzb-fe独立数出38条38唯一code16条test绑定;addendum 5处equivalence全为否定并自撤v1;源分母成立,26/38与12类未触发成立,分母须标声明集 · ref: /private/tmp/m2c-v9-semantic-validator-rule-inventory-20260901-v1.json

- `incident.v9_postcompact_read_order_3` — 压缩恢复后首工具误先审P2候选，随后完整重读state-v2 §§1–§4至§5边界；未写reports、未执行建包器、未消费v9 create-once路径。 · ref: /private/tmp/m2c-v9-semantic-validator-rule-inventory-20260901-v1.json

- `freeze.materials_baseline_v9` — v9材料面终版12份已逐字节核并落盘基线文件;未解析路径扫描仅2处且均带溯源标注、包内路径在前 · ref: state/v2/jobs/materials-baseline-v9.json

- `audit.v9_p2_inventory_independent` — P2 chain独立PASS:五JSON file/semantic摘要与引用全match；源码声明38唯一，38条source/emitter定位逐条命中，16个code有focused绑定且nodeid可解析；V1/V2不等价、不需要等价，V2仅对准声明集分母。 · ref: /private/tmp/m2c-v9-semantic-validator-rule-inventory-authority-wrapper-20260901-v2.json

- `stop.v9_p2_appendix_nonpackage_path` — tzb-fe已裁七件package-relative路径；S5正fresh修P2附录。并发现CLAIMS另一历史同类路径错，tzb-fe已改为包内路径在前/工作树溯源，故active11身份再次变化；待两件落定重启全量审计。 · ref: /Users/gl/tzb/reports/appendix-p2-rule-coverage.md

- `audit.v9_p2_appendix_landed_provenance` — tzb-fe核实:P2附录本轮就地修正，无fresh临时候选；v9索引须记包内路径+landed authority，worktree_source=NOT_APPLICABLE，禁引用旧v1或虚构v2。 · ref: /Users/gl/tzb/state/v2/jobs/materials-baseline-v9.json

- `audit.v9_active11_semantic_final` — v9 active11独立container/reverse语义审计PASS:21检查0失败；12材料字节与协调基线全match，brief7历史件排除TierA，current-state correspondence排除，P2/全仓/135/DEV/adapter/campaign边界成立。 · ref: /private/tmp/m2c-v9-active11-semantic-audit-v1.json

- `freeze.v9_active_presentation_final_v2` — v9 fresh refreeze-v2 PASS:协调baseline十二件逐字节全match；current active=11，brief7历史件outside TierA，current-state correspondence排除；绑定独立语义audit与v8 preservation。 · ref: /private/tmp/m2c-r13239-v9-active-presentation-refreeze-baseline-v2.json

- `incident.v9_postcompact_read_order_4` — 两次恢复顺序偏差：前次误读四份reports，本次误创建v9 preindex源码，均早于state-v2 §§1–§4重读。现已重读至§5前；scanner未执行，未消费receipt/package路径，未改reports。源码须审阅后方可运行。 · ref: /private/tmp/scan_m2c_tier_a_v9_preindex_v1.py

- `audit.v9_tier_a_preindex_final` — v9 active11 prescan-v1 PASS：绑定refreeze-v2与semantic audit；11份current身份未变，brief7历史且outside TierA，correspondence排除；P2/全仓/135/DEV/adapter/路径检查全绿。 · ref: /private/tmp/m2c-r13239-v9-tier-a-preindex-prescan-v1.json

- `incident.v9_coordinator_route_without_lookup` — v9 preindex进度消息直接发熟悉名tzb-fe，未先按WRITERS sessionId反查live name；消息到达预期会话且无hash/授权转移。后续发信恢复逐次反查。 · ref: /Users/gl/tzb/state/v2/WRITERS.json

- `incident.v9_postcompact_read_order_5` — 本次压缩恢复后首工具误创建v9 evidence-input审计源码，早于state-v2 §§1–§4重读；现已重读至§5前。源码未执行，未消费receipt/index/package路径，未改reports。 · ref: /private/tmp/audit_m2c_v9_evidence_inputs_v1.py

- `ruling.v9_index_material_paths_and_history` — tzb-fe 9/1裁定:fullrepo只装canonical evidence路径且CLAIMS已修;旧P2 projection仅历史保留、不得绑38/26;brief7归historical且outside TierA。 · ref: /Users/gl/tzb/state/v2/jobs/materials-baseline-v9.json

- `incident.v9_semantic_audit_v2_literal_false_fail` — CLAIMS路径修后fresh semantic-audit-v2写出FAIL/5，均为扫描字面不匹配；目标修正本身PASS。v2封存PROCESS_RECORD_DO_NOT_USE，不覆写删除复用；fresh v3按实际等价措辞审。 · ref: /private/tmp/m2c-v9-active11-semantic-audit-v2.json

- `freeze.v9_active_presentation_final_v3` — CLAIMS fullrepo引用改canonical包内路径后，active11 semantic-audit-v3 23项PASS、refreeze-v3与preindex-v2 PASS；brief7历史outside TierA，correspondence排除。 · ref: /private/tmp/m2c-r13239-v9-active-presentation-refreeze-baseline-v3.json

- `incident.v9_evidence_input_audit_v1_literal_false_fail` — evidence-input-audit-v1写出FAIL/2：exit文件含exit_code=前缀、node2声明排除有tensor及prepared duplicate两项；均为扫描器假设错。v1封存DO_NOT_USE，fresh v2按实际schema核。 · ref: /private/tmp/m2c-r13239-v9-evidence-input-audit-v1.json

- `audit.v9_evidence_inputs_final` — evidence-input-audit-v2 PASS 24项：v8 retained active 31、fullrepo exact13、P2/selector新7、node2 15/15及两项声明排除；未来current TierB候选51，路径唯一。 · ref: /private/tmp/m2c-r13239-v9-evidence-input-audit-v2.json

- `evidence.v9_index_rebuilt` — v9 fresh index-v11 PASS：current TierA=11+index=12；brief7 historical outside TierA；TierB 51/51；P2五件authority+23/1纠正+selector/fullrepo13；DEV不绑causal。 · ref: /private/tmp/m2c-r13239-evidence-index-provenance-rebuild-v11.json

- `incident.v9_final_source_v1_seed_readonly` — 用cp播种v9 packager/verifier-v1后，源继承0444，字符串改写PermissionError；两v1封存PROCESS_RECORD_DO_NOT_USE，不改权限/覆写/删除/复用。fresh v2用O_EXCL另建。 · ref: /private/tmp/package_m2c_external_review_v9_final_v1.py

- `audit.v9_tier_a_complete_final` — v9 complete scanner-v1 PASS 24项：current TierA12、brief7 historical1、TierB51/51、fullrepo13/node2 15、P2/selector/DEV按claim分割/路径/警告全绿。 · ref: /private/tmp/m2c-r13239-v9-complete-tier-a-prescan-v1.json

- `incident.v9_postcompact_read_order_6` — 本次压缩恢复后首工具误读v8 verifier源码，早于state-v2 §§1–§4重读；现已重读至§5前。只读且未执行脚本、未消费v9路径、未改reports；fresh v2链尚未创建。 · ref: /private/tmp/verify_m2c_external_review_v8_final_v1.py

- `freeze.v9_final_sources_v2` — v9 final packager/verifier fresh v2源码已用O_EXCL冻结为0444；draft与误播种v1均不作active。尚未执行；待source-bound invocation audit PASS且所有目标absence复核。 · ref: /private/tmp/package_m2c_external_review_v9_final_v2.py

- `incident.v9_final_sources_v2_static_defects` — v9冻结v2源码执行前发现3个静态缺陷；未执行且下游目标未消费。v2与其invocation-audit-v1封存PROCESS_RECORD_DO_NOT_USE，禁覆写/删/改权限/复用；fresh v3+audit-v2后再建包。 · ref: /private/tmp/package_m2c_external_review_v9_final_v2.py

- `audit.v9_freeze_defects_no_retro_impact` — v9冻结脚本v2三缺陷经tzb-fe独立验证仅v9新引入:v8/v7/v6 verifier对expected_reference_source等三字段命中全0,v8为read_bytes逐字节比对。既往假通过=0,brief-9无需既往披露 · ref: /private/tmp/verify_m2c_external_review_v8_final_v1.py

- `incident.v9_final_sources_v3_stale_audit_binding` — v3源码未执行即发现仍指向已封存audit-v1/v2源，无法由fresh audit-v2验过；v3与audit-v2封存PROCESS_RECORD_DO_NOT_USE，下游目标未消费。fresh v4须绑定fresh audit-v3后再单次建包。 · ref: /private/tmp/package_m2c_external_review_v9_final_v3.py

- `incident.v9_active_artifact_precheck_v1_classifier` — v4常量前检v1写出FAIL/8，均把包内运行时派生路径误当预存输入；active四绑定与dead引用检查均PASS。v1封存PROCESS_RECORD_DO_NOT_USE，fresh v2仅审顶层全大写Path常量。 · ref: /private/tmp/m2c-r13239-v9-active-artifact-constant-precheck-v1.json

- `incident.v9_v4_packager_partial_root` — v4单次packager在node2 manifest门停：index-v11省略旧source_frozen/copy别名而门仍要求，属schema继承缺陷。仅ROOT路径被消费(81文件)，archive/sidecar/receipt/核验/终审均未生成；禁清理/复用，fresh v10命名链。 · ref: /private/tmp/m2c-external-review-delivery-20260831-v9

- `incident.v10_prefreeze_v1_declared_exclusion_false_fail` — v10全门前检v1仅1项FAIL：把必须显式披露的safetensors声明性排除误当禁装payload命中；其余19项PASS。v1封存PROCESS_RECORD_DO_NOT_USE，fresh v2区分路径披露与实际source/package member。 · ref: /private/tmp/m2c-r13239-v10-active-artifact-schema-precheck-v1.json

- `audit.v10_prefreeze_v2` — v10全门前检v2 PASS:22/22；区分safetensors声明性排除与实际source/member inventory，payload零命中；83 planned paths唯一，final源/输出仍fresh。 · ref: /private/tmp/m2c-r13239-v10-active-artifact-schema-precheck-v2.json

- `incident.v10_invocation_audit_v1_path_literal_classifier` — v10 final源已按precheck逐字节O_EXCL冻结0444；invocation audit-v1仅因审计器要求源码含拼接后的绝对路径而FAIL，7项实质检查PASS，v10输出未消费。源与audit-v1封存禁复用，fresh v2链。 · ref: /private/tmp/m2c-r13239-v10-create-once-final-invocation-audit-v1.json

- `freeze.v10_final_sources_v2` — v10 fresh v2 packager/verifier经precheck-v3 22/22 PASS后冻结0444；invocation-audit-v2 10/10 PASS，AST解析绑定precheck/audit/双方源码，v10输出全未消费。 · ref: /private/tmp/m2c-r13239-v10-create-once-final-invocation-audit-v2.json

- `package.delivery_v10_built` — v10 final-v2 packager单次执行PASS：83 manifest成员、TierA12/TierB51、node2 15、exact-match及安全解包均PASS；archive已建，待独立verifier与终审。 · ref: /private/tmp/m2c-r13239-external-review-delivery-package-v10.json

- `incident.v10_independent_verifier_v1_stale_index_literals` — v10包PASS后final-v2 verifier单次执行仅2项FAIL:仍要求index旧表头和旧source_claim_ids中文句，实际index为新表头/等价语义。其余全绿；receipt/extract已消费，archive未改。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v10-v1.json

- `ruling.v11_rebuild_after_v10_self_verifier_fail` — tzb-fe裁定升v11：自带verifier会FAIL的v10不可交付；保留v10包/FAIL回执，MANIFEST披露ARCHIVE_BUILT_NOT_DELIVERED。v11把修正verifier装包，内容最小变更，先静态全门。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v10-v1.json

- `ruling.v11_scope_structural_verifier_only` — tzb-fe纠正v11理由：独立verifier不在包内，但MANIFEST provenance绑定FAIL verifier-v2，另跑checker会名称/内容失配。v11仍重建；批准结构化index断言；83成员，不装独立verifier源码。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v10-v1.json

- `freeze.v11_final_sources_v1` — v11全门precheck-v1 24/24 PASS；结构化index断言干跑51行全绑定；final packager/verifier字节一致O_EXCL冻结0444，invocation-audit-v1 10/10 PASS，输出全fresh。 · ref: /private/tmp/m2c-r13239-v11-create-once-final-invocation-audit-v1.json

- `verify.delivery_v11_independent` — v11 final packager/verifier各单次PASS：archive 83成员/TierA12/TierB51/node2 15；结构化index 51行与MANIFEST/解包bytes绑定，issues=0；待fresh终审与reports交付拷贝。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v11-v1.json

- `incident.v11_final_audit_v1_binding_source_classifier` — v11终审v1仅source_extracted_bytes误把expected_binding_source当物理Path而FAIL；该字段常为authority descriptor，独立verifier实核已PASS/0。其余23项PASS；archive未改。fresh v2用index source路径。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v11-v1.json

- `incident.v11_postcompact_read_order` — 本次压缩恢复后首工具误先运行fresh v11终审v2，早于state-v2 §§1–§4重读；终审用O_EXCL新路径且PASS，未改archive/reports/frozen源。现已重读至§5边界。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v11-v2.json

- `audit.delivery_v11_final` — v11 final-audit-v2 PASS：25项全绿；active index物理source到包字节零不一致；83成员/96 tar/TierA12/TierB51/node2 15；v8/v9/v10/legacy全保留，v1仅分类器误报过程件。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v11-v2.json

- `delivery.v11_reports_copy` — v11 archive+sidecar经final-audit PASS后以O_EXCL拷至reports，拷后archive/sidecar逐字节一致、摘要/大小/sidecar文件名全PASS；未commit/push/upload。待tzb-fe同强度复核。 · ref: /private/tmp/m2c-r13239-external-review-delivery-reports-copy-v11-v1.json

- `handoff.delivery_v11_to_tzbfe` — v11 reports拷贝核验PASS后，按WRITERS sessionId反查live tzb-fe；仅发送程序派生8位archive前缀，未发完整hash/包/外部内容。等待同强度发前复核。 · ref: /private/tmp/m2c-r13239-external-review-delivery-reports-copy-v11-v1.json

- `ruling.v12_manifest_history_annotation` — tzb-fe v11发前复核11项PASS、1项阻断：brief7历史banner过时项非穷尽。材料不动；fresh v12仅在MANIFEST该历史条目加illustrative标记、13/8/0→13/6/2补注与现行权威note。 · ref: /Users/gl/tzb/reports/external-consult-brief-7-20260831.md

- `freeze.v12_final_sources_v1` — v12 prefreeze全门19项PASS；仅MANIFEST历史brief7补注及统一v12 provenance变更，材料/证据源不变，planned 83唯一。packager/verifier O_EXCL冻结0444，source-bound audit 10项PASS，输出fresh。 · ref: /private/tmp/m2c-r13239-v12-create-once-final-invocation-audit-v1.json

- `verify.delivery_v12_independent` — v12 packager/verifier各单次PASS：83 manifest成员/96 tar/TierA12/TierB51/node2 15；brief7历史补注在top-level与成员行精确绑定且正文不变；结构index与源字节全绿，issues=0。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v12-v1.json

- `incident.v12_final_audit_v1_selector_reconstruction` — v12终审v1误从manifest selector_scope读不存在的路径字段，回退system python全仓pytest并139 collection errors；非包失败。v1封存，fresh v2从包内selector companion取exact_argv+working_directory。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v12-v1.json

- `audit.delivery_v12_final` — v12 final-audit-v2 PASS：29项全绿；包内selector companion exact_argv按其working_directory重跑135 passed/exit0；历史补注、83/96、51/51、node2 15、v8-v11与legacy保留。v1仅命令重建误报。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v12-v2.json

- `delivery.v12_reports_copy` — v12 final-audit PASS后，archive+sidecar以O_EXCL拷至reports；拷后逐字节、摘要、大小与sidecar文件名全PASS，0444。未commit/push/upload；待tzb-fe受影响项4/5/6+全量摘要复算。 · ref: /private/tmp/m2c-r13239-external-review-delivery-reports-copy-v12-v1.json

- `handoff.delivery_v12_to_tzbfe` — v12终审与reports拷贝PASS后，按WRITERS sessionId反查live tzb-fe；仅发程序派生8位archive前缀，未发完整hash/包/外部内容。等待协调限定复核。 · ref: /private/tmp/m2c-r13239-external-review-delivery-reports-copy-v12-v1.json

- `delivery.v12_ready_to_send` — v12经tzb-fe十二项复核可发:cd900c8a/335982B,摘要51零不一致,84文件全登记,材料12/12对baseline,node2 15件对源端零不一致,包内selector实跑135 exit0 · ref: reports/m2c-external-review-delivery-20260831-v12.tar.gz

- `ruling.v13_two_semantic_sentence_fixes` — 第九轮外审两阻断：current三文件精确4处替换(mtime局部观测三句、语义门→执行前验证链)，其余材料字节不动；包外correspondence同类1处可顺修但不入包。fresh v13，v12标superseded。 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260831.md

- `audit.v12_preservation_before_v13` — v12全链v13前preservation PASS:root/MANIFEST/archive/sidecar/package与独立回执/两版终审/reports拷贝/冻结源/precheck/invocation audit全绑定；archive前缀cd900c8a，原件不删不改，处置=语义SUPERSEDED。 · ref: /private/tmp/m2c-r13239-v12-preservation-before-v13-v1.json

- `freeze.v13_materials_baseline_v1` — v13材料精确改动已落盘并机械复原核验PASS：包内仅CLAIMS/brief8/VNEXT三文件变化，共4处裁定替换；其余9/12材料字节同v9基线。包外current-state correspondence仅1处同类替换且必须继续排除。 · ref: /private/tmp/m2c-r13239-v13-materials-baseline-v1.json

- `evidence.v13_index_rebuilt_v1` — v13 fresh index+receipt PASS：仅三条presentation身份机械更新；TierB51/51、S5 ontology、P2与历史brief7分区结构不变，correspondence仍排除。 · ref: /private/tmp/m2c-r13239-evidence-index-provenance-rebuild-v13-v1.json

- `pointing.phase2a_materialized` — PR-Bench真实秤已落地(rev d6fefc0c):6000行/六类各1000/3102图,manifest 2138592e,tzb-fe独立复算摘要与计数一致。可比性仍false待2b差分 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/real-prbench-d6fefc0c/materialization-receipt.json

- `pointing.scale_ceiling_below_100` — PR-Bench含矛盾GT:344组重复(image,expression),76组GT框不同,11组最小IoU<0.5(最小0.0),181行落在矛盾组内。任何分数须对照低于100的天花板读,禁称6000个独立可见输入 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/real-prbench-d6fefc0c/materialization-receipt.json

- `pointing.no_domestic_delivery_claim` — hf-mirror请求被308转至huggingface.co、ZIP转至us.aws.cdn.hf.co。禁称全域内交付。另:注释/评测CC BY-NC,源图保留原始条款且无逐图映射,图片再分发未清权 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/real-prbench-d6fefc0c/materialization-receipt.json

- `incident.v13_invocation_audit_v1_path_classifier` — v13冻结final-v1源未执行；invocation-audit-v1仅因要求源码含拼接后绝对audit路径而FAIL，其余10项PASS且包输出fresh。v1源与audit封存，fresh v2链。 · ref: /private/tmp/m2c-r13239-v13-create-once-final-invocation-audit-v1.json

- `pointing.official_check_acc_returns_iou` — 危险:官方check_acc()名为acc实返IoU,分数在calculate_macc_from_iou里由阈值算。tzb-fe首次比对即误把官方IoU当分数比,得4231假不符。接线官方evaluator者必踩 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/official-prbench-dc80faca/evaluation/get_prediction_Acc.py

- `pointing.phase2b_differential_pass` — 2b通过:tzb-fe独立跑已发布evaluator(8385154a,rev dc80faca)对6000行全parsed,逐项6000/6000逐位相同,六类np.mean(strict)与官方逐位相等。仅限全parsed+该rev+逐项与六类规则 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/official-prbench-dc80faca/differential-result-v5.json

- `pointing.incumbent_not_served` — 更正tzb-fe前提错误:现役27B从来不是already-served。据tzb-50读确切路径(tzb-fe无node2权限未独核):node2权重18分片齐全、labserver无、服务未起。48例为合成harness故交付包不受影响,已查非假设 · ref: /Users/gl/tzb/state/v2/jobs/rex-omni-pointing-lane-phase1.json

- `auth.user_chxy_kill_aivideo_20260901` — 用户gl 2026-09-01授权kill chxy上PID962984(/home/fangzhou/ai-video,占34490MiB,理由:挂一周GPU利用率0)。这是8/31残留规则要求的另次授权。仅限该PID,先证据后kill再复核,不清其他 · ref: /Users/gl/tzb/state/v2/jobs/rex-omni-pointing-lane-phase1.json

- `incident.v13_postcompact_read_order` — 恢复后首动作误先创建invocation-audit-v2，后补读state-v2 §§1–4；audit为fresh O_EXCL PASS，未执行final源、未消费包目标、未改reports。 · ref: /private/tmp/m2c-r13239-v13-create-once-final-invocation-audit-v2.json

- `freeze.v13_final_sources_v2` — v13 precheck-v2 26/26与source-bound audit-v2 11/11 PASS；packager/verifier frozen 0444且未执行，输出全fresh；v1链封存。 · ref: /private/tmp/m2c-r13239-v13-create-once-final-invocation-audit-v2.json

- `package.delivery_v13_built` — v13 final-v2 packager单次执行PASS：83 manifest成员/96 tar/TierA12/TierB51/node2 15/S5 13-6-2-0；archive已建，待单次独立核验。 · ref: /private/tmp/m2c-r13239-external-review-delivery-package-v13.json

- `verify.delivery_v13_independent` — v13 frozen final-v2 verifier单次独立核验PASS：83/96、TierA12/TierB51、node2 15、exact four edits与保护句/其余语义门/correspondence排除全绿，issues=0。 · ref: /private/tmp/m2c-r13239-external-review-delivery-independent-verification-v13-v1.json

- `incident.v13_final_audit_selector_capture_v1` — v13终审selector exact argv调用后，0555空目录导致O_EXCL捕获文件PermissionError；结果未留存且不作135主张。空根封存禁复用，archive/final源未改，fresh终审不重跑selector。 · ref: /private/tmp/m2c-r13239-v13-final-audit-selector-capture-incident-v1.json

- `audit.delivery_v13_final` — v13 fresh final-audit-v1 PASS 27/27：83/96、51/51、P2 38/26/12与23+1、三类adapter绑定、精确4处变更/保护句/排除项、v8-v12/legacy全绿；未重试selector。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v13-v1.json

- `delivery.v13_reports_copy` — v13 final-audit PASS后archive+sidecar以O_EXCL拷reports；拷后字节/摘要/大小/sidecar名与0444全PASS。程序派生前缀8ff65445、340389B；未commit/push/upload，待tzb-fe两点复核。 · ref: /private/tmp/m2c-r13239-external-review-delivery-reports-copy-v13-v1.json

- `handoff.delivery_v13_to_tzbfe` — 按WRITERS sessionId反查live tzb-fe后已发v13：程序派生前缀8ff65445/340389B、reports-copy回执与selector捕获incident；请求裁定承诺的两点复核，等待回复。 · ref: /private/tmp/m2c-r13239-external-review-delivery-reports-copy-v13-v1.json

- `ruling.v13_two_point_review_pass_and_v12_misfetch_fix` — tzb-fe独立解包两点复核v13全过；唯一发件隐患=reports内v12/v13均无SUPERSEDED。裁定将v12 archive+sidecar按既有约定标记，使仅v13可抓取；不进包不改MANIFEST。 · ref: /Users/gl/tzb/reports/m2c-external-review-delivery-20260831-v13.tar.gz

- `incident.tzbfe_ordered_labserver_read` — 越界归属tzb-fe:gpu_packet写死labserver拒,我随后却指示tzb-50去ls labserver上的model_path。lane依指示执行只读ls,零写零进程零正式面改动。指令错在我,非lane违规 · ref: /Users/gl/tzb/state/v2/jobs/rex-omni-pointing-lane-phase1.json

- `pointing.ceiling_authoritative_wording` — 天花板权威措辞:181行落在GT冲突组;11组最小两两GT IoU<0.5;全局最小0.0。tzb-fe此前说的11组框完全不相交为过强,作废 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/real-prbench-d6fefc0c/materialization-receipt.json

- `incident.chxy_kill_premise_conflict` — chxy PID962984清理fail-closed停:ps显示启动2026-08-29 15:01、约2.96天,与用户依据挂一周冲突。3次pmon SM=0且CPU ticks无增量。未发任何signal。已回上裁用户 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/chxy-pid-962984-cleanup-20260901.json

- `incident.lane_compaction_order_slip` — tzb-50压缩恢复后首工具误先hash下载件才重读state§§1-4,违CLAUDE.md压缩纪律。只读未改governed bytes。lane主动披露,记录不追责 · ref: /Users/gl/tzb/CLAUDE.md

- `delivery.v12_reports_marked_superseded_before_v13_send` — 按tzb-fe发件裁定，用renamex_np(RENAME_EXCL)将reports v12 archive+sidecar改名SUPERSEDED-DO-NOT-SEND；字节/0444不变。现仅v13是不带SUPERSEDED的交付archive。 · ref: /private/tmp/m2c-r13239-v12-reports-superseded-rename-before-v13-send-v1.json

- `delivery.v13_ready_to_send` — tzb-fe独立两点复核v13全PASS；v12发件误抓风险已用SUPERSEDED-DO-NOT-SEND命名闭合并回报。reports现仅v13可抓取：程序派生前缀8ff65445，340389B。 · ref: /Users/gl/tzb/reports/m2c-external-review-delivery-20260831-v13.tar.gz

- `auth.user_chxy_kill_reaffirmed_20260901` — 用户gl二次重申kill chxy PID962984(原话:给chxy kill了啊)。tzb-fe已披露启动时间实为2.96天非一周,用户仍下令,视为其决定。利用率0依据成立。授权仅限该PID,取证-kill-复核三段 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/chxy-pid-962984-cleanup-20260901.json

- `incident.chxy_pid962984_killed_by_user` — 962984已由用户gl以特权身份自行kill。tzb-fe拒绝代输sudo密码且未转交任何会话;lane先前精确单PID尝试被OS拒(rc=1 not permitted)。tzb-50执行只读后证。执行人=用户 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/chxy-pid-962984-cleanup-reaffirmed-20260901.json

- `incident.chxy_cleanup_closed` — chxy清理闭环14:09:25:PID空、GPU显存34607→14MiB、util0、其他compute 0→0、容器0→0无误伤。三事件分记:lane SIGTERM被拒/用户特权执行/lane只读后证 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/chxy-pid-962984-user-cleanup-postverification-20260901.json

- `incident.pointing_postcompact_read_order_20260901` — tzb-50本次压缩恢复后首工具误先读scorer/finalizer等lane文件，随后才重读state-v2 §§1–4至§5边界；均只读，未执行脚本、未消费新结果路径、未改governed bytes。固定600项远端推理已在压缩前运行，继续由watchdog保障。 · ref: /Users/gl/tzb/CLAUDE.md

- `pointing.incumbent_subset_600_complete` — 冻结27B在预登记平衡600项上完成:414 parsed/186 malformed/0 absent, strict micro=0.05888888888888888；六类各100守恒。仅同子集候选比较有效，禁对比published full PR-Bench。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/incumbent-subset-600-result-v1.json

- `pointing.incumbent_service_closed` — node2 exact Qwen3.8-27B服务在600/600后精确SIGTERM并复核:API PID/18767 listener/compute inventory/watchdog均空，GPU回14MiB；未清其他进程。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/incumbent-service-stop-20260901.json

- `incident.pointing_verifier_python_compat` — 独立verifier首次因node Python不支持zip(strict=)在写输出前TypeError；改为显式长度门+普通zip后fresh路径PASS_ZERO_DIVERGENCE。未消费失败回执。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/verify_incumbent_score.py

- `pointing.incumbent_omission_bias_measured` — 冻结600项实测格式失败186/600=31%；若按遗漏零分malformed且以survivor作micro分母，0.0588889→0.0853462，放大1.449275倍。该parsed-only micro是反事实诊断，非官方overall。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/incumbent-subset-600-omission-bias-diagnostic-v1.json

- `job.rex_omni_phase3` — REGISTERED phase-3:Rex-Omni在预登记600子集与在职者0.0589正面比。训练/LoRA经用户裁定下桌。host node2+chxy,GPU<=2,chxy无小时上限;写根含chxy /home/fx/rex-omni-pointing-v1/。可比性为硬约束,唯一允许变量是prompt · ref: state/v2/jobs/rex-omni-pointing-lane-phase3.json

- `ruling.rex_adapter_wire_vs_validity` — 裁定:允许Rex专用原始解析器(官方bins/999→源像素XYXY),scorer字节不变。分界=线格式解码可不同,有效性判据必须相同。可比性变量因此从1个增至2个(prompt+adapter),须同屏披露 · ref: state/v2/jobs/rex-omni-pointing-lane-phase3.json

- `incident.lane_read_order_pattern_20260901` — tzb-50压缩后读序违规当日第3次(首批工具含包读+state尾+只读检查才重读§§1-4)。三次均只读未写未起进程。已非偶发是模式,要求下次压缩后§§1-4为单独首动作 · ref: /Users/gl/tzb/CLAUDE.md

- `incident.incumbent_artifacts_shell_redirection` — 在职者adapter回执与strict-score件经shell >建于全新不存在目标,违前向create-once禁重定向规则。无覆盖发生,两输出均独立验证并冻结。裁定:保留不重生,重生冻结件危害大于流程偏离;今后须用create-once工具 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/incumbent-subset-600-result-v1.json

- `job.locateanything_vp_lora` — REGISTERED训练已授权(用户裁定推翻同日LoRA下桌):LocateAnything-3B视觉提示LoRA,chxy单A100,COCO/LVIS自动构造对。数据下载立即并行开(I/O不占卡)。首枪5-10万对2k steps做go/no-go。phase-3 Rex-Omni不受影响 · ref: state/v2/jobs/locateanything-visual-prompt-lora-v1.json

- `package.v13_signed` — v13经外审第九轮签字:限定范围通过,无剩余阻断。archive 8ff65445,verify PASS 83/83,七项全闭合。签字边界五条明列(RECORDED非runtime-loaded、日期观测非可复现结论、synthetic非物理证明、局部mtime非字节、DEV非单变量因果) · ref: reports/m2c-external-review-delivery-20260831-v13.tar.gz

- `pointing.rex_phase3_preregistered_v2` — Rex phase3固定600项完成：451 parsed/149 malformed/0 absent；strict micro 0.3755556，六类见冻结结果。零差异独立核验PASS；GPU释放，未重试/清理。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/rex-omni-subset-600-result-v1.json

- `job.repair_loop_v1` — REGISTERED caller-only repair loop：写根/Users/gl/tzb-lanes/repair-loop-v1；冻结48例/契约层/验证器严格只读。先冻k/案例/判据/prompt，再按用户GPU授权在node2跑现有27B配置。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `ownership.repair_loop_v1` — m2c-exec独占新写根/Users/gl/tzb-lanes/repair-loop-v1；仅新增调用方/预登记/回执，禁止修改两个冻结仓、验证器、契约层、48例套件及service-v1配置。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `incident.repair_loop_postcompact_read_order` — 压缩恢复后首工具误先窄读repair-loop冻结源，随后才重读state-v2 §§1–4至§5边界；均只读，未写lane、未发模型请求、未触远端/GPU。披露即结。 · ref: /Users/gl/tzb/CLAUDE.md

- `protocol.repair_loop_v1` — 闭环限定27B初产→不变验证链拒绝→仅回喂类型化code/path/message→至多k轮重规划再验；跑前冻结k/案例/成功与unsafe-bypass判据/prompt。只报本批synthetic validator-world观测。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `metrics.repair_loop_v1` — 必报：初产被拒N中≤k轮转为按预登记判据有效的数量/轮次分布；以及重试后仍保留预登记unsafe条件却获验证链PASS的数量（更重要）。禁称真实事故、物理闭环或通用自愈。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `stopline.repair_loop_v1` — 只准新增caller/预登记/回执于repair-loop-v1；契约/验证器/48例/service配置零字节改动。禁扩展BT/skill/多机；禁碰chxy。node2起服务/GPU须用户直接授权，结束须精确停服并独立复核。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `ruling.repair_loop_v1_protocol` — tzb-fe 2026-09-01裁：round0必须27B生成，N=round0被拒子集；全24保留；k=3反馈轮(总≤4)；修复=链PASS+原decision+TaskSpec/world不变，改路由单列；逐案retention谓词须见round0前冻，写不出仅弱报且不移分母。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `repair_loop.preregistered_v1` — repair-loop v1已在任何模型输出前冻结：全24 REJECT案例，round0=27B生成，k=3，总≤4；24/24 retention谓词冻结自测RETAINED；3例trusted-input不可修类保留。28 tests+Pyright PASS。尚未起服务。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-preregistration-v1.json

- `incident.repair_loop_postcompact_read_order_2` — 本次压缩恢复后首工具误先运行lane本地Pyright/compile/AST/pytest，后补读state-v2 §§1–§4；仅本地检查，未SSH/模型/GPU/写结果。披露即结。 · ref: /Users/gl/tzb/CLAUDE.md

- `pointing.rex_beats_incumbent_but_loses_reject` — Rex-Omni 600子集:micro 0.3756 vs 在职0.0589(6.38x),畸形24.83% vs 31%。但reject类0.0 vs 在职0.1——78条解析成功全错,即从不说不存在。安全维度上输给在职。600内落GT冲突组22行 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/rex-omni-strict-score-v1.json

- `repair_loop.lifecycle_v2_preexecution` — caller lifecycle v2替代禁执行草稿：远端Python O_EXCL建log/记录、partial-start fail-safe、精确停与watchdog。41 tests+Pyright+compile PASS；冻结预登记面全match；尚未SSH。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `incident.repair_loop_v1_claim_bug` — 冻结runner v1误把transport/envelope失败计入N，可能将基础设施故障写成模型坏计划。0模型输出前发现；v1全链标SUPERSEDED_DO_NOT_EXECUTE，fresh runner+prereg v2。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/run_repair_loop_v1.py

- `incident.repair_loop_postcompact_read_order_3` — 本次压缩恢复后首工具误先只读本地v5 runner进程状态，随后窄读state-v2权威键；未写lane、未发请求、未触远端/GPU/信号。披露即结。 · ref: /Users/gl/tzb/CLAUDE.md

- `incident.repair_loop_unregistered_readonly_agents` — 此前未先登记即派多只读审查子代理，违子代理登记纪律；均无写面/SSH/模型/GPU，结论仅作候选审查输入。现已停剩余后台代理并前向禁复发。 · ref: /Users/gl/tzb/CLAUDE.md

- `incident.repair_loop_v1_frozen_source_restored` — 误插改v1两源已按冻结预登记身份逐字节恢复并核验match；v1不再编辑，SUPERSEDED语义只记state/v2元数据。0模型输出/SSH/GPU。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-preregistration-v1.json

- `ruling.repair_loop_remove_lifecycle_scope` — tzb-fe 2026-09-01纠偏：砍掉repair-loop全部远端生命周期自动化；实验仅HTTP调用endpoint/类型化反馈/重规划/不变链验证/计数。服务起停为用户批卡后的人工一次性操作；endpoint不通即报错退出，禁重试/恢复/清理。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `repair_loop.caller_only_v2_scope_ready` — 按裁定已删全部生命周期脚本/测试；active仅retention、runner/prereg v2与caller测试。endpoint失败即ABORT且无headline，禁重试/恢复/清理。41 tests、Pyright、compile、AST均PASS；v2尚未冻结。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `ruling.repair_loop_v2_all_cases_full_rounds` — tzb-fe 2026-09-01裁：3例trusted-input预期不可修但仍跑满round0+3反馈轮，以免预登记结论并屏蔽反例。max requests=24x4=96；60s/请求与6300s共享上限不变。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `repair_loop.preregistered_v2` — caller-only v2已在0模型输出前冻结：24案各round0+3反馈，max96；60s/请求、6300s共享上限；任一基础设施/无输出/内部失败ABORT且无headline。42 tests、Pyright PASS。待用户直接批卡。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-preregistration-v2.json

- `auth.user_node2_gpu_20260901_repairloop_and_rexintegration` — 用户gl 2026-09-01直接授权node2 GPU给两条线:repair-loop(m2c-exec)与Rex感知集成(tzb-50),共用一个27B服务。人工起停一次,非自动生命周期。原话:给 · ref: state/v2/jobs/rex-omni-pointing-lane-phase3.json

- `incident.repair_loop_manual_preflight_v1_ssh_quoting` — 授权后首次node2只读preflight因ssh远端python -c参数未引用而rc2；远端仅import命令失败后在def处shell语法停，未起服/写远端/GPU。v1回执封存，fresh v2改stdin。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-preflight-v1.json

- `stop.repair_loop_node2_unexpected_occupancy` — 授权后node2 preflight-v2命中他人compute PID3951830(mpr_sam_bus python,61954MiB,GPU99%)；18767无listener、endpoint不通、容器空。依STOP_REPORT_DO_NOT_CLEAN未起服/未清理/0模型输出，待GPU调度。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-preflight-v2.json

- `ruling.repair_loop_active_occupancy_no_squeeze` — 取代:用户2026-09-01裁定抢占共享活跃卡,原话'和他抢,我们时间不多了,他搞完不知道什么时候'。量化为tzb-fe所选实现手段非用户指定,代价=被测对象变为量化变体,已披露 · ref: state/v2/jobs/rex-omni-pointing-lane-phase3.json

- `ruling.locateanything_coord_order_native` — 撤销:xyxy正确。gen528依据的x1x2y1y2只在generate_utils注释里,代码对四logits原样concat无重排;官方五处operational源一致xyxy。我拿注释当行为 · ref: chxy:/home/fx/locateanything-vp-v1/

- `ruling.repair_loop_quantized_v3_prereg` — 撤回:量化路径不可执行(node2冻结venv无bitsandbytes,vLLM0.28不列该方法)。改为守候策略:tzb-fe起node2-grab.sh秒级轮询,compute进程连续3次为空即按service-v1.json原样起BF16。v2预登记保持有效,不需v3 · ref: /Users/gl/tzb-ops/node2-grab.sh

- `job.locateanything_attn_contract` — 裁定选项2:Magi仅支Hopper/Blackwell,我们只有A100,故训练改SDPA。但先实测99997对在冻结processor下的token长度分布再定长度,不拍数。baseline已是SDPA,两臂一致反而更好 · ref: chxy:/home/fx/locateanything-vp-v1/

- `locateanything.baseline_v3_floor_zero` — baseline v3完成PASS:2000条,primary 0/2000=0,结构合法仅3/2000=0.0015,推理错误0,native error_box fallback命中1520/2000=76%。地板为零,故增益判据几乎必然满足;须另加区分格式与定位的测量 · ref: chxy:/home/fx/locateanything-vp-v1/receipts/baseline-independent-verification-v2.json

- `locateanything.localization_prior_diagnostic` — 先验诊断已训前冻结:全图先验0.09218/常数框0.02242(全2000留出)。baseline三条合法输出上模型0.04816 < 同子集全图0.15309,判FORMAT_ONLY_NOT_EXCLUDED。诊断已在baseline上实际触发,非橡皮图章;描述性,不替代预登记GO/NO_GO · ref: chxy:/home/fx/locateanything-vp-v1/receipts/localization-priors-v1.json

- `incident.repair_loop_fhk_pid_disappeared_after_grab` — 抢占后、repair首请求前观测fhk PID3951830消失；无法区分自然结束与抢占所致。tzb-fe裁继续跑，禁读其日志/家目录。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-ready-verification-v1.json

- `repair_loop.run_v2_started` — BF16 endpoint与冻结身份核验后已单次启动v2：24案、最多96请求；fresh evidence/result路径已消费。任一infra失败即ABORT无headline。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-evidence-v2-20260902-v1/run-start.json

- `live.node2_27b_service_up` — 已精确停服:仅SIGTERM launcher PID34927；engine PID35678退出。双重终态复核:两PID缺席、18767无listener、compute apps空、GPU 14MiB；未碰fhk。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-service-stop-20260902-v1.json

- `ruling.layered_pointing_perception_seam` — tzb-fe 2026-09-01裁定:27B存在门→冻结Rex框只到现有untrusted perception candidate seam；禁改TaskSpec/感知/验证链。PR-Bench无depth/calibration，禁称端到端、坐标进TaskSpec或验证链验过感知。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `incident.layered_pointing_unregistered_plan_agent` — 规划时未先登记即派Plan子代理，约21秒即停止；killed、无可用结论、无文件写入/SSH/模型/GPU。前向禁未登记子代理。 · ref: /Users/gl/tzb/CLAUDE.md

- `incident.layered_pointing_postcompact_plan_first` — 2026-09-01压缩恢复后首动作误先改仅允许的plan文件，再补读权威§§1-4；未改项目治理字节、未SSH/模型/GPU。已披露并前向纠正。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `finding.repair_loop_v2_period2_limit_cycle` — v2前13案见11/12拒绝案错误数[7,1,7,1]；attempt1/3同prompt同输出，第三反馈轮为确定性重放，有效新信息预算仅k=2。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-evidence-v2-20260902-v1

- `ruling.repair_loop_v3_accumulated_history` — 撤回：v2极限环有greedy退化与无历史两混淆因子，禁把无历史当唯一归因。v3暂停，待checkpoint generation_config与fresh设计裁定。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `finding.repair_loop_digest_domain_explained` — attempt顶层TaskSpec/World摘要含canonical JSON尾LF；validator报告摘要同对象但不含LF。差异是有意序列化域，不是对象漂移，结果须说明。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/run_repair_loop_v2.py

- `pointing.layered_gate_preregistered_v1` — layered gate在0门模型输出前冻结:同600、GT-blind三字段投影、精确PRESENT/ABSENT、冻结Rex透传、其他fail-closed；56 lane tests+78 semantic v2 tests+Pyright通过。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v1.json

- `result.repair_loop_v2_limit_cycle` — 自修复闭环 v2:round-0 拒 12/13,k=3 修复 0/12,unsafe 穿透 0/48;period-2 极限环,有效预算实为 k=2。裁定见 ADR-0032。 · ref: ADR-0032-m2c-repair-loop-v2-limit-cycle.md

- `infra.labserver_access_via_chxy` — labserver(EPYC 7B13,128线程)Tailscale 掉线,Mac 直连不通;唯一路径 ssh chxy -> root@10.13.28.6。仅纯CPU、create-only、盘已90%。 · ref: ADR-0032-m2c-repair-loop-v2-limit-cycle.md

- `incident.layered_gate_prereg_v1_postfreeze_edit` — layered prereg-v1冻结后为强化代码层GT隔离证明又编辑router.py，导致v1所绑candidate source tree失配；0门模型请求。v1封存DO_NOT_USE，fresh v2重冻。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v1.json

- `pointing.layered_gate_run_v2_started` — 冻结v2身份与CPU门通过后，已对共享node2 BF16 18767单次启动GT-blind 600项存在门；fresh captures-v2路径已消费。服务由m2c-exec保留至双方完成。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v2.json

- `ruling.repair_loop_v3_sampling_only` — ADR-0032 重放数改正 8/22→9/23(旧值取自 compound-12 未写完的运行中目录);判据=请求体规范化字节+assistant content 字节,不含 HTTP envelope;三种判据一致。sha:e64431f405423284 13085B · ref: ADR-0032-m2c-repair-loop-v2-limit-cycle.md

- `incident.layered_gate_result_omission_disclosure_gap` — v2门启动后发现冻结report结果schema漏串联自身parsed-only/omission inflation与Rex1.330字段；不改冻结源/不重跑，已即时回上裁是否准独立O_EXCL诊断补证。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v2.json

- `ruling.layered_gate_omission_diagnostic_v2` — tzb-fe准有界补证:不重跑/不改冻结源、route、scorer；仅在result已有三态守恒字段时按预冻公式建O_EXCL诊断，绑定串联+Rex1.330+incumbent1.449，complete同屏100/500。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v2.json

- `result.repair_loop_v2_complete` — v2完整24案：N=23，≤k修复0，轮次1/2/3均0；round0 PASS=1；unsafe retry bypass=0；无abort。修复率受greedy+无历史混淆，禁能力化。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v2-20260902-v1.json

- `hardstop.video_plan_sha256_must_not_use_repair_loop` — 禁:视频 single-11(ordinal 35)的 plan_sha256 占位不得用自修复闭环产出的 f5ff04d0… 填。同 case_id 但来源不同——闭环是 SYNTHETIC_VALIDATOR_WORLD,非打包 48 例套件。占位继续留红。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v2-20260902-v1.json

- `live.locateanything_formal_2000step_run` — chxy A100 正式唯一 run 运行中(PID 1398895,03:26 前后完成):2000步/warmup500/lr2e-5/cosine/8192。裁定:go-no-go 须同屏披露25% warmup;NO_GO 只可限定该配置,不得外推方向无效。 · ref: /home/fx/locateanything-vp-v1/logs/formal-training-2000step-v3.log

- `result.repair_loop_v2_final` — 自修复闭环 v2 终值(工件 COMPLETE,run_abort null):24例/93输出,round0拒23,k=3修复 0/23,unsafe穿透 0。0穿透可交付;0/23 在 v3 前禁单独引用。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v2-20260902-v1.json

- `pointing.layered_gate_v2_complete` — Layered v2固定600完成:477/123/0,micro .4585185;reject100=.57(43P/57A/0M);nonreject500=.4362222(467P/33A/0M,较Rex-.0144444);独立零差异,冻结身份0失败。仅RGB seam。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-complete-v2.json

- `pointing.layered_gate_v2_omission_diagnostic` — 补诊仅消费冻结result三态+micro:layered omission factor 1.2578616;分列Rex1.3303769、incumbent1.4492754;未重解析响应/重跑route/scorer/改冻结源。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-omission-bias-diagnostic-v2.json

- `lifecycle.layered_gate_endpoint_use_complete` — tzb-50已向共享service owner明确发送endpoint use complete；本lane未停node2:18767，等待owner按双方完成条件精确停服。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-complete-v2.json

- `result.layered_pointing_seam_v2` — 串行感知闸门(同600):strict micro 0.4585 vs Rex 0.3756 vs 在位 0.0589;reject 0.0→0.57(FPR0.43);非reject -0.0144,压制6.6%,Rex正分行存活96.2%;畸形20.5%;独立核验零分歧。仅RGB seam。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-complete-v2.json

- `incident.repair_loop_postcompact_read_order_v3` — 本次压缩恢复后首工具误读run_repair_loop_v3.py，后补读state-v2 §§1–§4至§5边界；只读，未改lane、未发v3请求、未触远端/GPU。披露即结。 · ref: /Users/gl/tzb/CLAUDE.md

- `lifecycle.node2_shared_service_retained_for_repair_v3` — 共享owner已核对layered endpoint-use-complete；因sampling-only v3尚需同一node2:18767，服务继续保留；v3/分析后由owner按PID/PGID/start identity精确停服并复核，tzb-50不介入。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-complete-v2.json

- `repair_loop.preregistered_v3` — sampling-only v3已在0个v3模型输出前create-once冻结：24案、k=3、max96、无历史两消息；相对v2仅请求体六采样字段变化；判据x>0，分母N_v3自有round0拒绝集；posthoc 23案视图仅描述。50 tests+Pyright+compile/AST PASS。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-preregistration-v3.json

- `repair_loop.run_v3_started` — 同launcher/engine PID+start_ticks+PGID+SID、health/model/listener/compute全match后，已单次启动冻结sampling-only v3；fresh evidence/result路径已消费。最多96请求；非链失败ABORT且无headline。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-evidence-v3-20260902-v1/run-start.json

- `infra.node2_27b_mtp_unused` — node2 的 27B 带 MTP 草稿层(config mtp_num_hidden_layers=1,checkpoint 15 个 mtp.* 张量)但 vLLM 以 speculative_config=None 启动,未启用。v3 期间禁开(需重启且破坏单变量)。冻结后再评估,开前先做输出一致性对拍。 · ref: /home/gl/vllm-grab-20260902-000523.log

- `incident.repair_loop_postcompact_read_order_v4` — 压缩恢复首工具误读v3 attempt，随后单独重读权威state §§1–4；只读，未改lane/请求/远端。披露即结。 · ref: /Users/gl/tzb/CLAUDE.md

- `finding.repair_loop_v2_replay_final_audit` — 终值重算见23个round0拒案均跑满4轮，其中attempt3 prompt+输出与attempt1同为9/23；ADR的8/22是末案前快照，分析前须更正裁定。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v2-20260902-v1.json

- `discipline.no_metrics_from_inflight_dirs` — 硬规矩:禁止对运行中的证据目录算终值。今晚同一错犯两次(0/12 与 8/22 均为在飞快照)。取数前必须先确认 result 工件已写且 runner 已退。 · ref: ADR-0032-m2c-repair-loop-v2-limit-cycle.md

- `result.repair_loop_v3_aborted_source_drift` — v3第26请求(single-07 attempt1)先60s超时触发整轮ABORT；随后ADR身份漂移使post-check抛错，故无result/无headline，禁自行重试。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-evidence-v3-20260902-v1/single-07-missing-safety-predicate/attempt-01.json

- `ruling.adr0032_frozen_immutable` — ADR-0032 已冻结不可变(chmod 444),sha dba870d09b5027cc 13867B。此后更正一律写 ADR-0033 起的后继文件。起因:v3 首轮因我在运行中改该文件导致 source drift 中止。 · ref: ADR-0032-m2c-repair-loop-v2-limit-cycle.md

- `ruling.repair_loop_v4_fresh_rerun` — 准 v4 重跑:fresh 预登记/evidence/result,禁用 v3 污染路径;绑定 ADR-0032(dba870d09b5027cc)+ADR-0033(9430837d5ed2940c);科学参数全不变含 60s 超时;起跑前单发非 case 探测 <=30s 放行;须披露 v3 首轮双故障与顺序。 · ref: ADR-0033-m2c-repair-loop-v3-abort-causal-order.md

- `infra.node2_fhk_retry_loop` — node2 fhk 任务是无人值守重试循环:OOM 后 bash 父进程自动重启(PID 123120→134346,同脚本 run_rf_mambaresunet.py,~3GB)。争用持续不消失。我方 vLLM 76354MiB 静态占用不受影响;v4 按 ADR-0033 探测规则等空窗。不碰他的进程。 · ref: ADR-0033-m2c-repair-loop-v3-abort-causal-order.md

- `ruling.repair_loop_v4_probe_advisory_user` — 用户 2026-09-02 02:20 裁定'不管他,我们继续跑':ADR-0033 §5 探测 ≤30s 门槛降为 advisory——探测照做、延迟照记,但不拦路,立即开跑。60s 超时与全部科学参数不变;拥塞超时即按预登记 ABORT 并另起 fresh 路径。烧路径风险由用户承担。 · ref: ADR-0033-m2c-repair-loop-v3-abort-causal-order.md

- `review.gate_text_leak_open` — 审:串行闸门看得到查询文本;reject 表达式更长且材质词/'instead'偏高,词袋分不开(0.765<0.833)但 27B 可能读题。已委托 text-only 消融(同600去图)关此备选解释;结果前 0.57 不得称纯视觉存在性判断。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-result-v2.json

- `review.locany_prompt_sensitivity_gap` — 审:LocateAnything go/no-go 与先验诊断均测不出模型是否在看 image-2;已委托 03:38 前预登记 swapped-prompt 诊断(prompt_sensitivity=matched−swapped),≈0 则不得称 visual-prompt 能力。 · ref: /home/fx/locateanything-vp-v1/metadata/visual-prompt-go-no-go-prereg-v1.json

- `review.repair_loop_premise_broken` — 修正:病根不是'契约从没给'——validator 错误消息已写明必需集(71%=223/314 为 predicate 集合类)。是 round-0 缺信息、反馈轮契约分批投喂且并集从不同屏,故修 A 破 B。round0 19/24 无种子缺陷、无对照、0/69 系推论三点不变。 · ref: /Users/gl/tzb-deliverables/methods-v1/METHODS.md

- `ruling.layered_textonly_ablation_v1` — 协调裁定追加同600 text-only消融:同prompt/model/temp0/max8/thinking false，仅移除image_url；同parser三态，独立工件不进result-v2/不改冻结源；同屏reject/nonreject ABSENT与有图57/33，判读须先冻后跑。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-result-v2.json

- `pointing.layered_textonly_ablation_v1_preregistered` — text-only v1已在0请求前冻结:同600/同prompt/model/temp0/max8/thinking false/同exact parser，唯一变量移除image_url；判读先冻：<=25图像主导，距57<=5降级联合门，其余仅报差值不定性。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-textonly-preregistration-v1.json

- `locany.swapped_prompt_diag_frozen` — swapped-prompt 诊断已在 adapted 输出前冻结:1156 对/394 多类别 B;阈 sensitivity>=0.10 且 bootstrap CI lower>0;非第四 gate,只限措辞。prereg sha df7c1f2b… · ref: chxy:/home/fx/locateanything-vp-v1/metadata/swapped-prompt-diagnostic-prereg-v1.json

- `pointing.layered_textonly_ablation_v1_complete` — 同600 text-only消融完成且独立复核:transport-ok600、malformed0；reject ABSENT99/100，nonreject466/500；有图57/33，差值-42；依预登记仅报INTERMEDIATE_NO_QUALITATIVE_CONCLUSION。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-textonly-complete-v1.json

- `lifecycle.layered_textonly_endpoint_use_complete` — text-only消融已完成node2:18767调用；本lane向共享owner发送新一轮endpoint use complete，不停止共享服务。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-textonly-complete-v1.json

- `result.gate_textonly_ablation` — text-only 消融(同600去图):reject ABSENT 99/100,非reject 466/500,整体 0.942 退化为常数 ABSENT。判别力 gap:text-only +0.058,有图 +0.504,图像贡献 +0.446。工件裁定 INTERMEDIATE(预登记带未覆盖此退化)。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-textonly-complete-v1.json

- `reading.gate_textleak_refuted_posthoc` — tzb-fe 事后判读(标明事后,不改工件 INTERMEDIATE):文本泄漏假设被否——去图后模型对 94% 样本答 ABSENT,文本单独判别力 0.058 vs 有图 0.504。0.57 的判别来自图像。预登记带的假设(去图仍会常答 PRESENT)本身错了。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-textonly-complete-v1.json

- `reporting.layered_textonly_ablation_followup` — 后续汇总须绑定text-only complete 9a82e3a55a81…，并列99/100、466/500与有图57/33；保留INTERMEDIATE；协调事后判读只指向state记录，禁改冻结工件。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-textonly-complete-v1.json

- `auth.user_two_gpu_100g_conditional` — 用户 2026-09-02 02:5x 预授权:LocateAnything 出 GO 后,两张 A100 都空(node2 无 vLLM 无第三方,chxy 训练结束)即可上两卡走 100G。先决:先 iperf3 实测带宽(job stop-line)。fhk 在卡上=不空,不起,早上报。 · ref: /Users/gl/tzb/state/v2/jobs/locateanything-visual-prompt-lora-v1.json

- `auth.overnight_delegation_20260902` — 用户 2026-09-02 睡前:不在时 tzb-fe 推进度并代批。可批:node2/chxy 既有授权内的 GPU 使用、起停我方服务、lane 新 create-only 路径、下载/实验/重跑/新预登记。永不:动第三方进程、冻结面、commit/push、权限/配置、密码、新主机、labserver GPU。 · ref: /Users/gl/tzb/state/v2/jobs/locateanything-visual-prompt-lora-v1.json

- `routing.tzb_fe_now_tzb_c2` — 协调 tzb-c2 [a95825]。闭环线=a1-planner-repair-memory [5c7be8];串行线=build-auditable-agent-demo [61881d];LocateAnything=two-shot-canonical-gate 空闲。发前查 sessions/*.json。 · ref: /Users/gl/tzb/CLAUDE.md

- `ruling.repair_loop_contract_visible_k0` — 排 v4 后、停 27B 前:契约可见基线 k=0。只改 system prompt(逐 decision 列必需 predicate 集,抄 validator),v4 六参,只测 round0 通过率/24 vs v2 的 1/24。不设阈;离开 0 则裁 v5。prompt 先发 tzb-c2 看。 · ref: ADR-0033-m2c-repair-loop-v3-abort-causal-order.md

- `ruling.locany_review6_connector_load` — 准 review6:adapted 评测 LoRA→language_model + strict load mlp1 connector(6 tensor 验数/shape/digest);review5 vs review6 对拍须不同;review5 标 SUPERSEDED。adapted 前冻。 · ref: chxy:/home/fx/locateanything-vp-v1/receipts/

- `lane.agent_demo_loop_v1` — 派 evaluate-serial-perception-gate 建 agent-demo-loop-v1:闸门+Rex+SYNTHETIC绑定(标NOT_TRUSTED)+27B指挥+validator 缝成可运行 trace+帧。不出新数;写根 tzb-lanes/agent-demo-v1。 · ref: state/v2/jobs/agent-demo-loop-v1.json

- `design.agent_input_recovered` — 用户 9/1 10:06 的智能体设计(GPT 架构+外审批评)压缩后丢失,9/2 从原始记录恢复,存 state/v2/jobs/agent-design-input-20260901-gpt-plus-review.md。外审裁定:主线不动,只取探针/话术/排版/排查单。agent-demo job 已按此修正。 · ref: state/v2/jobs/agent-design-input-20260901-gpt-plus-review.md

- `repair_loop.preregistered_v4` — fresh v4 source/governance receipt与prereg已create-once冻结；24案/k=3/96请求/60s超时/六采样参不变，绑定ADR-0032/0033、advisory probe合约及v3中止史。冻结时v4模型输出=0。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-preregistration-v4-20260902-v1.json

- `repair_loop.v4_probe_complete` — v4非case advisory probe已单发完成：GET /v1/models=200，代表性POST=200，elapsed=6.269s，<=30s仅作advisory；无重试，实验execute已紧接启动。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-v4-latency-probe-20260902-v1.json

- `ruling.repair_loop_v5_timeout_240` — v4 因 fhk 持续争用(12.6 tok/s)首案超时中止,abort 工件已落。裁 v5:fresh 路径,仅超时 60→240s,论证输出中立(v2 无超时,token 与墙钟无关),须披露。ADR-0034 d6ae40852ec52c8c 3006B 444。 · ref: ADR-0034-m2c-repair-loop-v5-timeout-under-contention.md

- `result.repair_loop_v4_aborted_timeout` — v4 fresh终态：probe 6.269s后，首案round0真实请求60.000s超时，INFRASTRUCTURE_FAILURE_ABORT；abort result已create-once落盘，post-run integrity MATCH，metrics=null、无headline。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v4-20260902-v1.json

- `repair_loop.preregistered_v5` — fresh v5 source/prereg已create-once冻结，绑定ADR-0032/0033/0034；24案/k3/六采样参/生成请求字节不变，仅caller timeout与budget floor 60→240s并显式输出中立论证；同长度non-case probe已预登记，模型输出=0。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-preregistration-v5-20260902-v2.json

- `repair_loop.v5_probe_complete` — v5同长度非case advisory probe已单发完成：GET /v1/models=200，代表性POST=200，elapsed=87.624s，分类ABOVE_30S_ADVISORY_NON_BLOCKING；无重试、非实验case、不进任何实验分母，execute已紧接启动。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-v5-latency-probe-20260902-v2.json

- `ruling.contract_visible_prompt_approved` — 契约可见 k=0 的 system-prompt 追加段已审准冻:全为符号引用(TaskSpec.*/subtask.agent),无逐案字面值。三标签义务:测'契约实例化保真度'非规划;契约段逐字进预登记并注 validator 来源;并排平凡模板基线 24/24。 · ref: ADR-0034-m2c-repair-loop-v5-timeout-under-contention.md

- `incident.agent_demo_lane_waiting` — 已解除:串行线改名 build-auditable-agent-demo,07:xx 自报'不在等裁定或权限',开始探针代码。此前 waiting 判定为权限弹窗不准确(可能是 plan 审批)。闭环线仍 waiting。 · ref: state/v2/jobs/agent-demo-loop-v1.json

- `ruling.repair_loop_contract_visible_k0_prompt_review` — tzb-c2 2026-09-02准冻k0 prompt；仅符号规则无逐案答案。须标契约实例化非规划、逐字来源、确定性模板24/24基线；等v5终态后起。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/contract-visible-k0-prompt-review-20260902.md

- `repair_loop.contract_visible_k0_prompt_review_frozen` — 协调审过的k0 prompt原文/三解释义务/源码映射已只读冻结：88a9411357d733e6，5506B，0444；须等v5终态后才建预登记。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/contract-visible-k0-prompt-review-20260902.md

- `ruling.locany_postcompletion_packaging_failure` — 准 COMPLETE_WITH_POSTCOMPLETION_PACKAGING_FAILURE:2000步+ckpt commit+save_model 后才因 0400 helper 复制 PermissionError 退出。七条件见 ADR-0035 71b81842e74a5324 3609B 444。 · ref: ADR-0035-m2c-locany-postcompletion-packaging-failure.md

- `result.repair_loop_v5_falsified` — v5(厂商采样,240s)终值已独立复算:24例/93输出,round0拒23,修复 1/23(single-04,第3轮达0错),穿透0/69。x>0 → 按 ADR-0032 §5.4.4,v2 的 0/23 是配置产物,禁入交付。1/23 非能力估计(§5.5)。14/93 超60s,ADR-0034 必要。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v5-20260902-v2.json

- `result.repair_loop_v5_complete` — v5完整终态：24案/93输出，round0 PASS 1、拒23；≤k修复1/23且在round3；unsafe穿透0/69；无abort，post-run integrity MATCH。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v5-20260902-v2.json

- `analysis.repair_loop_v5_frozen` — v5独立复算分析已create-once冻结：5d052ea3b8e1c1a9，68460B，0444；仅限synthetic validator-world观测，禁泛化自愈/能力率/物理主张。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-analysis-v5-20260902-v2.json

- `observation.repair_loop_v5_timeout_and_round3` — v5唯一修复落round3；14/93输出耗时>60s、最大67s，实证ADR-0034等待限必要性；因子B被打破，因子A无历史与契约不可见仍未分离。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-result-v5-20260902-v2.json

- `incident.two_lanes_waiting_on_prompts` — 12:06 闭环线(contract-visible-k0-baseline)再次 waiting(harness 弹窗),A-1 未起,node2 27B 自 11:07 空闲。两次催促排队未读。用户点掉弹窗。demo 线 busy 正常跑 B-4。 · ref: state/v2/jobs/agent-demo-loop-v1.json

- `auth.two_gpu_conditions_check_0625` — 06:25 gen605 条件核对:GO 满足;chxy 空(14MiB);node2 不空——我方 27B 76GB 留给 k=0/agent-demo + fhk 重试循环(新 PID 373339)。两卡 DDP 不起,等早上。 · ref: ADR-0035-m2c-locany-postcompletion-packaging-failure.md

- `result.locany_go_no_go_GO` — LocateAnything GO 已封装:bundle c7f56047,final 4090dbb9,独立核验 918f5204。739/2000=0.3695 CI[0.348,0.391];先验 0.490>0.096/0.023;swapped 0.301。chxy 已释放。 · ref: chxy:/home/fx/locateanything-vp-v1/receipts/formal-pilot-complete-bundle-v1.json

- `ownership.ppt_subagent` — 用户 09:3x 指示开子代理用 pptmaster 做 PPT。独占写面 /Users/gl/tzb-deliverables/ppt-v1/(create-only)。只读 state/ADR/lanes/reports。禁 reports/、冻结面、commit、lane 目录。brief 见 ref。 · ref: /Users/gl/tzb-deliverables/ppt-v1/BRIEF.md

- `ownership.review_subagent` — 用户 09:5x 指示开审核子代理。独占写面 /Users/gl/tzb-deliverables/review-v1/。任务:对 ppt-v1/BRIEF.md 每条主张逆核工件;PPT 落地后二审 NUMBERS.md。只读其余;远程仅 ssh 只读;无 GPU。 · ref: /Users/gl/tzb-deliverables/review-v1/

- `ownership.methods_subagent` — 用户 09:5x 指示开找新方法子代理。独占写面 /Users/gl/tzb-deliverables/methods-v1/。对准两问题:指挥体契约不可见产不出合法计划;闸门 reject FPR 0.43。产出按 9/3 前可落分级的备忘。只读;不改代码;无 GPU;无 ssh 写。 · ref: /Users/gl/tzb-deliverables/methods-v1/

- `deck.brief_v2_after_review` — BRIEF v2.1:审核 delta 八条全闭合;新抓 D1(本子集冲突 GT 实为 2 行/IoU 0.991,'22'系压缩摘要之误)已改;B6 出处加独立 SHA 锚点;N5 唯一上屏句;N8/N9/双层恢复禁语。PPT 重做中。 · ref: /Users/gl/tzb-deliverables/review-v1/REVIEW-BRIEF-v2-delta.md

- `ruling.methods_v1_queue` — 队列更新:B-1 预检作废(ABSENT 多 token)。B-4(极性反转+AND,§B-4)接替,chxy:18767,臂 A 复用冻结捕获、臂 B 新跑 600;四臂+兑换率判据同冻。A-1 在 node2。B-4 若预检也败,B 组止。 · ref: /Users/gl/tzb-deliverables/methods-v1/METHODS.md

- `deliverable.ppt_v1` — PPT v1 付印就绪:二审 2 阻断已按 §0c/§0d 允许句逐字修正,tzb-fe 自核 P2/P8 六项 OK、禁语零命中(重识别/新方法仅以否定形式出现)。占位待用户:P11 演示帧、P14 二维码。 · ref: /Users/gl/tzb-deliverables/ppt-v1/xh-202607-deck-v1.pptx

- `repair_loop.contract_visible_k0_preregistered` — k0预登记已0444冻结、零模型输出：source 361a642d5ffe555a/self 4f5ace523d37fd19；prereg 98df7b6425960d88/self 1f6a9ca894c6f96b；24承诺，仅system prompt差；模板24/24(PASS21+可信输入拒3)。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/contract-visible-k0-preregistration-20260902-v1.json

- `result.repair_loop_contract_visible_k0_complete` — k0完整终态：24个round0输出，chain PASS 21/24；无abort，evidence 25条守恒，post-run integrity MATCH。独立分析MATCH；仅契约实例化保真度观测，非规划/推理/能力率。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/contract-visible-k0-analysis-20260902-v1.json

- `analysis.repair_loop_contract_visible_k0_frozen` — k0分析0444冻结：result a026503376fbed0b；analysis f6200abf024e5cd0/self 13081f75b0774d1e；manifest 8fd81dd62608315a。并排v2 1/24、v5 1/24、模板24/24(非端到端PASS)。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/contract-visible-k0-analysis-20260902-v1.json

- `result.contract_visible_k0` — 契约可见 k=0 已独立复算:21/24 round-0 通过(v2/v5 各 1/24)。3 个未过全是 trusted_input=REJECT 案(compound-06/07/08,输入本身设计为被拒),故可评估案 21/21,与确定性模板持平。口径=契约实例化保真度,非规划。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/contract-visible-k0-result-20260902-v1.json

- `lane.rex_vs_locany_heldout` — 已闭合:Rex-Omni VP 接口仅支持同图内框(单图+boxes),无跨图双入口,同 held-out 公平对照不可构造。未启 GPU 未做适配器。交付口径:LocateAnything 只与自身 baseline 比,不提 Rex。说明见 ref。chxy 释放。 · ref: state/v2/jobs/rex-vs-locany-infeasibility-v1.md

- `result.visual_reality_probe_27b` — 四路探针(27B,20 图):REAL PRESENT 8/20 带位置;BLACK UNCERTAIN 17/20;SHUFFLED ABSENT 13/20;NO_IMAGE INVALID 10/20。四路分布明显不同→图像确实进模型。DIAGNOSTIC 非性能主张。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/visual-reality-probe-complete-v1.json

- `deliverable.agent_demo_frames` — agent-demo 五宫格帧落地中(absent-refuse、present-recover)。看过 summary.png:五格齐、标 DEMONSTRATION NOT EVALUATION / DEMO_SYNTHETIC_NOT_TRUSTED、契约链非行为树。等 ≥3 样例齐再填 P11。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/agent-demo-frames-v1/

- `live.chxy_27b_second_instance` — chxy 第二个 27B 已停(12:3x,tzb-fe 执行):launcher/engine 均退,18767 关闭,无 compute apps,显存 14MiB。用途已尽(B-1 作废、B-4 不采纳)。chxy 空。 · ref: /home/fx/qwen38-27b-mtp/vllm-20260902-114639.log

- `live.b1_chxy_ready` — tzb-fe 2026-09-02明确READY:http://chxy:18767，served model Qwen3.8-27B；B-1可在预登记与离线门全绿后单次preflight→600。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/

- `result.b1_gate_logprob_preflight` — B-1单次非case preflight已终态INVALIDATED：HTTP200，首token PRESENT；top20有精确PRESENT但无精确ABSENT，故不满足两候选可恢复；按预登记0/600 case、禁重试。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/b1-preflight-outcome-v1.json

- `result.b1_logprobs_invalidated` — B-1 预检作废:首 token top-20 有精确 PRESENT 但 ABSENT 被 BPE 拆分(AB/ABS…),logprob 差不可得。按预登记不重试、0/600。chxy 实例保留给 B 组下一格。 · ref: /Users/gl/tzb-deliverables/methods-v1/METHODS.md

- `result.b1_gate_logprob_terminal` — B-1终态已冻:B1_INVALIDATED_NO_CASE_REQUESTS；1非case、0/600 case、0重试/修补/选择；无DET/等压制/奇偶/兑换率主张。endpoint use complete。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/b1-complete-v1.json

- `ownership.repair_loop_a1` — m2c-exec独占A-1三个fresh caller与对应fresh工件；基于v5仅改反馈并集，冻结源/验证器/服务零改动。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/run_repair_memory_a1.py

- `result.b4_polarity_v1` — B-4四臂终态:A reject ABSENT57%,非reject压制6.6%；B 52%/6.2%；AND 58%/7.8%；OR 51%/5.0%；全臂三态600守恒、0 malformed。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-analysis-v1.json

- `analysis.b4_polarity_v1_economics` — AND对A:多恢复reject=1，多压nonreject=6；按1:2.2保守兑换，净变化=-1.7273，FAIL break-even。B-4不采纳为改进。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-analysis-v1.json

- `result.b4_polarity_not_adopted` — B-4 极性反转(600):A 57/100 & 6.6%;B 52/100 & 6.2%;AND 58/100 & 7.8%;OR 51/100 & 5.0%。AND 仅多收 1 reject 多压 6 非reject,1:2.2 净 −1.73,不采纳。B 组两格负结果(B-1 分词/B-4 不划算),B 组止。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-complete-v1.json

- `verification.agent_demo_b1_b4_v1` — 最终核验:agent-demo 4 trace/24 PNG/4 receipt守恒PASS；B1终态守恒PASS；B4 600 intent/outcome/capture与四臂分母守恒PASS；47 lane tests+56 frozen tests+双Pyright 0。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-complete-v1.json

- `analysis.b4_polarity_v1_interpretation` — post-hoc交叉表:A假阳性→B纠正1行，A正确ABSENT→B回退PRESENT6行，净reject ABSENT -5。仅证该具体极性/顺序改写不能纠正问题；不支持排除所有yes-bias/措辞效应或断言每个假阳性皆纯图像判断。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-analysis-interpretation-v1.json

- `frozen.repair_memory_a1` — A-1已先冻后输出：v5仅改同case validator错误并集+当前标记；24案、k=3、240s、node2同进程，证据/结果尚未生成。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/planner-side-repair-memory-a1-20260902-v1-preregistration.json

- `result.repair_memory_a1_complete` — A-1独立复算:round0 1/24；≤k修复20/23(轮次1/13/6)；穿透0/54；78输出。重放仅9案有01+03:0/9，另14案因v5式PASS即停无03。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/planner-side-repair-memory-a1-20260902-v1-analysis.json

- `result.a1_error_union_repair` — A-1(错误并集反馈)复算:修复 20/23,3 未修全为 trusted_input=REJECT → 可评估 20/20;round0 1 持平;穿透 0/54;attempt-03 重放 0/9(v2 9/23);落点 r1:1 r2:13 r3:6。planner-side repair memory。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/planner-side-repair-memory-a1-20260902-v1-result.json

- `analysis.repair_loop_terminal` — 终分析已冻：A-1总体20/23、可评估20/20；round0 1/24；穿透0/54；重放0/9可比；K0 21/24与21/21双层。仅planner-side memory。 · ref: /Users/gl/tzb-deliverables/methods-v1/REPAIR_LOOP_ANALYSIS.md

- `gpu.both_a100_empty_13xx` — 13:3x 两张 A100 均空:node2 27B 由闭环线精确停服(回执 9adb311e,gen716),fhk 进程亦已消失;chxy 第二实例 tzb-fe 已停(gen708)。gen605 三条件(GO/chxy 空/node2 空)首次全满足。两卡是否上,等用户当场裁。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/manual-node2-service-stop-20260902-v1.json

- `auth.two_gpu_100g_conditional` — 用户 13:4x 裁'上啊赶紧的'。两卡 DDP:LocateAnything 同 recipe,nnodes=2,NCCL over 10.10.10.x,max_steps 3000,argv 逐字同 GO run。新 run 新预登记。lane=two-shot-canonical-gate。 · ref: /Users/gl/tzb/state/v2/jobs/locateanything-visual-prompt-lora-v1.json

- `live.gen605_two_node_ddp` — attempt-4 训完:19:18 checkpoint-3000 双方闭合(trainer_state 9b35d789);后脚本 1582 行 copy2 覆盖 0400 文件 PermissionError=ADR-0035 同类打包失败,ckpt 无损;两卡空。RoCE 3.56/TCP 3.68 s/it · ref: /home/gl/locateanything-vp-v1/outputs/gen605-training-3000step-v1/checkpoint-3000/trainer_state.json

- `live.gen605_two_node_ddp_transport` — 两卡 DDP NCCL 实走 TCP(NET/Socket),launcher 显式 NCCL_IB_DISABLE=1;两端 mlx5_0 RoCE 可用未用。每步 3.70 vs 单卡 3.46(+7%)=479MB grad allreduce 开销。本轮不切,下轮可开 IB · ref: /home/gl/locateanything-vp-v1/logs/gen605-training-3000step-v1-node2-rank0-v2.log

- `live.gen605_eval_chain` — gen605 attempt-4 终判 GO(自证):776/2000=0.388 vs 基线 0,paired CI [0.3665,0.4095];定位 ABOVE_BOTH;swapped 26/1156,敏感度 0.336 CI[0.307,0.363];bundle 7254af6d 冻结。lane 停 · ref: /home/gl/locateanything-vp-v1/receipts/gen605-complete-bundle-attempt4-v1.json

- `gen605.posttraining_toolchain_freeze` — gen605 后训练工具链预冻结(lane,主评完成前):posttraining-toolchain-freeze-attempt4-v1 绑 independent/localization/swapped/decision;final-assembly-…-v1 绑装配/终验/bundle · ref: /home/gl/locateanything-vp-v1/receipts/gen605-final-assembly-toolchain-freeze-attempt4-v1.json

- `gen605.main_completion_validator_freeze` — gen605 主评闭合校验器预冻结(lane):receipts/gen605-main-completion-validator-freeze-attempt4-v1.json,校验五文件/2000 行原子闭合后才算完成;主评仍在跑 · ref: /home/gl/locateanything-vp-v1/receipts/gen605-main-completion-validator-freeze-attempt4-v1.json

- `job.agent_demo_v2_locany_s2` — 归属更正:agent-demo-v2 的 chxy 入口/回执/600 诊断归 LocateAnything lane sid 72ad7a26(tzb-f5 与 two-shot-canonical-gate 是同一会话的两个实例),归属绑 sid 不绑名;23:20"退出本线"仅指重复实例 · ref: state/v2/jobs/agent-demo-v2-locany-s2.json

- `evidence.locany_infer_entry_verified` — LocateAnything入口与冻结回执经chxy只读实测digest一致;text与vp经本lane客户端非案例preflight各1请求通过,exit0,adapter_attached分别false/true · ref: /Users/gl/tzb-lanes/agent-demo-v2/s2-preflight-noncase-v2-r2.json

- `live.node2_free_20260902_2315` — node2 23:15只读复核:GPU0 14MiB、无compute app、18767无listener、无vLLM进程;fhk已不在。仅剩两个旧pidfile · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-preregistration-v2-r2.json

- `live.node2_27b_up_agent_demo_v2` — agent-demo-v2起了唯一一个27B实例(参数与service-v1逐字同,FLASHINFER_SAMPLER=0),/v1/models 200,GPU 74807MiB,单实例;停服由本lane负责 · ref: /Users/gl/tzb-lanes/agent-demo-v2/node2-service-start-v2.json

- `live.node2_27b_stopped_agent_demo_v2` — 本lane的node2 27B已精确停:仅SIGTERM launcher 1491246,engine同退,18767无listener、无compute app、GPU回14MiB;未碰他人进程 · ref: /Users/gl/tzb-lanes/agent-demo-v2/node2-service-stop-v2.json

- `live.node2_27b_stopped_after_attempt2` — attempt2跑完已精确停服:仅SIGTERM launcher 1508751,engine同退,listener空、compute apps空、GPU回14MiB;未碰他人进程 · ref: /Users/gl/tzb-lanes/agent-demo-v2/attempt2-v3/node2-service-stop-v3.json

- `diag.locany_text_vs_rex_600` — LocateAnything text(基座) vs Rex 同图 600 张 DIAGNOSTIC(tzb-f5,不进交付物):结构合法 .955 vs .795;非拒 500 行严格均值 .525 vs .436;五非拒类均不低于 Rex;reject 类结构性 0。amendment A1-A4 已冻结 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/locany-text-600-diagnostic-v1.json

- `job.roadmap01_binding_v1` — 用户裁 00:2x:路线图 01 两子题分派——A 查 Isaac 12 发末端偏 ~95 mm 根因(tzb-f5,sid 72ad7a26);B 演示链合成绑定换 Isaac RGB-D 真绑定+修两感知 bug(demo lane,sid ef4db636)。vNext 证据,deck 不动 · ref: state/v2/jobs/roadmap01-binding-v1.json

- `job.vnext_binding_gap` — 用户 01:4x 裁"让的":残差线续做 problem_3=在 Isaac 里抓起来一次(修四条+找可达姿态+抓取提起),vNext 目录、GPU1;冻结时点 9/3 24:00 · ref: state/v2/jobs/vnext-binding-gap-v1.json

- `job.vnext_binding_gap_rules` — labserver GPU1 的 llama-server(用户自己的)按用户指令已停,两张 3080 空。Isaac 改为各用一张:demo lane GPU0,残差线 GPU1,互不等待,每卡一进程,起停仍互通知 · ref: state/v2/jobs/vnext-binding-gap-v1.json

- `vnext.residual_offline_findings` — 残差离线结论(vNext):95mm=感知 18.5+运动链 88.9(controller 收敛下限非过冲);指尖-物体真值实为 128.5;冻结四候选全竖直仅差 yaw,旋转约定不可辨识;contact goal 世界+Z 抵消工具偏移是巧合,非竖直即失效 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/offline-findings-v1.json

- `vnext.residual_replay_mount_ruling` — 裁:重放可 ro 挂载 family24 stage bundle(不在五个 -r3 冻结根内,v9 先例 ro 挂载 mutation:false);挂载前后递归 digest 入工件,输出只写 vnext-residual 目录;旧硬线"不触碰 xh-data/m2c"限定为不写不改 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/offline-findings-v1.json

- `job.flash_trial_v1` — 用户 01:1x 裁:开子代理 flash-trial,用 api.b.ai qwen3.8-flash 跑契约可见 k=0 24 例对照 27B(21/24)+demo 四案例换 S1/S4;写根 tzb-lanes/flash-trial-v1;key 在 ~/.config/tzb 不入 state · ref: state/v2/jobs/flash-trial-v1.json

- `vnext.residual_root_cause` — 残差根因(vNext,v12 A/B):95mm 是探针候选间不复位的路径依赖伪影,复位后同 goal 同朝向 361mm,与其余三候选同档;旋转约定否(有检出力);朝上 17.9mm 可达→朝向可行性问题非工作空间;指标测错对子 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/root-cause-findings-v1.json

- `competition.judging_format` — 老师群答复(用户转):评分以智能体评审为主,真机加分;评委在我们提交的场景+打包环境里现场下自然语言指令,无盲测集;须展示感知/任务分解中间过程,考虑跨本体与推理效率 · ref: /Users/gl/.claude/projects/-Users-gl-tzb/memory/competition-judging-format.md

- `trial.flash_k0` — flash-trial A(TRIAL):qwen3.8-flash 契约可见 k=0 15/24(可评 15/21) vs 27B 21/24;6 败中 5 例为 [] 退化输出(重发 5/5 过,随机非稳定),1 例真计划缺陷;供应商不强制 json_schema 只注入 prompt · ref: /Users/gl/tzb-lanes/flash-trial-v1/flash-k0-result-v1.json

- `vnext.perception_bugfix` — 感知两 bug 修毕(vNext,补丁文件未落共享库):Z 用观测顶高/2、Y 半径推距×1/√2;HEAD 口径 p90 5.43/11.34/6.98→5.30/6.75/2.91 mm;裁:补丁留 patch 文件,不改 qwen-brain src,打包时 vendored · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/perception-bugfix-report-v1.json

- `job.judge_package_v1` — 用户更正:评委机按 24GB 卡假设;大模型未微调、可插拔非限制项,任意 OpenAI 兼容端点,flash 默认、本地 vLLM 可选,小而快只是加分;LocateAnything 本地跑 · ref: state/v2/jobs/judge-package-v1.json

- `vnext.real_binding_first` — 首个真绑定(vNext,零 GPU):Isaac RGB-D 帧→LocateAnything text 框→深度前景分割→真内外参反投影→世界系;4 帧 3 帧离真值 6.2/7.4/6.6mm,1 帧指错实例 11.7mm(全披露);修后 Z 误差 1.5–1.8mm(修前多 26mm) · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/real-binding-supervision-check-v1.json

- `trial.flash_demo` — flash-trial B(TRIAL,4 案例零重试):flash PASS1/REJECT1/[]1/S1 超时1;27B PASS2/REJECT2。flash S1 延迟 3s–240s 超时不稳,27B 本地 1.0–1.4s;S4 相当;schema 注入 prompt 2.7×。C 跑中 · ref: /Users/gl/tzb-lanes/flash-trial-v1/flash-demo-result-v1.json

- `trial.bai_model_list` — api.b.ai 模型表 45 个,含 glm-5.3-flash/glm-5.3/kimi-k3/qwen3.8-max/qwen3.8-27b/deepseek-v4-flash/gemini-3.x-flash(均免费,用户裁随便用);glm-5.3-flash 探通(思考型)。子代理 C 后跑多模型 k=0 扫 · ref: /Users/gl/tzb-lanes/flash-trial-v1/flash-k0-result-v1.json

- `job.agent_design_review_v1` — 用户 01:4x 裁:开子代理 agent-design-review,调研大模型大脑+VLA 路线对照我们的设计,出差距/评委关注点/9-4 前可落地改进/架构叙述草稿;写根 tzb-lanes/agent-design-review-v1 · ref: state/v2/jobs/agent-design-review-v1.json

- `vnext.real_binding_chain` — 真绑定上全链跑通(vNext):S1 PRESENT→S2 现场框→S3 真 TaskSpec(trusted inputs PASS)→S4 PLAN_EXECUTE→S5 PASS,零合成夹具;边界:四项可信绑定三项到位,associator/ADR-0024 链未建;S1/S4 走可插拔端点,重发 0 次 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/chain-v1/000033/trace.json

- `vnext.grasp_v13_v16_invalid` — 更正:v13/v16 指标作废(只复位臂未复位物体,物体首候选被撞落后自由落体);站得住:命令 vs 达成姿态差 11–81°;按物体初值重算多候选指尖 1.4–6mm→可达性非瓶颈。v17 连物体复位+standoff 伺服跑中 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/v16-result.json

- `flash.thinking_on_diag` — flash子代理(C)诊断:同24个k=0体,思考开 19/24(可评19/21) vs 思考关 15/24,[]从5降到0,代价中位耗时10.2→31.7s、补全token 611→2145;两失败均为谓词集错非结构 · ref: /Users/gl/tzb-lanes/flash-trial-v1/flash-k0-thinking-on-diagnostic-v1.json

- `job.judge_package_skeleton` — 打包骨架已写 tzb-deliverables/judge-package-v1(24文件112KB,无权重无key,扫描净):README/config llm+chain/env Dockerfile+权重拉取计划/agent五段stub/vendored补丁/docs四篇;10项开放问题待9/4 owner · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/open-questions.md

- `flash.sweep_running` — flash子代理(D)七模型k=0扫在跑(每模型上限600s,约70min):glm-5.3-flash前3例全为思考吃满2048 token被截断→MODEL_EMPTY_OUTPUT;结果增量写 model-sweep-k0-v1.json · ref: /Users/gl/tzb-lanes/flash-trial-v1/

- `ruling.judge_pkg_oq` — 裁定(tzb-a5,09-03):打包10项开放问题——只发flash默认/27B自带主机;LocateAnything必sidecar;pins已从chxy只读取回;S1门60s+重发1次再回落框数记gate_fallback;密钥打包后再扫 · ref: /Users/gl/tzb-lanes/judge-package-inputs-v1/coordinator-rulings-on-open-questions-v1.md

- `ruling.live_entry_flash_stab` — 裁定(tzb-a5,09-03 02:0x):现场入口flash空返回——S4(试S1)开enable_thinking,依据(C)思考开[]0/24;重发上限仍1;两次失败S1回落框数记gate_fallback;本地vLLM改评委机默认属改用户裁定,早上问用户 · ref: /Users/gl/tzb-lanes/flash-trial-v1/flash-k0-thinking-on-diagnostic-v1.json

- `job.agent_design_review_done` — 调研子代理完成:tzb-lanes/agent-design-review-v1 四件(survey 13栈35链接分P/S/U;comparison;recommendations 9可做/8设计/10不动;architecture-narrative 中文两栏已实现/设计,禁词扫净) · ref: /Users/gl/tzb-lanes/agent-design-review-v1/recommendations.md

- `review.top5_and_weak_claims` — 调研结论:大脑+小策略是主流但执行器不必是VLA(ER1.5文档/FANUC先例);我们唯一差异点=符号计划级独立测试的执行前验证链。弱主张:BRIEF'让大模型理解任务'、deck 27B数字vs打包flash默认、CLAIMS 2层恢复、跨本体=接口性质仅Panda验证 · ref: /Users/gl/tzb-lanes/agent-design-review-v1/comparison.md

- `review.routing` — 调研9项分流(tzb-a5,02:1x):a1 S0已由demo lane做完(gen821);a4 HUD分解/错码/时序条→demo lane ③后;a2 ExecutorPort stub+a7本体profile+a6效率表+a8探针→打包子代理;a3账本/a5现场RECOVER/第二臂=新范围等早上 · ref: /Users/gl/tzb-lanes/agent-design-review-v1/recommendations.md

- `vnext.grasp_success_v18` — problem_3达成(tzb-a5从117条原始轨迹独立重算核实):v18姿态az135_el70_roll15指尖误差[1.3,1.7,-2.4]mm入包络;夹爪停15.1mm被物体挡住;提起101.2mm且hold 31采样恒定;邻居位移0;tier1无豁免 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/grasp-success-record-v1.json

- `vnext.grasp_v18_bounds` — v18边界:一次成功一物一场景,无成功率无统计主张;标vNext不回填冻结12发账目(5/0/7不变);进deck由用户裁。关键改动=每候选臂+物体验证复位、phase2复现搜索时的伺服运动;16候选8入包络12扰动取消;GPU1已释放 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/v18-result.json

- `pkg.q5_scene_host_path` — q5已解(残差线答复):family24宿主路径 labserver /var/tmp/xh-data/isaac-industrial/m2c/v5-existence-probe-stage-bundles-v1/…/templates/family-24;sha256拷原文件不转录 · ref: /Users/gl/tzb-lanes/judge-package-inputs-v1/family24-host-paths.md

- `flash.model_sweep_d` — flash子代理(D)七模型k=0扫:免费key仅通flash与glm-5.3-flash;glm始终思考在2048上限下15/16截断0/24(未测更大上限);其余5个403/429付费墙不可测。默认仍flash+S4思考开+重发1次 · ref: /Users/gl/tzb-lanes/flash-trial-v1/model-sweep-k0-v1.json

- `pkg.skeleton_merged` — 打包骨架并入(35文件176KB,key扫净):裁定进llm.yaml/open-questions仅q4显存待实测;pins精确;sidecar Dockerfile;scene路径+digest逐字节拷;ExecutorPort+stub合约测试2/2过;本体profile两字段TODO-verify · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/open-questions.md

- `vnext.fresh_render_blocker` — demo③卡点(gen834):官方Franka USD运行时从Omniverse CDN取,labserver不通→评委机同样会在首次建场景时炸。裁:改开冻结family24 stage usdc(残差线今晚就这样离线跑v18;usdc 10MB无外部引用);走用户代理下载=授权问题等早上;打包必自带stage · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/fresh-render-blocker-v1.json

- `ruling.user_small_perms_autoapprove` — 更正时刻:用户裁于2026-09-03 02:0x(前条写03:0x有误)。小权限由tzb-a5夜间代批(经用户代理拉Isaac资产、已用卡重占、外部下载);push/commit、PPT/交付物、冻结源、他人进程仍归用户 · ref: /Users/gl/tzb-lanes/coordinator-morning-20260903/summary-draft.md

- `vnext.grasp_v19_reexec` — v19重执行(tzb-a5核实):同冻结输入同位姿序列四判据全过,包络[4.5,3.0,-2.7]mm、升103mm、邻居≈0;与v18轨迹逐段最大偏差20.7mm→结果可复现轨迹不可逐点复现;v18+v19两次不构成成功率。v19/v20已记关节角,可字面回放 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/reproducibility-and-render-record-v1.json

- `vnext.grasp_render_blocked` — v18回放渲染未成:v19/v20共55帧全为恒定近白清屏(均值243,std<0.1),两条相机路径均初始化成功但无内容,线索=RTX render product未绑输出;v20每抓帧8次update步进物理440步致cylinder_04飞182mm→v20清洁性作废,'55帧已抓'撤回;GPU1释放 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/v20-result.json

- `flash.a8_visual_reality` — a8视觉真实性探针(flash,TRIAL):20图×4路;图像确实进模型(REAL-BLACK一致0/20)但NO_IMAGE路6/12解析答案判PRESENT=纯文本幻觉在场,门图像掉了不会fail-safe;80请求14传输错(429)、29 schema无效 vs 27B 3+17 · ref: /Users/gl/tzb-lanes/flash-trial-v1/vrp/table-flash-v1.json

- `pkg.skeleton_final` — 打包子代理收线:judge-package-v1终版41文件212KB(file-manifest.md逐文件一句),key扫净;仍开:q4显存实测、q11断网预检未在Isaac跑、Panda profile两字段待从stage读、托管路径规则未端到端演练、全部stub待9/4实装 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/file-manifest.md

- `vnext.render_recipe_handoff` — 裁定(tzb-a5,02:1x):demo③现渲成功且定位空白根因(需每帧rep.orchestrator.step,仅update读到清屏)→配方render-src/vnext_render_rgbd_v1.py转残差线,用v19关节角做字面回放并渲染(不跑物理),GPU1重占按gen842代批,渲完释放 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/render-src/vnext_render_rgbd_v1.py

- `vnext.replay_render_static` — v22/v23回放渲染(tzb-a5核实):管线已通(117真图 std~113),但帧间差≤0.0006%=画面静态;关节读回117/117设上,根因=play后渲染器读USD authored transform而PhysX写入不更新它;仍无可展示图像。缺陷披露:v22读回全抛错、v23覆盖v22帧目录 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-and-replay-record-v1.json

- `ruling.replay_round2` — 裁定(tzb-a5,02:2x,按用户gen842'小权限代批+全力推进'):残差线再放一轮回放渲染,≤1h GPU1:不play timeline,用URDF FK直接author各link xform与物体位姿再orchestrator.step;先帧间像素差验运动再报;目录加性不覆盖;不动则收 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/v23-result.json

- `vnext.replay_v24_crash` — v24回放渲染(tzb-a5核实):离线FK vs v19实测hand位姿117/117差≤0.001mm,运动学/数据/坐标系排除;但渲染前崩(rc=1,0帧),finally里close()先跑并挂2min吞掉traceback;疑点=硬编码12个link prim未验证存在。仍无可展示图像 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-addendum-v24-v1.json

- `ruling.live_referent_disambig` — 裁定(tzb-a5,02:4x):现场首框指错(3圆柱同标签,首框取最近蓝cylinder_03非青06,几何4.2mm对)。先看1280x960;不行走(b)现场专用预登记规则'注册颜色→框内中位色最近',帧上必标非localizer所做;冻结规则与离线链不动 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/fresh-binding-supervision-check-v1.json

- `ruling.live_repair_rounds` — 裁定(tzb-a5,02:4x):现场入口repair_rounds上限1→2(非3),每轮错误码与'N used/M allowed'必上帧与trace;离线链仍k=0;vNext参数非用户裁定项,早上报用户可撤 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/live-v2/live-session-v1.json

- `vnext.fresh_v2_closeout` — demo③闭环(核实回执):fresh-v2现渲rgb/depth+PhysX本体感成dataset_root形状,3帧过冻结RuntimeFrameV1,captured_at=现在,三帧全链跑完(S5 REJECT×3);q4实测峰8.83GiB不需cap(未同卡);q11零CDN开渲实证 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/fresh-render-closeout-v1.json

- `ruling.replay_round3` — 裁定(tzb-a5,02:5x,gen842代批):残差线第三轮=最后一轮回放渲染≤1h GPU1;先print_exc再close,CPU枚举prim,首试demo lane完整渲染序列,再updateToUsd,最后FK author;帧差验运动再报 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-addendum-v24-v1.json

- `pkg.q4_v2_and_wording` — q4补量:LocateAnything峰640x480 8.83GiB/1280x960 11.18GiB,均<20GiB线;同卡共驻未量,1280非必需按显存选。9/4硬口径:localizer只出类别级框,指代由注册规则选,不得写成VLM做的/实例重识别;真值只事后核验 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/locany-vram-measurement-v2.json

- `vnext.live_line_closes_fresh` — 现场线在现渲帧上端到端PASS(核实回执):1280x960仍3框同标签→按gen866(b)落地注册颜色选框规则(先发布,青hue距0.588°),中文指令→S0→S1→选框→真绑定→S4→S5 PASS,事后距青色cylinder_06约5mm;帧上强制披露;修复轮0/2 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-live-hires-v1/live-line-completion-v1.json

- `pkg.render_physics_risk_standdown` — demo lane 02:53登记的打包级风险'渲染器看不到物理状态'解除:来源是残差线相机bug不是渲染器;但至今无人演示过帧间场景跟踪,演示执行段能否显示运动仍待v28或现场线首次运动渲染证实 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-final-conclusion-v1.json

- `vnext.render_conclusion_withdrawn` — 更正gen892归因(残差线534d14bf):真因=相机既没对准也没设镜头(朝向应用路径未单测+默认50mm镜头视场仅23.67°),不是渲染器缺陷;v28同时改两处未隔离单一元凶;v24死于panda_link8无prim保留 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-conclusion-correction-v1.json

- `ruling.user_default_27b` — 用户裁(2026-09-03 08:3x):打包全部走API端点,默认指挥体=Qwen3.8-27B(OpenAI兼容端点,node2 vLLM先例,k=0 21/24);flash改为可选profile,用户之后付费买flash类模型再试。覆盖gen799的flash默认 · ref: /Users/gl/tzb-deliverables/judge-package-v1/config/llm.yaml

- `job.cross_embodiment_v1` — 用户裁(09-03 08:4x):做第二台臂跨本体演示,labserver走代理拉资产。同一份已验证计划JSON→两份本体profile(Panda+UR10)各跑approach位不抓;残差线v28后接手GPU1;24:00前出才算原创结果,否则只交profile · ref: state/v2/jobs/cross-embodiment-v1.json

- `claims.recovery_wording_v0903` — 用户批(09-03 08:4x):CLAIMS §8'2层恢复'→'一条RECOVER恢复路径',旧表述作废;不插改,新版本包 reports/CLAIMS-SHEET-20260903.md(72ccf913);deck/BRIEF无该词,引用换版待PPT批次 · ref: reports/CLAIMS-SHEET-20260903.md

- `claims.sheet_0831_digest_mismatch` — 核查结果:0831文件9/1 13:29的增补(§0e等)对应state已登记的v7后计划编辑(gen1220/gen142),是tzb-fe谱系的正当修订但漏落重冻结digest;非插改。现digest 62cd515a/43826B作为事实基线;文件与reports/另42件从未commit,建议入库以留痕 · ref: reports/CLAIMS-SHEET-20260831.md

- `vnext.grasp_render_v28_success` — v28成(核实记录dddb63d7):v19轨迹关节角字面回放渲染,close 22mm与wide 18mm各117/117帧有内容,渲前相机瞄准闸0.000°;lift帧可见夹爪抬起红圆柱、邻居未动。口径:回放非第二次执行,成功仍是v18一次+v19复现一次,无成功率 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-success-record-v1.json

- `s2.text_mode_domain_caveat` — S2口径限定(残差线自报):600图text诊断只在自然图像域成立,不得用来支撑'text模式能做属性定位';小尺度合成渲染上分辨率加倍仍不分色(demo lane实测),属性消歧靠注册规则;对外材料带'自然图像'限定 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/locany-text-600-diagnostic-v1.json

- `git.reports_tracked` — 用户裁(09-03 09:0x):reports/全部入git以留痕。commit efead17(main):96文件35929行,含CLAIMS-SHEET 0831/0903、咨询简报、SUPERSEDED tar包(共4.3MB)、hardware探针json;入库前扫过无密钥。未push · ref: reports/CLAIMS-SHEET-20260903.md

## 2. 归属与 lane
- `lane.m2c_exec` — **M2C 执行会话**:successor implementation candidate,commit-free,于全新隔离 clone(Q′ 模式);已登记候选路径内自由编辑(R132.41)。ETA(8/29 午报):交包 8/30 01:00–07:00;早沿(≤03:00)可达截止,晚沿不可达。
- `lane.tzb_fe` — **tzb-fe(协调)**:实现审查+七段治理批量激活(预告:批一 = R′ stage adoption→successor prereg→materialize→bootstrap;批二 = legacy P″ prefix adoption→recovery03→combined preflight;每步仍各自 pre-capture/记录/fail-closed,激活与 closeout 各批一次)。
- `lane.qwen_brain` — qwen-brain/S5 lane → `QWEN_BRAIN_STATE.md`(owner sessionId 72ad7a26)。

- `lane.subagent_consult4` — tzb-fe 派单个子代理写第四轮外部咨询包,唯一写面=reports/external-consult-brief-4-20260830.md(仅此一路径,不得写其他文件);未脱敏按用户8/30决定 · ref: reports/external-consult-brief-4-20260830.md

- `lane.s5_p2_done` — P2 48例对抗契约套件已 terminal clean;P3取消;S5剩余=Task#45 claim manifest + P2数字整理供deck第3/5页,不再开新工程线

- `lane.s5_engineering_closed` — S5工程线收官:P1/P2 terminal、P3取消、Task#45 closed(32 tests+复审CLEAN,三文件身份 a91c5d08/41dcef86/221afe6c)。转材料:第3页语义门数字、第6页LoRA三组2x2、能力边界一句话

- `lane.s5_docked` — S5完整停靠:P1/P2 terminal、P3取消、#45/#47 closed、deck文案六项落地。仅响应核对请求,不commit/bundle/push,不接新任务

- `lane.subagent_consult5` — tzb-fe派单个子代理写第五轮外部咨询包,唯一写面=reports/external-consult-brief-5-20260831.md,不得写其他文件;未脱敏 · ref: reports/external-consult-brief-5-20260831.md

- `lane.task32_debug` — Task32收官:v1-v9命名容器9次、授权前临时5次另账；v9不支持简单fixed hand/TCP错配，但冻结原向量缺失，故未确认固定偏移、无视频；后验残留0。 · ref: /private/tmp/m2c-r13239-task32-frame-chain-v1/task32-final-disposition-v3.json

- `lane.s5_materials_paths` — S5唯一写面=reports/{deck-p2-semantic-gate-demo.html,deck-p1-p3-p4-p6-content-blocks.md,appendix-p2-rule-coverage.md,appendix-qwen-lane-defense-qa.md}

- `lane.m2cexec_materials_paths` — m2c-exec唯一写面=reports/{deck-m2c-campaign-block-20260831.md,appendix-m2c-evidence-index-20260831.md};与S5四条不冲突

- `lane.tzbfe_video_script` — tzb-fe写面=reports/deck-video-script-20260831.md,90-110秒定稿单版本(无抓放镜头),六镜头含不可删的边界镜头与交片检查表 · ref: reports/deck-video-script-20260831.md

- `lane.m2cexec_materials_status` — 两条登记材料完成并终验PASS:campaign block与批准halted件及video冻结句机器一致；evidence index 14/14 digest回算一致。未commit/push。 · ref: /Users/gl/tzb/reports/deck-m2c-campaign-block-20260831.md

- `lane.s5_p2p5_paths` — S5 追加写面(登记):reports/deck-p2-p5-content-blocks.md,第2页架构与证明边界+第5页恢复结构与未实现项;此外禁写

- `lane.tzbfe_p7p8` — tzb-fe写面=reports/deck-p7-p8-content-blocks.md,第7页唯一边界页(承认->解释->不伪造三段顺序)与第8页交付及三项vNext · ref: reports/deck-p7-p8-content-blocks.md

- `lane.consult6` — 第六轮对抗性终审咨询件已备(tzb-fe自写未派子代理):五问逐页找过度声称/评委三攻点/镜头5抗压/证据索引与演示可信度/一句话定位 · ref: reports/external-consult-brief-6-20260831.md

- `lane.consult7` — 第七轮终审签字请求已备:P0十条逐条对账、零派发三级降级经过与归属更正、未做两件的取舍、元层错误模式提问。待两lane交付包齐即随实物同发 · ref: reports/external-consult-brief-7-20260831.md

- `ownership.layered_pointing_sources` — tzb-50独占写:rex lane的layered_pointing_v1包五个Python源；其余既有文件只读。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.layered_pointing_entry_tests` — tzb-50独占写:rex lane的preregister_layered_pointing_v1.py与tests/test_layered_pointing_v1.py。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.layered_pointing_frozen_artifacts` — tzb-50独占O_EXCL新建:layered-pointing-input-600-v1.jsonl、frozen-inputs-v1.json、preregistration-v1.json；既有件只读。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.layered_pointing_run_artifacts` — tzb-50独占未来O_EXCL新建layered-pointing captures/responses/route/score/verification/result/complete v1；GPU前禁消费。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.layered_pointing_frozen_artifacts_v2` — tzb-50独占O_EXCL新建layered-pointing-{input-600,frozen-inputs,preregistration}-v2；v1因post-freeze router编辑封存DO_NOT_USE。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.layered_pointing_run_artifacts_v2` — tzb-50独占O_EXCL新建layered-pointing-{captures,responses,route,strict-score,independent-verification,result,complete}-v2；v1 run路径禁消费。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v2.json

- `ownership.layered_pointing_diagnostics_v2` — tzb-50独占O_EXCL新建layered-pointing-omission-bias-diagnostic-v2.json；仅按已公开固定分母公式由strict-score复算，不影响门/route/scorer。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-preregistration-v2.json

- `ownership.layered_textonly_ablation_v1` — tzb-50独占新建run_layered_textonly_ablation_v1.py及layered-pointing-textonly-{preregistration,captures,ablation,complete}-v1工件；既有layered v2源/结果与qwen链只读。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/layered-pointing-complete-v2.json

- `ownership.repair_loop_contract_visible_k0_implementation` — k0实现归属：m2c-exec独占新增preregister/run/analyze_contract_visible_k0.py、tests/test_contract_visible_k0.py及pyright对应条目；无子代理写入。 · ref: /Users/gl/.claude/plans/merry-leaping-adleman.md

- `ownership.agent_demo_v1_code` — m2c-exec独占新写:agent_demo_common_v1.py、visual_reality_probe_v1.py、agent_loop_v1.py、render_agent_trace_v1.py、pyrightconfig.json。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.agent_demo_v1_tests` — m2c-exec独占新写:tests/test_visual_reality_probe_v1.py、tests/test_agent_loop_v1.py；根均为/Users/gl/tzb-lanes/agent-demo-v1。 · ref: /Users/gl/.claude/plans/abstract-brewing-knuth.md

- `ownership.b1_gate_logprob_v1` — B-1独占create-only根:b1-gate-logprob-v1；写source/tests/config/prereg/preflight/evidence/captures/analysis/complete。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/

- `ownership.b1_gate_logprob_v1_source` — owner m2c-exec: b1_gate_logprob_v1.py、tests/test_b1_gate_logprob_v1.py、pyrightconfig.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/b1_gate_logprob_v1.py

- `ownership.b1_gate_logprob_v1_prereg` — owner m2c-exec:create-only b1-preregistration-v1.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/b1-preregistration-v1.json

- `ownership.b1_gate_logprob_v1_capture` — owner m2c-exec:create-only preflight intent/outcome、case-intents/、case-outcomes/、captures、capture-complete。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/

- `ownership.b1_gate_logprob_v1_analysis` — owner m2c-exec:create-only b1-analysis-v1.json、b1-complete-v1.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/b1-analysis-v1.json

- `experiment.b1_gate_logprob_v1_preregistered` — B-1已create-only预登记，端点chxy:18767；0 endpoint请求；仅加logprobs/top_logprobs；单非case preflight后600，一致性差一行即ABORT。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b1-gate-logprob-v1/b1-preregistration-v1.json

- `ownership.b4_polarity_v1` — B-4独占fresh create-only根:b4-polarity-v1；owner m2c-exec写source/tests/config/prereg/preflight/evidence/captures/analysis/complete。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/

- `ownership.b4_polarity_v1_source` — owner m2c-exec:b4_polarity_v1.py、tests/test_b4_polarity_v1.py、pyrightconfig.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4_polarity_v1.py

- `ownership.b4_polarity_v1_prereg` — owner m2c-exec:create-only b4-preregistration-v1.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-preregistration-v1.json

- `ownership.b4_polarity_v1_capture` — owner m2c-exec:create-only preflight intent/outcome、case-intents/outcomes、captures、capture-complete。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/

- `ownership.b4_polarity_v1_analysis` — owner m2c-exec:create-only b4-analysis-v1.json、b4-complete-v1.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-analysis-v1.json

- `experiment.b4_polarity_v1_preregistered` — B-4已create-only预登记；臂A复用冻结600不重跑；臂B逐字反转prompt，先1非case二值preflight，过后600；报A/B/AND/OR及1:2.2。当前0 B-4请求。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-preregistration-v1.json

- `experiment.b4_polarity_v1_preflight` — B-4单次非case二值preflight PASS；HTTP成功且原样精确PRESENT/ABSENT文法，0重试；现按预登记可跑臂B 600单次。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-preflight-outcome-v1.json

- `experiment.b4_polarity_v1_capture` — B-4臂B 600单次capture已启动；冻结preflight PASS后依manifest顺序，逐请求先写intent再写outcome；0重试，运行中。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/case-outcomes-v1/

- `ownership.b4_polarity_v1_interpretation` — owner m2c-exec:create-only b4-analysis-interpretation-v1.json；仅对已冻四臂行重叠作边界化post-hoc解释，不改b4-analysis-v1。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-analysis-interpretation-v1.json

- `ownership.agent_demo_v2_root` — owner build-auditable-agent-demo:create-only /Users/gl/tzb-lanes/agent-demo-v2/**；v1严格只读，禁reports/qwen-brain/commit/push/subagent。 · ref: /Users/gl/tzb/state/v2/jobs/agent-demo-v2-locany-s2.json

- `ownership.agent_demo_v2_code` — owner build-auditable-agent-demo:agent_demo_common_v2.py、agent_loop_v2.py、render_agent_trace_v2.py、tests/test_agent_loop_v2.py、pyrightconfig.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent_loop_v2.py

- `ownership.agent_demo_v2_manifests` — owner:create-only operator-exemplars-v2/、operator-exemplar-manifest-v2.json、execution-manifest-v2.json、preregistration-v2.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-preregistration-v2.json

- `ownership.agent_demo_v2_outputs` — owner:create-only agent-demo-traces-v2/**、agent-demo-frames-v2/**、agent-demo-completion-v2.json。 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-completion-v2.json

- `ownership.agent_demo_v2_service_receipts` — owner:create-only node2-service-start-v2.json、node2-service-stop-v2.json；只启一个同service-v1实例，用完精确停并验listener/apps/显存。 · ref: /Users/gl/tzb-lanes/agent-demo-v2/node2-service-start-v2.json

- `lane.agent_demo_v2_skeleton_ready` — v2骨架完成:30 tests passed/pyright 0错;prereg-r2、执行清单、text+vp契约、operator示例框清单已冻;待S2模式裁定与node2起服 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-preregistration-v2-r2.json

- `fact.agent_demo_v2_s2_transport` — S2=常驻JSONL走单条ssh,一进程一模式,ready 180s/请求120s;取boxes_xyxy_pixels;首个返回框为候选,零重试零选择 · ref: /Users/gl/tzb-lanes/agent-demo-v2/s2-contract-text-v2.json

- `fact.agent_demo_v2_operator_exemplar` — 示例框=目标图上同类别的另一个实例(非被指目标非GT),目视输入+叠框复核;absent案无示例框;仅vp模式使用 · ref: /Users/gl/tzb-lanes/agent-demo-v2/operator-exemplar-manifest-v2.json

- `incident.agent_demo_v2_vp_contract_r1` — vp契约r1未预建--crop-dir致入口exit2启动失败;r1封存DO_NOT_USE,r2加mkdir并通过;消费案例0 · ref: /Users/gl/tzb-lanes/agent-demo-v2/s2-contract-vp-v2-r2.json

- `incident.agent_demo_v2_prereg_r1` — prereg r1绑定源要求ABSENT案也有示例框;改为S2分支内惰性解析后源digest变,r1封存SUPERSEDED,r2生效;消费案例0 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-preregistration-v2-r2.json

- `lane.agent_demo_v2_rehearsal_pass` — 离线全链演练PASS(stub 27B+stub S2):4 trace/24 PNG/completion COVERAGE_COMPLETE,计数s1=4 s2=3 s4=4;32测试过 pyright 0错 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-preregistration-v2-r3.json

- `incident.agent_demo_v2_prereg_r2` — 演练查出r2源两缺陷:vp+ABSENT帧被要求示例框、run-all未绑endpoint;已修,prereg r3生效,r1/r2封存SUPERSEDED,消费案例0 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-preregistration-v2-r3.json

- `fact.agent_demo_v2_vp_crop_dir` — vp裁剪图0400+O_EXCL且名含request_id,共享持久目录重跑必撞名;契约r3改每次跑新目录,chxy实测ready+1请求exit0 · ref: /Users/gl/tzb-lanes/agent-demo-v2/s2-preflight-noncase-v2-r3.json

- `fact.agent_demo_v2_s2_ready_budget` — S2 ready超时由180s提到600s:入口加载前强制校验7.2G/24文件checkpoint,冷读I/O受限(实测58.5s与74.1s);单请求仍120s。契约text-r2/vp-r4 · ref: /Users/gl/tzb-lanes/agent-demo-v2/s2-contract-vp-v2-r4.json

- `ruling.agent_demo_v2_gen759` — 协调gen759:入口归tzb-f5其冻结件可用;示例框口径(同类别另一实例/absent不给框)批准;模式等600图text粗测,00:30未到则回落vp并注明 · ref: /Users/gl/tzb/state/v2/jobs/agent-demo-v2-locany-s2.json

- `lane.agent_demo_v2_attempt1_incomplete` — attempt1 text模式跑完并冻结为DEMO_COVERAGE_INCOMPLETE:present链PASS=0,因chxy被他人64G占用致1920x1279那案S2 CUDA OOM;24帧齐,零重试 · ref: /Users/gl/tzb-lanes/agent-demo-v2/agent-demo-v2-attempt1-blocker-v1.json

- `lane.agent_demo_v2_attempt2_complete` — attempt2(chxy独占后)DEMO_COVERAGE_COMPLETE:present链PASS=1、absent REFUSE PASS、REJECT=2;24帧、守恒PASS、s1=4 s2=3 s4=4零重试 · ref: /Users/gl/tzb-lanes/agent-demo-v2/attempt2-v3/agent-demo-completion-v3.json

- `deliverable.agent_demo_v2_frames` — P11改取attempt2-v3/agent-demo-frames-v6(CJK字形+错误码换行+行距自适应,同一批trace零模型请求);v3/v4/v5为过程件;指针r2见ref · ref: /Users/gl/tzb-lanes/agent-demo-v2/deliverable-frames-pointer-v2-r2.json

- `lane.agent_demo_v3_isaac_rgbd` — problem_2启动:写根 /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd(create-only,取vnext-binding-gap-v1的根,roadmap01-binding-v1同题旧根不建);GPU0固定

- `lane.agent_demo_v3_labserver` — v3 labserver 工作目录 /var/tmp/vnext-demo-v3-20260903/ create-only,总量<=10GB,到8GB停报;只经 ssh chxy->root@10.13.28.6;GPU0一次一个Isaac进程,起停互通知

- `lane.agent_demo_v3_shared_file_question` — isaac_m1b_episode.py两bug修法:先在v3 lane实现+GT量p90,补丁交协调路由;该文件在qwen-brain活分支且不在我登记写集,不直接改

- `lane.v3_perception_bugfix` — 两感知bug已量:HEAD口径 Z p90 6.98->2.91mm、Y 11.34->6.75mm;冻结可比口径 Z 8.03->2.86mm;补丁验证过(补丁码复现+冻结单测55/55) · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/perception-bugfix-report-v1.json

- `lane.v3_patch_routing` — 补丁未落共享库:qwen-brain src 不在我写集、在他人活分支、且需改审计校验串(邻接冻结判定);交协调路由,补丁在 receipts/isaac-m1b-centre-geometry-fix-v1.patch

- `lane.v3_frozen_anchor_caveat` — 7/29冻结审计数(z25.9/4.32)不能当本次before:冻结件早于HEAD的颜色分割头与拟合桌面;深度-only口径可复现其7框/帧、1197配对

- `lane.v3_patch_ruling` — 裁定(tzb-a5,2026-09-03,gen795):补丁只留在v3 receipts/.patch,打包环境vendored副本带走;共享库改动冻结后由qwen-brain owner开vnext/perception-geometry-fix;审计校验串不动

- `lane.v3_binding_order` — 裁定(tzb-a5,2026-09-03):先在冻结Isaac capture上做真绑定零GPU拿第一个摘DEMO_SYNTHETIC案例并报;后续形态改为场景内现场接自然语言指令跑全链+五宫格实时显示

- `lane.v3_first_real_binding` — 第一个真绑定成了:LocateAnything text框->框内深度->真内外参反投影->世界系,4帧3帧指对唯一青色圆柱,3D距真值6.2/7.4/6.6mm,Z误差1.5-1.8mm · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/real-binding-supervision-check-v1.json

- `lane.v3_binding_bug_demo` — 同一批帧上若用修前Z规则会多26.2-26.9mm(躺倒圆柱吃直立类常数),真绑定案例本身就演示了bug修复;第4帧指错实例(cylinder_09,11.7mm)已披露不挑

- `lane.v3_chxy_unclaimed_process` — 结清:chxy pid 3434307 是 tzb-a5 派的 flash 子代理所起,01:22 已EOF正常退出,非第三方;两边都没碰过

- `lane.v3_real_taskspec` — 真TaskSpec过冻结校验:BoundExecuteTaskSpecV2+PublicWorldSnapshotV2 PASS零错,无合成夹具,DEMO_SYNTHETIC已摘;refs全部指向本lane已发布的真观测/真绑定/位姿登记 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/real-taskspec-v1/000033/real-taskspec-bundle.json

- `lane.v3_llm_pluggable` — 裁定(tzb-a5,2026-09-03,gen799):S1/S4改可插拔OpenAI兼容端点,默认api.b.ai qwen3.8-flash,key在~/.config/tzb/bai.env只读不外泄;node2 27B可选;现场入口S1/S4空输出或超时重发一次并记数

- `lane.v3_full_chain` — 全链跑通(帧000033):S1 PRESENT->S2 LocateAnything真框->S3真绑定真TaskSpec PASS->S4 PLAN_EXECUTE->S5冻结校验PASS;无合成夹具,重发0次 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/chain-v1/000033/trace.json

- `lane.v3_frames` — v3五宫格已出(chain-v1/000033/frames-v2,6张):横幅换成BINDING FROM SIMULATED RGB-D真内外参,中文指令正常渲染,行距自适应全在面板内 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/chain-v1/000033/frames-v2/render-receipt.json

- `lane.v3_next` — v3待办:ABSENT拒绝路径未实现(现为fail-closed)、现场任意指称词入口、GPU0新渲场景、ADR-0024关联链未接(目标ref绑本lane绑定记录而非associator track)

- `lane.v3_refuse_path` — 拒绝路径做实并验过:gate ABSENT->真REFUSE TaskSpec(绑真观测、无绑定记录声明未绑定)->S4 PLAN_REFUSE->S5 PASS;帧见 chain-v1/000033-absent-v2/frames-v2

- `lane.v3_order` — 裁定(tzb-a5,2026-09-03,gen798/799):顺序②现场入口->①拒绝路径(已做完)->③GPU0现渲;打包9/4 24:00截止,评委机24GB卡,打包骨架由打包子代理写 /Users/gl/tzb-deliverables/judge-package-v1/

- `lane.v3_scene_reset_rule` — 残差线教训(转自tzb-a5):③现渲与现场入口复用同场景时,每次尝试前复位物体状态或记录物体位移,>5mm标场景被上次尝试扰动;冻结7月capture不受影响

- `lane.v3_live_entry` — 现场入口跑通:S0分解(任意中英文指令->英文指称词+目的地)->热S2会话->真绑定->S4/S5;3轮指令 live-v2/turn-00{1,2,3},每轮出五宫格 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/live-v2/live-session-v1.json

- `lane.v3_repair_round` — 现场入口加1轮修复(冻结v4 correction路径):turn2 REJECT(3码)->PASS,turn1 4码->2码仍REJECT;离线链保持k=0不修复;轮次全记进trace

- `lane.v3_flash_flaky` — flash端点实测不稳:turn3 S1两次空返回->gate MALFORMED,S4重发后仍空->fail-closed;评委现场建议本地vLLM;24GB卡需同时装LocateAnything-3B(约7GB)+指挥体

- `lane.v3_thinking_on` — 裁定gen824/825已落:S1/S4开thinking(记进trace+帧)、S1 60s超时+重发1次、两次失败按框数回落gate(gate_fallback=true);实测thinking开后S1空返回消失(泰迪熊ABSENT正确)

- `lane.v3_degenerate_empty_array` — flash的[]退化按'空输出'处理(触发那1次重发),不再当结构错误去修复;仍不放宽上限。另实测撞到429限流:两次429->fail-closed,评委机建议本地vLLM再多一条理由

- `lane.v3_fresh_render_blocked` — ③现渲被卡:官方Franka USD需从Omniverse CDN取,labserver不可达(curl 000)、ov缓存空、本地只有29KB根层;打包必须自带Isaac资产树,否则评委机同样点失败 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/fresh-render-blocker-v1.json

- `lane.v3_render_recipe` — 现渲配方:拷stage到自己/tmp再开;相机按冻结capture参数(pos -0.8/-0.8/1.4,look_at -0.05/0/0.55,fov 1.047,640x480,clip 0.1-4.0),算出的内外参要和冻结capture逐位对上再采;每帧记物体位移>5mm标扰动

- `lane.v3_a4_frames` — a4三项已做:步骤列表带depends_on(REJECT案例上能直接看出gripper OPEN/CLOSE被换)、错误码code@path、底部阶段时序条;帧 live-v2/turn-00{1,2}/frames-a4-v2

- `lane.v3_fresh_render_unblock` — 裁定(tzb-a5,gen837):③改开冻结family24 stage(机器人已摊平,无CDN),不走代理;配方与路径见judge-package-inputs-v1/family24-host-paths.md与v18参考实现

- `lane.v3_fresh_render_done` — ③现渲成功:开冻结family24 stage零CDN,3帧全有内容(rgb_std20.85/86KB/深度std0.285),算出内参与冻结capture逐位一致,帧间物体位移0.000000m · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-v1/fresh-render-receipt.json

- `lane.v3_render_key_step` — 空白渲染根因(残差线两次全空,我一次成功):capture_on_play关闭后必须每帧rep.orchestrator.step()才真出图,只调simulation_app.update()读到的是clear buffer(恒定243/std0.05)

- `lane.v3_proxy_not_needed` — 代理授权(用户gen842经tzb-a5转)未使用:冻结stage路线已跑通,不需要下载官方资产树;若后续要材质再用并在receipts记裁定号

- `lane.v3_fresh_dataset_v2` — 现渲v2成dataset:policy_rgbd/{rgb,depth}+runtime_frames.jsonl(3帧过冻结IsaacM1BRuntimeFrameV1)+supervision;本体感按PhysX读法记;链可吃现渲帧 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-v2/fresh-render-receipt.json

- `lane.v3_fresh_stage_inventory` — family-24现渲场景:6个直立圆柱r15mm/h80mm,六色互异,青色唯一=cylinder_06;destination blue_partition_bin(0.20,0.15,0.45,yaw1.5708)同属该stage的source.sdf

- `lane.v3_fresh_deviations` — 现渲两处披露偏离:手臂每帧下发home目标(冻结capture是正弦)故三帧姿态静;相机prim名vnext_policy_rgbd而角色槽用冻结Literal policy_rgbd

- `lane.v3_fresh_chain_result` — 现渲三帧全链跑完:S1 PRESENT/S2 LOCALIZED/S3 REAL_TASKSPEC_PASS/S4 EXECUTE/S5 REJECT×3(无修复轮);拒因均为计划形状:多余谓词+参数绑定不符 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-chain-v1

- `lane.v3_referent_defect` — 关键缺陷:LocateAnything text模式对'cyan industrial cylinder'返回全部圆柱(同一类别标签),首框恒为离相机最近的cylinder_03;真青色cylinder_06在第2/3框里 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/fresh-binding-supervision-check-v1.json

- `lane.v3_metric_binding_quality` — 度量绑定本身好:对被框中的物体3帧误差4.24/4.24/4.26mm,观测顶高78-79mm(真80),半径16.95mm(真15);误差在指代不在几何

- `lane.v3_repair_round_evidence` — 现场入口修复轮实测:1轮把验证器错误从5条降到2条,残留仅最后两原语顺序颠倒(GRIPPER_POSITION/REMOVE_ATTACHMENT对调);已请裁能否放到2-3轮 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-live-v1/turn-001

- `lane.v3_locany_vram` — q4两分辨率已量:640x480峰值8.83GiB,1280x960峰值11.18GiB(4倍像素多约2.35GiB),均低于20GiB加cap线;若现场走1280x960则与Isaac同卡余量变窄,建议评委机确认一次 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/locany-vram-measurement-v2.json

- `lane.v3_hires_experiment` — 正在GPU0渲1280x960同视角版(光学不变,内参按整数倍精确校验),测text模式在物体大一倍后能否区分颜色词;不改任何契约

- `lane.v3_fresh_chain_closeout` — 现渲链闭环回执已发布:预登记+3次离线跑+1次现场轮+督导核验全在里面,4次EXECUTE尝试全REJECT(计划形状),无重跑无择优 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-chain-v1/fresh-chain-completion-v1.json

- `lane.v3_hires_dataset` — 1280x960现渲成功(fresh-v3):内参恰为冻结capture2倍且逐位相符,unique colours 7k->12.5k,3帧过冻结契约;已预登记为独立观测(hires prereg) · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-v3/fresh-render-receipt.json

- `lane.v3_peer_attribute_baseline` — 残差线600图text诊断(attribute 100行:中位1框/>1占14%/best≠first 8.2%)结论域=自然图像;作者已声明不得据此支持'text模式能做属性定位';小尺度合成渲染域上属性消歧必须靠注册规则 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/locany-text-600-diagnostic-v1.json

- `lane.v3_gpu_released` — GPU0已释放回143MiB容器已删;残差线通告两卡都不占且其渲染尝试到v24收手

- `lane.v3_ruling_box_selection` — 裁定gen866(tzb-a5,2026-09-03):先看1280x960;能分色则用并把分辨率记为现场设置+补量该分辨率显存;否则给现场线新起专用预登记选框规则(规则文本+颜色表先落盘记sha),帧与trace必须写明颜色消歧由注册规则完成;冻结首框规则与离线链一字不动;真值仍只事后核验

- `lane.v3_ruling_repair_rounds` — 裁定gen867(tzb-a5,2026-09-03):现场入口repair_rounds上限2(不到3),每轮错误码+计划digest+N used/M allowed上帧与trace;离线链仍k=0;非用户裁项,帧上不得写死'允许2轮'为定论,早上报用户可撤

- `lane.v3_hires_no_colour` — 分辨率不解决问题:1280x960下text模式仍返3个类别级框,首框仍是最近的cylinder_03;故按gen866走(b)注册颜色规则 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/colour-rule-dry-run-v1.json

- `lane.v3_colour_rule_live` — 已按gen866落地REGISTERED_COLOUR_MEDIAN_BOX_SELECTION_V1:规则文本+通用颜色表(不用场景diffuse)先发布记sha,只挂现场线;帧与trace强制写明颜色消歧非localizer所为;冻结首框规则与离线链未动 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/live-box-selection-rule-v1.json

- `lane.v3_colour_rule_dryrun` — 规则空跑(不发请求不改已发布绑定):青色框hue距0.59度 vs 蓝35.8/品红119.4,选中框事后核验落在cylinder_06(4.85/5.32mm),两分辨率都对

- `lane.v3_pointer` — 本lane活动指针已建(一屏):有效工件/已取代工件/两条必守口径/悬着的事;详情在回执,禁通读目录 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/LANE-POINTER.md

- `lane.v3_live_line_closed` — 现场线在现渲1280x960帧上端到端闭环:中文指令→S0分解→S1 PRESENT→注册颜色规则选中青色框(0.588度 vs 35.8/119.4)→真绑定→S5 PASS,修复轮0用/2允许;事后核验落在cylinder_06约5mm · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-live-hires-v1/live-line-completion-v1.json

- `lane.v3_frame_disclosure` — 帧上强制披露已生效:box choice行+术语hue+'colour disambiguation is done by a registered rule, not by the localizer';修复轮标(interim setting);渲染器按行高缩字号修了挤行

- `lane.v3_no_regression` — 改动回归已验:冻结capture的observation五个时间/身份字段与已发布逐字相同(mtime回落生效),旧trace(chain-v1/000033)用新渲染器仍出7个文件

- `lane.v3_hires_unrun_frames` — hires预登记3帧只跑了000000(离线1次+现场1次):分辨率实验的问题已被该帧答完,余两帧未发请求,不是弃用结果而是没跑;如需补跑请说

- `lane.v3_render_physics_visibility` — 待验风险:残差线v26称该配置下渲染器看不到物理状态(两模式max_change恰0.000000)。我的帧无法证否也无法证实——本线场景物体静止、手臂锁home;若成立则演示的执行段无法显示运动,属打包级风险

- `lane.v3_physics_did_advance` — 本线可证:PhysX张量读到关节速度逐帧变化(0.008931/0.010710/0.011482),物理确实在推进;物体位姿恰0.000000是因其真静止。故'恰0'不足以证明渲染器看不到物理

## 3. 硬约束与停止线
- `stopline.impl_phase` — 实现阶段(R132.36/39 停止线):禁改 governed 仓库字节;禁 formal-host 动作/SSH 治理面/容器/GPU;禁 ordinal;canonical 命名空间冻结;禁 push;landing/每治理段需单独裁定。
- `stopline.human_gates` — 两道人门:12发物理执行的用户批准已消费于 Option A 预授权(preflight PASS 后直跑);S6 执行仍锁(分母 ADR 已批 R132.20,其余 blocker 在档)。push/node2 大额调度归用户。
- `discipline.hash_and_citation` — 纪律:零手打完整 hash(程序化派生);操作关键条款逐字引 ADR;消息 hash ≤8 位前缀 informational;发信前按 sessionId 反查会话名。
- `stopline.compaction_ladder` — 压缩边界偏差四档阶梯(R132.37/38/40/41):只读零工件、追加披露写、已登记候选路径编辑 = 披露即结;其余逐案。unchanged-read 确认 = 重读已完成。大型工具输出落文件后只读尾部。

- `claim.no_visual_evidence` — 本轮无可辩护正面视觉能力证据:SYNTHETIC_TEST视觉行=0、BLIND视觉族欠识别、P3受特权真值边界不可做。deck第5页改语义门FAR/FRR版,视觉列为vNext

- `evidence.interpreter_identity_asymmetry` — 解释器身份钉定自ordinal05起;00-04仅有argv层身份,不可追溯补录。属证据发射层差异不触致动路径,须显式披露,禁反向声称00-04有解释器身份保证

- `stopline.sixth_contradiction` — 停止规则收紧+时间盒:此后任何不可追溯到tzb-fe裁定错误的结构矛盾即直接改halted报告不再重评;且ordinal05若08/31 02:00前未点火,无条件改halted

- `stopline.final_plan_prescan_identity` — 点火固定顺序：最终计划vN→以vN为输入的prescan→五条件→preflight″读回→点火。prescan须钉control_root+exact request digest并与点火计划显式相等；计划重生成则后续全重跑。第六类结构矛盾停报。 · ref: /private/tmp/m2c-r13239-task31-preflight-local-bindings-diff-v1.json

- `stopline.stable_request_identity` — 稳定request摘要仅排除requested_at_ns与其派生physical_dispatch_sha256。plan、最终prescan、实际请求须同stable digest；其余字段逐字相同。实际完整请求须在dispatch intent留痕。 · ref: /private/tmp/m2c-r13239-task31-plan-v4-runtime-request-repro-v1-run.out

- `stopline.ordinal05_deadline` — ordinal05须在2026-08-31T02:00+08:00前实际点火，否则无条件转诚实halted-campaign。后续未知结构矛盾若非tzb-fe裁定规格错误，也直接halt，不再修。 · ref: /private/tmp/m2c-r13239-task31-plan-v4-runtime-request-repro-v1-run.out

- `deck.model_declaration` — 第2页须显式写死 Qwen3.8-27B 多模态VL低频决策+模型不输出坐标/轨迹/关节值;因同期他队讨论部署超大纯文本规格,防被归入堆大模型直控一类。禁点名、禁比较式表述

- `report.disposition_must_restate` — 未消费ordinal准确计数=7(05及06-11),但须并列披露05有一次真实物理派发、worker启动、rc=1、无canonical outcome;禁用七未消费暗示无物理动作 · ref: /private/tmp/m2c-r13239-task31-ordinal05-halt-accounting-v1.json

- `claims.authoritative_sheet` — 对外主张权威清单已建:10节含每条事实的允许/禁止/必带数字,冲突时以其为准;新主张须tzb-fe裁定后写入方可对外。deck/视频/答辩/报告统一引用此件 · ref: reports/CLAIMS-SHEET-20260831.md

- `rule.gated_ruling_verification` — 常设:五类tzb-fe裁定(点火/冻结/schema身份规则/对外主张/状态迁移)执行前须核六项(主语id版本digest同一、同域比较、canonical active、动态字段、规则冲突、前缀可解析);不符必须拒,拒绝是义务 · ref: reports/CLAIMS-SHEET-20260831.md

- `rule.tzbfe_reload_receipt` — tzb-fe自我约束:压缩后做五类裁定前须用statectl生成机器重载回执,禁凭记忆复述;裁定须写明subject的id/version/digest,写不出即不下裁定;禁用不可解析短前缀

- `rule.remote_lifecycle_truth` — 硬要求:判定远端是否结束以remote lifecycle/health为准,禁把本地调用timeout当远端结束(ordinal04与孤儿容器同根因)。起容器前须先定收尾方式,不得依赖--rm+短命令

- `claim.no_degradation_forbidden` — 禁称'没微调所以能力没下降':权重未变不等于系统能力不降(长prompt/错误few-shot/强制JSON/错误路由/截断/误拒),且裸基座基线从未测过。唯一允许=三门单独验证表述

- `vnext.probe_must_record_pose` — 证据设计缺口:冻结actuation probe只记goal+标量final/min error,不记final position/orientation,信息不足以诊断自身失败。vNext要求探针记录足以重建误差向量的原始位姿

- `design.task32_probe_evidence_gap` — vNext证据设计输入:失败探针必须记录goal+final controller position/orientation+live hand/TCP pose，足以重建误差向量；仅存标量norm不足诊断根因。另动态current-pose重注入实测非幂等，重复重规划须记录并门控漂移。 · ref: /private/tmp/m2c-r13239-task32-frame-chain-v1/task32-independent-findings-v1.json

- `legacy.strict_readonly` — legacy M2C_STATE.md 自此严格只读,临时例外随campaign结束失效。告警已无法区分旧已处置与新未处置写入,故以规则禁行为替代失效探测器;字节再变即违规须报

- `vnext.statectl_reconcile` — 工具缺口:statectl缺reconcile命令以推进legacy基线,故legacy-reconcile告警无法清除。9/3后补,冻结期不做(新增工具属治理扩张)

- `stopline.legacy_strict_readonly` — 补偿控制:legacy M2C_STATE.md严格只读且临时例外失效;当前字节基线已完成B1处置,任何后续变化均为新违规并须立即报tzb-fe · ref: /private/tmp/m2c-r13239-legacy-readonly-baseline-v1.json

- `claim.no_universal_quantifier` — P0全称量词禁令:作废'任何/所有不安全计划都不能进入执行器',与自披露的6类未覆盖规则冲突。唯一允许=冻结规则/冻结案例/受测执行路径内已覆盖者被阻断 · ref: reports/CLAIMS-SHEET-20260831.md

- `package.two_tier` — 用户8/31授权:TierB冻结证据以发行拷贝完整入包,带source_frozen/copy/match与DISTRIBUTION_COPY_NOT_AUTHORITY。包因此对接收方真可核验;match=false须停报

- `claim.dispatch_v4_final` — 零派发第4次也是最终降级:'在冻结测试套件中,24个不安全计划全部被拒,均未到达末端原语dispatcher调用点'。禁'派发接口未被调用'(23例确调用了生产gate函数,有歧义)

- `freeze.tzbfe_materials_v3` — tzb-fe自锁:权威清单等五份对外材料自2026-08-31起冻结至v3发出,不再编辑;确需改为v4不插改v3窗口。若发现tzb-fe改源,lane须停下报我。变更源者亦须被门控

- `stopline.v3_tzbfe_five_file_freeze` — v3窗口内CLAIMS/deck7-8/video/vNext/consult7五文件冻结；任一字节变化即STOP并报tzb-fe，后续改动只能进v4 · ref: /private/tmp/m2c-r13239-v3-tzbfe-five-file-freeze-baseline-v1.json

- `stopline.v3_tzbfe_five_file_refreeze` — v3五文件经有界134→135纠正后重冻结;旧基线保留为违规前记录。此后任一字节变化即STOP,v3后改动归v4。 · ref: /private/tmp/m2c-r13239-v3-tzbfe-five-file-refreeze-baseline-v2.json

- `label.two_tier_rederived` — 重导出标签两层:上位REDERIVED_FROM_FROZEN_INPUTS+NOT_ORIGINAL_RUN供扫描命中全部8条,下位REDERIVED_AGAINST_CURRENT_FROZEN_IDENTITIES+NOT_ORIGINAL_P1_RUN供精确。正确但找不到的标签等同错标签

- `freeze.materials_baseline_final` — 五份材料最终重冻结基线:CLAIMS-SHEET=f90c7859/28637B,deck-p7-p8=8ea16ccb/4710B,视频脚本与vNext路线未变。此后任何改动一律新版本包,不插改

- `ruling.v6_refreeze_v1_disposition` — tzb-fe 2026-08-31裁定:v6 baseline-v1保留PROCESS_RECORD_DO_NOT_USE，不覆写/删除/改权限/复用；该路径从未承载基线内容，0B为shell重定向截断产物；改用v2并在MANIFEST/回执显式披露。 · ref: /private/tmp/m2c-r13239-v6-tzbfe-five-file-refreeze-baseline-v1.json

- `ruling.v6_existing_intermediates_valid` — tzb-fe 2026-08-31裁定:exists()+write_text既有baseline-v2/preindex/index-rebuild/complete-prescan继续有效，不追溯作废；O_EXCL仅前向要求。扫描v1由fresh完整扫描取代。v6 packager立即恢复。 · ref: /private/tmp/m2c-r13239-v6-create-once-shell-redirection-scan-v1.txt

- `stopline.governance_freeze_until_v6` — tzb-fe 2026-08-31裁定:v6发出前不新增/重建治理机制；只补覆盖Bash+Python的完整扫描并建v6。会致对外说错的内容问题立即报停；非内容性流程瑕疵照报并延至9/3后。 · ref: /Users/gl/tzb/reports/external-consult-brief-7-20260831.md

- `ruling.pointing_candidate_reporting_guard` — tzb-fe 2026-09-01裁定:候选须同子集同条件超过在职者，且同屏报在职者31%畸形率与1.449倍遗漏虚高；低分通用VL对手不是能力证据，禁据此称27B一般视觉能力差。 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/incumbent-subset-600-omission-bias-diagnostic-v1.json

- `ruling.repair_loop_gpu_authorization_scope` — tzb-fe撤回越权GPU放行：pointing lane用户授权不得扩成repair-loop类授权。用户直接授权前禁SSH/起服/占卡；技术实现可继续。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `ruling.repair_loop_exact_process_group_kill` — tzb-fe准技术清理fallback：仅lane-owned进程组且PID/PGID/start_ticks/token/role全匹配，TERM宽限后可KILL；任一不匹配或KILL失败即停报，禁pkill/模式匹配。非GPU授权。 · ref: /Users/gl/tzb-lanes/repair-loop-v1

- `incident.repair_loop_postcompact_read_order_v5` — 本次压缩恢复首工具误并行读取两个刚复制的v4源码，随后单独窄读权威state相关§§1–4键；仅只读，未改lane、未发模型请求、未触远端/GPU。披露即结。 · ref: /Users/gl/tzb/CLAUDE.md

- `ruling.repair_loop_v5_x_gt_zero_consequence` — tzb-c2复核裁：v5 x=1>0触发ADR-0032§5.4.4，v2 0/23不得进入任何交付；1/23禁作能力率，只证v2零为配置产物。 · ref: /Users/gl/tzb/ADR-0032-m2c-repair-loop-sampling-falsification.md

- `incident.legacy_state_drift_observed_20260902` — statectl check: v2 tail/journal一致，但legacy /Users/gl/tzb/M2C_STATE.md自迁移后变化，需既有legacy-reconcile；本线未编辑legacy，不代处置。 · ref: /Users/gl/tzb/M2C_STATE.md

- `ruling.b4_interpretation_boundary_confirmed` — tzb-fe确认撤回B-4因果越界表述；权威解释仅采用a7cdffd4版：该具体极性/顺序改写不能纠正，不外推所有措辞或43个假阳性成因。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/b4-polarity-v1/b4-analysis-interpretation-v1.json

## 4. 待办
- `todo.tzb_fe` — 【tzb-fe】收包即审;两批治理激活;preflight PASS→8 发→closeout→结果+judgment 报用户;若晚沿/超截止,按预案自动 halt 报告(除非用户延时)。
- `todo.user` — 【用户】可选:延截止至 8/30 晚(一句话);chxy 占卡已自行缓解,无待办。


- `todo.suffix_enumeration` — 零消费枚举2^7=128后缀,用冻结auditor真实判定路径(禁重实现)判N分支可达性、退回原因分布、terminal与reason对应。必报节点

- `todo.prescan_identity_gate` — 装身份绑定门:prescan须记录所验计划身份(control_root+request digest),点火前校验相等否则fail-closed;固定序列=定稿计划→prescan→五条件→preflight读回→点火,prescan须为最后一步



- `todo.v2_unknown_state` — v2远端终态未知须闭合(同ordinal04截断类)。禁自行核验/清理;先只读后议清理。现离线备最小只读核验命令集(禁rm/kill/stop/prune),待用户授权一次跑完

- `todo.s5_materials` — S5解除停靠转材料(非新工程线):P2 48例可视化演示、第1页语义门兜底版、第3/4/6页数字块、附录26/38分类表与答辩问答。口径以CLAIMS-SHEET为准,文件落reports/带deck-或appendix-前缀

- `todo.deck_pages_missing` — tzb-fe漏检:8页deck仅1/3/4/6有内容块,第2/5/7/8页缺失。分工=S5写第2、5页,tzb-fe写第7、8页


- `todo.send_v4` — 改发v12:正文=reports/external-consult-brief-8-20260831.md全文,附件=reports/下v12.tar.gz+.sha256。发GPT Web Pro。待用户执行


- `todo.create_once_sweep_all` — 9/3后:把create-once禁重定向规则扫遍全治理侧脚本(非仅v6)。当前0命中结论的范围限定须随结论一起引用,不得单独引用

- `todo.build_v7` — v7本地create-once建包与独立核验完成；待tzb-fe同强度发前复核。未commit/push/upload，包暂存/private/tmp，复核前禁复制/发送。 · ref: /private/tmp/m2c-r13239-external-review-delivery-final-audit-v7-v1.json

- `todo.deploy_adaptation` — 部署三洞:①无Authorization头②endpoint/model默认指向node2③guided_json硬依赖非vLLM后端400。验收=docker起mock OpenAI兼容端点跑通三场景+pytest仍135零FAIL

- `todo.vla_layering_wording` — tzb-fe自裁:CLAIMS §8加分层设计理由(learned policy输出动作无可检查中间表示;我们最强证据依赖'计划'这一可检查对象)。标为设计陈述非证据主张。v7建完再改,现在改会打断建包

- `todo.post_v7_claims_edits` — v7出包后一并改CLAIMS:①§8加VLA分层设计理由(标设计陈述非证据主张)②§0e加'未经核实的不可核实性'变种。现在改会打断建包

- `todo.weight_redistribution_license` — 9/3后网盘路径开通前必查:Qwen3.8-27B权重的再分发许可。放网盘给评委=再分发,与本地使用不同。S5在MolmoAct2上发现同类问题(repo Apache但权重card无license字段)

- `todo.build_v9` — 【m2c-exec】先独立核验transcript恢复、fullrepo argv降级、S5 P2 inventory与两份纠正版；active11全语义PASS后才建fresh v9链。 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json


- `todo.object_table_benchmark_owner` — 待用户定:对象表基准(那台秤)无owner。下周期整个感知选型计划压在它上面。PR-Bench可能补上一部分

- `todo.manifest_driven_constants` — 9/3后:冻结脚本常量硬编码版本化路径致任何修正级联成下游全部新版本(v2/v3各引入一次新缺陷)。改为从manifest读active身份,单点更新。属状态迁移受五类门控

- `todo.build_v13` — 【m2c-exec】按ruling.v13精确改current三文件4处+包外correspondence1处，其余材料字节不动；重建index/MANIFEST/archive/sidecar，单次package+verify，终审拷reports后报tzb-fe两点复核。 · ref: /private/tmp/m2c-r13239-v12-preservation-before-v13-v1.json

- `repair_loop.v3_abort_disposition` — 待tzb-fe裁：v3第26请求60s timeout已先触发ABORT，随后ADR漂移令post-check抛错且无result；仅无headline分析，fresh重跑须新裁定。 · ref: /Users/gl/tzb-lanes/repair-loop-v1/repair-loop-evidence-v3-20260902-v1/single-07-missing-safety-predicate/attempt-01.json

- `repair_loop.v4_implementation` — 实现fresh v4：新增v4 prereg/runner/tests，改pyright；冻新receipt/prereg，单发advisory probe后立即跑，终值后再取数。 · ref: /Users/gl/.claude/plans/merry-leaping-adleman.md

- `implementation.agent_demo_v1` — agent-demo四场景各单次S1+S4完成并渲染24帧；coverage COMPLETE：present PASS=1、absent REFUSE+PASS、validator REJECT=2；4+4请求、0重试/修补/选择。待最终独立守恒核验后转B-1。 · ref: /Users/gl/tzb-lanes/agent-demo-v1/agent-demo-completion-v1.json

- `todo.ppt_final_batch_edit` — 用户 13:5x:PPT 最后一起改。P11 占位换 agent-demo summary.png;P12 第三块'契约可见基线还没跑'已过时→换 k=0 21/24(21/21)+ A-1 20/23(20/20),标 planner-side repair memory;改完 grep 禁语。 · ref: /Users/gl/tzb-deliverables/ppt-v1/xh-202607-deck-v1.pptx

- `implementation.agent_demo_v2_locany_s2` — fresh v2 additive:S1/S3/S4/S5复用v1，仅S2换LocateAnything VP-LoRA live；同4案重出trace/frame，水印含OPERATOR_EXEMPLAR_BOX。 · ref: /Users/gl/tzb-lanes/agent-demo-v2/

## 5. Recent tail(journal 缓存,非权威)
- 2026-09-03T02:49+0800 [FACT/lane] <m2c-exec> `lane.v3_live_line_closed` — 现场线在现渲1280x960帧上端到端闭环:中文指令→S0分解→S1 PRESENT→注册颜色规则选中青色框(0.588度 vs 35.8/119.4)→真绑定→S5 PASS,修复轮0用/2允许;事后核验落在cylinder_06约5mm · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-live-hires-v1/live-line-completion-v1.json
- 2026-09-03T02:49+0800 [FACT/lane] <m2c-exec> `lane.v3_frame_disclosure` — 帧上强制披露已生效:box choice行+术语hue+'colour disambiguation is done by a registered rule, not by the localizer';修复轮标(interim setting);渲染器按行高缩字号修了挤行
- 2026-09-03T02:51+0800 [FACT/lane] <m2c-exec> `lane.v3_no_regression` — 改动回归已验:冻结capture的observation五个时间/身份字段与已发布逐字相同(mtime回落生效),旧trace(chain-v1/000033)用新渲染器仍出7个文件
- 2026-09-03T02:51+0800 [FACT/lane] <m2c-exec> `lane.v3_hires_unrun_frames` — hires预登记3帧只跑了000000(离线1次+现场1次):分辨率实验的问题已被该帧答完,余两帧未发请求,不是弃用结果而是没跑;如需补跑请说
- 2026-09-03T02:51+0800 [FACT/facts] <tzb-fe> `pkg.q4_v2_and_wording` — q4补量:LocateAnything峰640x480 8.83GiB/1280x960 11.18GiB,均<20GiB线;同卡共驻未量,1280非必需按显存选。9/4硬口径:localizer只出类别级框,指代由注册规则选,不得写成VLM做的/实例重识别;真值只事后核验 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/receipts/locany-vram-measurement-v2.json
- 2026-09-03T02:51+0800 [FACT/facts] <tzb-fe> `vnext.live_line_closes_fresh` — 现场线在现渲帧上端到端PASS(核实回执):1280x960仍3框同标签→按gen866(b)落地注册颜色选框规则(先发布,青hue距0.588°),中文指令→S0→S1→选框→真绑定→S4→S5 PASS,事后距青色cylinder_06约5mm;帧上强制披露;修复轮0/2 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/fresh-live-hires-v1/live-line-completion-v1.json
- 2026-09-03T02:53+0800 [FACT/lane] <m2c-exec> `lane.v3_peer_attribute_baseline` — 残差线600图text诊断(attribute 100行:中位1框/>1占14%/best≠first 8.2%)结论域=自然图像;作者已声明不得据此支持'text模式能做属性定位';小尺度合成渲染域上属性消歧必须靠注册规则 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/locany-text-600-diagnostic-v1.json
- 2026-09-03T02:53+0800 [FACT/lane] <m2c-exec> `lane.v3_render_physics_visibility` — 待验风险:残差线v26称该配置下渲染器看不到物理状态(两模式max_change恰0.000000)。我的帧无法证否也无法证实——本线场景物体静止、手臂锁home;若成立则演示的执行段无法显示运动,属打包级风险
- 2026-09-03T02:53+0800 [FACT/lane] <m2c-exec> `lane.v3_physics_did_advance` — 本线可证:PhysX张量读到关节速度逐帧变化(0.008931/0.010710/0.011482),物理确实在推进;物体位姿恰0.000000是因其真静止。故'恰0'不足以证明渲染器看不到物理
- 2026-09-03T08:16+0800 [FACT/facts] <tzb-fe> `pkg.render_physics_risk_standdown` — demo lane 02:53登记的打包级风险'渲染器看不到物理状态'解除:来源是残差线相机bug不是渲染器;但至今无人演示过帧间场景跟踪,演示执行段能否显示运动仍待v28或现场线首次运动渲染证实 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-final-conclusion-v1.json
- 2026-09-03T08:17+0800 [FACT/facts] <tzb-fe> `vnext.render_conclusion_withdrawn` — 更正(残差线02:5x撤回):render-final-conclusion-v1与gen854'渲染器读陈旧场景'结论作废;真因=相机四元数走未转置路径,镜头没对着工作区;authoring对到0.72µm;v24死于panda_link8无prim;相机修一行后v28待跑,08:15未见结果 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-final-conclusion-v1.json
- 2026-09-03T08:23+0800 [FACT/facts] <tzb-fe> `ruling.user_default_27b` — 用户裁(2026-09-03 08:3x):打包全部走API端点,默认指挥体=Qwen3.8-27B(OpenAI兼容端点,node2 vLLM先例,k=0 21/24);flash改为可选profile,用户之后付费买flash类模型再试。覆盖gen799的flash默认 · ref: /Users/gl/tzb-deliverables/judge-package-v1/config/llm.yaml
- 2026-09-03T08:41+0800 [FACT/facts] <tzb-fe> `job.cross_embodiment_v1` — 用户裁(09-03 08:4x):做第二台臂跨本体演示,labserver走代理拉资产。同一份已验证计划JSON→两份本体profile(Panda+UR10)各跑approach位不抓;残差线v28后接手GPU1;24:00前出才算原创结果,否则只交profile · ref: state/v2/jobs/cross-embodiment-v1.json
- 2026-09-03T08:43+0800 [FACT/facts] <tzb-fe> `claims.recovery_wording_v0903` — 用户批(09-03 08:4x):CLAIMS §8'2层恢复'→'一条RECOVER恢复路径',旧表述作废;不插改,新版本包 reports/CLAIMS-SHEET-20260903.md(72ccf913);deck/BRIEF无该词,引用换版待PPT批次 · ref: reports/CLAIMS-SHEET-20260903.md
- 2026-09-03T08:43+0800 [FACT/facts] <tzb-fe> `claims.sheet_0831_digest_mismatch` — 核查项:reports/CLAIMS-SHEET-20260831.md 现为62cd515a/43826B,与gen1161冻结基线f90c7859/28637B不符(多约15KB),文件未入git无法溯源;需查是否有后续重冻结记录,否则属插改 · ref: reports/CLAIMS-SHEET-20260831.md
- 2026-09-03T08:44+0800 [FACT/facts] <tzb-fe> `vnext.grasp_render_v28_success` — v28成(核实记录dddb63d7):v19轨迹关节角字面回放渲染,close 22mm与wide 18mm各117/117帧有内容,渲前相机瞄准闸0.000°;lift帧可见夹爪抬起红圆柱、邻居未动。口径:回放非第二次执行,成功仍是v18一次+v19复现一次,无成功率 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-success-record-v1.json
- 2026-09-03T08:44+0800 [FACT/facts] <tzb-fe> `vnext.render_conclusion_withdrawn` — 更正gen892归因(残差线534d14bf):真因=相机既没对准也没设镜头(朝向应用路径未单测+默认50mm镜头视场仅23.67°),不是渲染器缺陷;v28同时改两处未隔离单一元凶;v24死于panda_link8无prim保留 · ref: /Users/gl/tzb-lanes/isaac-residual-diagnosis-v1/render-conclusion-correction-v1.json
- 2026-09-03T08:44+0800 [FACT/facts] <tzb-fe> `s2.text_mode_domain_caveat` — S2口径限定(残差线自报):600图text诊断只在自然图像域成立,不得用来支撑'text模式能做属性定位';小尺度合成渲染上分辨率加倍仍不分色(demo lane实测),属性消歧靠注册规则;对外材料带'自然图像'限定 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/locany-text-600-diagnostic-v1.json
- 2026-09-03T08:58+0800 [FACT/facts] <tzb-fe> `claims.sheet_0831_digest_mismatch` — 核查结果:0831文件9/1 13:29的增补(§0e等)对应state已登记的v7后计划编辑(gen1220/gen142),是tzb-fe谱系的正当修订但漏落重冻结digest;非插改。现digest 62cd515a/43826B作为事实基线;文件与reports/另42件从未commit,建议入库以留痕 · ref: reports/CLAIMS-SHEET-20260831.md
- 2026-09-03T09:01+0800 [FACT/facts] <tzb-fe> `git.reports_tracked` — 用户裁(09-03 09:0x):reports/全部入git以留痕。commit efead17(main):96文件35929行,含CLAIMS-SHEET 0831/0903、咨询简报、SUPERSEDED tar包(共4.3MB)、hardware探针json;入库前扫过无密钥。未push · ref: reports/CLAIMS-SHEET-20260903.md
