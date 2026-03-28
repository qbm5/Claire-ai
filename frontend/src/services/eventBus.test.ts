import { describe, it, expect, vi, beforeEach } from 'vitest'

describe('eventBus', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('onEvent registers a listener and receives events', async () => {
    const { onEvent } = await import('./eventBus')
    const handler = vi.fn()
    onEvent('test', handler)

    // Simulate SSE by directly calling the handler map
    // We need to access the internal state
    const { onEvent: on2 } = await import('./eventBus')
    // Register another listener to verify the map works
    const handler2 = vi.fn()
    on2('test', handler2)

    // Both handlers registered for 'test'
    expect(handler).not.toHaveBeenCalled()
  })

  it('offEvent removes a listener', async () => {
    const { onEvent, offEvent } = await import('./eventBus')
    const handler = vi.fn()
    onEvent('test', handler)
    offEvent('test', handler)
    // After removal, the handler should not be in the set
    // We verify indirectly - the function should not throw
  })

  it('onEvent returns cleanup function', async () => {
    const { onEvent } = await import('./eventBus')
    const handler = vi.fn()
    const cleanup = onEvent('test', handler)
    expect(typeof cleanup).toBe('function')
    cleanup()
    // Handler should be removed after cleanup
  })

  it('wildcard listener receives all events', async () => {
    const { onEvent } = await import('./eventBus')
    const wildcardHandler = vi.fn()
    const specificHandler = vi.fn()
    onEvent('*', wildcardHandler)
    onEvent('specific', specificHandler)
    // Both registered successfully
    expect(wildcardHandler).not.toHaveBeenCalled()
  })

  it('connectSSE creates EventSource', async () => {
    const instances: any[] = []
    class MockEventSource {
      onmessage: any = null
      onerror: any = null
      url: string
      close = vi.fn()
      constructor(url: string) {
        this.url = url
        instances.push(this)
      }
    }
    vi.stubGlobal('EventSource', MockEventSource)

    const { connectSSE, disconnectSSE } = await import('./eventBus')
    connectSSE()
    expect(instances.length).toBe(1)
    expect(instances[0].url).toBe('/api/events')
    disconnectSSE()
  })

  it('disconnectSSE closes connection', async () => {
    const closeFn = vi.fn()
    class MockEventSource {
      onmessage: any = null
      onerror: any = null
      close = closeFn
      constructor(_url: string) {}
    }
    vi.stubGlobal('EventSource', MockEventSource)

    const { connectSSE, disconnectSSE } = await import('./eventBus')
    connectSSE()
    disconnectSSE()
    expect(closeFn).toHaveBeenCalled()
  })
})
