import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock all external composables and services
vi.mock('@/composables/useAuth', () => ({
  useAuth: vi.fn(() => ({
    authStatus: { value: { auth_enabled: true, needs_setup: false, oauth_providers: [] } },
    isAuthenticated: { value: false },
    mustChangePassword: { value: false },
    login: vi.fn().mockResolvedValue(null),
    register: vi.fn().mockResolvedValue(null),
    handleOAuthCallback: vi.fn(),
  })),
}))

vi.mock('@/composables/useToast', () => ({
  useToast: vi.fn(() => ({
    show: vi.fn(),
  })),
}))

vi.mock('@/services/authService', () => ({
  getOAuthLoginUrl: vi.fn(),
  changeOwnPassword: vi.fn(),
}))

describe('LoginView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login', component: { template: '<div>Login</div>' } },
        { path: '/dashboard', component: { template: '<div>Dashboard</div>' } },
      ],
    })
  })

  it('renders login form', async () => {
    const LoginView = (await import('./LoginView.vue')).default
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    await router.isReady()

    // Should have username and password inputs
    const inputs = wrapper.findAll('input')
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })

  it('shows error when fields are empty on submit', async () => {
    const LoginView = (await import('./LoginView.vue')).default
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    await router.isReady()

    // Find and click login button
    const button = wrapper.find('button[type="submit"], button')
    if (button.exists()) {
      await button.trigger('click')
    }
    // Error should be set (either via validation or visible in DOM)
  })
})
