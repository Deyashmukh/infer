import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createSession } from '../api'

type FetchMock = ReturnType<typeof vi.fn>

function fetchCalls(): [string, RequestInit][] {
  return (globalThis.fetch as unknown as FetchMock).mock.calls as [string, RequestInit][]
}

describe('createSession', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ session_id: 'sid', status: 'STARTING' }),
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the selected carrier in the request body', async () => {
    await createSession('geico', 'user1', 'pass1')
    const [, init] = fetchCalls()[0]
    const body = JSON.parse(init.body as string)
    expect(body).toEqual({ carrier: 'geico', username: 'user1', password: 'pass1' })
  })

  it('threads liberty_mutual when chosen', async () => {
    await createSession('liberty_mutual', 'u', 'p')
    const [url, init] = fetchCalls()[0]
    const body = JSON.parse(init.body as string)
    expect(body.carrier).toBe('liberty_mutual')
    expect(String(url)).toMatch(/\/sessions$/)
    expect(init.method).toBe('POST')
  })
})
