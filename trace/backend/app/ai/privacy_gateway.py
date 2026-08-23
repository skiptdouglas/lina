"""AI Privacy Gateway (brief §32).

    Investigation → retrieve evidence → pseudonymise → remove prohibited fields
                  → AI provider → validate response → attach evidence references
                  → analyst

Two rules hold regardless of provider:

1. The frontend never talks to a model. There is no browser-reachable model
   credential anywhere in TRACE.
2. Nothing leaves this process without passing :meth:`PrivacyGateway.prepare`.

Implemented in Sprint 6 — see docs/ROADMAP.md#sprint-6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.ai.provider import InvestigationContext

#: Fields never sent to a model provider, whatever the question.
PROHIBITED_FIELDS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "private_key",
        "credential",
        "authorization",
        "cookie",
        "session_id",
        "email_body",
        "attachment_bytes",
        "raw_payload",
    }
)


@dataclass(slots=True)
class RedactionProfile:
    """What a given request is permitted to send."""

    name: str = "default"
    pseudonymise_users: bool = True
    pseudonymise_hosts: bool = True
    pseudonymise_ips: bool = False
    strip_command_line_secrets: bool = True
    prohibited_fields: frozenset[str] = field(default_factory=lambda: PROHIBITED_FIELDS)


class PrivacyGateway(ABC):
    """The only path between TRACE data and a model provider."""

    @abstractmethod
    async def prepare(
        self, context: InvestigationContext, profile: RedactionProfile
    ) -> InvestigationContext:
        """Pseudonymise and strip context before it leaves the process."""

    @abstractmethod
    async def validate_response(self, response_text: str) -> str:
        """Reject or repair a model response that violates the output contract."""
