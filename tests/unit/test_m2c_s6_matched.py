from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from m2c.summarize_s6_matched import (
    EXPECTED_METHODS,
    M2CS6EpisodeEvidenceV1,
    M2CS6PhysicalExecutionReceiptV1,
    PROJECT,
    load_and_verify_frozen_inputs,
    paired_bootstrap_difference,
    summarize_s6,
)
from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopDecisionV1,
    M2BClosedLoopEpisodeV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import physical_receipt_sha256
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_receipt(root: Path, payload: dict[str, object]) -> str:
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    digest = sha256_bytes(raw)
    (root / f"{digest}.json").write_bytes(raw)
    return digest


@pytest.fixture(scope="module")
def frozen_inputs() -> tuple[dict, dict[str, str]]:
    return load_and_verify_frozen_inputs(
        PROJECT / "configs/m2c_s6_evaluation_keys.json",
        PROJECT / "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md",
    )


def decision(
    key: str,
    method: str,
    *,
    receipt_digest: str | None = None,
    violation: bool = False,
) -> M2BClosedLoopDecisionV1:
    model = method != "B0"
    digest = hashlib.sha256(f"{key}:{method}".encode()).hexdigest()
    return M2BClosedLoopDecisionV1(
        decision_id=f"{key}:{method}:decision-0",
        step_id=0,
        selected_skill="REOBSERVE",
        previous_failed_skill="GRASP",
        model_decision=model,
        mapping_status="VALID" if model else "NOT_APPLICABLE",
        ik_gate="NOT_APPLICABLE",
        collision_gate="NOT_APPLICABLE",
        safety_gate="PASS",
        execution_source=("MODEL_SELECTED_B0_SKILL" if model else "B0_BASELINE"),
        executed_skill="REOBSERVE",
        outcome="FAILURE" if violation else "SUCCESS",
        collision_or_safety_violation=violation,
        registry_sha256=digest if model else None,
        model_checkpoint_sha256=digest if model else None,
        model_input_sha256=digest if model else None,
        model_output_sha256=digest if model else None,
        mapping_result_sha256=digest if model else None,
        gate_evidence_sha256=(
            {
                "ik": digest,
                "collision": digest,
                "safety": digest,
                "execution_outcome": receipt_digest or digest,
            }
            if model
            else {}
        ),
    )


def physical_skill_receipt(index: int, method: str) -> PhysicalSkillReceiptV2:
    provisional = PhysicalSkillReceiptV2(
        receipt_id=f"physical-{index}-{method}",
        receipt_sha256="0" * 64,
        executed_skill="REOBSERVE",
        execution_source="MODEL_SELECTED_REGISTERED_SKILL",
        physically_executed=True,
        started_at_ns=1_000_000 + index * 100,
        completed_at_ns=1_000_050 + index * 100,
        schema_gate="PASS",
        stale_track_gate="PASS",
        frame_unit_gate="PASS",
        ik_gate="PASS",
        collision_gate="PASS",
        controller_gate="PASS",
        safety_gate="PASS",
    )
    return provisional.model_copy(update={"receipt_sha256": physical_receipt_sha256(provisional)})


def episode_evidence(
    frozen: dict,
    method: str,
    item: M2BClosedLoopDecisionV1,
    *,
    success: bool,
) -> M2CS6EpisodeEvidenceV1:
    episode = M2BClosedLoopEpisodeV1(
        episode_id=f"{frozen['matched_key']}:{method}",
        matched_key=frozen["matched_key"],
        method=method,
        scene_seed=frozen["scene_seed"],
        failure_type=frozen["failure_type"],
        initial_success=False,
        final_success=success,
        recovery_attempted=True,
        recovery_success=success,
        retries=0,
        task_time_s=3.0,
        decisions=[item],
        collision_or_safety_violation=item.collision_or_safety_violation,
    )
    return M2CS6EpisodeEvidenceV1(
        episode=episode,
        frozen_key_identity=frozen,
    )


def physical_envelope(
    frozen: dict,
    episode: M2BClosedLoopEpisodeV1,
    item: M2BClosedLoopDecisionV1,
    physical: PhysicalSkillReceiptV2,
) -> dict[str, object]:
    return M2CS6PhysicalExecutionReceiptV1(
        host="labserver",
        run_id=episode.episode_id,
        collected_at_ns=physical.completed_at_ns + 1,
        episode_id=episode.episode_id,
        matched_key=episode.matched_key,
        method=episode.method,
        frozen_key_identity=frozen,
        decision_id=item.decision_id,
        step_id=item.step_id,
        decision_outcome=item.outcome,
        registry_sha256=str(item.registry_sha256),
        model_checkpoint_sha256=str(item.model_checkpoint_sha256),
        model_input_sha256=str(item.model_input_sha256),
        model_output_sha256=str(item.model_output_sha256),
        mapping_result_sha256=str(item.mapping_result_sha256),
        physical_receipt=physical,
    ).model_dump(mode="json")


def matched_evidence(
    receipt_root: Path,
    manifest: dict,
    *,
    count: int = 30,
) -> list[M2CS6EpisodeEvidenceV1]:
    rows: list[M2CS6EpisodeEvidenceV1] = []
    receipt_index = 0
    for frozen in manifest["evaluation_keys"][:count]:
        for method in EXPECTED_METHODS:
            if method == "B0":
                rows.append(
                    episode_evidence(
                        frozen,
                        method,
                        decision(frozen["matched_key"], method),
                        success=False,
                    )
                )
                continue
            placeholder = decision(frozen["matched_key"], method)
            provisional_episode = episode_evidence(
                frozen, method, placeholder, success=True
            ).episode
            physical = physical_skill_receipt(receipt_index, method)
            digest = write_receipt(
                receipt_root,
                physical_envelope(frozen, provisional_episode, placeholder, physical),
            )
            item = placeholder.model_copy(
                update={
                    "gate_evidence_sha256": {
                        **placeholder.gate_evidence_sha256,
                        "execution_outcome": digest,
                    }
                }
            )
            rows.append(episode_evidence(frozen, method, item, success=True))
            receipt_index += 1
    return rows


def run_summary(
    rows: list[M2CS6EpisodeEvidenceV1],
    receipt_root: Path,
    frozen_inputs: tuple[dict, dict[str, str]],
) -> dict:
    manifest, bindings = frozen_inputs
    return summarize_s6(
        rows,
        frozen_manifest=manifest,
        frozen_bindings=bindings,
        physical_receipts_root=receipt_root,
        bootstrap_resamples=100,
        bootstrap_seed=7,
    )


def test_paired_bootstrap_is_deterministic_and_matched() -> None:
    first = paired_bootstrap_difference([(True, False)] * 20, resamples=100, seed=7)
    second = paired_bootstrap_difference([(True, False)] * 20, resamples=100, seed=7)
    assert first == second
    assert first["estimate"] == 1.0
    assert first["interval"] == [1.0, 1.0]


def test_s6_requires_external_authentication_after_local_receipt_replay(
    tmp_path: Path,
    frozen_inputs: tuple[dict, dict[str, str]],
) -> None:
    manifest, _ = frozen_inputs
    rows = matched_evidence(tmp_path, manifest)
    report = run_summary(rows, tmp_path, frozen_inputs)
    assert report["formal_evaluation_ready"] is False
    assert report["complete_matched_keys"] == 30
    assert report["episodes"] == 120
    assert report["qrm_model_decisions_executed"] == 0
    assert report["locally_replayed_model_decisions"] == 90
    assert report["physical_execution_receipts_verified"] == 0
    assert report["locally_replayed_physical_receipts"] == 90
    assert report["authenticated_episode_evidence_verifier_binding"] is None
    assert report["authenticated_episode_evidence_verified"] == 0
    assert report["required_authenticated_episode_evidence"] == 120
    assert any(
        "authenticated episode-level evidence verifier is not frozen" in item
        for item in report["findings"]
    )
    assert report["primary_metric"] is None
    assert report["collision_or_safety_violations"] is None
    assert report["pure_model_success_episodes"] is None
    assert report["experiment_executed_by_this_command"] is False


def test_s6_rejects_missing_key_and_complete_identity_drift(
    tmp_path: Path,
    frozen_inputs: tuple[dict, dict[str, str]],
) -> None:
    manifest, _ = frozen_inputs
    below = run_summary(matched_evidence(tmp_path, manifest, count=29), tmp_path, frozen_inputs)
    assert below["formal_evaluation_ready"] is False
    assert below["complete_matched_keys"] == 29
    assert any("missing frozen S6 keys" in item for item in below["findings"])

    rows = matched_evidence(tmp_path, manifest)
    drifted = dict(rows[0].frozen_key_identity)
    drifted["sdf_sha256"] = "0" * 64
    rows[0] = rows[0].model_copy(update={"frozen_key_identity": drifted})
    report = run_summary(rows, tmp_path, frozen_inputs)
    assert report["formal_evaluation_ready"] is False
    assert any("complete frozen key identity mismatch" in item for item in report["findings"])


def test_s6_rejects_missing_tampered_or_reused_receipt(
    tmp_path: Path,
    frozen_inputs: tuple[dict, dict[str, str]],
) -> None:
    manifest, _ = frozen_inputs
    rows = matched_evidence(tmp_path, manifest)
    first = rows[1].episode.decisions[0]
    first_path = tmp_path / f"{first.gate_evidence_sha256['execution_outcome']}.json"
    first_path.write_text(first_path.read_text() + " ")
    tampered = run_summary(rows, tmp_path, frozen_inputs)
    assert tampered["formal_evaluation_ready"] is False
    assert any("file SHA-256 mismatch" in item for item in tampered["findings"])

    rows = matched_evidence(tmp_path, manifest)
    reused_digest = rows[1].episode.decisions[0].gate_evidence_sha256["execution_outcome"]
    second = rows[2].episode.decisions[0]
    rows[2] = rows[2].model_copy(
        update={
            "episode": rows[2].episode.model_copy(
                update={
                    "decisions": [
                        second.model_copy(
                            update={
                                "gate_evidence_sha256": {
                                    **second.gate_evidence_sha256,
                                    "execution_outcome": reused_digest,
                                }
                            }
                        )
                    ]
                }
            )
        }
    )
    reused = run_summary(rows, tmp_path, frozen_inputs)
    assert reused["formal_evaluation_ready"] is False
    assert any("physical receipt file reused" in item for item in reused["findings"])


def test_s6_strict_envelopes_forbid_synthetic_teacher_truth_and_mock_flags(
    frozen_inputs: tuple[dict, dict[str, str]],
) -> None:
    manifest, _ = frozen_inputs
    frozen = manifest["evaluation_keys"][0]
    item = decision(frozen["matched_key"], "QRM_COARSE_FC")
    row = episode_evidence(frozen, "QRM_COARSE_FC", item, success=True)
    for field, value in (
        ("synthetic", True),
        ("mocked_physics", True),
        ("teacher_used", True),
        ("privileged_truth_policy_input", True),
        ("world_model_mainline_replaced", True),
    ):
        with pytest.raises(ValidationError):
            M2CS6EpisodeEvidenceV1.model_validate({**row.model_dump(mode="json"), field: value})


def test_s6_withholds_pure_metrics_until_external_authentication(
    tmp_path: Path,
    frozen_inputs: tuple[dict, dict[str, str]],
) -> None:
    manifest, _ = frozen_inputs
    report = run_summary(matched_evidence(tmp_path, manifest), tmp_path, frozen_inputs)
    assert report["pure_model_success_episodes"] is None
    assert report["successful_episodes_with_any_model_decision"] is None
    assert report["pure_model_success_exclusions"] == []


def test_frozen_input_loader_rejects_manifest_or_preregistration_drift(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "keys.json"
    prereg = tmp_path / "prereg.md"
    manifest.write_bytes((PROJECT / "configs/m2c_s6_evaluation_keys.json").read_bytes())
    prereg.write_bytes(
        (PROJECT / "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md").read_bytes()
    )
    manifest.write_text(manifest.read_text().replace('"scene_seed": 20057', '"scene_seed": 20058'))
    with pytest.raises(ValueError, match="manifest file SHA-256 mismatch"):
        load_and_verify_frozen_inputs(manifest, prereg)

    manifest.write_bytes((PROJECT / "configs/m2c_s6_evaluation_keys.json").read_bytes())
    prereg.write_text(prereg.read_text() + "\ndrift\n")
    with pytest.raises(ValueError, match="pre-registration SHA-256 mismatch"):
        load_and_verify_frozen_inputs(manifest, prereg)
