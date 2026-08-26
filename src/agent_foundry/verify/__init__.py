"""Validation, evidence, reconciliation, and learning Core API.

Protocol-neutral by construction: every entry point below takes contracts and
returns contracts. A future MCP facade calls these same functions rather than
re-implementing the business logic behind a second surface.
"""

from agent_foundry.verify.claims import CLAIMS_BY_ID, VALIDATOR_CLAIMS, VALIDATOR_IDS
from agent_foundry.verify.explain import (
    assess_inferred_fact_tightening,
    build_decision_trace,
    validate_decision_explainability,
)
from agent_foundry.verify.failures import classify_failure, classify_repeated_failures
from agent_foundry.verify.receipt import (
    artifact_digest,
    build_execution_receipt,
    receipt_artifacts,
)
from agent_foundry.verify.reconcile import reconcile_work_item
from agent_foundry.verify.slice import CompiledSlice, validate_compiled_slice
from agent_foundry.verify.validators import (
    validate_authority_ceiling,
    validate_evidence_bundle_completeness,
    validate_execution_bundle_completeness,
    validate_integration_preflight,
    validate_lifecycle_separation,
    validate_provenance_completeness,
    validate_receipt_completeness,
    validate_required_evidence,
    validate_role_separation,
    validate_contract_schema_compatibility,
    validate_toolkit_coherence,
    validate_work_dependency_graph,
    validate_write_scope_containment,
)

__all__ = [
    "CLAIMS_BY_ID",
    "CompiledSlice",
    "VALIDATOR_CLAIMS",
    "VALIDATOR_IDS",
    "artifact_digest",
    "assess_inferred_fact_tightening",
    "build_decision_trace",
    "build_execution_receipt",
    "classify_failure",
    "classify_repeated_failures",
    "receipt_artifacts",
    "reconcile_work_item",
    "validate_compiled_slice",
    "validate_authority_ceiling",
    "validate_decision_explainability",
    "validate_evidence_bundle_completeness",
    "validate_execution_bundle_completeness",
    "validate_integration_preflight",
    "validate_lifecycle_separation",
    "validate_provenance_completeness",
    "validate_receipt_completeness",
    "validate_required_evidence",
    "validate_role_separation",
    "validate_contract_schema_compatibility",
    "validate_toolkit_coherence",
    "validate_work_dependency_graph",
    "validate_write_scope_containment",
]
