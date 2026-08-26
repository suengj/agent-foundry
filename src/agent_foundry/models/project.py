"""Project intake, observation, readiness, and adoption contracts."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract
from agent_foundry.models.common import (
    AccessSensitivity,
    AdoptionAction,
    AdoptionChangeStatus,
    Ambiguity,
    AssuranceMode,
    AuthorityRequirement,
    Autonomy,
    Concurrency,
    ConsequenceClass,
    ExternalEffectClass,
    IntakeMode,
    PrimaryArtifactState,
    PrimaryWorkMode,
    Provenance,
    Reversibility,
    Statefulness,
    TemporalMode,
)


class ProjectObservation(FoundryModel):
    """Observed or declared fact with provenance."""

    subject: str
    content: str
    provenance: Provenance


class ClassificationFinding(FoundryModel):
    """Proposed classification field candidate — evidence, not synthesized profile."""

    dimension: str
    value: str | None = None
    reason: str | None = None
    provenance: Provenance
    evidence_refs: list[str] = Field(default_factory=list)


class ConventionSpec(FoundryModel):
    """Locally discovered convention with source evidence and confidence."""

    subject: str
    pattern: str
    source_ref: str
    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance


class ReadinessFinding(FoundryModel):
    """Readiness assessment finding."""

    dimension: str
    severity: ConsequenceClass
    message: str
    blocker: bool = False
    provenance: Provenance


class WorkModes(FoundryModel):
    primary: PrimaryWorkMode | None = None
    secondary: list[PrimaryWorkMode] = Field(default_factory=list)


class ProjectState(FoundryModel):
    persistence: Statefulness | None = None
    temporal_mode: TemporalMode | None = None


class ProjectImpact(FoundryModel):
    external_effect: ExternalEffectClass | None = None
    reversibility: Reversibility | None = None
    consequence: ConsequenceClass | None = None


class ProjectExecution(FoundryModel):
    autonomy: Autonomy | None = None
    ambiguity: Ambiguity | None = None
    concurrency: Concurrency | None = None


class ProjectAssurance(FoundryModel):
    required: list[AssuranceMode] = Field(default_factory=list)


class ProjectAccess(FoundryModel):
    sensitivity: AccessSensitivity | None = None


class ProjectAuthority(FoundryModel):
    """Repository bounds an owner grants to write-bearing work.

    This is the outer envelope compiled write authority is intersected against. It
    exists because a role's write scope cannot be guessed: a default of `src/, tests/`
    baked into the registry is a project-shape assumption, and every project whose
    changes land elsewhere compiled to a bundle that authorized nothing.

    Undeclared means no write is granted, not that any write is allowed. An owner who
    has not said which paths agents may touch has not granted write authority, and
    silence is not permission.
    """

    write_scope: list[str] = Field(default_factory=list)


class ProjectInfo(FoundryModel):
    name: str | None = None
    intake_mode: IntakeMode | None = None
    work_modes: WorkModes | None = None
    primary_artifact: PrimaryArtifactState | None = None


class AdoptionPlanItem(FoundryModel):
    target: str
    action: AdoptionAction
    rationale: str
    priority: int | None = None


class AdoptionEvidence(FoundryModel):
    """Evidence backing an adoption change — never silently normative."""

    summary: str
    provenance: Provenance
    evidence_refs: list[str] = Field(default_factory=list)
    verbatim: str | None = None


class AdoptionChangeItem(FoundryModel):
    """Typed adoption delta with authority and lifecycle metadata."""

    target: str
    action: AdoptionAction
    evidence: AdoptionEvidence
    authority_requirement: AuthorityRequirement
    status: AdoptionChangeStatus
    rationale: str | None = None
    priority: int | None = None


class AdoptionPlan(VersionedContract):
    """Brownfield retrofit plan skeleton — structure only."""

    project_name: str
    items: list[AdoptionPlanItem]


class AdoptionChangeSet(VersionedContract):
    """Explicit current → proposed adoption delta."""

    project_name: str | None = None
    intake_mode: IntakeMode | None = None
    changes: list[AdoptionChangeItem]


class AdoptionPlanResult(FoundryModel):
    """Synthesized manifest plus adoption change set from intake evidence."""

    manifest: ProjectManifest
    change_set: AdoptionChangeSet


class ProjectManifest(VersionedContract):
    """Durable machine-readable project characteristics."""

    project: ProjectInfo
    state: ProjectState
    impact: ProjectImpact
    execution: ProjectExecution
    assurance: ProjectAssurance
    access: ProjectAccess
    authority: ProjectAuthority = Field(default_factory=ProjectAuthority)
    observations: list[ProjectObservation] = Field(default_factory=list)
    readiness_findings: list[ReadinessFinding] = Field(default_factory=list)


class TraversalLimits(FoundryModel):
    """Documented traversal bounds applied during inspection."""

    max_depth: int
    max_entries: int
    max_file_bytes: int
    skipped_dir_names: list[str] = Field(default_factory=list)


class TraversalStats(FoundryModel):
    """Traversal accounting for bounded inspection.

    ``entries_skipped`` stays the total so existing consumers keep working, but a
    single total cannot tell a deliberate cache-directory skip from a containment
    refusal or from a subtree the OS refused to show. The per-reason counters carry
    that distinction, and ``entries_unobservable`` counts paths whose contents could
    not be read at all — unreadable directories (also counted in
    ``entries_skipped_unreadable``) plus files that were listed but not readable.
    """

    entries_visited: int
    entries_skipped: int
    entries_skipped_ignored_dir: int = 0
    entries_skipped_refused: int = 0
    entries_skipped_unreadable: int = 0
    entries_unobservable: int = 0
    depth_limit_reached: bool
    entry_limit_reached: bool
    limits: TraversalLimits


class ProjectIntake(VersionedContract):
    """Read-only project inspection output — evidence for later synthesis."""

    project_root: str
    repository_revision: str | None = None
    observations: list[ProjectObservation] = Field(default_factory=list)
    classification_findings: list[ClassificationFinding] = Field(default_factory=list)
    conventions: list[ConventionSpec] = Field(default_factory=list)
    readiness_findings: list[ReadinessFinding] = Field(default_factory=list)
    traversal_stats: TraversalStats
