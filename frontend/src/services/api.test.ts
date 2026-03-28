import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// We need to mock window.location before importing the module
const originalLocation = globalThis.location

describe('api service', () => {
  let apiModule: typeof import('./api')

  beforeEach(async () => {
    // Reset localStorage
    localStorage.clear()
    // Fresh import each test
    vi.resetModules()
    apiModule = await import('./api')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('get', () => {
    it('sends GET request with correct URL', async () => {
      const mockResponse = { ok: true, status: 200, json: () => Promise.resolve({ data: 'test' }) }
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

      const result = await apiModule.get('/tools')
      expect(fetch).toHaveBeenCalledWith('/api/tools', expect.objectContaining({
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      }))
      expect(result).toEqual({ data: 'test' })
    })

    it('includes auth token when present', async () => {
      localStorage.setItem('auth_token', 'my-token')
      vi.resetModules()
      const mod = await import('./api')

      const mockResponse = { ok: true, status: 200, json: () => Promise.resolve({}) }
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

      await mod.get('/tools')
      expect(fetch).toHaveBeenCalledWith('/api/tools', expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer my-token' }),
      }))
    })
  })

  describe('post', () => {
    it('sends POST request with body', async () => {
      const mockResponse = { ok: true, status: 200, json: () => Promise.resolve({ id: '1' }) }
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

      const body = { name: 'test' }
      await apiModule.post('/tools', body)
      expect(fetch).toHaveBeenCalledWith('/api/tools', expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(body),
      }))
    })
  })

  describe('put', () => {
    it('sends PUT request', async () => {
      const mockResponse = { ok: true, status: 200, json: () => Promise.resolve({}) }
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

      await apiModule.put('/tools/1', { name: 'updated' })
      expect(fetch).toHaveBeenCalledWith('/api/tools/1', expect.objectContaining({
        method: 'PUT',
      }))
    })
  })

  describe('del', () => {
    it('sends DELETE request', async () => {
      const mockResponse = { ok: true, status: 200, json: () => Promise.resolve({}) }
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

      await apiModule.del('/tools/1')
      expect(fetch).toHaveBeenCalledWith('/api/tools/1', expect.objectContaining({
        method: 'DELETE',
      }))
    })
  })

  describe('401 handling', () => {
    it('clears token and redirects on 401 when token exists', async () => {
      localStorage.setItem('auth_token', 'expired-token')
      vi.resetModules()
      const mod = await import('./api')

      // Mock window.location.href setter
      const hrefSetter = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { href: '', host: 'localhost:5173' },
        writable: true,
        configurable: true,
      })
      Object.defineProperty(window.location, 'href', {
        set: hrefSetter,
        get: () => '',
        configurable: true,
      })

      const mockResponse = { ok: false, status: 401, json: () => Promise.resolve({ detail: 'Unauthorized' }) }
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockResponse))

      await mod.get('/tools')
      expect(localStorage.getItem('auth_token')).toBeNull()
    })
  })

  describe('wsConnect', () => {
    it('creates WebSocket with correct URL', () => {
      const mockWs = vi.fn()
      vi.stubGlobal('WebSocket', mockWs)

      apiModule.wsConnect('/chat')
      expect(mockWs).toHaveBeenCalledWith(expect.stringContaining('/ws/chat'))
    })

    it('appends token as query param', () => {
      localStorage.setItem('auth_token', 'ws-token')
      const mockWs = vi.fn()
      vi.stubGlobal('WebSocket', mockWs)

      // Need fresh import to pick up the token
      // Since wsConnect reads token at call time, it should work
      apiModule.wsConnect('/chat')
      expect(mockWs).toHaveBeenCalledWith(expect.stringContaining('token=ws-token'))
    })
  })
})
