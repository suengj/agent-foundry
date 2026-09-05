"""Tests for tracker-neutral work decomposition and state separation."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.models import DependencyGraphError, WorkDecompositionError
from agent_foundry.models.common import (
    AdoptionAction,
    ConsequenceClass,
    EvidenceState,
    ExecutionState,
    ExternalEffectClass,
    WorkClass,
    WorkLifecycleState,
)
from agent_foundry.models.io import dump_json
from agent_foundry.models.work import (
    AdoptionGap,
    CapabilityUnit,
    DecompositionInput,
    DecompositionQualityFlag,
    EvidenceStateSnapshot,
    ExecutionRunRef,
    WorkItemContract,
    WorkItemExecutionContext,
    WorkLifecycleSnapshot,
    WorkObjective,
    OutcomeCapability,
    WorkPlan,
)
from agent_foundry.work import attach_execution_run, decompose_work, validate_dependency_graph

REPO_ROOT = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _objective() -> WorkObjective:
    return WorkObjective(
        id="obj-platform",
        title="Platform contracts",
        description="Deliver typed provider-neutral contracts",
    )


def _outcome(outcome_id: str = "out-contracts", title: str = "Contract layer") -> OutcomeCapability:
    return OutcomeCapability(
        id=outcome_id,
        objective_id="obj-platform",
        title=title,
        description=f"{title} capability",
    )


def _assert_every_work_item_in_exactly_one_package(plan: WorkPlan) -> None:
    packaged: dict[str, int] = {}
    for package in plan.packages:
        for item_id in package.work_item_ids:
            packaged[item_id] = packaged.get(item_id, 0) + 1
    for item in plan.work_items:
        assert packaged.get(item.id) == 1, f"{item.id} package membership={packaged.get(item.id)}"


def _base_unit_fields() -> dict[str, object]:
    return {
        "outcome_id": "out-contracts",
        "work_class": WorkClass.CAPABILITY,
        "acceptance_boundary_id": "boundary-shared",
        "authority_class": ExternalEffectClass.REPOSITORY_WRITE,
        "consequence_class": ConsequenceClass.MEDIUM,
        "rollback_boundary_id": "rollback-shared",
        "write_scope_id": "scope-shared",
        "discovery_only": False,
        "mutates_external": False,
        "acceptance_criteria": ["capability delivered with evidence"],
        "required_evidence": ["validation output"],
        "stop_conditions": ["escalate if authority unclear"],
    }


def _make_unit(unit_id: str, title: str, **overrides: object) -> CapabilityUnit:
    fields = _base_unit_fields()
    fields.update(overrides)
    return CapabilityUnit(id=unit_id, title=title, description=title, **fields)


def _pair_units(
    left_id: str,
    right_id: str,
    *,
    left_overrides: dict[str, object] | None = None,
    right_overrides: dict[str, object] | None = None,
) -> list[CapabilityUnit]:
    return [
        _make_unit(left_id, left_id, **(left_overrides or {})),
        _make_unit(right_id, right_id, **(right_overrides or {})),
    ]


def _single_causal_capability_units() -> list[CapabilityUnit]:
    shared = _base_unit_fields()
    shared["acceptance_boundary_id"] = "boundary-contract-layer"
    shared["rollback_boundary_id"] = "rollback-contract-layer"
    shared["write_scope_id"] = "scope-contract-models"
    shared["acceptance_criteria"] = [
        "contract defined and consumed by authoritative path",
        "regression evidence passes",
        "required review complete",
    ]
    shared["required_evidence"] = ["pytest green", "review sign-off"]
    shared["stop_conditions"] = ["semantics cannot be expressed without inventing behaviour"]
    return [
        CapabilityUnit(
            id="unit-schema",
            title="Contract schema",
            description="Define typed contract models",
            scope=["models package"],
            mechanical_steps=["add schema"],
            **shared,
        ),
        CapabilityUnit(
            id="unit-tests",
            title="Contract tests",
            description="Regression coverage for contracts",
            scope=["contract tests"],
            mechanical_steps=["add tests"],
            **shared,
        ),
        CapabilityUnit(
            id="unit-review",
            title="Contract review",
            description="Independent review of contract layer",
            scope=["review gate"],
            mechanical_steps=["complete review"],
            **shared,
        ),
    ]


def test_causal_capability_not_split_by_schema_tests_review() -> None:
    """One causal capability must not split schema, tests, and review."""
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=_single_causal_capability_units(),
        )
    )
    assert len(plan.work_items) == 1
    item = plan.work_items[0]
    assert "schema" in " ".join(item.scope).lower()
    assert "tests" in " ".join(item.scope).lower()
    assert "review" in " ".join(item.scope).lower()
    assert item.acceptance_criteria
    assert item.required_evidence
    assert item.stop_conditions
    _assert_every_work_item_in_exactly_one_package(plan)


@pytest.mark.parametrize(
    ("field", "left_value", "right_value"),
    [
        ("acceptance_boundary_id", "boundary-a", "boundary-b"),
        ("authority_class", ExternalEffectClass.REPOSITORY_WRITE, ExternalEffectClass.RUNTIME_MUTATION),
        ("rollback_boundary_id", "rollback-a", "rollback-b"),
        ("write_scope_id", "scope-a", "scope-b"),
        ("outcome_id", "out-one", "out-two"),
        ("consequence_class", ConsequenceClass.LOW, ConsequenceClass.CRITICAL),
        ("discovery_only", False, True),
        ("mutates_external", False, True),
    ],
    ids=[
        "acceptance_boundary_id",
        "authority_class",
        "rollback_boundary_id",
        "write_scope_id",
        "outcome_id",
        "consequence_class",
        "discovery_only",
        "mutates_external",
    ],
)
def test_splits_on_single_group_key_dimension(
    field: str,
    left_value: object,
    right_value: object,
) -> None:
    if field == "outcome_id":
        outcomes = [_outcome("out-one"), _outcome("out-two", "Second outcome")]
        units = _pair_units(
            "unit-left",
            "unit-right",
            left_overrides={field: left_value},
            right_overrides={field: right_value},
        )
    else:
        outcomes = [_outcome("out-shared", "Shared outcome")]
        units = _pair_units(
            "unit-left",
            "unit-right",
            left_overrides={field: left_value, "outcome_id": "out-shared"},
            right_overrides={field: right_value, "outcome_id": "out-shared"},
        )
    plan = decompose_work(
        DecompositionInput(objective=_objective(), outcomes=outcomes, capability_units=units)
    )
    assert len(plan.work_items) == 2
    assert len({item.id for item in plan.work_items}) == 2
    _assert_every_work_item_in_exactly_one_package(plan)


def test_orphan_outcome_id_raises() -> None:
    units = [
        _make_unit(
            "unit-orphan",
            "orphan unit",
            outcome_id="out-missing",
        )
    ]
    with pytest.raises(WorkDecompositionError, match="undeclared outcomes"):
        decompose_work(
            DecompositionInput(
                objective=_objective(),
                outcomes=[_outcome("out-declared", "Declared outcome")],
                capability_units=units,
            )
        )


def test_different_work_classes_merge_with_recorded_quality_issue() -> None:
    shared = _base_unit_fields()
    shared.pop("work_class")
    shared["acceptance_boundary_id"] = "boundary-contract"
    shared["write_scope_id"] = "scope-contract"
    units = [
        CapabilityUnit(
            id="unit-amend",
            title="Amend the contract",
            description="Amend the contract",
            work_class=WorkClass.CONTRACT_AMENDMENT,
            **shared,
        ),
        CapabilityUnit(
            id="unit-capability",
            title="Wire authoritative consumer",
            description="Wire authoritative consumer",
            work_class=WorkClass.CAPABILITY,
            **shared,
        ),
    ]
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=units,
        )
    )
    assert len(plan.work_items) == 1
    assert plan.work_items[0].work_class == WorkClass.CONTRACT_AMENDMENT
    flags = {issue.flag.value for issue in plan.quality_issues}
    assert "mixed-work-class" in flags
    _assert_every_work_item_in_exactly_one_package(plan)


def test_work_item_ids_unique_when_acceptance_boundary_shared() -> None:
    units = _pair_units(
        "unit-repo",
        "unit-runtime",
        left_overrides={"authority_class": ExternalEffectClass.REPOSITORY_WRITE},
        right_overrides={
            "authority_class": ExternalEffectClass.RUNTIME_MUTATION,
            "depends_on": ["unit-repo"],
        },
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=units,
        )
    )
    assert len(plan.work_items) == 2
    assert len({item.id for item in plan.work_items}) == 2


def test_cross_group_dependency_produces_valid_two_item_plan() -> None:
    units = _pair_units(
        "unit-repo",
        "unit-runtime",
        left_overrides={"authority_class": ExternalEffectClass.REPOSITORY_WRITE},
        right_overrides={
            "authority_class": ExternalEffectClass.RUNTIME_MUTATION,
            "depends_on": ["unit-repo"],
        },
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=units,
        )
    )
    assert len(plan.work_items) == 2
    by_authority = {item.authority_class: item for item in plan.work_items}
    runtime_item = by_authority[ExternalEffectClass.RUNTIME_MUTATION]
    repo_item = by_authority[ExternalEffectClass.REPOSITORY_WRITE]
    assert runtime_item.dependencies[0].target_id == repo_item.id


def test_cross_outcome_units_do_not_merge_or_empty_packages() -> None:
    units = _pair_units(
        "unit-auth",
        "unit-billing",
        left_overrides={"outcome_id": "out-one", "scope": ["auth"]},
        right_overrides={"outcome_id": "out-two", "scope": ["billing"]},
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome("out-one"), _outcome("out-two", "Billing")],
            capability_units=units,
        )
    )
    assert len(plan.work_items) == 2
    packages = {package.outcome_id: package.work_item_ids for package in plan.packages}
    assert packages["out-one"]
    assert packages["out-two"]


def test_discovery_and_mutation_split_into_separate_items() -> None:
    units = _pair_units(
        "unit-discover",
        "unit-mutate",
        left_overrides={"discovery_only": True, "scope": ["read prod"]},
        right_overrides={"mutates_external": True, "scope": ["drop tables"]},
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=units,
        )
    )
    assert len(plan.work_items) == 2
    flags = {issue.flag.value for issue in plan.quality_issues}
    assert "mixed-discovery-and-mutation" in flags
    _assert_every_work_item_in_exactly_one_package(plan)


def test_multiple_execution_runs_attach_without_mutating_work_item() -> None:
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=_single_causal_capability_units(),
        )
    )
    contract = plan.work_items[0]
    original_dump = dump_json(contract)

    context = WorkItemExecutionContext(contract=contract)
    context = attach_execution_run(context, run_id="run-001")
    context = attach_execution_run(context, run_id="run-002")

    assert dump_json(context.contract) == original_dump
    assert len(context.runs) == 2
    assert [run.id for run in context.runs] == ["run-001", "run-002"]


def test_work_lifecycle_execution_and_evidence_states_are_distinct() -> None:
    lifecycle_values = {member.value for member in WorkLifecycleState}
    execution_values = {member.value for member in ExecutionState}
    evidence_values = {member.value for member in EvidenceState}
    assert lifecycle_values.isdisjoint(execution_values)
    assert lifecycle_values.isdisjoint(evidence_values)
    assert execution_values.isdisjoint(evidence_values)

    lifecycle = WorkLifecycleSnapshot(
        work_item_id="wi-sample",
        lifecycle_state=WorkLifecycleState.IN_REVIEW,
    )
    execution = ExecutionRunRef(
        id="run-retry",
        work_item_id="wi-sample",
        execution_state=ExecutionState.RETRYING,
    )
    evidence = EvidenceStateSnapshot(
        work_item_id="wi-sample",
        run_id="run-retry",
        evidence_states=[EvidenceState.IMPLEMENTED, EvidenceState.NOT_REQUIRED],
    )
    assert lifecycle.lifecycle_state == WorkLifecycleState.IN_REVIEW
    assert execution.execution_state == ExecutionState.RETRYING
    assert EvidenceState.IMPLEMENTED in evidence.evidence_states


def test_adoption_gaps_produce_work_items() -> None:
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            adoption_gaps=[
                AdoptionGap(
                    id="gap-ci",
                    target="continuous integration pipeline",
                    action=AdoptionAction.HARDEN,
                    rationale="CI lacks deterministic validation gate",
                    blocker=True,
                )
            ],
        )
    )
    assert len(plan.work_items) == 1
    item = plan.work_items[0]
    assert item.work_class == WorkClass.ADOPTION
    assert "continuous integration pipeline" in item.scope
    assert item.escalation_conditions


def test_validate_dependency_graph_rejects_cycle() -> None:
    items = [
        WorkItemContract(
            schema_version="0.1",
            id="wi-a",
            title="A",
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            dependencies=[{"relation": "requires", "target_id": "wi-b"}],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        ),
        WorkItemContract(
            schema_version="0.1",
            id="wi-b",
            title="B",
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            dependencies=[{"relation": "requires", "target_id": "wi-a"}],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        ),
    ]
    with pytest.raises(DependencyGraphError) as exc:
        validate_dependency_graph(items)
    assert "circular dependency" in str(exc.value).lower()
    assert exc.value.cycle_path
    assert "wi-a" in exc.value.cycle_path
    assert "wi-b" in exc.value.cycle_path


def test_validate_dependency_graph_rejects_dangling_reference() -> None:
    items = [
        WorkItemContract(
            schema_version="0.1",
            id="wi-alone",
            title="Alone",
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            dependencies=[{"relation": "requires", "target_id": "wi-missing"}],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        )
    ]
    with pytest.raises(DependencyGraphError) as exc:
        validate_dependency_graph(items)
    assert "dangling" in str(exc.value).lower()
    assert "wi-missing" in exc.value.node_ids


def test_validate_dependency_graph_blocks_relation_is_not_false_cycle() -> None:
    items = [
        WorkItemContract(
            schema_version="0.1",
            id="wi-a",
            title="A",
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            dependencies=[{"relation": "requires", "target_id": "wi-b"}],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        ),
        WorkItemContract(
            schema_version="0.1",
            id="wi-b",
            title="B",
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            dependencies=[{"relation": "blocks", "target_id": "wi-a"}],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        ),
    ]
    validate_dependency_graph(items)


def test_decompose_work_is_deterministic() -> None:
    units = _pair_units(
        "unit-repo",
        "unit-runtime",
        left_overrides={"authority_class": ExternalEffectClass.REPOSITORY_WRITE},
        right_overrides={"authority_class": ExternalEffectClass.RUNTIME_MUTATION},
    )
    input_data = DecompositionInput(
        objective=_objective(),
        outcomes=[_outcome()],
        capability_units=units,
    )
    first = dump_json(decompose_work(input_data))
    second = dump_json(decompose_work(input_data))
    assert first == second


def test_decompose_work_input_permutations_are_identical() -> None:
    units = _pair_units(
        "unit-repo",
        "unit-runtime",
        left_overrides={"authority_class": ExternalEffectClass.REPOSITORY_WRITE},
        right_overrides={"authority_class": ExternalEffectClass.RUNTIME_MUTATION},
    )
    baseline = dump_json(
        decompose_work(
            DecompositionInput(
                objective=_objective(),
                outcomes=[_outcome()],
                capability_units=units,
            )
        )
    )
    for ordering in itertools.permutations(units):
        plan = decompose_work(
            DecompositionInput(
                objective=_objective(),
                outcomes=[_outcome()],
                capability_units=list(ordering),
            )
        )
        assert dump_json(plan) == baseline


def test_decompose_work_byte_identical_across_env() -> None:
    script = f"""
import agent_foundry
from pathlib import Path

repo_root = Path({str(REPO_ROOT)!r})
assert str(repo_root) in str(Path(agent_foundry.__file__).resolve())

from agent_foundry.models.common import ConsequenceClass, ExternalEffectClass, WorkClass
from agent_foundry.models.io import dump_json
from agent_foundry.models.work import CapabilityUnit, DecompositionInput, OutcomeCapability, WorkObjective
from agent_foundry.work import decompose_work

objective = WorkObjective(id="obj-x", title="t", description="d")
outcome = OutcomeCapability(id="out-x", objective_id="obj-x", title="o", description="od")
units = [
    CapabilityUnit(
        id="u1",
        outcome_id="out-x",
        title="impl",
        description="d",
        work_class=WorkClass.CAPABILITY,
        acceptance_boundary_id="b1",
        authority_class=ExternalEffectClass.REPOSITORY_WRITE,
        consequence_class=ConsequenceClass.MEDIUM,
        rollback_boundary_id="r1",
        write_scope_id="s1",
    ),
    CapabilityUnit(
        id="u2",
        outcome_id="out-x",
        title="apply",
        description="d",
        work_class=WorkClass.CAPABILITY,
        acceptance_boundary_id="b2",
        authority_class=ExternalEffectClass.RUNTIME_MUTATION,
        consequence_class=ConsequenceClass.HIGH,
        rollback_boundary_id="r2",
        write_scope_id="s2",
        depends_on=["u1"],
    ),
]
print(dump_json(decompose_work(DecompositionInput(objective=objective, outcomes=[outcome], capability_units=units))))
"""
    outputs: list[str] = []
    for hash_seed in ("0", "1", "42"):
        for cwd in (REPO_ROOT, REPO_ROOT / "tests"):
            env = _subprocess_env()
            env["PYTHONHASHSEED"] = hash_seed
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            outputs.append(result.stdout)
    assert len(set(outputs)) == 1


# --- SUE-336: failures on the failing path stay legible ---------------------

CYCLE_GRAPH_SIZE = 3000


def _chain_with_cycle(size: int) -> list[WorkItemContract]:
    """`wi-0000 -> wi-0001 -> ... -> wi-(size-1) -> wi-0000`, one long cycle."""
    ids = [f"wi-{index:04d}" for index in range(size)]
    return [
        WorkItemContract(
            schema_version="0.1",
            id=item_id,
            title=item_id,
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            dependencies=[
                {"relation": "requires", "target_id": ids[(index + 1) % size]}
            ],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        )
        for index, item_id in enumerate(ids)
    ]


def test_large_cycle_reports_circular_dependency_not_recursion_error() -> None:
    """Path reconstruction must survive graphs the cycle detector already handles."""
    items = _chain_with_cycle(CYCLE_GRAPH_SIZE)

    with pytest.raises(DependencyGraphError) as exc:
        validate_dependency_graph(items)

    assert "circular dependency" in str(exc.value).lower()
    path = exc.value.cycle_path
    assert path, "a detected cycle must be named"
    assert path[0] == path[-1], f"cycle path must close: {path[:3]}...{path[-3:]}"
    assert len(path) == CYCLE_GRAPH_SIZE + 1
    assert len(set(path)) == CYCLE_GRAPH_SIZE
    for current, following in zip(path, path[1:]):
        assert following in {
            dep.target_id for item in items if item.id == current for dep in item.dependencies
        }, f"{current} -> {following} is not a real edge"


def test_large_acyclic_graph_validates_without_recursion_error() -> None:
    items = _chain_with_cycle(CYCLE_GRAPH_SIZE)
    acyclic = [item for item in items if item.id != f"wi-{CYCLE_GRAPH_SIZE - 1:04d}"] + [
        WorkItemContract(
            schema_version="0.1",
            id=f"wi-{CYCLE_GRAPH_SIZE - 1:04d}",
            title="tail",
            work_class=WorkClass.CAPABILITY,
            objective="obj",
            current_facts=[],
            scope=[],
            out_of_scope=[],
            acceptance_criteria=["done"],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        )
    ]
    validate_dependency_graph(acyclic)


def test_cycle_path_is_unchanged_for_the_small_case() -> None:
    """The iterative walk reports the same path the recursive one did."""
    items = _chain_with_cycle(2)
    with pytest.raises(DependencyGraphError) as exc:
        validate_dependency_graph(items)
    assert exc.value.cycle_path == ["wi-0000", "wi-0001", "wi-0000"]


# --- SUE-336: the Work Item contract is genuinely immutable ----------------


def _contract() -> WorkItemContract:
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=_single_causal_capability_units(),
        )
    )
    return plan.work_items[0]


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "out_of_scope",
        "acceptance_criteria",
        "required_evidence",
        "stop_conditions",
        "escalation_conditions",
        "current_facts",
        "implementation_references",
        "dependencies",
    ],
)
def test_work_item_contract_sequence_fields_reject_in_place_edits(field: str) -> None:
    """`frozen=True` blocks rebinding; a list field would still accept .append()."""
    contract = _contract()
    before = dump_json(contract)
    with pytest.raises(AttributeError):
        getattr(contract, field).append("SMUGGLED")
    assert dump_json(contract) == before


def test_attached_contract_cannot_be_widened_through_the_execution_context() -> None:
    """Scope bounds compiled write authority; in-place widening must be impossible."""
    context = WorkItemExecutionContext(contract=_contract())
    before = dump_json(context.contract)
    with pytest.raises(AttributeError):
        context.contract.scope.append("SMUGGLED")
    with pytest.raises(AttributeError):
        context.runs.append(ExecutionRunRef(id="run-x", work_item_id=context.contract.id))
    assert dump_json(context.contract) == before
    assert "SMUGGLED" not in dump_json(context.contract).decode("utf-8")


# --- SUE-336: execution runs are a truthful attempt history ----------------


def test_attach_execution_run_rejects_a_duplicate_run_id() -> None:
    context = WorkItemExecutionContext(contract=_contract())
    context = attach_execution_run(context, run_id="run-000")
    with pytest.raises(WorkDecompositionError, match="already attached"):
        attach_execution_run(context, run_id="run-000")
    assert len(context.runs) == 1


def test_attach_execution_run_keeps_attach_order_not_lexical_order() -> None:
    context = WorkItemExecutionContext(contract=_contract())
    for run_id in ("run-9", "run-049", "run-1000"):
        context = attach_execution_run(context, run_id=run_id)
    assert [run.id for run in context.runs] == ["run-9", "run-049", "run-1000"]


def test_attaching_fifty_distinct_runs_yields_fifty_runs() -> None:
    context = WorkItemExecutionContext(contract=_contract())
    for index in range(50):
        context = attach_execution_run(context, run_id=f"run-{index:03d}")
    assert len(context.runs) == 50
    assert len({run.id for run in context.runs}) == 50


# --- SUE-336: the external validation requirement carries information ------


def test_read_only_discovery_item_declares_no_external_validation() -> None:
    units = [
        _make_unit(
            "unit-discover",
            "Survey the current state",
            authority_class=ExternalEffectClass.READ_ONLY,
            discovery_only=True,
        )
    ]
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=units,
        )
    )
    item = plan.work_items[0]
    assert item.authority_class == ExternalEffectClass.READ_ONLY
    assert item.runtime_external_validation_requirement is None


def test_runtime_mutating_item_declares_external_read_back() -> None:
    units = [
        _make_unit(
            "unit-apply",
            "Apply the runtime change",
            authority_class=ExternalEffectClass.RUNTIME_MUTATION,
            mutates_external=True,
            required_evidence=["runtime read-back"],
        )
    ]
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=units,
        )
    )
    requirement = plan.work_items[0].runtime_external_validation_requirement
    assert requirement is not None
    assert "runtime" in requirement
    assert "runtime read-back" in requirement


def test_external_validation_requirement_differs_by_authority_class() -> None:
    """A constant would read identically for every item; a derived one must not."""
    outcomes = [_outcome("out-shared", "Shared outcome")]
    units = _pair_units(
        "unit-read",
        "unit-write",
        left_overrides={
            "authority_class": ExternalEffectClass.READ_ONLY,
            "outcome_id": "out-shared",
        },
        right_overrides={
            "authority_class": ExternalEffectClass.REPOSITORY_WRITE,
            "outcome_id": "out-shared",
        },
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(), outcomes=outcomes, capability_units=units
        )
    )
    requirements = {
        item.authority_class: item.runtime_external_validation_requirement
        for item in plan.work_items
    }
    assert requirements[ExternalEffectClass.READ_ONLY] is None
    assert requirements[ExternalEffectClass.REPOSITORY_WRITE] is not None
    assert len(set(requirements.values())) == 2


# --- SUE-336: quality diagnostics say what happened and are self-contained --


def test_cross_outcome_collision_flag_names_units_not_outcomes() -> None:
    """The engine splits these units and produces no mega item; the flag says so."""
    units = _pair_units(
        "unit-auth",
        "unit-billing",
        left_overrides={"outcome_id": "out-one"},
        right_overrides={"outcome_id": "out-two"},
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome("out-one"), _outcome("out-two", "Billing")],
            capability_units=units,
        )
    )
    flags = {issue.flag.value for issue in plan.quality_issues}
    assert "cross-outcome-identity-collision" in flags
    assert "mega-item" not in flags

    issue = next(
        issue
        for issue in plan.quality_issues
        if issue.flag is DecompositionQualityFlag.CROSS_OUTCOME_IDENTITY_COLLISION
    )
    unit_ids = {unit.id for unit in units}
    assert set(issue.related_ids) == unit_ids
    assert issue.work_item_id is None
    # No mega item is produced: the units land in two separate work items.
    assert len(plan.work_items) == 2


def test_mixed_work_class_flag_relates_unit_ids_not_class_names() -> None:
    shared = _base_unit_fields()
    shared.pop("work_class")
    units = [
        CapabilityUnit(
            id="unit-amend",
            title="Amend the contract",
            description="Amend the contract",
            work_class=WorkClass.CONTRACT_AMENDMENT,
            **shared,
        ),
        CapabilityUnit(
            id="unit-capability",
            title="Wire authoritative consumer",
            description="Wire authoritative consumer",
            work_class=WorkClass.CAPABILITY,
            **shared,
        ),
    ]
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(), outcomes=[_outcome()], capability_units=units
        )
    )
    issue = next(
        issue
        for issue in plan.quality_issues
        if issue.flag is DecompositionQualityFlag.MIXED_WORK_CLASS
    )
    assert set(issue.related_ids) == {"unit-amend", "unit-capability"}
    assert issue.work_item_id == plan.work_items[0].id
    # The class names stay in the message, where they explain the choice.
    assert WorkClass.CONTRACT_AMENDMENT.value in issue.message
    assert WorkClass.CAPABILITY.value in issue.message


def test_every_quality_flag_relates_ids_that_resolve_within_the_plan() -> None:
    """A diagnostic that names nothing addressable cannot be acted on."""
    units = _pair_units(
        "unit-auth",
        "unit-billing",
        left_overrides={"outcome_id": "out-one"},
        right_overrides={"outcome_id": "out-two"},
    )
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome("out-one"), _outcome("out-two", "Billing")],
            capability_units=units,
        )
    )
    addressable = (
        {unit.id for unit in units}
        | {item.id for item in plan.work_items}
        | {
            criterion
            for item in plan.work_items
            for criterion in item.acceptance_criteria
        }
    )
    for issue in plan.quality_issues:
        unresolved = sorted(set(issue.related_ids) - addressable)
        assert unresolved == [], f"{issue.flag.value} relates unresolvable ids: {unresolved}"


# --- SUE-336: the orphan-outcome check has exactly one site ----------------


def test_undeclared_outcome_check_is_not_duplicated_in_the_source() -> None:
    source = (REPO_ROOT / "src" / "agent_foundry" / "work" / "decompose.py").read_text(
        encoding="utf-8"
    )
    assert source.count("reference undeclared outcomes") == 1, (
        "the undeclared-outcome check had an identical unreachable copy inside "
        "_packages_for_outcomes; one check site, one message"
    )
