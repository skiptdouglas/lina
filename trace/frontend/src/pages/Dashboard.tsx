import { Link } from 'react-router-dom'

import { api } from '@/api/client'
import { useAsync } from '@/hooks/useAsync'
import { Pill } from '@/components/Pill'
import type { Capabilities, Case, Paged } from '@/api/types'

export function Dashboard() {
  const { data: cases } = useAsync<Paged<Case>>(() => api.listCases(), [])
  const { data: capabilities } = useAsync<Capabilities>(() => api.capabilities(), [])

  const open = (cases?.items ?? []).filter((item) => item.status !== 'CLOSED' && item.status !== 'ARCHIVED')
  const evidenceTotal = (cases?.items ?? []).reduce((sum, item) => sum + item.counts.evidence, 0)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="subtitle">
            AI output is analysis, not evidence. Every conclusion in TRACE traces back to a
            hash-verified artifact.
          </p>
        </div>
      </div>

      <div className="stat-row" style={{ marginBottom: 20 }}>
        <div className="stat">
          <div className="label">Open cases</div>
          <div className="value">{open.length}</div>
        </div>
        <div className="stat">
          <div className="label">Total cases</div>
          <div className="value">{cases?.total ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Evidence objects</div>
          <div className="value">{evidenceTotal}</div>
        </div>
        <div className="stat">
          <div className="label">Capabilities live</div>
          <div className="value">
            {capabilities ? capabilities.implemented.length : '—'}
            <span className="muted" style={{ fontSize: 14 }}>
              /{capabilities ? capabilities.implemented.length + capabilities.not_implemented.length : '—'}
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Recent cases</h2>
          <Link to="/cases">All cases</Link>
        </header>
        <div className="body flush">
          {open.length === 0 ? (
            <div className="empty">
              No open cases. <Link to="/cases">Create one</Link> to start an investigation.
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Title</th>
                  <th>Severity</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {open.slice(0, 8).map((item) => (
                  <tr key={item.case_id}>
                    <td className="mono">
                      <Link to={`/cases/${item.case_id}`}>{item.case_id}</Link>
                    </td>
                    <td>{item.title}</td>
                    <td>
                      <Pill value={item.severity} />
                    </td>
                    <td>{item.counts.evidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Platform capabilities</h2>
          <span className="muted">Sprint 1 of 7</span>
        </header>
        <div className="body flush">
          <table>
            <thead>
              <tr>
                <th>Capability</th>
                <th>Status</th>
                <th>Sprint</th>
              </tr>
            </thead>
            <tbody>
              {[...(capabilities?.implemented ?? []), ...(capabilities?.not_implemented ?? [])].map(
                (capability) => (
                  <tr key={capability.key}>
                    <td>
                      {capability.title}
                      <div className="muted mono" style={{ fontSize: 11 }}>
                        {capability.key}
                      </div>
                    </td>
                    <td>
                      <Pill
                        value={capability.status === 'IMPLEMENTED' ? 'VERIFIED' : 'PENDING'}
                        tone={capability.status === 'IMPLEMENTED' ? 'verified' : 'muted'}
                      />
                    </td>
                    <td className="muted">{capability.sprint}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
