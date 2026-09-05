import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
type Tab = 'signin' | 'signup' | 'forgot'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-mut">{label}</label>
      {children}
    </div>
  )
}

export function Login() {
  const { session, login, register } = useAuth()
  const nav = useNavigate()
  const [open, setOpen] = useState<boolean | null>(null)
  const [first, setFirst] = useState(false)
  const [tab, setTab] = useState<Tab>('signin')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState('')
  const [show, setShow] = useState(false)
  const [remember, setRemember] = useState(true)
  const [forgotSent, setForgotSent] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch(`${BASE}/api/auth/status`)
      .then((r) => r.json())
      .then((s) => {
        setOpen(!!s.registration_open)
        setFirst(!!s.first_user)
        if (s.registration_open && s.first_user) setTab('signup')
      })
      .catch(() => setOpen(false))
  }, [])

  useEffect(() => {
    if (session) nav('/')
  }, [session, nav])

  const fail = (m: string) => { setErr(m); setOk('') }
  const good = (m: string) => { setOk(m); setErr('') }

  const validSignup = () => {
    if (username.trim().length < 3) return 'Username needs at least 3 characters.'
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return 'Enter a valid Gmail, e.g. you@gmail.com.'
    if (password.length < 8) return 'Password needs at least 8 characters.'
    if (password !== confirm) return 'Passwords do not match — type the same one twice.'
    return null
  }

  const doSignin = async () => {
    setBusy(true)
    const problem = await login(username.trim(), password, remember)
    setBusy(false)
    if (problem) fail(problem)
    else nav('/')
  }

  const doSignup = async () => {
    const v = validSignup()
    if (v) return fail(v)
    setBusy(true)
    const problem = await register(username.trim(), email.trim(), password)
    setBusy(false)
    if (problem) fail(problem)
    else nav('/')
  }

  const doForgot = async () => {
    if (!username.trim()) return fail('Enter your username or Gmail first.')
    setBusy(true)
    try {
      await api.forgotPassword(username.trim())
      setForgotSent(true)
      good('Code sent — check that Gmail (including spam), then enter it below.')
    } catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }

  const doReset = async () => {
    if (!/^\d{6}$/.test(code.trim())) return fail('The code is 6 digits.')
    if (password.length < 8) return fail('New password needs at least 8 characters.')
    if (password !== confirm) return fail('New passwords do not match.')
    setBusy(true)
    try {
      await api.resetPassword(username.trim(), code.trim(), password)
      good('Password changed — sign in with the new one.')
      setTab('signin')
      setPassword('')
      setConfirm('')
      setCode('')
      setForgotSent(false)
    } catch (e) { fail((e as Error).message) } finally { setBusy(false) }
  }

  const tabs: [Tab, string][] = [
    ['signin', 'Sign in'],
    ['signup', 'Sign up'],
    ['forgot', 'Forgot?'],
  ]

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="grid w-full max-w-4xl overflow-hidden rounded-3xl border border-line bg-panel/90 shadow-2xl md:grid-cols-2">
        <div className="hidden flex-col justify-between bg-gradient-to-br from-indigo-600 via-violet-700 to-[#0b1020] p-8 md:flex">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/15 text-base font-black">A</span>
            <b>AeroOps</b>
          </div>
          <div>
            <h1 className="text-3xl font-bold leading-tight">Every crash,<br />caught & fixed.</h1>
            <p className="mt-3 text-sm text-indigo-100/80">Detect → diagnose → restart → verify → notify. Watch it happen live.</p>
          </div>
          <div className="text-xs text-indigo-100/60">Self-healing operations console</div>
        </div>
        <div className="p-8">
          <div className="mb-5 flex rounded-xl border border-line bg-black/30 p-1 text-sm">
            {tabs.map(([t, label]) => (
              <button
                key={t}
                onClick={() => { setTab(t); setErr(''); setOk('') }}
                className={`flex-1 rounded-lg px-3 py-1.5 font-medium transition ${tab === t ? 'bg-indigo-600 text-white' : 'text-mut hover:text-slate-200'}`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab !== 'forgot' && (
            <>
              <h2 className="text-xl font-bold">{tab === 'signin' ? 'Welcome back' : 'Create your account'}</h2>
              <p className="mb-4 mt-1 text-sm text-mut">
                {open === true && first && 'No users yet — your account becomes the admin.'}
                {open === true && !first && 'Create a viewer account — an admin can promote you to operator later.'}
                {open === false && tab === 'signup' && 'Signups are closed on this server — ask your admin to add you in Settings → Team.'}
                {open === false && tab === 'signin' && 'Log in to your operations console.'}
              </p>
              <div className="space-y-3">
                <Field label="Username">
                  <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
                </Field>
                {tab === 'signup' && (
                  <Field label="Gmail">
                    <input className="input" placeholder="you@gmail.com" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
                  </Field>
                )}
                <Field label={tab === 'signup' ? 'Password (8+ characters)' : 'Password'}>
                  <div className="relative">
                    <input className="input pr-16" type={show ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={tab === 'signin' ? 'current-password' : 'new-password'} />
                    <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg px-2 py-1 text-xs text-indigo-300 hover:bg-white/5" onClick={() => setShow(!show)}>
                      {show ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </Field>
                {tab === 'signup' && (
                  <Field label="Confirm password">
                    <input
                      className={`input ${confirm && (password !== confirm ? '!border-red-500/60' : '!border-emerald-500/60')}`}
                      type={show ? 'text' : 'password'}
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      autoComplete="new-password"
                    />
                    {confirm && password !== confirm && <div className="mt-1 text-xs text-red-300">Not matching yet…</div>}
                  </Field>
                )}
                {tab === 'signin' && (
                  <label className="flex cursor-pointer items-center gap-2 text-sm text-mut">
                    <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 accent-indigo-600" />
                    Keep me logged in for 30 days
                  </label>
                )}
              </div>
              {err && <div className="mt-3 rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
              <button className="btn mt-4 w-full justify-center" disabled={busy || (tab === 'signup' && open === false)} onClick={tab === 'signin' ? doSignin : doSignup}>
                {busy ? 'One moment…' : tab === 'signin' ? 'Sign in' : 'Sign up'}
              </button>
            </>
          )}

          {tab === 'forgot' && (
            <>
              <h2 className="text-xl font-bold">Reset password</h2>
              <p className="mb-4 mt-1 text-sm text-mut">We’ll email a 6-digit code to the Gmail on your account. It works once, for 15 minutes.</p>
              <div className="space-y-3">
                <Field label="Username or Gmail">
                  <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
                </Field>
                {!forgotSent ? (
                  <button className="btn w-full justify-center" disabled={busy} onClick={doForgot}>
                    {busy ? 'Sending…' : 'Email me the code'}
                  </button>
                ) : (
                  <>
                    <Field label="6-digit code">
                      <input className="input font-mono tracking-[0.3em]" maxLength={6} placeholder="••••••" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />
                    </Field>
                    <Field label="New password (8+ characters)">
                      <input className="input" type={show ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
                    </Field>
                    <Field label="Confirm new password">
                      <input className="input" type={show ? 'text' : 'password'} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
                    </Field>
                    <button className="btn w-full justify-center" disabled={busy} onClick={doReset}>
                      {busy ? 'Checking…' : 'Set new password'}
                    </button>
                    <button className="w-full text-center text-xs text-mut hover:text-slate-300" onClick={doForgot}>Didn’t get it? Send again</button>
                  </>
                )}
              </div>
              {err && <div className="mt-3 rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</div>}
              {ok && <div className="mt-3 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{ok}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
