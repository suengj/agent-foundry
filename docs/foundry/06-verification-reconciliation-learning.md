# Verification, Reconciliation, and Learning

## 1. Purpose

Foundry should close work by comparing declared intent with implementation evidence and actual system state. Completion is a reconciliation problem, not a status label or agent narrative.

```text
Work Item contract
+ candidate/integrated implementation
+ deterministic evidence
+ independent review when required
+ runtime/external read-back when required
        ↓
Reconciliation
        ↓
Evidence state + Work state update + learning
```

## 2. Observe versus verify

Separate observation from correctness.

```text
Observe
= command completed, file exists, PR merged, process running

Verify
= required contract is satisfied, authoritative consumer is wired,
  external state reflects the intended change, no forbidden behavior remains
```

Exit code `0`, a generated file, or an agent report is not sufficient correctness evidence on its own.

## 3. Evidence classes

Common evidence types:

- repository revision / diff
- deterministic test result
- static/type/lint result
- schema or contract validation
- reproducible calculation
- statistical evaluation
- independent review decision
- integration/system proof
- merged/integrated identity
- runtime/external read-back
- human/user acceptance when required

Evidence should retain provenance, freshness, and the revision or external state it actually proves.

## 4. Evidence state

Do not compress all completion into one `PASS`.

```text
IMPLEMENTED
VALIDATED
REVIEWED
INTEGRATED
SYSTEM_VERIFIED
RUNTIME_APPLIED
RUNTIME_VERIFIED
USER_ACCEPTED
```

Each Work Item declares which states are required and which are `NOT_REQUIRED`.

## 5. Evidence Bundle

Conceptual structured result:

```yaml
work_item_id: WORK-123
run_id: RUN-456

identity:
  base_revision: abc123
  candidate_revision: def456
  integrated_revision: null

evidence:
  - type: deterministic-test
    result: pass
    source: artifact-ref
  - type: review
    result: pass
    source: review-ref

unresolved:
  blockers: []
  residuals: []
  hypotheses: []

provenance: []
```

## 6. Reviewer, system verifier, runtime verifier

These questions are different:

### Reviewer

> Is the candidate change consistent with the Work Item and durable contracts?

### System / integration verifier

> In the integrated current system, do producer, contract, consumer, and effect actually connect?

### Runtime / external-state verifier

> Did the intended revision/configuration actually apply, and does the real external state match the expected behavior?

A project may combine roles for low-consequence work but should preserve the semantic distinction.

## 7. Reconciliation across systems

Foundry should reconcile rather than mirror authoritative external state.

```text
Tracker
= work intent, priority, dependency, lifecycle

Repository
= implementation and review evidence

Runtime / external systems
= actual applied state

Foundry
= links identities, evaluates required evidence, records execution receipts,
  and proposes/executes authorized state updates
```

The Manager should be able to restart and reconstruct current work from external authorities plus versioned Foundry artifacts rather than hidden session memory.

## 8. Execution Receipt

A completed or stopped run should produce a concise receipt:

```text
Work Item identity
run identity
role/workflow
base/candidate/integrated revision
Toolkit and adapter versions
changes/findings
validation evidence
review decision
runtime/external validation
blocker/residual/hypothesis state
budget consumption
cleanup state
next action
```

The receipt records what happened; it does not become a second live work tracker.

## 9. Finding disposition

```text
BLOCKER
= current contract is not satisfied
→ repair within current causal scope

RESIDUAL
= bounded weakness after acceptance is otherwise valid
→ create finite follow-up work

HYPOTHESIS
= requires future/runtime evidence
→ record falsifiable prediction and evidence condition

HUMAN_REQUIRED
= reserved authority or unresolved material contract choice
→ minimal escalation
```

## 10. Failure taxonomy

Repeated failure should be classified before retrying.

Suggested classes:

- code/implementation
- test/fixture
- environment/dependency
- permission/credential
- missing or stale context
- integration unavailable
- policy conflict
- ambiguous work contract
- invalid work decomposition
- provider/model capacity
- runtime/external dependency

Two or more repeated failures in the same class should increase suspicion of the harness or contract rather than trigger unlimited model retries.

## 11. Learning loop

Project experience should feed improvements through a controlled path.

```text
Execution friction / incident / repeated review finding
        ↓
Learning Record
        ↓
Classify scope
   ├─ project-local
   ├─ toolkit/integration-specific
   └─ Foundry-generalizable
        ↓
bounded change + validation
        ↓
explicit version/adoption
```

A single project event should not automatically become a global Foundry invariant.

## 12. Promotion criteria for global learning

Before promoting a lesson into reusable Foundry behavior, ask:

- does it recur or reveal a structural failure class?
- is it relevant across multiple project types?
- can it be stated without project-specific assumptions?
- can it be validated mechanically or operationally?
- does it belong in policy, control, work decomposition, toolkit metadata, Skill, workflow, or documentation?
- could enforcing it globally damage a different project type?

Project-specific workarounds should remain local unless they pass this test.

## 13. Dogfood and adoption metrics

Useful measurements during real-project adoption include:

- Project Manifest corrections
- readiness gaps discovered after execution began
- generated Work Item correction rate
- decomposition defects / mega-item detection
- Toolkit over-selection and under-selection
- manual prompt additions
- missing/stale context incidents
- permission denied / overreach events
- integration authentication/health failures
- review rework rate
- evidence completeness
- human escalation rate
- repeated failure classes
- time from Work Item ready to verified closure

These metrics evaluate the Foundry system, not the quality of a particular model alone.

## 14. Versioned improvement

Changes to schemas, capability metadata, workflows, or adapters should be versioned and tested for compatibility. A new global registry version should not silently change a project's locked toolkit.

The normal learning path is:

```text
observation
→ issue / proposal
→ implementation
→ tests / dogfood
→ versioned release
→ explicit project upgrade
```

## 15. Practical objective

A reliable Foundry should make it possible to answer, from artifacts rather than memory:

> What was requested, what actually changed, which evidence proves it, what remains uncertain, which external systems agree on the current state, and what should change in the project or Foundry as a result?