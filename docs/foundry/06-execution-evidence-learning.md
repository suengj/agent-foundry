# Execution, Evidence, and Learning

## 1. Purpose

Foundry should distinguish execution progress from verified correctness and from externally applied state.

```text
Execute
→ Observe
→ Validate
→ Review
→ Integrate
→ Apply / Deploy when relevant
→ Runtime / External read-back
→ Execution Receipt
→ Audit / Learning
```

Each transition requires evidence appropriate to the project's assurance profile.

## 2. Observe versus Verify

`Observe` asks whether something happened.

Examples:

- a command exited
- a file was created
- a test runner produced output
- an agent returned a message

`Verify` asks whether the result satisfies the contract.

Examples:

- changed behavior matches acceptance criteria
- required regression checks pass
- review found no unresolved blocker
- deployed runtime is actually using the intended revision/config

A successful command exit is execution evidence, not automatically correctness evidence.

## 3. Canonical execution states

Foundry should avoid one overloaded `DONE` state.

A generic state vocabulary can include:

```text
PLANNED
COMPILED
DISPATCHED
IMPLEMENTED
VALIDATED
REVIEWED
INTEGRATED / MERGED
MAIN_VERIFIED
APPLIED
RUNTIME_VERIFIED
BLOCKED
HUMAN_REQUIRED
FAILED
```

Not every project uses every state, but the semantics must remain distinct.

## 4. Evidence classes

Evidence can include:

- repository revision / commit SHA
- diff or generated artifact
- deterministic test output
- lint/type/static-analysis output
- schema validation
- reproducible calculation
- statistical evaluation
- independent review decision
- CI/check result
- external-system read-back
- runtime/config identity
- customer/publication state read-back
- human acceptance where required

The Project Manifest and workflow determine which evidence classes are required for a terminal state.

## 5. Evidence Bundle

A node or agent should return structured evidence rather than only a narrative.

Conceptual structure:

```yaml
evidence_bundle:
  task_id: TASK-123
  run_id: run-001
  producer_role: validator
  base_revision: abc123
  evidence:
    - type: deterministic-test
      source: pytest
      result: pass
      reference: artifact-or-log
  unknowns: []
  limitations: []
```

Evidence should retain provenance, freshness and the identity of the artifact/state it validates.

## 6. Review Decision

Independent review should consume the original Task Contract plus current candidate artifacts/evidence, not merely continue the builder's narrative.

A review decision should record:

- contract reviewed
- candidate revision/artifact
- evidence inspected
- findings by severity
- unresolved uncertainty
- verdict
- required next action

Example verdict vocabulary:

```text
ACCEPT
ACCEPT_WITH_NOTES
CHANGES_REQUIRED
BLOCKED_MISSING_EVIDENCE
HUMAN_REQUIRED
```

## 7. Execution Receipt

The Execution Receipt is the canonical completion/decision receipt for one task/run. It is not a duplicate Work SSOT.

It should answer:

- what task was executed
- what configuration/toolkit/workflow was resolved
- what roles/providers were used
- what changed
- what validation/review occurred
- what revision/artifact was integrated
- whether external/runtime apply occurred
- what external read-back proved
- whether cleanup completed
- what blockers or follow-up remain

Conceptual fields:

```yaml
receipt:
  task_id: TASK-123
  run_id: run-001
  status: RUNTIME_VERIFIED
  execution_bundle_ref: ...
  artifacts: []
  evidence: []
  review: ...
  integration: ...
  runtime: ...
  blockers: []
  cleanup: ...
```

## 8. Evidence-driven completion

Terminal completion is a policy decision over evidence:

```text
Acceptance Criteria
+ required deterministic validation
+ independent review when required
+ integration evidence when required
+ external/runtime read-back when required
= completion state
```

Agent self-report can be included as context but cannot substitute for a required evidence class.

## 9. Failure classification

Repeated failure should be classified before retrying.

Initial generic categories:

- task contract / ambiguity
- missing or stale context
- code / implementation
- environment / dependency
- permission / authority
- tool / connector
- validation / evaluator
- external dependency
- workflow / coordination
- harness / policy mismatch

Repeated identical retries should stop. If the same failure family recurs, the likely fix may belong to the harness, workflow, Skill or contract rather than the prompt.

## 10. Incident and decision records

Not every failure becomes a constitutional rule.

Use different feedback artifacts:

### Decision record

For durable architecture, policy interpretation, exception or trade-off decisions.

### Incident record

For a material execution/runtime failure, including:

- what happened
- affected scope
- evidence
- root cause
- violated assumption/control
- recovery
- prevention layer

### Precedent

Only recurring or interpretively useful decisions should be promoted to precedent.

## 11. Feedback destination

Learning should modify the lowest appropriate durable layer.

```text
One task-specific mistake
→ Task/implementation fix

Repeatable procedure weakness
→ Skill improvement

Workflow/coordination weakness
→ Workflow / Agent Graph improvement

Missing executable boundary
→ Harness / validator improvement

Incorrect reusable operating rule
→ Policy amendment

Fundamental authority/invariant change
→ Constitution amendment
```

This prevents the Constitution from becoming an incident log.

## 12. Learning does not mean autonomous rule mutation

Foundry may generate an `AmendmentProposal`, but high-authority policy should not silently self-modify from one execution result.

```text
Evidence / incident
→ analysis
→ proposed change
→ appropriate authority/review
→ versioned adoption
```

## 13. SSOT relationship

- Linear remains Work SSOT for current issue/status/priority.
- GitHub remains Implementation SSOT for code/config/tests/revisions.
- Runtime/external systems remain factual authority for applied/live state.
- Execution Receipt is a task completion receipt, not a replacement status board.
- Foundry-generated Markdown views should be projections from canonical structured data where possible.
