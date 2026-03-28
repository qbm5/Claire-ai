/**
 * Shared test utilities for Vue component testing.
 */

import { createRouter, createMemoryHistory } from 'vue-router'
import type { Component } from 'vue'

/**
 * Create a test router with minimal routes.
 */
export function createTestRouter(routes?: any[]) {
  return createRouter({
    history: createMemoryHistory(),
    routes: routes || [
      { path: '/', component: { template: '<div>Home</div>' } },
      { path: '/login', component: { template: '<div>Login</div>' } },
      { path: '/tools', component: { template: '<div>Tools</div>' } },
      { path: '/pipelines', component: { template: '<div>Pipelines</div>' } },
    ],
  })
}

/**
 * Helper to mount a component with common providers (router, etc.).
 */
export function createMountOptions(options?: { routes?: any[] }) {
  const router = createTestRouter(options?.routes)
  return {
    global: {
      plugins: [router],
    },
    router,
  }
}
