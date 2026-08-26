# Governance and Harness

## 1. Purpose

This document defines how abstract rules become operational constraints.

```text
Constitution
→ Governance / Policy
→ Harness / Control
→ Orchestration
→ Execution
```

The first three layers are relatively reusable across projects. Orchestration and execution become increasingly project- and task-dependent.

## 2. Constitution

The Constitution owns only durable, high-authority rules:

- authority hierarchy
- separation of duties
- evidence-over-self-report principle
- non-overridable safety and integrity invariants
- human authority boundaries
- conflict resolution
- contract amendment and emergency override semantics

Constitution should remain small. Procedural commands, current project status, provider rankings, and detailed workflows do not belong here.

## 3. Governance / Policy

Governance turns constitutional principles into rules that can be applied to a class of projects or tasks.

Typical policy domains:

- role and authority policy
- write ownership / single-writer policy
- Git / branch / PR policy
- external mutation policy
- review independence
- state / SSOT ownership
- data / credential boundaries
- release / runtime policy
- archive / cleanup policy
- incident / exception policy
- provider, model, tool and connector governance

Important rules should eventually have machine-readable metadata such as:

```yaml
rule_id: REVIEW_INDEPENDENCE
authority: global
strength: hard
scope: execution
owner: foundry-governance
verification: deterministic
override:
  allowed: false
```

Not every sentence needs YAML. Machine-readable representation is most valuable for permissions, write scope, required review, required evidence, retry limits, allowed tools, external mutation and provider constraints.

## 4. Harness / Control

Harness is the execution mechanism that turns policy into operational boundaries.

```text
Policy
"unreviewed high-impact changes cannot be accepted"

Harness
→ independent reviewer required
→ reviewer cannot be the writer
→ transition gate rejects missing review evidence
```

Harness components include:

- repository / branch / worktree state
- filesystem scope
- tool and MCP/connector allowlists
- network and external-write permissions
- credential boundary
- sandbox / isolation
- role separation
- agent budget
- provider/model resolution constraints
- tests / validators
- retry and stop conditions
- evidence contract
- cleanup rules

### Static Harness

Long-lived defaults for a project or workflow:

- default roles
- provider capability policy
- tool / connector baseline
- write ownership
- required tests
- review conditions
- production / external-state authority
- output and cleanup rules

### Dynamic Harness

Resolved for one task/run:

- current task and verified base state
- exact role assignment
- exact model / effort when needed
- allowed and forbidden paths
- temporary permissions
- selected skills / tools
- acceptance criteria
- retry budget
- stop condition
- evidence requirements

```text
Dynamic Harness
= Static Harness
+ Current Project/Repository Truth
+ Task Contract
+ Authorized human delta
```

Dynamic Harness may specialize or tighten a hard rule; it must not silently remove one.

## 5. Authority and factual truth are separate

Foundry must distinguish normative authority from factual authority.

### Normative question

> What is allowed, required, or forbidden?

Resolution comes from Constitution, Policy, Project Constitution and the authorized Task Contract.

### Factual question

> What is actually true now?

Resolution comes from fresh external/runtime read-back, current repository state, tests/evidence and current Work SSOT.

If runtime/code conflicts with a normative contract, the current runtime does not automatically redefine the rule. It is a drift or incident to resolve.

## 6. Reusable versus project-specific control

| Layer | Default scope | Project specialization |
|---|---|---|
| Constitution | global / Foundry | exceptional |
| Governance Policy | global / capability class | normal but constrained |
| Harness Standard | global / risk class | expected |
| Project Constitution | project | canonical local invariants |
| Project Harness Profile | project | canonical local defaults |
| Dynamic Harness | task/run | generated every execution |

## 7. Hard rule implementation hierarchy

For high-value rules, prefer the strongest practical enforcement surface:

```text
Documentation
< schema validation
< preflight validation
< permission / sandbox restriction
< external system enforcement
```

Examples:

- "Do not modify this path" should become a write-scope control when possible.
- "Reviewer must be independent" should become a role/graph validation rule.
- "External writes require apply authorization" should become an explicit preview/apply state machine.
- "Evidence required before Done" should become a transition gate, not a reminder sentence.

## 8. Relationship to project toolkit

Governance and Harness do not directly choose every tool. They constrain the search space.

```text
Project characteristics
→ capability requirements
→ Toolkit Resolver
→ candidate roles / skills / tools
→ Governance filtering
→ Harness controls
→ approved Project Toolkit
```

This distinction lets Foundry remain adaptable without letting project-specific convenience override system-level authority.
