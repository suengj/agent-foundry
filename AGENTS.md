# AGENTS.md — Agent Foundry

Navigation adapter for coding agents. Durable contracts live in `docs/`; current work lives in Linear.

## Read first

1. `docs/ai/PROJECT_AGENT_CONSTITUTION.md` — P0 rules and authority
2. `docs/contracts/product-boundary.md` — product scope and artifact ownership (SUE-294)
3. `docs/ai/project-context.md` — paths, tooling, validation commands

## Work authority

- **Linear** = Work SSOT (current issue, priority, blockers)
- **GitHub** = Implementation SSOT (code, tests, PR evidence)
- **Prompt / Work Order** = execution delta only — do not restate full project state

Do not duplicate current Linear issue state into README, constitution, or AGENTS.md.

## Execution boundaries (M0)

- Implement only the active Linear issue scope
- External writes (Linear, GitHub, filesystem) default to **preview / dry-run** → **explicit apply**
- Core logic stays provider-neutral; Cursor/Codex/Claude are adapters
- Agent self-report is not evidence; tests/CI/runtime read-back are

## Validation

```bash
python -m agent_foundry doctor
pytest
```

## Out of scope for agents unless explicitly tasked

- SaaS, billing, auth, multi-tenancy, marketplace
- SUE-295+ features (ProjectTruth, compilers, dogfood automation) unless the active issue says so
- Copying ai-agent-dev-playbook content wholesale

## Links

- Playbook: https://github.com/suengj/ai-agent-dev-playbook
- Linear project: Agent Foundry · M0 Personal MVP
