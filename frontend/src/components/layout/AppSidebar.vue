<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'

const route = useRoute()
const auth = useAuth()

const allLinks = [
  { path: '/dashboard', label: 'Dashboard', resource: '', icon: 'M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z', prefixes: ['/dashboard'] },
  { path: '/tools', label: 'Tools', resource: 'tools', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066zM15 12a3 3 0 11-6 0 3 3 0 016 0z', prefixes: ['/tools', '/tool/', '/tool-runner/'] },
  { path: '/pipelines', label: 'Pipelines', resource: 'pipelines', icon: 'M13 10V3L4 14h7v7l9-11h-7z', prefixes: ['/pipelines', '/pipeline/', '/pipeline-runner/', '/pipeline-run/'] },
  { path: '/triggers', label: 'Triggers', resource: 'triggers', icon: 'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9', prefixes: ['/triggers', '/trigger/'] },
  { path: '/tasks', label: 'Tasks', resource: '', icon: 'M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z', prefixes: ['/tasks', '/task/'], beta: true },
]

const links = computed(() =>
  allLinks.filter(link => !link.resource || auth.canUse(link.resource))
)

function isActive(prefixes: string[]) {
  return prefixes.some(p => route.path.startsWith(p))
}

function handleLogout() {
  auth.logout()
  window.location.href = '/login'
}
</script>

<template>
  <header class="h-12 bg-black border-b border-gray-800 flex items-center px-4 gap-1 shrink-0">
    <!-- Logo + Brand -->
    <router-link to="/" class="flex items-center gap-2.5 mr-6 group">
      <!-- SVG Logo: half brain / half circuit -->
      <svg class="w-7 h-7 shrink-0" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <!-- Left half: organic brain -->
        <path d="M16 6.5C13.5 6.5 11.5 7.8 10.5 9.2C9.3 8.8 8.2 9.4 7.7 10.5C7 11.7 7.3 13 8 13.8C7.2 14.6 7 15.8 7.5 17C7.5 17 7 18.2 7.8 19.2C8.5 20 9.3 20.3 10 20.3C10.5 21.3 12 22.5 13.8 23C15 23.3 15.7 23 16 22.8" stroke="#60a5fa" stroke-width="1.6" stroke-linecap="round" fill="#60a5fa" fill-opacity="0.1" />
        <!-- Brain folds -->
        <path d="M8.5 12C10.5 11.5 12.5 12.5 15.5 11" stroke="#60a5fa" stroke-width="0.8" stroke-linecap="round" opacity="0.5" />
        <path d="M8 16C10 15.5 12.5 16.8 15.5 15" stroke="#60a5fa" stroke-width="0.8" stroke-linecap="round" opacity="0.45" />
        <path d="M9.5 19.5C11.5 19 13.5 19.8 15.5 19" stroke="#60a5fa" stroke-width="0.8" stroke-linecap="round" opacity="0.4" />
        <!-- Right half: circuit/digital -->
        <line x1="16" y1="6.5" x2="16" y2="22.8" stroke="#a78bfa" stroke-width="1.6" />
        <line x1="16" y1="9" x2="24" y2="9" stroke="#a78bfa" stroke-width="1.2" />
        <line x1="16" y1="13" x2="22" y2="13" stroke="#a78bfa" stroke-width="1.2" />
        <line x1="16" y1="17" x2="25" y2="17" stroke="#a78bfa" stroke-width="1.2" />
        <line x1="16" y1="21" x2="21" y2="21" stroke="#a78bfa" stroke-width="1.2" />
        <line x1="24" y1="9" x2="24" y2="13" stroke="#a78bfa" stroke-width="1.2" />
        <line x1="22" y1="13" x2="22" y2="17" stroke="#818cf8" stroke-width="1" />
        <line x1="21" y1="21" x2="21" y2="17" stroke="#818cf8" stroke-width="1" />
        <!-- Circuit nodes -->
        <circle cx="24" cy="9" r="1.5" fill="#a78bfa" />
        <circle cx="22" cy="13" r="1.3" fill="#818cf8" />
        <circle cx="25" cy="17" r="1.5" fill="#a78bfa" />
        <circle cx="21" cy="21" r="1.3" fill="#818cf8" />
        <circle cx="24" cy="13" r="1" fill="#a78bfa" opacity="0.7" />
        <!-- Glow dot on the split -->
        <circle cx="16" cy="14.5" r="2" fill="url(#logo-glow)" opacity="0.9" />
        <defs>
          <radialGradient id="logo-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#c4b5fd" />
            <stop offset="100%" stop-color="#818cf8" stop-opacity="0" />
          </radialGradient>
        </defs>
      </svg>
      <span class="text-lg font-bold bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400 bg-clip-text text-transparent group-hover:from-blue-300 group-hover:to-purple-300 transition-all">
        Claire
      </span>
    </router-link>

    <!-- Nav links -->
    <nav class="flex items-center gap-0.5">
      <router-link
        v-for="link in links"
        :key="link.path"
        :to="link.path"
        class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
        :class="isActive(link.prefixes)
          ? 'bg-blue-500/25 text-blue-300'
          : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path :d="link.icon" />
        </svg>
        <span>{{ link.label }}</span>
        <span v-if="link.beta" class="px-1.5 py-0.5 text-[9px] font-semibold rounded bg-amber-900/40 text-amber-400 border border-amber-800/60 leading-none">BETA</span>
      </router-link>
    </nav>

    <!-- Spacer -->
    <div class="flex-1"></div>

    <!-- Users link (admin/owner only) -->
    <router-link
      v-if="auth.isAdmin.value && auth.authRequired.value"
      to="/users"
      class="p-2 rounded-lg transition-colors mr-1"
      :class="isActive(['/users'])
        ? 'bg-blue-500/25 text-blue-300'
        : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'"
      title="Users & Permissions"
    >
      <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    </router-link>

    <!-- Docs -->
    <router-link
      to="/docs"
      class="p-2 rounded-lg transition-colors"
      :class="isActive(['/docs'])
        ? 'bg-blue-500/25 text-blue-300'
        : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'"
      title="Documentation"
    >
      <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
      </svg>
    </router-link>

    <!-- Settings (pushed right) -->
    <router-link
      v-if="auth.isAdmin.value"
      to="/settings"
      class="p-2 rounded-lg transition-colors"
      :class="isActive(['/settings'])
        ? 'bg-blue-500/25 text-blue-300'
        : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'"
    >
      <svg class="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066zM15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    </router-link>

    <!-- User info + Logout (only when auth enabled) -->
    <div v-if="auth.authRequired.value && auth.isAuthenticated.value" class="flex items-center gap-2 ml-3 pl-3 border-l border-gray-800">
      <router-link
        to="/profile"
        class="p-1.5 rounded-lg transition-colors"
        :class="isActive(['/profile'])
          ? 'bg-blue-500/25 text-blue-300'
          : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'"
        title="Profile"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
        </svg>
      </router-link>
      <span class="text-xs text-gray-400">{{ auth.user.value?.username }}</span>
      <span class="px-1.5 py-0.5 text-[10px] font-medium rounded border"
        :class="{
          'bg-purple-900/40 text-purple-400 border-purple-800': auth.user.value?.role === 'owner',
          'bg-blue-900/40 text-blue-400 border-blue-800': auth.user.value?.role === 'admin',
          'bg-gray-800 text-gray-400 border-gray-700': auth.user.value?.role === 'user',
        }"
      >
        {{ auth.user.value?.role }}
      </span>
      <button
        @click="handleLogout"
        class="p-1.5 rounded-lg text-gray-500 hover:bg-gray-800 hover:text-gray-300 transition-colors"
        title="Logout"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
        </svg>
      </button>
    </div>
  </header>
</template>
