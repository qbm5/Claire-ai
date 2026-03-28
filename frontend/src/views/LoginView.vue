<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { getOAuthLoginUrl, changeOwnPassword } from '@/services/authService'

const router = useRouter()
const route = useRoute()
const auth = useAuth()
const { show: toast } = useToast()

const isSetup = ref(false)
const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const error = ref('')
const submitting = ref(false)

// Force password change state
const showPasswordChange = ref(false)
const loginPassword = ref('')  // store login password to use as current_password
const newPassword = ref('')
const confirmNewPassword = ref('')
const changingPassword = ref(false)

const oauthProviders = computed(() => auth.authStatus.value?.oauth_providers || [])

onMounted(async () => {
  // Handle OAuth callback query params
  const oauthToken = route.query.oauth_token as string | undefined
  const oauthUser = route.query.oauth_user as string | undefined
  const oauthError = route.query.error as string | undefined

  if (oauthError) {
    error.value = oauthError
    router.replace('/login')
    return
  }

  if (oauthToken && oauthUser) {
    const ok = auth.handleOAuthCallback(oauthToken, oauthUser)
    router.replace('/login')
    if (ok) {
      router.push('/dashboard')
      return
    } else {
      error.value = 'OAuth login failed'
      return
    }
  }

  // If already authenticated and must change password, show the form
  if (auth.isAuthenticated.value && auth.mustChangePassword.value) {
    showPasswordChange.value = true
    return
  }

  if (auth.authStatus.value) {
    isSetup.value = auth.authStatus.value.needs_setup
  }
})

async function handleLogin() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = 'Username and password are required'
    return
  }
  submitting.value = true
  const err = await auth.login(username.value, password.value)
  submitting.value = false
  if (err) {
    error.value = err
  } else if (auth.mustChangePassword.value) {
    // Must change password before proceeding
    loginPassword.value = password.value
    password.value = ''
    showPasswordChange.value = true
  } else {
    router.push('/dashboard')
  }
}

async function handleRegister() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = 'Username and password are required'
    return
  }
  if (password.value.length < 6) {
    error.value = 'Password must be at least 6 characters'
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = 'Passwords do not match'
    return
  }
  submitting.value = true
  const err = await auth.register(username.value, email.value, password.value)
  submitting.value = false
  if (err) {
    error.value = err
  } else {
    toast('Owner account created', 'success')
    router.push('/dashboard')
  }
}

async function handlePasswordChange() {
  error.value = ''
  if (!newPassword.value) {
    error.value = 'New password is required'
    return
  }
  if (newPassword.value.length < 6) {
    error.value = 'Password must be at least 6 characters'
    return
  }
  if (newPassword.value !== confirmNewPassword.value) {
    error.value = 'Passwords do not match'
    return
  }
  changingPassword.value = true
  try {
    await changeOwnPassword(loginPassword.value, newPassword.value)
    auth.mustChangePassword.value = false
    showPasswordChange.value = false
    toast('Password changed', 'success')
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.message || 'Failed to change password'
  }
  changingPassword.value = false
}

async function handleOAuthLogin(provider: string) {
  try {
    const { url } = await getOAuthLoginUrl(provider)
    window.location.href = url
  } catch (e: any) {
    error.value = e.message || `Failed to start ${provider} login`
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-950">
    <div class="w-full max-w-md px-4">
      <!-- Logo -->
      <div class="flex items-center justify-center gap-3 mb-8">
        <svg class="w-10 h-10 shrink-0" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 6.5C13.5 6.5 11.5 7.8 10.5 9.2C9.3 8.8 8.2 9.4 7.7 10.5C7 11.7 7.3 13 8 13.8C7.2 14.6 7 15.8 7.5 17C7.5 17 7 18.2 7.8 19.2C8.5 20 9.3 20.3 10 20.3C10.5 21.3 12 22.5 13.8 23C15 23.3 15.7 23 16 22.8" stroke="#60a5fa" stroke-width="1.6" stroke-linecap="round" fill="#60a5fa" fill-opacity="0.1" />
          <path d="M8.5 12C10.5 11.5 12.5 12.5 15.5 11" stroke="#60a5fa" stroke-width="0.8" stroke-linecap="round" opacity="0.5" />
          <path d="M8 16C10 15.5 12.5 16.8 15.5 15" stroke="#60a5fa" stroke-width="0.8" stroke-linecap="round" opacity="0.45" />
          <path d="M9.5 19.5C11.5 19 13.5 19.8 15.5 19" stroke="#60a5fa" stroke-width="0.8" stroke-linecap="round" opacity="0.4" />
          <line x1="16" y1="6.5" x2="16" y2="22.8" stroke="#a78bfa" stroke-width="1.6" />
          <line x1="16" y1="9" x2="24" y2="9" stroke="#a78bfa" stroke-width="1.2" />
          <line x1="16" y1="13" x2="22" y2="13" stroke="#a78bfa" stroke-width="1.2" />
          <line x1="16" y1="17" x2="25" y2="17" stroke="#a78bfa" stroke-width="1.2" />
          <line x1="16" y1="21" x2="21" y2="21" stroke="#a78bfa" stroke-width="1.2" />
          <line x1="24" y1="9" x2="24" y2="13" stroke="#a78bfa" stroke-width="1.2" />
          <line x1="22" y1="13" x2="22" y2="17" stroke="#818cf8" stroke-width="1" />
          <line x1="21" y1="21" x2="21" y2="17" stroke="#818cf8" stroke-width="1" />
          <circle cx="24" cy="9" r="1.5" fill="#a78bfa" />
          <circle cx="22" cy="13" r="1.3" fill="#818cf8" />
          <circle cx="25" cy="17" r="1.5" fill="#a78bfa" />
          <circle cx="21" cy="21" r="1.3" fill="#818cf8" />
          <circle cx="24" cy="13" r="1" fill="#a78bfa" opacity="0.7" />
          <circle cx="16" cy="14.5" r="2" fill="url(#login-logo-glow)" opacity="0.9" />
          <defs>
            <radialGradient id="login-logo-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#c4b5fd" />
              <stop offset="100%" stop-color="#818cf8" stop-opacity="0" />
            </radialGradient>
          </defs>
        </svg>
        <span class="text-2xl font-bold bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400 bg-clip-text text-transparent">
          Claire
        </span>
      </div>

      <!-- Card -->
      <div class="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-xl">
        <!-- Force password change -->
        <template v-if="showPasswordChange">
          <h2 class="text-xl font-semibold text-center mb-2">Change Password</h2>
          <p class="text-sm text-gray-400 text-center mb-6">You must change your password before continuing.</p>

          <div v-if="error" class="mb-4 px-3 py-2 bg-red-900/30 border border-red-800 rounded-lg text-sm text-red-400">
            {{ error }}
          </div>

          <form @submit.prevent="handlePasswordChange" class="space-y-4">
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
                v-model="confirmNewPassword"
                type="password"
                autocomplete="new-password"
                class="input-base"
              />
            </div>
            <button
              type="submit"
              :disabled="changingPassword"
              class="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {{ changingPassword ? 'Changing...' : 'Change Password' }}
            </button>
          </form>
        </template>

        <!-- Normal login/setup -->
        <template v-else>
          <h2 class="text-xl font-semibold text-center mb-6">
            {{ isSetup ? 'Create Owner Account' : 'Sign In' }}
          </h2>

          <!-- Error -->
          <div v-if="error" class="mb-4 px-3 py-2 bg-red-900/30 border border-red-800 rounded-lg text-sm text-red-400">
            {{ error }}
          </div>

          <!-- Setup form -->
          <form v-if="isSetup" @submit.prevent="handleRegister" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Username</label>
              <input
                v-model="username"
                type="text"
                autocomplete="username"
                class="input-base"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Email <span class="text-gray-600">(optional)</span></label>
              <input
                v-model="email"
                type="email"
                autocomplete="email"
                class="input-base"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Password</label>
              <input
                v-model="password"
                type="password"
                autocomplete="new-password"
                class="input-base"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Confirm Password</label>
              <input
                v-model="confirmPassword"
                type="password"
                autocomplete="new-password"
                class="input-base"
              />
            </div>
            <button
              type="submit"
              :disabled="submitting"
              class="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {{ submitting ? 'Creating...' : 'Create Owner Account' }}
            </button>
          </form>

          <!-- Login form -->
          <form v-else @submit.prevent="handleLogin" class="space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">Username</label>
              <input
                v-model="username"
                type="text"
                autocomplete="username"
                class="input-base"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">Password</label>
              <input
                v-model="password"
                type="password"
                autocomplete="current-password"
                class="input-base"
              />
            </div>
            <button
              type="submit"
              :disabled="submitting"
              class="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {{ submitting ? 'Signing in...' : 'Sign In' }}
            </button>

            <!-- OAuth divider + buttons -->
            <template v-if="oauthProviders.length > 0">
              <div class="flex items-center gap-3 my-2">
                <div class="flex-1 border-t border-gray-700"></div>
                <span class="text-xs text-gray-500">or</span>
                <div class="flex-1 border-t border-gray-700"></div>
              </div>

              <button
                v-if="oauthProviders.includes('google')"
                type="button"
                @click="handleOAuthLogin('google')"
                class="w-full py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
              >
                <svg class="w-4 h-4" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                </svg>
                Sign in with Google
              </button>

              <button
                v-if="oauthProviders.includes('microsoft')"
                type="button"
                @click="handleOAuthLogin('microsoft')"
                class="w-full py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
              >
                <svg class="w-4 h-4" viewBox="0 0 21 21">
                  <rect x="1" y="1" width="9" height="9" fill="#F25022"/>
                  <rect x="11" y="1" width="9" height="9" fill="#7FBA00"/>
                  <rect x="1" y="11" width="9" height="9" fill="#00A4EF"/>
                  <rect x="11" y="11" width="9" height="9" fill="#FFB900"/>
                </svg>
                Sign in with Microsoft
              </button>
            </template>
          </form>
        </template>
      </div>
    </div>
  </div>
</template>
