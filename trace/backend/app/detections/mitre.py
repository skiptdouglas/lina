"""MITRE ATT&CK mapping (brief §20)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MitreMapping:
    """e.g. ``T1059.001`` / PowerShell / Execution."""

    tactic: str
    technique: str
    subtechnique: str | None = None
    technique_name: str | None = None

    @property
    def technique_id(self) -> str:
        return f"{self.technique}.{self.subtechnique}" if self.subtechnique else self.technique
