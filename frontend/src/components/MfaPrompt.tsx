import { useState, type FormEvent } from 'react'
import type { SessionStatus } from '../api'

interface MfaPromptProps {
  status: SessionStatus
  onSubmit: (code: string) => Promise<void>
}

export function MfaPrompt({ status, onSubmit }: MfaPromptProps) {
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)

  if (status !== 'AWAITING_MFA') return null

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await onSubmit(code)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="mfa-prompt" onSubmit={(e) => void handleSubmit(e)}>
      <label>
        MFA code
        <input
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
        />
      </label>
      <button type="submit" disabled={loading}>
        {loading ? 'Verifying…' : 'Submit code'}
      </button>
    </form>
  )
}
