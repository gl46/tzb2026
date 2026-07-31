"""Auditable Isaac PhysX collision evidence for QRM runtime gates.

The model never receives these simulator-only contact paths.  They are used
solely by the execution/planning validation layer to reject an unsafe mapped
B0 skill and to retain the reason in evidence.
"""

from __future__ import annotations

from typing import Any, Iterable


def _contact_path(event: dict[str, Any], side: int) -> str:
    collider = str(event.get(f"collider{side}", ""))
    if collider.startswith("/"):
        return collider
    return str(event.get(f"actor{side}", ""))


def _matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


def evaluate_robot_collision_events(
    events: Iterable[dict[str, Any]],
    *,
    phase: str,
    robot_prefix: str = "/World/Robot",
    allowed_robot_collider_prefixes: tuple[str, ...] = (),
    allowed_external_collider_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Classify official PhysX reports without feeding truth to the policy.

    A robot/external contact is allowed only when both its robot collider and
    external collider match explicit phase-local allowlists.  Robot self
    contacts are always unexpected.  Non-robot scene contacts are retained in
    the source log but do not affect the robot collision gate.
    """

    unique: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    for raw in events:
        event = dict(raw)
        path0 = _contact_path(event, 0)
        path1 = _contact_path(event, 1)
        key = (
            int(event.get("physics_step", -1)),
            int(event.get("event_type", -1)),
            path0,
            path1,
        )
        unique[key] = {**event, "resolved_path0": path0, "resolved_path1": path1}

    robot_contacts: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    for event in unique.values():
        path0 = str(event["resolved_path0"])
        path1 = str(event["resolved_path1"])
        side0_robot = _matches(path0, (robot_prefix,))
        side1_robot = _matches(path1, (robot_prefix,))
        if not (side0_robot or side1_robot):
            continue
        robot_contacts.append(event)
        if side0_robot and side1_robot:
            unexpected.append(event)
            continue
        robot_path, external_path = (
            (path0, path1) if side0_robot else (path1, path0)
        )
        is_allowed = _matches(
            robot_path, allowed_robot_collider_prefixes
        ) and _matches(external_path, allowed_external_collider_prefixes)
        (allowed if is_allowed else unexpected).append(event)

    return {
        "schema_version": "M2BIsaacCollisionGateV1",
        "status": "PASS" if not unexpected else "REJECTED",
        "phase": phase,
        "source": "ISAAC_PHYSX_CONTACT_REPORT_EXECUTION_MONITOR",
        "contact_reporting_required": True,
        "robot_prefix": robot_prefix,
        "allowed_robot_collider_prefixes": list(allowed_robot_collider_prefixes),
        "allowed_external_collider_prefixes": list(
            allowed_external_collider_prefixes
        ),
        "events_total": len(unique),
        "robot_contact_events": len(robot_contacts),
        "allowed_robot_contact_events": len(allowed),
        "unexpected_robot_contact_events": len(unexpected),
        "unexpected_contacts": unexpected,
        "privileged_truth_policy_input": False,
        "teacher_used": False,
    }
