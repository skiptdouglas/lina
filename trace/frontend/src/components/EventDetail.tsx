import { useState } from 'react'

import { api, ApiError } from '@/api/client'
import { Pill } from '@/components/Pill'
import type { TraceEvent } from '@/api/types'

/**
 * One event, expanded — and the path from it back to the original bytes.
 *
 * The "Show original record" action is the last hop of the provenance chain
 * (brief §57): it range-reads the exact bytes of the source record out of the
 * stored artifact. What the analyst sees is what the collector captured, not a
 * re-rendering of TRACE's interpretation of it.
 */
export function EventDetail({ event }: { event: TraceEvent }) {
  const [raw, setRaw] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const loadRaw = async () => {
    setBusy(true)
    setError(null)
    try {
      setRaw(await api.rawRecord(event.evidence_id, event.raw_reference))
    } catch (caught) {
      setError((caught as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  const corrected = event.timestamp !== event.original_timestamp

  return (
    <div style={{ padding: '12px 16px', background: 'var(--bg-inset)' }}>
      <div className="grid-2" style={{ gap: 16 }}>
        <Section title="When">
          <Field label="Normalized" value={formatTime(event.timestamp)} mono />
          <Field label="As the source recorded it" value={formatTime(event.original_timestamp)} mono />
          {corrected ? (
            <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
              Clock corrected by {event.clock.clock_offset_seconds}s ·{' '}
              {event.clock.method} · confidence {event.clock.correction_confidence}
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
              No clock correction applied.
            </div>
          )}
        </Section>

        <Section title="Who / where">
          <Field label="Host" value={event.device.hostname} />
          <Field
            label="User"
            value={
              event.user.name
                ? `${event.user.domain ? `${event.user.domain}\\` : ''}${event.user.name}`
                : null
            }
          />
          <Field label="Source" value={endpoint(event.source)} mono />
          <Field label="Destination" value={endpoint(event.destination)} mono />
        </Section>

        {event.process.name || event.process.command_line ? (
          <Section title="Process">
            <Field label="Name" value={event.process.name} />
            <Field label="PID" value={event.process.pid?.toString() ?? null} mono />
            <Field label="Parent" value={event.process.parent_name} />
            <Field label="Path" value={event.process.path} mono />
            <Field label="Command line" value={event.process.command_line} mono wrap />
            <Field label="SHA-256" value={event.process.sha256} mono wrap />
          </Section>
        ) : null}

        {event.file.path || event.file.name ? (
          <Section title="File">
            <Field label="Path" value={event.file.path} mono wrap />
            <Field label="SHA-256" value={event.file.sha256} mono wrap />
            <Field label="Size" value={event.file.size?.toLocaleString() ?? null} />
          </Section>
        ) : null}

        {event.network.protocol || event.network.bytes_out ? (
          <Section title="Network">
            <Field label="Protocol" value={event.network.protocol} />
            <Field label="Direction" value={event.network.direction} />
            <Field label="Bytes out" value={event.network.bytes_out?.toLocaleString() ?? null} />
            <Field label="Bytes in" value={event.network.bytes_in?.toLocaleString() ?? null} />
          </Section>
        ) : null}
      </div>

      {Object.keys(event.extra ?? {}).length > 0 ? (
        <details style={{ marginTop: 12 }}>
          <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>
            Source-specific fields
          </summary>
          <pre className="hash" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(event.extra, null, 2)}
          </pre>
        </details>
      ) : null}

      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <div className="row spread">
          <div>
            <div className="muted" style={{ fontSize: 11 }}>
              Provenance — evidence {event.evidence_id} · record {event.raw_reference}
            </div>
          </div>
          <button className="small" onClick={loadRaw} disabled={busy}>
            {busy ? 'Reading…' : raw ? 'Reload original record' : 'Show original record'}
          </button>
        </div>
        {error ? (
          <div className="notice danger" style={{ marginTop: 8, marginBottom: 0 }}>
            {error}
          </div>
        ) : null}
        {raw ? (
          <>
            <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
              Exact bytes from the stored artifact:
            </div>
            <pre className="hash" style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>
              {prettyIfJson(raw)}
            </pre>
          </>
        ) : null}
      </div>
    </div>
  )
}

export function EventRow({
  event,
  expanded,
  onToggle,
}: {
  event: TraceEvent
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr onClick={onToggle} style={{ cursor: 'pointer' }}>
        <td className="mono" style={{ whiteSpace: 'nowrap' }}>
          {formatTime(event.timestamp)}
          {event.timestamp !== event.original_timestamp ? (
            <span className="pill warn" style={{ marginLeft: 6 }} title="Clock corrected">
              ±
            </span>
          ) : null}
        </td>
        <td>
          <Pill value={event.event_type} tone={severityTone(event.severity)} />
        </td>
        <td className="muted">{event.device.hostname ?? '—'}</td>
        <td className="muted">{event.user.name ?? '—'}</td>
        <td className="mono" style={{ fontSize: 12, maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {summarise(event)}
        </td>
        <td className="muted">{event.severity}</td>
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={6} style={{ padding: 0 }}>
            <EventDetail event={event} />
          </td>
        </tr>
      ) : null}
    </>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        className="muted"
        style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}
      >
        {title}
      </div>
      {children}
    </div>
  )
}

function Field({
  label,
  value,
  mono,
  wrap,
}: {
  label: string
  value: string | null | undefined
  mono?: boolean
  wrap?: boolean
}) {
  if (!value) return null
  return (
    <div style={{ marginBottom: 4 }}>
      <span className="muted" style={{ fontSize: 11 }}>
        {label}:{' '}
      </span>
      <span
        className={mono ? 'mono' : undefined}
        style={wrap ? { wordBreak: 'break-all' } : undefined}
      >
        {value}
      </span>
    </div>
  )
}

export function summarise(event: TraceEvent): string {
  if (event.process.command_line) return event.process.command_line
  if (event.destination.domain) return event.destination.domain
  if (event.file.path) return event.file.path
  if (event.destination.ip) {
    return `${event.destination.ip}${event.destination.port ? `:${event.destination.port}` : ''}`
  }
  if (event.process.name) return event.process.name
  return event.category
}

export function severityTone(severity: number): string {
  if (severity >= 8) return 'critical'
  if (severity >= 5) return 'high'
  if (severity >= 3) return 'info'
  return 'muted'
}

export function formatTime(value: string): string {
  return new Date(value).toISOString().slice(0, 23).replace('T', ' ')
}

function endpoint(value: { ip: string | null; port: number | null; domain: string | null }): string | null {
  if (value.domain) return value.domain
  if (!value.ip) return null
  return value.port ? `${value.ip}:${value.port}` : value.ip
}

function prettyIfJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}
