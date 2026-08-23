"""Shared test fixtures.

Tests run against the real application object with two substitutions:
an in-memory object store and a file-backed SQLite metadata database. The
ingest/verify code paths under test are the production ones.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.evidence.storage import InMemoryObjectStore
from app.main import create_app

ADMIN_TOKEN = "test-token-admin"
INVESTIGATOR_TOKEN = "test-token-investigator"
ANALYST_TOKEN = "test-token-analyst"
VIEWER_TOKEN = "test-token-viewer"
AUDITOR_TOKEN = "test-token-auditor"
OTHER_TENANT_TOKEN = "test-token-other-tenant"

TOKENS = {
    ADMIN_TOKEN: {"subject": "admin@trace.test", "roles": ["ADMIN"], "tenant": "default"},
    INVESTIGATOR_TOKEN: {
        "subject": "investigator@trace.test",
        "roles": ["INVESTIGATOR"],
        "tenant": "default",
    },
    ANALYST_TOKEN: {"subject": "analyst@trace.test", "roles": ["ANALYST"], "tenant": "default"},
    VIEWER_TOKEN: {"subject": "viewer@trace.test", "roles": ["VIEWER"], "tenant": "default"},
    AUDITOR_TOKEN: {"subject": "auditor@trace.test", "roles": ["AUDITOR"], "tenant": "default"},
    OTHER_TENANT_TOKEN: {
        "subject": "admin@other.test",
        "roles": ["ADMIN"],
        "tenant": "other-tenant",
    },
}


def auth(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        auth_mode="token",
        api_tokens=json.dumps(TOKENS),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'trace-test.db'}",
        object_store="memory",
        clickhouse_enabled=False,
        audit_clickhouse_mirror=False,
        audit_fail_closed=True,
        rate_limit_enabled=False,
        evidence_max_upload_bytes=1024 * 1024,
        evidence_verify_on_ingest=True,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def object_store(app) -> InMemoryObjectStore:
    return app.state.trace.object_store


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://trace.test") as http_client:
            yield http_client


@pytest.fixture
async def case(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/cases",
        json={
            "title": "Suspected phishing to lateral movement",
            "description": "Synthetic case used by the test-suite.",
            "severity": "HIGH",
            "case_id": "CASE-DEMO-001",
        },
        headers=auth(),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def upload_evidence(
    client: AsyncClient,
    case_id: str,
    *,
    content: bytes = b"Sysmon raw record\n",
    filename: str = "sysmon.jsonl",
    token: str = ADMIN_TOKEN,
    source: str = "FINANCE-LAPTOP-07",
    source_type: str = "SYSMON",
):
    return await client.post(
        "/api/v1/evidence",
        files={"file": (filename, content, "application/octet-stream")},
        data={"case_id": case_id, "source": source, "source_type": source_type},
        headers=auth(token),
    )
