"""Evidence ingestion (brief §7, ADR-0005).

    Upload → generate evidence id → SHA-256 → write raw object to MinIO
          → verify the stored object → create metadata → audit → queue parsing

The upload stream is consumed exactly once, into a spooled temp file. Parsers
later read a *fresh copy* from object storage: TRACE never parses the only
copy of an artifact.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.anchoring.service import AnchoringService
from app.audit.actions import AuditAction
from app.audit.service import AuditService
from app.cases.service import CaseService
from app.core.config import Settings
from app.core.errors import EvidenceIntegrityError, StorageUnavailable
from app.core.ids import new_evidence_id
from app.core.security import Principal
from app.core.timeutil import utcnow
from app.evidence.enums import ParseStatus
from app.evidence.integrity import HASH_ALGORITHM, hash_stream, hashes_match, spool_stream
from app.evidence.models import Evidence
from app.evidence.schemas import EvidenceIngestMetadata
from app.ingestion.naming import safe_basename, storage_key
from app.ingestion.queue import IngestionQueue, ParseJob

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        store,  # noqa: ANN001 - app.evidence.storage.ObjectStore
        audit: AuditService,
        queue: IngestionQueue,
        settings: Settings,
        anchoring: AnchoringService | None = None,
    ) -> None:
        self.session = session
        self.store = store
        self.audit = audit
        self.queue = queue
        self.settings = settings
        self.anchoring = anchoring

    async def ingest(
        self,
        *,
        stream: AsyncIterator[bytes],
        filename: str | None,
        declared_content_type: str | None,
        metadata: EvidenceIngestMetadata,
        principal: Principal,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> Evidence:
        # The case must exist and belong to this tenant before anything is stored.
        case = await CaseService(self.session).get(metadata.case_id, principal)

        artifact = await spool_stream(
            stream, max_bytes=self.settings.evidence_max_upload_bytes
        )
        evidence_id = new_evidence_id()
        bucket = self.settings.evidence_bucket
        key = storage_key(principal.tenant_id, case.case_id, evidence_id, filename)
        display_name = safe_basename(filename)
        mime_type, mime_source = self._resolve_mime(declared_content_type, display_name)

        try:
            try:
                await self.store.ensure_bucket(bucket)
                await self.store.put_file(
                    bucket,
                    key,
                    artifact.path,
                    length=artifact.size,
                    content_type=mime_type,
                )
            except Exception as exc:  # noqa: BLE001 - mapped to a domain error
                logger.error("Evidence write failed for %s: %s", evidence_id, exc)
                raise StorageUnavailable(
                    "Evidence could not be written to object storage."
                ) from exc

            if self.settings.evidence_verify_on_ingest:
                await self._verify_round_trip(bucket, key, artifact.sha256, artifact.size)

            evidence = Evidence(
                evidence_id=evidence_id,
                tenant_id=principal.tenant_id,
                case_id=case.case_id,
                source=metadata.source,
                source_type=metadata.source_type,
                original_filename=display_name,
                original_path=metadata.original_path,
                collection_timestamp=metadata.collection_timestamp or utcnow(),
                original_timestamp=metadata.original_timestamp,
                collector=metadata.collector,
                acquisition_method=metadata.acquisition_method,
                size=artifact.size,
                sha256=artifact.sha256,
                mime_type=mime_type,
                mime_type_source=mime_source,
                storage_bucket=bucket,
                storage_key=key,
                retention_policy=metadata.retention_policy,
                legal_hold=metadata.legal_hold,
                parse_status=ParseStatus.PENDING,
                clock_offset_seconds=metadata.clock_offset_seconds,
                clock_offset_confidence=metadata.clock_offset_confidence,
                clock_offset_method=metadata.clock_offset_method,
                notes=metadata.notes,
                created_at=utcnow(),
            )
            self.session.add(evidence)
            await self.session.flush()

            # Commit the manifest to the transparency log inside this same
            # transaction: evidence must never exist without its log entry,
            # or the log stops being a complete record (docs/ANCHORING.md).
            leaf_index: int | None = None
            leaf_hash: str | None = None
            if self.anchoring is not None and self.settings.anchor_append_on_ingest:
                leaf = await self.anchoring.append_evidence(evidence)
                leaf_index = leaf.leaf_index
                leaf_hash = leaf.leaf_hash

            audit_common = {
                "principal": principal,
                "case_id": case.case_id,
                "evidence_id": evidence_id,
                "source_ip": source_ip,
                "user_agent": user_agent,
            }
            await self.audit.record(
                action=AuditAction.COLLECT,
                details={
                    "original_filename": display_name,
                    "source": metadata.source,
                    "source_type": str(metadata.source_type),
                    "collector": metadata.collector,
                    "acquisition_method": str(metadata.acquisition_method),
                    "size": artifact.size,
                    "algorithm": HASH_ALGORITHM,
                    "sha256": artifact.sha256,
                },
                **audit_common,
            )
            await self.audit.record(
                action=AuditAction.STORE,
                details={
                    "bucket": bucket,
                    "key": key,
                    "size": artifact.size,
                    "sha256": artifact.sha256,
                    "log_leaf_index": leaf_index,
                    "log_leaf_hash": leaf_hash,
                },
                **audit_common,
            )
            if self.settings.evidence_verify_on_ingest:
                await self.audit.record(
                    action=AuditAction.VERIFY,
                    details={
                        "result": "VERIFIED",
                        "stage": "round-trip-on-ingest",
                        "algorithm": HASH_ALGORITHM,
                        "expected_hash": artifact.sha256,
                        "actual_hash": artifact.sha256,
                    },
                    **audit_common,
                )

            evidence.parse_status = ParseStatus.QUEUED
            evidence.parse_detail = (
                "Queued for parsing. The artifact is stored and verifiable; no events "
                "have been produced from it yet."
            )
            await self.session.commit()
        except BaseException:
            # Never leave an object behind that no metadata row points at.
            await self._discard_object(bucket, key)
            await self.session.rollback()
            raise
        finally:
            artifact.cleanup()

        await self.audit.flush_mirror()
        await self.queue.enqueue(
            ParseJob(
                evidence_id=evidence.evidence_id,
                tenant_id=evidence.tenant_id,
                case_id=evidence.case_id,
                source_type=evidence.source_type,
            )
        )
        return evidence

    async def _verify_round_trip(
        self, bucket: str, key: str, expected_hash: str, expected_size: int
    ) -> None:
        actual_hash, actual_size = await hash_stream(
            self.store.stream(bucket, key, chunk_size=self.settings.evidence_read_chunk_bytes)
        )
        if not hashes_match(expected_hash, actual_hash) or actual_size != expected_size:
            raise EvidenceIntegrityError(
                "The stored object does not match the bytes received; the upload was rejected.",
                extra={
                    "expected_hash": expected_hash,
                    "actual_hash": actual_hash,
                    "size_expected": expected_size,
                    "size_actual": actual_size,
                },
            )

    async def _discard_object(self, bucket: str, key: str) -> None:
        try:
            await self.store.delete(bucket, key)
        except Exception as exc:  # noqa: BLE001 - best effort cleanup
            logger.warning("Could not remove orphaned object %s/%s: %s", bucket, key, exc)

    @staticmethod
    def _resolve_mime(declared: str | None, filename: str) -> tuple[str, str]:
        """Record what the client said *and* what the extension suggests.

        Content-based type detection (libmagic) is a Sprint 2 item; until then
        the source of the value is stored so an analyst knows how much to trust it.
        """
        guessed, _ = mimetypes.guess_type(filename)
        if declared and declared != "application/octet-stream":
            return declared[:128], "declared"
        if guessed:
            return guessed[:128], "extension"
        return "application/octet-stream", "default"
