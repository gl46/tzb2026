"""Independent structural evaluator for Qwen commander S5 plans."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence

from xh_agent.qwen_brain.contracts_v1 import CommanderPlanV1
from xh_agent.qwen_brain.s5_schemas_v1 import (
    S5EvaluationExpectationV1,
    S5EvaluationRecordV1,
    S5ReassociationBoundaryAuditV1,
)

PHYSICAL_PRIMITIVES = frozenset(
    {
        "CARTESIAN_POSE",
        "GRIPPER_POSITION",
        "ATTACH_CONTACT_ENTITY",
        "REMOVE_ATTACHMENT",
    }
)


def flatten_primitives(plan: CommanderPlanV1) -> list[str]:
    return [
        step.primitive
        for subtask in plan.subtasks
        for step in subtask.skill_plan
    ]


def flatten_target_refs(plan: CommanderPlanV1) -> set[str]:
    refs: set[str] = set()
    for subtask in plan.subtasks:
        for step in subtask.skill_plan:
            parameters = step.parameters.model_dump(mode="json")
            target_ref = parameters.get("target_ref")
            if isinstance(target_ref, str):
                refs.add(target_ref)
    return refs


def audit_reassociation_boundary(
    plan: CommanderPlanV1,
    *,
    unresolved_binding: bool,
) -> S5ReassociationBoundaryAuditV1:
    primitives = flatten_primitives(plan)
    reassociation_indices = [
        index
        for index, primitive in enumerate(primitives)
        if primitive == "PUBLIC_TRACK_REASSOCIATION"
    ]
    reasons: list[str] = []
    physical_after: list[str] = []
    if unresolved_binding:
        if not reassociation_indices:
            reasons.append("unresolved binding requires PUBLIC_TRACK_REASSOCIATION")
        else:
            last_reassociation = reassociation_indices[-1]
            physical_after = [
                primitive
                for primitive in primitives[last_reassociation + 1 :]
                if primitive in PHYSICAL_PRIMITIVES
            ]
            if last_reassociation != len(primitives) - 1:
                reasons.append("PUBLIC_TRACK_REASSOCIATION must terminate the current plan")
            if physical_after:
                reasons.append("physical primitive appears after reassociation")
    return S5ReassociationBoundaryAuditV1(
        unresolved_binding=unresolved_binding,
        flattened_primitive_count=len(primitives),
        reassociation_indices=reassociation_indices,
        physical_after_reassociation=physical_after,
        status="PASS" if not reasons else "FAIL",
        reasons=reasons,
    )


def evaluate_plan(
    *,
    case_id: str,
    plan: CommanderPlanV1,
    expectation: S5EvaluationExpectationV1,
) -> S5EvaluationRecordV1:
    primitives = flatten_primitives(plan)
    primitive_counts = Counter(primitives)
    required_counts = Counter(expectation.required_primitives)
    missing = sorted(
        primitive
        for primitive, count in required_counts.items()
        if primitive_counts[primitive] < count
    )
    forbidden = sorted(set(primitives) & set(expectation.forbidden_primitives))
    target_refs = flatten_target_refs(plan)
    missing_target_refs = sorted(set(expectation.expected_target_refs) - target_refs)
    outcome = "REFUSE" if plan.refused else "PLAN"
    boundary = audit_reassociation_boundary(
        plan,
        unresolved_binding=expectation.unresolved_binding,
    )
    reasons: list[str] = []
    if outcome != expectation.expected_outcome:
        reasons.append(
            f"outcome mismatch: expected {expectation.expected_outcome}, observed {outcome}"
        )
    if missing:
        reasons.append(f"missing required primitives: {missing}")
    if forbidden:
        reasons.append(f"forbidden primitives present: {forbidden}")
    if missing_target_refs:
        reasons.append(f"missing expected target refs: {missing_target_refs}")
    if boundary.status != "PASS":
        reasons.extend(f"reassociation boundary: {reason}" for reason in boundary.reasons)

    primitive_checks_pass = not missing and not forbidden and not missing_target_refs
    expectation_match = (
        outcome == expectation.expected_outcome
        and primitive_checks_pass
        and boundary.status == "PASS"
    )
    return S5EvaluationRecordV1(
        case_id=case_id,
        strict_valid=True,
        observed_outcome=outcome,
        expectation_match=expectation_match,
        primitive_checks_pass=primitive_checks_pass,
        reassociation_boundary=boundary,
        reasons=reasons,
    )


def evaluate_plan_payload(
    *,
    case_id: str,
    payload: object,
    expectation: S5EvaluationExpectationV1,
) -> S5EvaluationRecordV1:
    try:
        plan = CommanderPlanV1.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - invalid model output remains in denominator
        return S5EvaluationRecordV1(
            case_id=case_id,
            strict_valid=False,
            observed_outcome="ERROR",
            expectation_match=False,
            primitive_checks_pass=False,
            reassociation_boundary=None,
            reasons=[f"{type(exc).__name__}: {exc}"],
        )
    return evaluate_plan(case_id=case_id, plan=plan, expectation=expectation)


def deterministic_derangement(
    sample_ids: Sequence[str],
    *,
    group_by_sample: Mapping[str, str] | None = None,
) -> dict[str, str | None]:
    """Pair each sample with another in its group; singleton groups stay explicit."""

    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("sample IDs must be unique")
    groups: dict[str, list[str]] = defaultdict(list)
    for sample_id in sorted(sample_ids):
        group = group_by_sample[sample_id] if group_by_sample is not None else "ALL"
        groups[group].append(sample_id)

    result: dict[str, str | None] = {}
    for members in groups.values():
        if len(members) < 2:
            result[members[0]] = None
            continue
        for index, sample_id in enumerate(members):
            result[sample_id] = members[(index + 1) % len(members)]
    return result


def paired_transition_matrix(
    baseline_outcomes: Mapping[str, bool],
    candidate_outcomes: Mapping[str, bool],
) -> dict[str, int]:
    if set(baseline_outcomes) != set(candidate_outcomes):
        raise ValueError("paired systems must use the same full denominator")
    counts = Counter(
        (baseline_outcomes[case_id], candidate_outcomes[case_id])
        for case_id in sorted(baseline_outcomes)
    )
    return {
        "pass_to_pass": counts[(True, True)],
        "pass_to_fail": counts[(True, False)],
        "fail_to_pass": counts[(False, True)],
        "fail_to_fail": counts[(False, False)],
        "case_count": len(baseline_outcomes),
    }


def all_case_ids_unique(case_ids: Iterable[str]) -> bool:
    values = list(case_ids)
    return len(values) == len(set(values))
