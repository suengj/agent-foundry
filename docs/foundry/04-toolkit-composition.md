# Toolkit Composition and Resolution

## 1. Purpose

Agent Foundry should not deliver a fixed bundle of Markdown files, prompts, Skills and tools to every project.

A project is first classified, then Foundry resolves the smallest approved capability set that can operate that project safely and effectively.

```text
Foundry Capability Registry
        ↓
Project Manifest
        ↓
Capability Requirements
        ↓
Toolkit Resolution
        ↓
Project Toolkit
        ↓
Current Task + Current Truth
        ↓
Task Toolkit
```

## 2. Three toolkit levels

### Foundry Capability Registry

The complete set of components Foundry knows how to compose:

- roles
- workflows
- Skills
- tools
- MCP/connectors
- validators
- context sources/templates
- permission profiles
- provider/model capability profiles
- output/evidence schemas

This is a registry, not context that every agent receives.

### Project Toolkit

The approved capability universe for one project.

It answers:

- Which roles can exist here?
- Which workflows are appropriate?
- Which Skills are compatible with this project?
- Which tools and external connectors may be used?
- What permission ceilings apply?
- Which validators and evidence types are mandatory or available?
- Which provider capability classes may serve which roles?

### Task Toolkit

The minimum subset needed for the current task.

A project may support deployment, database writes and runtime inspection, while a documentation task should receive none of those capabilities unless necessary.

## 3. Toolkit component types

### Roles

Logical responsibilities such as Builder, Reviewer, Investigator or Runtime Verifier.

### Workflows

Reusable role/transition graphs such as:

- single bounded worker
- builder → validator
- manager → builder → reviewer
- investigator ensemble → synthesizer
- builder → independent judge → integrator
- release / runtime verification
- incident response
- shadow / canary promotion

### Skills

Repeatable procedures performed by a role. Examples are code review, repository inspection, test execution, RCA, statistical evaluation, documentation generation or release verification.

A Skill does not own the policy that authorizes its use.

### Tools

Direct execution capabilities such as shell, filesystem, Git, test runner, browser or structured data processing.

### MCP / Connectors

External boundaries such as GitHub, Linear, databases, deployment systems, cloud services, communication platforms or external APIs.

Connectors are privilege surfaces, not merely information sources.

### Validators

Deterministic or bounded verification capabilities such as schema checks, unit tests, linters, statistical gates, contract validators, independent review and runtime read-back.

### Context Sources

Canonical documents and truth sources from which task context may be compiled.

### Permission Profiles

Reusable control profiles describing filesystem, external write, network, credential, deployment and other authority ceilings.

### Provider Profiles

Current provider/model capability and cost/availability policy. Providers are adapters beneath logical roles and capability requirements.

## 4. Resolution pipeline

Toolkit selection should combine deterministic filtering and bounded agent reasoning.

```text
1. Read Project Manifest
2. Derive required capabilities
3. Apply hard policy / authority filters
4. Match compatible registry components
5. Apply workflow requirements and separation constraints
6. Select candidate Project Toolkit
7. Validate completeness / conflicts
8. Pin resolved versions
```

At task time:

```text
1. Read Task Contract and fresh truth
2. Determine required workflow nodes
3. Select minimum roles / Skills / tools
4. Remove capabilities not required by the task
5. Apply temporary tighter controls
6. Resolve provider/model/effort
7. Validate final Task Toolkit
```

## 5. Deterministic rules before LLM discretion

Examples of deterministic resolution:

```text
Task modifies repository
→ repository-write capability required

Project prohibits external writes for this task class
→ all write-capable external connectors excluded

Project requires independent review for high-consequence changes
→ reviewer node required
→ reviewer cannot equal builder identity

Task does not request deploy/apply
→ deployment capability excluded

Assurance requires runtime-readback
→ runtime verifier capability required before terminal completion
```

LLM/manager judgment is better suited to questions such as:

- Is this task simple enough for one worker?
- Does ambiguous RCA justify multiple investigators?
- Is an architect/decision owner necessary?
- Which of several compatible Skills is the best fit?

## 6. Registry metadata

Components need metadata so the resolver can reason over them without reading full procedural content.

Conceptual Skill metadata:

```yaml
skill_id: python-test
version: 1.0.0
provides:
  - deterministic-test-execution
applicable_when:
  languages: [python]
roles_allowed:
  - builder
  - validator
permissions:
  filesystem: repository
  external_write: false
inputs:
  - test_target
outputs:
  - validation_evidence
```

Conceptual workflow metadata:

```yaml
workflow_id: builder-reviewer
version: 1.0.0
requires:
  independent_review: true
nodes:
  - builder
  - validator
  - reviewer
terminal_evidence:
  - validation
  - review-decision
```

Conceptual connector metadata:

```yaml
connector_id: github
capabilities:
  - repository-read
  - repository-write
  - pull-request
external_effect: shared-service-write
requires_authority: task-defined
```

## 7. Progressive disclosure

A registry item has at least two surfaces:

```text
Metadata
= cheap discovery / matching surface

Full instructions / Skill / adapter
= loaded only after selection
```

This prevents the Capability Registry from becoming a giant prompt.

## 8. Provider resolution

Provider/model selection happens late:

```text
Task
→ consequence / ambiguity / verification needs
→ role
→ logical capability class
→ allowed providers
→ currently available model
→ effort / cost policy
→ exact session resolution
```

The toolkit may specify that a role needs `critical-independent-review`; it should not make a temporary product alias the permanent architecture authority.

## 9. Versioning and lock

Toolkit resolution should be reproducible.

```text
Project Manifest
+ registry versions
+ policy versions
       ↓
Toolkit Resolver
       ↓
Project Toolkit
       ↓
toolkit.lock
```

Conceptual lock content:

```yaml
playbook_ref: daa487c...
roles:
  builder: 1.0.0
  reviewer: 1.0.0
workflows:
  builder-reviewer: 1.1.0
skills:
  python-test: 1.2.0
adapters:
  codex: 1.0.0
```

A registry update should not silently alter an existing project's behavior. Toolkit upgrades should be explicit and reviewable.

## 10. Project-specific extensions

A project may add local domain Skills, validators or workflows when the global registry is insufficient.

Rules:

- local components must declare the same metadata contract
- local components may tighten inherited policy
- a local component cannot grant authority prohibited by the project/global policy
- reusable components should eventually be promoted to the Foundry registry rather than copied across projects

## 11. Toolkit output

The Project Toolkit should be a machine-readable resolved configuration, not a long prose document. Human-readable Markdown may be generated from it for inspection.

This leads to a practical direction for the code phase:

```text
Canonical config/schema
→ resolver
→ toolkit.lock / execution config
→ generated Markdown view
```

The Markdown is a projection for humans and agents; it should not become a second independently edited source of truth.
