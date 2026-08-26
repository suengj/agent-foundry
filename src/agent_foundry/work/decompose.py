"""Tracker-neutral work decomposition engine."""

from __future__ import annotations

from collections import defaultdict

from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.common import DependencyRelation
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
)
from agent_foundry.work.quality import check_capability_units, check_work_items
from agent_foundry.work.validate import validate_dependency_graph


def _group_key(unit: CapabilityUnit) -> tuple[str, str, str, str]:
    return (
        unit.acceptance_boundary_id,
        unit.authority_class.value,
        unit.rollback_boundary_id,
        unit.write_scope_id,
    )


def _merge_units(
    units: list[CapabilityUnit],
    *,
    objective: WorkObjective,
    schema_version: str,
    unit_id_to_work_item: dict[str, str],
) -> WorkItemContract:
    primary = sorted(units, key=lambda u: u.id)[0]
    unit_ids = {u.id for u in units}
    work_item_id = f"wi-{primary.acceptance_boundary_id}"

    scope: list[str] = []
    out_of_scope: list[str] = []
    acceptance: list[str] = []
    evidence: list[str] = []
    stop_conditions: list[str] = []
    facts: list[str] = []
    mechanical: list[str] = []
    external_deps: set[str] = set()

    for unit in sorted(units, key=lambda u: u.id):
        scope.extend(unit.scope)
        out_of_scope.extend(unit.out_of_scope)
        acceptance.extend(unit.acceptance_criteria)
        evidence.extend(unit.required_evidence)
        stop_conditions.extend(unit.stop_conditions)
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
        work_class=primary.work_class,
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
        rollback_boundary_id=primary.rollback_boundary_id,
        write_scope_id=primary.write_scope_id,
        runtime_external_validation_requirement="required evidence must be produced before closure",
        implementation_references=sorted(set(mechanical)),
    )


def _gap_to_unit(gap: AdoptionGap, outcome_id: str) -> CapabilityUnit:
    boundary = f"adopt-{gap.id}"
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
        stop_conditions=["blocked adoption path cannot be resolved within scope"],
        current_facts=[gap.rationale],
    )


def _packages_for_outcomes(
    outcomes: list[OutcomeCapability],
    work_items: list[WorkItemContract],
    units: list[CapabilityUnit],
) -> list[WorkPackage]:
    boundary_to_outcome: dict[str, str] = {}
    for unit in sorted(units, key=lambda u: u.id):
        boundary_to_outcome[unit.acceptance_boundary_id] = unit.outcome_id

    items_by_outcome: dict[str, list[str]] = defaultdict(list)
    for item in sorted(work_items, key=lambda wi: wi.id):
        boundary = item.id.removeprefix("wi-")
        outcome_id = boundary_to_outcome.get(boundary)
        if outcome_id:
            items_by_outcome[outcome_id].append(item.id)

    packages: list[WorkPackage] = []
    for outcome in sorted(outcomes, key=lambda o: o.id):
        packages.append(
            WorkPackage(
                id=f"pkg-{outcome.id}",
                outcome_id=outcome.id,
                title=outcome.title,
                description=outcome.description,
                work_item_ids=sorted(items_by_outcome.get(outcome.id, [])),
            )
        )
    return packages


def decompose_work(input_data: DecompositionInput) -> WorkPlan:
    """Produce a deterministic WorkPlan from objective and capability inputs."""
    schema_version = FOUNDRY_SCHEMA_VERSION
    units = list(input_data.capability_units)
    gaps = sorted(input_data.adoption_gaps, key=lambda g: g.id)

    if gaps:
        default_outcome = sorted(input_data.outcomes, key=lambda o: o.id)[0].id
        for gap in gaps:
            units.append(_gap_to_unit(gap, default_outcome))

    grouped: dict[tuple[str, str, str, str], list[CapabilityUnit]] = defaultdict(list)
    for unit in sorted(units, key=lambda u: u.id):
        grouped[_group_key(unit)].append(unit)

    unit_id_to_work_item: dict[str, str] = {}
    for key in sorted(grouped):
        group_units = sorted(grouped[key], key=lambda u: u.id)
        work_item_id = f"wi-{group_units[0].acceptance_boundary_id}"
        for unit in group_units:
            unit_id_to_work_item[unit.id] = work_item_id

    work_items: list[WorkItemContract] = []
    for key in sorted(grouped):
        group_units = sorted(grouped[key], key=lambda u: u.id)
        work_items.append(
            _merge_units(
                group_units,
                objective=input_data.objective,
                schema_version=schema_version,
                unit_id_to_work_item=unit_id_to_work_item,
            )
        )

    work_items = sorted(work_items, key=lambda wi: wi.id)
    validate_dependency_graph(work_items)

    quality_issues: list[DecompositionQualityIssue] = []
    quality_issues.extend(check_capability_units(units))
    quality_issues.extend(check_work_items(work_items))

    packages = _packages_for_outcomes(
        sorted(input_data.outcomes, key=lambda o: o.id),
        work_items,
        units,
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
    """Attach a new execution run without mutating the Work Item contract."""
    runs = list(context.runs) + [
        ExecutionRunRef(id=run_id, work_item_id=context.contract.id)
    ]
    return WorkItemExecutionContext(
        contract=context.contract,
        runs=sorted(runs, key=lambda r: r.id),
    )
