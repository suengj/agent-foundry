"""Rules that gate artifact construction — the producer side of the boundary.

These helpers decide whether a `RunFinding` or an `ExecutionReceipt` may exist at
all. They are producers, and the validation layer must never reach them: a validator
that calls one agrees with it however wrong it is, which is the defect AF6 was
blocked for twice. `agent_foundry.verify.independent` restates the same obligations
from `docs/foundry/06` §4 and §9 as separate constructions.

They live in their own private module so that the boundary is an *import* boundary
rather than a naming convention. `models/interaction.py` reaches them from inside the
validator bodies, so importing the DTOs does not put these functions — or this module
— into any namespace a verifier can walk to. Capturing a function object requires
naming the module that holds it, and no module under `verify/` is permitted to name
this one. See `tests/test_verify_independence.py` for the guard and
`agent_foundry.verify.claims` for what that guard does and does not prove.
"""

from __future__ import annotations

from agent_foundry.models.common import EvidenceState, FindingDisposition


def disposition_obligation_violations(
    *,
    disposition: FindingDisposition | str,
    finding_id: str,
    evidence_refs: list[str],
    follow_up_work_ref: str | None,
    falsifiable_prediction: str | None,
    evidence_condition: str | None,
    escalation_reason: str | None,
) -> list[str]:
    """Obligations a disposition owes, expressed over plain values."""
    violations: list[str] = []
    value = disposition.value if isinstance(disposition, FindingDisposition) else str(disposition)
    if value == FindingDisposition.BLOCKER.value and not evidence_refs:
        violations.append(f"finding {finding_id!r}: BLOCKER requires at least one evidence_ref")
    if value == FindingDisposition.RESIDUAL.value and not follow_up_work_ref:
        violations.append(f"finding {finding_id!r}: RESIDUAL requires follow_up_work_ref")
    if value == FindingDisposition.HYPOTHESIS.value:
        if not falsifiable_prediction:
            violations.append(
                f"finding {finding_id!r}: HYPOTHESIS requires falsifiable_prediction"
            )
        if not evidence_condition:
            violations.append(f"finding {finding_id!r}: HYPOTHESIS requires evidence_condition")
    if value == FindingDisposition.HUMAN_REQUIRED.value and not escalation_reason:
        violations.append(f"finding {finding_id!r}: HUMAN_REQUIRED requires escalation_reason")
    return violations


def evidence_state_partition_violations(
    *,
    attained: list[str],
    not_required: list[str],
) -> list[str]:
    """Partition rules for the two evidence-state lists, over plain values.

    A state cannot be both attained and exempt, and `NOT_REQUIRED` is the marker for
    the exempt list rather than an attainment.
    """
    violations: list[str] = []
    overlap = sorted(set(attained) & set(not_required))
    if overlap:
        violations.append(
            f"evidence states {overlap} are declared both attained and not-required"
        )
    if EvidenceState.NOT_REQUIRED.value in attained:
        violations.append(
            "NOT_REQUIRED is an exemption, not an attained evidence state"
        )
    return violations
