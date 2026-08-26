# Product boundary — Agent Foundry

**Status:** active product and authority contract.  
**Evidence:** this file + `docs/ai/PROJECT_AGENT_CONSTITUTION.md` + passing contract tests.

## Purpose

Agent Foundry helps turn new or existing projects into bounded AI-native execution environments.

Primary system journey:

1. Inspect a project or project description.
2. Classify operating characteristics and AI-native readiness.
3. Bootstrap a new project or generate a bounded retrofit plan for an existing project.
4. Express objectives as causal tracker-neutral Work Items.
5. Resolve a version-pinned Project Toolkit and minimum Task Toolkit.
6. Compile concise provider-neutral execution contracts.
7. Validate/reconcile implementation and external evidence before work closure.

## Product boundary

Foundry owns:

- project intake/classification models
- AI-native readiness and adoption-plan semantics
- tracker-neutral work hierarchy and decomposition validation
- capability/toolkit metadata and resolution
- integration declarations, credential references, and integration-health semantics
- task-time execution compilation
- agent interaction/evidence contracts
- validation and state reconciliation logic
- provider/tool/tracker/runtime adapters at the edges

Foundry does not own:

- authoritative project-management data
- repository implementation history
- runtime/external-system truth
- actual secret values or identity material
- a general-purpose workflow engine
- a monolithic agent runtime
- SaaS billing/auth/multi-tenancy or a marketplace

## Authority ownership

| Layer | Canonical owner | Foundry relationship |
|---|---|---|
| Objective / reserved authority | Human / project owner | interpret and compile bounded contracts |
| Work intent / priority / dependency / lifecycle | configured work tracker or Work Item source | adapt/reconcile |
| Code / config / tests / revision history | repository | inspect/reference/validate |
| Applied/live/external state | runtime or external system | read back/verify |
| Secret values / identity material | credential provider / execution environment | reference only |
| Project classification | Project Manifest | own schema/validation |
| Capability resolution | Toolkit lock | own resolution/validation |
| Execution delta | Work Item + Execution Bundle | compile/render |
| Execution evidence | Evidence Bundle / Execution Receipt | own schema/reconciliation |

## Generated artifact ownership

Current external state must not be duplicated across docs, prompts, trackers, and adapters.

| Artifact | Canonical source | Generated/derived surface |
|---|---|---|
| Project characteristics | structured Project Manifest | project summary Markdown |
| Approved capabilities | toolkit lock | toolkit summary |
| Work intent | tracker / Work Item contract | execution brief |
| Agent run contract | Execution Bundle | provider-specific prompt/Markdown |
| Handoff/evidence | structured interaction/evidence object | readable report |
| Implementation | repository | references/diffs only |
| Runtime result | runtime/external read-back | evidence reference |

## External writes

Capabilities that mutate repositories, trackers, shared services, data stores, runtimes, or public surfaces must have explicit external-effect semantics.

Default:

| Phase | Default | Requirement |
|---|---|---|
| Preview | **dry-run** | expose intended effect/diff when practical |
| Apply | **explicit apply** | authorized, logged, evidenced |

A project policy may grant narrower bounded automatic authority, but availability of a tool or credential never grants authority by itself.

## Provider independence

- **Core:** provider-neutral Python package (`agent_foundry`)
- **Adapters:** provider/model/tool-specific loading and execution boundaries
- Role and capability definitions must not depend on one provider identity
- Model/provider resolution occurs after Work Item, role, policy, toolkit, and health requirements

## Greenfield and brownfield

Both are first-class:

```text
Greenfield
→ bootstrap minimum operating structure

Brownfield
→ inspect existing truth
→ distinguish observed / declared / inferred / normative
→ assess readiness
→ KEEP / CONSOLIDATE / WRAP / HARDEN / MIGRATE / DEFER / BLOCK
→ progressively increase agent autonomy
```

Foundry should not rewrite an existing system merely to make it look Foundry-native.

## Work model

Foundry defines causal work semantics above any tracker:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

Work is split by independent acceptance, dependency, authority, rollback, ownership, and retry boundaries—not by arbitrary file counts or agent roles.

## Integration and credential boundary

Version-controlled project configuration may store:

- desired integrations
- capability scopes
- adapter/version requirements
- endpoints when safe/public
- credential references
- required integration-health state

It must not store raw secrets.

```text
Execution Bundle
→ scoped adapter
→ SecretRef / delegated identity
→ external service
```

## Success metrics

Useful evaluation metrics include:

| Metric | Intent |
|---|---|
| project classification correction rate | detect weak intake/classification |
| readiness-gap escape rate | gaps discovered only after execution begins |
| generated Work Item correction rate | measure decomposition quality |
| toolkit over/under-selection | measure capability resolution quality |
| manual prompt additions | measure missing compiled context |
| duplicate/stale-context detection | detect authority/SSOT problems |
| permission overreach / denied actions | measure control quality |
| integration auth/health failures | measure operational integration quality |
| review rework rate | measure execution quality |
| evidence completeness | measure closure reliability |
| human escalation rate | measure autonomy/authority balance |
| verified closure elapsed time | measure end-to-end operational efficiency |

## Public repository contract

Public documentation, schemas, examples, and tests must be self-contained and generic. They must not depend on private repositories, private project names, personal filesystem layouts, real credentials, or unpublished operating documents.