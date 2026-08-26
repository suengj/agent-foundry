# Execution Contract — wi-dcc714550913

## Identity
- project: orders-service
- run: RUN-EXAMPLE-001
- role: builder
- authority: repository-write

## Objective
Apply the planned adoption change set so agent execution in this repository is bounded, evidenced, and reviewable.

## Scope
- Makefile

## Acceptance criteria
- HARDEN applied to test-harness
- regression evidence passes

## Allowed capabilities
- repository.read
- repository.write

## Write scope
- Makefile

## Forbidden scopes
- .foundry/
- .github/
- AGENTS.md
- CLAUDE.md
- docs/
- src/
- tests/

## Skills (metadata only)
- `bounded-change`: Make bounded code changes with tests
  - relevance: work_class=ADOPTION
- `deterministic-test`: Run project-approved deterministic tests and return normalized evidence
  - relevance: work_class=ADOPTION
- `independent-review`: Perform independent review without implementation authority
  - relevance: work_class=ADOPTION
- `repository-inspection`: Inspect repository structure and conventions read-only
  - relevance: work_class=ADOPTION

## Required evidence
- deterministic-test
- repository-revision

## Validators
- evidence-contract
- schema-compat

## Integrations
- work-tracker

## Budget
- max_parallel=4
- max_retries=2
- profile=default

## Stop conditions
- blocked adoption path cannot be resolved within scope

## Required outputs
- implementation-diff
- review-decision
- structured-handoff

## Selected context (refs only)
- agent-instruction-surface
- git-policy
- lint-entrypoint
- repository-structure
- test-entrypoint
- test-invocation
- test-runner

## Selection provenance (summary)
- budget-profile/default: budget profile selected by task toolkit resolution
- capability/inspection.read: required by selected task skills
- capability/repository.read: required by selected task skills
- capability/repository.write: required by selected task skills
- capability/validation.review: required by selected task skills
- capability/validation.test: required by selected task skills
- convention/git-policy: convention selected because its evidence shares tokens with the work item objective (selection score=0.05)
- convention/test-invocation: convention selected because its subject, pattern shares tokens with the work item scope, title (selection score=0.05)
- convention/test-runner: convention selected because its subject, evidence shares tokens with the work item objective, title (selection score=0.07)
- convention/test-runner: convention selected because its subject, evidence shares tokens with the work item objective, title (selection score=0.07)
- ... and 29 further selection record(s); the ExecutionBundle `provenance` field carries all of them
