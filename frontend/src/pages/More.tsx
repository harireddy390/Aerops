import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { useAuth } from '../auth'
import { Card, EmptyState, clock } from '../components'

export function Logs() {
  const [q, setQ] = useState('')
  const [errOnly, setErrOnly] = useState(false)
  const { data } = useQuery({ queryKey: ['logs'], queryFn: () => api.logs('?limit=200'), refetchInterval: 5000 })
  const rows = (data ?? []).filter(
    (l) => (!q || l.content.toLowerCase().includes(q.toLowerCase())) && (!errOnly || /error|exception|fail|traceback|refused/i.test(l.content)),
  )
  return (
    <div>
      <h1 className="page-h">Logs</h1>
      <p className="page-sub">Captured service output, newest at the bottom. Errors glow red.</p>
      <div className="mb-3 flex gap-2">
        <input className="input" placeholder="Search logs — try “error” or “refused”…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-ghost shrink-0" onClick={() => setErrOnly(!errOnly)}>{errOnly ? 'Errors only ✓' : 'Errors only'}</button>
      </div>
      <div className="logbox">
        {rows.length === 0 ? <span className="text-mut">Nothing matches. Logs land here when services run or crash.</span> :
          rows.slice(-60).map((l, n) => (
            <div key={n} className={/error|exception|fail|traceback|refused/i.test(l.content) ? 'text-[#B91C1C]' : ''}>
              <span className="text-mut">{clock(l.t)} </span>{l.content.slice(-600)}
            </div>
          ))}
      </div>
    </div>
  )
}

export function Diagnostics() {
  const { data } = useQuery({ queryKey: ['diagnostics'], queryFn: api.diagnostics, refetchInterval: 5000 })
  const [text, setText] = useState('EADDRINUSE: address already in use')
  const [out, setOut] = useState<Record<string, unknown> | null>(null)
  return (
    <div>
      <h1 className="page-h">Diagnostics</h1>
      <p className="page-sub">Every root-cause call AeroOps has made — rules instantly, AI as backup.</p>
      <Card title="Try the rule engine yourself">
        <div className="flex gap-2">
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} />
          <button className="btn shrink-0" onClick={async () => setOut(await api.diagnoseText(text))}>Diagnose</button>
        </div>
        {out && <pre className="logbox mt-2 !text-blue-200">{JSON.stringify(out, null, 2)}</pre>}
      </Card>
      <div className="mt-4">
        <Card title={`History (${(data ?? []).length})`}>
          {(data ?? []).length === 0 ? <EmptyState what="diagnoses" /> : (
            <table className="tbl">
              <thead><tr><th>Incident</th><th>Root cause</th><th>Engine</th><th>Confidence</th><th>Risk</th><th>Advice</th></tr></thead>
              <tbody>{(data ?? []).map((d) => (
                <tr key={d.id}>
                  <td className="font-mono">#{d.incident_id}</td>
                  <td className="font-medium">{d.root_cause}</td>
                  <td className="text-xs text-mut">{d.source}{d.model ? ` · ${d.model}` : ''}</td>
                  <td>{d.confidence.toFixed(2)}</td>
                  <td>{d.risk}</td>
                  <td><code className="text-xs text-brand">{d.recommendation}</code></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  )
}

export function Remediation() {
  const { data } = useQuery({ queryKey: ['remediation'], queryFn: api.remediation, refetchInterval: 5000 })
  const srcColor = (s: string) => s === 'automation' ? 'text-[#15803D]' : s === 'operator' ? 'text-[#B45309]' : 'text-brand'
  return (
    <div>
      <h1 className="page-h">Fixes</h1>
      <p className="page-sub">Every automated or manual repair. <span className="text-[#15803D]">automation</span> = AeroOps itself · <span className="text-[#B45309]">operator</span> = you.</p>
      <Card>
        {(data ?? []).length === 0 ? <EmptyState what="fixes" /> : (
          <table className="tbl">
            <thead><tr><th>Incident</th><th>Fix</th><th>By</th><th>Result</th><th>Detail</th></tr></thead>
            <tbody>{(data ?? []).map((a, n) => (
              <tr key={n}>
                <td className="font-mono">#{String(a.incident_id)}</td>
                <td className="font-medium">{String(a.action)}</td>
                <td className={srcColor(String(a.source))}>{String(a.source)}</td>
                <td>{String(a.status)}</td>
                <td className="text-mut">{String(a.result || a.error || '')}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

export function Metrics() {
  const { data } = useQuery({ queryKey: ['summary'], queryFn: api.summary, refetchInterval: 5000 })
  const s = (data ?? {}) as Record<string, unknown>
  return (
    <div>
      <h1 className="page-h">Metrics</h1>
      <p className="page-sub">How well self-healing is performing overall.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="card"><div className="text-xs uppercase tracking-wider text-mut">Incidents closed</div><div className="stat-v">{String(s.resolved ?? '…')}</div></div>
        <div className="card"><div className="text-xs uppercase tracking-wider text-mut">Avg recovery</div><div className="stat-v">{s.avg_recovery_sec != null ? `${Number(s.avg_recovery_sec).toFixed(1)}s` : '…'}</div><div className="mt-1 text-xs text-mut">crash → healthy</div></div>
        <div className="card"><div className="text-xs uppercase tracking-wider text-mut">Total restarts</div><div className="stat-v">{String(s.restarts ?? '…')}</div></div>
      </div>
    </div>
  )
}

export function Notifications() {
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, refetchInterval: 5000 })
  return (
    <div>
      <h1 className="page-h">Notifications</h1>
      <p className="page-sub">Dashboard pings, emails and webhooks AeroOps has sent — with delivery proof.</p>
      <div className="space-y-2">
        {(data ?? []).length === 0 && <EmptyState what="notifications" />}
        {(data ?? []).map((n, i) => (
          <div key={i} className="card">
            <div className="flex items-center gap-2 text-sm">
              <b>{String(n.title)}</b>
              <span className="badge">{String(n.channel)}</span>
              <span className={`badge ${n.delivered ? '' : '!border-red-500/50'}`}>
                <span className={`dot ${n.delivered ? 'bg-emerald-400' : 'bg-red-400'}`} />{n.delivered ? 'sent' : 'failed'}
              </span>
            </div>
            <div className="mt-1 whitespace-pre-wrap text-xs text-mut">{String(n.body)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function Audit() {
  const { data } = useQuery({ queryKey: ['audit'], queryFn: api.audit, refetchInterval: 5000 })
  return (
    <div>
      <h1 className="page-h">Audit log</h1>
      <p className="page-sub">Proof of everything automatic: what happened, when, and what came of it.</p>
      <Card>
        {(data ?? []).length === 0 ? <EmptyState what="audit events" /> : (
          <table className="tbl">
            <thead><tr><th>Time</th><th>Event</th><th>Service</th><th>Incident</th><th>By</th><th>Detail</th><th>Result</th></tr></thead>
            <tbody>{(data ?? []).map((a, n) => (
              <tr key={n}>
                <td className="font-mono text-xs text-mut">{clock(String(a.t))}</td>
                <td className="font-medium">{String(a.event)}</td>
                <td>{String(a.service_id ?? '')}</td>
                <td>{a.incident_id ? `#${String(a.incident_id)}` : ''}</td>
                <td className="text-xs text-mut">{String(a.actor)}</td>
                <td className="max-w-64 truncate text-xs text-mut" title={String(a.action)}>{String(a.action)}</td>
                <td className="text-xs">{String(a.result)}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

export function Settings() {
  const { data } = useQuery({ queryKey: ['syshealth'], queryFn: api.systemHealth, refetchInterval: 10000 })
  const { session } = useAuth()
  const users = useQuery({ queryKey: ['users'], queryFn: api.users, enabled: session?.role === 'admin' })
  const [nu, setNu] = useState({ username: '', email: '', password: '', role: 'viewer' })
  const [umsg, setUmsg] = useState('')
  const [pw, setPw] = useState({ current: '', next: '' })
  const [pmsg, setPmsg] = useState('')
  const c = ((data ?? {}) as Record<string, unknown>).components as Record<string, unknown> | undefined
  const row = (k: string, v: unknown) => {
    const s = String(v ?? '—')
    const good = /up|configured|ok/i.test(s)
    const bad = /down|failed|unavailable/i.test(s)
    return (
      <div key={k} className="flex items-center justify-between border-t border-line/70 py-2 text-sm first:border-0">
        <span className="text-mut">{k}</span>
        <span className="badge"><span className={`dot ${good ? 'bg-emerald-400' : bad ? 'bg-red-400' : 'bg-slate-500'}`} />{s}</span>
      </div>
    )
  }
  return (
    <div>
      <h1 className="page-h">Settings & health</h1>
      <p className="page-sub">The platform watching itself.</p>
      <Card title="Component health">{c ? Object.entries(c).map(([k, v]) => row(k, v)) : <EmptyState what="health data" />}</Card>
      <div className="mt-4">
      <Card title="Configuration">
        <div className="text-[13px] leading-relaxed text-mut">
          Tune AeroOps with environment variables (see <code>.env.example</code>): <code>DATABASE_URL</code>, <code>OLLAMA_*</code>, <code>OPENAI_API_KEY</code>, <code>SMTP_*</code>, <code>MAX_RESTART_ATTEMPTS</code>, <code>AUTH_ENABLED</code>, <code>JWT_SECRET</code>. Secrets live in <code>backend/.env</code>, never in code.
        </div>
      </Card>
      <div className="mt-4">
        <Card title="Change my password">
          <div className="flex max-w-md flex-col gap-2">
            <input className="input" type="password" placeholder="Current password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
            <input className="input" type="password" placeholder="New password (8+ characters)" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
            <div>
              <button className="btn" onClick={async () => {
                try {
                  await api.changePassword(pw.current, pw.next)
                  setPmsg('Password changed. Use it next time you log in.')
                  setPw({ current: '', next: '' })
                } catch (e) { setPmsg(String((e as Error).message)) }
              }}>Update password</button>
              {pmsg && <span className="ml-3 text-xs text-mut">{pmsg}</span>}
            </div>
          </div>
        </Card>
      </div>
      {session?.role === 'admin' && (
        <div className="mt-4">
          <Card title="Team — operators">
            <div className="mb-3 flex flex-wrap gap-2">
              <input className="input !w-40" placeholder="username" value={nu.username} onChange={(e) => setNu({ ...nu, username: e.target.value })} />
              <input className="input !w-44" placeholder="gmail" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} />
              <input className="input !w-40" type="password" placeholder="password 8+" value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} />
              <select className="input !w-32" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value })}>
                <option value="viewer">viewer</option><option value="operator">operator</option><option value="admin">admin</option>
              </select>
              <button className="btn" onClick={async () => {
                try {
                  await api.createUser(nu.username.trim(), nu.email.trim(), nu.password, nu.role)
                  setUmsg(`“${nu.username}” added as ${nu.role}.`)
                  setNu({ username: '', email: '', password: '', role: 'viewer' })
                  users.refetch()
                } catch (e) { setUmsg(String((e as Error).message)) }
              }}>Add user</button>
              {umsg && <span className="w-full text-xs text-mut">{umsg}</span>}
            </div>
            <table className="tbl">
              <thead><tr><th>Username</th><th>Role</th><th>Joined</th></tr></thead>
              <tbody>{(users.data ?? []).map((u, n) => (
                <tr key={n}><td className="font-medium">{String(u.username)}</td><td className="capitalize">{String(u.role)}</td><td className="text-xs text-mut">{String(u.created_at).slice(0, 10)}</td></tr>
              ))}</tbody>
            </table>
          </Card>
        </div>
      )}
      </div>
    </div>
  )
}
