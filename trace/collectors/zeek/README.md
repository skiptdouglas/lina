# Zeek collector

Collects: conn, dns, http, ssl and files logs in JSON.
Evidence `source_type`: `ZEEK`.

The collector contract is in [../README.md](../README.md): preserve the
original artifact, describe how it was acquired, use a `SERVICE`-role token,
and declare collection gaps rather than hiding them.

Parsing for this source lands in Sprint 2
(docs/ROADMAP.md#sprint-2). Until then artifacts collected here are stored,
hashed and verifiable — `parse_status` stays `QUEUED` and TRACE does not
claim to have read them.

```bash
curl -H "Authorization: Bearer $TRACE_TOKEN" \
     -F "file=@/path/to/artifact" \
     -F "case_id=CASE-DEMO-001" \
     -F "source=$(hostname)" \
     -F "source_type=ZEEK" \
     -F "collector=zeek-collector/1.0" \
     -F "acquisition_method=LOG_EXPORT" \
     https://trace.example/api/v1/evidence
```
