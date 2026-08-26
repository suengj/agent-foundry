# Project Classification and Project Manifest

## 1. Purpose

Foundry should not begin by asking which named domain a project belongs to. Labels such as `trading`, `blog`, `backend`, or `research` are useful context, but they are too specific and too unstable to determine execution policy by themselves.

The classifier should instead characterize the project along reusable operational dimensions and derive capability, control, workflow and evidence needs from those dimensions.

```text
Project description + repository/system inspection
→ operational characteristics
→ risk / assurance characteristics
→ Project Manifest
→ Toolkit requirements
```

## 2. Classification dimensions

### A. Primary work mode

What kind of transformation does the system primarily perform?

- build / modify artifacts
- analyze / infer
- research / experiment
- generate / transform content
- operate / administer systems
- coordinate / orchestrate work
- monitor / detect / alert

A project can have more than one mode, but one should normally be primary for a given subsystem or workflow.

### B. Primary artifact / state

What is the durable thing being changed or produced?

- source code / configuration
- structured data / schema
- model / statistical result
- document / media / content
- decision / recommendation
- external-system state
- deployed/runtime state
- workflow/task state

### C. Statefulness

How much persistent state exists across executions?

- stateless
- local/reproducible state
- persistent internal state
- persistent external/shared state

Persistent shared state raises synchronization and rollback requirements even if the domain itself is low risk.

### D. External effect

What can execution change outside the isolated task environment?

- none / read-only
- repository or managed artifact write
- shared service / SaaS write
- data-store mutation
- runtime/infrastructure mutation
- public/customer-facing publication
- other real-world or externally consequential action

This is the general replacement for domain-specific concepts such as "analysis only versus live trading". Financial mutation is one possible external consequence, not the classification axis itself.

### E. Reversibility

How easily can a bad action be undone?

- trivially reversible
- reversible with version/history
- recoverable with explicit rollback
- partially reversible
- effectively irreversible

### F. Autonomy level

How far may agents act without a new human decision?

- suggest only
- prepare artifact / preview
- execute in isolated environment
- execute bounded external writes
- deploy/apply approved changes
- continuously operate within explicit policy

Autonomy is an authority property, not an intelligence rating.

### G. Consequence severity

What is the plausible cost of an incorrect action?

- low: local inconvenience / easy rework
- medium: shared work disruption / meaningful rework
- high: material customer, operational, data, reputation or business impact
- critical: severe or hard-to-recover external impact

The exact domain can explain the consequence, but the control decision should depend on severity and reversibility rather than domain naming alone.

### H. Assurance / verification mode

How can correctness be established?

- deterministic tests / schema checks
- static analysis / type/lint
- reproducible calculation
- statistical evaluation
- independent expert/reviewer judgment
- comparison against source evidence
- runtime / external read-back
- human acceptance
- longitudinal observation / canary

Projects may require multiple assurance modes.

### I. Ambiguity / discovery level

How well specified is the correct action?

- deterministic / procedural
- bounded engineering judgment
- ambiguous design trade-off
- exploratory research / unknown root cause

Higher ambiguity changes orchestration: it may require exploration, competing hypotheses, synthesis or architecture ownership rather than simply a stronger builder.

### J. Data / access sensitivity

What kind of protected information or privilege exists?

- public / non-sensitive
- internal
- confidential / credential-adjacent
- secrets / privileged systems

### K. Temporal mode

How is the project executed?

- one-shot / artifact generation
- interactive
- batch / scheduled
- long-running workflow
- continuous service / monitoring

### L. Collaboration / concurrency

How many independent actors can safely work at once?

- single writer
- parallel isolated workstreams
- shared read / bounded write scopes
- coordinated multi-agent graph

## 3. Why classification is not a single project type

Foundry should avoid a taxonomy such as:

```text
if trading → toolkit A
if blog → toolkit B
if backend → toolkit C
```

That approach quickly turns into special cases.

Prefer compositional classification:

```text
persistent external state
+ high consequence
+ rollback required
+ bounded external write
+ runtime read-back required

→ stronger mutation controls
→ independent review
→ runtime verifier
→ rollback-capable workflow
```

A finance system, publishing system and infrastructure system can therefore share the same control pattern when their operational characteristics are similar.

## 4. Project Manifest

Classification becomes durable project input through a machine-readable manifest. The exact schema will be implemented later, but the conceptual structure is:

```yaml
project:
  name: example
  work_modes:
    primary: build
    secondary: [operate]
  artifacts:
    primary: source-code

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

Domain metadata can still be recorded for context and skill selection:

```yaml
context:
  domain_tags:
    - financial-markets
```

but domain tags should not be the sole source of authority or risk decisions.

## 5. Classification sources

A Project Manifest can be initialized from:

- human goal / answers
- repository structure
- existing Constitution / AGENTS.md
- package/dependency files
- CI/testing configuration
- deployment/runtime files
- connected services / MCP declarations
- current external/runtime topology

The generated classification should distinguish `observed`, `declared`, and `inferred` facts. High-impact inferred properties should be confirmed before they grant broader authority.

## 6. Classification output to Toolkit requirements

Examples:

```text
external_effect = none
→ no external-write connector required

external_effect = shared-service-write
→ write-capable connector candidate
→ explicit authority policy required

reversibility = effectively-irreversible
→ human gate / preview strongly favored

ambiguity = exploratory
→ Explorer / Investigator capability
→ hypothesis/evidence workflow

temporal_mode = continuous-service
→ runtime verification / monitoring / incident workflow candidates

assurance includes statistical-evaluation
→ statistical validator capability
```

The classifier does not select an exact model or Skill. It produces requirements and constraints consumed by the Toolkit Resolver.

## 7. Classification lifecycle

Classification should be relatively stable but amendable.

```text
Initial bootstrap
→ classified manifest
→ project toolkit resolved
→ normal task execution

material architecture / authority / runtime change
→ reclassification or manifest amendment
→ toolkit re-resolution
```

A routine task should not silently change the project's autonomy, external-effect authority or consequence classification.

## 8. Practical principle

The Project Manifest answers:

> What kind of operating environment is this, what can go wrong, what may agents change, and how can correctness be proven?

The Toolkit then answers:

> Given those characteristics, which roles, workflows, skills, tools, permissions and validators should this project be allowed to use?
