# Changelog

All notable user-visible changes to Agent Foundry will be documented here.

The project follows Semantic Versioning principles while `<1.0.0`; pre-1.0 minor releases may contain explicit breaking changes to experimental contracts.

## [Unreleased]

### Changed

- `agent-foundry doctor` separates a package self-check from a target-project check. The project check resolves artifacts by discovering a project root upward from the working directory (or from an explicit `agent-foundry doctor PROJECT_PATH`), never from the installed package's own location. Exit codes distinguish the two: `1` when the installation itself is broken, `2` when a named project is missing expected artifacts, `0` when no project is in scope.

### Fixed

- Adoption authority guard is enforceable. `assert_change_set_respects_authority` previously compared `change.target` against two literal strings, one of which (`impact.external-effect`) had no emit site and was spelled with a hyphen where the classifier uses `impact.external_effect`; the guard could not raise for any planner output. Authority-bearing targets are now recognised by the manifest field they move, under either spelling, and an unclassified target fails closed instead of passing unexamined.
- Unknown current authority no longer reads as "not widening". `widens_autonomy` and `widens_external_effect` returned `False` whenever the current level was unknown — the ordinary case, since AF2 leaves manifest fields unknown by design. Unknown now ranks below every declared level, so a proposal against an unknown baseline is treated as widening.
- `test-harness` HARDEN is labelled for what it does. Adding or strengthening test entrypoints writes repository files, so both the greenfield and brownfield changes are `bounded-policy` / `proposed` rather than `none` / `auto-applicable`, matching their file-creating siblings.
- Adoption change evidence stops fabricating and discarding provenance: `source_ref` is the file the evidence came from (or `null` when none was located) instead of a hardcoded `"."`, every `agent-rule-fragmentation` finding produces a change rather than only the first, and the brownfield `test-harness` and `execution.autonomy` changes cite the entrypoints they rest on.

### Added

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

### Changed

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
