import type { ReactElement } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { useLive } from './hooks'

const ICONS: Record<string, ReactElement> = {
  '/': <path d="M3 12l9-9 9 9M5 10v10h5v-6h4v6h5V10" />,
  '/services': <path d="M4 6h16M4 12h16M4 18h16" />,
  '/incidents': <path d="M12 3l10 18H2L12 3zm0 7v5m0 3v.5" />,
  '/logs': <path d="M5 4h14v16H5zM9 9h6M9 13h6" />,
  '/diagnostics': <path d="M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3" />,
  '/remediation': <path d="M14 7a4 4 0 105.7 3.6L14 16.3V7zm-4 0a4 4 0 11-5.7 3.6L10 16.3V7z" />,
  '/metrics': <path d="M4 20V10m6 10V4m6 16v-7m4 7H2" />,
  '/notifications': <path d="M6 9a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6zm4 10a2 2 0 004 0" />,
  '/audit': <path d="M12 3v18M5 7l7-4 7 4M5 17l7 4 7-4" />,
  '/settings': <path d="M4 8h10m4 0h2M4 16h2m4 0h10" />,
}

const NAV: [string, string][] = [
  ['/', 'Dashboard'],
  ['/services', 'Services'],
  ['/incidents', 'Incidents'],
  ['/logs', 'Logs'],
  ['/diagnostics', 'Diagnostics'],
  ['/remediation', 'Remediation'],
  ['/metrics', 'Metrics'],
  ['/notifications', 'Notifications'],
  ['/audit', 'Audit Log'],
  ['/settings', 'Settings'],
]

function Icon({ to }: { to: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      {ICONS[to] ?? <circle cx="12" cy="12" r="8" />}
    </svg>
  )
}

export function Layout() {
  const loc = useLocation()
  const nav = useNavigate()
  const live = useLive()
  const { session, logout } = useAuth()
  return (
    <div className="min-h-screen">
      <div className="flex">
        <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-line bg-[#0d1330]/80 p-4 backdrop-blur">
          <div className="mb-1 flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-sm font-black">A</span>
            <div>
              <div className="font-bold leading-tight">AeroOps</div>
              <div className="text-[11px] text-mut">self-healing ops</div>
            </div>
          </div>
          <div className="mb-4 mt-3">
            <span className="badge" title={live ? 'Realtime stream connected' : 'Realtime stream unreachable — data still refreshes every few seconds'}>
              <span className={`dot ${live ? 'bg-emerald-400 dot-pulse' : 'bg-amber-400'}`} />
              {live ? 'LIVE' : 'POLLING'}
            </span>
          </div>
          <nav className="flex flex-col gap-0.5">
            {NAV.map(([to, label]) => {
              const active = loc.pathname === to || (to !== '/' && loc.pathname.startsWith(to))
              return (
                <Link
                  key={to}
                  to={to}
                  className={`flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition ${active ? 'bg-indigo-600 font-semibold text-white shadow-lg shadow-indigo-950' : 'text-slate-300 hover:bg-white/5'}`}
                >
                  <Icon to={to} />
                  {label}
                </Link>
              )
            })}
          </nav>
          <div className="mt-auto space-y-2">
            <div className="flex items-center justify-between rounded-xl border border-line bg-white/[0.02] px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-xs font-semibold">{session?.username}</div>
                <div className="text-[11px] capitalize text-mut">{session?.role}</div>
              </div>
              <button
                className="shrink-0 text-[11px] text-indigo-300 hover:underline"
                onClick={() => { logout(); nav('/login') }}
              >
                Log out
              </button>
            </div>
            <div className="rounded-xl border border-line bg-white/[0.02] p-3 text-[11px] leading-relaxed text-mut">
              Kill a service and watch AeroOps detect, diagnose, restart and verify — all here, live.
            </div>
          </div>
        </aside>
        <main className="mx-auto w-full max-w-6xl flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
