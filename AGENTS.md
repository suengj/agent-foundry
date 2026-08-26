# AGENTS.md — Agent Foundry

Navigation adapter for coding agents. Durable contracts live in `docs/`; current work belongs to the configured work tracker or the explicit current Work Item contract.

## Read first

1. `docs/ai/PROJECT_AGENT_CONSTITUTION.md` — P0 rules and authority
2. `docs/contracts/product-boundary.md` — product scope and artifact ownership
3. `docs/ai/project-context.md` — tooling and validation commands

## Read by task

- Foundry architecture / adoption / work / toolkit / compiler changes → `docs/foundry/00-overview.md` and only the applicable canonical document
- Architecture summary → `docs/architecture/overview.md`

Do not load the entire `docs/foundry/` tree into every prompt. Use progressive disclosure.

## Work authority

- **Work tracker / Work Item contract** = objective, scope, dependency, lifecycle state
- **Repository** = implementation truth: code, tests, review, revisions
- **Runtime / external systems** = applied factual truth where applicable
- **Prompt / rendered execution brief** = current execution delta only

Do not duplicate volatile work state into README, constitution, or AGENTS.md.

## Execution boundaries

- Implement only the active Work Item scope or an explicit authorized change
- External writes default to **preview / dry-run** → **explicit apply** unless a narrower project policy grants bounded automatic authority
- Core logic stays provider-neutral; provider/tool-specific behavior belongs in adapters
- Resolve logical role/capability before provider/model selection
- Project Toolkit is an approved capability universe; Task Toolkit exposes the minimum required subset
- Work Items should be causal and independently closable; do not split by files or roles alone
- Brownfield projects must be inspected before rules or structures are rewritten
- Agent self-report is not evidence; use deterministic artifacts and fresh read-back where required
- Raw API keys/secrets must never be written into version-controlled Foundry configuration or generated Markdown
- Do not create a second hand-maintained Markdown SSOT when structured canonical configuration can generate the view

## Validation

```bash
python -m agent_foundry doctor
pytest
```

## Out of scope unless explicitly tasked

- SaaS, billing, auth product, multi-tenancy, marketplace
- Implementing downstream compiler/runtime features merely because they are documented in `docs/foundry/`
- Turning Foundry into a secret vault, project-management database, or generic workflow engine

## Public repository rule

Public contracts and examples must be self-contained and generic. Do not add private repository references, private project names, personal filesystem paths, real credentials, or unpublished internal policy sources.