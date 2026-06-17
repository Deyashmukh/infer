const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// --- types ---

export type Carrier = 'liberty_mutual' | 'geico'

export type SessionStatus =
  | 'STARTING'
  | 'AWAITING_MFA'
  | 'VERIFYING_MFA'
  | 'FETCHING'
  | 'READY'
  | 'FAILED'

export interface Document {
  doc_id: string
  name: string
}

export interface SessionError {
  type: string
  message: string
}

export interface StatusResponse {
  session_id: string
  status: SessionStatus
  mfa_required: boolean
  documents?: Document[]
  error?: SessionError
  latency_ms?: number
}

export interface CreateSessionResponse {
  session_id: string
  status: SessionStatus
}

// --- functions ---

export async function createSession(
  carrier: Carrier,
  username: string,
  password: string,
): Promise<CreateSessionResponse> {
  const res = await fetch(`${BASE_URL}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ carrier, username, password }),
  })
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`)
  return res.json() as Promise<CreateSessionResponse>
}

export async function getStatus(id: string): Promise<StatusResponse> {
  const res = await fetch(`${BASE_URL}/sessions/${id}`)
  if (!res.ok) throw new Error(`getStatus failed: ${res.status}`)
  return res.json() as Promise<StatusResponse>
}

export async function submitMfa(
  id: string,
  code: string,
): Promise<CreateSessionResponse> {
  const res = await fetch(`${BASE_URL}/sessions/${id}/mfa`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })
  if (!res.ok) throw new Error(`submitMfa failed: ${res.status}`)
  return res.json() as Promise<CreateSessionResponse>
}

export function documentUrl(id: string, docId: string): string {
  return `${BASE_URL}/sessions/${id}/documents/${docId}`
}
