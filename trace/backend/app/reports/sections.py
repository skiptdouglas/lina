"""Report structure (brief §42).

The section list is static metadata, so it is served today; generating the
content requires Sprints 2–6 and is gated behind ``reports.generate``.
"""

from __future__ import annotations

REPORT_SECTIONS: tuple[str, ...] = (
    "Executive Summary",
    "Scope",
    "Evidence",
    "Evidence Integrity",
    "Timeline",
    "Affected Entities",
    "Technical Findings",
    "Patterns",
    "Anomalies",
    "MITRE ATT&CK",
    "Indicators",
    "Threat Intelligence",
    "Evidence Gaps",
    "Contradictions",
    "Confidence",
    "Recommendations",
)
