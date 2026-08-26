# Benchmarks, MCP Direction, and Design Evolution

## 1. Purpose

Agent Foundry should learn from systems that have already validated parts of the AI-native development stack without becoming a clone of any one of them.

This document records:

- relevant public benchmarks and related projects;
- the primitive each project has validated;
- the Foundry design delta derived from that evidence;
- areas where Foundry should remain intentionally different;
- MCP compatibility principles;
- how benchmark learning should influence implementation without destabilizing the current V0.1 work graph.

This document is an architectural reference, not a dependency list. Agent Foundry must remain self-contained and must not require these projects at runtime.

## 2. Benchmarking principle

Use benchmark projects to identify **validated primitives**, not to copy product boundaries.

```text
External project
→ validated primitive
→ Foundry design question
→ bounded design delta
→ implementation evidence
→ adopt / reject / defer
```

A benchmark does not override Foundry's own product boundary.

Changes should be adopted only when they improve at least one of:

- project understanding;
- brownfield safety;
- work decomposition quality;
- context relevance;
- capability/permission selection;
- execution reliability;
- explainability and evidence;
- interoperability.

## 3. Related projects

### 3.1 GitHub Spec Kit

Reference: <https://github.com/github/spec-kit>

Spec Kit validates a constitution-driven artifact lifecycle for spec-driven development. Its documented flow includes constitution, specification, clarification, planning, tasks, implementation, and convergence.

Useful primitives for Foundry:

- explicit artifact lifecycle;
- constitution/guardrail concept;
- provider/agent integration assets;
- spec-to-task discipline;
- existing-project guidance that warns against inventing unrealistic standards.

Foundry design delta:

- keep an explicit artifact lineage from observations/profile to work/toolkit/execution/evidence;
- ensure generated Work Items remain traceable to higher-level objectives and accepted project constraints;
- treat provider-specific files as render/adaptation outputs.

Intentional difference:

```text
Spec Kit
≈ structure what should be built

Agent Foundry
≈ first determine how agents may safely and effectively operate in this project,
  then compile bounded work/execution contracts
```

Foundry should not duplicate a complete feature-spec workflow when an external spec system can be used as a work/context input.

### 3.2 Agent OS

Reference: <https://github.com/buildermethods/agent-os>

Agent OS validates two especially relevant ideas:

1. discover conventions/standards from an existing codebase;
2. index those standards and inject only the relevant subset into current work.

Useful primitives for Foundry:

- codebase convention discovery;
- a cheap metadata/index surface before loading full standards;
- progressive disclosure;
- project standards as declarative knowledge rather than procedural Skills.

Foundry design delta:

Add explicit convention discovery to project intake:

```text
Repository samples
→ ConventionFinding
→ ConventionSpec / project standard index
→ relevance selection
→ Task context
```

Convention findings should include evidence/provenance/confidence and must not automatically become hard policy.

Example:

```yaml
key: db_access_boundary
value: service-layer-only
source: inferred
evidence:
  - src/services/example.py
  - src/repositories/example.py
confidence: 0.82
```

Intentional difference:

Agent Foundry generalizes beyond coding standards into:

- governance;
- authority;
- external effects;
- roles;
- permissions;
- integrations;
- evidence;
- work decomposition;
- execution contracts.

### 3.3 OpenSpec

Reference: <https://github.com/Fission-AI/OpenSpec>

OpenSpec is explicitly brownfield-oriented and models changes as deltas rather than requiring a complete up-front specification of an existing system.

Useful primitives for Foundry:

- current truth and proposed change are separate artifacts;
- incremental adoption over touched surfaces;
- one bounded change carries its proposal/design/tasks context;
- archive/applied history does not replace current truth.

Foundry design delta:

Make the adoption lifecycle explicit:

```text
Current Project Truth
→ AdoptionChangeSet
→ Proposed AI-native State
→ preview
→ applied state
→ read-back
```

`AdoptionChangeSet` should make changes auditable:

```yaml
changes:
  - target: agent-instructions
    action: CONSOLIDATE
    reason: duplicated rule surfaces

  - target: deployment
    action: KEEP
    reason: existing process already satisfies required controls
```

Intentional difference:

Foundry uses the delta concept for **project operating environment adoption**, not only behavior/spec changes.

### 3.4 OpenHands / OpenHands Extensions

References:

- <https://github.com/OpenHands/OpenHands>
- <https://github.com/OpenHands/extensions>

OpenHands validates reusable Skills/plugins, repository-local agent context, and progressive disclosure of Skill definitions.

Useful primitives for Foundry:

- Skills should be small and composable;
- a metadata/catalog surface should be cheap to inspect;
- full Skill instructions should load only after selection;
- public reusable Skills should avoid repo-local/private assumptions;
- integration metadata should have a canonical machine-readable owner.

Foundry design delta:

A Skill registry item should have:

```text
metadata / trigger / capabilities / compatibility
        ↓ selected
full procedure / instructions
```

Selection should depend on Project Profile + Work Item + Role rather than static project-type templates.

Intentional difference:

Foundry does not need to become a Skill runtime or marketplace. It should determine which capabilities a project/task requires and render or hand them to the chosen execution environment.

### 3.5 SWE-agent

Reference: <https://github.com/SWE-agent/SWE-agent>

SWE-agent validates the importance of the Agent-Computer Interface (ACI): tool design, concise file/search interfaces, feedback formatting, and immediate validation materially affect agent performance.

Useful primitives for Foundry:

- tools are not merely permission names; their interaction shape matters;
- concise feedback can be superior to dumping raw context;
- deterministic checks close to mutation improve reliability;
- agent-facing command/output contracts are part of the harness.

Foundry design delta:

Add `ToolInterfaceProfile` or equivalent metadata to the toolkit layer:

```text
capability
allowed operation
standard entrypoint
feedback format
automatic validator
write/external-effect boundary
```

V0.1 should model this surface before implementing a complete custom execution shell.

Intentional difference:

SWE-agent primarily executes tasks through a tuned computer interface. Foundry operates upstream: it configures the project, work, authority, toolkit, and interaction contract that a runner can consume.

### 3.6 OpenAI Symphony

References:

- <https://github.com/openai/symphony>
- <https://openai.com/index/open-source-codex-orchestration-symphony/>

Symphony validates issue-tracker-driven orchestration with isolated per-issue workspaces, bounded concurrency, retries, reconciliation, and persistent workspace/run state.

Useful primitives for Foundry:

- Work Item is not the same object as an Execution Run;
- tracker lifecycle state is not orchestrator runtime state;
- a run should have an isolated workspace/ownership boundary;
- retries/reconciliation require explicit runtime state;
- execution can finish at a handoff/review state rather than always `Done`.

Foundry design delta:

Preserve:

```text
Work Item
→ Execution Run
→ WorkspaceLease / WriteLease
→ Evidence / Handoff
```

A conceptual lease can record:

```yaml
work_item: WI-123
run_id: run-003
writer: builder-01
workspace: isolated
write_scope:
  - src/component/**
```

Intentional difference:

Symphony is an execution scheduler/orchestrator. Foundry should not rebuild it in V0.1.

A future deployment can reasonably compose:

```text
Agent Foundry
→ AI-native project configuration / work contracts
→ issue tracker
→ Symphony-like runtime
→ coding agents
```

### 3.7 Model Context Protocol (MCP)

References:

- <https://modelcontextprotocol.io/>
- <https://blog.modelcontextprotocol.io/posts/2026-07-28/>

MCP validates a standardized interface for agent-accessible tools/resources and now provides an extension model for long-running Tasks.

Useful primitives for Foundry:

- typed tool input/output contracts;
- resource URIs for structured context;
- authorization-aware external integration;
- optional Tasks extension for long-running operations.

Foundry design delta:

Expose Foundry Core through an optional MCP facade while keeping the core protocol-independent.

```text
              Foundry Core
                  │
       ┌──────────┼──────────┐
       ↓          ↓          ↓
      CLI     Python API   MCP Server
```

Candidate MCP tools:

```text
foundry.inspect
foundry.profile
foundry.adopt_preview
foundry.adopt_apply
foundry.work_plan
foundry.resolve_toolkit
foundry.integration_check
foundry.compile
foundry.validate
foundry.reconcile
```

Candidate resources:

```text
foundry://project/profile
foundry://project/manifest
foundry://project/adoption
foundry://project/toolkit
foundry://project/work
foundry://task/current
```

MCP `2026-07-28` deprecated Roots for new implementations. Therefore Foundry must not make `roots/list` its project-selection contract. Prefer:

- explicit project path tool parameters;
- project resource URIs;
- server configuration;
- environment-specific adapter configuration.

All paths must still pass Foundry-side canonicalization, containment, and permission checks.

The MCP Tasks extension may later represent long-running inspect/adopt/validate work, but V0.1 should first prove synchronous deterministic Core APIs.

## 4. Benchmark-derived Foundry improvements

The benchmark review produces the following priority improvements.

### 4.1 Project Profile Synthesis

Current inspection/classification concepts should converge into an explicit synthesis stage:

```text
Inspect
→ ProjectObservation
→ ClassificationFindings
→ Project Profile Synthesis
→ ProjectProfile
```

`ProjectProfile` can organize:

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

This becomes the bridge between observed project facts and policy/toolkit resolution.

**Precedence over §4.2.** Read alone, this section suggests that synthesis derives
profile values from observation. It does not. §4.2's conservative authority rule
governs: an authority-bearing characteristic reaches the profile only when an
authority declared it, and inference stays beside the profile as evidence. AF8
measured what that costs — across 12 repositories the median synthesized manifest
carried 1 of 14 fields, and 11 of 12 resolved an empty toolkit — and the answer is
still §4.2, because the alternative is inference silently granting authority. What
synthesis owes instead is to *say* the characteristics are undeclared and to propose
declaring them, which is where `MIGRATE foundry-project-declaration` comes from.

### 4.2 Confidence and provenance

Material classifications should be explainable:

```yaml
key: consequence
value: high
source: inferred
evidence:
  - persistent-store-config
  - deploy-script
confidence: 0.66
```

Conservative authority rule:

```text
inference may tighten controls
inference must not silently expand authority
```

### 4.3 Convention discovery

Inspector work should capture:

- repository conventions;
- architectural boundaries;
- testing patterns;
- naming patterns worth documenting;
- existing agent-rule surfaces;
- repeated local standards that are not obvious from framework defaults.

These remain observations/standards until promoted by an appropriate authority.

### 4.4 Current vs proposed adoption state

Brownfield migration should emit an explicit `AdoptionChangeSet` rather than a narrative-only recommendation.

### 4.5 Declarative policy engine

Avoid project-type branching:

```text
if backend ...
if trading ...
if content ...
```

Prefer predicates over composable characteristics:

```yaml
when:
  consequence: high
  external_effect: true
require:
  - independent-review
forbid:
  - self-approval
```

The policy system should combine:

1. deterministic invariants;
2. declarative rules;
3. bounded reasoning for ambiguous selection.

### 4.6 Skill relevance and progressive disclosure

Registry metadata should support discovery without loading full Skill contents. Full instructions should be compiled only after relevance selection.

### 4.7 Tool-interface profile

Toolkit design should eventually encode not only that `test` or `edit` is allowed, but how the agent receives standardized commands, validation, and concise feedback.

### 4.8 Work Item / Execution Run / Lease separation

The core model should maintain Work Item, Execution Run, and workspace/write ownership as separate objects even if V0.1 does not ship a long-running runtime.

### 4.9 Explainable toolkit resolution

A toolkit decision should be able to answer:

```text
Why was this role selected?
Why was this Skill selected?
Why was this integration required?
Why was this capability excluded?
Which project facts/policies caused the decision?
```

Selection rationale/provenance should be verifiable in AF7-style validation/evidence work.

## 5. Hard-coded versus adaptive behavior

Foundry should intentionally use three layers.

### Layer 1: deterministic invariants

Appropriate for code-level enforcement:

- raw secrets cannot be serialized into version-controlled config;
- path traversal / workspace escape is rejected;
- unsupported contract versions fail closed;
- required evidence cannot be treated as present when missing;
- a hard higher-authority policy cannot be weakened downstream;
- required reviewer independence cannot resolve to the writer identity.

### Layer 2: declarative rules

Appropriate for project-independent or project-local configuration:

```yaml
when:
  reversibility: rollback-required
require:
  - rollback-plan
  - post-apply-readback
```

Rules should be versioned, inspectable, and independently testable.

### Layer 3: bounded interpretation

Appropriate for questions such as:

- ambiguity level;
- convention equivalence;
- likely architectural boundary;
- best matching Skill/workflow among allowed alternatives.

Interpretation must retain provenance/confidence and may not directly grant new authority.

## 6. Implementation mapping

The current V0.1 work graph should remain stable. Benchmark learning should improve issue acceptance/review rather than constantly reset active implementation.

Suggested mapping:

```text
AF1 Typed contracts
→ consider foundational ProjectProfile / ClassificationFinding / ConventionSpec /
  AdoptionChangeSet / provenance-confidence fields / WorkspaceLease skeleton

AF2 Inspector
→ convention discovery + evidence/provenance + current-truth extraction

AF3 Adoption
→ explicit current → proposed AdoptionChangeSet

AF4 Work model
→ enforce Work Item ≠ Execution Run

AF5 Toolkit
→ ToolInterfaceProfile + Skill trigger/relevance metadata + declarative policy inputs

AF6 Compiler
→ ProjectProfile → applicable policy/conventions → minimal role/Skill/context subset

AF7 Verification
→ validate classification provenance and toolkit-selection explanation

AF8 End-to-end
→ measure manifest correction, convention quality, toolkit over/under-selection,
  prompt additions, integration failures, evidence completeness
```

The end-to-end measurements taken against this checklist, and every gap classified
against it, are recorded in [`v0.1-readiness-report.md`](v0.1-readiness-report.md).
Work status for the issues above lives in the tracker, not here.

If active implementation has already frozen an interface, do not inject broad scope mid-issue. Record a bounded follow-up or incorporate only truly foundational omissions before merge.

## 7. Benchmark-gap review checklist

Use this periodically during development:

| Question | Reference signal |
|---|---|
| Is objective/spec → Work Item quality strong? | Spec Kit |
| Are existing project conventions discovered correctly? | Agent OS |
| Are current truth and proposed adoption changes separate? | OpenSpec |
| Are only relevant Skills/context loaded? | OpenHands / Agent OS |
| Is the agent-facing tool/feedback interface well designed? | SWE-agent |
| Are Work Item and execution lifecycle cleanly separated? | Symphony |
| Are tool/resource integrations protocol-friendly without core coupling? | MCP |

## 8. Non-goals reinforced by benchmarks

Do not expand Foundry into:

- a full spec-driven feature framework;
- a coding-agent runtime;
- a general-purpose agent scheduler;
- a Skill marketplace;
- a project-management database;
- a secret manager;
- an MCP-dependent application core.

The narrow center remains:

```text
Inspect
→ Profile
→ Adopt
→ Model Work
→ Resolve Toolkit
→ Compile
→ Validate / Reconcile
```

## 9. Evolution rule

Benchmark learning should flow through evidence:

```text
benchmark / dogfood observation
→ LearningRecord
→ Foundry design delta
→ issue or acceptance update
→ implementation + validation
→ versioned adoption
```

Do not silently mutate core policy based on one external project's design choice or one project-local incident.
