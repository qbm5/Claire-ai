import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/composables/useAuth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'Home', redirect: '/dashboard' },
    { path: '/login', name: 'Login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    { path: '/dashboard', name: 'Dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/chatbots', redirect: '/dashboard' },
    { path: '/chatbot/:id', redirect: '/dashboard' },
    { path: '/chat/:id', redirect: '/dashboard' },
    { path: '/tools', name: 'Tools', component: () => import('@/views/ToolsView.vue') },
    { path: '/tool/:id', name: 'ToolEdit', component: () => import('@/views/ToolEditView.vue'), props: true },
    { path: '/tool-runner/:id', name: 'ToolRunner', component: () => import('@/views/ToolRunnerView.vue'), props: true },
    { path: '/pipelines', name: 'Pipelines', component: () => import('@/views/PipelinesView.vue') },
    { path: '/pipeline/:id', name: 'PipelineEdit', component: () => import('@/views/PipelineEditView.vue'), props: true },
    { path: '/pipeline-runner/:id', name: 'PipelineRunner', component: () => import('@/views/PipelineRunnerView.vue'), props: true },
    { path: '/pipeline-run/:id', name: 'PipelineRun', component: () => import('@/views/PipelineRunView.vue'), props: true },
    { path: '/triggers', name: 'Triggers', component: () => import('@/views/TriggersView.vue') },
    { path: '/trigger/:id', name: 'TriggerEdit', component: () => import('@/views/TriggerEditView.vue'), props: true },
    { path: '/tasks', name: 'Tasks', component: () => import('@/views/TasksView.vue') },
    { path: '/task/:id', name: 'TaskEdit', component: () => import('@/views/TaskView.vue'), props: true },
    { path: '/task-run/:id', name: 'TaskRun', component: () => import('@/views/TaskRunView.vue'), props: true },
    { path: '/profile', name: 'Profile', component: () => import('@/views/ProfileView.vue') },
    { path: '/settings', name: 'Settings', component: () => import('@/views/SettingsView.vue'), meta: { requiresAdmin: true } },
    { path: '/docs', name: 'Docs', component: () => import('@/views/DocsView.vue') },
    { path: '/legal', name: 'Legal', component: () => import('@/views/LegalView.vue') },
    { path: '/users', name: 'Users', component: () => import('@/views/UsersView.vue'), meta: { requiresAdmin: true } },
    { path: '/:catchAll(.*)', redirect: '/' },
  ],
})

router.beforeEach((to, _from, next) => {
  // Public routes always pass
  if (to.meta.public) {
    next()
    return
  }

  const auth = useAuth()

  // If auth not required (open mode), proceed
  if (!auth.authRequired.value) {
    next()
    return
  }

  // Auth required but not authenticated
  if (!auth.isAuthenticated.value) {
    next('/login')
    return
  }

  // Force password change — redirect to login
  if (auth.mustChangePassword.value && to.path !== '/login') {
    next('/login')
    return
  }

  // Admin-only routes
  if (to.meta.requiresAdmin && !auth.isAdmin.value) {
    next('/dashboard')
    return
  }

  next()
})

export default router
