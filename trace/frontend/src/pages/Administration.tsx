import { useState } from 'react'

import { api } from '@/api/client'
import { Pill } from '@/components/Pill'
import { useAsync } from '@/hooks/useAsync'
import type { Capabilities, ChainVerification, Readiness } from '@/api/types'

export function Administration() {
  const { data: readiness } = useAsync<Readiness>(() => api.readiness(), [])
  const { data: capabilities } = useAsync<Capabilities>(() => api.capabilities(), [])
  const [chain, setChain] = useState<ChainVerification | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const verifyChain = async () => {
    setBusy(true)
    setError(null)
    try {
      setChain(await api.verifyChain())
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Administration</h1>
          <p className="subtitle">Platform health, chain integrity and capability status.</p>
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Dependencies</h2>
          <Pill value={readiness?.status ?? null} tone={readiness?.status === 'READY' ? 'verified' : 'warn'} />
        </header>
        <div className="body flush">
          <table>
            <thead>
              <tr>
                <th>Dependency</th>
                <th>Status</th>
                <th>Backend</th>
                <th>Required</th>
              </tr>
            </thead>
            <tbody>
              {(readiness?.dependencies ?? []).map((dependency) => (
                <tr key={dependency.name}>
                  <td>{dependency.name}</td>
                  <td>
                    <Pill
                      value={dependency.status}
                      tone={dependency.status === 'UP' ? 'verified' : dependency.required ? 'mismatch' : 'warn'}
                    />
                  </td>
                  <td className="muted mono">{dependency.detail || '—'}</td>
                  <td className="muted">{dependency.required ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Chain of custody integrity</h2>
          <button className="small" onClick={verifyChain} disabled={busy}>
            {busy ? 'Recomputing…' : 'Verify chain'}
          </button>
        </header>
        <div className="body">
          <p className="muted" style={{ marginTop: 0 }}>
            Every audit record is hash-chained to its predecessor. Verification recomputes each
            link and reports the first divergence — an edited or deleted record cannot hide.
          </p>
          {error ? <div className="notice danger">{error}</div> : null}
          {chain ? (
            <div className={`notice ${chain.verified ? 'verified' : 'danger'}`} style={{ marginBottom: 0 }}>
              <h3>{chain.verified ? 'Chain verified' : 'Chain broken'}</h3>
              <p>{chain.detail}</p>
              {!chain.verified ? (
                <p style={{ marginTop: 6 }}>
                  First divergence at sequence {chain.first_broken_sequence ?? '—'}
                  {chain.missing_sequences.length > 0
                    ? ` · missing sequences: ${chain.missing_sequences.join(', ')}`
                    : ''}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Not implemented yet</h2>
          <span className="muted">{capabilities?.not_implemented.length ?? 0} capabilities</span>
        </header>
        <div className="body flush">
          <table>
            <thead>
              <tr>
                <th>Capability</th>
                <th>Sprint</th>
                <th>Endpoint</th>
              </tr>
            </thead>
            <tbody>
              {(capabilities?.not_implemented ?? []).map((capability) => (
                <tr key={capability.key}>
                  <td>
                    {capability.title}
                    <div className="muted" style={{ fontSize: 12 }}>
                      {capability.detail}
                    </div>
                  </td>
                  <td className="muted">{capability.sprint}</td>
                  <td className="mono muted" style={{ fontSize: 11 }}>
                    {capability.endpoints[0] ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
