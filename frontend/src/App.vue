<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { connectSSE, disconnectSSE } from '@/services/eventBus'
import { useAuth } from '@/composables/useAuth'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ToastContainer from '@/components/shared/ToastContainer.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuth()

onMounted(async () => {
  await auth.init()

  // If auth required and needs setup, redirect to login
  if (auth.authRequired.value && auth.authStatus.value?.needs_setup) {
    router.push('/login')
    return
  }

  // If auth required and not authenticated, redirect to login
  if (auth.authRequired.value && !auth.isAuthenticated.value) {
    router.push('/login')
    return
  }

  // If must change password, redirect to login
  if (auth.mustChangePassword.value) {
    router.push('/login')
    return
  }

  // Connect SSE if authenticated or open mode
  if (auth.isAuthenticated.value) {
    connectSSE()
  }
})

// Reconnect SSE when auth state changes (e.g., after login)
watch(() => auth.isAuthenticated.value, (authed) => {
  if (authed) {
    disconnectSSE()
    connectSSE()
  } else {
    disconnectSSE()
  }
})
</script>

<template>
  <div class="flex flex-col h-screen bg-gray-950 text-gray-100">
    <AppSidebar v-if="route.name !== 'Login'" />
    <main class="flex-1 overflow-auto">
      <router-view />
    </main>
    <!-- Legal links -->
    <div v-if="route.name !== 'Login'" class="fixed bottom-3 right-3 flex items-center gap-3 text-[11px] text-gray-600 z-10">
      <router-link to="/legal" class="hover:text-gray-400 transition-colors">Terms of Service</router-link>
      <span class="text-gray-800">|</span>
      <router-link to="/legal?tab=license" class="hover:text-gray-400 transition-colors">License</router-link>
    </div>
    <ToastContainer />
  </div>
</template>
