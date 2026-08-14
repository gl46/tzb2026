from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256
from xh_agent.policy.qrm_lite import lula_query_only_ik_v1 as subject
from xh_agent.policy.qrm_lite.lula_query_only_ik_v1 import (
    ActiveSessionMutationCountersV1,
    IsaacLulaNativeIKKernelV1,
    LULA_END_EFFECTOR_FRAME,
    LULA_JOINT_NAMES,
    LULA_PIP_PREBUNDLE,
    LulaImageFileBindingV1,
    LulaNativeIKResultV1,
    LulaQueryMutationDetected,
    LulaQueryOnlyIKCoordinatorV1,
    LulaQueryOnlyIKUnavailable,
    LulaQueryOnlySourceClosureV1,
    build_lula_query_only_ik_request_v1,
    canonical_lula_query_only_ik_configuration_v1,
    inspect_lula_query_only_source_closure_v1,
)


PROJECT_ROOT = Path(__file__).parents[2]
IMPLEMENTATION = PROJECT_ROOT / "src/xh_agent/policy/qrm_lite/lula_query_only_ik_v1.py"


def _closure() -> LulaQueryOnlySourceClosureV1:
    files = tuple(
        LulaImageFileBindingV1(
            role=role,
            path=path,
            sha256=sha256,
            size_bytes=size,
        )
        for role, path, sha256, size in subject._EXPECTED_IMAGE_FILES
    )
    payload: dict[str, Any] = {
        "schema_version": "LulaQueryOnlySourceClosureV1",
        "image_digest": subject.ISAAC_6_0_1_IMAGE_DIGEST,
        "files": files,
        "native_module_path": (f"{LULA_PIP_PREBUNDLE}/lula.cpython-312-x86_64-linux-gnu.so"),
        "robot_descriptor_path": subject.LULA_ROBOT_DESCRIPTOR,
        "robot_description_path": subject.LULA_ROBOT_DESCRIPTION,
        "joint_names": LULA_JOINT_NAMES,
        "end_effector_frame": LULA_END_EFFECTOR_FRAME,
        "scene_opened": False,
        "controller_called": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return LulaQueryOnlySourceClosureV1(
        **payload,
        source_closure_sha256=subject._canonical_payload_sha256(payload),
    )


def _request(
    closure: LulaQueryOnlySourceClosureV1,
    *,
    target_position: tuple[float, float, float] = (0.2, 0.0, 0.5),
):
    return build_lula_query_only_ik_request_v1(
        request_id="run/session/decision-0/sample-0",
        warm_start_joint_positions_rad=(0.0, -1.3, 0.0, -2.87, 0.0, 2.0, 0.75),
        target_position_robot_base_m=target_position,
        target_orientation_robot_base_wxyz=(1.0, 0.0, 0.0, 0.0),
        configuration=canonical_lula_query_only_ik_configuration_v1(),
        source_closure_sha256=closure.source_closure_sha256,
    )


class _Counters:
    implementation_sha256 = "e" * 64
    real_active_session_source = False
    mocked_counter_source = True

    def __init__(self, values: list[ActiveSessionMutationCountersV1] | None = None) -> None:
        self.values = values or [_counter()]
        self.index = 0

    def snapshot_mutation_counters(self) -> ActiveSessionMutationCountersV1:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


def _counter(**updates: int) -> ActiveSessionMutationCountersV1:
    payload = {
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "controller_commands": 0,
        "attachment_mutations": 0,
    }
    payload.update(updates)
    return ActiveSessionMutationCountersV1(**payload)


class _Kernel:
    joint_names = LULA_JOINT_NAMES
    frame_names = ("panda_link0", LULA_END_EFFECTOR_FRAME)
    implementation_sha256 = "f" * 64
    source_closure_sha256 = "0" * 64
    real_runtime_provider = False
    mocked_kernel = True

    def __init__(
        self,
        *,
        native_success: bool = True,
        achieved_position: tuple[float, float, float] = (0.2, 0.0, 0.5),
        fail: bool = False,
    ) -> None:
        self.native_success = native_success
        self.achieved_position = achieved_position
        self.fail = fail

    def solve(self, request: Any) -> LulaNativeIKResultV1:
        if self.fail:
            raise RuntimeError("native failure")
        return LulaNativeIKResultV1(
            native_success=self.native_success,
            solution_joint_positions_rad=request.warm_start_joint_positions_rad,
            native_position_error=math.dist(
                request.target_position_robot_base_m, self.achieved_position
            ),
            native_axis_orientation_errors=(0.0, 0.0, 0.0),
            num_descents=1,
            achieved_position_robot_base_m=self.achieved_position,
            achieved_orientation_robot_base_matrix=(
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ),
        )


def _coordinator(
    *,
    kernel: _Kernel | Any | None = None,
    counters: _Counters | None = None,
) -> LulaQueryOnlyIKCoordinatorV1:
    return LulaQueryOnlyIKCoordinatorV1(
        source_closure=_closure(),
        kernel=kernel or _Kernel(),
        counter_source=counters or _Counters(),
        mode="CONTRACT_TEST",
        adapter_implementation_path=IMPLEMENTATION,
    )


def test_configuration_is_fully_explicit_and_bounded_to_one_descent() -> None:
    config = canonical_lula_query_only_ik_configuration_v1()
    assert config.ccd_max_iterations == 32
    assert config.bfgs_max_iterations == 32
    assert config.maximum_descents == 1
    assert config.certified_iteration_upper_bound == 64
    assert config.deterministic_sampling_seed == 0
    assert config.query_frame == "robot_base"


def test_request_rejects_non_normalized_orientation_and_digest_tamper() -> None:
    request = _request(_closure())
    raw = request.model_dump(mode="json")
    raw["target_orientation_robot_base_wxyz"] = [2.0, 0.0, 0.0, 0.0]
    with pytest.raises(ValidationError, match="not normalized"):
        type(request).model_validate(raw)

    raw = request.model_dump(mode="json")
    raw["request_id"] = "tampered"
    with pytest.raises(ValidationError, match="request digest"):
        type(request).model_validate(raw)


def test_query_receipt_is_non_actuating_and_independently_replays_residual() -> None:
    closure = _closure()
    receipt = _coordinator().solve(_request(closure))
    assert receipt.accepted is True
    assert receipt.native_success is True
    assert receipt.position_residual_m == 0.0
    assert receipt.orientation_residual_rad == 0.0
    assert receipt.certified_iteration_upper_bound == 64
    assert receipt.mutation_counters_before == receipt.mutation_counters_after
    assert receipt.articulation_target_writes == 0
    assert receipt.simulation_steps == 0
    assert receipt.scene_mutations == 0
    assert receipt.controller_commands == 0
    assert receipt.attachment_mutations == 0
    assert receipt.whole_plan_authorization_claimed is False
    assert receipt.physical_execution_claimed is False
    assert receipt.formal_query_evidence_eligible is False
    assert receipt.teacher_used is False
    assert receipt.privileged_truth_policy_input is False


@pytest.mark.parametrize(
    ("kernel", "expected_native_success"),
    [
        (_Kernel(native_success=False), False),
        (_Kernel(achieved_position=(0.25, 0.0, 0.5)), True),
    ],
)
def test_native_failure_or_independent_residual_rejects_without_action(
    kernel: _Kernel, expected_native_success: bool
) -> None:
    closure = _closure()
    receipt = _coordinator(kernel=kernel).solve(_request(closure))
    assert receipt.native_success is expected_native_success
    assert receipt.accepted is False
    assert receipt.physical_execution_claimed is False


def test_counter_change_rejects_success_and_exception_paths() -> None:
    changed = _counter(simulation_steps=1)
    with pytest.raises(LulaQueryMutationDetected, match="mutated"):
        _coordinator(counters=_Counters([_counter(), changed])).solve(_request(_closure()))

    with pytest.raises(LulaQueryMutationDetected, match="before failing"):
        _coordinator(
            kernel=_Kernel(fail=True),
            counters=_Counters([_counter(), changed]),
        ).solve(_request(_closure()))


def test_kernel_exception_without_mutation_is_fail_closed() -> None:
    with pytest.raises(LulaQueryOnlyIKUnavailable, match="native Lula query failed"):
        _coordinator(kernel=_Kernel(fail=True)).solve(_request(_closure()))


def test_contract_fixture_cannot_claim_real_runtime() -> None:
    kernel = _Kernel()
    kernel.real_runtime_provider = True
    kernel.mocked_kernel = False
    with pytest.raises(LulaQueryOnlyIKUnavailable, match="contract Lula coordinator"):
        _coordinator(kernel=kernel)


@pytest.mark.parametrize(
    "kernel",
    [
        SimpleNamespace(joint_names=("wrong",), frame_names=(LULA_END_EFFECTOR_FRAME,)),
        SimpleNamespace(joint_names=LULA_JOINT_NAMES, frame_names=("panda_link0",)),
    ],
)
def test_kernel_identity_is_exact_before_any_query(kernel: Any) -> None:
    with pytest.raises(LulaQueryOnlyIKUnavailable, match="joint order|panda_hand"):
        _coordinator(kernel=kernel)


def test_source_closure_schema_rejects_missing_or_reordered_files() -> None:
    closure = _closure()
    raw = closure.model_dump(mode="json")
    raw["files"] = list(reversed(raw["files"]))
    raw["source_closure_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "source_closure_sha256"}
    )
    with pytest.raises(ValidationError, match="file set differs"):
        LulaQueryOnlySourceClosureV1.model_validate(raw)


def test_source_closure_inspector_fails_before_import_on_missing_bytes(tmp_path: Path) -> None:
    with pytest.raises(LulaQueryOnlyIKUnavailable, match="cannot be opened"):
        inspect_lula_query_only_source_closure_v1(
            image_root=tmp_path,
            image_digest=subject.ISAAC_6_0_1_IMAGE_DIGEST,
        )


class _FakeRotation:
    def __init__(self, matrix: Any) -> None:
        self._matrix = np.asarray(matrix, dtype=np.float64)

    def matrix(self) -> np.ndarray:
        return self._matrix


class _FakePose:
    def __init__(self, rotation: _FakeRotation, translation: Any) -> None:
        self.rotation = rotation
        self.translation = np.asarray(translation, dtype=np.float64)


class _FakeConfig:
    def __init__(self) -> None:
        self.bfgs_cspace_limit_biasing = "CSpaceLimitBiasing.AUTO"


class _FakeKinematics:
    def frame_names(self) -> list[str]:
        return ["panda_link0", LULA_END_EFFECTOR_FRAME]

    def pose(self, joint_positions: Any, frame_name: str) -> _FakePose:
        assert np.asarray(joint_positions).shape == (7, 1)
        assert frame_name == LULA_END_EFFECTOR_FRAME
        return _FakePose(_FakeRotation(np.eye(3)), (0.2, 0.0, 0.5))


class _FakeRobot:
    def __init__(self) -> None:
        self._kinematics = _FakeKinematics()

    def kinematics(self) -> _FakeKinematics:
        return self._kinematics

    def num_c_space_coords(self) -> int:
        return 7

    def c_space_coord_name(self, index: int) -> str:
        return LULA_JOINT_NAMES[index]


def test_native_kernel_maps_every_frozen_config_and_replays_fk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closure = _closure()
    module_path = tmp_path / LULA_PIP_PREBUNDLE / "lula.cpython-312-x86_64-linux-gnu.so"
    module_path.parent.mkdir(parents=True)
    module_path.touch()
    robot = _FakeRobot()
    captured: dict[str, Any] = {}

    def compute(kinematics: Any, pose: Any, frame: str, config: Any) -> Any:
        captured.update(vars(config))
        assert kinematics is robot.kinematics()
        assert frame == LULA_END_EFFECTOR_FRAME
        assert np.allclose(pose.rotation.matrix(), np.eye(3))
        assert np.allclose(pose.translation, (0.2, 0.0, 0.5))
        return SimpleNamespace(
            success=True,
            cspace_position=np.asarray((0.0, -1.3, 0.0, -2.87, 0.0, 2.0, 0.75)),
            position_error=0.0,
            x_axis_orientation_error=0.0,
            y_axis_orientation_error=0.0,
            z_axis_orientation_error=0.0,
            num_descents=1,
        )

    fake_lula = SimpleNamespace(
        __file__=str(module_path),
        load_robot=lambda descriptor, urdf: robot,
        CyclicCoordDescentIkConfig=_FakeConfig,
        Pose3=_FakePose,
        Rotation3=_FakeRotation,
        compute_ik_ccd=compute,
    )
    monkeypatch.setattr(
        subject,
        "inspect_lula_query_only_source_closure_v1",
        lambda **kwargs: closure,
    )
    kernel = IsaacLulaNativeIKKernelV1(
        image_root=tmp_path,
        source_closure=closure,
        lula_module=fake_lula,
    )
    result = kernel.solve(_request(closure))
    assert result.native_success is True
    assert result.achieved_position_robot_base_m == (0.2, 0.0, 0.5)
    assert captured["ccd_max_iterations"] == 32
    assert captured["bfgs_max_iterations"] == 32
    assert captured["max_num_descents"] == 1
    assert captured["sampling_seed"] == 0
    assert captured["cspace_seeds"][0].shape == (7,)

    receipt = LulaQueryOnlyIKCoordinatorV1(
        source_closure=closure,
        kernel=kernel,
        counter_source=_Counters(),
        mode="STARTUP_SMOKE",
        adapter_implementation_path=IMPLEMENTATION,
    ).solve(_request(closure))
    assert receipt.formal_query_evidence_eligible is False
    assert receipt.real_runtime_provider is True
    assert receipt.mocked_kernel is False

    with pytest.raises(LulaQueryOnlyIKUnavailable, match="REAL_ISAAC.*dependency"):
        LulaQueryOnlyIKCoordinatorV1(
            source_closure=closure,
            kernel=kernel,
            counter_source=_Counters(),
            mode="REAL_ISAAC",
            adapter_implementation_path=IMPLEMENTATION,
        )


def test_module_has_no_isaac_scene_or_controller_import() -> None:
    source = IMPLEMENTATION.read_text(encoding="utf-8")
    assert "from isaacsim" not in source
    assert "SimulationApp" not in source
    assert ".apply_action(" not in source
    assert ".set_dof_" not in source
