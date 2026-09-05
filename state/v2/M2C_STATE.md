<!-- GENERATED — 禁止直接 Edit/Write。唯一写入口: tools/statectl.py -->
<!-- statectl protocol=2 stream=M2C generation=2011 updated=2026-09-05T20:33+0800 -->
<!-- 自 M2C_STATE.md 迁移 sha=9dc690524ad77e6d51964237f11ee107e23e3ae92398d19e3424eb0676648fc6 -->

# M2C 权威状态(活跃快照,协议 v2)

> **只有 §1-§4 具规范效力。**§5 是 journal 缓存;仅存在于 journal 的内容**不是约束、不是待办、不是当前真相**。完整历史见 state/journal/M2C/。
> 唯一写入口 tools/statectl.py。写者角色 ['tzb-fe', 'm2c-exec'](角色串,重启不变;绑定见 state/v2/WRITERS.json)。`--session` 自声明未验证,属写入纪律层,**非安全属性**。
> 导入的历史记录 grandfathered,不受 1024B/160 字符上限约束(tzb-fe 裁定 2026-08-30 §3)。

## 1. 当前事实
- `chain.head` — 治理链 head:**P″ `51de5c916ed8065ab2d20effc23ad5c3336d24af`**,分支 `m2c-recovery-h3`,仓库 `/Users/gl/tzb-qrm-lite`(worktree 脏面受治理,禁动;零 origin recovery ref)。链序 H‴<R′<P<Q<R″<P′<Q′<R‴<P″(全身份见档)。
- `host.formal_canonical` — formal host(labserver root@labserver)canonical 面:P″ checkout、封印源 0555/25、ledger(bootstrap+attestation+claims00-03+terminals00-02)、evidence(run-00..03 目录)、scratch——全部冻结,禁触。
- `ruling.r132_39_option_a` — 用户决策(R132.39,Option A):**successor campaign 双机制**(前向类型化 POSE_GATE_REJECTED 终态化 + 零消费追溯 recovery03),八段治理序各自审查冻结;**successor combined-prefix preflight PASS 后剩余 8 发立即跑,不再询问用户**;**硬截止 2026-08-30T12:00+08:00**,未全绿则自动发布诚实 halted-campaign 报告(用户可延,截至目前未延)。
- `design.terminalization_fix` — 冻结设计蓝图:`/private/tmp/m2c-r13236-terminalization-fix-design-v1.json`(sha 0b02af91…,binding,偏离需 fresh ruling)。
- `auth.user_gpu_20260831` — 用户gl 2026-08-31明确授权两项:(1)按4dc01803计划原样只读核验v2未知终态;(2)Task32 labserver GPU<=2h。发现残留须停报不得清理;清理需另次用户授权
- `auth.user_node2_readonly_fetch` — 用户2026-08-31授权(原话'2你批一下')只读取回node2 /home/gl/xh-202607-qwen-s5 的TEST/BLIND/三split paired、two-epoch训练报告、adapter tree清单。仅读:禁rm/kill/写入/起GPU任务 · ref: state/v2/M2C_STATE.md
- `freeze.materials_baseline_v5` — v6基线:consult7=待m2c-exec重算(修陈旧计数13/13->30/30);CLAIMS=56238b92/32017B;deck-p7-p8=8ea16ccb;video=59254c26;vNext=59626c55。v5包因该错不发
- `stopline.create_once_no_shell_redirect` — 裁定:create-once产物禁shell'>'喂入(重定向先截断,守卫在破坏下游)。须--out+O_EXCL或临时名+RENAME_NOREPLACE。m2c-exec已扫v6调用面0命中——范围仅v6脚本,全治理侧清扫属9/3后
- `stopline.governance_freeze_until_v6` — 硬停:v6发出前不再新增/重建任何治理机制。只做两件=补完整Bash+Python扫描、建v6。非内容性流程瑕疵一律记录后延至9/3后。距冻结3天
- `freeze.materials_baseline_v7` — v7基线13件已程序化生成并发m2c-exec:S5四件760e7151/7e83cec8/a8632788/63da397f/49f5ce04经tzb-fe独立复核对上,命名清零,HTML 6处NOT_ORIGINAL_RUN+2处aggregate绑定+零外链
- `freeze.materials_baseline_v7_final` — v7非索引TierA最终baseline-v3 PASS:12件相对v6变更8、新增brief8、未变3；O_EXCL，源字节再变即停。 · ref: /private/tmp/m2c-r13239-v7-tier-a-refreeze-baseline-v3.json
- `auth.chxy_readonly_basis` — tzb-fe对chxy的只读访问依据=用户'chxy够的'(该线GPU授权)。仅限只读核验本线自产回执。写入/调度/触碰他人进程仍须另行授权
- `freeze.materials_baseline_v8` — v8非索引TierA refreeze-v1 PASS：12件相对v7仅brief7变更、无新增、其余11不变；新不变量存在且陈旧30计数缺席；O_EXCL。 · ref: /private/tmp/m2c-r13239-v8-tier-a-refreeze-baseline-v1.json
- `freeze.qwen_brain_repo_integrity` — 冻结面复查:13个terminal文件今日未动,contracts_v1=24a1d8e2与冻结记录逐字符同。git M项为早于冻结快照的未提交改动。今日仅改.gitignore与部署三文件
- `freeze.active_presentation_v9` — v9 active presentation refreeze-v1 PASS：11件现行材料相对v8仅CLAIMS与brief8变化、9件不变；brief7具三重历史banner且排除出active集合，另作为历史过程件保留。 · ref: /private/tmp/m2c-r13239-v9-active-presentation-refreeze-baseline-v1.json
- `auth.qwen_research_license_ok` — 用户2026-09-01裁定:Qwen RESEARCH LICENSE用于本次比赛允许。Rex-Omni路线许可证阻断解除。用户已另开会话推进该线
- `freeze.v9_latest_four_source_identities` — fresh4:41178/83937b55,14144/7d734a3a,14727/bee610dd,17736/331bbca8 · ref: /Users/gl/tzb/reports/evidence-fullrepo-test-20260901/FULLREPO-TEST-RECEIPT.json
- `freeze.materials_baseline_v9` — v9材料面终版12份已逐字节核并落盘基线文件;未解析路径扫描仅2处且均带溯源标注、包内路径在前 · ref: state/v2/jobs/materials-baseline-v9.json
- `freeze.v9_active_presentation_final_v2` — v9 fresh refreeze-v2 PASS:协调baseline十二件逐字节全match；current active=11，brief7历史件outside TierA，current-state correspondence排除；绑定独立语义audit与v8 preservation。 · ref: /private/tmp/m2c-r13239-v9-active-presentation-refreeze-baseline-v2.json
- `freeze.v9_active_presentation_final_v3` — CLAIMS fullrepo引用改canonical包内路径后，active11 semantic-audit-v3 23项PASS、refreeze-v3与preindex-v2 PASS；brief7历史outside TierA，correspondence排除。 · ref: /private/tmp/m2c-r13239-v9-active-presentation-refreeze-baseline-v3.json
- `freeze.v9_final_sources_v2` — v9 final packager/verifier fresh v2源码已用O_EXCL冻结为0444；draft与误播种v1均不作active。尚未执行；待source-bound invocation audit PASS且所有目标absence复核。 · ref: /private/tmp/package_m2c_external_review_v9_final_v2.py
- `freeze.v10_final_sources_v2` — v10 fresh v2 packager/verifier经precheck-v3 22/22 PASS后冻结0444；invocation-audit-v2 10/10 PASS，AST解析绑定precheck/audit/双方源码，v10输出全未消费。 · ref: /private/tmp/m2c-r13239-v10-create-once-final-invocation-audit-v2.json
- `freeze.v11_final_sources_v1` — v11全门precheck-v1 24/24 PASS；结构化index断言干跑51行全绑定；final packager/verifier字节一致O_EXCL冻结0444，invocation-audit-v1 10/10 PASS，输出全fresh。 · ref: /private/tmp/m2c-r13239-v11-create-once-final-invocation-audit-v1.json
- `freeze.v12_final_sources_v1` — v12 prefreeze全门19项PASS；仅MANIFEST历史brief7补注及统一v12 provenance变更，材料/证据源不变，planned 83唯一。packager/verifier O_EXCL冻结0444，source-bound audit 10项PASS，输出fresh。 · ref: /private/tmp/m2c-r13239-v12-create-once-final-invocation-audit-v1.json
- `freeze.v13_materials_baseline_v1` — v13材料精确改动已落盘并机械复原核验PASS：包内仅CLAIMS/brief8/VNEXT三文件变化，共4处裁定替换；其余9/12材料字节同v9基线。包外current-state correspondence仅1处同类替换且必须继续排除。 · ref: /private/tmp/m2c-r13239-v13-materials-baseline-v1.json
- `auth.user_chxy_kill_aivideo_20260901` — 用户gl 2026-09-01授权kill chxy上PID962984(/home/fangzhou/ai-video,占34490MiB,理由:挂一周GPU利用率0)。这是8/31残留规则要求的另次授权。仅限该PID,先证据后kill再复核,不清其他 · ref: /Users/gl/tzb/state/v2/jobs/rex-omni-pointing-lane-phase1.json
- `freeze.v13_final_sources_v2` — v13 precheck-v2 26/26与source-bound audit-v2 11/11 PASS；packager/verifier frozen 0444且未执行，输出全fresh；v1链封存。 · ref: /private/tmp/m2c-r13239-v13-create-once-final-invocation-audit-v2.json
- `auth.user_chxy_kill_reaffirmed_20260901` — 用户gl二次重申kill chxy PID962984(原话:给chxy kill了啊)。tzb-fe已披露启动时间实为2.96天非一周,用户仍下令,视为其决定。利用率0依据成立。授权仅限该PID,取证-kill-复核三段 · ref: /Users/gl/tzb-lanes/rex-omni-pointing-v1/chxy-pid-962984-cleanup-20260901.json
- `stopline.repair_loop_v1` — 只准新增caller/预登记/回执于repair-loop-v1；契约/验证器/48例/service配置零字节改动。禁扩展BT/skill/多机；禁碰chxy。node2起服务/GPU须用户直接授权，结束须精确停服并独立复核。 · ref: /Users/gl/tzb-lanes/repair-loop-v1
- `auth.user_node2_gpu_20260901_repairloop_and_rexintegration` — 用户gl 2026-09-01直接授权node2 GPU给两条线:repair-loop(m2c-exec)与Rex感知集成(tzb-50),共用一个27B服务。人工起停一次,非自动生命周期。原话:给 · ref: state/v2/jobs/rex-omni-pointing-lane-phase3.json
- `discipline.no_metrics_from_inflight_dirs` — 硬规矩:禁止对运行中的证据目录算终值。今晚同一错犯两次(0/12 与 8/22 均为在飞快照)。取数前必须先确认 result 工件已写且 runner 已退。 · ref: ADR-0032-m2c-repair-loop-v2-limit-cycle.md
- `auth.user_two_gpu_100g_conditional` — 用户 2026-09-02 02:5x 预授权:LocateAnything 出 GO 后,两张 A100 都空(node2 无 vLLM 无第三方,chxy 训练结束)即可上两卡走 100G。先决:先 iperf3 实测带宽(job stop-line)。fhk 在卡上=不空,不起,早上报。 · ref: /Users/gl/tzb/state/v2/jobs/locateanything-visual-prompt-lora-v1.json
- `auth.overnight_delegation_20260902` — 用户 2026-09-02 睡前:不在时 tzb-fe 推进度并代批。可批:node2/chxy 既有授权内的 GPU 使用、起停我方服务、lane 新 create-only 路径、下载/实验/重跑/新预登记。永不:动第三方进程、冻结面、commit/push、权限/配置、密码、新主机、labserver GPU。 · ref: /Users/gl/tzb/state/v2/jobs/locateanything-visual-prompt-lora-v1.json
- `auth.two_gpu_conditions_check_0625` — 06:25 gen605 条件核对:GO 满足;chxy 空(14MiB);node2 不空——我方 27B 76GB 留给 k=0/agent-demo + fhk 重试循环(新 PID 373339)。两卡 DDP 不起,等早上。 · ref: ADR-0035-m2c-locany-postcompletion-packaging-failure.md
- `auth.two_gpu_100g_conditional` — 用户 13:4x 裁'上啊赶紧的'。两卡 DDP:LocateAnything 同 recipe,nnodes=2,NCCL over 10.10.10.x,max_steps 3000,argv 逐字同 GO run。新 run 新预登记。lane=two-shot-canonical-gate。 · ref: /Users/gl/tzb/state/v2/jobs/locateanything-visual-prompt-lora-v1.json
- `ruling.refusal_evidence_registry` — 裁定(06:2x):未注册目的地的拒绝证据可列出'已注册的是什么'(蓝箱ref作为可用项而非解析结果),不算泄露,和HUD提示同理;serve配方须记启动脚本及其摘要与env(VLLM_USE_FLASHINFER_SAMPLER=0为配方一部分);渲染器行高截断+显式提示接受,26行面板重设计不在提交前做 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/registry/
- `ruling.compiler_primary` — 裁定(用户,09-04 11:5x):现场默认改编译器主路——LLM只做S0理解/S1门/EXECUTE-REFUSE-RECOVER-反问决策与解释,六步计划由compile_plan从绑定TaskSpec生成并过同一冻结验证器;模型写计划保留为开关(deck演示用)。deck/README/CLAIMS措辞今晚同改 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/src/compile_plan_v1.py
- `ruling.compiler_primary_variant_a` — 裁定(tzb-fe,09-04 12:2x):编译器主路取(A)——EXECUTE轮不调S4,decision/rationale/六步全由编译器出,模型只在S0/S1出现,决策=门+绑定的确定性函数;15/15与逐字节一致由此必然。(B)否决:模型decision与TaskSpec冲突会被验证器拒成误报 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/src/compile_plan_v1.py
- `ruling.statectl_writer_live_loop` — 裁定(tzb-fe,12:4x):.M2C.meta.json writers加live-loop-v1(残差线交互循环用),不借m2c-exec名义写;GPU1起停EVENT由该role补记 · ref: /Users/gl/tzb/state/v2/.M2C.meta.json
- `ruling.s2_adapter_negative_accepted` — 裁定(17:0x):S2 text+我方LoRA负结果采纳(IoU中位0.950→0.912、V11中心3.24→4.14mm、零框5→10/70,14格无一胜):不切contract;负结果进deck附录与README。批任务2(4B S4可选profile),19:30硬截止,非默认 · ref: /Users/gl/tzb-lanes/finetuned-live-path-v1/NEGATIVE-RESULT-s2-adapter-ab-v1.md
- `ruling.review_round1_dispositions` — 裁定(17:2x,审查R1):M14=S2/S3只作'链路阶段+单次工程演示证据',不作感知能力主张;M13=出CLAIMS-SHEET-20260904(0903不改);b.ai是真实付费端点,.env默认改27B;M5/M6/M9/S7交demo lane,其余tzb-fe改 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-round1.md
- `ruling.capture_not_today` — 裁定(18:5x):取(a)今天不做CAPTURE/LAST_OBSERVATION(出v21需重跑流验收);README写双Isaac进程RAM≥48GB;单进程取帧记设计项。Dockerfile CMD改--help与注释更正接受;常驻执行器已进包resident/ · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/
- `ruling.locator_naming` — 裁定(用户,19:0x):域适配版定位器可命名'XH-Locator(LocateAnything-3B + Isaac域适配LoRA)',每处随基座注明(NVIDIA License §3.1/3.5);写'自研域适配版本'不写'原创模型';仅在21:30 A/B为正并进现场路径时启用;措辞可有气势但不越CLAIMS · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260904.md
- `ruling.lora_adoption_criteria` — 裁定(16:0x):Isaac域适配LoRA采用判据按颜色分看——总体不差且cyan/green(现场指称色)在held-out与14格上均不差于基座,且无物请求假阳率不增;cyan样本仅16须随结论披露;切分为同场景时间切分非场景泛化。21:30按journal时钟 · ref: /Users/gl/tzb-lanes/finetuned-live-path-v1/dataset/build-receipt-v1.json
- `ruling.grasp_record_into_package` — 裁定(16:2x):准grasp-success-record-v1.json(77KB,仅来源指纹)进包resident/并入SHA256SUMS;A6观测时效30s不放宽,按gen1417分卡跑;S2 TCP桥+contract v4(仅transport差异)+bash /dev/tcp shim+对象注册表接受 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/
- `ruling.v20_result_disposition` — 裁定(16:3x,v20两跑):truth模式逐位复现v15;perception模式抓取不读真值成功,落地因物体滚出料箱停于LANDING_NOT_OBSERVABLE(行为正确),真实深度上正向落地定位未建立。取(a)收工:v20随包作感知模式变体并明写此限,默认执行器仍v17;不再占GPU;(c)桌面扫掠记设计项 · ref: /Users/gl/tzb-lanes/executor-no-truth-v1/receipts/acceptance-receipt-v1.json
- `ruling.pinned_wording_exempt` — 裁定(17:0x):gen1282钉死的回放措辞引用块保持原文(含'一次性派发'),术语规范只管正文;跨12文件改定稿不做。live-demo.md其余三处术语已改;12项runner前缀赋值传参已由loop lane实测 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/live-demo.md
- `ruling.claims_change11_isaac_lora` — CLAIMS-0904变更11:Isaac text-LoRA第1次负结果条目(与变更6并列):held-out收益+按色崩+类别失衡根因+三条限制;禁引14格IoU 0.9677/V11 0.898mm(幸存者偏差)、禁'训了没用'/'泛化'。CHAIN_IMAGE默认v3 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260904.md
- `discipline.sync_via_staging` — 纪律(17:0x,demo lane提醒):包目录是-v挂进容器的,同步即时生效;今后tzb-fe只同步到两机的pkg-next/暂存目录,由正在跑的lane在安全点自行rsync进pkg/,不再直接覆盖运行中的副本。run_demo加模型名预检(GET /models不匹配即退出)接受 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/run_demo.py
- `ruling.a7_bitwise_and_5315` — 裁定(17:4x,审查7b):A7'真值模式=逐位复现'越界→改'回执所记4项控制指标与落点逐位一致(整次运行非逐位复现)';'接近误差3.274'必须同页并列'感知中心对真值5.315mm'(必改,同类混淆已禁);A7口径补回'不是负结果,也不是成果主张'。CLAIMS变更5/10已收紧 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-round7b-a7delta.md
- `ruling.colour_rule_thin_margin` — 裁定(17:2x):冻结现场颜色规则余量(绿146.7°对分界150°仅6.6°;brown/orange差0.1°)为已知直播风险,冻结面不动;README/live-demo写'已测试指称词:青/蓝/品红/红',CLAIMS变更12。路线A:链跑Mac,不加key;待tzb-b9停其侧车后再起冻结v3入口 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260904.md
- `ruling.receipt_executor_identity` — 裁定(17:5x):v17/v20回执内执行器串仍是继承的'v15',不能自证谁跑的→demo lane加附加字段executor_identity{file,sha256,version,image},继承串不改;envelope两sha不同待答并区分字段名;已跑回执缺字段文档注明 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/PROVENANCE.md
- `ruling.render_font_noto` — 裁定(17:5x):容器内--render因冻结渲染器写死macOS字体且镜像无CJK必败→包内加Noto Sans CJK(OFL,chxy自带)与许可证并重定向,NOTICE/manifest登记;R11-M1 live-demo已改;hook07加打印请求sha256 · ref: /Users/gl/tzb-deliverables/judge-package-v1/NOTICE.md
- `ruling.reconfirm_round_wording` — 裁定(18:2x):再确认第二轮今晚按(a):链运行期间并发采一帧,回执只写'严格晚于绑定帧、与规划并发',不写'晚于计划';拒绝那半用绑定帧自复查验;run_demo在S5后自采(b)记设计项。chxy seg2日志进包evidence · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260904/chxy-cold-install/logs-seg2/
- `ruling.colour_rule_enable_and_disclose` — 裁定(18:4x):注册颜色规则未随包启用(r4记FIRST_RETURNED_BOX)→进包默认启用以与账目配置一致,启用后跑一轮记规则身份;披露无阈值无拒答、目标色框缺失时选别色框且按色词命名、S1唯一挡板;'绿→青'仅绿框缺失时成立;README/CLAIMS已改 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260904.md
- `ruling.reconfirm_live_positive_half` — 裁定(19:0x):再确认'测量半'现场不可达(取帧38s>链7s)不再硬凑;交付口径=拒绝半现场两次实证+测量半离线真深度实证(晚25min帧2.07mm);S5后自采记设计项。12项:1-6/11过,7=钩子,8/9/10/12 SKIP→demo lane修 · ref: /Users/gl/tzb-lanes/cold-install-chxy-v1/logs/seg2/round-r5.log
- `ruling.lora_v2_rejudge_on_truth` — LoRA第2次(19:01):held-out真值口径全面更好(det .845→.995,cyan .897→.983,IoU .861→.954,紫色真缺席假阳.991→0);14格按一致性未过但按真值cyan平手无丢框。裁(b)按真值重判,green先答帧内有无绿柱;LoRA侧车跑通合成一轮才切默认 · ref: /Users/gl/tzb-lanes/finetuned-live-path-v1/RESULT-isaac-text-lora-v2.md
- `ruling.lora_v2_optional_profile_shipped` — LoRA第2次真值重判三条全过→随包可选profile env/s2-lora-v1/(255MB,sha 8/8 OK),默认仍基座;采用门未跑不切默认;README/manifest/negative-results/CLAIMS变更13已写;名字待用户 · ref: /Users/gl/tzb-deliverables/judge-package-v1/env/s2-lora-v1/README.md
- `milestone.final_tarball_20260904` — 最终交付包 judge-package-v1-20260904-235958.tar.gz(764文件/225MB/CLEAN,ADDR+MODE双检,sha256 d16e5494…);前版入superseded/;含卡点23补丁、S2_PROFILE开关+首验、lora-r8b、直播两轮、OQ19/20 · ref: /Users/gl/tzb-deliverables/judge-package-v1-20260904-235958.tar.gz.sha256
- `ruling.lora_r8_attribution_criterion` — lora-r8 归属判据(tzb-b9核):s2-session-receipt ready_line 三条同时成立——adapter.attached=true、adapter段含两safetensors摘要、entrypoint=派生入口fd833a52…;s2_source_label包内不存在不作判据 · ref: /Users/gl/tzb-deliverables/judge-package-v1/env/s2-lora-v1/SHA256SUMS
- `ruling.lora_r8_merged_contract` — 裁定(23:2x):LoRA契约v4继承v3 ssh传输且镜像无ssh→lora-r8 用合并契约(vendor冻结v4为底,只改entrypoint/adapter/label/derivation,invoke不动),M2C_S2_CONTRACT指它,不进包;过后进env/重出;时限00:30 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/s2_locateanything/session.py
- `labonly-viewport-variant` — lab-only 视口 v3 在跑(16:59:33Z 起):72d91479(v17 纯增171行/删0行),每0.25s 查 pose 文件 mtime 实时改机位(轮内也可),启动脚本 v5 带关网格/轴五 flag(生效待验);包未动 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/
- `labonly-viewport-verified` — 视口变体已验(16:23-16:24Z 一轮青色):applied_by=set_camera_view 无回退;视口 1285x688(crop=1285:688:52:38),主体占满 1272x688(原~230x140);全帧 mean|Δ| 1.63(原 0.003);臂顶被裁 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/frames/
- `live_window.newview_round` — 新机位首轮(00:23):round-001-composite-20260904T162314 ALL_SIX;全帧臂动峰值1.3–2.1 vs 空闲0.079,两路采集同结论,不再需裁;限制:视口竖向窄,臂举高时上半截出画;同静态摆放三轮数字逐位相同不算样本;ssh -L 探8555空结论 · ref: /Users/gl/tzb-lanes/live-loop-v1/receipts/live-window-newview-round-v1.json
- `viewport-second-pose-candidates` — 第二机位候选(待用户选,未重起):A' eye(0.05,0.95,1.95) 俯角55° 抓取零遮挡;B' eye(1.00,-0.85,1.85) 俯角47° 与OBS相对、轨迹横穿画面;共同 look_at(0.02,-0.08,0.50);曝光未验 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/viewport-pose-candidates-v1.txt
- `ruling.viewport_pose_file_and_candidates` — 裁定(00:3x):直播变体改为每轮读 /m2c/labonly/viewport-pose.json(缺省OBS机位),切机位不重起;候选A'(+y侧俯角55°,遮挡最少)/B'(对面145°俯角47°,动作横穿、明显非模型视角),默认B';首轮抓帧查曝光>230则换;不动包与观测相机 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/
- `viewport-pose-in-effect` — 展示机位改由 tzb-60 按用户口令直接写 pose 文件(step1 = be0b1f9c, eye 1.327,-1.107,1.578 / look_at 0.02,-0.08,0.55);用户键盘版存 viewport-pose-user-0106.json;我方不写不覆盖, 待 tzb-60 喊定稿再固化 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/viewport-pose.json
- `live_window.viewport_b4_final` — 直播机位定 B4(eye 1.147,-0.965,1.903/look_at 0.02,-0.08,0.85,sha 975c7b54):臂完整进画(像素判据)、主体居中、曝光≥250占比0;机位文件每轮读、切换不重起;五份存档在 labserver /var/tmp/labonly-viewport-v1/ · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/frames/b4-mid.png
- `live_window.keyboard_camera_control` — 直播机位键盘实时调(01:0x):变体v3每0.25s轮询pose文件mtime→重摆相机(纯增171行,不进包);Mac脚本 viewport_keys.py(方向键转/WASD平移/JK升降/-=远近/[]瞄点/P/0/Q);第四次重起00:59含关网格flag;通路实测0.25s;当前pose z=0.65 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/viewport_keys.py
- `viewport-rect-measured` — 视口真 3D 视图 = 全帧 x69..1317 y63..725(1248x663);行0..24 工具条、crop 列17/1266 边框。桌面外是背景渐变(243->225)+桌沿,稳态无网格线;判此类结构须用去行斜坡后的残差,不能用 std 或灰带计数 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/frames/analysis/ramp-removed-bdouble-vs-gridoff.png
- `viewport-grid-axis-off` — 坐标三角已验去掉(714->560)。网格只在开 stage 的加载几秒内闪现, 稳态无线(±4/±12 残差图两侧都验过)。flag 是否消掉那几秒【仍未验】:双方帧相对 M2C_VIEWPORT 日志时刻(唯一共同时钟)落在加载完成的两侧 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/frames/analysis/
- `picture-measurement-method` — 画面测量方法笔记已落盘 MEASURING-THE-PICTURE.md 137af47a:相位零点取 docker logs -t 的 M2C_VIEWPORT(EXECUTE->相机 6.6s)、两样本须同前置状态、判结构须去渐变+固定窗口看图、聚合量只筛帧 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/MEASURING-THE-PICTURE.md
- `labonly-viewport-liveness-probe` — PING 8s 是病不是结构:重起后同代码 0.02s。8s=空转周期被拖慢;GIL 交接只解释倍数。1.616s 写入→应用亦为病中数。 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/PING-LATENCY-IS-NOT-A-HANG.md
- `ruling.capture_host_fresh_root` — 裁定(01:5x):取帧宿主每次重起一律用全新 dataset root(OQ19 已实发生:01:50 探测覆盖了 000000.png);v17 不重起,先跑一轮 cyan 判别画面冻结是渲染/编码侧还是空闲不重绘(loop lane 抓帧逐帧 Δ 精确 0.0000) · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/open-questions.md
- `submission.q9_six_items` — 用户 01:5x 给出主办方 Q9 六项交付要求:①推理代码+模型(模块可独立运行)②训练代码+预训练权重+数据集③仿真环境打包④仿真验证视频⑤技术报告(重点开放域感知/任务决策/微调策略/智能体设计)⑥使用说明。缺口:②训练代码与数据未进包、⑤技术报告未写 · ref: /Users/gl/.claude/projects/-Users-gl-tzb/memory/xh202607-submission-requirements-q9.md
- `task.tech_report_owner` — 技术报告 owner=tzb-66(用户 02:00 新开,sid 4035aaa0,角色 report-zh-v1 已注册);用户要求术语用领域常见中文词、不用内部造词、先查同行论文;事实来源=CLAIMS/NUMBERS/README;初稿12:00/定稿18:00;tzb-55 改为供数与守卫筛 · ref: /Users/gl/tzb/state/v2/WRITERS.json
- `report-v1-handover-to-tzb66` — 技术报告改由 tzb-66 写(tzb-56 改令 0205);deck-v2 转为供数+筛查:tools/screen_report.py 与禁写清单-给报告作者.md 已就绪;草稿已移出交付路径 · ref: /Users/gl/tzb-deliverables/report-v1/tools/禁写清单-给报告作者.md
- `ruling.report_banned_words` — 裁定(02:1x,报告线专用禁写表):放行 规划/推理/智能体(主办方原话与领域常用词);闭环只在变更10逐字句与否定句;位姿估计仅否定式;安全陈述带范围;统一用校验。deck 表不动;tzb-55 改筛查脚本与清单给 tzb-66 · ref: /Users/gl/tzb-deliverables/report-v1/tools/禁写清单-给报告作者.md
- `live_window.pose_user_final` — 用户裁定(02:0x):直播机位以 step 3 为准(eye 1.478,-1.226,1.698 / look_at 0.02,-0.08,0.60,sha 4dda3c2b,实测主体占比 30.7%);键盘那次作废;'缩略图'系渲染滞后旧画面;重起保持此 pose · ref: /Users/gl/tzb-lanes/live-loop-v1/evidence/live-round-20260905-bprime/step3-actual-after-render-caughtup.png
- `training-bundle-v1-delivered` — 训练交付包已出:tzb-deliverables/training-v1/training-bundle-v1(584MB/591文件)+ .tar 572MB sha 0273a99a。含两版数据集/adapter/日志/结果。脱敏过:无10.13./root@/key。 · ref: /Users/gl/tzb-deliverables/training-v1/training-bundle-v1/README-训练.md
- `v2-training-numbers-erratum` — 勘误0e6c90fd:RESULT-v2的train_loss 0.133是瞬时值比v1均值,错;同口径v1均值.1591 v2均值.1727(v2更高)。回执62a81648有4字段是v1硬编码常量,更正件b2e27ce7。 · ref: /Users/gl/tzb-lanes/finetuned-live-path-v1/RESULT-v2-training-numbers-erratum-v1.md
- `report-screen-ruling-applied` — 报告线禁写裁定已进 screen_report.py 覆盖层(规划/推理/智能体放行,闭环与位姿估计给否定豁免,校验统一);deck 表未动,正负例各复验 · ref: /Users/gl/tzb-deliverables/report-v1/tools/禁写清单-给报告作者.md
- `deliverable.training_bundle_v1` — 训练包第三版(tzb-76 02:4x):sha a5ba5091…(e669981e 作废);零代码改动;§1.2.1 执行环境约束(4 包外 digest 门、6 写死 ROOT、VENV_PYTHON)、§7 四件、PROVENANCE 对齐;偏离接受:仅第 5/6 步受限,第 7 步纯后处理;599/599 · ref: /Users/gl/tzb-deliverables/training-v1/training-bundle-v1.tar.sha256
- `report.zh_v1_started` — 技术报告 owner tzb-66 02:1x 开工:事实源读齐;PDF 路线 Markdown→HTML→Chrome headless(CJK 已验);tzb-55 旧稿改名为素材件仅查数;细节见 ref · ref: /Users/gl/tzb-lanes/report-zh-v1/LANE-NOTES.md
- `report.screen_tool_ready` — 报告筛查工具就绪(tzb-55 02:1x):screen_report.py 以覆盖层落实六条裁定(放行规划/推理/智能体;闭环与位姿估计逐处判+否定豁免;禁通用/自主智能体、符号契约验证);正负例各验;禁写清单 93 行给 tzb-66;deck 不动 · ref: /Users/gl/tzb-deliverables/report-v1/tools/禁写清单-给报告作者.md
- `live_window.v17_restart_0209` — v17 02:09 重起后 PING 0.01–0.02 s(重起前 7–8 s),GPU1 空转 10%;'8 s 结构性延迟'结论撤回(秒级即病);pose 保持 step 3;空闲循环本就渲染,先前是 0.125 fps 幻灯片;等轮内 GPU 利用率 · ref: /var/tmp/labonly-viewport-v1/slowgpu-vnext-v17-20260904T180841Z.log
- `live_window.gpu_recovered` — v17 重起后闭环(02:13):轮内 GPU1 34–70%(重起前 4–5%),一轮 55 s(前 11 min 停滞),reset_verified +8.4 s,ALL_SIX;机位重贴 +8 ms = step 3;直播恢复实时;用户可录 · ref: /var/tmp/labonly-viewport-v1/
- `judge-package-usage-doc-zh` — docs/使用说明.md 写完(459 行/12 模块):bash 18 块 -n 全过、python -c 4 条 compile 全过,manifest 已加行;附录 B 列 7 条缺独立入口待裁。 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/使用说明.md
- `defect.referring_expression_fixed_cyan` — 阻断缺陷(02:2x):start.sh 与直播驱动固定 expression=cyan cylinder,S0 只规则解目的地不派生指称词(无LLM),颜色规则只认英文→敲紫色抓青色。裁:S0 加颜色词表派生+新拒绝码,去固定值,紫/红评委路径复验;'S0=LLM'主张待更正 · ref: /Users/gl/tzb-deliverables/judge-package-v1/config/chain.yaml
- `s0-llm-exists-but-not-on-judge-path` — S0 两条路:live_entry_v4/v5 有真 LLM S0(stage=S0,usage 35/152/187,S0_DECOMPOSITION_FAILED_FAIL_CLOSED);评委路 run_demo 的 S0 是注册表确定性匹配、expression 由调用方传 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/src/live_entry_v5.py
- `ruling.s0_llm_extraction` — 用户裁(02:2x)颜色词表太固化→S0 改为 27B 抽取指称表达(JSON:zh/en 短语、注册颜色词或null、目的地、操作、否定;畸形即拒),S2 用开放词汇短语,颜色词 null 则规则跳过并披露;词表仅离线兜底;验收紫/红/最左边三句评委路径;README/deck 'S0=LLM' 暂不改 · ref: /Users/gl/tzb-deliverables/judge-package-v1/config/chain.yaml
- `s0.existing_llm_decomposition` — 树内已有真 LLM S0(live_entry_v4/v5,失败码 S0_DECOMPOSITION_FAILED_FAIL_CLOSED,回执 v4-switch-v1 turn.json,S0 2.12 s 出自此路);评委路未接它。裁:复用并扩槽接入评委路;S0 耗时须带路径身份;deck P2 槽位进 v2.1 · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- `report.s0_wording_pending` — 报告 S0 按 tzb-fe 02:4x 第二条改写为大模型结构化抽取(JSON 畸形即拒),留位【待补:S0 改版验收结果】;12:00 未过则改回确定性解析。紫色/红色两轮新证据留位于 4.1 · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.md
- `deck-v2.1-pending-list` — deck v2.1 待改清单已落 ppt-v1/PENDING-v2.1.md:P2 的 S0 槽位三改五(或按未过分支改确定性)、S0 耗时须带路径身份、LOCATOR_NAME、12项0FAIL落点 · ref: /Users/gl/tzb-deliverables/ppt-v1/PENDING-v2.1.md
- `discipline.varied_instructions` — 纪律(02:2x,用户指出后):评委路径'已验证'须至少三条不同指令(换物体/换目的地/应拒绝);管线图每步'谁在做'对代码核;README §Verification 已加说明;记忆已存 · ref: /Users/gl/.claude/projects/-Users-gl-tzb/memory/verify-with-varied-instructions.md
- `training-bundle-review-fixes` — 审查5条阻断改完,tar重打sha e669981e(旧0273a99a作废),599文件。T4显存标签错最重:设备级23.9/49.3GB而非8.45/9,硬件门槛差一量级,已改并加门槛句。 · ref: /Users/gl/tzb-deliverables/training-v1/training-bundle-v1/README-训练.md
- `report.zh_v1_draft1` — 技术报告初稿 v1 已写:report-v1/技术报告-XH-202607.md(约 45K 字)+ PDF 32 页;screen_report 仅余 2 项=冻结原话代码块(裁定豁免);留位 3 处(S0 验收、紫/红两轮);README 来源数字见 lane notes · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.md
- `judge-path-s0-referring-expression-fix` — 评委路 S0 指称表达修复:复用冻结 live_entry_v5.decompose;start.sh/smoke06 去固定 cyan cylinder;新增 21 测试(共 60 过);已同步 chxy pkg 并在镜像内验通。 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/run_demo.py
- `report.draft1_rulings` — 报告初稿 v1(02:3x,32页)裁:冻结原话块豁免;允许 0903/README/negative-results 作数字源;删 135 与 S0 2.12s;统一对外标题(CLAIMS 变更 14);审查即刻核 · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.md
- `s0.llm_extraction_landed` — S0 修复已交(02:3x):复用冻结 live_entry_v5.decompose(模型出英文指称短语/目的地/操作;颜色词规则子串;否定走登记表);start.sh/smoke06 去固定值;tests 60 过;已同步 chxy;待 tzb-b9 三指令验收 · ref: /Users/gl/tzb-deliverables/judge-package-v1/tests/test_s0_referring_expression_v1.py
- `ruling.report_title_20260905` — CLAIMS 变更 14 已落报告:主标题改「面向工业机械臂的指令交互型智能体原型——开放词汇感知、确定性任务规划与可审计执行」,内部名括注一次;4.11 冻结原话块加引言句;数字来源含 0903/README/negative-results · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.md
- `defect.truth_prim_english_lookup` — 直播线发现(loop lane):build_request 的 truth prim 按英文子串查注册表,纯中文指称→BRIDGE_REFUSED_BEFORE_MINT;S0 修复(英文物体短语)绕过;裁不做 B/C/D,A(truth prim 取自绑定)记 OQ21;loop lane 同步新包后重跑紫色 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/open-questions.md
- `defect.start_sh_chain_dropped_instruction` — 同类缺陷(demo lane 02:3x):start.sh 的 chain 分支未把参数传进 step_chain→评委敲的指令永远取默认句(青色);已改为传 "$@",bash -n 过,已同步 chxy(sha 664ea560…);其余三分支验收后统一改 · ref: /Users/gl/tzb-deliverables/judge-package-v1/scripts/start.sh
- `judge-path-instruction-not-forwarded` — start.sh 'chain) step_chain ;' 未传参,评委敲的指令到不了链、永远跑默认句;已改 step_chain "$@" 并同步 chxy。同类:另三分支待验收后统一。 · ref: /Users/gl/tzb-deliverables/judge-package-v1/scripts/start.sh
- `report.user_feedback_draft1` — 用户 02:3x 看报告初稿:'太烂,一点图没有,不像技术报告,去看网上同行怎么写';令 tzb-66 查同行技术报告结构,补十类图表(架构/流程/信任边界/场景与HUD截图/定位框/抓放对比/LoRA曲线/色相分布/时延/48例表),A4 排版带题注目录;第二稿 06:00,定稿 18:00 · ref: /Users/gl/tzb-deliverables/report-v1/
- `report-v1-screen-round1` — 报告初稿筛查:禁写 0 项(4.11 逐字句豁免锚在 CLAIMS-0903:145);数字 513 个 507 命中,5 项待裁(8192、2.97/0.53、两个引用年份);23 个数仅外源 · ref: /Users/gl/tzb-deliverables/report-v1/tools/screen_report.py
- `tests.judge_path_instruction_guard` — demo lane 加 5 条回归(start.sh 传参静态断言、假 docker 跑真 start.sh 断言指令回显、M2C_EXPRESSION 覆盖可见、不再写死 cyan、trace.instruction 逐字),回退即 2 failed;全套 65 过;已放行同步 chxy · ref: /Users/gl/tzb-deliverables/judge-package-v1/tests/test_judge_path_instruction_reaches_the_chain_v1.py
- `report.screen_results_draft1` — 报告初稿筛查(tzb-55):禁写 0 项;数字 513/507 命中,5 待裁→裁:加 serve-27b.md 与 live-demo.md 为源,2.97 改 2.966 引回执;豁免锚定受控源原句;deck v3 用 check_deck_v3(覆盖层)不用 v2 守卫 · ref: /Users/gl/tzb-deliverables/report-v1/tools/
- `judge-package-test-count` — judge-package tests=65(原 39+S0 21+评委路参数 5);跑在宿主解释器,镜像内无 pytest。回归守卫已对旧代码验证会 FAIL。 · ref: /Users/gl/tzb-deliverables/judge-package-v1/tests
- `deck-v3-guard-ready` — ppt-v3/tools/check_deck_v3.py 与简报补充已就位(03:28 前);覆盖层放行规划推理智能体、禁通用自主智能体、闭环位姿估计逐处判;v2 表未动;REQUIRED 未继承已注明 · ref: /Users/gl/tzb-deliverables/ppt-v3/tools/简报补充-给-tzb-63.md
- `deck.v3_guard_ready` — check_deck_v3.py 就位(tzb-55 02:44,ppt-v3/tools/):v2 表只读+覆盖层,正负例验过,v2 deck 过 v3 守卫;REQUIRED/CONDITIONAL 按 v2 页码故 v3 默认不启用(tzb-63 需重写);简报补充已写;报告筛查加两源后 513/507,禁写 0 · ref: /Users/gl/tzb-deliverables/ppt-v3/tools/check_deck_v3.py
- `defect.executor_target_prim_hardcoded` — 阻断(02:4x,两线证实):S0 修后链前半对紫色全对(→cylinder_05),但 v17 写死目标 cylinder_06,检查在 envelope_consumed 后→REJECTED 先烧 nonce。裁 v21 变体(目标取自请求+注册校验、检查前移),04:30 交 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/vnext_dispatch_executor_v17.py
- `s0.purple_round_slots_confirmed` — 紫色轮 preregistration.json 证实 S0 分槽:purple cylinder / blue bin / RELOCATE,colour_term 由英文短语规则取,目的地色词不入物体短语;注:规则注册色 15 vs 场景可达 9,黑/棕/灰/粉/白在铸造前拒 · ref: /Users/gl/tzb-lanes/live-loop-v1/receipts/live-window-s0-fix-purple-round-v1-addendum-v1.json
- `deck_v3.takeover` — deck-v3 owner(tzb-63,sid f4a8adc2)03:28 接手:已读简报+补充、CLAIMS-0904、v2 全 20 页文本、check_deck_v3、术语表;ppt-master 完整性门 rc=0;路线=Generate PPTX Default;初稿 09:00 定稿 16:00 · ref: /Users/gl/tzb-lanes/coordinator-notes/brief-deck-v3-pptmaster-20260905.md
- `review-v3-final-bundle-delivered` — 不脱敏GPT终审包已出:review-v3/final-review-bundle-20260905T0245(499文件/29MB,tar.gz 6.6MB sha 12f85317)。保留内网地址与绝对路径;排除密钥/权重/图像/视频;凭据扫描0命中,往返499/499。含REVIEW-BRIEF-FINAL.md · ref: /Users/gl/tzb-deliverables/review-v3/final-review-bundle-20260905T0245/REVIEW-BRIEF-FINAL.md
- `report.zh_v2_in_progress` — 报告第二稿(图文版)进行中:图件脚本 build/make_figs.py+SVG 示意图,结构改为摘要/引言/总体设计/模块/实验/讨论/结论/参考文献/附录;含 R1/R2、2.966 引回执、训练包指针、超参表;目标 06:00 · ref: /Users/gl/tzb-lanes/report-zh-v1/LANE-NOTES.md
- `deliverable.gpt_final_review_bundle` — GPT 终审包已交(tzb-76 03:4x):review-v3/final-review-bundle-20260905T0245(499 文件/29MB,tar 6.6MB,sha 12f85317…),不脱敏、无密钥/权重/图像;十项齐+REVIEW-BRIEF-FINAL.md;brief 明写视频尚无交付件 · ref: /Users/gl/tzb-deliverables/review-v3/final-review-bundle-20260905T0245.tar.gz.sha256
- `executor.v21_in_progress` — v21 过半(demo lane,04:15 交):builder 精确替换 v17 八处;目标取自请求+烘入六注册 prim 校验;邻居=六减目标;检查在 envelope_consumed 前拒不花 nonce;新拒绝本地异常同形回包;两自主决定接受 · ref: /Users/gl/tzb-lanes/coordinator-notes/v21-executor-change-list-20260905.md
- `acceptance-3-instructions` — 三句验收前半全过:①purple→cylinder_05 ②red→cylinder_01 S0/S2/选框/世界坐标均正确;③"料箱"未注册,S0 拒、S2 未调用 · ref: cold-install-chxy-v1/receipts/acceptance-3/
- `finding-29-executor-target-pinned` — 卡点29:v17:75 TARGET_PRIM_PATH 写死 cylinder_06 无 env 覆盖,检查在 1152 晚于 1149 envelope_consumed=先烧账目后拒;①②各烧一枚无运动 · ref: cold-install-chxy-v1/receipts/acceptance-3/r1/
- `acceptance.three_instructions_front_half` — 三指令验收(02:56):①紫②红前半全过(S0 DECOMPOSED、purple/red cylinder、S2 一框、cylinder_05/01 对),执行器拒(卡点29);③S0 拒未登记目的地不花账目;新卡点30 取帧宿主偶崩→loop lane,31 S0拒绝exit=1→demo lane · ref: /Users/gl/tzb-lanes/cold-install-chxy-v1/cold-install-report-v1.md
- `deck_v3.plan_locked` — deck-v3 Step1-4 完成:项目 .claude/projects/xh202607_deck_v3_ppt169_20260905,design_spec+spec_lock 已 validate;20 页 1:1 沿用 v2;委派自决 Stage1/2(决策记录见 ref);进入生图与 SVG 授权 · ref: /Users/gl/tzb-lanes/deck-v3/LANE_NOTES.md
- `judge-executor-v21-target-from-request` — v21 交付:目标取自请求+注册六 prim 校验+检查前移(拒绝不花 nonce)+邻居六减目标;v17 侧仅 8 行变化,gate 段未动;15 测试,全套 80 过;已同步 chxy。 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/PROVENANCE-v21.md
- `deliverable.cold_install_report_1449` — 冷装报告 1449 行(tzb-b9 03:5x):新增三句验收一节 + 卡点 29/30/31 + 驱动脚本自曝三处;已复制入包(脱敏);acceptance-3 三套 run 目录与回执入包 rounds/acceptance-3-20260905/ · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260904/chxy-cold-install/cold-install-report-v1.md
- `executor.v21_delivered` — v21 交付(03:47):六文件双侧 digest 核;tests 80 过;build_request 邻居本就动态;RUN03_* 无读取处;consumer 串保留 v15(launcher 明文),v21 回执以 v21_target_resolution 键区分;tzb-b9 紫/红复跑中 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/PROVENANCE-v21.md
- `executor.v21_sums_and_blocker31` — SHA256SUMS.txt 14/14 与 -v21 5/5 重算并同步 chxy;卡点 31 已修(S0 合法拒绝 exit 0 + NOT DISPATCHED 一行,3 测试,本地 83 过),run_demo.py 压着等 tzb-b9 紫/红跑完再推(同字节纪律);LC_ALL=C 数清单的教训再记一次 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/SHA256SUMS.txt
- `ruling.relabel_3_04s` — 裁定(03:5x):'确定性各段合计 3.04 s'是错标签(含 S1/S2 模型时间,确定性 S3+S5 仅 0.045 s)→改标签不改数,四处同改(NUMBERS-v2、deck v2.1、报告、fig-latency);题注口径:需访问端点的只有 S0/S1/可选 S4,S2 本地视觉模型 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260904.md
- `v21-followups-prepared` — 备好未应用:launch_resident 切默认 v21 的 diff 与 README §Claim boundary 两版草稿(A 两轮过/B 任一轮未动),均在 coordinator-notes/,等 tzb-b9 结果与放行。 · ref: /Users/gl/tzb-lanes/coordinator-notes/README-claim-boundary-v21-draft-20260905.md
- `executor.v21_default_diff_and_readme_draft` — demo lane 备好未应用:launch_resident 切默认 v21 的 diff(含注释同改)与 README §Claim boundary 草稿 A/B 两版(不写 any object;拒绝不花 nonce 单说;身份看 v21_target_resolution),等 tzb-b9 紫/红结果后我裁 · ref: /Users/gl/tzb-lanes/coordinator-notes/README-claim-boundary-v21-draft-20260905.md
- `live_window.v21_switch_plan` — 卡点30 已修(谓词等待;本次 extra_updates=0 不证治好);v21 已同步 labserver;裁:loop lane 切执行器,先等 15 min v21+视口叠层变体,否则纯 v21 跑一轮后切回视口 v3;chxy 侧由 tzb-b9 跑 · ref: /Users/gl/tzb-lanes/live-loop-v1/receipts/live-window-kadian30-physics-tensor-wait-v1.json
- `labonly-viewport-v21` — v21 lab-only 视口变体已建并双侧落盘(lane + labserver /var/tmp/labonly-viewport-v1),v21->变体纯增 171 行 0 删 0 改,插入行与 v17 变体逐行相同;不进包 · ref: /Users/gl/tzb-lanes/agent-demo-v3-isaac-rgbd/labonly-viewport-v1/vnext_dispatch_executor_v21_viewport_labonly.py
- `deck-v2.1-label-fix` — deck v2.1 出:P9 确定性各段 3.04s 改除S4外各段(确定性S3+S5=0.045s);v2 未动;守卫 PASS;pdf 晚 33s;字体纯 HiraginoSansGB · ref: /Users/gl/tzb-deliverables/ppt-v1/CHANGES-v2.md
- `forbidden-v2-变更14` — FORBIDDEN_V2 加 确定性各段;deck v3 守卫与报告筛查都 import 这张表,一处加三处生效;反向验证旧v2 FAIL、v2.1 PASS、确定性生成 未误伤 · ref: /Users/gl/tzb-deliverables/ppt-v1/check_deck_v2.py
- `报告图筛查缺口` — 报告 :399/:517 与 figs/fig-latency.png 图内标题仍含旧句(归 tzb-66);8张SVG无来源行;make_figs.py 只在 tzb-lanes 不在交付目录 · ref: /Users/gl/tzb-deliverables/report-v1/figs/FIGURE-DATA-SOURCES.md
- `live_window.v21_viewport_variant_ready` — v21 视口叠层变体就位(04:0x):vnext_dispatch_executor_v21_viewport_labonly.py(b1e2a856…,v21 上纯增 171 行)+ v6 启动器(EXECUTOR 可覆盖);双侧 sha 一致,不进包;loop lane 可切并跑紫色直播轮 · ref: /var/tmp/labonly-viewport-v1/
- `deck.v2_1_relabel` — deck v2.1 出(03:58):只改 P9 那句→'除 S4 外各段 3.04 s(确定性 S3+S5 0.045 s)';守卫 0 项、pdf 晚于 pptx、无字体回退;NUMBERS-v2:236 已改;禁写表加'确定性各段';PENDING-v2.1.md 待办未随此版(归 v3) · ref: /Users/gl/tzb-deliverables/ppt-v1/xh-202607-deck-v2.1.pdf
- `report.zh_v2_draft2` — 报告 05:04 版为定稿候选(tzb-56 05:0x):占位 0、筛查 PASS、term-check 干净;18:00 前不再改除非新证据;17:05 起改版本行为定稿并写 report.zh_v1_final · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.pdf
- `report.draft2_delivered` — 报告第二稿图文版(tzb-66 04:09):53 页 A4,24 图 22 表带题注与出处行,含 R1/R2/训练包指针/自家超参/3.04 s 改标签;待补三处(S0 验收、紫红两轮、附录 B 末行);审查 06:30 核图表出处;数字源加训练包 README · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.pdf
- `v21-rerun-purple-red` — v21 复跑:紫 cyl_05 六原语全成、落在登记格内、感知误差2.57mm;红 cyl_01 目标解析成功但 attach 断言失败(抓取几何未验证) · ref: cold-install-chxy-v1/receipts/v21-rerun/
- `finding-32-ping-reports-intent` — 卡点32改判[中]:v21 运行时自述身份落后——nonce消费记录写v15(:1224)、PING写v17(:2216)、产物名result-v17、grasp_gate.why是常量(:1806);行为无误,溯源字符串错 · ref: cold-install-chxy-v1/receipts/v21-rerun/
- `report.draft2_screen` — 第二稿复筛 PASS(0 项):772 数命中 763/归一 9/未命中 0;NUMBERS-v2 A6 加 2.966 rad/0.53 mm/0.655 m 行(出处 Z);Y 补登记;v3 简报补充 §6 转 PENDING-v2.1 五项 · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- `milestone.v21_purple_end_to_end` — 里程碑(04:1x):纯中文非青指令首次走到臂——v21 紫色 chxy 六原语落格(感知误差 2.57mm)与 labserver 直播轮 0.749 m 入箱(grasp_gate 过,邻件<6µm);红色 attach 断言失败;卡点 32 PING 自报 v17;切默认待青色 v21 轮 · ref: /Users/gl/tzb-lanes/live-loop-v1/receipts/live-window-v21-purple-round-dispatched-v1.json
- `报告二稿复筛PASS` — 第二稿 772数 命中763/归一9/未命中0,禁写0,图表节0;加 training-README 为源;拒收 logs(grad_norm 2.9667 撞 2.966 rad);NUMBERS-v2 加出处 Z · ref: /Users/gl/tzb-deliverables/report-v1/tools/screen_report.py
- `deck_v3.draft_exported` — deck v3 初稿已导出:ppt-master Default 路径,20 页原生 PPTX+PDF 落 ppt-v3/xh-202607-deck-v3.pptx/.pdf;final gate 0 错;守卫顶层 PASS 但导出器把根组打成 GROUP,守卫不递归,已用同表递归扫 PASS · ref: /Users/gl/tzb-deliverables/ppt-v3/xh-202607-deck-v3.pptx
- `deck_v3.draft_reported` — deck v3 初稿路径 04:2x 报 tzb-56(sid 5ae1238c):ppt-v3/xh-202607-deck-v3.pptx/.pdf + CHANGES-v3.md;待裁:演示机 Win/Mac、守卫组递归(tzb-55)、S0/三指令/v21 更新 12:00 前 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md
- `deck_v3.rulings_0420` — tzb-56 三裁(04:2x):演示机 Mac、PDF 为主交付;讲者备注开,16:00 前填,内容只出 CLAIMS/NUMBERS/报告;加宽文本框接受。S0 三槽/紫青入箱/红 attach 失败 12:00 前给定稿口径再改 P02/P04/P07 · ref: /Users/gl/tzb-lanes/deck-v3/LANE_NOTES.md
- `deck.v3_draft1` — deck v3 初稿(tzb-63 04:15,ppt-master):20 页 PPTX+PDF,标题按变更 14,P09 已改标签;守卫因 GROUP 空转→tzb-55 加组递归,递归扫 484 框 0 项;裁:Mac 字体、PDF 主件、备注开、加宽框接受 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md
- `live_window.v21_cyan_regression` — labserver 青色回归轮 v21 通过(04:16):cylinder_06 六原语,位移 0.659 m 入格(离底 30.2 mm),grasp_gate 过,邻件<4.1µm;与紫色轮并列两点非成功率;现场保持不动 · ref: /Users/gl/tzb-lanes/live-loop-v1/receipts/live-window-v21-cyan-regression-round-v1.json
- `v21-red-failure-detail` — 红轮=干净带码停止非traceback:停在step3 attach断言后(step556),手指停39mm未合到33mm柱体;邻件cylinder_02位移27.2mm;花1枚nonce,ordinal_consumed=0 · ref: cold-install-chxy-v1/receipts/v21-rerun/red/round-001/result-v17.json
- `report.f1_fixed_values_sent` — 报告 F1 已修(04:19,出处行统一附录 C 前缀 D/L/P/T,复筛 PASS 775/766/0);已把 S0 三句验收与 v21 紫/青/红字段值发 tzb-66 填 3.2.1 与表 15;默认执行器句留待裁定 · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.pdf
- `kadian-32-ping-identity` — 卡点32已修:builder 加第8处替换,PING 自报 vnext_dispatch_executor_v21 + v21_baseline;结果文件名 result-v17.json 按 v15 parity 不改;新 v21 sha 8b2d45fd 前缀;85 tests pass · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/SHA256SUMS-v21.txt
- `red-attach-root-cause` — 红轮 cylinder_01 失败根因=接近位姿够不到(基座半径 0.232m,首次伺服残差 331mm/28度)+伺服无发散保护把目标甩到 1.07m 外;非抓取力学、非邻件碰撞、非目标解析 · ref: /Users/gl/tzb-lanes/cold-install-chxy-v1/receipts/v21-rerun/red/round-001/result-v17.json
- `report.acceptance_filled` — 报告 04:22:3.2.1 三例与表 15 后 v21 段已填(引 L 直播回执),6.2 加第 7/8 条,附录 B 移位,摘要加句;筛查 803/793/未命中 1(2.57 mm 待 tzb-b9 v21 复跑回执入源);默认执行器句【待裁】 · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.pdf
- `deck_v3.notes_enabled` — deck v3 讲者备注已启用并导出(20/20 页);守卫递归生效禁写 0 项;几何断言 32 项均为页脚/条组误报待 tzb-55 改;产物 pptx 8f69e890 pdf ba3770ff;待 12:00 定稿口径改 P02/P04/P07 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md
- `defect.red_unreachable_servo_divergence` — 红色失败根因:cylinder_01 r_xy 0.232 m 近基座不可达,伺服无发散保护→失控挥动、撞动邻件 27 mm、attach 断言;紫/青 r≥0.35 成。裁:伺服发散保护现在做(v21 builder),可达带作启发不写常量,推荐词改青/品红/蓝,红/绿/橙标近基座区 · ref: /Users/gl/tzb-lanes/cold-install-chxy-v1/receipts/v21-rerun/
- `deck.v3_rebuilt_0425` — deck v3 重建(04:25):讲者备注 20/20、Mac 字体 PDF 主件、加宽框保留;守卫组递归生效禁写 0,几何断言 32 项误报待 tzb-55 修;P02/P04/P07 等定稿口径 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md
- `v3守卫空转已修` — check_deck_v3 曾对全组化导出件 0页0字仍报PASS;加组递归(484框/12920字)+紧缩空间匹配(88框含\x0b)+备注扫描(20页)+几何按几何内容认条+空转自检;v2 未动 · ref: /Users/gl/tzb-deliverables/ppt-v3/tools/check_deck_v3.py
- `guard.v3_recursion_and_idle_check` — v3 守卫修好(tzb-55 04:2x):组递归后扫 484 框/12920 字 PASS 0 项;原守卫对导出件空转(0 框仍 PASS)→加'0 文本框即 FAIL'空转自检;备注纳入禁写;三条负例验;批报告筛查与 v2.1 守卫同补空转自检 · ref: /Users/gl/tzb-deliverables/ppt-v3/tools/check_deck_v3.py
- `deck_v3.guard_pass` — check_deck_v3(tzb-55 修正版:组递归+几何+备注)对 deck v3 pptx 8f69e890 复核 PASS 0 项:484 框/12920 字,几何 20 页全认出,备注 20 页 8088 字 0 项;CHANGES-v3 已更新;待 12:00 口径改 P02/P04/P07 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md
- `v21-cyan-no-regression` — v21 青色轮与 v17 基线逐项对齐:六原语全成、落格内,各项差1e-7~1e-5(释放点偏移毫米级);判据成立=v21在青色上不退步(一轮对一轮) · ref: cold-install-chxy-v1/receipts/v21-rerun/cyan/
- `v21-red-rootcause-corrected` — 红轮根因更正(demo lane 提出,我逐项复核对上):手停在离柱290mm、伺服把残差当标定偏置固定3次不判收敛(0.331→0.515→0.325);判别量=离基座水平半径,红0.232失败/紫0.354青0.416成功 · ref: cold-install-chxy-v1/receipts/v21-rerun/red/round-001/result-v17.json
- `acceptance.v21_three_rounds_chxy` — chxy v21 三轮:青色与 v17 逐项对齐(差≤1e-5)不退步;紫色六原语落格;红色干净带码停止(exit 0)但撞邻件 27 mm(近基座不可达+伺服不判收敛);ordinal 全 0;报告 1654 行入包;卡点 32 升中 · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260904/chxy-cold-install/rounds/v21-rerun-20260905/
- `ruling-v21-default-switch` — 裁定(tzb-56, 2026-09-05):默认执行器切v21的条件=demo lane伺服发散保护落地后,我再跑红/紫/青三轮全符合预期(红期望HALTED_APPROACH_DID_NOT_CONVERGE干净停、邻件不动),跑完报它切
- `ruling-finding-32-fix-shape` — 裁定(tzb-56, 2026-09-05):卡点32升中采纳;修法=v21信封消费记录新增consumed_by_executor_identity=v21(不动consumed_by老字段保parity),grasp_gate.why常量改为按本轮事实生成或删掉;归demo lane
- `sidecar-8571-keep` — 8571 基座侧车 judge-locany-base 保持运行(裁定 tzb-56 2026-09-05 再确认一次);给用户实时窗口用,不撤
- `guard.idle_checks_added` — tzb-55:v2/v2.1 守卫与报告筛查各加空转自检(只数页面字、备注不算;图体按解析张数判),自检本身经负例验;报告新稿未命中 2.57 mm→裁 NUMBERS-v2 加 v21 三轮行(出处包内 v21-rerun-20260905) · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- `三工具空转自检` — v2守卫(只数页面字,备注不算)+报告筛查(空稿/空源/有图标记却零图体)各加空转自检,均负例验过;第一版两条自检自己是空转的,已修 · ref: /Users/gl/tzb-deliverables/report-v1/tools/screen_report.py
- `report.v2_screen_pass_0431` — 报告 04:31 重建:2.57 mm 带包内路径与字段,复筛 807 数命中 798/归一 9/未命中 0,禁写 0 PASS;红色轮细节已发作者;仅剩默认执行器一句待裁(等发散保护三轮复跑) · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.pdf
- `servo-divergence-guard` — 伺服发散保护已落 v21(builder 第9-14处):首次迭代跟踪误差>50mm 或迭代间增大即停 HALTED_APPROACH_DID_NOT_CONVERGE,不施修正/不下发/不闭合;新 v21 sha 03ef4cea;94 tests · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/SHA256SUMS-v21.txt
- `v21-receipt-identity-and-gate-wording` — v21 新增 envelope_consumption.consumed_by_executor_identity(consume 是 spliced 段不可改,故加在调用点;磁盘 nonce 文件仍只有 v15);grasp_gate.why 改为本轮实测
- `v21三轮入NUMBERS-Z2` — NUMBERS-v2 加 Z2 节(v21 紫/青/红三轮,报告用未上deck,label自述不计入冻结campaign);口述三处出入按回执改:3.5867→3.5868、98.28是伺服首拍非对齐项、红色attach断言失败且撞邻件27.22mm非干净停止 · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- `executor.v21_guard_landed` — v21 发散保护版落地(04:3x,sha 03ef4cea,tests 94):跟踪误差判据(首迭代>50mm 或增大即停,不施修正不闭合);回执加 consumed_by_executor_identity;grasp_gate.why 按本轮生成;SUMS 补 v21 行;三轮开跑 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/PROVENANCE-v21.md
- `v21-default-switch-prep` — 默认切 v21 的两件已备好未应用:launch_resident diff(重生成,dry-run 通过;旧版注释写红轮完成验收=错,已改)与 README Claim boundary A 版;等 tzb-56 一句"切" · ref: /Users/gl/tzb-lanes/coordinator-notes/README-claim-boundary-v21-draft-20260905.md
- `柱基座距离推导已独立复算` — 六个柱到基座距离由 red/round-001 的 arm_base_pose_world(-0.35,0)+object_truth_before+neighbours_before 重算,与 tzb-66 附录E.1 逐位一致;坐标与两种取整写法入 NUMBERS-v2 Z2;未把报告附录列为源(自证) · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- `report.numbers_all_sourced` — 报告数字侧全通(tzb-55 04:4x):855 数命中 846/归一 9/未命中 0;基座距离五数由回执字段重算入 NUMBERS-v2 Z2(不以报告附录自证,判断对);deck v2.1/v3 PASS;仅剩默认执行器三处占位待裁 · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- `v21-guard-3rounds-accept` — v21发散保护版三轮验收通过:红HALTED_APPROACH_DID_NOT_CONVERGE干净停(cylinder_02位移27.2mm→21nm)、紫青六原语全成落格内;nonce13→16每轮1枚,ordinal全0 · ref: cold-install-chxy-v1/receipts/v21-guard/
- `finding-33-halted-assertion-true` — 卡点33[低]:已halt轮的steps[2].assertion三格算true(gripper_blocked_on_object等,因手指停开爪25mm、间距50mm恰在[15,60]带内);held=false正确,按那三格筛已抓成轮会误纳 · ref: cold-install-chxy-v1/receipts/v21-guard/red/round-001/result-v17.json
- `nonce-ledger-identity-boundary` — 审计口径:磁盘nonce账目文件仍只有consumed_by=v15,真执行器身份只在回执的consumed_by_executor_identity;因consume是spliced gate segment、改它会让已记录digest变假
- `cyan-residual-round-variation` — 青轮1.6mm残差差已定位为取帧感知差、非发散保护:两轮感知中心相差1.663mm、残差相差1.625mm几乎相等;原保留意见撤销,不需多跑轮 · ref: cold-install-chxy-v1/receipts/v21-guard/cyan/
- `ruling.default_executor_v21` — 裁定(04:4x,05:2x 更正数字):默认执行器切 v21(03ef4cea 发散保护版)——三轮:红干净停止、邻件最差 1.06 µm(cylinder_03);紫/青六原语落格(紫躺倒);v17 随包可选;正式条目见 ruling.default_executor_v21_20260905 · ref: /Users/gl/tzb-lanes/coordinator-notes/v21-executor-change-list-20260905.md
- `launch-resident-in-two-manifests` — launch_resident.sh 的 digest 117d27f1 同时列在 SHA256SUMS.txt:22 与 SHA256SUMS-v21.txt:5;改默认执行器必须同时重算两份,否则 5/5 与 15/15 校验与 smoke 07 会失效
- `ruling-default-switched-to-v21` — 裁定(tzb-56, 2026-09-05):默认切 v21;demo lane 同步切默认 diff 后我跑一轮确认(不设 EXECUTOR、评委原样命令),核身份与 v21_target_resolution;卡点33交demo lane
- `pkg.v21_default_applied_mac` — Mac 权威拷贝(05:04):launch_resident 默认已是 v21(:62),tests 94 过,resident SUMS 15/15、v21 SUMS 5/5;干跑 tarball 867 文件/240MB/CLEAN(ADDR+MODE 双检);等 tzb-b9 默认路径确认轮后切终包 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/launch_resident.sh
- `ruling.default_executor_v21_20260905` — 裁定(tzb-fe/tzb-56,2026-09-05 05:0x):评审复现包默认执行器 v21(目标取自请求+消费凭证前检查+接近段发散保护),v17 随包 EXECUTOR=v17;依据 v21-guard 三轮;报告 5.1/6.2/3.5.2/附录B 已按原句落 · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260904/chxy-cold-install/rounds/v21-guard-20260905/
- `report.v21_default_filled` — 报告 05:04:默认执行器 v21 句已填,待裁/待补=0,筛查 869/860/未命中 0 PASS;偏离接受(附录 B 左列 v21 默认已实现,右列近基座柱抓取未解决);直播横幅与 live-demo.md 推荐词同步改 · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.pdf
- `v21-default-switched` — 默认已切 v21(diff 已应用,日期 2026-09-05);两份 manifest 重算并双侧验(主表15/15、v21表5/5);run_demo 卡点31 已同步 chxy;卡点33 记 open-questions 24 不改字节 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/SHA256SUMS-v21.txt
- `deck_v3.final_wording_applied` — deck v3 按 tzb-56 04:5x 口径改 P02/P04/P07+备注并重建,守卫 PASS 0。三处口述与 NUMBERS-v2 Z2 出入按账本写(红色 attach 失败非干净停止;邻件 27.22 mm;0.749/0.659 m 无出处未上页),已报 tzb-56 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md
- `deck_v3.ruling_z3_pending` — tzb-56 裁:deck v3 三处按账本写法保留;Z2 红轮作修复前对照;待 tzb-55 录 NUMBERS-v2 Z3 行(v21-guard 最终字节 03ef4cea 三轮)后改 P07(必要时 P04)再重建守卫回 sha;0.749/0.659 m 不上页 · ref: /Users/gl/tzb-lanes/deck-v3/LANE_NOTES.md
- `purple-lands-lying-down` — 紫色是躺着落进格子的(落地后倾角89.99°),青色直立(0.002°),四轮复现;离格底5.2vs30.2mm是姿态差非深度差。放进格子≠直立地放进格子 · ref: cold-install-chxy-v1/cold-install-report-v1.md
- `finding-33-disposition` — 卡点33记入 docs/open-questions.md 第24条、故意不改字节:改它要重建v21,而三件事刚在03ef4cea上验完,为可读性换未验收字节不划算
- `red-worst-neighbour-shift` — 红轮邻件最差位移是cylinder_03的1.063µm(文档用最差值);cylinder_02 27.2mm→21nm是单根对照非全场最差
- `vnext.v21_default_applied` — 05:1x demo lane 默认执行器已切 v21(launch_resident 3b9a9649,双表重算,chxy 同步 15/15+5/5 OK);卡点33→OQ24 不改字节;guard 视口叠层 3bd3f6e3 落 labserver 未覆盖运行份 · ref: /Users/gl/tzb-lanes/coordinator-notes/README-claim-boundary-v21-draft-20260905.md
- `vnext.v21_guard_red_neighbour_correction` — 更正:v21-guard 红轮邻件位移最差 1.06 µm(cylinder_03),21 nm 仅 cylinder_02;README/CLAIMS15/checklist 已改;报告 L502/L701 与 deck 待改;紫柱落格但躺倒 89.999° 如实写 · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260904/chxy-cold-install/rounds/v21-guard-20260905/red/round-001/result-v17.json
- `live_window.guard_overlay_restarted` — 05:11 loop lane 计划内重起:guard 叠层 3bd3f6e3 运行,step3 pose 未变,青轮完成 0.659 m 与切前逐位同;labserver pkg-next v21 同步到 03ef4cea;live_round.sh exit=2 为信息性管道 pipefail,已裁修 · ref: /Users/gl/tzb-lanes/coordinator-notes/delivery-checklist-20260904.md
- `report.final_candidate_review` — 05:1x 审稿人核 05:04 版:阻断 G1(21 nm 单件值当全体,L502×2/L701)、G2(青回归轮 4.109 µm 写成 <4.1);建议 G3/G4/G5;五条全转 tzb-66,改完自查定稿不再过审 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-report-final-candidate.md
- `readme-claim-boundary-v21-merged` — README §Claim boundary 已合入 v21 A 版口径(新 sha 405eec74);同时修 ground-truth 那条的 default v17→v21、重写 §Verification 那句过期 Net;negative-results 加紫柱躺倒一行;pkg 与 pkg-next 双份同步 · ref: /Users/gl/tzb-deliverables/judge-package-v1/README.md
- `report.zh_v1_final` — 技术报告定稿 05:31:md 4c38f395 / pdf 46873d50,54 页,三处30.2mm措辞已与deck同口径,筛查 PASS;此后不再动 · ref: /Users/gl/tzb-lanes/report-zh-v1/LANE-NOTES.md
- `review.index` — 审查线全部记录索引:/Users/gl/tzb-lanes/review-zh-v1/INDEX.md(63 行,含活项 U1–U6 与终包开箱清单 next-cut-checklist.md);历史 review.* 条目在 state/v2/archive/ 退役文件 · ref: /Users/gl/tzb-lanes/review-zh-v1/INDEX.md
- `state.compaction_20260905` — 05:3x 语义压缩:gen1906 全量快照归档 state/v2/archive/M2C_STATE-archive-20260905T0519-gen1906.md(sha bda9221bfb10f6a0…),退役条目按小节存 state/v2/archive/M2C_STATE-retired-20260905T0519-gen1906.md;退役≠完成,journal 未动

- `state.compaction_result_20260905` — 压缩后活跃文件约 84 KB(前 426 KB,4.9×);§1 198 条/§2 4/§3 40/§4 7;退役 1161 条在 archive/ retired 文件;演练与脚本在 coordinator-notes/state-compaction-dryrun-20260905.md · ref: /Users/gl/tzb-lanes/coordinator-notes/state-compaction-dryrun-20260905.md

- `Z3-v21最终字节三轮` — NUMBERS-v2:444-475 加 Z3(v21 03ef4cea 三轮)与 Z4(v17 五轮 3.5867);紫柱落位躺倒 89.999 已自算复现两轮;25mm离格底=姿态非深度(两轮独立指向 Ø10.40x60.40);425 行加轮次身份注记 · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md

- `default-executor-now-v21-confirmed` — 默认已切v21并确认(不设EXECUTOR跑评委原样命令):五处证据齐,含v17不写的v21_target_resolution块;身份sha 03ef4cea · ref: cold-install-chxy-v1/receipts/v21-default-confirm/

- `deck_v3.z3_applied` — deck v3 P07/P04 已按 NUMBERS-v2 Z3 行更新(Z3 三轮 + Z2 修复前对照),守卫 PASS 0;pptx 53485e68 pdf 41fa4dd5;细节见 CHANGES-v3.md · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `deck_v3.review_tzb55_pass` — tzb-55 独立复核 deck v3 pptx 53485e68:守卫 PASS 0(507 框),Z3/Z2 写法与位移零命中逐条核过,无待改;记录见 CHANGES-v3.md 外部复核节 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `delivery.report_and_deck_final_20260905` — 05:22 报告二次定稿 md 8b47e64e/pdf 713c028b(54 页,筛查 PASS);05:3x deck v3 pptx 53485e68/pdf 41fa4dd5 按 NUMBERS-v2 Z3 行改 P07/P04,审稿人核中;NUMBERS-v2 Z3 行 460–467/475 · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md

- `oq25-and-landing-height-wording` — OQ25 紫柱躺倒已记(三轮两台机,故意不修);negative-results 与 README 的"离池底"改为"声明平面偏移"(该平面比真实支承面高 9.65mm);使用说明 U4 补 ISAAC_IMAGE 注释 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/open-questions.md

- `pkg.v21_default_confirm_in_package` — tzb-b9 默认路径确认轮(exit 0/321 s,identity 03ef4cea,v21_target_resolution 块)脱敏入包 rounds/v21-default-confirm-20260905(13 文件)+ README 342 行 + 报告副本;等拒绝轮后重出终包 · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260904/chxy-cold-install/rounds/v21-default-confirm-20260905

- `correction.cell_floor_offset_not_radius` — 更正(05:4x):5.198/30.2 mm 是相对声明格底平面的偏移非净空(真实支承面低 9.65 mm),柱 Ø≈29.7×79.7;'感知半径高估 2.8 倍'撤;README 6efb1d39→bcdd7c8c;报告/deck/NUMBERS 466 改中 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/open-questions.md

- `report.zh_v1_final_20260905` — 05:27 报告三次定稿 md 4e34de23/pdf 120a36ca(54 页):2.8 倍句删、离格底改为相对声明平面偏移口径,grep 半径|半高|5.198|14.645 0 命中;筛查 PASS 0 项;此后只等用户 · ref: /Users/gl/tzb-deliverables/report-v1/技术报告-XH-202607.md

- `466行更正撤高估` — NUMBERS-v2:467 撤回'感知半径高估2.8倍'(我把 height_above_cell_floor 当成从真实支承面量起);柱实为 Ø29.7x79.7,感知低估直径0.41/0.47mm;5.198/30.2 是相对声明平面0.47的偏移、真实支承面低9.65mm · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md

- `cardpoint31-refusal-round-verified` — 卡点31复验通过:S0拒绝 exit 0、stderr有NOT DISPATCHED、[ok]非[FAIL]、nonce 17→17未耗;outcome 无 refused_at 键,S0事实由 disposition 与 s3 承载 · ref: cold-install-chxy-v1/receipts/s0-refusal-exit0/

- `finding-34-double-not-dispatched` — 卡点34[低]:一次S0拒绝在stderr打两行NOT DISPATCHED,两码不一致(run_demo.py:1285带S0_前缀/:1293不带),首行悬空--;归demo lane · ref: cold-install-chxy-v1/receipts/s0-refusal-exit0/57-s0-refusal.err

- `review.deck-v3` — deck v3(53485e68/41fa4dd5)核:1条阻断D1(P02三句验收括注把拒绝原因写成'最左边不是注册颜色词',回执是REFUSE_UNREGISTERED_DESTINATION);P07四行表12个数对上Z3、禁写0项、备注齐;重建后按新sha再核 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-deck-v3.md

- `deck_v3.candidate_164d1b38` — deck v3 定稿候选重建:P07 三处改'相对声明格底平面 +N mm'(tzb-56 裁,账本 466 行同步),守卫 PASS 0;pptx 164d1b38 pdf 7cee4b64;sha 已发 tzb-56/tzb-95(审稿) · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `delivery.deck_v3_rebuilt_20260905` — 05:3x deck v3 重建 pptx 164d1b38/pdf 7cee4b64(P07 三处改'相对声明格底平面 +x mm',守卫 PASS),已交 tzb-95 核;NUMBERS-v2 461–467 改口(466 柱 Ø≈29.7×79.7、467 感知直径低估≈1.5%) · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `pkg.readme_cell_floor_wording` — README §Verification 三处'x mm above the cell floor'改为 height_above_cell_floor_m 偏移口径(非净空),README bcdd7c8c→cad2b5cf;待拒绝轮 r2 行加入后再让 demo lane 同步 chxy · ref: /Users/gl/tzb-deliverables/judge-package-v1/README.md

- `kadian-34-single-not-dispatched` — 卡点34已修:S0 拒绝时跳过 executor 那条 NOT DISPATCHED、detail 空不打悬空 --;两处共用同一 refused_at_s0 判据;run_demo 73af14fe;95 tests;新测试对旧码复现两行 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/run_demo.py

- `deck_v3.review_d1_fixed` — tzb-95 审稿 D1(P02 拒绝原因括注)+2 非阻断已改,deck v3 重建 pptx fd607d1d pdf 487ba5d5,守卫 PASS 0,待 tzb-95 按新 sha 复核;记录见 CHANGES-v3.md 审稿复核节 · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `pkg.kadian34_fixed` — 卡点 34(S0 拒绝 stderr 两行 NOT DISPATCHED 码不同)已修:run_demo.py 73af14fe 两处按 refused_at_s0 互斥,新测试 test_s0_refusal_exit_code_v1(95 passed),三处同步;tzb-b9 重跑拒绝轮 r2 中 · ref: /Users/gl/tzb-deliverables/judge-package-v1/tests/test_s0_refusal_exit_code_v1.py

- `deck_v3.candidate_1bb70b2d` — deck v3 候选重建(审稿追加 17 nm 整轮口径):pptx 1bb70b2d pdf b0c0c73c,守卫 PASS 0;待 tzb-95 按新 sha 复核;记录见 CHANGES-v3.md · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `review.deck-v3-pass` — deck v3 重建版 pptx 1bb70b2d/pdf b0c0c73c 复核 PASS:D1括注、P07边界句、离格底三处改口、整轮口径全部落实;22个Z3数字仍在;禁写+旧措辞页面与备注0命中;µm渲染渲图核过 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-deck-v3.md

- `deck_v3.review_pass` — tzb-95 复核 deck v3 PASS 无阻断:pptx 1bb70b2d pdf b0c0c73c;整改三条落实,禁写 0 命中,Z3 22 数在;候选定稿,deck-v3 无待办;记录 CHANGES-v3.md + review-zh-v1/findings-deck-v3.md · ref: /Users/gl/tzb-deliverables/ppt-v3/CHANGES-v3.md

- `delivery.deck_v3_final_20260905` — 05:5x deck v3 定稿 pptx 1bb70b2d/pdf b0c0c73c:审稿人 PASS(D1 P02 拒绝原因、离格底三处偏移口径、17 nm 整轮、禁写 0 命中);报告终稿 md 4c38f395/pdf 46873d50 审稿人做双向措辞搜索中 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-deck-v3.md

- `cardpoint34-r2-verified` — 卡点34复跑通过:stderr NOT DISPATCHED 恰一行、无悬空--、S0_前缀码不再上终端、exit0、nonce17→17;回执字段未动(executor.reason_code仍S0_前缀) · ref: cold-install-chxy-v1/receipts/s0-refusal-exit0-r2/

- `refused-at-lives-in-trace` — 更正:refused_at="S0" 在 trace.json 里(不在 outcome.json);refusal trace 14键含 localizer_called=false、model_calls=0。终包写按 refused_at 可查成立,须指向 trace · ref: cold-install-chxy-v1/receipts/s0-refusal-exit0-r2/run-20260904T213643/trace.json

- `refusal-trace-not-run-identifying` — 两轮拒绝的 trace.json 逐字节相同(22414c8e):不含时间戳或run id,单看一份无法判断出自哪轮,需靠 outcome.trace_path 或所在 run 目录定位

- `review.report-final-4c38f395` — 报告终稿 md 4c38f395/pdf 46873d50 双向核查 PASS:旧措辞8项 md/pdf 各0命中,新措辞相对声明格底平面5处、净空2处 md/pdf 计数一致,抽样数字未动;仅1条非阻断建议(未给声明平面 0.47 m 与 9.65 mm 差值) · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-report-final-4c38f395.md

- `milestone.final_tarball_20260905` — 终包 judge-package-v1-20260905-202015.tar.gz(1018 文件/240MB/三门 CLEAN,sha 67752d9a…):默认 v24+七轮回执、A–E 修复、新入口文档、SHA256SUMS-v24、OQ26–36;055803 入 superseded/;提交目录①⑥已换 · ref: /Users/gl/tzb-deliverables/judge-package-v1-20260905-202015.tar.gz.sha256

- `delivery.morning_status_20260905` — 05:4x 交付态:终包 054100;报告 4c38f395/46873d50;deck v3 1bb70b2d/b0c0c73c;训练包 a5ba5091;GPT 终审包 0245;直播现场保持;待用户:LoRA 默认/模型名/push/GPT 结论/录视频/权重许可 · ref: /Users/gl/tzb-lanes/coordinator-notes/morning-report-20260905.md

- `review.tarball_054100` — 终包 054100 开箱 PASS 无阻断:sha 三方一致 892 文件;11 份 SHA256SUMS 摘要不符 0;地址/密钥/运行态/模式位全清;U1-U6 全修;5 条非阻断(判委错字7处、拒绝轮无五面板未进判委文档、目标柱15/17nm两口径、launcher旧摘要无说明、README 9 处包外引用旧有) · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-054100.md

- `review.tarball_055444` — 终包 055444 差量核 PASS:sha 三方一致 892 文件,逐文件比对确认只差 README+使用说明两个文件且摘要相符;N1-N5 五处全落实;新引入 2 处小错(v20 回执位置写成 evidence/、§Claim boundary 空指)非阻断 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-055444-delta.md

- `review.tarball_055803` — 终包 055803 PASS:sha 三方一致 892 文件,对 055444 仅 README 变(ad32241d)且只有两个变更块;D1 路径改对、D2 改为直引 launch_resident.sh:62 原文(与包内脚本逐字相符、分支正确)、句点已补;回归全 0 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-055444-delta.md

- `delivery.final_baseline_20260905` — 06:0x 交付基准定稿:终包 055803(e4108fbb…)审稿 PASS;报告 4c38f395/46873d50;deck v3 1bb70b2d/b0c0c73c;训练包 a5ba5091;GPT 终审包 0245;各线待命,直播现场保持;此后只按用户指令改 · ref: /Users/gl/tzb-lanes/coordinator-notes/morning-report-20260905.md

- `audit.triage_20260905` — 13:4x(非 06:1x)两份审查分级:今日可修 A(HALT→DISPATCHED 误报/UNKNOWN)B(S0 结构+operation 门)C(目的地未注册放行)D(无颜色词目标晚断)E(文档口径);F1/exit1 已过时;架构级写 OQ;用户裁定全修 · ref: /Users/gl/tzb-lanes/coordinator-notes/audit-triage-20260905.md

- `delivery.gpt_fix_round_20260905` — 13:5x 用户:本地 GPT 代理按工作单就地修 judge-package-v1(先 cp -a 备份,只改点名文件,写 GPT-FIX-REPORT.md,不建包不同步);demo lane 停写 A–D 转审/同步/测试;tzb-b9 四轮已备;报告/PPT 口径由 tzb-66/63 后改 · ref: /Users/gl/tzb-deliverables/review-v3/fix-round-20260905/FIX-LIST-20260905.md

- `audit-fix-A-out-of-package` — A(HALT/UNKNOWN 回执真实化)已在包外副本做完并 99 passed,补丁与测试留 /Users/gl/tzb-lanes/audit-fixes-20260905/;B-D 按裁定停手交 GPT 就地改;包对 SOURCE-SHA256SUMS 270/270 OK · ref: /Users/gl/tzb-lanes/audit-fixes-20260905/A-patch-isaac-receipt-truth.diff

- `delivery.gpt_changes_landed_20260905` — 18:2x 本地 GPT 四轮改包完成:A–E 修复、新 v22/v23/v24 执行器+launcher v2–4、capture v2/v3、run_chain_v6、颜色 v2/v3、许可门 v2、冷启动入口(start.sh 默认 v24);我实跑 975 passed/1 skipped;审与复验中 · ref: /Users/gl/tzb-deliverables/review-v3/fix-round-20260905/COLDSTART-FIX-REPORT.md

- `deck_v3.evening_prepared` — deck v3 晚间版改动已备未建(tzb-56 指示等复验过):P08 S0 四码行/P07 帧龄句/P02 回执句已入脚本;待裁执行器版本与三句逐句原码;清单 tzb-lanes/deck-v3/PREPARED-20260905-evening.md · ref: /Users/gl/tzb-lanes/deck-v3/PREPARED-20260905-evening.md

- `Z5预留-v24六轮` — Z5 预留给 v24 六轮评委路径(今晚 tzb-b9 跑,tzb-56 脱敏复制到 judge-package-v1/evidence/verification-20260905/chxy-judge-path-v24/);Z4 已是 v17 五轮基线勿重用;记录要点见 ref · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md

- `review.gptfix-round-20260905` — GPT 四轮就地修复复核:三条只读命令实测退出码 0/0/0(许可门反例4个全被拦、正对照仍到边界);冻结面零改动、README Verification 字节未变、isaac_primitives 只改回执口径未碰运动;紫色靠 magenta 兼容词、冷启青轮两次超期、grant 仍 V1 无签名均属实 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md

- `review.gptfix_round_verdict` — 18:4x 审稿人核 GPT 四轮:三条只读复核退出 0/0/0;冻结面零改动(892→948 文件,新增 56/改 11/删 0);工程门可信;存疑=v24 仅青一轮、证据在包外、紫靠 magenta 兼容族、许可 V1 无签名;活包多 output/smoke-all 目录待清 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md

- `gpt-fix-round-audit` — GPT 四轮改动审完:冻结面0改动、manifest 15/15+5/5、§Verification未动、A实现更严可接受;必修4条(v24自称v23、身份文件改名致smoke07失效、v22-24未登记、3.9下收集失败);默认已是无验收的v24 · ref: /Users/gl/tzb-deliverables/review-v3/fix-round-20260905/GPT-FIX-REPORT.md

- `ruling.default_executor_v24_pending` — 裁定(18:5x):默认暂留 v24,以修后字节六轮(青冷/紫/红/三句)为准,任一不过退回 v21;demo lane 先修 4 处(v24 自报 v23、identity-v1 文件、SHA256SUMS-v24+PROVENANCE-v24、3.9 收集错)再同步 chxy pkg-v24 · ref: /Users/gl/tzb-lanes/coordinator-notes/delivery-checklist-20260904.md

- `review.v24-bytes-never-run` — 包内 v24 字节 c83c0770 未被任何 GPU 轮跑过:冷启动最终轮跑的是 1f20b122(COLDSTART 表 19 行仅此行不符),两份只差 12 行=回执身份串 v23→v24;故该轮回执写 consumed_by_executor_identity=v23。解法:tzb-b9 六轮从当前活包部署 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md

- `stopline.v24_bytes_freeze` — 硬线(19:1x):tzb-b9 六轮必须跑随包字节的 v24(demo lane 修身份串后的版本),六轮到切包之间 v24 一字节不改;README 只引这六轮,GPT 的 v24 青冷轮注明跑的是订正前字节 1f20b122(回执自报 v23) · ref: /Users/gl/tzb-lanes/coordinator-notes/README-v24-drafts-20260905.md

- `pkg.docs_new_entry_20260905` — 18:5x tzb-76 三份文档改到新默认入口:使用说明 61c1cbb2、live-demo 3b6fcae8(颜色规则正文改 v3:14.9°/NO_MATCHING_BOX/purple-magenta 族内歧义拒)、file-manifest 6c5c27aa(54+2 新文件);tzb-76 待命 · ref: /Users/gl/tzb-deliverables/judge-package-v1/docs/live-demo.md

- `incident.v24_coldstart_identity_refusal` — 19:5x 第二次拒因=demo lane 改超时时把三行并进 except 致探针 NameError(自造回归;核错了工件:本机已被 GPT 19:34 修好 06551e98);批只推该文件重跑青冷;18:40 原问题仍未解;决策顺延至 20:15 · ref: /Users/gl/tzb-deliverables/review-v3/fix-round-20260905/DEMO-LANE-IDENTITY-FIX-20260905.md

- `v24-prelim-cyan-refused` — v24预跑青冷启动 exit=1/345s:RESIDENT_IDENTITY_MISMATCH→COLDSTART_REFUSED,nonce未耗,30s期限未被考验;驻留本身READY(140.66s)四检查全过 · ref: cold-install-chxy-v1/receipts/v24-judge-path/prelim-round/

- `v24-identity-mismatch-swallows-cause` — 线索:该拒因由 resident_identity_v4.py:324 的宽except(7类异常)打印且故意不回显异常(防凭据泄露),真正失败的子项从stderr不可知;建议加异常类型或阶段标记

- `v24-freshness-v2-two-ages` — v24 CaptureFreshnessV2 同记 age_at_chain_entry(7.15s)与检查时 age_s(12.24s)+绝对期限+剩余预算+时钟回拨容差;审查E项"帧龄=链内耗时"在v24已不成立

- `v24-identity-writes-v23` — 我独立确认:v24 result 的 consumed_by_executor_identity 写成 v23;result 文件仍名 result-v17.json,schema AgentDemoV3DispatchResultV15(卡点32族在v24仍在)

- `v24-output-moved-aside` — pkg-v24/output 已移到 pkg-v24-output-prelim-20260905T184646(root属主目录fx删不掉、sudo被排除),留档45文件在 receipts/v24-judge-path/prelim-round/leftover;pkg/output 完好516文件17 nonce

- `delivery.submission_dir_20260905` — 19:0x 建提交目录 tzb-deliverables/submission-XH-202607-20260905/(Q9 六项:①055803 候选 ②训练包 ③环境指引 ④视频待录 ⑤报告 ⑥使用说明)+ 提交说明.md;①/⑥ 版本随 20:00 决定同步 · ref: /Users/gl/tzb-deliverables/submission-XH-202607-20260905/提交说明.md

- `v24-four-fixes-synced` — 四项裁定修正落盘并同步 chxy:pkg-v24:v24 身份串、身份文件双名+smoke07、根级 SHA256SUMS-v24(18/18)+PROVENANCE-v24、三测试 3.10 版本门;3.9 collect 931/0 error,3.12 全量 976 passed · ref: tzb-deliverables/review-v3/fix-round-20260905/DEMO-LANE-IDENTITY-FIX-20260905.md

- `identity-mismatch-diagnostic` — resident_identity_v4 现自报 stage/error/reason(白名单回显探针原文);超时 30/5s 放宽到 180/20s;字节被换与容器重启已排除;根因未定,候选见交接文件;已停止对活包写入 · ref: tzb-deliverables/review-v3/fix-round-20260905/DEMO-LANE-IDENTITY-FIX-20260905.md

- `identity-probe-regression-mine` — 我同步的 resident_identity_v4(8970d5f9)三行缩进进 except 致 ping 未赋值 NameError,tzb-b9 青轮639s失败源此;本机 06551e98 已由GPT修好仅此三行;chxy 待推;SHA256SUMS-v24 过期 · ref: tzb-deliverables/review-v3/fix-round-20260905/DEMO-LANE-IDENTITY-FIX-20260905.md

- `v24-cyan-cold-pass` — v24修复探针NameError后青轮冷启动通过:exit=0/469s、六原语全成、落格内、ordinal=0、nonce0→1;consumed_by_executor_identity已正确写v24 · ref: cold-install-chxy-v1/receipts/v24-judge-path/cyan-pass/

- `v24-probe-nameerror-rootcause` — 19:24轮639s超时根因:RUNTIME_PROBE 三行被缩进进except且在raise之后,ping永不赋值→第61行NameError→通用identity mismatch;18:40:32那次是打补丁前的原始文件,仍未解释 · ref: cold-install-chxy-v1/receipts/v24-judge-path/cyan-attempt2/

- `ruling.default_executor_v24` — 裁定(20:0x):v24 定为默认——评委原样青冷启动在随包字节通过(exit 0/469 s/6/6,identity v24,nonce 0→1,outcome 622de2bd);余五轮暖态接跑;v24/identity_v4/coldstart/launcher v4 字节冻结;18:40 拒绝→OQ36 · ref: /Users/gl/tzb-lanes/cold-install-chxy-v1/receipts/v24-judge-path/cyan-pass

- `v24-default-cyan-round1-pass` — v24 定为默认:青冷启 exit0/469s/6原语/nonce 0->1/ordinal 0/落格内/离格底与v17逐位相同/identity v24;manifest 远近端各18/18;18:40那次未解释拒绝入 open-questions 36 · ref: tzb-deliverables/judge-package-v1/PROVENANCE-v24.md

- `review.v24-round1-precheck` — v24 round1 预核:运行字节=随包字节 c83c0770,SHA256SUMS-v24 18/18 OK,身份写 v24、6 原语、age 11.92/30。976vs975 差在 COLOUR_V3_REPLAY_EVIDENCE 门控的单条测试;3vs4 是表只列出结果目录 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md

- `pkg.v24_provenance_manifest` — 20:1x demo lane 收尾:SHA256SUMS-v24 18/18(459bf9e4)、PROVENANCE-v24 加六轮节(第 1 轮已填)、OQ36 写 18:40 未解释拒绝,均同步 chxy;probe-stderr 不进包 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/PROVENANCE-v24.md

- `review.v24_round1_precheck` — 20:1x 审稿人:975/1 vs 976/0 差在 COLOUR_V3_REPLAY_EVIDENCE 门控的单条测试;coldstart 第 4 目录=未起服务的准备目录;round1 预核硬线成立(轮内 v24 c83c0770=包内自算);scene_instance_id=null 勿写同实例 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md

- `evidence.v24_judge_path_rounds` — 20:3x v24 七轮齐:R1 青冷 6/6、R2 紫暖 6/6、R3 红 S0 拒(蓝箱子未登记)、R4–R6 三句拒绝、R7 红 HALTED/2 上层如实(A 验过);全部入包 verification-20260905/;README v24 段+验证行 eff5f49b · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260905/chxy-judge-path-v24

- `v24-judge-path-seven-rounds` — 七轮入 PROVENANCE(cab91620):R1青冷启过/R2紫过/R3-R6四种S0拒因各一行NOT DISPATCHED/R7补跑红柱HALTED 2of6验回执真值;活包写入到此为止 · ref: tzb-deliverables/judge-package-v1/PROVENANCE-v24.md

- `v24-judge-path-rounds` — v24 评委路径七轮验收完成:1冷启+2暖态派发成功,3-6 各按码 S0 拒绝,7 红轮 HALTED/2条。nonce 0→3,ordinal 全 0,冻结字节未变。 · ref: receipts/v24-judge-path/

- `audit-fixes-abcd` — 修法 A/B/C/D 全验过:A 需补跑第7轮(第3轮被 C 的 S0 拒绝挡住、未进执行器);D 实际在 S0 就拒,比裁定表更早,收紧偏离。 · ref: cold-install-report-v1.md v24 七轮节

- `height-above-floor-not-clearance` — height_above_cell_floor_m 相对声明面 bin_floor_top_z_m=0.47,该面高于真实停放面 9.652mm,不是净空;报告五处措辞已改。 · ref: demo lane 更正 2026-09-05

- `z5-v24-seven-rounds-entered` — Z5 已入 NUMBERS-v2:v24 评委路径七轮(R1青/R2紫/R7红HALTED + R3-R6 四条S0拒绝)。文件 sha 8273ec20 · ref: ppt-v1/NUMBERS-v2.md:480-557(节)、48(图例)、470-476(陷阱表扩到五条)

- `v24-prereg-box-rule-mislabel` — 七轮 preregistration.box_selection_rule 仍写冻结首框规则、active_chain_sources 漏 v3 模块;trace/outcome/result 三处才是 V3。R2 紫轮尤其要紧 · ref: run_demo.py:40,214,223 / run_chain_v6.py:41;v3 模块 88c380cd 全树 0 命中

- `z5r1-bitwise-reproduces-z4` — Z5 R1 与 Z4 五轮全精度逐位相同(误差量/感知/真值/落位/倾角/位移):是可复现性,禁止与 Z4 一起平均当六个独立样本 · ref: NUMBERS-v2.md:550;采集帧 02fb2792 在 v17 那批 0 命中

- `evidence.z5_ledger_20260905` — 20:3x Z5 入 NUMBERS-v2 480–557:引包内副本 sha;R1=Z4 逐位同(跨版本复现非样本);紫靠 magenta 族;R7 抓取布尔/−17 mm 不可引;预注册选框规则字面量陈旧+v3 sha 未入回执→OQ37(demo lane 写,随最后重切) · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md

- `z5-rulings-20260905` — tzb-56 裁 2026-09-05:账本引包内脱敏副本 sha;06551e98=identity 脚本;R7 两时长并列注口径;暖态按令牌+consumed_at 连续不写同 boot · ref: NUMBERS-v2.md:480-560(Z5),文件 sha 自算 f8b41478

- `oq37-prereg-box-rule-deferred` — 预注册 box_selection_rule 字面量陈旧 + v3 模块 sha 未入回执:tzb-56 裁今晚不改字节,demo lane 记 OQ37 随最后一次文档重切入包 · ref: run_demo.py:40,214,223;引选框规则只引 trace/outcome/result

- `review.tarball_202015` — 终包 202015(v24 默认)PASS 无阻断:sha 三方一致 1018 文件、删除 0、冻结面仅 REDACTION 追加;13 份清单摘要不符 0;v24 c83c0770 三方一致;七轮逐字段与 README 442 行相符;3 条非阻断=两脚本无执行位+两处行号指路失效 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-202015.md

- `oq37-written-pending-sync` — open-questions 第37条(选框规则名/预注册漏钉v3、halt布尔与-17.14mm非感知误差、拒绝文案中英不一且英文在冻结vendor、自检负例那行)已写 1e391d09,未同步;OQ24 close_report→command_report 已改正保留;等审稿人结论后由 tzb-56 叫同步并重切 · ref: tzb-deliverables/judge-package-v1/docs/open-questions.md

- `review.tarball_202942` — 终包 202942 差量核 PASS:仅 4 文档变内容+2 权限位(字节未变,v24 清单仍 18/18)+3 个新增 recovery 文件(无人引用、file-manifest 未收录);两条非阻断=审计文档句子改断、OQ24 的 close_report 只改一处 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-202015.md

## 2. 归属与 lane
- `lane.m2c_exec` — **M2C 执行会话**:successor implementation candidate,commit-free,于全新隔离 clone(Q′ 模式);已登记候选路径内自由编辑(R132.41)。ETA(8/29 午报):交包 8/30 01:00–07:00;早沿(≤03:00)可达截止,晚沿不可达。
- `lane.tzb_fe` — **tzb-fe(协调)**:实现审查+七段治理批量激活(预告:批一 = R′ stage adoption→successor prereg→materialize→bootstrap;批二 = legacy P″ prefix adoption→recovery03→combined preflight;每步仍各自 pre-capture/记录/fail-closed,激活与 closeout 各批一次)。
- `lane.qwen_brain` — qwen-brain/S5 lane → `QWEN_BRAIN_STATE.md`(owner sessionId 72ad7a26)。
- `ownership.registry_pointer` — 角色→sessionId 以 state/v2/WRITERS.json 为准;历史 lane.* 条目归档 state/v2/archive/M2C_STATE-retired-20260905T0519-gen1906.md

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
- `todo.weight_redistribution_license` — 9/3后网盘路径开通前必查:Qwen3.8-27B权重的再分发许可。放网盘给评委=再分发,与本地使用不同。S5在MolmoAct2上发现同类问题(repo Apache但权重card无license字段)
- `todo.object_table_benchmark_owner` — 待用户定:对象表基准(那台秤)无owner。下周期整个感知选型计划压在它上面。PR-Bench可能补上一部分
- `task.q9_deliverables_20260905` — Q9 分工:②训练包 tzb-76 10:00;⑤技术报告 tzb-55 初稿12:00/定稿18:00;①⑥使用说明 demo lane 08:00;④视频用户录;审查逐件点名;终包 20:00 重出 · ref: /Users/gl/tzb-lanes/coordinator-notes/delivery-checklist-20260904.md
- `task.deck_v3_pptmaster` — 用户(02:28):1 小时后让 tzb-63(sid f4a8adc2,角色 deck-v3)用 ppt-master 重做 PPT;简报 coordinator-notes/brief-deck-v3-pptmaster-20260905.md;03:28 定时发令;初稿 09:00/定稿 16:00 · ref: /Users/gl/tzb-lanes/coordinator-notes/brief-deck-v3-pptmaster-20260905.md
- `task.gpt_final_review_bundle` — 用户(02:3x):派空闲会话打'不脱敏'的项目+状态审核包给 GPT Web Pro 终审(保留内网地址与路径;仍排除 .env/密钥/权重/图像/npy/output);交 tzb-76;用户去睡,夜间按 overnight 边界自主推进 · ref: /Users/gl/tzb-deliverables/review-v3/
- `todo.archived_pre_delivery` — 8/29–9/4 的 42 条待办(建包/治理/S5/agent-demo v1–v3/HUD/v4 切换/RECOVER 等)已被 9/4–9/5 交付取代,未逐条核实完成,原文在 state/v2/archive/M2C_STATE-retired-20260905T0519-gen1906.md §4

- `live-loop-open-items-ptr` — 直播窗口 lane 三项未结(不追):①我方驱动 exit0 端到端待下一轮真实运行②卡点30 未对失败样本证伪③发散保护行为未触发。紫柱倾倒已裁今日不修→OQ25(demo lane 写)

- `audit-4-rounds-prepared-not-run` — 审查四轮已备未跑(判据+判别项经 tzb-56 认可);用户已裁定全修,demo lane 做 A-D、GPT 也出补丁,合并同步 chxy 后 tzb-56 叫我跑,预计下午晚些 · ref: cold-install-chxy-v1/audit-4-criteria.md

## 5. Recent tail(journal 缓存,非权威)
- 2026-09-05T20:04+0800 [FACT/facts] <m2c-exec> `v24-default-cyan-round1-pass` — v24 定为默认:青冷启 exit0/469s/6原语/nonce 0->1/ordinal 0/落格内/离格底与v17逐位相同/identity v24;manifest 远近端各18/18;18:40那次未解释拒绝入 open-questions 36 · ref: tzb-deliverables/judge-package-v1/PROVENANCE-v24.md
- 2026-09-05T20:05+0800 [FACT/facts] <review-zh-v1> `review.v24-round1-precheck` — v24 round1 预核:运行字节=随包字节 c83c0770,SHA256SUMS-v24 18/18 OK,身份写 v24、6 原语、age 11.92/30。976vs975 差在 COLOUR_V3_REPLAY_EVIDENCE 门控的单条测试;3vs4 是表只列出结果目录 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md
- 2026-09-05T20:06+0800 [FACT/facts] <tzb-fe> `pkg.v24_provenance_manifest` — 20:1x demo lane 收尾:SHA256SUMS-v24 18/18(459bf9e4)、PROVENANCE-v24 加六轮节(第 1 轮已填)、OQ36 写 18:40 未解释拒绝,均同步 chxy;probe-stderr 不进包 · ref: /Users/gl/tzb-deliverables/judge-package-v1/agent/executor/resident/PROVENANCE-v24.md
- 2026-09-05T20:06+0800 [FACT/facts] <tzb-fe> `review.v24_round1_precheck` — 20:1x 审稿人:975/1 vs 976/0 差在 COLOUR_V3_REPLAY_EVIDENCE 门控的单条测试;coldstart 第 4 目录=未起服务的准备目录;round1 预核硬线成立(轮内 v24 c83c0770=包内自算);scene_instance_id=null 勿写同实例 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-gptfix-round-20260905.md
- 2026-09-05T20:12+0800 [FACT/facts] <tzb-fe> `evidence.v24_judge_path_rounds` — 20:2x v24 六轮:R1 青冷 6/6;R2 紫暖 6/6;R3 红被 S0 拒(蓝箱子未登记)→A 未验;R4 INSPECT 拒;R5 绿箱拒无蓝箱绑定;R6 最左 S0 即拒;批 R7 红+蓝色料箱验 A · ref: /Users/gl/tzb-lanes/cold-install-chxy-v1/receipts/v24-judge-path
- 2026-09-05T20:16+0800 [FACT/facts] <tzb-fe> `evidence.v24_judge_path_rounds` — 20:3x v24 七轮齐:R1 青冷 6/6、R2 紫暖 6/6、R3 红 S0 拒(蓝箱子未登记)、R4–R6 三句拒绝、R7 红 HALTED/2 上层如实(A 验过);全部入包 verification-20260905/;README v24 段+验证行 eff5f49b · ref: /Users/gl/tzb-deliverables/judge-package-v1/evidence/verification-20260905/chxy-judge-path-v24
- 2026-09-05T20:19+0800 [FACT/facts] <m2c-exec> `v24-judge-path-seven-rounds` — 七轮入 PROVENANCE(cab91620):R1青冷启过/R2紫过/R3-R6四种S0拒因各一行NOT DISPATCHED/R7补跑红柱HALTED 2of6验回执真值;活包写入到此为止 · ref: tzb-deliverables/judge-package-v1/PROVENANCE-v24.md
- 2026-09-05T20:19+0800 [FACT/facts] <exec-no-truth-v1> `v24-judge-path-rounds` — v24 评委路径七轮验收完成:1冷启+2暖态派发成功,3-6 各按码 S0 拒绝,7 红轮 HALTED/2条。nonce 0→3,ordinal 全 0,冻结字节未变。 · ref: receipts/v24-judge-path/
- 2026-09-05T20:19+0800 [FACT/facts] <exec-no-truth-v1> `audit-fixes-abcd` — 修法 A/B/C/D 全验过:A 需补跑第7轮(第3轮被 C 的 S0 拒绝挡住、未进执行器);D 实际在 S0 就拒,比裁定表更早,收紧偏离。 · ref: cold-install-report-v1.md v24 七轮节
- 2026-09-05T20:19+0800 [FACT/facts] <exec-no-truth-v1> `height-above-floor-not-clearance` — height_above_cell_floor_m 相对声明面 bin_floor_top_z_m=0.47,该面高于真实停放面 9.652mm,不是净空;报告五处措辞已改。 · ref: demo lane 更正 2026-09-05
- 2026-09-05T20:21+0800 [FACT/facts] <tzb-fe> `milestone.final_tarball_20260905` — 终包 judge-package-v1-20260905-202015.tar.gz(1018 文件/240MB/三门 CLEAN,sha 67752d9a…):默认 v24+七轮回执、A–E 修复、新入口文档、SHA256SUMS-v24、OQ26–36;055803 入 superseded/;提交目录①⑥已换 · ref: /Users/gl/tzb-deliverables/judge-package-v1-20260905-202015.tar.gz.sha256
- 2026-09-05T20:22+0800 [FACT/facts] <deck-v2> `z5-v24-seven-rounds-entered` — Z5 已入 NUMBERS-v2:v24 评委路径七轮(R1青/R2紫/R7红HALTED + R3-R6 四条S0拒绝)。文件 sha 8273ec20 · ref: ppt-v1/NUMBERS-v2.md:480-557(节)、48(图例)、470-476(陷阱表扩到五条)
- 2026-09-05T20:22+0800 [FACT/facts] <deck-v2> `v24-prereg-box-rule-mislabel` — 七轮 preregistration.box_selection_rule 仍写冻结首框规则、active_chain_sources 漏 v3 模块;trace/outcome/result 三处才是 V3。R2 紫轮尤其要紧 · ref: run_demo.py:40,214,223 / run_chain_v6.py:41;v3 模块 88c380cd 全树 0 命中
- 2026-09-05T20:22+0800 [FACT/facts] <deck-v2> `z5r1-bitwise-reproduces-z4` — Z5 R1 与 Z4 五轮全精度逐位相同(误差量/感知/真值/落位/倾角/位移):是可复现性,禁止与 Z4 一起平均当六个独立样本 · ref: NUMBERS-v2.md:550;采集帧 02fb2792 在 v17 那批 0 命中
- 2026-09-05T20:25+0800 [FACT/facts] <tzb-fe> `evidence.z5_ledger_20260905` — 20:3x Z5 入 NUMBERS-v2 480–557:引包内副本 sha;R1=Z4 逐位同(跨版本复现非样本);紫靠 magenta 族;R7 抓取布尔/−17 mm 不可引;预注册选框规则字面量陈旧+v3 sha 未入回执→OQ37(demo lane 写,随最后重切) · ref: /Users/gl/tzb-deliverables/ppt-v1/NUMBERS-v2.md
- 2026-09-05T20:25+0800 [FACT/facts] <deck-v2> `z5-rulings-20260905` — tzb-56 裁 2026-09-05:账本引包内脱敏副本 sha;06551e98=identity 脚本;R7 两时长并列注口径;暖态按令牌+consumed_at 连续不写同 boot · ref: NUMBERS-v2.md:480-560(Z5),文件 sha 自算 f8b41478
- 2026-09-05T20:25+0800 [FACT/facts] <deck-v2> `oq37-prereg-box-rule-deferred` — 预注册 box_selection_rule 字面量陈旧 + v3 模块 sha 未入回执:tzb-56 裁今晚不改字节,demo lane 记 OQ37 随最后一次文档重切入包 · ref: run_demo.py:40,214,223;引选框规则只引 trace/outcome/result
- 2026-09-05T20:28+0800 [FACT/facts] <review-zh-v1> `review.tarball_202015` — 终包 202015(v24 默认)PASS 无阻断:sha 三方一致 1018 文件、删除 0、冻结面仅 REDACTION 追加;13 份清单摘要不符 0;v24 c83c0770 三方一致;七轮逐字段与 README 442 行相符;3 条非阻断=两脚本无执行位+两处行号指路失效 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-202015.md
- 2026-09-05T20:28+0800 [FACT/facts] <m2c-exec> `oq37-written-pending-sync` — open-questions 第37条(选框规则名/预注册漏钉v3、halt布尔与-17.14mm非感知误差、拒绝文案中英不一且英文在冻结vendor、自检负例那行)已写 1e391d09,未同步;OQ24 close_report→command_report 已改正保留;等审稿人结论后由 tzb-56 叫同步并重切 · ref: tzb-deliverables/judge-package-v1/docs/open-questions.md
- 2026-09-05T20:33+0800 [FACT/facts] <review-zh-v1> `review.tarball_202942` — 终包 202942 差量核 PASS:仅 4 文档变内容+2 权限位(字节未变,v24 清单仍 18/18)+3 个新增 recovery 文件(无人引用、file-manifest 未收录);两条非阻断=审计文档句子改断、OQ24 的 close_report 只改一处 · ref: /Users/gl/tzb-lanes/review-zh-v1/findings-tarball-202015.md
