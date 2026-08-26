# Toolkit and Integrations

## 1. Purpose

A project should not receive every available Skill, tool, connector, provider, or permission. Foundry resolves a bounded toolkit from project characteristics, current work, and policy.

```text
Foundry Capability Registry
        ↓
Project Manifest
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
Tools
Connectors / MCP servers / APIs
Validators
Permission profiles
Context sources
Provider capability profiles
Render/adaptation profiles
```

The registry is a catalog of available building blocks, not a set of capabilities automatically exposed to every project.

## 3. Project Toolkit

The Project Toolkit is the approved and version-pinned capability universe for one project.

It answers:

- which roles may exist
- which workflows are available
- which Skills can be selected
- which tools/connectors may be used
- which permission profiles are allowed
- which validators/evidence profiles apply
- which provider capability classes are permitted

## 4. Task Toolkit

The Task Toolkit is the minimum subset needed for one Work Item/run.

```text
Project Toolkit
- capabilities irrelevant to current work
- unavailable integrations
- permissions not required by the current role
+ workflow-required components
+ temporary tighter restrictions
= Task Toolkit
```

Least capability is both a safety principle and a context-quality principle.

## 5. Resolution stages

A practical resolver should combine deterministic filtering with bounded reasoning.

```text
1. Work / project requirements
2. Capability matching
3. Hard policy filtering
4. Integration health and availability
5. Workflow requirements
6. Role separation / ownership validation
7. Provider/model resolution
8. Final completeness validation
```

Domain tags may help select specialized Skills, but authority and control are primarily derived from external effect, consequence, reversibility, access sensitivity, and assurance requirements.

## 6. Capability metadata

A Skill or tool should carry enough metadata for deterministic selection.

Example:

```yaml
id: deterministic-test
kind: skill
version: 1.0.0

provides:
  - validation.test

applicable_when:
  artifact_types: [source-code]

roles:
  allowed: [builder, validator]

permissions:
  external_write: false

inputs:
  - changed_scope

outputs:
  - test_evidence
```

## 7. IntegrationSpec

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

## 8. Credential references

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

## 9. Identity and delegation

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

## 10. Integration lifecycle / health

Presence in configuration is not equivalent to usability.

Track integration state explicitly:

```text
DESIRED
INSTALLED
CONFIGURED
AUTHENTICATED
AUTHORIZED
HEALTHY
DEGRADED
UNAVAILABLE
```

A Task Toolkit requiring `work.write` must fail preflight if the required integration is not both authorized and sufficiently healthy.

## 11. Configuration split

Recommended project-side separation:

```text
.foundry/project.yaml
= project characteristics, authority inputs, desired integration IDs

.foundry/toolkit.lock.yaml
= resolved/pinned capability versions and integration profiles

local/runtime configuration
= credential references and environment-specific endpoints when appropriate

credential provider
= actual secrets
```

Environment-specific configuration must not be confused with project-level authority. A credential being available does not imply that a task is authorized to use it.

## 12. Toolkit lock and compatibility

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

## 13. Capability health

The resolver should distinguish declared capability from effective capability.

```text
DESIRED
AVAILABLE
COMPATIBLE
AUTHORIZED
HEALTHY
```

Examples of failure:

- Skill metadata exists but required executable is absent
- connector is installed but authentication expired
- provider exists but model/cost policy forbids the role
- runtime verifier exists but target environment cannot be read

These should become typed preflight failures rather than mid-run surprises.

## 14. Provider resolution

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

## 15. Practical objective

A toolkit is successful when project configuration can reproducibly answer:

> What may this project use, what does this Work Item actually need, which external systems are authorized and healthy, and how can the execution environment obtain the required capability without exposing unnecessary privileges or secrets?