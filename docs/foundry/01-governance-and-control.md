# Governance and Control

## 1. Purpose

This document defines how durable principles become executable boundaries.

```text
Constitution
→ Governance / Policy
→ Harness / Control
→ Project / Task configuration
→ Execution
```

The goal is not to encode every procedure as a constitutional rule. The goal is to keep authority, policy, controls, and procedures distinct enough that each can evolve without becoming instruction soup.

## 2. Layer responsibilities

### Constitution

Owns a small set of non-negotiable principles:

- authority hierarchy
- separation of duties where required
- evidence-first completion
- reserved human authority
- conflict and amendment rules
- prohibition on silent privilege expansion

### Governance / Policy

Owns operating rules such as:

- artifact ownership and SSOT boundaries
- work/review independence
- repository and external-write policy
- data/access policy
- release/apply policy
- incident and exception handling
- lifecycle and archival policy

### Harness / Control

Turns policy into constraints that can be enforced outside natural-language prompts:

- filesystem and write scopes
- branch/workspace isolation
- tool and connector allowlists
- sandbox/network boundaries
- approval gates
- retry and execution budgets
- required validation
- output schemas
- cleanup rules

## 3. Authority model

Every material capability should identify:

```yaml
authority:
  owner: project
  strength: hard      # hard | default | guidance
  scope: repository
  override:
    allowed: false
    required_authority: explicit-amendment
```

Lower-level configuration may make a rule stricter. It must not silently weaken a non-overridable upper-level rule.

## 4. Normative truth versus factual truth

Foundry must distinguish what should be true from what is currently true.

```text
Normative
= constitution / approved policy / project contracts / task contract

Factual
= runtime read-back / external-system state / current code and config /
  deterministic evidence / current tracker state
```

If factual behavior violates a contract, the result is contract drift or a defect; the current behavior does not automatically become the new rule.

## 5. Static and dynamic control

### Static control

Stable project/workflow defaults:

- default role separation
- provider capability policy
- permission baseline
- connector baseline
- required checks
- branch/workspace policy
- evidence profile
- budget ceilings

### Dynamic control

Task/run-specific resolved state:

- exact objective and work item
- current base revision
- actual role assignment
- selected Task Toolkit
- allowed paths and temporary capabilities
- resolved provider/model
- retry budget
- stop conditions
- required evidence

Dynamic controls are compiled from static rules plus fresh project truth and the current work item.

## 6. Trust and taint model

Not all context should be treated as equally trustworthy.

Suggested classes:

```text
TRUSTED_CONTRACT
= approved local contracts and structured Foundry configuration

TRUSTED_STATE
= fresh tracker/repository/runtime read-back from an authorized adapter

UNTRUSTED_CONTENT
= web pages, email, issue comments, user-provided documents, third-party tool output

SECRET
= credentials, tokens, keys, private identity material
```

Untrusted content may inform reasoning but must not grant authority, alter permissions, or override higher-level rules. Secret values should not be injected into agent context unless the execution substrate requires them and the capability is explicitly authorized.

## 7. Execution budget

Autonomy requires resource limits in addition to semantic rules.

A budget profile may constrain:

```text
max agents
max retries
max wall-clock duration
max tool calls
cost class
provider escalation
parallel workspaces
external-write count
```

Budget exhaustion is a typed stop condition, not a reason for silent escalation.

## 8. External-effect classes

Controls should be driven by the consequence and reversibility of actions rather than domain names.

Examples:

| Effect | Default control direction |
|---|---|
| Read-only inspection | broadest safe access |
| Repository write | branch/workspace isolation + validation |
| Shared-service write | scoped connector + evidence |
| Data mutation | rollback/backup semantics + authority |
| Runtime/infrastructure mutation | apply gate + read-back |
| Public/customer-facing publication | preview + publication authority |
| Effectively irreversible action | explicit reserved authority |

## 9. Control validation

Before dispatch, Foundry should reject configurations with conditions such as:

- missing required authority
- forbidden capability requested
- write-scope collision
- reviewer independence violation
- unavailable or unhealthy required integration
- unresolved hard-rule conflict
- missing credential reference for an authorized integration
- raw secret embedded in project configuration
- retry/cost budget outside policy

## 10. Amendment and exception

Requests should be classified before execution:

```text
ROUTINE_WORK
GOAL_CHANGE
CONTRACT_AMENDMENT
EMERGENCY_OVERRIDE
```

An emergency override should be scoped, time-bounded, auditable, reversible where possible, and followed by review. It should not silently become a permanent policy.

## 11. Practical rule

Use documents to explain the rule, structured configuration to declare it, and runtime controls to enforce the parts that must not depend on model interpretation.