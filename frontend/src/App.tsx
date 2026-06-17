import { useState } from 'react'
import './pdfWorker'
import { createSession, submitMfa, type Carrier, type SessionStatus } from './api'
import { usePolling } from './usePolling'
import { CarrierSelect } from './components/CarrierSelect'
import { CredentialForm } from './components/CredentialForm'
import { MfaPrompt } from './components/MfaPrompt'
import { DocumentViewer } from './components/DocumentViewer'
import './App.css'

type AppStep = 'select-carrier' | 'credentials' | 'polling'

const CARRIER_LABELS: Record<Carrier, string> = {
  liberty_mutual: 'Liberty Mutual',
  geico: 'Geico',
}

export function App() {
  const [step, setStep] = useState<AppStep>('select-carrier')
  const [carrier, setCarrier] = useState<Carrier | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [mfaSubmitTimestamp, setMfaSubmitTimestamp] = useState<number | null>(null)
  const [primaryLatencyMs, setPrimaryLatencyMs] = useState<number | null>(null)

  const pollingState = usePolling(step === 'polling' ? sessionId : null)
  const status: SessionStatus = pollingState?.status ?? 'STARTING'
  const documents = pollingState?.documents ?? []

  function handleCarrierSelect(selected: Carrier) {
    setCarrier(selected)
    setStep('credentials')
  }

  async function handleCredentials(username: string, password: string) {
    if (!carrier) return
    const res = await createSession(carrier, username, password)
    setSessionId(res.session_id)
    setStep('polling')
  }

  async function handleMfaSubmit(code: string) {
    if (!sessionId) return
    setMfaSubmitTimestamp(performance.now())
    await submitMfa(sessionId, code)
  }

  function handleFirstRender(latencyMs: number) {
    setPrimaryLatencyMs(latencyMs)
  }

  function renderError() {
    if (!pollingState?.error) return null
    const { type } = pollingState.error
    const messages: Record<string, string> = {
      auth_failed: 'Login failed — check your username and password.',
      mfa_failed: 'MFA verification failed — please try again.',
      timeout: 'The session timed out. Please refresh and try again.',
      scrape_failed: 'Could not retrieve policy documents. Please try again.',
    }
    return (
      <p className="error-msg" role="alert">
        {messages[type] ?? 'An unexpected error occurred.'}
      </p>
    )
  }

  return (
    <div className="app-shell">
      <div className="card">
        <header className="app-header">
          <h1 className="app-title">
            infer<span className="dot">.</span>
          </h1>
          <p className="app-subtitle">
            Pull your insurance policy documents in seconds.
          </p>
        </header>

        {step === 'select-carrier' && (
          <CarrierSelect onSelect={handleCarrierSelect} />
        )}

        {step === 'credentials' && (
          <div className="step">
            <p className="step-label">Step 2 of 2</p>
            <h2>Sign in{carrier ? ` to ${CARRIER_LABELS[carrier]}` : ''}</h2>
            <p className="step-hint">
              Enter your portal credentials. They’re used only to fetch your
              documents and are never stored.
            </p>
            <CredentialForm onSubmit={handleCredentials} />
          </div>
        )}

        {step === 'polling' && (
          <>
            {status === 'STARTING' && <p className="status-msg">Starting session…</p>}
            {status === 'VERIFYING_MFA' && <p className="status-msg">Verifying MFA…</p>}
            {status === 'FETCHING' && <p className="status-msg">Fetching documents…</p>}
            {status === 'FAILED' && renderError()}

            <MfaPrompt status={status} onSubmit={handleMfaSubmit} />

            <DocumentViewer
              status={status}
              sessionId={sessionId ?? ''}
              documents={documents}
              mfaSubmitTimestamp={mfaSubmitTimestamp}
              onFirstRender={handleFirstRender}
            />

            {primaryLatencyMs !== null && (
              <p className="latency-info">
                First document rendered in {Math.round(primaryLatencyMs)} ms
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default App
