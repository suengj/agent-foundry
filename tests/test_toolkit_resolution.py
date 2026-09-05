"""Toolkit registry and deterministic resolution tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_foundry.models import (
    AssuranceMode,
    AuthorityRequirement,
    ConsequenceClass,
    ExternalEffectClass,
    IntegrationAuthMethod,
    IntegrationHealthState,
    IntegrationKind,
    IntegrationTransport,
    PolicyRule,
    PolicyPredicate,
    PolicyViolationError,
    ProjectAccess,
    ProjectAssurance,
    ProjectExecution,
    ProjectImpact,
    ProjectInfo,
    ProjectManifest,
    ProjectState,
    ResolutionAction,
    ResolutionSource,
    SchemaCompatibilityError,
    SecretRef,
    ToolkitResolutionError,
    ToolkitLock,
    WorkClass,
    WorkItemContract,
    dump_json,
    dump_yaml,
    load_yaml,
)
from agent_foundry.models.io import dump_yaml_raw
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
from agent_foundry.models.integrations import (
    IntegrationAuth,
    IntegrationHealth,
    IntegrationHealthRequirement,
    IntegrationPermissions,
    IntegrationSpec,
)
from agent_foundry.models.policy import BudgetProfile, PermissionProfile
from agent_foundry.models.project import WorkModes
from agent_foundry.models.registry import CapabilityRegistry, CapabilitySpec
from agent_foundry.toolkit import (
    check_integrations,
    default_registry,
    resolve_task_toolkit_for_work_item,
    resolve_toolkit,
)
from agent_foundry.toolkit.builtin_registry import (
    build_default_registry,
    build_default_registry_permission_profiles,
)
from agent_foundry.toolkit.ceiling import (
    EFFECT_RANK,
    effective_permission_ceiling,
    validate_task_toolkit_against_ceiling,
    validate_toolkit_lock_against_ceiling,
)
from agent_foundry.toolkit.resolve import (
    _decision,
    _record_exclude,
    _record_include,
    _retract_include,
    _retract_exclude,
    resolve_project_toolkit,
    resolve_task_toolkit,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "valid"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _subprocess_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}


def _sample_manifest(**overrides: object) -> ProjectManifest:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "project": {
            "name": "sample-service",
            "intake_mode": "brownfield",
            "work_modes": {"primary": "build"},
            "primary_artifact": "code",
        },
        "state": {"persistence": "persistent-shared-external", "temporal_mode": "long-running"},
        "impact": {
            "external_effect": "runtime-mutation",
            "reversibility": "rollback-required",
            "consequence": "high",
        },
        "execution": {
            "autonomy": "bounded-external-write",
            "ambiguity": "bounded-judgment",
            "concurrency": "single-writer",
        },
        "assurance": {
            "required": [
                "deterministic-tests",
                "independent-review",
                "runtime-readback",
            ]
        },
        "access": {"sensitivity": "internal"},
    }
    base.update(overrides)
    return ProjectManifest.model_validate(base)


def _sample_work_item(**overrides: object) -> WorkItemContract:
    base = {
        "schema_version": FOUNDRY_SCHEMA_VERSION,
        "id": "WI-001",
        "title": "Implement capability",
        "work_class": "capability",
        "objective": "Deliver bounded change",
        "current_facts": ["bootstrap exists"],
        "scope": ["toolkit resolver"],
        "out_of_scope": ["execution"],
        "acceptance_criteria": ["pytest green"],
        "dependencies": [],
        "authority_class": "repository-write",
        "consequence_class": "medium",
        "required_evidence": ["pytest"],
        "stop_conditions": ["cannot express semantics"],
    }
    base.update(overrides)
    return WorkItemContract.model_validate(base)


def _integration_work_tracker() -> IntegrationSpec:
    return IntegrationSpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="work-tracker",
        kind=IntegrationKind.INTEGRATION,
        transport=IntegrationTransport.MCP,
        version="1",
        capabilities=["work.read", "work.write"],
        permissions=IntegrationPermissions(write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY),
        auth=IntegrationAuth(
            method=IntegrationAuthMethod.OAUTH,
            credential_ref=SecretRef.model_validate("managed:work-tracker"),
        ),
        health=IntegrationHealthRequirement(required=IntegrationHealthState.AUTHENTICATED),
    )


def _integration_repository() -> IntegrationSpec:
    return IntegrationSpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="repository",
        kind=IntegrationKind.INTEGRATION,
        transport=IntegrationTransport.LOCAL_SERVICE,
        version="1",
        capabilities=["repository.read", "repository.write"],
        permissions=IntegrationPermissions(write_requires=AuthorityRequirement.BOUNDED_POLICY),
        health=IntegrationHealthRequirement(required=IntegrationHealthState.CONFIGURED),
    )


def test_default_registry_is_small_and_inspectable() -> None:
    registry = default_registry()
    assert len(registry.roles) == 7
    assert len(registry.skills) == 4
    assert len(registry.workflows) == 4
    assert registry.foundry_compat == ">=0.2,<0.3"


def test_resolve_project_toolkit_from_sample_manifest() -> None:
    manifest = load_yaml(ProjectManifest, (FIXTURES / "project_manifest.yaml").read_bytes())
    resolution, lock = resolve_toolkit(manifest, integrations=[_integration_repository()])
    assert "bounded-change" in lock.skill_ids
    assert "independent-review" in lock.skill_ids
    assert "builder-reviewer" in lock.workflow_ids
    assert "runtime-verifier" in lock.role_ids
    assert "runtime.verify" in lock.capability_ids
    assert lock.integration_ids == ["repository"]
    assert resolution.integration_health
    assert all(item.message for item in resolution.integration_health)


def test_toolkit_lock_reproducibility_same_input_twice() -> None:
    manifest = _sample_manifest()
    _, lock_a = resolve_toolkit(manifest)
    _, lock_b = resolve_toolkit(manifest)
    assert dump_json(lock_a) == dump_json(lock_b)


def test_toolkit_lock_reproducibility_hash_seeds() -> None:
    manifest_path = FIXTURES / "project_manifest.yaml"
    digests: list[str] = []
    script = f"""
from pathlib import Path
from agent_foundry.models import load_yaml, ProjectManifest, dump_json
from agent_foundry.toolkit import resolve_toolkit
manifest = load_yaml(ProjectManifest, Path({str(manifest_path)!r}).read_bytes())
_, lock = resolve_toolkit(manifest)
print(dump_json(lock).decode())
"""
    for seed in ("0", "1", "42"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=REPO_ROOT,
            check=True,
        )
        digests.append(hashlib.sha256(result.stdout.encode()).hexdigest())
    assert digests[0] == digests[1] == digests[2]


def test_toolkit_lock_reproducibility_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _sample_manifest()
    locks: list[bytes] = []
    for cwd in (REPO_ROOT / "tests", REPO_ROOT / "src"):
        monkeypatch.chdir(cwd)
        _, lock = resolve_toolkit(manifest)
        locks.append(dump_json(lock))
    assert locks[0] == locks[1]


def test_toolkit_lock_reproducibility_permuted_registry_lists() -> None:
    manifest = _sample_manifest()
    registry = build_default_registry()
    permuted = CapabilityRegistry(
        schema_version=registry.schema_version,
        foundry_compat=registry.foundry_compat,
        capabilities=list(reversed(registry.capabilities)),
        skills=list(reversed(registry.skills)),
        workflows=list(reversed(registry.workflows)),
        roles=list(reversed(registry.roles)),
        tools=list(reversed(registry.tools)),
        connectors=list(reversed(registry.connectors)),
        validators=list(reversed(registry.validators)),
        permission_profiles=list(reversed(registry.permission_profiles)),
        budget_profiles=list(reversed(registry.budget_profiles)),
        integrations=list(reversed(registry.integrations)),
        policy_rules=list(reversed(registry.policy_rules)),
    )
    _, lock_a = resolve_toolkit(manifest, registry=registry)
    _, lock_b = resolve_toolkit(manifest, registry=permuted)
    assert dump_json(lock_a) == dump_json(lock_b)


def test_missing_mandatory_capability_fails_closed() -> None:
    manifest = _sample_manifest()
    registry = build_default_registry()
    registry = registry.model_copy(
        update={
            "policy_rules": [
                *registry.policy_rules,
                PolicyRule(
                    id="test-require-missing-cap",
                    description="test",
                    when=PolicyPredicate(),
                    require_capabilities=["nonexistent-capability"],
                ),
            ]
        }
    )
    with pytest.raises(ToolkitResolutionError, match="missing mandatory capability"):
        resolve_toolkit(manifest, registry=registry)


def test_forbidden_capability_rejected() -> None:
    manifest = _sample_manifest()
    registry = build_default_registry()
    registry = registry.model_copy(
        update={
            "policy_rules": [
                *registry.policy_rules,
                PolicyRule(
                    id="test-forbid-bounded-change",
                    description="test",
                    when=PolicyPredicate(),
                    require_skills=["bounded-change"],
                    forbid_skills=["bounded-change"],
                ),
            ]
        }
    )
    with pytest.raises(PolicyViolationError, match="forbidden skill"):
        resolve_toolkit(manifest, registry=registry)


def test_permission_escalation_rejected() -> None:
    from agent_foundry.toolkit.resolve import _assert_no_permission_escalation

    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    profile = PermissionProfile(
        id="repository-write-bounded",
        external_effect=ExternalEffectClass.REPOSITORY_WRITE,
        write_requires=AuthorityRequirement.BOUNDED_POLICY,
    )
    with pytest.raises(PolicyViolationError, match="permission escalation"):
        _assert_no_permission_escalation(manifest, profile)


def test_integration_spec_serialization_contains_secret_ref_only() -> None:
    spec = _integration_work_tracker()
    yaml_out = dump_yaml(spec).decode("utf-8")
    json_out = dump_json(spec).decode("utf-8")
    assert "managed" in yaml_out
    assert "work-tracker" in yaml_out
    forbidden = ["sk-live", "ghp_", "api_key:", "password"]
    for token in forbidden:
        assert token not in yaml_out
        assert token not in json_out
    assert "allow_paths" not in yaml_out


def test_task_toolkit_is_strict_subset_with_tighter_controls() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, project_lock = resolve_toolkit(manifest)
    work_item = _sample_work_item(
        authority_class="read-only",
        work_class="discovery",
        consequence_class="medium",
    )
    task = resolve_task_toolkit_for_work_item(work_item, project_lock)

    assert set(task.capability_ids) <= set(project_lock.capability_ids)
    assert set(task.skill_ids) <= set(project_lock.skill_ids)
    assert set(task.role_ids) <= set(project_lock.role_ids)
    assert set(task.integration_ids) <= set(project_lock.integration_ids)

    assert task.permission_profile_ids == ["read-only"]
    assert project_lock.permission_profile_ids == ["repository-write-bounded"]

    excluded_skills = set(project_lock.skill_ids) - set(task.skill_ids)
    assert excluded_skills
    assert "bounded-change" in excluded_skills
    assert "builder" not in task.role_ids
    assert task.role_ids
    assert task.skill_ids
    assert task.capability_ids


def _main_style_repository_write_lock() -> ToolkitLock:
    """Minimal merged-main project lock: builder + bounded-change only."""
    return ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="sample-service",
        capability_ids=["repository.read", "repository.write"],
        skill_ids=["bounded-change"],
        role_ids=["builder"],
        permission_profile_ids=["repository-write-bounded"],
        budget_profile_ids=["default"],
    )


def _assert_satisfiable_task_toolkit_nonempty(
    task: object,
    project_lock: ToolkitLock,
) -> None:
    from agent_foundry.models.toolkit import TaskToolkit

    assert isinstance(task, TaskToolkit)
    assert task.role_ids, "task toolkit role_ids must be non-empty for satisfiable work items"
    assert task.skill_ids, "task toolkit skill_ids must be non-empty for satisfiable work items"
    assert task.capability_ids, "task toolkit capability_ids must be non-empty for satisfiable work items"
    assert set(task.role_ids) <= set(project_lock.role_ids)
    assert set(task.skill_ids) <= set(project_lock.skill_ids)
    assert set(task.capability_ids) <= set(project_lock.capability_ids)


def test_task_toolkit_populates_roles_for_repository_write_capability_work_item() -> None:
    """Regression: merged main left role_ids empty even when skills/capabilities were selected."""
    lock = _main_style_repository_write_lock()
    work_item = _sample_work_item(authority_class="repository-write", work_class="capability")
    task = resolve_task_toolkit_for_work_item(work_item, lock)
    _assert_satisfiable_task_toolkit_nonempty(task, lock)
    assert task.role_ids == ["builder"]
    assert set(task.capability_ids) == {"repository.read", "repository.write"}
    assert task.skill_ids == ["bounded-change"]


def test_task_toolkit_read_only_discovery_nonempty_when_lock_has_inspection() -> None:
    lock = ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="sample-service",
        capability_ids=["inspection.read", "repository.read", "repository.write"],
        skill_ids=["bounded-change", "repository-inspection"],
        role_ids=["builder", "explorer"],
        permission_profile_ids=["repository-write-bounded"],
        budget_profile_ids=["default"],
    )
    work_item = _sample_work_item(authority_class="read-only", work_class="discovery")
    task = resolve_task_toolkit_for_work_item(work_item, lock)
    _assert_satisfiable_task_toolkit_nonempty(task, lock)
    assert "explorer" in task.role_ids
    assert "repository-inspection" in task.skill_ids
    assert "builder" not in task.role_ids
    assert "repository.write" not in task.capability_ids


def test_task_toolkit_unsatisfiable_read_only_discovery_on_builder_only_lock() -> None:
    lock = _main_style_repository_write_lock()
    work_item = _sample_work_item(authority_class="read-only", work_class="discovery")
    task = resolve_task_toolkit_for_work_item(work_item, lock)
    assert not task.role_ids
    assert not task.skill_ids
    assert not task.capability_ids
    unsat = [decision for decision in task.decisions if decision.component_kind == "task-toolkit"]
    assert len(unsat) == 1
    assert "no project-lock skill satisfies" in unsat[0].rationale


def test_task_toolkit_records_missing_role_when_skills_have_no_compatible_role() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, project_lock = resolve_toolkit(manifest)
    work_item = _sample_work_item(authority_class="read-only", consequence_class="medium")
    task = resolve_task_toolkit_for_work_item(work_item, project_lock)
    assert task.skill_ids
    assert not task.role_ids
    unsat = [decision for decision in task.decisions if decision.component_kind == "task-toolkit"]
    assert len(unsat) == 1
    assert "no compatible role" in unsat[0].rationale


def test_task_toolkit_nonempty_mutation_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_foundry.toolkit import api as toolkit_api

    original = toolkit_api.resolve_task_toolkit

    def _empty_toolkit(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        return result.model_copy(update={"role_ids": [], "skill_ids": [], "capability_ids": []})

    monkeypatch.setattr(toolkit_api, "resolve_task_toolkit", _empty_toolkit)
    lock = _main_style_repository_write_lock()
    work_item = _sample_work_item(authority_class="repository-write", work_class="capability")
    task = resolve_task_toolkit_for_work_item(work_item, lock)
    with pytest.raises(AssertionError, match="non-empty"):
        _assert_satisfiable_task_toolkit_nonempty(task, lock)


_SUPPORTIVE_TASK_AUTHORITIES: tuple[ExternalEffectClass, ...] = (
    ExternalEffectClass.READ_ONLY,
    ExternalEffectClass.REPOSITORY_WRITE,
    ExternalEffectClass.PUBLICATION,
)


def _supportive_project_lock() -> ToolkitLock:
    _, lock = resolve_toolkit(_sample_manifest())
    return lock


def _work_item_for_matrix(work_class: WorkClass, authority: ExternalEffectClass) -> WorkItemContract:
    consequence = (
        ConsequenceClass.HIGH
        if work_class in {WorkClass.CONTRACT_AMENDMENT, WorkClass.INCIDENT}
        else ConsequenceClass.MEDIUM
    )
    return _sample_work_item(
        work_class=work_class.value,
        authority_class=authority.value,
        consequence_class=consequence.value,
    )


def _assert_task_toolkit_resolves_or_explains(
    task: object,
    project_lock: ToolkitLock,
) -> None:
    from agent_foundry.models.toolkit import TaskToolkit

    assert isinstance(task, TaskToolkit)
    has_content = bool(task.role_ids and task.skill_ids and task.capability_ids)
    unsatisfied = [
        decision
        for decision in task.decisions
        if decision.component_kind == "task-toolkit"
    ]
    if has_content:
        assert set(task.role_ids) <= set(project_lock.role_ids)
        assert set(task.skill_ids) <= set(project_lock.skill_ids)
        assert set(task.capability_ids) <= set(project_lock.capability_ids)
        return
    assert unsatisfied, "empty task toolkit must record an explaining decision"
    assert all(decision.rationale for decision in unsatisfied)


def test_every_work_class_and_authority_resolves_or_explains_on_supportive_project() -> None:
    """Enum-complete matrix: every WorkClass × authority either resolves or explains emptiness."""
    lock = _supportive_project_lock()
    matrix: list[tuple[WorkClass, ExternalEffectClass, bool]] = []

    for work_class in WorkClass:
        for authority in _SUPPORTIVE_TASK_AUTHORITIES:
            work_item = _work_item_for_matrix(work_class, authority)
            task = resolve_task_toolkit_for_work_item(work_item, lock)
            has_content = bool(task.role_ids and task.skill_ids and task.capability_ids)
            matrix.append((work_class, authority, has_content))
            _assert_task_toolkit_resolves_or_explains(task, lock)

    assert all(
        resolved
        for work_class, authority, resolved in matrix
        if work_class in {WorkClass.INCIDENT, WorkClass.CONTRACT_AMENDMENT}
        and authority != ExternalEffectClass.READ_ONLY
    ), "INCIDENT and CONTRACT_AMENDMENT must resolve when authority permits remediation"


def test_incident_and_contract_amendment_nonempty_on_supportive_project() -> None:
    lock = _supportive_project_lock()
    for work_class in (WorkClass.INCIDENT, WorkClass.CONTRACT_AMENDMENT):
        work_item = _work_item_for_matrix(work_class, ExternalEffectClass.REPOSITORY_WRITE)
        task = resolve_task_toolkit_for_work_item(work_item, lock)
        _assert_satisfiable_task_toolkit_nonempty(task, lock)


def test_work_class_enum_coverage_mutation_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_foundry.toolkit import resolve as resolve_module

    original = resolve_module._work_item_skill_relevance

    def _block_incident(
        work_item: WorkItemContract,
        skill_id: str,
        skills: dict[str, object],
    ) -> bool:
        if work_item.work_class == WorkClass.INCIDENT:
            return False
        return original(work_item, skill_id, skills)

    monkeypatch.setattr(resolve_module, "_work_item_skill_relevance", _block_incident)
    lock = _supportive_project_lock()
    work_item = _work_item_for_matrix(WorkClass.INCIDENT, ExternalEffectClass.REPOSITORY_WRITE)
    task = resolve_task_toolkit_for_work_item(work_item, lock)
    with pytest.raises(AssertionError):
        _assert_satisfiable_task_toolkit_nonempty(task, lock)


def test_include_and_exclude_rationale_present() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    _, lock = resolve_toolkit(manifest)
    includes = [d for d in lock.decisions if d.action == ResolutionAction.INCLUDE]
    excludes = [d for d in lock.decisions if d.action == ResolutionAction.EXCLUDE]
    assert includes
    assert excludes
    assert any(d.project_fact or d.policy_id for d in includes)
    work_item = _sample_work_item(authority_class="read-only")
    task = resolve_task_toolkit_for_work_item(work_item, lock)
    task_excludes = [d for d in task.decisions if d.action == ResolutionAction.EXCLUDE]
    assert task_excludes
    assert all(d.rationale and d.source for d in task_excludes)
    assert "explorer" in lock.role_ids
    discovery_item = _sample_work_item(authority_class="read-only", work_class="discovery")
    discovery_task = resolve_task_toolkit_for_work_item(discovery_item, lock)
    assert discovery_task.role_ids
    assert discovery_task.skill_ids
    assert "explorer" in discovery_task.role_ids


def test_integration_health_distinct_without_credential_leak() -> None:
    integrations = [_integration_work_tracker()]
    health = check_integrations(
        integrations,
        required_ids=["work-tracker"],
        observed_health=[
            IntegrationHealth(
                integration_id="work-tracker",
                state=IntegrationHealthState.AUTHENTICATED,
                message="token valid",
            )
        ],
    )
    dumped = dump_json(health[0])
    text = dumped.decode("utf-8")
    assert IntegrationHealthState.AUTHENTICATED.value in text
    assert "managed:work-tracker" not in text


def test_unsupported_registry_schema_version_rejected() -> None:
    registry = build_default_registry()
    bad_skill = registry.skills[0].model_copy(update={"schema_version": "0.3"})
    bad_registry = registry.model_copy(update={"skills": [bad_skill, *registry.skills[1:]]})
    with pytest.raises(SchemaCompatibilityError):
        resolve_toolkit(_sample_manifest(), registry=bad_registry)


def test_resolve_toolkit_cli_from_manifest(tmp_path: Path) -> None:
    manifest_path = FIXTURES / "project_manifest.yaml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_foundry",
            "resolve-toolkit",
            "--manifest",
            str(manifest_path),
            "--format",
            "json",
        ],
        capture_output=True,
        env=_subprocess_env(),
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0
    assert b"bounded-change" in result.stdout
    child = subprocess.run(
        [sys.executable, "-c", "import agent_foundry; print(agent_foundry.__file__)"] ,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=REPO_ROOT,
        check=True,
    )
    assert str(REPO_ROOT / "src") in child.stdout


def test_integration_check_cli(tmp_path: Path) -> None:
    integrations_file = tmp_path / "integrations.yaml"
    integrations_file.write_text(
        dump_yaml_raw([_integration_work_tracker().model_dump(mode="json")]).decode("utf-8"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_foundry",
            "integration-check",
            str(integrations_file),
            "--required-id",
            "work-tracker",
            "--format",
            "json",
        ],
        capture_output=True,
        env=_subprocess_env(),
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0
    assert b"work-tracker" in result.stdout
    assert b"sk-live" not in result.stdout


def test_task_toolkit_permission_widening_rejected() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, project_lock = resolve_toolkit(manifest)
    assert project_lock.permission_profile_ids == ["repository-write-bounded"]
    work_item = _sample_work_item()
    publication_only = [
        PermissionProfile(
            id="aaa-publication",
            external_effect=ExternalEffectClass.PUBLICATION,
            write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        ),
    ]
    with pytest.raises(ToolkitResolutionError, match="not in supplied permission profiles"):
        resolve_task_toolkit(
            work_item,
            project_lock,
            build_default_registry(),
            permission_profiles=publication_only,
            budget_profiles=[BudgetProfile(id="default")],
        )


def test_task_toolkit_missing_project_permission_profile_raises() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, project_lock = resolve_toolkit(manifest)
    work_item = _sample_work_item()
    with pytest.raises(ToolkitResolutionError, match="not in supplied permission profiles"):
        resolve_task_toolkit(
            work_item,
            project_lock,
            build_default_registry(),
            permission_profiles=[
                PermissionProfile(
                    id="other-profile",
                    external_effect=ExternalEffectClass.READ_ONLY,
                    write_requires=AuthorityRequirement.NONE,
                )
            ],
            budget_profiles=[BudgetProfile(id="default")],
        )


def test_read_only_manifest_excludes_repository_write() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    _, lock = resolve_toolkit(manifest)
    assert "repository.write" not in lock.capability_ids
    assert "bounded-change" not in lock.skill_ids
    exclude_decisions = [d for d in lock.decisions if d.action == ResolutionAction.EXCLUDE]
    assert any(d.component_id == "bounded-change" for d in exclude_decisions)
    assert lock.permission_external_effect == ExternalEffectClass.READ_ONLY


def test_high_consequence_includes_evidence_validator_without_assurance() -> None:
    manifest = _sample_manifest(assurance={"required": []})
    _, lock = resolve_toolkit(manifest)
    assert "evidence-contract" in lock.validator_ids


def test_empty_permission_profiles_not_replaced_with_defaults() -> None:
    manifest = _sample_manifest()
    with pytest.raises(ToolkitResolutionError, match="permission profiles required"):
        resolve_toolkit(manifest, permission_profiles=[])


def test_malformed_foundry_compat_rejected() -> None:
    registry = build_default_registry()
    bad_registry = registry.model_copy(update={"foundry_compat": ">=0.1garbage"})
    with pytest.raises(SchemaCompatibilityError):
        resolve_toolkit(_sample_manifest(), registry=bad_registry)


def test_resolve_toolkit_on_repo_reads_the_declared_manifest() -> None:
    """This repository declares its own characteristics, and the resolver uses them.

    Before AF8 the declaration was read for `intake_mode` and nothing else, so this
    same command returned an empty toolkit and the test asserted that emptiness. What
    it should pin is the opposite property: a declared project resolves components,
    and every decision still names the fact that caused it.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_foundry",
            "resolve-toolkit",
            str(REPO_ROOT),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["project_name"] == "agent-foundry"
    assert payload["capability_ids"], "declared manifest must resolve capabilities"
    assert "builder" in payload["role_ids"]
    assert payload["declared_external_effect"] == "repository-write"
    # No integration is declared, and an undeclared integration is never selected.
    assert payload["integration_ids"] == []
    assert all(
        decision["project_fact"] or decision["policy_id"] or decision["source"] == "registry"
        for decision in payload["decisions"]
    )


def test_resolve_toolkit_on_undeclared_project_explains_every_exclusion(tmp_path: Path) -> None:
    """A project that declares nothing resolves nothing, and says why for each part."""
    project = tmp_path / "undeclared"
    (project / "src").mkdir(parents=True)
    for name in ("a", "b", "c", "d", "e", "f", "g", "h"):
        (project / "src" / f"{name}.py").write_text("x = 1\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname = "undeclared"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, "-m", "agent_foundry", "resolve-toolkit", str(project), "--format", "json"],
        capture_output=True,
        text=True,
        env=_subprocess_env(),
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["capability_ids"] == []
    assert payload["role_ids"] == []
    assert payload["integration_ids"] == []
    assert "unknown" in result.stdout.lower()
    assert "no integration declared" in result.stdout


def test_policy_required_capability_unsatisfiable_raises() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    registry = build_default_registry()
    registry = registry.model_copy(
        update={
            "policy_rules": [
                *registry.policy_rules,
                PolicyRule(
                    id="test-require-repository-write",
                    description="test",
                    when=PolicyPredicate(),
                    require_capabilities=["repository.write"],
                ),
            ]
        }
    )
    with pytest.raises(PolicyViolationError, match="policy-required capabilities unsatisfiable"):
        resolve_toolkit(manifest, registry=registry)


def test_unknown_capability_fail_closed_against_read_only_ceiling() -> None:
    from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION
    from agent_foundry.models.registry import CapabilitySpec

    registry = build_default_registry()
    custom_cap = CapabilitySpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="production.deploy",
        version="1.0.0",
        description="Deploy to production",
        min_external_effect=ExternalEffectClass.PUBLICATION,
    )
    registry = registry.model_copy(
        update={"capabilities": [*registry.capabilities, custom_cap]}
    )
    registry = registry.model_copy(
        update={
            "policy_rules": [
                *registry.policy_rules,
                PolicyRule(
                    id="test-require-production-deploy",
                    description="test",
                    when=PolicyPredicate(),
                    require_capabilities=["production.deploy"],
                ),
            ]
        }
    )
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    with pytest.raises(PolicyViolationError, match="policy-required capabilities unsatisfiable"):
        resolve_toolkit(manifest, registry=registry)


def test_lock_has_no_contradictory_decisions() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    _, lock = resolve_toolkit(manifest)
    by_component: dict[tuple[str, str], set[str]] = {}
    for decision in lock.decisions:
        key = (decision.component_kind, decision.component_id)
        by_component.setdefault(key, set()).add(decision.action.value)
    contradictions = {key: actions for key, actions in by_component.items() if len(actions) > 1}
    assert contradictions == {}


def test_compat_rejects_empty_and_bare_version() -> None:
    registry = build_default_registry()
    for bad_compat in ("", "   ", "0.1"):
        bad_registry = registry.model_copy(update={"foundry_compat": bad_compat})
        with pytest.raises(SchemaCompatibilityError):
            resolve_toolkit(_sample_manifest(), registry=bad_registry)


def test_task_stage_role_exclude_decisions_recorded() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, project_lock = resolve_toolkit(manifest)
    work_item = _sample_work_item(authority_class="read-only", consequence_class="medium")
    task = resolve_task_toolkit_for_work_item(work_item, project_lock)
    role_excludes = [
        d
        for d in task.decisions
        if d.action == ResolutionAction.EXCLUDE and d.component_kind == "role"
    ]
    assert role_excludes
    assert any(d.component_id == "builder" for d in role_excludes)


def _assert_lock_decisions_coherent(lock) -> None:
    in_lock = {
        *(("capability", item) for item in lock.capability_ids),
        *(("skill", item) for item in lock.skill_ids),
        *(("role", item) for item in lock.role_ids),
        *(("workflow", item) for item in lock.workflow_ids),
        *(("integration", item) for item in lock.integration_ids),
        *(("validator", item) for item in lock.validator_ids),
        ("permission-profile", lock.permission_profile_ids[0]),
        ("budget-profile", lock.budget_profile_ids[0]),
    }
    by_component: dict[tuple[str, str], set[str]] = {}
    for decision in lock.decisions:
        key = (decision.component_kind, decision.component_id)
        by_component.setdefault(key, set()).add(decision.action.value)
        if decision.action == ResolutionAction.INCLUDE:
            assert key in in_lock
    contradictions = {
        key: actions for key, actions in by_component.items() if len(actions) > 1
    }
    assert contradictions == {}


def _assert_lock_component_coherence(lock, registry: CapabilityRegistry) -> None:
    index = {
        "capabilities": {item.id: item for item in registry.capabilities},
        "skills": {item.id: item for item in registry.skills},
        "workflows": {item.id: item for item in registry.workflows},
    }
    from agent_foundry.models.registry import SkillSpec, WorkflowSpec

    for workflow_id in lock.workflow_ids:
        workflow = index["workflows"][workflow_id]
        assert isinstance(workflow, WorkflowSpec)
        assert set(workflow.required_roles) <= set(lock.role_ids)
        assert set(workflow.required_skills) <= set(lock.skill_ids)
    for skill_id in lock.skill_ids:
        skill = index["skills"][skill_id]
        assert isinstance(skill, SkillSpec)
        assert set(skill.required_capabilities) <= set(lock.capability_ids)


def test_read_only_high_consequence_resolves_with_readonly_review_workflow() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "high",
        },
        assurance={"required": ["deterministic-tests", "independent-review"]},
    )
    _, lock = resolve_toolkit(manifest)
    assert "independent-review-readonly" in lock.workflow_ids
    assert "builder-reviewer" not in lock.workflow_ids
    assert "independent-review" in lock.skill_ids
    assert lock.declared_external_effect == ExternalEffectClass.READ_ONLY
    assert lock.permission_external_effect == ExternalEffectClass.READ_ONLY


@pytest.mark.parametrize(
    "manifest",
    [
        _sample_manifest(),
        _sample_manifest(
            impact={
                "external_effect": "read-only",
                "reversibility": "trivial",
                "consequence": "low",
            },
            assurance={"required": []},
        ),
        load_yaml(ProjectManifest, (FIXTURES / "project_manifest.yaml").read_bytes()),
    ],
)
def test_lock_coherence_invariant_across_manifests(manifest: ProjectManifest) -> None:
    registry = build_default_registry()
    _, lock = resolve_toolkit(manifest, registry=registry)
    _assert_lock_decisions_coherent(lock)
    _assert_lock_component_coherence(lock, registry)


def test_capability_omitting_min_external_effect_fail_closed_at_read_only_ceiling() -> None:
    registry = build_default_registry()
    custom_cap = CapabilitySpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="production.deploy",
        version="1.0.0",
        description="Deploy to production",
    )
    registry = registry.model_copy(
        update={"capabilities": [*registry.capabilities, custom_cap]}
    )
    registry = registry.model_copy(
        update={
            "policy_rules": [
                *registry.policy_rules,
                PolicyRule(
                    id="test-require-production-deploy",
                    description="test",
                    when=PolicyPredicate(),
                    require_capabilities=["production.deploy"],
                ),
            ]
        }
    )
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    with pytest.raises(PolicyViolationError, match="policy-required capabilities unsatisfiable"):
        resolve_toolkit(manifest, registry=registry)


def test_task_toolkit_respects_pinned_profile_not_declared_effect() -> None:
    builtin_profiles = build_default_registry_permission_profiles()
    looser_profile = PermissionProfile(
        id="aaa-publication",
        external_effect=ExternalEffectClass.PUBLICATION,
        write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        preview_required=True,
        apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
    )
    manifest = _sample_manifest(
        impact={
            "external_effect": "publication",
            "reversibility": "rollback-required",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, lock = resolve_toolkit(manifest, permission_profiles=builtin_profiles)
    assert lock.declared_external_effect == ExternalEffectClass.PUBLICATION
    assert lock.permission_external_effect == ExternalEffectClass.RUNTIME_MUTATION
    assert lock.permission_profile_ids[0] == "runtime-mutation-bounded"

    work_item = _sample_work_item(
        authority_class="publication",
        consequence_class="medium",
    )
    task_profiles = [*builtin_profiles, looser_profile]
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        permission_profiles=task_profiles,
    )
    task_profile = next(profile for profile in task_profiles if profile.id == task.permission_profile_ids[0])
    assert EFFECT_RANK[task_profile.external_effect] <= EFFECT_RANK[ExternalEffectClass.RUNTIME_MUTATION]
    assert task.permission_profile_ids[0] != "aaa-publication"


def test_record_exclude_retracts_prior_include() -> None:
    decisions = [
        _decision(
            ResolutionAction.INCLUDE,
            "skill",
            "bounded-change",
            "policy requires skill",
            ResolutionSource.POLICY,
        ),
    ]
    _record_exclude(
        decisions,
        "skill",
        "bounded-change",
        "exceeds ceiling",
        ResolutionSource.PROJECT_FACT,
    )
    assert not any(
        decision.action == ResolutionAction.INCLUDE and decision.component_id == "bounded-change"
        for decision in decisions
    )
    assert any(
        decision.action == ResolutionAction.EXCLUDE and decision.component_id == "bounded-change"
        for decision in decisions
    )


def test_retract_include_removes_only_matching_component() -> None:
    decisions = [
        _decision(
            ResolutionAction.INCLUDE,
            "capability",
            "repository.write",
            "write",
            ResolutionSource.REGISTRY,
        ),
        _decision(
            ResolutionAction.INCLUDE,
            "capability",
            "repository.read",
            "read",
            ResolutionSource.REGISTRY,
        ),
    ]
    _retract_include(decisions, "capability", "repository.write")
    assert len(decisions) == 1
    assert decisions[0].component_id == "repository.read"


def test_effective_permission_ceiling_is_single_manifest_source() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        }
    )
    assert effective_permission_ceiling(manifest) == ExternalEffectClass.REPOSITORY_WRITE


_ASSURANCE_SWEEP_SETS = [
    [],
    ["independent-review"],
    ["runtime-readback"],
    ["deterministic-tests", "independent-review", "runtime-readback"],
]

_IMPACT_COMBINATIONS = [
    {
        "external_effect": "read-only",
        "reversibility": "trivial",
        "consequence": "low",
    },
    {
        "external_effect": "read-only",
        "reversibility": "trivial",
        "consequence": "high",
    },
    {
        "external_effect": "repository-write",
        "reversibility": "versioned",
        "consequence": "medium",
    },
    {
        "external_effect": "runtime-mutation",
        "reversibility": "rollback-required",
        "consequence": "high",
    },
    {
        "external_effect": "publication",
        "reversibility": "rollback-required",
        "consequence": "critical",
    },
    {
        "external_effect": "shared-service-write",
        "reversibility": "versioned",
        "consequence": "medium",
    },
]


def test_assurance_sweep_fixture_assurance_set_resolves() -> None:
    manifest = load_yaml(ProjectManifest, (FIXTURES / "project_manifest.yaml").read_bytes())
    _, lock = resolve_toolkit(manifest)
    assert lock.workflow_ids
    assert "runtime.verify" in lock.capability_ids


def test_assurance_sweep_refusal_counts() -> None:
    refused_by_assurance: dict[tuple[str, ...], int] = {tuple(s): 0 for s in _ASSURANCE_SWEEP_SETS}
    for assurance in _ASSURANCE_SWEEP_SETS:
        for impact in _IMPACT_COMBINATIONS:
            manifest = _sample_manifest(
                impact=impact,
                assurance={"required": assurance},
            )
            try:
                resolve_toolkit(manifest)
            except (PolicyViolationError, ToolkitResolutionError):
                refused_by_assurance[tuple(assurance)] += 1

    fixture_key = tuple(_ASSURANCE_SWEEP_SETS[-1])
    assert refused_by_assurance[fixture_key] == 0
    assert refused_by_assurance[("independent-review",)] <= 2


def test_unknown_external_effect_critical_requires_independent_review() -> None:
    manifest = _sample_manifest(
        impact={
            "reversibility": "trivial",
            "consequence": "critical",
        },
        assurance={"required": ["independent-review"]},
    )
    assert manifest.impact.external_effect is None
    _, lock = resolve_toolkit(manifest)
    assert "independent-review" in lock.skill_ids
    assert "reviewer" in lock.role_ids
    assert "independent-review-readonly" in lock.workflow_ids
    assert "builder-reviewer" not in lock.workflow_ids


def _decision_contradictions(lock) -> dict[tuple[str, str], set[str]]:
    by_component: dict[tuple[str, str], set[str]] = {}
    for decision in lock.decisions:
        key = (decision.component_kind, decision.component_id)
        by_component.setdefault(key, set()).add(decision.action.value)
    return {key: actions for key, actions in by_component.items() if len(actions) > 1}


def test_unknown_project_shape_no_stale_exclude_after_policy_include() -> None:
    manifest = _sample_manifest(
        project={
            "name": "sample-service",
            "intake_mode": "brownfield",
        },
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "high",
        },
        assurance={"required": ["deterministic-tests", "independent-review"]},
    )
    _, lock = resolve_toolkit(manifest)
    assert "repository.read" in lock.capability_ids
    assert "builder" in lock.role_ids
    assert "bounded-change" in lock.skill_ids
    assert "builder-reviewer" in lock.workflow_ids
    assert _decision_contradictions(lock) == {}


def test_record_include_retracts_prior_exclude() -> None:
    decisions = [
        _decision(
            ResolutionAction.EXCLUDE,
            "skill",
            "bounded-change",
            "project facts unknown",
            ResolutionSource.PROJECT_FACT,
        ),
    ]
    _record_include(
        decisions,
        "skill",
        "bounded-change",
        "required by workflow builder-reviewer",
        ResolutionSource.REGISTRY,
    )
    assert not any(
        decision.action == ResolutionAction.EXCLUDE and decision.component_id == "bounded-change"
        for decision in decisions
    )
    assert any(
        decision.action == ResolutionAction.INCLUDE and decision.component_id == "bounded-change"
        for decision in decisions
    )


def test_retract_exclude_removes_only_matching_component() -> None:
    decisions = [
        _decision(
            ResolutionAction.EXCLUDE,
            "capability",
            "repository.write",
            "excluded",
            ResolutionSource.PROJECT_FACT,
        ),
        _decision(
            ResolutionAction.EXCLUDE,
            "capability",
            "repository.read",
            "excluded",
            ResolutionSource.PROJECT_FACT,
        ),
    ]
    _retract_exclude(decisions, "capability", "repository.write")
    assert len(decisions) == 1
    assert decisions[0].component_id == "repository.read"


_PROJECT_SHAPES = [
    {"primary_artifact": "code", "work_modes": {"primary": "build"}},
    {"primary_artifact": "code", "work_modes": None},
    {"primary_artifact": None, "work_modes": {"primary": "build"}},
    {"primary_artifact": None, "work_modes": None},
]


def _manifest_for_shape(
    shape: dict[str, object | None],
    impact: dict[str, str],
    assurance: list[str],
) -> ProjectManifest:
    project: dict[str, object] = {
        "name": "sample-service",
        "intake_mode": "brownfield",
    }
    if shape.get("primary_artifact") is not None:
        project["primary_artifact"] = shape["primary_artifact"]
    if shape.get("work_modes") is not None:
        project["work_modes"] = shape["work_modes"]
    return _sample_manifest(
        project=project,
        impact=impact,
        assurance={"required": assurance},
    )


def test_assurance_sweep_none_axes_assurance_never_dropped() -> None:
    external_effects: list[str | None] = [
        None,
        "read-only",
        "repository-write",
        "shared-service-write",
        "runtime-mutation",
        "publication",
        "data-mutation",
    ]
    consequences: list[str | None] = [None, "low", "medium", "high", "critical"]
    dropped = 0
    for assurance in _ASSURANCE_SWEEP_SETS:
        if "independent-review" not in assurance:
            continue
        for external_effect in external_effects:
            for consequence in consequences:
                for shape in _PROJECT_SHAPES:
                    impact: dict[str, str] = {"reversibility": "trivial"}
                    if external_effect is not None:
                        impact["external_effect"] = external_effect
                    if consequence is not None:
                        impact["consequence"] = consequence
                    manifest = _manifest_for_shape(shape, impact, assurance)
                    try:
                        _, lock = resolve_toolkit(manifest)
                        if "independent-review" not in lock.skill_ids:
                            dropped += 1
                    except PolicyViolationError:
                        pass
    assert dropped == 0


def test_decision_sweep_zero_contradictions_with_project_shape_axis() -> None:
    contradictions = 0
    for assurance in _ASSURANCE_SWEEP_SETS:
        for impact in _IMPACT_COMBINATIONS:
            for shape in _PROJECT_SHAPES:
                manifest = _manifest_for_shape(shape, impact, assurance)
                try:
                    _, lock = resolve_toolkit(manifest)
                except (PolicyViolationError, ToolkitResolutionError):
                    continue
                contradictions += len(_decision_contradictions(lock))
    assert contradictions == 0


def test_validate_toolkit_lock_against_ceiling_rejects_forged_capability() -> None:
    registry = build_default_registry()
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    _, lock = resolve_toolkit(manifest, registry=registry)
    forged = lock.model_copy(
        update={"capability_ids": sorted([*lock.capability_ids, "repository.write"])}
    )
    with pytest.raises(ToolkitResolutionError, match="repository.write"):
        validate_toolkit_lock_against_ceiling(
            forged,
            registry,
            ExternalEffectClass.READ_ONLY,
        )


def test_validate_task_toolkit_against_ceiling_rejects_looser_profile() -> None:
    builtin_profiles = build_default_registry_permission_profiles()
    looser_profile = PermissionProfile(
        id="aaa-publication",
        external_effect=ExternalEffectClass.PUBLICATION,
        write_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
        preview_required=True,
        apply_requires=AuthorityRequirement.EXPLICIT_AUTHORITY,
    )
    manifest = _sample_manifest(
        impact={
            "external_effect": "runtime-mutation",
            "reversibility": "rollback-required",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )
    _, lock = resolve_toolkit(manifest, permission_profiles=builtin_profiles)
    work_item = _sample_work_item(authority_class="publication", consequence_class="medium")
    task_profiles = [*builtin_profiles, looser_profile]
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        permission_profiles=task_profiles,
    )
    forged = task.model_copy(update={"permission_profile_ids": ["aaa-publication"]})
    with pytest.raises(ToolkitResolutionError, match="exceeds pinned profile"):
        validate_task_toolkit_against_ceiling(
            forged,
            lock,
            build_default_registry(),
            work_item,
            task_profiles,
        )


# --- SUE-338: integration preflight and fail-closed integration reconciliation -------------


def _integration_health(state: IntegrationHealthState, integration_id: str = "work-tracker") -> IntegrationHealth:
    return IntegrationHealth(integration_id=integration_id, state=state)


def _shared_service_manifest() -> ProjectManifest:
    return _sample_manifest(
        impact={
            "external_effect": "shared-service-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )


def _work_tracker_lock() -> ToolkitLock:
    _, lock = resolve_toolkit(
        _shared_service_manifest(),
        integrations=[_integration_work_tracker()],
        desired_integration_ids=["work-tracker"],
    )
    assert lock.integration_ids == ["work-tracker"]
    return lock


def test_task_toolkit_retains_integration_whose_preflight_health_is_sufficient() -> None:
    lock = _work_tracker_lock()
    work_item = _sample_work_item(authority_class="shared-service-write")
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        integrations=[_integration_work_tracker()],
        integration_health=[_integration_health(IntegrationHealthState.AUTHORIZED)],
    )
    assert task.integration_ids == ["work-tracker"]
    include = [
        decision
        for decision in task.decisions
        if decision.action == ResolutionAction.INCLUDE
        and decision.component_kind == "integration"
        and decision.component_id == "work-tracker"
    ]
    assert include and "authorized" in include[0].rationale


def test_task_toolkit_subtracts_integration_whose_health_is_unavailable() -> None:
    lock = _work_tracker_lock()
    work_item = _sample_work_item(authority_class="shared-service-write")
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        integrations=[_integration_work_tracker()],
        integration_health=[_integration_health(IntegrationHealthState.UNAVAILABLE)],
    )
    assert task.integration_ids == []
    exclude = [
        decision
        for decision in task.decisions
        if decision.action == ResolutionAction.EXCLUDE
        and decision.component_kind == "integration"
        and decision.component_id == "work-tracker"
    ]
    assert exclude, "unavailable integration must be explained, not silently dropped"
    assert "unavailable" in exclude[0].rationale


def test_task_toolkit_subtracts_integration_when_health_is_unobserved() -> None:
    lock = _work_tracker_lock()
    work_item = _sample_work_item(authority_class="shared-service-write")
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        integrations=[_integration_work_tracker()],
        integration_health=[],
    )
    assert task.integration_ids == []


def test_task_toolkit_subtracts_integration_exceeding_work_item_authority() -> None:
    lock = _work_tracker_lock()
    read_only_item = _sample_work_item(
        authority_class="read-only",
        work_class="discovery",
    )
    task = resolve_task_toolkit_for_work_item(
        read_only_item,
        lock,
        integrations=[_integration_work_tracker()],
        integration_health=[_integration_health(IntegrationHealthState.AUTHORIZED)],
    )
    assert task.integration_ids == []
    exclude = [
        decision
        for decision in task.decisions
        if decision.action == ResolutionAction.EXCLUDE
        and decision.component_kind == "integration"
        and decision.component_id == "work-tracker"
    ]
    assert exclude and "work.write" in exclude[0].rationale


def test_task_toolkit_subtracts_integration_with_no_declared_spec() -> None:
    lock = _work_tracker_lock()
    work_item = _sample_work_item(authority_class="shared-service-write")
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        integrations=[],
        integration_health=[_integration_health(IntegrationHealthState.HEALTHY)],
    )
    assert task.integration_ids == []


def test_undeclared_integration_is_not_pinned_in_project_lock() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    _, lock = resolve_toolkit(manifest, desired_integration_ids=["work-tracker"])
    assert lock.integration_ids == []
    exclude = [
        decision
        for decision in lock.decisions
        if decision.action == ResolutionAction.EXCLUDE
        and decision.component_kind == "integration"
        and decision.component_id == "work-tracker"
    ]
    assert exclude and "no IntegrationSpec declared" in exclude[0].rationale


def test_absent_integration_spec_is_never_wider_than_a_supplied_one() -> None:
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    _, without_spec = resolve_toolkit(manifest, desired_integration_ids=["work-tracker"])
    _, with_spec = resolve_toolkit(
        manifest,
        integrations=[_integration_work_tracker()],
        desired_integration_ids=["work-tracker"],
    )
    assert set(without_spec.integration_ids) <= set(with_spec.integration_ids)
    assert without_spec.integration_ids == []


def test_lock_ceiling_validator_rejects_integration_with_no_declared_spec() -> None:
    registry = build_default_registry()
    forged = ToolkitLock(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        project_name="forged",
        integration_ids=["work-tracker"],
    )
    with pytest.raises(ToolkitResolutionError, match="no declared IntegrationSpec"):
        validate_toolkit_lock_against_ceiling(
            forged,
            registry,
            ExternalEffectClass.PUBLICATION,
            integrations=[],
        )


# --- SUE-338: registry-load guards --------------------------------------------------------


def test_effect_keyed_policy_requirement_without_sibling_is_rejected() -> None:
    registry = build_default_registry()
    orphan = PolicyRule(
        id="publication-only-requirement",
        description="Requires a skill only for publication projects",
        when=PolicyPredicate(external_effect=ExternalEffectClass.PUBLICATION),
        require_skills=["deterministic-test"],
    )
    bad_registry = registry.model_copy(
        update={"policy_rules": [*registry.policy_rules, orphan]}
    )
    with pytest.raises(
        ToolkitResolutionError,
        match="lacks read-only or effect-agnostic sibling",
    ):
        resolve_toolkit(_sample_manifest(), registry=bad_registry)


def test_effect_keyed_policy_requirement_with_sibling_is_accepted() -> None:
    registry = build_default_registry()
    effect_rule = PolicyRule(
        id="publication-only-requirement",
        description="Requires a skill for publication projects",
        when=PolicyPredicate(external_effect=ExternalEffectClass.PUBLICATION),
        require_skills=["deterministic-test"],
    )
    sibling = PolicyRule(
        id="read-only-sibling-requirement",
        description="Same requirement for read-only projects",
        when=PolicyPredicate(external_effect=ExternalEffectClass.READ_ONLY),
        require_skills=["deterministic-test"],
    )
    good_registry = registry.model_copy(
        update={"policy_rules": [*registry.policy_rules, effect_rule, sibling]}
    )
    _, lock = resolve_toolkit(_sample_manifest(), registry=good_registry)
    assert "deterministic-test" in lock.skill_ids


def test_registry_without_validators_fails_closed_instead_of_pinning_names() -> None:
    registry = build_default_registry()
    bad_registry = registry.model_copy(update={"validators": []})
    with pytest.raises(ToolkitResolutionError, match="missing mandatory validator"):
        resolve_toolkit(_sample_manifest(), registry=bad_registry)


def test_registry_missing_only_evidence_validator_fails_closed() -> None:
    registry = build_default_registry()
    remaining = [item for item in registry.validators if item.id != "evidence-contract"]
    bad_registry = registry.model_copy(update={"validators": remaining})
    with pytest.raises(ToolkitResolutionError, match="evidence-contract"):
        resolve_toolkit(_sample_manifest(), registry=bad_registry)


def test_toolkit_lock_pins_validator_versions() -> None:
    _, lock = resolve_toolkit(_sample_manifest())
    assert lock.validator_ids
    assert set(lock.validator_versions) == set(lock.validator_ids)
    registry_versions = {item.id: item.version for item in build_default_registry().validators}
    for validator_id, version in lock.validator_versions.items():
        assert version == registry_versions[validator_id]


# --- SUE-338: fail-closed unknown capability ids and helper defaults ----------------------


def test_unknown_capability_id_fail_closed_against_read_only_ceiling() -> None:
    from agent_foundry.models.registry import RoleContract

    registry = build_default_registry()
    ghost_role = RoleContract(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="ghost-role",
        version="1.0.0",
        description="Role allowing a capability that has no CapabilitySpec",
        allowed_capabilities=["ghost.capability"],
    )
    assert all(item.id != "ghost.capability" for item in registry.capabilities)
    registry = registry.model_copy(update={"roles": [*registry.roles, ghost_role]})
    registry = registry.model_copy(
        update={
            "policy_rules": [
                *registry.policy_rules,
                PolicyRule(
                    id="test-require-ghost-role",
                    description="test",
                    when=PolicyPredicate(),
                    require_roles=["ghost-role"],
                ),
            ]
        }
    )
    manifest = _sample_manifest(
        impact={
            "external_effect": "read-only",
            "reversibility": "trivial",
            "consequence": "low",
        },
        assurance={"required": []},
    )
    with pytest.raises(PolicyViolationError, match="policy-required roles unsatisfiable: ghost-role"):
        resolve_toolkit(manifest, registry=registry)


def test_capability_helper_defaults_to_publication_when_effect_omitted() -> None:
    from agent_foundry.toolkit.builtin_registry import _cap

    spec = _cap("unclassified.capability", "Capability added without stating its effect")
    assert spec.min_external_effect == ExternalEffectClass.PUBLICATION
    assert EFFECT_RANK[spec.min_external_effect] == max(EFFECT_RANK.values())


def test_min_external_effect_documents_the_axis_it_measures() -> None:
    description = CapabilitySpec.model_fields["min_external_effect"].description
    assert description is not None
    assert "read-only" in description


# --- SUE-338: work.read is a read, not a write --------------------------------------------


def test_work_read_is_read_only_and_work_write_is_shared_service_write() -> None:
    by_id = {item.id: item for item in build_default_registry().capabilities}
    assert by_id["work.read"].min_external_effect == ExternalEffectClass.READ_ONLY
    assert by_id["work.write"].min_external_effect == ExternalEffectClass.SHARED_SERVICE_WRITE
    assert (
        by_id["work.read"].min_external_effect == by_id["runtime.verify"].min_external_effect
    ), "reading an external system is classified the same way regardless of which system"


# --- SUE-338 follow-up: absent health evidence is not a health observation ----------------


def _integration_no_auth(required: IntegrationHealthState) -> IntegrationSpec:
    """Integration declaring no auth — the shape that used to self-report as configured."""
    return IntegrationSpec(
        schema_version=FOUNDRY_SCHEMA_VERSION,
        id="repository",
        kind=IntegrationKind.INTEGRATION,
        transport=IntegrationTransport.LOCAL_SERVICE,
        version="1",
        capabilities=["repository.read", "repository.write"],
        permissions=IntegrationPermissions(write_requires=AuthorityRequirement.BOUNDED_POLICY),
        auth=None,
        health=IntegrationHealthRequirement(required=required),
    )


def _repository_write_manifest() -> ProjectManifest:
    return _sample_manifest(
        impact={
            "external_effect": "repository-write",
            "reversibility": "versioned",
            "consequence": "medium",
        },
        assurance={"required": ["deterministic-tests"]},
    )


def _repository_lock(spec: IntegrationSpec) -> ToolkitLock:
    _, lock = resolve_toolkit(_repository_write_manifest(), integrations=[spec])
    assert lock.integration_ids == ["repository"]
    return lock


def test_unobserved_integration_without_auth_is_not_reported_configured() -> None:
    spec = _integration_no_auth(IntegrationHealthState.CONFIGURED)
    health = check_integrations([spec], required_ids=["repository"], observed_health=[])
    assert health[0].state != IntegrationHealthState.CONFIGURED
    assert health[0].state == IntegrationHealthState.DESIRED
    assert "not observed" in (health[0].message or "")


def test_unobserved_integration_without_auth_does_not_reach_task_toolkit() -> None:
    spec = _integration_no_auth(IntegrationHealthState.CONFIGURED)
    lock = _repository_lock(spec)
    work_item = _sample_work_item(authority_class="repository-write")
    task = resolve_task_toolkit_for_work_item(
        work_item,
        lock,
        integrations=[spec],
        integration_health=[],
    )
    assert task.integration_ids == []
    exclude = [
        decision
        for decision in task.decisions
        if decision.action == ResolutionAction.EXCLUDE
        and decision.component_kind == "integration"
        and decision.component_id == "repository"
    ]
    assert exclude and "desired" in exclude[0].rationale


def test_auth_shape_does_not_decide_unobserved_health_state() -> None:
    """The declaration shape says nothing about the world; only the diagnostic differs."""
    without_auth = _integration_no_auth(IntegrationHealthState.CONFIGURED)
    with_auth = _integration_work_tracker()

    no_auth_health = check_integrations(
        [without_auth], required_ids=["repository"], observed_health=[]
    )[0]
    auth_health = check_integrations(
        [with_auth], required_ids=["work-tracker"], observed_health=[]
    )[0]

    assert no_auth_health.state == auth_health.state == IntegrationHealthState.DESIRED
    assert no_auth_health.message != auth_health.message


def test_declared_no_health_bar_is_distinct_from_unobserved_health() -> None:
    """Absent evidence and a declared "no verification needed" are different states.

    Same absent evidence on the observation side; the outcome is decided by what the
    IntegrationSpec actually declared, never by what was left unsaid.
    """
    work_item = _sample_work_item(authority_class="repository-write")

    bar_declared = _integration_no_auth(IntegrationHealthState.CONFIGURED)
    unobserved = resolve_task_toolkit_for_work_item(
        work_item,
        _repository_lock(bar_declared),
        integrations=[bar_declared],
        integration_health=[],
    )
    assert unobserved.integration_ids == [], "unobserved health must not clear a declared bar"

    no_bar = _integration_no_auth(IntegrationHealthState.DESIRED)
    waived = resolve_task_toolkit_for_work_item(
        work_item,
        _repository_lock(no_bar),
        integrations=[no_bar],
        integration_health=[],
    )
    assert waived.integration_ids == ["repository"], (
        "health.required=desired is the explicit declared way to waive verification"
    )

    observed = resolve_task_toolkit_for_work_item(
        work_item,
        _repository_lock(bar_declared),
        integrations=[bar_declared],
        integration_health=[
            IntegrationHealth(
                integration_id="repository",
                state=IntegrationHealthState.CONFIGURED,
            )
        ],
    )
    assert observed.integration_ids == ["repository"], "a real observation clears the bar"


def test_project_lock_pins_declared_integration_independently_of_volatile_health() -> None:
    """The lock is the approved universe and must stay reproducible.

    Health is volatile, so gating the lock on it would make one manifest resolve
    differently run to run. Subtraction of unusable integrations happens at task time
    (docs/foundry/04 §4), which is what the preceding tests pin down.
    """
    spec = _integration_no_auth(IntegrationHealthState.CONFIGURED)
    manifest = _repository_write_manifest()
    _, unobserved_lock = resolve_toolkit(manifest, integrations=[spec])
    _, observed_lock = resolve_toolkit(
        manifest,
        integrations=[spec],
        integration_health=[
            IntegrationHealth(
                integration_id="repository",
                state=IntegrationHealthState.HEALTHY,
            )
        ],
    )
    assert unobserved_lock.integration_ids == observed_lock.integration_ids == ["repository"]
    assert dump_json(unobserved_lock) == dump_json(observed_lock)
