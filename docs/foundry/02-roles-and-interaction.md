# Roles and Agent Interaction

## 1. Purpose

Agent roles define responsibility and authority. Interaction contracts define how information, evidence and decisions move between those roles.

These are separate concerns:

```text
Role model
= who is responsible for what

Interaction protocol
= what must be transmitted, in what form, and with what authority
```

The interaction protocol is cross-cutting. It applies across planning, implementation, review, integration and runtime verification.

## 2. Core role catalog

The default logical roles are provider-neutral.

| Role | Primary responsibility | Typical authority boundary |
|---|---|---|
| Manager / Orchestrator | classify, plan, route, coordinate, integrate state | coordinates work; should not self-certify high-risk results |
| Explorer / Investigator | inspect repository/system and produce evidence-backed findings | read-only by default |
| Architect / Decision Owner | resolve architecture or high-ambiguity design choices | design authority within assigned scope |
| Builder | create candidate changes | one bounded write scope |
| Validator | run deterministic checks and validate artifacts | validation authority, not product acceptance |
| Reviewer / Judge | independent contract/diff/evidence review | accept/reject findings; should not be original writer |
| Integrator | merge/order/reconcile implementation state | integration authority after required gates |
| Runtime Verifier | confirm deployed/applied state and external read-back | verification only unless deployment authority is separately granted |

Roles are logical contracts, not model names. A provider/model is resolved after the role and task requirements are known.

## 3. Role contract

A role definition should eventually expose at least:

```yaml
role_id: builder
responsibilities: []
may_decide: []
may_not_decide: []
allowed_capabilities: []
default_write_scope: task-defined
required_inputs: []
required_outputs: []
escalation_target: manager
separation_rules: []
```

This makes role separation lintable instead of purely advisory.

## 4. Communication problem

Natural-language-only handoff creates predictable failure modes:

- context loss
- ambiguous meaning of Done / Verified / Approved
- hidden assumptions
- stale repository or runtime state
- unclear authority of a statement
- self-reported evidence
- missing unresolved risks
- task drift during retries

Foundry should therefore keep natural language for reasoning while using typed contracts at important boundaries.

## 5. Canonical message types

The initial protocol should distinguish at least:

| Message type | Purpose |
|---|---|
| `REQUEST` | ask another role to perform bounded work |
| `DELEGATION` | assign responsibility and authority for a subtask |
| `HANDOFF` | transfer work/state to the next actor |
| `EVIDENCE` | transmit verifiable facts/artifacts |
| `DECISION` | record a bounded authority decision |
| `REVIEW_DECISION` | accept/reject/require changes against a contract |
| `BLOCKER` | state why execution cannot safely continue |
| `ESCALATION` | move a decision to a higher authority |
| `STATE_UPDATE` | report a typed execution-state transition |

These may later become schemas rather than standalone files.

## 6. Minimum handoff contract

A practical handoff should carry:

```text
Task identity
Role / sender
Current verified state
What changed or was learned
Evidence references
Known risks / unresolved items
Assumptions introduced
Requested next action or decision
Authority of the request
Provenance / relevant SHA or runtime identity
```

A handoff should not merely say "done" or paste the previous agent's chain of thought.

## 7. Information classes passed between agents

### Task context

- objective
- scope / out-of-scope
- acceptance criteria
- dependencies
- risk / authority class

### Project context

Only the relevant subset:

- architecture/component information
- canonical paths
- domain vocabulary
- runtime topology
- applicable project invariants

### Execution state

- branch/worktree
- base/current SHA
- affected paths
- current workflow node
- retries used
- outstanding blockers

### Evidence

- diff / commit
- test output
- generated artifact
- CI result
- runtime/external read-back
- structured measurement

### Decision context

- decision requested
- options considered when relevant
- authority required
- decision made
- rationale/evidence reference
- expiry or reconsideration condition if temporary

## 8. Interpretation contract

Foundry should maintain a shared vocabulary for states and decisions. At minimum:

```text
IMPLEMENTED
≠ VALIDATED
≠ REVIEWED
≠ MERGED
≠ MAIN_VERIFIED
≠ RUNTIME_APPLIED
≠ RUNTIME_VERIFIED
```

Likewise:

```text
recommendation ≠ authorization
authorization ≠ execution
execution ≠ verification
```

The protocol should make these distinctions explicit in structured fields rather than rely on wording style.

## 9. Authority signaling

Every material request or decision should be classifiable as one of:

- informational
- recommendation
- delegated execution request
- approval
- rejection
- escalation
- human-required decision

An agent must not infer that a recommendation grants new authority.

## 10. Context transfer rules

1. Do not forward the entire conversation by default.
2. Do not forward another agent's narrative as evidence.
3. Pass canonical references and current-state identifiers.
4. Freeze the Task Contract; retries receive a repair delta rather than a rewritten objective.
5. Prefer structured artifacts for handoffs that drive state transitions.
6. Refresh volatile truth at the receiving node when material.
7. Preserve unresolved uncertainty explicitly instead of smoothing it into a confident summary.

## 11. Conflict and escalation

When two agents disagree:

```text
Same factual question
→ obtain stronger/fresher evidence

Different interpretation of a lower-level rule
→ apply authority hierarchy / policy owner

Conflict with hard invariant
→ do not vote; stop or escalate

Missing authority for irreversible/external action
→ HUMAN_REQUIRED or designated authority
```

Multi-agent voting is not a substitute for evidence or authority.

## 12. Future implementation target

The code phase should formalize a small set of boundary objects rather than invent a universal messaging bus first:

- `TaskContract`
- `Handoff`
- `EvidenceBundle`
- `ReviewDecision`
- `Blocker`
- `ExecutionReceipt`

The first objective is lossless, auditable handoff across a bounded workflow, not real-time agent chat infrastructure.
