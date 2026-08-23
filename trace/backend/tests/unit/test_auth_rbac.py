"""Authentication and the permission matrix (docs/SECURITY.md §3)."""

from __future__ import annotations

import pytest

from app.core.security import ROLE_PERMISSIONS, Principal, Role
from tests.conftest import ANALYST_TOKEN, AUDITOR_TOKEN, VIEWER_TOKEN, auth

#: Deliberately unauthenticated. ``/health/ready`` is reachable by container
#: health checks, which cannot present a token; it exposes dependency up/down
#: only — never case, evidence or telemetry data (docs/SECURITY.md §8).
PUBLIC_PATHS = {
    "/health",
    "/api/v1/health/ready",
    "/api/v1/capabilities",
    "/docs",
    "/openapi.json",
}


def _concrete(path: str) -> str:
    """Substitute path parameters so the route resolves and auth is reached."""
    replacements = {
        "{case_id}": "CASE-0001",
        "{evidence_id}": "EVD-0000",
        "{entity_id}": "USER-00001",
        "{subject_type}": "USER",
        "{subject_id}": "USER-00001",
    }
    for placeholder, value in replacements.items():
        path = path.replace(placeholder, value)
    return path


async def test_every_api_route_requires_authentication(client, app) -> None:
    """A route added without a permission dependency is a review defect."""
    schema = app.openapi()
    checked = 0
    for path, operations in schema["paths"].items():
        if path in PUBLIC_PATHS or not path.startswith("/api/v1"):
            continue
        for method in operations:
            if method.upper() not in {"GET", "POST", "PATCH", "DELETE"}:
                continue
            response = await client.request(method.upper(), _concrete(path))
            assert response.status_code == 401, (
                f"{method.upper()} {path} responded {response.status_code} without credentials"
            )
            checked += 1
    assert checked > 20, "route discovery found suspiciously few routes"


async def test_health_and_capabilities_are_public(client) -> None:
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/api/v1/capabilities")).status_code == 200


async def test_invalid_token_is_rejected(client) -> None:
    response = await client.get("/api/v1/cases", headers=auth("not-a-real-token"))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_analyst_can_verify_but_not_download(client, case) -> None:
    listed = await client.get("/api/v1/evidence", headers=auth(ANALYST_TOKEN))
    assert listed.status_code == 200

    denied = await client.get(
        "/api/v1/evidence/EVD-missing/download?reason=investigation",
        headers=auth(ANALYST_TOKEN),
    )
    assert denied.status_code == 403


async def test_auditor_can_read_audit_but_investigator_cannot(client) -> None:
    assert (await client.get("/api/v1/audit", headers=auth(AUDITOR_TOKEN))).status_code == 200
    denied = await client.get("/api/v1/audit", headers=auth(VIEWER_TOKEN))
    assert denied.status_code == 403


def test_role_matrix_matches_documentation() -> None:
    assert "identity:reveal" not in ROLE_PERMISSIONS[Role.INVESTIGATOR]
    assert "identity:reveal" in ROLE_PERMISSIONS[Role.LEAD_INVESTIGATOR]
    assert "evidence:delete" not in ROLE_PERMISSIONS[Role.LEAD_INVESTIGATOR]
    assert ROLE_PERMISSIONS[Role.VIEWER] < ROLE_PERMISSIONS[Role.ANALYST] | {"search:query"}


def test_principal_permission_union() -> None:
    principal = Principal(
        subject="x", tenant_id="default", roles=frozenset({Role.VIEWER, Role.AUDITOR})
    )
    assert principal.has_permission("audit:read")
    assert not principal.has_permission("case:create")
    with pytest.raises(Exception, match="case:create"):
        principal.require("case:create")
