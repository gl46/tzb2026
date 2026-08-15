from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any

import pytest

from test_m2c_formal_isaac_backend_v4 import _start_request
from test_m2c_formal_isaac_endpoint_v4 import (
    _Backend,
    _binding,
    _execute_request,
    _observations,
)
from test_m2c_formal_public_observation_provider_v4 import _packet
from test_m2c_path_blocked_supervision_v4 import attribute_binding, deployment
from xh_agent.policy.qrm_lite.executed_intent_history_v2 import (
    PublicExecutedIntentHistoryItemV2,
)
from xh_agent.policy.qrm_lite.formal_isaac_episode_io_v4 import (
    ACCEPTED_ADR_REPO_PATH,
    IMPLEMENTATION_REPO_PATH,
    PUBLIC_OBSERVATION_PROVIDER_REPO_PATH,
    FormalIsaacEpisodeIODeploymentBindingV1,
    FormalIsaacEpisodeIOV4,
    FormalIsaacSceneFinalEvidenceV4,
    FormalIsaacSceneStartEvidenceV4,
)
from xh_agent.policy.qrm_lite.formal_public_observation_provider_v4 import (
    FormalPublicCapturePacketV4,
    ReplayableFormalPublicObservationProviderV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacEndpointBindingV4,
    IsaacExecuteRequestV4,
    IsaacExecuteResponseV4,
    IsaacFinalizeRequestV4,
    IsaacStartRequestV4,
)
from xh_agent.policy.qrm_lite.skill_registry_v2 import load_registry_v2


ROOT = Path(__file__).resolve().parents[2]


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _committed_project(tmp_path: Path) -> tuple[Path, str]:
    project = tmp_path / "project"
    for relative in (
        IMPLEMENTATION_REPO_PATH,
        PUBLIC_OBSERVATION_PROVIDER_REPO_PATH,
        ACCEPTED_ADR_REPO_PATH,
    ):
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    _run_git(project, "init", "-q")
    _run_git(project, "config", "user.name", "M2C Contract Test")
    _run_git(project, "config", "user.email", "m2c-contract@example.invalid")
    _run_git(project, "add", ".")
    _run_git(project, "commit", "-q", "-m", "freeze episode io fixture")
    return project, _run_git(project, "rev-parse", "HEAD")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _association(source_sha256: str):  # noqa: ANN202
    raw = deployment().model_dump(mode="json")
    raw["capture_source_implementation_sha256"] = source_sha256
    raw["deployment_binding_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "deployment_binding_sha256"}
    )
    return type(deployment()).model_validate(raw)


def _deployment_fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    FormalIsaacEpisodeIODeploymentBindingV1,
    IsaacEndpointBindingV4,
    Any,
    Any,
]:
    project, commit = _committed_project(tmp_path)
    lifecycle_sha = _sha(project / IMPLEMENTATION_REPO_PATH)
    provider_sha = _sha(project / PUBLIC_OBSERVATION_PROVIDER_REPO_PATH)
    adr_sha = _sha(project / ACCEPTED_ADR_REPO_PATH)
    association = _association(lifecycle_sha)
    declared_attribute = attribute_binding()
    endpoint_raw = _binding(_observations()[0]).model_dump(mode="json")
    endpoint_raw.update(
        physical_backend_path=IMPLEMENTATION_REPO_PATH,
        physical_backend_sha256=lifecycle_sha,
        public_observation_provider_path=PUBLIC_OBSERVATION_PROVIDER_REPO_PATH,
        public_observation_provider_sha256=provider_sha,
        capture_source_implementation_sha256=lifecycle_sha,
        association_deployment_sha256=association.deployment_binding_sha256,
        declared_attribute_selector_implementation_sha256=(
            declared_attribute.selector_source_implementation_sha256
        ),
        immutable_commit=commit,
        container_image_digest="sha256:" + "a" * 64,
        transitive_dependency_manifest_sha256="b" * 64,
    )
    endpoint = IsaacEndpointBindingV4.model_validate(endpoint_raw)
    payload: dict[str, Any] = {
        "schema_version": "FormalIsaacEpisodeIODeploymentBindingV1",
        "accepted_adr_path": ACCEPTED_ADR_REPO_PATH,
        "accepted_adr_sha256": adr_sha,
        "lifecycle_implementation_path": IMPLEMENTATION_REPO_PATH,
        "lifecycle_implementation_sha256": lifecycle_sha,
        "scene_owner_implementation_path": IMPLEMENTATION_REPO_PATH,
        "scene_owner_implementation_sha256": lifecycle_sha,
        "capture_source_implementation_path": IMPLEMENTATION_REPO_PATH,
        "capture_source_implementation_sha256": lifecycle_sha,
        "public_observation_provider_path": PUBLIC_OBSERVATION_PROVIDER_REPO_PATH,
        "public_observation_provider_sha256": provider_sha,
        "endpoint_binding_sha256": canonical_sha256(endpoint),
        "association_deployment_sha256": association.deployment_binding_sha256,
        "declared_attribute_binding_sha256": declared_attribute.binding_sha256,
        "immutable_commit": commit,
        "container_image_digest": endpoint.container_image_digest,
        "transitive_dependency_manifest_sha256": (endpoint.transitive_dependency_manifest_sha256),
        "review_status": "REVIEWED_BINDING_ADDENDUM",
        "formal_execution_eligible": True,
        "real_isaac": True,
        "mocked_physics": False,
        "simulator_identity_exposed_to_model": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    binding = FormalIsaacEpisodeIODeploymentBindingV1(
        **payload,
        deployment_binding_sha256=canonical_sha256(payload),
    )
    return project, binding, endpoint, association, declared_attribute


def _execution_responses(tmp_path: Path, endpoint: IsaacEndpointBindingV4):
    observations = _observations()
    backend = _Backend(
        tmp_path=tmp_path,
        binding=endpoint,
        observations=observations,
    )
    registry = load_registry_v2(ROOT / "configs/qrm_runtime_mapping_v2.yaml")
    history: tuple[PublicExecutedIntentHistoryItemV2, ...] = ()
    responses: list[IsaacExecuteResponseV4] = []
    for index, observation in enumerate(observations):
        response = backend.execute(
            _execute_request(observation, index=index, history=history),
            registry,
        )
        responses.append(response)
        if index < 7:
            history = (
                *history,
                PublicExecutedIntentHistoryItemV2(
                    decision_index=index,
                    selected_skill=str(response.mapping.canonical_skill),
                    target_track_id=response.mapping.target_track_id,
                    destination_cell=None,
                    physical_receipt_sha256=(response.execution_receipts[0].receipt_sha256),
                    execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
                ),
            )
    return tuple(responses), observations


class _Owner:
    real_isaac = True
    mocked_physics = False

    def __init__(
        self,
        *,
        implementation_sha256: str,
        packets: list[FormalPublicCapturePacketV4],
    ) -> None:
        self.implementation_sha256 = implementation_sha256
        self.capture_source_implementation_sha256 = implementation_sha256
        self.packets = packets
        self.start_calls = 0
        self.capture_calls = 0
        self.final_calls = 0
        self.execution_commits: list[tuple[IsaacExecuteRequestV4, Any]] = []

    def establish_public_failure_boundary_v4(
        self,
        request: IsaacStartRequestV4,
    ) -> FormalIsaacSceneStartEvidenceV4:
        self.start_calls += 1
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacSceneStartEvidenceV4",
            "run_id": request.run_id,
            "session_id": "formal-episode-io-session",
            "start_request_sha256": canonical_sha256(request),
            "endpoint_binding_sha256": request.endpoint_binding_sha256,
            "scene_owner_implementation_sha256": self.implementation_sha256,
            "matched_key": request.matched_key,
            "scene_seed": request.scene_seed,
            "failure_seed": request.failure_seed,
            "sdf_sha256": request.sdf_sha256,
            "supervision_sha256": request.supervision_sha256,
            "declared_attribute_binding_sha256": (request.declared_attribute_binding_sha256),
            "failure_observed_at_ns": 50,
            "public_failure_boundary_evidence_sha256": "c" * 64,
            "real_isaac": True,
            "mocked_physics": False,
            "failure_boundary_derived_from_public_observation": True,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return FormalIsaacSceneStartEvidenceV4(
            **payload,
            evidence_sha256=canonical_sha256(payload),
        )

    def capture_public_v4(self, **_kwargs: Any) -> FormalPublicCapturePacketV4:
        self.capture_calls += 1
        return self.packets.pop(0)

    def commit_public_execution_v4(
        self,
        *,
        request: IsaacExecuteRequestV4,
        receipt: Any,
    ) -> None:
        self.execution_commits.append((request, receipt))

    def evaluate_public_outcome_v4(
        self,
        request: IsaacFinalizeRequestV4,
        *,
        execution_responses: tuple[IsaacExecuteResponseV4, ...],
    ) -> FormalIsaacSceneFinalEvidenceV4:
        self.final_calls += 1
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacSceneFinalEvidenceV4",
            "run_id": request.run_id,
            "session_id": request.session_id,
            "finalize_request_sha256": canonical_sha256(request),
            "scene_owner_implementation_sha256": self.implementation_sha256,
            "last_execution_receipt_sha256": request.last_execution_receipt_sha256,
            "last_bundle_execution_receipt_sha256": (request.last_bundle_execution_receipt_sha256),
            "execution_response_sha256": tuple(
                canonical_sha256(item) for item in execution_responses
            ),
            "public_evaluation_evidence_sha256": "d" * 64,
            "evaluated_at_ns": 9_000,
            "final_task_success": False,
            "real_isaac": True,
            "mocked_physics": False,
            "outcome_used_as_policy_input": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return FormalIsaacSceneFinalEvidenceV4(
            **payload,
            evidence_sha256=canonical_sha256(payload),
        )


def _packets(
    *,
    source_sha256: str,
    responses: tuple[IsaacExecuteResponseV4, ...],
    observations: list[Any],
) -> list[FormalPublicCapturePacketV4]:
    packets: list[FormalPublicCapturePacketV4] = []
    for index, observation in enumerate(observations):
        previous_completed = (
            50 if index == 0 else responses[index - 1].execution_receipts[0].completed_at_ns
        )
        capture = observation.observation.association_history[-1].capture
        raw = _packet(
            index,
            capture,
            previous_completed_at_ns=previous_completed,
            source_sha256=source_sha256,
        ).model_dump(mode="json")
        raw.update(
            run_id="contract-v4-run",
            session_id="formal-episode-io-session",
            observation_id=f"formal-episode-io-observation-{index}",
            real_isaac=True,
            mocked_physics=False,
            contract_test_only=False,
        )
        packets.append(FormalPublicCapturePacketV4.model_validate(raw))
    return packets


def test_episode_io_binds_one_scene_owner_across_start_capture_and_finalize(
    tmp_path: Path,
) -> None:
    project, binding, endpoint, association, declared_attribute = _deployment_fixture(tmp_path)
    responses, observations = _execution_responses(tmp_path, endpoint)
    owner = _Owner(
        implementation_sha256=binding.scene_owner_implementation_sha256,
        packets=_packets(
            source_sha256=binding.capture_source_implementation_sha256,
            responses=responses,
            observations=observations,
        ),
    )
    episode_io = FormalIsaacEpisodeIOV4(
        project_root=project,
        mode="REAL_ISAAC",
        binding=binding,
        endpoint_binding=endpoint,
        association_deployment=association,
        declared_attribute_binding=declared_attribute,
        owner=owner,
    )
    start_request = _start_request(endpoint)
    start = episode_io.lifecycle.start_episode(start_request)
    assert start.public_failure_boundary_evidence_sha256 == "c" * 64
    provider = ReplayableFormalPublicObservationProviderV4(
        mode="REAL_ISAAC",
        source=episode_io.capture_source,
        association_deployment=association,
        declared_attribute_binding=declared_attribute,
    )
    provider.begin_session(run_id=start.run_id, session_id=start.session_id)
    history: tuple[PublicExecutedIntentHistoryItemV2, ...] = ()
    for index, response in enumerate(responses):
        previous_completed = (
            50 if index == 0 else responses[index - 1].execution_receipts[0].completed_at_ns
        )
        observation = provider.capture(
            run_id=start.run_id,
            session_id=start.session_id,
            decision_index=index,
            previous_execution_completed_at_ns=previous_completed,
        )
        assert len(observation.observation.association_history) == index + 1
        assert observation.observation.capture_receipt_sha256 == (
            observations[index].observation.capture_receipt_sha256
        )
        execution_request = _execute_request(
            observation,
            index=index,
            history=history,
        ).model_copy(update={"session_id": start.session_id})
        receipt_payload = response.execution_receipts[0].model_dump(mode="json")
        receipt_payload["receipt_id"] = f"{start.session_id}-execution-{index}"
        receipt_payload["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in receipt_payload.items() if key != "receipt_sha256"}
        )
        execution_receipt = type(response.execution_receipts[0]).model_validate(receipt_payload)
        episode_io.lifecycle.commit_public_execution_v4(
            request=execution_request,
            receipt=execution_receipt,
        )
        if index < 7:
            history = (
                *history,
                PublicExecutedIntentHistoryItemV2(
                    decision_index=index,
                    selected_skill=str(response.mapping.canonical_skill),
                    target_track_id=response.mapping.target_track_id,
                    destination_cell=None,
                    physical_receipt_sha256=response.execution_receipts[0].receipt_sha256,
                    execution_attribution="MODEL_SELECTED_REGISTERED_SKILL",
                ),
            )
    last = responses[-1]
    finalize_request = IsaacFinalizeRequestV4(
        run_id=start.run_id,
        session_id=start.session_id,
        last_execution_receipt_sha256=last.execution_receipts[0].receipt_sha256,
        last_bundle_execution_receipt_sha256=last.bundle_execution_receipt_sha256,
    )
    final = episode_io.lifecycle.finalize_episode(
        finalize_request,
        execution_responses=responses,
    )
    assert final.final_task_success is False
    assert final.public_evaluation_evidence_sha256 == "d" * 64
    assert (owner.start_calls, owner.capture_calls, owner.final_calls) == (1, 8, 1)
    assert len(owner.execution_commits) == 8


def test_episode_io_rejects_source_drift_before_owner_contact(tmp_path: Path) -> None:
    project, binding, endpoint, association, declared_attribute = _deployment_fixture(tmp_path)
    target = project / PUBLIC_OBSERVATION_PROVIDER_REPO_PATH
    target.write_text(target.read_text() + "\n# drift\n")
    owner = _Owner(
        implementation_sha256=binding.scene_owner_implementation_sha256,
        packets=[],
    )
    with pytest.raises(ValueError, match="source hash differs"):
        FormalIsaacEpisodeIOV4(
            project_root=project,
            mode="REAL_ISAAC",
            binding=binding,
            endpoint_binding=endpoint,
            association_deployment=association,
            declared_attribute_binding=declared_attribute,
            owner=owner,
        )
    assert owner.start_calls == 0


def test_episode_io_rejects_contract_binding_as_real_deployment(tmp_path: Path) -> None:
    project, binding, endpoint, association, declared_attribute = _deployment_fixture(tmp_path)
    raw = binding.model_dump(mode="json")
    raw.update(
        review_status="CONTRACT_TEST_ONLY",
        formal_execution_eligible=False,
        real_isaac=False,
        mocked_physics=True,
    )
    raw["deployment_binding_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "deployment_binding_sha256"}
    )
    contract = FormalIsaacEpisodeIODeploymentBindingV1.model_validate(raw)
    owner = _Owner(
        implementation_sha256=binding.scene_owner_implementation_sha256,
        packets=[],
    )
    with pytest.raises(ValueError, match="reviewed real deployment"):
        FormalIsaacEpisodeIOV4(
            project_root=project,
            mode="REAL_ISAAC",
            binding=contract,
            endpoint_binding=endpoint,
            association_deployment=association,
            declared_attribute_binding=declared_attribute,
            owner=owner,
        )


def test_episode_io_start_evidence_mismatch_consumes_attempt(tmp_path: Path) -> None:
    project, binding, endpoint, association, declared_attribute = _deployment_fixture(tmp_path)
    owner = _Owner(
        implementation_sha256=binding.scene_owner_implementation_sha256,
        packets=[],
    )
    original = owner.establish_public_failure_boundary_v4

    def crossed(request: IsaacStartRequestV4) -> FormalIsaacSceneStartEvidenceV4:
        evidence = original(request)
        raw = evidence.model_dump(mode="json")
        raw["matched_key"] = "crossed-key"
        raw["evidence_sha256"] = canonical_sha256(
            {key: value for key, value in raw.items() if key != "evidence_sha256"}
        )
        return FormalIsaacSceneStartEvidenceV4.model_validate(raw)

    owner.establish_public_failure_boundary_v4 = crossed  # type: ignore[method-assign]
    episode_io = FormalIsaacEpisodeIOV4(
        project_root=project,
        mode="REAL_ISAAC",
        binding=binding,
        endpoint_binding=endpoint,
        association_deployment=association,
        declared_attribute_binding=declared_attribute,
        owner=owner,
    )
    request = _start_request(endpoint)
    with pytest.raises(ValueError, match="crosses request/deployment"):
        episode_io.lifecycle.start_episode(request)
    with pytest.raises(RuntimeError, match="poisoned"):
        episode_io.lifecycle.start_episode(request)
    assert owner.start_calls == 1
