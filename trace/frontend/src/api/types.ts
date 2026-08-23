/** Response shapes mirrored from the TRACE OpenAPI schema. */

export type CaseStatus = 'OPEN' | 'IN_PROGRESS' | 'CONTAINMENT' | 'CLOSED' | 'ARCHIVED'
export type Severity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type VerificationResult = 'VERIFIED' | 'MISMATCH' | 'MISSING' | 'ERROR'
export type ParseStatus = 'PENDING' | 'QUEUED' | 'PARSING' | 'PARSED' | 'FAILED' | 'UNSUPPORTED'

export interface CaseCounts {
  evidence: number
  /** null means "not computed yet" — rendered as NOT IMPLEMENTED, never as 0. */
  entities: number | null
  findings: number | null
}

export interface Case {
  case_id: string
  tenant_id: string
  title: string
  description: string | null
  status: CaseStatus
  severity: Severity
  investigator: string | null
  tags: string[]
  created_at: string
  updated_at: string
  closed_at: string | null
  counts: CaseCounts
}

export interface Evidence {
  evidence_id: string
  case_id: string
  source: string
  source_type: string
  original_filename: string
  original_path: string | null
  collection_timestamp: string
  original_timestamp: string | null
  collector: string
  acquisition_method: string
  size: number
  sha256: string
  mime_type: string
  storage_bucket: string
  storage_key: string
  retention_policy: string
  legal_hold: boolean
  parse_status: ParseStatus
  parse_detail: string | null
  last_verified_at: string | null
  last_verification_result: VerificationResult | null
  notes: string | null
  created_at: string
}

export interface Verification {
  verified: boolean
  expected_hash: string
  actual_hash: string | null
  evidence_id: string
  algorithm: string
  size_expected: number
  size_actual: number | null
  result: VerificationResult
  verified_at: string
  detail: string
}

export interface AuditRecord {
  audit_id: string
  sequence: number
  timestamp: string
  actor: string
  actor_type: string
  action: string
  case_id: string | null
  evidence_id: string | null
  entity_id: string | null
  source_ip: string | null
  reason: string | null
  details: Record<string, unknown>
  prev_hash: string
  record_hash: string
}

export interface ChainVerification {
  verified: boolean
  tenant_id: string
  records_checked: number
  first_broken_sequence: number | null
  first_broken_audit_id: string | null
  missing_sequences: number[]
  detail: string
}

export interface Capability {
  key: string
  title: string
  status: 'IMPLEMENTED' | 'NOT_IMPLEMENTED'
  sprint: number
  endpoints: string[]
  detail: string
}

export interface Capabilities {
  implemented: Capability[]
  not_implemented: Capability[]
}

export interface Paged<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface DependencyHealth {
  name: string
  status: string
  detail: string
  required: boolean
}

export interface Readiness {
  status: string
  dependencies: DependencyHealth[]
}
