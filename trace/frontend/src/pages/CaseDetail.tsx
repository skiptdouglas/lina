import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { Link } from 'react-router-dom'

import { api, ApiError } from '@/api/client'
import { Pill } from '@/components/Pill'
import { ProofPanel } from '@/components/ProofPanel'
import { useAsync } from '@/hooks/useAsync'
import type { AuditRecord, Case, Evidence, Paged, ParseReport, Verification } from '@/api/types'

const SOURCE_TYPES = [
  'SYSMON',
  'WINDOWS_SECURITY',
  'WINDOWS_EVTX',
  'LINUX_JSON',
  'LINUX_SYSLOG',
  'ZEEK',
  'SURICATA',
  'PCAP',
  'MEMORY_IMAGE',
  'DISK_IMAGE',
  'CLOUD_AUDIT',
  'EMAIL',
  'FILE',
  'OTHER',
]

const ACQUISITION_METHODS = [
  'MANUAL_UPLOAD',
  'LOG_EXPORT',
  'LIVE_COLLECTION',
  'DISK_ACQUISITION',
  'MEMORY_ACQUISITION',
  'API_PULL',
  'AGENT_STREAM',
]

export function CaseDetail() {
  const { caseId = '' } = useParams()
  const { data: detail, reload: reloadCase } = useAsync<Case>(() => api.getCase(caseId), [caseId])
  const {
    data: evidence,
    reload: reloadEvidence,
    loading,
  } = useAsync<Paged<Evidence>>(() => api.listEvidence(caseId), [caseId])
  const { data: audit, reload: reloadAudit } = useAsync<Paged<AuditRecord>>(
    () => api.listAudit({ case_id: caseId }),
    [caseId],
  )

  const refresh = () => {
    reloadCase()
    reloadEvidence()
    reloadAudit()
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>
            <span className="mono">{caseId}</span> {detail ? `— ${detail.title}` : ''}
          </h1>
          <p className="subtitle">{detail?.description || 'No description recorded.'}</p>
        </div>
        <div className="row">
          <Link className="btn small" to={`/timeline?case=${caseId}`}>
            View timeline
          </Link>
          <Pill value={detail?.severity} />
          <Pill value={detail?.status} />
        </div>
      </div>

      <div className="stat-row" style={{ marginBottom: 20 }}>
        <div className="stat">
          <div className="label">Evidence objects</div>
          <div className="value">{detail?.counts.evidence ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Entities</div>
          <div className="value small muted">Sprint 3</div>
        </div>
        <div className="stat">
          <div className="label">Findings</div>
          <div className="value small muted">Sprint 4</div>
        </div>
        <div className="stat">
          <div className="label">Investigator</div>
          <div className="value small">{detail?.investigator ?? '—'}</div>
        </div>
      </div>

      <UploadEvidence caseId={caseId} onUploaded={refresh} />
      <EvidenceTable
        evidence={evidence?.items ?? []}
        loading={loading}
        onVerified={refresh}
      />
      <ChainOfCustody records={audit?.items ?? []} />
    </>
  )
}

function UploadEvidence({ caseId, onUploaded }: { caseId: string; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [source, setSource] = useState('')
  const [sourceType, setSourceType] = useState('OTHER')
  const [acquisition, setAcquisition] = useState('MANUAL_UPLOAD')
  const [originalPath, setOriginalPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Evidence | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('case_id', caseId)
      form.append('source', source)
      form.append('source_type', sourceType)
      form.append('acquisition_method', acquisition)
      if (originalPath) form.append('original_path', originalPath)
      const created = await api.uploadEvidence(form)
      setResult(created)
      setFile(null)
      setSource('')
      setOriginalPath('')
      onUploaded()
    } catch (caught) {
      setError((caught as ApiError).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <header>
        <h2>Add evidence</h2>
        <span className="muted">
          Hashed on receipt · stored raw · verified before it is registered
        </span>
      </header>
      <div className="body">
        {error ? <div className="notice danger">{error}</div> : null}
        {result ? (
          <div className="notice verified">
            <h3>Evidence registered — {result.evidence_id}</h3>
            <p>
              SHA-256 computed over {result.size.toLocaleString()} bytes and confirmed against the
              stored object.
            </p>
            <code className="hash" style={{ marginTop: 8 }}>
              {result.sha256}
            </code>
          </div>
        ) : null}

        <div
          className={`dropzone ${file ? 'active' : ''}`}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            const dropped = event.dataTransfer.files?.[0]
            if (dropped) setFile(dropped)
          }}
        >
          {file ? (
            <span>
              <strong>{file.name}</strong> — {file.size.toLocaleString()} bytes
            </span>
          ) : (
            <span>Drop an artifact here, or choose a file below.</span>
          )}
        </div>

        <div className="field" style={{ marginTop: 12 }}>
          <label htmlFor="evidence-file">Artifact</label>
          <input
            id="evidence-file"
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>

        <div className="grid-2">
          <div className="field">
            <label htmlFor="evidence-source">Source system</label>
            <input
              id="evidence-source"
              required
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="FINANCE-LAPTOP-07"
            />
          </div>
          <div className="field">
            <label htmlFor="evidence-source-type">Source type</label>
            <select
              id="evidence-source-type"
              value={sourceType}
              onChange={(event) => setSourceType(event.target.value)}
            >
              {SOURCE_TYPES.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="evidence-acquisition">Acquisition method</label>
            <select
              id="evidence-acquisition"
              value={acquisition}
              onChange={(event) => setAcquisition(event.target.value)}
            >
              {ACQUISITION_METHODS.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="evidence-path">Original path on the source</label>
            <input
              id="evidence-path"
              value={originalPath}
              onChange={(event) => setOriginalPath(event.target.value)}
              placeholder="C:\Windows\System32\winevt\Logs\Sysmon.evtx"
            />
          </div>
        </div>

        <button className="primary" type="submit" disabled={busy || !file || !source}>
          {busy ? 'Hashing and storing…' : 'Upload evidence'}
        </button>
      </div>
    </form>
  )
}

function EvidenceTable({
  evidence,
  loading,
  onVerified,
}: {
  evidence: Evidence[]
  loading: boolean
  onVerified: () => void
}) {
  const [verifications, setVerifications] = useState<Record<string, Verification>>({})
  const [reports, setReports] = useState<Record<string, ParseReport>>({})
  const [parseError, setParseError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const verify = async (evidenceId: string) => {
    setBusy(evidenceId)
    try {
      const result = await api.verifyEvidence(evidenceId)
      setVerifications((current) => ({ ...current, [evidenceId]: result }))
      onVerified()
    } finally {
      setBusy(null)
    }
  }

  const parse = async (evidenceId: string, force: boolean) => {
    setBusy(evidenceId)
    setParseError(null)
    try {
      const result = await api.parseEvidence(evidenceId, force)
      setReports((current) => ({ ...current, [evidenceId]: result }))
      onVerified()
    } catch (caught) {
      setParseError((caught as ApiError).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card">
      <header>
        <h2>Evidence</h2>
        <span className="muted">{evidence.length} object(s)</span>
      </header>
      <div className="body flush">
        {parseError ? (
          <div className="notice danger" style={{ margin: 16 }}>
            {parseError}
          </div>
        ) : null}
        {loading && evidence.length === 0 ? <div className="empty">Loading…</div> : null}
        {!loading && evidence.length === 0 ? (
          <div className="empty">No evidence uploaded to this case yet.</div>
        ) : null}
        {evidence.map((item) => {
          const verification = verifications[item.evidence_id]
          return (
            <div
              key={item.evidence_id}
              style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}
            >
              <div className="row spread">
                <div>
                  <strong>{item.original_filename}</strong>{' '}
                  <span className="muted mono" style={{ fontSize: 11 }}>
                    {item.evidence_id}
                  </span>
                  <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                    {item.source} · {item.source_type} · {item.size.toLocaleString()} bytes ·
                    collected {new Date(item.collection_timestamp).toISOString().slice(0, 19).replace('T', ' ')}Z
                  </div>
                </div>
                <div className="row">
                  <Pill value={item.parse_status} />
                  {item.legal_hold ? <span className="pill warn">Legal hold</span> : null}
                  <button
                    className="small"
                    disabled={busy === item.evidence_id}
                    onClick={() => verify(item.evidence_id)}
                  >
                    {busy === item.evidence_id ? 'Verifying…' : 'Verify evidence'}
                  </button>
                  <button
                    className="small"
                    disabled={busy === item.evidence_id}
                    onClick={() => parse(item.evidence_id, item.parse_status === 'PARSED')}
                  >
                    {item.parse_status === 'PARSED' ? 'Re-parse' : 'Parse'}
                  </button>
                  <ProofPanel evidenceId={item.evidence_id} sha256={item.sha256} />
                </div>
              </div>

              <code className="hash" style={{ marginTop: 8 }}>
                sha256:{item.sha256}
              </code>

              {verification ? (
                <div
                  className={`notice ${verification.verified ? 'verified' : 'danger'}`}
                  style={{ marginTop: 10, marginBottom: 0 }}
                >
                  <h3>
                    {verification.result} — {verification.verified ? 'integrity intact' : 'integrity FAILED'}
                  </h3>
                  <p>{verification.detail}</p>
                  <div style={{ marginTop: 8 }}>
                    <div className="muted" style={{ fontSize: 11 }}>
                      Expected
                    </div>
                    <code className="hash">{verification.expected_hash}</code>
                    <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
                      Recalculated
                    </div>
                    <code className="hash">{verification.actual_hash ?? 'object not found'}</code>
                  </div>
                </div>
              ) : item.last_verification_result ? (
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  Last verified{' '}
                  {item.last_verified_at
                    ? new Date(item.last_verified_at).toISOString().slice(0, 19).replace('T', ' ')
                    : '—'}
                  Z — <Pill value={item.last_verification_result} />
                </div>
              ) : null}

              {reports[item.evidence_id] ? (
                <div
                  className={`notice ${reports[item.evidence_id].events_produced > 0 ? 'verified' : 'warn'}`}
                  style={{ marginTop: 10, marginBottom: 0 }}
                >
                  <h3>
                    {reports[item.evidence_id].parse_status} —{' '}
                    {reports[item.evidence_id].events_produced} event(s) from{' '}
                    {reports[item.evidence_id].records_read} record(s)
                  </h3>
                  <p>{reports[item.evidence_id].detail}</p>
                  {reports[item.evidence_id].unrecognised > 0 ? (
                    <p style={{ marginTop: 6 }}>
                      {reports[item.evidence_id].unrecognised} record(s) were read but not
                      mapped. What TRACE did not understand is reported, not hidden.
                    </p>
                  ) : null}
                </div>
              ) : item.parse_detail ? (
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  {item.parse_detail}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ChainOfCustody({ records }: { records: AuditRecord[] }) {
  return (
    <div className="card">
      <header>
        <h2>Chain of custody</h2>
        <span className="muted">{records.length} record(s), newest first</span>
      </header>
      <div className="body flush">
        {records.length === 0 ? (
          <div className="empty">No audit records for this case.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Timestamp</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Evidence</th>
                <th>Reason</th>
                <th className="mono">Record hash</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.audit_id}>
                  <td className="muted mono">{record.sequence}</td>
                  <td className="mono">
                    {new Date(record.timestamp).toISOString().slice(0, 19).replace('T', ' ')}Z
                  </td>
                  <td>
                    <Pill value={record.action} tone="info" />
                  </td>
                  <td className="muted">{record.actor}</td>
                  <td className="mono muted" style={{ fontSize: 11 }}>
                    {record.evidence_id ?? '—'}
                  </td>
                  <td className="muted">{record.reason ?? '—'}</td>
                  <td className="mono muted" style={{ fontSize: 11 }}>
                    {record.record_hash.slice(0, 16)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
