import { token } from './auth'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { ...(opts?.headers as Record<string, string> | undefined) }
  const t = token()
  if (t) headers['Authorization'] = `Bearer ${t}`
  const r = await fetch(`${BASE}${path}`, { ...opts, headers })
  if (r.status === 401 && !window.location.pathname.startsWith('/login')) {
    window.dispatchEvent(new Event('aeroops:logout'))
    window.location.href = '/login'
    throw new Error('Session expired — log in again')
  }
  if (!r.ok) throw new Error(`${opts?.method ?? 'GET'} ${path} -> ${r.status}`)
  if (r.status === 204) return undefined as T
  return r.json() as Promise<T>
}

const json = (body: unknown) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  services: () => req<import('./types').Service[]>('/api/services'),
  service: (id: number) => req<import('./types').Service>(`/api/services/${id}`),
  createService: (b: unknown) => req('/api/services', json(b)),
  serviceAction: (id: number, a: 'start' | 'stop' | 'restart') =>
    req(`/api/services/${id}/${a}`, { method: 'POST' }),
  metrics: (id: number) => req<{ cpu: number; mem_mb: number; response_ms: number | null; t: string }[]>(`/api/services/${id}/metrics`),
  incidents: (q = '') => req<import('./types').Incident[]>(`/api/incidents${q}`),
  incident: (id: number) => req<Record<string, unknown>>(`/api/incidents/${id}`),
  timeline: (id: number) => req<import('./types').TimelineEvent[]>(`/api/incidents/${id}/timeline`),
  acknowledge: (id: number) => req(`/api/incidents/${id}/acknowledge`, { method: 'POST' }),
  remediate: (id: number, action_type: string, params = {}) =>
    req(`/api/incidents/${id}/remediate`, json({ action_type, params })),
  logs: (q = '') => req<{ content: string; t: string; service_id: number }[]>(`/api/logs${q}`),
  diagnostics: () => req<import('./types').Diagnosis[]>('/api/diagnostics'),
  remediation: () => req<Record<string, unknown>[]>('/api/remediation'),
  notifications: () => req<Record<string, unknown>[]>('/api/notifications'),
  audit: () => req<Record<string, unknown>[]>('/api/audit'),
  summary: () => req<Record<string, unknown>>('/api/metrics/summary'),
  diagnoseText: (text: string) => req<Record<string, unknown>>('/api/diagnose', json({ text })),
  simulateFailure: (service_id: number) =>
    req(`/api/demo/simulate-failure?service_id=${service_id}`, { method: 'POST' }),
  systemHealth: () => req<Record<string, unknown>>('/api/system/health'),
  users: () => req<Record<string, unknown>[]>('/api/auth/users'),
  createUser: (username: string, email: string, password: string, role: string) =>
    req('/api/auth/users', json({ username, email, password, confirm_password: password, role })),
  forgotPassword: (username_or_email: string) =>
    req('/api/auth/forgot-password', json({ username_or_email })),
  resetPassword: (username_or_email: string, code: string, new_password: string) =>
    req('/api/auth/reset-password', json({ username_or_email, code, new_password, confirm_password: new_password })),
  changePassword: (current_password: string, new_password: string) =>
    req('/api/auth/change-password', json({ current_password, new_password })),
}
