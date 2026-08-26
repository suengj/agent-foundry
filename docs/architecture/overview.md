# Architecture overview — Agent Foundry (M0)

Frozen at SUE-294. Implementation of downstream components is owned by SUE-295+.

## Positioning

```text
AI Dev Playbook (knowledge / constitution)
        ↓ pinned adoption
Agent Foundry (executable toolbox)
        ↓
Real projects (bootstrap, work graph, adapters, evidence)
```

Agent Foundry is **not** a playbook fork. It applies playbook principles to operational project workflows.

## Long-term flow (not implemented in M0 bootstrap)

```text
Human Goal
    ↓
Verified Project Truth
    ↓
Authority / Information Classification
    ↓
Project Bootstrap
    ↓
Finite Linear Work Graph
    ↓
Provider-neutral Work Order
    ↓
Cursor / Codex / Claude execution adapter
    ↓
Validation / Review / Evidence
```

## M0 repository layout

```text
src/agent_foundry/     # provider-neutral CLI core (bootstrap only)
docs/contracts/        # frozen product/authority contracts
docs/ai/               # constitution + project context
tests/                 # smoke + contract freeze validation
```

## Deferred modules (Linear-owned)

| Capability | Issue |
|---|---|
| ProjectTruth intake | SUE-295 |
| Linear/GitHub compilers | SUE-296+ |
| Dogfood harness | SUE-301 |

## Design constraints

- Thin work orders; fat contracts in `docs/`
- No duplicate current-state mirrors
- External mutation: dry-run → apply
- Adapters stay at the edges; core stays importable without provider SDKs
