"""RFC 6962 Merkle tree.

The generator functions (recursive, transcribed from the RFC) and the verifier
functions (iterative, the standard CT client algorithms) are independent
implementations. These tests cross-check them exhaustively: every leaf of
every tree size, and every (first, second) pair. Agreement across all of those
is strong evidence that both match the specification.
"""

from __future__ import annotations

import hashlib

import pytest

from app.anchoring.merkle import (
    EMPTY_ROOT,
    consistency_proof,
    inclusion_proof,
    largest_power_of_two_below,
    leaf_hash,
    merkle_tree_hash,
    node_hash,
    verify_consistency,
    verify_inclusion,
)

MAX_N = 33


def leaves(n: int) -> list[bytes]:
    return [leaf_hash(f"entry-{i}".encode()) for i in range(n)]


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------
def test_empty_tree_is_sha256_of_empty_string() -> None:
    assert merkle_tree_hash([]) == EMPTY_ROOT == hashlib.sha256(b"").digest()


def test_single_leaf_tree_root_is_the_leaf() -> None:
    entries = leaves(1)
    assert merkle_tree_hash(entries) == entries[0]


def test_leaf_and_node_prefixes_are_domain_separated() -> None:
    """An internal node must never be presentable as a leaf (second preimage)."""
    data = b"payload"
    assert leaf_hash(data) == hashlib.sha256(b"\x00" + data).digest()
    left, right = leaves(2)
    assert node_hash(left, right) == hashlib.sha256(b"\x01" + left + right).digest()
    # A 64-byte "leaf" cannot collide with the node hash of its two halves.
    assert leaf_hash(left + right) != node_hash(left, right)


@pytest.mark.parametrize(
    ("n", "expected_k"),
    [(2, 1), (3, 2), (4, 2), (5, 4), (6, 4), (7, 4), (8, 4), (9, 8), (16, 8), (17, 16)],
)
def test_split_point_is_largest_power_of_two_below_n(n: int, expected_k: int) -> None:
    assert largest_power_of_two_below(n) == expected_k


def test_odd_node_is_promoted_not_duplicated() -> None:
    """Guards against the Bitcoin Merkle flaw (CVE-2012-2459).

    Duplicating the final node when a level is odd makes distinct leaf sets
    share a root. RFC 6962 promotes instead, so the root is unique.
    """
    d = leaves(3)
    promoted = node_hash(node_hash(d[0], d[1]), d[2])
    duplicated = node_hash(node_hash(d[0], d[1]), node_hash(d[2], d[2]))
    assert merkle_tree_hash(d) == promoted
    assert merkle_tree_hash(d) != duplicated


def test_distinct_leaf_counts_give_distinct_roots() -> None:
    roots = {merkle_tree_hash(leaves(n)) for n in range(MAX_N)}
    assert len(roots) == MAX_N


def test_root_is_deterministic() -> None:
    assert merkle_tree_hash(leaves(17)) == merkle_tree_hash(leaves(17))


def test_root_changes_if_any_leaf_changes() -> None:
    entries = leaves(12)
    original = merkle_tree_hash(entries)
    for index in range(len(entries)):
        mutated = list(entries)
        mutated[index] = leaf_hash(b"tampered")
        assert merkle_tree_hash(mutated) != original


def test_root_changes_if_leaves_are_reordered() -> None:
    entries = leaves(8)
    swapped = list(entries)
    swapped[2], swapped[5] = swapped[5], swapped[2]
    assert merkle_tree_hash(swapped) != merkle_tree_hash(entries)


# --------------------------------------------------------------------------
# Inclusion proofs
# --------------------------------------------------------------------------
def test_every_leaf_of_every_tree_size_verifies() -> None:
    checked = 0
    for n in range(1, MAX_N):
        entries = leaves(n)
        root = merkle_tree_hash(entries)
        for index in range(n):
            proof = inclusion_proof(index, entries)
            assert verify_inclusion(entries[index], index, n, proof, root), (
                f"leaf {index} of tree size {n} failed"
            )
            checked += 1
    assert checked == sum(range(1, MAX_N))


def test_inclusion_proof_length_is_logarithmic() -> None:
    for n in (1, 2, 4, 8, 16, 32):
        entries = leaves(n)
        assert len(inclusion_proof(0, entries)) == max(0, n.bit_length() - 1)


def test_inclusion_fails_for_the_wrong_leaf() -> None:
    entries = leaves(9)
    root = merkle_tree_hash(entries)
    proof = inclusion_proof(4, entries)
    assert not verify_inclusion(leaf_hash(b"not-in-the-log"), 4, 9, proof, root)


def test_inclusion_fails_for_the_wrong_index() -> None:
    entries = leaves(9)
    root = merkle_tree_hash(entries)
    proof = inclusion_proof(4, entries)
    for wrong in range(9):
        if wrong != 4:
            assert not verify_inclusion(entries[4], wrong, 9, proof, root)


def test_inclusion_fails_against_a_different_root() -> None:
    entries = leaves(9)
    proof = inclusion_proof(4, entries)
    assert not verify_inclusion(entries[4], 4, 9, proof, merkle_tree_hash(leaves(10)))


def test_inclusion_fails_when_a_proof_node_is_altered() -> None:
    entries = leaves(11)
    root = merkle_tree_hash(entries)
    proof = inclusion_proof(6, entries)
    for position in range(len(proof)):
        tampered = list(proof)
        tampered[position] = hashlib.sha256(tampered[position]).digest()
        assert not verify_inclusion(entries[6], 6, 11, tampered, root)


def test_inclusion_fails_when_proof_nodes_are_added_or_removed() -> None:
    entries = leaves(11)
    root = merkle_tree_hash(entries)
    proof = inclusion_proof(6, entries)
    assert not verify_inclusion(entries[6], 6, 11, proof[:-1], root)
    assert not verify_inclusion(entries[6], 6, 11, [*proof, entries[0]], root)


def test_inclusion_fails_when_proof_order_is_swapped() -> None:
    entries = leaves(16)
    root = merkle_tree_hash(entries)
    proof = inclusion_proof(5, entries)
    reordered = [proof[1], proof[0], *proof[2:]]
    assert not verify_inclusion(entries[5], 5, 16, reordered, root)


def test_inclusion_rejects_malformed_inputs() -> None:
    entries = leaves(4)
    root = merkle_tree_hash(entries)
    proof = inclusion_proof(1, entries)
    assert not verify_inclusion(entries[1], -1, 4, proof, root)
    assert not verify_inclusion(entries[1], 4, 4, proof, root)
    assert not verify_inclusion(entries[1], 1, 0, proof, root)
    assert not verify_inclusion(b"short", 1, 4, proof, root)
    assert not verify_inclusion(entries[1], 1, 4, [b"short"], root)
    assert not verify_inclusion(entries[1], 1, 4, proof, b"short")


def test_inclusion_proof_index_out_of_range_raises() -> None:
    with pytest.raises(IndexError):
        inclusion_proof(5, leaves(5))


# --------------------------------------------------------------------------
# Consistency proofs — the append-only guarantee
# --------------------------------------------------------------------------
def test_every_pair_of_tree_sizes_is_consistent() -> None:
    roots = {n: merkle_tree_hash(leaves(n)) for n in range(MAX_N)}
    checked = 0
    for second in range(1, MAX_N):
        entries = leaves(second)
        for first in range(second + 1):
            proof = consistency_proof(first, entries)
            assert verify_consistency(first, second, proof, roots[first], roots[second]), (
                f"consistency {first} -> {second} failed"
            )
            checked += 1
    assert checked > 500


def test_consistency_detects_a_rewritten_entry() -> None:
    """The scenario the whole design exists to defeat.

    The operator anchors a tree of 8 entries, then quietly rewrites entry 3
    and grows the log to 12. No consistency proof can bridge the anchored root
    and the rewritten log.
    """
    honest = leaves(8)
    anchored_root = merkle_tree_hash(honest)

    rewritten = leaves(12)
    rewritten[3] = leaf_hash(b"evidence quietly replaced")
    rewritten_root = merkle_tree_hash(rewritten)

    proof = consistency_proof(8, rewritten)
    assert not verify_consistency(8, 12, proof, anchored_root, rewritten_root)


def test_consistency_detects_a_deleted_entry() -> None:
    honest = leaves(9)
    anchored_root = merkle_tree_hash(honest)
    truncated = leaves(9)[:5] + leaves(9)[6:]
    proof = consistency_proof(8, truncated)
    assert not verify_consistency(8, 8, proof, anchored_root, merkle_tree_hash(truncated))


def test_consistency_rejects_shrinking_the_log() -> None:
    roots = {n: merkle_tree_hash(leaves(n)) for n in (4, 9)}
    proof = consistency_proof(4, leaves(9))
    assert not verify_consistency(9, 4, proof, roots[9], roots[4])


def test_consistency_of_identical_sizes_needs_an_empty_proof() -> None:
    root = merkle_tree_hash(leaves(6))
    assert verify_consistency(6, 6, [], root, root)
    assert not verify_consistency(6, 6, [root], root, root)
    assert not verify_consistency(6, 6, [], root, merkle_tree_hash(leaves(7)))


def test_every_tree_extends_the_empty_tree() -> None:
    for n in range(1, 12):
        assert consistency_proof(0, leaves(n)) == []
        assert verify_consistency(0, n, [], EMPTY_ROOT, merkle_tree_hash(leaves(n)))


def test_consistency_fails_when_a_proof_node_is_altered() -> None:
    entries = leaves(13)
    roots = (merkle_tree_hash(leaves(6)), merkle_tree_hash(entries))
    proof = consistency_proof(6, entries)
    assert verify_consistency(6, 13, proof, *roots)
    for position in range(len(proof)):
        tampered = list(proof)
        tampered[position] = hashlib.sha256(tampered[position]).digest()
        assert not verify_consistency(6, 13, tampered, *roots)


def test_consistency_fails_with_an_empty_proof_when_one_is_required() -> None:
    assert not verify_consistency(
        3, 9, [], merkle_tree_hash(leaves(3)), merkle_tree_hash(leaves(9))
    )


def test_consistency_proof_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="out of range"):
        consistency_proof(10, leaves(4))
