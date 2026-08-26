"""Toolkit registry and deterministic resolution tests."""

from __future__ import annotations

import hashlib
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
    _retract_include,
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
        "work_class": "CAPABILITY",
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


def test_default_registry_is_small_and_inspectable() -> None:
    registry = default_registry()
    assert len(registry.roles) == 7
    assert len(registry.skills) == 4
    assert len(registry.workflows) == 4
    assert registry.foundry_compat == ">=0.1,<0.2"


def test_resolve_project_toolkit_from_sample_manifest() -> None:
    manifest = load_yaml(ProjectManifest, (FIXTURES / "project_manifest.yaml").read_bytes())
    resolution, lock = resolve_toolkit(manifest)
    assert "bounded-change" in lock.skill_ids
    assert "independent-review" in lock.skill_ids
    assert "builder-reviewer" in lock.workflow_ids
    assert "runtime-verifier" in lock.role_ids
    assert "runtime.verify" in lock.capability_ids
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
    work_item = _sample_work_item(authority_class="read-only", consequence_class="medium")
    task = resolve_task_toolkit_for_work_item(work_item, project_lock)

    assert set(task.capability_ids) <= set(project_lock.capability_ids)
    assert set(task.skill_ids) <= set(project_lock.skill_ids)
    assert set(task.role_ids) <= set(project_lock.role_ids)
    assert set(task.integration_ids) <= set(project_lock.integration_ids)

    assert task.permission_profile_ids == ["read-only"]
    assert project_lock.permission_profile_ids == ["repository-write-bounded"]

    excluded_skills = set(project_lock.skill_ids) - set(task.skill_ids)
    assert "bounded-change" in excluded_skills


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
    bad_skill = registry.skills[0].model_copy(update={"schema_version": "0.2"})
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


def test_resolve_toolkit_on_repo_explains_empty_manifest() -> None:
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
    assert '"decisions"' in result.stdout
    assert "unknown" in result.stdout.lower()
    assert '"capability_ids":[]' in result.stdout.replace(" ", "") or '"capability_ids": []' in result.stdout
    assert '"integration_ids":[]' in result.stdout.replace(" ", "") or '"integration_ids": []' in result.stdout
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
                impact: dict[str, str] = {"reversibility": "trivial"}
                if external_effect is not None:
                    impact["external_effect"] = external_effect
                if consequence is not None:
                    impact["consequence"] = consequence
                manifest = _sample_manifest(
                    impact=impact,
                    assurance={"required": assurance},
                )
                try:
                    _, lock = resolve_toolkit(manifest)
                    if "independent-review" not in lock.skill_ids:
                        dropped += 1
                except PolicyViolationError:
                    pass
    assert dropped == 0


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
