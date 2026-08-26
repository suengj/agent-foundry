# Project Intake and Adoption

## 1. Purpose

Foundry must work for both newly created projects and already-implemented systems.

The intake process therefore begins with the operating reality of the project, not with an assumption that Foundry can create a clean structure from scratch.

```text
Project input
→ Inspect
→ Characterize
→ Assess readiness
→ Build Project Manifest
→ Resolve adoption gaps
→ Bootstrap or Retrofit
```

## 2. Intake modes

### Greenfield

Use when the project is not yet materially implemented.

Typical path:

```text
Goal
→ minimal project structure
→ project classification
→ Project Manifest
→ initial work model
→ Project Toolkit
→ first bounded work items
```

### Brownfield

Use when code, runtime, workflows, documentation, credentials, trackers, or agent rules already exist.

Typical path:

```text
Existing system
→ inventory
→ current-truth map
→ readiness assessment
→ gap analysis
→ adoption work graph
→ progressive retrofit
→ bounded/shadow execution
→ progressive autonomy
```

Brownfield adoption is migration, not rewrite. Existing structures should be retained when they are authoritative and compatible; duplicated or conflicting control surfaces should be consolidated deliberately.

## 3. Domain-neutral classification

Named domains can be recorded as context, but they should not determine authority or toolkit selection by themselves.

Classify along operational dimensions:

| Dimension | Examples |
|---|---|
| Primary work mode | build, analyze, research, generate, operate, coordinate, monitor |
| Primary artifact/state | code, data, model, document, decision, external state, runtime state |
| Statefulness | stateless, local, persistent internal, persistent shared/external |
| External effect | read-only, repository write, shared service write, data mutation, runtime mutation, publication |
| Reversibility | trivial, versioned, rollback-required, partial, effectively irreversible |
| Autonomy | suggest, prepare, isolated execute, bounded external write, approved apply, continuous operation |
| Consequence severity | low, medium, high, critical |
| Assurance mode | deterministic, statistical, independent review, source evidence, runtime read-back, human acceptance |
| Ambiguity | procedural, bounded judgment, design trade-off, exploratory |
| Access sensitivity | public, internal, confidential, secret/privileged |
| Temporal mode | one-shot, interactive, batch, long-running, continuous |
| Concurrency | single writer, isolated parallel lanes, coordinated graph |

## 4. Observed, declared, inferred, normative

Project discovery must preserve provenance.

```text
observed
= directly found in repository/runtime/external systems

declared
= explicitly stated by an authorized owner

inferred
= reasoned from incomplete evidence

normative
= approved contract or policy describing what should be true
```

High-impact inferred properties must not grant broader authority without confirmation.

For brownfield projects, `observed behavior != intended behavior != normative rule` is a hard distinction. Legacy behavior must not become policy merely because it exists.

## 5. AI-native readiness assessment

Brownfield intake should evaluate whether reliable agent execution is possible before increasing autonomy.

Recommended dimensions:

- repository legibility
- canonical ownership clarity
- reproducibility of local execution
- testability and deterministic checks
- observability and evidence availability
- architecture boundary clarity
- work-tracker hygiene
- branch/workspace isolation
- runtime/apply separation
- rollback capability
- credential and permission isolation
- existing agent-rule fragmentation
- external integration inventory

The result should identify blockers and adoption work rather than produce a single vanity score.

## 6. Project Manifest

The Project Manifest is the durable machine-readable output of classification and approved declarations.

Conceptual example:

```yaml
schema_version: 1

project:
  name: example
  intake_mode: brownfield
  work_modes:
    primary: build
    secondary: [operate]

state:
  persistence: external-shared
  temporal_mode: long-running

impact:
  external_effect: runtime-mutation
  reversibility: rollback-required
  consequence: high

execution:
  autonomy: bounded-external-write
  ambiguity: bounded-judgment
  concurrency: single-writer

assurance:
  required:
    - deterministic-tests
    - independent-review
    - runtime-readback

access:
  sensitivity: internal
```

Domain tags may be included for context and Skill selection, but not as the sole source of risk or authority decisions.

## 7. Brownfield adoption outputs

An existing system may need an `AdoptionPlan` in addition to the Project Manifest.

Typical categories:

```text
KEEP
= current authoritative structure is acceptable

CONSOLIDATE
= duplicate instruction/state surfaces should converge

WRAP
= existing tool/runtime retained behind a Foundry adapter

HARDEN
= add tests, permissions, evidence, or isolation

MIGRATE
= move a contract/config to a canonical structured form

DEFER
= known gap not required for current autonomy level

BLOCK
= unsafe or ambiguous condition prevents requested autonomy
```

Adoption work should itself be represented as bounded work items and pass through the normal work/evidence lifecycle.

## 8. Progressive autonomy

Brownfield conversion should normally increase autonomy in stages:

```text
Inspect / read-only
→ generated plan and previews
→ isolated/local execution
→ repository writes
→ bounded external writes
→ apply/deploy authority when explicitly permitted
→ continuous operation within policy
```

Each transition should be justified by evidence and control readiness, not merely by model capability.

## 9. Reclassification

A material change to architecture, external effect, reversibility, autonomy, access sensitivity, or runtime ownership can require reclassification and toolkit re-resolution.

Routine work items must not silently modify these project-level characteristics.