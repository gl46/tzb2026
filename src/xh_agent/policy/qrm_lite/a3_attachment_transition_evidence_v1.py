"""Replayable query-only attachment-state planning evidence for ADR-0022 A.3.

The exact-plan preflight does not create an attachment and does not predict a
physical contact outcome.  It only proves that an ATTACH phase names exactly
one deterministic two-finger/external-path broker candidate, or that a REMOVE
phase consumes the already bound attachment identity.  The real executor must
still obtain the physical bilateral-contact broker result before it mutates
the scene.

This module is intentionally pure data.  It rejects TaskSpec/Teacher/truth
inputs by construction and derives the planned attachment identity from the
frozen plan, phase, path, runtime snapshot and allowlists.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    SHA256_PATTERN,
    canonical_sha256,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class A3PlannedBilateralContactPairV1(_FrozenModel):
    left_robot_path: str = Field(pattern=r"^/World/Robot/[^\s]+$")
    right_robot_path: str = Field(pattern=r"^/World/Robot/[^\s]+$")
    external_path: str = Field(pattern=r"^/World/M1B/[^\s]+$")

    @model_validator(mode="after")
    def distinct_fingers(self) -> "A3PlannedBilateralContactPairV1":
        if self.left_robot_path == self.right_robot_path:
            raise ValueError("A.3 planned bilateral pair repeats one robot path")
        return self


def _finger_side(path: str) -> Literal["LEFT", "RIGHT"] | None:
    leaf = path.rsplit("/", 1)[-1].lower()
    left = "left" in leaf
    right = "right" in leaf
    if left == right:
        return None
    return "LEFT" if left else "RIGHT"


def canonical_planned_bilateral_pair_v1(
    *,
    allowed_robot_contact_paths: tuple[str, ...],
    allowed_external_contact_paths: tuple[str, ...],
) -> A3PlannedBilateralContactPairV1:
    """Select one explicit left/right/external allowlist tuple or reject."""

    if (
        len(allowed_robot_contact_paths) != 2
        or len(set(allowed_robot_contact_paths)) != 2
        or len(allowed_external_contact_paths) != 1
        or len(set(allowed_external_contact_paths)) != 1
    ):
        raise ValueError("A.3 attachment allowlists do not name one bilateral pair")
    sided = {side: path for path in allowed_robot_contact_paths if (side := _finger_side(path))}
    if set(sided) != {"LEFT", "RIGHT"}:
        raise ValueError("A.3 attachment allowlist lacks one left and one right finger")
    return A3PlannedBilateralContactPairV1(
        left_robot_path=sided["LEFT"],
        right_robot_path=sided["RIGHT"],
        external_path=allowed_external_contact_paths[0],
    )


def canonical_planned_attachment_sha256_v1(
    *,
    bound_plan_sha256: str,
    phase_index: int,
    phase_sha256: str,
    path_sha256: str,
    runtime_snapshot_sha256: str,
    pair: A3PlannedBilateralContactPairV1,
    attachment_configuration_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "schema_version": "A3PlannedAttachmentIdentityV1",
            "bound_plan_sha256": bound_plan_sha256,
            "phase_index": phase_index,
            "phase_sha256": phase_sha256,
            "path_sha256": path_sha256,
            "runtime_snapshot_sha256": runtime_snapshot_sha256,
            "pair": pair.model_dump(mode="json"),
            "attachment_configuration_sha256": attachment_configuration_sha256,
        }
    )


class A3AttachmentTransitionEvidenceV1(_FrozenModel):
    """Complete deterministic input/output projection for one phase."""

    schema_version: Literal["A3AttachmentTransitionEvidenceV1"] = "A3AttachmentTransitionEvidenceV1"
    bound_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    phase_index: int = Field(ge=0)
    phase_sha256: str = Field(pattern=SHA256_PATTERN)
    path_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_snapshot_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_snapshot_provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    provider_implementation_sha256: str = Field(pattern=SHA256_PATTERN)
    algorithm_sha256: str = Field(pattern=SHA256_PATTERN)
    attachment_configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    command: Literal[
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "REMOVE_ATTACHMENT",
        "PUBLIC_RGBD_CAPTURE",
        "PUBLIC_TRACK_REASSOCIATION",
    ]
    transition: Literal["NONE", "ATTACH", "REMOVE"]
    attachment_or_removal_selector: Literal[
        "NONE",
        "TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST",
        "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT",
    ]
    allowed_robot_contact_paths: tuple[str, ...]
    allowed_external_contact_paths: tuple[str, ...]
    planned_bilateral_pair: A3PlannedBilateralContactPairV1 | None
    attachment_present_before: bool
    attachment_sha256_before: str | None = Field(default=None, pattern=SHA256_PATTERN)
    attachment_present_after: bool
    attachment_sha256_after: str | None = Field(default=None, pattern=SHA256_PATTERN)
    real_runtime_snapshot: bool
    formal_query_evidence_eligible: bool
    query_only: Literal[True] = True
    articulation_target_writes: Literal[0] = 0
    simulation_steps: Literal[0] = 0
    scene_mutations: Literal[0] = 0
    teacher_used: Literal[False] = False
    privileged_truth_policy_input: Literal[False] = False
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def replay_transition(self) -> "A3AttachmentTransitionEvidenceV1":
        if self.attachment_present_before != (self.attachment_sha256_before is not None):
            raise ValueError("A.3 attachment before-state identity differs")
        if self.attachment_present_after != (self.attachment_sha256_after is not None):
            raise ValueError("A.3 attachment after-state identity differs")
        expected_transition = {
            "ATTACH_CONTACT_ENTITY": "ATTACH",
            "REMOVE_ATTACHMENT": "REMOVE",
        }.get(self.command, "NONE")
        expected_selector = {
            "ATTACH_CONTACT_ENTITY": ("TERMINAL_BILATERAL_CONTACT_BROKER_WITHIN_BOUND_ALLOWLIST"),
            "REMOVE_ATTACHMENT": "REMOVE_PREVIOUSLY_BOUND_ATTACHMENT",
        }.get(self.command, "NONE")
        if (
            self.transition != expected_transition
            or self.attachment_or_removal_selector != expected_selector
        ):
            raise ValueError("A.3 attachment transition/selector differs from command")

        if expected_transition == "ATTACH":
            if self.attachment_present_before:
                raise ValueError("A.3 attachment plan attempts to attach twice")
            try:
                expected_pair = canonical_planned_bilateral_pair_v1(
                    allowed_robot_contact_paths=self.allowed_robot_contact_paths,
                    allowed_external_contact_paths=self.allowed_external_contact_paths,
                )
            except ValueError as exc:
                raise ValueError("A.3 planned bilateral pair is not unique") from exc
            expected_after = canonical_planned_attachment_sha256_v1(
                bound_plan_sha256=self.bound_plan_sha256,
                phase_index=self.phase_index,
                phase_sha256=self.phase_sha256,
                path_sha256=self.path_sha256,
                runtime_snapshot_sha256=self.runtime_snapshot_sha256,
                pair=expected_pair,
                attachment_configuration_sha256=self.attachment_configuration_sha256,
            )
            if (
                self.planned_bilateral_pair != expected_pair
                or not self.attachment_present_after
                or self.attachment_sha256_after != expected_after
            ):
                raise ValueError("A.3 planned bilateral attachment identity differs")
        elif expected_transition == "REMOVE":
            if (
                not self.attachment_present_before
                or self.planned_bilateral_pair is not None
                or self.attachment_present_after
                or self.attachment_sha256_after is not None
            ):
                raise ValueError("A.3 planned removal does not consume the bound attachment")
        elif (
            self.planned_bilateral_pair is not None
            or self.attachment_present_after != self.attachment_present_before
            or self.attachment_sha256_after != self.attachment_sha256_before
        ):
            raise ValueError("A.3 non-transition phase changes planned attachment state")

        if self.formal_query_evidence_eligible != self.real_runtime_snapshot:
            raise ValueError("A.3 attachment formal eligibility differs from runtime snapshot")
        expected_digest = canonical_sha256(
            self.model_dump(mode="json", exclude={"evidence_sha256"})
        )
        if self.evidence_sha256 != expected_digest:
            raise ValueError("A.3 attachment transition evidence digest differs")
        return self


def build_a3_attachment_transition_evidence_v1(
    **payload: object,
) -> A3AttachmentTransitionEvidenceV1:
    return A3AttachmentTransitionEvidenceV1(
        **payload,
        evidence_sha256=canonical_sha256(payload),
    )
