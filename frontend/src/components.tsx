/** Shared display helpers: badges, cards, stats, time formatting. */

const STATUS_DOT: Record<string, string> = {
  HEALTHY: 'bg-emerald-400',
  RECOVERED: 'bg-emerald-300',
  RESOLVED: 'bg-emerald-400',
  WARNING: 'bg-amber-400',
  DEGRADED: 'bg-orange-400',
  UNHEALTHY: 'bg-red-400',
  CRASHED: 'bg-red-500',
  OPEN: 'bg-red-400',
  FAILED: 'bg-red-600',
  RESTARTING: 'bg-blue-400',
  RECOVERING: 'bg-sky-300',
  ACKNOWLEDGED: 'bg-violet-400',
  STOPPED: 'bg-slate-400',
  UNKNOWN: 'bg-slate-500',
}

const SEV_DOT: Record<string, string> = {
  critical: 'bg-red-500',
  warning: 'bg-amber-400',
  info: 'bg-sky-400',
}

export function StatusBadge({ value, pulse = false }: { value: string; pulse?: boolean }) {
  const dot = STATUS_DOT[value] ?? 'bg-slate-500'
  return (
    <span className="badge">
      <span className={`dot ${dot}${pulse ? ' dot-pulse' : ''}`} />
      {value}
    </span>
  )
}

export function SeverityBadge({ value }: { value: string }) {
  const dot = SEV_DOT[value?.toLowerCase()] ?? 'bg-slate-500'
  return (
    <span className="badge">
      <span className={`dot ${dot}`} />
      {value}
    </span>
  )
}

export function Card({ title, action, children }: { title?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card fade-in">
      {title && (
        <div className="card-h">
          <h2 className="card-t">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="card">
      <div className="text-xs font-medium uppercase tracking-wider text-mut">{label}</div>
      <div className="stat-v">{value}</div>
      {sub && <div className="mt-1 text-xs text-mut">{sub}</div>}
    </div>
  )
}

export function EmptyState({ what, hint }: { what: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-4 py-8 text-center">
      <div className="text-sm font-medium text-slate-300">No {what} yet</div>
      {hint && <div className="mt-1 text-xs text-mut">{hint}</div>}
    </div>
  )
}

export function Spinner() {
  return <span className="spin" aria-label="loading" />
}

/** "2026-..T19:50:01" -> "19:50:01", tolerant of bad input. */
export function clock(iso: unknown): string {
  const s = String(iso ?? '')
  return s.length >= 19 ? s.slice(11, 19) : s
}

/** "2026-..T19:50:01" -> "Sep 5, 19:50", tolerant of bad input. */
export function dayTime(iso: unknown): string {
  const s = String(iso ?? '')
  if (s.length < 16) return s
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const m = Number(s.slice(5, 7))
  return `${months[m - 1] ?? ''} ${Number(s.slice(8, 10))}, ${s.slice(11, 16)}`
}

export function fmtSecs(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (n < 60) return `${n.toFixed(1)}s`
  return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`
}

/** Destructive actions ask first. */
export function ConfirmButton({ label, ask, onConfirm, danger = false }: { label: string; ask: string; onConfirm: () => void; danger?: boolean }) {
  return (
    <button
      className={danger ? 'btn-danger' : 'btn-ghost'}
      onClick={() => {
        if (window.confirm(ask)) onConfirm()
      }}
    >
      {label}
    </button>
  )
}
