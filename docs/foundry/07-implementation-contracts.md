# Implementation Contracts

## 1. Purpose

This document defines the boundary between the architecture/specification layer and the next code implementation layer.

The implementation goal is not to generate more hand-maintained Markdown. It is to create typed models, registries, resolvers, compilers, validators, and adapters that can produce concise agent-facing artifacts from canonical structured data.

## 2. What remains human-readable

Markdown should continue to explain:

- architecture intent and rationale
- governance semantics
- project-intake semantics
- work-decomposition principles
- interaction vocabulary
- toolkit composition rules
- evidence semantics
- migration/adoption guidance

These documents answer why the system behaves the way it does.

## 3. What becomes machine-readable

Recommended first-class objects:

```text
ProjectIntake
ProjectObservation
ReadinessFinding
AdoptionPlan
ProjectManifest
PolicyRule / PolicyRef
WorkObjective
WorkPackage
WorkItemContract
DependencySpec
RoleContract
CapabilitySpec
SkillSpec
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

The exact storage format can be YAML/JSON/TOML plus typed application models, but every mutable concept should have one canonical owner.

## 4. Proposed package boundaries

```text
src/agent_foundry/
├─ models/          # typed contracts / schemas
├─ inspect/         # repository/system inventory and observations
├─ classify/        # project classification / readiness
├─ adopt/           # greenfield bootstrap + brownfield retrofit planning
├─ work/            # work hierarchy, decomposition, tracker-neutral contracts
├─ registry/        # roles, skills, workflows, tools, integrations, validators
├─ policy/          # authority, inheritance, trust, filtering, budgets
├─ resolve/         # Project Toolkit / Task Toolkit / compatibility
├─ compile/         # Work Item + context → Execution Bundle
├─ render/          # Markdown and provider/tool-specific projections
├─ integrations/    # tracker, repository, MCP/API, credential-provider adapters
├─ validate/        # schema, policy, work, toolkit, graph, evidence validators
├─ reconcile/       # tracker/repository/runtime state reconciliation
└─ runtime/         # later dispatch / observe / retry lifecycle
```

This is a target architecture, not a requirement to create every package in the first coding change.

## 5. Project-side output

A project managed by Foundry may eventually contain:

```text
AGENTS.md

docs/ai/
├─ PROJECT_AGENT_CONSTITUTION.md
└─ project-context.md

.foundry/
├─ project.yaml
├─ toolkit.lock.yaml
├─ adoption.yaml          # optional for brownfield migration
├─ profiles/
├─ integrations.yaml      # declarations + SecretRefs, never raw secrets
└─ local-registry/        # optional project-specific extensions
```

Important ownership:

```text
project.yaml
= declared/confirmed project characteristics and authority inputs

toolkit.lock.yaml
= resolved/pinned operational capability set

integrations.yaml
= desired integration declarations and credential references

credential provider / environment
= actual secret values

generated Markdown
= agent/human-readable projection, not an independently edited truth source
```

## 6. Work-tracker boundary

Foundry should define its own tracker-neutral work model and adapt it to external trackers rather than copying one product's hierarchy into the core.

Core hierarchy:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

Tracker adapters map these semantics to available initiatives, projects, epics, issues, stories, tasks, or subtasks.

The runtime should maintain Execution Run and evidence state separately from tracker lifecycle state.

## 7. Initial CLI direction

A useful CLI can evolve toward:

```text
agent-foundry inspect
# inventory existing repository/system and integrations

agent-foundry classify
# propose/validate Project Manifest and readiness findings

agent-foundry adopt
# generate greenfield bootstrap or brownfield retrofit plan

agent-foundry work plan
# propose causal work hierarchy/dependencies from an objective or adoption gap

agent-foundry resolve
# resolve Project Toolkit and lock

agent-foundry integration check
# validate declared integrations, SecretRefs, auth/health without exposing secrets

agent-foundry compile
# compile one Work Item into Task Toolkit + Execution Bundle

agent-foundry render
# render concise agent-facing Markdown/adapters

agent-foundry validate
# validate manifest, work graph, toolkit, bundle, evidence

agent-foundry reconcile
# compare tracker/repository/runtime evidence and produce state updates/receipt
```

External mutation remains preview-first and explicit-apply unless project policy grants narrower automatic authority.

## 8. Recommended implementation sequence

### Phase A — core typed contracts

Implement and test:

- Project Manifest
- Work Item Contract
- Role/Capability metadata
- IntegrationSpec / SecretRef
- Toolkit Resolution / Lock
- Execution Bundle

Goal: deterministic parse/validate/round-trip without live agent execution.

### Phase B — intake and brownfield inspection

Implement a small repository inspector that can collect:

- existing instructions/rules
- package/tooling metadata
- test/CI entrypoints
- repository structure
- declared integrations
- runtime/deploy hints when observable

Output observed facts and readiness findings without rewriting the project.

### Phase C — work decomposition model

Implement:

- Objective / Work Package / Work Item schemas
- dependency graph validation
- causal-decomposition heuristics
- detection of mega-items, mixed authority, unverifiable acceptance, and ownership collisions

Keep the first tracker adapter read-only or preview-first.

### Phase D — registry and resolver

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
- evidence-contract

Goal: Project Manifest + Work Item resolve reproducibly to Project Toolkit and Task Toolkit.

### Phase E — integration configuration and health

Implement:

- IntegrationSpec parsing
- SecretRef validation
- no-secret-in-config linting
- integration state model (`DESIRED → AUTHENTICATED → AUTHORIZED → HEALTHY`)
- one tracker/repository adapter pair first

Do not build a secret store. Consume environment/keychain/managed-connection/vault-style providers through interfaces.

### Phase F — Markdown rendering and task compiler

Render:

- project/adoption summary
- Work Item brief
- role-specific Execution Bundle
- handoff/evidence summary

Goal: structured canonical inputs generate concise `.md` artifacts suitable for existing agent CLIs and Skills.

### Phase G — reconciliation and execution adapters

Add:

- current tracker/repository truth acquisition
- evidence ingestion
- state reconciliation
- provider-specific execution adapters
- bounded retry/escalation

Long-running orchestration comes after the compiler and evidence contracts are stable.

## 9. First practical vertical slice

The most useful first end-to-end slice is now:

```text
Input
- an existing or sample repository
- a small project declaration
- one objective/work item
- optional generic integration declarations using SecretRefs

Inspect
- collect observed project facts

Classify
- produce/validate Project Manifest + readiness findings

Resolve
- Project Toolkit + lock

Work
- validate one causal Work Item

Compile
- Task Toolkit + Execution Bundle

Render
- concise role-specific Markdown

Validate
- reject forbidden capability
- reject raw secrets
- reject missing integration health
- reject invalid work decomposition
- reject missing evidence requirements
- reject invalid builder/reviewer identity
```

This proves that Foundry can retrofit or bootstrap an AI-native execution contract without requiring a brand-new project.

## 10. Version and compatibility contract

Version at least:

```text
foundry schema
Project Manifest
Work Item schema
Toolkit lock
Capability/Skill/Workflow metadata
Integration adapter
Execution Bundle
Evidence/Receipt schema
```

Compatibility errors should be explicit. Existing project behavior must not silently change when the global registry or Foundry implementation updates.

## 11. Public implementation boundary

The core package and public documentation must be self-contained and generic.

Avoid:

- dependencies on private repositories or unpublished policy sources
- hard-coded personal project names or filesystem paths
- raw credentials or real external-system identifiers in examples
- provider-specific assumptions in core models

Examples should use synthetic projects, synthetic Work Item IDs, and generic integrations.

## 12. Definition of the next milestone

The next milestone should prove:

> Given either a new project description or an existing repository, Agent Foundry can inspect and classify the operating environment, express a bounded causal Work Item, resolve a pinned least-capability toolkit with safe integration references, and generate a validated concise agent-facing execution package from structured canonical data.

That is the point where the repository moves from operating philosophy into a practical project-to-agent compiler.