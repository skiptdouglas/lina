"""Case CRUD, identifier allocation and tenant isolation."""

from __future__ import annotations

from tests.conftest import (
    ADMIN_TOKEN,
    OTHER_TENANT_TOKEN,
    VIEWER_TOKEN,
    auth,
)


async def test_create_and_fetch_case(client) -> None:
    response = await client.post(
        "/api/v1/cases",
        json={"title": "Beaconing on a finance host", "severity": "CRITICAL"},
        headers=auth(),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["case_id"].startswith("CASE-")
    assert created["severity"] == "CRITICAL"
    assert created["status"] == "OPEN"
    assert created["investigator"] == "admin@trace.test"
    assert created["counts"]["evidence"] == 0
    # Entities/findings are not computed yet — null, never a misleading zero.
    assert created["counts"]["entities"] is None

    fetched = await client.get(f"/api/v1/cases/{created['case_id']}", headers=auth())
    assert fetched.status_code == 200
    assert fetched.json()["case_id"] == created["case_id"]


async def test_sequential_allocation(client) -> None:
    ids = []
    for index in range(3):
        response = await client.post(
            "/api/v1/cases", json={"title": f"Case {index}"}, headers=auth()
        )
        ids.append(response.json()["case_id"])
    assert ids == ["CASE-0001", "CASE-0002", "CASE-0003"]


async def test_explicit_case_id_is_honoured_and_unique(client) -> None:
    first = await client.post(
        "/api/v1/cases", json={"title": "Demo", "case_id": "CASE-DEMO-001"}, headers=auth()
    )
    assert first.status_code == 201
    assert first.json()["case_id"] == "CASE-DEMO-001"

    duplicate = await client.post(
        "/api/v1/cases", json={"title": "Demo again", "case_id": "CASE-DEMO-001"}, headers=auth()
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONFLICT"


async def test_invalid_case_id_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/cases", json={"title": "Bad", "case_id": "not-a-case"}, headers=auth()
    )
    assert response.status_code == 422


async def test_patch_updates_and_sets_closed_at(client, case) -> None:
    response = await client.patch(
        f"/api/v1/cases/{case['case_id']}",
        json={"status": "CLOSED", "severity": "LOW"},
        headers=auth(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CLOSED"
    assert body["closed_at"] is not None

    reopened = await client.patch(
        f"/api/v1/cases/{case['case_id']}", json={"status": "OPEN"}, headers=auth()
    )
    assert reopened.json()["closed_at"] is None


async def test_list_filters_by_status_and_title(client) -> None:
    await client.post("/api/v1/cases", json={"title": "Phishing wave"}, headers=auth())
    await client.post(
        "/api/v1/cases", json={"title": "Ransomware", "status": "CLOSED"}, headers=auth()
    )

    open_cases = await client.get("/api/v1/cases?status=OPEN", headers=auth())
    assert [c["title"] for c in open_cases.json()["items"]] == ["Phishing wave"]

    searched = await client.get("/api/v1/cases?q=ransom", headers=auth())
    assert searched.json()["total"] == 1


async def test_cases_are_isolated_between_tenants(client, case) -> None:
    """A cross-tenant read returns 404, not 403 — existence is not disclosed."""
    response = await client.get(
        f"/api/v1/cases/{case['case_id']}", headers=auth(OTHER_TENANT_TOKEN)
    )
    assert response.status_code == 404

    listed = await client.get("/api/v1/cases", headers=auth(OTHER_TENANT_TOKEN))
    assert listed.json()["total"] == 0


async def test_viewer_cannot_create_a_case(client) -> None:
    response = await client.post(
        "/api/v1/cases", json={"title": "Nope"}, headers=auth(VIEWER_TOKEN)
    )
    assert response.status_code == 403
    assert "case:create" in response.json()["detail"]


async def test_unknown_fields_are_rejected(client) -> None:
    response = await client.post(
        "/api/v1/cases",
        json={"title": "Strict", "unexpected": "field"},
        headers=auth(ADMIN_TOKEN),
    )
    assert response.status_code == 422
