import { useState, type FormEvent } from 'react'

interface CredentialFormProps {
  onSubmit: (username: string, password: string) => Promise<void>
}

export function CredentialForm({ onSubmit }: CredentialFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await onSubmit(username, password)
    } catch {
      // Surface failures (network/CORS/backend) instead of leaving the button looking dead.
      setError('Could not reach the server. Please check your connection and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="credential-form" onSubmit={(e) => void handleSubmit(e)}>
      <label>
        Username
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <button type="submit" className="btn-primary" disabled={loading}>
        {loading ? 'Signing in…' : 'Sign in'}
      </button>
      {error && (
        <p className="error-msg" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
