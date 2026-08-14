from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from m2c import build_terminal_regrasp_diagnostic_prereg as builder
from m2c.derive_model_owned_chain_probe import derive_probe_bytes_v4
from m2c.derive_terminal_regrasp_diagnostic_probe import (
    derive_terminal_regrasp_diagnostic_probe_bytes,
)
from m2c.run_terminal_regrasp_diagnostic import _probe_command
from m2c.s4_scene_family import materialize_scene
from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    CommittedSourceSnapshotV1,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ADR_INTRODUCED_COMMIT,
    ADR_PATH,
    ADR_SHA256,
    DIAGNOSTIC_CONDITIONS,
    DIAGNOSTIC_EXCLUSION_PATHS,
    DIAGNOSTIC_IMPLEMENTATION_PATHS,
    ISAAC_IMAGE_ID,
    M2CTerminalDiagnosticAttemptV1,
    M2CTerminalRegraspDiagnosticPreregV1,
    M2CTerminalRegraspDiagnosticRawV1,
    ResolvedTerminalDiagnosticPreregV1,
    TerminalDiagnosticError,
    canonical_sha256,
    consume_diagnostic_run,
    evaluate_preregistered_decision_tree,
    materialize_diagnostic_scene,
)


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
TEMPLATE = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"


def _prereg_payload() -> dict[str, object]:
    runs = []
    for source_seed in builder.BASE_SEEDS:
        for condition in DIAGNOSTIC_CONDITIONS:
            runs.append(
                builder._run_record(
                    ordinal=len(runs),
                    source_base_seed=source_seed,
                    condition=condition,
                    sdf_sha256=hashlib.sha256(
                        f"sdf-{source_seed}-{condition}".encode()
                    ).hexdigest(),
                    supervision_sha256=hashlib.sha256(
                        f"supervision-{source_seed}-{condition}".encode()
                    ).hexdigest(),
                )
            )
    snapshot = CommittedSourceSnapshotV1(
        commit="1" * 40,
        tree="2" * 40,
        file_count=1,
        total_bytes=1,
        inventory_sha256="3" * 64,
    )
    core: dict[str, object] = {
        "schema_version": "M2CTerminalRegraspDiagnosticPreregV1",
        "status": "FROZEN_BEFORE_ANY_DIAGNOSTIC_EXECUTION_OR_RESULT",
        "repository_relative_path": builder.PREREG_PATH.as_posix(),
        "introduction_commit_paths": [builder.PREREG_PATH.as_posix()],
        "campaign_id": "m2c-s4-terminal-regrasp-diagnostic-v1",
        "governing_adr": {
            "path": ADR_PATH,
            "sha256": ADR_SHA256,
            "introduced_commit": ADR_INTRODUCED_COMMIT,
            "status": "ACCEPTED_HUMAN_ADR",
        },
        "written_date_asia_shanghai": "2026-08-15",
        "outcomes_observed_before_freeze": False,
        "collection_halted": True,
        "training_collection_authorized": False,
        "diagnostic_only": True,
        "fixed_order": True,
        "paired_source_seeds": True,
        "runs_per_condition": 12,
        "total_runs": 36,
        "retry_authorized": False,
        "replacement_authorized": False,
        "terminal_only_estimand": True,
        "no_gate_threshold_b0_or_predicate_change": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "container_image": "nvcr.io/nvidia/isaac-sim:6.0.1",
        "container_image_id": ISAAC_IMAGE_ID,
        "upstream_v4_probe_sha256": (
            "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
        ),
        "controlled_urdf_sha256": (
            "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
        ),
        "ledger_root": "/tmp/diagnostic-ledger",
        "ledger_namespace": "M2C_S4_TERMINAL_REGRASP_DIAGNOSTIC_V1",
        "implementation_commit": "1" * 40,
        "committed_source_snapshot": snapshot.model_dump(mode="json"),
        "implementation_bindings": [
            {"path": path, "sha256": f"{index + 1:x}" * 64}
            for index, path in enumerate(DIAGNOSTIC_IMPLEMENTATION_PATHS)
        ],
        "exclusion_sources": [
            {"path": path, "sha256": f"{index + 1:x}" * 64}
            for index, path in enumerate(DIAGNOSTIC_EXCLUSION_PATHS)
        ],
        "external_identity_digest": "e" * 64,
        "runs": runs,
        "decision_tree": {
            "schema_version": "M2CTerminalRegraspDecisionTreeV1",
            "success_definition": (
                "PHYSICAL_LIFTED_AND_PUBLIC_GRASPED_TRUE_AND_LIFTED_TRUE_AND_ZERO_SAFETY_VIOLATIONS"
            ),
            "denominator_policy": "EXACTLY_12_VALID_TERMINAL_MEASUREMENTS_PER_CONDITION",
            "incomplete_policy": "NO_BRANCH_UNTIL_ALL_36_RUNS_HAVE_VALID_MEASUREMENTS",
            "r1_c1_min_successes": 9,
            "r1_c3_max_successes": 3,
            "r2_c1_min_failures": 6,
            "r3_policy": "ALL_COMPLETE_OUTCOMES_NOT_MATCHING_R1_OR_R2",
            "no_retry_or_replacement": True,
        },
    }
    return {**core, "prereg_sha256": canonical_sha256(core)}


def _attempt(run: object, *, success: bool) -> M2CTerminalDiagnosticAttemptV1:
    return M2CTerminalDiagnosticAttemptV1(
        schema_version="M2CTerminalDiagnosticAttemptV1",
        run_id=run.run_id,
        ordinal=run.ordinal,
        condition=run.condition,
        terminal_measurement_valid=True,
        terminal_execution_status="LIFTED" if success else "CONTACT_GATE_REJECTED",
        pregrasp_ik_passed=True,
        contact_gate_passed=success,
        selected_free_gap_yaw_rad=0.0,
        terminal_target_blocker_surface_gap_m=run.terminal_target_blocker_surface_gap_m,
        public_predicates=["grasped=true", "lifted=true"] if success else [],
        terminal_success=success,
        physical_action_executed=True,
        collision_or_safety_violations=0,
        teacher_used=False,
        privileged_truth_policy_input=False,
        raw_evidence_sha256=f"{run.ordinal + 1:064x}",
    )


def test_scene_ablation_removes_only_preregistered_local_blockers() -> None:
    source_seed = builder.BASE_SEEDS[0]
    full = materialize_scene(TEMPLATE.read_text(), source_seed, (-0.115, 0.13))
    assert full is not None
    expected_absent = {
        "C1_NO_BLOCKER": {"cylinder_01", "cylinder_02"},
        "C2_RETAINED_BLOCKER": {"cylinder_01"},
        "C3_FULL_V4": set(),
    }
    for index, condition in enumerate(DIAGNOSTIC_CONDITIONS, start=1):
        sdf, supervision = materialize_diagnostic_scene(
            full_v4_sdf_bytes=full[0],
            full_v4_supervision_bytes=full[1],
            scene_seed=source_seed * 10 + index,
            source_base_seed=source_seed,
            condition=condition,
        )
        root = ET.fromstring(sdf)
        world = root.find("world")
        assert world is not None
        names = {model.get("name") for model in world.findall("model")}
        assert not (expected_absent[condition] & names)
        payload = json.loads(supervision)
        object_ids = {
            item["actual_sim_entity_id"] for item in payload["simulator_supervision"]["objects"]
        }
        assert not (expected_absent[condition] & object_ids)
        assert (
            payload["m2c_terminal_regrasp_diagnostic"]["outcome_observed_during_materialization"]
            is False
        )


def test_derived_probe_preserves_terminal_helper_and_guards_before_kit() -> None:
    upstream = UPSTREAM.read_bytes()
    v4 = derive_probe_bytes_v4(upstream).decode()
    diagnostic = derive_terminal_regrasp_diagnostic_probe_bytes(upstream).decode()
    compile(diagnostic, "terminal-diagnostic.py", "exec")

    def function_text(source: str, name: str) -> str:
        tree = ast.parse(source)
        node = next(
            item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name
        )
        result = ast.get_source_segment(source, node)
        assert result is not None
        return result

    assert function_text(v4, "_execute_m2b_public_regrasp") == function_text(
        diagnostic, "_execute_m2b_public_regrasp"
    )
    assert (
        diagnostic.index("require_pre_freeze(")
        < diagnostic.index("bind_diagnostic_claim_to_raw_session(")
        < diagnostic.index("from isaacsim import SimulationApp")
    )
    assert 'choices=("DIAGNOSTIC",)' in diagnostic
    assert '"terminal_measurement_valid": result is not None' in diagnostic


@pytest.mark.parametrize(
    ("c1_successes", "c3_successes", "expected"),
    [(9, 3, "R1"), (5, 12, "R2"), (8, 6, "R3")],
)
def test_decision_tree_is_exact(c1_successes: int, c3_successes: int, expected: str) -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV1.model_validate(_prereg_payload())
    quotas = {"C1_NO_BLOCKER": c1_successes, "C2_RETAINED_BLOCKER": 6, "C3_FULL_V4": c3_successes}
    seen = {condition: 0 for condition in DIAGNOSTIC_CONDITIONS}
    attempts = []
    for run in prereg.runs:
        success = seen[run.condition] < quotas[run.condition]
        seen[run.condition] += 1
        attempts.append(_attempt(run, success=success))
    decision = evaluate_preregistered_decision_tree(prereg=prereg, attempts=attempts)
    assert decision.selected_branch == expected
    with pytest.raises(TerminalDiagnosticError, match="exactly 36"):
        evaluate_preregistered_decision_tree(prereg=prereg, attempts=attempts[:-1])


def test_consumption_is_ordered_create_only(tmp_path: Path) -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV1.model_validate(_prereg_payload())
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)
    payload = prereg.model_dump(mode="json")
    resolved = ResolvedTerminalDiagnosticPreregV1(
        path=tmp_path / "prereg.json",
        file_sha256=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
        raw_bytes=b"{}",
        prereg=prereg.model_copy(update={"ledger_root": str(ledger)}),
        introduced_commit="4" * 40,
    )
    first = consume_diagnostic_run(
        resolved=resolved,
        run_id=resolved.prereg.runs[0].run_id,
        ledger_root=ledger,
        derived_probe_sha256="5" * 64,
        consumed_at_ns=1,
    )
    assert first.name == "claim-00.json"
    with pytest.raises(TerminalDiagnosticError, match="frozen order"):
        consume_diagnostic_run(
            resolved=resolved,
            run_id=resolved.prereg.runs[2].run_id,
            ledger_root=ledger,
            derived_probe_sha256="5" * 64,
            consumed_at_ns=2,
        )
    with pytest.raises(TerminalDiagnosticError, match="frozen order"):
        consume_diagnostic_run(
            resolved=resolved,
            run_id=resolved.prereg.runs[0].run_id,
            ledger_root=ledger,
            derived_probe_sha256="5" * 64,
            consumed_at_ns=2,
        )


def test_probe_command_separates_direct_and_full_conditions(tmp_path: Path) -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV1.model_validate(_prereg_payload())
    for name in ("metrics.json",):
        (tmp_path / name).write_text("{}")
    common = dict(
        image_id=ISAAC_IMAGE_ID,
        gpu=0,
        container_name="diagnostic",
        snapshot_root=tmp_path,
        source_root=tmp_path,
        derived_probe=tmp_path / "probe.py",
        stage_root=tmp_path,
        probe_root=tmp_path,
        claim_projection=tmp_path / "claim.json",
        sdf=tmp_path / "scene.sdf",
        supervision=tmp_path / "scene.json",
        urdf=tmp_path / "panda.urdf",
        stage_command=["docker", "run"],
        scripted_bin_cell=3,
    )
    direct = _probe_command(run=prereg.runs[0], **common)
    full = _probe_command(run=prereg.runs[2], **common)
    assert direct[direct.index("--target-object") + 1] == "cylinder_04"
    assert "--m2b-injected-public-grasp-color" not in direct
    assert full[full.index("--target-object") + 1] == "cylinder_01"
    assert full[full.index("--m2b-task-target-object") + 1] == "cylinder_04"
    assert full[full.index("--m2c-scripted-safe-place-bin-cell") + 1] == "3"


def test_raw_schema_rejects_success_without_terminal_execution() -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV1.model_validate(_prereg_payload())
    run = prereg.runs[0]
    authorization = {
        "schema_version": "M2CTerminalDiagnosticAuthorizationBindingV1",
        "campaign_id": prereg.campaign_id,
        "condition": run.condition,
        "run_id": run.run_id,
        "matched_key": run.matched_key,
        "ordinal": run.ordinal,
        "scene_seed": run.scene_seed,
        "failure_seed": run.failure_seed,
        "probe_mode": run.probe_mode,
        "expected_local_blockers": run.expected_local_blockers,
        "terminal_target_blocker_surface_gap_m": run.terminal_target_blocker_surface_gap_m,
        "consumption_receipt_sha256": "6" * 64,
        "prereg_sha256": prereg.prereg_sha256,
        "source_sdf_sha256": run.sdf_sha256,
        "source_supervision_sha256": run.supervision_sha256,
        "source_urdf_sha256": prereg.controlled_urdf_sha256,
        "upstream_v4_probe_sha256": prereg.upstream_v4_probe_sha256,
        "derived_probe_sha256": "7" * 64,
        "container_image_id": ISAAC_IMAGE_ID,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    raw = {
        "schema_version": "M2CTerminalRegraspDiagnosticRawV1",
        "authorization": authorization,
        "run_id": run.run_id,
        "matched_key": run.matched_key,
        "scene_seed": run.scene_seed,
        "failure_seed": run.failure_seed,
        "condition": run.condition,
        "terminal_measurement_valid": True,
        "terminal_execution_status": "LIFTED",
        "pregrasp_ik_passed": True,
        "contact_gate_passed": True,
        "selected_free_gap_yaw_rad": 0.0,
        "terminal_target_blocker_surface_gap_m": None,
        "public_predicates": ["grasped=true", "lifted=true"],
        "terminal_success": True,
        "physical_action_executed": True,
        "collision_or_safety_violations": 0,
        "public_capture_evidence": [],
        "terminal_regrasp_execution": None,
        "actuation_probe_source_sha256": "7" * 64,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    with pytest.raises(ValueError, match="terminal-valid"):
        M2CTerminalRegraspDiagnosticRawV1.model_validate(raw)


def test_batch24_cancellation_report_is_not_an_outcome() -> None:
    report = json.loads((ROOT / "reports/m2c-s4-v4-batch24-cancellation-adr0026.json").read_text())
    assert report["status"] == "CANCELLED_BY_ADR0026_NO_OUTCOME"
    assert report["actuation_probe_present"] is False
    assert report["terminal_outcome_recorded"] is False
    assert report["training_sample_count"] == report["failure_count_increment"] == 0
    assert len(report["consumed_keys"]) == 1
    assert len(report["unrun_keys"]) == 2
