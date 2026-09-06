import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useCanAct } from '../auth'
import { Card, EmptyState, SeverityBadge, Spinner, Stat, StatusBadge, clock, dayTime, fmtSecs } from '../components'
import type { Incident } from '../types'

export function Incidents() {
  const { data } = useQuery({ queryKey: ['incidents'], queryFn: () => api.incidents('?limit=50'), refetchInterval: 5000 })
  return (
    <div>
      <h1 className="page-h">Incidents</h1>
      <p className="page-sub">Every failure AeroOps has handled — newest first. Green RESOLVED means it fixed itself.</p>
      <Card>
        {(data ?? []).length === 0 ? (
          <EmptyState what="incidents" hint="Simulate a failure on any service to watch one appear here." />
        ) : (
          <table className="tbl">
            <thead><tr><th>ID</th><th>Service</th><th>Severity</th><th>Status</th><th>Detected</th><th>Recovery</th><th /></tr></thead>
            <tbody>
              {(data ?? []).map((i: Incident) => (
                <tr key={i.id}>
                  <td className="font-mono">#{i.id}</td>
                  <td>service {i.service_id}</td>
                  <td><SeverityBadge value={i.severity} /></td>
                  <td><StatusBadge value={i.status} /></td>
                  <td className="text-xs text-mut">{dayTime(i.detected_at)}</td>
                  <td className={i.recovery_verified ? 'text-[#15803D]' : 'text-mut'}>{i.recovery_verified ? fmtSecs(i.duration_sec) : '—'}</td>
                  <td className="text-right"><Link className="text-xs text-brand hover:underline" to={`/incidents/${i.id}`}>timeline</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

export function IncidentDetail() {
  const { id } = useParams()
  const iid = Number(id)
  const qc = useQueryClient()
  const canAct = useCanAct()
  const { data } = useQuery({ queryKey: ['incident', iid], queryFn: () => api.incident(iid), refetchInterval: 3000 })
  const { data: timeline } = useQuery({ queryKey: ['timeline', iid], queryFn: () => api.timeline(iid), refetchInterval: 3000 })
  if (!data) return <div className="page-sub">Loading incident… <Spinner /></div>
  const d = data as Record<string, unknown>
  const diags = (d.diagnoses ?? []) as Record<string, unknown>[]
  const actions = (d.actions ?? []) as Record<string, unknown>[]

  return (
    <div>
      <Link to="/incidents" className="text-sm text-brand hover:underline">← all incidents</Link>
      <div className="mb-1 mt-1 flex flex-wrap items-center gap-3">
        <h1 className="page-h !mb-0">Incident #{String(d.id)}</h1>
        <StatusBadge value={String(d.status)} pulse={String(d.status) === 'RECOVERING'} />
        <SeverityBadge value={String(d.severity)} />
        {canAct && (
        <button className="btn-ghost !px-3 !py-1.5" onClick={async () => { await api.acknowledge(iid); qc.invalidateQueries({ queryKey: ['incident', iid] }) }}>
          Mark seen
        </button>
        )}
      </div>
      <p className="page-sub">Detected {dayTime(d.detected_at)}{d.resolved_at ? ` · closed ${dayTime(d.resolved_at)}` : ' · still open'}</p>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Recovery time" value={d.recovery_verified ? fmtSecs(d.duration_sec) : '—'} sub={d.recovery_verified ? 'verified healthy' : 'not yet'} />
        <Stat label="Restart tries" value={String(d.restart_attempts)} />
        <Stat label="Exit code" value={<span className="font-mono">{String(d.exit_code ?? '—')}</span>} />
        <Stat label="Verified" value={d.recovery_verified ? <span className="text-[#15803D]">YES</span> : 'no'} />
      </div>
      <Card title="What broke">
        <div className="font-mono text-[13px] text-[#B91C1C]">{String(d.error_message)}</div>
        {d.failure_reason ? <div className="mt-1 text-xs text-mut">{String(d.failure_reason).slice(0, 300)}</div> : null}
      </Card>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="How it unfolded">
          <ol className="relative ml-2 space-y-3 border-l border-line pl-5">
            {(timeline ?? []).map((e, n) => (
              <li key={n} className="relative text-sm">
                <span className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full border-2 border-panel bg-blue-400" />
                <div className="text-[11px] font-semibold uppercase tracking-wide text-brand">{e.type.replaceAll('_', ' ')}</div>
                <div>{e.message}</div>
                <div className="font-mono text-[11px] text-mut">{clock(e.t)}</div>
              </li>
            ))}
            {(timeline ?? []).length === 0 && <EmptyState what="timeline events" />}
          </ol>
        </Card>
        <div className="space-y-4">
          <Card title="Diagnosis">
            {diags.length === 0 ? <EmptyState what="diagnoses yet" /> : diags.map((g) => (
              <div key={String(g.id)} className="border-t border-line/70 py-2.5 text-sm first:border-0">
                <div><b>{String(g.root_cause)}</b></div>
                <div className="mt-0.5 text-[13px] text-mut">{String(g.explanation)}</div>
                <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                  <span className="badge">{String(g.source)}{g.model ? ` · ${String(g.model)}` : ''}</span>
                  <span className="badge">confidence {Number(g.confidence).toFixed(2)}</span>
                  <span className="badge">risk {String(g.risk_level)}</span>
                </div>
                <div className="mt-1 text-[13px]">Next step: <code className="text-brand">{String(g.recommended_action)}</code></div>
              </div>
            ))}
          </Card>
          <Card title="Fixes attempted">
            {actions.length === 0 ? <EmptyState what="actions yet" /> : actions.map((a) => (
              <div key={String(a.id)} className="border-t border-line/70 py-2 text-sm first:border-0">
                <b>{String(a.type)}</b> <span className="text-xs text-mut">({String(a.source)})</span>{' '}
                <StatusBadge value={String(a.status).toUpperCase()} />
                <div className="text-mut">{String(a.result || a.error || '')}</div>
              </div>
            ))}
            {canAct && (
            <button className="btn mt-2" onClick={async () => { await api.remediate(iid, 'restart_service'); qc.invalidateQueries({ queryKey: ['incident', iid] }) }}>
              Restart again (manual)
            </button>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
