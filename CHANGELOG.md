# Changelog

All notable user-visible changes to Agent Foundry will be documented here.

The project follows Semantic Versioning principles while `<1.0.0`; pre-1.0 minor releases may contain explicit breaking changes to experimental contracts.

## [Unreleased]

### Added

- Work Item compiler (`agent_foundry.compile`) producing minimum Task Toolkit, role-specific `ExecutionBundle`, and provenance-bearing selections with authority intersection.
- Concise Markdown renderer (`agent_foundry.render`) projecting agent-facing contracts from `ExecutionBundle` only.
- `agent-foundry compile` CLI subcommand with `--render` for Markdown projection.

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

- Toolkit resolution reconciles capabilities against the manifest-declared external-effect ceiling (not the selected profile), pins that declaration in locks, and raises on unsatisfiable hard policy requirements.
- Pre-release vocabulary correction: removed `external-shared` from `Statefulness` (use `persistent-shared-external`); removed `deterministic` from `AssuranceMode` (use `deterministic-tests`).

### In progress

- V0.1 typed contracts, inspection, adoption planning, work decomposition, toolkit resolution, compilation, validation, and end-to-end preview proof.

## Release targets

- `v0.1.0` — first Public Preview: Diagnosis → Prescription → Compilation → Validation.
- Post-`v0.1` — bounded Controlled Apply, first MCP facade, and selected live adapters based on V0.1 evidence.
