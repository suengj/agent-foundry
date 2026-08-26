---
constitution_version: 2
project: Agent Foundry
status: active
---

# Agent Foundry — Project Agent Constitution

> Project-local constitutional entrypoint for this repository.

## 1. Project purpose

- **Product/system:** provider-neutral tooling that converts new or existing projects into bounded AI-native execution environments
- **Primary objective:** inspect/classify projects, model work, resolve least-capability toolkits, compile execution contracts, and verify/reconcile evidence
- **Critical domains:** authority classification, artifact ownership, work decomposition, external-write safety, integration/credential boundaries, evidence integrity
- **Non-goals:** secret vault, generic project-management database, monolithic agent runtime, SaaS control plane

## 2. Authority hierarchy

```text
Human / project owner objective and reserved authority
→ this Project Constitution
→ durable product / Foundry contracts
→ configured Work Item contract
→ role / workflow / Task Toolkit contracts
→ agent inference and defaults
```

Factual truth resolution:

```text
runtime / external-system read-back
→ current repository code/config/schema
→ deterministic tests / generated evidence
→ current work-tracker state
→ agent report / chat history
```

A lower factual layer cannot silently rewrite a higher normative contract. If current behavior conflicts with approved rules, treat it as drift, defect, or an explicit amendment decision.

## 3. P0 invariants

1. **Single canonical owner per volatile artifact class.** Do not mirror current work, implementation, runtime, or credential state into competing sources.
2. **External writes are preview-first by default.** Apply requires explicit authority unless a narrower bounded policy has already granted it.
3. **Provider-neutral core.** Provider/model/tool-specific behavior belongs at adapter boundaries.
4. **Role before provider.** Resolve responsibility and logical capability before provider/model selection.
5. **Project Toolkit before Task Toolkit.** Tasks receive the minimum capability subset required for their Work Item.
6. **Causal work decomposition.** Split work by independently closable outcomes, authority/rollback boundaries, dependencies, and ownership surfaces—not by files or agent roles alone.
7. **Brownfield is first-class.** Existing projects are inspected and progressively retrofitted; observed behavior is not automatically treated as intended policy.
8. **Evidence over agent self-report.** Completion requires the declared evidence classes.
9. **Tracker, execution, and evidence state remain distinct.** One overloaded `Done` signal must not substitute for all three.
10. **Secrets are referenced, never embedded.** Raw credentials do not belong in version-controlled Foundry configuration or generated Markdown.
11. **Hard rules should become executable controls where practical.** Important safety/integrity properties must not depend only on prompt interpretation.
12. **Public contracts are self-contained.** Do not introduce dependencies on private repositories, private project names, personal paths, real credentials, or unpublished policy sources.

## 4. Canonical ownership

| Concept | Canonical owner | Foundry role |
|---|---|---|
| Objective / reserved authority | Human / project owner | interpret and compile bounded contracts |
| Work intent / priority / dependency / lifecycle | configured work tracker or Work Item source | adapt/reconcile, not duplicate |
| Implementation | repository | inspect, compile, validate, reference |
| Applied/live truth | runtime / external system | read back and verify |
| Secret values / identity material | credential provider / execution environment | reference via `SecretRef`-style abstraction |
| Foundry project characteristics | Project Manifest | classify/validate |
| Approved capabilities | Project Toolkit / toolkit lock | resolve/pin |
| Current execution delta | Work Item + Execution Bundle | compile/render |
| Agent interaction state | typed handoff/evidence/receipt artifacts | validate/reconcile |
| Durable Foundry behavior | this constitution + `docs/foundry/*` | canonical repository contract |

## 5. Generated artifact rule

Generated Markdown is a projection of canonical structured inputs where possible.

```text
structured project/work/toolkit/interaction data
→ renderer
→ concise agent/human-readable Markdown
```

Do not independently maintain the generated view as a second source of truth.

## 6. External write contract

Any capability that mutates a repository, work tracker, shared service, data store, runtime, public surface, or other external state must have:

1. declared external-effect class
2. scoped authority
3. applicable permission/integration profile
4. preview/dry-run when required
5. explicit apply semantics
6. required evidence/read-back
7. rollback or failure interpretation where applicable

Silent privilege expansion or implicit writes are forbidden.

## 7. Work contract rule

A Work Item must be independently understandable and closable without hidden conversation history.

Minimum concerns:

- objective / expected outcome
- current verified facts
- scope / out of scope
- acceptance criteria
- dependencies / blockers
- authority / consequence class
- required evidence
- stop / escalation conditions

## 8. Integration and credential rule

Configuration may declare integrations and credential references, but must not contain raw credentials.

```text
Execution Bundle
→ scoped Integration Adapter
→ credential reference / delegated identity
→ external system
```

Credential availability never grants task authority by itself.

## 9. Entry points

### Always read

- `AGENTS.md`
- this file
- the active Work Item / explicit current task contract

### Read by task

| Concern | Path |
|---|---|
| Product boundary | `docs/contracts/product-boundary.md` |
| Architecture | `docs/architecture/overview.md` |
| Environment / commands | `docs/ai/project-context.md` |
| Detailed operating model | `docs/foundry/00-overview.md` and applicable linked contract |

## 10. Change rule

Routine implementation work must not silently change project-level authority, autonomy, external-effect, reversibility, credential boundaries, or constitutional invariants. Such changes require an explicit contract amendment or equivalent authorized decision.