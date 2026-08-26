# Orchestration and Interaction

## 1. Purpose

Orchestration determines who does what and when. Interaction defines how agents and systems exchange authority, context, evidence, uncertainty, and decisions without relying on ambiguous free-form conversation.

```text
Work Item
→ workflow selection
→ role assignment
→ Task Toolkit
→ node/edge contracts
→ execution
→ typed handoff / evidence / decisions
```

## 2. Role model

Common logical roles:

- Manager / Router
- Explorer / Investigator
- Architect / Decision Owner when needed
- Builder / Writer
- Validator / Tester
- Reviewer / Judge
- Integrator
- Runtime / External-state Verifier

Roles are responsibility contracts, not model names. A small task may combine compatible roles; high-consequence tasks should separate conflicting authority surfaces.

## 3. Role contract

A role should define:

```text
responsibility
required inputs
allowed decisions
denied decisions
write scope
allowed capabilities
required outputs
escalation target
independence constraints
```

Examples:

- Builder may modify the owned change surface but does not approve its own critical review.
- Reviewer evaluates the original contract, candidate change, and evidence; it should not inherit Builder conclusions as facts.
- Integrator owns merge/integration identity, not source implementation correctness.
- Runtime Verifier reads actual applied state and distinguishes deployment from source merge.

## 4. Workflow selection

Workflow selection is based on work characteristics rather than project labels.

### Simple bounded work

```text
Builder
→ Validator
→ Result
```

### Independent review

```text
Manager
→ Builder
→ Validator
→ Reviewer
→ Integrator
```

### Ambiguous investigation

```text
Investigator A ─┐
Investigator B ─┼→ Synthesizer / Decision Owner
Investigator C ─┘
```

### High-consequence external apply

```text
Builder
→ Deterministic Validation
→ Independent Reviewer
→ Integrator
→ Apply Authority Gate
→ Runtime / External-state Verifier
```

### Brownfield adoption slice

```text
Explorer
→ Gap Classification
→ Manager
→ Bounded Retrofit Builder
→ Validator / Reviewer
→ Re-inspect current truth
```

## 5. Agent Graph node contract

Each node is a state-transformation contract, not merely a role label.

```yaml
node_id: builder
role: builder
inputs: []
outputs: []
required_capabilities: []
allowed_tools: []
write_scope: []
success_criteria: []
failure_codes: []
retry_budget: 1
escalation_target: manager
```

## 6. Edge contract

Edges should be evidence-gated.

```text
Builder → Validator
requires candidate change + scope compliance

Validator → Reviewer
requires declared validation evidence

Reviewer → Integrator
requires no unresolved blocking findings

Integrator → Runtime Verifier
requires fixed integrated identity + separate apply authority when applicable
```

`agent says done` is never a sufficient graph edge.

## 7. Interaction message types

Material agent-to-agent communication should use a small vocabulary:

```text
REQUEST
DELEGATION
HANDOFF
EVIDENCE
DECISION
REJECTION
BLOCKER
ESCALATION
STATE_UPDATE
```

Not every chat sentence needs structure; transitions that affect authority, work ownership, acceptance, or state should be structured.

## 8. Common message envelope

A material interaction should be able to carry:

```yaml
message_type: HANDOFF
work_item_id: WORK-123
run_id: RUN-456
sender:
  role: builder
receiver:
  role: reviewer

state:
  base_revision: abc123
  candidate_revision: def456

summary: "..."
changed_or_learned: []
evidence_refs: []
known_risks: []
unknowns: []
assumptions: []
requested_action: review
requested_decision: null
authority: advisory
provenance: []
```

## 9. Authority signaling

Messages must distinguish among:

```text
INFORMATION
RECOMMENDATION
REQUEST
DELEGATED_INSTRUCTION
APPROVAL
REJECTION
RESERVED_AUTHORITY_DECISION
```

A reviewer suggestion is not automatically a manager instruction; a tool output is not an authority grant; an agent recommendation is not an approval.

## 10. Semantic vocabulary

Foundry should define state words centrally so agents do not reinterpret them.

```text
IMPLEMENTED
!= VALIDATED
!= REVIEWED
!= INTEGRATED
!= SYSTEM_VERIFIED
!= RUNTIME_APPLIED
!= RUNTIME_VERIFIED
```

Similarly:

```text
BLOCKER
RESIDUAL
HYPOTHESIS
HUMAN_REQUIRED
```

are finding/decision categories, not interchangeable generic failure states.

## 11. Context transfer

Handoffs should transfer the minimum context needed to continue correctly:

- Work Item identity and frozen objective
- fresh verified state and revision identity
- applicable contracts/policy references
- completed changes/findings
- evidence references
- unresolved risks/unknowns
- requested next decision or action

Avoid transferring entire conversation histories when structured artifacts can carry the necessary state.

## 12. Interpretation and ambiguity

When an agent encounters ambiguity, it should classify it rather than silently broaden scope.

```text
LOW
= bounded assumption, recorded in output

MATERIAL
= could change acceptance, authority, architecture, external effect, or work decomposition
→ Manager / owner decision

RESERVED
= requires human or explicitly reserved authority
```

## 13. Write ownership

Before parallel execution, the orchestrator should verify canonical ownership surfaces.

Two agents are not independent merely because they edit different files. Shared schemas, APIs, runtime contracts, configuration, evaluation definitions, and authority surfaces can create write collisions across files.

Default high-integrity pattern:

```text
one causal Work Item
→ one primary write owner
→ independent read-only support/review as needed
```

## 14. Repair loop

A fixable finding normally returns to the owning execution path rather than creating a new authority decision.

```text
candidate
→ finding
→ bounded repair
→ targeted verification
→ delta review
→ continue original acceptance
```

Repeated failures of the same class should trigger diagnosis of the harness, context, fixture, permission, or task contract—not unlimited prompt repetition.

## 15. Execution Bundle

Task-time compilation should eventually emit a structured bundle containing:

```text
project/run identity
Work Item contract
role and authority
applicable context and policies
Task Toolkit
allowed/forbidden scopes
resolved integration/provider profile
budget/retry limits
verification requirements
interaction/output contract
stop/escalation conditions
```

Markdown or provider-specific prompts are rendered from this bundle rather than serving as the independent source of truth.