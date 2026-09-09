# AGENTS.md — Agent Foundry

Navigation adapter for coding agents. Durable contracts live in `docs/`; current work belongs to the configured work tracker or the explicit current Work Item contract.

## Read first

Read this adapter, `docs/ai/PROJECT_AGENT_CONSTITUTION.md` and the current Work Item. This follows the Constitution's always-read/task-read distinction; it does not relax any product or authority boundary.

## Read by task

- Product scope, artifact ownership, authority or architecture changes → `docs/contracts/product-boundary.md` before deciding the change
- Code, tooling, tests or repository validation → `docs/ai/project-context.md` and the applicable validation contract
- Foundry architecture / adoption / work / toolkit / compiler changes → `docs/foundry/00-overview.md` and only the applicable canonical document
- Architecture summary and planned context-selection seams → `docs/architecture/overview.md`
- A newly discovered security, migration or external-write consequence → before that action, load the applicable existing governing contract: authority/external-write rules in `docs/ai/PROJECT_AGENT_CONSTITUTION.md` §6 and `docs/contracts/product-boundary.md` §External writes; governance/control rules in `docs/foundry/01-governance-and-control.md`; brownfield migration in `docs/foundry/02-project-intake-and-adoption.md`; schema/contract migration in `docs/contracts/v0.2-contract-delta.md`; or release/version policy in `docs/foundry/09-release-and-versioning.md`. No standalone security contract exists; if no listed contract applies, report UNKNOWN and do not infer permission or omit the gate.

Do not load the entire `docs/foundry/` tree into every prompt. Use progressive disclosure. Keep required source locators discoverable; an unread required source is UNKNOWN, not a reason to infer permission or silently omit a gate.

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

Preserve applicable required gates. Documentation navigation changes do not certify compiler behavior; required checks that cannot run remain NOT_RUN. Do not introduce CI or bypass a project-required check merely to shorten the workflow.

## Out of scope unless explicitly tasked

- SaaS, billing, auth product, multi-tenancy, marketplace
- Implementing downstream compiler/runtime features merely because they are documented in `docs/foundry/`
- Turning Foundry into a secret vault, project-management database, or generic workflow engine

## Public repository rule

Public contracts and examples must be self-contained and generic. Do not add private repository references, private project names, personal filesystem paths, real credentials, or unpublished internal policy sources.
