import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// react-pdf needs a canvas/worker that jsdom lacks; stub it (App imports it via pdfWorker).
vi.mock('react-pdf', () => ({
  Document: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Page: () => <div />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: '' } },
}))
// Keep the polling loop inert — this test only covers the carrier→createSession wiring.
vi.mock('../usePolling', () => ({ usePolling: () => null }))
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    createSession: vi.fn().mockResolvedValue({ session_id: 'sid', status: 'STARTING' }),
    submitMfa: vi.fn().mockResolvedValue({ session_id: 'sid', status: 'VERIFYING_MFA' }),
  }
})

import { App } from '../App'
import * as api from '../api'

describe('App carrier threading', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('passes the carrier chosen in CarrierSelect to createSession', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /liberty mutual/i }))
    await userEvent.type(screen.getByLabelText('Username'), 'user1')
    await userEvent.type(screen.getByLabelText('Password'), 'pass1')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(api.createSession).toHaveBeenCalledWith('liberty_mutual', 'user1', 'pass1')
  })
})
