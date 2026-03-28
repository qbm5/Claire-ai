import { get, post, put, del } from './api'

export interface AuthStatus {
  auth_enabled: boolean
  has_owner: boolean
  needs_setup: boolean
  oauth_providers: string[]
}

export interface AuthUser {
  id: string
  username: string
  email: string
  role: string
  is_active?: boolean
  display_name?: string
  must_change_password?: boolean
  oauth_provider?: string
  created_at?: string
}

export interface LoginResponse {
  token: string
  user: AuthUser
  must_change_password?: boolean
}

export interface RolePermission {
  id: string
  resource_type: string
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
  can_use: boolean
}

export interface UserPermission {
  id: string
  user_id: string
  resource_type: string
  can_create: boolean
  can_edit: boolean
  can_delete: boolean
}

// Public endpoints
export function getAuthStatus(): Promise<AuthStatus> {
  return get<AuthStatus>('/auth/status')
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return post<LoginResponse>('/auth/login', { username, password })
}

export function register(username: string, email: string, password: string): Promise<LoginResponse> {
  return post<LoginResponse>('/auth/register', { username, email, password })
}

export function getMe(): Promise<AuthUser & { permissions: Record<string, any>; resource_access: Record<string, string[]> }> {
  return get('/auth/me')
}

// Admin endpoints
export function getUsers(): Promise<AuthUser[]> {
  return get<AuthUser[]>('/auth/users')
}

export function createUser(username: string, email: string, password: string, role: string, displayName?: string, mustChangePassword?: boolean): Promise<AuthUser> {
  return post<AuthUser>('/auth/users', {
    username, email, password, role,
    display_name: displayName || username,
    must_change_password: mustChangePassword || false,
  })
}

export function changeRole(userId: string, role: string): Promise<any> {
  return put<any>(`/auth/users/${userId}/role`, { role })
}

export function toggleActive(userId: string, is_active: boolean): Promise<any> {
  return put<any>(`/auth/users/${userId}/active`, { is_active })
}

export function deleteUser(userId: string): Promise<any> {
  return del<any>(`/auth/users/${userId}`)
}

// Per-user permissions (admin)
export function getUserPermissions(userId: string): Promise<UserPermission[]> {
  return get<UserPermission[]>(`/auth/users/${userId}/permissions`)
}

export function saveUserPermissions(userId: string, permissions: { resource_type: string; can_create: boolean; can_edit: boolean; can_delete: boolean }[]): Promise<any> {
  return post<any>(`/auth/users/${userId}/permissions`, permissions)
}

export function getUserAccess(userId: string): Promise<Record<string, string[]>> {
  return get<Record<string, string[]>>(`/auth/users/${userId}/access`)
}

export function saveUserAccess(userId: string, access: Record<string, string[]>): Promise<any> {
  return post<any>(`/auth/users/${userId}/access`, access)
}

// Self-service
export function changeOwnPassword(currentPassword: string, newPassword: string): Promise<any> {
  return put<any>('/auth/me/password', { current_password: currentPassword, new_password: newPassword })
}

export function updateOwnProfile(displayName: string): Promise<any> {
  return put<any>('/auth/me/profile', { display_name: displayName })
}

// Admin password management
export function adminResetPassword(userId: string, newPassword: string, forceChange: boolean): Promise<any> {
  return put<any>(`/auth/users/${userId}/password`, { new_password: newPassword, force_change: forceChange })
}

// Legacy global permissions (backward compat)
export function getPermissions(): Promise<RolePermission[]> {
  return get<RolePermission[]>('/auth/permissions')
}

export function savePermissions(permissions: RolePermission[]): Promise<any> {
  return post<any>('/auth/permissions', permissions)
}

// OAuth
export function getOAuthLoginUrl(provider: string): Promise<{ url: string }> {
  return get<{ url: string }>(`/auth/oauth/${provider}/login`)
}
