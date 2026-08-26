"""Agent interaction, evidence, review, and execution receipt contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_serializer, field_validator

from agent_foundry.models.base import FoundryModel, VersionedContract, serialize_datetime_utc
from agent_foundry.models.common import (
    EvidenceState,
    ExecutionState,
    MessageType,
    ReviewOutcome,
    WorkLifecycleState,
)


class Handoff(FoundryModel):
    """Structured handoff between roles."""

    message_type: MessageType = MessageType.HANDOFF
    work_item_id: str
    run_id: str
    sender_role: str
    receiver_role: str
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class EvidenceItem(FoundryModel):
    """Single evidence artifact reference."""

    kind: str
    ref: str
    description: str | None = None


class EvidenceBundle(VersionedContract):
    """Collected evidence for work verification."""

    work_item_id: str
    run_id: str
    items: list[EvidenceItem] = Field(default_factory=list)


class ReviewDecision(FoundryModel):
    """Independent review outcome."""

    work_item_id: str
    run_id: str
    reviewer_role: str
    outcome: ReviewOutcome
    findings: list[str] = Field(default_factory=list)
    blocking: bool = False


class ExecutionReceipt(VersionedContract):
    """Receipt of an execution run with outcome."""

    work_item_id: str
    run_id: str
    role_id: str
    work_lifecycle_state: WorkLifecycleState
    execution_state: ExecutionState
    evidence_state: EvidenceState
    started_at: datetime
    finished_at: datetime | None = None
    evidence_bundle_id: str | None = None

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def _parse_datetime(cls, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise TypeError(f"expected datetime or ISO-8601 string, got {type(value)!r}")

    @field_serializer("started_at", "finished_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return serialize_datetime_utc(value)
