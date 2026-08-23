import { useState } from 'react'

import { api, ApiError } from '@/api/client'
import { Pill } from '@/components/Pill'
import { useAsync } from '@/hooks/useAsync'
import type {
  Anchor,
  AnchorBackendStatus,
  AnchorVerification,
  ConsistencyProof,
  Independence,
  LogStatus,
  Paged,
} from '@/api/types'

const INDEPENDENCE_LABEL: Record<Independence, string> = {
  SELF_ATTESTED: 'Self-attested by TRACE',
  THIRD_PARTY: 'Third party',
  PUBLIC_BLOCKCHAIN: 'Public blockchain',
}

const INDEPENDENCE_TONE: Record<Independence, string> = {
  SELF_ATTESTED: 'warn',
  THIRD_PARTY: 'info',
  PUBLIC_BLOCKCHAIN: 'verified',
}

export function Anchoring() {
  const { data: status, reload: reloadStatus } = useAsync<LogStatus>(() => api.logStatus(), [])
  const { data: anchors, reload: reloadAnchors } = useAsync<Paged<Anchor>>(
    () => api.listAnchors(),
    [],
  )
  const { data: backends } = useAsync<{ items: AnchorBackendStatus[] }>(
    () => api.anchorBackends(),
    [],
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedBackend, setSelectedBackend] = useState<string>('')

  const refresh = () => {
    reloadStatus()
    reloadAnchors()
  }

  const anchorNow = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.createAnchor(selectedBackend ? { backend: selectedBackend } : {})
      refresh()
    } catch (caught) {
      setError((caught as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Evidence anchoring</h1>
          <p className="subtitle">
            Evidence → SHA-256 → manifest → Merkle leaf → root → signed by TRACE → immutable
            ledger. Only the 32-byte root is published; evidence never leaves storage.
          </p>
        </div>
      </div>

      {error ? <div className="notice danger">{error}</div> : null}

      <div className="stat-row" style={{ marginBottom: 20 }}>
        <div className="stat">
          <div className="label">Log entries</div>
          <div className="value">{status?.tree_size ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Anchored up to</div>
          <div className="value">{status?.last_anchored_size ?? 0}</div>
        </div>
        <div className="stat">
          <div className="label">Waiting to anchor</div>
          <div className="value" style={{ color: status?.unanchored_entries ? 'var(--warn)' : undefined }}>
            {status?.unanchored_entries ?? '—'}
          </div>
        </div>
        <div className="stat">
          <div className="label">Audit checkpoints</div>
          <div className="value">{status?.audit_log_size ?? '—'}</div>
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Current tree head</h2>
          <div className="row">
            <select
              value={selectedBackend}
              onChange={(event) => setSelectedBackend(event.target.value)}
              style={{ width: 190 }}
            >
              <option value="">Default ({status?.default_backend ?? '—'})</option>
              {(backends?.items ?? [])
                .filter((backend) => backend.available)
                .map((backend) => (
                  <option key={backend.name} value={backend.name}>
                    {backend.name}
                  </option>
                ))}
            </select>
            <button className="primary small" onClick={anchorNow} disabled={busy || !status?.tree_size}>
              {busy ? 'Anchoring…' : 'Anchor now'}
            </button>
          </div>
        </header>
        <div className="body">
          <div className="muted" style={{ fontSize: 11 }}>
            Merkle root of {status?.tree_size ?? 0} entr{status?.tree_size === 1 ? 'y' : 'ies'}
          </div>
          <code className="hash">{status?.root_hash ?? '—'}</code>
          <div className="grid-2" style={{ marginTop: 14 }}>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Signing key id</div>
              <code className="hash">{status?.signing_key_id ?? '—'}</code>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>
                Public key ({status?.signing_algorithm ?? 'ed25519'}) — publish this so others can verify
              </div>
              <code className="hash">{status?.public_key_b64 ?? '—'}</code>
            </div>
          </div>
        </div>
      </div>

      <ConsistencyCheck status={status} />

      <div className="card">
        <header>
          <h2>Ledgers</h2>
          <span className="muted">where roots can be published</span>
        </header>
        <div className="body flush">
          <table>
            <thead>
              <tr>
                <th>Backend</th>
                <th>Independence</th>
                <th>Available</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {(backends?.items ?? []).map((backend) => (
                <tr key={backend.name}>
                  <td className="mono">
                    {backend.name}
                    {backend.is_default ? <span className="pill info" style={{ marginLeft: 6 }}>default</span> : null}
                  </td>
                  <td>
                    <span className={`pill ${INDEPENDENCE_TONE[backend.independence]}`}>
                      {INDEPENDENCE_LABEL[backend.independence]}
                    </span>
                  </td>
                  <td>
                    <Pill
                      value={backend.available ? 'YES' : 'NO'}
                      tone={backend.available ? 'verified' : 'muted'}
                    />
                  </td>
                  <td className="muted" style={{ fontSize: 12 }}>{backend.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <AnchorTable anchors={anchors?.items ?? []} onChanged={refresh} />
    </>
  )
}

function ConsistencyCheck({ status }: { status: LogStatus | null }) {
  const [first, setFirst] = useState('')
  const [second, setSecond] = useState('')
  const [result, setResult] = useState<ConsistencyProof | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(
        await api.consistency(
          Number(first || status?.last_anchored_size || 0),
          Number(second || status?.tree_size || 0),
        ),
      )
    } catch (caught) {
      setError((caught as ApiError).message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <header>
        <h2>Append-only check</h2>
        <span className="muted">proves nothing was removed, reordered or rewritten</span>
      </header>
      <div className="body">
        <p className="muted" style={{ marginTop: 0 }}>
          A consistency proof shows the log at one size is a prefix of the log at a later size.
          An operator who edited an entry after anchoring it cannot produce one.
        </p>
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            type="number"
            min={0}
            placeholder={`from (${status?.last_anchored_size ?? 0})`}
            value={first}
            onChange={(event) => setFirst(event.target.value)}
            style={{ width: 150 }}
          />
          <input
            type="number"
            min={0}
            placeholder={`to (${status?.tree_size ?? 0})`}
            value={second}
            onChange={(event) => setSecond(event.target.value)}
            style={{ width: 150 }}
          />
          <button className="small" onClick={run} disabled={busy}>
            {busy ? 'Checking…' : 'Check consistency'}
          </button>
        </div>
        {error ? <div className="notice danger">{error}</div> : null}
        {result ? (
          <div className={`notice ${result.verified ? 'verified' : 'danger'}`} style={{ marginBottom: 0 }}>
            <h3>
              {result.verified ? 'Append-only confirmed' : 'CONSISTENCY FAILED'} — sizes {result.first} → {result.second}
            </h3>
            <p>{result.detail}</p>
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
              {result.proof.length} proof node(s)
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function AnchorTable({ anchors, onChanged }: { anchors: Anchor[]; onChanged: () => void }) {
  const [verifications, setVerifications] = useState<Record<string, AnchorVerification>>({})
  const [busy, setBusy] = useState<string | null>(null)

  const verify = async (anchorId: string) => {
    setBusy(anchorId)
    try {
      const result = await api.verifyAnchor(anchorId)
      setVerifications((current) => ({ ...current, [anchorId]: result }))
    } finally {
      setBusy(null)
    }
  }

  const refresh = async (anchorId: string) => {
    setBusy(anchorId)
    try {
      await api.refreshAnchor(anchorId)
      onChanged()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card">
      <header>
        <h2>Anchors</h2>
        <span className="muted">{anchors.length} published tree head(s)</span>
      </header>
      <div className="body flush">
        {anchors.length === 0 ? (
          <div className="empty">
            No anchors yet. Ingest evidence, then press <strong>Anchor now</strong>.
          </div>
        ) : null}
        {anchors.map((anchor) => {
          const verification = verifications[anchor.anchor_id]
          return (
            <div key={anchor.anchor_id} style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
              <div className="row spread">
                <div>
                  <strong className="mono">tree size {anchor.tree_size}</strong>{' '}
                  <span className="muted mono" style={{ fontSize: 11 }}>{anchor.anchor_id}</span>
                  <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                    {anchor.backend} · {new Date(anchor.created_at).toISOString().slice(0, 19).replace('T', ' ')}Z
                    {anchor.previous_tree_size !== null ? ` · extends size ${anchor.previous_tree_size}` : ' · first anchor'}
                  </div>
                </div>
                <div className="row">
                  <span className={`pill ${INDEPENDENCE_TONE[anchor.independence]}`}>
                    {INDEPENDENCE_LABEL[anchor.independence]}
                  </span>
                  <Pill value={anchor.status} tone={anchor.status === 'CONFIRMED' ? 'verified' : anchor.status === 'FAILED' ? 'mismatch' : 'queued'} />
                  {anchor.status === 'SUBMITTED' ? (
                    <button className="small" onClick={() => refresh(anchor.anchor_id)} disabled={busy === anchor.anchor_id}>
                      Check status
                    </button>
                  ) : null}
                  <button className="small" onClick={() => verify(anchor.anchor_id)} disabled={busy === anchor.anchor_id}>
                    {busy === anchor.anchor_id ? 'Verifying…' : 'Verify'}
                  </button>
                  <a className="btn small" href={api.receiptUrl(anchor.anchor_id)} target="_blank" rel="noreferrer">
                    Receipt
                  </a>
                </div>
              </div>

              <code className="hash" style={{ marginTop: 8 }}>root:{anchor.root_hash}</code>

              {anchor.external_ref ? (
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  Ledger reference: <code>{anchor.external_ref}</code>
                  {anchor.explorer_url ? (
                    <>
                      {' · '}
                      <a href={anchor.explorer_url} target="_blank" rel="noreferrer">view on explorer</a>
                    </>
                  ) : null}
                </div>
              ) : null}
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{anchor.detail}</div>

              {verification ? (
                <div className={`notice ${verification.verified ? 'verified' : 'danger'}`} style={{ marginTop: 10, marginBottom: 0 }}>
                  <h3>{verification.verified ? 'Anchor verified' : 'Anchor verification FAILED'}</h3>
                  <p>{verification.detail}</p>
                  <div className="row" style={{ marginTop: 8 }}>
                    <Pill value={verification.root_recomputed ? 'ROOT OK' : 'ROOT MISMATCH'} tone={verification.root_recomputed ? 'verified' : 'mismatch'} />
                    <Pill value={verification.signature_valid ? 'SIGNATURE OK' : 'SIGNATURE INVALID'} tone={verification.signature_valid ? 'verified' : 'mismatch'} />
                  </div>
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}
