import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Cpu,
  MemoryStick,
  MoreHorizontal,
  Server,
  Siren,
  Timer,
  XCircle,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import { RANGE_MS, useRange } from '../Layout'
import {
  Card,
  EmptyState,
  Kpi,
  SeverityBadge,
  SkeletonCards,
  SkeletonRows,
  StatusBadge,
  clock,
  dayTime,
  fmtSecs,
} from '../components'
import type { Incident, Service, TimelineEvent } from '../types'

type FleetRow = { id: number; name: string; cpu: number; mem: number; resp: number | null; checkedAt?: string; uptimePct: number | null }

const GRID = '#E2E8F0'
const TICK = { fontSize: 11, fill: '#64748B' }
const TIP = { background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 8, fontSize: 12, color: '#0F172A' }

const PIPE_STEPS = ['Detected', 'Diagnosing', 'Remediating', 'Restarting', 'Health Check', 'Recovered', 'Resolved']

function pipeIndex(inc: Incident, events: TimelineEvent[]): number {
  const kinds = new Set(events.map((e) => e.type))
  if (inc.status === 'RESOLVED') return 6
  if (inc.status === 'FAILED') return -1
  let i = { OPEN: 0, ACKNOWLEDGED: 0, INVESTIGATING: 1, DIAGNOSED: 1, REMEDIATING: 2, RECOVERING: 4 }[inc.status] ?? 0
  if (kinds.has('REMEDIATION_EXECUTED')) i = Math.max(i, 3)
  if (kinds.has('RECOVERING')) i = Math.max(i, 4)
  return i
}

function inRange(iso: string, rangeMs: number): boolean {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return true
  return Date.now() - t <= rangeMs
}

function eventTone(type: string): string {
  if (/RESOLVED|RECOVERED|SUCCEEDED|CREATED|STARTED/i.test(type)) return 'bg-[#F0FDF4] text-[#16A34A]'
  if (/CRASH|FAIL|ERROR/i.test(type)) return 'bg-[#FEF2F2] text-[#DC2626]'
  if (/WARN|DIAGNOS|INVESTIGAT|RESTART|REMEDIAT|RECOVER/i.test(type)) return 'bg-[#FFFBEB] text-[#B45309]'
  return 'bg-[#EFF6FF] text-[#2563EB]'
}

export function Dashboard() {
  const range = useRange()
  const rangeMs = RANGE_MS[range]
  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary, refetchInterval: 5000 })
  const services = useQuery({ queryKey: ['services'], queryFn: api.services, refetchInterval: 5000 })
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: () => api.incidents('?limit=12'), refetchInterval: 5000 })
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.audit, refetchInterval: 5000 })
  const sys = useQuery({ queryKey: ['syshealth'], queryFn: api.systemHealth, refetchInterval: 15000 })
  const fleet = useQuery({
    queryKey: ['fleet-metrics'],
    queryFn: async (): Promise<FleetRow[]> => {
      const svcs = await api.services()
      return Promise.all(svcs.map(async (s) => {
        try {
          const m = await api.metrics(s.id)
          const day = m.filter((p) => inRange(p.t, 24 * 3600e3))
          const healthy = day.filter((p) => ['HEALTHY', 'RECOVERED'].includes(p.status)).length
          const last = m[m.length - 1]
          return {
            id: s.id, name: s.name,
            cpu: last?.cpu ?? 0, mem: last?.mem_mb ?? 0,
            resp: last?.response_ms ?? null, checkedAt: last?.t,
            uptimePct: day.length ? Math.round((healthy / day.length) * 100) : null,
          }
        } catch {
          return { id: s.id, name: s.name, cpu: 0, mem: 0, resp: null, uptimePct: null }
        }
      }))
    },
    refetchInterval: 10000,
  })
  const history = useQuery({
    queryKey: ['fleet-history'],
    queryFn: async () => {
      const svcs = await api.services()
      const all = await Promise.all(svcs.map(async (s) => {
        try {
          return (await api.metrics(s.id)).slice(-24)
        } catch {
          return []
        }
      }))
      const n = Math.max(0, ...all.map((a) => a.length))
      const pts: { i: number; healthyPct: number; cpu: number; mem: number; resp: number | null }[] = []
      for (let i = 0; i < n; i++) {
        let ok = 0, total = 0, cpu = 0, mem = 0, resp = 0, respN = 0
        for (const a of all) {
          const p = a[a.length - n + i]
          if (!p) continue
          total++
          if (['HEALTHY', 'RECOVERED'].includes(p.status)) ok++
          cpu += p.cpu
          mem += p.mem_mb
          if (p.response_ms != null) { resp += p.response_ms; respN++ }
        }
        if (total) pts.push({ i, healthyPct: Math.round((ok / total) * 100), cpu: +(cpu / total).toFixed(1), mem: +(mem / total).toFixed(1), resp: respN ? +(resp / respN).toFixed(0) : null })
      }
      return pts
    },
    refetchInterval: 15000,
  })

  if (summary.isPending || services.isPending) {
    return (
      <div>
        <SkeletonCards n={5} />
        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <div className="card xl:col-span-2"><SkeletonRows n={5} /></div>
          <div className="card"><SkeletonRows n={5} /></div>
        </div>
      </div>
    )
  }
  if (summary.isError || services.isError) {
    return (
      <div className="card border-[#FECACA]">
        <b className="text-ink">No data available — backend unreachable.</b>
        <div className="mt-1 text-[13px] text-mut">Start it with <code>cd backend; python -m uvicorn app.main:app --port 8000</code>. This page fills in on its own.</div>
      </div>
    )
  }

  const s = (summary.data ?? {}) as Record<string, unknown>
  const byStatus = (s.by_status ?? {}) as Record<string, number>
  const total = Number(s.total ?? 0)
  const healthy = byStatus.HEALTHY ?? 0
  const degraded = (byStatus.WARNING ?? 0) + (byStatus.DEGRADED ?? 0)
  const down = (byStatus.CRASHED ?? 0) + (byStatus.UNHEALTHY ?? 0)
  const openCount = Number(s.open_incidents ?? 0)
  const score = total ? Math.round((healthy / total) * 100) : 0
  const open = (incidents.data ?? []).filter((i) => !['RESOLVED', 'FAILED'].includes(i.status))
  const activeIncident = open[0] ?? (incidents.data ?? [])[0] ?? null
  const activity = ((audit.data ?? []) as Record<string, string>[]).filter((a) => inRange(a.t, rangeMs)).slice(0, 10)
  const comps = (sys.data as Record<string, unknown> | undefined)?.components as Record<string, unknown> | undefined
  const donut = [
    { k: 'Healthy', v: healthy, fill: '#16A34A' },
    { k: 'Degraded', v: degraded, fill: '#F59E0B' },
    { k: 'Down', v: down, fill: '#DC2626' },
    { k: 'Other', v: Math.max(0, total - healthy - degraded - down), fill: '#94A3B8' },
  ].filter((d) => d.v > 0)
  const topCpu = [...(fleet.data ?? [])].sort((a, b) => b.cpu - a.cpu).slice(0, 3)
  const topMem = [...(fleet.data ?? [])].sort((a, b) => b.mem - a.mem).slice(0, 3)
  const envGroups = (() => {
    const g: Record<string, { total: number; bad: number }> = {}
    for (const sv of services.data ?? []) {
      const k = sv.type === 'http' ? 'HTTP checks' : 'Local processes'
      g[k] ??= { total: 0, bad: 0 }
      g[k].total++
      if (['CRASHED', 'UNHEALTHY'].includes(sv.status)) g[k].bad++
    }
    return Object.entries(g)
  })()
  const respAvg = (() => {
    const vals = (fleet.data ?? []).map((r) => r.resp).filter((v): v is number => v != null)
    return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null
  })()

  return (
    <div>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi label="Total Services" value={total} sub={`${(services.data ?? []).length} watched`} tone="info" icon={<Server size={18} />} />
        <Kpi label="Healthy" value={healthy} sub={total ? `${score}% of fleet` : 'No data available'} tone="good" icon={<CheckCircle2 size={18} />} />
        <Kpi label="Degraded" value={degraded} sub={degraded ? 'needs attention' : 'none right now'} tone="warn" icon={<AlertTriangle size={18} />} />
        <Kpi label="Down" value={down} sub={down ? 'needs attention' : 'all clear'} tone="bad" icon={<XCircle size={18} />} />
        <Kpi label="Incidents" value={openCount} sub="currently open" tone="bad" icon={<Siren size={18} />} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Card title="Services Overview" sub="Live state of everything under watch" action={<Link className="link text-xs" to="/services">Manage</Link>}>
            {(services.data ?? []).length === 0 ? <EmptyState /> : (
              <table className="tbl">
                <thead><tr><th>Service Name</th><th>Status</th><th>Uptime</th><th>Response Time</th><th>Last Check</th><th /></tr></thead>
                <tbody>
                  {(services.data ?? []).map((sv: Service) => {
                    const f = (fleet.data ?? []).find((r) => r.id === sv.id)
                    return (
                      <tr key={sv.id}>
                        <td>
                          <span className="flex items-center gap-2 font-medium text-ink">
                            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-soft text-mut"><Server size={14} /></span>
                            <Link className="hover:text-brand hover:underline" to={`/services/${sv.id}`}>{sv.name}</Link>
                          </span>
                        </td>
                        <td><StatusBadge value={sv.status} /></td>
                        <td className="font-mono text-xs">{f?.uptimePct != null ? `${f.uptimePct}%` : '—'}</td>
                        <td className="font-mono text-xs">{f?.resp != null ? `${Math.round(f.resp)}ms` : '—'}</td>
                        <td className="text-xs text-mut" title={f?.checkedAt ?? ''}>{f?.checkedAt ? clock(f.checkedAt) : '—'}</td>
                        <td className="text-right"><RowMenu id={sv.id} /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </Card>
        </div>
        <Card title="Service Status Distribution" sub="Current fleet mix">
          {total === 0 ? <EmptyState /> : (
            <div className="flex items-center gap-4">
              <div className="relative h-40 w-40 shrink-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={donut} dataKey="v" nameKey="k" innerRadius={52} outerRadius={72} strokeWidth={2} stroke="#fff">
                      {donut.map((d, n) => <Cell key={n} fill={d.fill} />)}
                    </Pie>
                    <Tooltip contentStyle={TIP} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-bold text-ink">{total}</span>
                  <span className="text-[11px] text-mut">services</span>
                </div>
              </div>
              <ul className="min-w-0 flex-1 space-y-1.5 text-[13px]">
                {donut.map((d) => (
                  <li key={d.k} className="flex items-center gap-2" title={`${d.k}: ${d.v} (${Math.round((d.v / total) * 100)}%)`}>
                    <span className="dot" style={{ background: d.fill }} />
                    <span className="flex-1 text-secondary">{d.k}</span>
                    <b className="text-ink">{d.v}</b>
                    <span className="w-10 text-right text-xs text-mut">{Math.round((d.v / total) * 100)}%</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card title="System Health Score" sub="% of services currently healthy">
          <div className="flex items-end gap-2">
            <span className="text-3xl font-bold tracking-tight text-ink">{total ? score : '—'}</span>
            {total > 0 && <span className="pb-1 text-sm text-mut">/ 100</span>}
          </div>
          {(history.data ?? []).length > 1 ? (
            <ResponsiveContainer width="100%" height={90}>
              <AreaChart data={history.data} margin={{ top: 8, right: 0, bottom: 0, left: -18 }}>
                <XAxis dataKey="i" hide />
                <YAxis domain={[0, 100]} tick={TICK} width={30} />
                <Tooltip contentStyle={TIP} />
                <Area type="monotone" dataKey="healthyPct" name="healthy %" stroke="#2563EB" fill="#EFF6FF" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : <div className="mt-2 text-xs text-mut">Collecting history…</div>}
        </Card>
        <Card title="Active Incidents" sub={open.length ? `${open.length} need attention` : 'All clear'}>
          {open.length === 0 ? <EmptyState hint="New failures will appear here instantly." /> : open.slice(0, 4).map((i: Incident) => (
            <Link key={i.id} to={`/incidents/${i.id}`} className="mb-2 flex items-start gap-2.5 rounded-lg border border-line p-2.5 transition last:mb-0 hover:border-slate-300 hover:bg-soft" title={`Incident #${i.id}: ${i.error_message}`}>
              <span className={`mt-1 h-8 w-1 shrink-0 rounded ${i.severity === 'critical' ? 'bg-[#DC2626]' : i.severity === 'warning' ? 'bg-[#F59E0B]' : 'bg-[#2563EB]'}`} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-ink">{i.error_message.slice(0, 80)}</span>
                <span className="mt-0.5 block text-xs text-mut">Started {dayTime(i.detected_at)} · #{i.id}</span>
              </span>
              <SeverityBadge value={i.severity} />
            </Link>
          ))}
        </Card>
        <Card title="Recent Activity" sub={`Last ${range === '15m' ? '15 minutes' : range === '1h' ? 'hour' : '24 hours'}`}>
          <div className="scroll-thin max-h-64 space-y-2.5 overflow-auto">
            {activity.length === 0 && <EmptyState />}
            {activity.map((a, n) => (
              <div key={n} className="flex gap-2.5 text-[13px]" title={`${a.event} · ${a.result}`}>
                <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${eventTone(a.event)}`}>
                  <ActivityDot event={a.event} />
                </span>
                <span className="min-w-0"><b className="font-medium text-ink">{prettyEvent(a.event)}</b><span className="block truncate text-xs text-mut">{a.result}</span></span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-faint">{clock(a.t)}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Resource Utilization" sub="Fleet averages + host">
          <ResRow label="CPU Usage" value={comps ? `${comps.cpu_pct}%` : '—'} pct={Number(comps?.cpu_pct ?? 0)} color="#2563EB" data={(history.data ?? []).map((p) => p.cpu)} />
          <ResRow label="Memory Usage" value={comps ? `${comps.mem_pct}%` : '—'} pct={Number(comps?.mem_pct ?? 0)} color="#16A34A" data={(history.data ?? []).map((p) => p.mem)} />
          <ResRow label="Avg Response" value={respAvg != null ? `${respAvg}ms` : '—'} pct={respAvg != null ? Math.min(100, respAvg / 10) : 0} color="#F59E0B" data={(history.data ?? []).map((p) => p.resp ?? 0)} />
        </Card>
        <Card title="Services by Environment" sub="Where the fleet runs">
          {envGroups.length === 0 ? <EmptyState /> : envGroups.map(([k, g]) => (
            <div key={k} className="mb-3 last:mb-0" title={`${k}: ${g.total} services, ${g.bad} with problems`}>
              <div className="mb-1 flex justify-between text-[13px]"><span className="font-medium text-ink">{k}</span><span className="text-xs text-mut">{g.total} services</span></div>
              <div className="flex h-2 overflow-hidden rounded bg-slate-100">
                <div className="bg-[#16A34A]" style={{ width: `${(100 * (g.total - g.bad)) / g.total}%` }} />
                <div className="bg-[#DC2626]" style={{ width: `${(100 * g.bad) / g.total}%` }} />
              </div>
              <div className="mt-1 text-xs text-mut">{g.bad === 0 ? 'All healthy' : `${g.bad} with problems`}</div>
            </div>
          ))}
          <p className="mt-2 text-[11px] text-faint">Grouped by check type — no region data is tracked.</p>
        </Card>
        <Card title="Self-Healing Pipeline" sub="Latest incident, live">
          <Pipeline incident={activeIncident} />
        </Card>

        <div className="xl:col-span-2">
          <Card title="Fleet Response Time" sub="Average check latency across services">
            {(history.data ?? []).length > 1 ? (
              <ResponsiveContainer width="100%" height={170}>
                <BarChart data={history.data} margin={{ top: 4 }}>
                  <XAxis dataKey="i" tick={TICK} />
                  <YAxis tick={TICK} width={44} />
                  <Tooltip contentStyle={TIP} />
                  <Bar dataKey="resp" name="avg ms" fill="#2563EB" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <EmptyState hint="Latency history builds as checks run." />}
          </Card>
        </div>
        <Card title="Top Services by CPU" sub="Latest sample">
          <TopList rows={(fleet.data ?? []).map((r) => ({ id: r.id, name: r.name, v: r.cpu }))} color="#2563EB" unit="%" />
        </Card>
        <Card title="Top Services by Memory" sub="Latest sample">
          <TopList rows={(fleet.data ?? []).map((r) => ({ id: r.id, name: r.name, v: r.mem }))} color="#16A34A" unit=" MB" />
        </Card>
      </div>
    </div>
  )
}

function RowMenu({ id }: { id: number }) {
  const [open, setOpen] = useState(false)
  return (
    <span className="relative">
      <button className="rounded p-1 text-mut hover:bg-soft hover:text-ink" title="Service actions" onClick={() => setOpen((v) => !v)}><MoreHorizontal size={15} /></button>
      {open && (
        <>
          <span className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <span className="absolute right-0 z-20 flex w-32 flex-col rounded-lg border border-line bg-white py-1 shadow-pop">
            <MenuLink to={`/services/${id}`} label="Open" close={() => setOpen(false)} />
            <MenuLink to={`/services/${id}`} label="Start / Stop" close={() => setOpen(false)} />
            <MenuLink to="/incidents" label="Incidents" close={() => setOpen(false)} />
          </span>
        </>
      )}
    </span>
  )
}

function MenuLink({ to, label, close }: { to: string; label: string; close: () => void }) {
  return <Link to={to} onClick={close} className="px-3 py-1.5 text-left text-[13px] text-secondary hover:bg-soft">{label}</Link>
}

function TopList({ rows, color, unit }: { rows: { id: number; name: string; v: number }[]; color: string; unit: string }) {
  const top = [...rows].sort((a, b) => b.v - a.v).slice(0, 3)
  const max = Math.max(1, ...top.map((r) => r.v))
  if (!rows.length) return <EmptyState />
  return (
    <div>
      {top.map((r) => (
        <div key={r.id} className="mb-2.5 last:mb-0" title={`${r.name}: ${r.v}${unit}`}>
          <div className="mb-1 flex justify-between text-xs"><span className="truncate text-secondary">{r.name}</span><span className="font-mono text-mut">{r.v}{unit}</span></div>
          <div className="h-1.5 overflow-hidden rounded bg-slate-100"><div className="h-full rounded" style={{ width: `${Math.min(100, (r.v / max) * 100)}%`, background: color }} /></div>
        </div>
      ))}
    </div>
  )
}

function ResRow({ label, value, pct, color, data }: { label: string; value: string; pct: number; color: string; data: number[] }) {
  return (
    <div className="mb-3 last:mb-0" title={`${label}: ${value}`}>
      <div className="mb-1 flex items-center justify-between text-[13px]">
        <span className="flex items-center gap-1.5 text-secondary">{label === 'CPU Usage' ? <Cpu size={14} className="text-mut" /> : label === 'Memory Usage' ? <MemoryStick size={14} className="text-mut" /> : <Timer size={14} className="text-mut" />}{label}</span>
        <b className="text-ink">{value}</b>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-slate-100"><div className="h-full rounded" style={{ width: `${Math.min(100, pct)}%`, background: color }} /></div>
      {data.length > 1 && (
        <ResponsiveContainer width="100%" height={34}>
          <AreaChart data={data.map((v, i) => ({ i, v }))} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
            <Area type="monotone" dataKey="v" stroke={color} fill={color} fillOpacity={0.15} strokeWidth={1.5} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function Pipeline({ incident }: { incident: Incident | null }) {
  const { data: events } = useQuery({
    queryKey: ['timeline', incident?.id],
    queryFn: () => api.timeline(incident!.id),
    enabled: incident != null,
    refetchInterval: 5000,
  })
  if (!incident) return <EmptyState hint="Trigger a failure to watch the pipeline run." />
  const idx = pipeIndex(incident, events ?? [])
  const failed = idx === -1
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-[13px]">
        <span className="font-mono text-mut">#{incident.id}</span>
        <StatusBadge value={incident.status} />
      </div>
      <ol>
        {PIPE_STEPS.map((step, n) => {
          const done = !failed && (n < idx || incident.status === 'RESOLVED')
          const current = !failed && n === idx && incident.status !== 'RESOLVED'
          return (
            <li key={step} className="relative flex gap-2.5 pb-3.5 last:pb-0">
              {n < PIPE_STEPS.length - 1 && <span className={`absolute left-[6px] top-4 h-full w-px ${done ? 'bg-[#BBF7D0]' : 'bg-line'}`} />}
              <span className={`z-10 mt-0.5 flex h-[13px] w-[13px] shrink-0 items-center justify-center rounded-full border-2 border-white shadow ${done ? 'bg-[#16A34A]' : current ? 'bg-[#2563EB]' : failed ? 'bg-slate-300' : 'bg-slate-200'}`} title={done ? 'done' : current ? 'in progress' : 'pending'} />
              <span className={`text-[13px] ${current ? 'font-semibold text-[#1D4ED8]' : done ? 'text-ink' : 'text-mut'}`}>{step}</span>
            </li>
          )
        })}
      </ol>
      {failed && <p className="mt-1 text-xs text-[#DC2626]">Stopped — restart budget exhausted, needs an operator.</p>}
      <Link className="link mt-2 inline-flex items-center gap-1 text-xs" to={`/incidents/${incident.id}`}>
        Full timeline <ArrowRight size={12} />
      </Link>
    </div>
  )
}

function ActivityDot({ event }: { event: string }) {
  const cls = eventTone(event)
  if (/RESOLVED|RECOVERED|SUCCEEDED/i.test(event)) return <CheckCircle2 size={13} className={cls + ' rounded-full'} />
  return <span className={`dot ${cls.includes('green') || cls.includes('16A34A') ? 'bg-[#16A34A]' : cls.includes('red') || cls.includes('DC2626') ? 'bg-[#DC2626]' : cls.includes('amber') || cls.includes('F59E0B') ? 'bg-[#F59E0B]' : 'bg-[#2563EB]'}`} />
}

function prettyEvent(e: string): string {
  return e.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())
}
