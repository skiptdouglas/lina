import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { Administration } from '@/pages/Administration'
import { Anchoring } from '@/pages/Anchoring'
import { CaseDetail } from '@/pages/CaseDetail'
import { Cases } from '@/pages/Cases'
import { Dashboard } from '@/pages/Dashboard'
import { Pending } from '@/pages/Pending'

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/:caseId" element={<CaseDetail />} />
        <Route path="anchoring" element={<Anchoring />} />
        <Route path="administration" element={<Administration />} />

        {/* Capabilities that arrive in later sprints. */}
        <Route path="search" element={<Pending feature="search.query" title="Search" />} />
        <Route
          path="patterns"
          element={<Pending feature="patterns.find_similar" title="Pattern Hunter" />}
        />
        <Route path="entities" element={<Pending feature="entities.registry" title="Entities" />} />
        <Route path="graph" element={<Pending feature="graph.neighbourhood" title="Graph" />} />
        <Route path="timeline" element={<Pending feature="timeline.case" title="Timeline" />} />
        <Route
          path="detections"
          element={<Pending feature="detections.sigma" title="Detections" />}
        />
        <Route
          path="threat-intel"
          element={<Pending feature="threatintel.enrich" title="Threat Intelligence" />}
        />
        <Route path="ai" element={<Pending feature="ai.investigate" title="AI Investigator" />} />
        <Route path="reports" element={<Pending feature="reports.generate" title="Reports" />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
