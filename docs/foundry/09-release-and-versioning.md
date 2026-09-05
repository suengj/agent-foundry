# Release and Versioning Policy

## 1. Purpose

Agent Foundry separates product maturity, package versions, schema compatibility, and public-repository readiness so that a repository being visible does not imply capabilities that have not been implemented or verified.

The product method is:

```text
Diagnosis
→ Prescription
→ Compilation
→ Controlled Apply
```

The first public release intentionally stops before broad automatic mutation.

## 2. First public release: v0.1.0

`v0.1.0` is the first **Public Preview** target.

Its purpose is to prove that Agent Foundry can take a new or existing repository and produce a useful, auditable agent-ready operating package without requiring destructive project mutation.

Required V0.1 capability boundary:

```text
Diagnosis
  inspect current project truth
  discover conventions and instruction surfaces
  classify operating characteristics
  synthesize an evidence-backed Project Profile

Prescription
  assess AI-native readiness
  produce greenfield bootstrap or brownfield AdoptionChangeSet
  derive causal Work Items
  derive governance / role / interaction / evidence requirements

Compilation
  resolve Project Toolkit + Toolkit Lock
  resolve least-capability Task Toolkit
  preflight IntegrationSpec / SecretRef requirements
  compile Execution Bundle
  render concise agent-facing projections

Validation
  validate schemas / compatibility
  reject unsafe or contradictory contracts
  preserve provenance / confidence for material inferences
  produce evidence / receipt outputs for the preview flow
```

The V0.1 flow should work for both a controlled/synthetic fixture and at least one meaningful brownfield repository.

## 3. Explicitly not required for v0.1.0

The following are valuable but are **not release blockers for the first public preview**:

- broad `Controlled Apply` that automatically rewrites arbitrary project files;
- autonomous agent dispatch or long-running orchestration;
- production deployment automation;
- live write adapters for every tracker/repository provider;
- MCP server implementation;
- MCP Tasks / background execution;
- large Skill, integration, provider, or marketplace catalogs;
- SaaS, billing, multi-tenancy, or hosted control plane.

These remain post-Core work.

An earlier version of this section predicted that the next product line would be
`v0.2.x → bounded Controlled Apply → safe project mutation / rollback receipts → first
MCP facade → selected live adapters`. That prediction is withdrawn: it named the V0.3
boundary. Controlled Apply, real execution identity, MCP, and live write adapters all
sit **after** V0.2.

The V0.2 line is a contract and modelling line, not an execution line:

```text
v0.2.x
→ rebase the contract surface and compatibility boundary onto schema 0.2
→ first-class descriptive project and outcome contracts
→ operating-model / decision-rights profiles
→ still no Controlled Apply, no execution runtime, no MCP facade
```

Nothing in this paragraph is evidence that any of it is implemented. The current,
per-seam disposition — what is changed, what is planned, and what is only recorded —
is `docs/contracts/v0.2-contract-delta.md`.

The exact boundary of any line beyond the current one should stay evidence-driven after dogfooding rather than precommitted as a large roadmap.

## 4. Public repository gate

Changing repository visibility to public is a separate gate from merely merging V0.1 implementation code.

Before public visibility, verify all of the following:

### Product evidence

- AF1–AF8 or their accepted causal replacements are complete.
- Fresh-checkout tests pass.
- The documented CLI/API preview path works end to end.
- Greenfield and brownfield fixtures demonstrate materially different but coherent behavior.
- Generated artifacts are useful without hidden prompt context.
- Known limitations are explicit.

### Public hygiene

- No private repository dependencies in public contracts.
- No private project names in durable public content.
- No tracker content or tracker addresses in durable public content, and no tracker identifiers in consumer-facing documentation. See §4.1.
- No personal filesystem paths — including inside captured command output. A verification transcript pasted into a durable document is durable public content, and transcripts are where this leaks.
- No real secrets, API keys, tokens, credentials, or private fixture data.
- Examples are synthetic/public-safe.
- README, LICENSE, CHANGELOG, release notes, and contributor-facing install instructions are coherent.

### 4.1 Tracker identifiers: what is prohibited, and the one carve-out

This clause originally read "no private project names or internal tracker identifiers in durable public content", unqualified. Preparing the first public release showed that to be both too broad and too vague to apply, so it is stated exactly here rather than left to be interpreted differently each time.

**Prohibited unconditionally: tracker content and tracker addresses.** An issue description, a comment thread, a review document, or any URL into the tracker. This is the leak the rule exists to prevent. A bare key reveals only that an item exists; a URL or a pasted description reveals what is in it and where to find more, and it exposes the workspace itself. An automated linkback that publishes issue bodies into a public repository falls here, whoever configured it.

**Prohibited in consumer-facing documentation.** A reader of the release cannot open an internal issue. In a README, a release note, or any report written for that reader, a tracker key is a dead pointer: it costs attention and returns nothing. State the fact the key stands for instead. If the fact is not worth stating, the reference was not worth making.

**Permitted: a bare tracker key as source-level provenance.** A comment naming the Work Item that caused a regression test to exist answers a question the code cannot otherwise answer — *why does this test exist?* — and it is read by a contributor, not a consumer. This project treats evidence that supports its own claim as a first-class property; severing the causal link between a regression test and the defect that produced it removes exactly that. A bare key is opaque, carries no content, and the same keys are already permanent in merged pull-request titles, so deleting them from source would not make them unpublished. The same permission covers commit messages and pull-request metadata, under the same limit: the key alone, never a URL and never pasted content.

The distinction is provenance versus reference. A key that records *why a durable artifact is the way it is* is provenance and may stay. A key used as an incidental label, or as a stand-in for a fact the text could simply state, is a reference and should go.

### GitHub history / object hygiene

Branch history cleanup alone is not sufficient if historical pull-request objects expose material that should not become public.

The current private repository previously contained merged PR objects created before the public-contract cleanup. Before changing visibility, explicitly audit PR discussions/diffs and other durable GitHub objects. If they contain references that should not become public, prefer recreating/reinitializing the public repository from the accepted clean tree rather than assuming a force-pushed branch history removed those objects.

This visibility operation is intentionally outside ordinary feature development because repository recreation/history changes are destructive publication actions.

## 5. Package versioning

Agent Foundry uses Semantic Versioning principles with additional caution while `<1.0.0`.

```text
MAJOR.MINOR.PATCH
```

Before `1.0.0`:

- **MINOR** may include material contract/schema/API changes and capability-boundary changes.
- **PATCH** should remain backward-compatible bug fixes, validation corrections, documentation corrections, and safe implementation refinements.
- pre-release/development identifiers may be used before a public tag.

Development line before the first public tag:

```text
0.1.0.dev0
```

First public preview after the release gate:

```text
v0.1.0
```

Do not create the `v0.1.0` Git tag merely because package metadata says `0.1.0`; the tag is release evidence and is created only after the public release gate passes.

## 6. Artifact and schema versioning

The package version is not sufficient to version all project-generated artifacts.

At minimum version independently:

- Project Manifest schema;
- Project Profile / finding schema where serialized;
- Work Item contract schema;
- Toolkit Lock schema;
- Capability / Skill / Workflow metadata schema;
- Integration adapter contract;
- Execution Bundle schema;
- Evidence / Execution Receipt schema.

Example:

```yaml
schema_version: 1
foundry_compat: ">=0.2,<0.3"
```

Rules:

- incompatible versions fail explicitly;
- global registry updates do not silently alter an existing Toolkit Lock;
- migration, if introduced, is explicit rather than implicit;
- generated artifacts retain enough identity to explain which Foundry/schema/toolkit version produced them.

## 7. Release workflow

A release should follow:

```text
implementation complete
→ deterministic validation
→ end-to-end preview proof
→ public-hygiene audit
→ version freeze
→ CHANGELOG / release notes
→ clean release commit
→ Git tag vX.Y.Z
→ fresh-install verification
→ release publication
```

For `v0.1.0`, package metadata should move from `0.1.0.dev0` to `0.1.0` only at the release-preparation boundary.

## 8. Changelog policy

`CHANGELOG.md` tracks user-visible changes using an `Unreleased` section.

Changes should be grouped by meaningful product impact rather than every internal commit.

Suggested categories:

- Added
- Changed
- Fixed
- Security / Safety
- Deprecated
- Removed

At release, move the accepted entries under the released version/date and create a fresh `Unreleased` section.

## 9. Stability promise

`v0.x` is an experimental public line, not a stable `1.0` API promise.

However, experimental does not mean arbitrary:

- breaking changes must be explicit;
- generated artifacts remain versioned;
- compatibility failures are surfaced rather than silently coerced;
- public documentation states implemented versus planned capabilities accurately;
- project-local output should remain auditable and reproducible from pinned inputs.

`1.0.0` should be considered only after the project demonstrates repeated successful use across materially different greenfield and brownfield projects and the core project/profile/work/toolkit/execution contracts have stopped changing rapidly.
