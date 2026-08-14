"""Query-only Lula IK contract for the ADR-0024 Phase-2 preflight.

This module deliberately imports no Isaac extension and opens no USD stage at
module import time.  The production kernel loads the byte-pinned Lula native
module directly from the immutable Isaac Sim image, operates in the robot-base
frame, and recomputes the achieved pose with the same read-only kinematics
object.  A caller-supplied active-session counter source is sampled before and
after every query; any target write, simulation step, scene mutation,
controller command, or attachment mutation rejects the result.

The receipt proves a single non-actuating IK query only.  It is not an A.3
whole-plan receipt and cannot by itself authorize execution.
"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Literal, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


ISAAC_6_0_1_IMAGE_DIGEST = "sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9"
LULA_PIP_PREBUNDLE = "extsDeprecated/isaacsim.robot_motion.lula/pip_prebundle"
LULA_ROBOT_DESCRIPTOR = (
    "extsDeprecated/isaacsim.robot_motion.motion_generation/motion_policy_configs/"
    "franka/rmpflow/robot_descriptor.yaml"
)
LULA_ROBOT_DESCRIPTION = (
    "extsDeprecated/isaacsim.robot_motion.motion_generation/motion_policy_configs/"
    "franka/lula_franka_gen.urdf"
)
LULA_JOINT_NAMES = (
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
)
LULA_END_EFFECTOR_FRAME = "panda_hand"

_EXPECTED_IMAGE_FILES: tuple[tuple[str, str, str, int], ...] = (
    (
        "LULA_KINEMATICS_PYTHON_WRAPPER",
        "extsDeprecated/isaacsim.robot_motion.motion_generation/isaacsim/robot_motion/"
        "motion_generation/lula/kinematics.py",
        "e5a33c21634f9d9c761aa4fd122f7245c78eab0b4bcc010d63e17668d2ec43c5",
        25397,
    ),
    (
        "LULA_INTERFACE_HELPER",
        "extsDeprecated/isaacsim.robot_motion.motion_generation/isaacsim/robot_motion/"
        "motion_generation/lula/interface_helper.py",
        "d99b4e6136eac8b5ed72b4652a9e302f6650316f5e1da0bf622097557a7d21a2",
        8057,
    ),
    (
        "LULA_PYTHON_EXTENSION",
        f"{LULA_PIP_PREBUNDLE}/lula.cpython-312-x86_64-linux-gnu.so",
        "40f10561eb4ef404ae6b9034c6d692bbfced12cc78ba3e68ea4a88336b26ba11",
        8026832,
    ),
    (
        "LULA_KINEMATICS_LIBRARY",
        f"{LULA_PIP_PREBUNDLE}/_lula_libs/liblula_kinematics.so",
        "197c48f8388a33df94c88a4f37fd30715e745ae89e56d30e585b5d7515f3cfa1",
        750568,
    ),
    (
        "LULA_MATH_LIBRARY",
        f"{LULA_PIP_PREBUNDLE}/_lula_libs/liblula_math.so",
        "c18c9659f92e1d3b14ce7a27315193bcb17fbee8949978cf73162e1813b71084",
        684184,
    ),
    (
        "LULA_UTIL_LIBRARY",
        f"{LULA_PIP_PREBUNDLE}/_lula_libs/liblula_util.so",
        "c7a5244e64fb257d095b10e4b91d6adb645014505bd87bfcb75ee1a407e91ed2",
        340704,
    ),
    (
        "LULA_ROBOT_DESCRIPTOR",
        LULA_ROBOT_DESCRIPTOR,
        "e4e1125a73be58093f5b496ceca843abd0a752701ff276e5661b8cb54cdc3355",
        5490,
    ),
    (
        "LULA_ROBOT_DESCRIPTION",
        LULA_ROBOT_DESCRIPTION,
        "e9024642e7952cbcaec0ae14425bf1cd19d674d3c98eeef3793913f63a8101b6",
        14771,
    ),
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LulaQueryOnlyIKUnavailable(RuntimeError):
    """The native query or its immutable closure could not be proven."""


class LulaQueryMutationDetected(LulaQueryOnlyIKUnavailable):
    """A nominal query changed an active-session mutation counter."""


def _canonical_model_sha256(model: BaseModel, digest_field: str) -> str:
    return canonical_sha256(model.model_dump(mode="json", exclude={digest_field}))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_payload_sha256(value: Any) -> str:
    return canonical_sha256(_jsonable(value))


def _read_regular_file_once(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LulaQueryOnlyIKUnavailable(f"Lula closure file cannot be opened: {path}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise LulaQueryOnlyIKUnavailable(f"Lula closure file is not unique/regular: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise LulaQueryOnlyIKUnavailable(f"Lula closure file changed while read: {path}")
    return b"".join(chunks)


class LulaImageFileBindingV1(FrozenModel):
    role: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    path: str = Field(pattern=r"^[^/][^\n]*$")
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(gt=0)


class LulaQueryOnlySourceClosureV1(FrozenModel):
    schema_version: Literal["LulaQueryOnlySourceClosureV1"] = "LulaQueryOnlySourceClosureV1"
    image_digest: Literal[ISAAC_6_0_1_IMAGE_DIGEST] = ISAAC_6_0_1_IMAGE_DIGEST
    files: tuple[LulaImageFileBindingV1, ...] = Field(
        min_length=len(_EXPECTED_IMAGE_FILES), max_length=len(_EXPECTED_IMAGE_FILES)
    )
    native_module_path: str
    robot_descriptor_path: Literal[LULA_ROBOT_DESCRIPTOR] = LULA_ROBOT_DESCRIPTOR
    robot_description_path: Literal[LULA_ROBOT_DESCRIPTION] = LULA_ROBOT_DESCRIPTION
    joint_names: tuple[str, ...] = LULA_JOINT_NAMES
    end_effector_frame: Literal[LULA_END_EFFECTOR_FRAME] = LULA_END_EFFECTOR_FRAME
    source_closure_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_opened: Literal[False] = False
    controller_called: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def exact_and_canonical(self) -> "LulaQueryOnlySourceClosureV1":
        actual = tuple((item.role, item.path, item.sha256, item.size_bytes) for item in self.files)
        if actual != _EXPECTED_IMAGE_FILES:
            raise ValueError("Lula source closure file set differs")
        expected_module = f"{LULA_PIP_PREBUNDLE}/lula.cpython-312-x86_64-linux-gnu.so"
        if self.native_module_path != expected_module or self.joint_names != LULA_JOINT_NAMES:
            raise ValueError("Lula source closure runtime identity differs")
        if self.source_closure_sha256 != _canonical_model_sha256(self, "source_closure_sha256"):
            raise ValueError("Lula source closure digest differs")
        return self


def inspect_lula_query_only_source_closure_v1(
    *, image_root: Path, image_digest: str
) -> LulaQueryOnlySourceClosureV1:
    """Verify the exact direct-Lula source/asset bytes without importing Isaac."""

    if image_digest != ISAAC_6_0_1_IMAGE_DIGEST:
        raise LulaQueryOnlyIKUnavailable("Lula query image digest differs")
    root = image_root.resolve()
    bindings: list[LulaImageFileBindingV1] = []
    for role, relative, expected_sha256, expected_size in _EXPECTED_IMAGE_FILES:
        raw = _read_regular_file_once(root / relative)
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256 or len(raw) != expected_size:
            raise LulaQueryOnlyIKUnavailable(f"Lula closure file bytes differ: {role}")
        bindings.append(
            LulaImageFileBindingV1(
                role=role,
                path=relative,
                sha256=actual_sha256,
                size_bytes=len(raw),
            )
        )
    payload: dict[str, Any] = {
        "schema_version": "LulaQueryOnlySourceClosureV1",
        "image_digest": image_digest,
        "files": bindings,
        "native_module_path": (f"{LULA_PIP_PREBUNDLE}/lula.cpython-312-x86_64-linux-gnu.so"),
        "robot_descriptor_path": LULA_ROBOT_DESCRIPTOR,
        "robot_description_path": LULA_ROBOT_DESCRIPTION,
        "joint_names": LULA_JOINT_NAMES,
        "end_effector_frame": LULA_END_EFFECTOR_FRAME,
        "scene_opened": False,
        "controller_called": False,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return LulaQueryOnlySourceClosureV1(
        **payload,
        source_closure_sha256=_canonical_payload_sha256(payload),
    )


class LulaQueryOnlyIKConfigurationV1(FrozenModel):
    schema_version: Literal["LulaQueryOnlyIKConfigurationV1"] = "LulaQueryOnlyIKConfigurationV1"
    position_tolerance_m: float = Field(gt=0.0)
    orientation_tolerance_rad: float = Field(gt=0.0, le=math.pi)
    ccd_max_iterations: int = Field(ge=32)
    bfgs_max_iterations: int = Field(gt=0)
    maximum_descents: int = Field(gt=0)
    certified_iteration_upper_bound: int = Field(gt=0)
    ccd_bracket_search_num_uniform_samples: int = Field(gt=0)
    ccd_descent_termination_delta: float = Field(gt=0.0)
    ccd_position_weight: float = Field(gt=0.0)
    ccd_orientation_weight: float = Field(gt=0.0)
    bfgs_position_weight: float = Field(gt=0.0)
    bfgs_orientation_weight: float = Field(gt=0.0)
    bfgs_cspace_limit_biasing: Literal["AUTO"] = "AUTO"
    bfgs_cspace_limit_biasing_weight: float = Field(gt=0.0)
    bfgs_cspace_limit_penalty_region: float = Field(gt=0.0)
    bfgs_gradient_norm_termination: float = Field(gt=0.0)
    bfgs_gradient_norm_termination_coarse_scale_factor: float = Field(gt=0.0)
    irwin_hall_sampling_order: int = Field(gt=0)
    deterministic_sampling_seed: Literal[0] = 0
    query_frame: Literal["robot_base"] = "robot_base"
    distance_units: Literal["m"] = "m"
    angle_units: Literal["rad"] = "rad"
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def values_and_digest(self) -> "LulaQueryOnlyIKConfigurationV1":
        numeric = (
            self.position_tolerance_m,
            self.orientation_tolerance_rad,
            self.ccd_descent_termination_delta,
            self.ccd_position_weight,
            self.ccd_orientation_weight,
            self.bfgs_position_weight,
            self.bfgs_orientation_weight,
            self.bfgs_cspace_limit_biasing_weight,
            self.bfgs_cspace_limit_penalty_region,
            self.bfgs_gradient_norm_termination,
            self.bfgs_gradient_norm_termination_coarse_scale_factor,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("Lula IK configuration contains NaN/Inf")
        expected_upper = self.maximum_descents * (
            self.ccd_max_iterations + self.bfgs_max_iterations
        )
        if self.certified_iteration_upper_bound != expected_upper:
            raise ValueError("Lula IK certified iteration upper bound differs")
        if self.configuration_sha256 != _canonical_model_sha256(self, "configuration_sha256"):
            raise ValueError("Lula IK configuration digest differs")
        return self


def canonical_lula_query_only_ik_configuration_v1() -> LulaQueryOnlyIKConfigurationV1:
    """Return the proposal recorded for the Phase-2 binding addendum.

    One deterministic descent is allowed.  The combined CCD+BFGS worst-case
    bound is 64 iterations; a non-converged query rejects instead of trying a
    new seed.
    """

    payload = {
        "schema_version": "LulaQueryOnlyIKConfigurationV1",
        "position_tolerance_m": 0.002,
        "orientation_tolerance_rad": 0.01,
        "ccd_max_iterations": 32,
        "bfgs_max_iterations": 32,
        "maximum_descents": 1,
        "certified_iteration_upper_bound": 64,
        "ccd_bracket_search_num_uniform_samples": 10,
        "ccd_descent_termination_delta": 0.1,
        "ccd_position_weight": 1.0,
        "ccd_orientation_weight": 0.05,
        "bfgs_position_weight": 1.0,
        "bfgs_orientation_weight": 100.0,
        "bfgs_cspace_limit_biasing": "AUTO",
        "bfgs_cspace_limit_biasing_weight": 1.0,
        "bfgs_cspace_limit_penalty_region": 0.01,
        "bfgs_gradient_norm_termination": 1e-6,
        "bfgs_gradient_norm_termination_coarse_scale_factor": 10_000_000.0,
        "irwin_hall_sampling_order": 2,
        "deterministic_sampling_seed": 0,
        "query_frame": "robot_base",
        "distance_units": "m",
        "angle_units": "rad",
    }
    return LulaQueryOnlyIKConfigurationV1(
        **payload,
        configuration_sha256=_canonical_payload_sha256(payload),
    )


def _finite_tuple(values: tuple[float, ...], *, width: int, label: str) -> None:
    if len(values) != width or not all(math.isfinite(float(value)) for value in values):
        raise ValueError(f"{label} is malformed")


class LulaQueryOnlyIKRequestV1(FrozenModel):
    schema_version: Literal["LulaQueryOnlyIKRequestV1"] = "LulaQueryOnlyIKRequestV1"
    request_id: str = Field(min_length=1)
    joint_names: tuple[str, ...] = LULA_JOINT_NAMES
    warm_start_joint_positions_rad: tuple[float, ...] = Field(min_length=7, max_length=7)
    target_position_robot_base_m: tuple[float, float, float]
    target_orientation_robot_base_wxyz: tuple[float, float, float, float]
    configuration: LulaQueryOnlyIKConfigurationV1
    source_closure_sha256: str = Field(pattern=SHA256_PATTERN)
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False

    @model_validator(mode="after")
    def finite_and_canonical(self) -> "LulaQueryOnlyIKRequestV1":
        if self.joint_names != LULA_JOINT_NAMES:
            raise ValueError("Lula IK request joint order differs")
        _finite_tuple(self.warm_start_joint_positions_rad, width=7, label="warm start")
        _finite_tuple(self.target_position_robot_base_m, width=3, label="target position")
        _finite_tuple(self.target_orientation_robot_base_wxyz, width=4, label="target orientation")
        norm = math.sqrt(sum(value * value for value in self.target_orientation_robot_base_wxyz))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("Lula IK target quaternion is not normalized")
        if self.request_sha256 != _canonical_model_sha256(self, "request_sha256"):
            raise ValueError("Lula IK request digest differs")
        return self


def build_lula_query_only_ik_request_v1(
    *,
    request_id: str,
    warm_start_joint_positions_rad: tuple[float, ...],
    target_position_robot_base_m: tuple[float, float, float],
    target_orientation_robot_base_wxyz: tuple[float, float, float, float],
    configuration: LulaQueryOnlyIKConfigurationV1,
    source_closure_sha256: str,
) -> LulaQueryOnlyIKRequestV1:
    payload = {
        "schema_version": "LulaQueryOnlyIKRequestV1",
        "request_id": request_id,
        "joint_names": LULA_JOINT_NAMES,
        "warm_start_joint_positions_rad": warm_start_joint_positions_rad,
        "target_position_robot_base_m": target_position_robot_base_m,
        "target_orientation_robot_base_wxyz": target_orientation_robot_base_wxyz,
        "configuration": configuration,
        "source_closure_sha256": source_closure_sha256,
        "teacher_used": False,
        "privileged_truth_policy_input": False,
    }
    return LulaQueryOnlyIKRequestV1(
        **payload,
        request_sha256=_canonical_payload_sha256(payload),
    )


class ActiveSessionMutationCountersV1(FrozenModel):
    schema_version: Literal["ActiveSessionMutationCountersV1"] = "ActiveSessionMutationCountersV1"
    articulation_target_writes: int = Field(ge=0)
    simulation_steps: int = Field(ge=0)
    scene_mutations: int = Field(ge=0)
    controller_commands: int = Field(ge=0)
    attachment_mutations: int = Field(ge=0)


class ActiveSessionMutationCounterSourceV1(Protocol):
    implementation_sha256: str
    real_active_session_source: bool
    mocked_counter_source: bool

    def snapshot_mutation_counters(self) -> ActiveSessionMutationCountersV1: ...


class LulaNativeIKResultV1(FrozenModel):
    schema_version: Literal["LulaNativeIKResultV1"] = "LulaNativeIKResultV1"
    native_success: bool
    solution_joint_positions_rad: tuple[float, ...] = Field(min_length=7, max_length=7)
    native_position_error: float = Field(ge=0.0)
    native_axis_orientation_errors: tuple[float, float, float]
    num_descents: int = Field(ge=0)
    achieved_position_robot_base_m: tuple[float, float, float]
    achieved_orientation_robot_base_matrix: tuple[float, ...] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def finite(self) -> "LulaNativeIKResultV1":
        _finite_tuple(self.solution_joint_positions_rad, width=7, label="IK solution")
        _finite_tuple(
            self.native_axis_orientation_errors, width=3, label="native orientation error"
        )
        _finite_tuple(self.achieved_position_robot_base_m, width=3, label="achieved position")
        _finite_tuple(
            self.achieved_orientation_robot_base_matrix,
            width=9,
            label="achieved orientation",
        )
        if not math.isfinite(self.native_position_error):
            raise ValueError("native position error is NaN/Inf")
        return self


class LulaNativeIKKernelV1(Protocol):
    joint_names: tuple[str, ...]
    frame_names: tuple[str, ...]
    implementation_sha256: str
    source_closure_sha256: str
    real_runtime_provider: bool
    mocked_kernel: bool

    def solve(self, request: LulaQueryOnlyIKRequestV1) -> LulaNativeIKResultV1: ...


class LulaQueryOnlyIKReceiptV1(FrozenModel):
    schema_version: Literal["LulaQueryOnlyIKReceiptV1"] = "LulaQueryOnlyIKReceiptV1"
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    source_closure_sha256: str = Field(pattern=SHA256_PATTERN)
    adapter_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    kernel_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    mode: Literal["CONTRACT_TEST", "STARTUP_SMOKE", "REAL_ISAAC"]
    real_runtime_provider: bool
    mocked_kernel: bool
    counter_source_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    real_active_session_counter_source: bool
    mocked_counter_source: bool
    formal_query_evidence_eligible: bool
    native_success: bool
    accepted: bool
    solution_joint_positions_rad: tuple[float, ...] = Field(min_length=7, max_length=7)
    achieved_position_robot_base_m: tuple[float, float, float]
    achieved_orientation_robot_base_matrix: tuple[float, ...] = Field(min_length=9, max_length=9)
    position_residual_m: float = Field(ge=0.0)
    orientation_residual_rad: float = Field(ge=0.0, le=math.pi)
    native_position_error: float = Field(ge=0.0)
    native_axis_orientation_errors: tuple[float, float, float]
    num_descents: int = Field(ge=0)
    certified_iteration_upper_bound: int = Field(gt=0)
    mutation_counters_before: ActiveSessionMutationCountersV1
    mutation_counters_after: ActiveSessionMutationCountersV1
    query_duration_ns: int = Field(ge=0)
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    controller_commands: Literal[0] = 0
    attachment_mutations: Literal[0] = 0
    whole_plan_authorization_claimed: Literal[False] = False
    physical_execution_claimed: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def safe_and_canonical(self) -> "LulaQueryOnlyIKReceiptV1":
        if self.mutation_counters_before != self.mutation_counters_after:
            raise ValueError("Lula IK mutation counters changed")
        _finite_tuple(self.solution_joint_positions_rad, width=7, label="IK receipt solution")
        _finite_tuple(
            self.achieved_orientation_robot_base_matrix,
            width=9,
            label="IK receipt orientation",
        )
        if not all(
            math.isfinite(value)
            for value in (
                *self.achieved_position_robot_base_m,
                self.position_residual_m,
                self.orientation_residual_rad,
                self.native_position_error,
                *self.native_axis_orientation_errors,
            )
        ):
            raise ValueError("Lula IK receipt contains NaN/Inf")
        if self.accepted and not self.native_success:
            raise ValueError("Lula IK accepted a native failure")
        expected_formal = bool(
            self.mode == "REAL_ISAAC"
            and self.real_runtime_provider
            and not self.mocked_kernel
            and self.real_active_session_counter_source
            and not self.mocked_counter_source
        )
        if self.formal_query_evidence_eligible != expected_formal:
            raise ValueError("Lula IK formal query evidence eligibility differs")
        if self.receipt_sha256 != _canonical_model_sha256(self, "receipt_sha256"):
            raise ValueError("Lula IK receipt digest differs")
        return self


def _quaternion_wxyz_to_matrix(value: tuple[float, float, float, float]) -> np.ndarray:
    w, x, y, z = value
    return np.asarray(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        ),
        dtype=np.float64,
    )


def _orientation_residual_rad(target: np.ndarray, achieved: np.ndarray) -> float:
    relative = target.T @ achieved
    cosine = float(np.clip((np.trace(relative) - 1.0) / 2.0, -1.0, 1.0))
    return float(math.acos(cosine))


class LulaQueryOnlyIKCoordinatorV1:
    """Cross-check one native solve against mutation counters and independent FK."""

    def __init__(
        self,
        *,
        source_closure: LulaQueryOnlySourceClosureV1,
        kernel: LulaNativeIKKernelV1,
        counter_source: ActiveSessionMutationCounterSourceV1,
        mode: Literal["CONTRACT_TEST", "STARTUP_SMOKE", "REAL_ISAAC"],
        adapter_implementation_path: Path | None = None,
    ) -> None:
        self.source_closure = source_closure
        self.kernel = kernel
        self.counter_source = counter_source
        implementation = adapter_implementation_path or Path(__file__)
        self.adapter_implementation_sha256 = hashlib.sha256(
            _read_regular_file_once(implementation)
        ).hexdigest()
        if kernel.joint_names != LULA_JOINT_NAMES:
            raise LulaQueryOnlyIKUnavailable("native Lula kernel joint order differs")
        if LULA_END_EFFECTOR_FRAME not in kernel.frame_names:
            raise LulaQueryOnlyIKUnavailable("native Lula kernel lacks panda_hand")
        if mode == "CONTRACT_TEST":
            if (
                kernel.real_runtime_provider
                or not kernel.mocked_kernel
                or counter_source.real_active_session_source
                or not counter_source.mocked_counter_source
            ):
                raise LulaQueryOnlyIKUnavailable(
                    "contract Lula coordinator received production dependency claims"
                )
        elif mode == "STARTUP_SMOKE":
            if (
                type(kernel) is not IsaacLulaNativeIKKernelV1
                or not kernel.real_runtime_provider
                or kernel.mocked_kernel
                or counter_source.real_active_session_source
                or not counter_source.mocked_counter_source
                or kernel.source_closure_sha256 != source_closure.source_closure_sha256
            ):
                raise LulaQueryOnlyIKUnavailable("STARTUP_SMOKE Lula dependency identity differs")
        elif (
            type(kernel) is not IsaacLulaNativeIKKernelV1
            or not kernel.real_runtime_provider
            or kernel.mocked_kernel
            or not counter_source.real_active_session_source
            or counter_source.mocked_counter_source
            or kernel.source_closure_sha256 != source_closure.source_closure_sha256
        ):
            raise LulaQueryOnlyIKUnavailable("REAL_ISAAC Lula dependency identity differs")
        self.mode = mode

    def solve(self, request: LulaQueryOnlyIKRequestV1) -> LulaQueryOnlyIKReceiptV1:
        if request.source_closure_sha256 != self.source_closure.source_closure_sha256:
            raise LulaQueryOnlyIKUnavailable("Lula IK request source closure differs")
        before = self.counter_source.snapshot_mutation_counters()
        started = time.perf_counter_ns()
        try:
            native = self.kernel.solve(request)
        except Exception as exc:
            after_failure = self.counter_source.snapshot_mutation_counters()
            if after_failure != before:
                raise LulaQueryMutationDetected(
                    "native Lula query mutated the active session before failing"
                ) from exc
            if isinstance(exc, LulaQueryOnlyIKUnavailable):
                raise
            raise LulaQueryOnlyIKUnavailable("native Lula query failed") from exc
        duration = time.perf_counter_ns() - started
        after = self.counter_source.snapshot_mutation_counters()
        if after != before:
            raise LulaQueryMutationDetected("native Lula query mutated the active session")

        target_position = np.asarray(request.target_position_robot_base_m, dtype=np.float64)
        achieved_position = np.asarray(native.achieved_position_robot_base_m, dtype=np.float64)
        target_rotation = _quaternion_wxyz_to_matrix(request.target_orientation_robot_base_wxyz)
        achieved_rotation = np.asarray(
            native.achieved_orientation_robot_base_matrix, dtype=np.float64
        ).reshape(3, 3)
        position_residual = float(np.linalg.norm(target_position - achieved_position))
        orientation_residual = _orientation_residual_rad(target_rotation, achieved_rotation)
        configuration = request.configuration
        accepted = bool(
            native.native_success
            and native.num_descents <= configuration.maximum_descents
            and position_residual <= configuration.position_tolerance_m
            and orientation_residual <= configuration.orientation_tolerance_rad
        )
        payload: dict[str, Any] = {
            "schema_version": "LulaQueryOnlyIKReceiptV1",
            "request_sha256": request.request_sha256,
            "source_closure_sha256": self.source_closure.source_closure_sha256,
            "adapter_implementation_sha256": self.adapter_implementation_sha256,
            "kernel_implementation_sha256": self.kernel.implementation_sha256,
            "configuration_sha256": configuration.configuration_sha256,
            "mode": self.mode,
            "real_runtime_provider": self.kernel.real_runtime_provider,
            "mocked_kernel": self.kernel.mocked_kernel,
            "counter_source_implementation_sha256": (self.counter_source.implementation_sha256),
            "real_active_session_counter_source": (self.counter_source.real_active_session_source),
            "mocked_counter_source": self.counter_source.mocked_counter_source,
            "formal_query_evidence_eligible": self.mode == "REAL_ISAAC",
            "native_success": native.native_success,
            "accepted": accepted,
            "solution_joint_positions_rad": native.solution_joint_positions_rad,
            "achieved_position_robot_base_m": native.achieved_position_robot_base_m,
            "achieved_orientation_robot_base_matrix": (
                native.achieved_orientation_robot_base_matrix
            ),
            "position_residual_m": position_residual,
            "orientation_residual_rad": orientation_residual,
            "native_position_error": native.native_position_error,
            "native_axis_orientation_errors": native.native_axis_orientation_errors,
            "num_descents": native.num_descents,
            "certified_iteration_upper_bound": (configuration.certified_iteration_upper_bound),
            "mutation_counters_before": before,
            "mutation_counters_after": after,
            "query_duration_ns": duration,
            "query_only": True,
            "articulation_target_writes": 0,
            "simulation_steps": 0,
            "scene_mutations": 0,
            "controller_commands": 0,
            "attachment_mutations": 0,
            "whole_plan_authorization_claimed": False,
            "physical_execution_claimed": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return LulaQueryOnlyIKReceiptV1(
            **payload,
            receipt_sha256=_canonical_payload_sha256(payload),
        )


class IsaacLulaNativeIKKernelV1:
    """Direct, query-only binding to the byte-pinned Lula native extension."""

    def __init__(
        self,
        *,
        image_root: Path,
        source_closure: LulaQueryOnlySourceClosureV1,
        lula_module: Any | None = None,
    ) -> None:
        self.image_root = image_root.resolve()
        self.real_runtime_provider = True
        self.mocked_kernel = False
        self.implementation_sha256 = hashlib.sha256(
            _read_regular_file_once(Path(__file__))
        ).hexdigest()
        verified = inspect_lula_query_only_source_closure_v1(
            image_root=self.image_root,
            image_digest=source_closure.image_digest,
        )
        if verified != source_closure:
            raise LulaQueryOnlyIKUnavailable("native Lula source closure differs")
        self.source_closure_sha256 = verified.source_closure_sha256
        prebundle = self.image_root / LULA_PIP_PREBUNDLE
        if lula_module is None:
            sys.path.insert(0, str(prebundle))
            try:
                lula_module = importlib.import_module("lula")
            finally:
                if sys.path[0] == str(prebundle):
                    sys.path.pop(0)
        module_path = Path(str(lula_module.__file__)).resolve()
        expected_module = (
            self.image_root / LULA_PIP_PREBUNDLE / "lula.cpython-312-x86_64-linux-gnu.so"
        ).resolve()
        if module_path != expected_module:
            raise LulaQueryOnlyIKUnavailable("loaded Lula module path differs")
        self._lula = lula_module
        self._robot = lula_module.load_robot(
            str(self.image_root / LULA_ROBOT_DESCRIPTOR),
            str(self.image_root / LULA_ROBOT_DESCRIPTION),
        )
        self._kinematics = self._robot.kinematics()
        self.joint_names = tuple(
            self._robot.c_space_coord_name(index)
            for index in range(self._robot.num_c_space_coords())
        )
        self.frame_names = tuple(self._kinematics.frame_names())
        if self.joint_names != LULA_JOINT_NAMES or LULA_END_EFFECTOR_FRAME not in self.frame_names:
            raise LulaQueryOnlyIKUnavailable("loaded Lula robot identity differs")

    @staticmethod
    def _native_orientation_tolerance(radians: float) -> float:
        return float(math.sqrt(2.0 - 2.0 * math.cos(radians)))

    def solve(self, request: LulaQueryOnlyIKRequestV1) -> LulaNativeIKResultV1:
        config_model = request.configuration
        config = self._lula.CyclicCoordDescentIkConfig()
        config.position_tolerance = config_model.position_tolerance_m
        config.orientation_tolerance = self._native_orientation_tolerance(
            config_model.orientation_tolerance_rad
        )
        config.ccd_max_iterations = config_model.ccd_max_iterations
        config.bfgs_max_iterations = config_model.bfgs_max_iterations
        config.max_num_descents = config_model.maximum_descents
        config.ccd_bracket_search_num_uniform_samples = (
            config_model.ccd_bracket_search_num_uniform_samples
        )
        config.ccd_descent_termination_delta = config_model.ccd_descent_termination_delta
        config.ccd_position_weight = config_model.ccd_position_weight
        config.ccd_orientation_weight = config_model.ccd_orientation_weight
        config.bfgs_position_weight = config_model.bfgs_position_weight
        config.bfgs_orientation_weight = config_model.bfgs_orientation_weight
        config.bfgs_cspace_limit_biasing_weight = config_model.bfgs_cspace_limit_biasing_weight
        config.bfgs_cspace_limit_penalty_region = config_model.bfgs_cspace_limit_penalty_region
        config.bfgs_gradient_norm_termination = config_model.bfgs_gradient_norm_termination
        config.bfgs_gradient_norm_termination_coarse_scale_factor = (
            config_model.bfgs_gradient_norm_termination_coarse_scale_factor
        )
        config.irwin_hall_sampling_order = config_model.irwin_hall_sampling_order
        config.sampling_seed = config_model.deterministic_sampling_seed
        if str(config.bfgs_cspace_limit_biasing).rsplit(".", 1)[-1] != "AUTO":
            raise LulaQueryOnlyIKUnavailable("native Lula cspace biasing default differs")
        seed = np.asarray(request.warm_start_joint_positions_rad, dtype=np.float64)
        config.cspace_seeds = [seed]
        target_rotation = _quaternion_wxyz_to_matrix(request.target_orientation_robot_base_wxyz)
        target_pose = self._lula.Pose3(
            self._lula.Rotation3(target_rotation),
            np.asarray(request.target_position_robot_base_m, dtype=np.float64),
        )
        result = self._lula.compute_ik_ccd(
            self._kinematics,
            target_pose,
            LULA_END_EFFECTOR_FRAME,
            config,
        )
        solution = np.asarray(result.cspace_position, dtype=np.float64).reshape(-1)
        achieved = self._kinematics.pose(np.expand_dims(solution, 1), LULA_END_EFFECTOR_FRAME)
        payload = {
            "schema_version": "LulaNativeIKResultV1",
            "native_success": bool(result.success),
            "solution_joint_positions_rad": tuple(float(value) for value in solution),
            "native_position_error": float(result.position_error),
            "native_axis_orientation_errors": (
                float(result.x_axis_orientation_error),
                float(result.y_axis_orientation_error),
                float(result.z_axis_orientation_error),
            ),
            "num_descents": int(result.num_descents),
            "achieved_position_robot_base_m": tuple(
                float(value) for value in np.asarray(achieved.translation).reshape(-1)
            ),
            "achieved_orientation_robot_base_matrix": tuple(
                float(value) for value in np.asarray(achieved.rotation.matrix()).reshape(-1)
            ),
        }
        return LulaNativeIKResultV1.model_validate(payload)
