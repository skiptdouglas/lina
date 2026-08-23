# Sysmon collector

## Events TRACE parses (Sprint 2)

| Event ID | Meaning | Why it matters |
|---|---|---|
| 1 | Process Create | Process tree, command lines, hashes |
| 3 | Network Connection | Process-to-destination attribution |
| 7 | Image Loaded | Side-loading, unsigned modules |
| 10 | Process Access | Credential access (LSASS handles) |
| 11 | File Create | Payload drops, staged archives |
| 13 | Registry Value Set | Persistence |
| 22 | DNS Query | C2 lookups, process-attributed DNS |

## Collection

Export the operational channel without filtering:

```powershell
wevtutil epl "Microsoft-Windows-Sysmon/Operational" C:\collect\sysmon.evtx
```

Then post it as evidence (a `SERVICE`-role token, no download permission):

```powershell
curl -H "Authorization: Bearer $env:TRACE_TOKEN" `
     -F "file=@C:\collect\sysmon.evtx" `
     -F "case_id=CASE-DEMO-001" `
     -F "source=$env:COMPUTERNAME" `
     -F "source_type=SYSMON" `
     -F "collector=wevtutil/1.0" `
     -F "acquisition_method=LOG_EXPORT" `
     -F "original_path=C:\Windows\System32\winevt\Logs\Microsoft-Windows-Sysmon%4Operational.evtx" `
     https://trace.example/api/v1/evidence
```

`sysmon-config.xml` is the configuration TRACE's parsers are written against.
Collecting *less* than this is supported; TRACE reports the resulting gaps
rather than inferring across them.
