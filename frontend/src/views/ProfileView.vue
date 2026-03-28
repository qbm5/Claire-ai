<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { updateOwnProfile, changeOwnPassword } from '@/services/authService'

const auth = useAuth()
const { show: toast } = useToast()

const displayName = ref('')
const savingProfile = ref(false)

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changingPassword = ref(false)
const passwordError = ref('')

const resourceLabels: Record<string, string> = {
  tools: 'Tools',
  pipelines: 'Pipelines',
  chatbots: 'Chatbots',
  triggers: 'Triggers',
}

const isOAuthUser = computed(() => {
  const u = auth.user.value as any
  return !!u?.oauth_provider
})

onMounted(async () => {
  await auth.refreshMe()
  displayName.value = (auth.user.value as any)?.display_name || auth.user.value?.username || ''
})

async function saveProfile() {
  if (!displayName.value.trim()) return
  savingProfile.value = true
  try {
    await updateOwnProfile(displayName.value.trim())
    await auth.refreshMe()
    toast('Profile updated', 'success')
  } catch (e: any) {
    toast(e.message || 'Failed to update profile', 'error')
  }
  savingProfile.value = false
}

async function handleChangePassword() {
  passwordError.value = ''
  if (!currentPassword.value || !newPassword.value) {
    passwordError.value = 'Both fields are required'
    return
  }
  if (newPassword.value.length < 6) {
    passwordError.value = 'New password must be at least 6 characters'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    passwordError.value = 'Passwords do not match'
    return
  }
  changingPassword.value = true
  try {
    await changeOwnPassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    toast('Password changed', 'success')
  } catch (e: any) {
    passwordError.value = e.message || 'Failed to change password'
  }
  changingPassword.value = false
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
  <div class="flex flex-col h-full max-w-2xl p-6">
    <h1 class="text-2xl font-bold mb-6">Profile</h1>

    <!-- User Info -->
    <section class="mb-6">
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
        <div class="flex items-center gap-3">
          <div class="w-12 h-12 rounded-full bg-gray-800 flex items-center justify-center text-lg font-bold text-gray-400">
            {{ (auth.user.value?.username || '?')[0].toUpperCase() }}
          </div>
          <div>
            <div class="font-semibold text-gray-100">{{ auth.user.value?.username }}</div>
            <div class="flex items-center gap-2 mt-0.5">
              <span class="text-sm text-gray-400">{{ auth.user.value?.email || 'No email' }}</span>
              <span class="px-2 py-0.5 text-xs font-medium rounded border" :class="roleBadgeClass(auth.user.value?.role || '')">
                {{ auth.user.value?.role }}
              </span>
            </div>
          </div>
        </div>

        <div>
          <label class="block text-sm text-gray-400 mb-1">Display Name</label>
          <div class="flex gap-2">
            <input
              v-model="displayName"
              type="text"
              class="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-blue-500"
            />
            <button
              @click="saveProfile"
              :disabled="savingProfile"
              class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {{ savingProfile ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Change Password (not for OAuth users) -->
    <section v-if="!isOAuthUser" class="mb-6">
      <h2 class="text-lg font-semibold mb-3">Change Password</h2>
      <div class="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
        <div v-if="passwordError" class="px-3 py-2 bg-red-900/30 border border-red-800 rounded-lg text-sm text-red-400">
          {{ passwordError }}
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">Current Password</label>
          <input
            v-model="currentPassword"
            type="password"
            autocomplete="current-password"
            class="input-base"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">New Password</label>
          <input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            class="input-base"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">Confirm New Password</label>
          <input
            v-model="confirmPassword"
            type="password"
            autocomplete="new-password"
            class="input-base"
          />
        </div>
        <button
          @click="handleChangePassword"
          :disabled="changingPassword"
          class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
        >
          {{ changingPassword ? 'Changing...' : 'Change Password' }}
        </button>
      </div>
    </section>

    <!-- Permissions (non-admin only) -->
    <section v-if="!auth.isAdmin.value">
      <h2 class="text-lg font-semibold mb-3">Your Permissions</h2>

      <!-- Type-level permissions -->
      <div class="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden mb-4">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-800 text-gray-400 text-left">
              <th class="px-4 py-3 font-medium">Resource</th>
              <th class="px-4 py-3 font-medium text-center">Create</th>
              <th class="px-4 py-3 font-medium text-center">Edit</th>
              <th class="px-4 py-3 font-medium text-center">Delete</th>
              <th class="px-4 py-3 font-medium text-center">Access</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rt in ['tools', 'pipelines', 'chatbots', 'triggers']" :key="rt" class="border-b border-gray-800/50 last:border-0">
              <td class="px-4 py-3 font-medium">{{ resourceLabels[rt] }}</td>
              <td class="px-4 py-3 text-center">
                <span :class="auth.permissions.value[rt]?.can_create ? 'text-green-400' : 'text-gray-600'">
                  {{ auth.permissions.value[rt]?.can_create ? 'Yes' : 'No' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span :class="auth.permissions.value[rt]?.can_edit ? 'text-green-400' : 'text-gray-600'">
                  {{ auth.permissions.value[rt]?.can_edit ? 'Yes' : 'No' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span :class="auth.permissions.value[rt]?.can_delete ? 'text-green-400' : 'text-gray-600'">
                  {{ auth.permissions.value[rt]?.can_delete ? 'Yes' : 'No' }}
                </span>
              </td>
              <td class="px-4 py-3 text-center text-gray-400">
                {{ (auth.resourceAccess.value[rt] || []).length }} items
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="text-xs text-gray-500">Permissions are managed by your administrator.</p>
    </section>

    <section v-else>
      <div class="text-sm text-gray-500">As an {{ auth.user.value?.role }}, you have full access to all resources.</div>
    </section>
  </div>
</template>
