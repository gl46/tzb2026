"""ADR-0022 unchanged-B0 fallback wrapper provenance contract.

The wrapper never contains, copies, or reimplements a B0 action.  It verifies
the frozen M2C B0 manifest and can build the exact argv for the already frozen
``run_physical_failure_smoke.py`` entry point.  That entry point starts a new
Isaac process and is therefore *not* compatible with the active persistent
formal session.  Production invocation consequently remains unavailable and
returns a signed-by-content ``NO_PHYSICAL_EXECUTION`` receipt until a human-
reviewed, hash-frozen active-session B0 entry point is supplied by the
ADR-0022 binding addendum.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


FROZEN_B0_PROBE_PATH = "scripts/isaac_m1b_actuation_probe.py"
FROZEN_B0_PROBE_SHA256 = "1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"
FROZEN_B0_RUNNER_PATH = "scripts/m2b/run_physical_failure_smoke.py"
FROZEN_B0_RUNNER_SHA256 = "7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865"
FROZEN_B0_MANIFEST_PATH = "configs/m2c_b0_freeze.json"
FROZEN_B0_MANIFEST_SHA256 = "4bec9104be849dfd8d71b32b537eb2b5d70ea4d8560b4bdd65b1d1019d3e8d04"
FROZEN_B0_IMAGE = "nvcr.io/nvidia/isaac-sim:6.0.1"
FROZEN_B0_TRIGGER_SET = frozenset(
    {
        "INVALID_POINTER",
        "STALE_TRACK",
        "INVALID_CELL",
        "INVALID_MAPPING",
        "PREFLIGHT_REJECTION",
    }
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenB0Unavailable(RuntimeError):
    """Raised before process launch if unchanged-B0 identity is not provable."""


def read_regular_file_once(path: Path) -> bytes:
    """Read stable bytes from one O_NOFOLLOW regular-file descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FrozenB0Unavailable(f"B0 binding is not a single-link regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise FrozenB0Unavailable(f"B0 binding changed during read: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class FrozenB0SourceBindingV1(FrozenModel):
    schema_version: Literal["FrozenB0SourceBindingV1"] = "FrozenB0SourceBindingV1"
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    role: str = Field(min_length=1)


class FrozenB0ManifestReceiptV1(FrozenModel):
    schema_version: Literal["FrozenB0ManifestReceiptV1"] = "FrozenB0ManifestReceiptV1"
    freeze_manifest_path: Literal["configs/m2c_b0_freeze.json"] = FROZEN_B0_MANIFEST_PATH
    freeze_manifest_sha256: Literal[
        "4bec9104be849dfd8d71b32b537eb2b5d70ea4d8560b4bdd65b1d1019d3e8d04"
    ] = FROZEN_B0_MANIFEST_SHA256
    baseline_commit: Literal["141e45dabddcaf59bb49ab958d9d5273d1f54d88"]
    probe_sha256: Literal["1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"] = (
        FROZEN_B0_PROBE_SHA256
    )
    runner_sha256: Literal["7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865"] = (
        FROZEN_B0_RUNNER_SHA256
    )
    source_bindings: tuple[FrozenB0SourceBindingV1, ...] = Field(min_length=12)
    source_set_sha256: str = Field(pattern=SHA256_PATTERN)
    all_sources_verified_before_launch: Literal[True] = True
    b0_modified: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class FrozenB0FallbackRequestV1(FrozenModel):
    schema_version: Literal["FrozenB0FallbackRequestV1"] = "FrozenB0FallbackRequestV1"
    wrapper_name: Literal["FrozenB0FallbackWrapperV1"] = "FrozenB0FallbackWrapperV1"
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    decision_index: int = Field(ge=0, le=7)
    trigger: Literal[
        "INVALID_POINTER",
        "STALE_TRACK",
        "INVALID_CELL",
        "INVALID_MAPPING",
        "PREFLIGHT_REJECTION",
    ]
    active_scene_state_sha256: str = Field(pattern=SHA256_PATTERN)
    rejected_model_mapping_sha256: str = Field(pattern=SHA256_PATTERN)
    previous_capture_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    requested_failure: Literal["EMPTY_GRASP"] = "EMPTY_GRASP"
    target_object: Literal["cylinder_04"] = "cylinder_04"
    public_target_object: Literal["cylinder_04"] = "cylinder_04"
    contact_centerline_m: Literal["0.120"] = "0.120"
    max_attempts: Literal[2] = 2
    capture_public_rgbd: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class FrozenB0LegacyArgvV1(FrozenModel):
    schema_version: Literal["FrozenB0LegacyArgvV1"] = "FrozenB0LegacyArgvV1"
    argv: tuple[str, ...] = Field(min_length=2)
    argv_sha256: str = Field(pattern=SHA256_PATTERN)
    environment: tuple[tuple[str, str], ...]
    environment_sha256: str = Field(pattern=SHA256_PATTERN)
    runner_sha256: Literal["7e68c9f18b26bedaa600e642ca59339da9a99739bc2770d8aed3f87c53e98865"] = (
        FROZEN_B0_RUNNER_SHA256
    )
    unchanged_parameters: Literal[True] = True
    starts_new_isaac_process: Literal[True] = True
    compatible_with_active_formal_session: Literal[False] = False

    @model_validator(mode="after")
    def command_is_canonical(self) -> "FrozenB0LegacyArgvV1":
        if self.argv_sha256 != canonical_sha256(self.argv):
            raise ValueError("legacy B0 argv digest differs")
        if self.environment_sha256 != canonical_sha256(self.environment):
            raise ValueError("legacy B0 environment digest differs")
        if tuple(key for key, _ in self.environment) != tuple(
            sorted(key for key, _ in self.environment)
        ):
            raise ValueError("legacy B0 environment is not canonical")
        return self


class FrozenB0ActiveSessionBindingV1(FrozenModel):
    """Future addendum binding for an actual unchanged-B0 callable."""

    schema_version: Literal["FrozenB0ActiveSessionBindingV1"] = "FrozenB0ActiveSessionBindingV1"
    binding_addendum_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    wrapper_entrypoint_path: str = Field(min_length=1)
    wrapper_entrypoint_sha256: str = Field(pattern=SHA256_PATTERN)
    active_session_b0_entrypoint_path: str = Field(min_length=1)
    active_session_b0_entrypoint_sha256: Literal[
        "1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"
    ] = FROZEN_B0_PROBE_SHA256
    freeze_manifest_sha256: Literal[
        "4bec9104be849dfd8d71b32b537eb2b5d70ea4d8560b4bdd65b1d1019d3e8d04"
    ] = FROZEN_B0_MANIFEST_SHA256
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    exact_argv_sha256: str = Field(pattern=SHA256_PATTERN)
    exact_environment_sha256: str = Field(pattern=SHA256_PATTERN)
    active_formal_session_compatible: Literal[True] = True
    unchanged_parameters_retries_controllers_gates_success_and_failure: Literal[True] = True
    independently_reviewed: Literal[True] = True
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False


class FrozenB0FallbackReceiptV1(FrozenModel):
    schema_version: Literal["FrozenB0FallbackReceiptV1"] = "FrozenB0FallbackReceiptV1"
    wrapper_name: Literal["FrozenB0FallbackWrapperV1"] = "FrozenB0FallbackWrapperV1"
    request_sha256: str = Field(pattern=SHA256_PATTERN)
    manifest_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    invocation_argv_sha256: str = Field(pattern=SHA256_PATTERN)
    invocation_environment_sha256: str = Field(pattern=SHA256_PATTERN)
    executed_skill: Literal["B0_FALLBACK", "NO_PHYSICAL_EXECUTION"]
    execution_source: Literal["B0_FALLBACK", "NO_PHYSICAL_EXECUTION"]
    physically_executed: bool
    status: Literal["PASS", "FAILED", "NO_PHYSICAL_EXECUTION"]
    fallback_reason: str = Field(min_length=1)
    b0_probe_sha256: Literal["1e32fa89c8b1ef403a52f1b2c8326942b72092e6e88f50e8f780eff1c08c6094"] = (
        FROZEN_B0_PROBE_SHA256
    )
    active_session_compatible: bool
    pure_model_success_eligible: Literal[False] = False
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def attribution_and_digest_are_exact(self) -> "FrozenB0FallbackReceiptV1":
        if self.physically_executed:
            if (
                self.execution_source != "B0_FALLBACK"
                or self.executed_skill != "B0_FALLBACK"
                or not self.active_session_compatible
                or self.status == "NO_PHYSICAL_EXECUTION"
            ):
                raise ValueError("physical B0 fallback has false attribution/session status")
        elif (
            self.execution_source != "NO_PHYSICAL_EXECUTION"
            or self.executed_skill != "NO_PHYSICAL_EXECUTION"
            or self.status != "NO_PHYSICAL_EXECUTION"
        ):
            raise ValueError("unexecuted fallback is falsely attributed to B0")
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(payload):
            raise ValueError("fallback receipt digest differs")
        return self


class FrozenB0FallbackWrapperV1:
    """Verify unchanged B0 identity; never synthesize a B0 implementation."""

    def __init__(self, *, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def verify_frozen_sources(self) -> FrozenB0ManifestReceiptV1:
        manifest_path = self.project_root / FROZEN_B0_MANIFEST_PATH
        manifest_bytes = read_regular_file_once(manifest_path)
        if _sha256(manifest_bytes) != FROZEN_B0_MANIFEST_SHA256:
            raise FrozenB0Unavailable("frozen B0 manifest SHA-256 differs")
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenB0Unavailable("frozen B0 manifest is not canonical JSON data") from exc
        if manifest.get("schema_version") != "M2CB0FreezeManifestV1":
            raise FrozenB0Unavailable("unexpected B0 freeze-manifest schema")
        items = manifest.get("b0_files")
        if not isinstance(items, list) or len(items) != 12:
            raise FrozenB0Unavailable("B0 freeze manifest has an unexpected source set")
        bindings: list[FrozenB0SourceBindingV1] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != {"path", "role", "sha256"}:
                raise FrozenB0Unavailable("malformed B0 source binding")
            path_value = str(item["path"])
            if (
                path_value in seen
                or Path(path_value).is_absolute()
                or ".." in Path(path_value).parts
            ):
                raise FrozenB0Unavailable("duplicate or unsafe B0 source path")
            seen.add(path_value)
            source = self.project_root / path_value
            actual = _sha256(read_regular_file_once(source))
            if actual != item["sha256"]:
                raise FrozenB0Unavailable(f"frozen B0 source SHA-256 differs: {path_value}")
            bindings.append(
                FrozenB0SourceBindingV1(
                    path=path_value,
                    role=str(item["role"]),
                    sha256=actual,
                )
            )
        by_path = {item.path: item.sha256 for item in bindings}
        if by_path.get(FROZEN_B0_PROBE_PATH) != FROZEN_B0_PROBE_SHA256:
            raise FrozenB0Unavailable("freeze manifest does not bind the accepted B0 probe")
        if by_path.get(FROZEN_B0_RUNNER_PATH) != FROZEN_B0_RUNNER_SHA256:
            raise FrozenB0Unavailable("freeze manifest does not bind the accepted B0 runner")
        source_set = tuple(item.model_dump(mode="json") for item in bindings)
        return FrozenB0ManifestReceiptV1(
            baseline_commit=manifest["baseline_commit"],
            source_bindings=tuple(bindings),
            source_set_sha256=canonical_sha256(source_set),
        )

    def build_legacy_argv(
        self,
        request: FrozenB0FallbackRequestV1,
        *,
        source_root: Path,
        stage: Path,
        sdf: Path,
        supervision: Path,
        output_root: Path,
        gpu: int,
    ) -> FrozenB0LegacyArgvV1:
        """Build exactly the frozen runner's public EMPTY_GRASP invocation."""

        if request.trigger not in FROZEN_B0_TRIGGER_SET:
            raise FrozenB0Unavailable("fallback trigger is not ADR-0020 section 7.4")
        if gpu < 0:
            raise FrozenB0Unavailable("GPU index is negative")
        roots = (source_root, stage, sdf, supervision, output_root)
        if any(not path.is_absolute() for path in roots):
            raise FrozenB0Unavailable("legacy B0 argv paths must be absolute")
        if sdf.parent != source_root or supervision.parent != source_root:
            raise FrozenB0Unavailable("scene sources are not direct source-root files")
        argv = (
            os.fspath(self.project_root / FROZEN_B0_RUNNER_PATH),
            "--project-root",
            os.fspath(self.project_root),
            "--source-root",
            os.fspath(source_root),
            "--stage",
            os.fspath(stage),
            "--sdf",
            os.fspath(sdf),
            "--supervision",
            os.fspath(supervision),
            "--output-root",
            os.fspath(output_root),
            "--gpu",
            str(gpu),
            "--target-object",
            request.target_object,
            "--public-target-object",
            request.public_target_object,
            "--contact-centerline-m",
            request.contact_centerline_m,
            "--image",
            FROZEN_B0_IMAGE,
            "--container-prefix",
            "m2b-physical-smoke",
            "--max-attempts",
            str(request.max_attempts),
            "--timeout-s",
            "1800.0",
            "--settle-s",
            "30.0",
            "--capture-public-rgbd",
            "--failures",
            request.requested_failure,
        )
        environment = tuple(sorted(sanitized_subprocess_environment().items()))
        return FrozenB0LegacyArgvV1(
            argv=argv,
            argv_sha256=canonical_sha256(argv),
            environment=environment,
            environment_sha256=canonical_sha256(environment),
        )

    def invoke(
        self,
        request: FrozenB0FallbackRequestV1,
        *,
        legacy_argv: FrozenB0LegacyArgvV1,
        active_session_binding: FrozenB0ActiveSessionBindingV1 | None,
    ) -> FrozenB0FallbackReceiptV1:
        """Fail closed: the frozen legacy runner cannot join an active session.

        No subprocess is launched.  A future implementation may invoke only a
        human-reviewed active-session entry point after proving its source,
        argv, environment, assets, and receipt contract against the addendum.
        """

        manifest = self.verify_frozen_sources()
        if request.trigger not in FROZEN_B0_TRIGGER_SET:
            raise FrozenB0Unavailable("fallback trigger is outside the approved set")
        reason = "ACTIVE_FORMAL_SESSION_UNCHANGED_B0_ENTRYPOINT_NOT_BOUND"
        if active_session_binding is not None:
            reason = (
                "ACTIVE_SESSION_BINDING_PRESENT_BUT_NO_REVIEWED_IN_PROCESS_"
                "INVOCATION_ADAPTER_IMPLEMENTED"
            )
        payload: dict[str, object] = {
            "schema_version": "FrozenB0FallbackReceiptV1",
            "wrapper_name": "FrozenB0FallbackWrapperV1",
            "request_sha256": canonical_sha256(request),
            "manifest_receipt_sha256": canonical_sha256(manifest),
            "invocation_argv_sha256": legacy_argv.argv_sha256,
            "invocation_environment_sha256": legacy_argv.environment_sha256,
            "executed_skill": "NO_PHYSICAL_EXECUTION",
            "execution_source": "NO_PHYSICAL_EXECUTION",
            "physically_executed": False,
            "status": "NO_PHYSICAL_EXECUTION",
            "fallback_reason": reason,
            "b0_probe_sha256": FROZEN_B0_PROBE_SHA256,
            "active_session_compatible": False,
            "pure_model_success_eligible": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        return FrozenB0FallbackReceiptV1(
            **payload,
            receipt_sha256=canonical_sha256(payload),
        )


def sanitized_subprocess_environment(
    supplied: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """A future launcher may use only this fixed, non-secret environment."""

    if supplied:
        raise FrozenB0Unavailable("B0 fallback does not permit caller-supplied environment")
    return {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"}


def validate_no_extra_argv(actual: Sequence[str], expected: FrozenB0LegacyArgvV1) -> None:
    if tuple(actual) != expected.argv:
        raise FrozenB0Unavailable("B0 invocation argv changed or gained an extra argument")
