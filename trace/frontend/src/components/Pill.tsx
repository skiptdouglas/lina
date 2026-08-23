interface Props {
  value: string | null | undefined
  tone?: string
}

const TONES: Record<string, string> = {
  VERIFIED: 'verified',
  MISMATCH: 'mismatch',
  MISSING: 'missing',
  ERROR: 'danger',
  CRITICAL: 'critical',
  HIGH: 'high',
  MEDIUM: 'info',
  LOW: 'muted',
  INFO: 'muted',
  OPEN: 'info',
  IN_PROGRESS: 'info',
  CONTAINMENT: 'warn',
  CLOSED: 'muted',
  ARCHIVED: 'muted',
  QUEUED: 'queued',
  PENDING: 'muted',
  PARSED: 'verified',
  FAILED: 'danger',
  UNSUPPORTED: 'warn',
}

export function Pill({ value, tone }: Props) {
  if (!value) return <span className="muted">—</span>
  return <span className={`pill ${tone ?? TONES[value] ?? 'muted'}`}>{value.replace(/_/g, ' ')}</span>
}
