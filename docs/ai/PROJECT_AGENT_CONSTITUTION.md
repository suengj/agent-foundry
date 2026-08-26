---
constitution_version: 1
project: Agent Foundry
playbook:
  repository: suengj/ai-agent-dev-playbook
  ref: daa487c874822921ae07b968671e5852e41f728f
adopted_at: 2026-08-26
owner: suengj
status: active
linear_project: Agent Foundry · M0 Personal MVP
foundation_issue: SUE-294
---

# Agent Foundry — Project Agent Constitution

> Project-local constitutional entrypoint. Does **not** copy the central playbook.

## 1. Project purpose

- **Product/system:** Executable toolbox applying AI Dev Playbook principles to real projects
- **User-visible objective (M0):** Personal MVP first — bootstrap projects, freeze authority, emit provider-neutral work orders
- **Critical domains:** authority classification, artifact ownership, external-write safety
- **Out-of-scope sibling systems:** Playbook (knowledge only), production runtimes of other products

## 2. Authority and inheritance

This project adopts the central Agent Constitution at the pinned `playbook.ref`.

```text
Human objective / authority
→ ChatGPT governor / architecture
→ this Project Constitution
→ docs/contracts/*
→ Linear Task Contract (active issue)
→ agent execution defaults
```

Playbook updates do **not** apply until this project explicitly bumps `playbook.ref`.  
Do **not copy** playbook documents wholesale into this repository.

Factual truth resolution:

```text
runtime/external read-back
→ code/config/schema (GitHub)
→ tests/CI/evidence
→ Linear current work state
→ chat/history (non-authoritative)
```

## 3. P0 invariants

1. **Personal MVP first;** business toolbox second.
2. **Single owner per artifact class** — no duplicate current state across Linear, docs, prompts, adapters.
3. **External writes default to preview/dry-run** unless an explicit apply is authorized and evidenced.
4. **Provider-neutral core** — Cursor, Codex, Claude are adapters only.
5. **Linear = Work SSOT; GitHub = Implementation SSOT.**
6. **Evidence over agent self-report** — DONE requires validation artifacts.

## 4. Canonical owners

| Concept | Canonical owner | Delegate only | Forbidden duplicate |
|---|---|---|---|
| Objective / priority | Human | ChatGPT proposes | README, constitution |
| Work intent / status | Linear | — | GitHub docs, AGENTS.md |
| Implementation | GitHub | agents | Linear descriptions |
| Production truth | Runtime | read-back adapters | static docs |
| Reusable constitution | AI Dev Playbook (pinned ref) | — | full copy in repo |
| Project behavior / safety | This constitution | AGENTS.md navigation | playbook fork |
| Technical environment | project-context.md | — | scattered path notes |
| Agent behavior per task | Work Order / prompt | — | constitution bloat |
| Foundry-generated artifacts | per product-boundary.md | preview surfaces | multi-place mirrors |

## 5. Generated artifact rule

Foundry outputs must not replicate current state in multiple places.

| State | Owner |
|---|---|
| Current issue / priority | Linear only |
| Technical context | `docs/ai/project-context.md` |
| Agent behavior | This constitution + AGENTS.md |
| Execution delta | Work Order |
| Implementation | GitHub |
| Runtime result | Runtime evidence |

## 6. External write contract

Any future Foundry capability that mutates Linear, GitHub, or the filesystem:

1. **Preview / dry-run** (default)
2. **Explicit apply** (authorized, logged, evidenced)

Silent or implicit writes are forbidden.

## 7. Entry points

### Always read

- `AGENTS.md`
- this file
- active Linear issue

### Read by task

| Task | Path |
|---|---|
| Product scope / M0 boundary | `docs/contracts/product-boundary.md` |
| Architecture | `docs/architecture/overview.md` |
| Environment / commands | `docs/ai/project-context.md` |

## 8. M0 metrics (dogfood targets)

Recorded in `docs/contracts/product-boundary.md` for future measurement:

- planning elapsed time
- manual correction rate
- generated-task acceptance rate
- duplicate/stale-context detection rate
- authority-boundary miss rate
- evidence completeness
