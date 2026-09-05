import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { useCanAct } from '../auth'
import { Card, ConfirmButton, EmptyState, Spinner, Stat, StatusBadge, dayTime } from '../components'
import type { Incident } from '../types'

export function ServiceDetail() {
  const { id } = useParams()
  const sid = Number(id)
  const qc = useQueryClient()
  const svc = useQuery({ queryKey: ['service', sid], queryFn: () => api.service(sid), refetchInterval: 3000 })
  const metrics = useQuery({ queryKey: ['metrics', sid], queryFn: () => api.metrics(sid), refetchInterval: 5000 })
  const incidents = useQuery({ queryKey: ['incidents', sid], queryFn: () => api.incidents(`?service_id=${sid}&limit=10`), refetchInterval: 5000 })
  const logs = useQuery({ queryKey: ['logs', sid], queryFn: () => api.logs(`?service_id=${sid}&limit=20`), refetchInterval: 5000 })
  const [msg, setMsg] = useStateMsg()
  const canAct = useCanAct()
  const d = svc.data as unknown as Record<string, unknown> | undefined

  const act = async (a: 'start' | 'stop' | 'restart') => {
    const r = await api.serviceAction(sid, a) as Record<string, unknown>
    setMsg(`${a}: pid ${String(r.pid ?? '—')}`)
    qc.invalidateQueries({ queryKey: ['service', sid] })
  }

  if (svc.isPending) return <div className="page-sub">Loading service… <Spinner /></div>
  if (!d) return <div className="card">Service not found. <Link className="text-indigo-400" to="/services">Back</Link></div>

  return (
    <div>
      <Link to="/services" className="text-sm text-indigo-400 hover:underline">← all services</Link>
      <div className="mb-1 mt-1 flex flex-wrap items-center gap-3">
        <h1 className="page-h !mb-0">{String(d.name)}</h1>
        <StatusBadge value={String(d.status)} pulse={String(d.status) === 'RECOVERING'} />
      </div>
      <p className="page-sub">{String(d.description || 'No description')} · watching via {String(d.health_check_type)}</p>
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Process" value={d.pid ? <span className="font-mono">{String(d.pid)}</span> : '—'} sub={d.pid ? 'running' : 'not running'} />
        <Stat label="Auto-restarts" value={String(d.restart_count)} />
        <Stat label="Policy" value={<span className="text-lg">{String(d.restart_policy)}</span>} sub={`max ${String(d.max_restart_attempts)} tries`} />
        <Stat label="Safety" value={<span className="text-lg">{d.auto_remediation ? 'Auto' : 'Manual'}</span>} sub={d.ai_diagnosis ? 'AI diagnosis on' : 'rules only'} />
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {canAct ? (
          <>
            <button className="btn" onClick={() => act('start')}>Start</button>
            <button className="btn-ghost" onClick={() => act('stop')}>Stop</button>
            <button className="btn-ghost" onClick={() => act('restart')}>Restart</button>
            <ConfirmButton danger label="Simulate failure" ask={`Crash ${String(d.name)} on purpose to watch AeroOps recover it?`} onConfirm={async () => { await api.simulateFailure(sid); setMsg('Crashed on purpose — watch it come back.') }} />
          </>
        ) : <span className="text-xs text-mut">Viewer role — watching only.</span>}
        {msg && <span className="text-xs text-mut">{msg}</span>}
      </div>
      <Card title="Resource usage">
        {(metrics.data ?? []).length === 0 ? (
          <EmptyState what="metrics yet" hint="They appear within seconds of the service running." />
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={(metrics.data ?? []).map((m, i) => ({ i, ...m }))} margin={{ top: 4 }}>
              <XAxis dataKey="i" tick={{ fontSize: 10, fill: '#8b96b8' }} />
              <YAxis tick={{ fontSize: 10, fill: '#8b96b8' }} width={40} />
              <Tooltip contentStyle={{ background: '#141b33', border: '1px solid #243055', borderRadius: 12, fontSize: 12 }} />
              <Line type="monotone" dataKey="cpu" name="CPU %" stroke="#818cf8" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="mem_mb" name="Memory MB" stroke="#34d399" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Recent incidents">
          {(incidents.data ?? []).length === 0 ? <EmptyState what="incidents" hint="A clean record. Simulate a failure to see the lifecycle." /> :
            (incidents.data ?? []).map((i: Incident) => (
              <div key={i.id} className="flex items-center gap-2 border-t border-line/70 py-2 text-sm first:border-0">
                <Link className="font-mono text-indigo-300 hover:underline" to={`/incidents/${i.id}`}>#{i.id}</Link>
                <StatusBadge value={i.status} />
                <span className="truncate text-mut">{i.error_message.slice(0, 70)}</span>
              </div>
            ))}
        </Card>
        <Card title="Recent logs">
          {(logs.data ?? []).length === 0 ? <EmptyState what="captured logs" /> :
            <div className="logbox">{(logs.data ?? []).slice(-8).map((l, n) => <div key={n}>{l.content.slice(-400)}</div>)}</div>}
        </Card>
      </div>
      <p className="mt-3 text-xs text-mut">Health endpoint: <code>{String((d.health_check_url as string) || 'process check')}</code> · last seen {dayTime(d.updated_at)}</p>
    </div>
  )
}

function useStateMsg(): [string, (s: string) => void] {
  return useState('')
}
