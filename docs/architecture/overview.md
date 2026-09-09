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

Agent Foundry is a project-to-agent compiler/control layer, not a replacement for authoritative work trackers, repositories, runtimes, credential providers, or agent execution products. Its objective is not to generate the largest rule/Skill/context package: it is to compile the minimum sufficient context, capability, authority and assurance that preserve the outcome contract.

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

Domain labels remain optional context tags. They do not directly grant authority or choose a toolkit. Assurance also depends on coupling and observability of correctness; a policy change in Markdown can have higher consequence than a reversible code edit. Unknown impact is not evidence for weaker assurance.

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

### Capability-preserving integration seams

These are planned contract/compiler integration requirements, not a claim of already implemented selection, model execution or measured savings. Their detailed owners remain [toolkit/integrations](../foundry/04-toolkit-and-integrations.md), [orchestration](../foundry/05-orchestration-and-interaction.md) and [the V0.2 contract delta](../contracts/v0.2-contract-delta.md). No parallel Context Compiler, Prompt database or instruction registry is introduced.

| Existing abstraction | Integration responsibility |
|---|---|
| ProjectProfile | Evidence-backed project characteristics and uncertainty; observations never grant authority |
| OperatingModel / DecisionRights | Role and assurance floors, reserved decisions, allowed actions and escalation; consequence, uncertainty, reversibility and observability remain distinct |
| Project Toolkit / Task Toolkit | Audit material instruction families, select relevant approved Skills/sources/capabilities, and defer irrelevant bodies without losing critical boundaries |
| ExecutionBundle / existing lineage | Outcome activation, selected source/version/authority/purpose, material exclusions and unresolved requirements; compile snapshot is not execution evidence |
| Execution adapter | Surface-specific rendering, availability and permission limitations; no reinterpretation of the product contract |

Selection uses three loading stages: **bootstrap** (outcome, current Work Item, authority, critical invariants), **task-triggered** (affected contracts/code, selected Skill/profile/source), and **escalation** (security, migration, release/external-effect controls before the relevant action). A deferred required source retains a locator and loading condition; failed retrieval is explicit. The budget cannot remove a mandatory invariant.

Instruction auditing can recommend keep-always, load-on-demand, reference, eval, executable guardrail, operator-profile or retirement. These are dispositions, not mutually exclusive safety layers or newly implemented enum values. An authority rule may need an agent-visible cue, enforcement and a negative test. Repeated failure does not automatically justify another AGENTS rule; first locate the truth, authority, capability, selection, tool, evaluator, validator or contract failure.

Context accounting distinguishes actual observable input surfaces from estimates and unknown host context. System/AGENTS/Skill metadata and bodies, loaded sources, tool definitions, work and history may all contribute. File bytes are not tokenizer counts or billed usage. Trace material inclusions/exclusions, not every repository file. Evaluate necessary-source recall alongside over-selection, plus retrieval/reload and correction cost where observable.

Logical responsibility is not process count. The Manager owns goal interpretation, decomposition, authority and acceptance; the Writer retains inspection and implementation choice within binding decisions. Independent review has an explicit objective and may find no material defect. Stronger management never substitutes for the artifact's Writer capability floor. Provider/model/effort choices remain approved profile data.

### Version and evidence boundary

- **V0.2:** represent and validate supplied project/policy/context/capability declarations and compile bounded artifacts. Planned M2 selection/provenance extensions must follow their existing contract dependencies. This documentation does not implement them or authorize live probing.
- **V0.3:** existing execution surfaces may consume the same bundle and return actual run/read-back evidence. Deferred tool loading is used only when the adapter's surface supports it; a prompt alone cannot enforce tool permissions. A tracker-driven runtime such as Symphony is a reference surface, not a new Foundry scheduler.
- **V0.4:** trace-backed operating-change candidates and governed promotion/rollback. No automatic authority expansion or inheritance of every old model-compensation rule.

Compiled-artifact tests and model-run experiments are separate. First isolate an instruction family at fixed model/effort/topology; then compare eligible legacy/thin/hybrid operating configurations. Preserve project floors, include failures/unknowns and stop promotion on critical integrity or authority regressions. A shorter activation or a valid schema is not proof of outcome quality. Structured-contract determinism and free-prose semantic equivalence are separate checks; require byte identity only for a renderer that explicitly promises deterministic output.

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

Hard rules should use schemas, preflight checks, permission boundaries, sandboxes, and external enforcement when practical. Execution budgets constrain agents/retries/tool use/cost escalation in addition to semantic policy. Fresh observed behavior establishes current facts, not new permission; conflict with a governing invariant is contract drift.

## Repository layout

```text
src/agent_foundry/     # provider-neutral package; consult current contracts/release evidence for implemented capability

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
