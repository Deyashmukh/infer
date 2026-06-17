import { useState, type FormEvent } from 'react'

interface CredentialFormProps {
  onSubmit: (username: string, password: string) => Promise<void>
}

export function CredentialForm({ onSubmit }: CredentialFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await onSubmit(username, password)
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
      <button type="submit" disabled={loading}>
        {loading ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  )
}
