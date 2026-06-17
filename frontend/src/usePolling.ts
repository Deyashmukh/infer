import { useEffect, useRef, useState } from 'react'
import { getStatus, type StatusResponse, type SessionStatus } from './api'

const TERMINAL: Set<SessionStatus> = new Set(['READY', 'FAILED'])
const POLL_INTERVAL_MS = 700

export function usePolling(sessionId: string | null) {
  const [state, setState] = useState<StatusResponse | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!sessionId) return

    let cancelled = false

    async function poll() {
      if (cancelled || !sessionId) return
      try {
        const status = await getStatus(sessionId)
        if (cancelled) return
        setState(status)
        if (!TERMINAL.has(status.status)) {
          timerRef.current = setTimeout(poll, POLL_INTERVAL_MS)
        }
      } catch {
        // network error: retry
        if (!cancelled) {
          timerRef.current = setTimeout(poll, POLL_INTERVAL_MS)
        }
      }
    }

    void poll()

    return () => {
      cancelled = true
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [sessionId])

  return state
}
