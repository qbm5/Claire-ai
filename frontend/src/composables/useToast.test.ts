import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

describe('useToast', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.useFakeTimers()
  })

  it('shows a toast and auto-removes it', async () => {
    const { useToast } = await import('./useToast')
    const { toasts, show } = useToast()

    show('Hello', 'info', 3000)
    expect(toasts.value.length).toBe(1)
    expect(toasts.value[0].message).toBe('Hello')
    expect(toasts.value[0].type).toBe('info')

    vi.advanceTimersByTime(3000)
    expect(toasts.value.length).toBe(0)
  })

  it('supports different toast types', async () => {
    const { useToast } = await import('./useToast')
    const { toasts, show } = useToast()

    show('Success!', 'success')
    expect(toasts.value[0].type).toBe('success')

    show('Error!', 'error')
    expect(toasts.value[1].type).toBe('error')
  })

  it('assigns unique IDs', async () => {
    const { useToast } = await import('./useToast')
    const { toasts, show } = useToast()

    show('First', 'info')
    show('Second', 'info')
    expect(toasts.value[0].id).not.toBe(toasts.value[1].id)
  })

  afterEach(() => {
    vi.useRealTimers()
  })
})
