"""Authentication, roles and permissions.

The permission matrix is the single source of truth for authorization and is
mirrored in docs/SECURITY.md §3.
"""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.config import Settings
from app.core.errors import Forbidden, Unauthorized


class Role(StrEnum):
    ADMIN = "ADMIN"
    LEAD_INVESTIGATOR = "LEAD_INVESTIGATOR"
    INVESTIGATOR = "INVESTIGATOR"
    ANALYST = "ANALYST"
    AUDITOR = "AUDITOR"
    VIEWER = "VIEWER"
    SERVICE = "SERVICE"


# Permission vocabulary --------------------------------------------------------
CASE_READ = "case:read"
CASE_CREATE = "case:create"
CASE_UPDATE = "case:update"
EVIDENCE_READ = "evidence:read"
EVIDENCE_CREATE = "evidence:create"
EVIDENCE_VERIFY = "evidence:verify"
EVIDENCE_DOWNLOAD = "evidence:download"
EVIDENCE_DELETE = "evidence:delete"
SEARCH_QUERY = "search:query"
DETECTION_RUN = "detection:run"
AI_QUERY = "ai:query"
IDENTITY_REVEAL = "identity:reveal"
AUDIT_READ = "audit:read"
#: Read the transparency log, fetch proof bundles, verify anchors.
ANCHOR_READ = "anchor:read"
#: Publish a signed tree head to a ledger (costs money on some backends).
ANCHOR_CREATE = "anchor:create"
REPORT_GENERATE = "report:generate"
ADMIN_MANAGE = "admin:manage"

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        CASE_READ,
        CASE_CREATE,
        CASE_UPDATE,
        EVIDENCE_READ,
        EVIDENCE_CREATE,
        EVIDENCE_VERIFY,
        EVIDENCE_DOWNLOAD,
        EVIDENCE_DELETE,
        SEARCH_QUERY,
        DETECTION_RUN,
        AI_QUERY,
        IDENTITY_REVEAL,
        AUDIT_READ,
        ANCHOR_READ,
        ANCHOR_CREATE,
        REPORT_GENERATE,
        ADMIN_MANAGE,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ADMIN: ALL_PERMISSIONS,
    Role.LEAD_INVESTIGATOR: frozenset(
        {
            CASE_READ, CASE_CREATE, CASE_UPDATE,
            EVIDENCE_READ, EVIDENCE_CREATE, EVIDENCE_VERIFY, EVIDENCE_DOWNLOAD,
            SEARCH_QUERY, DETECTION_RUN, AI_QUERY, IDENTITY_REVEAL,
            AUDIT_READ, ANCHOR_READ, ANCHOR_CREATE, REPORT_GENERATE,
        }
    ),
    Role.INVESTIGATOR: frozenset(
        {
            CASE_READ, CASE_CREATE, CASE_UPDATE,
            EVIDENCE_READ, EVIDENCE_CREATE, EVIDENCE_VERIFY, EVIDENCE_DOWNLOAD,
            SEARCH_QUERY, DETECTION_RUN, AI_QUERY, REPORT_GENERATE,
            ANCHOR_READ,
        }
    ),
    Role.ANALYST: frozenset(
        {
            CASE_READ, EVIDENCE_READ, EVIDENCE_VERIFY, SEARCH_QUERY,
            DETECTION_RUN, AI_QUERY, ANCHOR_READ,
        }
    ),
    # An auditor's whole job is checking the custody record, so they can read
    # the log and pull proof bundles — but not spend gas creating anchors.
    Role.AUDITOR: frozenset(
        {CASE_READ, EVIDENCE_READ, EVIDENCE_VERIFY, AUDIT_READ, ANCHOR_READ}
    ),
    Role.VIEWER: frozenset({CASE_READ, EVIDENCE_READ, SEARCH_QUERY}),
    Role.SERVICE: frozenset(
        {
            CASE_READ, CASE_CREATE,
            EVIDENCE_READ, EVIDENCE_CREATE, EVIDENCE_VERIFY,
            SEARCH_QUERY, DETECTION_RUN, ANCHOR_READ, ANCHOR_CREATE,
        }
    ),
}

#: Actions that must carry an analyst-supplied justification (docs/SECURITY.md §3).
REASON_REQUIRED_PERMISSIONS: frozenset[str] = frozenset(
    {EVIDENCE_DOWNLOAD, IDENTITY_REVEAL}
)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. ``tenant_id`` is never taken from the request body."""

    subject: str
    tenant_id: str
    roles: frozenset[Role]
    display_name: str = ""
    auth_method: str = "token"
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def permissions(self) -> frozenset[str]:
        granted: set[str] = set()
        for role in self.roles:
            granted |= ROLE_PERMISSIONS.get(role, frozenset())
        return frozenset(granted)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, *permissions: str) -> None:
        missing = [p for p in permissions if not self.has_permission(p)]
        if missing:
            raise Forbidden(f"Missing permission(s): {', '.join(sorted(missing))}")


class Authenticator(ABC):
    """Pluggable authentication (token today, OIDC in Sprint 7)."""

    mode: str

    @abstractmethod
    def authenticate(self, credential: str | None) -> Principal:
        """Return a principal or raise :class:`Unauthorized`."""


class TokenAuthenticator(Authenticator):
    """Bearer tokens loaded from configuration/secret storage.

    Tokens are compared with :func:`secrets.compare_digest` and never logged.
    """

    mode = "token"

    def __init__(self, registry: dict[str, dict], default_tenant: str) -> None:
        self._registry = registry
        self._default_tenant = default_tenant

    def authenticate(self, credential: str | None) -> Principal:
        if not credential:
            raise Unauthorized("Missing bearer token.")
        if not self._registry:
            raise Unauthorized("No API tokens are configured on this deployment.")
        for token, spec in self._registry.items():
            if secrets.compare_digest(credential, token):
                return self._principal_from_spec(spec)
        raise Unauthorized("Invalid bearer token.")

    def _principal_from_spec(self, spec: dict) -> Principal:
        roles = frozenset(
            Role(role) for role in spec.get("roles", []) if role in Role.__members__
        )
        if not roles:
            raise Unauthorized("Token carries no usable role.")
        return Principal(
            subject=spec.get("subject", "unknown"),
            tenant_id=spec.get("tenant", self._default_tenant),
            roles=roles,
            display_name=spec.get("display_name", spec.get("subject", "unknown")),
            auth_method="token",
        )


class DevAuthenticator(Authenticator):
    """Development convenience only — refused when TRACE_ENV is staging/prod."""

    mode = "dev"

    def __init__(self, default_tenant: str) -> None:
        self._default_tenant = default_tenant

    def authenticate(self, credential: str | None) -> Principal:  # noqa: ARG002
        return Principal(
            subject="dev.principal",
            tenant_id=self._default_tenant,
            roles=frozenset({Role.ADMIN}),
            display_name="Development principal",
            auth_method="dev",
        )


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth_mode == "dev":
        if settings.is_production:  # defence in depth; config also refuses this
            raise RuntimeError("Dev authentication is not permitted outside development.")
        return DevAuthenticator(settings.default_tenant)
    return TokenAuthenticator(settings.token_registry, settings.default_tenant)
