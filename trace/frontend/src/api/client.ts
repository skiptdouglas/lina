/**
 * TRACE API client.
 *
 * The browser holds exactly one credential: the analyst's TRACE API token.
 * It never holds a model, object-store or database credential — all of that
 * stays server-side behind the API (docs/SECURITY.md §7).
 */

import type {
  Anchor,
  AnchorBackendStatus,
  AnchorVerification,
  AuditRecord,
  Capabilities,
  Case,
  ChainVerification,
  ConsistencyProof,
  Evidence,
  LogEntryRow,
  LogStatus,
  Paged,
  ProofBundle,
  Readiness,
  Verification,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'
const TOKEN_STORAGE_KEY = 'trace.api.token'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly payload: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** A capability that exists in the roadmap but is not built yet (ADR-0004). */
  get notImplemented(): boolean {
    return this.status === 501
  }
}

export function getToken(): string {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setToken(token: string): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
    else window.localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    /* storage unavailable (private mode) — the session simply is not persisted */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...init, headers })
  const text = await response.text()
  const body = text ? (JSON.parse(text) as Record<string, unknown>) : {}

  if (!response.ok) {
    throw new ApiError(
      response.status,
      (body.code as string) ?? (body.status as string) ?? 'ERROR',
      (body.detail as string) ?? response.statusText,
      body,
    )
  }
  return body as T
}

export const api = {
  readiness: () => request<Readiness>('/health/ready'),
  capabilities: () => request<Capabilities>('/capabilities'),

  listCases: (params: { status?: string; q?: string } = {}) => {
    const search = new URLSearchParams()
    if (params.status) search.set('status', params.status)
    if (params.q) search.set('q', params.q)
    const suffix = search.toString()
    return request<Paged<Case>>(`/cases${suffix ? `?${suffix}` : ''}`)
  },
  getCase: (caseId: string) => request<Case>(`/cases/${encodeURIComponent(caseId)}`),
  createCase: (payload: {
    title: string
    description?: string
    severity?: string
    case_id?: string
  }) => request<Case>('/cases', { method: 'POST', body: JSON.stringify(payload) }),
  updateCase: (caseId: string, payload: Record<string, unknown>) =>
    request<Case>(`/cases/${encodeURIComponent(caseId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  listEvidence: (caseId?: string) =>
    request<Paged<Evidence>>(
      `/evidence${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ''}`,
    ),
  uploadEvidence: (form: FormData) =>
    request<Evidence>('/evidence', { method: 'POST', body: form }),
  verifyEvidence: (evidenceId: string) =>
    request<Verification>(`/evidence/${encodeURIComponent(evidenceId)}/verify`),
  /** Download URL — the reason is recorded in the chain of custody. */
  downloadUrl: (evidenceId: string, reason: string) =>
    `${BASE_URL}/evidence/${encodeURIComponent(evidenceId)}/download?reason=${encodeURIComponent(reason)}`,

  // ---- anchoring (docs/ANCHORING.md) ----
  logStatus: () => request<LogStatus>('/anchoring/log'),
  logEntries: (limit = 50) => request<{ items: LogEntryRow[]; total: number }>(
    `/anchoring/log/entries?limit=${limit}`,
  ),
  anchorBackends: () => request<{ items: AnchorBackendStatus[] }>('/anchoring/backends'),
  listAnchors: () => request<Paged<Anchor>>('/anchors'),
  createAnchor: (payload: { backend?: string; force?: boolean } = {}) =>
    request<Anchor>('/anchors', { method: 'POST', body: JSON.stringify(payload) }),
  refreshAnchor: (anchorId: string) =>
    request<Anchor>(`/anchors/${encodeURIComponent(anchorId)}/refresh`, { method: 'POST' }),
  verifyAnchor: (anchorId: string) =>
    request<AnchorVerification>(`/anchors/${encodeURIComponent(anchorId)}/verify`),
  consistency: (first: number, second: number) =>
    request<ConsistencyProof>(`/anchoring/consistency?first=${first}&second=${second}`),
  evidenceProof: (evidenceId: string) =>
    request<ProofBundle>(`/evidence/${encodeURIComponent(evidenceId)}/proof`),
  receiptUrl: (anchorId: string) =>
    `${BASE_URL}/anchors/${encodeURIComponent(anchorId)}/receipt`,

  listAudit: (params: { case_id?: string; evidence_id?: string } = {}) => {
    const search = new URLSearchParams()
    if (params.case_id) search.set('case_id', params.case_id)
    if (params.evidence_id) search.set('evidence_id', params.evidence_id)
    const suffix = search.toString()
    return request<Paged<AuditRecord>>(`/audit${suffix ? `?${suffix}` : ''}`)
  },
  verifyChain: () => request<ChainVerification>('/audit/verify-chain'),
}
