"""What each validator proves, and what it does not.

This catalog is part of the contract, not documentation about it. A validator whose
claim is absent — or a claim with no validator — fails a test, so the honest answer
to "what does this check actually establish?" cannot drift away from the code.

`independently_derived` means the validator restates the property from the durable
contract and shares no implementation with anything that produces or gates the
artifact — including the pydantic model validators, which are producers: they decide
whether an artifact may exist at all. Two entries here were wrongly marked True in
the first version of this change because their obligations were delegated to a
model-validator helper.

Two guards now hold that line, on purpose:

* `tests/test_verify_independence.py` reads the import graph of every module in
  `verify/` and discovers producer-owned rules from `models/` rather than from a
  list. Cheap, fast, and catches the ordinary regression — but it is syntactic, so a
  call assembled at runtime is invisible to it.
* `tests/test_verify_producer_tripwire.py` wraps every producer rule and runs the
  whole validation surface, failing if validation logic calls one by any route:
  dynamic import, re-export, `getattr`, or function-local import. It distinguishes
  that from the legitimate case — pydantic constructing a model — by which boundary
  the call stack crosses first.

A claim of independence therefore rests on observed behavior, not on how the source
happens to be spelled.
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
            "independent fields with disjoint vocabularies, that a receipt does not "
            "collapse them into one status, that every value in BOTH evidence lists "
            "names a real evidence state, that no state is both attained and exempt, "
            "and that a lifecycle claiming closure is backed by the evidence states the "
            "work item requires. The partition is derived from the evidence progression "
            "in verify.independent — NOT_REQUIRED has no rung, so it cannot have been "
            "attained, and it cannot exempt itself either — rather than from the "
            "ExecutionReceipt model validator that gates construction. Both lists are "
            "checked against the vocabulary: an unrecognised exemption is BLOCKED, "
            "because an exemption naming no evidence state lifts no obligation"
        ),
        cannot_prove=(
            "that the three recorded values were observed independently; it detects "
            "conflation of the record, not of the observation"
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
