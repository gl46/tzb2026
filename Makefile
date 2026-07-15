PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := src

.PHONY: doctor test validate sim-smoke constrained-pick-place empty-grasp-failures record-constrained-episode moveit-plan-smoke baseline teacher-audit bakeoff-prepare m0-report m0-audit status
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
