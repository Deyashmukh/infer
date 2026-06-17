import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CarrierSelect } from '../components/CarrierSelect'

describe('CarrierSelect', () => {
  it('renders Liberty Mutual as clickable', () => {
    const onSelect = vi.fn()
    render(<CarrierSelect onSelect={onSelect} />)
    const btn = screen.getByRole('button', { name: /liberty mutual/i })
    expect(btn).toBeEnabled()
  })

  it('renders Geico as disabled', () => {
    render(<CarrierSelect onSelect={vi.fn()} />)
    const btn = screen.getByRole('button', { name: /geico/i })
    expect(btn).toBeDisabled()
  })

  it('calls onSelect with liberty_mutual when clicked', async () => {
    const onSelect = vi.fn()
    render(<CarrierSelect onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /liberty mutual/i }))
    expect(onSelect).toHaveBeenCalledWith('liberty_mutual')
  })
})
