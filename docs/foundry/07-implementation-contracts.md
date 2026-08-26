# Implementation Contracts

## 1. Purpose

This document defines the boundary between the architecture/specification layer and the code implementation layer.

The implementation goal is not to generate more hand-maintained Markdown. It is to create typed models, registries, resolvers, compilers, validators, adapters, and provenance-bearing outputs that can produce concise agent-facing artifacts from canonical structured data.

## 2. What remains human-readable

Markdown should continue to explain:

- architecture intent and rationale;
- governance semantics;
- project-intake semantics;
- work-decomposition principles;
- interaction vocabulary;
- toolkit composition rules;
- evidence semantics;
- migration/adoption guidance;
- benchmark-derived design choices and non-goals.

These documents answer why the system behaves the way it does.

## 3. What becomes machine-readable

Recommended first-class objects:

```text
ProjectIntake
ProjectObservation
ClassificationFinding
ConventionSpec
ReadinessFinding
ProjectProfile
AdoptionPlan
AdoptionChangeSet
ProjectManifest
PolicyRule / PolicyRef
WorkObjective
WorkPackage
WorkItemContract
DependencySpec
ExecutionRun
WorkspaceLease / WriteLease
RoleContract
CapabilitySpec
SkillSpec
ToolInterfaceProfile
WorkflowSpec
NodeSpec / EdgeSpec
PermissionProfile
BudgetProfile
IntegrationSpec
SecretRef
IntegrationHealth
ProviderProfile
ToolkitResolution
ToolkitLock
TaskToolkit
ExecutionBundle
InteractionMessage / Handoff
EvidenceBundle
ReviewDecision
ExecutionReceipt
LearningRecord
```

Not every object must land in one implementation issue. The list defines the intended durable model vocabulary.

Every mutable concept should have one canonical owner. Generated Markdown remains a projection.

## 4. Common provenance contract

Observed/inferred project facts should share a small provenance envelope where useful:

```yaml
key: runtime_mutation
value: true
source: observed        # observed | declared | inferred | confirmed
evidence:
  - deploy-config
confidence: 0.98
```

Design rules:

- absence of evidence is not positive evidence;
- unknown stays explicit;
- inferred facts may tighten controls;
- inferred facts may not silently widen authority;
- validation should be able to explain which evidence/policy led to a profile/toolkit decision.

## 5. Project Profile Synthesis

Make synthesis an explicit compiler stage rather than hiding it inside ad hoc classification.

```text
ProjectObservation
+ ClassificationFinding
+ ConventionSpec
+ ReadinessFinding
        ↓
Project Profile Synthesis
        ↓
ProjectProfile
```

A `ProjectProfile` can group:

```text
Operating Profile
Governance Profile
Work Profile
Role Profile
Interaction Profile
Evidence Profile
Integration Requirements
Toolkit Requirements
```

The exact internal schema may evolve, but downstream Toolkit resolution should consume structured profile/manifest facts rather than repeatedly reinterpret the raw repository.

## 6. Proposed package boundaries

```text
src/agent_foundry/
├─ models/          # typed contracts / schemas
├─ inspect/         # repository/system inventory, conventions and observations
├─ classify/        # classification findings / readiness / profile synthesis
├─ adopt/           # greenfield bootstrap + brownfield retrofit planning/change sets
├─ work/            # work hierarchy, decomposition, tracker-neutral contracts
├─ registry/        # roles, skills, workflows, tools, integrations, validators
├─ policy/          # invariants, declarative rules, trust, filtering, budgets
├─ resolve/         # Project Toolkit / Task Toolkit / compatibility / rationale
├─ compile/         # Work Item + profile/context → Execution Bundle
├─ render/          # Markdown and provider/tool-specific projections
├─ integrations/    # tracker, repository, MCP/API, credential-provider adapters
├─ validate/        # schema, policy, work, toolkit, graph, provenance, evidence validators
├─ reconcile/       # tracker/repository/runtime state reconciliation
└─ runtime/         # later dispatch / workspace lease / observe / retry lifecycle
```

This is a target architecture, not a requirement to create every package in the first coding change.

## 7. Project-side output

A project managed by Foundry may eventually contain:

```text
AGENTS.md

docs/ai/
├─ PROJECT_AGENT_CONSTITUTION.md
└─ project-context.md

.foundry/
├─ project.yaml
├─ profile.yaml            # generated/confirmed project operating profile
├─ toolkit.lock.yaml
├─ adoption.yaml           # optional for migration/retrofit state
├─ integrations.yaml       # declarations + SecretRefs, never raw secrets
├─ profiles/
└─ local-registry/         # optional project-specific extensions
```

Important ownership:

```text
project.yaml
= declared/confirmed project characteristics and authority inputs

profile.yaml / equivalent canonical object
= synthesized operating/work/role/evidence/integration requirements

toolkit.lock.yaml
= resolved/pinned operational capability set

adoption.yaml
= current vs proposed adoption changes and status when needed

integrations.yaml
= desired integration declarations and credential references

credential provider / environment
= actual secret values

generated Markdown
= agent/human-readable projection, not an independently edited truth source
```

The exact persisted files may be reduced if the same ownership can be represented more simply. Do not create files merely to mirror in-memory objects.

## 8. Work-tracker and runtime boundary

Foundry should define its own tracker-neutral work model and adapt it to external trackers rather than copying one product's hierarchy into the core.

Core hierarchy:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

Maintain the distinction:

```text
Work Item
≠ Execution Run
≠ Evidence state
```

Tracker adapters map work semantics to initiatives, projects, epics, issues, stories, tasks, or subtasks.

A future runtime may attach an isolated `WorkspaceLease`/`WriteLease` to an Execution Run. V0.1 can define the model without implementing a persistent scheduler.

## 9. Initial CLI direction

A useful CLI can evolve toward:

```text
agent-foundry inspect <project-path>
# inventory repository/system, conventions and integrations

agent-foundry classify <project-path>
# produce classification/readiness findings

agent-foundry profile <project-path>
# synthesize/validate ProjectProfile

agent-foundry adopt <project-path> --preview
# generate greenfield bootstrap or brownfield AdoptionChangeSet

agent-foundry adopt <project-path> --apply
# later: apply explicitly authorized project-local changes

agent-foundry work plan <objective>
# propose causal work hierarchy/dependencies

agent-foundry resolve <project-path>
# resolve Project Toolkit and lock, with rationale

agent-foundry integration check <project-path>
# validate IntegrationSpec/SecretRef/auth/health without exposing secrets

agent-foundry compile <work-item>
# compile one Work Item into Task Toolkit + Execution Bundle

agent-foundry render <execution-bundle>
# render concise agent-facing Markdown/adapters

agent-foundry validate <artifact>
# validate manifest/profile/work/toolkit/bundle/evidence

agent-foundry reconcile <project-path>
# compare tracker/repository/runtime evidence and propose state updates/receipt
```

External mutation remains preview-first and explicit-apply unless project policy grants narrower automatic authority.

## 10. MCP interface direction

MCP is an optional facade around Foundry Core:

```text
              Foundry Core
                  │
       ┌──────────┼──────────┐
       ↓          ↓          ↓
      CLI     Python API   MCP Server
```

Candidate MCP tools should map to the same Core functions used by CLI/API. Do not implement a second MCP-specific business logic path.

New MCP implementation should use explicit project-path parameters, resource URIs, or server configuration rather than depending on deprecated Roots.

Possible later MCP resources expose project profile/manifest/adoption/toolkit/work/current task as read-only structured views.

The MCP Tasks extension is optional future transport for long-running calls, not a V0.1 requirement.

## 11. Recommended implementation sequence

### Phase A - core typed contracts

Implement/test the smallest foundational model set required by downstream work:

- Project Manifest;
- provenance-bearing observation/classification primitives;
- ProjectProfile skeleton if it can be defined without premature over-modeling;
- Work Item Contract;
- Role/Capability metadata;
- IntegrationSpec / SecretRef;
- Toolkit Resolution / Lock;
- Execution Bundle.

Goal: deterministic parse/validate/round-trip without live agent execution.

If active implementation has already frozen an interface, do not destabilize it for non-foundational benchmark ideas. Record bounded follow-ups.

### Phase B - intake, convention discovery and brownfield inspection

Implement a small repository inspector that can collect:

- existing instructions/rules;
- package/tooling metadata;
- test/CI entrypoints;
- repository structure;
- declared integrations;
- runtime/deploy hints when observable;
- representative architectural/coding conventions worth recording.

Output evidence-bearing observations/findings without rewriting the project.

Do not document obvious framework defaults merely to fill a standards catalog.

### Phase C - Project Profile Synthesis and adoption planning

Implement:

- profile synthesis from structured findings;
- readiness interpretation with conservative authority;
- greenfield bootstrap plan;
- brownfield `AdoptionChangeSet` using KEEP / CONSOLIDATE / WRAP / HARDEN / MIGRATE / DEFER / BLOCK;
- explicit current truth vs proposed state.

### Phase D - work decomposition model

Implement:

- Objective / Work Package / Work Item schemas;
- dependency graph validation;
- causal-decomposition heuristics;
- detection of mega-items, mixed authority, unverifiable acceptance, and ownership collisions;
- clear Work Item vs Execution Run semantics.

Keep the first tracker adapter read-only or preview-first.

### Phase E - registry, declarative policy and resolver

Implement a deliberately small built-in registry:

Roles:
- manager
- explorer
- builder
- validator
- reviewer
- integrator
- runtime-verifier

Workflows:
- single-worker-validation
- builder-reviewer
- investigator-synthesis
- brownfield-retrofit

Skills:
- repository-inspection
- bounded-code-change
- deterministic-test
- independent-review

Validators:
- schema/preflight
- role-separation
- work-decomposition
- integration-health
- provenance/explanation
- evidence-contract

Add compact Skill trigger/relevance metadata and a minimal declarative policy representation. Avoid named-project-type branching.

Goal: ProjectProfile/Manifest + Work Item resolve reproducibly to Project Toolkit and Task Toolkit with explainable include/exclude rationale.

### Phase F - integration configuration and health

Implement:

- IntegrationSpec parsing;
- SecretRef validation;
- no-secret-in-config linting;
- integration state model (`DESIRED → AVAILABLE → CONFIGURED → AUTHENTICATED → AUTHORIZED → HEALTHY`);
- one tracker/repository adapter pair first;
- MCP adapter skeleton only after Core APIs are stable enough to expose.

Do not build a secret store. Consume environment/keychain/managed-connection/vault/workload-identity style providers through interfaces.

### Phase G - Markdown rendering and task compiler

Compile:

```text
ProjectProfile
+ applicable policy
+ relevant conventions
+ Work Item
+ Project Toolkit
+ fresh truth
        ↓
minimal Task Toolkit
+ role-specific Execution Bundle
+ provenance
```

Render concise agent-facing Markdown. Do not concatenate the whole project documentation tree.

A future `ToolInterfaceProfile` may configure normalized tool/feedback behavior, but V0.1 need not ship a custom ACI shell.

### Phase H - verification, reconciliation and execution adapters

Add:

- validation of classification/profile provenance;
- validation/explanation of toolkit selection;
- current tracker/repository truth acquisition;
- evidence ingestion;
- state reconciliation;
- provider-specific execution adapters;
- bounded retry/escalation.

Long-running orchestration comes after compiler and evidence contracts are stable.

## 12. First practical vertical slice

The useful end-to-end slice is:

```text
Input
- an existing or sample repository
- a small project declaration
- one objective/work item
- optional generic integration declarations using SecretRefs

Inspect
- collect observed project facts + conventions

Classify / Profile
- produce/validate findings, readiness and ProjectProfile

Adopt
- produce preview-only AdoptionChangeSet

Resolve
- Project Toolkit + lock + selection rationale

Work
- validate one causal Work Item

Compile
- Task Toolkit + Execution Bundle + provenance

Render
- concise role-specific Markdown

Validate
- reject forbidden capability
- reject raw secrets
- reject missing integration health
- reject invalid work decomposition
- reject missing evidence requirements
- reject invalid builder/reviewer identity
- reject unsupported version
```

This proves that Foundry can retrofit or bootstrap an AI-native execution contract without requiring a brand-new project.

## 13. Version and compatibility contract

Version at least:

```text
Foundry schema
Project Manifest / Profile
Work Item schema
Toolkit lock
Capability/Skill/Workflow metadata
Integration adapter
Execution Bundle
Evidence/Receipt schema
```

Compatibility errors should be explicit. Existing project behavior must not silently change when the global registry or Foundry implementation updates.

## 14. Public implementation boundary

The core package and public documentation must be self-contained and generic.

Avoid:

- dependencies on private repositories or unpublished policy sources;
- hard-coded personal project names or filesystem paths;
- raw credentials or real external-system identifiers in examples;
- provider-specific assumptions in core models;
- project-type condition trees standing in for composable policy predicates.

Examples should use synthetic projects, synthetic Work Item IDs, and generic integrations.

## 15. Benchmark learning during implementation

Benchmark-derived improvements should be integrated conservatively.

```text
benchmark finding
→ design delta
→ determine whether foundational
→ current issue acceptance update OR bounded follow-up
→ implementation evidence
→ retain / revise / reject
```

The current V0.1 work graph should not be constantly reset by benchmark review.

See `08-benchmarks-and-evolution.md` for the source projects and issue-level mapping.

## 16. Definition of the V0.1 milestone

V0.1 should prove:

> Given either a new project description or an existing repository, Agent Foundry can inspect and profile the operating environment, express a bounded causal Work Item, resolve a pinned least-capability toolkit with safe integration references and explainable selection, and generate a validated concise agent-facing execution package from structured canonical data.

That is the point where the repository moves from operating philosophy into a practical project-to-agent compiler.
