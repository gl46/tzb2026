from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from m2c import build_terminal_regrasp_diagnostic_prereg_v2 as builder
from m2c.derive_model_owned_chain_probe import derive_probe_bytes_v4
from m2c.derive_terminal_regrasp_diagnostic_probe_v2 import (
    derive_terminal_regrasp_diagnostic_probe_bytes_v2,
)
from m2c.s4_scene_family import materialize_scene
from xh_agent.data.isaac_m1b import load_m1b_isaac_generated_scene
from xh_agent.policy.qrm_lite.s4_v4_collection_authorization_v1 import (
    CommittedSourceSnapshotV1,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v1 import (
    ADR_INTRODUCED_COMMIT,
    ADR_PATH,
    ADR_SHA256,
    DIAGNOSTIC_CONDITIONS,
    M2CTerminalDiagnosticAttemptV1,
    TerminalDiagnosticError,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.terminal_regrasp_diagnostic_v2 import (
    CAMPAIGN_ID,
    EXCLUSION_PATHS,
    IMPLEMENTATION_PATHS,
    ISAAC_IMAGE,
    ISAAC_IMAGE_ID,
    LEDGER_NAMESPACE,
    M2CTerminalRegraspDiagnosticPreregV2,
    M2CTerminalRegraspDiagnosticRawV2,
    PARKING_XY_M,
    PREREG_REPOSITORY_PATH,
    ResolvedTerminalDiagnosticPreregV2,
    UPSTREAM_V4_PROBE_SHA256,
    consume_diagnostic_run_v2,
    evaluate_preregistered_decision_tree_v2,
    materialize_diagnostic_scene_v2,
)


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path("/Users/gl/tzb-m2c-evidence/m2c-s2/source-v4/isaac_m2c_blocker_probe.py")
TEMPLATE = ROOT / "robot_ws/src/xh_sim/worlds/industrial_cylinder_v1.sdf"


def _runs() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for source_seed in range(260100, 260112):
        for condition in DIAGNOSTIC_CONDITIONS:
            result.append(
                builder._run_record(
                    ordinal=len(result),
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
    return result


def _prereg_payload() -> dict[str, object]:
    snapshot = CommittedSourceSnapshotV1(
        commit="1" * 40,
        tree="2" * 40,
        file_count=1,
        total_bytes=1,
        inventory_sha256="3" * 64,
    )
    core: dict[str, object] = {
        "schema_version": "M2CTerminalRegraspDiagnosticPreregV2",
        "status": ("FROZEN_AFTER_V1_PRE_ACTION_INVALIDATION_BEFORE_ANY_VALID_DIAGNOSTIC_OUTCOME"),
        "repository_relative_path": PREREG_REPOSITORY_PATH,
        "introduction_commit_paths": [PREREG_REPOSITORY_PATH],
        "campaign_id": CAMPAIGN_ID,
        "governing_adr": {
            "path": ADR_PATH,
            "sha256": ADR_SHA256,
            "introduced_commit": ADR_INTRODUCED_COMMIT,
            "status": "ACCEPTED_HUMAN_ADR",
        },
        "written_date_asia_shanghai": "2026-08-15",
        "diagnostic_outcomes_observed_before_freeze": False,
        "v1_pre_action_infrastructure_failure_observed": True,
        "v1_invalidation": {
            "preregistration": {"path": "v1-prereg.json", "sha256": "4" * 64},
            "incomplete_audit": {"path": "v1-report.json", "sha256": "5" * 64},
            "valid_terminal_measurements": 0,
            "probe_launched": False,
            "physical_action_outcome": "NOT_AVAILABLE",
            "failed_before_kit": True,
            "v1_claim_reused": False,
            "v1_identity_reused": False,
        },
        "restart_basis": ("NEW_CAMPAIGN_ALL_FRESH_IDENTITIES_NO_V1_CLAIM_OR_IDENTITY_REUSE"),
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
        "unchanged_six_object_schema": True,
        "excluded_blockers_are_parked_not_removed": True,
        "no_gate_threshold_b0_or_predicate_change": True,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
        "container_image": ISAAC_IMAGE,
        "container_image_id": ISAAC_IMAGE_ID,
        "upstream_v4_probe_sha256": UPSTREAM_V4_PROBE_SHA256,
        "controlled_urdf_sha256": (
            "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"
        ),
        "ledger_root": "/tmp/v2-ledger",
        "ledger_namespace": LEDGER_NAMESPACE,
        "implementation_commit": "1" * 40,
        "committed_source_snapshot": snapshot.model_dump(mode="json"),
        "implementation_bindings": [
            {"path": path, "sha256": f"{index + 1:064x}"}
            for index, path in enumerate(IMPLEMENTATION_PATHS)
        ],
        "exclusion_sources": [
            {"path": path, "sha256": f"{index + 101:064x}"}
            for index, path in enumerate(EXCLUSION_PATHS)
        ],
        "external_identity_digest": "e" * 64,
        "parking_xy_m": {key: list(value) for key, value in PARKING_XY_M.items()},
        "runs": _runs(),
        "decision_tree": {
            "schema_version": "M2CTerminalRegraspDecisionTreeV1",
            "success_definition": (
                "PHYSICAL_LIFTED_AND_PUBLIC_GRASPED_TRUE_AND_LIFTED_TRUE_AND_ZERO_SAFETY_VIOLATIONS"
            ),
            "denominator_policy": ("EXACTLY_12_VALID_TERMINAL_MEASUREMENTS_PER_CONDITION"),
            "incomplete_policy": "NO_BRANCH_UNTIL_ALL_36_RUNS_HAVE_VALID_MEASUREMENTS",
            "r1_c1_min_successes": 9,
            "r1_c3_max_successes": 3,
            "r2_c1_min_failures": 6,
            "r3_policy": "ALL_COMPLETE_OUTCOMES_NOT_MATCHING_R1_OR_R2",
            "no_retry_or_replacement": True,
        },
    }
    return {**core, "prereg_sha256": canonical_sha256(core)}


def test_v2_parks_blockers_but_retains_six_object_schema(tmp_path: Path) -> None:
    full = materialize_scene(TEMPLATE.read_text(), 260104, (-0.115, 0.13))
    assert full is not None
    expected_parked = {
        "C1_NO_BLOCKER": {"cylinder_01", "cylinder_02"},
        "C2_RETAINED_BLOCKER": {"cylinder_01"},
        "C3_FULL_V4": set(),
    }
    for index, condition in enumerate(DIAGNOSTIC_CONDITIONS, start=1):
        sdf, supervision = materialize_diagnostic_scene_v2(
            full_v4_sdf_bytes=full[0],
            full_v4_supervision_bytes=full[1],
            scene_seed=2_601_000 + index,
            source_base_seed=260104,
            condition=condition,
        )
        root = ET.fromstring(sdf)
        world = root.find("world")
        assert world is not None
        cylinders = [
            model
            for model in world.findall("model")
            if model.get("name", "").startswith("cylinder_")
        ]
        assert [model.get("name") for model in cylinders] == [
            f"cylinder_{number:02d}" for number in range(1, 7)
        ]
        payload = json.loads(supervision)
        assert len(payload["simulator_supervision"]["objects"]) == 6
        assert payload["m2c_terminal_regrasp_diagnostic"]["parked_nonlocal_blockers"] == sorted(
            expected_parked[condition]
        )
        sdf_path = tmp_path / f"{condition}.sdf"
        supervision_path = tmp_path / f"{condition}.json"
        sdf_path.write_bytes(sdf)
        supervision_path.write_bytes(supervision)
        scene = load_m1b_isaac_generated_scene(sdf_path, supervision_path)
        assert scene.cylinder_count == 6


def test_v2_derived_probe_changes_only_authority_and_raw_schema() -> None:
    upstream = UPSTREAM.read_bytes()
    v4 = derive_probe_bytes_v4(upstream).decode()
    diagnostic = derive_terminal_regrasp_diagnostic_probe_bytes_v2(upstream).decode()
    compile(diagnostic, "terminal-diagnostic-v2.py", "exec")

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
    assert "bind_diagnostic_claim_to_raw_session_v2" in diagnostic
    assert '"schema_version": "M2CTerminalRegraspDiagnosticRawV2"' in diagnostic
    assert (
        diagnostic.index("require_pre_freeze(")
        < diagnostic.index("bind_diagnostic_claim_to_raw_session(")
        < diagnostic.index("from isaacsim import SimulationApp")
    )


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
        terminal_target_blocker_surface_gap_m=(run.terminal_target_blocker_surface_gap_m),
        public_predicates=["grasped=true", "lifted=true"] if success else [],
        terminal_success=success,
        physical_action_executed=True,
        collision_or_safety_violations=0,
        teacher_used=False,
        privileged_truth_policy_input=False,
        raw_evidence_sha256=f"{run.ordinal + 1:064x}",
    )


@pytest.mark.parametrize(
    ("c1_successes", "c3_successes", "expected"),
    [(9, 3, "R1"), (5, 12, "R2"), (8, 6, "R3")],
)
def test_v2_decision_tree_remains_exact(
    c1_successes: int, c3_successes: int, expected: str
) -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV2.model_validate(_prereg_payload())
    quotas = {
        "C1_NO_BLOCKER": c1_successes,
        "C2_RETAINED_BLOCKER": 6,
        "C3_FULL_V4": c3_successes,
    }
    seen = {condition: 0 for condition in DIAGNOSTIC_CONDITIONS}
    attempts = []
    for run in prereg.runs:
        success = seen[run.condition] < quotas[run.condition]
        seen[run.condition] += 1
        attempts.append(_attempt(run, success=success))
    decision = evaluate_preregistered_decision_tree_v2(
        prereg=prereg,
        attempts=attempts,
    )
    assert decision.selected_branch == expected


def test_v2_consumption_is_fresh_ordered_and_create_only(tmp_path: Path) -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV2.model_validate(_prereg_payload())
    ledger = tmp_path / "ledger-v2"
    ledger.mkdir(mode=0o700)
    resolved = ResolvedTerminalDiagnosticPreregV2(
        path=tmp_path / "prereg-v2.json",
        file_sha256="6" * 64,
        raw_bytes=b"{}",
        prereg=prereg.model_copy(update={"ledger_root": str(ledger)}),
        introduced_commit="7" * 40,
    )
    first = consume_diagnostic_run_v2(
        resolved=resolved,
        run_id=resolved.prereg.runs[0].run_id,
        ledger_root=ledger,
        derived_probe_sha256="8" * 64,
        consumed_at_ns=1,
    )
    assert first.name == "claim-00.json"
    with pytest.raises(TerminalDiagnosticError, match="frozen order"):
        consume_diagnostic_run_v2(
            resolved=resolved,
            run_id=resolved.prereg.runs[2].run_id,
            ledger_root=ledger,
            derived_probe_sha256="8" * 64,
            consumed_at_ns=2,
        )


def test_v2_raw_rejects_success_without_terminal_execution() -> None:
    prereg = M2CTerminalRegraspDiagnosticPreregV2.model_validate(_prereg_payload())
    run = prereg.runs[0]
    authorization = {
        "schema_version": "M2CTerminalDiagnosticAuthorizationBindingV2",
        "campaign_id": CAMPAIGN_ID,
        "condition": run.condition,
        "run_id": run.run_id,
        "matched_key": run.matched_key,
        "ordinal": run.ordinal,
        "scene_seed": run.scene_seed,
        "failure_seed": run.failure_seed,
        "probe_mode": run.probe_mode,
        "expected_local_blockers": run.expected_local_blockers,
        "terminal_target_blocker_surface_gap_m": run.terminal_target_blocker_surface_gap_m,
        "consumption_receipt_sha256": "9" * 64,
        "prereg_sha256": prereg.prereg_sha256,
        "source_sdf_sha256": run.sdf_sha256,
        "source_supervision_sha256": run.supervision_sha256,
        "source_urdf_sha256": prereg.controlled_urdf_sha256,
        "upstream_v4_probe_sha256": prereg.upstream_v4_probe_sha256,
        "derived_probe_sha256": "a" * 64,
        "container_image_id": ISAAC_IMAGE_ID,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    raw = {
        "schema_version": "M2CTerminalRegraspDiagnosticRawV2",
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
        "actuation_probe_source_sha256": "a" * 64,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    with pytest.raises(ValueError, match="terminal-valid"):
        M2CTerminalRegraspDiagnosticRawV2.model_validate(raw)
