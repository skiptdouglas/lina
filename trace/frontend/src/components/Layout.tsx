import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'

import { api, getToken, setToken } from '@/api/client'
import { useAsync } from '@/hooks/useAsync'
import type { Capabilities } from '@/api/types'

/** Navigation from brief §43; entries flag what is not built yet. */
const NAV = [
  { to: '/', label: 'Dashboard', capability: null },
  { to: '/cases', label: 'Cases', capability: null },
  { to: '/search', label: 'Search', capability: 'search.query' },
  { to: '/patterns', label: 'Pattern Hunter', capability: 'patterns.find_similar' },
  { to: '/entities', label: 'Entities', capability: 'entities.registry' },
  { to: '/graph', label: 'Graph', capability: 'graph.neighbourhood' },
  { to: '/timeline', label: 'Timeline', capability: 'timeline.case' },
  { to: '/detections', label: 'Detections', capability: 'detections.sigma' },
  { to: '/threat-intel', label: 'Threat Intelligence', capability: 'threatintel.enrich' },
  { to: '/ai', label: 'AI Investigator', capability: 'ai.investigate' },
  { to: '/reports', label: 'Reports', capability: 'reports.generate' },
  { to: '/administration', label: 'Administration', capability: null },
]

export function Layout() {
  const { data: capabilities } = useAsync<Capabilities>(() => api.capabilities(), [])
  const pending = new Set((capabilities?.not_implemented ?? []).map((c) => c.key))

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span>
            TRACE
            <small>Threat Reconstruction &amp; Analysis</small>
          </span>
        </div>
        <nav className="nav">
          <div className="nav-section">Investigation</div>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}>
              <span>{item.label}</span>
              {item.capability && pending.has(item.capability) ? (
                <span className="pending">SOON</span>
              ) : null}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <TopBar />
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

function TopBar() {
  const [token, setLocalToken] = useState(getToken())
  const [editing, setEditing] = useState(!getToken())
  const { data: readiness, reload } = useAsync(() => api.readiness(), [token])

  useEffect(() => {
    const timer = window.setInterval(reload, 30_000)
    return () => window.clearInterval(timer)
  }, [reload])

  const save = () => {
    setToken(token)
    setEditing(false)
    reload()
  }

  return (
    <div className="topbar">
      <div className="row">
        {(readiness?.dependencies ?? []).map((dependency) => (
          <span
            key={dependency.name}
            className={`pill ${dependency.status === 'UP' ? 'verified' : dependency.required ? 'mismatch' : 'warn'}`}
            title={dependency.detail}
          >
            {dependency.name} {dependency.status}
          </span>
        ))}
      </div>
      <div className="row">
        {editing ? (
          <>
            <input
              type="password"
              value={token}
              placeholder="TRACE API token"
              onChange={(event) => setLocalToken(event.target.value)}
              style={{ width: 260 }}
            />
            <button className="primary small" onClick={save}>
              Save
            </button>
          </>
        ) : (
          <button className="small" onClick={() => setEditing(true)}>
            API token set — change
          </button>
        )}
      </div>
    </div>
  )
}
