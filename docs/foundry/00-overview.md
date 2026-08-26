# Agent Foundry operating model

## Purpose

Agent Foundry is a provider-neutral system for turning a real project into a bounded AI-native execution environment.

Its core responsibility is:

```text
Inspect
→ Classify
→ Adopt / Retrofit
→ Resolve capabilities
→ Compile work
→ Validate execution contracts
→ Adapt to tools and agents
→ Reconcile evidence
```

Foundry is not intended to become a second project-management database, a secret vault, a general-purpose workflow engine, or a monolithic agent runtime. It should integrate with those systems through explicit adapters and contracts.

## End-to-end lifecycle

Foundry supports both new and existing projects.

```text
Human objective / existing system
        ↓
Project intake
        ↓
Project classification + readiness assessment
        ↓
Project Manifest
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

For a new project, adoption creates the minimum operating structure. For an existing project, adoption begins with inventory, truth reconstruction, gap analysis, and progressive retrofit rather than rewriting the project around Foundry.

## Design principles

1. **Source once, compile many.** Durable rules and structured configuration have one canonical owner; agent-facing Markdown is a projection.
2. **Project first, task second.** Project characteristics determine the allowed capability universe before a task selects its minimum subset.
3. **Work is causal, not file-shaped.** Work items are split by independently testable outcomes, authority boundaries, dependencies, rollback units, and ownership surfaces—not by arbitrary file or agent boundaries.
4. **Project Toolkit is an approved universe; Task Toolkit is least-capability.** A task receives only the capabilities it actually needs.
5. **Policy is not Skill.** Policy defines what is allowed or required; Skills define reusable procedures.
6. **Hard rules should become executable controls where practical.** Prose alone is not a permission system.
7. **Typed boundaries reduce interpretation loss.** Material handoffs, evidence, state transitions, and decisions should be structured.
8. **Fresh truth beats hidden memory.** Repository, tracker, runtime, and external-system read-back outrank agent recollection.
9. **Role before provider.** Responsibility and capability requirements are resolved before provider/model selection.
10. **Evidence controls state transition.** Agent self-report is never sufficient completion evidence.
11. **Tracker state, execution state, and evidence state are distinct.** A task can be in review while a run is retrying and evidence is only partially complete.
12. **Secrets are referenced, not stored.** Foundry configuration may point to credential providers but should not contain raw secret values.
13. **Pinned and compatible by default.** Schemas, toolkits, adapters, and capability versions must not silently alter existing projects.
14. **Learning is gated.** A project-local incident or workaround is not automatically promoted to a global Foundry rule.

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
  Intake / Classification / Adoption
      ↓
Work control
  Objective / Outcome / Work Package / Work Item
      ↓
Capability composition
  Project Toolkit / Integrations
      ↓
Coordination
  Roles / Workflow / Task Toolkit / Interaction
      ↓
Execution
  Agent / Skills / Tools
      ↓
Verification
  Evidence / review / runtime read-back
      ↓
Reconciliation & Learning
  Tracker / repository / runtime state + improvements
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
= project manifest, toolkit resolution/lock, task execution contracts,
  adapters, validation, and reconciliation logic
```

## Public-repository boundary

The public architecture must be self-contained. It should not depend on private repositories, private project names, personal filesystem layouts, or unpublished operating rules. Internal experiments may inform the design, but public contracts must stand on their own and use generic examples.

## Documentation versus implementation

Human-readable Markdown owns architecture intent, semantics, and rationale. Deterministic behavior should move into structured schemas and code.

```text
Human-readable contract
        ↓
Machine-readable spec
        ↓
Resolver / Compiler / Validator
        ↓
Generated agent-facing Markdown
```

The implementation target is described in `07-implementation-contracts.md`.