import { describe, it, expect, vi, beforeEach } from 'vitest'

describe('useTheme', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('defaults to dark theme', async () => {
    const { useTheme } = await import('./useTheme')
    const { theme } = useTheme()
    expect(theme.value).toBe('dark')
  })

  it('reads stored theme', async () => {
    localStorage.setItem('theme', 'light')
    const { useTheme } = await import('./useTheme')
    const { theme } = useTheme()
    expect(theme.value).toBe('light')
  })

  it('toggle switches theme', async () => {
    const { useTheme } = await import('./useTheme')
    const { theme, toggle } = useTheme()
    expect(theme.value).toBe('dark')
    toggle()
    expect(theme.value).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
    toggle()
    expect(theme.value).toBe('dark')
    expect(localStorage.getItem('theme')).toBe('dark')
  })

  it('setTheme sets specific theme', async () => {
    const { useTheme } = await import('./useTheme')
    const { theme, setTheme } = useTheme()
    setTheme('light')
    expect(theme.value).toBe('light')
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('applies light class to document', async () => {
    const { useTheme } = await import('./useTheme')
    const { setTheme } = useTheme()
    setTheme('light')
    expect(document.documentElement.classList.contains('light')).toBe(true)
    setTheme('dark')
    expect(document.documentElement.classList.contains('light')).toBe(false)
  })
})
