import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api, ApiError } from '@/api/client'
import { EventDetail, formatTime, severityTone, summarise } from '@/components/EventDetail'
import { Pill } from '@/components/Pill'
import { useAsync } from '@/hooks/useAsync'
import type { Case, Paged, TimelineResponse } from '@/api/types'

export function Timeline() {
  const [params, setParams] = useSearchParams()
  const caseId = params.get('case') ?? ''
  const entity = params.get('entity') ?? ''
  const minSeverity = params.get('min_severity') ?? ''

  const { data: cases } = useAsync<Paged<Case>>(() => api.listCases(), [])
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data, error, loading } = useAsync<TimelineResponse | null>(async () => {
    if (!caseId) return null
    const query: Record<string, string> = { limit: '500' }
    if (entity) query.entity = entity
    if (minSeverity) query.min_severity = minSeverity
    return api.timeline(caseId, query)
  }, [caseId, entity, minSeverity])

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Timeline</h1>
          <p className="subtitle">
            Chronological reconstruction across every parsed source. Ordering uses the
            clock-corrected time; what the source recorded is preserved on every entry.
          </p>
        </div>
      </div>

      <div className="card">
        <header>
          <h2>Scope</h2>
          {data ? (
            <span className="muted" style={{ fontSize: 12 }}>
              {data.total} event{data.total === 1 ? '' : 's'} · {data.took_ms}ms
            </span>
          ) : null}
        </header>
        <div className="body">
          <div className="grid-2">
            <div className="field">
              <label htmlFor="tl-case">Case</label>
              <select id="tl-case" value={caseId} onChange={(e) => update('case', e.target.value)}>
                <option value="">Select a case…</option>
                {(cases?.items ?? []).map((item) => (
                  <option key={item.case_id} value={item.case_id}>
                    {item.case_id} — {item.title}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="tl-entity">Entity (exact host, user, IP or domain)</label>
              <input
                id="tl-entity"
                defaultValue={entity}
                placeholder="FINANCE-LAPTOP-07"
                onBlur={(e) => update('entity', e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="tl-sev">Minimum severity</label>
              <select
                id="tl-sev"
                value={minSeverity}
                onChange={(e) => update('min_severity', e.target.value)}
              >
                <option value="">Any</option>
                <option value="3">3 — notable</option>
                <option value="5">5 — suspicious</option>
                <option value="8">8 — critical</option>
              </select>
            </div>
          </div>
          {data?.clock_corrections_applied ? (
            <div className="notice warn" style={{ marginBottom: 0 }}>
              <h3>Clock corrections applied</h3>
              <p>
                Some entries were reordered using a collector-reported clock offset. Entries
                marked <span className="pill warn">±</span> show both times when expanded — the
                original is never overwritten.
              </p>
            </div>
          ) : null}
        </div>
      </div>

      {error ? <div className="notice danger">{(error as ApiError).message}</div> : null}
      {!caseId ? (
        <div className="card">
          <div className="empty">Select a case to reconstruct its timeline.</div>
        </div>
      ) : null}
      {caseId && loading && !data ? (
        <div className="card">
          <div className="empty">Loading…</div>
        </div>
      ) : null}

      {data && data.entries.length === 0 ? (
        <div className="card">
          <div className="empty">
            No events for this scope. If evidence was uploaded but never parsed, check its parse
            status on the case page.
          </div>
        </div>
      ) : null}

      {data && data.entries.length > 0 ? (
        <div className="card">
          <header>
            <h2>{data.case_id}</h2>
            <span className="muted" style={{ fontSize: 12 }}>
              oldest first
            </span>
          </header>
          <div className="body flush">
            {data.entries.map((entry) => {
              const event = entry.event
              const open = expanded === event.event_id
              return (
                <div key={event.event_id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <div
                    className="row"
                    style={{ padding: '10px 16px', cursor: 'pointer', alignItems: 'flex-start' }}
                    onClick={() => setExpanded(open ? null : event.event_id)}
                  >
                    <span
                      className="mono muted"
                      style={{ width: 200, flexShrink: 0, fontSize: 12 }}
                    >
                      {formatTime(event.timestamp)}
                      {entry.clock_corrected ? (
                        <span className="pill warn" style={{ marginLeft: 6 }} title="Clock corrected">
                          ±
                        </span>
                      ) : null}
                    </span>
                    <span style={{ width: 190, flexShrink: 0 }}>
                      <Pill value={event.event_type} tone={severityTone(event.severity)} />
                    </span>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <div className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>
                        {summarise(event)}
                      </div>
                      <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                        {event.device.hostname ?? '—'}
                        {event.user.name ? ` · ${event.user.name}` : ''}
                        {` · evidence ${entry.provenance.evidence_id.slice(0, 12)}…`}
                      </div>
                    </span>
                  </div>
                  {open ? <EventDetail event={event} /> : null}
                </div>
              )
            })}
          </div>
        </div>
      ) : null}
    </>
  )
}
