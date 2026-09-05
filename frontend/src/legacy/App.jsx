import { useCallback, useEffect, useState } from 'react'
import './App.css'

async function api(path, opts) {
  const r = await fetch(path, opts)
  if (!r.ok) throw new Error(`${opts?.method || 'GET'} ${path} -> ${r.status}`)
  return r.json()
}

export default function App() {
  const [status, setStatus] = useState(null)
  const [logs, setLogs] = useState([])
  const [diagInput, setDiagInput] = useState("TypeError: Cannot read properties of undefined (reading 'profile')")
  const [diag, setDiag] = useState(null)
  const [fixMsg, setFixMsg] = useState('')
  const [err, setErr] = useState('')

  const refresh = useCallback(async () => {
    try {
      setErr('')
      const s = await api('/api/status')
      setStatus(s)
      const l = await api('/api/logs')
      setLogs(l.lines || [])
    } catch (e) { setErr(String(e.message || e)) }
  }, [])

  useEffect(() => { refresh(); const t = setInterval(refresh, 5000); return () => clearInterval(t) }, [refresh])

  const crash = async () => {
    await fetch('/crash').catch(() => {})
    setFixMsg('Crash triggered — restart + AI diagnosis in ~20s…')
    setTimeout(refresh, 6000); setTimeout(refresh, 22000)
  }
  const runDiagnose = async () => {
    setDiag({ loading: true })
    try { setDiag(await api('/api/diagnose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: diagInput }) })) }
    catch (e) { setDiag({ error: String(e.message || e) }) }
  }
  const runFix = async () => {
    try { const r = await api('/api/fix', { method: 'POST' }); setFixMsg(JSON.stringify(r)); refresh() }
    catch (e) { setFixMsg(String(e.message || e)) }
  }

  return (
    <div className="wrap">
      <header><div className={`pulse ${status?.status === 'ok' ? '' : 'down'}`} /><div>
        <h1>AeroOps · Real Service Console</h1>
        <small>backend :3000 · sqlite · frontend :5173 · monitor + local-AI</small>
      </div></header>
      {err && <p className="err">Backend unreachable: {err} — run <code>npm start</code> in AeroOps-Project</p>}
      <div className="grid">
        <div className="card"><small>Status</small><h2>{status?.status ?? '…'}</h2><small>{status ? `uptime ${status.uptimeSec}s · v${status.version}` : ''}</small></div>
        <div className="card"><small>Restarts (db)</small><h2>{status?.restarts ?? '…'}</h2><small>store: {status?.store}</small></div>
        <div className="card"><small>Auto-fix / model</small><h2>{status ? (status.autoFix ? 'ON' : 'OFF') : '…'}</h2><small>{status?.model}</small></div>
      </div>
      <div className="row">
        <button className="danger" onClick={crash}>Trigger crash</button>
        <button onClick={runFix}>Apply auto-fix</button>
        <button className="ghost" onClick={refresh}>Refresh</button>
      </div>
      {fixMsg && <p className="msg">{fixMsg}</p>}
      <h3>Crashes from database ({status?.crashes?.length ?? 0})</h3>
      <table><thead><tr><th>ID</th><th>Time</th><th>Exit</th><th>Diagnosis</th></tr></thead>
        <tbody>{(status?.crashes ?? []).slice().reverse().map((c) => (
          <tr key={c.id}><td>{c.id}</td><td>{c.time}</td><td>{c.code}</td>
            <td><b>{c.diagnosis?.cause}</b><br /><small>{c.diagnosis?.fix}</small>
              {c.diagnosis?.ai && <div className="ai">{c.diagnosis.ai}</div>}</td></tr>
        ))}</tbody></table>
      <h3>Test local-AI diagnosis</h3>
      <div className="row"><input value={diagInput} onChange={(e) => setDiagInput(e.target.value)} /><button onClick={runDiagnose}>Diagnose</button></div>
      {diag && <pre className="ai">{JSON.stringify(diag, null, 2).slice(0, 2000)}</pre>}
      <h3>Monitor log</h3>
      <pre id="logs">{logs.join('\n').slice(-3000)}</pre>
    </div>
  )
}
