# Agent Foundry

**Agent Foundry is an AI-native project adoption and configuration compiler.**

It takes a new or existing project as input, diagnoses how that project actually operates, prescribes an AI-native operating model, and compiles bounded execution contracts that existing coding agents and AI workers can use.

The core product method is:

```text
Diagnosis
→ Prescription
→ Compilation
→ Controlled Apply
```

The project deliberately works **before and around** execution agents. It is not intended to replace Claude Code, Cursor, Codex, OpenHands, work trackers, secret managers, or long-running agent runtimes.

## Why this exists

Real projects differ materially in architecture, conventions, testability, external side effects, rollback cost, authority, tools, credentials, work-management style, and the evidence required to call work complete.

A fixed prompt or one universal agent template cannot represent those differences reliably.

Agent Foundry treats the **project itself as input** and produces structured, auditable configuration describing how agents should work in that project.

## Product method

### 1. Diagnosis

```text
project / repository
→ inspect current truth
→ discover conventions and instruction surfaces
→ classify operating characteristics
→ synthesize evidence-backed Project Profile
```

### 2. Prescription

```text
Project Profile
→ AI-native readiness assessment
→ greenfield bootstrap or brownfield retrofit plan
→ governance / role / interaction / evidence requirements
→ causal Work Items
→ required project capabilities
```

### 3. Compilation

```text
Project Profile / Manifest
→ Project Toolkit + Toolkit Lock
→ Work Item
→ least-capability Task Toolkit
→ Integration / SecretRef preflight
→ Execution Bundle
→ concise agent-facing projections
```

### 4. Controlled Apply

```text
reviewed adoption change set
→ bounded project mutation
→ validation
→ rollback / adoption receipt
```

Controlled Apply is the intended next layer after the read-only/preview Core has been proven. Broad automatic project mutation is **not required for the first public release**.

## Release status

Current development version:

```text
0.1.0.dev0
```

Target first public release:

```text
v0.1.0 — Public Preview
```

`v0.1.0` is scoped to:

```text
Diagnosis
→ Prescription
→ Compilation
→ Validation
```

It works end to end for both a controlled/synthetic project and a meaningful existing
brownfield project — proved by running it, with the artifacts examined field by field.
The measurements, and everything the run could **not** prove, are in
[`docs/foundry/v0.1-readiness-report.md`](docs/foundry/v0.1-readiness-report.md).
Read [**Known limitations**](#known-limitations) before relying on any of it.

The first public release does **not** require:

- broad Controlled Apply;
- autonomous agent dispatch;
- production deployment automation;
- MCP server implementation;
- large integration/Skill/provider catalogs;
- SaaS or hosted control-plane features.

See [`docs/foundry/09-release-and-versioning.md`](docs/foundry/09-release-and-versioning.md) for the full public-release gate and compatibility policy, [`docs/release-notes/v0.1.0.md`](docs/release-notes/v0.1.0.md) for the release notes, and [`CHANGELOG.md`](CHANGELOG.md) for user-visible evolution.

## End-user flow

These commands ship today, and this is the whole list:

```bash
agent-foundry doctor [<project-path>]         # check the install, and a project if one is in scope
agent-foundry inspect <project-path>          # read-only inventory, conventions, readiness
agent-foundry adopt <project-path>            # ProjectManifest + AdoptionChangeSet (preview only)
agent-foundry resolve-toolkit <project-path>  # version-pinned Project Toolkit, or a Task Toolkit
agent-foundry integration-check <file>        # integration preflight, credentials never read
agent-foundry compile --work-item <file> ...  # ExecutionBundle, or --render for Markdown
agent-foundry validate <artifact> --kind ...  # run every validator that applies to one artifact
agent-foundry version
```

`adopt` is preview-only: it prints a plan and writes nothing. There is no `--apply`.

Still intended, and **not yet built** — no subcommand exists for any of these:

```text
agent-foundry profile <project-path>       # ProjectProfile synthesis as a first-class stage
agent-foundry work plan <objective>        # decomposition from the CLI (Python API only today)
agent-foundry render <execution-bundle>    # standalone render (today: compile --render)
agent-foundry reconcile <project-path>     # reconciliation from the CLI (Python API only today)
agent-foundry adopt <project-path> --apply # controlled mutation surface
```

Everything the CLI does is a thin dispatch over the Python API; there is no logic
behind a command that a Python caller cannot reach. See
[`docs/foundry/v0.1-readiness-report.md`](docs/foundry/v0.1-readiness-report.md) §7.

External mutations remain preview-first unless a narrower project policy explicitly grants bounded automatic authority.

## Core outputs

These contracts are produced today, are versioned, and are serialized to YAML or JSON:

```text
ProjectIntake            ProjectObservation / ReadinessFinding / ClassificationFinding / conventions
ProjectManifest          the project's declared + classified operating characteristics
AdoptionChangeSet        KEEP / CONSOLIDATE / WRAP / HARDEN / MIGRATE / DEFER / BLOCK, preview only
WorkPlan                 causal Work Items with acceptance criteria, scope and typed evidence
ToolkitLock              the version-pinned Project Toolkit
TaskToolkit              the least-capability subset for one Work Item
IntegrationSpec/SecretRef integration declarations and credential coordinates, never values
ExecutionBundle          the compiled, authority-bounded contract for one role and one run
EvidenceBundle           typed evidence classes, results and revision identity
ExecutionReceipt         run identity, content digests, dispositioned findings, limitations
Agent-facing Markdown    a projection of the ExecutionBundle, rendered by `compile --render`
```

Working examples of every one of these are committed under
[`examples/e2e-synthetic/`](examples/e2e-synthetic/) and are regenerated and
byte-compared by the test suite, so an example cannot document a shape the code no
longer produces.

Described in the architecture documents and **not implemented in V0.1**:

```text
ProjectProfile as a first-class synthesized artifact
Governance / Work / Role / Interaction / Evidence profiles as separate contracts
adapter projections other than Markdown
```

Generated Markdown is a projection from structured canonical data, not a second independently maintained source of truth.

## Greenfield and brownfield

Foundry does not assume a new project.

### Greenfield

```text
project goal
→ minimum operating contracts
→ initial profile / manifest
→ work model
→ toolkit
→ agent-ready bootstrap
```

### Brownfield

```text
existing repository
→ inventory current truth and conventions
→ distinguish observed behavior from intended rules
→ assess AI-native readiness
→ propose KEEP / CONSOLIDATE / WRAP / HARDEN / MIGRATE / DEFER / BLOCK
→ preview AdoptionChangeSet
→ progressively retrofit only what is needed
```

The goal is **migration and adaptation, not rewriting a functioning project around Foundry**.

## Project Profile Synthesis

> **Direction, not V0.1 behavior.** What ships today is `ProjectManifest` synthesis from
> owner declarations plus classification findings. The named profiles below are not
> separate contracts in V0.1, and no profile value is supplied by inference — see
> [Known limitations](#known-limitations).

Foundry should not reduce projects to hard-coded categories such as `backend`, `finance`, or `content`.

Instead it derives composable characteristics and synthesizes profiles such as:

```text
Operating Profile
Governance Profile
Work Profile
Role Profile
Interaction Profile
Evidence Profile
Integration Requirements
Toolkit Requirements
```

Material findings retain provenance and uncertainty:

```yaml
key: runtime_mutation
value: true
source: observed
evidence:
  - deploy-config
confidence: 0.98
```

Core rule:

```text
inference may tighten controls
inference must not silently expand authority
```

This keeps the system adaptive without turning it into a hard-coded project-type template engine.

## Work model

Foundry defines work above any specific tracker:

```text
Objective
→ Outcome / Capability
→ Work Package
→ Work Item
→ Execution Run
```

A Work Item is a causal, independently closable capability boundary. It should not be split merely because files, agents, tests, or implementation roles differ.

```text
Work Item state
≠ Execution Run state
≠ Evidence state
```

External trackers are adapters rather than architectural dependencies of the core.

## Toolkit model

```text
Foundry Capability Registry
        ↓
Project Profile / Manifest
        ↓
Project Toolkit
        ↓
Work Item + current truth
        ↓
Task Toolkit
        ↓
Execution Bundle
```

**Project Toolkit** is the version-pinned capability universe approved for the project.

**Task Toolkit** is the least-capability subset needed for one Work Item/run.

Toolkit components may include:

- logical agent roles;
- workflows / Agent Graph nodes;
- Skills and procedures;
- tool-interface profiles;
- MCP/API/CLI integrations;
- permission and execution-budget profiles;
- validators and evidence requirements;
- provider capability profiles;
- context sources and rendering adapters.

Provider/model selection happens after logical role and capability requirements are known.

## Integrations and secrets

Foundry is not a secret vault.

```text
Execution Bundle
→ scoped Integration Adapter
→ SecretRef / delegated identity
→ credential provider
→ external system
```

Version-controlled Foundry configuration stores integration declarations and credential references, never raw API keys or secret values.

Integration availability is explicit:

```text
DESIRED
→ AVAILABLE
→ CONFIGURED
→ AUTHENTICATED
→ AUTHORIZED
→ HEALTHY
```

Credential availability does not imply task authority.

## MCP direction

MCP is planned as an optional **facade**, not the Foundry Core.

```text
                    Agent Foundry Core
                           │
              ┌────────────┼────────────┐
              ↓            ↓            ↓
             CLI       Python API    MCP Server
```

The same deterministic models, resolvers, compilers, and validators must remain usable when MCP is unavailable.

Candidate MCP tools include:

```text
foundry.inspect
foundry.profile
foundry.adopt_preview
foundry.adopt_apply
foundry.work_plan
foundry.resolve_toolkit
foundry.integration_check
foundry.compile
foundry.validate
foundry.reconcile
```

New MCP implementations should pass project directories through tool parameters, resource URIs, or server configuration rather than building new architecture around deprecated MCP Roots.

The first MCP facade is expected after the V0.1 Core unless implementation evidence justifies a smaller earlier adapter.

## Current repository state

The V0.1 slice is implemented and runs end to end. What ships:

- typed, versioned canonical contracts (`agent_foundry.models`) with schema-compatibility enforcement and a write/render embedded-secret guard;
- read-only project inspection: traversal under explicit bounds, observations, convention discovery, classification candidates, readiness findings, and a nested-project boundary (`agent_foundry.inspect`);
- adoption planning: `ProjectManifest` synthesis and a preview-only `AdoptionChangeSet` for greenfield and brownfield (`agent_foundry.adopt`);
- tracker-neutral causal work decomposition with dependency-graph validation (`agent_foundry.work`);
- a capability registry and a deterministic two-stage toolkit resolver producing a version-pinned `ToolkitLock` and a narrowed `TaskToolkit`, with integration preflight (`agent_foundry.toolkit`);
- a Work Item compiler producing an authority-bounded `ExecutionBundle`, and a concise Markdown renderer (`agent_foundry.compile`, `agent_foundry.render`);
- fourteen validators, evidence and receipt contracts, and read-only reconciliation (`agent_foundry.verify`);
- an eight-command CLI that is thin dispatch over that Python API;
- canonical architecture and governance contracts, release/versioning policy, and the MIT License.

Everything the CLI does, a Python caller can do. Nothing in V0.1 mutates a target
project, dispatches an agent, or executes work — see **Known limitations** below.

[`docs/foundry/v0.1-readiness-report.md`](docs/foundry/v0.1-readiness-report.md)
records what the slice proved by running it, what it could not prove, and every
remaining gap.

## Known limitations

These are measured, not estimated. V0.1 is an experimental public preview and these
are the things a reader should know before relying on it.

**Nothing is executed.** V0.1 compiles and verifies contracts. It does not run the
work an `ExecutionBundle` describes. The evidence bundle in an end-to-end run is what
a runtime *would* report, and each receipt records that substitution as a limitation.
"The bundle is coherent" is not "the work was done".

**A project that has not declared itself cannot reach an `ExecutionBundle`.** Inference
may tighten controls but never expand authority, so operating characteristics come from
an owner's `.foundry/project.yaml`, not from guesswork. Measured across 12 local
repositories, the median project populates 1 of 16 manifest dimensions and 11 of 12
resolve no roles and no capabilities at all. This is the defining shape of V0.1
usability. An undeclared brownfield repository is now told so — adoption proposes
`MIGRATE foundry-project-declaration` — rather than being handed a clean-looking plan
over an empty toolkit.

**Convention discovery knows four hardcoded patterns**: a pytest mention in an
instruction surface, a commit constraint in an instruction surface, a Makefile `test`
recipe that invokes pytest, and a CI checkout step. A convention outside those four is
not found at any confidence, and no finding rises above confidence 0.5 because all four
claim a textual mention. The strongest available fact — a declared test runner in
`pyproject.toml` — is not read. Across 12 repositories only three distinct convention
subjects were ever produced.

**The embedded-secret guard is not exhaustive.** Tier A recognises known vendor
credential formats and is the only tier that blocks serialization. It matches at a
token boundary, so a credential glued into a longer identifier with no separator
(`xyzAKIA…`) or joined by an underscore (`svc_AKIA…`) is **not detected by either
tier**, and a credential joined by a hyphen (`orders-service-AKIA…`) falls through to
Tier B. Tier B is entropy-based, **advisory only, and does not block** — and it fires
on ordinary explanation prose, so its findings are not reliable evidence of a secret in
either direction. Do not treat a clean scan as proof that no credential is present.

**The blocked-adoption path is unverified against real input.** `AdoptionAction.BLOCK`
has two emit sites and is exercised by fixtures and unit tests. It was triggered by
**none** of the 12 real repositories surveyed, because readiness assessment never marks
an observable condition as a blocker. Treat brownfield decision-class coverage as
unproven for `BLOCK`.

**Inspection can conclude from an incomplete read, and does not say so.** Traversal
stops at 2000 entries, depth 12, and 64 KB per file. The skips are recorded as
observations, but readiness assessment does not receive the traversal statistics, so it
cannot distinguish "no test entrypoints" from "the walk stopped before `tests/`". 3 of
12 surveyed repositories reached the entry limit and 298 files across them exceeded the
read limit.

**`repository_revision` is unknown in a `git worktree` checkout**, where `.git` is a
file pointing outside the repository root and containment correctly refuses to follow
it. Every downstream identity that binds to a revision — evidence, receipt, and
reconciliation — then has nothing to bind to.

**The nested-project boundary is a heuristic about ownership.** A directory carrying
its own project manifest or its own `.git` is excluded from the target's diagnosis.
That is right for a workspace of independent services and arguably wrong for one
cohesive project split into modules. Every exclusion is recorded as a `nested-project`
observation, so the decision is visible; there is no way to override it today.

**`agent-foundry validate` cannot give a whole-slice verdict.** Six of the fourteen
validators need inputs no single artifact carries. The command reports what it could
not run and exits `3` rather than `0` when anything applicable was skipped. The
whole-slice answer is the Python API `agent_foundry.verify.validate_compiled_slice`;
there is no CLI surface for it.

**Validation proves coherence, not correctness.** `write-scope-containment` proves a
granted path lies inside every declared bound; it cannot prove the bound is the right
bound. `toolkit-coherence` cannot prove a selected subset is the minimum one.
`required-evidence` reads an evidence record; it does not re-run the test.
`receipt-completeness` is not an independent derivation — it binds a receipt to the
artifact handed in for comparison, and both sides wrap the same serializer. Producer
isolation is enforced by import, AST and runtime guards inside one process; a process
boundary is the complete answer and is out of scope for V0.1.

**`WorkClass` serializes as `UPPER_SNAKE`** (`ADOPTION`) while every sibling vocabulary
is `kebab-case`. A hand-authored Work Item YAML must use the upper-case spelling. This
is a contract break to fix and is deferred to a versioned change.

**No `AdoptionChangeSet` → work-plan mapping is published.** `AdoptionGap` exists and
`decompose_work` consumes it, but nothing in `agent_foundry` produces a gap from a
planned change; the end-to-end harness supplies that mapping in the open, because which
changes become work is a policy choice a consumer may reasonably make differently.

## Install

Python `>=3.11` is required. Agent Foundry is not on PyPI yet; install from a clone.

### Use it

```bash
python -m venv .venv
.venv/bin/pip install /path/to/agent-foundry
.venv/bin/agent-foundry version
.venv/bin/agent-foundry doctor
```

`doctor` works from any working directory, including one unrelated to any checkout.
It runs two checks and reports them separately:

| Exit | Meaning |
|---|---|
| `0` | the installed package is intact, and either a project in scope passed or no project was in scope |
| `1` | the **installation itself** is broken — whatever the project check said was produced by code that cannot be trusted, so this outranks any project finding |
| `2` | the installation is fine, but a **target project** is missing artifacts Foundry expects |

The project check is optional and takes an explicit path:

```bash
agent-foundry doctor                 # search upward from the current directory; skip if nothing is found
agent-foundry doctor /path/to/repo   # check that project
```

It discovers a project root by looking for the project's own contract artifacts
(`docs/contracts/product-boundary.md` or `docs/ai/PROJECT_AGENT_CONSTITUTION.md`),
never from the installed package's own location.

### A first run

```bash
agent-foundry inspect  /path/to/repo --format yaml    # read-only inventory and readiness
agent-foundry adopt    /path/to/repo --format yaml    # manifest + change set, preview only
agent-foundry resolve-toolkit /path/to/repo --format yaml
agent-foundry compile  /path/to/repo --work-item work-item.yaml \
                       --role-id builder --run-id run-001 --render
```

Nothing above writes to the target project.

### Work on it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m agent_foundry --help
pytest
```

## Compatibility

`v0.x` is an experimental public line, not a `1.0` API promise. What that means
concretely for a consumer of V0.1:

| Surface | Frozen at V0.1 | What may change before `1.0` |
|---|---|---|
| Serialized contract schema | `schema_version: "0.1"` on every separately-persisted contract | a `0.2` may change contract shapes; incompatibility fails explicitly rather than being coerced |
| Schema acceptance rule | same MAJOR, MINOR no newer than supported — a `0.1` build reads `0.0` and `0.1`, and rejects `0.2` and `1.0` | the rule itself is stable; the supported version moves |
| Registry / lock compatibility | `foundry_compat: ">=0.1,<0.2"` on `CapabilityRegistry` and `ToolkitLock`, compared on MAJOR.MINOR only | a `0.2` package will not load a `0.1`-pinned registry without an explicit, versioned migration |
| Package version | `0.1.0` | `0.1.z` stays backward-compatible; `0.2.0` may change contracts and the capability boundary |
| CLI | the eight subcommands listed above, and their exit codes | subcommands may be added; the five listed as not built are not a promise of their eventual spelling |
| Python API | the names exported from `agent_foundry.models`, `.inspect`, `.adopt`, `.work`, `.toolkit`, `.compile`, `.render`, `.verify` | anything not exported is private and may move without notice |

Rules that hold across the line: an incompatible version fails explicitly; a global
registry update does not silently alter an existing `ToolkitLock`; migration, if
introduced, is explicit; and a generated artifact retains enough identity to say which
Foundry and schema version produced it.

Full policy: [`docs/foundry/09-release-and-versioning.md`](docs/foundry/09-release-and-versioning.md).

## Architecture principles

- Provider-neutral Core; provider identities stay in adapters.
- Source once, compile many.
- Project first, task second.
- Diagnosis precedes prescription and mutation.
- Project characteristics are compositional rather than domain-hardcoded.
- Deterministic invariants + declarative policies + bounded interpretation.
- Observed, declared, inferred, and normative facts stay distinct.
- Confidence/provenance accompany material classifications.
- Hard policies become executable controls where practical.
- Progressive disclosure instead of loading every rule/Skill into every prompt.
- Project Toolkit before Task Toolkit; least capability at execution time.
- Raw secrets are referenced, never embedded.
- Tracker state, execution state, and evidence state remain separate.
- Schemas, toolkits, adapters, and integrations are versioned explicitly.
- Project-local learning is not automatically promoted to a global rule.

## Benchmarks and related projects

Agent Foundry learns from existing open-source systems without trying to clone them.

| Project | Validated primitive | What Foundry borrows | Main distinction |
|---|---|---|---|
| [GitHub Spec Kit](https://github.com/github/spec-kit) | Constitution-driven spec → plan → task workflows | artifact lifecycle, spec/task discipline | Foundry first derives **how agents may operate in this project** |
| [Agent OS](https://github.com/buildermethods/agent-os) | project-standard discovery and relevance-based injection | convention discovery, progressive disclosure | Foundry extends into governance, permissions, integrations, roles, evidence, and toolkit resolution |
| [OpenSpec](https://github.com/Fission-AI/OpenSpec) | brownfield-first delta-oriented changes | current truth vs proposed change | Foundry additionally synthesizes operating profiles and agent constraints |
| [OpenHands](https://github.com/OpenHands/OpenHands) | reusable Skills/plugins and progressive loading | composable Skills and metadata-driven selection | Foundry configures capabilities rather than primarily hosting the execution runtime |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | Agent-Computer Interface design | tool-interface profiles, concise feedback | Foundry configures the project/harness upstream of a task runner |
| [OpenAI Symphony](https://github.com/openai/symphony) | issue → isolated workspace → agent run | Work Item vs Run separation, lease/reconciliation concepts | Symphony is an execution scheduler; Foundry is an upstream adoption/configuration compiler |
| [Model Context Protocol](https://modelcontextprotocol.io/) | standardized tool/context interoperability | optional MCP facade and typed integration boundary | Foundry Core remains protocol-independent |

See [`docs/foundry/08-benchmarks-and-evolution.md`](docs/foundry/08-benchmarks-and-evolution.md).

## What is intentionally different

Foundry's intended niche is not another spec generator, coding agent, workflow runner, or Skills marketplace.

Its core transformation is:

```text
New or existing project
+ human objective
        ↓
Diagnosis
+ adoption prescription
+ operating profiles
+ work model
+ bounded toolkit
+ agent interaction/evidence contracts
        ↓
Agent-ready project environment
```

Execution can then be delegated to the existing agent ecosystem.

## Documentation

Start with [`docs/foundry/00-overview.md`](docs/foundry/00-overview.md).

| Document | Focus |
|---|---|
| `docs/foundry/01-governance-and-control.md` | authority, trust, harness and executable controls |
| `docs/foundry/02-project-intake-and-adoption.md` | classification, greenfield/brownfield adoption, readiness |
| `docs/foundry/03-work-model-and-decomposition.md` | causal work hierarchy and tracker-neutral contracts |
| `docs/foundry/04-toolkit-and-integrations.md` | toolkit resolution, Skills/tools/MCP/API, credentials |
| `docs/foundry/05-orchestration-and-interaction.md` | roles, Agent Graph, communication and handoffs |
| `docs/foundry/06-verification-reconciliation-learning.md` | evidence, reconciliation and learning |
| `docs/foundry/07-implementation-contracts.md` | machine-readable models and implementation sequence |
| `docs/foundry/08-benchmarks-and-evolution.md` | benchmark references, MCP direction and design evolution |
| `docs/foundry/09-release-and-versioning.md` | public release gate, versioning and compatibility policy |
| `docs/foundry/v0.1-readiness-report.md` | what the V0.1 slice proved by running it, and what it could not |
| `docs/foundry/v0.1-release-certification.md` | the V0.1 release gate, verified by execution with output captured |
| `docs/release-notes/v0.1.0.md` | release notes for the first public preview |
| `examples/e2e-synthetic/` | every V0.1 output contract, generated and byte-compared by the tests |

## License

Agent Foundry is released under the [MIT License](LICENSE).
