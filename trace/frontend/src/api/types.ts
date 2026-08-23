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

// ---------------------------------------------------------------------------
// Evidence anchoring (docs/ANCHORING.md)
// ---------------------------------------------------------------------------

export type AnchorStatus = 'PENDING' | 'SUBMITTED' | 'CONFIRMED' | 'FAILED'

/** How much of the guarantee survives TRACE itself being compromised. */
export type Independence = 'SELF_ATTESTED' | 'THIRD_PARTY' | 'PUBLIC_BLOCKCHAIN'

export interface LogStatus {
  log_id: string
  tree_size: number
  root_hash: string
  last_anchored_size: number | null
  last_anchored_root: string | null
  last_anchor_id: string | null
  last_anchor_at: string | null
  unanchored_entries: number
  audit_log_size: number
  signing_key_id: string
  signing_algorithm: string
  public_key_b64: string
  default_backend: string
}

export interface Anchor {
  anchor_id: string
  log_id: string
  tree_size: number
  root_hash: string
  previous_tree_size: number | null
  previous_root_hash: string | null
  backend: string
  independence: Independence
  status: AnchorStatus
  external_ref: string | null
  explorer_url: string | null
  detail: string
  key_id: string
  algorithm: string
  created_at: string
  confirmed_at: string | null
  last_checked_at: string | null
}

export interface AnchorBackendStatus {
  name: string
  independence: Independence
  available: boolean
  detail: string
  is_default: boolean
}

export interface AnchorVerification {
  anchor_id: string
  verified: boolean
  status: AnchorStatus
  backend: string
  independence: Independence
  detail: string
  root_hash: string
  signature_valid: boolean
  root_recomputed: boolean
  external_ref: string | null
  metadata: Record<string, unknown>
}

export interface LogEntryRow {
  leaf_index: number
  entry_type: string
  entry_hash: string
  leaf_hash: string
  evidence_id: string | null
  case_id: string | null
  created_at: string
}

export interface ConsistencyProof {
  log_id: string
  first: number
  second: number
  first_root: string
  second_root: string
  proof: string[]
  verified: boolean
  detail: string
}

/** A self-contained, offline-verifiable proof of one evidence object. */
export interface ProofBundle {
  bundle_version: string
  evidence_id: string
  manifest: { manifest_version: string; entry_type: string; body: Record<string, unknown> }
  entry_hash: string
  leaf: { index: number; leaf_hash: string; hash_construction: string }
  tree: { tree_size: number; root_hash: string; inclusion_proof: string[] }
  signed_tree_head: Record<string, unknown>
  signature: { algorithm: string; key_id: string; public_key_b64: string; value: string }
  anchor: Record<string, unknown> | null
  how_to_verify: { offline_tool: string; usage: string; steps: string[] }
  what_this_proves: string[]
  what_this_does_not_prove: string[]
}
