"""Parse queue.

Sprint 1 records the *intent* to parse (``parse_status = QUEUED``); the worker
that consumes the queue arrives in Sprint 2. Nothing here pretends an artifact
has been parsed.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParseJob:
    evidence_id: str
    tenant_id: str
    case_id: str
    source_type: str


class IngestionQueue(ABC):
    """Hand-off point between ingestion and the (Sprint 2) parser workers."""

    name: str

    @abstractmethod
    async def enqueue(self, job: ParseJob) -> None: ...

    @abstractmethod
    async def depth(self) -> int: ...


class InMemoryIngestionQueue(IngestionQueue):
    """Process-local queue.

    Durable brokering (Redis/NATS/Kafka) lands with the parser workers; until
    then a restart drops queued jobs, which is safe because the raw evidence
    is already stored and can be re-queued.
    """

    name = "memory"

    def __init__(self) -> None:
        self._jobs: deque[ParseJob] = deque()

    async def enqueue(self, job: ParseJob) -> None:
        self._jobs.append(job)
        logger.info("Queued parse job for %s (%s)", job.evidence_id, job.source_type)

    async def depth(self) -> int:
        return len(self._jobs)

    async def drain(self) -> list[ParseJob]:
        jobs = list(self._jobs)
        self._jobs.clear()
        return jobs
