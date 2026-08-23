"""Composition of the v1 API surface."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    anchoring,
    audit,
    cases,
    detections,
    entities,
    evidence,
    health,
    ingestion,
    patterns,
    reports,
    search,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(cases.router)
api_router.include_router(evidence.router)
api_router.include_router(audit.router)
api_router.include_router(anchoring.router)
api_router.include_router(ingestion.router)
api_router.include_router(search.router)
api_router.include_router(entities.router)
api_router.include_router(detections.router)
api_router.include_router(patterns.router)
api_router.include_router(ai.router)
api_router.include_router(reports.router)
