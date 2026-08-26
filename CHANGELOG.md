# Changelog

All notable user-visible changes to Agent Foundry will be documented here.

The project follows Semantic Versioning principles while `<1.0.0`; pre-1.0 minor releases may contain explicit breaking changes to experimental contracts.

## [Unreleased]

### Changed

- `DecompositionQualityFlag.MEGA_ITEM` (`mega-item`) is now `CROSS_OUTCOME_IDENTITY_COLLISION` (`cross-outcome-identity-collision`). The engine splits these units into separate work items and sets `work_item_id=None` on the issue; no mega item is ever produced, so the old name described an outcome that does not occur. `agent_foundry.models.__all__` is unchanged — only the member of an exported enum was renamed.
- Decomposition quality issues relate ids that resolve inside the plan. `cross-outcome-identity-collision` related outcome ids and `mixed-work-class` related work-class *names*, so neither diagnostic pointed at anything a reader could open. Both now relate the capability unit ids that disagreed; the outcome ids and class names moved into the message, where they explain the finding.
- `agent-foundry doctor` separates a package self-check from a target-project check. The project check resolves artifacts by discovering a project root upward from the working directory (or from an explicit `agent-foundry doctor PROJECT_PATH`), never from the installed package's own location. Exit codes distinguish the two: `1` when the installation itself is broken, `2` when a named project is missing expected artifacts, `0` when no project is in scope.

### Fixed

- Work decomposition fails clearly instead of crashing when `WorkClass` grows. `_WORK_CLASS_PRECEDENCE` ranks every member by hand, and a member added without extending it raised a bare `KeyError` from inside the rank lookup — only once two unlike capability units happened to merge. The merge now raises `WorkDecompositionError` naming the unranked member and the tuple to extend, and a named test fails in CI before any input reaches it.
- A cycle in a large dependency graph is still reported as a cycle. Cycle *detection* is iterative and handles thousands of nodes, but path reconstruction recursed once per node and raised `RecursionError` at 3000 — on the already-failing path, so an actionable "circular dependency: a -> b -> a" turned into a stack overflow. Reconstruction is iterative; node visit order and the reported path are unchanged.
- The Work Item contract can no longer be widened in place. `frozen=True` stops rebinding an attribute but leaves a `list` field open to `.append()`, so `context.contract.scope.append(...)` silently changed the serialized contract that bounds compiled write authority. Sequence fields on the work model are tuples.
- `attach_execution_run` no longer accepts a run id twice, and runs keep attach order. Attaching `run-000` to a 50-run context produced 51 runs, and sorting by id ordered them lexically, so `run-9` preceded `run-049` and the run sequence read as a history that never happened.
- `runtime_external_validation_requirement` says something about the item it is on. It was one hardcoded sentence stamped onto every Work Item, including READ_ONLY discovery-only ones with nothing external to validate. It is now derived from the item's authority class and required evidence, and is unset for items with no external effect.
- Adoption authority guard is enforceable. `assert_change_set_respects_authority` previously compared `change.target` against two literal strings, one of which (`impact.external-effect`) had no emit site and was spelled with a hyphen where the classifier uses `impact.external_effect`; the guard could not raise for any planner output. Authority-bearing targets are now recognised by the manifest field they move, under either spelling, and an unclassified target fails closed instead of passing unexamined.
- Unknown current authority no longer reads as "not widening". `widens_autonomy` and `widens_external_effect` returned `False` whenever the current level was unknown — the ordinary case, since AF2 leaves manifest fields unknown by design. Unknown now ranks below every declared level, so a proposal against an unknown baseline is treated as widening.
- `test-harness` HARDEN is labelled for what it does. Adding or strengthening test entrypoints writes repository files, so both the greenfield and brownfield changes are `bounded-policy` / `proposed` rather than `none` / `auto-applicable`, matching their file-creating siblings.
- Adoption change evidence stops fabricating and discarding provenance: `source_ref` is the file the evidence came from (or `null` when none was located) instead of a hardcoded `"."`, every `agent-rule-fragmentation` finding produces a change rather than only the first, and the brownfield `test-harness` and `execution.autonomy` changes cite the entrypoints they rest on.

### Removed

- The unreachable second copy of the undeclared-outcome check inside `_packages_for_outcomes`; the identical check in `decompose_work` already ran on every path. The dead `work_class.value` tiebreak in `resolve_merged_work_class` is gone too — precedence ranks are unique per member, so it could never be reached. The `unpackaged` post-condition and `_assert_unique_work_item_ids` stay, now with comments saying why they are deliberate defense-in-depth rather than live checks.

### Added

- Exhaustiveness guards for the work model's enum-keyed lookup tables (`tests/test_work_vocabulary_exhaustiveness.py`), following the existing docs-vocabulary guard: a `WorkClass` member with no precedence rank, or an `ExternalEffectClass` member with no external-validation clause, is a named test failure naming the member and the table.
- End-to-end adoption property tests over a planner-input corpus: no planned change is both authority-widening and `auto-applicable`/`none`; no change whose action requires writing repository files (MIGRATE/HARDEN/CONSOLIDATE/WRAP) is `auto-applicable`/`none`; and every planned target is classified by the authority guard, so a new `_change(...)` call site cannot silently escape review.
- The adoption property tests assert their own coverage. Every on-disk fixture emits zero authority-widening changes, so a property that only inspects widening changes passes however they are labelled; the corpus now includes an input that reaches the planner's authority-proposal path, and a named guard test fails if the corpus ever stops producing one.
- The adopt determinism test now compares output across PYTHONHASHSEED and working directory instead of running both subprocesses with the same environment and comparing a run to itself.

- Work Item compiler (`agent_foundry.compile`) producing minimum Task Toolkit, role-specific `ExecutionBundle`, and provenance-bearing selections with authority intersection.
- Concise Markdown renderer (`agent_foundry.render`) projecting agent-facing contracts from `ExecutionBundle` only.
- `agent-foundry compile` CLI subcommand with `--render` for Markdown projection.
- Compiled write scope is a true path intersection of Work Item scope and Role Contract scope: `.`, `./`, redundant separators, and `..` traversal are resolved before comparison, and any bound that resolves to the repository root, an absolute path, or above the root grants nothing.
- Drive-rooted and UNC paths (`C:\repo\src`, `\\host\share`) are rejected as write-scope bounds rather than compared textually as if repository-relative.
- `validate_execution_bundle_authority` performs structural checks that do not call the compiler, so a forged or over-broad bundle is still rejected when compilation itself is wrong; an empty Role Contract write scope authorizes no write path rather than skipping the containment check.
- Selection provenance names the Work Item field that actually supplied the matching token (scope, objective, or title) instead of always claiming scope overlap.
- Work Item escalation conditions carried into an `ExecutionBundle` now have provenance, as stop conditions already did.
- `ExecutionBundle` provenance is bounded: every selected component and the highest-scoring near-misses are itemized, and the remaining candidates are accounted for by count rather than enumerated, so bundle size no longer grows with project material.

- Capability registry and deterministic two-stage toolkit resolver (`agent_foundry.toolkit`) with explainable include/exclude decisions.
- `agent-foundry resolve-toolkit` and `agent-foundry integration-check` CLI subcommands.
- Extended registry/toolkit contracts: skill trigger metadata, policy rules, version-pinned `ToolkitLock`, and integration preflight health states.

- `agent-foundry adopt <path>` CLI and Core API for greenfield bootstrap and brownfield adoption planning from inspection evidence.
- `agent-foundry inspect <path>` CLI and Core API for read-only project inventory, classification candidates, convention discovery, and readiness findings.
- Tracker-neutral work decomposition engine (`agent_foundry.work`) with causal grouping, dependency graph validation, and quality checks.
- Work hierarchy extension points: `OutcomeCapability`, `ExecutionRunRef`, `WorkspaceLeaseRef`, `WriteLeaseRef`, and distinct lifecycle/execution/evidence snapshots.
- Write/render boundary embedded-secret guard: Tier A (known vendor credential formats in values and keys) hard-fails serialization; Tier B (value entropy) is advisory only and does not block.
- Embedded-secret guard covers hyphenated OpenAI project/service-account keys, JOSE headers with `alg` in any position, and PGP private-key armor; credential-shaped mapping keys are redacted out of diagnostic paths.
- Clean public architecture baseline for Agent Foundry.
- Greenfield and brownfield project-adoption model.
- Tracker-neutral causal work model.
- Project Toolkit / Task Toolkit and IntegrationSpec / SecretRef architecture.
- Project Profile Synthesis, provenance/confidence, convention-discovery, and benchmark-derived design direction.
- MCP direction as an optional facade over protocol-neutral Foundry Core.
- Public release/versioning policy and MIT License.

### Fixed

- Integration preflight health now gates Task Toolkit resolution instead of only being reported next to it. `docs/foundry/04` §4 promised the Task Toolkit subtracts unavailable integrations, but the task stage hard-filtered to the literal id `repository`, so an integration whose health was `unavailable` could still be pinned and handed to a run. An integration now reaches the Task Toolkit only when a spec declares it, observed health meets that spec's `health.required`, and its capabilities stay within the Work Item's authority ceiling; every subtraction carries a rationale.
- An integration id with no declared `IntegrationSpec` is no longer retained by the external-effect ceiling reconciliation. Requesting `work-tracker` on a read-only project without a spec resolved to `integrations: ['work-tracker']` while supplying the spec correctly resolved to `[]` — missing data widened the result. Unknown capabilities are now treated as the fail-closed maximum at both the project and task stages, and the lock ceiling chokepoint rejects a pinned integration it cannot check.
- Absent integration health evidence no longer reads as a health observation. `preflight_integrations` derived `configured` from `IntegrationSpec.auth is None`, inferring a lifecycle state from the shape of a declaration rather than from anything measured — so an integration that was never checked cleared a `required: configured` bar and reached the Task Toolkit. An unobserved integration is now `desired` whether or not it declares `auth`; the auth shape only changes the diagnostic message. Waiving verification is now a declaration (`health: {required: desired}`) rather than an inference drawn from missing data.
- Validator ids are presence-checked against the registry before being pinned. A registry with `validators: []` previously still produced a lock naming `evidence-contract` and `schema-compat`, neither of which could run.
- `work.read` is classified `read-only` rather than `shared-service-write`. Reading a work tracker changes no state, exactly as `runtime.verify` reads a runtime without mutating it; the old value denied trackers to read-only work items for no reason. `CapabilitySpec.min_external_effect` now documents the axis it measures so the classification is not re-guessed.

### Changed

- `ToolkitLock` pins `validator_versions` alongside `skill_versions`, `workflow_versions`, and `integration_adapter_versions`.
- **Behavior change:** resolving a toolkit without supplying `integrations` no longer pins the default `repository` integration, because nothing declares its capabilities or health. Declare an `IntegrationSpec` for every integration a project should be allowed to use.
- Task toolkit resolution derives `role_ids` from selected skills, filters workflow roles by work-item authority, and records explaining decisions when a work item cannot be satisfied from the project lock.
- Builtin registry skill triggers now cover `INCIDENT` and `CONTRACT_AMENDMENT` via honest extensions to existing skills.
- Write-scope intersection now truly narrows role and work-item bounds; read-only compiles clear advertised write scope.
- Markdown render path applies the embedded-secret guard; compile provenance records bundle fields and integration health.

- Toolkit resolution reconciles capabilities against the manifest-declared external-effect ceiling (not the selected profile), pins that declaration in locks, and raises on unsatisfiable hard policy requirements.
- Pre-release vocabulary correction: removed `external-shared` from `Statefulness` (use `persistent-shared-external`); removed `deterministic` from `AssuranceMode` (use `deterministic-tests`).

### In progress

- V0.1 typed contracts, inspection, adoption planning, work decomposition, toolkit resolution, compilation, validation, and end-to-end preview proof.

## Release targets

- `v0.1.0` — first Public Preview: Diagnosis → Prescription → Compilation → Validation.
- Post-`v0.1` — bounded Controlled Apply, first MCP facade, and selected live adapters based on V0.1 evidence.
