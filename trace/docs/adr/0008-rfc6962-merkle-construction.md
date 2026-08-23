# ADR-0008 — RFC 6962 for the Merkle construction

**Status:** Accepted

## Context

A Merkle tree looks trivial and has two well-known ways to be subtly,
exploitably wrong.

**Missing domain separation.** If leaves and internal nodes are hashed
identically, a 64-byte "leaf" can be crafted whose hash equals the hash of an
internal node with two chosen children. An attacker can then present an
internal node as a leaf, or vice versa — a second-preimage attack on the tree
structure itself.

**Duplicating the odd node.** Bitcoin's construction duplicates the final node
when a level has an odd number of entries. This makes distinct leaf sets
produce identical roots (CVE-2012-2459), so an inclusion proof can be valid
for an entry that was never in the log.

Both are avoided by the Certificate Transparency construction, which is
specified, widely reviewed, and already implemented by many independent
clients — an advantage that matters when the goal is for someone else to
verify our output.

## Decision

Use RFC 6962:

```
MTH({})   = SHA-256()
MTH({d0}) = SHA-256(0x00 || d0)
MTH(D[n]) = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n]))
            k = largest power of two strictly less than n
```

Implement both inclusion proofs (§2.1.1) and **consistency proofs** (§2.1.2).
Consistency proofs are what make the log verifiably append-only: without them,
an anchored root proves a snapshot, but nothing links snapshots together.

The generators are recursive transcriptions of the RFC; the verifiers are the
standard iterative CT client algorithms. They are independent implementations
and the test-suite cross-checks them exhaustively — every leaf of every tree
size up to 33, and every `(first, second)` consistency pair, around 1,100
cases — plus explicit regression tests for both failure modes above.

## Consequences

* Proof bundles are checkable by any RFC 6962 implementation, not only ours.
* Consistency proofs let an auditor verify the entire history between two
  anchors, not just one entry.
* Roots are recomputed from stored leaves, which is `O(n)`. For a given tree
  size an append-only log has exactly one root forever, so results cache
  permanently; a log with hundreds of millions of entries wants a persisted
  internal-node cache, tracked in ROADMAP rather than pretended away.
