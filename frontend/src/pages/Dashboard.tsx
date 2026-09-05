import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { Card, EmptyState, SeverityBadge, Spinner, Stat, StatusBadge, clock, fmtSecs } from '../components'
import type { Incident, Service } from '../types'

const BAR_COLORS = ['#34d399', '#fbbf24', '#f87171', '#60a5fa', '#a78bfa', '#94a3b8']

export function Dashboard() {
  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary, refetchInterval: 5000 })
  const services = useQuery({ queryKey: ['services'], queryFn: api.services, refetchInterval: 5000 })
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: () => api.incidents('?limit=8'), refetchInterval: 5000 })
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.audit, refetchInterval: 5000 })

  if (summary.isPending || services.isPending) {
    return (
      <div>
        <h1 className="page-h">Dashboard</h1>
        <p className="page-sub">Connecting to AeroOps backend… <Spinner /></p>
      </div>
    )
  }
  if (summary.isError || services.isError) {
    return (
      <div>
        <h1 className="page-h">Dashboard</h1>
        <div className="card border-red-500/40">
          <b>Backend unreachable.</b>
          <div className="mt-1 text-sm text-mut">Start it: <code>cd backend; python -m uvicorn app.main:app --port 8000</code>, then this page fills in automatically.</div>
        </div>
      </div>
    )
  }

  const s = (summary.data ?? {}) as Record<string, unknown>
  const byStatus = (s.by_status ?? {}) as Record<string, number>
  const down = (byStatus.CRASHED ?? 0) + (byStatus.UNHEALTHY ?? 0)

  return (
    <div>
      <h1 className="page-h">Good {dayPart()}, operator</h1>
      <p className="page-sub">Everything AeroOps is watching, in one glance. Updates live.</p>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Services" value={String(s.total ?? 0)} />
        <Stat label="Healthy" value={String(byStatus.HEALTHY ?? 0)} sub="steady state" />
        <Stat label="Down" value={<span className={down ? 'text-red-400' : ''}>{down}</span>} sub={down ? 'needs attention' : 'all clear'} />
        <Stat label="Open incidents" value={String(s.open_incidents ?? 0)} />
        <Stat label="Restarts" value={String(s.restarts ?? 0)} sub="auto-recoveries" />
        <Stat label="Avg recovery" value={fmtSecs(s.avg_recovery_sec)} sub="detect → healthy" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Service health" action={<Link className="text-xs text-indigo-400 hover:underline" to="/services">manage →</Link>}>
          {(services.data ?? []).length === 0 ? (
            <EmptyState what="services" hint="Register one on the Services page." />
          ) : (
            <table className="tbl">
              <thead><tr><th>Service</th><th>Status</th><th>Restarts</th><th /></tr></thead>
              <tbody>
                {(services.data ?? []).map((sv: Service) => (
                  <tr key={sv.id}>
                    <td className="font-medium">{sv.name}</td>
                    <td><StatusBadge value={sv.status} pulse={sv.status === 'RECOVERING' || sv.status === 'RESTARTING'} /></td>
                    <td>{sv.restart_count}</td>
                    <td className="text-right"><Link className="text-xs text-indigo-400 hover:underline" to={`/services/${sv.id}`}>open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Recent incidents" action={<Link className="text-xs text-indigo-400 hover:underline" to="/incidents">all →</Link>}>
          {(incidents.data ?? []).length === 0 ? (
            <EmptyState what="incidents" hint="Simulate a failure to watch the full lifecycle." />
          ) : (
            <table className="tbl">
              <thead><tr><th>ID</th><th>Severity</th><th>Status</th><th>Duration</th><th /></tr></thead>
              <tbody>
                {(incidents.data ?? []).map((i: Incident) => (
                  <tr key={i.id}>
                    <td className="font-mono">#{i.id}</td>
                    <td><SeverityBadge value={i.severity} /></td>
                    <td><StatusBadge value={i.status} /></td>
                    <td className="text-mut">{fmtSecs(i.duration_sec)}</td>
                    <td className="text-right"><Link className="text-xs text-indigo-400 hover:underline" to={`/incidents/${i.id}`}>open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Fleet status">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={Object.entries(byStatus).map(([k, v], n) => ({ k, v, fill: BAR_COLORS[n % BAR_COLORS.length] }))} margin={{ top: 4 }}>
              <XAxis dataKey="k" tick={{ fontSize: 10, fill: '#8b96b8' }} interval={0} angle={-12} dy={6} height={44} />
              <YAxis tick={{ fontSize: 10, fill: '#8b96b8' }} allowDecimals={false} width={28} />
              <Tooltip contentStyle={{ background: '#141b33', border: '1px solid #243055', borderRadius: 12, fontSize: 12 }} />
              <Bar dataKey="v" radius={[6, 6, 0, 0]}>
                {Object.entries(byStatus).map((_, n) => (
                  <Cell key={n} fill={BAR_COLORS[n % BAR_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Live activity">
          <div className="max-h-48 space-y-1.5 overflow-auto text-[13px]">
            {((audit.data ?? []) as Record<string, string>[]).slice(0, 15).map((a, n) => (
              <div key={n} className="flex gap-2">
                <span className="w-14 shrink-0 font-mono text-xs text-mut">{clock(a.t)}</span>
                <span><b className="font-semibold">{a.event}</b> <span className="text-mut">{a.result}</span></span>
              </div>
            ))}
            {(audit.data ?? []).length === 0 && <EmptyState what="activity" />}
          </div>
        </Card>
      </div>
    </div>
  )
}

function dayPart(): string {
  const h = new Date().getHours()
  return h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening'
}
