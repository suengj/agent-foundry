"""What each validator proves, and what it does not.

This catalog is part of the contract, not documentation about it. A validator whose
claim is absent — or a claim with no validator — fails a test, so the honest answer
to "what does this check actually establish?" cannot drift away from the code.

`independently_derived` means the validator restates the property from the durable
contract and shares no implementation with anything that produces or gates the
artifact — including the pydantic model validators, which are producers: they decide
whether an artifact may exist at all.

Three mechanisms hold that line, and none of them is complete on its own:

* **An import boundary.** The two artifact-property rules a validator could be
  tempted to reuse live in a private module of their own under `agent_foundry.models`,
  imported only from inside the model-validator bodies that need them — so importing
  the DTOs does not put those functions, or their module, into any namespace a
  verifier can walk to. No module under `verify/` may name that module, by import,
  attribute, or string literal; this file is subject to that rule too, which is why
  the module is described here rather than spelled. `test_verify_independence.py`
  names it, and the guard's own failure message names it. This is what closes
  *pre-capture*: binding a reference at import time, before anything could patch it.
* **A static rule-name scan**, covering the producer rules that cannot move behind
  that boundary — `validate_schema_compatibility` and `lint_no_raw_secrets` are part
  of the public model API and are called from many places. Cheap and fast, but
  syntactic, so a name assembled at runtime is invisible to it.
* **A runtime tripwire** that wraps each producer rule and fails if validation logic
  calls one while a validator is executing. This covers the live-dynamic route the
  static scans cannot see.

**What this pair does not prove.** An earlier version of this file claimed the
tripwire caught a producer rule "by any route". That was false, and the reason is
ordinary Python semantics rather than a missing case: `monkeypatch.setattr` rebinds a
module dictionary entry and cannot rewrite a reference captured before it installs.
A module-level capture, a closure, a default argument, a `functools.partial`, or an
object handed to another module all keep the original callable. The import boundary
is what actually closes that route for the two rules behind it, and the guards
together are strong evidence rather than a proof.

The residue, stated plainly: a verifier that assembles the module path from pieces at
runtime, or reaches a rule through some future third module that legitimately imports
it, would still escape all three. The complete answer is a
process boundary — running verification in a fresh interpreter whose imports are
restricted to DTOs and independently derived rules, over serialized primitives. That
is out of scope for V0.1 and is recorded here as a limitation, not a promise.
"""

from __future__ import annotations

from agent_foundry.models.verification import ValidatorClaim

CONTRACT_SCHEMA_COMPATIBILITY = "contract-schema-compatibility"
WORK_DEPENDENCY_GRAPH = "work-dependency-graph"
TOOLKIT_COHERENCE = "toolkit-coherence"
AUTHORITY_CEILING = "authority-ceiling"
WRITE_SCOPE_CONTAINMENT = "write-scope-containment"
ROLE_SEPARATION = "role-separation"
INTEGRATION_PREFLIGHT = "integration-preflight"
REQUIRED_EVIDENCE = "required-evidence"
EVIDENCE_BUNDLE_COMPLETENESS = "evidence-bundle-completeness"
PROVENANCE_COMPLETENESS = "provenance-completeness"
EXECUTION_BUNDLE_COMPLETENESS = "execution-bundle-completeness"
LIFECYCLE_SEPARATION = "lifecycle-separation"
RECEIPT_COMPLETENESS = "receipt-completeness"
DECISION_EXPLAINABILITY = "decision-explainability"


VALIDATOR_CLAIMS: tuple[ValidatorClaim, ...] = (
    ValidatorClaim(
        validator_id=CONTRACT_SCHEMA_COMPATIBILITY,
        proves=(
            "every supplied contract declares a parseable MAJOR.MINOR schema_version "
            "within the supported range, and every foundry_compat expression admits "
            "the running package version"
        ),
        cannot_prove=(
            "that the fields inside a compatible contract mean what this version "
            "expects; a version number is a claim about shape, not about semantics"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.models.base.validate_schema_compatibility",
    ),
    ValidatorClaim(
        validator_id=WORK_DEPENDENCY_GRAPH,
        proves=(
            "work item ids are unique, every dependency names a known item, no item "
            "depends on itself, no forward-relation cycle exists, and no pair of "
            "items claims to block each other"
        ),
        cannot_prove=(
            "that the declared dependencies are the real ones; an item that silently "
            "needs another it never names produces a valid graph"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.work.validate.validate_dependency_graph",
    ),
    ValidatorClaim(
        validator_id=TOOLKIT_COHERENCE,
        proves=(
            "the Task Toolkit is a subset of the pinned Project Toolkit on every "
            "component kind, each selected component exists in the registry, skill "
            "and workflow requirements are satisfied within the same lock, every "
            "pinned version names a selected component, and no component is both "
            "included and excluded by the recorded decisions"
        ),
        cannot_prove=(
            "that the selected subset is the *minimum* one; under-selection that "
            "still satisfies every declared requirement is indistinguishable here"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.toolkit.resolve.resolve_task_toolkit",
    ),
    ValidatorClaim(
        validator_id=AUTHORITY_CEILING,
        proves=(
            "compiled authority exceeds no declared bound — manifest ceiling, work "
            "item authority class, permission profile, role capability ceiling — and "
            "that no capability the toolkit allows demands more than it grants"
        ),
        cannot_prove=(
            "that the granted authority is *needed*; an over-tight ceiling that "
            "blocks legitimate work looks identical to a correct one"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.compile.authority.compute_compiled_authority",
    ),
    ValidatorClaim(
        validator_id=WRITE_SCOPE_CONTAINMENT,
        proves=(
            "every granted write path resolves to a usable repository-relative bound "
            "and lies inside both the work item scope and the role write scope, with "
            "traversal, absolute, drive-rooted and root-equivalent bounds granting "
            "nothing, and no path both granted and forbidden"
        ),
        cannot_prove=(
            "that the execution runtime honours the scope; this is a claim about the "
            "contract, not about what a process is able to open"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.compile.authority._normalize_scope_path",
    ),
    ValidatorClaim(
        validator_id=ROLE_SEPARATION,
        proves=(
            "concurrent bundles for one run do not grant overlapping write paths to "
            "different roles, a review-only role holds no write authority, and a "
            "review decision does not name its own implementing role as reviewer"
        ),
        cannot_prove=(
            "that two separate roles were staffed by independent agents or people; "
            "separation of contracts is not separation of judgement"
        ),
        independently_derived=True,
        checks_output_of=None,
    ),
    ValidatorClaim(
        validator_id=INTEGRATION_PREFLIGHT,
        proves=(
            "every required integration is declared, carries an auth block when its "
            "required health implies authentication, and has a *positive observation* "
            "meeting that requirement; an unobserved integration resolves to MISSING"
        ),
        cannot_prove=(
            "that the observation is current or truthful; freshness is checked only "
            "against a supplied clock, and an adapter that reports healthy while "
            "broken is outside what a preflight record can detect"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.toolkit.preflight.preflight_integrations",
    ),
    ValidatorClaim(
        validator_id=REQUIRED_EVIDENCE,
        proves=(
            "each evidence class the work item requires is satisfied by at least one "
            "typed, passing evidence item that names the revision it proves, or is "
            "declared not-required; unrecognised and untyped requirements resolve to "
            "MISSING rather than passing unexamined"
        ),
        cannot_prove=(
            "that the referenced artifact says what the item claims; this validator "
            "reads the evidence record, it does not re-run the test"
        ),
        independently_derived=True,
        checks_output_of=None,
    ),
    ValidatorClaim(
        validator_id=EVIDENCE_BUNDLE_COMPLETENESS,
        proves=(
            "the bundle carries run and work identity, a revision identity block, no "
            "class both attained and exempt, and unresolved findings that each meet "
            "the obligation their disposition owes — the obligations being re-derived "
            "from docs/foundry/06 §9 as a table in verify.independent, not taken from "
            "the RunFinding model validator that gates construction"
        ),
        cannot_prove=(
            "that the bundle is the complete set of evidence produced; a run can "
            "always omit an artifact it never recorded"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.models.interaction.EvidenceBundle",
    ),
    ValidatorClaim(
        validator_id=PROVENANCE_COMPLETENESS,
        proves=(
            "every provenance envelope in the payload names a kind and a source, "
            "every inferred envelope carries a confidence, and every recorded "
            "selection decision cites a project fact or a policy id"
        ),
        cannot_prove=(
            "that a cited source actually supports the claim; provenance is a "
            "pointer, and this checks that the pointer exists and is typed"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.compile.api._execution_bundle_provenance",
    ),
    ValidatorClaim(
        validator_id=EXECUTION_BUNDLE_COMPLETENESS,
        proves=(
            "the bundle names work, run and role, carries an objective, acceptance "
            "criteria, required evidence, stop conditions, a compiled authority and a "
            "task toolkit, and that allowed capabilities are drawn from that toolkit, "
            "are disjoint from the forbidden set, and agree with the authority block"
        ),
        cannot_prove=(
            "that the bundle is sufficient to do the work; completeness of a contract "
            "is not adequacy of a plan"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.compile.api.compile_work_item",
    ),
    ValidatorClaim(
        validator_id=LIFECYCLE_SEPARATION,
        proves=(
            "work lifecycle, execution state and evidence state are recorded as three "
            "independent fields drawn from three disjoint vocabularies; that EVERY "
            "enum-typed position on the receipt — the three state fields and both "
            "evidence lists, nested models included — holds a value from its declared "
            "vocabulary, checked before any membership test, rank lookup or "
            "dereference and BLOCKED when it does not; that a receipt does not "
            "collapse the three into one status; that no state is both attained and "
            "exempt; and that a lifecycle claiming closure is backed by the evidence "
            "states the work item requires. The partition is derived from the evidence "
            "progression in verify.independent — NOT_REQUIRED has no rung, so it "
            "cannot have been attained, and it cannot exempt itself either — rather "
            "than from the ExecutionReceipt model validator that gates construction"
        ),
        cannot_prove=(
            "that the three recorded values were observed independently; it detects "
            "conflation of the record, not of the observation. Nor does a recognised "
            "value mean a true one: this establishes that a state belongs to its "
            "vocabulary, not that the run was in it"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.verify.receipt.build_execution_receipt",
    ),
    ValidatorClaim(
        validator_id=RECEIPT_COMPLETENESS,
        proves=(
            "the receipt names exact work, run, role, revision, toolkit, permission "
            "and budget identities, that each declared artifact digest matches the "
            "artifact supplied for comparison, and that limitations and findings are "
            "recorded rather than left implicit"
        ),
        cannot_prove=(
            "that the digest algorithm or the serializer is correct. This is the one "
            "entry marked not independently derived, and the digest is the reason: "
            "recomputation runs through verify.independent.contract_digest, a call site "
            "deliberately kept separate from the receipt.artifact_digest that stamps a "
            "receipt — so neutralizing the stamp is caught — but both wrap the same "
            "deterministic serializer, and if that serializer were wrong both sides "
            "would be wrong together. The check is worth exactly one thing: a receipt "
            "cannot name a different artifact than the one under review, which is the "
            "property reconciliation depends on. The finding-disposition obligations "
            "this validator also checks ARE independently derived, from the same table "
            "in verify.independent that evidence-bundle completeness uses"
        ),
        independently_derived=False,
        checks_output_of="agent_foundry.verify.receipt.build_execution_receipt",
    ),
    ValidatorClaim(
        validator_id=DECISION_EXPLAINABILITY,
        proves=(
            "every material inferred fact carries provenance kind and confidence, "
            "every selected or excluded component names the facts or policies that "
            "caused it, inferred facts did not raise the authority a declared-only "
            "baseline supports, and the three lifecycles are traceable from the trace"
        ),
        cannot_prove=(
            "that the recorded cause is the real cause; it establishes that a "
            "structured reason exists and is attributable, not that the reasoning was "
            "sound"
        ),
        independently_derived=True,
        checks_output_of="agent_foundry.compile.api.compile_work_item",
    ),
)

CLAIMS_BY_ID: dict[str, ValidatorClaim] = {claim.validator_id: claim for claim in VALIDATOR_CLAIMS}

VALIDATOR_IDS: tuple[str, ...] = tuple(claim.validator_id for claim in VALIDATOR_CLAIMS)
