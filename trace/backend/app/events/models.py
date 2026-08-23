"""Relational table for normalized events (used by :class:`SqlEventStore`).

Mirrors ``deploy/clickhouse/003_events.sql`` column for column, so the two
backends store the same shape and the shared contract tests mean something.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.timeutil import utcnow


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_tenant_case_time", "tenant_id", "case_id", "timestamp"),
        Index("ix_events_evidence", "tenant_id", "evidence_id"),
        Index("ix_events_type", "tenant_id", "event_type"),
        Index("ix_events_host", "tenant_id", "device_hostname"),
        Index("ix_events_user", "tenant_id", "user_name"),
        Index("ix_events_process", "tenant_id", "process_name"),
        Index("ix_events_dst_ip", "tenant_id", "dst_ip"),
        Index("ix_events_file_sha256", "tenant_id", "file_sha256"),
    )

    # Ports, PIDs and sizes are nullable: "absent" and "zero" are different
    # facts. PID 0 is a real process and an empty file has size 0 — conflating
    # them with "unknown" would be silent data loss.
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(String(72), nullable=False)

    #: Clock-corrected, used for ordering. Never overwrites the original.
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    original_timestamp: Mapped[datetime] = mapped_column(nullable=False)
    clock_offset: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    correction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="OTHER")
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    user_domain: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    user_sid: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    user_entity_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    device_hostname: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    device_ip: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    device_entity_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    src_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    src_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dst_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    dst_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dst_domain: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    process_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    process_guid: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    process_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    process_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    process_command_line: Mapped[str] = mapped_column(Text, nullable=False, default="")
    process_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    parent_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_guid: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    parent_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    file_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    network_protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    network_direction: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    network_bytes_in: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    network_bytes_out: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    #: Provenance — required. An event that cannot be walked back to the
    #: original bytes must never reach this table.
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_reference: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Everything not materialised as a column, so a round trip is lossless.
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
