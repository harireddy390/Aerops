import { createContext, useCallback, useContext, useEffect, useState } from 'react'

export type Session = { token: string; username: string; role: string } | null

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const KEY = 'aeroops.session'

const Ctx = createContext<{
  session: Session
  checked: boolean
  login: (username: string, password: string, remember: boolean) => Promise<string | null>
  register: (username: string, email: string, password: string) => Promise<string | null>
  logout: () => void
}>({ session: null, checked: false, login: async () => 'noop', register: async () => 'noop', logout: () => {} })

export const useAuth = () => useContext(Ctx)

/** Viewers watch; operators and admins act. */
export const useCanAct = () => {
  const { session } = useAuth()
  return session != null && session.role !== 'viewer'
}

export function token(): string | null {
  try {
    return (JSON.parse(localStorage.getItem(KEY) ?? 'null') as Session)?.token ?? null
  } catch {
    return null
  }
}

export function parseErrorDetail(data: unknown, fallback: string): string {
  if (!data || typeof data !== 'object') return fallback
  const d = (data as Record<string, unknown>).detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    return d
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) return String((item as { msg: unknown }).msg)
        return JSON.stringify(item)
      })
      .join(', ')
  }
  if (typeof (data as Record<string, unknown>).message === 'string') {
    return (data as Record<string, unknown>).message as string
  }
  return fallback
}

async function api(path: string, body: unknown) {
  let r: Response
  try {
    r = await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error(`Unable to connect to AeroOps backend (${BASE}). Ensure the backend server is running on port 8000.`)
  }
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(parseErrorDetail(data, `Request failed (${r.status})`))
  return data
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session>(() => {
    try {
      return JSON.parse(localStorage.getItem(KEY) ?? 'null')
    } catch {
      return null
    }
  })
  // false until the saved session is verified with the backend (or found absent)
  const [checked, setChecked] = useState(false)

  const save = useCallback((s: Session) => {
    setSession(s)
    if (s) localStorage.setItem(KEY, JSON.stringify(s))
    else localStorage.removeItem(KEY)
  }, [])

  // on load: is the saved token still good? bad/expired -> forget it silently
  useEffect(() => {
    let live = true
    ;(async () => {
      const t = token()
      if (!t) {
        if (live) setChecked(true)
        return
      }
      try {
        const r = await fetch(`${BASE}/api/auth/me`, { headers: { Authorization: `Bearer ${t}` } })
        if (r.status === 401) {
          if (live) save(null)
          return
        }
        if (!r.ok) throw new Error('bad token')
        const me = await r.json()
        if (live) save({ token: t, username: me.username, role: me.role })
      } catch {
        // network issue: don't clear token on momentary connection drop
      } finally {
        if (live) setChecked(true)
      }
    })()
    return () => { live = false }
  }, [save])

  const login = useCallback(async (username: string, password: string, remember: boolean) => {
    try {
      const data = await api('/api/auth/login', { username, password, remember }) as { token: string; username: string; role: string }
      save({ token: data.token, username: data.username, role: data.role })
      return null
    } catch (e) {
      return (e as Error).message
    }
  }, [save])

  const register = useCallback(async (username: string, email: string, password: string) => {
    try {
      await api('/api/auth/register', { username, email, password, confirm_password: password })
      return await login(username, password, true)
    } catch (e) {
      return (e as Error).message
    }
  }, [login])

  const logout = useCallback(() => save(null), [save])

  useEffect(() => {
    const onLogout = () => save(null)
    window.addEventListener('aeroops:logout', onLogout)
    return () => window.removeEventListener('aeroops:logout', onLogout)
  }, [save])

  return <Ctx.Provider value={{ session, checked, login, register, logout }}>{children}</Ctx.Provider>
}
