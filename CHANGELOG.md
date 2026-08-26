# Changelog

All notable user-visible changes to Agent Foundry will be documented here.

The project follows Semantic Versioning principles while `<1.0.0`; pre-1.0 minor releases may contain explicit breaking changes to experimental contracts.

## [Unreleased]

### Changed

- Pre-release vocabulary correction: removed `external-shared` from `Statefulness` (use `persistent-shared-external`); removed `deterministic` from `AssuranceMode` (use `deterministic-tests`).

### Added

- Clean public architecture baseline for Agent Foundry.
- Greenfield and brownfield project-adoption model.
- Tracker-neutral causal work model.
- Project Toolkit / Task Toolkit and IntegrationSpec / SecretRef architecture.
- Project Profile Synthesis, provenance/confidence, convention-discovery, and benchmark-derived design direction.
- MCP direction as an optional facade over protocol-neutral Foundry Core.
- Public release/versioning policy and MIT License.

### In progress

- V0.1 typed contracts, inspection, adoption planning, work decomposition, toolkit resolution, compilation, validation, and end-to-end preview proof.

## Release targets

- `v0.1.0` — first Public Preview: Diagnosis → Prescription → Compilation → Validation.
- Post-`v0.1` — bounded Controlled Apply, first MCP facade, and selected live adapters based on V0.1 evidence.
