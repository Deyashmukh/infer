import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePolling } from '../usePolling'
import * as api from '../api'
import type { StatusResponse } from '../api'

function makeStatus(status: StatusResponse['status']): StatusResponse {
  return { session_id: 'sid', status, mfa_required: false }
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('stops polling when status is READY', async () => {
    const getStatusSpy = vi
      .spyOn(api, 'getStatus')
      .mockResolvedValueOnce(makeStatus('STARTING'))
      .mockResolvedValueOnce(makeStatus('READY'))

    const { result } = renderHook(() => usePolling('sid'))

    // First poll fires immediately
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    // Should have polled twice (STARTING then READY) and stopped
    expect(getStatusSpy).toHaveBeenCalledTimes(2)
    expect(result.current?.status).toBe('READY')

    // Advance time — no further polls should fire
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(getStatusSpy).toHaveBeenCalledTimes(2)
  })

  it('stops polling when status is FAILED', async () => {
    const getStatusSpy = vi
      .spyOn(api, 'getStatus')
      .mockResolvedValueOnce(makeStatus('FETCHING'))
      .mockResolvedValueOnce(makeStatus('FAILED'))

    const { result } = renderHook(() => usePolling('sid'))

    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(getStatusSpy).toHaveBeenCalledTimes(2)
    expect(result.current?.status).toBe('FAILED')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(getStatusSpy).toHaveBeenCalledTimes(2)
  })

  it('keeps polling for non-terminal statuses', async () => {
    const getStatusSpy = vi
      .spyOn(api, 'getStatus')
      .mockResolvedValue(makeStatus('FETCHING'))

    renderHook(() => usePolling('sid'))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(700 * 3 + 100)
      // flush promises after each timer tick
      await Promise.resolve()
    })

    // Should have fired at least 3 times
    expect(getStatusSpy.mock.calls.length).toBeGreaterThanOrEqual(3)
  })

  it('returns null when sessionId is null', () => {
    const getStatusSpy = vi.spyOn(api, 'getStatus')
    const { result } = renderHook(() => usePolling(null))
    expect(result.current).toBeNull()
    expect(getStatusSpy).not.toHaveBeenCalled()
  })
})
