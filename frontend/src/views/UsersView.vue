<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import {
  getUsers, createUser, changeRole, toggleActive, deleteUser,
  getUserPermissions, saveUserPermissions,
  getUserAccess, saveUserAccess,
  adminResetPassword,
} from '@/services/authService'
import { get } from '@/services/api'
import type { AuthUser } from '@/services/authService'

const auth = useAuth()
const { show: toast } = useToast()

// Users
const users = ref<AuthUser[]>([])
const loadingUsers = ref(true)
const showAddForm = ref(false)
const newUsername = ref('')
const newEmail = ref('')
const newPassword = ref('')
const newRole = ref('user')
const addError = ref('')
const deleteConfirm = ref('')

// Per-user management
const managingUserId = ref<string | null>(null)
const managingLoading = ref(false)
const managingSaving = ref(false)

const RESOURCE_TYPES = ['tools', 'pipelines', 'chatbots', 'triggers'] as const
const resourceLabels: Record<string, string> = {
  tools: 'Tools',
  pipelines: 'Pipelines',
  chatbots: 'Chatbots',
  triggers: 'Triggers',
}

// Per-user permissions state
const userPerms = reactive<Record<string, { can_create: boolean; can_edit: boolean; can_delete: boolean }>>({})

// Per-user resource access state
const userAccess = reactive<Record<string, string[]>>({})

// All available resources (for checkboxes)
const allResources = reactive<Record<string, { id: string; name: string }[]>>({})

// Password reset
const resetPassword = ref('')
const forceChange = ref(false)

onMounted(async () => {
  await loadUsers()
})

async function loadUsers() {
  loadingUsers.value = true
  users.value = await getUsers()
  loadingUsers.value = false
}

async function handleAddUser() {
  addError.value = ''
  if (!newUsername.value || !newPassword.value) {
    addError.value = 'Username and password are required'
    return
  }
  if (newPassword.value.length < 6) {
    addError.value = 'Password must be at least 6 characters'
    return
  }
  try {
    const result = await createUser(newUsername.value, newEmail.value, newPassword.value, newRole.value)
    if ((result as any).detail) {
      addError.value = (result as any).detail
      return
    }
    toast('User created', 'success')
    newUsername.value = ''
    newEmail.value = ''
    newPassword.value = ''
    newRole.value = 'user'
    showAddForm.value = false
    await loadUsers()
  } catch (e: any) {
    addError.value = e.message || 'Failed to create user'
  }
}

async function handleChangeRole(userId: string, role: string) {
  await changeRole(userId, role)
  toast('Role updated', 'success')
  await loadUsers()
}

async function handleToggleActive(userId: string, active: boolean) {
  await toggleActive(userId, active)
  toast(active ? 'User activated' : 'User deactivated', 'success')
  await loadUsers()
}

async function handleDelete(userId: string) {
  if (deleteConfirm.value !== userId) {
    deleteConfirm.value = userId
    return
  }
  await deleteUser(userId)
  deleteConfirm.value = ''
  if (managingUserId.value === userId) managingUserId.value = null
  toast('User deleted', 'success')
  await loadUsers()
}

async function toggleManage(userId: string) {
  if (managingUserId.value === userId) {
    managingUserId.value = null
    return
  }
  managingUserId.value = userId
  managingLoading.value = true

  try {
    // Load all resources, user permissions, and user access in parallel
    const [permsRes, accessRes, toolsRes, pipelinesRes, chatbotsRes, triggersRes] = await Promise.all([
      getUserPermissions(userId),
      getUserAccess(userId),
      get<any[]>('/tools'),
      get<any[]>('/pipelines'),
      get<any[]>('/chatbots'),
      get<any[]>('/triggers'),
    ])

    // Populate permissions
    for (const rt of RESOURCE_TYPES) {
      const perm = permsRes.find((p: any) => p.resource_type === rt)
      userPerms[rt] = {
        can_create: perm ? !!perm.can_create : false,
        can_edit: perm ? !!perm.can_edit : false,
        can_delete: perm ? !!perm.can_delete : false,
      }
    }

    // Populate access
    for (const rt of RESOURCE_TYPES) {
      userAccess[rt] = accessRes[rt] || []
    }

    // Populate all resources
    allResources.tools = (toolsRes || []).map((t: any) => ({ id: t.id, name: t.name }))
    allResources.pipelines = (pipelinesRes || []).filter((p: any) => p.id !== '__tool_runs__').map((p: any) => ({ id: p.id, name: p.name }))
    allResources.chatbots = (chatbotsRes || []).map((c: any) => ({ id: c.id, name: c.name }))
    allResources.triggers = (triggersRes || []).map((t: any) => ({ id: t.id, name: t.name }))

    // Reset password fields
    resetPassword.value = ''
    forceChange.value = false
  } catch (e: any) {
    toast(e.message || 'Failed to load user data', 'error')
    managingUserId.value = null
  }

  managingLoading.value = false
}

function toggleResourceAccess(rt: string, resourceId: string) {
  const idx = userAccess[rt].indexOf(resourceId)
  if (idx >= 0) {
    userAccess[rt].splice(idx, 1)
  } else {
    userAccess[rt].push(resourceId)
  }
}

function selectAllResources(rt: string) {
  userAccess[rt] = allResources[rt].map(r => r.id)
}

function deselectAllResources(rt: string) {
  userAccess[rt] = []
}

async function handleSaveUserSettings() {
  if (!managingUserId.value) return
  managingSaving.value = true

  try {
    // Save permissions
    const permsPayload = RESOURCE_TYPES.map(rt => ({
      resource_type: rt,
      ...userPerms[rt],
    }))
    await saveUserPermissions(managingUserId.value, permsPayload)

    // Save access
    const accessPayload: Record<string, string[]> = {}
    for (const rt of RESOURCE_TYPES) {
      accessPayload[rt] = userAccess[rt]
    }
    await saveUserAccess(managingUserId.value, accessPayload)

    // Reset password if provided
    if (resetPassword.value) {
      if (resetPassword.value.length < 6) {
        toast('Password must be at least 6 characters', 'error')
        managingSaving.value = false
        return
      }
      await adminResetPassword(managingUserId.value, resetPassword.value, forceChange.value)
      resetPassword.value = ''
    } else if (forceChange.value) {
      // Just set force_change without new password
      await adminResetPassword(managingUserId.value, '', forceChange.value)
    }

    toast('User settings saved', 'success')
  } catch (e: any) {
    toast(e.message || 'Failed to save', 'error')
  }

  managingSaving.value = false
}

function roleBadgeClass(role: string) {
  switch (role) {
    case 'owner': return 'bg-purple-900/40 text-purple-400 border-purple-800'
    case 'admin': return 'bg-blue-900/40 text-blue-400 border-blue-800'
    default: return 'bg-gray-800 text-gray-400 border-gray-700'
  }
}
</script>

<template>
  <div class="flex flex-col h-full max-w-5xl p-6">
    <h1 class="text-2xl font-bold mb-6">Users & Permissions</h1>

    <!-- Users Section -->
    <section class="mb-8">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold">Users</h2>
        <button
          @click="showAddForm = !showAddForm"
          class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors"
          :class="showAddForm ? 'bg-gray-700 text-gray-300' : 'bg-blue-600 hover:bg-blue-700 text-white'"
        >
          {{ showAddForm ? 'Cancel' : 'Add User' }}
        </button>
      </div>

      <!-- Add user form -->
      <div v-if="showAddForm" class="mb-4 p-4 bg-gray-900 border border-gray-800 rounded-lg space-y-3">
        <div v-if="addError" class="px-3 py-2 bg-red-900/30 border border-red-800 rounded-lg text-sm text-red-400">
          {{ addError }}
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-sm text-gray-400 mb-1">Username</label>
            <input v-model="newUsername" type="text" class="input-base" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">Email <span class="text-gray-600">(optional)</span></label>
            <input v-model="newEmail" type="email" class="input-base" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">Password</label>
            <input v-model="newPassword" type="password" class="input-base" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">Role</label>
            <select v-model="newRole" class="input-base">
              <option value="user">User</option>
              <option v-if="auth.isOwner.value" value="admin">Admin</option>
            </select>
          </div>
        </div>
        <button @click="handleAddUser" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors">
          Create User
        </button>
      </div>

      <!-- Users table -->
      <div v-if="loadingUsers" class="text-gray-400 text-sm">Loading...</div>
      <div v-else class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-800 text-gray-400 text-left">
              <th class="px-4 py-3 font-medium">Username</th>
              <th class="px-4 py-3 font-medium">Display Name</th>
              <th class="px-4 py-3 font-medium">Email</th>
              <th class="px-4 py-3 font-medium">Role</th>
              <th class="px-4 py-3 font-medium">Active</th>
              <th class="px-4 py-3 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="u in users" :key="u.id">
              <tr class="border-b border-gray-800/50">
                <td class="px-4 py-3">{{ u.username }}</td>
                <td class="px-4 py-3 text-gray-400">{{ u.display_name || '-' }}</td>
                <td class="px-4 py-3 text-gray-400">{{ u.email || '-' }}</td>
                <td class="px-4 py-3">
                  <span v-if="u.role === 'owner' || !auth.isOwner.value" class="px-2 py-0.5 text-xs font-medium rounded border" :class="roleBadgeClass(u.role)">
                    {{ u.role }}
                  </span>
                  <select
                    v-else
                    :value="u.role"
                    @change="handleChangeRole(u.id, ($event.target as HTMLSelectElement).value)"
                    class="px-2 py-1 bg-gray-800 border border-gray-700 rounded text-xs focus:outline-none focus:border-blue-500"
                  >
                    <option value="admin">admin</option>
                    <option value="user">user</option>
                  </select>
                </td>
                <td class="px-4 py-3">
                  <button
                    v-if="u.role !== 'owner'"
                    @click="handleToggleActive(u.id, !u.is_active)"
                    class="w-8 h-5 rounded-full transition-colors relative"
                    :class="u.is_active ? 'bg-green-600' : 'bg-gray-600'"
                  >
                    <span class="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform" :class="u.is_active ? 'left-3.5' : 'left-0.5'" />
                  </button>
                  <span v-else class="text-xs text-gray-500">-</span>
                </td>
                <td class="px-4 py-3 text-right space-x-2">
                  <button
                    v-if="u.role === 'user'"
                    @click="toggleManage(u.id)"
                    class="px-2 py-1 text-xs font-medium rounded transition-colors"
                    :class="managingUserId === u.id ? 'bg-blue-600 text-white' : 'text-blue-400 hover:bg-blue-900/30'"
                  >
                    {{ managingUserId === u.id ? 'Close' : 'Manage' }}
                  </button>
                  <button
                    v-if="u.role !== 'owner' && auth.isOwner.value"
                    @click="handleDelete(u.id)"
                    class="px-2 py-1 text-xs font-medium rounded transition-colors"
                    :class="deleteConfirm === u.id ? 'bg-red-600 hover:bg-red-700 text-white' : 'text-red-400 hover:bg-red-900/30'"
                  >
                    {{ deleteConfirm === u.id ? 'Confirm?' : 'Delete' }}
                  </button>
                </td>
              </tr>

              <!-- Inline management panel -->
              <tr v-if="managingUserId === u.id">
                <td colspan="6" class="px-0 py-0">
                  <div class="border-t border-gray-800 bg-gray-950/50 p-5 space-y-6">
                    <div v-if="managingLoading" class="text-gray-400 text-sm py-4 text-center">Loading user settings...</div>
                    <template v-else>
                      <!-- General Permissions -->
                      <div>
                        <h3 class="text-sm font-semibold text-gray-300 mb-3">General Permissions</h3>
                        <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
                          <table class="w-full text-sm">
                            <thead>
                              <tr class="border-b border-gray-800 text-gray-400 text-left">
                                <th class="px-4 py-2 font-medium">Resource</th>
                                <th class="px-4 py-2 font-medium text-center">Create</th>
                                <th class="px-4 py-2 font-medium text-center">Edit</th>
                                <th class="px-4 py-2 font-medium text-center">Delete</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr v-for="rt in RESOURCE_TYPES" :key="rt" class="border-b border-gray-800/50 last:border-0">
                                <td class="px-4 py-2 font-medium">{{ resourceLabels[rt] }}</td>
                                <td class="px-4 py-2 text-center">
                                  <input type="checkbox" v-model="userPerms[rt].can_create" class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer" />
                                </td>
                                <td class="px-4 py-2 text-center">
                                  <input type="checkbox" v-model="userPerms[rt].can_edit" class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer" />
                                </td>
                                <td class="px-4 py-2 text-center">
                                  <input type="checkbox" v-model="userPerms[rt].can_delete" class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer" />
                                </td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </div>

                      <!-- Resource Access -->
                      <div>
                        <h3 class="text-sm font-semibold text-gray-300 mb-3">Resource Access</h3>
                        <p class="text-xs text-gray-500 mb-3">Select which resources this user can see and use/run.</p>

                        <div class="space-y-4">
                          <div v-for="rt in RESOURCE_TYPES" :key="rt" class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                            <div class="flex items-center justify-between mb-2">
                              <span class="text-sm font-medium text-gray-300">{{ resourceLabels[rt] }}</span>
                              <div class="flex gap-2">
                                <button @click="selectAllResources(rt)" class="text-xs text-blue-400 hover:text-blue-300">All</button>
                                <button @click="deselectAllResources(rt)" class="text-xs text-gray-400 hover:text-gray-300">None</button>
                              </div>
                            </div>
                            <div v-if="!allResources[rt] || allResources[rt].length === 0" class="text-xs text-gray-500 italic">
                              No {{ resourceLabels[rt].toLowerCase() }} available
                            </div>
                            <div v-else class="flex flex-wrap gap-2">
                              <label
                                v-for="res in allResources[rt]"
                                :key="res.id"
                                class="flex items-center gap-1.5 px-2 py-1 rounded border cursor-pointer transition-colors text-xs"
                                :class="userAccess[rt]?.includes(res.id) ? 'bg-blue-900/30 border-blue-700 text-blue-300' : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600'"
                              >
                                <input
                                  type="checkbox"
                                  :checked="userAccess[rt]?.includes(res.id)"
                                  @change="toggleResourceAccess(rt, res.id)"
                                  class="w-3 h-3 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-0 cursor-pointer"
                                />
                                {{ res.name }}
                              </label>
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- Password Reset (hide for OAuth users) -->
                      <div v-if="!users.find(u => u.id === managingUserId)?.oauth_provider">
                        <h3 class="text-sm font-semibold text-gray-300 mb-3">Password</h3>
                        <div class="bg-gray-900 border border-gray-800 rounded-lg p-4">
                          <div class="flex items-end gap-3">
                            <div class="flex-1">
                              <label class="block text-xs text-gray-400 mb-1">New Password</label>
                              <input
                                v-model="resetPassword"
                                type="password"
                                placeholder="Leave empty to keep current"
                                class="input-base"
                              />
                            </div>
                            <label class="flex items-center gap-2 pb-2 cursor-pointer">
                              <input
                                type="checkbox"
                                v-model="forceChange"
                                class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500 focus:ring-offset-0 cursor-pointer"
                              />
                              <span class="text-xs text-gray-400 whitespace-nowrap">Force change on next login</span>
                            </label>
                          </div>
                        </div>
                      </div>

                      <!-- Save button -->
                      <div class="flex justify-end">
                        <button
                          @click="handleSaveUserSettings"
                          :disabled="managingSaving"
                          class="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                        >
                          {{ managingSaving ? 'Saving...' : 'Save Settings' }}
                        </button>
                      </div>
                    </template>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
