/*
   Fixtures for the Sprint 4 YARA engine. These match the synthetic artifacts
   produced by scripts/generate_demo_data.py, not real malware.
*/

rule TRACE_Demo_Staged_Archive
{
    meta:
        description = "Archive staged in a user temp directory before exfiltration"
        author      = "TRACE"
        date        = "2026-08-23"
        attack      = "T1560.001"
        severity    = "medium"
        synthetic   = "true"

    strings:
        $seven_zip_magic = { 37 7A BC AF 27 1C }
        $temp_path       = "\\AppData\\Local\\Temp\\" ascii wide

    condition:
        $seven_zip_magic at 0 and $temp_path
}

rule TRACE_Demo_Encoded_PowerShell_Dropper
{
    meta:
        description = "Encoded PowerShell downloader pattern"
        author      = "TRACE"
        date        = "2026-08-23"
        attack      = "T1059.001"
        severity    = "high"
        synthetic   = "true"

    strings:
        $enc  = "-enc" ascii wide nocase
        $hide = "-w hidden" ascii wide nocase
        $net  = "Net.WebClient" ascii wide nocase

    condition:
        2 of them
}
