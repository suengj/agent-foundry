# Project context — Agent Foundry

Technical environment and canonical paths. **Not** a substitute for Linear work state.

## Repository

| Field | Value |
|---|---|
| Local root | `~/Developer/PJT/p01_agent_foundry` |
| GitHub | `suengj/agent-foundry` (private) |
| Default branch | `main` |
| Package import | `agent_foundry` |

## Tooling

- Python ≥ 3.11
- Packaging: `hatchling` via `pyproject.toml`
- Tests: `pytest`

## Commands

```bash
# from repo root with dev extras installed
pip install -e ".[dev]"
python -m agent_foundry --help
python -m agent_foundry version
python -m agent_foundry doctor
pytest
```

## Playbook reference (read-only)

- Repository: `suengj/ai-agent-dev-playbook`
- Pinned ref: `daa487c874822921ae07b968671e5852e41f728f`
- Adoption mechanism: `playbook.ref` in constitution — bump explicitly; never wholesale copy

## Linear

- Project: **Agent Foundry · M0 Personal MVP**
- Work SSOT: Linear issues (e.g. SUE-294 foundation, SUE-295+ backlog)
- Do not mirror issue titles/status here

## Related systems

| System | Relationship |
|---|---|
| AI Dev Playbook | Upstream constitution (pinned) |
| Trading Lab | Future dogfood target (AF0.8) |
| Cursor / Codex / Claude | Execution adapters |

## Evidence expectations

- Contract changes: updated `docs/contracts/*` + passing `pytest`
- CLI/bootstrap changes: `python -m agent_foundry doctor` clean
- Issue completion: GitHub SHA linked in Linear before Done
