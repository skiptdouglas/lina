"""AI response contract and the FACT/INFERENCE/HYPOTHESIS/UNKNOWN guardrail.

Brief §35 and §36. The guardrail is enforced structurally: a statement with no
evidence reference **cannot** be serialized as a ``FACT``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class StatementKind(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class EvidenceReference(BaseModel):
    """A pointer an analyst can click through to the original bytes."""

    evidence_id: str
    event_ids: list[str] = []
    raw_reference: str | None = None
    sha256: str | None = None
    description: str | None = None


class Statement(BaseModel):
    kind: StatementKind
    text: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidenceReference] = []

    @model_validator(mode="after")
    def _facts_require_evidence(self) -> Statement:
        if self.kind == StatementKind.FACT and not self.evidence:
            raise ValueError(
                "A statement without an evidence reference cannot be classified as FACT."
            )
        return self


class InvestigationResponse(BaseModel):
    """The only shape the AI investigator may return (brief §35)."""

    summary: str
    facts: list[Statement] = []
    inferences: list[Statement] = []
    hypotheses: list[Statement] = []
    unknowns: list[Statement] = []
    evidence: list[EvidenceReference] = []
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _kinds_match_buckets(self) -> InvestigationResponse:
        buckets = (
            (self.facts, StatementKind.FACT),
            (self.inferences, StatementKind.INFERENCE),
            (self.hypotheses, StatementKind.HYPOTHESIS),
            (self.unknowns, StatementKind.UNKNOWN),
        )
        for statements, expected in buckets:
            for statement in statements:
                if statement.kind != expected:
                    raise ValueError(
                        f"Statement of kind {statement.kind} placed in the {expected} bucket."
                    )
        return self
