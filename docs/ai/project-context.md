# Project context — Agent Foundry

Technical environment and canonical repository paths. This document is not a live work-status board.

## Repository

| Field | Value |
|---|---|
| Repository root | current checkout |
| Default branch | `main` |
| Package import | `agent_foundry` |
| Source | `src/agent_foundry/` |
| Tests | `tests/` |
| Durable docs | `docs/` |

## Tooling

- Python >= 3.11
- Packaging: `hatchling` via `pyproject.toml`
- Tests: `pytest`

## Commands

```bash
# from repository root with dev extras installed
pip install -e ".[dev]"
python -m agent_foundry --help
python -m agent_foundry version
python -m agent_foundry doctor
pytest
```

## Canonical document paths

```text
AGENTS.md
= thin agent navigation entrypoint

docs/ai/PROJECT_AGENT_CONSTITUTION.md
= repository-local P0 agent authority / behavior

docs/contracts/product-boundary.md
= product scope and authority ownership

docs/architecture/overview.md
= architecture summary

docs/foundry/
= detailed operating model and implementation contracts
```

## Work-state boundary

Current work state belongs to the configured work tracker or explicit current Work Item source. This repository's durable docs should not mirror volatile priority, issue status, or next-work lists.

Foundry's core work model is tracker-neutral:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

## Implementation state

The current package is intentionally small. The operating model documents describe target capabilities including project inspection, brownfield adoption, work decomposition, toolkit/integration resolution, compilation, rendering, validation, and reconciliation. Documentation does not imply those components are already implemented.

## Provider and integration boundary

The core package remains provider-neutral. Provider CLIs, work trackers, repositories, MCP/API services, credential providers, and runtime systems are integration/adaptation surfaces.

Public examples and tests should use synthetic identifiers and must not include real secret values.

## Evidence expectations

- Contract changes: relevant durable docs updated and `pytest` remains green
- CLI/bootstrap changes: `python -m agent_foundry doctor` remains clean
- Future compiler changes: structured outputs validate deterministically and generated Markdown is derived from canonical configuration
- External integration changes: preview-first semantics, credential references rather than raw secrets, and integration-health validation where applicable

## Public repository hygiene

Do not add:

- private repository dependencies to public contracts
- personal filesystem paths
- private project/tracker identifiers
- raw credentials or tokens
- project-specific operating history as reusable architecture