PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := src:scripts

.PHONY: doctor test validate sim-smoke constrained-pick-place empty-grasp-failures record-constrained-episode moveit-plan-smoke baseline teacher-audit bakeoff-prepare m0-report m0-audit status m2a-doctor isaac-contract isaac-benchmark isaac-pilot isaac-validate isaac-sync qrm-beta-train qrm-beta-eval qrm-beta-closed-loop shadow-isaac lingbot-prep m2a-status m2b-audit m2b-export-schemas m2b-generate-failures m2b-generate-residuals m2b-pack-evidence-pilot m2b-dataset m2b-coarse-dataset m2b-coarse-gate m2b-residual-pilot m2b-residual-dataset m2b-residual-training-dataset m2b-physical-gates m2b-train m2b-map-validate m2b-run-prospective-preflights m2b-preflight-manifest m2b-map-prospective m2b-run-matched-closed-loop m2b-summarize-matched-closed-loop m2b-status
doctor:
	$(PYTHON) -m xh_agent.diagnostics.doctor --local --output reports/hardware-local.json
	$(PYTHON) -m xh_agent.diagnostics.doctor --remote node2 --user gl --output reports/hardware-remote-node2.json
	$(PYTHON) -m xh_agent.diagnostics.doctor --remote chxy --user fx --output reports/hardware-remote-chxy.json
	$(PYTHON) scripts/aggregate_doctors.py
test:
	$(PYTHON) -m pytest -q
validate:
	$(PYTHON) scripts/validate_project.py
sim-smoke:
	bash scripts/run_sim_smoke_test.sh
constrained-pick-place:
	bash scripts/run_constrained_pick_place.sh
empty-grasp-failures:
	bash scripts/run_empty_grasp_failure_batch.sh
record-constrained-episode:
	$(PYTHON) scripts/record_constrained_transfer_episode.py
moveit-plan-smoke:
	bash scripts/run_moveit_planning_smoke.sh
baseline:
	bash scripts/run_pick_place_baseline.sh
teacher-audit:
	$(PYTHON) scripts/check_hf_metadata.py
bakeoff-prepare:
	$(PYTHON) scripts/prepare_teacher_bakeoff.py
m0-report:
	$(PYTHON) scripts/generate_m0_reports.py
m0-audit:
	$(PYTHON) scripts/audit_m0_completion.py
status:
	$(PYTHON) scripts/status.py
m2a-doctor:
	$(PYTHON) scripts/m2a_status.py --doctor-only
isaac-contract:
	bash scripts/isaac/run_contract_suite.sh
isaac-benchmark:
	bash scripts/isaac/benchmark_workers.sh
isaac-pilot:
	bash scripts/isaac/generate_pilot_dataset.sh
isaac-validate:
	for shard in "$${ISAAC_DATA_ROOT}/$${DATASET_VERSION:-isaac-industrial-v1-pilot}/shards/"*.READY; do $(PYTHON) scripts/isaac/validate_shard.py "$$shard"; done
isaac-sync:
	bash scripts/isaac/sync_ready_shards.sh
qrm-beta-train:
	$(PYTHON) scripts/qrm_lite/train_q012.py --dataset "$${QRM_BETA_DATASET}" --models Q0,Q1,Q2 --out-dir artifacts/qrm_lite/m2a-beta --report reports/m2a-s4-qrm-beta-train.md --report-json reports/m2a-s4-qrm-beta-train.json
qrm-beta-eval:
	$(PYTHON) scripts/qrm_lite/eval_beta_offline.py --dataset "$${QRM_BETA_DATASET}" --train-report reports/m2a-s4-qrm-beta-train.json
qrm-beta-closed-loop:
	bash scripts/qrm_lite/run_isaac_closed_loop_eval.sh
shadow-isaac:
	$(PYTHON) scripts/isaac/run_shadow_rollout_pilot.py \
		--project-root "$${ISAAC_PROJECT_ROOT}" \
		--source-root "$${ISAAC_SOURCE_ROOT}" \
		--data-root "$${ISAAC_DATA_ROOT}/$${DATASET_VERSION:-isaac-industrial-v1-pilot}" \
		--dataset "$${SHADOW_QRM_DATASET:-$${ISAAC_DATA_ROOT}/$${DATASET_VERSION:-isaac-industrial-v1-pilot}/qrm/isaac-fc-on.jsonl}" \
		--output-root "$${ISAAC_DATA_ROOT}/shadow/m2a-shadow-pilot-v1" \
		--report-json reports/m2a-s6-shadow-isaac.json \
		--report-md reports/m2a-s6-shadow-isaac.md
lingbot-prep:
	$(PYTHON) scripts/lingbot/export_canonical_to_lerobot.py \
		--dataset-root "$${ISAAC_DATASET_ROOT}" \
		--output-root "$${LEROBOT_OUTPUT_ROOT}" \
		--limit "$${LEROBOT_SAMPLE_SIZE:-30}"
m2a-status:
	$(PYTHON) scripts/m2a_status.py
m2b-audit:
	@test -n "$${M2A_DATASET_ROOT}" || (echo "M2A_DATASET_ROOT is required" >&2; exit 2)
	$(PYTHON) scripts/m2b/audit_m2a.py --dataset-root "$${M2A_DATASET_ROOT}"
m2b-export-schemas:
	$(PYTHON) scripts/m2b/export_failure_rich_schemas.py
m2b-generate-failures:
	bash scripts/m2b/run_remote_failure_batch.sh
m2b-generate-residuals:
	bash scripts/m2b/launch_residual_evidence_scale.sh
m2b-pack-evidence-pilot:
	@test -n "$${M2B_EMPTY_EVIDENCE}" -a -n "$${M2B_WRONG_EVIDENCE}" -a -n "$${M2B_RELEASE_EVIDENCE}" || (echo "M2B_EMPTY_EVIDENCE, M2B_WRONG_EVIDENCE, and M2B_RELEASE_EVIDENCE are required" >&2; exit 2)
	$(PYTHON) scripts/m2b/build_failure_evidence_pilot.py \
		--evidence "EMPTY_GRASP=$${M2B_EMPTY_EVIDENCE}" \
		--evidence "WRONG_OBJECT=$${M2B_WRONG_EVIDENCE}" \
		--evidence "RELEASE_FAILURE=$${M2B_RELEASE_EVIDENCE}" \
		--output artifacts/m2b/failure-evidence-pilot.jsonl \
		--report reports/m2b-s2-failure-evidence-pilot.json
m2b-dataset:
	$(PYTHON) scripts/m2b/build_dataset_v2.py \
		--source-manifest configs/m2b_dataset_sources.json \
		--output artifacts/m2b/dataset-v2.jsonl \
		--quarantine artifacts/m2b/dataset-v2-quarantine.jsonl \
		--report reports/m2b-s2-dataset-v2.json
m2b-coarse-dataset:
	$(PYTHON) scripts/m2b/build_coarse_training_v2.py \
		--episodes artifacts/m2b/dataset-v2.jsonl \
		--asset-root artifacts/m2b/dataset-v2-assets \
		--output artifacts/m2b/coarse-training-v2.jsonl \
		--quarantine artifacts/m2b/coarse-training-v2-quarantine.jsonl \
		--report reports/m2b-s2-coarse-training-v2.json
m2b-coarse-gate:
	$(PYTHON) scripts/m2b/validate_coarse_training_v2.py \
		--dataset artifacts/m2b/coarse-training-v2.jsonl \
		--report reports/m2b-s4-coarse-training-data-gate.json
m2b-residual-pilot:
	@test -n "$${M2B_WRONG_EVIDENCE}" || (echo "M2B_WRONG_EVIDENCE is required" >&2; exit 2)
	$(PYTHON) scripts/m2b/build_residual_pair_pilot.py \
		--evidence "$${M2B_WRONG_EVIDENCE}" \
		--output artifacts/m2b/residual-pair-pilot.jsonl \
		--report reports/m2b-s3-residual-pairs-pilot.json
m2b-residual-dataset:
	@test -n "$${M2B_RESIDUAL_WORKER0_STATUS}" -a -n "$${M2B_RESIDUAL_WORKER1_STATUS}" || (echo "M2B_RESIDUAL_WORKER0_STATUS and M2B_RESIDUAL_WORKER1_STATUS are required" >&2; exit 2)
	$(PYTHON) scripts/m2b/build_residual_pairs.py \
		--remote-worker-status "$${M2B_RESIDUAL_WORKER0_STATUS}" \
		--remote-worker-status "$${M2B_RESIDUAL_WORKER1_STATUS}" \
		--output artifacts/m2b/residual-pairs.jsonl \
		--quarantine artifacts/m2b/residual-pairs-quarantine.jsonl \
		--report reports/m2b-s3-residual-pairs.json
m2b-residual-training-dataset:
	$(PYTHON) scripts/m2b/build_residual_training_v2.py \
		--pairs artifacts/m2b/residual-pairs.jsonl \
		--asset-root artifacts/m2b/dataset-v2-assets \
		--output artifacts/m2b/residual-training-v2.jsonl \
		--quarantine artifacts/m2b/residual-training-v2-quarantine.jsonl \
		--report reports/m2b-s3-residual-training-v2.json
m2b-physical-gates:
	$(PYTHON) scripts/m2b/summarize_physical_runtime_gates.py \
		--source-manifest configs/m2b_dataset_sources.json \
		--required-probe-sha256 1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094 \
		--output artifacts/m2b/physical-runtime-gates.jsonl \
		--report reports/m2b-s5-physical-runtime-gates.json
m2b-train:
	bash scripts/m2b/run_a100_coarse_ablation.sh
	bash scripts/m2b/run_a100_residual_mlp.sh
m2b-map-validate:
	$(PYTHON) scripts/m2b/validate_runtime_mapping_offline.py \
		--dataset data/qrm_lite/manifests/real-v1.jsonl \
		--checkpoint artifacts/qrm_lite/beta1/Q2.npz \
		--registry configs/qrm_runtime_mapping.yaml \
		--split test \
		--output artifacts/m2b/runtime-mapping-heldout.jsonl \
		--report reports/m2b-s5-runtime-mapping-offline.json
m2b-preflight-manifest:
	@test -n "$${M2B_PREFLIGHT_PLAN}" || (echo "M2B_PREFLIGHT_PLAN is required" >&2; exit 2)
	$(PYTHON) scripts/m2b/build_isolated_preflight_manifest.py \
		--plan "$${M2B_PREFLIGHT_PLAN}" \
		--output artifacts/m2b/isolated-preflight-manifest.jsonl
m2b-run-prospective-preflights:
	@test -n "$${M2B_MODEL_RECORDS}" -a -n "$${M2B_PREFLIGHT_OUTPUT}" -a -n "$${M2B_PREFLIGHT_EVIDENCE_ROOT}" || (echo "M2B_MODEL_RECORDS, M2B_PREFLIGHT_OUTPUT, and M2B_PREFLIGHT_EVIDENCE_ROOT are required" >&2; exit 2)
	$(PYTHON) scripts/m2b/run_prospective_preflight_batch.py \
		--model-records "$${M2B_MODEL_RECORDS}" \
		--dataset "$${M2B_DATASET:-artifacts/m2b/dataset-v2.jsonl}" \
		--registry configs/qrm_runtime_mapping.yaml \
		--local-evidence-root "$${M2B_PREFLIGHT_EVIDENCE_ROOT}" \
		--output "$${M2B_PREFLIGHT_OUTPUT}" \
		$${M2B_PREFLIGHT_GPU:+--gpu "$${M2B_PREFLIGHT_GPU}"}
m2b-map-prospective:
	@test -n "$${M2B_MODEL_RECORDS}" -a -n "$${M2B_PREFLIGHT_MANIFEST}" || (echo "M2B_MODEL_RECORDS and M2B_PREFLIGHT_MANIFEST are required" >&2; exit 2)
	$(PYTHON) scripts/m2b/build_prospective_runtime_decisions.py \
		--model-records "$${M2B_MODEL_RECORDS}" \
		--preflight-manifest "$${M2B_PREFLIGHT_MANIFEST}" \
		--registry configs/qrm_runtime_mapping.yaml \
		--output artifacts/m2b/prospective-runtime-decisions.jsonl
	$(PYTHON) scripts/m2b/summarize_prospective_runtime_mapping.py \
		--decisions artifacts/m2b/prospective-runtime-decisions.jsonl \
		--report reports/m2b-s5-runtime-mapping-offline.json
m2b-run-matched-closed-loop:
	@test -n "$${M2B_NO_FC_DECISIONS}" -a -n "$${M2B_FC_DECISIONS}" -a -n "$${M2B_CLOSED_LOOP_OUTPUT}" -a -n "$${M2B_CLOSED_LOOP_JOURNAL}" -a -n "$${M2B_CLOSED_LOOP_BATCH_REPORT}" || (echo "M2B_NO_FC_DECISIONS, M2B_FC_DECISIONS, M2B_CLOSED_LOOP_OUTPUT, M2B_CLOSED_LOOP_JOURNAL, and M2B_CLOSED_LOOP_BATCH_REPORT are required" >&2; exit 2)
	$(PYTHON) scripts/m2b/run_matched_closed_loop_batch.py \
		--no-fc-decisions "$${M2B_NO_FC_DECISIONS}" \
		--fc-decisions "$${M2B_FC_DECISIONS}" \
		--dataset "$${M2B_DATASET:-artifacts/m2b/dataset-v2.jsonl}" \
		--registry configs/qrm_runtime_mapping.yaml \
		--output "$${M2B_CLOSED_LOOP_OUTPUT}" \
		--journal "$${M2B_CLOSED_LOOP_JOURNAL}" \
		--report "$${M2B_CLOSED_LOOP_BATCH_REPORT}" \
		$${M2B_CLOSED_LOOP_GPU:+--gpu "$${M2B_CLOSED_LOOP_GPU}"}
m2b-summarize-matched-closed-loop:
	@test -n "$${M2B_CLOSED_LOOP_EPISODES}" || (echo "M2B_CLOSED_LOOP_EPISODES is required" >&2; exit 2)
	$(PYTHON) scripts/m2b/summarize_matched_closed_loop.py \
		--episodes "$${M2B_CLOSED_LOOP_EPISODES}" \
		--expected-method B0 \
		--expected-method QRM_COARSE_NO_FC \
		--expected-method QRM_COARSE_FC \
		--report reports/m2b-s5-closed-loop.json
m2b-status:
	$(PYTHON) scripts/m2b/status.py
