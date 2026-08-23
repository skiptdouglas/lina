"""RFC 6962 Merkle tree — the cryptographic core of evidence anchoring.

Why RFC 6962 (Certificate Transparency) rather than a hand-rolled tree:

* **Domain separation.** Leaves are hashed ``SHA-256(0x00 || data)`` and
  internal nodes ``SHA-256(0x01 || left || right)``. Without the prefixes an
  attacker can present an internal node as if it were a leaf — a second
  preimage attack on the tree structure.
* **No duplicated odd node.** Bitcoin's Merkle construction duplicates the
  last node when a level has an odd count, which makes distinct leaf sets
  collide on the same root (CVE-2012-2459). RFC 6962 splits at the largest
  power of two below ``n`` instead, so every leaf set has exactly one root.
* **Consistency proofs.** The log can prove it only ever *appended* — that
  the tree of size ``m`` is a prefix of the tree of size ``n``. An anchored
  root without this proves a snapshot; with it, the whole history is provably
  append-only.

Definitions (RFC 6962 §2.1)::

    MTH({})     = SHA-256()
    MTH({d0})   = SHA-256(0x00 || d0)
    MTH(D[n])   = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n]))
                  where k is the largest power of two strictly less than n

The recursive functions below are direct transcriptions of the RFC; the
iterative verifiers are the standard CT client algorithms. They are
independent implementations, and the test-suite cross-checks them against each
other exhaustively for every leaf and every tree size up to 33.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"
HASH_ALGORITHM = "sha256"
HASH_SIZE = 32

#: MTH of the empty tree: SHA-256 of the empty string.
EMPTY_ROOT = hashlib.sha256(b"").digest()


def leaf_hash(data: bytes) -> bytes:
    """``SHA-256(0x00 || data)`` — the hash of a single log entry."""
    return hashlib.sha256(LEAF_PREFIX + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    """``SHA-256(0x01 || left || right)`` — the hash of an internal node."""
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def largest_power_of_two_below(n: int) -> int:
    """The ``k`` used by the RFC's split rule: largest power of two ``< n``.

    Defined for ``n > 1``. ``k`` is strictly less than ``n`` and at least 1,
    which is what makes the recursion terminate and the tree canonical.
    """
    if n < 2:
        raise ValueError("k is only defined for n > 1")
    return 1 << (n - 1).bit_length() - 1


def merkle_tree_hash(leaves: Sequence[bytes]) -> bytes:
    """``MTH(D[n])`` over already-hashed leaves.

    ``leaves`` are leaf *hashes* (the output of :func:`leaf_hash`), not raw
    entry data.
    """
    n = len(leaves)
    if n == 0:
        return EMPTY_ROOT
    if n == 1:
        return leaves[0]
    k = largest_power_of_two_below(n)
    return node_hash(merkle_tree_hash(leaves[:k]), merkle_tree_hash(leaves[k:]))


def inclusion_proof(index: int, leaves: Sequence[bytes]) -> list[bytes]:
    """``PATH(m, D[n])`` — the audit path proving ``leaves[index]`` is in the tree."""
    n = len(leaves)
    if not 0 <= index < n:
        raise IndexError(f"leaf index {index} out of range for tree size {n}")
    if n == 1:
        return []
    k = largest_power_of_two_below(n)
    if index < k:
        return [*inclusion_proof(index, leaves[:k]), merkle_tree_hash(leaves[k:])]
    return [*inclusion_proof(index - k, leaves[k:]), merkle_tree_hash(leaves[:k])]


def consistency_proof(first: int, leaves: Sequence[bytes]) -> list[bytes]:
    """``PROOF(m, D[n])`` — proof that the size-``first`` tree is a prefix of this one."""
    n = len(leaves)
    if not 0 <= first <= n:
        raise ValueError(f"first={first} is out of range for tree size {n}")
    if first == 0:
        # Every tree extends the empty tree; nothing to prove.
        return []
    return _subproof(first, leaves, True)


def _subproof(m: int, leaves: Sequence[bytes], b: bool) -> list[bytes]:
    n = len(leaves)
    if m == n:
        # The size-m tree *is* this tree; its root is only needed when it is
        # not already known to the verifier from the proof context.
        return [] if b else [merkle_tree_hash(leaves)]
    k = largest_power_of_two_below(n)
    if m <= k:
        return [*_subproof(m, leaves[:k], b), merkle_tree_hash(leaves[k:])]
    return [*_subproof(m - k, leaves[k:], False), merkle_tree_hash(leaves[:k])]


def verify_inclusion(
    leaf: bytes,
    index: int,
    tree_size: int,
    proof: Sequence[bytes],
    root: bytes,
) -> bool:
    """Verify an audit path without access to the log.

    This is the algorithm a third party runs: given a leaf hash, its position,
    the tree size, the audit path and a root they trust (because it was signed
    and anchored), it recomputes the root. No part of the log is needed.
    """
    if index < 0 or tree_size <= 0 or index >= tree_size:
        return False
    if len(root) != HASH_SIZE or len(leaf) != HASH_SIZE:
        return False
    if any(len(node) != HASH_SIZE for node in proof):
        return False

    fn, sn = index, tree_size - 1
    computed = leaf
    for sibling in proof:
        if sn == 0:
            # More proof nodes than the tree size allows.
            return False
        if fn & 1 or fn == sn:
            computed = node_hash(sibling, computed)
            while fn != 0 and not fn & 1:
                fn >>= 1
                sn >>= 1
        else:
            computed = node_hash(computed, sibling)
        fn >>= 1
        sn >>= 1

    # sn must be exhausted: too few proof nodes is as much a failure as too many.
    return sn == 0 and _constant_time_eq(computed, root)


def verify_consistency(
    first: int,
    second: int,
    proof: Sequence[bytes],
    first_root: bytes,
    second_root: bytes,
) -> bool:
    """Verify that the size-``first`` tree is a prefix of the size-``second`` tree.

    This is what proves the log is append-only: an operator who rewrote or
    removed an entry cannot produce a passing consistency proof between the
    two roots, and both roots are independently anchored.
    """
    if first > second or first < 0:
        return False
    if any(len(node) != HASH_SIZE for node in proof):
        return False
    if first == second:
        return not proof and _constant_time_eq(first_root, second_root)
    if first == 0:
        # The empty tree is a prefix of every tree; the proof carries nothing.
        return not proof

    fn, sn = first - 1, second - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1

    nodes = list(proof)
    if not nodes:
        return False

    if fn != 0:
        # `first` is not a power of two: the proof supplies the seed node.
        seed = nodes[0]
        rest = nodes[1:]
    else:
        # `first` is a power of two: the seed is the old root itself.
        seed = first_root
        rest = nodes

    computed_first = seed
    computed_second = seed
    for sibling in rest:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            computed_first = node_hash(sibling, computed_first)
            computed_second = node_hash(sibling, computed_second)
            while fn != 0 and not fn & 1:
                fn >>= 1
                sn >>= 1
        else:
            computed_second = node_hash(computed_second, sibling)
        fn >>= 1
        sn >>= 1

    return (
        sn == 0
        and _constant_time_eq(computed_first, first_root)
        and _constant_time_eq(computed_second, second_root)
    )


def _constant_time_eq(a: bytes, b: bytes) -> bool:
    import hmac  # noqa: PLC0415 - stdlib, imported lazily to keep the module surface small

    return hmac.compare_digest(a, b)
