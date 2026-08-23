# ADR-0009 — State exactly what an anchor proves, everywhere it appears

**Status:** Accepted

## Context

"Blockchain-verified evidence" is a phrase that does real damage. It invites
the reader to believe the evidence is *true*, when what was proven is that a
digest *existed by a certain time*. In a forensic context that gap is not
academic — it is the question an opposing expert will ask, and a tool that
encouraged the overstatement will have caused the problem.

The same applies to independence. An anchor in TRACE's own database and an
anchor in the Bitcoin blockchain are both "anchors" and are not remotely the
same guarantee. Presenting them identically would be misleading by omission.

## Decision

1. **Every anchor records its independence** — `SELF_ATTESTED`,
   `THIRD_PARTY`, or `PUBLIC_BLOCKCHAIN` — and it is surfaced in the API, the
   UI, the proof bundle and the offline verifier. The local ledger describes
   itself as self-attested in its own verification output.
2. **Every proof bundle carries `what_this_does_not_prove`**, and the offline
   verifier prints it on every run, including successful ones.
3. **An unanchored entry is never presented as anchored.** Bundles for entries
   not yet covered by a published head say `NOT_ANCHORED` and explain that the
   guarantee is self-attested until then.
4. **Key pinning is offered and its absence is called out.** A bundle carries
   the key that signed it, so a forger who re-signs with their own key passes
   the signature check. `--expect-key-id` closes that, and the verifier warns
   plainly when it is not used.
5. **The docs lead with the limits**, not with the capability.

## Consequences

* Marketing language about anchoring is a review defect, not a style
  preference.
* Users learn the real shape of the guarantee, which makes them harder to
  mislead — including by us.
* When a case turns on the anchor, what TRACE printed at the time already
  matches what an expert would say under cross-examination.
