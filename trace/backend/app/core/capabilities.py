"""Capability registry — the machine-readable answer to "what does TRACE do yet?".

Both ``GET /api/v1/capabilities`` and every 501 stub read from this table, so
the API, the UI and the roadmap cannot drift apart (ADR-0004).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.errors import FeatureNotImplemented

Status = Literal["IMPLEMENTED", "NOT_IMPLEMENTED"]


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    title: str
    status: Status
    sprint: int
    endpoints: tuple[str, ...] = ()
    detail: str = ""


CAPABILITIES: tuple[Capability, ...] = (
    # ---- Sprint 1 (implemented) -------------------------------------------
    Capability("cases.manage", "Case management", "IMPLEMENTED", 1,
               ("POST /api/v1/cases", "GET /api/v1/cases", "GET /api/v1/cases/{id}",
                "PATCH /api/v1/cases/{id}")),
    Capability("evidence.ingest", "Evidence ingestion with SHA-256", "IMPLEMENTED", 1,
               ("POST /api/v1/evidence",)),
    Capability("evidence.verify", "Evidence integrity verification", "IMPLEMENTED", 1,
               ("GET /api/v1/evidence/{id}/verify",)),
    Capability("evidence.download", "Raw evidence retrieval", "IMPLEMENTED", 1,
               ("GET /api/v1/evidence/{id}/download",)),
    Capability("audit.chain", "Hash-chained chain of custody", "IMPLEMENTED", 1,
               ("GET /api/v1/audit", "GET /api/v1/audit/verify-chain")),
    # ---- Sprint 1.5 — evidence anchoring (docs/ANCHORING.md) --------------
    Capability("anchoring.log", "Merkle transparency log", "IMPLEMENTED", 1,
               ("GET /api/v1/anchoring/log", "GET /api/v1/anchoring/log/entries",
                "GET /api/v1/anchoring/consistency"),
               "RFC 6962 append-only log; one leaf per evidence manifest."),
    Capability("anchoring.anchor", "Signed tree heads published to a ledger",
               "IMPLEMENTED", 1,
               ("POST /api/v1/anchors", "GET /api/v1/anchors",
                "GET /api/v1/anchors/{id}/verify"),
               "Ed25519-signed roots anchored to a local ledger, OpenTimestamps, "
               "an EVM chain, or an exported receipt."),
    Capability("anchoring.proof", "Offline-verifiable proof bundles", "IMPLEMENTED", 1,
               ("GET /api/v1/evidence/{id}/proof",
                "POST /api/v1/anchoring/verify-bundle"),
               "Self-contained bundles verifiable with scripts/verify_anchor.py, "
               "without access to TRACE."),
    # ---- Sprint 2 (implemented) --------------------------------------------
    Capability("ingestion.parse", "Parse stored evidence", "IMPLEMENTED", 2,
               ("POST /api/v1/ingestion/parse/{evidence_id}",
                "GET /api/v1/ingestion/parsers"),
               "Reads a fresh copy from object storage; re-parsing replaces "
               "rather than duplicates an artifact's events."),
    Capability("normalization.parsers", "Sysmon/Windows/Linux/Zeek/Suricata parsers",
               "IMPLEMENTED", 2, (),
               "Sysmon events 1, 3, 7, 10, 11, 13, 22; Windows Security; Zeek "
               "conn/dns/http/ssl/files; Suricata EVE; generic Linux JSON."),
    Capability("normalization.provenance", "Byte-accurate record locators",
               "IMPLEMENTED", 2, ("GET /api/v1/evidence/{id}/record",),
               "Every event addresses the exact bytes it came from."),
    Capability("search.query", "Event search", "IMPLEMENTED", 2,
               ("POST /api/v1/search", "GET /api/v1/events/{event_id}"),
               "Served from the event store by default; OpenSearch adds fuzzy "
               "matching and relevance ranking when configured."),
    Capability("timeline.case", "Case timeline", "IMPLEMENTED", 2,
               ("GET /api/v1/cases/{case_id}/timeline",),
               "Clock-corrected ordering with the original timestamps preserved."),
    # ---- Sprint 3 ----------------------------------------------------------
    Capability("entities.registry", "Canonical entities", "NOT_IMPLEMENTED", 3,
               ("GET /api/v1/entities", "GET /api/v1/entities/{id}")),
    Capability("entities.identity_resolution", "Identity resolution", "NOT_IMPLEMENTED", 3),
    Capability("graph.neighbourhood", "Graph exploration", "NOT_IMPLEMENTED", 3,
               ("GET /api/v1/graph/neighbourhood",)),
    # ---- Sprint 4 ----------------------------------------------------------
    Capability("detections.sigma", "Sigma detections", "NOT_IMPLEMENTED", 4,
               ("POST /api/v1/detections/sigma/run",)),
    Capability("detections.yara", "YARA/YARA-X scanning", "NOT_IMPLEMENTED", 4,
               ("POST /api/v1/detections/yara/scan",)),
    Capability("detections.mitre", "MITRE ATT&CK mapping", "NOT_IMPLEMENTED", 4,
               ("GET /api/v1/detections/mitre/coverage",)),
    Capability("hunt.rare", "Rare event detection", "NOT_IMPLEMENTED", 4,
               ("GET /api/v1/hunt/rare",)),
    Capability("hunt.first_seen", "First-seen detection", "NOT_IMPLEMENTED", 4,
               ("GET /api/v1/hunt/first-seen",)),
    Capability("correlation.basic", "Cross-source correlation", "NOT_IMPLEMENTED", 4),
    # ---- Sprint 5 ----------------------------------------------------------
    Capability("patterns.find_similar", "Pattern Hunter similarity search",
               "NOT_IMPLEMENTED", 5, ("POST /api/v1/patterns/find-similar",)),
    Capability("patterns.sequences", "Sequence detection", "NOT_IMPLEMENTED", 5,
               ("POST /api/v1/patterns/sequences/run",)),
    Capability("baselines.behaviour", "Behaviour baselines", "NOT_IMPLEMENTED", 5,
               ("GET /api/v1/baselines/{subject_type}/{subject_id}",)),
    Capability("anomalies.statistical", "Explainable anomaly detection",
               "NOT_IMPLEMENTED", 5, ("GET /api/v1/anomalies",)),
    Capability("anomalies.beacons", "Beacon detection", "NOT_IMPLEMENTED", 5,
               ("GET /api/v1/anomalies/beacons",)),
    Capability("anomalies.exfiltration", "Exfiltration detection", "NOT_IMPLEMENTED", 5,
               ("GET /api/v1/anomalies/exfiltration",)),
    # ---- Sprint 6 ----------------------------------------------------------
    Capability("ai.investigate", "AI investigator", "NOT_IMPLEMENTED", 6,
               ("POST /api/v1/ai/investigate",),
               "No LLM provider is wired up; TRACE will not return an unsourced answer."),
    Capability("ai.privacy_gateway", "AI privacy gateway", "NOT_IMPLEMENTED", 6),
    # ---- Sprint 7 ----------------------------------------------------------
    Capability("reports.generate", "Evidence-backed reports", "NOT_IMPLEMENTED", 7,
               ("POST /api/v1/reports/generate",)),
    Capability("threatintel.enrich", "Threat intelligence enrichment",
               "NOT_IMPLEMENTED", 7, ("GET /api/v1/threatintel/enrich",)),
    Capability("privacy.pseudonymise", "Anonymous investigation mode",
               "NOT_IMPLEMENTED", 7),
    Capability("privacy.reveal", "Identity reveal", "NOT_IMPLEMENTED", 7,
               ("POST /api/v1/entities/{id}/reveal",)),
    Capability("gaps.detect", "Evidence gap detection", "NOT_IMPLEMENTED", 7,
               ("GET /api/v1/cases/{id}/evidence-gaps",)),
    Capability("contradictions.detect", "Contradiction detection", "NOT_IMPLEMENTED", 7,
               ("GET /api/v1/cases/{id}/contradictions",)),
    Capability("replay.investigation", "Investigation replay", "NOT_IMPLEMENTED", 7),
)

CAPABILITY_INDEX: dict[str, Capability] = {c.key: c for c in CAPABILITIES}


def not_implemented(key: str) -> FeatureNotImplemented:
    """Build the 501 error for a registered capability.

    Raising for an unregistered key is a programming error — every stub must
    appear in ``GET /api/v1/capabilities``.
    """
    capability = CAPABILITY_INDEX.get(key)
    if capability is None:  # pragma: no cover - guarded by tests
        raise KeyError(f"Unknown capability key: {key}")
    if capability.status == "IMPLEMENTED":  # pragma: no cover - guarded by tests
        raise KeyError(f"Capability {key} is marked IMPLEMENTED; it must not raise 501")
    return FeatureNotImplemented(
        capability.key,
        planned_sprint=capability.sprint,
        detail=capability.detail or f"{capability.title} is not implemented yet.",
    )
