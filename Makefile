PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := src

.PHONY: doctor test validate sim-smoke constrained-pick-place empty-grasp-failures record-constrained-episode moveit-plan-smoke baseline teacher-audit bakeoff-prepare m0-report m0-audit status m2a-doctor isaac-contract isaac-benchmark isaac-pilot isaac-validate isaac-sync qrm-beta-train qrm-beta-eval qrm-beta-closed-loop shadow-isaac m2a-status
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
	@echo "NOT_RUN: optional P1 shadow Isaac is intentionally not implemented in M2A P0"
m2a-status:
	$(PYTHON) scripts/m2a_status.py
