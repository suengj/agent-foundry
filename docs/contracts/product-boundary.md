# Product boundary — Agent Foundry (SUE-294)

**Status:** Frozen — canonical product and authority contract for M0 Personal MVP.  
**Linear:** [SUE-294](https://linear.app/suengj/issue/SUE-294)  
**Evidence:** this file + `PROJECT_AGENT_CONSTITUTION.md` + passing `tests/test_contract_freeze.py`

## Purpose

### Personal MVP first

Primary user journey (M0):

1. Human states a project goal.
2. Governor (ChatGPT) decomposes work into a finite Linear graph.
3. Foundry (future) assists bootstrap, truth inventory, and work-order emission.
4. Adapters (Cursor/Codex/Claude) execute bounded implementation.
5. Evidence (tests, PR, runtime read-back) confirms completion before Linear Done.

**Terminal outputs (M0 contract):** frozen constitution, product boundary, runnable bootstrap CLI, validation tests — not a full compiler pipeline.

### Business toolbox second

Multi-tenant SaaS, billing, marketplace, and org-wide control plane are **explicit non-goals** for M0.

## Non-goals (M0)

- SaaS, billing, authentication, multi-tenancy
- Plugin marketplace
- Playbook rewrite or wholesale copy
- Production deployment automation
- ProjectTruth engine, Linear auto-write, work-order compiler (SUE-295+)

## Playbook adoption

| Field | Value |
|---|---|
| Repository | `suengj/ai-agent-dev-playbook` |
| Mechanism | Explicit `playbook.ref` tag/SHA in constitution |
| Pinned SHA | `daa487c874822921ae07b968671e5852e41f728f` |
| Rule | Reference and adopt — **do not** fork/copy entire playbook tree |

## Authority ownership

| Layer | Owner | Notes |
|---|---|---|
| Objective / priority | Human | Final authority |
| Architecture / decomposition | ChatGPT | Governor; not implementation SSOT |
| Work intent, status, blockers | Linear | Work SSOT |
| Code, tests, PR, commits | GitHub | Implementation SSOT |
| Deployed / live truth | Runtime | Production Truth where applicable |
| Reusable constitution | AI Dev Playbook | External; pinned |
| Project behavior / safety | Project Constitution | This repo |
| Generated Foundry artifacts | Foundry (per rules below) | Single-owner emission |

## Generated artifact ownership

Current state must not be duplicated across Linear, docs, prompts, and adapters.

| Artifact | Single owner | Update rule |
|---|---|---|
| Current issue / priority | Linear | Update Linear only |
| Technical context | `docs/ai/project-context.md` | PR when environment changes |
| Agent behavior | Constitution + AGENTS.md | PR when P0 rules change |
| Execution delta | Work Order / prompt | Per task; ephemeral |
| Implementation | GitHub | PR + review |
| Runtime result | Runtime evidence | Attestation / read-back |

## External writes

All future Foundry capabilities that mutate Linear, GitHub, or filesystem:

| Phase | Default | Requirement |
|---|---|---|
| Preview | **dry-run** (default) | Show diff/intent |
| Apply | **explicit apply** (authorized) | Logged + evidenced |

Unauthorized or silent writes are forbidden.

## Provider independence

- **Core:** provider-neutral Python package (`agent_foundry`)
- **Adapters:** Cursor, Codex, Claude, others — thin execution boundaries only
- Core modules must not depend on provider-specific SDKs for M0 bootstrap

## M0 success metrics (dogfood gates)

Targets to measure in future dogfood (AF0.8+); definitions frozen here:

| Metric | Intent |
|---|---|
| planning elapsed time | Time from goal to bounded Linear work graph |
| manual correction rate | Human edits required per generated artifact |
| generated-task acceptance rate | Share of agent tasks accepted without rework |
| duplicate/stale-context detection | Findings where state was mirrored incorrectly |
| authority-boundary miss rate | Violations of single-owner / SSOT rules |
| evidence completeness | Required validation present before Done |

## Acceptance mapping (SUE-294)

- [x] Canonical product/authority contract in repository (`this file` + constitution)
- [x] Playbook referenced by pinned SHA, not copied wholesale
- [x] Personal MVP inputs/outputs and non-goals explicit
- [x] Generated artifacts have one owner and update rule
- [x] External writes default to preview/dry-run unless explicitly authorized
- [x] M0 gate metrics and dogfood targets recorded
