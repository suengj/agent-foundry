# Agent Foundry

Provider-neutral tooling for turning new or existing projects into bounded AI-native execution environments.

Agent Foundry is designed around a simple pipeline:

```text
Inspect project
→ classify operating characteristics
→ bootstrap or retrofit AI-native controls
→ decompose objectives into causal work
→ resolve a least-capability toolkit
→ compile agent execution contracts
→ verify and reconcile evidence
```

## What this is

- A project intake and adoption layer for both greenfield and brownfield systems
- A tracker-neutral work/decomposition model
- A capability registry and Project/Task Toolkit resolver
- A compiler from structured project/work state to concise agent-facing execution bundles
- A validation and reconciliation layer across work trackers, repositories, integrations, and runtime/external state
- A provider-neutral core with provider/tool-specific adapters at the edges

## What this is not

- A second project-management database
- A secret vault
- A general-purpose workflow engine
- A monolithic agent runtime
- A plugin marketplace or SaaS control plane
- A collection of giant prompts copied into every project

## Current repository state

The repository currently contains a minimal Python CLI/bootstrap plus the canonical operating-model contracts for the next implementation phase. The full classifier, work planner, toolkit resolver, compiler, integration layer, and runtime orchestration are not yet implemented.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m agent_foundry --help
python -m agent_foundry doctor
pytest
```

## Canonical contracts and design

| Artifact | Path |
|---|---|
| Product / authority boundary | `docs/contracts/product-boundary.md` |
| Project Agent Constitution | `docs/ai/PROJECT_AGENT_CONSTITUTION.md` |
| Technical environment | `docs/ai/project-context.md` |
| Architecture overview | `docs/architecture/overview.md` |
| Foundry operating model / ToC | `docs/foundry/00-overview.md` |
| Governance + executable controls | `docs/foundry/01-governance-and-control.md` |
| Project intake + greenfield/brownfield adoption | `docs/foundry/02-project-intake-and-adoption.md` |
| Work model + decomposition | `docs/foundry/03-work-model-and-decomposition.md` |
| Toolkit + integrations + credential references | `docs/foundry/04-toolkit-and-integrations.md` |
| Orchestration + agent interaction | `docs/foundry/05-orchestration-and-interaction.md` |
| Verification + reconciliation + learning | `docs/foundry/06-verification-reconciliation-learning.md` |
| Machine-readable implementation contracts | `docs/foundry/07-implementation-contracts.md` |

## Operating model

```text
Human objective / existing project
        ↓
Project intake + current-truth inspection
        ↓
Classification + readiness assessment
        ↓
Project Manifest
        ↓
Objective → Outcome → Work Package → Work Item
        ↓
Project Toolkit resolution + pinning
        ↓
Current Work Item + fresh project truth
        ↓
Task Toolkit + Execution Bundle
        ↓
Agent / Agent Graph execution
        ↓
Verification / evidence / reconciliation
        ↓
Learning and versioned improvement
```

A **Project Toolkit** is the approved capability universe for a project. A **Task Toolkit** is the minimum subset exposed for one Work Item/run. Provider/model selection happens after role and capability requirements are resolved.

## Greenfield and brownfield

Foundry does not assume a new project.

```text
Greenfield
→ bootstrap minimum contracts and toolkit

Brownfield
→ inventory existing project
→ distinguish observed behavior from intended contracts
→ assess AI-native readiness
→ consolidate/wrap/harden/migrate only where needed
→ increase autonomy progressively
```

The goal is migration and retrofit, not rewriting a functioning system around Foundry.

## Work model

Foundry defines work above any specific tracker:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

Trackers such as issue/project-management systems are adapters. Repository and runtime state remain authoritative in their own domains rather than being mirrored into Foundry.

## Integrations and credentials

Toolkits can declare tools, MCP servers, APIs, and external services through `IntegrationSpec`-style metadata. Version-controlled Foundry configuration stores only capability declarations and credential references.

```text
Agent / Execution Bundle
→ scoped Integration Adapter
→ credential reference / delegated identity
→ external system
```

Raw API keys or secret values do not belong in `.foundry/` project configuration or generated Markdown.

## Authority model

```text
Human / project owner
= objective and reserved authority

Work tracker
= work intent, priority, dependency, lifecycle

Repository
= implementation truth: code, config, tests, reviews, revisions

Runtime / external systems
= applied/external factual truth

Credential provider
= secret and identity material

Agent Foundry
= project manifest, work contracts, toolkit resolution, execution contracts,
  adapters, validation, and reconciliation
```

## Design constraints

- Provider-neutral core; provider identities stay in adapters
- Progressive disclosure instead of loading all docs/Skills into every prompt
- Causal Work Items rather than file-shaped tasks
- External writes default to preview/dry-run until narrower authority is explicitly granted
- Hard policies become executable controls where practical
- Structured canonical configuration generates Markdown projections
- Tracker state, execution state, and evidence state remain separate
- Secrets are referenced, never embedded
- Toolkit/schema/adapter upgrades are versioned and explicit

Start with [`docs/foundry/00-overview.md`](docs/foundry/00-overview.md).