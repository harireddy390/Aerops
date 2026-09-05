import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { Layout } from './Layout'
import { Dashboard } from './pages/Dashboard'
import { IncidentDetail, Incidents } from './pages/Incidents'
import { Login } from './pages/Login'
import { Audit, Diagnostics, Logs, Metrics, Notifications, Remediation, Settings } from './pages/More'
import { ServiceDetail } from './pages/ServiceDetail'
import { Services } from './pages/Services'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1 } } })

function Guard({ children }: { children: React.ReactNode }) {
  const { session, checked } = useAuth()
  const loc = useLocation()
  if (!checked) return <div className="flex min-h-screen items-center justify-center text-sm text-mut">Checking your session…</div>
  if (!session) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  return <>{children}</>
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<Guard><Layout /></Guard>}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/services" element={<Services />} />
              <Route path="/services/:id" element={<ServiceDetail />} />
              <Route path="/incidents" element={<Incidents />} />
              <Route path="/incidents/:id" element={<IncidentDetail />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/diagnostics" element={<Diagnostics />} />
              <Route path="/remediation" element={<Remediation />} />
              <Route path="/metrics" element={<Metrics />} />
              <Route path="/notifications" element={<Notifications />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/settings" element={<Settings />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
