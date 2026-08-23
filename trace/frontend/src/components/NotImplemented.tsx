import type { Capability } from '@/api/types'

interface Props {
  feature: string
  title: string
  capability?: Capability
}

/**
 * Rendered wherever a capability is not built yet (ADR-0004).
 *
 * Deliberately not an empty chart or a zeroed table: an investigator must be
 * able to tell "TRACE has not looked" from "TRACE looked and found nothing".
 */
export function NotImplemented({ feature, title, capability }: Props) {
  return (
    <div className="card">
      <header>
        <h2>{title}</h2>
        <span className="pill warn">Not implemented</span>
      </header>
      <div className="body">
        <p style={{ marginTop: 0 }}>
          {capability?.detail || `${title} is not implemented yet.`}
        </p>
        <div className="stat-row" style={{ marginTop: 16 }}>
          <div className="stat">
            <div className="label">Capability</div>
            <div className="value small mono">{capability?.key ?? feature}</div>
          </div>
          <div className="stat">
            <div className="label">Planned</div>
            <div className="value small">Sprint {capability?.sprint ?? '—'}</div>
          </div>
          <div className="stat">
            <div className="label">API</div>
            <div className="value small mono">
              {capability?.endpoints?.[0] ?? '—'}
            </div>
          </div>
        </div>
        <p className="muted" style={{ marginTop: 16, marginBottom: 0 }}>
          The endpoint returns <code>501 NOT_IMPLEMENTED</code> rather than fabricated
          results. See <code>docs/ROADMAP.md</code>.
        </p>
      </div>
    </div>
  )
}
