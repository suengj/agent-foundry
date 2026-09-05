"""Shared enums, identifier types, and small value objects."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agent_foundry.models.base import FoundryModel


class ProvenanceKind(StrEnum):
    OBSERVED = "observed"
    DECLARED = "declared"
    INFERRED = "inferred"
    NORMATIVE = "normative"


class Provenance(FoundryModel):
    """Reusable provenance envelope for observations and findings."""

    kind: ProvenanceKind
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_ref: str | None = None


class ProfileResolution(StrEnum):
    """How a descriptive profile dimension stands after synthesis.

    Unknown and conflicted are first-class outcomes, not error states: a dimension
    with no evidence must not be reported as settled, and two sources that disagree
    must not be collapsed into whichever was read last.
    """

    RESOLVED = "resolved"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class AdoptionAction(StrEnum):
    KEEP = "KEEP"
    CONSOLIDATE = "CONSOLIDATE"
    WRAP = "WRAP"
    HARDEN = "HARDEN"
    MIGRATE = "MIGRATE"
    DEFER = "DEFER"
    BLOCK = "BLOCK"


class AdoptionChangeStatus(StrEnum):
    """Lifecycle status for an adoption change-set entry."""

    PROPOSED = "proposed"
    AUTO_APPLICABLE = "auto-applicable"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class SecretProvider(StrEnum):
    """Credential reference schemes from docs/foundry/04 §8."""

    ENV = "env"
    OS_KEYCHAIN = "os-keychain"
    MANAGED = "managed"
    VAULT = "vault"
    WORKLOAD_IDENTITY = "workload-identity"
    CI_SECRET = "ci-secret"


class IntegrationHealthState(StrEnum):
    DESIRED = "desired"
    AVAILABLE = "available"
    CONFIGURED = "configured"
    AUTHENTICATED = "authenticated"
    AUTHORIZED = "authorized"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class IntegrationKind(StrEnum):
    INTEGRATION = "integration"


class IntegrationTransport(StrEnum):
    MCP = "mcp"
    API = "api"
    CLI = "cli"
    LOCAL_SERVICE = "local-service"


class IntegrationAuthMethod(StrEnum):
    """Auth methods documented in docs/foundry/04 §7, §8, and §9."""

    OAUTH = "oauth"
    TOKEN = "token"
    DELEGATED_IDENTITY = "delegated-identity"


class DependencyRelation(StrEnum):
    REQUIRES = "requires"
    BLOCKS = "blocks"
    SUPERSEDES = "supersedes"
    VALIDATES = "validates"
    APPLIES_AFTER = "applies-after"
    DISCOVERED_BY = "discovered-by"


class PrimaryWorkMode(StrEnum):
    BUILD = "build"
    ANALYZE = "analyze"
    RESEARCH = "research"
    GENERATE = "generate"
    OPERATE = "operate"
    COORDINATE = "coordinate"
    MONITOR = "monitor"


class PrimaryArtifactState(StrEnum):
    CODE = "code"
    DATA = "data"
    MODEL = "model"
    DOCUMENT = "document"
    DECISION = "decision"
    EXTERNAL_STATE = "external-state"
    RUNTIME_STATE = "runtime-state"


class Statefulness(StrEnum):
    STATELESS = "stateless"
    LOCAL = "local"
    PERSISTENT_INTERNAL = "persistent-internal"
    PERSISTENT_SHARED_EXTERNAL = "persistent-shared-external"


class ExternalEffectClass(StrEnum):
    READ_ONLY = "read-only"
    REPOSITORY_WRITE = "repository-write"
    SHARED_SERVICE_WRITE = "shared-service-write"
    DATA_MUTATION = "data-mutation"
    RUNTIME_MUTATION = "runtime-mutation"
    PUBLICATION = "publication"


class Reversibility(StrEnum):
    TRIVIAL = "trivial"
    VERSIONED = "versioned"
    ROLLBACK_REQUIRED = "rollback-required"
    PARTIAL = "partial"
    EFFECTIVELY_IRREVERSIBLE = "effectively-irreversible"


class Autonomy(StrEnum):
    SUGGEST = "suggest"
    PREPARE = "prepare"
    ISOLATED_EXECUTE = "isolated-execute"
    BOUNDED_EXTERNAL_WRITE = "bounded-external-write"
    APPROVED_APPLY = "approved-apply"
    CONTINUOUS_OPERATION = "continuous-operation"


class ConsequenceClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AssuranceMode(StrEnum):
    DETERMINISTIC_TESTS = "deterministic-tests"
    STATISTICAL = "statistical"
    INDEPENDENT_REVIEW = "independent-review"
    SOURCE_EVIDENCE = "source-evidence"
    RUNTIME_READBACK = "runtime-readback"
    HUMAN_ACCEPTANCE = "human-acceptance"


class Ambiguity(StrEnum):
    PROCEDURAL = "procedural"
    BOUNDED_JUDGMENT = "bounded-judgment"
    DESIGN_TRADE_OFF = "design-trade-off"
    EXPLORATORY = "exploratory"


class AccessSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET_PRIVILEGED = "secret-privileged"


class TemporalMode(StrEnum):
    ONE_SHOT = "one-shot"
    INTERACTIVE = "interactive"
    BATCH = "batch"
    LONG_RUNNING = "long-running"
    CONTINUOUS = "continuous"


class Concurrency(StrEnum):
    SINGLE_WRITER = "single-writer"
    ISOLATED_PARALLEL_LANES = "isolated-parallel-lanes"
    COORDINATED_GRAPH = "coordinated-graph"


class AuthorityRequirement(StrEnum):
    EXPLICIT_AUTHORITY = "explicit-authority"
    BOUNDED_POLICY = "bounded-policy"
    NONE = "none"


class WorkClass(StrEnum):
    BASELINE = "BASELINE"
    CAPABILITY = "CAPABILITY"
    RESIDUAL_HARDENING = "RESIDUAL_HARDENING"
    INCIDENT = "INCIDENT"
    DISCOVERY = "DISCOVERY"
    ADOPTION = "ADOPTION"
    CONTRACT_AMENDMENT = "CONTRACT_AMENDMENT"


class IntakeMode(StrEnum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class MessageType(StrEnum):
    REQUEST = "REQUEST"
    DELEGATION = "DELEGATION"
    HANDOFF = "HANDOFF"
    EVIDENCE = "EVIDENCE"
    DECISION = "DECISION"
    REJECTION = "REJECTION"
    BLOCKER = "BLOCKER"
    ESCALATION = "ESCALATION"
    STATE_UPDATE = "STATE_UPDATE"


class ReviewOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class WorkLifecycleState(StrEnum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    IN_REVIEW = "in-review"
    DONE = "done"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


class ExecutionState(StrEnum):
    UNCLAIMED = "unclaimed"
    PREPARING = "preparing"
    RUNNING = "running"
    WAITING = "waiting"
    RETRYING = "retrying"
    ESCALATED = "escalated"
    STOPPED = "stopped"


class EvidenceState(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    VALIDATED = "VALIDATED"
    REVIEWED = "REVIEWED"
    MERGED_INTEGRATED = "MERGED_INTEGRATED"
    SYSTEM_VERIFIED = "SYSTEM_VERIFIED"
    RUNTIME_APPLIED = "RUNTIME_APPLIED"
    RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
    USER_ACCEPTED = "USER_ACCEPTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class EvidenceClass(StrEnum):
    """Evidence types from docs/foundry/06 §3.

    A typed class is what a required-evidence check can be satisfied by. Untyped
    evidence (an `EvidenceItem` carrying only a free-form `kind`) deliberately
    satisfies nothing: unrecognised is not the same as proven.
    """

    REPOSITORY_REVISION = "repository-revision"
    DETERMINISTIC_TEST = "deterministic-test"
    STATIC_ANALYSIS = "static-analysis"
    CONTRACT_VALIDATION = "contract-validation"
    REPRODUCIBLE_CALCULATION = "reproducible-calculation"
    STATISTICAL_EVALUATION = "statistical-evaluation"
    INDEPENDENT_REVIEW = "independent-review"
    INTEGRATION_PROOF = "integration-proof"
    MERGED_IDENTITY = "merged-identity"
    RUNTIME_READBACK = "runtime-readback"
    HUMAN_ACCEPTANCE = "human-acceptance"


class EvidenceResult(StrEnum):
    """Outcome an evidence artifact reports.

    `NOT_OBSERVED` exists so that "we did not look" is recordable as a value rather
    than expressed by omitting the item, which would read as a pass by default.
    """

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_OBSERVED = "not-observed"


class ValidationOutcome(StrEnum):
    """Outcome vocabulary shared by validation and reconciliation.

    There is no single boolean here on purpose. `MISSING` is what absent evidence
    resolves to; it never collapses into `PASS`, and `NOT_REQUIRED` must be
    declared rather than inferred from the absence of a requirement.
    """

    PASS = "PASS"
    NOT_REQUIRED = "NOT_REQUIRED"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class FindingDisposition(StrEnum):
    """Finding disposition from docs/foundry/06 §9."""

    BLOCKER = "BLOCKER"
    RESIDUAL = "RESIDUAL"
    HYPOTHESIS = "HYPOTHESIS"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class FailureCategory(StrEnum):
    """Repeated-failure classes for later repair logic.

    `UNKNOWN` is a first-class answer. A signal that does not structurally support a
    category returns `UNKNOWN` rather than the closest-looking guess.
    """

    CONTRACT = "contract"
    CONTEXT = "context"
    PERMISSION = "permission"
    TOOL = "tool"
    HARNESS = "harness"
    UNKNOWN = "unknown"


class StateAuthority(StrEnum):
    """Which system is authoritative for a piece of state (docs/foundry/06 §7)."""

    TRACKER = "tracker"
    REPOSITORY = "repository"
    RUNTIME = "runtime"
    FOUNDRY = "foundry"


class ReconciliationDimension(StrEnum):
    """Axis along which declared intent and observed state are compared."""

    IDENTITY_LINKAGE = "identity-linkage"
    WORK_LIFECYCLE = "work-lifecycle"
    EVIDENCE_STATE = "evidence-state"
    INTEGRATION_STATE = "integration-state"
    RUNTIME_STATE = "runtime-state"
    AUTHORITY = "authority"
