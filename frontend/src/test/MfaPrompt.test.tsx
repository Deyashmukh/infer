import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MfaPrompt } from '../components/MfaPrompt'
import type { SessionStatus } from '../api'

const NON_MFA_STATUSES: SessionStatus[] = [
  'STARTING',
  'VERIFYING_MFA',
  'FETCHING',
  'READY',
  'FAILED',
]

describe('MfaPrompt', () => {
  it('renders when status is AWAITING_MFA', () => {
    render(<MfaPrompt status="AWAITING_MFA" onSubmit={vi.fn()} />)
    expect(screen.getByRole('button', { name: /submit code/i })).toBeInTheDocument()
  })

  it.each(NON_MFA_STATUSES)(
    'returns null for status %s',
    (status) => {
      const { container } = render(<MfaPrompt status={status} onSubmit={vi.fn()} />)
      expect(container.firstChild).toBeNull()
    },
  )

  it('calls onSubmit with the entered code', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<MfaPrompt status="AWAITING_MFA" onSubmit={onSubmit} />)
    await userEvent.type(screen.getByLabelText(/mfa code/i), '123456')
    await userEvent.click(screen.getByRole('button', { name: /submit code/i }))
    expect(onSubmit).toHaveBeenCalledWith('123456')
  })
})
