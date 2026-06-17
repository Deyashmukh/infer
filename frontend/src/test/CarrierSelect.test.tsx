import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CarrierSelect } from '../components/CarrierSelect'

describe('CarrierSelect', () => {
  it('offers Liberty Mutual as a selectable option', () => {
    render(<CarrierSelect onSelect={vi.fn()} />)
    expect(screen.getByRole('option', { name: /liberty mutual/i })).toBeEnabled()
  })

  it('shows Geico as a disabled option', () => {
    render(<CarrierSelect onSelect={vi.fn()} />)
    expect(screen.getByRole('option', { name: /geico/i })).toBeDisabled()
  })

  it('disables Continue until a carrier is chosen', () => {
    render(<CarrierSelect onSelect={vi.fn()} />)
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('calls onSelect with the chosen carrier when Continue is clicked', async () => {
    const onSelect = vi.fn()
    render(<CarrierSelect onSelect={onSelect} />)
    await userEvent.selectOptions(screen.getByRole('combobox'), 'liberty_mutual')
    await userEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(onSelect).toHaveBeenCalledWith('liberty_mutual')
  })
})
