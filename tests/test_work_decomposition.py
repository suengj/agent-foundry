"""Tests for tracker-neutral work decomposition and state separation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

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
    EvidenceStateSnapshot,
    ExecutionRunRef,
    WorkItemContract,
    WorkItemExecutionContext,
    WorkLifecycleSnapshot,
    WorkObjective,
    OutcomeCapability,
)
from agent_foundry.models import DependencyGraphError
from agent_foundry.work import attach_execution_run, decompose_work, validate_dependency_graph

REPO_ROOT = Path(__file__).resolve().parents[1]


def _objective() -> WorkObjective:
    return WorkObjective(
        id="obj-platform",
        title="Platform contracts",
        description="Deliver typed provider-neutral contracts",
    )


def _outcome() -> OutcomeCapability:
    return OutcomeCapability(
        id="out-contracts",
        objective_id="obj-platform",
        title="Contract layer",
        description="Versioned data contracts for the core package",
    )


def _single_causal_capability_units() -> list[CapabilityUnit]:
    """Schema, tests, and review share one acceptance boundary."""
    shared = {
        "outcome_id": "out-contracts",
        "work_class": WorkClass.CAPABILITY,
        "acceptance_boundary_id": "boundary-contract-layer",
        "authority_class": ExternalEffectClass.REPOSITORY_WRITE,
        "consequence_class": ConsequenceClass.MEDIUM,
        "rollback_boundary_id": "rollback-contract-layer",
        "write_scope_id": "scope-contract-models",
        "acceptance_criteria": [
            "contract defined and consumed by authoritative path",
            "regression evidence passes",
            "required review complete",
        ],
        "required_evidence": ["pytest green", "review sign-off"],
        "stop_conditions": ["semantics cannot be expressed without inventing behaviour"],
    }
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


def _split_capability_units() -> list[CapabilityUnit]:
    """Repository write vs runtime mutation differ in authority and rollback."""
    base = {
        "outcome_id": "out-contracts",
        "work_class": WorkClass.CAPABILITY,
        "consequence_class": ConsequenceClass.HIGH,
        "acceptance_criteria": ["capability delivered with evidence"],
        "required_evidence": ["validation output"],
        "stop_conditions": ["escalate if authority unclear"],
    }
    return [
        CapabilityUnit(
            id="unit-impl",
            title="Implement service contract",
            description="Source implementation in repository",
            acceptance_boundary_id="boundary-impl",
            authority_class=ExternalEffectClass.REPOSITORY_WRITE,
            rollback_boundary_id="rollback-git",
            write_scope_id="scope-repo",
            scope=["service module"],
            **base,
        ),
        CapabilityUnit(
            id="unit-apply",
            title="Apply runtime configuration",
            description="Mutate shared runtime with approved apply",
            acceptance_boundary_id="boundary-apply",
            authority_class=ExternalEffectClass.RUNTIME_MUTATION,
            rollback_boundary_id="rollback-runtime",
            write_scope_id="scope-runtime",
            scope=["deployment target"],
            depends_on=["unit-impl"],
            **base,
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


def test_splits_when_authority_or_rollback_boundary_differs() -> None:
    """Split when authority and rollback boundaries genuinely differ."""
    plan = decompose_work(
        DecompositionInput(
            objective=_objective(),
            outcomes=[_outcome()],
            capability_units=_split_capability_units(),
        )
    )
    assert len(plan.work_items) == 2
    authorities = {item.authority_class for item in plan.work_items}
    rollbacks = {item.rollback_boundary_id for item in plan.work_items}
    assert ExternalEffectClass.REPOSITORY_WRITE in authorities
    assert ExternalEffectClass.RUNTIME_MUTATION in authorities
    assert len(rollbacks) == 2


def test_multiple_execution_runs_attach_without_mutating_work_item() -> None:
    """Work Item contract stays immutable while runs accumulate."""
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
    assert all(run.work_item_id == contract.id for run in context.runs)


def test_work_lifecycle_execution_and_evidence_states_are_distinct() -> None:
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
    assert lifecycle.lifecycle_state != execution.execution_state.value  # type: ignore[comparison-overlap]


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
                )
            ],
        )
    )
    assert len(plan.work_items) == 1
    item = plan.work_items[0]
    assert item.work_class == WorkClass.ADOPTION
    assert item.scope
    assert item.out_of_scope is not None
    assert item.dependencies is not None


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
            dependencies=[
                {
                    "relation": "requires",
                    "target_id": "wi-b",
                }
            ],
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
            dependencies=[
                {
                    "relation": "requires",
                    "target_id": "wi-a",
                }
            ],
            authority_class=ExternalEffectClass.READ_ONLY,
            consequence_class=ConsequenceClass.LOW,
            required_evidence=["evidence"],
            stop_conditions=["stop"],
        ),
    ]
    with pytest.raises(DependencyGraphError) as exc:
        validate_dependency_graph(items)
    assert "circular dependency" in str(exc.value).lower()
    assert "wi-a" in exc.value.node_ids
    assert "wi-b" in exc.value.node_ids


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
            dependencies=[
                {
                    "relation": "requires",
                    "target_id": "wi-missing",
                }
            ],
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


def test_decompose_work_is_deterministic() -> None:
    input_data = DecompositionInput(
        objective=_objective(),
        outcomes=[_outcome()],
        capability_units=_split_capability_units(),
    )
    first = dump_json(decompose_work(input_data))
    second = dump_json(decompose_work(input_data))
    assert first == second


def test_decompose_work_byte_identical_across_env() -> None:
    script = """
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
    for hash_seed in ("0", "42"):
        for cwd in (REPO_ROOT, REPO_ROOT / "tests"):
            env = {**os.environ, "PYTHONHASHSEED": hash_seed}
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
