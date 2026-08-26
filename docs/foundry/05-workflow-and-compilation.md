# Workflow, Agent Graph, and Task-time Compilation

## 1. Purpose

Foundry's project bootstrap determines the approved operating environment. Task-time compilation determines what one concrete run is allowed and required to do.

```text
Project Constitution
+ Project Manifest
+ Project Toolkit
+ Current Task
+ Fresh Project/Repository/Runtime Truth
        ↓
Execution Compiler
        ↓
Execution Bundle
        ↓
Agent / Agent Graph
```

The Execution Bundle is the practical bridge from abstract governance to agent execution.

## 2. Task Contract

The Task Contract should contain the execution delta, not a duplicate of the entire project history.

Minimum fields:

```text
Task identity
Objective
Current verified facts
Scope
Out of scope
Acceptance criteria
Dependencies
Authority / consequence class
Required evidence
Stop / escalation conditions
```

The Task Contract should remain stable during execution. Repair cycles should add bounded deltas instead of silently rewriting the objective.

## 3. Workflow selection

A workflow is selected from the Project Toolkit based on task characteristics.

Examples:

### Simple bounded task

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

### High-consequence apply path

```text
Builder
→ Deterministic Validation
→ Independent Reviewer
→ Integration
→ Apply/Deploy Authority Gate
→ Runtime Verifier
```

The project domain does not by itself choose the pattern. Ambiguity, external effect, consequence, reversibility and required assurance are more important inputs.

## 4. Agent Graph node contract

Each node should be a state-transformation contract rather than just a role label.

Minimum conceptual fields:

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

## 5. Edge contract

An edge defines what evidence permits the next transition.

Example:

```text
Builder → Validator
requires:
- candidate change exists
- scope boundary respected

Validator → Reviewer
requires:
- required deterministic checks complete
- validation evidence present

Reviewer → Integrator
requires:
- BLOCKER = 0
- required MAJOR findings resolved

Integrator → Runtime Verifier
requires:
- target revision fixed
- apply/deploy separately authorized where required
```

This prevents "agent says done" from functioning as a graph edge.

## 6. Execution Bundle

The compiler should eventually emit one structured artifact containing at least:

```yaml
execution:
  project_id: example
  task_id: TASK-123
  run_id: generated
  base_revision: abc123

role:
  role_id: builder
  authority: bounded-write

objective:
  summary: "..."
  acceptance: []

context:
  references: []
  compiled_facts: []

policy:
  applicable_rules: []

scope:
  allowed_paths: []
  forbidden_paths: []

capabilities:
  skills: []
  tools: []
  connectors: []

execution_profile:
  provider: resolved-later-or-here
  model: resolved
  effort: resolved
  retries: 1

verification:
  required_evidence: []

output:
  contract: handoff-or-receipt-schema

stop:
  conditions: []
  escalation_target: manager
```

The exact schema will be implemented later; the important boundary is that the bundle is generated from canonical sources and should be reproducible.

## 7. Context compilation

The compiler should not concatenate every document.

It should select context in layers:

```text
Base invariants
+ role contract
+ project-local invariants
+ relevant technical context
+ current task
+ applicable policy subset
+ current verified state
+ selected Skills/procedures
+ output contract
```

Context sources should retain provenance so an agent or reviewer can trace a statement back to its canonical source.

## 8. Applicable-policy resolution

A task should receive only rules that apply to its scope and capabilities.

Example:

```text
Task = local documentation update
→ repository write policy
→ review/evidence policy
→ no deployment policy context
→ no production connector

Task = runtime-changing service update
→ repository write policy
→ runtime mutation policy
→ deploy/apply gate
→ runtime-readback requirement
→ rollback conditions
```

## 9. Task Toolkit resolution

The Task Toolkit is compiled after workflow selection.

```text
Project Toolkit
- capabilities irrelevant to current task
+ temporary tighter restrictions
+ current workflow-required components
= Task Toolkit
```

This is a least-capability principle, not merely a context-size optimization.

## 10. Provider / model resolution

Resolve execution substrate after task and role requirements:

```text
Task requirements
→ role
→ logical capability requirement
→ provider policy
→ runtime availability / cost class
→ model / effort
```

A task requiring exact model identity can forbid `Auto`; a routine task may allow it. Provider aliases must remain outside the core role definitions.

## 11. Preflight validation

Before dispatch, Foundry should validate:

- required inputs exist
- Project Toolkit contains required capabilities
- no hard policy conflict
- role separation rules hold
- write scopes do not collide
- required connectors are authorized
- output/evidence contracts are known
- provider/model resolution is permitted
- task/run identity and base revision are pinned

Invalid configuration should fail before agent execution where practical.

## 12. Compilation outputs

The code implementation should favor structured canonical outputs:

- `project manifest`
- `toolkit lock`
- `task contract`
- `execution bundle`
- `handoff`
- `evidence bundle`
- `review decision`
- `execution receipt`

Markdown can then be rendered from these objects for CLI/provider consumption.

## 13. Practical objective

A successful Foundry compiler should make this possible:

```text
Linear/Task input + project truth
→ deterministic configuration resolution
→ small, role-specific execution package
→ bounded agent execution
→ structured handoff/evidence
```

The human should not have to repeatedly construct a giant prompt or interpret terminal screenshots to move the workflow forward.
