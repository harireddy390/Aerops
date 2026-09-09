/**
 * AeroOps browser reporter (TypeScript) — drop-in crash telemetry.
 *
 * Hooks window.onerror + window.onunhandledrejection, ships an
 * <AeroOpsErrorBoundary> for React, and POSTs normalized payloads to
 * POST {endpoint}/api/telemetry/crash (default http://localhost:8000).
 *
 *   import { initAeroOps, AeroOpsErrorBoundary } from './aeroops-reporter'
 *   initAeroOps({ endpoint: 'http://localhost:8000', service: 'my-web-app' })
 *   <AeroOpsErrorBoundary><App /></AeroOpsErrorBoundary>
 */
import { Component, createElement, type ReactNode } from 'react'

export interface AeroOpsConfig {
  /** Base URL of AeroOps, e.g. 'http://localhost:8000' */
  endpoint: string
  /** Service name as registered in AeroOps (auto-registers on first report) */
  service: string
  release?: string
}

export interface CrashPayload {
  service_id: string
  error_name: string
  message: string
  file_path: string
  line_number: number
  column_number: number
  stack_trace: string
}

type Normalized = CrashPayload & {
  url: string
  userAgent: string
  release: string
  componentStack?: string
}

let cfg: Required<Pick<AeroOpsConfig, 'endpoint' | 'service'>> & { release: string } | null = null
let installed = false
const recent = new Map<string, number>() // signature -> ts (flood guard)

function topFrames(stack: string, n = 5): string {
  const lines = stack.split('\n')
  const head = /^(\w*Error\b.*)?$/.test(lines[0] ?? '') ? lines.slice(0, 1) : []
  const frames = lines.filter((l) => /^\s*at\s/.test(l)).slice(0, n)
  return [...head, ...frames].join('\n').slice(0, 8000)
}

function firstFrame(stack: string): { file: string; line: number; col: number } {
  const m = stack.match(/\(?(https?:\/\/[^()\s]+|[A-Za-z]:\\[^()\s]+|\/[^()\s]+):(\d+):(\d+)\)?/)
  return { file: m?.[1] ?? '', line: m ? Number(m[2]) : 0, col: m ? Number(m[3]) : 0 }
}

function normalize(kind: string, err: unknown, componentStack?: string): Normalized | null {
  if (!cfg) return null
  const e = err as { name?: string; message?: string; stack?: string } | null
  const message = String(e?.message ?? err ?? 'Unknown error').slice(0, 1000)
  const stack = topFrames(String(e?.stack ?? `${e?.name ?? 'Error'}: ${message}`))
  const f = firstFrame(stack)
  return {
    service_id: cfg.service,
    error_name: String(e?.name ?? 'Error').slice(0, 80),
    message,
    file_path: f.file.slice(0, 500),
    line_number: f.line,
    column_number: f.col,
    stack_trace: stack,
    url: location.href.slice(0, 500),
    userAgent: navigator.userAgent.slice(0, 300),
    release: cfg.release,
    ...(componentStack ? { componentStack: componentStack.slice(0, 4000) } : {}),
  }
}

async function transmit(p: Normalized, attempt = 1): Promise<void> {
  const key = `${p.message}|${p.file_path}:${p.line_number}`
  const now = Date.now()
  if ((recent.get(key) ?? 0) > now - 60000) return // 1/min per unique crash
  recent.set(key, now)
  const url = `${cfg!.endpoint.replace(/\/$/, '')}/api/telemetry/crash`
  const body = JSON.stringify(p)
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      if (navigator.sendBeacon(url, blob)) return
    }
  } catch { /* fall through to fetch */ }
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    })
    if (!r.ok && attempt === 1) {
      await new Promise((res) => setTimeout(res, 2000))
      await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {})
    }
  } catch { /* telemetry must never break the host app */ }
}

function capture(kind: string, err: unknown, componentStack?: string): void {
  try {
    const p = normalize(kind, err, componentStack)
    if (p) void transmit(p)
  } catch { /* never throw into host handlers */ }
}

/** Idempotent init — safe to call twice (e.g. StrictMode). */
export function initAeroOps(options: AeroOpsConfig): void {
  if (installed) return
  if (!options?.endpoint || !options?.service) {
    throw new Error('initAeroOps needs { endpoint, service }')
  }
  cfg = { endpoint: options.endpoint, service: options.service.slice(0, 120), release: (options.release ?? '').slice(0, 60) }
  window.addEventListener('error', (e) => capture('onerror', e.error ?? e.message))
  window.addEventListener('unhandledrejection', (e) => capture('unhandledrejection', (e as PromiseRejectionEvent).reason))
  installed = true
}

/** Report manually (or from the boundary below). */
export function reportCrash(err: unknown, componentStack?: string): void {
  capture('manual', err, componentStack)
}

type BoundaryProps = { children: ReactNode; fallback?: ReactNode; onCatch?: (e: unknown) => void }

/** Wrap your tree: <AeroOpsErrorBoundary><App /></AeroOpsErrorBoundary> */
export class AeroOpsErrorBoundary extends Component<BoundaryProps, { crashed: boolean }> {
  state = { crashed: false }

  static getDerivedStateFromError(): { crashed: boolean } {
    return { crashed: true }
  }

  componentDidCatch(error: unknown, info: { componentStack?: string }): void {
    capture('error-boundary', error, info?.componentStack)
    try {
      this.props.onCatch?.(error)
    } catch { /* host callback errors are swallowed on purpose */ }
  }

  render(): ReactNode {
    if (this.state.crashed) {
      return (
        this.props.fallback ??
        createElement(
          'div',
          { style: { padding: 24, fontFamily: 'system-ui, sans-serif' } },
          createElement('h2', null, 'Something went wrong.'),
          createElement('p', null, 'The error was reported automatically. Please reload the page.'),
        )
      )
    }
    return this.props.children
  }
}
