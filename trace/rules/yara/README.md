# YARA rules

Scanned against stored evidence from Sprint 4
(`POST /api/v1/detections/yara/scan`, currently **501 NOT_IMPLEMENTED**).

Two constraints hold when the scanner lands:

* Scanning runs in an isolated, resource-limited, network-denied worker —
  never in the API process (docs/SECURITY.md §5).
* The scanner reads a fresh copy from object storage. It never consumes the
  only copy of an artifact (ADR-0005).

Either YARA or YARA-X may back the engine; the `DetectionEngine` interface in
`backend/app/detections/engine.py` does not depend on which.
