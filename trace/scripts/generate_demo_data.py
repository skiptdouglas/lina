#!/usr/bin/env python3
"""Generate synthetic telemetry for CASE-DEMO-001.

Produces *raw* collector output — the same shapes a real Sysmon/Zeek/Suricata
export has — so the Sprint 1 evidence workflow can be exercised with realistic
artifacts, and so the Sprint 2 parsers have fixtures waiting for them.

Attack sequence modelled (brief §51):

    phishing email -> Word macro -> PowerShell -> payload download
    -> persistence -> credential access -> lateral movement
    -> file share access -> data staging -> external transfer

Everything here is fabricated test data. It is written to disk as evidence
files; it is never inserted directly into the analytics store, because
evidence enters TRACE only through the ingestion API.

    python scripts/generate_demo_data.py --out sample-data/case-demo-001
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
from datetime import UTC, datetime, timedelta

VICTIM_HOST = "FINANCE-LAPTOP-07"
VICTIM_USER = "EXAMPLE\\jsmith"
FILE_SERVER = "FS-CORP-02"
SERVICE_ACCOUNT = "EXAMPLE\\svc_backup"
ATTACKER_IP = "203.0.113.47"          # TEST-NET-3, safe for documentation
STAGING_IP = "198.51.100.22"          # TEST-NET-2
C2_DOMAIN = "cdn-update-service.example"
INTERNAL_SUBNET = "10.20.30."

START = datetime(2026, 8, 20, 8, 41, 0, tzinfo=UTC)


def _ts(offset_seconds: int) -> datetime:
    return START + timedelta(seconds=offset_seconds)


def _sysmon_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _guid(seed: str) -> str:
    digest = hashlib.sha1(seed.encode()).hexdigest()  # noqa: S324 - test fixture id only
    return f"{{{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}}}"


def sysmon_events() -> list[dict]:
    """Sysmon events 1, 3, 7, 10, 11, 13 and 22 across the intrusion."""
    winword = "C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE"
    powershell = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    events: list[dict] = []

    def base(event_id: int, offset: int, **fields) -> dict:
        return {
            "EventID": event_id,
            "UtcTime": _sysmon_time(_ts(offset)),
            "Computer": VICTIM_HOST,
            "User": VICTIM_USER,
            **fields,
        }

    # 08:44 — the user opens the attachment.
    events.append(
        base(1, 180, Image=winword, ProcessId=4820, ProcessGuid=_guid("winword"),
             CommandLine=f'"{winword}" /n "C:\\Users\\jsmith\\Downloads\\Invoice_8842.docm"',
             ParentImage="C:\\Windows\\explorer.exe", ParentProcessId=1204,
             Hashes="SHA256=1f2c9a4be0c9b7f31a2d5e6c8b0a4d7e9f1c3b5a7d9e1f3a5c7b9d1e3f5a7c9b",
             IntegrityLevel="Medium")
    )
    # 08:45 — macro spawns PowerShell.
    events.append(
        base(1, 240, Image=powershell, ProcessId=6612, ProcessGuid=_guid("ps1"),
             CommandLine=(
                 "powershell.exe -nop -w hidden -enc "
                 "SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQAIABOAGUAdAAuAFcAZQBiAEMAbABpAGUAbgB0"
             ),
             ParentImage=winword, ParentProcessId=4820, ParentProcessGuid=_guid("winword"),
             Hashes="SHA256=9b1c3d5e7f9a1b3c5d7e9f1a3b5c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c",
             IntegrityLevel="Medium")
    )
    # DNS lookup for the C2 domain.
    events.append(
        base(22, 245, Image=powershell, ProcessId=6612, QueryName=C2_DOMAIN,
             QueryStatus="0", QueryResults=f"type: 5 {ATTACKER_IP};")
    )
    # Outbound HTTPS to the payload host.
    events.append(
        base(3, 248, Image=powershell, ProcessId=6612, Protocol="tcp", Initiated="true",
             SourceIp=f"{INTERNAL_SUBNET}55", SourcePort=51344,
             DestinationIp=ATTACKER_IP, DestinationPort=443, DestinationHostname=C2_DOMAIN)
    )
    # Payload written to disk.
    events.append(
        base(11, 255, Image=powershell, ProcessId=6612,
             TargetFilename="C:\\Users\\jsmith\\AppData\\Roaming\\updater.exe",
             CreationUtcTime=_sysmon_time(_ts(255)))
    )
    # Persistence via Run key.
    events.append(
        base(13, 262, Image=powershell, ProcessId=6612, EventType="SetValue",
             TargetObject=(
                 "HKU\\S-1-5-21-1004336348-1177238915-682003330-1114\\Software\\Microsoft"
                 "\\Windows\\CurrentVersion\\Run\\WindowsUpdater"
             ),
             Details="C:\\Users\\jsmith\\AppData\\Roaming\\updater.exe")
    )
    # Credential access: LSASS handle request.
    events.append(
        base(10, 420, SourceImage=powershell, SourceProcessId=6612,
             TargetImage="C:\\Windows\\system32\\lsass.exe", TargetProcessId=760,
             GrantedAccess="0x1010", CallTrace="UNKNOWN(00007FFB1E0A1F30)")
    )
    # Credential-dumping DLL loaded.
    events.append(
        base(7, 425, Image=powershell, ProcessId=6612,
             ImageLoaded="C:\\Users\\jsmith\\AppData\\Local\\Temp\\dbghelp.dll",
             Signed="false", SignatureStatus="Unavailable",
             Hashes="SHA256=3c5e7a9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c3e5b7d9f1a3c5e7b9d1f3a5c")
    )
    # Lateral movement to the file server.
    events.append(
        base(1, 600, Image="C:\\Windows\\System32\\wbem\\WMIC.exe", ProcessId=7104,
             ProcessGuid=_guid("wmic"),
             CommandLine=f'wmic /node:{FILE_SERVER} process call create "cmd.exe /c whoami"',
             ParentImage=powershell, ParentProcessId=6612, ParentProcessGuid=_guid("ps1"),
             IntegrityLevel="High")
    )
    events.append(
        base(3, 610, Image="C:\\Windows\\System32\\wbem\\WMIC.exe", ProcessId=7104,
             Protocol="tcp", Initiated="true", SourceIp=f"{INTERNAL_SUBNET}55",
             SourcePort=52001, DestinationIp=f"{INTERNAL_SUBNET}12",
             DestinationPort=445, DestinationHostname=FILE_SERVER)
    )
    # Data staging: archive created.
    events.append(
        base(11, 1200, Image="C:\\Program Files\\7-Zip\\7z.exe", ProcessId=7422,
             TargetFilename="C:\\Users\\jsmith\\AppData\\Local\\Temp\\fin_q3.7z",
             CreationUtcTime=_sysmon_time(_ts(1200)))
    )
    # Exfiltration.
    events.append(
        base(3, 1560, Image="C:\\Users\\jsmith\\AppData\\Roaming\\updater.exe",
             ProcessId=7890, Protocol="tcp", Initiated="true",
             SourceIp=f"{INTERNAL_SUBNET}55", SourcePort=53127,
             DestinationIp=STAGING_IP, DestinationPort=443,
             DestinationHostname="storage.example")
    )
    return events


def zeek_conn_log() -> list[dict]:
    """Zeek conn.log in JSON form, including a beacon-shaped pattern."""
    records: list[dict] = []
    rng = random.Random(20260820)

    def conn(offset: int, dst: str, port: int, sent: int, received: int, duration: float) -> dict:
        moment = _ts(offset)
        return {
            "ts": moment.timestamp(),
            "uid": f"C{hashlib.md5(f'{offset}{dst}'.encode()).hexdigest()[:16]}",  # noqa: S324
            "id.orig_h": f"{INTERNAL_SUBNET}55",
            "id.orig_p": 40000 + (offset % 20000),
            "id.resp_h": dst,
            "id.resp_p": port,
            "proto": "tcp",
            "service": "ssl" if port == 443 else "smb",
            "duration": duration,
            "orig_bytes": sent,
            "resp_bytes": received,
            "conn_state": "SF",
        }

    records.append(conn(248, ATTACKER_IP, 443, 812, 486_112, 4.1))
    # ~60s beacon with jitter — the signal Sprint 5's beacon detector looks for.
    for beat in range(40):
        offset = 300 + beat * 60 + rng.randint(-4, 4)
        records.append(conn(offset, ATTACKER_IP, 443, rng.randint(280, 340),
                            rng.randint(180, 260), rng.uniform(0.4, 0.9)))
    records.append(conn(610, f"{INTERNAL_SUBNET}12", 445, 18_204, 4_902, 12.3))
    records.append(conn(1210, f"{INTERNAL_SUBNET}12", 445, 9_120, 4_120_998_400, 288.4))
    # The exfiltration itself: 38 GB out against a 620 MB median.
    records.append(conn(1560, STAGING_IP, 443, 40_802_189_312, 91_204, 1841.9))
    return sorted(records, key=lambda record: record["ts"])


def suricata_eve() -> list[dict]:
    """Suricata EVE JSON alerts."""
    def alert(offset: int, signature: str, sid: int, category: str, severity: int,
              dst: str, port: int) -> dict:
        return {
            "timestamp": _ts(offset).isoformat(),
            "event_type": "alert",
            "src_ip": f"{INTERNAL_SUBNET}55",
            "src_port": 51344,
            "dest_ip": dst,
            "dest_port": port,
            "proto": "TCP",
            "alert": {
                "action": "allowed",
                "signature": signature,
                "signature_id": sid,
                "category": category,
                "severity": severity,
            },
        }

    return [
        alert(246, "ET INFO Observed DNS Query to Suspicious Domain", 2027865,
              "Potentially Bad Traffic", 2, ATTACKER_IP, 53),
        alert(249, "ET MALWARE Suspected Downloader Activity Outbound", 2036612,
              "A Network Trojan was detected", 1, ATTACKER_IP, 443),
        alert(660, "ET POLICY SMB Executable Transfer Internal", 2018568,
              "Potential Corporate Privacy Violation", 2, f"{INTERNAL_SUBNET}12", 445),
        alert(1562, "ET POLICY Large Outbound Data Transfer", 2019401,
              "Potential Corporate Privacy Violation", 2, STAGING_IP, 443),
    ]


def windows_security_events() -> list[dict]:
    """Windows Security log: logons, including a service-account interactive logon."""
    def record(offset: int, event_id: int, **fields) -> dict:
        return {
            "EventID": event_id,
            "TimeCreated": _ts(offset).isoformat(),
            "Channel": "Security",
            "Computer": fields.pop("Computer", VICTIM_HOST),
            **fields,
        }

    return [
        record(0, 4624, TargetUserName="jsmith", TargetDomainName="EXAMPLE",
               LogonType=2, IpAddress=f"{INTERNAL_SUBNET}55", WorkstationName=VICTIM_HOST),
        record(430, 4648, SubjectUserName="jsmith", TargetUserName="svc_backup",
               TargetServerName=FILE_SERVER, ProcessName="powershell.exe"),
        # First interactive logon this service account has ever had — a Sprint 4
        # "first seen" finding once the analytics land.
        record(605, 4624, Computer=FILE_SERVER, TargetUserName="svc_backup",
               TargetDomainName="EXAMPLE", LogonType=10,
               IpAddress=f"{INTERNAL_SUBNET}55", WorkstationName=VICTIM_HOST,
               AuthenticationPackageName="Negotiate"),
        record(1190, 5140, Computer=FILE_SERVER, SubjectUserName="svc_backup",
               ShareName="\\\\*\\FINANCE", IpAddress=f"{INTERNAL_SUBNET}55",
               AccessMask="0x1"),
        # Log clearing — an evidence-gap signal for Sprint 7.
        record(1800, 1102, Computer=FILE_SERVER, SubjectUserName="svc_backup"),
    ]


DATASETS = {
    "sysmon-operational.jsonl": (sysmon_events, "SYSMON", VICTIM_HOST),
    "windows-security.jsonl": (windows_security_events, "WINDOWS_SECURITY", VICTIM_HOST),
    "zeek-conn.jsonl": (zeek_conn_log, "ZEEK", "zeek-sensor-01"),
    "suricata-eve.jsonl": (suricata_eve, "SURICATA", "suricata-sensor-01"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="sample-data/case-demo-001", help="Output directory")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = []
    for filename, (factory, source_type, source) in DATASETS.items():
        path = out / filename
        payload = "".join(json.dumps(record) + "\n" for record in factory())
        path.write_text(payload, encoding="utf-8")
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        manifest.append(
            {
                "file": filename,
                "source": source,
                "source_type": source_type,
                "size": len(payload.encode("utf-8")),
                "sha256": digest,
                "records": payload.count("\n"),
            }
        )
        print(f"{filename:32} {len(payload.encode()):>9} bytes  sha256:{digest[:16]}…")

    manifest_path = out / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            {
                "case_id": "CASE-DEMO-001",
                "generated_by": "scripts/generate_demo_data.py",
                "synthetic": True,
                "note": (
                    "Fabricated telemetry for demonstration and testing. "
                    "The SHA-256 values here are the digests TRACE must reproduce "
                    "on ingest and on verification."
                ),
                "files": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {len(manifest)} artifact(s) and MANIFEST.json to {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
