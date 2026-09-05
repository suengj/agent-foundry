"""Deterministic round-trip tests for valid contract fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_foundry.models import (
    AdoptionPlan,
    CapabilitySpec,
    ExecutionBundle,
    ExecutionReceipt,
    EvidenceBundle,
    IntegrationSpec,
    ProjectManifest,
    ProjectProfile,
    RoleContract,
    SkillSpec,
    TaskToolkit,
    ToolkitLock,
    WorkItemContract,
    WorkflowSpec,
    dump_json,
    dump_json_raw,
    dump_yaml,
    dump_yaml_raw,
    load_json,
    load_yaml,
    parse_json,
    parse_yaml,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "valid"

FIXTURE_MODELS: list[tuple[str, type]] = [
    ("project_manifest.yaml", ProjectManifest),
    ("project_manifest.json", ProjectManifest),
    ("adoption_plan.yaml", AdoptionPlan),
    ("project_profile.yaml", ProjectProfile),
    ("work_item_contract.yaml", WorkItemContract),
    ("toolkit_lock.yaml", ToolkitLock),
    ("task_toolkit.yaml", TaskToolkit),
    ("integration_spec.yaml", IntegrationSpec),
    ("execution_bundle.yaml", ExecutionBundle),
    ("evidence_bundle.yaml", EvidenceBundle),
    ("execution_receipt.yaml", ExecutionReceipt),
    ("execution_receipt_not_required.yaml", ExecutionReceipt),
    ("capability_spec.yaml", CapabilitySpec),
    ("skill_spec.yaml", SkillSpec),
    ("workflow_spec.yaml", WorkflowSpec),
    ("role_contract.yaml", RoleContract),
]


@pytest.mark.parametrize(("fixture_name", "model_type"), FIXTURE_MODELS)
def test_yaml_roundtrip_model(fixture_name: str, model_type: type) -> None:
    source = (FIXTURES / fixture_name).read_bytes()
    obj = load_yaml(model_type, source)
    dumped = dump_yaml(obj)
    round = load_yaml(model_type, dumped)
    assert round == obj
    assert dumped == dump_yaml(round)


@pytest.mark.parametrize(("fixture_name", "model_type"), FIXTURE_MODELS)
def test_json_roundtrip_model(fixture_name: str, model_type: type) -> None:
    source_yaml = (FIXTURES / fixture_name).read_bytes()
    obj = load_yaml(model_type, source_yaml)
    dumped = dump_json(obj)
    round = load_json(model_type, dumped)
    assert round == obj
    assert dumped == dump_json(round)


@pytest.mark.parametrize(("fixture_name", "model_type"), FIXTURE_MODELS)
def test_yaml_byte_stable_redump(fixture_name: str, model_type: type) -> None:
    source = (FIXTURES / fixture_name).read_bytes()
    obj = load_yaml(model_type, source)
    first_dump = dump_yaml(obj)
    reparsed = parse_yaml(first_dump)
    second_dump = dump_yaml_raw(reparsed)
    assert first_dump == second_dump


@pytest.mark.parametrize(("fixture_name", "model_type"), FIXTURE_MODELS)
def test_json_byte_stable_redump(fixture_name: str, model_type: type) -> None:
    source = (FIXTURES / fixture_name).read_bytes()
    if fixture_name.endswith(".json"):
        obj = load_json(model_type, source)
    else:
        obj = load_yaml(model_type, source)
    first_dump = dump_json(obj)
    reparsed = parse_json(first_dump)
    second_dump = dump_json_raw(reparsed)
    assert first_dump == second_dump


@pytest.mark.parametrize(("fixture_name", "model_type"), FIXTURE_MODELS)
def test_json_fixture_load_json(fixture_name: str, model_type: type) -> None:
    if not fixture_name.endswith(".json"):
        return
    source = (FIXTURES / fixture_name).read_bytes()
    obj = load_json(model_type, source)
    assert obj.schema_version == "0.1"

