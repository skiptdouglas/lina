import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError } from '@/api/client'
import { Pill } from '@/components/Pill'
import { useAsync } from '@/hooks/useAsync'
import type { Case, Paged } from '@/api/types'

export function Cases() {
  const [query, setQuery] = useState('')
  const { data, error, loading, reload } = useAsync<Paged<Case>>(
    () => api.listCases({ q: query || undefined }),
    [query],
  )

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Cases</h1>
          <p className="subtitle">Investigations visible to your organisation.</p>
        </div>
      </div>

      <NewCaseForm onCreated={reload} />

      <div className="card">
        <header>
          <h2>All cases {data ? `(${data.total})` : ''}</h2>
          <input
            placeholder="Filter by title…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            style={{ width: 220 }}
          />
        </header>
        <div className="body flush">
          {error ? <div className="empty">{(error as ApiError).message}</div> : null}
          {loading && !data ? <div className="empty">Loading…</div> : null}
          {data && data.items.length === 0 ? (
            <div className="empty">No cases yet. Create one above to begin.</div>
          ) : null}
          {data && data.items.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Title</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Investigator</th>
                  <th>Evidence</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.case_id}>
                    <td className="mono">
                      <Link to={`/cases/${item.case_id}`}>{item.case_id}</Link>
                    </td>
                    <td>{item.title}</td>
                    <td>
                      <Pill value={item.severity} />
                    </td>
                    <td>
                      <Pill value={item.status} />
                    </td>
                    <td className="muted">{item.investigator ?? '—'}</td>
                    <td>{item.counts.evidence}</td>
                    <td className="muted mono">{new Date(item.created_at).toISOString().slice(0, 16).replace('T', ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </div>
      </div>
    </>
  )
}

function NewCaseForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [caseId, setCaseId] = useState('')
  const [severity, setSeverity] = useState('MEDIUM')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.createCase({
        title,
        severity,
        description: description || undefined,
        case_id: caseId || undefined,
      })
      setTitle('')
      setCaseId('')
      setDescription('')
      setOpen(false)
      onCreated()
    } catch (caught) {
      setError((caught as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <div style={{ marginBottom: 20 }}>
        <button className="primary" onClick={() => setOpen(true)}>
          + New case
        </button>
      </div>
    )
  }

  return (
    <form className="card" onSubmit={submit}>
      <header>
        <h2>New case</h2>
        <button type="button" className="small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </header>
      <div className="body">
        {error ? <div className="notice danger">{error}</div> : null}
        <div className="field">
          <label htmlFor="case-title">Title</label>
          <input
            id="case-title"
            required
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Suspected phishing to lateral movement"
          />
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="case-id">Case ID (optional)</label>
            <input
              id="case-id"
              value={caseId}
              onChange={(event) => setCaseId(event.target.value.toUpperCase())}
              placeholder="Allocated automatically, e.g. CASE-0042"
            />
          </div>
          <div className="field">
            <label htmlFor="case-severity">Severity</label>
            <select
              id="case-severity"
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              {['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="case-description">Description</label>
          <textarea
            id="case-description"
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <button className="primary" type="submit" disabled={busy || !title}>
          {busy ? 'Creating…' : 'Create case'}
        </button>
      </div>
    </form>
  )
}
