# TRACE — Evidence Anchoring

> **What goes on the ledger is a 32-byte Merkle root. Evidence never leaves
> TRACE.** That distinction is the whole design.

```
Evidence File
    ↓  SHA-256 (computed while streaming, at ingest)
Evidence Manifest            immutable facts only, canonically serialized
    ↓  SHA-256(0x00 || manifest)
Merkle Leaf
    ↓  RFC 6962 tree over every entry in the tenant's log
Merkle Root
    ↓  Ed25519, domain-separated
Signed Tree Head
    ↓
Immutable Ledger             local · OpenTimestamps (Bitcoin) · EVM · file receipt
```

---

## 1. What this actually proves

Being precise here matters more than anywhere else in TRACE, because this is
the part an opposing expert will attack.

**A verified anchor proves:**

| Claim | Because |
|---|---|
| This evidence digest existed **before** a specific time | The root committing to it was published at that time |
| The manifest has not changed since | Any change alters the leaf, which alters the root |
| The log was not reordered or rewritten below that root | Consistency proofs between anchored roots |
| The tree head was issued by the holder of a specific key | Ed25519 signature over the head |

**A verified anchor does NOT prove:**

* **That the evidence is authentic.** Anchoring a forgery anchors a forgery,
  provably and permanently. Anchoring says *when* something existed, never
  *whether it is true*.
* **Who collected the artifact.** The signature attests to custody of the log
  signing key. Attribution to a person comes from the chain-of-custody records
  (ADR-0006), not from the ledger.
* **Anything about entries added later.** A proof is against one tree size.
* **That evidence existed before it was ingested.** The clock starts at
  ingest. An artifact collected on Monday and ingested on Friday is anchored
  as Friday.

TRACE states these limits in the API response, in the proof bundle, in the UI
and in the offline verifier's output. A tool that overstates its guarantees is
worse than one that has none, because someone will rely on it.

---

## 2. Why a Merkle root and not the evidence

Putting evidence — or even evidence *metadata* — on a public ledger is a
serious mistake, and a surprisingly common one:

* **It is permanent and public.** Case identifiers, hostnames, filenames and
  timestamps published to a public chain describe an active investigation to
  anyone watching, forever.
* **It cannot be erased.** GDPR Article 17 and equivalent regimes conflict
  directly with an immutable public record of personal data. A blockchain
  cannot honour a deletion order.
* **It does not scale.** A forensic case is gigabytes to terabytes. On-chain
  storage is priced per byte for a reason.

A Merkle root is 32 bytes, reveals nothing (it is a hash of hashes), and is
enough to prove inclusion for every entry beneath it. One anchor covers a
million evidence objects at identical cost. See
[ADR-0007](adr/0007-anchor-merkle-roots-not-evidence.md).

---

## 3. The log

One append-only log per tenant per purpose:

| Log id | Contents |
|---|---|
| `<tenant>:evidence` | one leaf per evidence object, appended at ingest |
| `<tenant>:audit` | periodic checkpoints of the chain-of-custody head |

The audit log matters: the hash chain in ADR-0006 makes tampering detectable
*within* TRACE. Anchoring its head externally makes tampering detectable even
when whoever runs TRACE is the one doing it.

### Append-only is structural

The leaf is written **inside the same database transaction as the evidence
row**, so an evidence object cannot exist without its log entry. There is no
update and no delete path for a leaf anywhere in the application, and
`tests/unit/test_anchoring_api.py` asserts the API exposes no mutating verb on
the log.

### RFC 6962, not a hand-rolled tree

Two properties are non-negotiable and both are easy to get wrong:

* **Domain separation.** Leaves hash as `SHA-256(0x00 || data)`, internal
  nodes as `SHA-256(0x01 || left || right)`. Without the prefixes an internal
  node can be presented as a leaf — a second-preimage attack on the structure.
* **No duplicated odd node.** Bitcoin's tree duplicates the last node when a
  level is odd, which lets distinct leaf sets collide on one root
  (CVE-2012-2459). RFC 6962 splits at the largest power of two below `n`
  instead, so every leaf set has exactly one root.

The generator (recursive, transcribed from the RFC) and the verifier
(iterative, the standard CT client algorithm) are independent implementations,
cross-checked exhaustively for every leaf of every tree size up to 33 and
every consistency pair — around 1,100 cases. See
[ADR-0008](adr/0008-rfc6962-merkle-construction.md).

---

## 4. The manifest: immutable facts only

This is the decision that makes or breaks the feature.

An evidence row carries both immutable facts (its digest, its size, when it
was collected) and mutable state (legal hold, parse status, last verified).
Committing a mutable field would mean **flipping a legal hold silently
invalidates every proof issued before the flip**.

| Committed | Excluded (mutable by design) |
|---|---|
| `evidence_id`, `tenant_id`, `case_id` | `legal_hold` |
| `sha256`, `size` | `retention_policy` |
| `original_filename`, `original_path` | `parse_status`, `parse_detail` |
| `source`, `source_type` | `last_verified_at`, `last_verification_result` |
| `collector`, `acquisition_method` | `notes` |
| `collection_timestamp`, `original_timestamp` | `mime_type_source` |
| `storage_bucket`, `storage_key`, `mime_type`, `created_at` | |

`tests/unit/test_manifest.py` asserts **both halves**: changing any committed
field changes the entry hash; changing any excluded field does not.

Serialization is canonical — sorted keys, no insignificant whitespace, UTF-8,
RFC 3339 UTC timestamps, and **floats are refused outright** because their
textual representation is not stable enough to hash. The manifest carries a
`manifest_version` so a future format change cannot silently alter historical
hashes.

---

## 5. Signing

Ed25519, chosen deliberately: no curve or parameter choices to get wrong, no
nonce-reuse failure mode, small keys, and available in every serious KMS.

Every signed payload is prefixed with `TRACE-STH-v1\x00`. Without domain
separation, a signature over one structure could be replayed as another.

The signed payload covers `log_id`, `tree_size`, `root_hash`, `timestamp` and
the previous head. It deliberately does **not** cover `key_id` or the
signature itself — those describe the signature, not the statement.

### Key handling

```bash
python3 scripts/generate_signing_key.py --out deploy/keys/log-signing-key.pem
```

* Losing the key does **not** invalidate past anchors. Published roots stay
  verifiable against the public key embedded in every bundle; you simply
  cannot sign new heads until you generate a replacement.
* Leaking it lets someone sign tree heads in your name. Treat it like a
  code-signing key: mount read-only, keep it out of travelling backups.
* `TRACE_ANCHOR_ALLOW_KEY_GENERATION=true` is refused when `TRACE_ENV` is
  staging or prod — an ephemeral key makes every tree head unverifiable after
  a restart.
* A `KmsSigner` interface exists for deployments that need the key never to
  enter application memory. It raises rather than silently falling back.

**Publish the public key.** It is what lets anyone verify a TRACE bundle
without trusting TRACE. Put it in case reports and on a page you control.

---

## 6. Ledgers

| Backend | What an anchor there proves | Cost | Confirmation |
|---|---|---|---|
| `local` | Internal consistency only. Hash-chained and append-only, but TRACE operates it. **Self-attested.** | none | instant |
| `opentimestamps` | Existence before a Bitcoin block, independent of TRACE and of any company | none | hours |
| `evm` | Existence before a block, attributable to the sending address | gas | minutes |
| `file` | Nothing on its own — exports a signed receipt for an external notary or WORM store | none | manual |

Every anchor records its `independence` (`SELF_ATTESTED`, `THIRD_PARTY`,
`PUBLIC_BLOCKCHAIN`), and the API, the UI and the offline verifier all display
it. Nobody should mistake a local anchor for a blockchain one, so TRACE never
lets them.

**Why OpenTimestamps is the recommended external default:** no wallet, no gas,
no account. Calendar servers aggregate submissions into one periodic Bitcoin
transaction, so the marginal cost of anchoring is zero. The `.ots` binary
format is produced by the reference `opentimestamps` library, never
reimplemented — a subtly wrong hand-rolled writer would produce receipts that
look valid and verify nowhere.

**EVM privacy note:** the sending address is a permanent public identifier for
your deployment, and anchor cadence leaks activity volume. Calldata is
`TRAC` + the 32-byte root and nothing else, but the metadata around it is
still a signal. Prefer OpenTimestamps if that matters.

---

## 7. Batching

Appending a leaf is cheap and happens on every ingest. Publishing is slow and
sometimes costs money, so it batches: **one anchor covers every entry added
since the last one**.

```
TRACE_ANCHOR_AUTO=true
TRACE_ANCHOR_INTERVAL_SECONDS=3600
TRACE_ANCHOR_MIN_NEW_LEAVES=1
```

The window between ingest and anchor is the interval. Inside it, an entry is
in the log and signed, but not externally published — proof bundles say
`NOT_ANCHORED` explicitly rather than implying more. Shorten the interval if
your threat model needs a tighter bound; anchoring more often costs more only
on the paid backends.

---

## 8. Proof bundles and independent verification

A bundle contains everything needed to verify one evidence object **without
TRACE**: manifest, leaf index, audit path, signed tree head, public key and
anchor receipt. It contains **no evidence bytes** — sharing a bundle does not
share the evidence.

```bash
# From the UI: Case → evidence row → Show proof → Download bundle
curl -H "Authorization: Bearer $TRACE_TOKEN" \
  "$API/evidence/EVD-…/proof" > proof.json

python3 scripts/verify_anchor.py proof.json \
    --evidence-file sysmon.jsonl \
    --expect-key-id 56475aa75463474c0285df5dbf2bcab7
```

`scripts/verify_anchor.py` has **no dependencies** — Python 3.9+ standard
library only. It uses `cryptography` when present and otherwise falls back to
a pure-Python RFC 8032 Ed25519 verifier included in the file, so it runs on an
air-gapped laptop with nothing installed. `tests/integration/test_offline_verifier.py`
runs it as a real subprocess, including with `cryptography` deliberately
blocked.

### Pin the key

A bundle carries the public key that signed it, so a forger who re-signs a
doctored bundle with their own key passes the signature check. `--expect-key-id`
with a value obtained **out of band** is what turns "internally consistent"
into "authentic". The verifier says so loudly when the flag is absent.

---

## 9. Threat model

| Adversary | Attempt | Result |
|---|---|---|
| Analyst | Edit a manifest after ingest | Leaf hash changes → inclusion proof fails |
| Analyst | Swap the stored object | `sha256` no longer matches → `/verify` reports `MISMATCH`, and the anchored manifest still records the original digest |
| DB admin | Delete a log entry | Consistency proof against the anchored root fails; leaf indexes are non-contiguous |
| DB admin | Rewrite an entry and rebuild the tree | New root cannot be reconciled with the published one |
| TRACE operator | Rebuild the whole log and re-anchor | Defeats `local`; **cannot** defeat OpenTimestamps or EVM — the old root is already on a chain they do not control |
| TRACE operator | Forge a tree head | Requires the signing key; a KMS-backed signer puts it out of reach |
| Anyone | Backdate an anchor | Ledger timestamps are not TRACE's to choose |

The last row of what remains: **an operator who controls both TRACE and the
signing key, before anything is externally anchored, can produce a consistent
but false log.** That gap is exactly why external anchoring exists and why
`local` is labelled self-attested rather than dressed up as a blockchain.

---

## 10. Configuration

```bash
TRACE_ANCHOR_ENABLED=true
TRACE_ANCHOR_BACKEND=local              # local | opentimestamps | evm | file
TRACE_ANCHOR_APPEND_ON_INGEST=true
TRACE_ANCHOR_AUTO=false
TRACE_ANCHOR_INTERVAL_SECONDS=3600
TRACE_ANCHOR_MIN_NEW_LEAVES=1
TRACE_ANCHOR_SIGNING_KEY_PATH=/run/secrets/log-signing-key.pem
# or TRACE_ANCHOR_SIGNING_KEY_SEED=<base64 32 bytes>
TRACE_ANCHOR_ALLOW_KEY_GENERATION=false # refused in staging/prod
TRACE_ANCHOR_RECEIPT_DIR=./data/receipts
TRACE_ANCHOR_OTS_CALENDARS=             # empty = OpenTimestamps defaults
TRACE_ANCHOR_EVM_RPC_URL=
TRACE_ANCHOR_EVM_PRIVATE_KEY=
TRACE_ANCHOR_EVM_CHAIN_ID=
TRACE_ANCHOR_EVM_CONFIRMATIONS=3
```

If no signing key can be resolved, anchoring is **disabled loudly** and the
endpoints say so. It never falls back to something weaker.

---

## 11. API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/anchoring/log` | Size, current root, last anchor, public key |
| `GET /api/v1/anchoring/log/entries` | Recent leaves |
| `GET /api/v1/anchoring/backends` | Which ledgers are usable, and how independent |
| `GET /api/v1/anchoring/consistency?first=&second=` | Append-only proof between two sizes |
| `POST /api/v1/anchors` | Sign the current head and publish it |
| `GET /api/v1/anchors` · `/{id}` | List / detail |
| `POST /api/v1/anchors/{id}/refresh` | Has a submitted anchor confirmed yet? |
| `GET /api/v1/anchors/{id}/verify` | Recompute root, re-check signature, re-check ledger |
| `GET /api/v1/anchors/{id}/receipt` | Raw backend receipt (e.g. `.ots`) |
| `GET /api/v1/evidence/{id}/proof` | Offline-verifiable proof bundle |
| `POST /api/v1/anchoring/verify-bundle` | Re-check a bundle (convenience only) |

Permissions: `anchor:read` for everything read-only; `anchor:create` to
publish, because on some backends that spends money. Auditors get `anchor:read`
and not `anchor:create` — checking the custody record is their job, paying gas
is not.

---

## 12. Known limits

Stated plainly rather than implied to be solved:

| Limit | Consequence | Planned |
|---|---|---|
| Roots are recomputed from leaves, `O(n)` | Fine to millions; slow beyond | Persisted internal-node cache |
| Append ordering uses an in-process lock | Correct for one API replica | Database sequence / dedicated sequencer |
| Bitcoin attestation height is read, not chain-validated | TRACE reports the height and says a node is needed | Optional Bitcoin header verification |
| No key rotation workflow | A new key cannot re-sign old heads (by design), but there is no UI for the transition | Sprint 7 with OIDC |
| Anchoring proves existence at *ingest*, not at collection | Collector-side signing would tighten it | Signed collector receipts |
| `local` is self-attested | Not independent evidence | Use OpenTimestamps or EVM in production |
