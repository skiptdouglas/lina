import { NotImplemented } from '@/components/NotImplemented'
import { api } from '@/api/client'
import { useAsync } from '@/hooks/useAsync'
import type { Capabilities } from '@/api/types'

/**
 * Every navigation entry whose backing capability is not built yet renders
 * this page. It reads the live capability registry so the UI can never claim
 * more than the API actually implements.
 */
export function Pending({ feature, title }: { feature: string; title: string }) {
  const { data } = useAsync<Capabilities>(() => api.capabilities(), [])
  const capability = data?.not_implemented.find((item) => item.key === feature)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{title}</h1>
          <p className="subtitle">Planned capability — not built yet.</p>
        </div>
      </div>
      <NotImplemented feature={feature} title={title} capability={capability} />
    </>
  )
}
