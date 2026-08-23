"""The transparency log: an append-only sequence of entries with Merkle proofs.

One log per tenant per purpose::

    <tenant>:evidence   one leaf per evidence object, appended at ingest
    <tenant>:audit      periodic checkpoints of the chain-of-custody head

**Append-only is enforced by absence.** There is no update and no delete path
for :class:`~app.anchoring.models.MerkleLeaf` anywhere in the application, and
``tests/unit/test_transparency_log.py`` asserts the API exposes none.

Roots are recomputed from the stored leaves. For a given ``tree_size`` a root
can never change (that is what append-only means), so the cache below is
permanently valid and never needs invalidating. Recomputation is ``O(n)``; a log with
hundreds of millions of leaves wants a persisted internal-node cache instead,
which is noted in docs/ROADMAP.md rather than pretended away here.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.anchoring.manifest import LogEntry
from app.anchoring.merkle import (
    EMPTY_ROOT,
    consistency_proof,
    inclusion_proof,
    merkle_tree_hash,
)
from app.anchoring.models import MerkleLeaf
from app.core.errors import NotFound, ValidationFailure
from app.core.timeutil import utcnow

#: Appends are serialized per log so leaf indexes stay dense and ordered.
#: Correct for a single API replica; a multi-replica deployment needs a
#: database sequence or a dedicated sequencer (docs/ROADMAP.md backlog).
_append_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

_ROOT_CACHE_LIMIT = 512
_root_cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()


def evidence_log_id(tenant_id: str) -> str:
    return f"{tenant_id}:evidence"


def audit_log_id(tenant_id: str) -> str:
    return f"{tenant_id}:audit"


def _cache_get(log_id: str, tree_size: int) -> bytes | None:
    key = (log_id, tree_size)
    value = _root_cache.get(key)
    if value is not None:
        _root_cache.move_to_end(key)
    return value


def _cache_put(log_id: str, tree_size: int, root: bytes) -> None:
    key = (log_id, tree_size)
    _root_cache[key] = root
    _root_cache.move_to_end(key)
    while len(_root_cache) > _ROOT_CACHE_LIMIT:
        _root_cache.popitem(last=False)


def reset_root_cache() -> None:
    """Test helper — the cache is process-wide and outlives a test database."""
    _root_cache.clear()


class TransparencyLog:
    def __init__(self, session: AsyncSession, log_id: str) -> None:
        self.session = session
        self.log_id = log_id

    # ---- writing -----------------------------------------------------------
    async def append(
        self,
        entry: LogEntry,
        *,
        tenant_id: str,
        evidence_id: str | None = None,
        case_id: str | None = None,
    ) -> MerkleLeaf:
        """Append an entry. Never overwrites, never reorders.

        Runs inside the caller's transaction so a leaf and the thing it
        describes commit or roll back together.
        """
        async with _append_locks[self.log_id]:
            next_index = await self.size()
            leaf = MerkleLeaf(
                log_id=self.log_id,
                leaf_index=next_index,
                tenant_id=tenant_id,
                entry_type=str(entry.entry_type),
                entry_hash=entry.entry_hash(),
                leaf_hash=entry.merkle_leaf().hex(),
                entry_json=entry.to_payload(),
                evidence_id=evidence_id,
                case_id=case_id,
                created_at=utcnow(),
            )
            self.session.add(leaf)
            await self.session.flush()
            return leaf

    # ---- reading -----------------------------------------------------------
    async def size(self) -> int:
        return (
            await self.session.execute(
                select(func.count()).select_from(MerkleLeaf).where(MerkleLeaf.log_id == self.log_id)
            )
        ).scalar_one()

    async def leaf_hashes(self, tree_size: int | None = None) -> list[bytes]:
        stmt = (
            select(MerkleLeaf.leaf_hash)
            .where(MerkleLeaf.log_id == self.log_id)
            .order_by(MerkleLeaf.leaf_index)
        )
        if tree_size is not None:
            stmt = stmt.limit(tree_size)
        rows = (await self.session.execute(stmt)).scalars().all()
        if tree_size is not None and len(rows) < tree_size:
            raise ValidationFailure(
                f"Log {self.log_id} holds {len(rows)} leaves; tree_size {tree_size} requested."
            )
        return [bytes.fromhex(value) for value in rows]

    async def root(self, tree_size: int | None = None) -> bytes:
        size = await self.size() if tree_size is None else tree_size
        if size == 0:
            return EMPTY_ROOT
        cached = _cache_get(self.log_id, size)
        if cached is not None:
            return cached
        root = merkle_tree_hash(await self.leaf_hashes(size))
        _cache_put(self.log_id, size, root)
        return root

    async def leaves(self, offset: int = 0, limit: int = 100) -> list[MerkleLeaf]:
        stmt = (
            select(MerkleLeaf)
            .where(MerkleLeaf.log_id == self.log_id)
            .order_by(MerkleLeaf.leaf_index.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def leaf_for_evidence(self, evidence_id: str) -> MerkleLeaf:
        stmt = select(MerkleLeaf).where(
            MerkleLeaf.log_id == self.log_id, MerkleLeaf.evidence_id == evidence_id
        )
        leaf = (await self.session.execute(stmt)).scalars().first()
        if leaf is None:
            raise NotFound(f"Evidence {evidence_id} has no entry in log {self.log_id}.")
        return leaf

    # ---- proofs ------------------------------------------------------------
    async def inclusion_proof(self, leaf_index: int, tree_size: int) -> list[str]:
        if leaf_index >= tree_size:
            raise ValidationFailure(
                f"Leaf index {leaf_index} is not inside a tree of size {tree_size}."
            )
        path = inclusion_proof(leaf_index, await self.leaf_hashes(tree_size))
        return [node.hex() for node in path]

    async def consistency_proof(self, first: int, second: int) -> list[str]:
        if first > second:
            raise ValidationFailure("first must not exceed second.")
        path = consistency_proof(first, await self.leaf_hashes(second))
        return [node.hex() for node in path]
