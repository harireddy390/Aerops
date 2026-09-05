import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { token } from './auth'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/** Subscribe to SSE; invalidate queries on any event (realtime, no refresh needed). */
export function useLive() {
  const qc = useQueryClient()
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    const t = token()
    const es = new EventSource(`${BASE}/api/events/stream${t ? `?token=${encodeURIComponent(t)}` : ''}`)
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = () => {
      setConnected(true)
      qc.invalidateQueries({ queryKey: ['services'] })
      qc.invalidateQueries({ queryKey: ['incidents'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    }
    return () => {
      setConnected(false)
      es.close()
    }
  }, [qc])
  return connected
}
