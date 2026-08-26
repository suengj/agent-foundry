# Agent Foundry operating model

## Purpose

Agent Foundry turns reusable AI development principles into project-specific, task-specific execution contracts.

It is not a second AI Dev Playbook and it is not a repository of giant prompts. The intended boundary is:

```text
AI Dev Playbook
= reusable principles, governance, operating knowledge

Agent Foundry
= classify a project, resolve an approved toolkit, compile a task execution bundle,
  enforce execution boundaries, and verify results with evidence

Project
= local constitution, technical context, selected toolkit, and task/runtime truth
```

The long-term operating loop is:

```text
Human objective
→ Project definition
→ Project classification
→ Project manifest
→ Toolkit resolution
→ Project bootstrap
→ Current task + current truth
→ Task-time compilation
→ Agent / Agent Graph execution
→ Verification / evidence
→ Execution receipt
→ Audit / learning
```

## Design principles

1. **Source once, compile many.** Durable principles and policies have one canonical source; task prompts receive only the applicable subset.
2. **Project first, task second.** Foundry first determines what kind of project it is operating, then resolves the capabilities appropriate for that project.
3. **Project Toolkit is an approved universe; Task Toolkit is a minimal subset.** Do not expose every role, skill, tool, or connector to every agent.
4. **Policy is not Skill.** Policy defines what is allowed or required; a Skill defines how to perform a repeatable procedure.
5. **Hard rules require executable controls where possible.** Prose alone is not a permission system.
6. **Typed boundaries reduce interpretation loss.** Agent-to-agent handoffs, evidence, state transitions, and decisions should be structured when practical.
7. **Fresh truth beats hidden memory.** Linear, GitHub, runtime, and external-system read-back outrank agent recollection.
8. **Role before provider.** Resolve responsibility and capability needs before selecting Claude, Codex, Cursor, or another model/provider.
9. **Evidence controls state transition.** Agent self-report is never sufficient evidence for completion.
10. **Pinned inheritance.** Global policies, toolkits, and adapters do not silently change project behavior.

## Canonical document map

| Document | Owns |
|---|---|
| `docs/ai/PROJECT_AGENT_CONSTITUTION.md` | Agent Foundry's own project-local P0 rules and pinned Playbook adoption |
| `docs/contracts/product-boundary.md` | Product / authority boundary for Agent Foundry itself |
| `docs/ai/project-context.md` | Technical environment of this repository |
| `docs/foundry/01-governance-and-harness.md` | Governance, policy, authority, harness and control model |
| `docs/foundry/02-roles-and-interaction.md` | Agent roles, communication, handoff and interpretation contracts |
| `docs/foundry/03-project-classification.md` | Domain-neutral project characterization and Project Manifest model |
| `docs/foundry/04-toolkit-composition.md` | Capability registry, Project Toolkit, Task Toolkit and resolution rules |
| `docs/foundry/05-workflow-and-compilation.md` | Workflow/Agent Graph model and Execution Bundle compilation |
| `docs/foundry/06-execution-evidence-learning.md` | Verification, evidence, receipts, incidents and feedback |
| `docs/foundry/07-implementation-direction.md` | Boundary between documentation/specification and the next code implementation phase |

## Conceptual layers

```text
Principles
  Constitution
      ↓
Rules
  Governance / Policy
      ↓
Controls
  Harness / permissions / gates
      ↓
Project interpretation
  Classification / Manifest
      ↓
Capability composition
  Project Toolkit
      ↓
Task coordination
  Workflow / roles / Task Toolkit
      ↓
Execution
  Agent / tools / skills
      ↓
Verification
  Evidence / review / runtime read-back
      ↓
Learning
  Decision / incident / amendment
```

`Interaction / Communication` is a cross-cutting plane rather than a hierarchy level. It defines how agents pass context, evidence, state and decisions across all execution stages.

## Global versus project-local responsibility

The upper layers are deliberately more reusable:

```text
Global / Foundry-oriented
Constitution → Governance / Policy → Harness / Control → Protocols / Registries

Project-dependent
Project Classification → Project Manifest → Project Toolkit
→ Workflow / Task Toolkit → Execution / Verification
```

Projects inherit global defaults but should normally specialize by narrowing scope, adding domain requirements, or making controls stricter. Lower-level configuration must not silently weaken a non-overridable upper-level rule.

## Relationship to AI Dev Playbook

Agent Foundry should adopt rather than duplicate the Playbook. The Playbook already provides the conceptual source for federated constitution, normative versus factual authority, static/dynamic harness, role-first provider routing, Agent Graph node/edge contracts, evidence-first completion, and provider/tool governance.

Foundry's unique responsibility is to make those ideas executable:

```text
Playbook principle
→ Foundry schema / registry / resolver / compiler
→ project-specific configuration
→ task-specific execution bundle
→ runtime evidence
```

## Non-goal of this documentation phase

This document set freezes the operating model and implementation boundaries. It does not yet implement the toolkit registry, classifier, resolver, compiler, agent runtime, or generated Markdown artifacts. Those are the next code phase described in `07-implementation-direction.md`.
