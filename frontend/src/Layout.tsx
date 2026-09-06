import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  Bell,
  ChevronDown,
  FileBarChart,
  LayoutDashboard,
  Menu,
  ScrollText,
  Search,
  Server,
  Settings as SettingsIcon,
  Siren,
  Stethoscope,
  Wrench,
  Zap,
} from 'lucide-react'
import { Link, Outlet, useLocation, useNavigate, useOutletContext } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import { useLive } from './hooks'
import { formatName } from './components'

export type RangeKey = '15m' | '1h' | '24h'
export const RANGE_MS: Record<RangeKey, number> = { '15m': 15 * 60e3, '1h': 3600e3, '24h': 24 * 3600e3 }

/** Labels follow the reference; Alerts/Reports reuse the notifications/audit routes. */
const NAV: [string, string, React.ReactNode][] = [
  ['/', 'Dashboard', <LayoutDashboard size={17} />],
  ['/services', 'Services', <Server size={17} />],
  ['/incidents', 'Incidents', <Siren size={17} />],
  ['/notifications', 'Alerts', <Bell size={17} />],
  ['/diagnostics', 'Diagnostics', <Stethoscope size={17} />],
  ['/remediation', 'Remediation', <Wrench size={17} />],
  ['/metrics', 'Metrics', <Activity size={17} />],
  ['/logs', 'Logs', <ScrollText size={17} />],
  ['/audit', 'Reports', <FileBarChart size={17} />],
  ['/settings', 'Settings', <SettingsIcon size={17} />],
]

const PAGE_TITLE: Record<string, [string, string]> = {
  '/': ['Welcome back', "Here's what's happening with your systems today."],
  '/services': ['Services', 'Every system under watch.'],
  '/incidents': ['Incidents', 'Failures, investigations and recoveries.'],
  '/notifications': ['Alerts', 'Notifications that went out.'],
  '/diagnostics': ['Diagnostics', 'Root causes, rules and AI.'],
  '/remediation': ['Remediation', 'Fixes automatic and manual.'],
  '/metrics': ['Metrics', 'Recovery and fleet numbers.'],
  '/logs': ['Logs', 'Captured service output.'],
  '/audit': ['Reports', 'Audit trail of everything automatic.'],
  '/settings': ['Settings', 'System health and team.'],
}

function initials(name: string): string {
  const parts = name.split(/[._\-@\s]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? 'A') + (parts[1]?.[0] ?? 'R')).toUpperCase()
}

function SidebarBody({ onNav }: { onNav?: () => void }) {
  const loc = useLocation()
  const nav = useNavigate()
  const { session, logout } = useAuth()
  const live = useLive()
  return (
    <div className="flex h-full flex-col">
      <Link to="/" onClick={onNav} className="mb-5 flex items-center gap-2.5 px-2" title="AeroOps home">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-white">
          <Zap size={18} />
        </span>
        <span className="text-[17px] font-bold tracking-tight text-ink">
          Aero<span className="text-brand">Ops</span>
        </span>
      </Link>
      <nav className="flex flex-col gap-0.5" aria-label="Primary">
        {NAV.map(([to, label, icon]) => {
          const active = loc.pathname === to || (to !== '/' && loc.pathname.startsWith(to))
          return (
            <Link
              key={to}
              to={to}
              onClick={onNav}
              title={label}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${active ? 'bg-[#EAF2FF] font-semibold text-brand' : 'font-medium text-secondary hover:bg-soft'}`}
            >
              <span className={active ? 'text-brand' : 'text-mut'}>{icon}</span>
              {label}
            </Link>
          )
        })}
      </nav>
      <div className="mt-auto border-t border-line pt-3">
        <button
          className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-soft"
          title={`${session?.username} (${session?.role}) — log out`}
          onClick={() => { logout(); nav('/login') }}
        >
          <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-light text-xs font-bold text-brand">
            {initials(session?.username ?? 'AR')}
            <span className={`absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white ${live ? 'bg-[#16A34A]' : 'bg-[#94A3B8]'}`} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-semibold text-ink">{formatName(session?.username) || 'AeroOps Admin'}</span>
            <span className="block text-[11px] capitalize text-mut">{session?.role ?? 'Administrator'}</span>
          </span>
          <ChevronDown size={15} className="shrink-0 text-faint" />
        </button>
      </div>
    </div>
  )
}

function CommandPalette({ close }: { close: () => void }) {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const services = useQuery({ queryKey: ['services'], queryFn: api.services })
  const incidents = useQuery({ queryKey: ['incidents'], queryFn: () => api.incidents('?limit=30') })
  const needle = q.trim().toLowerCase()
  const svcHits = (services.data ?? []).filter((s) => !needle || s.name.toLowerCase().includes(needle)).slice(0, 6)
  const incHits = (incidents.data ?? []).filter((i) => !needle || `#${i.id}`.includes(needle) || i.error_message.toLowerCase().includes(needle)).slice(0, 6)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])
  const go = (to: string) => { close(); nav(to) }
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/30 p-4 pt-24" onClick={close}>
      <div className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-white shadow-pop" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-4 py-3">
          <Search size={16} className="text-faint" />
          <input autoFocus className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-faint" placeholder="Search services, incidents…" value={q} onChange={(e) => setQ(e.target.value)} />
          <kbd className="rounded border border-line bg-soft px-1.5 py-0.5 text-[11px] text-mut">esc</kbd>
        </div>
        <div className="max-h-80 overflow-auto p-2">
          {svcHits.length === 0 && incHits.length === 0 && <div className="px-3 py-6 text-center text-sm text-mut">No data available</div>}
          {svcHits.length > 0 && <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-mut">Services</div>}
          {svcHits.map((s) => (
            <button key={s.id} onClick={() => go(`/services/${s.id}`)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-soft">
              <Server size={14} className="text-mut" /><span className="font-medium text-ink">{s.name}</span><span className="ml-auto text-xs text-mut">{s.status}</span>
            </button>
          ))}
          {incHits.length > 0 && <div className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-mut">Incidents</div>}
          {incHits.map((i) => (
            <button key={i.id} onClick={() => go(`/incidents/${i.id}`)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-soft">
              <Siren size={14} className="text-mut" /><span className="font-mono text-ink">#{i.id}</span><span className="truncate text-mut">{i.error_message.slice(0, 60)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export function Layout() {
  const loc = useLocation()
  const nav = useNavigate()
  const { session } = useAuth()
  const [palette, setPalette] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [range, setRange] = useState<RangeKey>('15m')
  const notes = useQuery({ queryKey: ['notifications'], queryFn: api.notifications, refetchInterval: 15000 })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((v) => !v) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => { setMobileNav(false) }, [loc.pathname])

  const [title, sub] = PAGE_TITLE[loc.pathname] ?? ['AeroOps', '']
  const head = loc.pathname === '/' ? `Welcome back, ${formatName(session?.username)} 👋` : title
  const unread = (notes.data ?? []).length

  return (
    <div className="min-h-screen bg-white">
      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-white px-3 py-4 lg:flex">
          <SidebarBody />
        </aside>
        {mobileNav && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <div className="absolute inset-0 bg-ink/30" onClick={() => setMobileNav(false)} />
            <aside className="absolute left-0 top-0 h-full w-64 bg-white px-3 py-4 shadow-pop">
              <SidebarBody onNav={() => setMobileNav(false)} />
            </aside>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-6 py-4">
              <button className="rounded-md border border-line p-2 lg:hidden" onClick={() => setMobileNav(true)} title="Menu">
                <Menu size={16} className="text-secondary" />
              </button>
              <div className="min-w-0 flex-1">
                <h1 className="truncate text-lg font-bold tracking-tight text-ink">{head}</h1>
                <p className="truncate text-[13px] text-mut">{loc.pathname === '/' ? sub : sub}</p>
              </div>
              <button
                onClick={() => setPalette(true)}
                title="Search services and incidents"
                className="hidden min-w-52 items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-[13px] text-faint transition hover:border-slate-300 md:flex"
              >
                <Search size={14} />
                <span className="flex-1 text-left">Search services, incidents…</span>
                <kbd className="rounded border border-line bg-soft px-1.5 py-0.5 text-[11px] text-mut">Ctrl K</kbd>
              </button>
              <button onClick={() => nav('/notifications')} title={`${unread} notifications — open alerts`} className="relative rounded-md border border-line p-2 transition hover:bg-soft">
                <Bell size={16} className="text-secondary" />
                {unread > 0 && <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#DC2626] px-1 text-[10px] font-bold text-white">{unread > 99 ? '99+' : unread}</span>}
              </button>
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-light text-xs font-bold text-brand" title={session?.username ?? ''}>
                {initials(session?.username ?? 'AR')}
              </span>
              <select
                value={range}
                onChange={(e) => setRange(e.target.value as RangeKey)}
                title="Time range for activity and logs"
                className="input !w-auto cursor-pointer text-[13px]"
              >
                <option value="15m">Last 15 minutes</option>
                <option value="1h">Last 1 hour</option>
                <option value="24h">Last 24 hours</option>
              </select>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl p-6">
            <Outlet context={{ range }} />
            <footer className="mt-8 border-t border-line pt-4 text-xs text-faint">
              AeroOps self-healing operations · detect → diagnose → remediate → verify · all times local
            </footer>
          </main>
        </div>
      </div>
      {palette && <CommandPalette close={() => setPalette(false)} />}
    </div>
  )
}

export function useRange(): RangeKey {
  return (useOutletContext() as { range: RangeKey }).range
}
