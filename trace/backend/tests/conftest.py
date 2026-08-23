"""Shared test fixtures.

Tests run against the real application object with two substitutions:
an in-memory object store and a file-backed SQLite metadata database. The
ingest/verify code paths under test are the production ones.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.anchoring.log import reset_root_cache
from app.core.config import Settings
from app.evidence.storage import InMemoryObjectStore
from app.main import create_app

#: Deterministic Ed25519 seed so signatures are reproducible across runs.
#: A test fixture, not a credential — it signs nothing outside the suite.
TEST_ONLY_SIGNING_SEED = base64.b64encode(bytes(range(32))).decode("ascii")

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
        anchor_enabled=True,
        anchor_backend="local",
        anchor_append_on_ingest=True,
        anchor_auto=False,
        anchor_signing_key_seed=TEST_ONLY_SIGNING_SEED,
        anchor_signing_key_path="",
        anchor_receipt_dir=str(tmp_path / "receipts"),
        # Tests parse explicitly. A background worker racing the assertions
        # would make them flaky and hide the ordering being tested.
        parse_on_ingest=False,
        event_store="sql",
        search_backend="sql",
    )


@pytest.fixture(autouse=True)
def _isolate_root_cache():
    """The Merkle root cache is process-wide and keyed by (log_id, tree_size).

    That is sound in a deployment — for a given size an append-only log has
    exactly one root, forever. It is *not* sound across tests, which reuse the
    same log ids against fresh databases, so it is cleared between them.
    """
    reset_root_cache()
    yield
    reset_root_cache()


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def object_store(app) -> InMemoryObjectStore:
    return app.state.trace.object_store


@pytest.fixture
async def database(app):
    """Metadata database with the schema applied, without starting the API.

    Tests that exercise a service or backend directly need the tables but not
    the whole HTTP stack.
    """
    await app.state.trace.database.create_all()
    try:
        yield app.state.trace.database
    finally:
        await app.state.trace.database.dispose()


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
