# Architecture overview — Agent Foundry

The detailed operating model lives under `docs/foundry/`. This overview summarizes the intended architecture; it does not imply that all downstream components are already implemented.

## Positioning

```text
Human objective / existing project
        ↓
Agent Foundry
  inspect / classify / adopt
  model work
  resolve toolkit
  compile execution
  validate / reconcile
        ↓
Existing agent CLIs, tools, trackers, repositories, runtimes and services
```

Agent Foundry is a project-to-agent compiler/control layer, not a replacement for authoritative work trackers, repositories, runtimes, credential providers, or agent execution products.

## Long-term flow

```text
Project description or existing repository/system
    ↓
Project Intake + Verified Project Truth
    ↓
Domain-neutral Classification + Readiness Assessment
    ↓
Project Manifest + optional Adoption Plan
    ↓
Objective → Outcome → Work Package → Work Item
    ↓
Project Toolkit Resolution + Version Lock
    ↓
Current Work Item + Fresh Tracker / Repository / Runtime Truth
    ↓
Task Toolkit + Dynamic Controls
    ↓
Provider-neutral Execution Bundle
    ↓
Agent / Agent Graph through adapters
    ↓
Validation / Independent Review when required
    ↓
Integration / Apply / External Read-back as applicable
    ↓
Evidence Bundle / Execution Receipt
    ↓
Reconciliation + Learning
```

## Project intake

Foundry supports two first-class intake modes.

```text
Greenfield
→ bootstrap minimum project contracts and toolkit

Brownfield
→ inventory existing truth
→ assess AI-native readiness
→ preserve valid authority surfaces
→ consolidate/wrap/harden/migrate gaps
→ progressive autonomy
```

Brownfield adoption distinguishes:

```text
observed behavior
!= declared intent
!= inferred intent
!= normative approved rule
```

## Project classification philosophy

Classification is compositional rather than domain-hardcoded. Operational dimensions include:

- primary work mode and durable artifact/state
- state persistence
- external effect
- reversibility
- autonomy
- consequence severity
- assurance/verification mode
- ambiguity/discovery level
- data/access sensitivity
- temporal mode
- collaboration/concurrency

Domain labels remain optional context tags. They do not directly grant authority or choose a toolkit.

## Work architecture

Foundry defines a tracker-neutral hierarchy:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

Trackers are adapters to this causal work model. Work Item decomposition follows independent acceptance, dependency, authority, rollback, ownership, and retry boundaries rather than arbitrary file/agent splits.

Tracker lifecycle, agent execution state, and evidence state remain separate state machines.

## Toolkit architecture

```text
Foundry Capability Registry
        ↓
Project Manifest
        ↓
Project Toolkit
        ↓
Work Item + current truth
        ↓
Task Toolkit
        ↓
Execution Bundle
```

The Capability Registry can contain roles, workflows, Skills, tools, integrations, validators, permission/budget profiles, context sources, and provider capability profiles.

The Project Toolkit is an approved/pinned subset. The Task Toolkit is the minimum subset needed for one Work Item/run.

## Integration and credential architecture

External tools and services are integration boundaries.

```text
Task Toolkit / Execution Bundle
        ↓
Integration Adapter
        ↓
Credential reference / delegated identity
        ↓
External system
```

Foundry configuration declares capability/authority requirements and credential references. Actual secret values belong to external credential providers or the execution environment.

Integration health is distinct from configuration presence:

```text
DESIRED → INSTALLED → CONFIGURED → AUTHENTICATED → AUTHORIZED → HEALTHY
```

## Communication / interaction

Agent interaction is a cross-cutting protocol. Material transitions should carry typed:

- Work Item/run identity
- role and authority
- current verified state
- change/finding summary
- evidence references
- unknowns/risks/assumptions
- requested action or decision
- revision/runtime provenance

Important state transitions must not depend on free-form `done` messages.

See `docs/foundry/05-orchestration-and-interaction.md`.

## Trust and controls

The control model separates:

```text
trusted contracts
trusted fresh state
untrusted external content
secret/credential material
```

Hard rules should use schemas, preflight checks, permission boundaries, sandboxes, and external enforcement when practical. Execution budgets constrain agents/retries/tool use/cost escalation in addition to semantic policy.

## Repository layout

```text
src/agent_foundry/     # provider-neutral package; currently minimal bootstrap

docs/contracts/        # product/authority contracts
docs/ai/               # repository-local constitution + project context
docs/foundry/          # operating model and implementation contracts
docs/architecture/     # architecture summaries
tests/                 # smoke / contract validation
```

## Detailed operating model

Start at `docs/foundry/00-overview.md`.

```text
Governance / Control
→ Project Intake / Adoption
→ Work Model / Decomposition
→ Toolkit / Integrations
→ Orchestration / Interaction
→ Verification / Reconciliation / Learning
→ Implementation Contracts
```

## Design constraints

- Public, self-contained architecture with no private upstream dependency
- Thin execution delta; durable structured contracts are canonical
- No duplicate current-state mirrors
- Causal Work Items rather than file-shaped tasks
- Greenfield and brownfield both supported
- External mutation is preview-first unless explicitly authorized otherwise
- Provider/tool/tracker/runtime integrations stay at the edges
- Role before provider/model
- Project Toolkit before Task Toolkit
- Least privilege and least capability
- Secret references instead of raw credentials
- Hard rules become executable controls where practical
- Structured config generates Markdown views rather than parallel hand-maintained truth
- Schema/toolkit/adapter upgrades are versioned and explicit