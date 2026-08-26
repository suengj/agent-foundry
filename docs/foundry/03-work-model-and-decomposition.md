# Work Model and Decomposition

## 1. Purpose

Foundry needs a work model above any specific project-management product. Linear, Jira, GitHub Issues, or another tracker should be adapters to the same causal work semantics.

The work model answers:

> What outcome are we trying to create, what is the smallest independently closable unit, what depends on what, and what evidence closes it?

## 2. Hierarchy

Recommended hierarchy:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

### Objective

A durable project or program goal. It should not be rewritten for every implementation detail.

### Outcome / Capability

A user/system capability or measurable result that can be accepted at a meaningful boundary.

### Work Package

A bounded group of related Work Items that delivers a coherent capability slice or adoption step.

### Work Item

The primary causal execution unit. A Work Item should be independently understandable, ownable, testable, and closable without hidden chat history.

### Execution Run

One concrete attempt by an agent or Agent Graph to advance a Work Item. Runs are runtime/evidence objects, not separate roadmap objects unless they create new work.

## 3. Decomposition principles

Split work when one or more of these materially differ:

- acceptance can be evaluated independently
- dependency ordering differs
- authority or consequence class differs
- rollback/apply unit differs
- primary ownership surface differs
- work can fail/retry independently
- discovery should complete before mutation is authorized
- a result can be safely merged/delivered without another result

Do not split work merely because:

- files are different
- different agent roles participate
- tests are separate commands
- review is a separate stage
- implementation has several mechanical steps

## 4. Causal work item rule

A good Work Item describes one causal outcome, not a list of implementation files.

Poor decomposition:

```text
Task A: add schema
Task B: add function
Task C: add test
Task D: review
```

Better:

```text
Work Item:
"The new contract is implemented and consumed by the authoritative path."

Acceptance:
- contract defined
- authoritative consumer wired
- regression evidence passes
- required review complete
```

If applying the change to an external system has a different authority/rollback boundary, source implementation and external apply may be separate Work Items.

## 5. Work Item contract

Minimum fields:

```text
Identity
Objective / expected outcome
Problem and current verified facts
Scope
Out of scope
Acceptance criteria
Dependencies / blockers
Authority / consequence class
Required verification and evidence
Runtime/external validation requirement
Stop / escalation conditions
Implementation references when known
```

A Work Item should be executable without reconstructing historical conversation context.

## 6. Discovery versus implementation

Do not mix open-ended discovery and irreversible implementation in one opaque task when the implementation scope depends on unresolved findings.

Preferred pattern:

```text
Discovery Work Item
→ Evidence / decision
→ Implementation Work Item(s)
```

For small bounded engineering work, discovery may remain an initial node inside the same Work Item when its result cannot materially change authority, project scope, or acceptance.

## 7. Baseline, feature, residual, incident

Useful work classes:

```text
BASELINE
= establish a known operating state

CAPABILITY
= add or materially change a bounded capability

RESIDUAL_HARDENING
= bounded weakness after the main capability is already valid

INCIDENT
= restore or contain a broken operating state

DISCOVERY
= resolve uncertainty before scoped implementation

ADOPTION
= retrofit an existing project toward the desired operating model

CONTRACT_AMENDMENT
= intentionally change authority, invariants, or major project semantics
```

Completed baseline work should not be repeatedly reopened for unrelated defects. New defects should become causal follow-up Work Items unless the original acceptance was never actually satisfied.

## 8. Dependency model

Dependencies should encode real execution constraints rather than cosmetic hierarchy.

Typical dependency relations:

- requires
- blocks
- supersedes
- validates
- applies-after
- discovered-by

A Manager should choose executable work from dependency state and write-scope compatibility, not merely tracker order.

## 9. Work ownership and repository mapping

Default engineering mapping:

```text
1 causal Work Item
→ 1 primary write owner
→ 1 primary branch/workspace
→ 1 primary PR/change set
→ required post-merge/system verification
```

Exceptions are allowed when a narrow repair or follow-up is genuinely part of the same causal acceptance boundary.

Parallelization should be based on canonical ownership surfaces, not filename count. Different files that alter the same shared schema, authority, or runtime contract may still require a single writer.

## 10. Tracker adapters

Foundry should not require one tracker hierarchy. Adapters map Foundry semantics to the available product.

Conceptual mapping:

| Foundry | Typical tracker representation |
|---|---|
| Objective | initiative / goal / program |
| Outcome / Capability | project / epic / milestone |
| Work Package | project segment / epic / issue group |
| Work Item | issue / story / task / bug |
| Child work | sub-issue / subtask when needed |
| Execution Run | Foundry runtime/evidence, usually not a tracker issue |

The adapter must preserve causal identity and dependencies even if tracker-specific naming differs.

## 11. Three distinct state machines

Do not overload one status field with three different meanings.

### Work lifecycle state

```text
Backlog / Todo
In Progress
In Review
Done
Blocked / Deferred as supported
```

### Execution state

```text
Unclaimed
Preparing
Running
Waiting
Retrying
Escalated
Stopped
```

### Evidence state

```text
IMPLEMENTED
VALIDATED
REVIEWED
MERGED / INTEGRATED
SYSTEM_VERIFIED
RUNTIME_APPLIED
RUNTIME_VERIFIED
USER_ACCEPTED
```

A tracker may show `In Review` while an execution run is retrying and runtime evidence is still `NOT_REQUIRED` or pending.

## 12. Done semantics

`Done` means the Work Item's own required acceptance and evidence are complete.

```text
Done
= acceptance satisfied
+ required implementation evidence
+ required independent review
+ required integrated-system verification
+ required runtime/external read-back
+ required human/user acceptance
```

Inapplicable gates should be explicitly `NOT_REQUIRED`; they should not be silently omitted when their applicability matters.

## 13. Finding disposition

Review and verification findings should be separated from work lifecycle state.

```text
BLOCKER
= current capability does not satisfy its contract; repair same scope

RESIDUAL
= capability is valid but a bounded weakness remains; create finite follow-up

HYPOTHESIS
= needs future/runtime evidence; record falsifiable condition

HUMAN_REQUIRED
= reserved authority or unresolved contract decision
```

## 14. Decomposition quality checks

Before creating work, Foundry should be able to flag:

- mega items with several independent outcomes
- items whose acceptance criteria are implementation steps rather than outcomes
- circular or missing dependencies
- mixed authority classes that should be separated
- ambiguous ownership of a shared write surface
- duplicate work already represented elsewhere
- discovery and mutation combined despite unresolved scope
- work that cannot be verified with the declared evidence profile

## 15. Practical objective

A work model is successful when a new agent can read one Work Item, reconstruct the required current truth, execute within bounded authority, produce evidence, and close or escalate the work without relying on hidden historical conversation.