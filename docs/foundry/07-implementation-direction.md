# Implementation Direction

## 1. Purpose

This document defines the boundary between the current documentation/specification phase and the next code implementation phase.

The next step is not to generate more static Markdown manually. The next step is to implement the minimal data model and compiler pipeline that can resolve a project-specific toolkit and render agent-facing artifacts from canonical configuration.

## 2. What should remain documentation

Human-readable Markdown should continue to own:

- architecture intent
- governance rationale
- conceptual definitions
- authority model
- project classification semantics
- toolkit composition principles
- interaction and evidence semantics
- implementation boundaries

These documents explain why the system behaves as it does.

## 3. What should become machine-readable

The code phase should introduce structured representations for the items that need deterministic resolution, validation or generation.

Recommended first objects:

```text
ProjectManifest
PolicyRule / PolicyRef
RoleContract
CapabilitySpec
SkillSpec
WorkflowSpec
PermissionProfile
ToolkitResolution
ToolkitLock
TaskContract
ExecutionBundle
Handoff
EvidenceBundle
ReviewDecision
ExecutionReceipt
```

The exact storage format may be YAML/JSON/TOML plus Python models; the canonical ownership rule should be decided before generators are added.

## 4. Proposed package boundaries

A target structure for the implementation phase:

```text
src/agent_foundry/
├─ models/          # typed contracts / schemas
├─ classify/        # project classification and manifest synthesis
├─ registry/        # roles, skills, workflows, tools, validators, providers
├─ policy/          # inheritance, filtering, conflict/authority checks
├─ resolve/         # project toolkit + task toolkit resolution
├─ compile/         # context and Execution Bundle compilation
├─ render/          # Markdown/provider-specific projection
├─ adapters/        # Codex / Claude / Cursor / other thin adapters
├─ validate/        # preflight, schema, evidence and graph validators
└─ runtime/         # later dispatch/observe/retry integration
```

This is a target boundary, not a requirement to create every package in the first coding issue.

## 5. Proposed project-side output

A project bootstrapped by Foundry may eventually contain:

```text
AGENTS.md

docs/ai/
├─ PROJECT_AGENT_CONSTITUTION.md
└─ project-context.md

.foundry/
├─ project.yaml
├─ toolkit.lock.yaml
├─ profiles/
└─ local-registry/       # optional project-only extensions
```

The important distinction is:

```text
project.yaml
= declared / classified project characteristics and authority inputs

toolkit.lock.yaml
= resolved/pinned operational capability set

Generated Markdown
= human/agent-readable projection, not an independently edited second source
```

## 6. Initial CLI direction

A minimal useful CLI can evolve toward:

```text
agent-foundry inspect       # inspect repository/system inputs
agent-foundry classify      # propose/validate Project Manifest
agent-foundry resolve       # resolve Project Toolkit + lock
agent-foundry compile       # compile one Task into Execution Bundle
agent-foundry render        # render Markdown/provider adapter view
agent-foundry validate      # validate manifest/toolkit/bundle/evidence
```

External mutation should remain preview-first and explicit-apply, consistent with the existing product boundary.

## 7. Recommended implementation sequence

### Phase A — typed contracts

Implement and test:

- Project Manifest
- Role/Capability metadata
- Toolkit Resolution / Lock
- Task Contract
- Execution Bundle

Goal: deterministic parse/validate/round-trip with no live agent execution.

### Phase B — registry and resolver

Implement:

- small built-in role registry
- small Skill/workflow metadata registry
- deterministic capability matching
- hard policy filtering
- completeness/conflict validation

Goal: a Project Manifest resolves to a reproducible Project Toolkit.

### Phase C — Markdown rendering

Implement renderers for:

- project toolkit summary
- role-specific execution brief
- task execution bundle
- handoff/evidence summary

Goal: canonical config generates concise `.md` artifacts rather than humans maintaining parallel documents.

### Phase D — task-time compiler

Integrate:

- task input
- current GitHub/project truth
- applicable policy/context selection
- Task Toolkit minimization
- provider-neutral Execution Bundle

Goal: one task produces a bounded execution package.

### Phase E — execution adapters

Add one or two adapters first, then expand:

- provider-specific entrypoint/rule loading
- dispatch input rendering
- output capture
- typed handoff/evidence ingestion

The core compiler should remain provider-neutral.

### Phase F — runtime and reconciliation

Later integrate:

- Linear Work SSOT read/reconcile
- GitHub implementation evidence
- runtime/external read-back
- Execution Receipt
- bounded retry / escalation

## 8. Keep the first registry intentionally small

Do not start by building a marketplace-sized catalog.

A practical first registry can contain:

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

Skills:
- repository-inspection
- bounded-code-change
- deterministic-test
- independent-review

Validators:
- schema/preflight
- repository/test evidence
- role-separation

The value of the first implementation is proving the composition mechanism, not catalog breadth.

## 9. AI Dev Playbook as upstream source

Do not copy the Playbook into code constants line by line.

Use it as the durable design authority for reusable concepts such as:

- federated/pinned constitution
- normative vs factual authority
- static vs dynamic harness
- role-first provider routing
- single writer / reviewer independence
- Node/Edge contracts
- observe vs verify
- evidence-first completion
- provider/tool/MCP governance

Foundry should encode the operational portions as explicit schemas, validators and resolver behavior while retaining a pinned reference to the upstream Playbook.

## 10. Key implementation test

A useful vertical slice is:

```text
Input
- small sample Project Manifest
- small built-in Registry
- one Task Contract

Resolve
- Project Toolkit
- Task Toolkit

Compile
- Execution Bundle

Render
- concise role-specific Markdown

Validate
- reject forbidden capability, missing evidence requirement,
  or invalid builder/reviewer identity
```

If that works deterministically, the system has crossed from documentation into a real Foundry.

## 11. Definition of the next milestone

The next implementation milestone should prove:

> Given an abstract, domain-neutral Project Manifest and a bounded Task Contract, Agent Foundry can resolve a pinned minimal toolkit and generate a validated, concise agent-facing Markdown execution package from structured canonical data.

Agent dispatch, long-running orchestration and broad external integration can come after that vertical slice is stable.
