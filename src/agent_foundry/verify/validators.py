"""Independently derived validators over finished Foundry artifacts.

Each validator restates a property from `docs/foundry/` and checks it against the
artifact as data. None of them calls the function that produced the artifact, so a
wrong producer cannot launder a wrong result through the check that is supposed to
catch it. `agent_foundry.verify.claims` records what each one proves and what it
does not.

This includes rules that a pydantic model validator also enforces. A model
validator is a producer — it decides whether an artifact may exist — so its helper
is off limits here, and the obligations it checks are restated in
`agent_foundry.verify.independent` from the contract text instead. A dependency test
reads the import graph of every module in this package to keep that route closed.

Three rules the whole module obeys:

* Absence resolves to `MISSING`, never `PASS`. An unobserved integration, an absent
  evidence class, an unrecognised requirement — none of them pass by default.
* `NOT_REQUIRED` is only ever returned for something declared not required.
* Every report contains at least one finding, so "the validator ran and found
  nothing to say" is never indistinguishable from "the validator did not run".
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from agent_foundry import __version__
from agent_foundry.models.base import FOUNDRY_SCHEMA_VERSION, FoundryModel
from agent_foundry.models.common import (
    DependencyRelation,
    EvidenceClass,
    EvidenceResult,
    EvidenceState,
    ExternalEffectClass,
    IntegrationHealthState,
    ProvenanceKind,
    ValidationOutcome,
)
from agent_foundry.models.execution import CompiledAuthority, ExecutionBundle
from agent_foundry.models.integrations import IntegrationHealth, IntegrationSpec
from agent_foundry.models.interaction import (
    EvidenceBundle,
    ExecutionReceipt,
    ReviewDecision,
)
from agent_foundry.models.policy import PermissionProfile
from agent_foundry.models.project import ProjectManifest
from agent_foundry.models.registry import CapabilityRegistry, RoleContract
from agent_foundry.models.toolkit import TaskToolkit, ToolkitLock
from agent_foundry.models.verification import ValidationFinding, ValidationReport
from agent_foundry.models.work import WorkItemContract
from agent_foundry.verify import claims
from agent_foundry.verify.independent import (
    authentication_evidenced,
    compat_clause_satisfied,
    contained_in_any,
    contract_digest,
    declared_ceiling,
    effect_rank,
    evidence_state_partition_conflicts,
    exceeds,
    finding_obligation_violations,
    health_satisfies,
    normalize_repository_path,
    parse_major_minor,
    parse_release_version,
    path_within,
)

# Relations that mean "the target must be closed first". Restated from
# docs/foundry/03 §dependency relations rather than imported, so that a change to
# the decomposition engine's edge table shows up here as a disagreement.
_PREREQUISITE_RELATIONS: frozenset[DependencyRelation] = frozenset(
    {
        DependencyRelation.REQUIRES,
        DependencyRelation.APPLIES_AFTER,
        DependencyRelation.DISCOVERED_BY,
        DependencyRelation.VALIDATES,
        DependencyRelation.SUPERSEDES,
    }
)

# Health requirements that cannot be met without a completed authentication.
_AUTH_IMPLYING_REQUIREMENTS: frozenset[IntegrationHealthState] = frozenset(
    {
        IntegrationHealthState.AUTHENTICATED,
        IntegrationHealthState.AUTHORIZED,
        IntegrationHealthState.HEALTHY,
    }
)

# Evidence classes named by the durable contract, indexed by their declared value so
# a work item's free-text requirement can be matched to a typed class.
_EVIDENCE_CLASS_BY_VALUE: dict[str, EvidenceClass] = {
    member.value: member for member in EvidenceClass
}

# Roles whose contract is judgement about someone else's change. Holding write
# authority collapses the separation the review is for.
_REVIEW_ONLY_ROLE_IDS: frozenset[str] = frozenset({"reviewer", "runtime-verifier"})


def _finding(
    validator_id: str,
    outcome: ValidationOutcome,
    subject: str,
    message: str,
    evidence_refs: list[str] | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        validator_id=validator_id,
        outcome=outcome,
        subject=subject,
        message=message,
        evidence_refs=sorted(evidence_refs or []),
    )


def _report(
    subject_kind: str,
    subject_id: str,
    findings: list[ValidationFinding],
    *,
    validator_id: str,
    pass_message: str,
    pass_subject: str,
) -> ValidationReport:
    """Assemble a report, substituting an explicit PASS when nothing was wrong.

    An empty findings list would aggregate to MISSING by design, so a validator that
    genuinely found nothing has to say so rather than return silence.
    """
    if not findings:
        findings = [
            _finding(validator_id, ValidationOutcome.PASS, pass_subject, pass_message)
        ]
    return ValidationReport(
        subject_kind=subject_kind,
        subject_id=subject_id,
        findings=findings,
    )


def _payload(model: FoundryModel | Mapping[str, Any]) -> dict[str, Any]:
    """View a model as plain data.

    Validators read the serialized form so that an object assembled through
    `model_construct` — bypassing every field and model validator — is examined on
    the same terms as one that was validated on the way in.
    """
    if isinstance(model, Mapping):
        return dict(model)
    return model.model_dump(mode="json")


# --- 1. schema / version compatibility --------------------------------------


def validate_contract_schema_compatibility(
    contracts: Iterable[tuple[str, Any]],
    *,
    supported_schema_version: str = FOUNDRY_SCHEMA_VERSION,
    running_version: str = __version__,
) -> ValidationReport:
    """Check declared schema and compat expressions against what this build supports.

    Reads `schema_version` and `foundry_compat` off the serialized payload and
    compares them with a second parser. The producing check lives in a pydantic model
    validator; neutralizing it lets an incompatible contract be constructed, and this
    validator still rejects it.
    """
    validator_id = claims.CONTRACT_SCHEMA_COMPATIBILITY
    supported = parse_major_minor(supported_schema_version)
    findings: list[ValidationFinding] = []
    seen = 0

    if supported is None:
        return ValidationReport(
            subject_kind="contract-set",
            subject_id="schema",
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    "supported-version",
                    f"supported schema version {supported_schema_version!r} is not MAJOR.MINOR",
                )
            ],
        )

    current_release = parse_release_version(running_version)

    for name, contract in contracts:
        seen += 1
        data = _payload(contract)
        declared = data.get("schema_version")
        if declared is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    name,
                    "contract declares no schema_version; compatibility is unproven",
                )
            )
        else:
            parsed = parse_major_minor(str(declared))
            if parsed is None:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        name,
                        f"schema_version {declared!r} is not MAJOR.MINOR",
                    )
                )
            elif parsed[0] != supported[0]:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        name,
                        f"schema_version {declared} has major {parsed[0]}, "
                        f"supported major is {supported[0]}",
                    )
                )
            elif parsed[1] > supported[1]:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        name,
                        f"schema_version {declared} is newer than supported "
                        f"{supported_schema_version}",
                    )
                )

        compat = data.get("foundry_compat")
        if compat is None:
            continue
        if current_release is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    name,
                    f"running version {running_version!r} is unparseable; "
                    f"foundry_compat {compat!r} cannot be evaluated",
                )
            )
            continue
        clauses = [part for part in str(compat).split(",")]
        if not clauses or any(not part.strip() for part in clauses):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    name,
                    f"foundry_compat {compat!r} is malformed",
                )
            )
            continue
        for clause in clauses:
            satisfied = compat_clause_satisfied(clause, current_release)
            if satisfied is None:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        name,
                        f"foundry_compat clause {clause.strip()!r} is unparseable",
                    )
                )
            elif not satisfied:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        name,
                        f"foundry_compat clause {clause.strip()!r} excludes running "
                        f"version {running_version}",
                    )
                )

    if seen == 0:
        return ValidationReport(
            subject_kind="contract-set",
            subject_id="schema",
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    "contract-set",
                    "no contracts supplied; nothing was checked",
                )
            ],
        )

    return _report(
        "contract-set",
        "schema",
        findings,
        validator_id=validator_id,
        pass_subject="contract-set",
        pass_message=f"{seen} contract(s) declare a supported schema version",
    )


# --- 2. work dependency graph ------------------------------------------------


def validate_work_dependency_graph(work_items: list[WorkItemContract]) -> ValidationReport:
    """Check the declared dependency graph for the properties a plan must hold.

    Builds prerequisite edges from the relation semantics and looks for cycles with
    an explicit colour-marking depth-first walk. The decomposition engine validates
    the same graph with a topological sort; neutralizing it lets a cyclic plan
    through, and this walk still finds the cycle.
    """
    validator_id = claims.WORK_DEPENDENCY_GRAPH
    findings: list[ValidationFinding] = []

    if not work_items:
        return ValidationReport(
            subject_kind="work-plan",
            subject_id="dependency-graph",
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    "work-plan",
                    "no work items supplied; the dependency graph was not checked",
                )
            ],
        )

    counts: dict[str, int] = defaultdict(int)
    for item in work_items:
        counts[item.id] += 1
    duplicates = sorted(item_id for item_id, count in counts.items() if count > 1)
    for item_id in duplicates:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                item_id,
                f"work item id {item_id!r} appears {counts[item_id]} times",
            )
        )

    known = set(counts)
    prerequisites: dict[str, set[str]] = {item_id: set() for item_id in known}
    blocks: set[tuple[str, str]] = set()

    for item in sorted(work_items, key=lambda wi: wi.id):
        for dep in sorted(item.dependencies, key=lambda d: (d.relation.value, d.target_id)):
            if dep.target_id not in known:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        item.id,
                        f"dependency {dep.relation.value} -> {dep.target_id!r} names an "
                        "item that is not in this plan",
                    )
                )
                continue
            if dep.target_id == item.id:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        item.id,
                        f"work item declares a {dep.relation.value} dependency on itself",
                    )
                )
                continue
            if dep.relation in _PREREQUISITE_RELATIONS:
                prerequisites[item.id].add(dep.target_id)
            elif dep.relation == DependencyRelation.BLOCKS:
                prerequisites[dep.target_id].add(item.id)
                blocks.add((item.id, dep.target_id))

    for source, target in sorted(blocks):
        if (target, source) in blocks:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    source,
                    f"work items {source!r} and {target!r} each declare they block the other",
                )
            )

    cycle = _first_cycle(prerequisites)
    if cycle is not None:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                cycle[0],
                "circular dependency: " + " -> ".join(cycle),
            )
        )

    return _report(
        "work-plan",
        "dependency-graph",
        findings,
        validator_id=validator_id,
        pass_subject="work-plan",
        pass_message=(
            f"{len(known)} work item(s) form an acyclic graph with no dangling, "
            "self, or mutually blocking dependencies"
        ),
    )


def _first_cycle(prerequisites: dict[str, set[str]]) -> list[str] | None:
    """Return one cycle as a node path, or None.

    Explicit three-colour marking with an iterative stack: white nodes are unvisited,
    grey nodes are on the current path, black nodes are finished. A grey node reached
    again closes a cycle.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {node: WHITE for node in prerequisites}
    parent: dict[str, str | None] = {node: None for node in prerequisites}

    for root in sorted(prerequisites):
        if colour[root] != WHITE:
            continue
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            node, finished = stack.pop()
            if finished:
                colour[node] = BLACK
                continue
            if colour[node] == GREY:
                continue
            colour[node] = GREY
            stack.append((node, True))
            for neighbour in sorted(prerequisites.get(node, ())):
                if colour.get(neighbour) == GREY:
                    path = [neighbour]
                    walk: str | None = node
                    while walk is not None and walk != neighbour:
                        path.append(walk)
                        walk = parent[walk]
                    path.append(neighbour)
                    return list(reversed(path))
                if colour.get(neighbour) == WHITE:
                    parent[neighbour] = node
                    stack.append((neighbour, False))
    return None


# --- 3. Project Toolkit / Task Toolkit coherence -----------------------------


def validate_toolkit_coherence(
    task_toolkit: TaskToolkit,
    project_lock: ToolkitLock,
    registry: CapabilityRegistry,
) -> ValidationReport:
    """Check the task subset against the pinned project lock and the registry.

    Expressed as set relations over the two contracts. The resolver enforces the same
    containment while building; neutralizing it lets a task toolkit escape the lock,
    and these relations still catch it.
    """
    validator_id = claims.TOOLKIT_COHERENCE
    findings: list[ValidationFinding] = []

    capabilities = {item.id for item in registry.capabilities}
    skills_by_id = {item.id: item for item in registry.skills}
    workflows_by_id = {item.id: item for item in registry.workflows}
    roles = {item.id for item in registry.roles}
    validators = {item.id for item in registry.validators}

    subsets: list[tuple[str, list[str], list[str]]] = [
        ("capability", task_toolkit.capability_ids, project_lock.capability_ids),
        ("skill", task_toolkit.skill_ids, project_lock.skill_ids),
        ("role", task_toolkit.role_ids, project_lock.role_ids),
        ("validator", task_toolkit.validator_ids, project_lock.validator_ids),
        ("integration", task_toolkit.integration_ids, project_lock.integration_ids),
        (
            "permission-profile",
            task_toolkit.permission_profile_ids,
            project_lock.permission_profile_ids,
        ),
        ("budget-profile", task_toolkit.budget_profile_ids, project_lock.budget_profile_ids),
    ]
    for kind, task_ids, lock_ids in subsets:
        for escaped in sorted(set(task_ids) - set(lock_ids)):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"{kind}:{escaped}",
                    f"task toolkit {kind} {escaped!r} is not in the pinned project lock",
                )
            )
        duplicates = sorted({item for item in task_ids if task_ids.count(item) > 1})
        for duplicate in duplicates:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"{kind}:{duplicate}",
                    f"task toolkit lists {kind} {duplicate!r} more than once",
                )
            )

    if task_toolkit.workflow_id is not None:
        if task_toolkit.workflow_id not in project_lock.workflow_ids:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"workflow:{task_toolkit.workflow_id}",
                    f"task workflow {task_toolkit.workflow_id!r} is not in the project lock",
                )
            )
        workflow = workflows_by_id.get(task_toolkit.workflow_id)
        if workflow is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"workflow:{task_toolkit.workflow_id}",
                    f"task workflow {task_toolkit.workflow_id!r} is not in the registry",
                )
            )
        else:
            for role_id in sorted(set(workflow.required_roles) - set(task_toolkit.role_ids)):
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.MISSING,
                        f"workflow:{workflow.id}",
                        f"workflow requires role {role_id!r}, which the task toolkit does "
                        "not carry",
                    )
                )
            for skill_id in sorted(set(workflow.required_skills) - set(task_toolkit.skill_ids)):
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.MISSING,
                        f"workflow:{workflow.id}",
                        f"workflow requires skill {skill_id!r}, which the task toolkit "
                        "does not carry",
                    )
                )

    registry_membership: list[tuple[str, list[str], set[str]]] = [
        ("capability", task_toolkit.capability_ids, capabilities),
        ("skill", task_toolkit.skill_ids, set(skills_by_id)),
        ("role", task_toolkit.role_ids, roles),
        ("validator", task_toolkit.validator_ids, validators),
    ]
    for kind, ids, available in registry_membership:
        for unknown in sorted(set(ids) - available):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"{kind}:{unknown}",
                    f"task toolkit {kind} {unknown!r} is not declared in the registry",
                )
            )

    for skill_id in sorted(task_toolkit.skill_ids):
        skill = skills_by_id.get(skill_id)
        if skill is None:
            continue
        for capability_id in sorted(
            set(skill.required_capabilities) - set(task_toolkit.capability_ids)
        ):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"skill:{skill_id}",
                    f"skill requires capability {capability_id!r}, which the task "
                    "toolkit does not carry",
                )
            )

    findings.extend(_lock_pin_findings(project_lock, validator_id))
    findings.extend(_decision_conflict_findings(task_toolkit, project_lock, validator_id))

    return _report(
        "task-toolkit",
        task_toolkit.work_item_id,
        findings,
        validator_id=validator_id,
        pass_subject=f"task-toolkit:{task_toolkit.work_item_id}",
        pass_message=(
            "task toolkit is contained in the pinned project lock, resolves in the "
            "registry, and satisfies its skill and workflow requirements"
        ),
    )


def _lock_pin_findings(project_lock: ToolkitLock, validator_id: str) -> list[ValidationFinding]:
    """A pinned version must name a selected component, and vice versa."""
    findings: list[ValidationFinding] = []
    pin_sets: list[tuple[str, dict[str, str], list[str]]] = [
        ("skill", project_lock.skill_versions, project_lock.skill_ids),
        ("workflow", project_lock.workflow_versions, project_lock.workflow_ids),
        (
            "integration",
            project_lock.integration_adapter_versions,
            project_lock.integration_ids,
        ),
    ]
    for kind, pins, selected in pin_sets:
        for orphan in sorted(set(pins) - set(selected)):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"{kind}:{orphan}",
                    f"project lock pins a version for {kind} {orphan!r}, which it does "
                    "not select",
                )
            )
        for unpinned in sorted(set(selected) - set(pins)):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"{kind}:{unpinned}",
                    f"project lock selects {kind} {unpinned!r} without pinning a version",
                )
            )
    return findings


def _decision_conflict_findings(
    task_toolkit: TaskToolkit,
    project_lock: ToolkitLock,
    validator_id: str,
) -> list[ValidationFinding]:
    """A component cannot be both included and excluded by the same decision record."""
    findings: list[ValidationFinding] = []
    for label, decisions in (
        ("task-toolkit", task_toolkit.decisions),
        ("project-lock", project_lock.decisions),
    ):
        actions: dict[tuple[str, str], set[str]] = defaultdict(set)
        for decision in decisions:
            actions[(decision.component_kind, decision.component_id)].add(decision.action.value)
        for (kind, component_id), seen in sorted(actions.items()):
            if len(seen) > 1:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        f"{kind}:{component_id}",
                        f"{label} records both include and exclude for {kind} "
                        f"{component_id!r}",
                    )
                )
    return findings


# --- 4. authority ceiling ----------------------------------------------------


def validate_authority_ceiling(
    authority: CompiledAuthority,
    *,
    work_item: WorkItemContract,
    manifest: ProjectManifest,
    task_toolkit: TaskToolkit,
    role: RoleContract | None,
    permission_profile: PermissionProfile | None,
    registry: CapabilityRegistry,
) -> ValidationReport:
    """Check compiled authority against each declared bound, one bound at a time.

    Ranking and unknown handling are re-derived in `verify.independent`; nothing here
    consults the compiler's rank table or its intersection. A compiler that computes
    a widened ceiling, and a `validate_execution_bundle_authority` that agrees with
    it, both still fail these comparisons.
    """
    validator_id = claims.AUTHORITY_CEILING
    findings: list[ValidationFinding] = []
    granted = authority.external_effect

    manifest_ceiling = declared_ceiling(manifest.impact.external_effect)
    if exceeds(granted, manifest_ceiling):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                "manifest",
                f"granted {granted.value} exceeds the manifest ceiling "
                f"{manifest_ceiling.value}",
            )
        )
    if manifest.impact.external_effect is None and granted != ExternalEffectClass.READ_ONLY:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                "manifest",
                "project manifest declares no external effect; only read-only "
                f"authority is supportable, not {granted.value}",
            )
        )

    if exceeds(granted, work_item.authority_class):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                f"work-item:{work_item.id}",
                f"granted {granted.value} exceeds the work item authority class "
                f"{work_item.authority_class.value}",
            )
        )

    if permission_profile is None:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                "permission-profile",
                "no permission profile supplied; the policy bound on this authority "
                "is unproven",
            )
        )
    elif exceeds(granted, permission_profile.external_effect):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                f"permission-profile:{permission_profile.id}",
                f"granted {granted.value} exceeds the permission profile bound "
                f"{permission_profile.external_effect.value}",
            )
        )

    capabilities_by_id = {item.id: item for item in registry.capabilities}

    if role is None:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                "role",
                "no role contract supplied; the role bound on this authority is unproven",
            )
        )
    else:
        role_ceiling = ExternalEffectClass.READ_ONLY
        for capability_id in role.allowed_capabilities:
            spec = capabilities_by_id.get(capability_id)
            if spec is None:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.MISSING,
                        f"role:{role.id}",
                        f"role allows capability {capability_id!r}, which is not in the "
                        "registry; its authority demand is unknown",
                    )
                )
                continue
            if effect_rank(spec.min_external_effect) > effect_rank(role_ceiling):
                role_ceiling = spec.min_external_effect
        if exceeds(granted, role_ceiling):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"role:{role.id}",
                    f"granted {granted.value} exceeds what role capabilities reach "
                    f"({role_ceiling.value})",
                )
            )

    for capability_id in sorted(task_toolkit.capability_ids):
        spec = capabilities_by_id.get(capability_id)
        if spec is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"capability:{capability_id}",
                    "allowed capability is not declared in the registry; its minimum "
                    "external effect is unknown and cannot be shown to fit",
                )
            )
            continue
        if exceeds(spec.min_external_effect, granted):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"capability:{capability_id}",
                    f"capability needs {spec.min_external_effect.value}, above the "
                    f"granted {granted.value}",
                )
            )

    if granted == ExternalEffectClass.READ_ONLY and authority.write_scope:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                "write-scope",
                f"read-only authority carries write scope {sorted(authority.write_scope)!r}",
            )
        )

    return _report(
        "compiled-authority",
        work_item.id,
        findings,
        validator_id=validator_id,
        pass_subject=f"work-item:{work_item.id}",
        pass_message=(
            f"granted {granted.value} is at or below every declared bound "
            "(manifest, work item, permission profile, role, capabilities)"
        ),
    )


# --- 5. write-scope containment ----------------------------------------------


def validate_write_scope_containment(
    authority: CompiledAuthority,
    *,
    work_item: WorkItemContract,
    role: RoleContract | None,
) -> ValidationReport:
    """Check every granted path resolves, and lies inside both declared bounds.

    Path resolution is re-derived in `verify.independent` on top of
    `posixpath.normpath`. Replacing the compiler's normalizer with the identity
    function lets a traversal escape into a compiled bundle; this still rejects it.
    """
    validator_id = claims.WRITE_SCOPE_CONTAINMENT
    findings: list[ValidationFinding] = []

    role_scope = list(role.write_scope) if role is not None else []

    for raw in sorted(authority.write_scope):
        resolved = normalize_repository_path(raw)
        if resolved is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    raw,
                    f"granted write path {raw!r} does not resolve to a usable "
                    "repository-relative bound",
                )
            )
            continue
        if not contained_in_any(resolved, list(work_item.scope)):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    raw,
                    f"granted write path {resolved!r} is not inside the work item scope "
                    f"{sorted(work_item.scope)!r}",
                )
            )
        if role is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    raw,
                    f"granted write path {resolved!r} has no role contract to be "
                    "checked against",
                )
            )
        elif not contained_in_any(resolved, role_scope):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    raw,
                    f"granted write path {resolved!r} is not inside the role write "
                    f"scope {sorted(role_scope)!r}",
                )
            )

    granted_resolved = {
        resolved
        for resolved in (normalize_repository_path(raw) for raw in authority.write_scope)
        if resolved is not None
    }
    for raw in sorted(authority.forbidden_scopes):
        resolved = normalize_repository_path(raw)
        if resolved is None:
            continue
        if resolved in granted_resolved:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    raw,
                    f"path {resolved!r} is declared both granted and forbidden",
                )
            )
        elif any(path_within(resolved, grant) for grant in granted_resolved):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    raw,
                    f"forbidden path {resolved!r} contains a granted path",
                )
            )

    return _report(
        "compiled-authority",
        work_item.id,
        findings,
        validator_id=validator_id,
        pass_subject=f"work-item:{work_item.id}",
        pass_message=(
            f"{len(granted_resolved)} granted write path(s) resolve and lie inside "
            "both the work item and role bounds"
        ),
    )


# --- 6. role separation / write-scope collisions -----------------------------


def validate_role_separation(
    bundles: list[ExecutionBundle],
    *,
    review_decisions: list[ReviewDecision] | None = None,
    review_only_role_ids: frozenset[str] = _REVIEW_ONLY_ROLE_IDS,
) -> ValidationReport:
    """Check that concurrently authorized roles do not overlap or self-review."""
    validator_id = claims.ROLE_SEPARATION
    findings: list[ValidationFinding] = []

    if not bundles:
        return ValidationReport(
            subject_kind="execution-bundle-set",
            subject_id="role-separation",
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    "execution-bundle-set",
                    "no bundles supplied; role separation was not checked",
                )
            ],
        )

    by_run: dict[tuple[str, str], list[ExecutionBundle]] = defaultdict(list)
    for bundle in bundles:
        by_run[(bundle.work_item_id, bundle.run_id)].append(bundle)

    for (work_item_id, run_id), group in sorted(by_run.items()):
        ordered = sorted(group, key=lambda item: item.role_id)
        seen_roles: dict[str, ExecutionBundle] = {}
        for bundle in ordered:
            if bundle.role_id in seen_roles:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        f"{work_item_id}/{run_id}",
                        f"role {bundle.role_id!r} holds two bundles in the same run",
                    )
                )
            seen_roles[bundle.role_id] = bundle

        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if left.role_id == right.role_id:
                    continue
                overlaps = sorted(
                    {
                        left_path
                        for left_path in left.write_scope
                        for right_path in right.write_scope
                        if path_within(left_path, right_path)
                        or path_within(right_path, left_path)
                    }
                )
                if overlaps:
                    findings.append(
                        _finding(
                            validator_id,
                            ValidationOutcome.BLOCKED,
                            f"{work_item_id}/{run_id}",
                            f"roles {left.role_id!r} and {right.role_id!r} hold "
                            f"overlapping write scope {overlaps!r}",
                        )
                    )

        for bundle in ordered:
            if bundle.role_id in review_only_role_ids and bundle.write_scope:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        f"{work_item_id}/{run_id}",
                        f"review-only role {bundle.role_id!r} holds write scope "
                        f"{sorted(bundle.write_scope)!r}",
                    )
                )

    for decision in review_decisions or []:
        if decision.implementing_role_id is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"{decision.work_item_id}/{decision.run_id}",
                    "review decision does not name the implementing role it is "
                    "independent of; independence is unproven",
                )
            )
        elif decision.implementing_role_id == decision.reviewer_role:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    f"{decision.work_item_id}/{decision.run_id}",
                    f"role {decision.reviewer_role!r} reviewed its own implementation",
                )
            )

    return _report(
        "execution-bundle-set",
        "role-separation",
        findings,
        validator_id=validator_id,
        pass_subject="execution-bundle-set",
        pass_message=(
            f"{len(bundles)} bundle(s) grant no overlapping write scope across roles "
            "and no review-only role holds write authority"
        ),
    )


# --- 7. integration preflight (auth AND health) -------------------------------


def validate_integration_preflight(
    integrations: list[IntegrationSpec],
    *,
    required_ids: list[str],
    observed_health: list[IntegrationHealth] | None = None,
    now: datetime | None = None,
    max_observation_age: timedelta | None = None,
) -> ValidationReport:
    """Check declared integrations against positive health observations.

    The rule this exists for: *unobserved is not healthy*. The preflight helper in
    `toolkit.preflight` synthesizes a state for an integration nobody has checked,
    which is fine as a report but must never read as a pass. Here, no observation is
    MISSING, and a required health that implies authentication needs an auth block
    plus an observation that positively evidences it.
    """
    validator_id = claims.INTEGRATION_PREFLIGHT
    findings: list[ValidationFinding] = []
    by_id = {spec.id: spec for spec in integrations}
    observed = {item.integration_id: item for item in (observed_health or [])}

    if not required_ids:
        return ValidationReport(
            subject_kind="integration-set",
            subject_id="preflight",
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.NOT_REQUIRED,
                    "integration-set",
                    "no integrations are required for this work item",
                )
            ],
        )

    for integration_id in sorted(set(required_ids)):
        spec = by_id.get(integration_id)
        if spec is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    integration_id,
                    "required integration is not declared; there is no spec to preflight",
                )
            )
            continue

        required = spec.health.required
        observation = observed.get(integration_id)

        if required in _AUTH_IMPLYING_REQUIREMENTS and spec.auth is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    integration_id,
                    f"required health {required.value} implies authentication, but the "
                    "spec declares no auth block",
                )
            )

        if observation is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    integration_id,
                    f"required health {required.value} has no observation; unobserved "
                    "is not healthy",
                )
            )
            continue

        if observation.checked_at is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    integration_id,
                    "health observation carries no checked_at; its freshness cannot be "
                    "established",
                )
            )
        elif now is not None and max_observation_age is not None:
            checked = observation.checked_at
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            reference = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
            if reference - checked > max_observation_age:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.MISSING,
                        integration_id,
                        f"health observation is older than {max_observation_age}; a "
                        "stale reading is not a current one",
                    )
                )

        if required in _AUTH_IMPLYING_REQUIREMENTS and not authentication_evidenced(
            observation.state
        ):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    integration_id,
                    f"observed state {observation.state.value} is not positive evidence "
                    "of authentication",
                )
            )

        if not health_satisfies(observation.state, required):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    integration_id,
                    f"observed state {observation.state.value} does not meet required "
                    f"health {required.value}",
                )
            )

    return _report(
        "integration-set",
        "preflight",
        findings,
        validator_id=validator_id,
        pass_subject="integration-set",
        pass_message=(
            f"{len(set(required_ids))} required integration(s) are declared and carry "
            "fresh observations meeting their auth and health requirements"
        ),
    )


# --- 8. required evidence classes --------------------------------------------


def validate_required_evidence(
    work_item: WorkItemContract,
    evidence_bundle: EvidenceBundle | None,
) -> ValidationReport:
    """Check each required evidence class against a typed, passing evidence item."""
    validator_id = claims.REQUIRED_EVIDENCE
    findings: list[ValidationFinding] = []

    if not work_item.required_evidence:
        return ValidationReport(
            subject_kind="evidence-bundle",
            subject_id=work_item.id,
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"work-item:{work_item.id}",
                    "work item declares no required evidence; what would prove this "
                    "work is unspecified, which is not the same as nothing being needed",
                )
            ],
        )

    if evidence_bundle is None:
        for requirement in sorted(work_item.required_evidence):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    requirement,
                    "no evidence bundle supplied; the requirement is unproven",
                )
            )
        return ValidationReport(
            subject_kind="evidence-bundle",
            subject_id=work_item.id,
            findings=findings,
        )

    exempt = {item.value for item in evidence_bundle.not_required_classes}
    required_classes = {
        _EVIDENCE_CLASS_BY_VALUE[requirement.strip()].value
        for requirement in work_item.required_evidence
        if requirement.strip() in _EVIDENCE_CLASS_BY_VALUE
    }
    satisfying: dict[str, list[str]] = defaultdict(list)
    for item in evidence_bundle.items:
        if item.evidence_class is None or item.result != EvidenceResult.PASS:
            continue
        satisfying[item.evidence_class.value].append(item.ref)

    for requirement in sorted(work_item.required_evidence):
        typed = _EVIDENCE_CLASS_BY_VALUE.get(requirement.strip())
        if typed is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    requirement,
                    f"required evidence {requirement!r} does not name a known evidence "
                    "class; it cannot be shown satisfied",
                )
            )
            continue
        if typed.value in exempt:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    requirement,
                    f"evidence class {typed.value} is both required by the work item "
                    "and declared not-required by the bundle",
                )
            )
            continue
        refs = satisfying.get(typed.value, [])
        if not refs:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    requirement,
                    f"no passing evidence item declares class {typed.value}",
                )
            )
            continue
        unproven = [
            item.ref
            for item in evidence_bundle.items
            if item.evidence_class == typed
            and item.result == EvidenceResult.PASS
            and not item.proves_revision
        ]
        if len(unproven) == len(refs):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    requirement,
                    f"evidence for class {typed.value} names no revision it proves",
                    evidence_refs=refs,
                )
            )
            continue
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.PASS,
                requirement,
                f"class {typed.value} satisfied by passing evidence naming a revision",
                evidence_refs=refs,
            )
        )

    for exempt_class in sorted(exempt):
        if exempt_class not in required_classes:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.NOT_REQUIRED,
                    exempt_class,
                    "evidence class declared not required for this work item",
                )
            )

    return ValidationReport(
        subject_kind="evidence-bundle",
        subject_id=work_item.id,
        findings=findings,
    )


# --- 9. evidence bundle completeness -----------------------------------------


def validate_evidence_bundle_completeness(bundle: EvidenceBundle) -> ValidationReport:
    """Check the bundle's own structure, reading it as data."""
    validator_id = claims.EVIDENCE_BUNDLE_COMPLETENESS
    findings: list[ValidationFinding] = []
    data = _payload(bundle)
    subject = str(data.get("work_item_id") or "unknown")

    for field in ("work_item_id", "run_id", "schema_version"):
        if not data.get(field):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject,
                    f"evidence bundle declares no {field}",
                )
            )

    identity = data.get("identity")
    if not identity:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "evidence bundle names no revision identity; what it proves something "
                "about is unrecorded",
            )
        )
    elif not identity.get("candidate_revision") and not identity.get("integrated_revision"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "evidence bundle identity names neither a candidate nor an integrated "
                "revision",
            )
        )

    items = data.get("items") or []
    if not items:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "evidence bundle carries no items",
            )
        )
    for index, item in enumerate(items):
        if not item.get("evidence_class"):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"{subject}#items[{index}]",
                    f"evidence item {item.get('ref')!r} declares no evidence_class; it "
                    "satisfies no typed requirement",
                )
            )
        if not item.get("result"):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    f"{subject}#items[{index}]",
                    f"evidence item {item.get('ref')!r} declares no result",
                )
            )

    attained = {
        item.get("evidence_class")
        for item in items
        if item.get("evidence_class") and item.get("result") == EvidenceResult.PASS.value
    }
    for exempt in data.get("not_required_classes") or []:
        if exempt in attained:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"evidence class {exempt} is declared not-required but also has "
                    "passing evidence",
                )
            )

    for index, finding_data in enumerate(data.get("unresolved") or []):
        for message in finding_obligation_violations(
            finding_data,
            label=str(finding_data.get("id", f"#{index}")),
        ):
            findings.append(
                _finding(validator_id, ValidationOutcome.BLOCKED, subject, message)
            )

    return _report(
        "evidence-bundle",
        subject,
        findings,
        validator_id=validator_id,
        pass_subject=subject,
        pass_message=(
            f"evidence bundle names its identity, carries {len(items)} typed item(s), "
            "and every unresolved finding meets its disposition's obligation"
        ),
    )


# --- 10. provenance completeness ---------------------------------------------

_PROVENANCE_KINDS: frozenset[str] = frozenset(member.value for member in ProvenanceKind)


def validate_provenance_completeness(subject: FoundryModel) -> ValidationReport:
    """Walk a payload for provenance envelopes and selection records.

    A structural walk over serialized data, so it applies to any contract without
    knowing which one it was handed, and applies equally to an object that never
    passed a model validator.
    """
    validator_id = claims.PROVENANCE_COMPLETENESS
    findings: list[ValidationFinding] = []
    data = _payload(subject)
    subject_id = str(data.get("work_item_id") or data.get("id") or type(subject).__name__)

    envelopes = 0
    decisions = 0

    def walk(node: Any, path: str) -> None:
        nonlocal envelopes, decisions
        if isinstance(node, dict):
            if _looks_like_provenance(node):
                envelopes += 1
                findings.extend(_provenance_envelope_findings(node, path, validator_id))
            if _looks_like_selection_record(node):
                decisions += 1
                findings.extend(_selection_record_findings(node, path, validator_id))
            for key in sorted(node):
                walk(node[key], f"{path}.{key}" if path else str(key))
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(data, "")

    if envelopes == 0 and decisions == 0:
        return ValidationReport(
            subject_kind=type(subject).__name__,
            subject_id=subject_id,
            findings=[
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject_id,
                    "payload carries no provenance envelope and no selection record; "
                    "why it says what it says is untraceable",
                )
            ],
        )

    return _report(
        type(subject).__name__,
        subject_id,
        findings,
        validator_id=validator_id,
        pass_subject=subject_id,
        pass_message=(
            f"{envelopes} provenance envelope(s) and {decisions} selection record(s) "
            "name a kind, a source, and a cause"
        ),
    )


def _looks_like_provenance(node: dict[str, Any]) -> bool:
    return "kind" in node and set(node) <= {"kind", "confidence", "source_ref"}


def _looks_like_selection_record(node: dict[str, Any]) -> bool:
    return {"component_kind", "component_id", "rationale"} <= set(node)


def _provenance_envelope_findings(
    node: dict[str, Any], path: str, validator_id: str
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    kind = node.get("kind")
    if kind not in _PROVENANCE_KINDS:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                path or "provenance",
                f"provenance kind {kind!r} is not a known kind",
            )
        )
        return findings
    if not node.get("source_ref"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                path or "provenance",
                f"{kind} provenance names no source_ref",
            )
        )
    if kind == ProvenanceKind.INFERRED.value and node.get("confidence") is None:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                path or "provenance",
                "inferred provenance carries no confidence; an inference without a "
                "stated confidence cannot be weighed against a declared fact",
            )
        )
    return findings


def _selection_record_findings(
    node: dict[str, Any], path: str, validator_id: str
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    component = f"{node.get('component_kind')}:{node.get('component_id')}"
    if not node.get("rationale"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                path or component,
                f"selection record for {component} carries no rationale",
            )
        )
    if not node.get("project_fact") and not node.get("policy_id"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                path or component,
                f"selection record for {component} cites neither a project fact nor a "
                "policy id; what caused the decision is unrecorded",
            )
        )
    return findings


# --- 11. ExecutionBundle completeness -----------------------------------------

_REQUIRED_BUNDLE_LISTS: tuple[str, ...] = (
    "scope",
    "acceptance_criteria",
    "required_evidence",
    "stop_conditions",
)


def validate_execution_bundle_completeness(bundle: ExecutionBundle) -> ValidationReport:
    """Check that the compiled bundle carries everything a run is entitled to."""
    validator_id = claims.EXECUTION_BUNDLE_COMPLETENESS
    findings: list[ValidationFinding] = []
    data = _payload(bundle)
    subject = str(data.get("work_item_id") or "unknown")

    for field in ("work_item_id", "run_id", "role_id", "objective", "schema_version"):
        if not data.get(field):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject,
                    f"execution bundle declares no {field}",
                )
            )

    for field in _REQUIRED_BUNDLE_LISTS:
        if not data.get(field):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject,
                    f"execution bundle carries an empty {field}",
                )
            )

    authority = data.get("authority")
    if not authority:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "execution bundle carries no compiled authority block",
            )
        )
    else:
        bundle_scope = sorted(data.get("write_scope") or [])
        authority_scope = sorted(authority.get("write_scope") or [])
        if bundle_scope != authority_scope:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"bundle write_scope {bundle_scope!r} disagrees with compiled "
                    f"authority write_scope {authority_scope!r}",
                )
            )

    task_toolkit = data.get("task_toolkit")
    if not task_toolkit:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "execution bundle carries no task toolkit",
            )
        )
    else:
        toolkit_capabilities = set(task_toolkit.get("capability_ids") or [])
        allowed = set(data.get("allowed_capabilities") or [])
        for escaped in sorted(allowed - toolkit_capabilities):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"allowed capability {escaped!r} is not in the task toolkit",
                )
            )
        toolkit_validators = set(task_toolkit.get("validator_ids") or [])
        for escaped in sorted(set(data.get("validator_ids") or []) - toolkit_validators):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"bundle validator {escaped!r} is not in the task toolkit",
                )
            )
        if task_toolkit.get("work_item_id") != data.get("work_item_id"):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"task toolkit was resolved for work item "
                    f"{task_toolkit.get('work_item_id')!r}, not {data.get('work_item_id')!r}",
                )
            )

    overlap = sorted(
        set(data.get("allowed_capabilities") or [])
        & set(data.get("forbidden_capabilities") or [])
    )
    if overlap:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.BLOCKED,
                subject,
                f"capabilities {overlap!r} are both allowed and forbidden",
            )
        )

    if not data.get("provenance"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "execution bundle carries no provenance",
            )
        )

    return _report(
        "execution-bundle",
        subject,
        findings,
        validator_id=validator_id,
        pass_subject=subject,
        pass_message=(
            "execution bundle names work, run and role, carries authority, toolkit, "
            "acceptance criteria, required evidence and stop conditions, and its "
            "capability sets are consistent"
        ),
    )


# --- 12. lifecycle separation -------------------------------------------------

# The three vocabularies must stay disjoint. Overlap would let one status field be
# read as any of the three, which is exactly the collapse this validator exists to
# prevent.
_TERMINAL_WORK_STATES = {"done"}
_IN_FLIGHT_EXECUTION_STATES = {"preparing", "running", "waiting", "retrying"}


def validate_lifecycle_separation(
    receipt: ExecutionReceipt,
    *,
    required_evidence_states: Iterable[EvidenceState] = (),
) -> ValidationReport:
    """Check that work, execution, and evidence stay three separate records.

    Reads the receipt as data so a receipt built by `model_construct` — bypassing the
    partition rule the model enforces — is examined on the same terms.
    """
    validator_id = claims.LIFECYCLE_SEPARATION
    findings: list[ValidationFinding] = []
    data = _payload(receipt)
    subject = f"{data.get('work_item_id')}/{data.get('run_id')}"

    lifecycle = data.get("work_lifecycle_state")
    execution = data.get("execution_state")
    attained = list(data.get("attained_evidence_states") or [])
    not_required = list(data.get("not_required_evidence_states") or [])

    if lifecycle is None:
        findings.append(
            _finding(
                validator_id, ValidationOutcome.MISSING, subject,
                "receipt records no work lifecycle state",
            )
        )
    if execution is None:
        findings.append(
            _finding(
                validator_id, ValidationOutcome.MISSING, subject,
                "receipt records no execution state",
            )
        )
    if not attained and not not_required:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "receipt records evidence only as a single collapsed state; which "
                "states are attained and which are exempt is unrecorded",
            )
        )

    for message in evidence_state_partition_conflicts(
        attained=[str(state) for state in attained],
        not_required=[str(state) for state in not_required],
    ):
        findings.append(_finding(validator_id, ValidationOutcome.BLOCKED, subject, message))

    required = [state.value for state in required_evidence_states]
    unmet = sorted(set(required) - set(attained) - set(not_required))

    if lifecycle in _TERMINAL_WORK_STATES:
        if unmet:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"work lifecycle is {lifecycle!r} while required evidence states "
                    f"{unmet!r} are neither attained nor declared not-required",
                )
            )
        if execution in _IN_FLIGHT_EXECUTION_STATES:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"work lifecycle is {lifecycle!r} while execution is still "
                    f"{execution!r}; a run in flight cannot have closed the work",
                )
            )

    return _report(
        "execution-receipt",
        subject,
        findings,
        validator_id=validator_id,
        pass_subject=subject,
        pass_message=(
            "work lifecycle, execution state, and evidence states are recorded "
            "separately and do not contradict each other"
        ),
    )


# --- 13. receipt completeness -------------------------------------------------


def validate_receipt_completeness(
    receipt: ExecutionReceipt,
    *,
    artifacts: Mapping[str, FoundryModel] | None = None,
) -> ValidationReport:
    """Check that the receipt names exact identities and records its own limits.

    Digest comparison is not an independent derivation and does not claim to be: it
    binds the receipt to the artifact handed in for comparison. See the catalog entry
    for what that is worth.
    """
    validator_id = claims.RECEIPT_COMPLETENESS
    findings: list[ValidationFinding] = []
    data = _payload(receipt)
    subject = f"{data.get('work_item_id')}/{data.get('run_id')}"

    for field in ("work_item_id", "run_id", "role_id", "started_at"):
        if not data.get(field):
            findings.append(
                _finding(
                    validator_id, ValidationOutcome.MISSING, subject,
                    f"receipt declares no {field}",
                )
            )

    for field in ("permission_profile_id", "budget_profile_id"):
        if not data.get(field):
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject,
                    f"receipt does not name the {field.replace('_', ' ')} the run was "
                    "granted",
                )
            )

    if not data.get("base_revision") and not data.get("candidate_revision"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "receipt names neither a base nor a candidate revision; what the run "
                "acted on is unrecorded",
            )
        )

    identities = data.get("artifact_identities") or []
    if not identities:
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "receipt names no configuration artifact identities",
            )
        )

    by_kind = {entry.get("kind"): entry for entry in identities}
    for kind, artifact in sorted((artifacts or {}).items()):
        entry = by_kind.get(kind)
        if entry is None:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject,
                    f"receipt names no identity for the {kind!r} the run used",
                )
            )
            continue
        declared = entry.get("digest")
        if not declared:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.MISSING,
                    subject,
                    f"receipt identity for {kind!r} carries no digest",
                )
            )
            continue
        # Recomputed through the independent layer, not through the function a
        # receipt producer uses to stamp the digest. Neutralizing the stamping
        # function must not neutralize this comparison.
        actual = contract_digest(artifact)
        if declared != actual:
            findings.append(
                _finding(
                    validator_id,
                    ValidationOutcome.BLOCKED,
                    subject,
                    f"receipt names {kind!r} digest {declared[:12]}…, but the artifact "
                    f"under review digests to {actual[:12]}…",
                )
            )

    if not data.get("findings") and not data.get("limitations"):
        findings.append(
            _finding(
                validator_id,
                ValidationOutcome.MISSING,
                subject,
                "receipt records neither findings nor limitations; a run that proved "
                "everything and left nothing open has to say so explicitly",
            )
        )

    for index, finding_data in enumerate(data.get("findings") or []):
        for message in finding_obligation_violations(
            finding_data,
            label=str(finding_data.get("id", f"#{index}")),
        ):
            findings.append(
                _finding(validator_id, ValidationOutcome.BLOCKED, subject, message)
            )

    budget = data.get("budget")
    if budget:
        pairs = (
            ("retries_used", "max_retry_budget"),
            ("parallel_runs_peak", "max_parallel_runs"),
            ("tokens_used", "token_budget"),
        )
        for used_field, limit_field in pairs:
            used = budget.get(used_field)
            limit = budget.get(limit_field)
            if used is not None and limit is not None and used > limit:
                findings.append(
                    _finding(
                        validator_id,
                        ValidationOutcome.BLOCKED,
                        subject,
                        f"{used_field} {used} exceeds {limit_field} {limit}",
                    )
                )

    return _report(
        "execution-receipt",
        subject,
        findings,
        validator_id=validator_id,
        pass_subject=subject,
        pass_message=(
            "receipt names exact work, run, role, revision, profile and artifact "
            "identities, and records its findings and limitations"
        ),
    )
