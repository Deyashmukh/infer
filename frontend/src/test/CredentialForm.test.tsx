import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CredentialForm } from '../components/CredentialForm'

describe('CredentialForm', () => {
  it('renders username and masked password inputs', () => {
    render(<CredentialForm onSubmit={vi.fn()} />)
    expect(screen.getByRole('textbox', { name: /username/i })).toBeInTheDocument()
    const pwd = screen.getByLabelText(/password/i)
    expect(pwd).toHaveAttribute('type', 'password')
  })

  it('calls onSubmit with username and password', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<CredentialForm onSubmit={onSubmit} />)
    await userEvent.type(screen.getByRole('textbox', { name: /username/i }), 'alice')
    await userEvent.type(screen.getByLabelText(/password/i), 'secret')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(onSubmit).toHaveBeenCalledWith('alice', 'secret')
  })
})
