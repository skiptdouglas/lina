import { useState } from 'react'

import { api, ApiError } from '@/api/client'
import { EventRow } from '@/components/EventDetail'
import { useAsync } from '@/hooks/useAsync'
import type { Case, Paged, SearchRequest, SearchResponse } from '@/api/types'

const EVENT_TYPES = [
  'PROCESS_CREATE', 'NETWORK_CONNECT', 'NETWORK_FLOW', 'DNS_QUERY', 'FILE_CREATE',
  'REGISTRY_SET', 'IMAGE_LOAD', 'PROCESS_ACCESS', 'AUTH_LOGON', 'AUTH_LOGON_FAILED',
  'FILE_SHARE_ACCESS', 'LOG_CLEARED', 'IDS_ALERT', 'HTTP_REQUEST', 'TLS_SESSION',
]

export function Search() {
  const { data: cases } = useAsync<Paged<Case>>(() => api.listCases(), [])
  const [form, setForm] = useState<SearchRequest>({ limit: 100 })
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = (key: keyof SearchRequest, value: string) =>
    setForm((current) => ({ ...current, [key]: value || undefined }))

  const run = async (event?: React.FormEvent) => {
    event?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setResult(await api.search(form))
    } catch (caught) {
      setError((caught as ApiError).message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Search</h1>
          <p className="subtitle">
            Normalized events across every parsed source. Each result traces back to the exact
            bytes it came from.
          </p>
        </div>
      </div>

      <form className="card" onSubmit={run}>
        <header>
          <h2>Query</h2>
          <button className="primary small" type="submit" disabled={busy}>
            {busy ? 'Searching…' : 'Search'}
          </button>
        </header>
        <div className="body">
          <div className="field">
            <label htmlFor="q">Free text</label>
            <input
              id="q"
              value={form.query ?? ''}
              onChange={(e) => set('query', e.target.value)}
              placeholder="powershell, lsass, a domain, a path…"
            />
          </div>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="case">Case</label>
              <select
                id="case"
                value={form.case_id ?? ''}
                onChange={(e) => set('case_id', e.target.value)}
              >
                <option value="">All cases</option>
                {(cases?.items ?? []).map((item) => (
                  <option key={item.case_id} value={item.case_id}>
                    {item.case_id} — {item.title}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="event-type">Event type</label>
              <select
                id="event-type"
                value={form.event_type ?? ''}
                onChange={(e) => set('event_type', e.target.value)}
              >
                <option value="">Any</option>
                {EVENT_TYPES.map((type) => (
                  <option key={type}>{type}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="hostname">Host</label>
              <input id="hostname" value={form.hostname ?? ''} onChange={(e) => set('hostname', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="user">User</label>
              <input id="user" value={form.user ?? ''} onChange={(e) => set('user', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="ip">IP address</label>
              <input id="ip" value={form.ip ?? ''} onChange={(e) => set('ip', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="domain">Domain</label>
              <input id="domain" value={form.domain ?? ''} onChange={(e) => set('domain', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="process">Process</label>
              <input id="process" value={form.process ?? ''} onChange={(e) => set('process', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="hash">SHA-256</label>
              <input id="hash" value={form.hash ?? ''} onChange={(e) => set('hash', e.target.value)} />
            </div>
          </div>
        </div>
      </form>

      {error ? <div className="notice danger">{error}</div> : null}

      {result ? (
        <div className="card">
          <header>
            <h2>
              {result.total} result{result.total === 1 ? '' : 's'}
            </h2>
            <span className="muted" style={{ fontSize: 12 }}>
              {result.took_ms}ms · backend “{result.backend.name}”
            </span>
          </header>
          <div className="body flush">
            {/* An analyst must be able to tell "nothing matched" from
                "this backend cannot express that". */}
            {!result.backend.fuzzy ? (
              <div
                className="muted"
                style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)', fontSize: 12 }}
              >
                {result.backend.notes}
              </div>
            ) : null}
            {result.events.length === 0 ? (
              <div className="empty">
                No events matched. This is a real result from the “{result.backend.name}” backend,
                not a limitation — though note its capabilities above.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Time (UTC)</th>
                    <th>Event</th>
                    <th>Host</th>
                    <th>User</th>
                    <th>Detail</th>
                    <th>Sev</th>
                  </tr>
                </thead>
                <tbody>
                  {result.events.map((event) => (
                    <EventRow
                      key={event.event_id}
                      event={event}
                      expanded={expanded === event.event_id}
                      onToggle={() =>
                        setExpanded(expanded === event.event_id ? null : event.event_id)
                      }
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      ) : null}
    </>
  )
}
