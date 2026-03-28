/**
 * Global test setup for Vitest.
 * Provides localStorage mock and cleanup between tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
// Map-based localStorage mock
const store = new Map<string, string>()

const localStorageMock: Storage = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => { store.set(key, value) },
  removeItem: (key: string) => { store.delete(key) },
  clear: () => { store.clear() },
  get length() { return store.size },
  key: (index: number) => [...store.keys()][index] ?? null,
}

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

// Mock document.documentElement.classList for theme tests
if (typeof document !== 'undefined') {
  // happy-dom provides this, but ensure it exists
  if (!document.documentElement) {
    Object.defineProperty(document, 'documentElement', {
      value: { classList: { add: () => {}, remove: () => {}, contains: () => false } },
    })
  }
}

afterEach(() => {
  store.clear()
})
