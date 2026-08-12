#!/usr/bin/env python3
"""Replay M2C terminal evidence instead of trusting stage summaries.

This module is intentionally independent from the report writers.  A stage
summary can point at evidence, but every completion value used by ``status.py``
is recomputed here from strict episode models, frozen manifests, and the
underlying receipt files.  Missing bindings are a normal ``PARTIAL`` state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any, Literal
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from xh_agent.policy.qrm_lite.closed_loop_metrics import (
    M2BClosedLoopEpisodeV1,
    pure_model_success_episode,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import (
    ModelOwnedChainEpisodeV2,
    validate_model_owned_chain_episode,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    physical_receipt_sha256,
)
from xh_agent.policy.qrm_lite.s5_evidence import (
    S5AcceptedGovernanceReceiptV1,
    S5PhysicalExecutionReceiptV1,
    S5ResidualEpisodeEvidenceV1,
    validate_s5_accepted_adr_text,
)


EXPECTED_METHODS = (
    "B0",
    "QRM_COARSE_NO_FC",
    "QRM_COARSE_FC",
    "QRM_COARSE_FC_MLP",
)
S6_PREREGISTRATION = "docs/decisions/M2C-S6-MATCHED-EVALUATION-PREREG.md"
S6_EVALUATION_MANIFEST = "configs/m2c_s6_evaluation_keys.json"
B0_FREEZE_MANIFEST = "configs/m2c_b0_freeze.json"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoundFileV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RawEvidenceManifestV1(StrictModel):
    schema_version: Literal["M2CTerminalRawEvidenceManifestV1"]
    files: list[BoundFileV1] = Field(min_length=1)
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class EvidenceBindingV1(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class S4TerminalBindingV1(StrictModel):
    schema_version: Literal["M2CS4TerminalEvidenceBindingV1"]
    episodes: EvidenceBindingV1
    evidence_manifest: EvidenceBindingV1
    entry_gate_report: EvidenceBindingV1


class S4FormalEpisodeEvidenceV1(StrictModel):
    schema_version: Literal["M2CS4FormalEpisodeEvidenceV1"]
    closed_loop_episode: M2BClosedLoopEpisodeV1
    model_owned_chain_episode: ModelOwnedChainEpisodeV2
    formal_runner_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_integration_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    teacher_used: Literal[False]
    privileged_truth_policy_input: Literal[False]


class ResidualDispositionV1(StrictModel):
    status: Literal["ACTIVE_WITH_PHYSICAL_EVIDENCE", "FROZEN_ZERO"]
    rationale: str = Field(min_length=1)
    impact_on_conclusion: str = Field(min_length=1)
    evidence: EvidenceBindingV1 | None = None


class S5TerminalBindingV1(StrictModel):
    schema_version: Literal["M2CS5TerminalEvidenceBindingV1"]
    episodes: EvidenceBindingV1
    evidence_manifest: EvidenceBindingV1
    governance: EvidenceBindingV1
    r6d_disposition: ResidualDispositionV1
    gripper_disposition: ResidualDispositionV1


class S6TerminalBindingV1(StrictModel):
    schema_version: Literal["M2CS6TerminalEvidenceBindingV1"]
    episodes: EvidenceBindingV1
    evidence_manifest: EvidenceBindingV1
    preregistration: EvidenceBindingV1
    evaluation_key_manifest: EvidenceBindingV1


class FinalVerificationBindingV1(StrictModel):
    schema_version: Literal["M2CFinalVerificationBindingV1"]
    checked_head_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    full_test_command: list[str] = Field(min_length=4)
    junit: EvidenceBindingV1
    b0_freeze_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    m2b_artifact_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    blockers: tuple[str, ...]
    metrics: dict[str, Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, raw: str) -> Path:
    path = Path(raw)
    path = path if path.is_absolute() else root / path
    if path.is_symlink():
        raise ValueError(f"terminal evidence path may not be a symlink: {raw}")
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"terminal evidence file is absent: {raw}")
    return path


def _bound_path(root: Path, binding: EvidenceBindingV1, label: str) -> Path:
    path = _resolve(root, binding.path)
    actual = _sha256(path)
    if actual != binding.sha256:
        raise ValueError(f"{label} SHA-256 mismatch: {actual} != {binding.sha256}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence is not an object: {path}")
    return payload


def _read_jsonl(path: Path, model: type[BaseModel]) -> list[Any]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(model.model_validate_json(line))
            except ValidationError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    if not rows:
        raise ValueError(f"terminal episode evidence is empty: {path}")
    return rows


def _manifest_files(
    root: Path,
    binding: EvidenceBindingV1,
) -> tuple[RawEvidenceManifestV1, dict[str, Path]]:
    path = _bound_path(root, binding, "raw evidence manifest")
    manifest = RawEvidenceManifestV1.model_validate(_read_json(path))
    digests: dict[str, Path] = {}
    paths: set[Path] = set()
    for item in manifest.files:
        evidence_path = _resolve(root, item.path)
        if evidence_path in paths:
            raise ValueError("raw evidence manifest repeats a file path")
        paths.add(evidence_path)
        actual = _sha256(evidence_path)
        if actual != item.sha256:
            raise ValueError(f"raw evidence file SHA-256 mismatch: {item.path}")
        if actual in digests:
            raise ValueError("raw evidence manifest repeats identical file bytes")
        digests[actual] = evidence_path
    return manifest, digests


def _required_episode_digests(episode: M2BClosedLoopEpisodeV1) -> set[str]:
    required: set[str] = set()
    for decision in episode.decisions:
        for digest in (
            decision.registry_sha256,
            decision.model_checkpoint_sha256,
            decision.model_input_sha256,
            decision.model_output_sha256,
            decision.mapping_result_sha256,
            *decision.gate_evidence_sha256.values(),
        ):
            if digest is not None:
                required.add(digest)
    return required


def _require_inventory(
    required: set[str], inventory: set[str] | dict[str, Path], label: str
) -> None:
    missing = sorted(required - set(inventory))
    if missing:
        raise ValueError(f"{label} lacks {len(missing)} hash-bound evidence files")


def _entry_gate_replay(root: Path, binding: EvidenceBindingV1) -> dict[str, Any]:
    path = _bound_path(root, binding, "S4 entry-gate report")
    reported = _read_json(path)
    if reported.get("schema_version") != "M2CS4EntryGateReportV2":
        raise ValueError("S4 entry-gate report schema is not V2")
    local_path = (reported.get("local_contract_tests") or {}).get("receipt_path")
    physical_path = (reported.get("physical_integration") or {}).get("receipt_path")
    if not isinstance(local_path, str) or not isinstance(physical_path, str):
        raise ValueError("S4 entry-gate report lacks local/physical receipt paths")
    from xh_agent.policy.qrm_lite.s4_entry_gate import evaluate_s4_entry_gate

    replayed = evaluate_s4_entry_gate(
        root,
        local_receipt_path=_resolve(root, local_path),
        physical_receipt_path=_resolve(root, physical_path),
    )
    if replayed.get("formal_q_b_evaluation_authorized") is not True:
        raise ValueError("S4 entry gate does not replay to formal authorization")
    for field in (
        "checked_head_commit",
        "frozen_bindings",
        "formal_q_b_evaluation_authorized",
    ):
        if reported.get(field) != replayed.get(field):
            raise ValueError(f"S4 entry-gate report differs from replay: {field}")
    reported_physical = reported.get("physical_integration") or {}
    replayed_physical = replayed.get("physical_integration") or {}
    for field in (
        "status",
        "passed",
        "evidence_origin",
        "execution_mode",
        "test_model_provenance",
        "checked_implementation_commit",
        "matched_key",
        "episode_id",
        "decisions_observed",
        "physical_receipts_observed",
        "fresh_observations_observed",
        "strict_pure_model_success",
        "world_model_bundle_verified",
        "world_model_bundle",
        "structured_q012_control_policy_accepted",
        "synthetic_unit_journal_accepted",
    ):
        if reported_physical.get(field) != replayed_physical.get(field):
            raise ValueError(f"S4 entry-gate physical layer differs from replay: {field}")
    return replayed


def verify_s4(
    root: Path,
    summary: dict[str, Any] | None,
) -> VerificationResult:
    blockers: list[str] = []
    metrics: dict[str, Any] = {"pure_model_success_episodes": None}
    try:
        if summary is None:
            raise ValueError("S4 terminal summary is absent")
        binding = S4TerminalBindingV1.model_validate(summary.get("terminal_evidence"))
        episodes_path = _bound_path(root, binding.episodes, "S4 episode evidence")
        _, inventory = _manifest_files(root, binding.evidence_manifest)
        entry = _entry_gate_replay(root, binding.entry_gate_report)
        rows = _read_jsonl(episodes_path, S4FormalEpisodeEvidenceV1)
        from xh_agent.policy.qrm_lite.s4_entry_gate import (
            PhysicalIntegrationReceiptV2,
            _external_physical_evidence_blockers,
        )

        pure = 0
        episode_ids: set[str] = set()
        receipt_digests: set[str] = set()
        for row in rows:
            closed = row.closed_loop_episode
            chain = row.model_owned_chain_episode
            if closed.episode_id != chain.episode_id:
                raise ValueError("S4 closed-loop and model-owned episode IDs differ")
            if closed.final_success != chain.final_task_success:
                raise ValueError("S4 closed-loop and model-owned success values differ")
            if closed.episode_id in episode_ids:
                raise ValueError("S4 terminal evidence repeats an episode ID")
            episode_ids.add(closed.episode_id)
            if closed.method == "B0":
                raise ValueError("S4 terminal evidence contains a B0 baseline episode")
            if len(closed.decisions) != len(chain.decisions):
                raise ValueError("S4 closed-loop and model-owned decision counts differ")
            execution_source = {
                "MODEL_SELECTED_REGISTERED_SKILL": "MODEL_SELECTED_B0_SKILL",
                "B0_FALLBACK": "B0_FALLBACK",
                "B0_CONTINUATION": "B0_BASELINE",
                "NO_PHYSICAL_EXECUTION": "NONE",
            }
            for closed_decision, chain_decision in zip(
                closed.decisions,
                chain.decisions,
                strict=True,
            ):
                if (
                    closed_decision.decision_id != chain_decision.decision_id
                    or closed_decision.step_id != chain_decision.step_index
                    or closed_decision.selected_skill != chain_decision.selected_skill
                ):
                    raise ValueError("S4 closed-loop and model-owned decisions differ")
                if len(chain_decision.physical_skill_receipts) != 1:
                    raise ValueError("S4 model-owned decision lacks exactly one receipt")
                chain_receipt = chain_decision.physical_skill_receipts[0]
                if (
                    closed_decision.execution_source
                    != execution_source[chain_receipt.execution_source]
                ):
                    raise ValueError("S4 closed-loop attribution differs from physical receipt")
                if closed_decision.executed_skill != (
                    chain_receipt.executed_skill if chain_receipt.physically_executed else None
                ):
                    raise ValueError("S4 closed-loop execution differs from physical receipt")
            validation = validate_model_owned_chain_episode(chain)
            strict = pure_model_success_episode(closed)
            if strict != validation.strict_pure_model_success:
                raise ValueError("S4 strict predicates disagree for one episode")
            pure += int(strict)
            required = _required_episode_digests(closed)
            required.update(
                {
                    row.formal_runner_evidence_sha256,
                    row.physical_integration_receipt_sha256,
                }
            )
            for decision in chain.decisions:
                for receipt in decision.physical_skill_receipts:
                    if receipt.receipt_sha256 != physical_receipt_sha256(receipt):
                        raise ValueError("S4 chain contains a non-canonical physical receipt")
                required.update(
                    {
                        decision.observation.rgb_sha256,
                        decision.observation.depth_sha256,
                        decision.model_output_sha256,
                        *(receipt.receipt_sha256 for receipt in decision.physical_skill_receipts),
                    }
                )
            _require_inventory(required, inventory, "S4 evidence manifest")
            if row.physical_integration_receipt_sha256 in receipt_digests:
                raise ValueError("S4 physical integration receipt is reused")
            receipt_digests.add(row.physical_integration_receipt_sha256)
            physical_receipt = PhysicalIntegrationReceiptV2.model_validate(
                _read_json(inventory[row.physical_integration_receipt_sha256])
            )
            if physical_receipt.episode != chain:
                raise ValueError("S4 physical receipt episode differs from raw episode")
            physical_blockers = _external_physical_evidence_blockers(
                root,
                physical_receipt,
            )
            if physical_blockers:
                raise ValueError(
                    "S4 physical receipt replay failed: " + "; ".join(physical_blockers)
                )
        if summary.get("pure_model_success_episodes") != pure:
            raise ValueError("S4 reported pure count differs from strict replay")
        d2 = summary.get("d2_triggered") is True
        expected_status = "D2_GO_QRM_COARSE_ONLY" if d2 else "PASS_Q_B_PURE_MODEL_RECOVERY"
        if summary.get("status") != expected_status:
            raise ValueError("S4 status differs from replayed disposition")
        if (d2 and pure != 0) or (not d2 and pure < 1):
            raise ValueError("S4 D2/pure disposition is inconsistent")
        if summary.get("q_b_training_executed") is not True:
            raise ValueError("S4 has no executed training receipt")
        if summary.get("q_b_evaluation_executed") is not True:
            raise ValueError("S4 has no executed Q-B evaluation")
        metrics = {
            "pure_model_success_episodes": pure,
            "d2_triggered": d2,
            "entry_gate_checked_head_commit": entry["checked_head_commit"],
        }
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, KeyError) as error:
        blockers.append(f"S4 terminal evidence failed closed: {type(error).__name__}: {error}")
    return VerificationResult(not blockers, tuple(blockers), metrics)


def _verify_disposition(
    root: Path,
    disposition: ResidualDispositionV1,
    inventory: set[str],
    label: str,
) -> None:
    if disposition.status == "ACTIVE_WITH_PHYSICAL_EVIDENCE":
        if disposition.evidence is None:
            raise ValueError(f"active {label} has no physical evidence binding")
        path = _bound_path(root, disposition.evidence, f"{label} disposition evidence")
        if _sha256(path) not in inventory:
            raise ValueError(f"{label} disposition evidence is absent from raw inventory")
    elif disposition.evidence is not None:
        raise ValueError(f"frozen {label} unexpectedly names active evidence")


def verify_s5(root: Path, summary: dict[str, Any] | None) -> VerificationResult:
    blockers: list[str] = []
    metrics: dict[str, Any] = {"residual_gain_over_fc": None}
    try:
        if summary is None:
            raise ValueError("S5 terminal summary is absent")
        binding = S5TerminalBindingV1.model_validate(summary.get("terminal_evidence"))
        episodes_path = _bound_path(root, binding.episodes, "S5 episode evidence")
        _, inventory = _manifest_files(root, binding.evidence_manifest)
        if inventory.get(_sha256(episodes_path)) != episodes_path:
            raise ValueError("S5 episode JSONL is absent from raw evidence inventory")
        governance_path = _bound_path(root, binding.governance, "S5 governance receipt")
        _git_file_matches_head(root, governance_path, "S5 governance receipt")
        governance = S5AcceptedGovernanceReceiptV1.model_validate(_read_json(governance_path))
        adr_path = _bound_path(root, governance.adr, "S5 accepted human ADR")
        _git_file_matches_head(root, adr_path, "S5 accepted human ADR")
        adr_text = adr_path.read_text(encoding="utf-8")
        validate_s5_accepted_adr_text(adr_text, selected_option=governance.selected_option)
        introduced = _git(
            root,
            "log",
            "--diff-filter=A",
            "-1",
            "--format=%H",
            "--",
            str(adr_path.relative_to(root)),
        )
        if introduced.returncode != 0 or introduced.stdout.strip() != governance.approval_commit:
            raise ValueError("S5 accepted ADR introduction commit differs from governance receipt")
        if (
            _git(root, "merge-base", "--is-ancestor", governance.approval_commit, "HEAD").returncode
            != 0
        ):
            raise ValueError("S5 accepted ADR commit is not an ancestor of current HEAD")
        _verify_disposition(root, binding.r6d_disposition, inventory, "r6d")
        _verify_disposition(root, binding.gripper_disposition, inventory, "gripper")
        if (
            binding.r6d_disposition.status != "FROZEN_ZERO"
            or binding.gripper_disposition.status != "FROZEN_ZERO"
        ):
            raise ValueError(
                "implemented S5 option A requires frozen-zero r6d and gripper dispositions"
            )
        rows = _read_jsonl(episodes_path, S5ResidualEpisodeEvidenceV1)
        episodes = [row.episode for row in rows]
        expected_modes = {
            "QRM_COARSE_FC": "ZERO_RESIDUAL",
            "QRM_COARSE_FC_MLP": "MLP_RESIDUAL",
        }
        if any(expected_modes.get(row.episode.method) != row.residual_mode for row in rows):
            raise ValueError("S5 residual mode differs from its FC/FC+MLP method")
        required = {row.physical_execution_receipt_sha256 for row in rows} | set().union(
            *(_required_episode_digests(episode) for episode in episodes)
        )
        _require_inventory(required, inventory, "S5 evidence manifest")
        receipt_hashes: set[str] = set()
        receipt_ids: set[str] = set()
        for row in rows:
            receipt_path = inventory[row.physical_execution_receipt_sha256]
            receipt = S5PhysicalExecutionReceiptV1.model_validate(_read_json(receipt_path))
            receipt.validate_episode_binding(row)
            required_receipt_digests = receipt.required_raw_digests()
            _require_inventory(
                required_receipt_digests,
                inventory,
                "S5 physical receipt evidence manifest",
            )
            for physical in receipt.physical_skill_receipts:
                if physical.receipt_id in receipt_ids:
                    raise ValueError("S5 reuses a physical skill receipt ID")
                if physical.receipt_sha256 in receipt_hashes:
                    raise ValueError("S5 reuses a physical skill receipt hash")
                receipt_ids.add(physical.receipt_id)
                receipt_hashes.add(physical.receipt_sha256)
        by_key: dict[str, dict[str, M2BClosedLoopEpisodeV1]] = {}
        for episode in episodes:
            if episode.method not in {"QRM_COARSE_FC", "QRM_COARSE_FC_MLP"}:
                raise ValueError("S5 raw evidence contains a non-FC comparison method")
            methods = by_key.setdefault(episode.matched_key, {})
            if episode.method in methods:
                raise ValueError("S5 raw evidence repeats a key/method")
            methods[episode.method] = episode
        if not by_key or any(
            set(methods) != {"QRM_COARSE_FC", "QRM_COARSE_FC_MLP"} for methods in by_key.values()
        ):
            raise ValueError("S5 raw evidence lacks paired FC/FC+MLP episodes")
        gain = sum(
            int(methods["QRM_COARSE_FC_MLP"].final_success)
            - int(methods["QRM_COARSE_FC"].final_success)
            for methods in by_key.values()
        ) / len(by_key)
        metric = summary.get("comparison_metric") or {}
        if metric.get("name") != "fc_mlp_gain_over_fc" or metric.get("estimate") != gain:
            raise ValueError("S5 reported residual metric differs from raw replay")
        d3 = summary.get("d3_triggered") is True
        if d3:
            if gain != 0 or summary.get("status") != "D3_GO_QRM_COARSE_ONLY":
                raise ValueError("S5 D3 disposition has the wrong status")
        else:
            if gain == 0 or summary.get("status") != "PASS_MEASURABLE_RESIDUAL_DIFFERENCE":
                raise ValueError("S5 does not contain a measurable residual difference")
        if summary.get("residual_closed_loop_executed") is not True:
            raise ValueError("S5 summary does not attest an executed closed loop")
        if summary.get("selected_adr_option") != governance.selected_option:
            raise ValueError("S5 summary option differs from the accepted human ADR")
        metrics = {"residual_gain_over_fc": gain, "d3_triggered": d3}
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, KeyError) as error:
        blockers.append(f"S5 terminal evidence failed closed: {type(error).__name__}: {error}")
    return VerificationResult(not blockers, tuple(blockers), metrics)


def _load_s6_summarizer(root: Path) -> Any:
    path = root / "scripts/m2c/summarize_s6_matched.py"
    spec = importlib.util.spec_from_file_location("m2c_terminal_s6_summarizer", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load the frozen S6 summarizer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_s6(root: Path, summary: dict[str, Any] | None) -> VerificationResult:
    blockers: list[str] = []
    metrics: dict[str, Any] = {
        "primary_metric": None,
        "complete_matched_keys": 0,
        "qrm_model_decisions_executed": 0,
        "collision_or_safety_violations": None,
    }
    try:
        if summary is None:
            raise ValueError("S6 terminal summary is absent")
        binding = S6TerminalBindingV1.model_validate(summary.get("terminal_evidence"))
        episodes_path = _bound_path(root, binding.episodes, "S6 episode evidence")
        _, inventory = _manifest_files(root, binding.evidence_manifest)
        prereg_path = _bound_path(root, binding.preregistration, "S6 preregistration")
        if prereg_path != (root / S6_PREREGISTRATION).resolve():
            raise ValueError("S6 binding does not name the frozen preregistration")
        manifest_path = _bound_path(root, binding.evaluation_key_manifest, "S6 key manifest")
        if manifest_path != (root / S6_EVALUATION_MANIFEST).resolve():
            raise ValueError("S6 binding does not name the frozen key manifest")
        summarizer = _load_s6_summarizer(root)
        manifest, frozen_bindings = summarizer.load_and_verify_frozen_inputs(
            manifest_path,
            prereg_path,
            project_root=root,
        )
        rows = _read_jsonl(episodes_path, summarizer.M2CS6EpisodeEvidenceV1)
        # The strict summarizer loads every model execution receipt by its
        # gate-evidence hash.  The independent terminal manifest must contain
        # those same immutable files, so it cannot point the summarizer at an
        # unrelated receipt directory.
        receipt_roots: set[Path] = set()
        for row in rows:
            for decision in row.episode.decisions:
                digest = decision.gate_evidence_sha256.get("execution_outcome")
                if row.episode.method != "B0" and decision.model_decision:
                    if digest is None or digest not in inventory:
                        raise ValueError("S6 raw inventory lacks a model execution receipt")
                    receipt_path = inventory[digest]
                    if receipt_path.name != f"{digest}.json":
                        raise ValueError("S6 physical receipt file name is not its SHA-256")
                    receipt_roots.add(receipt_path.parent)
        if len(receipt_roots) != 1:
            raise ValueError("S6 physical receipts are not in one hash-addressed root")
        replayed = summarizer.summarize_s6(
            rows,
            frozen_manifest=manifest,
            frozen_bindings=frozen_bindings,
            physical_receipts_root=next(iter(receipt_roots)),
        )
        for field in (
            "status",
            "expected_methods",
            "complete_matched_keys",
            "qrm_model_decisions_executed",
            "collision_or_safety_violations",
            "method_metrics",
            "primary_metric",
            "secondary_metrics",
            "findings",
            "formal_evaluation_ready",
        ):
            if summary.get(field) != replayed.get(field):
                raise ValueError(f"S6 summary differs from strict replay: {field}")
        if replayed.get("formal_evaluation_ready") is not True:
            raise ValueError("S6 strict replay is not formal-evaluation ready")
        metrics = {
            "primary_metric": replayed["primary_metric"],
            "complete_matched_keys": replayed["complete_matched_keys"],
            "qrm_model_decisions_executed": replayed["qrm_model_decisions_executed"],
            "collision_or_safety_violations": replayed["collision_or_safety_violations"],
        }
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, KeyError) as error:
        blockers.append(f"S6 terminal evidence failed closed: {type(error).__name__}: {error}")
    return VerificationResult(not blockers, tuple(blockers), metrics)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
    )


def _git_file_matches_head(root: Path, path: Path, label: str) -> None:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"{label} is not inside the project repository") from error
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"HEAD:{relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"{label} is not committed at current Git HEAD")
    if result.stdout != path.read_bytes():
        raise ValueError(f"{label} differs between current Git HEAD and worktree")


def _junit_counts(path: Path) -> tuple[int, int]:
    xml = ET.parse(path).getroot()
    suites = [xml] if xml.tag == "testsuite" else list(xml.findall("testsuite"))
    if not suites:
        raise ValueError("full-test JUnit has no testsuite")
    tests = sum(int(item.attrib.get("tests", "0")) for item in suites)
    failed = sum(
        int(item.attrib.get("failures", "0")) + int(item.attrib.get("errors", "0"))
        for item in suites
    )
    return tests, failed


def _verify_b0_and_m2b(root: Path, binding: FinalVerificationBindingV1) -> None:
    freeze_path = root / B0_FREEZE_MANIFEST
    if _sha256(freeze_path) != binding.b0_freeze_manifest_sha256:
        raise ValueError("final verification B0 freeze manifest SHA-256 mismatch")
    freeze = _read_json(freeze_path)
    if freeze.get("schema_version") != "M2CB0FreezeManifestV1":
        raise ValueError("final verification B0 freeze schema changed")
    for group in ("b0_files", "m2b_local_artifacts"):
        entries = freeze.get(group)
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"B0 freeze has no {group}")
        for item in entries:
            path = _resolve(root, item["path"])
            if _sha256(path) != item["sha256"]:
                raise ValueError(f"final verification frozen file changed: {item['path']}")
    index = freeze.get("m2b_artifact_index") or {}
    index_path = _resolve(root, index.get("path", ""))
    actual_index_sha = _sha256(index_path)
    if (
        actual_index_sha != index.get("sha256")
        or actual_index_sha != binding.m2b_artifact_index_sha256
    ):
        raise ValueError("final verification M2B artifact index SHA-256 mismatch")


def verify_final(
    root: Path,
    verification: dict[str, Any] | None,
) -> VerificationResult:
    blockers: list[str] = []
    metrics: dict[str, Any] = {"tests_passed": 0, "tests_failed": None}
    try:
        if verification is None:
            raise ValueError("final verification receipt is absent")
        binding = FinalVerificationBindingV1.model_validate(verification.get("terminal_evidence"))
        head = _git(root, "rev-parse", "HEAD")
        if head.returncode != 0 or head.stdout.strip() != binding.checked_head_commit:
            raise ValueError("final verification was not run against current Git HEAD")
        command = binding.full_test_command
        forbidden_test_selectors = {
            "-k",
            "-m",
            "--collect-only",
            "--lf",
            "--ff",
            "--last-failed",
            "--failed-first",
        }
        if command[1:3] != ["-m", "pytest"] or any(
            argument.startswith("tests/")
            or argument.startswith("src/")
            or argument.startswith("scripts/")
            or argument.startswith("--ignore")
            or argument.startswith("--deselect")
            or "::" in argument
            or argument in forbidden_test_selectors
            for argument in command[3:]
        ):
            raise ValueError("final verification command is not the complete pytest suite")
        dirty = _git(root, "diff", "--quiet", "HEAD", "--")
        if dirty.returncode != 0:
            raise ValueError("final verification cannot pass with tracked worktree changes")
        untracked = _git(root, "ls-files", "--others", "--exclude-standard")
        protected_prefixes = ("src/", "scripts/", "tests/", "configs/", "schemas/", "docs/")
        if any(line.startswith(protected_prefixes) for line in untracked.stdout.splitlines()):
            raise ValueError("final verification cannot pass with untracked source/config files")
        junit_path = _bound_path(root, binding.junit, "full-test JUnit")
        passed, failed = _junit_counts(junit_path)
        tests = verification.get("tests") or {}
        if passed < 1 or failed != 0:
            raise ValueError("full-test JUnit is empty or failing")
        if tests.get("passed") != passed or tests.get("failed") != failed:
            raise ValueError("final verification test totals differ from JUnit replay")
        if verification.get("status") != "PASS":
            raise ValueError("final verification status is not PASS")
        _verify_b0_and_m2b(root, binding)
        metrics = {"tests_passed": passed, "tests_failed": failed}
    except (
        OSError,
        ET.ParseError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        KeyError,
    ) as error:
        blockers.append(f"final verification failed closed: {type(error).__name__}: {error}")
    return VerificationResult(not blockers, tuple(blockers), metrics)


def verify_terminal_evidence(
    root: Path,
    *,
    s4: dict[str, Any] | None,
    s5: dict[str, Any] | None,
    s6: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    d2_summary_claimed: bool,
) -> dict[str, VerificationResult]:
    """Return independent terminal-gate replays for ``status.py``."""

    s4_result = verify_s4(root, s4)
    d2_verified = bool(s4_result.passed and s4_result.metrics.get("d2_triggered"))
    if d2_verified and d2_summary_claimed:
        s5_result = VerificationResult(True, (), {"skipped_by_verified_d2": True})
    elif not s4_result.passed:
        s5_result = VerificationResult(
            False,
            ("S5 terminal evidence failed closed: a verified S4 governed disposition is required",),
            {"residual_gain_over_fc": None},
        )
    else:
        s5_result = verify_s5(root, s5)
    return {
        "s4": s4_result,
        "s5": s5_result,
        "s6": verify_s6(root, s6),
        "final": verify_final(root, verification),
    }
