"""Storage key construction.

Client-supplied filenames never influence the object key beyond a sanitised
basename (docs/SECURITY.md §5).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_BASENAME = 200
FALLBACK_NAME = "artifact.bin"


def safe_basename(filename: str | None) -> str:
    """Reduce an arbitrary client filename to a safe basename.

    Handles Windows paths (``C:\\Users\\x\\evil.evtx``), POSIX paths, traversal
    sequences, control characters and unicode look-alikes.
    """
    if not filename:
        return FALLBACK_NAME
    candidate = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    candidate = candidate.replace("\\", "/")
    candidate = PurePosixPath(PureWindowsPath(candidate).name or candidate).name
    candidate = _SAFE.sub("_", candidate).strip("._")
    candidate = candidate[:MAX_BASENAME]
    return candidate or FALLBACK_NAME


def storage_key(tenant_id: str, case_id: str, evidence_id: str, filename: str | None) -> str:
    """``{tenant}/{case}/{evidence_id}/{safe_filename}`` — generated, never client-supplied."""
    return (
        f"{_segment(tenant_id)}/{_segment(case_id)}/"
        f"{_segment(evidence_id)}/{safe_basename(filename)}"
    )


def _segment(value: str) -> str:
    cleaned = _SAFE.sub("_", value).strip("._")
    return cleaned or "unknown"
