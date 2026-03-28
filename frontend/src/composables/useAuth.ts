import { ref, computed } from 'vue'
import type { User } from '@/models'
import { getAuthStatus, login as apiLogin, register as apiRegister, getMe } from '@/services/authService'
import type { AuthStatus } from '@/services/authService'

interface ResourcePermissions {
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
}

const user = ref<User | null>(null)
const token = ref<string>(localStorage.getItem('auth_token') || '')
const authStatus = ref<AuthStatus | null>(null)
const permissions = ref<Record<string, ResourcePermissions>>({})
const resourceAccess = ref<Record<string, string[]>>({})
const mustChangePassword = ref(false)
const loading = ref(false)

const isAuthenticated = computed(() => !!user.value)
const isAdmin = computed(() => user.value?.role === 'admin' || user.value?.role === 'owner')
const isOwner = computed(() => user.value?.role === 'owner')
const authRequired = computed(() => authStatus.value?.auth_enabled === true)

export function useAuth() {
  async function init() {
    loading.value = true
    try {
      authStatus.value = await getAuthStatus()

      if (!authStatus.value.auth_enabled) {
        // Open mode — synthetic owner
        user.value = { id: 'default', username: 'default', email: '', role: 'owner' }
        permissions.value = {}
        resourceAccess.value = {}
        mustChangePassword.value = false
        loading.value = false
        return
      }

      // Auth enabled — check for existing token
      if (token.value) {
        try {
          const me = await getMe()
          if (me && me.id) {
            user.value = me
            permissions.value = me.permissions || {}
            resourceAccess.value = me.resource_access || {}
            mustChangePassword.value = !!me.must_change_password
          } else {
            clearAuth()
          }
        } catch {
          clearAuth()
        }
      }
    } catch {
      // API unreachable — assume open mode
      user.value = { id: 'default', username: 'default', email: '', role: 'owner' }
    }
    loading.value = false
  }

  async function refreshMe() {
    if (!token.value) return
    try {
      const me = await getMe()
      if (me && me.id) {
        user.value = me
        permissions.value = me.permissions || {}
        resourceAccess.value = me.resource_access || {}
        mustChangePassword.value = !!me.must_change_password
      }
    } catch { /* ignore */ }
  }

  async function login(username: string, password: string): Promise<string | null> {
    try {
      const res = await apiLogin(username, password)
      if (res.token) {
        token.value = res.token
        localStorage.setItem('auth_token', res.token)
        user.value = res.user
        mustChangePassword.value = !!res.must_change_password
        return null
      }
      return (res as any).detail || 'Login failed'
    } catch (e: any) {
      return e.message || 'Login failed'
    }
  }

  async function register(username: string, email: string, password: string): Promise<string | null> {
    try {
      const res = await apiRegister(username, email, password)
      if (res.token) {
        token.value = res.token
        localStorage.setItem('auth_token', res.token)
        user.value = res.user
        mustChangePassword.value = false
        return null
      }
      return (res as any).detail || 'Registration failed'
    } catch (e: any) {
      return e.message || 'Registration failed'
    }
  }

  function handleOAuthCallback(oauthToken: string, userJson: string): boolean {
    try {
      const parsed = JSON.parse(userJson)
      if (oauthToken && parsed && parsed.id) {
        token.value = oauthToken
        localStorage.setItem('auth_token', oauthToken)
        user.value = parsed
        mustChangePassword.value = false
        return true
      }
    } catch { /* ignore parse errors */ }
    return false
  }

  function logout() {
    clearAuth()
  }

  function clearAuth() {
    token.value = ''
    user.value = null
    permissions.value = {}
    resourceAccess.value = {}
    mustChangePassword.value = false
    localStorage.removeItem('auth_token')
  }

  function canUse(resource: string): boolean {
    // Admin/owner always have full access
    if (isAdmin.value) return true
    // Show section if user has any accessible resources for that type OR has can_create
    const access = resourceAccess.value[resource]
    if (access && access.length > 0) return true
    const perm = permissions.value[resource]
    if (perm && perm.can_create) return true
    return false
  }

  function canAccessResource(type: string, id: string): boolean {
    if (isAdmin.value) return true
    const access = resourceAccess.value[type]
    if (!access) return false
    return access.includes(id)
  }

  function canCreate(type: string): boolean {
    if (isAdmin.value) return true
    const perm = permissions.value[type]
    if (!perm) return false
    return perm.can_create
  }

  function canEdit(type: string): boolean {
    if (isAdmin.value) return true
    const perm = permissions.value[type]
    if (!perm) return false
    return perm.can_edit
  }

  function canDelete(type: string): boolean {
    if (isAdmin.value) return true
    const perm = permissions.value[type]
    if (!perm) return false
    return perm.can_delete
  }

  return {
    user,
    token,
    authStatus,
    permissions,
    resourceAccess,
    mustChangePassword,
    loading,
    isAuthenticated,
    isAdmin,
    isOwner,
    authRequired,
    init,
    refreshMe,
    login,
    register,
    logout,
    handleOAuthCallback,
    canUse,
    canAccessResource,
    canCreate,
    canEdit,
    canDelete,
  }
}
