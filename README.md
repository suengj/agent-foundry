# Agent Foundry

**Agent Foundry is an AI-native project adoption and configuration compiler.**

It analyzes a new or existing project, derives the operating profile agents should follow, resolves a bounded project-specific toolkit, and compiles concise execution contracts for coding agents and other AI workers.

The long-term user experience is:

```text
Target project
→ inspect current truth
→ classify operating characteristics
→ synthesize project profile
→ bootstrap or retrofit AI-native controls
→ decompose objectives into causal work
→ resolve a least-capability toolkit
→ compile agent execution contracts
→ execute through existing agents/tools
→ verify and reconcile evidence
```

Agent Foundry is intended to work **before and around** an execution agent. It is not an attempt to replace Claude Code, Cursor, Codex, OpenHands, issue trackers, secret managers, or agent runtimes.

## Why this exists

Coding agents are increasingly capable, but real projects differ materially in:

- architecture and repository conventions;
- existing or missing agent instructions;
- testability and observability;
- external side effects and rollback cost;
- authority and approval boundaries;
- required tools, skills, integrations, and credentials;
- work-management conventions;
- evidence needed to call work complete.

A single giant prompt or fixed agent template does not capture those differences reliably.

Agent Foundry treats the **project itself as input** and produces structured, auditable configuration describing how agents should operate in that project.

## Core outputs

A mature Foundry run should be able to derive or generate:

```text
ProjectObservation
ProjectProfile
ProjectManifest
ReadinessFindings
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
→ minimum project contracts
→ initial manifest/profile
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
→ preview changes
→ progressively retrofit only what is needed
```

The goal is **migration and adaptation, not rewriting a functioning project around Foundry**.

## Project Profile Synthesis

Project inspection should not collapse immediately into a hard-coded project type such as `backend`, `trading`, or `content`.

Instead Foundry derives composable characteristics and synthesizes profiles such as:

```text
Operating characteristics
Governance profile
Work profile
Role profile
Interaction profile
Evidence profile
Integration requirements
Toolkit requirements
```

A classification result should retain provenance and uncertainty:

```yaml
key: runtime_mutation
value: true
source: observed
evidence:
  - deploy-config
confidence: 0.98
```

Inferred facts may safely tighten controls, but inferred facts should not silently expand authority.

## Work model

Foundry defines work above any specific tracker:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

A Work Item is a causal, independently closable capability boundary. It should not be split merely because files, agents, test phases, or implementation roles differ.

Tracker lifecycle, execution lifecycle, and evidence lifecycle remain separate:

```text
Work Item state
≠ Execution Run state
≠ Evidence state
```

External trackers are adapters to this model rather than architectural dependencies of the core.

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

**Project Toolkit** = the version-pinned capability universe approved for the project.

**Task Toolkit** = the least-capability subset actually needed by one Work Item/run.

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

Integration availability is explicit rather than binary:

```text
DESIRED
→ AVAILABLE
→ CONFIGURED
→ AUTHENTICATED
→ AUTHORIZED
→ HEALTHY
```

A credential being available does not imply that a task is authorized to use it.

## MCP direction

MCP is planned as an **interface/facade**, not the Foundry core.

```text
                    Agent Foundry Core
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
             CLI       Python API    MCP Server
```

The same deterministic models/resolvers/validators should remain usable when MCP is unavailable.

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

Candidate MCP resources include project profile, manifest, adoption plan, toolkit, work model, and current execution bundle views.

For new MCP implementations, project directories should be passed through tool parameters, resource URIs, or server configuration rather than building new architecture around MCP Roots, which was deprecated in MCP `2026-07-28`.

Long-running Foundry operations may later use the MCP Tasks extension, but V0.1 remains focused on a stable synchronous core first.

## CLI direction

Today the repository contains only a minimal bootstrap CLI. The intended command surface is:

```bash
agent-foundry inspect <project-path>
agent-foundry classify <project-path>
agent-foundry profile <project-path>
agent-foundry adopt <project-path> --preview
agent-foundry adopt <project-path> --apply
agent-foundry work plan <objective>
agent-foundry resolve <project-path>
agent-foundry integration check <project-path>
agent-foundry compile <work-item>
agent-foundry render <execution-bundle>
agent-foundry validate <artifact>
agent-foundry reconcile <project-path>
```

External mutations should remain preview-first unless a narrower policy explicitly grants bounded automatic authority.

## Current repository state

The repository currently contains:

- a minimal Python package and bootstrap CLI;
- a clean public baseline;
- canonical architecture and governance contracts;
- a V0.1 implementation plan for typed contracts, inspection, adoption, work decomposition, toolkit resolution, compilation, and verification.

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

- Provider-neutral core; provider identities stay in adapters.
- Source once, compile many.
- Project first, task second.
- Project characteristics are compositional rather than domain-hardcoded.
- Deterministic invariants + declarative policies + bounded LLM interpretation.
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

Agent Foundry deliberately learns from existing open-source systems without trying to clone them.

| Project | What it validates | What Foundry borrows | Main distinction from Foundry |
|---|---|---|---|
| [GitHub Spec Kit](https://github.com/github/spec-kit) | Constitution-driven spec → plan → tasks → implementation workflows | explicit artifact lifecycle, provider integrations, spec/task discipline | Spec Kit primarily structures **what to build**; Foundry first derives **how agents may operate in this project** |
| [Agent OS](https://github.com/buildermethods/agent-os) | Discovering project standards and injecting only relevant standards | convention discovery, indexed standards, progressive disclosure | Foundry generalizes beyond coding standards into governance, permissions, integrations, roles, evidence, and toolkit resolution |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | Brownfield-first, delta-oriented change artifacts | current truth vs proposed change, incremental brownfield adoption | Foundry additionally synthesizes project operating profiles and execution/toolkit constraints |
| [OpenHands](https://github.com/OpenHands/OpenHands) / [Extensions](https://github.com/OpenHands/extensions) | Reusable Skills/plugins and progressive loading | small composable skills, metadata-driven loading | Foundry selects/configures capabilities for the project rather than acting primarily as the agent runtime/skill host |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | Agent-Computer Interface design materially affects agent performance | tool-interface profiles, concise feedback, executable validation | Foundry configures the project/harness before a specific task runner operates |
| [OpenAI Symphony](https://github.com/openai/symphony) | Issue tracker → isolated workspace → autonomous agent runs | Work Item vs Run separation, workspace/lease concepts, reconciliation | Symphony is an execution scheduler/orchestrator; Foundry is the project adoption/configuration compiler upstream of such runtimes |
| [Model Context Protocol](https://modelcontextprotocol.io/) | Standardized agent-to-tool/context interoperability | optional MCP facade, typed tool/resource interfaces, integration boundary | Foundry Core remains protocol-independent and usable via CLI/Python API |

See [`docs/foundry/08-benchmarks-and-evolution.md`](docs/foundry/08-benchmarks-and-evolution.md) for the benchmark-derived design deltas and non-goals.

## What is intentionally different

Foundry's intended niche is not another spec generator, coding agent, workflow runner, or Skills marketplace.

Its core transformation is:

```text
New or existing project
+ human objective
        ↓
Project understanding
+ adoption strategy
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

## License

Agent Foundry is released under the [MIT License](LICENSE).
