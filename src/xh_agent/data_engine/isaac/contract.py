"""Isaac Industrial Dataset V1 validation and non-Oracle boundary.

The canonical episode deliberately keeps ``simulator_supervision`` beside,
not inside, the policy projection.  Training code must call
``policy_projection`` and explicitly request labels separately.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


ACTION_DIMENSION_NAMES = [
    "dx",
    "dy",
    "dz",
    "r6d_0",
    "r6d_1",
    "r6d_2",
    "r6d_3",
    "r6d_4",
    "r6d_5",
    "gripper",
]

FORBIDDEN_POLICY_KEYS = {
    "actual_sim_entity_id",
    "attached_entity",
    "constraint_internal_id",
    "entity_name",
    "failure_oracle",
    "perfect_bin_occupancy",
    "perfect_contact_identity",
    "perfect_object_pose",
    "perfect_object_poses",
    "prim_path",
    "rigid_body_name",
    "simulator_supervision",
    "success_oracle",
    "target_object",
    "task_success",
}

_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"(?:^|/)World(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|[/_-])cylinder_\d+(?:$|[/_.-])", re.IGNORECASE),
    re.compile(r"(?:^|/)RigidBody(?:/|$)", re.IGNORECASE),
)


class ShardState(str, Enum):
    WRITING = "WRITING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    SYNCED = "SYNCED"
    QUARANTINED = "QUARANTINED"


_ALLOWED_TRANSITIONS = {
    ShardState.WRITING: {ShardState.VALIDATING, ShardState.QUARANTINED},
    ShardState.VALIDATING: {ShardState.READY, ShardState.QUARANTINED},
    ShardState.READY: {ShardState.SYNCED, ShardState.QUARANTINED},
    ShardState.SYNCED: set(),
    ShardState.QUARANTINED: set(),
}


def transition_shard_state(current: ShardState | str, target: ShardState | str) -> ShardState:
    source = ShardState(current)
    destination = ShardState(target)
    if destination not in _ALLOWED_TRANSITIONS[source]:
        raise ValueError(f"invalid shard state transition: {source.value} -> {destination.value}")
    return destination


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            child = (*path, str(key))
            yield child, item
            yield from _walk(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, (*path, str(index)))


def audit_policy_projection(policy: dict[str, Any]) -> list[str]:
    """Return Oracle-leak findings without inspecting offline supervision."""

    findings: list[str] = []
    for path, value in _walk(policy):
        key = path[-1].lower()
        dotted = ".".join(path)
        if key in FORBIDDEN_POLICY_KEYS:
            findings.append(f"forbidden key at {dotted}")
        if key in {"track_id", "object_id", "target_track_id", "rgb_uri", "depth_uri"}:
            text = str(value)
            if any(pattern.search(text) for pattern in _FORBIDDEN_VALUE_PATTERNS):
                findings.append(f"entity truth encoded in {dotted}")
    return sorted(set(findings))


def policy_projection(episode: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_before": episode["observation_before"],
        "observation_after": episode["observation_after"],
        "task_spec": episode["task_spec"],
        "robot_state": episode["robot_state"],
        "skill_history": episode["skill_history"],
        "failure_context": episode["failure_context"],
        "nominal_skill": episode["nominal_skill"],
        "nominal_action": episode["nominal_action"],
        "executed_action": episode["executed_action"],
        "expected_predicates": episode["expected_predicates"],
        "observed_predicates": episode["observed_predicates"],
        "recovery_sequence": episode["recovery_sequence"],
    }


def _finite_rows(action: dict[str, Any], *, label: str) -> list[str]:
    errors: list[str] = []
    required = {
        "coordinate_frame",
        "units",
        "frequency_hz",
        "chunk_length",
        "dimension_names",
        "normalization_revision",
        "values",
    }
    missing = required - set(action)
    if missing:
        return [f"{label} missing fields: {sorted(missing)}"]
    rows = action["values"]
    dimensions = action["dimension_names"]
    if action["chunk_length"] != len(rows):
        errors.append(f"{label} chunk_length mismatch")
    for row in rows:
        if len(row) != len(dimensions):
            errors.append(f"{label} dimension mismatch")
            break
        if not all(math.isfinite(float(value)) for value in row):
            errors.append(f"{label} contains NaN/Inf")
            break
    return errors


def validate_episode(episode: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version",
        "dataset_version",
        "episode_id",
        "scene_seed",
        "scene_group_id",
        "split",
        "worker_id",
        "code_revision",
        "isaac_version",
        "scene_asset_revision",
        "config_hash",
        "observation_before",
        "observation_after",
        "task_spec",
        "robot_state",
        "skill_history",
        "failure_context",
        "nominal_skill",
        "nominal_action",
        "executed_action",
        "residual_action",
        "expected_predicates",
        "observed_predicates",
        "recovery_sequence",
        "result",
        "simulator_supervision",
        "provenance",
    }
    missing = required - set(episode)
    if missing:
        return [f"missing fields: {sorted(missing)}"]
    if episode["schema_version"] != "IsaacIndustrialEpisodeV1":
        errors.append("unsupported schema_version")
    if episode["split"] not in {"train", "val", "test"}:
        errors.append("invalid split")
    for action_name in ("nominal_action", "executed_action", "residual_action"):
        errors.extend(_finite_rows(episode[action_name], label=action_name))
    before_ns = int(episode["observation_before"]["timestamp_ns"])
    after_ns = int(episode["observation_after"]["timestamp_ns"])
    if after_ns <= before_ns:
        errors.append("timestamps are not strictly monotonic")
    if episode["simulator_supervision"].get("training_and_evaluation_only") is not True:
        errors.append("SimulatorSupervision boundary marker missing")
    errors.extend(audit_policy_projection(policy_projection(episode)))
    return sorted(set(errors))


def stable_split(scene_seed: int) -> tuple[str, str]:
    """Episode/scene-level 70/15/15 split with deterministic OOD marking."""

    bucket = int(scene_seed) % 20
    split = "train" if bucket < 14 else "val" if bucket < 17 else "test"
    kind = "OOD" if split == "test" and bucket == 19 else "compositional" if split != "train" else "IID"
    return split, kind


def atomic_write_json(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)

