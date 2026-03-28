import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the authService module
vi.mock('@/services/authService', () => ({
  getAuthStatus: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  getMe: vi.fn(),
}))

describe('useAuth', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('canCreate returns true for admin', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    // Set up admin user
    auth.user.value = { id: '1', username: 'admin', email: '', role: 'admin' }
    expect(auth.canCreate('tools')).toBe(true)
  })

  it('canCreate returns true for owner', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'owner', email: '', role: 'owner' }
    expect(auth.canCreate('tools')).toBe(true)
  })

  it('canCreate checks permissions for regular user', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'user', email: '', role: 'user' }
    auth.permissions.value = {
      tools: { can_create: true, can_edit: false, can_delete: false },
    }
    expect(auth.canCreate('tools')).toBe(true)
    expect(auth.canEdit('tools')).toBe(false)
    expect(auth.canDelete('tools')).toBe(false)
  })

  it('canEdit returns false when no permissions', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'user', email: '', role: 'user' }
    auth.permissions.value = {}
    expect(auth.canEdit('tools')).toBe(false)
  })

  it('canAccessResource checks resource access for user', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'user', email: '', role: 'user' }
    auth.resourceAccess.value = { tools: ['t1', 't2'] }
    expect(auth.canAccessResource('tools', 't1')).toBe(true)
    expect(auth.canAccessResource('tools', 't3')).toBe(false)
  })

  it('canAccessResource returns true for admin', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'admin', email: '', role: 'admin' }
    expect(auth.canAccessResource('tools', 'any-id')).toBe(true)
  })

  it('canUse returns true for admin', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'admin', email: '', role: 'admin' }
    expect(auth.canUse('tools')).toBe(true)
  })

  it('canUse checks resource access and create permission', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'user', email: '', role: 'user' }
    auth.resourceAccess.value = { tools: ['t1'] }
    auth.permissions.value = {}
    expect(auth.canUse('tools')).toBe(true)  // has accessible resources
  })

  it('isAuthenticated computed', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    expect(auth.isAuthenticated.value).toBe(false)
    auth.user.value = { id: '1', username: 'test', email: '', role: 'user' }
    expect(auth.isAuthenticated.value).toBe(true)
  })

  it('isAdmin computed', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'user', email: '', role: 'user' }
    expect(auth.isAdmin.value).toBe(false)
    auth.user.value = { id: '1', username: 'admin', email: '', role: 'admin' }
    expect(auth.isAdmin.value).toBe(true)
  })

  it('logout clears state', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    auth.user.value = { id: '1', username: 'test', email: '', role: 'user' }
    auth.token.value = 'some-token'
    localStorage.setItem('auth_token', 'some-token')
    auth.logout()
    expect(auth.user.value).toBeNull()
    expect(auth.token.value).toBe('')
    expect(localStorage.getItem('auth_token')).toBeNull()
  })

  it('handleOAuthCallback sets user on valid data', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    const result = auth.handleOAuthCallback('oauth-token', JSON.stringify({ id: '1', username: 'oauth-user' }))
    expect(result).toBe(true)
    expect(auth.token.value).toBe('oauth-token')
    expect(auth.user.value?.id).toBe('1')
  })

  it('handleOAuthCallback returns false on invalid JSON', async () => {
    const { useAuth } = await import('./useAuth')
    const auth = useAuth()
    const result = auth.handleOAuthCallback('token', 'not-json')
    expect(result).toBe(false)
  })
})
