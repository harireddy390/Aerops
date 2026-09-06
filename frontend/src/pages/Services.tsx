import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useCanAct } from '../auth'
import { Card, EmptyState, StatusBadge } from '../components'
import type { Service } from '../types'

export function Services() {
  const qc = useQueryClient()
  const canAct = useCanAct()
  const { data } = useQuery({ queryKey: ['services'], queryFn: api.services, refetchInterval: 5000 })
  const [form, setForm] = useState({ name: '', command: '', health_check_type: 'process', health_check_url: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const create = async () => {
    if (!form.name.trim()) { setMsg('Give the service a name first.'); return }
    setBusy(true)
    try {
      await api.createService({ ...form, working_directory: '.', health_check_interval: 5 })
      setMsg(`“${form.name}” registered and being watched.`)
      setForm({ name: '', command: '', health_check_type: 'process', health_check_url: '' })
      qc.invalidateQueries({ queryKey: ['services'] })
    } catch (e) { setMsg(String((e as Error).message)) } finally { setBusy(false) }
  }
  const act = async (id: number, a: 'start' | 'stop' | 'restart', label: string) => {
    const r = await api.serviceAction(id, a) as Record<string, unknown>
    setMsg(`${label}: ${JSON.stringify(r)}`)
    qc.invalidateQueries({ queryKey: ['services'] })
  }

  return (
    <div>
      <h1 className="page-h">Services</h1>
      <p className="page-sub">Every app AeroOps is keeping alive. Green means healthy — anything else is being handled or needs you.</p>
      {!canAct && <p className="page-sub">You’re signed in as a viewer — watching only. An admin can promote you to act.</p>}
      {canAct && (
      <Card title="Register a service">
        <div className="grid gap-2 md:grid-cols-2">
          <input className="input" placeholder="Name — e.g. billing-api" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="input" placeholder="Command — e.g. python -m http.server 4101" value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} />
          <select className="input" value={form.health_check_type} onChange={(e) => setForm({ ...form, health_check_type: e.target.value })}>
            <option value="process">Check: process running</option>
            <option value="http">Check: HTTP endpoint</option>
          </select>
          <input className="input" placeholder="Health URL — e.g. http://localhost:4101 (HTTP check only)" value={form.health_check_url} onChange={(e) => setForm({ ...form, health_check_url: e.target.value })} />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <button className="btn" disabled={busy} onClick={create}>{busy ? 'Registering…' : 'Start watching'}</button>
          {msg && <span className="text-xs text-mut">{msg}</span>}
        </div>
      </Card>
      )}
      <div className="mt-4">
        <Card title={`Watched services (${(data ?? []).length})`}>
          {(data ?? []).length === 0 ? (
            <EmptyState what="services" hint="Register your first one above." />
          ) : (
            <table className="tbl">
              <thead><tr><th>Name</th><th>Status</th><th>PID</th><th>Check</th><th>Restarts</th>{canAct && <th className="text-right">Actions</th>}</tr></thead>
              <tbody>
                {(data ?? []).map((sv: Service) => (
                  <tr key={sv.id}>
                    <td><Link className="font-medium text-brand hover:underline" to={`/services/${sv.id}`}>{sv.name}</Link>
                      <div className="text-xs text-mut">{sv.status === 'STOPPED' ? 'Stopped by you — press Start to resume watching' : (sv.description || sv.type)}</div></td>
                    <td><StatusBadge value={sv.status} pulse={sv.status === 'RECOVERING' || sv.status === 'RESTARTING'} /></td>
                    <td className="font-mono text-xs">{sv.pid ?? '—'}</td>
                    <td className="max-w-52 truncate text-xs text-mut" title={sv.health_check_url}>{sv.health_check_url || sv.health_check_type}</td>
                    <td>{sv.restart_count}</td>
                    {canAct && (
                    <td>
                      <div className="flex justify-end gap-1.5">
                        <button className="btn-ghost !px-3 !py-1.5" onClick={() => act(sv.id, 'start', 'Started')}>Start</button>
                        <button className="btn-ghost !px-3 !py-1.5" onClick={() => act(sv.id, 'stop', 'Stopped')}>Stop</button>
                        <button className="btn-ghost !px-3 !py-1.5" onClick={() => act(sv.id, 'restart', 'Restarted')}>Restart</button>
                      </div>
                    </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  )
}
