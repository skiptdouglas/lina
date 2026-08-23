"""Auditable actions (docs/DATA_MODEL.md §3, brief §9)."""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    # Chain of custody
    COLLECT = "COLLECT"
    STORE = "STORE"
    VERIFY = "VERIFY"
    VIEW = "VIEW"
    PARSE = "PARSE"
    SEARCH = "SEARCH"
    EXPORT = "EXPORT"
    DOWNLOAD = "DOWNLOAD"
    AI_ACCESS = "AI_ACCESS"
    IDENTITY_REVEAL = "IDENTITY_REVEAL"
    REPORT = "REPORT"
    # Platform lifecycle
    CASE_CREATE = "CASE_CREATE"
    CASE_UPDATE = "CASE_UPDATE"
    DETECTION_RUN = "DETECTION_RUN"
    GRAPH_QUERY = "GRAPH_QUERY"
    LOGIN = "LOGIN"
    AUTH_FAILURE = "AUTH_FAILURE"


class ActorType(StrEnum):
    USER = "USER"
    SERVICE = "SERVICE"
    SYSTEM = "SYSTEM"


#: Actions that are meaningless without a written justification.
REASON_REQUIRED: frozenset[AuditAction] = frozenset(
    {AuditAction.IDENTITY_REVEAL, AuditAction.EXPORT, AuditAction.DOWNLOAD}
)
