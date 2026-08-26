# Agent Foundry

Personal-first AI-native project toolbox that applies [AI Dev Playbook](https://github.com/suengj/ai-agent-dev-playbook) principles to real projects.

**Work SSOT:** [Linear — Agent Foundry · M0 Personal MVP](https://linear.app/suengj)  
**Implementation SSOT:** this repository (`suengj/agent-foundry`)

Linear owns current issue priority and status. This repository does not duplicate live task state.

## What this is

- Executable toolbox that turns Playbook principles into project bootstrap, work orders, and evidence-aware execution adapters
- Provider-neutral core with Cursor / Codex / Claude as adapters

## What this is not (M0)

- SaaS, billing, authentication, multi-tenancy
- Playbook wholesale copy or fork
- Linear auto-write compiler (AF0.2+)
- ProjectTruth engine (AF0.2+)

## Quick start

```bash
cd ~/Developer/PJT/p01_agent_foundry
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m agent_foundry --help
python -m agent_foundry doctor
pytest
```

## Canonical contracts

| Artifact | Path |
|---|---|
| Product / authority boundary (SUE-294) | `docs/contracts/product-boundary.md` |
| Project Agent Constitution | `docs/ai/PROJECT_AGENT_CONSTITUTION.md` |
| Technical environment | `docs/ai/project-context.md` |
| Architecture overview | `docs/architecture/overview.md` |

## Playbook adoption

Playbook is referenced by pinned repository + commit SHA in the constitution. Content is not copied wholesale into this repo.

## Authority model

```text
Human          → objective / authority
ChatGPT        → governor / architecture / Linear decomposition
Linear         → Work SSOT
GitHub         → Implementation SSOT
Runtime        → Production Truth (where applicable)
AI Dev Playbook → reusable development constitution (external, pinned)
Project Constitution → repository-specific behavior / safety
Foundry outputs → generated artifacts (single-owner rules apply)
```

## Repository

- **Local:** `~/Developer/PJT/p01_agent_foundry`
- **GitHub:** https://github.com/suengj/agent-foundry (private)
