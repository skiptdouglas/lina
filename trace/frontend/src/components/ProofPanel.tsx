import { useState } from 'react'

import { api, ApiError } from '@/api/client'
import type { ProofBundle } from '@/api/types'

/**
 * The "SHOW EVIDENCE" chain for anchoring: file → digest → manifest → leaf →
 * root → signature → ledger, each step shown with the value it produced.
 *
 * The download hands the analyst a bundle that verifies without TRACE, which
 * is the point: a guarantee only checkable by the system under scrutiny is not
 * a guarantee.
 */
export function ProofPanel({ evidenceId, sha256 }: { evidenceId: string; sha256: string }) {
  const [bundle, setBundle] = useState<ProofBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)

  const load = async () => {
    setBusy(true)
    setError(null)
    try {
      setBundle(await api.evidenceProof(evidenceId))
      setOpen(true)
    } catch (caught) {
      setError((caught as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  const download = () => {
    if (!bundle) return
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${evidenceId}-proof.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  if (!open) {
    return (
      <>
        <button className="small" onClick={load} disabled={busy}>
          {busy ? 'Building proof…' : 'Show proof'}
        </button>
        {error ? (
          <div className="notice danger" style={{ marginTop: 8, marginBottom: 0 }}>
            {error}
          </div>
        ) : null}
      </>
    )
  }

  const anchor = (bundle?.anchor ?? {}) as Record<string, string>
  const anchored = anchor.status === 'CONFIRMED' || anchor.status === 'SUBMITTED'

  return (
    <div className="notice" style={{ marginTop: 10, marginBottom: 0 }}>
      <div className="row spread" style={{ marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Provenance chain</h3>
        <div className="row">
          <button className="small" onClick={download}>Download bundle</button>
          <button className="small" onClick={() => setOpen(false)}>Close</button>
        </div>
      </div>

      <ChainStep label="1 · Evidence file" value={`sha256:${sha256}`} />
      <ChainStep
        label="2 · Manifest (immutable facts only)"
        value={`entry hash ${bundle?.entry_hash ?? '—'}`}
      />
      <ChainStep
        label={`3 · Merkle leaf (entry ${bundle?.leaf.index ?? '—'})`}
        value={bundle?.leaf.leaf_hash ?? '—'}
      />
      <ChainStep
        label={`4 · Root of ${bundle?.tree.tree_size ?? '—'} entries (${bundle?.tree.inclusion_proof.length ?? 0} proof nodes)`}
        value={bundle?.tree.root_hash ?? '—'}
      />
      <ChainStep
        label={`5 · Signed by TRACE (${bundle?.signature.algorithm ?? 'ed25519'}, key ${bundle?.signature.key_id ?? '—'})`}
        value={bundle?.signature.value ?? '—'}
      />
      <div style={{ marginTop: 10 }}>
        <div className="muted" style={{ fontSize: 11 }}>6 · Published to a ledger</div>
        {anchored ? (
          <div style={{ marginTop: 4 }}>
            <span className={`pill ${anchor.status === 'CONFIRMED' ? 'verified' : 'queued'}`}>
              {anchor.status}
            </span>{' '}
            <span className="muted">
              {anchor.backend} · {anchor.independence}
              {anchor.external_ref ? ` · ${anchor.external_ref}` : ''}
            </span>
          </div>
        ) : (
          <div className="muted" style={{ marginTop: 4 }}>
            <span className="pill warn">Not anchored</span>{' '}
            {anchor.detail ?? 'This entry is in the log but no tree head covering it is published yet.'}
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
          Verify this independently — no TRACE required:
        </div>
        <code className="hash">
          python3 scripts/verify_anchor.py {evidenceId}-proof.json --evidence-file &lt;file&gt;
          {bundle ? ` --expect-key-id ${bundle.signature.key_id}` : ''}
        </code>
      </div>

      {bundle?.what_this_does_not_prove?.length ? (
        <details style={{ marginTop: 10 }}>
          <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>
            What this does not prove
          </summary>
          <ul className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
            {bundle.what_this_does_not_prove.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}

function ChainStep({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div className="muted" style={{ fontSize: 11 }}>{label}</div>
      <code className="hash">{value}</code>
    </div>
  )
}
