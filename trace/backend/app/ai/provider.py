"""AI provider abstraction (brief §33).

Ollama is the first implementation (Sprint 6); OpenAI, Azure OpenAI, Anthropic
and vLLM implement the same interface. Nothing in the product path may import
a provider SDK directly — everything goes through this interface *and* the
privacy gateway.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.ai.schemas import InvestigationResponse


@dataclass(slots=True)
class InvestigationContext:
    """Retrieved, already-pseudonymised context for a single question.

    Never the whole datastore (brief §34): the retriever selects a bounded set
    of events, entities and evidence references relevant to the question.
    """

    case_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    detections: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    token_budget: int = 8000


class AIProvider(ABC):
    """Model backend. Implementations must be stateless and cancellable."""

    name: str
    model: str

    @abstractmethod
    async def investigate(
        self, context: InvestigationContext, question: str
    ) -> InvestigationResponse: ...

    @abstractmethod
    async def summarize(self, context: InvestigationContext) -> str: ...

    @abstractmethod
    async def generate_report(self, case: dict[str, Any]) -> str: ...

    @abstractmethod
    async def health(self) -> bool: ...
