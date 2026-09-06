/** Light enterprise kit. All colors come from the §29 token set (index.css). */
import type { ReactNode } from 'react'

const STATUS: Record<string, string> = {
  HEALTHY: 'bg-[#F0FDF4] text-[#16A34A] border-[#BBF7D0]',
  RECOVERED: 'bg-[#F0FDF4] text-[#16A34A] border-[#BBF7D0]',
  RESOLVED: 'bg-[#F0FDF4] text-[#16A34A] border-[#BBF7D0]',
  WARNING: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
  DEGRADED: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
  REMEDIATING: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
  ACKNOWLEDGED: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
  UNHEALTHY: 'bg-[#FEF2F2] text-[#DC2626] border-[#FECACA]',
  CRASHED: 'bg-[#FEF2F2] text-[#DC2626] border-[#FECACA]',
  OPEN: 'bg-[#FEF2F2] text-[#DC2626] border-[#FECACA]',
  FAILED: 'bg-[#FEF2F2] text-[#DC2626] border-[#FECACA]',
  RESTARTING: 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]',
  RECOVERING: 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]',
  INVESTIGATING: 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]',
  DIAGNOSED: 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]',
  STOPPED: 'bg-[#F8FAFC] text-[#64748B] border-[#CBD5E1]',
  UNKNOWN: 'bg-[#F8FAFC] text-[#64748B] border-[#CBD5E1]',
}

const STATUS_DOT: Record<string, string> = {
  HEALTHY: 'bg-[#16A34A]',
  RECOVERED: 'bg-[#16A34A]',
  RESOLVED: 'bg-[#16A34A]',
  WARNING: 'bg-[#F59E0B]',
  DEGRADED: 'bg-[#F59E0B]',
  REMEDIATING: 'bg-[#F59E0B]',
  ACKNOWLEDGED: 'bg-[#F59E0B]',
  UNHEALTHY: 'bg-[#DC2626]',
  CRASHED: 'bg-[#DC2626]',
  OPEN: 'bg-[#DC2626]',
  FAILED: 'bg-[#DC2626]',
  RESTARTING: 'bg-[#2563EB]',
  RECOVERING: 'bg-[#2563EB]',
  INVESTIGATING: 'bg-[#2563EB]',
  DIAGNOSED: 'bg-[#2563EB]',
  STOPPED: 'bg-[#64748B]',
  UNKNOWN: 'bg-[#64748B]',
}

const SEV: Record<string, string> = {
  critical: 'bg-[#FEF2F2] text-[#DC2626] border-[#FECACA]',
  high: 'bg-[#FEF2F2] text-[#DC2626] border-[#FECACA]',
  warning: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
  medium: 'bg-[#FFFBEB] text-[#B45309] border-[#FDE68A]',
  info: 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]',
  low: 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]',
}

const SEV_DOT: Record<string, string> = {
  critical: 'bg-[#DC2626]',
  high: 'bg-[#DC2626]',
  warning: 'bg-[#F59E0B]',
  medium: 'bg-[#F59E0B]',
  info: 'bg-[#2563EB]',
  low: 'bg-[#2563EB]',
}

export function StatusBadge({ value, pulse }: { value: string; pulse?: boolean }) {
  const v = String(value ?? 'UNKNOWN')
  void pulse
  return (
    <span className={`badge border ${STATUS[v] ?? STATUS.UNKNOWN}`} title={`Status: ${v}`}>
      <span className={`dot ${STATUS_DOT[v] ?? STATUS_DOT.UNKNOWN}`} />
      {v}
    </span>
  )
}

export function SeverityBadge({ value }: { value: string }) {
  const v = String(value ?? 'info').toLowerCase()
  return (
    <span className={`badge border ${SEV[v] ?? SEV.info}`} title={`Severity: ${value}`}>
      <span className={`dot ${SEV_DOT[v] ?? SEV_DOT.info}`} />
      {String(value)}
    </span>
  )
}

export function Card({ title, sub, action, children }: { title?: string; sub?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card fade-in">
      {title && (
        <div className="card-h">
          <div>
            <h2 className="card-t">{title}</h2>
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'bad' | 'warn' | 'good' | 'info' }) {
  const color = tone === 'bad' ? 'text-[#DC2626]' : tone === 'warn' ? 'text-[#B45309]' : tone === 'good' ? 'text-[#16A34A]' : tone === 'info' ? 'text-[#2563EB]' : 'text-ink'
  return (
    <div className="card">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-mut">{label}</div>
      <div className={`mt-1 text-[26px] font-bold leading-none tracking-tight ${color}`}>{value}</div>
      {sub && <div className="mt-1.5 text-xs text-mut">{sub}</div>}
    </div>
  )
}

/** KPI card with circular icon, per reference §8. tone picks icon colors. */
export function Kpi({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone: 'info' | 'good' | 'warn' | 'bad'; icon: ReactNode }) {
  const tones = {
    info: 'bg-[#EFF6FF] text-[#2563EB]',
    good: 'bg-[#F0FDF4] text-[#16A34A]',
    warn: 'bg-[#FFFBEB] text-[#B45309]',
    bad: 'bg-[#FEF2F2] text-[#DC2626]',
  }
  return (
    <div className="card">
      <div className="flex items-center gap-3">
        <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${tones[tone]}`}>{icon}</span>
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-mut">{label}</div>
          <div className="text-2xl font-bold leading-tight tracking-tight text-ink">{value}</div>
        </div>
      </div>
      {sub && <div className="mt-2 text-xs text-mut">{sub}</div>}
    </div>
  )
}

export function EmptyState({ what, hint }: { what?: string; hint?: string }) {
  return (
    <div className="rounded-[10px] border border-dashed border-line bg-white px-4 py-7 text-center">
      <div className="text-[13px] font-medium text-ink">No data available</div>
      <div className="mt-1 text-xs text-mut">{hint ?? (what ? `No ${what} to show.` : '')}</div>
    </div>
  )
}

export function Spinner() {
  return <span className="spin" aria-label="loading" />
}

export function SkeletonRows({ n = 4 }: { n?: number }) {
  return (
    <div className="space-y-2" aria-label="loading">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="skel h-9 w-full" style={{ opacity: 1 - i * 0.1 }} />
      ))}
    </div>
  )
}

export function SkeletonCards({ n = 6 }: { n?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="skel h-[86px] w-full" />
      ))}
    </div>
  )
}

/** "2026-..T19:50:01" -> "19:50:01", tolerant of bad input. */
export function clock(iso: unknown): string {
  const s = String(iso ?? '')
  return s.length >= 19 ? s.slice(11, 19) : s || '—'
}

/** "2026-..T19:50:01" -> "Sep 5, 19:50", tolerant of bad input. */
export function dayTime(iso: unknown): string {
  const s = String(iso ?? '')
  if (s.length < 16) return s || '—'
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const m = Number(s.slice(5, 7))
  return `${months[m - 1] ?? ''} ${Number(s.slice(8, 10))}, ${s.slice(11, 16)}`
}

export function fmtSecs(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n) || n < 0) return '—'
  if (n < 60) return `${n.toFixed(1)}s`
  return `${Math.floor(n / 60)}m ${(n % 60).toFixed(0)}s`
}

/** "harireddy" -> "Harireddy", "hari.reddy" -> "Hari Reddy". Display only. */
export function formatName(username: unknown): string {
  return String(username ?? '')
    .split(/[._\-@\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Destructive actions ask first. */
export function ConfirmButton({ label, ask, onConfirm, danger = false }: { label: string; ask: string; onConfirm: () => void; danger?: boolean }) {
  return (
    <button
      className={danger ? 'btn-danger' : 'btn-secondary'}
      title={ask}
      onClick={() => {
        if (window.confirm(ask)) onConfirm()
      }}
    >
      {label}
    </button>
  )
}
