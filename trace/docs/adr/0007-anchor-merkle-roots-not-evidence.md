# ADR-0007 — Anchor Merkle roots, never evidence

**Status:** Accepted

## Context

The request was to "offload evidence to a blockchain", with a pipeline of
evidence → SHA-256 → manifest → Merkle tree → root → signed → immutable ledger.
The pipeline is right, and the distinction it draws is the important part:
what reaches the ledger is the **root**, not the evidence.

It is worth recording why the alternative is not a trade-off but a defect.

Publishing evidence, or even evidence metadata, to an immutable public ledger:

* **Publishes the investigation.** Case identifiers, hostnames, filenames and
  timestamps describe live investigative activity to anyone watching, forever.
* **Cannot be erased.** GDPR Article 17 and equivalent regimes require
  deletion on valid request. An immutable public record of personal data
  cannot comply. This is not a policy gap that can be papered over.
* **Does not scale.** Forensic cases run to terabytes; on-chain storage is
  priced per byte.
* **Buys nothing extra.** A hash commits to the content just as strongly.

## Decision

Only a 32-byte Merkle root, and the signed tree head describing it, are ever
sent to an anchor backend. The `AnchorBackend.submit` signature takes exactly
`(root_hash, sth)` — there is no parameter through which evidence content,
case identifiers or filenames could reach a ledger, and
`tests/unit/test_anchor_backends.py` asserts that signature.

Evidence bytes stay in object storage under the existing controls (ADR-0005).
Manifests stay in TRACE. One anchor covers every entry beneath it, so cost is
independent of case size.

## Consequences

* Anchoring is safe to point at a public chain, because there is nothing
  sensitive to publish.
* A right-to-erasure request can be honoured: delete the evidence and the
  manifest. The root remains, and it reveals nothing — it is a hash of hashes.
  The proof for that entry stops verifying, which is the correct outcome: the
  data is gone.
* Cost per anchor is constant regardless of how much evidence it covers, which
  is what makes periodic batching viable.
* The guarantee obtained is "this digest existed by time T", not "this evidence
  is authentic". ADR-0009 records how carefully that must be communicated.
