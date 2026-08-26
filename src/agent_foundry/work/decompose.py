"""Tracker-neutral work decomposition engine."""

from __future__ import annotations

from collections import defaultdict

from agent_foundry.models.base import WorkDecompositionError
from agent_foundry.models.common import DependencyRelation, Reversibility
from agent_foundry.models.work import (
    AdoptionGap,
    CapabilityUnit,
    DecompositionInput,
    DecompositionQualityIssue,
    DependencySpec,
    ExecutionRunRef,
    OutcomeCapability,
    WorkItemContract,
    WorkItemExecutionContext,
    WorkObjective,
    WorkPackage,
    WorkPlan,
    default_schema_version,
)
from agent_foundry.work.grouping import (
    GroupKey,
    capability_group_key,
    resolve_merged_work_class,
    work_item_id_for_group_key,
)
from agent_foundry.work.quality import (
    check_capability_units_pre_grouping,
    check_grouped_units,
    check_work_items,
    work_class_merge_issue,
)
from agent_foundry.work.validate import validate_dependency_graph


def _assert_unique_work_item_ids(work_items: list[WorkItemContract]) -> None:
    ids = [item.id for item in work_items]
    if len(set(ids)) != len(ids):
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        raise WorkDecompositionError(
            f"duplicate work item id after decomposition: {', '.join(duplicates)}"
        )


def _validate_declared_outcomes(
    outcomes: list[OutcomeCapability],
    units: list[CapabilityUnit],
) -> None:
    declared_ids = {outcome.id for outcome in outcomes}
    orphan_outcomes = sorted(
        {unit.outcome_id for unit in units if unit.outcome_id not in declared_ids}
    )
    if orphan_outcomes:
        raise WorkDecompositionError(
            "capability units reference undeclared outcomes: "
            + ", ".join(orphan_outcomes)
        )


def _merge_units(
    units: list[CapabilityUnit],
    *,
    group_key: GroupKey,
    objective: WorkObjective,
    schema_version: str,
    unit_id_to_work_item: dict[str, str],
) -> WorkItemContract:
    primary = sorted(units, key=lambda u: u.id)[0]
    unit_ids = {u.id for u in units}
    work_item_id = work_item_id_for_group_key(group_key)
    merged_work_class = resolve_merged_work_class(units)

    scope: list[str] = []
    out_of_scope: list[str] = []
    acceptance: list[str] = []
    evidence: list[str] = []
    stop_conditions: list[str] = []
    escalation_conditions: list[str] = []
    facts: list[str] = []
    mechanical: list[str] = []
    external_deps: set[str] = set()

    for unit in sorted(units, key=lambda u: u.id):
        scope.extend(unit.scope)
        out_of_scope.extend(unit.out_of_scope)
        acceptance.extend(unit.acceptance_criteria)
        evidence.extend(unit.required_evidence)
        stop_conditions.extend(unit.stop_conditions)
        escalation_conditions.extend(unit.escalation_conditions)
        facts.extend(unit.current_facts)
        mechanical.extend(unit.mechanical_steps)
        for dep_id in unit.depends_on:
            if dep_id not in unit_ids:
                external_deps.add(dep_id)

    dependencies: list[DependencySpec] = []
    for dep_id in sorted(external_deps):
        target = unit_id_to_work_item.get(dep_id, dep_id)
        dependencies.append(
            DependencySpec(
                relation=DependencyRelation.REQUIRES,
                target_id=target,
                description=f"requires completion of {dep_id}",
            )
        )

    title = primary.title
    if len(units) > 1:
        title = f"{primary.title} (causal closure)"

    return WorkItemContract(
        schema_version=schema_version,
        id=work_item_id,
        title=title,
        work_class=merged_work_class,
        objective=objective.description,
        current_facts=sorted(set(facts)),
        scope=sorted(set(scope + mechanical)),
        out_of_scope=sorted(set(out_of_scope)),
        acceptance_criteria=sorted(set(acceptance)),
        dependencies=sorted(
            dependencies,
            key=lambda d: (d.relation.value, d.target_id),
        ),
        authority_class=primary.authority_class,
        consequence_class=primary.consequence_class,
        required_evidence=sorted(set(evidence)),
        stop_conditions=sorted(set(stop_conditions)),
        escalation_conditions=sorted(set(escalation_conditions)),
        rollback_boundary_id=primary.rollback_boundary_id,
        write_scope_id=primary.write_scope_id,
        runtime_external_validation_requirement="required evidence must be produced before closure",
        implementation_references=sorted(set(mechanical)),
    )


def _gap_to_unit(gap: AdoptionGap, outcome_id: str) -> CapabilityUnit:
    boundary = f"adopt-{gap.id}"
    stop_conditions = ["blocked adoption path cannot be resolved within scope"]
    escalation_conditions: list[str] = []
    if gap.blocker:
        stop_conditions.append("blocker gap must be resolved before dependent work proceeds")
        escalation_conditions.append("blocker adoption gap requires human escalation")
    if gap.reversibility == Reversibility.EFFECTIVELY_IRREVERSIBLE:
        stop_conditions.append("adoption change is effectively irreversible; explicit approval required")

    return CapabilityUnit(
        id=f"unit-{gap.id}",
        outcome_id=outcome_id,
        title=f"Adopt: {gap.target}",
        description=gap.rationale,
        work_class=gap.suggested_work_class,
        acceptance_boundary_id=boundary,
        authority_class=gap.authority_class,
        consequence_class=gap.consequence_class,
        rollback_boundary_id=boundary,
        write_scope_id=f"scope-{gap.id}",
        scope=[gap.target],
        acceptance_criteria=[
            f"{gap.action.value} applied to {gap.target}",
            "regression evidence passes",
        ],
        required_evidence=["implementation diff", "validation output"],
        stop_conditions=stop_conditions,
        escalation_conditions=escalation_conditions,
        current_facts=[gap.rationale],
    )


def _packages_for_outcomes(
    outcomes: list[OutcomeCapability],
    units: list[CapabilityUnit],
    work_items: list[WorkItemContract],
    unit_id_to_work_item: dict[str, str],
) -> list[WorkPackage]:
    declared_ids = {outcome.id for outcome in outcomes}
    orphan_outcomes = sorted(
        {unit.outcome_id for unit in units if unit.outcome_id not in declared_ids}
    )
    if orphan_outcomes:
        raise WorkDecompositionError(
            "capability units reference undeclared outcomes: "
            + ", ".join(orphan_outcomes)
        )

    items_by_outcome: dict[str, set[str]] = defaultdict(set)
    for unit in sorted(units, key=lambda u: u.id):
        items_by_outcome[unit.outcome_id].add(unit_id_to_work_item[unit.id])

    packages: list[WorkPackage] = []
    for outcome in sorted(outcomes, key=lambda o: o.id):
        outcome_units = [unit for unit in units if unit.outcome_id == outcome.id]
        item_ids = sorted(items_by_outcome.get(outcome.id, set()))
        if outcome_units and not item_ids:
            raise WorkDecompositionError(
                f"outcome {outcome.id} has capability units but no work items in package"
            )
        packages.append(
            WorkPackage(
                id=f"pkg-{outcome.id}",
                outcome_id=outcome.id,
                title=outcome.title,
                description=outcome.description,
                work_item_ids=item_ids,
            )
        )

    packaged_ids = {item_id for package in packages for item_id in package.work_item_ids}
    work_item_ids = {item.id for item in work_items}
    unpackaged = sorted(work_item_ids - packaged_ids)
    if unpackaged:
        raise WorkDecompositionError(
            "work items are not assigned to any package: " + ", ".join(unpackaged)
        )

    return packages


def decompose_work(input_data: DecompositionInput) -> WorkPlan:
    """Produce a deterministic WorkPlan from objective and capability inputs."""
    schema_version = default_schema_version()
    units = list(input_data.capability_units)
    gaps = sorted(input_data.adoption_gaps, key=lambda g: g.id)

    if gaps and not input_data.outcomes:
        raise WorkDecompositionError("adoption gaps require at least one outcome")

    if gaps:
        default_outcome = sorted(input_data.outcomes, key=lambda o: o.id)[0].id
        for gap in gaps:
            units.append(_gap_to_unit(gap, default_outcome))

    _validate_declared_outcomes(input_data.outcomes, units)

    quality_issues: list[DecompositionQualityIssue] = []
    quality_issues.extend(check_capability_units_pre_grouping(units))

    grouped: dict[GroupKey, list[CapabilityUnit]] = defaultdict(list)
    for unit in sorted(units, key=lambda u: u.id):
        grouped[capability_group_key(unit)].append(unit)

    unit_id_to_work_item: dict[str, str] = {}
    for key in sorted(grouped):
        group_units = sorted(grouped[key], key=lambda u: u.id)
        work_item_id = work_item_id_for_group_key(key)
        for unit in group_units:
            unit_id_to_work_item[unit.id] = work_item_id

    work_items: list[WorkItemContract] = []
    for key in sorted(grouped):
        group_units = sorted(grouped[key], key=lambda u: u.id)
        item = _merge_units(
            group_units,
            group_key=key,
            objective=input_data.objective,
            schema_version=schema_version,
            unit_id_to_work_item=unit_id_to_work_item,
        )
        work_items.append(item)
        merge_issue = work_class_merge_issue(
            group_units,
            work_item_id=item.id,
            chosen=item.work_class.value,
        )
        if merge_issue is not None:
            quality_issues.append(merge_issue)

    work_items = sorted(work_items, key=lambda wi: wi.id)
    _assert_unique_work_item_ids(work_items)
    validate_dependency_graph(work_items)

    quality_issues.extend(check_grouped_units(units, unit_id_to_work_item))
    quality_issues.extend(check_work_items(work_items))

    packages = _packages_for_outcomes(
        sorted(input_data.outcomes, key=lambda o: o.id),
        units,
        work_items,
        unit_id_to_work_item,
    )

    return WorkPlan(
        schema_version=schema_version,
        objective=input_data.objective,
        outcomes=sorted(input_data.outcomes, key=lambda o: o.id),
        packages=packages,
        work_items=work_items,
        quality_issues=sorted(
            quality_issues,
            key=lambda q: (q.flag.value, q.work_item_id or "", q.message),
        ),
    )


def attach_execution_run(
    context: WorkItemExecutionContext,
    *,
    run_id: str,
) -> WorkItemExecutionContext:
    """Attach a new execution run; the Work Item contract payload is not modified."""
    contract = context.contract.model_copy(deep=True)
    runs = list(context.runs) + [
        ExecutionRunRef(id=run_id, work_item_id=contract.id)
    ]
    return WorkItemExecutionContext(
        contract=contract,
        runs=sorted(runs, key=lambda r: r.id),
    )
