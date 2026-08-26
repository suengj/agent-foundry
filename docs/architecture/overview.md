# Architecture overview — Agent Foundry (M0)

Frozen product boundary remains owned by SUE-294. The `docs/foundry/` tree now defines the longer-term operating model for downstream implementation; it does not claim those components are already implemented.

## Positioning

```text
AI Dev Playbook (knowledge / reusable constitution)
        ↓ pinned adoption
Agent Foundry (classification / toolkit / execution compiler)
        ↓
Real projects (project-local constitution, context, toolkit, tasks, evidence)
```

Agent Foundry is **not** a Playbook fork. It operationalizes Playbook principles through schemas, registries, resolution, compilation, validation and provider adapters.

## Long-term flow

```text
Human Goal
    ↓
Project Definition + Verified Project Truth
    ↓
Domain-neutral Project Classification
    ↓
Project Manifest
    ↓
Capability Requirements
    ↓
Project Toolkit Resolution + Pinning
    ↓
Project Bootstrap / Work Graph
    ↓
Current Task + Fresh GitHub / Runtime Truth
    ↓
Task Toolkit + Dynamic Harness
    ↓
Provider-neutral Execution Bundle
    ↓
Agent / Agent Graph
    ↓
Validation / Independent Review
    ↓
Integration / Apply / Runtime Read-back as applicable
    ↓
Evidence Bundle / Execution Receipt
```

## Project classification philosophy

Classification is compositional rather than domain-hardcoded. A project is characterized using operational dimensions such as:

- primary work mode / artifact
- state persistence
- external effect
- reversibility
- autonomy
- consequence severity
- assurance / verification mode
- ambiguity / discovery level
- data/access sensitivity
- temporal mode
- collaboration/concurrency

Domain labels remain context tags, but they do not directly grant authority or choose a toolkit.

## Toolkit architecture

```text
Foundry Capability Registry
        ↓
Project Manifest
        ↓
Project Toolkit
        ↓
Task Contract + current truth
        ↓
Task Toolkit
        ↓
Execution Bundle
```

The Capability Registry contains roles, workflows, Skills, tools, connectors, validators, permission profiles, context sources and provider capability profiles. The Project Toolkit is an approved/pinned subset. The Task Toolkit is the minimum subset needed for one execution.

## Communication / interaction

Agent communication is a cross-cutting protocol, not another hierarchy layer. Material handoffs should carry typed task identity, verified state, changes/findings, evidence, unresolved risks, requested decisions and provenance. Important state transitions should not depend on free-form `done` messages.

See `docs/foundry/02-roles-and-interaction.md`.

## M0 repository layout

```text
src/agent_foundry/     # provider-neutral CLI core (bootstrap only)
docs/contracts/        # frozen product/authority contracts
docs/ai/               # constitution + project context
docs/foundry/          # operating model / future compiler contracts
tests/                 # smoke + contract freeze validation
```

## Detailed operating model

Start at `docs/foundry/00-overview.md`.

The detailed design is split into:

```text
Governance / Harness
→ Roles / Interaction
→ Project Classification
→ Toolkit Composition
→ Workflow / Compilation
→ Execution / Evidence / Learning
→ Implementation Direction
```

## Design constraints

- Thin task/work-order delta; durable contracts and structured configuration are canonical upstream sources
- No duplicate current-state mirrors
- External mutation: preview/dry-run → explicit apply
- Adapters stay at the edges; core stays provider-neutral
- Role before provider/model
- Project Toolkit before Task Toolkit
- Hard rules should become executable controls where practical
- Structured config should generate Markdown views rather than create parallel hand-maintained truth
