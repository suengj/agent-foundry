# Agent Foundry operating model

## Purpose

Agent Foundry is a provider-neutral system for turning a real project into a bounded AI-native execution environment.

Its core responsibility is:

```text
Inspect
→ Classify
→ Synthesize Project Profile
→ Adopt / Retrofit
→ Model Work
→ Resolve Toolkit
→ Compile
→ Validate / Reconcile
```

At the product level, this is summarized as:

```text
Diagnosis
→ Prescription
→ Compilation
→ Controlled Apply
```

`Diagnosis` reconstructs project truth and operating characteristics. `Prescription` proposes the AI-native operating model, adoption changes, work structure, roles, policies, evidence and capability requirements. `Compilation` turns those structured decisions into pinned toolkits and agent-facing execution contracts. `Controlled Apply` is the later bounded mutation layer that applies reviewed changes and verifies the result.

The first public release target (`v0.1.0`) proves Diagnosis → Prescription → Compilation → Validation in read-only/preview mode. Broad Controlled Apply is intentionally post-Core and is not a V0.1 release blocker. See `09-release-and-versioning.md`.

Foundry is not intended to become a second project-management database, a secret vault, a full spec framework, a general-purpose workflow engine, a Skill marketplace, or a monolithic agent runtime. It should integrate with those systems through explicit adapters and contracts.

## End-to-end lifecycle

Foundry supports both new and existing projects.

```text
Human objective / existing system
        ↓
Project intake
        ↓
Project observations + convention discovery
        ↓
Classification findings + provenance/confidence
        ↓
Project Profile Synthesis
        ↓
Project Manifest + adoption/readiness state
        ↓
Work model + Project Toolkit
        ↓
Work Item + fresh project truth
        ↓
Task Toolkit + Execution Bundle
        ↓
Agent / Agent Graph execution
        ↓
Verification / evidence / reconciliation
        ↓
Learning / project or Foundry improvement
```

For a new project, adoption creates the minimum operating structure. For an existing project, adoption begins with inventory, truth reconstruction, convention discovery, gap analysis, and progressive retrofit rather than rewriting the project around Foundry.

## Project Profile Synthesis

The Project Profile is the explicit bridge between observed project facts and downstream policy/toolkit decisions.

It can organize:

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

A profile must be evidence-aware. Material findings should distinguish:

```text
observed
≠ declared
≠ inferred
≠ normative
```

and retain provenance/confidence where interpretation is involved.

Conservative authority principle:

```text
inference may tighten controls
inference must not silently expand authority
```

## Design principles

1. **Source once, compile many.** Durable rules and structured configuration have one canonical owner; agent-facing Markdown is a projection.
2. **Project first, task second.** Project characteristics determine the allowed capability universe before a task selects its minimum subset.
3. **Project characteristics are compositional.** Avoid hard-coded domain taxonomies when operational predicates can express the same constraint.
4. **Work is causal, not file-shaped.** Work items are split by independently testable outcomes, authority boundaries, dependencies, rollback units, and ownership surfaces - not arbitrary file or agent boundaries.
5. **Project Toolkit is an approved universe; Task Toolkit is least-capability.** A task receives only the capabilities it actually needs.
6. **Policy is not Skill.** Policy defines what is allowed or required; Skills define reusable procedures.
7. **Hard rules should become executable controls where practical.** Prose alone is not a permission system.
8. **Typed boundaries reduce interpretation loss.** Material handoffs, evidence, state transitions, and decisions should be structured.
9. **Fresh truth beats hidden memory.** Repository, tracker, runtime, and external-system read-back outrank agent recollection.
10. **Role before provider.** Responsibility and capability requirements are resolved before provider/model selection.
11. **Evidence controls state transition.** Agent self-report is never sufficient completion evidence.
12. **Tracker state, execution state, and evidence state are distinct.** A Work Item can be in review while a run is retrying and evidence is incomplete.
13. **Secrets are referenced, not stored.** Foundry configuration may point to credential providers but should not contain raw secret values.
14. **Pinned and compatible by default.** Schemas, toolkits, adapters, and capability versions must not silently alter existing projects.
15. **Progressive disclosure.** Discover through lightweight metadata/indexes, then load only relevant standards, Skills, policy, and context.
16. **Learning is gated.** A project-local incident, benchmark choice, or workaround is not automatically promoted to a global Foundry rule.

## Adaptive behavior model

Foundry should combine three layers rather than hard-code project types.

### Deterministic invariants

Examples:

- raw secret serialization is forbidden;
- path/workspace escape is rejected;
- incompatible schema versions fail closed;
- required evidence cannot be treated as present when missing;
- hard higher-authority policy cannot be weakened downstream;
- reviewer independence is enforced when required.

### Declarative policies

Example:

```yaml
when:
  consequence: high
  external_effect: true
require:
  - independent-review
forbid:
  - self-approval
```

### Bounded interpretation

Use reasoning only where project evidence genuinely requires interpretation, such as ambiguity, convention equivalence, architecture-boundary inference, or Skill/workflow selection among already-authorized options.

Interpretation should produce typed findings with evidence and confidence rather than implicit prompt memory.

## Canonical document map

| Document | Owns |
|---|---|
| `docs/ai/PROJECT_AGENT_CONSTITUTION.md` | This repository's project-local P0 rules and authority |
| `docs/contracts/product-boundary.md` | Product scope and authority boundary |
| `docs/ai/project-context.md` | Technical environment of this repository |
| `docs/foundry/01-governance-and-control.md` | Governance, policy, authority, trust, harness and executable controls |
| `docs/foundry/02-project-intake-and-adoption.md` | Domain-neutral classification, greenfield bootstrap, brownfield retrofit, readiness |
| `docs/foundry/03-work-model-and-decomposition.md` | Objective-to-work decomposition and tracker-neutral work contracts |
| `docs/foundry/04-toolkit-and-integrations.md` | Capability registry, Project/Task Toolkit, tools, MCP/API integrations, credential references |
| `docs/foundry/05-orchestration-and-interaction.md` | Roles, workflows, Agent Graph, communication and handoff contracts |
| `docs/foundry/06-verification-reconciliation-learning.md` | Evidence, state reconciliation, incidents and learning feedback |
| `docs/foundry/07-implementation-contracts.md` | Machine-readable schemas, package boundaries and implementation sequence |
| `docs/foundry/08-benchmarks-and-evolution.md` | Public benchmarks, MCP direction and benchmark-derived design deltas |
| `docs/foundry/09-release-and-versioning.md` | Public-release gate, package/schema versioning and compatibility policy |

## Conceptual layers

```text
Principles
  Constitution
      ↓
Rules
  Governance / Policy
      ↓
Controls
  Harness / permissions / trust / budgets
      ↓
Project interpretation
  Intake / Observation / Classification / Profile Synthesis / Adoption
      ↓
Work control
  Objective / Outcome / Work Package / Work Item / Execution Run
      ↓
Capability composition
  Project Toolkit / Integrations
      ↓
Coordination
  Roles / Workflow / Task Toolkit / Interaction
      ↓
Execution
  Agent / Skills / Tool Interfaces
      ↓
Verification
  Evidence / review / runtime read-back
      ↓
Reconciliation & Learning
  Tracker / repository / runtime state + versioned improvements
```

Communication is a cross-cutting protocol rather than another hierarchy level. It defines how authority, context, evidence, uncertainty, state, and requested decisions move between agents and systems.

## Foundry-owned versus external state

Foundry should not duplicate the authoritative state of external systems.

```text
Work tracker
= objectives, work items, priority, dependency, lifecycle state

Repository
= code, configuration, tests, PRs, implementation history

Runtime / external systems
= actual deployed or externally visible truth

Credential provider
= secret values and identity material

Foundry
= observations/profile, project manifest, adoption state, toolkit resolution/lock,
  task execution contracts, adapters, validation, and reconciliation logic
```

## MCP boundary

MCP is an optional facade over Foundry Core, not the implementation substrate of the core itself.

```text
              Foundry Core
                  │
       ┌──────────┼──────────┐
       ↓          ↓          ↓
      CLI     Python API   MCP Server
```

The core must remain usable when MCP is unavailable.

New MCP implementation should not rely on deprecated MCP Roots for project selection. Prefer explicit project path parameters, resource URIs, or server configuration, with Foundry-side path containment and permission checks.

See `04-toolkit-and-integrations.md` and `08-benchmarks-and-evolution.md`.

## Public-repository boundary

The public architecture must be self-contained. It should not depend on private repositories, private project names, personal filesystem layouts, or unpublished operating rules. Internal experiments may inform the design, but public contracts must stand on their own and use generic examples.

Public visibility is a distinct release operation. Before publication, audit not only branch contents but also durable GitHub objects such as historical merged pull requests. See `09-release-and-versioning.md`.

## Documentation versus implementation

Human-readable Markdown owns architecture intent, semantics, benchmark rationale, release boundaries, and design rationale. Deterministic behavior should move into structured schemas and code.

```text
Human-readable contract
        ↓
Machine-readable spec
        ↓
Resolver / Compiler / Validator
        ↓
Generated agent-facing Markdown / adapters
```

The implementation target is described in `07-implementation-contracts.md`; benchmark-derived evolution is tracked in `08-benchmarks-and-evolution.md`; public release and compatibility policy are defined in `09-release-and-versioning.md`.
