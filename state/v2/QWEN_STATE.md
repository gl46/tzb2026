<!-- GENERATED — 禁止直接 Edit/Write。唯一写入口: tools/statectl.py -->
<!-- statectl protocol=2 stream=QWEN generation=138 updated=2026-09-02T16:59+0800 -->
<!-- 自 QWEN_BRAIN_STATE.md 迁移 sha=4515ae2214ce5395db64b887c82246c41ed191ea48433f897f6e90ebede0a9cb -->

# QWEN 权威状态(活跃快照,协议 v2)

> **只有 §1-§4 具规范效力。**§5 是 journal 缓存;仅存在于 journal 的内容**不是约束、不是待办、不是当前真相**。完整历史见 state/journal/QWEN/。
> 唯一写入口 tools/statectl.py。写者角色 ['qwen-brain-owner'](角色串,重启不变;绑定见 state/v2/WRITERS.json)。`--session` 自声明未验证,属写入纪律层,**非安全属性**。
> 导入的历史记录 grandfathered,不受 1024B/160 字符上限约束(tzb-fe 裁定 2026-08-30 §3)。

## 1. 当前事实
- `archive.path` — 只读归档：`/Users/gl/tzb/QWEN_BRAIN_STATE_ARCHIVE-20260830.md`
- `archive.identity` — 归档最终 identity：size=`214651` B；SHA-256=`942c0f9cc69240287ec32768e21e463a4cfa4461db3687f7f68041c76596bd94`；mode=`0444`。
- `archive.prefix_equal` — 归档 bytes `[0,213814)` 与迁移前 active state 逐字节一致；该前缀 size=`213814` B，SHA-256=`33ef7bbb39580589c2183d7adb82372e234fba119479a9c62cce7345a4742b45`。
- `archive.read_rule` — 归档末尾追加 migration record 后冻结；需要旧裁定时只 grep/读取相关节，不得整读。
- `lane.clone` — lane clone：`/Users/gl/projects/xh-202607-qwen-brain`。冻结 baseline commit=`d2aae551e2710d25d28f64866e31dc6dd93a1da2`；当前 Node2 successor repo文件未获 commit 授权，不 commit、不 bundle、不 push。
- `auth.user_training` — 用户直接训练授权：`批准 S5 smoke32 + 两 epoch LoRA 训练,冻结配置 r8/a16/lr2e-5,chxy A100`。用户直接宿主修正：`你去Node 2上干怎么样？Node 2是空的。两台机子100G内网互联。` 宿主修正只改变 host/path/environment identity，不改变科学配置或授权序列。
- `config.node2_strict` — strict Node2配置：`/Users/gl/projects/xh-202607-qwen-brain/configs/qwen_brain/s5-training-node2-v1.json`；trainer：`scripts/qwen_brain/train_s5_lora_node2_v1.py`；authorization：`QWEN_BRAIN_S5_TRAINING_AUTHORIZATION_NODE2.md`；migration ADR：`ADR-0037-qwen-commander-s5-node2-training-migration.md`。
- `env.node2` — Node2环境：`/home/gl/xh-202607-qwen-s5/.venv-s5`；identity report=`/home/gl/xh-202607-qwen-s5/preflight/environment-identity-node2-v1.json`，SHA-256=`28a6726f72f9a26405549a9ae667190bf0c14ba10374d5a8ebb3d75e6af6dc6a`。
- `pkg.immutable` — immutable package：`/home/gl/xh-202607-qwen-s5/training-package-node2-v1`；manifest=`training-package-manifest-node2-v1.json`，SHA-256=`666ecd839eff934ee4e2e82739bdad89f5cfdf1aade60487f0ea5db75bb0fb16`；完整树16 regular files、0444/0555、零symlink/pyc/unmanifested。
- `snapshot.model` — exact snapshot：`/home/gl/qwen38-27b-mtp/Qwen3.8-27B`；32-file semantic digest=`187d7847a7de61b1d26c0f1a09354d2b880d499bee23fd208543fa15b77b52da`；ignored real top-level dirs=`[".cache"]`；吻合，禁止重传模型。
- `data.train_reconstructed` — reconstructed TRAIN：428 rows / 374 sources；JSONL SHA-256=`3d3675e919babaf2e967c5162a84e699c0f2986f7b7557a466d3c8d1fa0945a8`。Node2 TRAIN-only root=`/home/gl/xh-202607-qwen-s5/training-input-v2`；374 images / 33,592,890 B；manifest SHA-256=`44824a1a3ba77928672c7bded67dad699f7435717850226dfc35fc3417bc13f2`；image-set SHA-256=`55a420e3ad0b4d0574037b89a7572b3666ab6bde2d5058c55a1df46ca9eb0db7`。绝不向trainer传`dataset-v4.jsonl`，只用重建TRAIN materialization。
- `freeze.scientific` — scientific freeze：r8/a16/dropout0.05/LR2e-5/AdamW/constant+5 warmup/clip1.0/microbatch1/accum16/seed20260827/external selected-logit FP32 CE；208 targets、416 FP32 tensors、19,791,872 trainable params；two-epoch=856 microsteps/54 updates，末组8样本/divisor8。
- `smoke32.pass` — Node2 smoke32唯一执行已PASS全部12 promotion gates：report=`/home/gl/xh-202607-qwen-s5/smoke32-report-node2-v1.json`，SHA-256=`6ac796cc3e8aa56801dcb0cc6ba8bf35f9756f7cc2c1922c96ce46964a11c301`；32 microsteps/2 updates。
- `probe.promoted` — Compatibility pointer only: use probe.s5_base_00bc9a0705e1b2873937.smoke32 and .two_epoch; no unqualified measurement lives here. · ref: /home/gl/xh-202607-qwen-s5/smoke32-report-node2-v1.json
- `adapter.smoke` — smoke adapter=`/home/gl/xh-202607-qwen-s5/adapter-smoke32-node2-v1`；PREPARED SHA=`f6e9f274fc08e9c95711e1716c4531d26c6ceb0dbdc58019430413a2b1a4e3c3`；publication SHA=`b7ad8ebc4134f63165bad8b27be674b552c1bb83a39522ac6b9fb22be55f5d1c`；post-smoke package rehash SHA=`ba55f773c97a78cd09ae6a77cd9edf1c96fdca4278ff9f79b0d64dff0cb733e4`。stderr/receipts/adapter tree已独立reconcile全PASS。
- `gpu.evidence` — immediate final-run GPU evidence=`/home/gl/xh-202607-qwen-s5/gpu-process-evidence-two-epoch-node2-v1.json`，SHA-256=`13f804eae821b6974bf84b707839f3245e20e01221e78575fe1e37030a24c013`；free=74,171MiB；external PID3239742/python/6,960MiB，仅记录、不kill/停止。
- `final.not_started` — Pristine Node2 two-epoch PASS: 856 microsteps/54 updates, 12/12 gates; report SHA 1513f6de…; fixed-probe CE 0.3207→0.1787. · ref: /home/gl/xh-202607-qwen-s5/two-epoch-report-node2-v1.json

- `p1.semantic_closed` — P1 terminal: active V2 contracts, strict fail-closed dispatch gate, and semantic client/CLI verified; 134 PASS plus lint/compile/schema/diff gates. · ref: src/xh_agent/qwen_brain/semantic_dispatch_gate_v2.py

- `adapter.final` — Final adapter=adapter-two-epoch-node2-v1; tree SHA 8a09f56a…; PREPARED 3e85204b…; publication 137d65bf…. · ref: /home/gl/xh-202607-qwen-s5/adapter-two-epoch-node2-v1

- `eval.adapter_binding` — Paired DEV/TEST/BLIND TRAINED_LORA arm binds final adapter tree 8a09f56a…, not smoke; A2 result NO_BENEFIT_EVIDENCE. · ref: /home/gl/xh-202607-qwen-s5/icl-final-benefit-claim-v3.json

- `p2.semantic_closed` — P2 final: 48 cases; FAR/FRR 0; route 1; rules 26/38; fields 44/44; matcher witnesses 14; zero-dispatch 24/24. · ref: src/xh_agent/qwen_brain/semantic_contract_suite_v2.py

- `p2.validator` — Terminal SHA-256=f2cdf8b74cc7ea5c59a77088d3a539dcd6106f4e49d303daff1d6fecf746ad54; size=29309 B; clean re-review. · ref: src/xh_agent/qwen_brain/semantic_validator_v2.py

- `p2.suite` — P2 suite SHA-256=846d1753ae6b7051f9d76a0e66cc677104dcbf3bfc35661ebaebd2a8c5642f15; size=49647 B; clean review. · ref: src/xh_agent/qwen_brain/semantic_contract_suite_v2.py

- `p2.inventory` — P2 inventory SHA-256=358c73f947d6d0e8b6049657a62e9f66cdd07f7d83f75bb924caeaa00d0d5609; size=21349 B. · ref: configs/qwen_brain/semantic-contract-suite-v2.json

- `p2.cli` — P2 CLI SHA-256=fba6685148b50ec6166a3341bdc9287e8c81a4a738156809b547958cf136f5a3; size=2969 B. · ref: scripts/qwen_brain/evaluate_semantic_contract_suite_v2.py

- `p2.validator_tests` — Terminal SHA-256=a73c0542ef75036ecae6d19a582452911e6963e11d82537cd9418b6d2db8316a; size=39624 B; clean re-review. · ref: tests/unit/test_qwen_brain_semantic_validator_v2.py

- `p2.suite_tests` — P2 suite tests SHA-256=3b142cfdc60f3dbb40f19a39e095baeeace501638f4eda1bab83cb9f0dc93fe2; size=11674 B. · ref: tests/unit/test_qwen_brain_semantic_contract_suite_v2.py

- `p3.cancelled` — P3 cancelled for this round: privileged simulator truth cannot enter test-time policy input; no offline diagnostic or governed-path implementation. · ref: CODEX_GOAL_M2C_HEADROOM.md

- `p3.vnext_spec` — Corrected P3 design is vNext specification only: target-blind overlay, hard negatives, content-mask, UNRESOLVED, split metrics and sample counts. · ref: QWEN_BRAIN_P3_VNEXT_ORACLE_CANDIDATE_SPEC.md

- `adapter.identity_chain` — Common tree digest and production/loading chain verified; smoke and final are distinct, DEV/TEST/BLIND load final. · ref: /home/gl/xh-202607-qwen-s5/two-epoch-report-node2-v1.json

- `claim.resolver_trust` — tzb-fe: trust resolver boundary; manifest must disclose no independent payload-to-file-byte proof and forbid that overclaim. · ref: src/xh_agent/qwen_brain/claim_manifest_v1.py

- `claim.manifest_closed` — Task #45 closed: one claim, 11 pinned reports, final tree, paired matrices, resolver trust boundary; 32 tests and clean review. · ref: src/xh_agent/qwen_brain/claim_manifest_v1.py

- `claim.manifest_identities` — Terminal SHA: source a91c5d08…/23466B; config 41dcef86…/10903B; tests 221afe6c…/16052B. · ref: configs/qwen_brain/lora-no-benefit-v1.json

- `probe.s5_base_00bc9a0705e1b2873937.smoke32` — Smoke32 run: fixed probe CE 0.3206965923309326→0.3191450238227844; adapter-on/off max delta 9.021484375. · ref: /home/gl/xh-202607-qwen-s5/smoke32-report-node2-v1.json

- `probe.s5_base_00bc9a0705e1b2873937.two_epoch` — Two-epoch run: fixed probe CE 0.3206965923309326→0.1786690652370453; adapter-on/off max delta 15.140625. · ref: /home/gl/xh-202607-qwen-s5/two-epoch-report-node2-v1.json

- `eval.family_breakdown` — BASE/LoRA逐族一致；BLIND视觉0/12、恢复7/9、拒绝13/13、重定位11/11；TEST恢复6/9、拒绝3/3、重定位10/10。 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260831.md

- `p2.uncovered.boundary` — P2未触发但属既定边界: INVALID_SNAPSHOT_TIME/INTERVAL, NOT_YET_VALID, STALE, DECISION_MISMATCH, PHYSICAL_AUTOMATON。 · ref: src/xh_agent/qwen_brain/semantic_validator_v2.py

- `p2.uncovered.omissions` — P2冻结套件遗漏: UNKNOWN_TASK_TARGET/POSE, UNREGISTERED_TASK_DESTINATION, EXECUTION_RESOURCE_CONFLICT, RECOVERY_AUTOMATON, UNEXPECTED_CAPTURE。 · ref: src/xh_agent/qwen_brain/semantic_validator_v2.py

- `locateanything.license_terms` — NVIDIA License terms read/frozen; research/evaluation-only, redistribution/notice duties recorded; not a proceeding gate. · ref: chxy:/home/fx/locateanything-vp-v1/metadata/locateanything-3b-license-terms-v1.json

- `locateanything.data_download` — COCO train2017 and LVIS v1 train/val downloaded create-once; exact byte/SHA identities verified PASS. · ref: chxy:/home/fx/locateanything-vp-v1/receipts/download-coco-train2017-v3.json

- `locateanything.checkpoint_freeze` — Base checkpoint runtime closure frozen before baseline: HF immutable rev c32291ca; 21 required files; unsafe training_args.bin excluded. · ref: chxy:/home/fx/locateanything-vp-v1/metadata/locateanything-3b-checkpoint-freeze-v2.json

- `locateanything-v2-review2-accept-20260901` — Independent review ACCEPT: builder 40a17014/test 4c9cc07f; 16/16 pass; prereg/source binding and atomic no-replace cleared. V2 freeze is next. · ref: /home/fx/locateanything-vp-v1/source/pair_builder_v2_review2.py

- `locateanything-v2-freeze-wrapper-attempt1-halt-20260901` — Freeze wrapper halted before builder: noclobber rejected just-created empty log. RC=1; authority/lock/stage absent. Additive logs only. · ref: /home/fx/locateanything-vp-v1/logs/pair-authority-v2-freeze.rc

- `locateanything-v2-authority-freeze-attempt2-running-20260901` — V2 freeze attempt2 running on chxy: PID835181, exact reviewed builder 40a17014, freeze phase only. Authority/data absent at launch. · ref: /home/fx/locateanything-vp-v1/logs/pair-authority-v2-freeze-attempt2.log

- `locateanything-v2-review2-provenance-clarification-20260901` — Review2 ACCEPT source=a65fc20c91e3dc624 in-process task notification, not peer claude-77. Misrouted thank-you corrected; freeze authorization unchanged. · ref: /private/tmp/claude-501/-Users-gl-tzb/72ad7a26-9a33-4894-ba52-21a593ed7175/tasks/a65fc20c91e3dc624.output

- `locateanything-v2-in-process-reviewer-wording-20260901` — Supersedes review2 wording in generations100/103: IN_PROCESS_REVIEWER_TASK_ACCEPT, task a65fc20c91e3dc624; not external/third-party endorsement. · ref: /private/tmp/claude-501/-Users-gl-tzb/72ad7a26-9a33-4894-ba52-21a593ed7175/tasks/a65fc20c91e3dc624.output

- `locateanything-v2-authority-freeze-pass-20260901` — V2 freeze attempt2 RC0: atomic read-only authority published; split/plan/manifest present, locks absent, data-v2 absent. Audit gate now active. · ref: /home/fx/locateanything-vp-v1/metadata/pair-authority-v2

- `locateanything-v2-authority-audit-owner-20260901` — Own planned read-only audit files: /private/tmp/locateanything_vp_authority_audit_v2.py plus remote source/log/rc create-only paths. · ref: /home/fx/locateanything-vp-v1/source/pair_authority_audit_v2.py

- `locateanything-v2-authority-audit-running-20260901` — Standalone read-only audit 3b892fb1 running chxy PID887838; imports no builder code; exact split/top-N/geometry recomputation. data-v2 absent. · ref: /home/fx/locateanything-vp-v1/source/pair_authority_audit_v2.py

- `locateanything-v2-dataset-audit-owner-20260901` — Own planned post-materialization audit files only: local /private/tmp/locateanything_vp_dataset_audit_v2.py plus remote source/log/rc paths. · ref: /home/fx/locateanything-vp-v1/source/pair_dataset_audit_v2.py

- `locateanything-v2-authority-audit-pass-20260901` — Standalone audit 3b892fb1 RC0: exact split/top-N recomputation, 102k references, 353262 targets, 76249 COCO members; data-v2 absent. · ref: /home/fx/locateanything-vp-v1/logs/pair-authority-v2-audit.log

- `locateanything-v2-materialization-running-20260901` — V2 atomic materialization running chxy PID913970 with exact builder 40a17014. Authority audit RC0; data-v2 absent at launch. · ref: /home/fx/locateanything-vp-v1/logs/pair-materialization-v2.log

- `locateanything-v2-dataset-audit-review2-frozen-20260901` — Post-materialization audit hardened/frozen as c2fe3277: exact pair-plan order and split membership, plus all prior row/media/receipt checks; no builder import. · ref: /home/fx/locateanything-vp-v1/source/pair_dataset_audit_v2_review2.py

- `locateanything-v2-materialization-harness-detached-remote-alive-20260901` — Local launch task killed only its SSH; remote materializer PID913970 +16 workers still alive. Stage has 114228 files/10.8GB; final absent. Monitor rearmed. · ref: /home/fx/locateanything-vp-v1/logs/pair-materialization-v2.log

- `locateanything-v2-materialization-pass-20260901` — V2 materialization RC0: atomic read-only data-v2 published; 100k/2k rows, 57025 targets, 86104 crops, 143133 files; locks/stage absent. · ref: /home/fx/locateanything-vp-v1/data-v2/receipts/pair-construction-v2.json

- `locateanything-v2-dataset-audit-review2-fail-20260901` — Audit c2fe3277 RC1 from audit-only bug: expected authority omitted root; receipt correctly includes it. Dataset unchanged; additive correction next. · ref: /home/fx/locateanything-vp-v1/logs/pair-dataset-v2-audit-review2.log

- `locateanything-v2-dataset-audit-review3-running-20260901` — Corrected standalone dataset audit e144b346 running chxy PID977710. One-field expected-authority correction only; dataset remains immutable. · ref: /home/fx/locateanything-vp-v1/source/pair_dataset_audit_v2_review3.py

- `locateanything-v2-dataset-audit-review3-fail-20260901` — Audit e144b346 RC1: Pillow rejected crop PNG iCCP as too large; dataset unchanged. Diagnose media compatibility additively. · ref: /home/fx/locateanything-vp-v1/logs/pair-dataset-v2-audit-review3.log

- `locateanything-v2-png-compat-audit-owner-20260901` — Own additive read-only PNG compatibility audit source/log/rc review1 paths; V2 data remains immutable. · ref: /home/fx/locateanything-vp-v1/source/png_compat_audit_v2_review1.py

- `locateanything-v2-png-compat-audit-result-20260901` — Full 143129-media audit: 3 failures, all train crops from COCO 479400; held-out 0. Source JPEG carries 1.829MB ICC; target JPEG loads. · ref: /home/fx/locateanything-vp-v1/logs/png-compat-audit-v2-review1.log

- `locateanything-v2-train-only-exclusion-ruling-20260901` — tzb-fe ruling: few incompatibles all train => preregister exclusion and continue without rebuild; held-out exclusion would require refreeze. · ref: peer-msg:bca5c387-f61d-4674-8352-4ad4f4faec55

- `locateanything-v2-effective-train-owner-20260901` — Own additive effective-train builder/audit sources, data-v2-effective root, logs/rc only; frozen V2 stays untouched. · ref: /home/fx/locateanything-vp-v1/source/build_effective_train_v2.py

- `locateanything-v2-effective-train-frozen-20260901` — Additive effective training manifest frozen: 99997 rows, 3 explicit train exclusions; held-out 2000 unchanged/0 affected; V2 immutable. · ref: /home/fx/locateanything-vp-v1/data-v2-effective/receipts/train-media-exclusion-v2.json

- `locateanything-official-source-snapshot-owner-20260901` — Own additive exact Eagle commit snapshot root and freeze receipt/log/source under LocateAnything write root; damaged checkout untouched. · ref: /home/fx/locateanything-vp-v1/sources/Eagle-783f656d-snapshot-v1

- `locateanything-v2-effective-dataset-audit-pass-20260901` — Audit 3fafe75d RC0: effective train 99997 exact base subsequence, 199994 media opens/0 fail; held-out 2000 unchanged/0 affected. · ref: /home/fx/locateanything-vp-v1/logs/effective-dataset-v2-audit.log

- `locateanything-official-embodied-snapshot-frozen-20260901` — Exact official Embodied tree at Eagle 783f656d recovered additively: 132 tracked files, manifest bc0833e8, damaged checkout untouched. · ref: /home/fx/locateanything-vp-v1/sources/Eagle-Embodied-783f656d-snapshot-v1/SNAPSHOT_MANIFEST.json

- `locateanything.trainer_png_limit_override` — Trainer sets PNG MAX_TEXT_CHUNK=1GiB, so exact trainer should not reproduce default-Pillow 1.829MB iCCP failure. Keep frozen effective rows=99,997. · ref: chxy:/home/fx/locateanything-vp-v1/sources/Eagle-Embodied-783f656d-snapshot-v1/Embodied/eaglevl/train/locany_finetune_magi_stream.py

- `locateanything.train_exclusion_rationale_corrected` — Keep 99,997 rows; exclusion is conservative under stricter default-Pillow audit, not proven trainer necessity; trainer read remains likely but unexecuted. · ref: chxy:/home/fx/locateanything-vp-v1/receipts/train-media-exclusion-rationale-correction-v1.json

- `locateanything.heldout_schema_read_disclosure` — First 3 held-out rows were read before preflight, violating lane discipline; receipt frozen. Denominator stays 2,000 and thresholds stay fixed. · ref: chxy:/home/fx/locateanything-vp-v1/receipts/heldout-schema-read-disclosure-v1.json#sha256=c52e69fe60dd

- `locateanything.checkpoint_closure_v2_loadability_defect` — Frozen checkpoint v2 contains Git LFS pointer files; byte identity passed but AutoProcessor offline load failed. Additive v3 is required. · ref: chxy:/home/fx/locateanything-vp-v1/checkpoints/LocateAnything-3B-c32291ca-v2

## 2. 归属与 lane
- `owner.p2_contract_suite` — qwen-brain-owner owns P2 source, report CLI, and focused tests; exact paths in ref; no subagents or forbidden rows. · ref: src/xh_agent/qwen_brain/semantic_contract_suite_v2.py

- `owner.p2_suite_config` — P2 owned path: configs/qwen_brain/semantic-contract-suite-v2.json; create only from synthetic/free-contact builders. · ref: configs/qwen_brain/semantic-contract-suite-v2.json

- `owner.p2_suite_cli` — P2 CLI: synthetic report only; no model/physical dispatcher. Rejected cases use a non-actuating in-memory gate probe. · ref: scripts/qwen_brain/evaluate_semantic_contract_suite_v2.py

- `owner.p2_suite_tests` — P2 owned path: tests/unit/test_qwen_brain_semantic_contract_suite_v2.py; synthetic/free-contact only. · ref: tests/unit/test_qwen_brain_semantic_contract_suite_v2.py

- `owner.p3_vnext_spec` — qwen-brain-owner owns one documentation-only vNext P3 specification; no code, simulator, evaluation, or governed policy changes. · ref: QWEN_BRAIN_P3_VNEXT_ORACLE_CANDIDATE_SPEC.md

- `owner.p2_suite_gap` — P2 reporting owns raw structural-gap witness changes in suite, inventory, CLI, and focused suite tests only; production V2 contracts/gate stay frozen. · ref: src/xh_agent/qwen_brain/semantic_contract_suite_v2.py

- `owner.claim_manifest_v1` — Task #45 sole write surface: claim_manifest_v1.py, lora-no-benefit-v1.json, and test_qwen_brain_claim_manifest_v1.py. · ref: src/xh_agent/qwen_brain/claim_manifest_v1.py

- `locateanything-pair-v1-nonauthoritative-late-plan` — Pair V1 remains NONAUTHORITATIVE/0 materialized pairs; a late pair-plan-v1 appeared after the halt. Preserve V1 unchanged; additive V2 only. · ref: chxy:/home/fx/locateanything-vp-v1/receipts/pair-construction-attempt-v1-halt.json;chxy:/home/fx/locateanything-vp-v1/metadata/pair-plan-v1.json

- `locateanything-stale-lfs-owner` — Stale lane-owned Git LFS writes only its incomplete COCO object/log, not canonical train2017.zip or pair-plan; leave running absent ruling. · ref: chxy:pids 658992,658993;.git/lfs/incomplete/69a8bb58...1343124058

- `locateanything-pair-v2-review-gate` — V2 builder frozen on chxy; local+remote focused tests PASS 13/13. Authority/data roots remain absent pending independent read-only verdict. · ref: chxy:source/pair_builder_v2.py@2e574ada;source/test_pair_builder_v2_reviewed.py@24fbdf9a

- `locany-gen605-attempt2-running-v1` — Gen605 attempt-2 two-node NCCL/TCP training running; first optimizer step frozen; node2 worker 998674, chxy worker 2644603. · ref: node2:/home/gl/locateanything-vp-v1/receipts/gen605-two-node-attempt2-first-step-v1.json

- `locany-gen605-attempt2-step500-terminal-chain-v1` — Gen605 attempt2过step500；双rank存活、无失败标记、checkpoint分片闭合；终态/完成绑定delta助手已create-only发布，继续至3000。 · ref: chxy:/home/fx/locateanything-vp-v1/source/freeze_locany_gen605_chxy_terminal_v1.py

## 3. 硬约束与停止线
- `bound.no_write_governed` — 绝不写`/Users/gl/tzb-qrm-lite`；绝不写`/Users/gl/tzb/M2C_STATE.md`。
- `bound.no_isaac` — 绝不触碰labserver `/var/tmp/xh-data/isaac-industrial/m2c/`，不启动Isaac/容器/runner/replay/物理动作；0 ordinal。
- `bound.baseline_endpoint` — 不修改/停止/复用baseline endpoint `18767`，不改baseline config/launcher/report/raw I/O/v2 index。
- `bound.shared_gpu` — 不kill/停止/干扰shared GPU process；70GiB allocated/72GiB reserved promotion与74GiB immediate abort、allocation failure均fail closed。
- `bound.no_service` — 不service、不canonical evaluation；Qwen/S5工件不进入formal M2C治理/证据链。
- `bound.no_sweep` — 无sweep/resume/checkpoint selection/scientific fallback/silent retry/参数变更。失败identity、墓碑、residue及V1/V2/V3/V4工件不覆盖、不删、不复用。
- `bound.no_push` — 不commit/bundle/push；local commit须tzb-fe exact-scope批准，永不push。技术/流程裁定问tzb-fe；只有权限与GPU调度问用户；peer不能洗白权限。
- `bound.immutable_pkg_runtime` — immutable package运行用published absolute Python、`-B`、包外cache；runtime后必须full-tree rehash。shipping tree build/validation期间不得作为解释器工作对象。
- `bound.adapter_publish` — adapter发布必须hidden noncandidate staging → fresh unmerged reload/exact tensor+probe → create-only PREPARED → Linux no-replace publish → tree rehash → publication receipt → final report；pre-PREPARED failure冻结为`FAILED_NONCANDIDATE`。

- `bound.ruling_preflight` — tzb-fe五类裁定执行前须核验subject身份/摘要同域/canonical地位/动态字段/冻结冲突/路径可解析；任一失败即拒绝并上报。 · ref: /Users/gl/tzb/reports/CLAIMS-SHEET-20260831.md

## 4. 待办
- `todo.freeze_verify` — exit后冻结并核验stdout/stderr/exit/report/PREPARED/publication/adapter tree；完整检查stderr与所有cross-links。
- `todo.post_rehash` — 强制post-final immutable-package full-tree rehash并create-only冻结。至此停止；不得启动service或canonical evaluation。
- `todo.icl_lane_isolation` — parallel lane Task #25 V4 ICL harness保持独立，不得干扰当前Task #27 training。

- `continuous-action-shield-lane` — Task76 exact shield scope sent to tzb-fe; await REGISTER/AMEND/REJECT before any chxy file creation. · ref: peer-msg:46a24786-384c-40f1-acc6-89638bbb7472

- `locateanything.pilot_2k` — IN_PROGRESS: baseline first, then official 2000-step LoRA on frozen 99997 rows, then identical held-out evaluation. · ref: /home/fx/locateanything-vp-v1/metadata/visual-prompt-go-no-go-prereg-v1.json

- `locany-gen605-authorized-v1` — Task89 IN_PROGRESS: user authorized new node2+chxy Gen605; 2 nodes/2 GPUs, max_steps3000, batch2, create-only, formal-v3 recipe otherwise fixed. · ref: task-tool:89

## 5. Recent tail(journal 缓存,非权威)
- 2026-09-01T21:14+0800 [FACT/facts] <qwen-brain-owner> `locateanything-v2-png-compat-audit-result-20260901` — Full 143129-media audit: 3 failures, all train crops from COCO 479400; held-out 0. Source JPEG carries 1.829MB ICC; target JPEG loads. · ref: /home/fx/locateanything-vp-v1/logs/png-compat-audit-v2-review1.log
- 2026-09-01T21:15+0800 [FACT/facts] <qwen-brain-owner> `locateanything-v2-train-only-exclusion-ruling-20260901` — tzb-fe ruling: few incompatibles all train => preregister exclusion and continue without rebuild; held-out exclusion would require refreeze. · ref: peer-msg:bca5c387-f61d-4674-8352-4ad4f4faec55
- 2026-09-01T21:16+0800 [FACT/facts] <qwen-brain-owner> `locateanything-v2-effective-train-owner-20260901` — Own additive effective-train builder/audit sources, data-v2-effective root, logs/rc only; frozen V2 stays untouched. · ref: /home/fx/locateanything-vp-v1/source/build_effective_train_v2.py
- 2026-09-01T21:21+0800 [FACT/facts] <qwen-brain-owner> `locateanything-v2-effective-train-frozen-20260901` — Additive effective training manifest frozen: 99997 rows, 3 explicit train exclusions; held-out 2000 unchanged/0 affected; V2 immutable. · ref: /home/fx/locateanything-vp-v1/data-v2-effective/receipts/train-media-exclusion-v2.json
- 2026-09-01T21:21+0800 [FACT/facts] <qwen-brain-owner> `locateanything-official-source-snapshot-owner-20260901` — Own additive exact Eagle commit snapshot root and freeze receipt/log/source under LocateAnything write root; damaged checkout untouched. · ref: /home/fx/locateanything-vp-v1/sources/Eagle-783f656d-snapshot-v1
- 2026-09-01T21:22+0800 [FACT/facts] <qwen-brain-owner> `locateanything-v2-effective-dataset-audit-pass-20260901` — Audit 3fafe75d RC0: effective train 99997 exact base subsequence, 199994 media opens/0 fail; held-out 2000 unchanged/0 affected. · ref: /home/fx/locateanything-vp-v1/logs/effective-dataset-v2-audit.log
- 2026-09-01T21:23+0800 [DONE/task] <qwen-brain-owner> `locateanything.pair_construction` — DONE: effective train 99997; final audit RC0; held-out 2000 unchanged and zero media failures. · ref: /home/fx/locateanything-vp-v1/logs/effective-dataset-v2-audit.log
- 2026-09-01T21:23+0800 [TASK/task] <qwen-brain-owner> `locateanything.pilot_2k` — IN_PROGRESS: baseline first, then official 2000-step LoRA on frozen 99997 rows, then identical held-out evaluation. · ref: /home/fx/locateanything-vp-v1/metadata/visual-prompt-go-no-go-prereg-v1.json
- 2026-09-01T21:37+0800 [FACT/facts] <qwen-brain-owner> `locateanything-official-embodied-snapshot-frozen-20260901` — Exact official Embodied tree at Eagle 783f656d recovered additively: 132 tracked files, manifest bc0833e8, damaged checkout untouched. · ref: /home/fx/locateanything-vp-v1/sources/Eagle-Embodied-783f656d-snapshot-v1/SNAPSHOT_MANIFEST.json
- 2026-09-01T21:45+0800 [FACT/facts] <qwen-brain-owner> `locateanything.trainer_png_limit_override` — Trainer sets PNG MAX_TEXT_CHUNK=1GiB, so exact trainer should not reproduce default-Pillow 1.829MB iCCP failure. Keep frozen effective rows=99,997. · ref: chxy:/home/fx/locateanything-vp-v1/sources/Eagle-Embodied-783f656d-snapshot-v1/Embodied/eaglevl/train/locany_finetune_magi_stream.py
- 2026-09-01T21:50+0800 [FACT/facts] <qwen-brain-owner> `locateanything.train_exclusion_rationale_corrected` — Keep 99,997 rows; exclusion is conservative under stricter default-Pillow audit, not proven trainer necessity; trainer read remains likely but unexecuted. · ref: chxy:/home/fx/locateanything-vp-v1/receipts/train-media-exclusion-rationale-correction-v1.json
- 2026-09-01T22:19+0800 [FACT/facts] <qwen-brain-owner> `locateanything.heldout_schema_read_disclosure` — Read first 3 held-out JSONL rows before preflight freeze; no model ran or thresholds changed. Further reads stopped pending tzb-fe ruling. · ref: chxy:/home/fx/locateanything-vp-v1/data-v2/held-out/pairs.jsonl
- 2026-09-01T22:21+0800 [FACT/facts] <qwen-brain-owner> `locateanything.heldout_schema_read_disclosure` — First 3 held-out rows were read before preflight, violating lane discipline; receipt frozen. Denominator stays 2,000 and thresholds stay fixed. · ref: chxy:/home/fx/locateanything-vp-v1/receipts/heldout-schema-read-disclosure-v1.json#sha256=c52e69fe60dd
- 2026-09-01T22:25+0800 [FACT/facts] <qwen-brain-owner> `locateanything.checkpoint_closure_v2_loadability_defect` — Frozen checkpoint v2 contains Git LFS pointer files; byte identity passed but AutoProcessor offline load failed. Additive v3 is required. · ref: chxy:/home/fx/locateanything-vp-v1/checkpoints/LocateAnything-3B-c32291ca-v2
- 2026-09-02T04:08+0800 [TASK/task] <qwen-brain-owner> `locateanything-vp-formal-pilot` — Task85运行中：baseline=0/2000；训练exact2000步/99997行，ADR-0035包装失败；adapted exact2000评测PID1615067勿中断，冻结下游链待运行。 · ref: /home/fx/locateanything-vp-v1/receipts/postevaluation-chain-freeze-v4.json
- 2026-09-02T06:24+0800 [TASK/task] <qwen-brain-owner> `locateanything-vp-formal-pilot` — Task85主/互换评测与GO均完成；final assembler因ADR-0035 receipt的ensure_ascii规范误判而闭式失败，最终件未创建，待加法successor。 · ref: /home/fx/locateanything-vp-v1/logs/postevaluation-chain-v4.log
- 2026-09-02T06:29+0800 [DONE/task] <qwen-brain-owner> `locateanything-vp-formal-pilot` — Task85完成：单次formal pilot=GO；0→739/2000，Δ0.3695，CI[0.348,0.391]；swapped支持类别级视觉提示；ADR-0035同件披露。 · ref: /home/fx/locateanything-vp-v1/receipts/formal-pilot-complete-bundle-v1.json
- 2026-09-02T13:46+0800 [TASK/task] <qwen-brain-owner> `locany-gen605-authorized-v1` — Task89 IN_PROGRESS: user authorized new node2+chxy Gen605; 2 nodes/2 GPUs, max_steps3000, batch2, create-only, formal-v3 recipe otherwise fixed. · ref: task-tool:89
- 2026-09-02T16:05+0800 [FACT/lane] <qwen-brain-owner> `locany-gen605-attempt2-running-v1` — Gen605 attempt-2 two-node NCCL/TCP training running; first optimizer step frozen; node2 worker 998674, chxy worker 2644603. · ref: node2:/home/gl/locateanything-vp-v1/receipts/gen605-two-node-attempt2-first-step-v1.json
- 2026-09-02T16:32+0800 [FACT/lane] <qwen-brain-owner> `locany-gen605-attempt2-step500-terminal-chain-v1` — Gen605 attempt2过step500；双rank存活、无失败标记、checkpoint分片闭合；终态/完成绑定delta助手已create-only发布，继续至3000。 · ref: chxy:/home/fx/locateanything-vp-v1/source/freeze_locany_gen605_chxy_terminal_v1.py
