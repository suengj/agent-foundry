# Agent Foundry

**Agent Foundry is an AI-native project adoption and configuration compiler.**

It takes a new or existing project as input, diagnoses how that project actually operates, prescribes an AI-native operating model, and compiles bounded execution contracts that existing coding agents and AI workers can use.

The core product method is:

```text
Diagnosis
→ Prescription
→ Compilation
→ Controlled Apply
```

The project deliberately works **before and around** execution agents. It is not intended to replace Claude Code, Cursor, Codex, OpenHands, work trackers, secret managers, or long-running agent runtimes.

## Why this exists

Real projects differ materially in architecture, conventions, testability, external side effects, rollback cost, authority, tools, credentials, work-management style, and the evidence required to call work complete.

A fixed prompt or one universal agent template cannot represent those differences reliably.

Agent Foundry treats the **project itself as input** and produces structured, auditable configuration describing how agents should work in that project.

## Product method

### 1. Diagnosis

```text
project / repository
→ inspect current truth
→ discover conventions and instruction surfaces
→ classify operating characteristics
→ synthesize evidence-backed Project Profile
```

### 2. Prescription

```text
Project Profile
→ AI-native readiness assessment
→ greenfield bootstrap or brownfield retrofit plan
→ governance / role / interaction / evidence requirements
→ causal Work Items
→ required project capabilities
```

### 3. Compilation

```text
Project Profile / Manifest
→ Project Toolkit + Toolkit Lock
→ Work Item
→ least-capability Task Toolkit
→ Integration / SecretRef preflight
→ Execution Bundle
→ concise agent-facing projections
```

### 4. Controlled Apply

```text
reviewed adoption change set
→ bounded project mutation
→ validation
→ rollback / adoption receipt
```

Controlled Apply is the intended next layer after the read-only/preview Core has been proven. Broad automatic project mutation is **not required for the first public release**.

## Release status

Current development version:

```text
0.1.0.dev0
```

Target first public release:

```text
v0.1.0 — Public Preview
```

`v0.1.0` is scoped to:

```text
Diagnosis
→ Prescription
→ Compilation
→ Validation
```

It must work end to end for both a controlled/synthetic project and a meaningful existing brownfield project.

The first public release does **not** require:

- broad Controlled Apply;
- autonomous agent dispatch;
- production deployment automation;
- MCP server implementation;
- large integration/Skill/provider catalogs;
- SaaS or hosted control-plane features.

See [`docs/foundry/09-release-and-versioning.md`](docs/foundry/09-release-and-versioning.md) for the full public-release gate and compatibility policy, and [`CHANGELOG.md`](CHANGELOG.md) for user-visible evolution.

## End-user flow

These commands ship today, and this is the whole list:

```bash
agent-foundry doctor [<project-path>]         # check the install, and a project if one is in scope
agent-foundry inspect <project-path>          # read-only inventory, conventions, readiness
agent-foundry adopt <project-path>            # ProjectManifest + AdoptionChangeSet (preview only)
agent-foundry resolve-toolkit <project-path>  # version-pinned Project Toolkit, or a Task Toolkit
agent-foundry integration-check <file>        # integration preflight, credentials never read
agent-foundry compile --work-item <file> ...  # ExecutionBundle, or --render for Markdown
agent-foundry validate <artifact> --kind ...  # run every validator that applies to one artifact
agent-foundry version
```

`adopt` is preview-only: it prints a plan and writes nothing. There is no `--apply`.

Still intended, and **not yet built** — no subcommand exists for any of these:

```text
agent-foundry profile <project-path>       # ProjectProfile synthesis as a first-class stage
agent-foundry work plan <objective>        # decomposition from the CLI (Python API only today)
agent-foundry render <execution-bundle>    # standalone render (today: compile --render)
agent-foundry reconcile <project-path>     # reconciliation from the CLI (Python API only today)
agent-foundry adopt <project-path> --apply # controlled mutation surface
```

Everything the CLI does is a thin dispatch over the Python API; there is no logic
behind a command that a Python caller cannot reach. See
[`docs/foundry/v0.1-readiness-report.md`](docs/foundry/v0.1-readiness-report.md) §7.

External mutations remain preview-first unless a narrower project policy explicitly grants bounded automatic authority.

## Core outputs

A mature Foundry run should be able to derive or generate:

```text
ProjectObservation
ProjectProfile
ProjectManifest
ReadinessFinding
AdoptionPlan / AdoptionChangeSet
Governance / Work / Role / Interaction / Evidence profiles
Project Toolkit / Toolkit Lock
Integration declarations + SecretRefs
Causal Work Items
Task Toolkit
Execution Bundle
Evidence Bundle / Execution Receipt
Agent-facing Markdown / adapter projections
```

Generated Markdown is a projection from structured canonical data, not a second independently maintained source of truth.

## Greenfield and brownfield

Foundry does not assume a new project.

### Greenfield

```text
project goal
→ minimum operating contracts
→ initial profile / manifest
→ work model
→ toolkit
→ agent-ready bootstrap
```

### Brownfield

```text
existing repository
→ inventory current truth and conventions
→ distinguish observed behavior from intended rules
→ assess AI-native readiness
→ propose KEEP / CONSOLIDATE / WRAP / HARDEN / MIGRATE / DEFER / BLOCK
→ preview AdoptionChangeSet
→ progressively retrofit only what is needed
```

The goal is **migration and adaptation, not rewriting a functioning project around Foundry**.

## Project Profile Synthesis

Foundry should not reduce projects to hard-coded categories such as `backend`, `finance`, or `content`.

Instead it derives composable characteristics and synthesizes profiles such as:

```text
Operating Profile
Governance Profile
Work Profile
Role Profile
Interaction Profile
Evidence Profile
Integration Requirements
Toolkit Requirements
```

Material findings retain provenance and uncertainty:

```yaml
key: runtime_mutation
value: true
source: observed
evidence:
  - deploy-config
confidence: 0.98
```

Core rule:

```text
inference may tighten controls
inference must not silently expand authority
```

This keeps the system adaptive without turning it into a hard-coded project-type template engine.

## Work model

Foundry defines work above any specific tracker:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

A Work Item is a causal, independently closable capability boundary. It should not be split merely because files, agents, tests, or implementation roles differ.

```text
Work Item state
≠ Execution Run state
≠ Evidence state
```

External trackers are adapters rather than architectural dependencies of the core.

## Toolkit model

```text
Foundry Capability Registry
        ↓
Project Profile / Manifest
        ↓
Project Toolkit
        ↓
Work Item + current truth
        ↓
Task Toolkit
        ↓
Execution Bundle
```

**Project Toolkit** is the version-pinned capability universe approved for the project.

**Task Toolkit** is the least-capability subset needed for one Work Item/run.

Toolkit components may include:

- logical agent roles;
- workflows / Agent Graph nodes;
- Skills and procedures;
- tool-interface profiles;
- MCP/API/CLI integrations;
- permission and execution-budget profiles;
- validators and evidence requirements;
- provider capability profiles;
- context sources and rendering adapters.

Provider/model selection happens after logical role and capability requirements are known.

## Integrations and secrets

Foundry is not a secret vault.

```text
Execution Bundle
→ scoped Integration Adapter
→ SecretRef / delegated identity
→ credential provider
→ external system
```

Version-controlled Foundry configuration stores integration declarations and credential references, never raw API keys or secret values.

Integration availability is explicit:

```text
DESIRED
→ AVAILABLE
→ CONFIGURED
→ AUTHENTICATED
→ AUTHORIZED
→ HEALTHY
```

Credential availability does not imply task authority.

## MCP direction

MCP is planned as an optional **facade**, not the Foundry Core.

```text
                    Agent Foundry Core
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
             CLI       Python API    MCP Server
```

The same deterministic models, resolvers, compilers, and validators must remain usable when MCP is unavailable.

Candidate MCP tools include:

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

New MCP implementations should pass project directories through tool parameters, resource URIs, or server configuration rather than building new architecture around deprecated MCP Roots.

The first MCP facade is expected after the V0.1 Core unless implementation evidence justifies a smaller earlier adapter.

## Current repository state

The repository currently contains:

- a minimal Python package and bootstrap CLI;
- canonical architecture and governance contracts;
- MIT License;
- benchmark/MCP evolution guidance;
- release/versioning policy;
- an active V0.1 implementation plan for typed contracts, project inspection, adoption, work decomposition, toolkit resolution, compilation, validation, and end-to-end preview proof.

The full Foundry compiler described above is **not yet implemented**.

## Quick start for contributors

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m agent_foundry --help
python -m agent_foundry doctor
pytest
```

Python `>=3.11` is required.

## Architecture principles

- Provider-neutral Core; provider identities stay in adapters.
- Source once, compile many.
- Project first, task second.
- Diagnosis precedes prescription and mutation.
- Project characteristics are compositional rather than domain-hardcoded.
- Deterministic invariants + declarative policies + bounded interpretation.
- Observed, declared, inferred, and normative facts stay distinct.
- Confidence/provenance accompany material classifications.
- Hard policies become executable controls where practical.
- Progressive disclosure instead of loading every rule/Skill into every prompt.
- Project Toolkit before Task Toolkit; least capability at execution time.
- Raw secrets are referenced, never embedded.
- Tracker state, execution state, and evidence state remain separate.
- Schemas, toolkits, adapters, and integrations are versioned explicitly.
- Project-local learning is not automatically promoted to a global rule.

## Benchmarks and related projects

Agent Foundry learns from existing open-source systems without trying to clone them.

| Project | Validated primitive | What Foundry borrows | Main distinction |
|---|---|---|---|
| [GitHub Spec Kit](https://github.com/github/spec-kit) | Constitution-driven spec → plan → task workflows | artifact lifecycle, spec/task discipline | Foundry first derives **how agents may operate in this project** |
| [Agent OS](https://github.com/buildermethods/agent-os) | project-standard discovery and relevance-based injection | convention discovery, progressive disclosure | Foundry extends into governance, permissions, integrations, roles, evidence, and toolkit resolution |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | brownfield-first delta-oriented changes | current truth vs proposed change | Foundry additionally synthesizes operating profiles and agent constraints |
| [OpenHands](https://github.com/OpenHands/OpenHands) | reusable Skills/plugins and progressive loading | composable Skills and metadata-driven selection | Foundry configures capabilities rather than primarily hosting the execution runtime |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | Agent-Computer Interface design | tool-interface profiles, concise feedback | Foundry configures the project/harness upstream of a task runner |
| [OpenAI Symphony](https://github.com/openai/symphony) | issue → isolated workspace → agent run | Work Item vs Run separation, lease/reconciliation concepts | Symphony is an execution scheduler; Foundry is an upstream adoption/configuration compiler |
| [Model Context Protocol](https://modelcontextprotocol.io/) | standardized tool/context interoperability | optional MCP facade and typed integration boundary | Foundry Core remains protocol-independent |

See [`docs/foundry/08-benchmarks-and-evolution.md`](docs/foundry/08-benchmarks-and-evolution.md).

## What is intentionally different

Foundry's intended niche is not another spec generator, coding agent, workflow runner, or Skills marketplace.

Its core transformation is:

```text
New or existing project
+ human objective
        ↓
Diagnosis
+ adoption prescription
+ operating profiles
+ work model
+ bounded toolkit
+ agent interaction/evidence contracts
        ↓
Agent-ready project environment
```

Execution can then be delegated to the existing agent ecosystem.

## Documentation

Start with [`docs/foundry/00-overview.md`](docs/foundry/00-overview.md).

| Document | Focus |
|---|---|
| `docs/foundry/01-governance-and-control.md` | authority, trust, harness and executable controls |
| `docs/foundry/02-project-intake-and-adoption.md` | classification, greenfield/brownfield adoption, readiness |
| `docs/foundry/03-work-model-and-decomposition.md` | causal work hierarchy and tracker-neutral contracts |
| `docs/foundry/04-toolkit-and-integrations.md` | toolkit resolution, Skills/tools/MCP/API, credentials |
| `docs/foundry/05-orchestration-and-interaction.md` | roles, Agent Graph, communication and handoffs |
| `docs/foundry/06-verification-reconciliation-learning.md` | evidence, reconciliation and learning |
| `docs/foundry/07-implementation-contracts.md` | machine-readable models and implementation sequence |
| `docs/foundry/08-benchmarks-and-evolution.md` | benchmark references, MCP direction and design evolution |
| `docs/foundry/09-release-and-versioning.md` | public release gate, versioning and compatibility policy |

## License

Agent Foundry is released under the [MIT License](LICENSE).
