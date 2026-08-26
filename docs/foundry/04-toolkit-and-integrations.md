# Toolkit and Integrations

## 1. Purpose

A project should not receive every available Skill, tool, connector, provider, or permission. Foundry resolves a bounded toolkit from project characteristics, current work, and policy.

```text
Foundry Capability Registry
        ↓
Project Profile / Manifest
        ↓
Project Toolkit
        ↓
Work Item + fresh truth
        ↓
Task Toolkit
        ↓
Execution Bundle
```

## 2. Capability Registry

The global registry can describe:

```text
Roles
Workflows
Skills
Tools / Tool Interface Profiles
Connectors / MCP servers / APIs
Validators
Permission profiles
Execution budget profiles
Context sources / convention indexes
Provider capability profiles
Render/adaptation profiles
```

The registry is a catalog of available building blocks, not a set of capabilities automatically exposed to every project.

## 3. Project Toolkit

The Project Toolkit is the approved and version-pinned capability universe for one project.

It answers:

- which roles may exist;
- which workflows are available;
- which Skills can be selected;
- which tools/connectors may be used;
- which permission and execution-budget profiles are allowed;
- which validators/evidence profiles apply;
- which provider capability classes are permitted.

## 4. Task Toolkit

The Task Toolkit is the minimum subset needed for one Work Item/run.

```text
Project Toolkit
- capabilities irrelevant to current work
- unavailable integrations
- permissions not required by the current role
- standards/context irrelevant to the current work
+ workflow-required components
+ temporary tighter restrictions
= Task Toolkit
```

Least capability is both a safety principle and a context-quality principle.

## 5. Resolution stages

A practical resolver should combine deterministic filtering with bounded reasoning.

```text
1. Project Profile + Work Item requirements
2. Capability matching
3. Hard policy filtering
4. Integration health and availability
5. Workflow requirements
6. Role separation / ownership validation
7. Skill/context relevance selection
8. Provider/model resolution
9. Final completeness validation
```

Domain tags may help select specialized Skills, but authority and control are primarily derived from external effect, consequence, reversibility, access sensitivity, and assurance requirements.

## 6. Capability metadata

A Skill or tool should carry enough metadata for deterministic discovery before full instructions are loaded.

Example:

```yaml
id: deterministic-test
kind: skill
version: 1.0.0

description: Run project-approved deterministic tests and return normalized evidence.

provides:
  - validation.test

triggers:
  artifact_types: [source-code]
  work_modes: [implementation, validation]

roles:
  allowed: [builder, validator]

permissions:
  external_write: false

inputs:
  - changed_scope

outputs:
  - test_evidence
```

Discovery metadata should stay compact. Full Skill/procedure content is loaded only after selection.

## 7. Progressive disclosure and convention relevance

Project intake may discover many conventions and standards. They should be indexed with short descriptions and relevance metadata rather than copied into every Execution Bundle.

```text
Convention / standard index
        ↓
Project Profile + Work Item + Role
        ↓ relevance selection
Applicable conventions only
        ↓
Execution Bundle context
```

This keeps project context lean while preserving local architectural intent.

A discovered convention is not automatically a hard policy. Preserve source/evidence/confidence and promote it only through the appropriate governance path.

## 8. Tool Interface Profile

A tool is more than an allow/deny capability. Agent performance also depends on how commands, context, and feedback are presented.

A future toolkit should be able to describe an agent-facing interaction profile such as:

```yaml
id: repository-edit
kind: tool-interface
version: 1

capabilities:
  - file.read
  - file.edit
  - repo.search

feedback:
  max_context_lines: 120
  normalize_empty_output: true

post_actions:
  - syntax-check

permissions:
  external_write: false
```

V0.1 does not need to implement a custom shell or ACI. It should establish metadata/contracts that future adapters can consume.

## 9. IntegrationSpec

External systems should be modeled separately from procedures.

```yaml
id: work-tracker
kind: integration
transport: mcp        # mcp | api | cli | local-service
version: 1

capabilities:
  - work.read
  - work.write

permissions:
  write_requires: explicit-authority

auth:
  method: oauth
  credential_ref: managed:work-tracker

health:
  required: authenticated
```

An integration is a privilege and state boundary, not merely a convenient tool.

## 10. Credential references

Foundry configuration should never require raw secret values in version-controlled project files.

Use references to external credential providers:

```text
env:NAME
os-keychain:entry
managed:connection-id
vault:path-or-role
workload-identity:profile
ci-secret:name
```

Conceptual schema:

```yaml
auth:
  method: token
  credential_ref: env:SERVICE_TOKEN
```

Forbidden pattern:

```yaml
api_key: actual-secret-value
```

Foundry may validate that a reference exists or that an integration can authenticate, but the secret value belongs to the credential provider or execution environment.

### Embedded-secret guard (write/render boundary)

Foundry enforces the public promise — secrets are referenced, never embedded — at two layers with different scope:

**Model validation (structural, fail-closed).** Credential-shaped keys (`api_key`, `token`, `secret`, and similar) are rejected when the value is not a `SecretRef`. This is structural matching with near-zero false-positive rate.

**Serialization boundary (write/render).** When a model is dumped to JSON or YAML (`dump_json`, `dump_yaml`, and the raw dump helpers), a scanner runs before bytes are written:

- **Tier A — known vendor credential formats** (OpenAI-style `sk-` keys with a closed label set — `live`, `test`, `proj`, `svcacct`, `admin`; GitHub tokens; Slack tokens; AWS access keys; Google API keys; GitLab/npm/Doppler/Stripe prefixes; PEM/PGP private-key armor; JWTs whose JOSE header carries an `alg` member in any position) in string **values** or dict **keys** cause a hard failure. Strong prefixes match on format alone. The weak `sk-` prefix collides with ordinary language (`risk-`, `task-`, `mask-`), so it is discriminated structurally: an unbroken alphanumeric body of 16+, or — since real project keys are base64url and may contain `-` — a hyphenated body of 16+ that also carries a digit and an upper-case character. `sk-live-feature-toggle-enabled` stays writable; `sk-proj-<base64url>` does not. `SecretRef` mappings are traversed field-by-field; credential-shaped values in `name`, `scope`, or `version` are not exempt.
- **Tier B — value entropy** is reported as an **advisory diagnostic only** and deliberately does **not** block. Entropy cannot distinguish a credential from a legitimate opaque identifier without unacceptable false positives. This is a known limitation, not total coverage.
- Detection runs at the serialization boundary, **not** in model validation. A false positive on Tier A is recoverable: the project can still be loaded and inspected; only the write is refused, with a diagnostic naming the JSON path and the rule that matched (never the secret value).
- A per-path `allow_paths` escape exists for legitimate values that trip Tier A. It is per-path by design, not a global off-switch. Paths are matched structurally: `adapter_options.a.b` means nested keys `a` then `b`, not a literal key `a.b`. Escape a literal dot in a key name with `\\.` (for example `adapter_options.a\\.b`). The bracket form `[key]` marks a credential used as a dict **key** (distinct from a literal key named `@key`, which encodes as `y.@key`). Diagnostic messages use the escaped dotted form so the reported path can be pasted directly into `allow_paths`.
- Two scope limits on that escape are worth stating plainly. All credential-shaped **keys** of one mapping share the single path `<mapping>[key]`, so allowing that path allows every such key in that mapping, including ones added later — prefer removing the credential over allowing the path. And a path *segment* that is itself a Tier A credential is rendered as `[redacted:<rule>]` rather than verbatim, so such a path is deliberately **not** pasteable into `allow_paths`: the supported fix is to stop using a credential as a key.

**Residual risk (honest boundary).** An unrecognised credential format stored under a generic key (for example `adapter_options.custom_option`) can still serialize. Foundry is not a secret vault. `SecretRef` is the supported mechanism for credential material.

## 11. Identity and delegation

Where supported, prefer delegated or workload identity over long-lived shared credentials.

The desired boundary is:

```text
Agent role / Execution Bundle
        ↓ scoped capability
Integration adapter
        ↓ delegated identity / SecretRef resolution
External system
```

Agents should not need to reason about or reproduce secret material in their natural-language output.

## 12. Integration lifecycle / health

Presence in configuration is not equivalent to usability.

Track integration state explicitly:

```text
desired
available
configured
authenticated
authorized
healthy
degraded
unavailable
```

A Task Toolkit requiring `work.write` must fail preflight if the required integration is not both authorized and sufficiently healthy.

## 13. Configuration split

Recommended project-side separation:

```text
.foundry/project.yaml
= project characteristics, authority inputs, desired integration IDs

.foundry/toolkit.lock.yaml
= resolved/pinned capability versions and integration profiles

.foundry/integrations.yaml
= integration declarations + SecretRefs, never raw secrets

local/runtime configuration
= environment-specific endpoints and credential-provider bindings where appropriate

credential provider
= actual secrets
```

Environment-specific configuration must not be confused with project-level authority. A credential being available does not imply that a task is authorized to use it.

## 14. Toolkit lock and compatibility

A resolved toolkit should be reproducible.

Conceptual lock:

```yaml
schema_version: 1
foundry_compat: ">=0.1,<0.2"

skills:
  deterministic-test: 1.0.0

workflows:
  builder-reviewer: 1.1.0

integrations:
  repository: adapter-v1

validators:
  evidence-contract: 1.0.0
```

Updating the global registry should not silently change an existing project's resolved behavior. Toolkit upgrades should be explicit and validate compatibility.

## 15. Capability health

The resolver should distinguish declared capability from effective capability.

```text
desired
available
compatible
authorized
healthy
```

Examples of failure:

- Skill metadata exists but required executable is absent;
- connector is installed but authentication expired;
- provider exists but model/cost policy forbids the role;
- runtime verifier exists but target environment cannot be read.

These should become typed preflight failures rather than mid-run surprises.

## 16. Provider resolution

Provider/model selection is downstream of role and capability requirements.

```text
Work Item
→ role
→ logical capability class
→ allowed provider policy
→ current availability / cost / health
→ exact provider/model/effort
```

Provider identities should remain adapters at the edge, not core role definitions.

## 17. MCP facade principle

MCP is a supported interface for Foundry capabilities, not the core architecture.

```text
              Foundry Core
                  │
       ┌──────────┼──────────┐
       ↓          ↓          ↓
      CLI     Python API   MCP Server
```

Core inspection, profiling, resolution, compilation, and validation should be testable without an MCP host.

Candidate MCP tools:

```text
foundry.inspect
foundry.profile
foundry.adopt_preview
foundry.adopt_apply
foundry.work_plan
foundry.resolve_toolkit
foundry.integration_check
foundry.compile
foundry.validate
foundry.reconcile
```

Candidate resources:

```text
foundry://project/profile
foundry://project/manifest
foundry://project/adoption
foundry://project/toolkit
foundry://project/work
foundry://task/current
```

### Project path handling

For MCP `2026-07-28` and newer designs, do not build new project selection around MCP Roots, which is deprecated for new implementations.

Prefer:

- explicit `project_path` tool parameters;
- project resource URIs;
- server configuration;
- environment-specific adapter configuration.

Foundry itself must still canonicalize paths, enforce allowed-root containment, reject traversal/symlink escape where applicable, and apply read/write policy independently of MCP metadata.

### Long-running tasks

The MCP Tasks extension is a possible future transport for long-running inspect/adopt/validate operations. It should not be required to prove V0.1 Core correctness.

## 18. Declarative policy input to toolkit resolution

Avoid toolkit selection through hard-coded named project types.

Prefer composable predicates:

```yaml
when:
  consequence: high
  external_effect: true
require:
  - independent-review
forbid:
  - self-approval
```

The resolver should combine:

1. deterministic invariants;
2. declarative policy rules;
3. bounded reasoning for ambiguous selection among already-permitted alternatives.

A reasoning result may tighten capability selection, but must not silently grant broader authority than declared/confirmed project inputs permit.

## 19. Explainable resolution

Toolkit outputs should eventually retain enough decision trace to answer:

```text
Why was this role selected?
Why was this Skill selected?
Why is this integration required?
Why was this capability excluded?
Which project facts and policies caused the decision?
```

This explanation/provenance becomes part of validation and audit rather than hidden reasoning state.

## 20. Practical objective

A toolkit is successful when project configuration can reproducibly answer:

> What may this project use, what does this Work Item actually need, which standards and Skills are relevant, which external systems are authorized and healthy, and how can the execution environment obtain the required capability without exposing unnecessary privileges or secrets?
