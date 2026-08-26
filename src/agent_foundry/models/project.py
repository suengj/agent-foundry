"""Project intake, observation, readiness, and adoption contracts."""

from __future__ import annotations

from pydantic import Field

from agent_foundry.models.base import FoundryModel, VersionedContract
from agent_foundry.models.common import (
    AccessSensitivity,
    AdoptionAction,
    Ambiguity,
    AssuranceMode,
    Autonomy,
    Concurrency,
    ConsequenceClass,
    ExternalEffectClass,
    IntakeMode,
    PrimaryArtifactState,
    PrimaryWorkMode,
    ProvenanceKind,
    Reversibility,
    Statefulness,
    TemporalMode,
)


class ProjectObservation(FoundryModel):
    """Observed or declared fact with provenance."""

    subject: str
    content: str
    provenance: ProvenanceKind
    source_ref: str | None = None


class ReadinessFinding(FoundryModel):
    """Readiness assessment finding."""

    dimension: str
    severity: str
    message: str
    blocker: bool = False


class WorkModes(FoundryModel):
    primary: PrimaryWorkMode
    secondary: list[PrimaryWorkMode] = Field(default_factory=list)


class ProjectState(FoundryModel):
    persistence: Statefulness
    temporal_mode: TemporalMode


class ProjectImpact(FoundryModel):
    external_effect: ExternalEffectClass
    reversibility: Reversibility
    consequence: ConsequenceClass


class ProjectExecution(FoundryModel):
    autonomy: Autonomy
    ambiguity: Ambiguity
    concurrency: Concurrency


class ProjectAssurance(FoundryModel):
    required: list[AssuranceMode]


class ProjectAccess(FoundryModel):
    sensitivity: AccessSensitivity


class ProjectInfo(FoundryModel):
    name: str
    intake_mode: IntakeMode
    work_modes: WorkModes
    primary_artifact: PrimaryArtifactState | None = None


class AdoptionPlanItem(FoundryModel):
    target: str
    action: AdoptionAction
    rationale: str
    priority: int | None = None


class AdoptionPlan(VersionedContract):
    """Brownfield retrofit plan skeleton — structure only."""

    project_name: str
    items: list[AdoptionPlanItem]


class ProjectManifest(VersionedContract):
    """Durable machine-readable project characteristics."""

    project: ProjectInfo
    state: ProjectState
    impact: ProjectImpact
    execution: ProjectExecution
    assurance: ProjectAssurance
    access: ProjectAccess
    observations: list[ProjectObservation] = Field(default_factory=list)
    readiness_findings: list[ReadinessFinding] = Field(default_factory=list)
